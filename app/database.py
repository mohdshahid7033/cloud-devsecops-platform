import os
import time
import uuid
import json
import logging
import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)

# Database Configuration with Configurable Environment Overrides
# Production strictly requires credentials via environment variables (e.g. AWS SSM / Secrets Manager).
# Local development and tests default to local Docker credentials if APP_ENV is non-production.
_is_prod = os.getenv("APP_ENV", "").lower() in ("production", "prod")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "" if _is_prod else "devsecops_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "" if _is_prod else "devsecops_pass")
DB_NAME = os.getenv("DB_NAME", "devsecops_db")
DB_TIMEOUT = int(os.getenv("DB_TIMEOUT", "1"))

# Fallback Policy: Disallow silent fallback in production to avoid masking genuine DB outages
ALLOW_DB_FALLBACK = os.getenv(
    "ALLOW_DB_FALLBACK",
    "false" if os.getenv("APP_ENV") == "production" else "true"
).lower() in ("true", "1", "yes")

# Circuit breaker parameters to prevent repeated connection timeouts when offline
_last_failure_time = 0
_RETRY_INTERVAL = 15  # seconds before retrying connection if offline

# In-memory fallback storage for offline development & tests when MySQL is unreachable
_memory_store = []
_projects_store = []
_deployments_store = []
_pipeline_store = []
_security_store = []
_environments_store = []


