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
