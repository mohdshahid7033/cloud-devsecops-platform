"""
Phase 1A: Hardened Isolated Blue-Green Deployment Prototype.

Demonstrates and verifies:
1. Guaranteed cleanup in a finally block on success, assertion failure, or interruption.
2. Bridge-network candidate health verification (reverse-proxy perspective via wget).
3. Safe Nginx validation in a temporary directory outside the wildcard include directory.
4. Continuous traffic assertions with per-slot request accounting (zero downtime proof).
5. Pre-switch candidate failure detection & traffic protection.
6. Post-switch crash simulation & automated rollback restoration.
7. Verification that production containers (port 80, 5000) remain 100% untouched.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TEST_PORT = 8088
NETWORK_NAME = "cloud-devsecops-platform_devsecops-network"
APP_IMAGE = "cloud-devsecops-platform-app:latest"


def run_cmd(cmd, input_text=None, capture=True):
    """Run a shell command safely without exposing sensitive data."""
    res = subprocess.run(
        cmd,
        shell=True,
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()


def get_db_password_from_env():
    """Extract DB credentials in-memory from running devsecops-app container."""
    code, stdout, _ = run_cmd('docker inspect devsecops-app --format "{{json .Config.Env}}"')
    if code != 0:
        raise RuntimeError("Failed to inspect devsecops-app to get DB credentials")
    env_list = json.loads(stdout)
    db_pass = ""
    for item in env_list:
        if item.startswith("DB_PASSWORD="):
            db_pass = item.split("=", 1)[1]
            break
    if not db_pass:
        raise RuntimeError("DB_PASSWORD not found in devsecops-app")
    return db_pass


def cleanup():
    """
    Clean up ONLY explicitly named prototype containers and temporary prototype files.
    Strictly avoids touching devsecops-* production containers.
    """
    print("--- Cleaning up prototype containers (proto-*) ---")
    try:
        run_cmd("docker stop proto-nginx proto-app-blue proto-app-green")
        run_cmd("docker rm -f proto-nginx proto-app-blue proto-app-green")
    except Exception as e:
        print(f"Notice during prototype cleanup: {e}", file=sys.stderr)


def wait_for_http(url, timeout_sec=20, expected_status=200, check_db=False):
    """Poll an endpoint until it responds with expected status."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == expected_status:
                    body = json.loads(resp.read().decode())
                    if check_db:
                        if body.get("database", {}).get("connected") is True:
                            return True, body
                    else:
                        return True, body
        except Exception:
            pass
        time.sleep(0.3)
    return False, None