def _seed_memory_stores():
    """Seed in-memory fallback stores with default baseline project telemetry."""
    global _projects_store, _deployments_store, _pipeline_store, _security_store, _environments_store
    if not _projects_store:
        _projects_store = [
            {
                "id": 1,
                "project_id": "proj-abc-demo",
                "name": "ABC Free Consultants",
                "repository": "https://github.com/mohdshahid7033/cloud-devsecops-platform.git",
                "branch": "main",
                "app_type": "Python / Flask (Docker Alpine)",
                "environment": "Production",
                "deployment_target": "AWS EC2 via SSM (ap-south-1)",
                "status": "active",
                "health_status": "healthy",
                "pipeline_status": "passed",
                "created_at": "2026-09-26 12:00:00",
                "updated_at": "2026-09-26 18:20:33"
            }
        ]
    if not _deployments_store:
        _deployments_store = [
            {
                "id": 1,
                "deployment_id": "DEP-202609-01",
                "project_id": "proj-abc-demo",
                "commit_hash": "bf6b812",
                "commit_message": "Update demo heading for CI/CD deployment",
                "branch": "main",
                "environment": "Production",
                "status": "SUCCESS",
                "start_time": "2026-09-26 18:15:30",
                "duration_seconds": 195,
                "deployed_by": "GitHub Actions (Self-Hosted Runner)",
                "target_instance": "i-0fb9dcbeb35b4fdbe",
                "ecr_image": "850252650249.dkr.ecr.ap-south-1.amazonaws.com/devsecops-platform:latest",
                "logs": "Docker pull succeeded. Containers restarted on devsecops-network. Nginx proxy active. Health check returned HTTP 200.",
                "created_at": "2026-09-26 18:20:33"
            }
        ]
    if not _pipeline_store:
        default_stages = [
            {"id": "checkout", "name": "Checkout code", "status": "PASSED", "duration": "3s", "command": "actions/checkout@v4"},
            {"id": "python-check", "name": "Check Python & Runner", "status": "PASSED", "duration": "4s", "command": "python --version; pip --version"},
            {"id": "deps", "name": "Install dependencies", "status": "PASSED", "duration": "18s", "command": "pip install -r app/requirements.txt pytest awscli"},
            {"id": "pytest", "name": "Run unit tests", "status": "PASSED", "duration": "6s", "command": "pytest (9/9 passed)"},
            {"id": "sonarqube", "name": "SonarQube analysis", "status": "PASSED", "duration": "42s", "command": "sonar-scanner -Dsonar.projectKey=cloud-devsecops-platform"},
            {"id": "trivy-fs", "name": "Trivy filesystem scan", "status": "PASSED", "duration": "14s", "command": "trivy fs --severity HIGH,CRITICAL --ignorefile .trivyignore ."},
            {"id": "docker-build", "name": "Build Docker image", "status": "PASSED", "duration": "38s", "command": "docker build -t devsecops-platform -f docker/Dockerfile ."},
            {"id": "trivy-image", "name": "Trivy image scan", "status": "PASSED", "duration": "22s", "command": "trivy image --severity HIGH,CRITICAL devsecops-platform:latest"},
            {"id": "aws-config", "name": "Configure AWS credentials", "status": "PASSED", "duration": "2s", "command": "aws-actions/configure-aws-credentials@v4 (ap-south-1)"},
            {"id": "ecr-login", "name": "Login to Amazon ECR", "status": "PASSED", "duration": "4s", "command": "aws-actions/amazon-ecr-login@v2"},
            {"id": "ecr-push", "name": "Push Docker image to ECR", "status": "PASSED", "duration": "51s", "command": "docker push 850252650249.dkr.ecr.ap-south-1.amazonaws.com/devsecops-platform:latest"},
            {"id": "ssm-deploy", "name": "Deploy to EC2 via SSM", "status": "PASSED", "duration": "68s", "command": "aws ssm send-command --instance-ids i-0fb9dcbeb35b4fdbe"},
            {"id": "health-check", "name": "Application health check", "status": "PASSED", "duration": "5s", "command": "curl -f http://localhost/health (HTTP 200 OK)"}
        ]
        _pipeline_store = [
            {
                "id": 1,
                "run_id": "RUN-202609-01",
                "project_id": "proj-abc-demo",
                "commit_hash": "bf6b812",
                "branch": "main",
                "status": "SUCCESS",
                "stages_json": json.dumps(default_stages),
                "triggered_by": "push: main",
                "duration_seconds": 310,
                "created_at": "2026-09-26 18:20:33"
            }
        ]
    if not _security_store:
        _security_store = [
            {
                "id": 1,
                "scan_id": "SCAN-202609-01",
                "project_id": "proj-abc-demo",
                "scanner": "trivy",
                "scan_type": "filesystem",
                "status": "PASSED",
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "details_json": json.dumps({
                    "target": "app/requirements.txt",
                    "packages_analyzed": ["Flask@3.1.3", "PyMySQL@1.1.1", "prometheus-flask-exporter@0.23.2"],
                    "vulnerabilities": [],
                    "ignored_cves": ["GHSA-6v7p-g79w-8964", "CVE-2025-47273"]
                }),
                "scanned_at": "2026-09-26 18:18:36"
            }
        ]
    if not _environments_store:
        _environments_store = [
            {
                "id": 1,
                "env_name": "Production",
                "status": "Active",
                "target_type": "AWS EC2 via SSM (ap-south-1)",
                "url": "http://localhost",
                "description": "Live production environment deployed on AWS EC2 (i-0fb9dcbeb35b4fdbe) with Nginx proxy and Prometheus",
                "created_at": "2026-09-26 12:00:00"
            },
            {
                "id": 2,
                "env_name": "Staging",
                "status": "Configurable",
                "target_type": "AWS EC2 / Isolated Container",
                "url": "Pending configuration",
                "description": "Pre-production staging gate for automated integration testing before production release",
                "created_at": "2026-09-26 12:00:00"
            },
            {
                "id": 3,
                "env_name": "Development",
                "status": "Active",
                "target_type": "Docker Compose (Local)",
                "url": "http://localhost:5000",
                "description": "Local containerized development stack with live MySQL and Prometheus exporter",
                "created_at": "2026-09-26 12:00:00"
            }
        ]


_seed_memory_stores()


def is_offline_cooldown():
    """Returns True if within circuit breaker cooldown period after a connection failure."""
    global _last_failure_time
    return (time.time() - _last_failure_time) < _RETRY_INTERVAL


def record_failure():
    """Record connection failure to trigger cooldown."""
    global _last_failure_time
    _last_failure_time = time.time()


def record_success():
    """Reset connection failure on successful connection."""
    global _last_failure_time
    _last_failure_time = 0


