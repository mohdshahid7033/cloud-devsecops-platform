import json
import pytest
from unittest.mock import patch
from app.app import app

@pytest.fixture(autouse=True)
def mock_external_apis():
    fake_gh_data = {
        "run": {"status": "completed", "conclusion": "success", "id": 123456, "head_branch": "main", "head_sha": "abcdef123"},
        "deploy_step": {"status": "PASSED"}
    }
    fake_trivy_data = {
        "status": "PASSED",
        "critical_vulnerabilities": 0,
        "high_vulnerabilities": 0,
        "summary_statement": "0 HIGH / CRITICAL vulnerabilities detected in the latest configured scan",
        "ignored_cves": []
    }
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=fake_gh_data):
        with patch("app.platform_service.get_real_github_pipeline_data", return_value=fake_gh_data):
            with patch("urllib.request.urlopen"):
                with patch("socket.create_connection"):
                    with patch("app.platform_routes.platform_service.get_trivy_security_status", return_value=fake_trivy_data):
                        with patch("app.platform_service.get_trivy_security_status", return_value=fake_trivy_data):
                            yield
def test_platform_home():
    """Verify platform console page renders with 200 and expected branding."""
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    assert b"DevSecOps Platform" in res.data
    assert b"ABC Free Consultants" in res.data
    assert b"Dashboard" in res.data
    assert b"Pipelines" in res.data


def test_client_app_demo_route():
    """Verify standalone demo application routes render correctly."""
    client = app.test_client()
    for route in ["/demo", "/client-app"]:
        res = client.get(route)
        assert res.status_code == 200
        assert b"ABC Free Consultants" in res.data


def test_platform_overview():
    """Verify /api/platform/overview returns valid metrics structure."""
    client = app.test_client()
    res = client.get("/api/platform/overview")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "online"
    assert "metrics" in data
    m = data["metrics"]
    assert "total_projects" in m
    assert m["total_projects"] >= 1
    assert "latest_deployment" in m
    assert "security_summary" in m
    assert "application_health" in m
    assert "database_health" in m
    assert "infrastructure" in m
    assert "git" in m


def test_platform_projects_list():
    """Verify projects list returns connected projects including ABC demo."""
    client = app.test_client()
    res = client.get("/api/platform/projects")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert isinstance(data["projects"], list)
    assert len(data["projects"]) >= 1
    first_project = data["projects"][0]
    assert first_project["project_id"] == "proj-abc-demo"
    assert "ABC Free Consultants" in first_project["name"]


def test_platform_project_details():
    """Verify retrieving single project details with runtime telemetry."""
    client = app.test_client()
    res = client.get("/api/platform/projects/proj-abc-demo")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert data["project"]["project_id"] == "proj-abc-demo"
    assert "runtime_telemetry" in data
    assert "health_status" in data["runtime_telemetry"]
    assert "database_status" in data["runtime_telemetry"]


def test_platform_project_not_found():
    """Verify 404 error returned for non-existent project ID."""
    client = app.test_client()
    res = client.get("/api/platform/projects/non-existent-proj")
    assert res.status_code == 404
    assert "error" in res.json


def test_platform_validate_project():
    """Verify honest validation checklist for project onboarding."""
    client = app.test_client()
    valid_payload = {
        "name": "Cloud Microservice",
        "repository": "https://github.com/mohdshahid7033/cloud-devsecops-platform.git",
        "branch": "main",
        "app_type": "Python / Flask",
        "environment": "Production",
        "deployment_target": "AWS EC2 via SSM"
    }
    res = client.post("/api/platform/validate-project", json=valid_payload)
    assert res.status_code == 200
    data = res.json
    assert data["valid"] is True
    assert len(data["checklist"]) >= 5


def test_platform_validate_invalid_project():
    """Verify validation detects invalid repo or short name."""
    client = app.test_client()
    invalid_payload = {
        "name": "ab",
        "repository": "not-a-valid-url"
    }
    res = client.post("/api/platform/validate-project", json=invalid_payload)
    assert res.status_code == 200
    data = res.json
    assert data["valid"] is False


def test_platform_deployments_list():
    """Verify deployments list returns deployment history."""
    client = app.test_client()
    res = client.get("/api/platform/deployments")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert isinstance(data["deployments"], list)
    assert len(data["deployments"]) >= 1


def test_platform_deployments_trigger():
    """Verify triggering deployment via platform API."""
    client = app.test_client()
    payload = {"project_id": "proj-abc-demo", "environment": "Production"}
    res = client.post("/api/platform/deployments/trigger", json=payload)
    assert res.status_code == 201
    data = res.json
    assert data["status"] == "success"
    assert "deployment" in data
    assert data["deployment"]["status"] == "SUCCESS"


def test_platform_pipelines_list():
    """Verify pipeline runs list returns recorded stages."""
    client = app.test_client()
    res = client.get("/api/platform/pipelines")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert len(data["pipeline_runs"]) >= 1
    first_run = data["pipeline_runs"][0]
    assert "stages" in first_run
    assert len(first_run["stages"]) == 13


def test_platform_security_status():
    """Verify security endpoint returns Trivy and SonarQube telemetry."""
    client = app.test_client()
    res = client.get("/api/platform/security")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert "vulnerabilities" in data
    assert data["vulnerabilities"]["critical"] == 0
    assert data["vulnerabilities"]["high"] == 0
    assert "0 HIGH / CRITICAL vulnerabilities detected in the latest configured scan" in data["vulnerabilities"]["summary_statement"]
    assert "trivy" in data
    assert "sonarqube" in data


def test_platform_monitoring_status():
    """Verify monitoring endpoint returns Prometheus & Grafana telemetry."""
    client = app.test_client()
    res = client.get("/api/platform/monitoring")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert "application_uptime_seconds" in data
    assert "database_connectivity" in data
    assert "http_requests_total" in data
    assert "prometheus" in data
    assert "grafana" in data


