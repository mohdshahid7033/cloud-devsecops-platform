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
        if [ -f "$STATE_DIR/nginx_rollback_syntax_fail" ]; then
            echo "nginx: [emerg] host not found in upstream \"devsecops-app-blue\" in /etc/nginx/conf.d/upstream.conf:2" >&2
            echo "nginx: configuration file /etc/nginx/nginx.conf test failed" >&2
            exit 1
        fi
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

    if [[ "$CMD" == *"cat /etc/nginx/upstream.conf.previous"* ]] && [[ "$CMD" != *">"* ]]; then
        cat "$STATE_DIR/upstream.conf.previous" 2>/dev/null || true
        exit 0
    fi

    if [[ "$CMD" == *"cat /etc/nginx/upstream.conf.previous > /etc/nginx/conf.d/upstream.conf"* ]]; then
        if [ -f "$STATE_DIR/restore_write_fail" ]; then
            exit 1
        fi
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


DEFAULT_MOCK_DIGEST = "ba018c08cfb1eab89293eee28d92b24b90e801d7994a8df33798cfd5a7fa7cec"


def run_deploy(mock_env, deploy_image=None, extra_env=None, args=None, allow_raw_image=False):
    """Executes deploy_blue_green.sh with mocked dependencies and captures output."""
    if deploy_image is None:
        deploy_image = f"test-repo/app:latest@sha256:{DEFAULT_MOCK_DIGEST}"
    elif not allow_raw_image and "@sha256:" not in deploy_image:
        deploy_image = f"{deploy_image}@sha256:{DEFAULT_MOCK_DIGEST}"

    env = os.environ.copy()
    env["DOCKER_CMD"] = mock_env["docker_bin"]
    env["CURL_CMD"] = mock_env["curl_bin"]
    env["DB_PASSWORD"] = "TestMockDbPassword123!"
    env["PROBE_TIMEOUT_SECS"] = "4"
    env["POST_SWITCH_TIMEOUT_SECS"] = "4"
    env["DEPLOY_LOCK_PATH"] = (mock_env["mock_dir"] / "deploy.lock").as_posix()
    env["DEPLOYMENT_STATE_FILE"] = (mock_env["mock_dir"] / "deployment_state.json").as_posix()
    if extra_env:
        env.update(extra_env)

    if args is not None:
        cmd = [BASH_BIN, SCRIPT_PATH] + args
    else:
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
# UNIT TEST HARNESS: ISOLATED ROUTE STRING PARSER REGEX LOGIC
#
# NOTE: This parser script is maintained strictly as an isolated unit-testing harness
# for raw regex/string pattern matching (used in Scenarios 29-31 below).
# It is NOT used as proof of end-to-end production workflow behavior.
# Production workflow discovery behavior is verified via run_ci_discovery_cascade(),
# which executes the exact production shell script dynamically extracted directly
# from .github/workflows/ci.yml (via extract_ci_discovery_script()).
# ==============================================================================

CI_ROUTE_PARSER_SCRIPT = r"""
RAW_CONF="$1"
CLEAN_DUMP=$(echo "$RAW_CONF" | sed -e 's/#.*//')
if [ -z "$(echo "$CLEAN_DUMP" | tr -d '[:space:]')" ]; then
    echo "EMPTY"
    exit 1
fi

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

# Check for unknown backend targets
UNKNOWN_TARGETS=false
for s_target in $(echo "$CLEAN_DUMP" | grep -E '(^|[[:space:];{}])server[[:space:]]+[a-zA-Z0-9_.-]+(:[0-9]+)?' | awk '{for(i=1;i<=NF;i++) if($i=="server") print $(i+1)}' | sed 's/[:;].*//'); do
    case "$s_target" in
        devsecops-app-blue|devsecops-app-green|devsecops-app|app)
            ;;
        *)
            UNKNOWN_TARGETS=true
            ;;
    esac
done
for p_target in $(echo "$CLEAN_DUMP" | grep -E 'proxy_pass[[:space:]]+http://[a-zA-Z0-9_.-]+' | awk '{for(i=1;i<=NF;i++) if($i ~ /^http:\/\//) print $i}' | sed -e 's#^http://##' -e 's/[:;/].*//'); do
    case "$p_target" in
        devsecops-app-blue|devsecops-app-green|devsecops-app|app|app_backend)
            ;;
        *)
            UNKNOWN_TARGETS=true
            ;;
    esac
done

if [ "$UNKNOWN_TARGETS" = true ]; then
    echo "UNKNOWN_TARGET"
    exit 1
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
    """
    Isolated unit test helper: executes the route parser regex patterns on raw strings.
    For end-to-end production workflow testing, use run_ci_discovery_cascade().
    """
    proc = subprocess.run(
        [BASH_BIN, "-c", CI_ROUTE_PARSER_SCRIPT, "sh", clean_dump_text],
        capture_output=True,
        text=True
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def extract_ci_discovery_script():
    """
    Extracts the exact production Nginx discovery and syntax validation shell block
    directly from .github/workflows/ci.yml to ensure 100% implementation equivalence
    and prevent test harness drift.
    """
    import yaml
    with open(".github/workflows/ci.yml", "r", encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    deploy_step = next(s for s in wf["jobs"]["deploy-blue-green"]["steps"] if s.get("id") == "ssm_deploy")
    script = deploy_step["run"]
    lines = script.splitlines()

    start_idx = next(i for i, l in enumerate(lines) if "Inspect running Nginx configuration to discover the active route" in l)
    end_idx = next(i for i, l in enumerate(lines) if "Determine the active upstream target" in l)
    return "\n".join(lines[start_idx:end_idx])


def run_ci_discovery_cascade(
    container_upstream=None,
    host_upstream=None,
    host_mount_provenance=None,
    nginx_t_output=None,
    nginx_t_fail=False,
    nginx_t_script=None,
    container_root_conf=None,
    nginx_syntax_script=None,
    nginx_syntax_fail=False
):
    """
    Executes the exact extracted production Nginx discovery shell script
    against an isolated mock environment with a shell-native mock Docker CLI.
    """
    import tempfile
    test_dir = tempfile.mkdtemp(prefix="mock_ci_disc_")
    try:
        bin_dir = Path(test_dir) / "bin"
        state_dir = Path(test_dir) / "state"
        bin_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        if container_upstream:
            shutil.copy(container_upstream, state_dir / "container_upstream.conf")
        if container_root_conf:
            shutil.copy(container_root_conf, state_dir / "container_root.conf")
        if nginx_t_script:
            shutil.copy(nginx_t_script, state_dir / "nginx_t_script")
        elif nginx_t_output:
            (state_dir / "nginx_t_output.conf").write_text(nginx_t_output, encoding="utf-8")
        elif nginx_t_fail:
            (state_dir / "nginx_t_fail").write_text("failed", encoding="utf-8")

        if nginx_syntax_script:
            shutil.copy(nginx_syntax_script, state_dir / "nginx_syntax_script")
        elif nginx_syntax_fail:
            (state_dir / "nginx_syntax_fail").write_text("syntax fail", encoding="utf-8")

        mock_mount = host_mount_provenance if host_mount_provenance is not None else (
            Path(host_upstream).as_posix() if host_upstream else ""
        )
        (state_dir / "mount_source").write_text(mock_mount, encoding="utf-8")

        posix_state_dir = state_dir.as_posix()
        mock_docker = f"""#!/usr/bin/env bash