def get_connection(include_db=True):
    """Establish and return a PyMySQL connection with timeout."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME if include_db else None,
        connect_timeout=DB_TIMEOUT,
        read_timeout=DB_TIMEOUT,
        write_timeout=DB_TIMEOUT,
        cursorclass=DictCursor,
        charset="utf8mb4"
    )


def init_db():
    """
    Initialize MySQL database and tables if server is reachable.
    Creates schema for consultation requests, projects, deployments,
    pipelines, security scans, and environments.
    """
    if is_offline_cooldown():
        return False

    try:
        # Step 1: Connect to server without specific DB to ensure DB exists
        conn = get_connection(include_db=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                )
            conn.commit()
        finally:
            conn.close()

        # Step 2: Connect to specific DB and ensure schema
        conn = get_connection(include_db=True)
        try:
            with conn.cursor() as cursor:
                # 1. Existing consultation_requests table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS consultation_requests (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        reference_id VARCHAR(36) NOT NULL UNIQUE,
                        name VARCHAR(100) NOT NULL,
                        email VARCHAR(150) NOT NULL,
                        company VARCHAR(150) NOT NULL,
                        service VARCHAR(100) NOT NULL,
                        message TEXT NOT NULL,
                        status VARCHAR(50) DEFAULT 'received',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 2. Projects table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS projects (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        project_id VARCHAR(64) NOT NULL UNIQUE,
                        name VARCHAR(150) NOT NULL,
                        repository VARCHAR(255) NOT NULL,
                        branch VARCHAR(64) DEFAULT 'main',
                        app_type VARCHAR(64) DEFAULT 'Python / Flask',
                        environment VARCHAR(32) DEFAULT 'Production',
                        deployment_target VARCHAR(128) DEFAULT 'AWS EC2 via SSM',
                        status VARCHAR(32) DEFAULT 'active',
                        health_status VARCHAR(32) DEFAULT 'healthy',
                        pipeline_status VARCHAR(32) DEFAULT 'passed',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 3. Deployments table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS deployments (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        deployment_id VARCHAR(64) NOT NULL UNIQUE,
                        project_id VARCHAR(64) NOT NULL,
                        commit_hash VARCHAR(40) NOT NULL,
                        commit_message VARCHAR(255),
                        branch VARCHAR(64) DEFAULT 'main',
                        environment VARCHAR(32) DEFAULT 'Production',
                        status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
                        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        duration_seconds INT DEFAULT 0,
                        deployed_by VARCHAR(100) DEFAULT 'GitHub Actions (Self-Hosted Runner)',
                        target_instance VARCHAR(64) DEFAULT 'i-0fb9dcbeb35b4fdbe',
                        ecr_image VARCHAR(255) DEFAULT '850252650249.dkr.ecr.ap-south-1.amazonaws.com/devsecops-platform:latest',
                        logs TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 4. Pipeline Runs table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pipeline_runs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        run_id VARCHAR(64) NOT NULL UNIQUE,
                        project_id VARCHAR(64) NOT NULL,
                        commit_hash VARCHAR(40) NOT NULL,
                        branch VARCHAR(64) DEFAULT 'main',
                        status VARCHAR(32) DEFAULT 'SUCCESS',
                        stages_json TEXT,
                        triggered_by VARCHAR(100) DEFAULT 'push: main',
                        duration_seconds INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 5. Security Scans table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS security_scans (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        scan_id VARCHAR(64) NOT NULL UNIQUE,
                        project_id VARCHAR(64) NOT NULL,
                        scanner VARCHAR(32) NOT NULL,
                        scan_type VARCHAR(32) NOT NULL,
                        status VARCHAR(32) NOT NULL DEFAULT 'PASSED',
                        critical_count INT DEFAULT 0,
                        high_count INT DEFAULT 0,
                        medium_count INT DEFAULT 0,
                        low_count INT DEFAULT 0,
                        details_json TEXT,
                        scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 6. Environments table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS environments (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        env_name VARCHAR(32) NOT NULL UNIQUE,
                        status VARCHAR(32) NOT NULL,
                        target_type VARCHAR(64),
                        url VARCHAR(255),
                        description VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # Seed baseline data if empty
                cursor.execute("SELECT COUNT(*) AS total FROM projects")
                if cursor.fetchone()["total"] == 0:
                    cursor.execute("""
                        INSERT INTO projects (project_id, name, repository, branch, app_type, environment, deployment_target, status, health_status, pipeline_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        "proj-abc-demo", "ABC Free Consultants",
                        "https://github.com/mohdshahid7033/cloud-devsecops-platform.git",
                        "main", "Python / Flask (Docker Alpine)", "Production",
                        "AWS EC2 via SSM (ap-south-1)", "active", "healthy", "passed"
                    ))

                cursor.execute("SELECT COUNT(*) AS total FROM deployments")
                if cursor.fetchone()["total"] == 0:
                    cursor.execute("""
                        INSERT INTO deployments (deployment_id, project_id, commit_hash, commit_message, branch, environment, status, duration_seconds, deployed_by, target_instance, ecr_image, logs)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        "DEP-202609-01", "proj-abc-demo", "bf6b812",
                        "Update demo heading for CI/CD deployment", "main", "Production",
                        "SUCCESS", 195, "GitHub Actions (Self-Hosted Runner)",
                        "i-0fb9dcbeb35b4fdbe",
                        "850252650249.dkr.ecr.ap-south-1.amazonaws.com/devsecops-platform:latest",
                        "Docker pull succeeded. Containers restarted on devsecops-network. Nginx proxy active. Health check returned HTTP 200."
                    ))

                cursor.execute("SELECT COUNT(*) AS total FROM pipeline_runs")
                if cursor.fetchone()["total"] == 0 and _pipeline_store:
                    first_run = _pipeline_store[0]
                    cursor.execute("""
                        INSERT INTO pipeline_runs (run_id, project_id, commit_hash, branch, status, stages_json, triggered_by, duration_seconds)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        first_run["run_id"], first_run["project_id"], first_run["commit_hash"],
                        first_run["branch"], first_run["status"], first_run["stages_json"],
                        first_run["triggered_by"], first_run["duration_seconds"]
                    ))

                cursor.execute("SELECT COUNT(*) AS total FROM security_scans")
                if cursor.fetchone()["total"] == 0 and _security_store:
                    first_scan = _security_store[0]
                    cursor.execute("""
                        INSERT INTO security_scans (scan_id, project_id, scanner, scan_type, status, critical_count, high_count, medium_count, low_count, details_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        first_scan["scan_id"], first_scan["project_id"], first_scan["scanner"],
                        first_scan["scan_type"], first_scan["status"], first_scan["critical_count"],
                        first_scan["high_count"], first_scan["medium_count"], first_scan["low_count"],
                        first_scan["details_json"]
                    ))

                cursor.execute("SELECT COUNT(*) AS total FROM environments")
                if cursor.fetchone()["total"] == 0 and _environments_store:
                    for env in _environments_store:
                        cursor.execute("""
                            INSERT INTO environments (env_name, status, target_type, url, description)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (env["env_name"], env["status"], env["target_type"], env["url"], env["description"]))

            conn.commit()
            record_success()
            logger.info("Database schema initialized and baseline seeded successfully.")
            return True
        finally:
            conn.close()
    except Exception as e:
        record_failure()
        logger.warning(
            f"MySQL initialization skipped (running in offline/fallback mode): {e}"
        )
        return False


