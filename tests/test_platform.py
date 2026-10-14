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