def test_platform_infrastructure_status():
    """Verify infrastructure endpoint returns AWS and container details."""
    client = app.test_client()
    res = client.get("/api/platform/infrastructure")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    infra = data["infrastructure"]
    assert "ap-south-1" in infra["aws_region"]
    assert infra["ec2"]["instance_id"] == "i-0fb9dcbeb35b4fdbe"
    assert "850252650249" in infra["ecr"]["registry_id"]
    assert "terraform" in infra
    assert "docker_containers" in infra


def test_platform_environments_list():
    """Verify environments endpoint returns Production, Staging, Development."""
    client = app.test_client()
    res = client.get("/api/platform/environments")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    names = [e["env_name"] for e in data["environments"]]
    assert "Production" in names
    assert "Staging" in names
    assert "Development" in names


def test_platform_rollback_options():
    """Verify rollback endpoint returns supported strategy and history."""
    client = app.test_client()
    res = client.get("/api/platform/rollback/options")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert data["rollback_supported"] is True
    assert "Amazon ECR" in data["strategy"]


def test_platform_diagnostics():
    """Verify diagnostic connection test endpoint probes all engines."""
    client = app.test_client()
    res = client.post("/api/platform/diagnostics/test-connections")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert len(data["diagnostics"]["engines"]) >= 6


def test_platform_logs():
    """Verify platform logs endpoint returns real execution log entries."""
    client = app.test_client()
    res = client.get("/api/platform/logs")
    assert res.status_code == 200
    data = res.json
    assert data["status"] == "success"
    assert isinstance(data["logs"], list)
    assert len(data["logs"]) >= 1