def get_db_status():
    """
    Check database connectivity, measuring latency.
    Returns status dictionary with exact operational details.
    """
    if is_offline_cooldown():
        return {
            "connected": False,
            "host": DB_HOST,
            "port": DB_PORT,
            "database": DB_NAME,
            "driver": "PyMySQL",
            "latency_ms": None,
            "mode": "offline_fallback" if ALLOW_DB_FALLBACK else "disconnected",
            "fallback_allowed": ALLOW_DB_FALLBACK,
            "reason": "Host unreachable (Circuit breaker active)"
        }

    start_time = time.time()
    try:
        conn = get_connection(include_db=True)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 AS alive;")
                cursor.fetchone()
            latency_ms = round((time.time() - start_time) * 1000, 2)
            record_success()
            return {
                "connected": True,
                "host": DB_HOST,
                "port": DB_PORT,
                "database": DB_NAME,
                "driver": "PyMySQL",
                "latency_ms": latency_ms,
                "mode": "live_mysql",
                "fallback_allowed": ALLOW_DB_FALLBACK
            }
        finally:
            conn.close()
    except Exception as e:
        record_failure()
        return {
            "connected": False,
            "host": DB_HOST,
            "port": DB_PORT,
            "database": DB_NAME,
            "driver": "PyMySQL",
            "latency_ms": None,
            "mode": "offline_fallback" if ALLOW_DB_FALLBACK else "disconnected",
            "fallback_allowed": ALLOW_DB_FALLBACK,
            "reason": str(e)
        }


# ==============================================================================
# CONSULTATION REQUESTS (PRESERVED EXISTING FUNCTIONALITY)
# ==============================================================================