def probe_candidate_from_reverse_proxy(candidate_host, timeout_sec=25):
    """
    Verify candidate health from the reverse proxy's perspective across the
    Docker bridge network (cloud-devsecops-platform_devsecops-network).
    Verifies DNS resolution, port routing, HTTP 200, and database connectivity.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        code, out, _ = run_cmd(
            f"docker exec proto-nginx wget -qO- --timeout=3 http://{candidate_host}:5000/health"
        )
        if code == 0 and out:
            try:
                data = json.loads(out)
                if data.get("status") == "healthy" and data.get("database", {}).get("connected") is True:
                    return True, data
            except json.JSONDecodeError:
                pass
        time.sleep(1)
    return False, None


def validate_candidate_nginx_config(candidate_upstream_content):
    """
    Safely validate candidate Nginx configuration outside of /etc/nginx/conf.d/.
    Prevents duplicate upstream definitions from being caught by wildcard includes.
    """
    # 1. Create an isolated scratch directory inside container
    run_cmd("docker exec proto-nginx rm -rf /tmp/nginx-validate")
    run_cmd("docker exec proto-nginx mkdir -p /tmp/nginx-validate/conf.d")

    # 2. Replicate config structure in /tmp/nginx-validate
    run_cmd("docker exec proto-nginx cp /etc/nginx/nginx.conf /tmp/nginx-validate/nginx.conf")
    run_cmd("docker exec proto-nginx cp /etc/nginx/conf.d/app.conf /tmp/nginx-validate/conf.d/app.conf")

    # 3. Write candidate upstream into validation directory
    run_cmd(
        'docker exec -i proto-nginx sh -c "cat > /tmp/nginx-validate/conf.d/upstream.conf"',
        input_text=candidate_upstream_content,
    )

    # 4. Point validation nginx.conf to the test conf.d directory
    run_cmd(
        'docker exec proto-nginx sed -i "s|/etc/nginx/conf.d/\\*.conf|/tmp/nginx-validate/conf.d/\\*.conf|g" /tmp/nginx-validate/nginx.conf'
    )

    # 5. Run nginx -t against the isolated candidate configuration
    code, out, err = run_cmd("docker exec proto-nginx nginx -t -c /tmp/nginx-validate/nginx.conf")

    # 6. Clean up temporary validation directory
    run_cmd("docker exec proto-nginx rm -rf /tmp/nginx-validate")

    return (code == 0), (out + " " + err).strip()


def run_prototype_suite():
    print("================================================================")
    print("STARTING HARDENED BLUE-GREEN DEPLOYMENT PROTOTYPE TEST (PHASE 1A)")
    print(f"Target Prototype Port: {TEST_PORT} (Production Port 80 Untouched)")
    print("================================================================")

    # Ensure clean state from any prior runs
    cleanup()

    db_password = get_db_password_from_env()

    # Base environment template with distinct APP_ENV tags to record serving slots
    env_blue = (
        f"-e FLASK_ENV=production -e APP_ENV=proto-blue -e DB_HOST=mysql "
        f"-e DB_PORT=3306 -e DB_NAME=devsecops_db -e DB_USER=devsecops_user "
        f"-e DB_PASSWORD={db_password}"
    )
    env_green = (
        f"-e FLASK_ENV=production -e APP_ENV=proto-green -e DB_HOST=mysql "
        f"-e DB_PORT=3306 -e DB_NAME=devsecops_db -e DB_USER=devsecops_user "
        f"-e DB_PASSWORD={db_password}"
    )

    # -------------------------------------------------------------------------
    # STEP 1: Launch proto-app-blue & proto-nginx
    # -------------------------------------------------------------------------
    print("\n[Step 1] Launching proto-app-blue (Initial Active Slot)...")
    code, _, err = run_cmd(
        f"docker run -d --name proto-app-blue --network {NETWORK_NAME} --restart always {env_blue} {APP_IMAGE}"
    )
    assert code == 0, f"Failed to start proto-app-blue: {err}"

    print("[Step 2] Launching proto-nginx reverse proxy on port 8088...")
    code, _, err = run_cmd(
        f"docker run -d --name proto-nginx --network {NETWORK_NAME} -p {TEST_PORT}:80 nginx:alpine"
    )
    assert code == 0, f"Failed to start proto-nginx: {err}"
    time.sleep(2)

    app_conf = (
        "server {\n"
        "    listen 80;\n"
        "    location / {\n"
        "        proxy_pass http://app_backend;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_connect_timeout 2s;\n"
        "        proxy_read_timeout 5s;\n"
        "    }\n"
        "}\n"
    )
    upstream_blue = "upstream app_backend {\n    server proto-app-blue:5000;\n}\n"

    # Remove default welcome conf and initialize our modular upstream and app blocks
    run_cmd("docker exec proto-nginx rm -f /etc/nginx/conf.d/default.conf")
    run_cmd("docker exec -i proto-nginx sh -c \"cat > /etc/nginx/conf.d/app.conf\"", input_text=app_conf)
    run_cmd("docker exec -i proto-nginx sh -c \"cat > /etc/nginx/conf.d/upstream.conf\"", input_text=upstream_blue)

    # Initial nginx -t and reload
    code, _, err = run_cmd("docker exec proto-nginx nginx -t")
    assert code == 0, f"Initial Nginx config syntax invalid: {err}"
    run_cmd("docker exec proto-nginx nginx -s reload")

    # Verify baseline health probe across bridge network
    ok, data = probe_candidate_from_reverse_proxy("proto-app-blue", timeout_sec=20)
    assert ok, "Reverse proxy failed to reach proto-app-blue across bridge network"
    print(f"  -> Verified proto-app-blue reachable from proto-nginx (mode: {data['database']['mode']}).")

    # Verify public prototype endpoint
    ok, data = wait_for_http(f"http://localhost:{TEST_PORT}/health", timeout_sec=10, check_db=True)
    assert ok and data.get("environment") == "proto-blue", "Prototype endpoint not serving proto-blue"
    print(f"  -> Prototype public endpoint verified: http://localhost:{TEST_PORT}/health serving '{data['environment']}'.")

    # -------------------------------------------------------------------------
    # STEP 3: SCENARIO 1 - Safe Zero-Downtime Deployment (Blue -> Green)
    # -------------------------------------------------------------------------
    print("\n[Step 3: SCENARIO 1] Executing Blue -> Green Zero-Downtime Traffic Switch...")

    traffic_active = True
    traffic_results = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "slots": {"proto-blue": 0, "proto-green": 0, "other": 0},
        "latencies": [],
    }

    def generate_traffic():
        while traffic_active:
            traffic_results["total"] += 1
            t0 = time.time()
            try:
                with urllib.request.urlopen(f"http://localhost:{TEST_PORT}/health", timeout=2) as r:
                    if r.status == 200:
                        traffic_results["success"] += 1
                        body = json.loads(r.read().decode())
                        env_slot = body.get("environment", "other")
                        if env_slot in traffic_results["slots"]:
                            traffic_results["slots"][env_slot] += 1
                        else:
                            traffic_results["slots"]["other"] += 1
                    else:
                        traffic_results["failed"] += 1
            except Exception:
                traffic_results["failed"] += 1
            traffic_results["latencies"].append(time.time() - t0)
            time.sleep(0.03)  # ~30 requests per second continuous traffic

    traffic_thread = threading.Thread(target=generate_traffic)
    traffic_thread.start()

    # 1. Start candidate slot
    print("  -> Starting candidate slot: proto-app-green...")
    code, _, err = run_cmd(
        f"docker run -d --name proto-app-green --network {NETWORK_NAME} --restart always {env_green} {APP_IMAGE}"
    )
    assert code == 0, f"Failed to start proto-app-green: {err}"

    # 2. Bridge-network pre-switch verification from reverse proxy
    print("  -> Pre-switch verification: probing proto-app-green from proto-nginx via bridge network...")
    green_ready, green_data = probe_candidate_from_reverse_proxy("proto-app-green", timeout_sec=25)
    assert green_ready, "Candidate proto-app-green failed bridge-network pre-switch verification"
    print(f"  -> Candidate verified healthy from proto-nginx (connected: {green_data['database']['connected']}).")

    # 3. Safe configuration validation outside wildcard include directory
    print("  -> Safely validating candidate Nginx configuration in isolated directory...")
    # First verify candidate validator reliably catches invalid syntax outside /etc/nginx/conf.d/
    bad_val_ok, _ = validate_candidate_nginx_config("upstream app_backend { server ; }")
    assert not bad_val_ok, "Validator failed to catch invalid candidate Nginx configuration syntax!"
    print("  -> Confirmed invalid candidate syntax is safely rejected.")

    upstream_green = "upstream app_backend {\n    server proto-app-green:5000;\n}\n"
    val_ok, val_msg = validate_candidate_nginx_config(upstream_green)
    assert val_ok, f"Candidate configuration validation failed: {val_msg}"
    print("  -> Candidate configuration validated successfully without duplicate upstream risk.")

    # 4. Save known-good upstream and execute atomic switch
    print("  -> Performing atomic traffic switch (nginx -s reload)...")
    run_cmd("docker exec proto-nginx cp /etc/nginx/conf.d/upstream.conf /etc/nginx/upstream.conf.previous")
    run_cmd(
        'docker exec -i proto-nginx sh -c "cat > /etc/nginx/conf.d/upstream.conf"',
        input_text=upstream_green,
    )
    code, _, err = run_cmd("docker exec proto-nginx nginx -s reload")
    if code != 0:
        # Emergency recovery if reload itself fails: restore, validate, reload, verify
        print(f"  -> Emergency recovery: reload failed ({err}), restoring known-good upstream...")
        run_cmd("docker exec proto-nginx cp /etc/nginx/upstream.conf.previous /etc/nginx/conf.d/upstream.conf")
        t_code, _, t_err = run_cmd("docker exec proto-nginx nginx -t")
        assert t_code == 0, f"Restored upstream failed validation: {t_err}"
        r_code, _, r_err = run_cmd("docker exec proto-nginx nginx -s reload")
        assert r_code == 0, f"Restored upstream failed reload: {r_err}"
        rec_ok, _ = wait_for_http(f"http://localhost:{TEST_PORT}/health", timeout_sec=5, check_db=True)
        assert rec_ok, "Health check failed after emergency rollback"
        raise RuntimeError(f"Nginx reload failed: {err} (emergency recovery completed and verified)")

    # 5. Verify post-switch endpoint routes to Green
    time.sleep(1)
    ok, data = wait_for_http(f"http://localhost:{TEST_PORT}/health", timeout_sec=5, check_db=True)
    assert ok and data.get("environment") == "proto-green", "Post-switch health check did not reach proto-green"
    print("  -> Post-switch verification confirmed: traffic actively served by proto-green.")

    # Stop continuous traffic and assert results
    traffic_active = False
    traffic_thread.join()

    avg_lat = sum(traffic_results["latencies"]) / max(1, len(traffic_results["latencies"])) * 1000
    print(f"\n[Continuous Traffic Switch Verification Results]:")
    print(f"  Total Requests During Switch            : {traffic_results['total']}")
    print(f"  Successful Requests (HTTP 200)          : {traffic_results['success']}")
    print(f"  Failed / Dropped Requests               : {traffic_results['failed']}")
    print(f"  Requests Served by Initial (proto-blue) : {traffic_results['slots']['proto-blue']}")
    print(f"  Requests Served by Candidate (proto-green): {traffic_results['slots']['proto-green']}")
    print(f"  Average Request Latency                 : {avg_lat:.2f} ms")

    # Rigorous assertions: zero errors AND requests were served by both slots across the transition
    assert traffic_results["failed"] == 0, f"Downtime detected! {traffic_results['failed']} requests dropped."
    assert traffic_results["slots"]["proto-blue"] > 0, "Initial slot proto-blue served zero requests"
    assert traffic_results["slots"]["proto-green"] > 0, "Candidate slot proto-green served zero requests"
    print("  -> ZERO DOWNTIME DEMONSTRATED AND PROVEN: 100% success rate across in-flight slot transition.")

    # Retire previous slot cleanly
    run_cmd("docker stop proto-app-blue")
    print("  -> Previous slot (proto-app-blue) stopped cleanly.")

    # -------------------------------------------------------------------------
    # STEP 4: SCENARIO 2 - Candidate Failure & Abort (Traffic Protected)
    # -------------------------------------------------------------------------
    print("\n[Step 4: SCENARIO 2] Testing Candidate Failure Handling (Bad DB Password)...")
    faulty_env = (
        f"-e FLASK_ENV=production -e APP_ENV=proto-blue -e DB_HOST=mysql "
        f"-e DB_PORT=3306 -e DB_NAME=devsecops_db -e DB_USER=devsecops_user "
        f"-e DB_PASSWORD=FAULTY_PASSWORD_GATE_TEST"
    )
    run_cmd("docker rm -f proto-app-blue")
    code, _, err = run_cmd(
        f"docker run -d --name proto-app-blue --network {NETWORK_NAME} {faulty_env} {APP_IMAGE}"
    )
    assert code == 0

    print("  -> Probing faulty candidate across bridge network from proto-nginx...")
    time.sleep(3)
    candidate_ok, cand_data = probe_candidate_from_reverse_proxy("proto-app-blue", timeout_sec=5)
    print(f"  -> Candidate bridge health result: ok={candidate_ok} (Expected: False)")
    assert not candidate_ok, "Faulty candidate unexpectedly passed health check!"

    print("  -> PRE-SWITCH GATE TRIGGERED: Candidate failed database connectivity check.")
    print("  -> Aborting deployment: Traffic switch is PREVENTED.")
    run_cmd("docker stop proto-app-blue && docker rm -f proto-app-blue")

    # Confirm active slot (green) is 100% online and serving
    ok, data = wait_for_http(f"http://localhost:{TEST_PORT}/health", timeout_sec=5, check_db=True)
    assert ok and data.get("environment") == "proto-green", "Active slot was impacted by failed candidate!"
    print(f"  -> Verified active slot (proto-green) remained 100% online and healthy (HTTP 200).")

    # -------------------------------------------------------------------------
    # STEP 5: SCENARIO 3 - Automated Rollback on Post-Switch Failure
    # -------------------------------------------------------------------------
    print("\n[Step 5: SCENARIO 3] Testing Automated Rollback Trigger (Post-Switch Crash Simulation)...")

    # Start proto-app-blue as hot standby
    run_cmd("docker rm -f proto-app-blue")
    run_cmd(f"docker run -d --name proto-app-blue --network {NETWORK_NAME} --restart always {env_blue} {APP_IMAGE}")
    time.sleep(3)

    # Save active configuration as rollback target
    run_cmd("docker exec proto-nginx cp /etc/nginx/conf.d/upstream.conf /etc/nginx/upstream.conf.previous")

    # Switch traffic to candidate (Blue)
    run_cmd(
        'docker exec -i proto-nginx sh -c "cat > /etc/nginx/conf.d/upstream.conf"',
        input_text=upstream_blue,
    )
    run_cmd("docker exec proto-nginx nginx -s reload")
    print("  -> Switched traffic to candidate slot (proto-app-blue).")

    # Simulate post-switch failure (container crash)
    print("  -> Simulating catastrophic post-switch crash on new slot...")
    run_cmd("docker stop proto-app-blue")

    # Verify post-switch probe detects outage
    post_switch_ok, _ = wait_for_http(f"http://localhost:{TEST_PORT}/health", timeout_sec=2)
    print(f"  -> Post-switch health probe result after crash: ok={post_switch_ok} (Expected: False)")
    assert not post_switch_ok, "Service unexpectedly healthy after crash"

    # Automated Rollback Handler executes: restore known-good, validate, reload, verify
    print("  -> POST-SWITCH FAILURE DETECTED: Executing automated rollback...")
    run_cmd("docker exec proto-nginx cp /etc/nginx/upstream.conf.previous /etc/nginx/conf.d/upstream.conf")
    t_code, _, t_err = run_cmd("docker exec proto-nginx nginx -t")
    assert t_code == 0, f"Restored known-good config validation failed: {t_err}"
    r_code, _, r_err = run_cmd("docker exec proto-nginx nginx -s reload")
    assert r_code == 0, f"Restored known-good config reload failed: {r_err}"
    run_cmd("docker rm -f proto-app-blue")

    # Verify recovery
    ok, data = wait_for_http(f"http://localhost:{TEST_PORT}/health", timeout_sec=5, check_db=True)
    assert ok and data.get("environment") == "proto-green", "Rollback failed to restore proto-green!"
    print(f"  -> Rollback SUCCESSFUL: Service immediately restored to healthy state by previous slot ('{data['environment']}').")

    # -------------------------------------------------------------------------
    # STEP 6: Verify Production Stack was 100% Untouched
    # -------------------------------------------------------------------------
    print("\n[Step 6] Verifying existing production services...")
    code, out, _ = run_cmd("docker ps --filter name=devsecops- --format '{{.Names}}: {{.Status}}'")
    print(out)
    ok_prod, _ = wait_for_http("http://localhost:5000/health", timeout_sec=5, check_db=True)
    ok_nginx, _ = wait_for_http("http://localhost/health", timeout_sec=5, check_db=True)
    assert ok_prod, "Production devsecops-app was impacted!"
    assert ok_nginx, "Production devsecops-nginx was impacted!"
    print("  -> Verified production devsecops-app (port 5000) and devsecops-nginx (port 80) are healthy and untouched.")

    print("\n================================================================")
    print("ALL HARDENED BLUE-GREEN DEPLOYMENT PROTOTYPE TESTS PASSED!")
    print("================================================================")


def main():
    try:
        run_prototype_suite()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