def test_platform_pipeline_honest_trigger(monkeypatch):
    """Verify triggering pipeline without GitHub token returns honest 400 error."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = app.test_client()
    res = client.post("/api/platform/pipelines/run")
    assert res.status_code == 400
    data = res.json
    assert data["status"] == "unavailable"
    assert "Pipeline trigger is unavailable from the platform runtime" in data["message"]


def test_platform_pipeline_stages_mapping():
    """Verify 13 mapped verification stages returned with correct structure."""
    client = app.test_client()
    res = client.get("/api/platform/pipelines")
    assert res.status_code == 200
    data = res.json
    stages = data.get("stages", [])
    assert len(stages) == 13
    stage_names = [s["name"] for s in stages]
    assert "Checkout" in stage_names[0]
    assert "pytest" in stage_names[3]
    assert "SonarQube" in stage_names[4]
    assert "Trivy" in stage_names[5]
    assert "Docker" in stage_names[6]
    assert "EC2" in stage_names[11]


def test_platform_infrastructure_environment_separation():
    """Verify infrastructure endpoint cleanly partitions AWS Production from Local Docker Compose."""
    client = app.test_client()
    res = client.get("/api/platform/infrastructure")
    assert res.status_code == 200
    infra = res.json["infrastructure"]
    assert "production" in infra
    assert "local" in infra
    prod = infra["production"]
    local = infra["local"]
    assert prod["ec2"]["instance_id"] == "i-0fb9dcbeb35b4fdbe"
    assert "850252650249" in prod["ecr"]["image_uri"]
    assert "docker_available" in local
    assert "local_service_probes" in local
    assert isinstance(local["local_service_probes"], list)


def test_platform_diagnostics_context_awareness():
    """Verify diagnostic results include environment and check_source for each engine."""
    client = app.test_client()
    res = client.post("/api/platform/diagnostics/test-connections")
    assert res.status_code == 200
    engines = res.json["diagnostics"]["engines"]
    for eng in engines:
        assert "engine" in eng
        assert "role" in eng
        assert "environment" in eng
        assert "check_source" in eng
        assert "status" in eng
        assert eng["status"] not in ["NOT FOUND", "NOT LOCATED"]


def test_platform_security_policy_wording():
    """Verify Trivy ignored CVEs use accurate policy and configuration wording."""
    fake_trivy_data = {
        "status": "PASSED",
        "critical_vulnerabilities": 0,
        "high_vulnerabilities": 0,
        "summary_statement": "0 HIGH / CRITICAL vulnerabilities detected in the latest configured scan",
        "ignored_cves": [
            {"cve_id": "GHSA-6v7p-g79w-8964", "rationale": "Configured in .trivyignore", "policy": "Ignored by project policy"},
            {"cve_id": "CVE-2025-47273", "rationale": "Not exploitable .trivyignore", "policy": "Ignored by project policy"}
        ]
    }
    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_trivy_security_status", return_value=fake_trivy_data):
        res = client.get("/api/platform/security")
    assert res.status_code == 200
    trivy_data = res.json["trivy"]
    ignored = trivy_data.get("ignored_cves", [])
    assert len(ignored) >= 2
    cve_ids = [c["cve_id"] for c in ignored]
    assert "GHSA-6v7p-g79w-8964" in cve_ids
    assert "CVE-2025-47273" in cve_ids
    for c in ignored:
        assert "Ignored by project policy" in c["policy"]
        assert ".trivyignore" in c["rationale"]


def test_platform_security_sonarqube_honest_status():
    """Verify SonarQube reports real server telemetry and avoids fabricating metrics."""
    client = app.test_client()
    res = client.get("/api/platform/security")
    assert res.status_code == 200
    sq = res.json["sonarqube"]
    assert "status" in sq
    assert "quality_gate" in sq
    assert sq["status"] in ["ONLINE", "UNAVAILABLE", "OFFLINE"]


def test_platform_monitoring_prometheus_states():
    """Verify monitoring endpoint returns real state classification."""
    client = app.test_client()
    res = client.get("/api/platform/monitoring")
    assert res.status_code == 200
    data = res.json
    assert data["state"] in ["CONNECTED", "DEGRADED", "UNAVAILABLE", "UNKNOWN"]
    assert "prometheus" in data
    assert "grafana" in data


def test_dashboard_live_health_indicator():
    """Verify dashboard contains compact live health status indicator and accessibility attributes."""
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="topbar-health-chip"' in html
    assert 'id="health-status-indicator"' in html
    assert 'id="dash-app-health-badge"' in html
    assert 'Checking…' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'DB Offline' in html

    js_res = client.get("/static/js/platform.js")
    assert js_res.status_code == 200
    js = js_res.data.decode("utf-8")
    assert "isAppHealthy" in js
    assert "checkHealth" in js
    assert "updateHealthUI" in js
    assert "initHealthIndicator" in js

    # Verify actual /health response contract matches frontend validator requirements
    health_res = client.get("/health")
    assert health_res.status_code == 200
    data = health_res.json
    assert data["status"] == "healthy"
    assert data["service"] == "devsecops-platform"
    assert "database" in data
    assert isinstance(data["database"]["connected"], bool)
    assert isinstance(data["database"]["mode"], str)
    # When MySQL is offline locally, database.connected must be False
    assert data["database"]["connected"] is False
    assert data["database"]["mode"] in ["offline_fallback", "disconnected"]


def test_map_github_workflow_status_matrix():
    """Verify GitHub Actions status/conclusion mapping logic handles all states accurately."""
    from app.platform_service import map_github_workflow_status

    # In progress and queued states
    assert map_github_workflow_status("in_progress") == "RUNNING"
    assert map_github_workflow_status("queued") == "PENDING"
    assert map_github_workflow_status("waiting") == "PENDING"
    assert map_github_workflow_status("requested") == "PENDING"
    assert map_github_workflow_status("pending") == "PENDING"

    # Completed states
    assert map_github_workflow_status("completed", "success") == "PASSED"
    assert map_github_workflow_status("completed", "failure") == "FAILED"
    assert map_github_workflow_status("completed", "timed_out") == "FAILED"
    assert map_github_workflow_status("completed", "action_required") == "FAILED"
    assert map_github_workflow_status("completed", "cancelled") == "CANCELLED"
    assert map_github_workflow_status("completed", "skipped") == "SKIPPED"
    assert map_github_workflow_status("completed", "neutral") == "PASSED"
    # Never convert unexpected completed conclusion to success
    assert map_github_workflow_status("completed", "stale") == "FAILED"

    # Empty / unknown states
    assert map_github_workflow_status(None) == "UNKNOWN"
    assert map_github_workflow_status("") == "UNKNOWN"
    assert map_github_workflow_status("some_random_state") == "UNKNOWN"


def test_pipeline_endpoint_real_shaped_successful_run():
    """Verify /api/platform/pipelines correctly structures a real-shaped successful workflow run."""
    fake_payload = {
        "status": "success",
        "run": {
            "id": 987654321,
            "run_number": 161,
            "name": "CI",
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "head_sha": "2671dacdca3fe2d79db395610a4a1516516c5954",
            "html_url": "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654321",
            "created_at": "2026-10-14T08:00:00Z",
            "updated_at": "2026-10-14T08:04:30Z",
            "event": "push",
            "actor": {"login": "mohdshahid7033"}
        },
        "runs": [
            {
                "id": 987654321,
                "run_number": 161,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": "2671dacdca3fe2d79db395610a4a1516516c5954",
                "html_url": "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654321",
                "created_at": "2026-10-14T08:00:00Z",
                "updated_at": "2026-10-14T08:04:30Z",
                "event": "push",
                "actor": {"login": "mohdshahid7033"}
            }
        ],
        "jobs": [
            {"id": 11, "name": "test", "status": "completed", "conclusion": "success", "steps": []}
        ],
        "telemetry_source": "github_actions",
        "last_fetched": 123456789.0
    }

    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=fake_payload):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json
        assert data["status"] == "success"
        assert data["telemetry_source"] == "github_actions"
        assert data["total"] == 1
        assert len(data["pipeline_runs"]) == 1

        run0 = data["pipeline_runs"][0]
        assert run0["run_number"] == 161
        assert run0["status"] == "PASSED"
        assert run0["conclusion"] == "success"
        assert run0["branch"] == "main"
        assert run0["commit_hash"] == "2671dac"
        assert run0["duration_seconds"] == 270
        assert run0["html_url"] == "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654321"

        latest = data["latest_run"]
        assert latest is not None
        assert latest["run_number"] == 161
        assert latest["status"] == "PASSED"

        # Check jobs
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["name"] == "test"
        assert data["jobs"][0]["status"] == "completed"

        # Check overview reflects it
        overview_res = client.get("/api/platform/overview")
        assert overview_res.status_code == 200
        ov_data = overview_res.json
        assert ov_data["metrics"]["pipeline_status"] == "PASSED"
        assert ov_data["metrics"]["latest_pipeline_run"]["status"] == "PASSED"
        assert ov_data["metrics"]["latest_pipeline_run"]["run_number"] == 161


def test_pipeline_endpoint_in_progress_never_shows_success():
    """Verify in-progress workflow run is NEVER presented as passed or successful."""
    in_prog_payload = {
        "run": {
            "id": 987654322,
            "run_number": 162,
            "name": "CI",
            "status": "in_progress",
            "conclusion": None,
            "head_branch": "main",
            "head_sha": "a1b2c3d4e5f6",
            "html_url": "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654322",
            "created_at": "2026-10-14T08:10:00Z",
            "updated_at": "2026-10-14T08:11:00Z"
        },
        "runs": [
            {
                "id": 987654322,
                "run_number": 162,
                "name": "CI",
                "status": "in_progress",
                "conclusion": None,
                "head_branch": "main",
                "head_sha": "a1b2c3d4e5f6",
                "html_url": "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654322",
                "created_at": "2026-10-14T08:10:00Z",
                "updated_at": "2026-10-14T08:11:00Z"
            }
        ]
    }

    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=in_prog_payload):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json
        assert data["latest_run"]["status"] == "RUNNING"
        assert data["latest_run"]["status"] != "PASSED"
        assert data["latest_run"]["status"] != "SUCCESS"
        assert data["pipeline_runs"][0]["status"] == "RUNNING"

        # Check overview also shows RUNNING
        overview_res = client.get("/api/platform/overview")
        assert overview_res.status_code == 200
        assert overview_res.json["metrics"]["pipeline_status"] == "RUNNING"
        assert overview_res.json["metrics"]["latest_pipeline_run"]["status"] == "RUNNING"


def test_pipeline_endpoint_failed_remains_failed():
    """Verify failed workflow run remains FAILED and is never coerced to success."""
    failed_payload = {
        "run": {
            "id": 987654323,
            "run_number": 163,
            "name": "CI",
            "status": "completed",
            "conclusion": "failure",
            "head_branch": "main",
            "head_sha": "f1e2d3c4b5a6",
            "html_url": "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654323",
            "created_at": "2026-10-14T08:15:00Z",
            "updated_at": "2026-10-14T08:16:30Z"
        },
        "runs": [
            {
                "id": 987654323,
                "run_number": 163,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "main",
                "head_sha": "f1e2d3c4b5a6",
                "html_url": "https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/runs/987654323",
                "created_at": "2026-10-14T08:15:00Z",
                "updated_at": "2026-10-14T08:16:30Z"
            }
        ]
    }

    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=failed_payload):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json
        assert data["latest_run"]["status"] == "FAILED"
        assert data["latest_run"]["status"] != "PASSED"
        assert data["pipeline_runs"][0]["status"] == "FAILED"

        overview_res = client.get("/api/platform/overview")
        assert overview_res.status_code == 200
        assert overview_res.json["metrics"]["pipeline_status"] == "FAILED"
        assert overview_res.json["metrics"]["latest_pipeline_run"]["status"] == "FAILED"


def test_pipeline_endpoint_cancelled_and_skipped_states():
    """Verify cancelled and skipped workflow runs are mapped accurately."""
    client = app.test_client()

    for conc, expected in [("cancelled", "CANCELLED"), ("skipped", "SKIPPED")]:
        payload = {
            "run": {
                "id": 987654324,
                "run_number": 164,
                "status": "completed",
                "conclusion": conc,
                "head_branch": "feature/test",
                "head_sha": "1234567890ab"
            },
            "runs": [
                {
                    "id": 987654324,
                    "run_number": 164,
                    "status": "completed",
                    "conclusion": conc,
                    "head_branch": "feature/test",
                    "head_sha": "1234567890ab"
                }
            ]
        }
        with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=payload):
            res = client.get("/api/platform/pipelines")
            assert res.status_code == 200
            data = res.json
            assert data["latest_run"]["status"] == expected
            assert data["pipeline_runs"][0]["status"] == expected


def test_pipeline_endpoint_fallback_and_malformed_responses():
    """Verify missing, empty, or malformed GitHub API responses do not cause crashes or false success."""
    client = app.test_client()

    # Case 1: None returned
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=None):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json
        assert data["status"] == "success"
        assert data["telemetry_source"] == "database_fallback"
        assert isinstance(data["pipeline_runs"], list)

    # Case 2: Empty dict returned
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value={}):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json
        assert data["status"] == "success"
        assert data["telemetry_source"] == "database_fallback"

    # Case 3: Run with invalid/malformed timestamps and missing fields
    malformed = {
        "run": {
            "id": "not-an-int",
            "status": None,
            "created_at": "invalid-timestamp",
            "updated_at": 12345
        }
    }
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=malformed):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json
        assert data["latest_run"]["status"] == "UNKNOWN"
        assert data["latest_run"]["duration_seconds"] is None


def test_pipeline_endpoint_no_credentials_exposed(monkeypatch):
    """Verify sensitive tokens and authorization headers are never leaked in responses."""
    test_token = "ghp_secure_dummy_token_9876543210_abcdef"
    monkeypatch.setenv("GITHUB_TOKEN", test_token)

    client = app.test_client()
    for endpoint in ["/api/platform/pipelines", "/api/platform/overview", "/"]:
        res = client.get(endpoint)
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert test_token not in body
        assert "ghp_" not in body
        assert "Bearer ghp_" not in body


# ==============================================================================
# PIPELINE DASHBOARD ACCURACY & LIVE GITHUB ACTIONS MAPPING TESTS
# ==============================================================================

def test_accurate_normal_ci_run_mapping():
    """1 & 4 & 9: Verify normal CI push run accurately maps 8 passed stages and 5 skipped deployment stages."""
    fake_jobs = [
        {
            "name": "Test & Security Scan",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Checkout code", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:33:24Z", "completed_at": "2026-11-02T15:33:25Z"},
                {"name": "Check Python", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:33:25Z", "completed_at": "2026-11-02T15:33:27Z"},
                {"name": "Install dependencies", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:33:27Z", "completed_at": "2026-11-02T15:33:34Z"},
                {"name": "Run unit & integration tests", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:33:34Z", "completed_at": "2026-11-02T15:33:38Z"},
                {"name": "SonarQube analysis", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:33:38Z", "completed_at": "2026-11-02T15:34:27Z"},
                {"name": "Run Trivy filesystem scan", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:34:27Z", "completed_at": "2026-11-02T15:34:34Z"},
                {"name": "Build Docker image for security scan", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:34:34Z", "completed_at": "2026-11-02T15:34:51Z"},
                {"name": "Scan Docker image with Trivy", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:34:51Z", "completed_at": "2026-11-02T15:34:52Z"}
            ]
        },
        {"name": "Build & Publish ECR", "status": "completed", "conclusion": "skipped", "steps": []},
        {"name": "Blue/Green Deployment", "status": "completed", "conclusion": "skipped", "steps": []},
        {"name": "Verify Production Health", "status": "completed", "conclusion": "skipped", "steps": []}
    ]

    from app.platform_service import _map_jobs_to_canonical_stages
    stages = _map_jobs_to_canonical_stages(fake_jobs)
    assert len(stages) == 13

    # First 8 stages must be PASSED with actual calculated durations
    passed_stages = [s for s in stages if s["status"] == "PASSED"]
    assert len(passed_stages) == 8
    assert stages[0]["id"] == "checkout" and stages[0]["duration"] == "1s"
    assert stages[1]["id"] == "python-check" and stages[1]["duration"] == "2s"
    assert stages[2]["id"] == "deps" and stages[2]["duration"] == "7s"
    assert stages[3]["id"] == "pytest" and stages[3]["duration"] == "4s"
    assert stages[4]["id"] == "sonarqube" and stages[4]["duration"] == "49s"
    assert stages[5]["id"] == "trivy-fs" and stages[5]["duration"] == "7s"
    assert stages[6]["id"] == "docker-build" and stages[6]["duration"] == "17s"
    assert stages[7]["id"] == "trivy-image" and stages[7]["duration"] == "1s"

    # Remaining 5 deployment stages MUST be SKIPPED with 0s duration, never PASSED
    skipped_stages = [s for s in stages if s["status"] == "SKIPPED"]
    assert len(skipped_stages) == 5
    skipped_ids = [s["id"] for s in skipped_stages]
    assert skipped_ids == ["aws-config", "ecr-login", "ecr-push", "ssm-deploy", "health-check"]
    for s in skipped_stages:
        assert s["duration"] == "0s"


def test_failed_ci_run_mapping():
    """2: Verify failed CI run reflects FAILED accurately without converting to success."""
    fake_jobs = [
        {
            "name": "Test & Security Scan",
            "status": "completed",
            "conclusion": "failure",
            "steps": [
                {"name": "Checkout code", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T10:00:00Z", "completed_at": "2026-11-02T10:00:02Z"},
                {"name": "Check Python", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T10:00:02Z", "completed_at": "2026-11-02T10:00:04Z"},
                {"name": "Install dependencies", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T10:00:04Z", "completed_at": "2026-11-02T10:00:10Z"},
                {"name": "Run unit & integration tests", "status": "completed", "conclusion": "failure", "started_at": "2026-11-02T10:00:10Z", "completed_at": "2026-11-02T10:00:15Z"},
                {"name": "SonarQube analysis", "status": "completed", "conclusion": "skipped"}
            ]
        },
        {"name": "Build & Publish ECR", "status": "completed", "conclusion": "skipped", "steps": []},
        {"name": "Blue/Green Deployment", "status": "completed", "conclusion": "skipped", "steps": []},
        {"name": "Verify Production Health", "status": "completed", "conclusion": "skipped", "steps": []}
    ]

    from app.platform_service import _map_jobs_to_canonical_stages
    stages = _map_jobs_to_canonical_stages(fake_jobs)
    pytest_st = next(s for s in stages if s["id"] == "pytest")
    assert pytest_st["status"] == "FAILED"
    assert pytest_st["duration"] == "5s"

    sonar_st = next(s for s in stages if s["id"] == "sonarqube")
    assert sonar_st["status"] == "SKIPPED"


def test_running_workflow_mapping():
    """3: Verify in-progress workflow reflects RUNNING and PENDING, never false PASSED."""
    fake_jobs = [
        {
            "name": "Test & Security Scan",
            "status": "in_progress",
            "conclusion": None,
            "steps": [
                {"name": "Checkout code", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T10:00:00Z", "completed_at": "2026-11-02T10:00:01Z"},
                {"name": "Check Python", "status": "in_progress", "conclusion": None, "started_at": "2026-11-02T10:00:01Z"}
            ]
        },
        {"name": "Build & Publish ECR", "status": "queued", "conclusion": None, "steps": []}
    ]

    from app.platform_service import _map_jobs_to_canonical_stages
    stages = _map_jobs_to_canonical_stages(fake_jobs)
    assert stages[0]["status"] == "PASSED"
    assert stages[1]["status"] == "RUNNING"
    assert stages[2]["status"] == "PENDING"
    assert stages[8]["status"] == "PENDING"  # aws-config in queued job


def test_successful_production_deployment_mapping():
    """5: Verify manual production deployment maps all 13 stages as PASSED with real durations."""
    fake_jobs = [
        {
            "name": "Test & Security Scan",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Checkout code", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:43:03Z", "completed_at": "2026-11-02T15:43:04Z"},
                {"name": "Check Python", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:43:04Z", "completed_at": "2026-11-02T15:43:06Z"},
                {"name": "Install dependencies", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:43:06Z", "completed_at": "2026-11-02T15:43:14Z"},
                {"name": "Run unit & integration tests", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:43:14Z", "completed_at": "2026-11-02T15:43:18Z"},
                {"name": "SonarQube analysis", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:43:18Z", "completed_at": "2026-11-02T15:44:04Z"},
                {"name": "Run Trivy filesystem scan", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:44:04Z", "completed_at": "2026-11-02T15:44:11Z"},
                {"name": "Build Docker image for security scan", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:44:11Z", "completed_at": "2026-11-02T15:44:30Z"},
                {"name": "Scan Docker image with Trivy", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:44:30Z", "completed_at": "2026-11-02T15:44:30Z"}
            ]
        },
        {
            "name": "Build & Publish ECR",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Configure AWS credentials (GitHub OIDC)", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:44:44Z", "completed_at": "2026-11-02T15:44:46Z"},
                {"name": "Login to Amazon ECR", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:44:46Z", "completed_at": "2026-11-02T15:44:48Z"},
                {"name": "Build, tag, and push image to ECR", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:44:48Z", "completed_at": "2026-11-02T15:45:09Z"}
            ]
        },
        {
            "name": "Blue/Green Deployment",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Execute Blue/Green deployment via SSM", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:45:27Z", "completed_at": "2026-11-02T15:45:57Z"}
            ]
        },
        {
            "name": "Verify Production Health",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Verify production endpoint health", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T15:46:19Z", "completed_at": "2026-11-02T15:46:20Z"}
            ]
        }
    ]

    from app.platform_service import _map_jobs_to_canonical_stages
    stages = _map_jobs_to_canonical_stages(fake_jobs)
    assert len(stages) == 13
    assert all(s["status"] == "PASSED" for s in stages)
    assert stages[8]["id"] == "aws-config" and stages[8]["duration"] == "2s"
    assert stages[9]["id"] == "ecr-login" and stages[9]["duration"] == "2s"
    assert stages[10]["id"] == "ecr-push" and stages[10]["duration"] == "21s"
    assert stages[11]["id"] == "ssm-deploy" and stages[11]["duration"] == "30s"
    assert stages[12]["id"] == "health-check" and stages[12]["duration"] == "1s"


def test_separation_between_ci_run_and_production_deployment():
    """6: Verify latest CI run (with skipped deployment) does NOT overwrite production deployment."""
    ci_push_run = {
        "id": 41472641243,
        "run_number": 312,
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "head_branch": "main",
        "head_sha": "eb778b1000000000000000000000000000000000",
        "created_at": "2026-11-02T15:33:00Z",
        "updated_at": "2026-11-02T15:34:53Z"
    }
    prod_deploy_run = {
        "id": 41474256894,
        "run_number": 313,
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "eb778b1000000000000000000000000000000000",
        "created_at": "2026-11-02T15:42:40Z",
        "updated_at": "2026-11-02T15:46:21Z",
        "actor": {"login": "mohdshahid7033"}
    }

    # Simulate user pushing a new commit (CI push is latest)
    payload = {
        "run": ci_push_run,
        "runs": [ci_push_run, prod_deploy_run],
        "stages": [
            {"id": "checkout", "name": "Checkout code", "status": "PASSED", "duration": "1s"},
            {"id": "python-check", "name": "Check Python", "status": "PASSED", "duration": "2s"},
            {"id": "deps", "name": "Install dependencies", "status": "PASSED", "duration": "7s"},
            {"id": "pytest", "name": "Run tests (pytest)", "status": "PASSED", "duration": "4s"},
            {"id": "sonarqube", "name": "SonarQube analysis", "status": "PASSED", "duration": "49s"},
            {"id": "trivy-fs", "name": "Run Trivy filesystem scan", "status": "PASSED", "duration": "7s"},
            {"id": "docker-build", "name": "Build Docker image", "status": "PASSED", "duration": "17s"},
            {"id": "trivy-image", "name": "Scan Docker image with Trivy", "status": "PASSED", "duration": "1s"},
            {"id": "aws-config", "name": "Configure AWS credentials", "status": "SKIPPED", "duration": "0s"},
            {"id": "ecr-login", "name": "Login to Amazon ECR", "status": "SKIPPED", "duration": "0s"},
            {"id": "ecr-push", "name": "Push Docker image to ECR", "status": "SKIPPED", "duration": "0s"},
            {"id": "ssm-deploy", "name": "Deploy to EC2 via SSM", "status": "SKIPPED", "duration": "0s"},
            {"id": "health-check", "name": "Application health check", "status": "SKIPPED", "duration": "0s"}
        ],
        "latest_deployment": {
            "deployment_id": "DEP-41474256894",
            "commit_hash": "eb778b1",
            "status": "SUCCESS",
            "environment": "Production",
            "deployed_by": "GitHub Actions (mohdshahid7033)",
            "start_time": "2026-11-02T15:46:21Z",
            "duration_seconds": 221
        },
        "telemetry_source": "github_actions",
        "last_fetched": 1000.0
    }

    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=payload):
        res = client.get("/api/platform/overview")
        assert res.status_code == 200
        data = res.json["metrics"]

        # Latest CI run reports the push run
        assert data["latest_pipeline_run"]["run_id"] == "41472641243"
        assert data["latest_pipeline_run"]["status"] == "PASSED"
        pipe_stages = data["latest_pipeline_run"]["stages"]
        assert len(pipe_stages) == 13
        assert sum(1 for s in pipe_stages if s["status"] == "PASSED") == 8
        assert sum(1 for s in pipe_stages if s["status"] == "SKIPPED") == 5

        # Latest production deployment reports the deployment run, NOT the push run
        assert data["latest_deployment"]["deployment_id"] == "DEP-41474256894"
        assert data["latest_deployment"]["status"] == "SUCCESS"
        assert data["deployment_status"] == "Healthy / Live"


def test_missing_github_token_handling(monkeypatch):
    """7: Verify missing GitHub token handles gracefully and returns honest telemetry."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    from app.platform_service import _get_github_token
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.side_effect = Exception("No git credential helper")
        token = _get_github_token()
        assert token == ""