def _save_to_memory(reference_id, name, email, company, service, message):
    """Internal helper to persist to memory fallback store."""
    record = {
        "id": len(_memory_store) + 1,
        "reference_id": reference_id,
        "name": name,
        "email": email,
        "company": company,
        "service": service,
        "message": message,
        "status": "received",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    _memory_store.append(record)
    return {
        "success": True,
        "reference_id": reference_id,
        "storage": "fallback_store"
    }


def save_consultation(name, email, company, service, message):
    """
    Save a new consultation request using parameterized SQL queries.
    Preserves exact contract while ensuring resilient error handling.
    """
    ref_suffix = uuid.uuid4().hex[:8].upper()
    reference_id = f"ABC-{time.strftime('%Y%m')}-{ref_suffix}"

    if is_offline_cooldown():
        if not ALLOW_DB_FALLBACK:
            return {
                "success": False,
                "error": "Database service is offline and fallback is disabled in production.",
                "storage": "mysql"
            }
        return _save_to_memory(reference_id, name, email, company, service, message)

    try:
        conn = get_connection(include_db=True)
    except Exception as e:
        record_failure()
        logger.warning(f"MySQL connection unreachable: {e}")
        if not ALLOW_DB_FALLBACK:
            return {
                "success": False,
                "error": f"Database connection failed: {e}",
                "storage": "mysql"
            }
        return _save_to_memory(reference_id, name, email, company, service, message)

    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO consultation_requests 
                (reference_id, name, email, company, service, message, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'received')
            """
            cursor.execute(sql, (reference_id, name, email, company, service, message))
        conn.commit()
        record_success()
        return {
            "success": True,
            "reference_id": reference_id,
            "storage": "mysql"
        }
    except Exception as e:
        logger.error(f"Genuine MySQL execution error: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"MySQL execution error: {e}",
            "storage": "mysql"
        }
    finally:
        conn.close()


def get_consultations(limit=10):
    """Retrieve recent consultation requests (non-sensitive overview)."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT reference_id, company, service, status, created_at
                        FROM consultation_requests
                        ORDER BY id DESC LIMIT %s
                    """, (limit,))
                    rows = cursor.fetchall()
                    for row in rows:
                        if "created_at" in row and row["created_at"]:
                            row["created_at"] = str(row["created_at"])
                    record_success()
                    return rows
            finally:
                conn.close()
        except Exception:
            record_failure()

    return [
        {
            "reference_id": r["reference_id"],
            "company": r["company"],
            "service": r["service"],
            "status": r["status"],
            "created_at": r["created_at"]
        }
        for r in reversed(_memory_store[-limit:])
    ]


def get_consultations_count():
    """Return total count of consultation requests."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) AS total FROM consultation_requests")
                    res = cursor.fetchone()
                    record_success()
                    return res["total"] if res else 0
            finally:
                conn.close()
        except Exception:
            record_failure()

    return len(_memory_store)


# ==============================================================================
# UNIFIED PLATFORM: PROJECTS
# ==============================================================================

def get_projects():
    """Retrieve all onboarded projects."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM projects ORDER BY id ASC")
                    rows = cursor.fetchall()
                    for row in rows:
                        if "created_at" in row and row["created_at"]:
                            row["created_at"] = str(row["created_at"])
                        if "updated_at" in row and row["updated_at"]:
                            row["updated_at"] = str(row["updated_at"])
                    record_success()
                    return rows
            finally:
                conn.close()
        except Exception:
            record_failure()

    return list(_projects_store)


def get_project(project_id):
    """Retrieve single project by its project_id."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM projects WHERE project_id = %s LIMIT 1", (project_id,))
                    row = cursor.fetchone()
                    if row:
                        if "created_at" in row and row["created_at"]:
                            row["created_at"] = str(row["created_at"])
                        if "updated_at" in row and row["updated_at"]:
                            row["updated_at"] = str(row["updated_at"])
                        record_success()
                        return row
            finally:
                conn.close()
        except Exception:
            record_failure()

    for p in _projects_store:
        if p["project_id"] == project_id:
            return p
    return None