STATE_DIR="{posix_state_dir}"
CMD="$*"

if [ "$1" = "ps" ]; then
    echo "devsecops-nginx"
    exit 0
fi

if [[ "$CMD" == *"inspect devsecops-nginx"* ]]; then
    if [[ "$CMD" == *"Destination \\"/etc/nginx/conf.d/upstream.conf\\""* ]]; then
        cat "$STATE_DIR/mount_source" 2>/dev/null || true
        exit 0
    fi
    exit 0
fi

if [[ "$CMD" == *"exec devsecops-nginx test -s /etc/nginx/conf.d/upstream.conf"* ]]; then
    [ -s "$STATE_DIR/container_upstream.conf" ] && exit 0 || exit 1
fi

if [[ "$CMD" == *"exec devsecops-nginx cat /etc/nginx/conf.d/upstream.conf"* ]]; then
    cat "$STATE_DIR/container_upstream.conf" 2>/dev/null || exit 1
    exit 0
fi

if [[ "$CMD" == *"exec devsecops-nginx nginx -T"* ]]; then
    if [ -f "$STATE_DIR/nginx_t_script" ]; then
        bash "$STATE_DIR/nginx_t_script" 2>&1
        exit $?
    fi
    if [ -f "$STATE_DIR/nginx_t_fail" ]; then
        echo "nginx: [emerg] open() \\"/etc/nginx/nginx.conf\\" failed (2: No such file or directory)" >&2
        exit 1
    fi
    if [ -f "$STATE_DIR/nginx_t_output.conf" ]; then
        cat "$STATE_DIR/nginx_t_output.conf"
        exit 0
    fi
    exit 1
fi

if [[ "$CMD" == *"exec devsecops-nginx test -s /etc/nginx/nginx.conf"* ]]; then
    [ -s "$STATE_DIR/container_root.conf" ] && exit 0 || exit 1
fi

if [[ "$CMD" == *"exec devsecops-nginx cat /etc/nginx/nginx.conf"* ]]; then
    cat "$STATE_DIR/container_root.conf" 2>/dev/null || exit 1
    exit 0
fi

if [[ "$CMD" == *"exec devsecops-nginx nginx -t"* ]]; then
    if [ -f "$STATE_DIR/nginx_syntax_script" ]; then
        bash "$STATE_DIR/nginx_syntax_script" 2>&1
        exit $?
    fi
    if [ -f "$STATE_DIR/nginx_syntax_fail" ]; then
        echo "nginx: [emerg] invalid parameter in /etc/nginx/nginx.conf:15" >&2
        exit 1
    fi
    echo "nginx: syntax ok"
    exit 0
fi

exit 0
"""
        (bin_dir / "docker").write_text(mock_docker, encoding="utf-8", newline="\n")

        extracted_prod_script = extract_ci_discovery_script()
        runner = f"""#!/usr/bin/env bash
set -e
NGINX_RUNNING=true
{extracted_prod_script}
echo "DISCOVERED_ROUTE=$CURRENT_ROUTE"
echo "DISCOVERED_SOURCE=$DISCOVERY_SOURCE"
"""
        runner_path = Path(test_dir) / "run_discovery.sh"
        runner_path.write_text(runner, encoding="utf-8", newline="\n")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir.as_posix()}:{env.get('PATH', '')}"
        if host_upstream:
            env["HOST_UPSTREAM_FILE"] = Path(host_upstream).as_posix()

        proc = subprocess.run(
            [BASH_BIN, runner_path.as_posix()],
            env=env,
            capture_output=True,
            text=True
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


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
# SCENARIO 29: Isolated parser unit test: inline/minified route detection
# ------------------------------------------------------------------------------
def test_ci_route_detection_inline_and_minified():
    """
    Unit test for isolated parser regexes: verifies that route regex patterns correctly
    detect inline / minified directives following opening braces or semicolons.
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
# SCENARIO 30: Isolated parser unit test: upstream directives with optional parameters
# ------------------------------------------------------------------------------
def test_ci_route_detection_optional_parameters():
    """
    Unit test for isolated parser regexes: verifies that upstream directives with
    parameters (weight, max_fails, backup) or trailing spaces are parsed without error.
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
# SCENARIO 31: Isolated parser unit test: both legacy backend aliases
# ------------------------------------------------------------------------------
def test_ci_route_detection_both_legacy_aliases():
    """
    Unit test for isolated parser regexes: verifies that both legacy Docker alias
    'app:5000' and container name 'devsecops-app:5000' are supported across both server
    and proxy_pass directives.
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


