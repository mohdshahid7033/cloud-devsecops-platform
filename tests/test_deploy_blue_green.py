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

    if [[ "$CMD" == *"test -f /etc/nginx/upstream.conf.previous"* ]]; then
        [ -f "$STATE_DIR/upstream.conf.previous" ] && exit 0 || exit 1
    fi

    if [[ "$CMD" == *"cp /etc/nginx/conf.d/upstream.conf /etc/nginx/upstream.conf.previous"* ]]; then
        cp "$STATE_DIR/upstream.conf" "$STATE_DIR/upstream.conf.previous" 2>/dev/null || true
        exit 0
    fi

    if [[ "$CMD" == *"cp /etc/nginx/upstream.conf.previous /etc/nginx/conf.d/upstream.conf"* ]]; then
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
