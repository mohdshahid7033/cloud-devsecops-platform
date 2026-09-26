from app.app import app


def test_home():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"ABC Free Consultants" in response.data
    assert b"Zero-Cost" in response.data
    assert b"Services" in response.data


def test_health():
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "healthy"
    assert response.json["service"] == "devsecops-platform"
    assert "database" in response.json


def test_static_assets():
    client = app.test_client()
    css_res = client.get("/static/css/style.css")
    assert css_res.status_code == 200
    assert b"ABC Free Consultants" in css_res.data

    js_res = client.get("/static/js/main.js")
    assert js_res.status_code == 200
    assert b"ABC Free Consultants" in js_res.data


def test_metrics():
    client = app.test_client()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"flask_http_request_total" in response.data


def test_api_status():
    client = app.test_client()
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "online"
    assert data["service"] == "devsecops-platform"
    assert data["client_name"] == "ABC Free Consultants"
    assert "database" in data
    assert "pipeline" in data
    assert data["pipeline"]["ci_runner"] == "Windows Self-Hosted Runner (PowerShell)"
    assert data["pipeline"]["sast_scanner"] == "SonarQube (SonarScanner CLI)"
    assert data["pipeline"]["vulnerability_scanner"] == "Aqua Security Trivy (OS, Package & Docker Scan)"


def test_api_contact_valid():
    client = app.test_client()
    payload = {
        "name": "Alex Mercer",
        "email": "alex.mercer@enterprise.com",
        "company": "Mercer Global Dynamics",
        "service": "cloud",
        "message": "We need architectural guidance for automating our multi-region Kubernetes deployments."
    }
    response = client.post("/api/contact", json=payload)
    assert response.status_code == 201
    data = response.json
    assert data["status"] == "success"
    assert "reference_id" in data
    assert data["reference_id"].startswith("ABC-")
    assert "storage" in data


def test_api_contact_invalid_email():
    client = app.test_client()
    payload = {
        "name": "Alex Mercer",
        "email": "not-an-email",
        "company": "Mercer Global",
        "service": "security",
        "message": "Testing invalid email rejection handling."
    }
    response = client.post("/api/contact", json=payload)
    assert response.status_code == 400
    assert "error" in response.json
    assert response.json["field"] == "email"


def test_api_contact_missing_fields():
    client = app.test_client()
    payload = {
        "name": "Alex Mercer",
        "email": "alex@mercer.com"
        # missing company, service, message
    }
    response = client.post("/api/contact", json=payload)
    assert response.status_code == 400
    assert "error" in response.json


def test_api_contact_get():
    client = app.test_client()
    response = client.get("/api/contact")
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "success"
    assert "total_count" in data
    assert isinstance(data["requests"], list)