def create_project(name, repository, branch="main", app_type="Python / Flask", environment="Production", deployment_target="AWS EC2 via SSM"):
    """Create and persist a new onboarded project."""
    project_slug = name.lower().replace(" ", "-").replace("/", "-")
    rand_suffix = uuid.uuid4().hex[:6]
    project_id = f"proj-{project_slug}-{rand_suffix}"

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    project_record = {
        "project_id": project_id,
        "name": name,
        "repository": repository,
        "branch": branch,
        "app_type": app_type,
        "environment": environment,
        "deployment_target": deployment_target,
        "status": "active",
        "health_status": "healthy",
        "pipeline_status": "pending",
        "created_at": now_str,
        "updated_at": now_str
    }

    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO projects (project_id, name, repository, branch, app_type, environment, deployment_target, status, health_status, pipeline_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        project_id, name, repository, branch, app_type,
                        environment, deployment_target, "active", "healthy", "pending"
                    ))
                conn.commit()
                record_success()
                return {"success": True, "project": project_record, "storage": "mysql"}
            finally:
                conn.close()
        except Exception as e:
            record_failure()
            logger.warning(f"Failed to persist project to MySQL, saving to memory fallback: {e}")

    project_record["id"] = len(_projects_store) + 1
    _projects_store.append(project_record)
    return {"success": True, "project": project_record, "storage": "memory"}


# ==============================================================================
# UNIFIED PLATFORM: DEPLOYMENTS
# ==============================================================================

def get_deployments(limit=20):
    """Retrieve deployment history."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT d.*, p.name AS project_name
                        FROM deployments d
                        LEFT JOIN projects p ON d.project_id = p.project_id
                        ORDER BY d.id DESC LIMIT %s
                    """, (limit,))
                    rows = cursor.fetchall()
                    for row in rows:
                        if "start_time" in row and row["start_time"]:
                            row["start_time"] = str(row["start_time"])
                        if "created_at" in row and row["created_at"]:
                            row["created_at"] = str(row["created_at"])
                    record_success()
                    return rows
            finally:
                conn.close()
        except Exception:
            record_failure()

    res = []
    for d in reversed(_deployments_store[-limit:]):
        item = dict(d)
        item["project_name"] = "ABC Free Consultants" if item.get("project_id") == "proj-abc-demo" else item.get("project_id")
        res.append(item)
    return res


def get_latest_deployment():
    """Retrieve the single most recent deployment."""
    deployments = get_deployments(limit=1)
    return deployments[0] if deployments else None


def create_deployment(project_id, commit_hash, commit_message, branch="main", environment="Production",
                      status="SUCCESS", duration_seconds=180, target_instance="i-0fb9dcbeb35b4fdbe",
                      ecr_image="850252650249.dkr.ecr.ap-south-1.amazonaws.com/devsecops-platform:latest",
                      deployed_by="Platform UI Trigger", logs="Deployment initiated via unified platform."):
    """Record a new deployment event."""
    deployment_id = f"DEP-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    dep_record = {
        "deployment_id": deployment_id,
        "project_id": project_id,
        "commit_hash": commit_hash,
        "commit_message": commit_message,
        "branch": branch,
        "environment": environment,
        "status": status,
        "start_time": now_str,
        "duration_seconds": duration_seconds,
        "deployed_by": deployed_by,
        "target_instance": target_instance,
        "ecr_image": ecr_image,
        "logs": logs,
        "created_at": now_str
    }

    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO deployments (deployment_id, project_id, commit_hash, commit_message, branch, environment, status, duration_seconds, deployed_by, target_instance, ecr_image, logs)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        deployment_id, project_id, commit_hash, commit_message,
                        branch, environment, status, duration_seconds,
                        deployed_by, target_instance, ecr_image, logs
                    ))
                conn.commit()
                record_success()
                return {"success": True, "deployment": dep_record, "storage": "mysql"}
            finally:
                conn.close()
        except Exception as e:
            record_failure()
            logger.warning(f"Failed to persist deployment to MySQL: {e}")

    dep_record["id"] = len(_deployments_store) + 1
    _deployments_store.append(dep_record)
    return {"success": True, "deployment": dep_record, "storage": "memory"}


# ==============================================================================
# UNIFIED PLATFORM: PIPELINES
# ==============================================================================

def get_pipeline_runs(limit=10):
    """Retrieve recent pipeline execution runs."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT %s
                    """, (limit,))
                    rows = cursor.fetchall()
                    for row in rows:
                        if "created_at" in row and row["created_at"]:
                            row["created_at"] = str(row["created_at"])
                        if isinstance(row.get("stages_json"), str):
                            try:
                                row["stages"] = json.loads(row["stages_json"])
                            except Exception:
                                row["stages"] = []
                    record_success()
                    return rows
            finally:
                conn.close()
        except Exception:
            record_failure()

    res = []
    for p in reversed(_pipeline_store[-limit:]):
        item = dict(p)
        if isinstance(item.get("stages_json"), str):
            try:
                item["stages"] = json.loads(item["stages_json"])
            except Exception:
                item["stages"] = []
        res.append(item)
    return res


