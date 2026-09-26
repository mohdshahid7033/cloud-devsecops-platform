import os
import re
import time
import logging
from flask import Flask, jsonify, render_template, request
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import REGISTRY, Gauge

# Support importing database whether running directly (python app.py) or as package (from root)
try:
    import database
except ImportError:
    try:
        from app import database
    except ImportError:
        from . import database

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("devsecops-app")

app = Flask(__name__)
metrics = PrometheusMetrics(app)

# Record application start time for uptime telemetry
START_TIME = time.time()
APP_VERSION = os.getenv("APP_VERSION", "v1.0.1-production")

# Register custom Prometheus Gauge for MySQL Database health (idempotent / reload-safe)
if "devsecops_database_up" in getattr(REGISTRY, "_names_to_collectors", {}):
    DB_GAUGE = REGISTRY._names_to_collectors["devsecops_database_up"]
else:
    try:
        DB_GAUGE = Gauge(
            "devsecops_database_up",
            "DevSecOps MySQL database connection status (1 = connected, 0 = disconnected)"
        )
    except Exception:
        DB_GAUGE = REGISTRY._names_to_collectors.get("devsecops_database_up")

# Initialize database schema if MySQL is accessible
database.init_db()


def update_db_metric():
    """Query database status and update Prometheus gauge."""
    status = database.get_db_status()
    if DB_GAUGE:
        DB_GAUGE.set(1 if status.get("connected") else 0)
    return status


@app.route("/", methods=["GET"])
def home():
    """Render the ABC Free Consultants client enterprise website."""
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    """
    Standard health check endpoint for load balancers and deployment verification.
    Preserves exact contract while including database connectivity metadata.
    """
    db_status = update_db_metric()
    return jsonify({
        "status": "healthy",
        "service": "devsecops-platform",
        "environment": os.getenv("APP_ENV", "production"),
        "version": APP_VERSION,
        "database": {
            "connected": db_status.get("connected", False),
            "mode": db_status.get("mode", "unknown"),
            "latency_ms": db_status.get("latency_ms")
        }
    })


@app.route("/api/status", methods=["GET"])
def api_status():
    """
    Comprehensive platform telemetry and architecture status endpoint.
    Exposes non-sensitive deployment, pipeline, and database health metrics.
    """
    db_status = update_db_metric()
    total_consultations = database.get_consultations_count()
    uptime_seconds = int(time.time() - START_TIME)

    return jsonify({
        "status": "online",
        "service": "devsecops-platform",
        "client_name": "ABC Free Consultants",
        "project_title": "Cloud-Based DevSecOps Platform for Automated Application Deployment and Monitoring",
        "version": APP_VERSION,
        "uptime_seconds": uptime_seconds,
        "database": {
            "status": "connected" if db_status.get("connected") else "offline_fallback",
            "host": db_status.get("host"),
            "port": db_status.get("port"),
            "database": db_status.get("database"),
            "driver": db_status.get("driver"),
            "mode": db_status.get("mode"),
            "latency_ms": db_status.get("latency_ms"),
            "total_records": total_consultations
        },
        "pipeline": {
            "ci_runner": "Windows Self-Hosted Runner (PowerShell)",
            "test_framework": "pytest",
            "sast_scanner": "SonarQube (SonarScanner CLI)",
            "vulnerability_scanner": "Aqua Security Trivy (OS, Package & Docker Scan)",
            "containerization": "Docker (Alpine Linux, Multi-Stage / Hardened)",
            "registry": "AWS Elastic Container Registry (ECR)",
            "cd_orchestrator": "AWS Systems Manager (SSM Run Command)",
            "target_host": "AWS EC2 (Amazon Linux 2023)",
            "ingress": "Nginx Reverse Proxy",
            "monitoring": "Prometheus & Grafana"
        },
        "telemetry_endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "status": "/api/status",
            "contact_api": "/api/contact"
        }
    })


@app.route("/api/contact", methods=["GET", "POST"])
def api_contact():
    """
    Handle consultation and advisory requests with server-side validation.
    Stores records into MySQL (or resilient fallback) using parameterized queries.
    """
    if request.method == "GET":
        requests_list = database.get_consultations(limit=10)
        total_count = database.get_consultations_count()
        return jsonify({
            "status": "success",
            "total_count": total_count,
            "requests": requests_list
        })

    # Handle POST
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "Invalid request payload. JSON or form data required."}), 400

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    company = str(data.get("company", "")).strip()
    service = str(data.get("service", "")).strip()
    message = str(data.get("message", "")).strip()

    # Server-Side Input Validation
    if not name or len(name) < 2:
        return jsonify({"error": "Full name is required (minimum 2 characters).", "field": "name"}), 400

    email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not email or not re.match(email_regex, email):
        return jsonify({"error": "A valid corporate email address is required.", "field": "email"}), 400

    if not company:
        return jsonify({"error": "Organization / Company name is required.", "field": "company"}), 400

    if not service:
        return jsonify({"error": "Please select a valid practice area of interest.", "field": "service"}), 400

    if not message or len(message) < 10:
        return jsonify({"error": "Project overview message must be at least 10 characters.", "field": "message"}), 400

    # Save to Database with parameterized query
    save_result = database.save_consultation(
        name=name,
        email=email,
        company=company,
        service=service,
        message=message
    )

    update_db_metric()

    if not save_result.get("success"):
        logger.error(f"Failed to persist consultation: {save_result.get('error')}")
        return jsonify({
            "error": "Failed to persist consultation request to database.",
            "details": save_result.get("error")
        }), 500

    return jsonify({
        "status": "success",
        "reference_id": save_result["reference_id"],
        "storage": save_result["storage"],
        "message": f"Thank you, {name}! Your consultation request for {company} has been received.",
        "confirmation": {
            "email": email,
            "practice_area": service,
            "reference_id": save_result["reference_id"]
        }
    }), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
