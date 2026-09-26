import os
import time
import uuid
import logging
import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)

# Database Configuration with Environment Defaults
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
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
    Creates database and `consultation_requests` table with parameterized structure.
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
            conn.commit()
            record_success()
            logger.info("Database schema initialized successfully.")
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
    Does NOT mask genuine production database errors:
    - If in production (ALLOW_DB_FALLBACK=False), failures raise/return error.
    - If connection succeeds, SQL execution errors are never masked.
    - Offline fallback is only used for local tests/development.
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
    except pymysql.OperationalError as e:
        record_failure()
        logger.warning(f"MySQL connection unreachable: {e}")
        if not ALLOW_DB_FALLBACK:
            return {
                "success": False,
                "error": f"Database connection failed: {e}",
                "storage": "mysql"
            }
        return _save_to_memory(reference_id, name, email, company, service, message)
    except Exception as e:
        record_failure()
        logger.error(f"Unexpected database connection error: {e}")
        if not ALLOW_DB_FALLBACK:
            return {
                "success": False,
                "error": f"Database connection error: {e}",
                "storage": "mysql"
            }
        return _save_to_memory(reference_id, name, email, company, service, message)

    # Connection succeeded -> execute parameterized query
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
        # Genuine database execution error (constraint violation, table locked, syntax error)
        # NEVER mask genuine execution errors
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

    # Return fallback records
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