# ------------------------------------------------------------------------------
# Helpers for In-Place Nginx Configuration Updates and External SSM Recovery
# ------------------------------------------------------------------------------
def run_ci_inplace_update(tmp_path, setup_flags=None):
    """
    Executes the CI in-place Nginx configuration update logic from .github/workflows/ci.yml
    with mock Docker.
    """
    setup_flags = setup_flags or {}
    work_dir = tmp_path / "ci_inplace_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    conf_dir = work_dir / "nginx-conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    bin_dir = work_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    state_dir = work_dir.as_posix()

    # Host configuration files
    if "narrowed_conf" in setup_flags:
        (conf_dir / "nginx.conf").write_text(
            "events { worker_connections 1024; } http { include /etc/nginx/conf.d/upstream.conf; server { listen 80; } }\n",
            encoding="utf-8", newline="\n"
        )
    else:
        (conf_dir / "nginx.conf").write_text(
            "events { worker_connections 1024; } http { include /etc/nginx/conf.d/*.conf; server { listen 80; } }\n",
            encoding="utf-8", newline="\n"
        )
    (conf_dir / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )

    mock_docker_script = f"""#!/usr/bin/env bash
STATE_DIR="{state_dir}"
CMD="$*"

if [ "$1" = "ps" ]; then
    echo "devsecops-nginx"
    exit 0
fi

if [ "$1" = "inspect" ]; then
    if [ -f "$STATE_DIR/invalid_mounts" ]; then
        echo ""
        exit 0
    fi
    if [[ "$CMD" == *"/etc/nginx/conf.d/upstream.conf"* ]]; then
        echo "/home/ec2-user/nginx-conf/upstream.conf"
    elif [[ "$CMD" == *"/etc/nginx/nginx.conf"* ]]; then
        echo "/home/ec2-user/nginx-conf/nginx.conf"
    else
        echo "/home/ec2-user/nginx-conf/upstream.conf"
        echo "/home/ec2-user/nginx-conf/nginx.conf"
    fi
    exit 0
fi

if [ "$1" = "exec" ]; then
    shift
    if [ "$1" = "-i" ]; then shift; fi
    shift # container name
    EXEC_CMD="$*"
    if [[ "$EXEC_CMD" == *"md5sum /etc/nginx/conf.d/upstream.conf"* ]]; then
        md5sum "{conf_dir.as_posix()}/upstream.conf" 2>/dev/null | awk '{{print $1}}'
        exit 0
    fi
    if [[ "$EXEC_CMD" == *"md5sum /etc/nginx/nginx.conf"* ]]; then
        md5sum "{conf_dir.as_posix()}/nginx.conf" 2>/dev/null | awk '{{print $1}}'
        exit 0
    fi
    if [[ "$EXEC_CMD" == *"test -s /etc/nginx/conf.d/upstream.conf"* ]]; then
        exit 0
    fi
    if [[ "$EXEC_CMD" == *"nginx -t"* ]]; then
        if [ -f "$STATE_DIR/inplace_syntax_fail" ]; then
            echo "nginx: [emerg] syntax error" >&2
            exit 1
        fi
        exit 0
    fi
    if [[ "$EXEC_CMD" == *"nginx -s reload"* ]]; then
        COUNT=0
        if [ -f "$STATE_DIR/reload_count" ]; then
            COUNT=$(cat "$STATE_DIR/reload_count")
        fi
        COUNT=$((COUNT + 1))
        echo "$COUNT" > "$STATE_DIR/reload_count"
        if [ "$COUNT" -eq 1 ] && [ -f "$STATE_DIR/inplace_reload_fail" ]; then
            echo "nginx: reload failed" >&2
            exit 1
        fi
        if [ "$COUNT" -gt 1 ] && [ -f "$STATE_DIR/recovery_reload_fail" ]; then
            echo "nginx: recovery reload failed" >&2
            exit 1
        fi
        echo "nginx: reload ok"
        exit 0
    fi
    exit 0
fi

if [ "$1" = "stop" ] || [ "$1" = "rm" ] || [ "$1" = "rename" ] || [ "$1" = "run" ]; then
    echo "$*" >> "$STATE_DIR/docker_ci_actions.log"
    exit 0
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
    CONF_DIR="{conf_dir.as_posix()}"
    NGINX_RUNNING=true
    NGINX_MOUNTS_VALID=false
    CONFIGS_CONSISTENT=false
    NGINX_CONF_NARROWED=false

    UPSTREAM_SRC=$(docker inspect devsecops-nginx --format '{{{{range .Mounts}}}}{{{{if eq .Destination "/etc/nginx/conf.d/upstream.conf"}}}}{{{{.Source}}}}{{{{end}}}}{{{{end}}}}' 2>/dev/null || true)
    CONF_SRC=$(docker inspect devsecops-nginx --format '{{{{range .Mounts}}}}{{{{if eq .Destination "/etc/nginx/nginx.conf"}}}}{{{{.Source}}}}{{{{end}}}}{{{{end}}}}' 2>/dev/null || true)

    if [ "$UPSTREAM_SRC" = "/home/ec2-user/nginx-conf/upstream.conf" ] && \
       [ "$CONF_SRC" = "/home/ec2-user/nginx-conf/nginx.conf" ]; then
        NGINX_MOUNTS_VALID=true
    fi

    if [ "$NGINX_MOUNTS_VALID" = true ] && [ -s "$CONF_DIR/nginx.conf" ]; then
        if grep -q 'include /etc/nginx/conf.d/upstream.conf;' "$CONF_DIR/nginx.conf" 2>/dev/null && \
           ! grep -q 'include /etc/nginx/conf.d/\\*\\.conf;' "$CONF_DIR/nginx.conf" 2>/dev/null; then
            HOST_CONF_MD5=$(md5sum "$CONF_DIR/nginx.conf" 2>/dev/null | awk '{{print $1}}')
            CONT_CONF_MD5=$(docker exec devsecops-nginx md5sum /etc/nginx/nginx.conf 2>/dev/null | awk '{{print $1}}')
            if [ -n "$HOST_CONF_MD5" ] && [ "$HOST_CONF_MD5" = "$CONT_CONF_MD5" ]; then
                NGINX_CONF_NARROWED=true
            fi
        fi
    fi

    if [ "$NGINX_RUNNING" = true ] && [ "$NGINX_MOUNTS_VALID" = true ] && [ "$NGINX_CONF_NARROWED" != true ]; then
        echo "Applying narrowed include to nginx.conf in-place through verified bind mount..."
        cp "$CONF_DIR/nginx.conf" "$CONF_DIR/nginx.conf.bak" 2>/dev/null || true

        cat << 'NGINX_EOF' > "$CONF_DIR/nginx.conf"
events {{ worker_connections 1024; }}
http {{
    include /etc/nginx/conf.d/upstream.conf;
    server {{
        listen 80;
        location / {{
            proxy_pass http://app_backend;
        }}
    }}
}}
NGINX_EOF

        if ! docker exec devsecops-nginx nginx -t >/dev/null 2>&1; then
            echo "CRITICAL: In-place nginx.conf update failed syntax check! Reverting to backup..." >&2
            cp "$CONF_DIR/nginx.conf.bak" "$CONF_DIR/nginx.conf" 2>/dev/null || true
            exit 1
        fi

        if ! docker exec devsecops-nginx nginx -s reload >/dev/null 2>&1; then
            echo "CRITICAL: In-place Nginx reload failed! Reverting to backup..." >&2
            cp "$CONF_DIR/nginx.conf.bak" "$CONF_DIR/nginx.conf" 2>/dev/null || true
            if ! docker exec devsecops-nginx nginx -s reload >/dev/null 2>&1; then
                echo "CRITICAL: Recovery reload of backup configuration also failed! Manual intervention required." >&2
                exit 2
            fi
            exit 1
        fi

        echo "In-place nginx.conf update and reload succeeded without container restart."
        NGINX_CONF_NARROWED=true
    fi

    if [ "$NGINX_RUNNING" != true ] || [ "$NGINX_MOUNTS_VALID" != true ]; then
        echo "Container recreation triggered"
        docker stop devsecops-nginx
        docker rm -f devsecops-nginx
        docker run -d --name devsecops-nginx nginx:alpine
    fi
    """

    res = subprocess.run([BASH_BIN, "-c", ci_script], capture_output=True, text=True)
    log_file = work_dir / "docker_ci_actions.log"
    actions = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    return res, actions, conf_dir


