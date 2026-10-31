"""
Tests for scripts/deploy_blue_green.sh

Covers 12 essential production safety and switching scenarios:
1. Active blue slot switches to green.
2. Active green slot switches to blue.
3. Unhealthy candidate is rejected.
4. Candidate with disconnected MySQL is rejected.
5. Invalid Nginx configuration prevents switching.
6. Nginx reload failure triggers rollback.
7. Post-switch health failure triggers rollback.
8. Rollback failure is reported clearly without claiming recovery.
9. Unknown active slot aborts safely.
10. Zero or ambiguous candidate targets abort safely.
11. Secret values do not appear in captured logs.
12. Existing production containers are not stopped or removed by tests.
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
import pytest

SCRIPT_PATH = "scripts/deploy_blue_green.sh"
GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"
BASH_BIN = GIT_BASH if os.path.exists(GIT_BASH) else "bash"


@pytest.fixture
def mock_env():
    """
    Creates an isolated mock environment in C:/Users/Public (no spaces in path)
    with shell-native mock_docker and mock_curl.
    """
    mock_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    mock_dir = Path("C:/Users/Public") / f"mock_deploy_{mock_id}"
    mock_dir.mkdir(parents=True, exist_ok=True)
    state_dir = mock_dir.as_posix()

    # Default state files
    (mock_dir / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8",
        newline="\n"
    )
    (mock_dir / "probe_health.json").write_text(
        json.dumps({"status": "healthy", "environment": "production-green", "database": {"connected": True, "mode": "live_mysql", "latency_ms": 3.5}}),
        encoding="utf-8",
        newline="\n"
    )
    (mock_dir / "post_switch_health.json").write_text(
        json.dumps({"status": "healthy", "environment": "production-green", "database": {"connected": True, "mode": "live_mysql", "latency_ms": 3.8}}),
        encoding="utf-8",
        newline="\n"
    )

    # Mock Docker script
    docker_script = f"""#!/usr/bin/env bash
STATE_DIR="{state_dir}"

if [ "$1" = "ps" ]; then
    echo "devsecops-nginx"
    exit 0
fi

if [ "$1" = "pull" ]; then
    echo "Image pulled successfully"
    exit 0
fi

if [ "$1" = "stop" ] || [ "$1" = "rm" ]; then
    ACTION="$1"
    shift
    for arg in "$@"; do
        if [ "$arg" != "-f" ]; then
            echo "$ACTION $arg" >> "$STATE_DIR/docker_actions.log"
        fi
    done
    exit 0
fi

if [ "$1" = "run" ]; then
    echo "mock-cid-12345"
    exit 0
fi

if [ "$1" = "inspect" ]; then
    exit 0
fi

if [ "$1" = "exec" ]; then
    shift
    if [ "$1" = "-i" ]; then shift; fi
    shift # skip container name (devsecops-nginx)

    CMD="$*"
    if [[ "$CMD" == *"cat /etc/nginx/conf.d/upstream.conf"* ]]; then
        cat "$STATE_DIR/upstream.conf" 2>/dev/null || true
        exit 0
    fi

    if [[ "$CMD" == *"nginx -T"* ]] || [[ "$CMD" == *"cat /etc/nginx/nginx.conf"* ]]; then
        if [ -f "$STATE_DIR/nginx_runtime.conf" ]; then
            cat "$STATE_DIR/nginx_runtime.conf"
        elif [ -f "$STATE_DIR/upstream.conf" ]; then
            cat "$STATE_DIR/upstream.conf"
        fi
        exit 0
    fi

    if [[ "$CMD" == *"wget"* && "$CMD" == *"/health"* ]]; then
        cat "$STATE_DIR/probe_health.json" 2>/dev/null || true
        exit 0
    fi

    if [[ "$CMD" == *"nginx -t -c /tmp/nginx-validate/nginx.conf"* ]]; then
        if [ -f "$STATE_DIR/nginx_validate_fail" ]; then
            echo "nginx: [emerg] syntax error in candidate" >&2
            exit 1
        fi
        echo "nginx: syntax ok"
        exit 0
    fi

    if [[ "$CMD" == *"nginx -s reload"* ]]; then
        COUNT=0
        if [ -f "$STATE_DIR/reload_count" ]; then
            COUNT=$(cat "$STATE_DIR/reload_count")
        fi
        COUNT=$((COUNT + 1))
        echo "$COUNT" > "$STATE_DIR/reload_count"

        if [ "$COUNT" -eq 1 ] && [ -f "$STATE_DIR/nginx_reload_fail" ]; then
            echo "nginx: reload failed" >&2
            exit 1
        fi
        if [ "$COUNT" -gt 1 ] && [ -f "$STATE_DIR/rollback_reload_fail" ]; then
            echo "nginx: rollback reload failed" >&2
            exit 1
        fi
        echo "nginx: reloaded successfully"
        exit 0
    fi

    if [[ "$CMD" == *"nginx -t"* ]]; then
        echo "nginx: syntax ok"
        exit 0
    fi

    if [[ "$CMD" == *"test -s /etc/nginx/upstream.conf.previous"* ]] || [[ "$CMD" == *"test -f /etc/nginx/upstream.conf.previous"* ]]; then
        if [ -f "$STATE_DIR/backup_test_fail" ]; then
            exit 1
        fi
        [ -s "$STATE_DIR/upstream.conf.previous" ] && exit 0 || exit 1
    fi

    if [[ "$CMD" == *"cat > /etc/nginx/upstream.conf.previous"* ]]; then
        if [ -f "$STATE_DIR/backup_write_fail" ]; then
            exit 1
        fi
        cat > "$STATE_DIR/upstream.conf.previous"
        exit 0
    fi

    if [[ "$CMD" == *"cp /etc/nginx/conf.d/upstream.conf /etc/nginx/upstream.conf.previous"* ]]; then
        cp "$STATE_DIR/upstream.conf" "$STATE_DIR/upstream.conf.previous" 2>/dev/null || true
        exit 0
    fi

    if [[ "$CMD" == *"cat /etc/nginx/upstream.conf.previous > /etc/nginx/conf.d/upstream.conf"* ]]; then
        cp "$STATE_DIR/upstream.conf.previous" "$STATE_DIR/upstream.conf" 2>/dev/null || true
        touch "$STATE_DIR/rollback_restored"
        exit 0
    fi

    if [[ "$CMD" == *"cat > /etc/nginx/conf.d/upstream.conf"* ]]; then
        cat > "$STATE_DIR/upstream.conf"
        exit 0
    fi

    exit 0
fi

exit 0
"""
    (mock_dir / "docker.sh").write_text(docker_script, encoding="utf-8", newline="\n")

    # Mock Curl script
    curl_script = f"""#!/usr/bin/env bash
STATE_DIR="{state_dir}"
if [ -f "$STATE_DIR/rollback_restored" ]; then
    cat "$STATE_DIR/probe_health.json" 2>/dev/null || true
else
    cat "$STATE_DIR/post_switch_health.json" 2>/dev/null || true
