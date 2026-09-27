import os
import sys
import json
import pymysql
import urllib.request

print("==================================================================")
print("PLATFORM MANUAL SMOKE-TEST VERIFICATION SCRIPT")
print("==================================================================")

# 1. Root & 8 navigation views
print("\n[1] Checking Platform Root (http://localhost:5000/):")
with urllib.request.urlopen("http://localhost:5000/") as resp:
    html = resp.read().decode("utf-8")
    assert resp.status == 200, f"Expected 200, got {resp.status}"

views = ["dashboard", "projects", "deployments", "pipelines", "security", "monitoring", "infrastructure", "settings"]
for v in views:
    assert f'data-view="{v}"' in html, f"Missing nav item data-view={v}"
    assert f'id="view-{v}"' in html, f"Missing view panel id=view-{v}"
    print(f"  [OK] Navigation section verified: {v}")

# 2. Check 13 visual pipeline stages via API and dashboard
print("\n[2] Checking Visual CI/CD 13 Pipeline Stages:")
with urllib.request.urlopen("http://localhost:5000/api/platform/pipelines") as resp:
    pipeline_data = json.loads(resp.read().decode("utf-8"))
    runs = pipeline_data.get("pipeline_runs", [])
    assert len(runs) > 0, "No pipeline runs returned by API"
    stages = runs[0].get("stages", [])
    assert len(stages) == 13, f"Expected 13 pipeline stages, found {len(stages)}"
    expected_stage_ids = [
        "checkout", "python-check", "deps", "pytest", "sonarqube",
        "trivy-fs", "docker-build", "trivy-image", "aws-config",
        "ecr-login", "ecr-push", "ssm-deploy", "health-check"
    ]
    actual_stage_ids = [s.get("id") for s in stages]
    assert actual_stage_ids == expected_stage_ids, f"Stages mismatch: {actual_stage_ids}"
    for st in stages:
        print(f"  [OK] Pipeline stage verified: {st.get('id')} - {st.get('name')} ({st.get('status')})")

# 3. Check Security disclosure & whitelist
print("\n[3] Checking Security Disclosure and .trivyignore Whitelist:")
with urllib.request.urlopen("http://localhost:5000/api/platform/security") as resp:
    sec_data = json.loads(resp.read().decode("utf-8"))
    summary = sec_data.get("vulnerabilities", {}).get("summary_statement", "")
    assert "0 HIGH / CRITICAL vulnerabilities detected in the latest configured scan" in summary
    print(f"  [OK] Scan-specific disclosure statement verified: {summary}")

    trivy_ignored = sec_data.get("trivy", {}).get("ignored_cves", [])
    ignored_ids = [item.get("cve_id") for item in trivy_ignored]
    assert "GHSA-6v7p-g79w-8964" in ignored_ids
    assert "CVE-2025-47273" in ignored_ids
    print(f"  [OK] Ignored CVEs (.trivyignore) verified: {ignored_ids}")

# 4. Check Demo Application route
print("\n[4] Checking Standalone Demo Client Application (/demo & /client-app):")
for path in ["/demo", "/client-app"]:
    with urllib.request.urlopen(f"http://localhost:5000{path}") as resp:
        demo_html = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "ABC Free Consultants" in demo_html
        assert "Zero-Cost" in demo_html
        print(f"  [OK] Route {path} rendered HTTP 200 with ABC Free Consultants content.")

# 5. Check Consultation submission & MySQL persistence
print("\n[5] Submitting Consultation Request to /api/contact:")
payload = json.dumps({
    "name": "Smoke Test Engineer",
    "email": "smoke.test@enterprise-devsecops.io",
    "company": "DevSecOps Quality Labs",
    "service": "security",
    "message": "Performing automated smoke test of consultation form persistence to MySQL."
}).encode("utf-8")
req = urllib.request.Request("http://localhost:5000/api/contact", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode("utf-8"))
    print(f"  [OK] HTTP Status: {resp.status}")
    print(f"  [OK] Reference ID: {res.get('reference_id')}")
    print(f"  [OK] Storage Driver: {res.get('storage')}")
    assert res.get("status") == "success"
    assert res.get("storage") == "mysql"
    ref_id = res.get("reference_id")

# 6. Direct MySQL record verification
print("\n[6] Verifying record exists in MySQL database:")
conn = pymysql.connect(
    host="localhost", port=3306, user="devsecops_user",
    password="devsecops_pass", database="devsecops_db"
)
with conn.cursor() as cur:
    cur.execute("SELECT reference_id, name, email, company, service, status FROM consultation_requests WHERE reference_id = %s", (ref_id,))
    row = cur.fetchone()
    assert row is not None, f"Record {ref_id} not found in MySQL!"
    print(f"  [OK] Verified row in MySQL table 'consultation_requests': {row}")
conn.close()

# 7. Check Nginx Ingress & Health check
print("\n[7] Checking Nginx Reverse Proxy (http://localhost/health):")
with urllib.request.urlopen("http://localhost/health") as resp:
    nginx_data = json.loads(resp.read().decode("utf-8"))
    print(f"  [OK] Nginx Response: {nginx_data}")
    assert nginx_data.get("status") == "healthy"
    assert nginx_data.get("database", {}).get("connected") is True
    print(f"  [OK] Ingress Health check confirmed healthy via Nginx!")

# 8. Check Secrets Exposure (Ensure no AWS credentials in HTML or responses)
print("\n[8] Checking Secrets Masking:")
forbidden_strings = ["AKIA", "SECRET_ACCESS_KEY", "AWS_SECRET", "devsecops_root_pass"]
for forbidden in forbidden_strings:
    assert forbidden not in html, f"Security risk: {forbidden} found in HTML!"
print("  [OK] Zero AWS secrets or root credentials exposed in frontend UI!")

print("\n==================================================================")
print("ALL 8 VERIFICATION CHECKS PASSED SUCCESSFULLY!")
print("==================================================================")