def test_github_api_errors_handling():
    """8: Verify GitHub API HTTP 403, 500, or network errors are handled gracefully."""
    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=None):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        assert res.json["telemetry_source"] == "database_fallback"


def test_no_fabricated_success_or_duration():
    """10: Verify default stages when telemetry is unavailable do NOT fabricate PASSED or 310s duration."""
    from app.platform_service import get_pipeline_stages
    with patch("app.platform_service.get_real_github_pipeline_data", return_value=None):
        stages = get_pipeline_stages()
        assert len(stages) == 13
        for s in stages:
            assert s["status"] == "NOT_RUN"
            assert s["duration"] == "0s"


def test_pipelines_endpoint_returns_push_run_with_skipped_deployment():
    """Verify /api/platform/pipelines returns run 41472641243 (event push) with skipped deployment stages and separate deployment."""
    ci_push_run = {
        "id": 41472641243,
        "run_number": 312,
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "head_branch": "main",
        "head_sha": "eb778b1000000000000000000000000000000000",
        "created_at": "2026-11-02T15:33:00Z",
        "updated_at": "2026-11-02T15:34:53Z"
    }
    prod_deploy_run = {
        "id": 41474256894,
        "run_number": 313,
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "eb778b1000000000000000000000000000000000",
        "created_at": "2026-11-02T15:42:40Z",
        "updated_at": "2026-11-02T15:46:21Z",
        "actor": {"login": "mohdshahid7033"}
    }

    stages = [
        {"id": "checkout", "name": "Checkout code", "status": "PASSED", "duration": "1s"},
        {"id": "python-check", "name": "Check Python", "status": "PASSED", "duration": "2s"},
        {"id": "deps", "name": "Install dependencies", "status": "PASSED", "duration": "7s"},
        {"id": "pytest", "name": "Run tests (pytest)", "status": "PASSED", "duration": "4s"},
        {"id": "sonarqube", "name": "SonarQube analysis", "status": "PASSED", "duration": "49s"},
        {"id": "trivy-fs", "name": "Run Trivy filesystem scan", "status": "PASSED", "duration": "7s"},
        {"id": "docker-build", "name": "Build Docker image", "status": "PASSED", "duration": "17s"},
        {"id": "trivy-image", "name": "Scan Docker image with Trivy", "status": "PASSED", "duration": "1s"},
        {"id": "aws-config", "name": "Configure AWS credentials", "status": "SKIPPED", "duration": "0s"},
        {"id": "ecr-login", "name": "Login to Amazon ECR", "status": "SKIPPED", "duration": "0s"},
        {"id": "ecr-push", "name": "Push Docker image to ECR", "status": "SKIPPED", "duration": "0s"},
        {"id": "ssm-deploy", "name": "Deploy to EC2 via SSM", "status": "SKIPPED", "duration": "0s"},
        {"id": "health-check", "name": "Application health check", "status": "SKIPPED", "duration": "0s"}
    ]

    payload = {
        "run": ci_push_run,
        "runs": [ci_push_run, prod_deploy_run],
        "stages": stages,
        "jobs": [
            {"id": 1, "name": "Test & Security Scan", "status": "completed", "conclusion": "success"},
            {"id": 2, "name": "Build & Publish ECR", "status": "completed", "conclusion": "skipped"},
            {"id": 3, "name": "Blue/Green Deployment", "status": "completed", "conclusion": "skipped"},
            {"id": 4, "name": "Verify Production Health", "status": "completed", "conclusion": "skipped"}
        ],
        "latest_deployment": {
            "deployment_id": "DEP-41474256894",
            "commit_hash": "eb778b1",
            "status": "SUCCESS",
            "environment": "Production",
            "deployed_by": "GitHub Actions (mohdshahid7033)",
            "start_time": "2026-11-02T15:46:21Z",
            "duration_seconds": 221
        },
        "telemetry_source": "github_actions",
        "last_fetched": 1000.0
    }

    client = app.test_client()
    with patch("app.platform_routes.platform_service.get_real_github_pipeline_data", return_value=payload):
        res = client.get("/api/platform/pipelines")
        assert res.status_code == 200
        data = res.json

        # Must return the push run
        assert data["latest_run"]["run_id"] == "41472641243"
        assert data["latest_run"]["event"] == "push"
        assert data["latest_run"]["status"] == "PASSED"

        # Stages must show 8 passed and 5 skipped
        out_stages = data["stages"]
        assert len(out_stages) == 13
        assert sum(1 for s in out_stages if s["status"] == "PASSED") == 8
        assert sum(1 for s in out_stages if s["status"] == "SKIPPED") == 5
        for s in out_stages[8:]:
            assert s["status"] == "SKIPPED"
            assert s["duration"] == "0s"

        # Separate deployment is preserved
        assert data["latest_deployment"]["deployment_id"] == "DEP-41474256894"
        assert data["latest_deployment"]["status"] == "SUCCESS"