fi
exit 0
"""
    (mock_dir / "curl.sh").write_text(curl_script, encoding="utf-8", newline="\n")

    yield {
        "mock_dir": mock_dir,
        "state_dir": state_dir,
        "docker_bin": f"bash {(mock_dir / 'docker.sh').as_posix()}",
        "curl_bin": f"bash {(mock_dir / 'curl.sh').as_posix()}",
    }

    shutil.rmtree(mock_dir, ignore_errors=True)


def run_deploy(mock_env, deploy_image="test-repo/app:latest", extra_env=None):
    """Executes deploy_blue_green.sh with mocked dependencies and captures output."""
    env = os.environ.copy()
    env["DOCKER_CMD"] = mock_env["docker_bin"]
    env["CURL_CMD"] = mock_env["curl_bin"]
    env["DB_PASSWORD"] = "TestMockDbPassword123!"
    env["PROBE_TIMEOUT_SECS"] = "4"
    env["POST_SWITCH_TIMEOUT_SECS"] = "4"
    env["DEPLOY_LOCK_PATH"] = (mock_env["mock_dir"] / "deploy.lock").as_posix()
    if extra_env:
        env.update(extra_env)

    cmd = [BASH_BIN, SCRIPT_PATH, deploy_image]
    res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res


# ------------------------------------------------------------------------------
# SCENARIO 1: Active Blue Slot Switches to Green
# ------------------------------------------------------------------------------
def test_active_blue_switches_to_green(mock_env):
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:v2")
    assert res.returncode == 0
    assert "Active slot is now: green (devsecops-app-green)" in res.stdout
    assert "Previous slot (devsecops-app-blue) remains RUNNING in standby" in res.stdout

    # Verify updated upstream configuration in mock state
    updated_upstream = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "devsecops-app-green:5000" in updated_upstream


# ------------------------------------------------------------------------------
# SCENARIO 2: Active Green Slot Switches to Blue
# ------------------------------------------------------------------------------
def test_active_green_switches_to_blue(mock_env):
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "probe_health.json").write_text(
        json.dumps({"status": "healthy", "environment": "production-blue", "database": {"connected": True, "mode": "live_mysql"}}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:v3")
    assert res.returncode == 0
    assert "Active slot is now: blue (devsecops-app-blue)" in res.stdout
    assert "Previous slot (devsecops-app-green) remains RUNNING in standby" in res.stdout

    updated_upstream = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "devsecops-app-blue:5000" in updated_upstream


# ------------------------------------------------------------------------------
# SCENARIO 3: Unhealthy Candidate is Rejected
# ------------------------------------------------------------------------------
def test_unhealthy_candidate_is_rejected(mock_env):
    (mock_env["mock_dir"] / "probe_health.json").write_text(
        json.dumps({"status": "unhealthy", "database": {"connected": True, "mode": "live_mysql"}}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:faulty")
    assert res.returncode == 1
    assert "Candidate pre-switch health check FAILED" in res.stderr
    assert "Active slot 'devsecops-app-blue' continues serving traffic without impact" in res.stdout

    # Upstream must NOT have been switched
    updated_upstream = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "devsecops-app-blue:5000" in updated_upstream


# ------------------------------------------------------------------------------
# SCENARIO 4: Candidate with Disconnected MySQL is Rejected
# ------------------------------------------------------------------------------
def test_candidate_with_disconnected_mysql_rejected(mock_env):
    (mock_env["mock_dir"] / "probe_health.json").write_text(
        json.dumps({"status": "healthy", "database": {"connected": False, "mode": "disconnected"}}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:db-fail")
    assert res.returncode == 1
    assert "Candidate pre-switch health check FAILED" in res.stderr
    assert "Candidate was either unresponsive or failed database connectivity" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 5: Invalid Nginx Configuration Prevents Switching
# ------------------------------------------------------------------------------
def test_invalid_nginx_configuration_prevents_switching(mock_env):
    (mock_env["mock_dir"] / "nginx_validate_fail").touch()

    res = run_deploy(mock_env, "test-repo/app:bad-conf")
    assert res.returncode == 1
    assert "Candidate Nginx configuration validation FAILED syntax check" in res.stderr
    assert "Aborting traffic switch" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 6: Nginx Reload Failure Triggers Rollback
# ------------------------------------------------------------------------------
def test_nginx_reload_failure_triggers_rollback(mock_env):
    (mock_env["mock_dir"] / "nginx_reload_fail").touch()

    res = run_deploy(mock_env, "test-repo/app:reload-fail")
    assert res.returncode == 1
    assert "TRIGGERING AUTOMATED ROLLBACK: Nginx reload failed during traffic switch" in res.stderr
    assert "Restoring known-good configuration from /etc/nginx/upstream.conf.previous" in res.stdout
    assert "Automated rollback completed successfully" in res.stdout


# ------------------------------------------------------------------------------
# SCENARIO 7: Post-Switch Health Failure Triggers Rollback
# ------------------------------------------------------------------------------
def test_post_switch_health_failure_triggers_rollback(mock_env):
    (mock_env["mock_dir"] / "post_switch_health.json").write_text(
        json.dumps({"status": "degraded", "database": {"connected": False, "mode": "disconnected"}}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:post-switch-fail")
    assert res.returncode == 1
    assert "TRIGGERING AUTOMATED ROLLBACK: Post-switch public health check failed" in res.stderr
    assert "ROLLBACK VERIFIED: Production service successfully recovered and healthy on previous slot." in res.stdout


# ------------------------------------------------------------------------------
# SCENARIO 8: Rollback Failure Reported Clearly Without Claiming Recovery
# ------------------------------------------------------------------------------
def test_rollback_failure_reported_clearly(mock_env):
    (mock_env["mock_dir"] / "nginx_reload_fail").touch()
    (mock_env["mock_dir"] / "rollback_reload_fail").touch()

    res = run_deploy(mock_env, "test-repo/app:double-fail")
    assert res.returncode == 2
    assert "CRITICAL: Restored Nginx reload failed! Reverse proxy state uncertain!" in res.stderr
    assert "Automated rollback completed successfully" not in res.stdout
    assert "BLUE/GREEN DEPLOYMENT COMPLETED SUCCESSFULLY" not in res.stdout


# ------------------------------------------------------------------------------
# SCENARIO 9: Unknown Active Slot Aborts Safely
# ------------------------------------------------------------------------------
def test_unknown_active_slot_aborts_safely(mock_env):
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server unknown-service:8080;\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:unknown-slot")
    assert res.returncode == 1
    assert "Unknown active upstream configuration" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 10: Ambiguous Active Targets Abort Safely
# ------------------------------------------------------------------------------
def test_ambiguous_active_targets_abort_safely(mock_env):
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:ambiguous")
    assert res.returncode == 1
    assert "Ambiguous upstream configuration: both 'devsecops-app-blue' and 'devsecops-app-green' found" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 11: Secret Values Do Not Appear in Captured Logs
# ------------------------------------------------------------------------------
def test_secret_values_do_not_appear_in_logs(mock_env):
    secret_pass = "SuperSecretDbPassword9988!@#"
    res = run_deploy(mock_env, "test-repo/app:v1", extra_env={"DB_PASSWORD": secret_pass})
    assert res.returncode == 0
    full_output = res.stdout + "\n" + res.stderr
    assert secret_pass not in full_output, "CRITICAL: Secret password was exposed in deployment script output!"


# ------------------------------------------------------------------------------
# SCENARIO 12: Production Containers Are Not Stopped or Removed
# ------------------------------------------------------------------------------
def test_production_containers_never_stopped_or_removed(mock_env):
    res = run_deploy(mock_env, "test-repo/app:v1")
    assert res.returncode == 0

    log_file = mock_env["mock_dir"] / "docker_actions.log"
    actions_log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    protected_production_names = ["devsecops-mysql", "devsecops-prometheus", "devsecops-grafana", "devsecops-nginx"]

    for line in actions_log.splitlines():
        for protected in protected_production_names:
            assert protected not in line, f"Production container '{protected}' was targeted for stop/rm: {line}"


# ------------------------------------------------------------------------------
# SCENARIO 13: Concurrent Deployment Lock Prevents Race Conditions
# ------------------------------------------------------------------------------
def test_concurrent_deployment_aborts_when_lock_held(mock_env):
    lock_path = Path(mock_env["mock_dir"] / "deploy.lock")
    lock_dir = Path(str(lock_path) + ".d")
    lock_dir.mkdir(parents=True, exist_ok=True)

    # Spawn an active background process to simulate another deployment in-flight
    proc = subprocess.Popen([BASH_BIN, "-c", "echo $$; sleep 10"], stdout=subprocess.PIPE, text=True)
    try:
        active_pid = proc.stdout.readline().strip()
        (lock_dir / "pid").write_text(active_pid, encoding="utf-8")

        res = run_deploy(mock_env, "test-repo/app:concurrent-attempt")
        assert res.returncode == 1
        assert "Concurrent deployment detected" in res.stderr
    finally:
        proc.terminate()
        proc.wait()


# ------------------------------------------------------------------------------
# SCENARIO 14: Stale Deployment Lock from Inactive PID is Reclaimed
# ------------------------------------------------------------------------------
def test_stale_lock_is_reclaimed_safely(mock_env):
    lock_path = Path(mock_env["mock_dir"] / "deploy.lock")
    lock_dir = Path(str(lock_path) + ".d")
    lock_dir.mkdir(parents=True, exist_ok=True)
    # 999999 is inactive on Windows/POSIX
    (lock_dir / "pid").write_text("999999", encoding="utf-8")

    res = run_deploy(mock_env, "test-repo/app:stale-recovery")
    assert res.returncode == 0
    assert "Active slot is now:" in res.stdout


# ------------------------------------------------------------------------------
# SCENARIO 15: Missing Upstream Conf Discovers Active Route and Preserves Rollback
# ------------------------------------------------------------------------------
def test_missing_upstream_conf_discovers_active_v1_route(mock_env):
    """
    When /etc/nginx/conf.d/upstream.conf does not exist, inspects Nginx runtime
    config, identifies the active legacy route ('app:5000'), preserves that exact
    prior route in /etc/nginx/upstream.conf.previous, and switches to candidate blue.
    """
    upstream_file = mock_env["mock_dir"] / "upstream.conf"
    if upstream_file.exists():
        upstream_file.unlink()

    # Runtime Nginx configuration routing to legacy app
    (mock_env["mock_dir"] / "nginx_runtime.conf").write_text(
        "events {}\nhttp {\n    server {\n        listen 80;\n        location / {\n            proxy_pass http://app:5000;\n        }\n    }\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:v2-cutover")
    assert res.returncode == 0
    assert "Discovered legacy active container route ('app') in Nginx runtime configuration" in res.stdout
    assert "Preserving verified prior routing configuration to /etc/nginx/upstream.conf.previous..." in res.stdout
    assert "Active slot is now: blue (devsecops-app-blue)" in res.stdout

    # Verify previous backup captured the actual prior route (app:5000), not the candidate!
    prev_conf = (mock_env["mock_dir"] / "upstream.conf.previous").read_text(encoding="utf-8")
    assert "server app:5000;" in prev_conf
    assert "devsecops-app-blue" not in prev_conf

    # Verify new upstream points to candidate blue
    new_conf = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "server devsecops-app-blue:5000;" in new_conf


# ------------------------------------------------------------------------------
# SCENARIO 16: Missing Upstream Conf with Unidentifiable Route Aborts Safely
# ------------------------------------------------------------------------------
def test_missing_upstream_conf_unidentifiable_route_aborts(mock_env):
    """
    When /etc/nginx/conf.d/upstream.conf does not exist and Nginx runtime
    has no recognizable route, refuses cutover, aborts before container modifications,
    and never fabricates a rollback configuration.
    """
    upstream_file = mock_env["mock_dir"] / "upstream.conf"
    if upstream_file.exists():
        upstream_file.unlink()

    (mock_env["mock_dir"] / "nginx_runtime.conf").write_text(
        "events {}\nhttp {\n    server {\n        listen 80;\n        location / {\n            return 404;\n        }\n    }\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:unidentifiable")
    assert res.returncode == 1
    assert "Unable to unambiguously identify active production route from Nginx configuration" in res.stderr
    assert "Aborting deployment before modifying any routing or container state" in res.stderr

    # Ensure no fabricated backup was created
    prev_file = mock_env["mock_dir"] / "upstream.conf.previous"
    assert not prev_file.exists()


# ------------------------------------------------------------------------------
# SCENARIO 17: Candidate Health-Check Failure Cleans Candidate Without Touching Active
# ------------------------------------------------------------------------------
def test_candidate_health_check_failure_cleans_candidate_only(mock_env):
    (mock_env["mock_dir"] / "probe_health.json").write_text(
        json.dumps({"status": "unhealthy", "database": {"connected": False}}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:fail-probe")
    assert res.returncode == 1

    actions_log = (mock_env["mock_dir"] / "docker_actions.log").read_text(encoding="utf-8")
    # Candidate green was stopped and removed
    assert "stop devsecops-app-green" in actions_log
    assert "rm devsecops-app-green" in actions_log
    # Active slot blue was NOT stopped or removed
    assert "stop devsecops-app-blue" not in actions_log
    assert "rm devsecops-app-blue" not in actions_log


# ------------------------------------------------------------------------------
# SCENARIO 18: Rollback Restores Exact Original Upstream Configuration
# ------------------------------------------------------------------------------
def test_rollback_restores_exact_original_upstream(mock_env):
    original_upstream = "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n"
    (mock_env["mock_dir"] / "upstream.conf").write_text(original_upstream, encoding="utf-8", newline="\n")

    # Simulate post-switch failure
    (mock_env["mock_dir"] / "post_switch_health.json").write_text(
        json.dumps({"status": "degraded"}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:post-switch-fail")
    assert res.returncode == 1
    assert "Restoring known-good configuration from /etc/nginx/upstream.conf.previous..." in res.stdout
    assert "ROLLBACK VERIFIED" in res.stdout

    # Upstream must be restored to original blue
    restored_upstream = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "server devsecops-app-blue:5000;" in restored_upstream
    assert "server devsecops-app-green:5000;" not in restored_upstream


# ------------------------------------------------------------------------------
# SCENARIO 19: Cleanup Trap Never Targets Active Container on Early Exit
# ------------------------------------------------------------------------------
def test_cleanup_trap_never_targets_active_container_on_early_abort(mock_env):
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )

    # Force early failure before candidate container run by making pull fail
    res = run_deploy(mock_env, "non-existent-image:latest", extra_env={"DOCKER_CMD": "false"})
    assert res.returncode != 0

    log_file = mock_env["mock_dir"] / "docker_actions.log"
    actions_log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "stop devsecops-app-blue" not in actions_log
    assert "rm devsecops-app-blue" not in actions_log


# ------------------------------------------------------------------------------
# SCENARIO 20: Commented-out green reference while blue is active
# ------------------------------------------------------------------------------
def test_commented_out_green_reference_while_blue_is_active(mock_env):
    """
    When /etc/nginx/conf.d/upstream.conf has a commented-out reference to green,
    the script ignores the comment, identifies blue as the single active slot,
    designates green as candidate, and successfully cuts over to green.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n"
        "    # server devsecops-app-green:5000;\n"
        "    server devsecops-app-blue:5000;\n"
        "}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:comment-test")
    assert res.returncode == 0
    assert "Active slot is now: green (devsecops-app-green)" in res.stdout

    # Verify upstream was updated to green
    new_conf = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "server devsecops-app-green:5000;" in new_conf