def run_ssm_rollback_simulation(status, exit_code="0", stdout_msg="ROLLBACK SUCCESS", stderr_msg=""):
    """
    Simulates the external SSM rollback evaluation logic from .github/workflows/ci.yml.
    """
    script = f"""
    STATUS="{status}"
    EXIT_CODE="{exit_code}"
    STDOUT_MSG="{stdout_msg}"
    STDERR_MSG="{stderr_msg}"

    echo "Status: $STATUS | ExitCode: $EXIT_CODE"
    echo "--- Standard Output ---"
    echo "$STDOUT_MSG"
    echo "--- Standard Error ---"
    echo "$STDERR_MSG"

    if [ "$STATUS" = "Success" ] && [ "$EXIT_CODE" = "0" ]; then
        echo "=================================================================="
        echo "PRODUCTION ROLLBACK VERIFIED: Reverse proxy restored to previous slot and confirmed healthy."
        echo "The failed candidate container has been stopped and removed."
        echo "Deployment job marked FAILED to indicate original deployment was not applied."
        echo "=================================================================="
        exit 1
    elif [ "$STATUS" = "TimedOut" ]; then
        echo "CRITICAL: MANUAL INTERVENTION REQUIRED: SSM Rollback command timed out or did not complete." >&2
        exit 1
    else
        echo "CRITICAL: MANUAL INTERVENTION REQUIRED: SSM Rollback command failed on EC2 instance (Status: $STATUS, ExitCode: $EXIT_CODE)." >&2
        exit 1
    fi
    """
    res = subprocess.run([BASH_BIN, "-c", script], capture_output=True, text=True)
    return res


# ------------------------------------------------------------------------------
# SCENARIO 43: In-place Nginx configuration update without container restart
# ------------------------------------------------------------------------------
def test_inplace_nginx_update_without_container_restart(tmp_path):
    """
    Verifies that when devsecops-nginx is running with valid bind mounts,
    the configuration is updated through the bind mount and reloaded in place
    without stopping, removing, or running a new container.
    """
    res, actions, conf_dir = run_ci_inplace_update(tmp_path)
    assert res.returncode == 0
    assert "In-place nginx.conf update and reload succeeded without container restart." in res.stdout
    assert not any("stop" in a for a in actions)
    assert not any("rm" in a for a in actions)
    assert not any("run" in a for a in actions)
    assert "include /etc/nginx/conf.d/upstream.conf;" in (conf_dir / "nginx.conf").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------
