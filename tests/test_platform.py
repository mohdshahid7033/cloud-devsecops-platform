import json
from app.app import app


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
    client = app.test_client()
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