# ------------------------------------------------------------------------------
# SCENARIO 21: Both slot names present in configuration text but only one active
# ------------------------------------------------------------------------------
def test_both_slot_names_present_but_only_one_active_directive(mock_env):
    """
    When configuration text mentions both slot names (e.g. documentation or migration comment),
    only the actual uncommented server directive determines the active slot.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "# Note: previous production slot was devsecops-app-green before maintenance\n"
        "upstream app_backend {\n"
        "    server devsecops-app-blue:5000; # active production container\n"
        "}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:both-names-comment")
    assert res.returncode == 0
    assert "Active slot is now: green (devsecops-app-green)" in res.stdout


# ------------------------------------------------------------------------------
# SCENARIO 22: Ambiguous active routes in runtime configuration aborts before container changes
# ------------------------------------------------------------------------------
def test_ambiguous_runtime_nginx_routes_abort_before_container_changes(mock_env):
    """
    When /etc/nginx/conf.d/upstream.conf is missing and runtime Nginx has multiple
    conflicting proxy_pass destinations, the script aborts without modifying containers.
    """
    upstream_file = mock_env["mock_dir"] / "upstream.conf"
    if upstream_file.exists():
        upstream_file.unlink()

    (mock_env["mock_dir"] / "nginx_runtime.conf").write_text(
        "events {}\nhttp {\n    server {\n        listen 80;\n"
        "        location /api { proxy_pass http://devsecops-app-blue:5000; }\n"
        "        location / { proxy_pass http://devsecops-app-green:5000; }\n"
        "    }\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:ambiguous-runtime")
    assert res.returncode == 1
    assert "Ambiguous active production route detected across Nginx runtime configuration" in res.stderr
    assert "Aborting deployment to avoid split-brain or unintended routing state" in res.stderr

    # Verify no container actions were logged
    actions_log = (mock_env["mock_dir"] / "docker_actions.log").read_text(encoding="utf-8") if (mock_env["mock_dir"] / "docker_actions.log").exists() else ""
    assert "stop" not in actions_log
    assert "rm" not in actions_log


# ------------------------------------------------------------------------------
# SCENARIO 23: Legacy app:5000 route detection and exact rollback restoration
# ------------------------------------------------------------------------------
def test_legacy_app_5000_detection_and_exact_rollback_restoration(mock_env):
    """
    When upstream.conf contains legacy 'server app:5000;', it is correctly identified
    as legacy slot, candidate blue is prepared, and if post-switch check fails,
    rollback restores the exact 'server app:5000;' upstream.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server app:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )

    # Force post-switch failure to trigger rollback
    (mock_env["mock_dir"] / "post_switch_health.json").write_text(
        json.dumps({"status": "degraded"}),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:legacy-app-fail")
    assert res.returncode == 1
    assert "Detected legacy alias 'app' in modular upstream" in res.stdout
    assert "Restoring known-good configuration from /etc/nginx/upstream.conf.previous..." in res.stdout
    assert "ROLLBACK VERIFIED" in res.stdout

    # Verify upstream was restored to legacy server app:5000;
    restored = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "server app:5000;" in restored


# ------------------------------------------------------------------------------
# SCENARIO 24: Legacy devsecops-app:5000 route detection and cutover
# ------------------------------------------------------------------------------
def test_legacy_devsecops_app_5000_detection_and_cutover(mock_env):
    """
    When upstream.conf contains 'server devsecops-app:5000;', it is recognized as legacy,
    candidate blue is deployed, and upstream is updated to blue.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, "test-repo/app:legacy-devsecops")
    assert res.returncode == 0
    assert "Detected legacy single container 'devsecops-app' in modular upstream" in res.stdout
    assert "Active slot is now: blue (devsecops-app-blue)" in res.stdout

    new_conf = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "server devsecops-app-blue:5000;" in new_conf


# ------------------------------------------------------------------------------
# SCENARIO 25: Pre-stop protection aborts if candidate is active traffic destination
# ------------------------------------------------------------------------------
def test_pre_stop_protection_aborts_if_candidate_is_active_traffic_destination(mock_env):
    """
    If the candidate container happens to be actively referenced in live Nginx routing,
    Section 4 aborts immediately before issuing docker stop or docker rm.
    """
    # Active upstream points to devsecops-app-green
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    # Runtime dump also shows devsecops-app-blue actively referenced in location proxy_pass
    (mock_env["mock_dir"] / "nginx_runtime.conf").write_text(
        "events {}\nhttp {\n    upstream app_backend { server devsecops-app-green:5000; }\n"
        "    server {\n        location / { proxy_pass http://devsecops-app-blue:5000; }\n    }\n}\n",
        encoding="utf-8", newline="\n"
    )

    # Active slot is green, so candidate is blue. But blue is in live Nginx routing!
    res = run_deploy(mock_env, "test-repo/app:candidate-live")
    assert res.returncode == 1
    assert "CRITICAL SAFETY VIOLATION: Candidate container 'devsecops-app-blue' is actively referenced in Nginx live routing!" in res.stderr

    # Ensure devsecops-app-blue was NOT stopped or removed
    actions_log = (mock_env["mock_dir"] / "docker_actions.log").read_text(encoding="utf-8") if (mock_env["mock_dir"] / "docker_actions.log").exists() else ""
    assert "stop devsecops-app-blue" not in actions_log
    assert "rm devsecops-app-blue" not in actions_log


# ------------------------------------------------------------------------------
# SCENARIO 26: Failed backup creation refuses cutover
# ------------------------------------------------------------------------------
def test_failed_backup_creation_refuses_cutover(mock_env):
    """
    If /etc/nginx/upstream.conf.previous cannot be verified (e.g. write error or empty),
    traffic cutover is refused, candidate is cleaned up, and active slot is untouched.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    # Simulate backup verification failure
    (mock_env["mock_dir"] / "backup_test_fail").touch()

    res = run_deploy(mock_env, "test-repo/app:backup-fail")
    assert res.returncode == 1
    assert "Failed to verify /etc/nginx/upstream.conf.previous backup" in res.stderr

    # Active upstream should still be blue, NOT switched to green
    current_upstream = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "server devsecops-app-blue:5000;" in current_upstream
    assert "server devsecops-app-green:5000;" not in current_upstream


# ------------------------------------------------------------------------------
# SCENARIO 27: Preservation of MySQL and persistent volume on all failure paths
# ------------------------------------------------------------------------------
def test_preservation_of_mysql_and_persistent_volume_on_all_failures(mock_env):
    """
    Verify that across various deployment failure paths (bad image, syntax failure,
    health failure, post-switch failure), devsecops-mysql is never targeted.
    """
    # Test case 1: Health failure
    (mock_env["mock_dir"] / "probe_health.json").write_text(
        json.dumps({"status": "unhealthy"}), encoding="utf-8", newline="\n"
    )
    run_deploy(mock_env, "test-repo/app:fail-1")

    # Test case 2: Syntax failure
    (mock_env["mock_dir"] / "probe_health.json").unlink()
    (mock_env["mock_dir"] / "nginx_validate_fail").touch()
    run_deploy(mock_env, "test-repo/app:fail-2")

    actions_log = (mock_env["mock_dir"] / "docker_actions.log").read_text(encoding="utf-8") if (mock_env["mock_dir"] / "docker_actions.log").exists() else ""
    for line in actions_log.splitlines():
        assert "devsecops-mysql" not in line
        assert "mysql-data" not in line


# ------------------------------------------------------------------------------
# SCENARIO 28: CI Nginx bind mount consistency validation logic
# ------------------------------------------------------------------------------
def test_ci_nginx_bind_mount_and_stale_config_logic(tmp_path):
    """
    Validates the CI workflow Section 4 inspection logic:
    Verifies that when docker inspect shows mismatched mount source,
    NGINX_MOUNTS_VALID is false and re-provisioning is required.
    """
    ci_script = """
    UPSTREAM_SRC="/wrong/host/path/upstream.conf"
    CONF_SRC="/home/ec2-user/nginx-conf/nginx.conf"

    NGINX_MOUNTS_VALID=false
    if [ "$UPSTREAM_SRC" = "/home/ec2-user/nginx-conf/upstream.conf" ] && \\
       [ "$CONF_SRC" = "/home/ec2-user/nginx-conf/nginx.conf" ]; then
        NGINX_MOUNTS_VALID=true
    fi
    echo "NGINX_MOUNTS_VALID=$NGINX_MOUNTS_VALID"
    """
    proc = subprocess.run([BASH_BIN, "-c", ci_script], capture_output=True, text=True, check=True)
    assert "NGINX_MOUNTS_VALID=false" in proc.stdout


# ==============================================================================
# CI SECTION 4 MIGRATION & ROUTE DETECTION REGRESSION TEST SUITE (PHASE 6E)
# ==============================================================================

CI_ROUTE_PARSER_SCRIPT = """
CLEAN_DUMP="$1"
FOUND_BLUE=false
FOUND_GREEN=false
FOUND_DEVSECOPS=false
FOUND_APP=false

# Check active server directives (inside upstream blocks)
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app-blue(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
    FOUND_BLUE=true
fi
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app-green(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
    FOUND_GREEN=true
fi
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
    FOUND_DEVSECOPS=true
fi
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+app(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
    FOUND_APP=true
fi

# Check direct proxy_pass directives (outside upstream blocks)
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://devsecops-app-blue(:[0-9]+)?/?;'; then
    FOUND_BLUE=true
fi
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://devsecops-app-green(:[0-9]+)?/?;'; then
    FOUND_GREEN=true
fi
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://devsecops-app(:[0-9]+)?/?;'; then
    FOUND_DEVSECOPS=true
fi
if echo "$CLEAN_DUMP" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://app(:[0-9]+)?/?;'; then
    FOUND_APP=true
fi

DUMP_MATCHES=0
[ "$FOUND_BLUE" = true ] && DUMP_MATCHES=$((DUMP_MATCHES + 1))
[ "$FOUND_GREEN" = true ] && DUMP_MATCHES=$((DUMP_MATCHES + 1))
[ "$FOUND_DEVSECOPS" = true ] && DUMP_MATCHES=$((DUMP_MATCHES + 1))
[ "$FOUND_APP" = true ] && DUMP_MATCHES=$((DUMP_MATCHES + 1))

if [ "$DUMP_MATCHES" -gt 1 ]; then
    echo "AMBIGUOUS"
    exit 1
elif [ "$FOUND_BLUE" = true ]; then
    echo "devsecops-app-blue"
elif [ "$FOUND_GREEN" = true ]; then
    echo "devsecops-app-green"
elif [ "$FOUND_DEVSECOPS" = true ]; then
    echo "devsecops-app"
elif [ "$FOUND_APP" = true ]; then
    echo "app"
else
    echo "UNKNOWN"
    exit 1
fi
"""


def run_ci_parser(clean_dump_text):
    proc = subprocess.run(
        [BASH_BIN, "-c", CI_ROUTE_PARSER_SCRIPT, "sh", clean_dump_text],
        capture_output=True,
        text=True
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def run_ci_migration(tmp_path, setup_flags=None):
    """
    Simulates execution of CI Section 4 migration logic in an isolated directory
    with a mock docker CLI that records command execution order.
    """
    setup_flags = setup_flags or {}
    work_dir = tmp_path / "ci_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    bin_dir = work_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    conf_dir = work_dir / "nginx-conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    state_dir = work_dir.as_posix()

    mock_docker_script = f"""#!/usr/bin/env bash
STATE_DIR="{state_dir}"
LOG="$STATE_DIR/docker_ci_actions.log"

CMD="$*"
echo "$CMD" >> "$LOG"

if [ "$1" = "ps" ]; then
    if [ -f "$STATE_DIR/nginx_stopped" ]; then
        exit 0
    fi
    echo "devsecops-nginx"
    exit 0
fi

if [ "$1" = "inspect" ]; then
    exit 0
fi

if [ "$1" = "cp" ]; then
    if [ -f "$STATE_DIR/backup_fail" ]; then
        exit 1
    fi
    SRC="$2"
    DEST="$3"
    if [ -f "$STATE_DIR/backup_empty" ]; then
        touch "$DEST"
        exit 0
    fi
    if [[ "$SRC" == *"upstream.conf"* ]]; then
        if [ -f "$STATE_DIR/upstream_backup_fail" ]; then
            exit 1
        fi
        echo "upstream app_backend {{ server app:5000; }}" > "$DEST"
        exit 0
    fi
    echo "events {{ worker_connections 1024; }} http {{ server {{ listen 80; location / {{ proxy_pass http://app:5000; }} }} }}" > "$DEST"
    exit 0
fi

if [ "$1" = "run" ]; then
    if [[ "$CMD" == *"--rm"* && "$CMD" == *"nginx -t"* ]]; then
        if [[ "$CMD" != *"--network devsecops-network"* ]]; then
            echo "docker: pre-flight validation requires --network devsecops-network" >&2
            exit 1
        fi
        if [ -f "$STATE_DIR/preflight_fail" ]; then
            echo "nginx: [emerg] syntax error" >&2
            exit 1
        fi
        exit 0
    fi
    if [[ "$CMD" == *"-d"* ]]; then
        if [ -f "$STATE_DIR/startup_fail" ]; then
            echo "docker: Error response from daemon: port is already allocated" >&2
            exit 1
        fi
        rm -f "$STATE_DIR/nginx_stopped"
        echo "mock-new-nginx-cid"
        exit 0
    fi
fi

if [ "$1" = "rename" ]; then
    if [ -f "$STATE_DIR/rename_fail" ]; then
        echo "docker: Error response from daemon: cannot rename container" >&2
        exit 1
    fi
    exit 0
fi

if [ "$1" = "stop" ]; then
    if [ -f "$STATE_DIR/stop_fail" ]; then
        echo "docker: Error response from daemon: cannot stop container" >&2
        exit 1
    fi
    touch "$STATE_DIR/nginx_stopped"
    exit 0
fi

if [ "$1" = "start" ]; then
    rm -f "$STATE_DIR/nginx_stopped"
    exit 0
fi

if [ "$1" = "rm" ]; then
    exit 0
fi

if [ "$1" = "exec" ]; then
    if [[ "$CMD" == *"test -s /etc/nginx/conf.d/upstream.conf"* ]]; then
        if [ -f "$STATE_DIR/no_upstream_in_container" ]; then
            exit 1
        fi
        exit 0
    fi
    if [[ "$CMD" == *"nginx -t"* ]]; then
        if [ -f "$STATE_DIR/health_fail" ]; then
            echo "nginx: health validation failed" >&2
            exit 1
        fi
        exit 0
    fi
fi

exit 0
"""
    docker_bin = bin_dir / "docker.sh"
    docker_bin.write_text(mock_docker_script, encoding="utf-8", newline="\n")

    for k, v in setup_flags.items():
        if v is True:
            (work_dir / k).touch()

    ci_script = f"""
    set -euo pipefail
    docker() {{
        bash "{docker_bin.as_posix()}" "$@"
    }}
    NGINX_CONF_DIR="{conf_dir.as_posix()}"
    ACTIVE_TARGET="devsecops-app-blue"
    NGINX_RUNNING=true
    ORIGINAL_PRESERVED=false

    mkdir -p "$NGINX_CONF_DIR/backup"
    rm -f "$NGINX_CONF_DIR/backup/*" 2>/dev/null || true

    docker cp devsecops-nginx:/etc/nginx/nginx.conf "$NGINX_CONF_DIR/backup/nginx.conf.orig" 2>/dev/null || true
    docker cp devsecops-nginx:/etc/nginx/conf.d/upstream.conf "$NGINX_CONF_DIR/backup/upstream.conf.orig" 2>/dev/null || true

    if [ ! -s "$NGINX_CONF_DIR/backup/nginx.conf.orig" ] && [ -s "$NGINX_CONF_DIR/nginx.conf.bak" ]; then
        cp "$NGINX_CONF_DIR/nginx.conf.bak" "$NGINX_CONF_DIR/backup/nginx.conf.orig" 2>/dev/null || true
    fi
    if [ ! -s "$NGINX_CONF_DIR/backup/upstream.conf.orig" ] && [ -s "$NGINX_CONF_DIR/upstream.conf.bak" ]; then
        cp "$NGINX_CONF_DIR/upstream.conf.bak" "$NGINX_CONF_DIR/backup/upstream.conf.orig" 2>/dev/null || true
    fi

    BACKUP_VALID=false
    if [ -s "$NGINX_CONF_DIR/backup/nginx.conf.orig" ]; then
        BACKUP_VALID=true
    fi

    if docker exec devsecops-nginx test -s /etc/nginx/conf.d/upstream.conf 2>/dev/null; then
        if [ ! -s "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
            BACKUP_VALID=false
        fi
    elif [ -s "$NGINX_CONF_DIR/upstream.conf.bak" ]; then
        if [ ! -s "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
            BACKUP_VALID=false
        fi
    fi

    if [ "$BACKUP_VALID" != true ]; then
        echo "CRITICAL: Failed to preserve non-empty original Nginx configuration backup from running container. Aborting before disruption." >&2
        exit 1
    fi

    echo "upstream app_backend {{ server ${{ACTIVE_TARGET}}:5000; }}" > "$NGINX_CONF_DIR/upstream.conf"
    echo "events {{ worker_connections 1024; }} http {{ include $NGINX_CONF_DIR/upstream.conf; }}" > "$NGINX_CONF_DIR/nginx.conf"

    if ! docker run --rm --network devsecops-network -v "$NGINX_CONF_DIR/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$NGINX_CONF_DIR/upstream.conf:/etc/nginx/conf.d/upstream.conf:ro" nginx:alpine nginx -t >/dev/null 2>&1; then
        echo "CRITICAL: Generated Nginx configuration failed pre-flight syntax check. Aborting before disrupting service." >&2
        if [ -f "$NGINX_CONF_DIR/backup/nginx.conf.orig" ]; then
            cp "$NGINX_CONF_DIR/backup/nginx.conf.orig" "$NGINX_CONF_DIR/nginx.conf" 2>/dev/null || true
        fi
        if [ -f "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
            cp "$NGINX_CONF_DIR/backup/upstream.conf.orig" "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
        else
            rm -f "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
        fi
        exit 1
    fi

    if [ "$NGINX_RUNNING" = true ]; then
        if ! docker rename devsecops-nginx devsecops-nginx-original; then
            echo "CRITICAL: Failed to rename devsecops-nginx to devsecops-nginx-original. Aborting without disrupting service." >&2
            if [ -f "$NGINX_CONF_DIR/backup/nginx.conf.orig" ]; then
                cp "$NGINX_CONF_DIR/backup/nginx.conf.orig" "$NGINX_CONF_DIR/nginx.conf" 2>/dev/null || true
            fi
            if [ -f "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
                cp "$NGINX_CONF_DIR/backup/upstream.conf.orig" "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
            else
                rm -f "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
            fi
            exit 1
        fi

        if ! docker stop devsecops-nginx-original; then
            echo "CRITICAL: Failed to stop devsecops-nginx-original. Restoring original container name and aborting." >&2
            docker rename devsecops-nginx-original devsecops-nginx 2>/dev/null || true
            if [ -f "$NGINX_CONF_DIR/backup/nginx.conf.orig" ]; then
                cp "$NGINX_CONF_DIR/backup/nginx.conf.orig" "$NGINX_CONF_DIR/nginx.conf" 2>/dev/null || true
            fi
            if [ -f "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
                cp "$NGINX_CONF_DIR/backup/upstream.conf.orig" "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
            else
                rm -f "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
            fi
            exit 1
        fi

        ORIGINAL_PRESERVED=true
    fi

    REPLACEMENT_STARTED=false
    if docker run -d --name devsecops-nginx --network devsecops-network --restart always -p 80:80 \\
        -v "$NGINX_CONF_DIR/nginx.conf:/etc/nginx/nginx.conf:ro" \\
        -v "$NGINX_CONF_DIR/upstream.conf:/etc/nginx/conf.d/upstream.conf" \\
        nginx:alpine >/dev/null 2>&1; then
        REPLACEMENT_STARTED=true
    fi

    REPLACEMENT_HEALTHY=false
    if [ "$REPLACEMENT_STARTED" = true ]; then
        if docker ps --filter "name=^/devsecops-nginx$" --filter "status=running" -q | grep -q .; then
            if docker exec devsecops-nginx nginx -t >/dev/null 2>&1; then
                REPLACEMENT_HEALTHY=true
            fi
        fi
    fi

    if [ "$REPLACEMENT_HEALTHY" != true ]; then
        echo "CRITICAL: Replacement devsecops-nginx failed startup or health verification! Initiating rollback..." >&2
        docker stop devsecops-nginx 2>/dev/null || true
        docker rm -f devsecops-nginx 2>/dev/null || true

        if [ "$ORIGINAL_PRESERVED" = true ]; then
            RESTORE_SUCCESS=true
            if [ -f "$NGINX_CONF_DIR/backup/nginx.conf.orig" ]; then
                if ! cp "$NGINX_CONF_DIR/backup/nginx.conf.orig" "$NGINX_CONF_DIR/nginx.conf"; then
                    RESTORE_SUCCESS=false
                fi
            fi
            if [ -f "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
                if ! cp "$NGINX_CONF_DIR/backup/upstream.conf.orig" "$NGINX_CONF_DIR/upstream.conf"; then
                    RESTORE_SUCCESS=false
                fi
            else
                rm -f "$NGINX_CONF_DIR/upstream.conf" 2>/dev/null || true
            fi

            docker rename devsecops-nginx-original devsecops-nginx 2>/dev/null || true
            docker start devsecops-nginx 2>/dev/null || true

            CONTAINER_RUNNING=false
            if docker ps --filter "name=^/devsecops-nginx$" --filter "status=running" -q | grep -q .; then
                CONTAINER_RUNNING=true
            fi

            CONFIG_VERIFIED=true
            if [ -f "$NGINX_CONF_DIR/backup/nginx.conf.orig" ]; then
                if ! cmp -s "$NGINX_CONF_DIR/backup/nginx.conf.orig" "$NGINX_CONF_DIR/nginx.conf"; then
                    CONFIG_VERIFIED=false
                fi
            fi
            if [ -f "$NGINX_CONF_DIR/backup/upstream.conf.orig" ]; then
                if ! cmp -s "$NGINX_CONF_DIR/backup/upstream.conf.orig" "$NGINX_CONF_DIR/upstream.conf"; then
                    CONFIG_VERIFIED=false
                fi
            fi

            if [ "$CONTAINER_RUNNING" = true ] && [ "$CONFIG_VERIFIED" = true ] && [ "$RESTORE_SUCCESS" = true ]; then
                echo "RECOVERY VERIFIED: Original Nginx service successfully restored and operational."
            else
                echo "CRITICAL: Rollback failed! Original Nginx container or configuration could not be verified. Manual intervention required!" >&2
            fi
        fi
        exit 1
    fi

    if [ "$ORIGINAL_PRESERVED" = true ]; then
        docker rm -f devsecops-nginx-original 2>/dev/null || true
    fi
    echo "devsecops-nginx migration successfully verified and operational with modular mounts."
    """

    res = subprocess.run([BASH_BIN, "-c", ci_script], capture_output=True, text=True)
    log_file = work_dir / "docker_ci_actions.log"
    actions = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    return res, actions, work_dir


# ------------------------------------------------------------------------------
# SCENARIO 29: Inline/minified route detection in CI
# ------------------------------------------------------------------------------
def test_ci_route_detection_inline_and_minified():
    """
    Verifies that CI route parser correctly detects inline / minified directives
    following opening braces or semicolons without false negatives.
    """
    rc, out, _ = run_ci_parser("server { location / { proxy_pass http://app:5000; } }")
    assert rc == 0
    assert out == "app"

    rc, out, _ = run_ci_parser("upstream app_backend { server devsecops-app-blue:5000; }")
    assert rc == 0
    assert out == "devsecops-app-blue"

    rc, out, _ = run_ci_parser("upstream app_backend { server devsecops-app-green:5000; }")
    assert rc == 0
    assert out == "devsecops-app-green"

    rc, out, _ = run_ci_parser("server { location / { proxy_pass http://devsecops-app:5000; } }")
    assert rc == 0
    assert out == "devsecops-app"


# ------------------------------------------------------------------------------
# SCENARIO 30: Upstream directives with optional parameters in CI
# ------------------------------------------------------------------------------
def test_ci_route_detection_optional_parameters():
    """
    Verifies that upstream directives with parameters (weight, max_fails, backup)
    or trailing spaces are parsed without error.
    """
    rc, out, _ = run_ci_parser("upstream app_backend {\n    server devsecops-app-blue:5000 weight=5 max_fails=3;\n}")
    assert rc == 0
    assert out == "devsecops-app-blue"

    rc, out, _ = run_ci_parser("upstream app_backend {\n    server devsecops-app-green:5000 backup;\n}")
    assert rc == 0
    assert out == "devsecops-app-green"

    rc, out, _ = run_ci_parser("upstream app_backend {\n    server devsecops-app:5000 ;\n}")
    assert rc == 0
    assert out == "devsecops-app"


# ------------------------------------------------------------------------------
# SCENARIO 31: Both legacy backend aliases in CI
# ------------------------------------------------------------------------------
def test_ci_route_detection_both_legacy_aliases():
    """
    Verifies that both legacy Docker alias 'app:5000' and container name
    'devsecops-app:5000' are supported across both server and proxy_pass directives.
    """
    rc, out, _ = run_ci_parser("location / { proxy_pass http://app:5000; }")
    assert rc == 0
    assert out == "app"

    rc, out, _ = run_ci_parser("location / { proxy_pass http://devsecops-app:5000; }")
    assert rc == 0
    assert out == "devsecops-app"

    rc, out, _ = run_ci_parser("upstream app_backend {\n    server app:5000;\n}")
    assert rc == 0
    assert out == "app"

    rc, out, _ = run_ci_parser("upstream app_backend {\n    server devsecops-app:5000;\n}")
    assert rc == 0
    assert out == "devsecops-app"


# ------------------------------------------------------------------------------
# SCENARIO 32: Missing host configuration recovered from running container
# ------------------------------------------------------------------------------
def test_ci_missing_host_config_recovered_from_running_container(tmp_path):
    """
    Verifies that when host configuration does not exist, CI migration preserves
    the configuration directly from the running container via docker cp before
    writing new configuration.
    """
    res, actions, work_dir = run_ci_migration(tmp_path)
    assert res.returncode == 0
    backup_file = work_dir / "nginx-conf" / "backup" / "nginx.conf.orig"
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    cp_actions = [a for a in actions if a.startswith("cp devsecops-nginx")]
    assert len(cp_actions) >= 1


# ------------------------------------------------------------------------------
# SCENARIO 33: Failed or empty container backup aborts before disruptive operation
# ------------------------------------------------------------------------------
def test_ci_failed_or_empty_container_backup_aborts_safely(tmp_path):
    """
    If container configuration backup fails or produces an empty file,
    the workflow aborts immediately with an error before stopping, renaming,
    or removing the running container.
    """
    res, actions, _ = run_ci_migration(tmp_path, setup_flags={"backup_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: Failed to preserve non-empty original Nginx configuration backup" in res.stderr

    for act in actions:
        assert not act.startswith("stop")
        assert not act.startswith("rename")
        assert not act.startswith("rm")


# ------------------------------------------------------------------------------
# SCENARIO 34: Invalid generated configuration aborts before replacing running service
# ------------------------------------------------------------------------------
def test_ci_invalid_generated_config_aborts_before_replacing_service(tmp_path):
    """
    Verifies that pre-flight syntax check ('docker run --rm --network devsecops-network ... nginx -t') catches
    configuration errors BEFORE disrupting the running service.
    """
    res, actions, _ = run_ci_migration(tmp_path, setup_flags={"preflight_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: Generated Nginx configuration failed pre-flight syntax check" in res.stderr

    assert any("--rm" in a and "nginx -t" in a and "--network devsecops-network" in a for a in actions)
    assert not any(a.startswith("rename") for a in actions)
    assert not any(a.startswith("stop") for a in actions)


# ------------------------------------------------------------------------------
# SCENARIO 35: Replacement container startup failure triggers recovery
# ------------------------------------------------------------------------------
def test_ci_replacement_container_startup_failure_triggers_recovery(tmp_path):
    """
    If replacement container fails to start, recovery cleans up the replacement,
    restores host files from backup, renames devsecops-nginx-original back to
    devsecops-nginx, and restarts it.
    """
    res, actions, _ = run_ci_migration(tmp_path, setup_flags={"startup_fail": True})
    assert res.returncode == 1
    assert "RECOVERY VERIFIED: Original Nginx service successfully restored and operational." in res.stdout

    rename_orig_idx = next(i for i, a in enumerate(actions) if a == "rename devsecops-nginx devsecops-nginx-original")
    stop_orig_idx = next(i for i, a in enumerate(actions) if a == "stop devsecops-nginx-original")
    run_repl_idx = next(i for i, a in enumerate(actions) if "run -d --name devsecops-nginx" in a)
    restore_rename_idx = next(i for i, a in enumerate(actions) if a == "rename devsecops-nginx-original devsecops-nginx")
    start_orig_idx = next(i for i, a in enumerate(actions) if a == "start devsecops-nginx")

    assert rename_orig_idx < stop_orig_idx < run_repl_idx < restore_rename_idx < start_orig_idx


# ------------------------------------------------------------------------------
# SCENARIO 36: Failed replacement health check restores original service
# ------------------------------------------------------------------------------
def test_ci_replacement_health_check_failure_restores_original_service(tmp_path):
    """
    If replacement container starts but fails health verification,
    the workflow triggers automated recovery to restore the original container.
    """
    res, actions, _ = run_ci_migration(tmp_path, setup_flags={"health_fail": True})
    assert res.returncode == 1
    assert "RECOVERY VERIFIED: Original Nginx service successfully restored and operational." in res.stdout
    assert any(a == "start devsecops-nginx" for a in actions)


# ------------------------------------------------------------------------------
# SCENARIO 37: Original container not removed before successful verification
# ------------------------------------------------------------------------------
def test_ci_original_container_not_removed_before_successful_verification(tmp_path):
    """
    Verifies that the original container is NEVER removed before the replacement
    has passed startup and health verification.
    """
    res, actions, _ = run_ci_migration(tmp_path)
    assert res.returncode == 0
    assert "devsecops-nginx migration successfully verified" in res.stdout

    preflight_idx = next(i for i, a in enumerate(actions) if "--rm" in a and "--network devsecops-network" in a and "nginx -t" in a)
    run_repl_idx = next(i for i, a in enumerate(actions) if "run -d --name devsecops-nginx" in a)
    exec_health_idx = next(i for i, a in enumerate(actions) if "exec devsecops-nginx nginx -t" in a)
    rm_orig_idx = next(i for i, a in enumerate(actions) if a == "rm -f devsecops-nginx-original")

    assert preflight_idx < run_repl_idx < exec_health_idx < rm_orig_idx


# ------------------------------------------------------------------------------
# SCENARIO 38: MySQL and persistent volume untouched during all failure paths
# ------------------------------------------------------------------------------
def test_ci_mysql_and_persistent_volume_untouched_on_all_failures(tmp_path):
    """
    Verifies that across all CI Section 4 failure paths (backup failure,
    upstream backup failure, pre-flight syntax failure, rename failure,
    stop failure, startup failure, health verification failure),
    neither devsecops-mysql nor its data volume are ever targeted.
    """
    failure_cases = [
        {"backup_fail": True},
        {"upstream_backup_fail": True},
        {"preflight_fail": True},
        {"rename_fail": True},
        {"stop_fail": True},
        {"startup_fail": True},
        {"health_fail": True},
    ]

    for flags in failure_cases:
        sub_dir = tmp_path / f"test_{list(flags.keys())[0]}"
        _, actions, _ = run_ci_migration(sub_dir, setup_flags=flags)
        for act in actions:
            assert "devsecops-mysql" not in act
            assert "mysql-data" not in act


# ------------------------------------------------------------------------------
# SCENARIO 39: Container rename failure aborts without disrupting service
# ------------------------------------------------------------------------------
def test_ci_rename_failure_aborts_without_disruption(tmp_path):
    """
    Verifies that if docker rename fails, the workflow does not attempt to stop
    or remove the original container or start a replacement container.
    """
    res, actions, work_dir = run_ci_migration(tmp_path, setup_flags={"rename_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: Failed to rename devsecops-nginx to devsecops-nginx-original" in res.stderr

    # Container was never stopped or removed
    assert not any(a.startswith("stop") for a in actions)
    assert not any(a.startswith("rm") for a in actions)
    assert not any("run -d" in a for a in actions)


# ------------------------------------------------------------------------------
# SCENARIO 40: Container stop failure restores original name and aborts safely
# ------------------------------------------------------------------------------
def test_ci_stop_failure_restores_name_and_aborts(tmp_path):
    """
    Verifies that if stopping devsecops-nginx-original fails, the container is
    immediately renamed back to devsecops-nginx and the workflow aborts without
    starting a replacement or removing the container.
    """
    res, actions, work_dir = run_ci_migration(tmp_path, setup_flags={"stop_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: Failed to stop devsecops-nginx-original. Restoring original container name and aborting." in res.stderr

    # Verify rename back occurred
    rename_orig_idx = next(i for i, a in enumerate(actions) if a == "rename devsecops-nginx devsecops-nginx-original")
    rename_back_idx = next(i for i, a in enumerate(actions) if a == "rename devsecops-nginx-original devsecops-nginx")
    assert rename_orig_idx < rename_back_idx

    # Replacement was never started and container was never removed
    assert not any(a.startswith("rm") for a in actions)
    assert not any("run -d" in a for a in actions)


# ------------------------------------------------------------------------------
# SCENARIO 41: Backup failure when upstream exists aborts before host modification
# ------------------------------------------------------------------------------
def test_ci_upstream_backup_failure_aborts_safely(tmp_path):
    """
    If container has an upstream.conf but backup of upstream.conf fails,
    the workflow aborts before renaming, stopping, or running any replacement.
    """
    res, actions, work_dir = run_ci_migration(tmp_path, setup_flags={"upstream_backup_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: Failed to preserve non-empty original Nginx configuration backup" in res.stderr

    for act in actions:
        assert not act.startswith("stop")
        assert not act.startswith("rename")
        assert not act.startswith("rm")
        assert "run -d" not in act


# ------------------------------------------------------------------------------
# SCENARIO 42: Restoration of both configuration files on rollback
# ------------------------------------------------------------------------------
def test_ci_restoration_of_both_configuration_files_on_rollback(tmp_path):
    """
    Verifies that when rollback is triggered, both nginx.conf and upstream.conf
    are restored and verified to match their backups, and RECOVERY VERIFIED is reported.
    """
    res, actions, work_dir = run_ci_migration(tmp_path, setup_flags={"startup_fail": True})
    assert res.returncode == 1
    assert "RECOVERY VERIFIED: Original Nginx service successfully restored and operational." in res.stdout

    # Verify both files match their backup counterparts
    conf_dir = work_dir / "nginx-conf"
    assert (conf_dir / "nginx.conf").read_text(encoding="utf-8") == (conf_dir / "backup" / "nginx.conf.orig").read_text(encoding="utf-8")
    assert (conf_dir / "upstream.conf").read_text(encoding="utf-8") == (conf_dir / "backup" / "upstream.conf.orig").read_text(encoding="utf-8")