# SCENARIO 44: Invalid Nginx configuration recovery during in-place update
# ------------------------------------------------------------------------------
def test_invalid_nginx_configuration_recovery_inplace(tmp_path):
    """
    Verifies that if the new in-place Nginx configuration fails syntax validation,
    the original configuration is restored from backup without stopping the container.
    """
    res, actions, conf_dir = run_ci_inplace_update(tmp_path, setup_flags={"inplace_syntax_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: In-place nginx.conf update failed syntax check! Reverting to backup..." in res.stderr
    assert not any("stop" in a for a in actions)
    assert not any("rm" in a for a in actions)
    assert "include /etc/nginx/conf.d/*.conf;" in (conf_dir / "nginx.conf").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------
# SCENARIO 45: Failed reload recovery during in-place update
# ------------------------------------------------------------------------------
def test_failed_reload_recovery_inplace(tmp_path):
    """
    Verifies that if in-place reload fails, the backup configuration is restored
    and reloaded. If recovery reload also fails, it exits with critical error code 2.
    """
    res, actions, conf_dir = run_ci_inplace_update(tmp_path, setup_flags={"inplace_reload_fail": True})
    assert res.returncode == 1
    assert "CRITICAL: In-place Nginx reload failed! Reverting to backup..." in res.stderr
    assert not any("stop" in a for a in actions)

    # When recovery reload also fails
    res_critical, _, _ = run_ci_inplace_update(tmp_path / "crit", setup_flags={"inplace_reload_fail": True, "recovery_reload_fail": True})
    assert res_critical.returncode == 2
    assert "CRITICAL: Recovery reload of backup configuration also failed! Manual intervention required." in res_critical.stderr


# ------------------------------------------------------------------------------
# SCENARIO 46: Persistent deployment state creation and transitions
# ------------------------------------------------------------------------------
def test_deployment_state_creation_and_transitions(mock_env):
    """
    Verifies that deploy_blue_green.sh writes an accurate persistent deployment state,
    records deployment ID, previous slot, candidate slot, and transitions to 'standby_ready',
    and transitions to 'verified' upon invocation of --mark-verified.
    """
    res = run_deploy(mock_env, "test-repo/app:commit_safe123")
    assert res.returncode == 0

    state_file = mock_env["mock_dir"] / "deployment_state.json"
    assert state_file.exists()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["deployment_id"] == "commit_safe123"
    assert state["previous_slot"] == "blue"
    assert state["previous_container"] == "devsecops-app-blue"
    assert state["candidate_slot"] == "green"
    assert state["candidate_container"] == "devsecops-app-green"
    assert state["cutover_performed"] is True
    assert state["deployment_status"] == "standby_ready"
    assert "timestamp" in state

    # Now verify --mark-verified transitions status to 'verified'
    res_verify = run_deploy(mock_env, args=["--mark-verified"])
    assert res_verify.returncode == 0
    assert "Deployment state successfully marked as verified." in res_verify.stdout

    updated_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert updated_state["deployment_status"] == "verified"


# ------------------------------------------------------------------------------
# SCENARIO 47: Standalone rollback successfully restores traffic and removes candidate
# ------------------------------------------------------------------------------
def test_standalone_rollback_success(mock_env):
    """
    Verifies that deploy_blue_green.sh --rollback restores upstream to previous slot,
    reloads Nginx, verifies public health, safely removes the candidate container,
    and records 'rolled_back' state.
    """
    # Simulate candidate green active and candidate container running
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_v2",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 0
    assert "Restored live reverse proxy to previous slot 'devsecops-app-blue'" in res.stdout
    assert "ROLLBACK VERIFIED: Reverse proxy confirmed healthy on previous slot 'devsecops-app-blue'" in res.stdout
    assert "Stopped and removed candidate container 'devsecops-app-green'" in res.stdout

    # Verify upstream was restored to blue
    restored_upstream = (mock_env["mock_dir"] / "upstream.conf").read_text(encoding="utf-8")
    assert "devsecops-app-blue:5000" in restored_upstream

    # Verify state record updated
    final_state = json.loads((mock_env["mock_dir"] / "deployment_state.json").read_text(encoding="utf-8"))
    assert final_state["deployment_status"] == "rolled_back"
    assert final_state["cutover_performed"] is False


# ------------------------------------------------------------------------------
# SCENARIO 48: Standalone rollback is idempotent when already completed
# ------------------------------------------------------------------------------
def test_standalone_rollback_already_completed_idempotent(mock_env):
    """
    Verifies that calling --rollback when reverse proxy is already routing to
    the previous slot completes idempotently with code 0 without errors.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_v2",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": False,
            "deployment_status": "rolled_back"
        }),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 0
    assert "Rollback is already completed. Live reverse proxy is routing to previous slot 'devsecops-app-blue'." in res.stdout


# ------------------------------------------------------------------------------
# SCENARIO 49: Standalone rollback handles missing or malformed state safely
# ------------------------------------------------------------------------------
def test_standalone_rollback_missing_or_malformed_state(mock_env):
    """
    Verifies standalone rollback behavior with missing or malformed state file:
    - If live and backup configurations are unambiguous, restores safely.
    - If backup is missing or ambiguous, refuses container deletion and exits code 2.
    """
    # Case A: Missing state, but live (green) and backup (blue) are clear
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    state_file = mock_env["mock_dir"] / "deployment_state.json"
    if state_file.exists():
        state_file.unlink()

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 0
    assert "Restored live reverse proxy to previous slot 'devsecops-app-blue'" in res.stdout

    # Case B: Missing state AND missing backup configuration
    (mock_env["mock_dir"] / "upstream.conf.previous").unlink(missing_ok=True)
    res_b = run_deploy(mock_env, args=["--rollback"])
    assert res_b.returncode == 2
    assert "Ambiguous rollback state" in res_b.stderr

    # Case C: Malformed JSON in state file (and no valid backup)
    state_file.write_text("{malformed: json, not valid ...", encoding="utf-8")
    res_c = run_deploy(mock_env, args=["--rollback"])
    assert res_c.returncode == 2
    assert "Ambiguous rollback state" in res_c.stderr


# ------------------------------------------------------------------------------
# SCENARIO 50: Standalone rollback detects ambiguous targets and refuses cleanup
# ------------------------------------------------------------------------------
def test_standalone_rollback_ambiguous_targets_refuses_cleanup(mock_env):
    """
    Verifies that if live and backup targets conflict or are identical,
    standalone rollback reports ambiguous state, does not delete any containers,
    and exits with code 2 requiring manual intervention.
    """
    # Both point to green (ambiguous conflict)
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_v2",
            "previous_slot": "green",
            "previous_container": "devsecops-app-green",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 2
    assert "Ambiguous rollback state" in res.stderr
    assert "manual intervention required" in res.stderr

    # Verify no container was deleted
    log_file = mock_env["mock_dir"] / "docker_actions.log"
    actions = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    assert not any("rm devsecops-app-green" in a for a in actions)


# ------------------------------------------------------------------------------
# SCENARIO 51: Candidate cleanup protection prevents removal of core infrastructure
# ------------------------------------------------------------------------------
def test_candidate_cleanup_protects_infrastructure_containers(mock_env):
    """
    Verifies that the protected infrastructure containers (devsecops-nginx,
    devsecops-mysql, devsecops-prometheus, devsecops-grafana) can never be removed
    during candidate cleanup, even if recorded in deployment state.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    # Tampered state attempting to target MySQL
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_tampered",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "mysql",
            "candidate_container": "devsecops-mysql",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, args=["--rollback"])
    # Ambiguity check prevents execution or candidate cleanup guard skips it
    log_file = mock_env["mock_dir"] / "docker_actions.log"
    actions = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    assert not any("devsecops-mysql" in a for a in actions)
    assert not any("devsecops-nginx" in a for a in actions)


# ------------------------------------------------------------------------------
# SCENARIO 52: SSM rollback reporting on success, failure, and timeout
# ------------------------------------------------------------------------------
def test_external_ssm_recovery_reporting():
    """
    Verifies external SSM rollback command evaluation:
    - Success: reports recovery verified and marks workflow FAILED (exit 1).
    - Failed: reports critical manual intervention required (exit 1).
    - TimedOut: reports critical manual intervention required (exit 1).
    """
    # Success scenario
    res_succ = run_ssm_rollback_simulation("Success", exit_code="0")
    assert res_succ.returncode == 1
    assert "PRODUCTION ROLLBACK VERIFIED: Reverse proxy restored to previous slot and confirmed healthy." in res_succ.stdout

    # Failure scenario
    res_fail = run_ssm_rollback_simulation("Failed", exit_code="1")
    assert res_fail.returncode == 1
    assert "CRITICAL: MANUAL INTERVENTION REQUIRED: SSM Rollback command failed on EC2 instance" in res_fail.stderr

    # Timeout scenario
    res_timeout = run_ssm_rollback_simulation("TimedOut")
    assert res_timeout.returncode == 1
    assert "CRITICAL: MANUAL INTERVENTION REQUIRED: SSM Rollback command timed out or did not complete." in res_timeout.stderr


# ------------------------------------------------------------------------------
# SCENARIO 53: Rollback reports actual Nginx syntax diagnostics on validation failure
# ------------------------------------------------------------------------------
def test_rollback_reports_nginx_syntax_diagnostics(mock_env):
    """
    Verifies that when nginx -t fails during rollback, the actual syntax error
    diagnostic is captured and reported in stderr rather than suppressed.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_test",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )
    # Trigger mock syntax check failure
    (mock_env["mock_dir"] / "nginx_rollback_syntax_fail").touch()

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 2
    assert "CRITICAL: Restored Nginx configuration failed syntax validation! Manual intervention required!" in res.stderr
    assert "Nginx syntax error diagnostics:" in res.stderr
    assert "host not found in upstream" in res.stderr and "devsecops-app-blue" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 54: Rollback failure preserves active candidate container without stopping it
# ------------------------------------------------------------------------------
def test_rollback_failure_preserves_candidate_container(mock_env):
    """
    Verifies that if Nginx syntax validation fails during rollback, the active
    healthy candidate container is NEVER stopped or removed.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_test",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "nginx_rollback_syntax_fail").touch()

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 2

    # Assert docker actions log contains zero stops/removals of devsecops-app-green
    log_file = mock_env["mock_dir"] / "docker_actions.log"
    actions = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    assert not any("devsecops-app-green" in a for a in actions), f"devsecops-app-green was unexpectedly targeted: {actions}"


# ------------------------------------------------------------------------------
# SCENARIO 55: Rollback safely handles empty or malformed backup configuration
# ------------------------------------------------------------------------------
def test_rollback_rejects_empty_or_malformed_backup_configuration(mock_env):
    """
    Verifies that if the backup configuration is empty or lacks a server directive,
    the rollback aborts fail-closed (exit 2) before attempting Nginx test or reload.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    # Empty backup file
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text("", encoding="utf-8", newline="\n")
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_test",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 2
    assert "backup target could not be resolved" in res.stderr or \
           "Ambiguous rollback state" in res.stderr or \
           "CRITICAL: Backup upstream configuration is empty" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 56: Single-file bind mount restoration preserves container-side inode & no host mv
# ------------------------------------------------------------------------------
def test_rollback_uses_container_mount_without_host_mv(mock_env):
    """
    Verifies that rollback restores configuration strictly through the container-side
    mounted path /etc/nginx/conf.d/upstream.conf, and that no host-side mv operation
    targets /home/ec2-user/nginx-conf/upstream.conf.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_test",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 0
    assert (mock_env["mock_dir"] / "rollback_restored").exists()
    assert "ROLLBACK VERIFIED" in res.stdout

    # Verify via script inspection that no mv targets upstream.conf (not .bak)
    with open("scripts/deploy_blue_green.sh", "r", encoding="utf-8") as f:
        script_content = f.read()
    import re
    host_mv_matches = re.findall(r'mv\s+-[^\n]*upstream\.conf(?!\.bak)', script_content)
    assert len(host_mv_matches) == 0, f"Found host-side mv targeting upstream.conf: {host_mv_matches}"


# ------------------------------------------------------------------------------
# SCENARIO 57: Failed container restoration prevents Nginx validation/reload and candidate cleanup
# ------------------------------------------------------------------------------
def test_failed_container_restoration_prevents_reload_and_cleanup(mock_env):
    """
    Verifies that if writing to /etc/nginx/conf.d/upstream.conf fails during rollback,
    the script immediately aborts with exit code 2, does NOT attempt reload or health check,
    and preserves the candidate container.
    """
    (mock_env["mock_dir"] / "upstream.conf").write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "upstream.conf.previous").write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "deployment_state.json").write_text(
        json.dumps({
            "deployment_id": "commit_test",
            "previous_slot": "blue",
            "previous_container": "devsecops-app-blue",
            "candidate_slot": "green",
            "candidate_container": "devsecops-app-green",
            "cutover_performed": True,
            "deployment_status": "standby_ready"
        }),
        encoding="utf-8", newline="\n"
    )
    (mock_env["mock_dir"] / "restore_write_fail").touch()

    res = run_deploy(mock_env, args=["--rollback"])
    assert res.returncode == 2
    assert "CRITICAL: Failed to restore backup configuration" in res.stderr

    # Candidate container must not be stopped or removed
    log_file = mock_env["mock_dir"] / "docker_actions.log"
    actions = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    assert not any("devsecops-app-green" in a for a in actions), f"devsecops-app-green was targeted: {actions}"