def test_missing_or_unestablished_step_returns_unknown_or_not_run():
    """Verify that if GitHub job steps cannot establish a stage, it displays NOT_RUN or UNKNOWN rather than PASSED."""
    fake_jobs = [
        {
            "id": 999,
            "name": "Test & Security Scan",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Checkout code", "status": "completed", "conclusion": "success", "started_at": "2026-11-02T10:00:00Z", "completed_at": "2026-11-02T10:00:01Z"}
                # All other steps are missing from the job
            ]
        }
    ]

    from app.platform_service import _map_jobs_to_canonical_stages
    stages = _map_jobs_to_canonical_stages(fake_jobs)
    assert stages[0]["id"] == "checkout"
    assert stages[0]["status"] == "PASSED"

    # All unestablished steps must be UNKNOWN or NOT_RUN, NEVER PASSED
    for s in stages[1:]:
        assert s["status"] in ("NOT_RUN", "UNKNOWN")
        assert s["status"] != "PASSED"
        assert s["duration"] == "0s"


# ==============================================================================
# SONARQUBE QUALITY GATE ENFORCEMENT & CLASSIFICATION TESTS
# ==============================================================================

def test_sonarqube_actual_quality_gate_passed(monkeypatch):
    """Verify that an actual Quality Gate result from SonarQube API with OK status reports PASSED."""
    from app import platform_service
    import io

    monkeypatch.setenv("SONAR_TOKEN", "fake_token_12345")
    with patch("app.platform_service.probe_endpoint", return_value=(True, "127.0.0.1", 0.01)):
        def mock_urlopen_handler(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/api/system/status" in url:
                return io.BytesIO(json.dumps({"status": "UP", "version": "10.6"}).encode())
            elif "/api/qualitygates/project_status" in url:
                return io.BytesIO(json.dumps({"projectStatus": {"status": "OK"}}).encode())
            elif "/api/measures/component" in url:
                return io.BytesIO(json.dumps({"component": {"measures": [{"metric": "bugs", "value": "0"}]}}).encode())
            return io.BytesIO(b"{}")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
            res = platform_service.get_sonarqube_status()
            assert res["quality_gate"] == "PASSED"
            assert res["authenticated"] is True
            assert res["status"] == "ONLINE"
            assert res["message"] == "SonarQube Quality Gate passed."


def test_sonarqube_actual_quality_gate_failed(monkeypatch):
    """Verify that an actual Quality Gate result with ERROR status reports FAILED."""
    from app import platform_service
    import io

    monkeypatch.setenv("SONAR_TOKEN", "fake_token_12345")
    with patch("app.platform_service.probe_endpoint", return_value=(True, "127.0.0.1", 0.01)):
        def mock_urlopen_handler(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/api/system/status" in url:
                return io.BytesIO(json.dumps({"status": "UP", "version": "10.6"}).encode())
            elif "/api/qualitygates/project_status" in url:
                return io.BytesIO(json.dumps({"projectStatus": {"status": "ERROR"}}).encode())
            return io.BytesIO(b"{}")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
            res = platform_service.get_sonarqube_status()
            assert res["quality_gate"] == "FAILED"
            assert res["scanner_status"] == "SUCCESS"
            assert res["authenticated"] is True
            assert res["message"] == "SonarQube Quality Gate failed."


def test_sonarqube_ci_step_failure_distinguished_from_qg_failure(monkeypatch):
    """Verify that a generic CI scanner execution failure reports UNKNOWN quality gate with scanner_status=FAILED."""
    from app import platform_service

    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    fake_ci_data = {
        "stages": [
            {"id": "sonarqube", "name": "SonarQube analysis", "status": "FAILED", "duration": "35s"}
        ]
    }
    with patch("app.platform_service.probe_endpoint", return_value=(False, "127.0.0.1", 0.0)):
        with patch("app.platform_service.get_real_github_pipeline_data", return_value=fake_ci_data):
            res = platform_service.get_sonarqube_status()
            assert res["quality_gate"] == "UNKNOWN"
            assert res["scanner_status"] == "FAILED"
            assert res["authenticated"] is False
            assert "unverified" in res["message"].lower() or "unverified" in res["note"].lower()


def test_sonarqube_pending_running_result(monkeypatch):
    """Verify that in-progress analysis in either live server or CI reports PENDING."""
    from app import platform_service
    import io

    # Case A: Live server returns PENDING status
    monkeypatch.setenv("SONAR_TOKEN", "fake_token_12345")
    with patch("app.platform_service.probe_endpoint", return_value=(True, "127.0.0.1", 0.01)):
        def mock_urlopen_handler(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/api/system/status" in url:
                return io.BytesIO(json.dumps({"status": "UP"}).encode())
            elif "/api/qualitygates/project_status" in url:
                return io.BytesIO(json.dumps({"projectStatus": {"status": "PENDING"}}).encode())
            return io.BytesIO(b"{}")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
            res = platform_service.get_sonarqube_status()
            assert res["quality_gate"] == "PENDING"
            assert res["authenticated"] is True

    # Case B: CI step is RUNNING
    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    fake_ci_data = {
        "stages": [
            {"id": "sonarqube", "name": "SonarQube analysis", "status": "RUNNING", "duration": "12s"}
        ]
    }
    with patch("app.platform_service.probe_endpoint", return_value=(False, "127.0.0.1", 0.0)):
        with patch("app.platform_service.get_real_github_pipeline_data", return_value=fake_ci_data):
            res = platform_service.get_sonarqube_status()
            assert res["quality_gate"] == "PENDING"
            assert res["authenticated"] is False


def test_sonarqube_scanner_success_without_verified_qg(monkeypatch):
    """Verify that a successful scanner step in CI alone is NOT represented as Quality Gate PASSED."""
    from app import platform_service

    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    fake_ci_data = {
        "stages": [
            {"id": "sonarqube", "name": "SonarQube analysis", "status": "PASSED", "duration": "49s"}
        ]
    }
    with patch("app.platform_service.probe_endpoint", return_value=(False, "127.0.0.1", 0.0)):
        with patch("app.platform_service.get_real_github_pipeline_data", return_value=fake_ci_data):
            res = platform_service.get_sonarqube_status()
            # MUST NOT be PASSED because QG was not verified via authenticated API
            assert res["quality_gate"] == "UNKNOWN"
            assert res["quality_gate"] != "PASSED"
            assert res["scanner_status"] == "PASSED"
            assert res["authenticated"] is False
            assert "unverified" in res["message"].lower()


def test_sonarqube_unknown_or_unavailable_result(monkeypatch):
    """Verify that when SonarQube is unreachable and no CI data is available, it reports UNAVAILABLE."""
    from app import platform_service

    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    with patch("app.platform_service.probe_endpoint", return_value=(False, "127.0.0.1", 0.0)):
        with patch("app.platform_service.get_real_github_pipeline_data", return_value=None):
            res = platform_service.get_sonarqube_status()
            assert res["quality_gate"] == "UNAVAILABLE"
            assert res["status"] == "UNAVAILABLE"
            assert res["connected"] is False

    # When reachable but unauthenticated and no CI data
    with patch("app.platform_service.probe_endpoint", return_value=(True, "127.0.0.1", 0.01)):
        with patch("urllib.request.urlopen"):
            with patch("app.platform_service.get_real_github_pipeline_data", return_value=None):
                res = platform_service.get_sonarqube_status()
                assert res["quality_gate"] == "AUTHENTICATION_REQUIRED"
                assert res["status"] == "ONLINE"