def get_latest_pipeline_run():
    """Retrieve the single most recent pipeline run."""
    runs = get_pipeline_runs(limit=1)
    return runs[0] if runs else None


def create_pipeline_run(project_id, commit_hash, branch="main", status="SUCCESS", stages=None, triggered_by="Platform Execution", duration_seconds=120):
    """Save a new pipeline run."""
    run_id = f"RUN-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    stages_json = json.dumps(stages or [])

    run_record = {
        "run_id": run_id,
        "project_id": project_id,
        "commit_hash": commit_hash,
        "branch": branch,
        "status": status,
        "stages_json": stages_json,
        "stages": stages or [],
        "triggered_by": triggered_by,
        "duration_seconds": duration_seconds,
        "created_at": now_str
    }

    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO pipeline_runs (run_id, project_id, commit_hash, branch, status, stages_json, triggered_by, duration_seconds)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        run_id, project_id, commit_hash, branch,
                        status, stages_json, triggered_by, duration_seconds
                    ))
                conn.commit()
                record_success()
                return {"success": True, "pipeline_run": run_record, "storage": "mysql"}
            finally:
                conn.close()
        except Exception as e:
            record_failure()
            logger.warning(f"Failed to persist pipeline run to MySQL: {e}")

    run_record["id"] = len(_pipeline_store) + 1
    _pipeline_store.append(run_record)
    return {"success": True, "pipeline_run": run_record, "storage": "memory"}


# ==============================================================================
# UNIFIED PLATFORM: SECURITY SCANS
# ==============================================================================

def get_security_scans(limit=10):
    """Retrieve security scan reports."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT * FROM security_scans ORDER BY id DESC LIMIT %s
                    """, (limit,))
                    rows = cursor.fetchall()
                    for row in rows:
                        if "scanned_at" in row and row["scanned_at"]:
                            row["scanned_at"] = str(row["scanned_at"])
                        if isinstance(row.get("details_json"), str):
                            try:
                                row["details"] = json.loads(row["details_json"])
                            except Exception:
                                row["details"] = {}
                    record_success()
                    return rows
            finally:
                conn.close()
        except Exception:
            record_failure()

    res = []
    for s in reversed(_security_store[-limit:]):
        item = dict(s)
        if isinstance(item.get("details_json"), str):
            try:
                item["details"] = json.loads(item["details_json"])
            except Exception:
                item["details"] = {}
        res.append(item)
    return res


def get_latest_security_scan():
    """Retrieve latest security scan."""
    scans = get_security_scans(limit=1)
    return scans[0] if scans else None


def save_security_scan(project_id, scanner, scan_type, status, critical_count, high_count, medium_count, low_count, details):
    """Persist a new security scan."""
    scan_id = f"SCAN-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    details_json = json.dumps(details or {})

    scan_record = {
        "scan_id": scan_id,
        "project_id": project_id,
        "scanner": scanner,
        "scan_type": scan_type,
        "status": status,
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "details_json": details_json,
        "details": details or {},
        "scanned_at": now_str
    }

    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO security_scans (scan_id, project_id, scanner, scan_type, status, critical_count, high_count, medium_count, low_count, details_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        scan_id, project_id, scanner, scan_type, status,
                        critical_count, high_count, medium_count, low_count, details_json
                    ))
                conn.commit()
                record_success()
                return {"success": True, "scan": scan_record, "storage": "mysql"}
            finally:
                conn.close()
        except Exception as e:
            record_failure()
            logger.warning(f"Failed to persist security scan to MySQL: {e}")

    scan_record["id"] = len(_security_store) + 1
    _security_store.append(scan_record)
    return {"success": True, "scan": scan_record, "storage": "memory"}


# ==============================================================================
# UNIFIED PLATFORM: ENVIRONMENTS
# ==============================================================================

def get_environments():
    """Retrieve configured deployment environments."""
    if not is_offline_cooldown():
        try:
            conn = get_connection(include_db=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM environments ORDER BY id ASC")
                    rows = cursor.fetchall()
                    for row in rows:
                        if "created_at" in row and row["created_at"]:
                            row["created_at"] = str(row["created_at"])
                    record_success()
                    if rows:
                        return rows
            finally:
                conn.close()
        except Exception:
            record_failure()

    return list(_environments_store)