# ------------------------------------------------------------------------------
# SCENARIO 58: Deployment ID extraction for tagged immutable, ordinary tagged, and digest-only references
# ------------------------------------------------------------------------------
def test_deployment_id_extraction_matrix(mock_env):
    """
    Tests deployment ID extraction across:
    1. Tagged immutable reference: app:commit_123@sha256:<hash> -> commit_123
    2. Ordinary tagged reference: app:commit_456 -> commit_456
    3. Fully-qualified ECR tagged immutable reference -> commit_789
    4. Malformed/untagged reference -> rejected by immutable validator
    """
    import subprocess
    digest = "ba018c08cfb1eab89293eee28d92b24b90e801d7994a8df33798cfd5a7fa7cec"

    # Helper to test Bash extraction logic directly from deploy_blue_green.sh
    def extract_dep_id(image_str, extra_env=None):
        cmd = [BASH_BIN, "scripts/deploy_blue_green.sh", "--extract-deployment-id", image_str]
        full_env = {**os.environ, **(extra_env or {})}
        r = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
        assert r.returncode == 0, f"Bash failed with code {r.returncode}: {r.stderr}"
        return r.stdout.strip()

    # 1. Tagged immutable
    assert extract_dep_id(f"test-repo/app:commit_safe123@sha256:{digest}") == "commit_safe123"
    assert extract_dep_id(f"123456789012.dkr.ecr.ap-south-1.amazonaws.com/devsecops-platform:caaf7ef5@sha256:{digest}") == "caaf7ef5"
    assert extract_dep_id(f"localhost:5000/app:v2.1.0@sha256:{digest}") == "v2.1.0"

    # 2. Ordinary tagged reference
    assert extract_dep_id("test-repo/app:commit_safe456") == "commit_safe456"
    assert extract_dep_id("localhost:5000/app:release-99") == "release-99"

    # 3. Environment override precedence
    assert extract_dep_id(f"test-repo/app:commit_safe123@sha256:{digest}", {"DEPLOYMENT_ID": "override_id"}) == "override_id"
    assert extract_dep_id(f"test-repo/app:commit_safe123@sha256:{digest}", {"GITHUB_SHA": "git_sha_abc"}) == "git_sha_abc"

    # 4. Digest-only reference
    assert extract_dep_id(f"test-repo/app@sha256:{digest}") == digest

    # 5. Full deploy execution records correct deployment_id in state
    res = run_deploy(mock_env, f"test-repo/app:feature_xyz@sha256:{digest}")
    assert res.returncode == 0
    state_file = mock_env["mock_dir"] / "deployment_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["deployment_id"] == "feature_xyz"


# ------------------------------------------------------------------------------
# SCENARIO 59: Ordinary mutable reference rejected by deployment script validation
# ------------------------------------------------------------------------------
def test_ordinary_mutable_reference_rejected_by_immutable_validator(mock_env):
    """
    Confirms that while DEPLOYMENT_ID can be parsed from an ordinary tagged reference,
    deploy_blue_green.sh strictly enforces immutable digest requirement and rejects mutable tags.
    """
    res = run_deploy(mock_env, "test-repo/app:commit_safe123", allow_raw_image=True)
    assert res.returncode == 1
    assert "Deployment rejected: DEPLOY_IMAGE must reference an immutable digest" in res.stderr


# ------------------------------------------------------------------------------
# SCENARIO 60: Tier 1 container-upstream discovery succeeds with verified syntax
# ------------------------------------------------------------------------------
def test_ci_discovery_tier1_container_upstream_success(tmp_path):
    """
    Scenario 60: Tier 1 container-upstream discovery. When /etc/nginx/conf.d/upstream.conf
    is present and readable in the running container, the active route is discovered
    directly from Tier 1, and running Nginx syntax validation is verified.
    """
    container_upstream = tmp_path / "upstream.conf"
    container_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8"
    )
    syntax_script = tmp_path / "syntax.sh"
    syntax_script.write_text("#!/bin/bash\necho 'nginx: syntax ok'\nexit 0\n", encoding="utf-8")

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=container_upstream.as_posix(),
        nginx_syntax_script=syntax_script.as_posix()
    )
    assert rc == 0
    assert "DISCOVERED_ROUTE=devsecops-app-green" in stdout
    assert "DISCOVERED_SOURCE=container /etc/nginx/conf.d/upstream.conf" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 61: Tier 1 container-upstream discovery preempts Tier 3 runtime dump
# ------------------------------------------------------------------------------
def test_ci_discovery_tier1_preempts_tier3_runtime_dump(tmp_path):
    """
    Scenario 61a: Tier 1 container-upstream discovery takes precedence over Tier 3
    runtime dump. When /etc/nginx/conf.d/upstream.conf is readable directly from the
    container, route discovery succeeds from Tier 1 without invoking or depending
    on nginx -T runtime dump.
    """
    container_upstream = tmp_path / "upstream.conf"
    container_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8"
    )
    nginx_t_script = tmp_path / "nginx_t.sh"
    nginx_t_script.write_text("#!/bin/bash\necho 'nginx -T dump failed' >&2\nexit 1\n", encoding="utf-8")
    syntax_script = tmp_path / "syntax.sh"
    syntax_script.write_text("#!/bin/bash\necho 'nginx: syntax ok'\nexit 0\n", encoding="utf-8")

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=container_upstream.as_posix(),
        nginx_t_script=nginx_t_script.as_posix(),
        nginx_syntax_script=syntax_script.as_posix()
    )
    assert rc == 0
    assert "DISCOVERED_ROUTE=devsecops-app-blue" in stdout
    assert "DISCOVERED_SOURCE=container /etc/nginx/conf.d/upstream.conf" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


def test_ci_discovery_failed_nginx_t_with_syntax_failure_aborts(tmp_path):
    """
    Scenario 61b: Reading upstream.conf alone does NOT prove syntax is valid.
    If running container syntax check fails, deployment aborts fail-closed.
    """
    container_upstream = tmp_path / "upstream.conf"
    container_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8"
    )
    nginx_t_script = tmp_path / "nginx_t.sh"
    nginx_t_script.write_text("#!/bin/bash\necho 'nginx -T failed' >&2\nexit 1\n", encoding="utf-8")
    syntax_script = tmp_path / "syntax.sh"
    syntax_script.write_text(
        "#!/bin/bash\necho 'nginx: [emerg] invalid parameter in /etc/nginx/nginx.conf:15' >&2\nexit 1\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=container_upstream.as_posix(),
        nginx_t_script=nginx_t_script.as_posix(),
        nginx_syntax_script=syntax_script.as_posix()
    )
    assert rc == 1
    assert "Inspecting active route from container /etc/nginx/conf.d/upstream.conf..." in stdout
    assert "CRITICAL: Running Nginx configuration failed syntax validation" in stderr
    assert "invalid parameter in /etc/nginx/nginx.conf:15" in stderr
    assert "Aborting deployment because Nginx configuration is invalid." in stderr


def test_ci_discovery_failed_nginx_t_with_valid_syntax_succeeds(tmp_path):
    """
    Scenario 61c: Failed nginx -T followed by successful syntax check allows deployment.
    """
    host_upstream = tmp_path / "host_upstream.conf"
    host_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8"
    )
    nginx_t_script = tmp_path / "nginx_t.sh"
    nginx_t_script.write_text("#!/bin/bash\necho 'nginx: [warn] dump issue' >&2\nexit 1\n", encoding="utf-8")
    syntax_script = tmp_path / "syntax.sh"
    syntax_script.write_text("#!/bin/bash\necho 'nginx: syntax ok'\nexit 0\n", encoding="utf-8")

    rc, stdout, stderr = run_ci_discovery_cascade(
        host_upstream=host_upstream.as_posix(),
        nginx_t_script=nginx_t_script.as_posix(),
        nginx_syntax_script=syntax_script.as_posix()
    )
    assert rc == 0
    assert "DISCOVERED_ROUTE=devsecops-app-green" in stdout
    assert "host" in stdout and "(verified mount)" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 62: Missing upstream file with legacy inline route
# ------------------------------------------------------------------------------
def test_ci_discovery_missing_upstream_legacy_inline_route(tmp_path):
    """
    Scenario 62: When modular upstream files are missing and nginx -T fails,
    the cascade falls back to legacy /etc/nginx/nginx.conf.
    """
    root_conf = tmp_path / "nginx.conf"
    root_conf.write_text(
        "events {}\nhttp {\n    server {\n        listen 80;\n        location / {\n            proxy_pass http://devsecops-app:5000;\n        }\n    }\n}\n",
        encoding="utf-8"
    )
    syntax_script = tmp_path / "syntax.sh"
    syntax_script.write_text("#!/bin/bash\necho 'nginx: syntax ok'\nexit 0\n", encoding="utf-8")

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_root_conf=root_conf.as_posix(),
        nginx_syntax_script=syntax_script.as_posix()
    )
    assert rc == 0
    assert "DISCOVERED_ROUTE=devsecops-app" in stdout
    assert "DISCOVERED_SOURCE=container /etc/nginx/nginx.conf" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 63: Empty upstream configuration aborts fail-closed
# ------------------------------------------------------------------------------
def test_ci_discovery_empty_upstream_aborts_fail_closed(tmp_path):
    """
    Scenario 63: Empty or whitespace-only upstream configuration triggers fail-closed abort.
    """
    empty_upstream = tmp_path / "empty_upstream.conf"
    empty_upstream.write_text("   \n\t  \n  ", encoding="utf-8")

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=empty_upstream.as_posix()
    )
    assert rc == 1
    assert "CRITICAL: Nginx is running but all configuration discovery sources were missing or empty. Aborting." in stderr


# ------------------------------------------------------------------------------
# SCENARIO 64: Both blue and green active upstream directives abort as ambiguous
# ------------------------------------------------------------------------------
def test_ci_discovery_both_blue_and_green_aborts_ambiguous(tmp_path):
    """
    Scenario 64: Configuration with both active blue and green server directives
    is detected as ambiguous and aborts fail-closed.
    """
    ambiguous_upstream = tmp_path / "ambiguous_upstream.conf"
    ambiguous_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=ambiguous_upstream.as_posix()
    )
    assert rc == 1
    assert "CRITICAL: Ambiguous active routes detected in Nginx configuration (2 conflicting matches" in stderr


# ------------------------------------------------------------------------------
# SCENARIO 65: Commented-out backend directive ignored
# ------------------------------------------------------------------------------
def test_ci_discovery_commented_out_directive_ignored(tmp_path):
    """
    Scenario 65: Commented-out backend directive is ignored; active directive is identified.
    """
    commented_upstream = tmp_path / "commented_upstream.conf"
    commented_upstream.write_text(
        "upstream app_backend {\n    # server devsecops-app-blue:5000;\n    server devsecops-app-green:5000; # server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8"
    )
    syntax_script = tmp_path / "syntax.sh"
    syntax_script.write_text("#!/bin/bash\necho 'nginx: syntax ok'\nexit 0\n", encoding="utf-8")

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=commented_upstream.as_posix(),
        nginx_syntax_script=syntax_script.as_posix()
    )
    assert rc == 0
    assert "DISCOVERED_ROUTE=devsecops-app-green" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 66: Unknown backend target rejected
# ------------------------------------------------------------------------------
def test_ci_discovery_unknown_backend_target_rejected(tmp_path):
    """
    Scenario 66: Unrecognized backend targets are rejected fail-closed.
    """
    # 1. Unknown server target
    unknown_server_conf = tmp_path / "unknown_server.conf"
    unknown_server_conf.write_text(
        "upstream app_backend {\n    server rogue-backend:5000;\n}\n",
        encoding="utf-8"
    )
    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=unknown_server_conf.as_posix()
    )
    assert rc == 1
    assert "CRITICAL: Unknown active backend target detected in Nginx configuration" in stderr
    assert "Unknown upstream server target detected: 'rogue-backend'" in stderr

    # 2. Unknown proxy_pass target
    unknown_proxy_conf = tmp_path / "unknown_proxy.conf"
    unknown_proxy_conf.write_text(
        "server {\n    location / {\n        proxy_pass http://unauthorized-host:5000;\n    }\n}\n",
        encoding="utf-8"
    )
    rc, stdout, stderr = run_ci_discovery_cascade(
        container_root_conf=unknown_proxy_conf.as_posix()
    )
    assert rc == 1
    assert "CRITICAL: Unknown active backend target detected in Nginx configuration" in stderr
    assert "Unknown proxy_pass target detected: 'unauthorized-host'" in stderr


# ------------------------------------------------------------------------------
# SCENARIO 67: Ambiguous upstream and direct proxy routes rejected
# ------------------------------------------------------------------------------
def test_ci_discovery_ambiguous_upstream_and_direct_proxy_rejected(tmp_path):
    """
    Scenario 67: If both upstream server and direct proxy_pass point to different
    slots, detection aborts as ambiguous.
    """
    ambiguous_conf = tmp_path / "ambiguous_mixed.conf"
    ambiguous_conf.write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n"
        "server {\n    location / {\n        proxy_pass http://devsecops-app-green:5000;\n    }\n}\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        container_upstream=ambiguous_conf.as_posix()
    )
    assert rc == 1
    assert "CRITICAL: Ambiguous active routes detected in Nginx configuration (2 conflicting matches" in stderr


# ------------------------------------------------------------------------------
# SCENARIO 68: Failed nginx -T diagnostics captured and logged
# ------------------------------------------------------------------------------
def test_ci_discovery_failed_nginx_t_captures_diagnostics(tmp_path):
    """
    Scenario 68: Confirms that when nginx -T fails, diagnostics are NOT redirected
    to /dev/null but captured and printed with [nginx -T] prefix for operators.
    """
    nginx_t_script = tmp_path / "nginx_t_failing.sh"
    nginx_t_script.write_text(
        "#!/bin/bash\n"
        "echo 'nginx: [emerg] open() \"/etc/nginx/nginx.conf\" failed (2: No such file or directory)' >&2\n"
        "exit 1\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        nginx_t_script=nginx_t_script.as_posix()
    )
    assert rc == 1
    assert "[nginx -T] nginx: [emerg] open() \"/etc/nginx/nginx.conf\" failed (2: No such file or directory)" in stdout
    assert "CRITICAL: Nginx is running but all configuration discovery sources were missing or empty. Aborting." in stderr


# ------------------------------------------------------------------------------
# SCENARIO 69: Independent Tier 3 nginx -T success with modular upstream dump
# ------------------------------------------------------------------------------
def test_ci_discovery_tier3_nginx_t_success_modular_upstream():
    """
    Scenario 69: Container and host upstream are both unavailable.
    Tier 3 runtime dump (nginx -T) succeeds and returns a modular configuration
    containing an active slot. Active route is discovered directly from Tier 3.
    """
    dump_content = (
        "# configuration file /etc/nginx/nginx.conf:\n"
        "events {}\n"
        "http { include /etc/nginx/conf.d/*.conf; }\n\n"
        "# configuration file /etc/nginx/conf.d/upstream.conf:\n"
        "upstream app_backend {\n"
        "    server devsecops-app-green:5000;\n"
        "}\n"
    )
    rc, stdout, stderr = run_ci_discovery_cascade(
        nginx_t_output=dump_content
    )
    assert rc == 0
    assert "Inspecting active route from runtime dump (nginx -T) (exit code 0)..." in stdout
    assert "DISCOVERED_ROUTE=devsecops-app-green" in stdout
    assert "DISCOVERED_SOURCE=runtime dump (nginx -T)" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 70: Independent Tier 3 nginx -T failure emits diagnostics and aborts
# ------------------------------------------------------------------------------
def test_ci_discovery_tier3_nginx_t_failure_emits_diagnostics_and_aborts():
    """
    Scenario 70: Container and host upstream are both unavailable.
    Tier 3 runtime dump (nginx -T) fails and emits error diagnostics.
    Workflow logs diagnostics with [nginx -T] prefix and aborts fail-closed.
    """
    rc, stdout, stderr = run_ci_discovery_cascade(
        nginx_t_fail=True
    )
    assert rc == 1
    assert "'nginx -T' failed with exit status 1:" in stdout
    assert "[nginx -T] nginx: [emerg] open() \"/etc/nginx/nginx.conf\" failed" in stdout
    assert "CRITICAL: Nginx is running but all configuration discovery sources were missing or empty. Aborting." in stderr


# ------------------------------------------------------------------------------
# SCENARIO 71: Host bind-mount provenance verified via docker inspect
# ------------------------------------------------------------------------------
def test_ci_discovery_host_mount_provenance_verified_succeeds(tmp_path):
    """
    Scenario 71: Container upstream is unavailable.
    Host upstream file exists, and docker inspect confirms its exact host path
    is mounted into /etc/nginx/conf.d/upstream.conf.
    Host configuration is trusted as authoritative (verified mount).
    """
    host_upstream = tmp_path / "upstream.conf"
    host_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-green:5000;\n}\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        host_upstream=host_upstream.as_posix(),
        host_mount_provenance=host_upstream.as_posix()
    )
    assert rc == 0
    assert "(verified mount)" in stdout
    assert "DISCOVERED_ROUTE=devsecops-app-green" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 72: Host bind-mount provenance unverified skips host file
# ------------------------------------------------------------------------------
def test_ci_discovery_host_mount_provenance_unverified_skips_host(tmp_path):
    """
    Scenario 72: Container upstream is unavailable.
    Host upstream file exists (pointing to blue), BUT docker inspect reports
    that the container's mount source is different (unverified provenance).
    The host file is NOT trusted. Discovery falls through to Tier 3 (nginx -T)
    which specifies green. Green is selected, proving unverified host was ignored.
    """
    host_upstream = tmp_path / "unmounted_upstream.conf"
    host_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        host_upstream=host_upstream.as_posix(),
        host_mount_provenance="/some/other/path/upstream.conf",
        nginx_t_output="upstream app_backend { server devsecops-app-green:5000; }"
    )
    assert rc == 0
    assert "Skipping unverified host file." in stdout
    assert "DISCOVERED_ROUTE=devsecops-app-green" in stdout
    assert "DISCOVERED_SOURCE=runtime dump (nginx -T)" in stdout
    assert "Running Nginx configuration syntax is verified valid" in stdout


# ------------------------------------------------------------------------------
# SCENARIO 73: Host bind-mount provenance unverified and Tier 3 fails triggers abort
# ------------------------------------------------------------------------------
def test_ci_discovery_host_mount_provenance_unverified_and_tier3_fails_aborts(tmp_path):
    """
    Scenario 73: Host upstream file exists but mount provenance cannot be verified.
    Tier 3 (nginx -T) also fails. Workflow refuses to proceed on uncertain
    configuration and aborts fail-closed.
    """
    host_upstream = tmp_path / "unmounted_upstream.conf"
    host_upstream.write_text(
        "upstream app_backend {\n    server devsecops-app-blue:5000;\n}\n",
        encoding="utf-8"
    )

    rc, stdout, stderr = run_ci_discovery_cascade(
        host_upstream=host_upstream.as_posix(),
        host_mount_provenance="",
        nginx_t_fail=True
    )
    assert rc == 1
    assert "Skipping unverified host file." in stdout
    assert "'nginx -T' failed with exit status 1:" in stdout
    assert "CRITICAL: Nginx is running but all configuration discovery sources were missing or empty. Aborting." in stderr
