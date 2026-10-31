#!/usr/bin/env bash
# ==============================================================================
# Production-Conscious Blue/Green Deployment Script
# Project: Cloud-Based DevSecOps Platform
# Repository: mohdshahid7033/cloud-devsecops-platform
#
# ARCHITECTURE & NETWORKING:
# - Two application slots: devsecops-app-blue and devsecops-app-green.
# - Both slots attach to devsecops-network bridge.
# - Nginx routes traffic via Docker internal DNS (http://devsecops-app-(blue|green):5000).
# - Application host ports are NOT exposed unnecessarily.
# - Nginx configuration is modular: /etc/nginx/conf.d/upstream.conf defines app_backend.
# - Pre-switch health check runs from Nginx container across devsecops-network.
# - Atomic in-memory traffic switch performed via 'nginx -s reload'.
#
# DATABASE MIGRATION POLICY (EXPAND / CONTRACT):
# - Both blue and green slots share the same live MySQL database (devsecops-mysql).
# - Automatic destructive migrations (DROP, ALTER, RENAME) MUST NEVER be run during deployment.
# - Phase 1 (Expand): Schema migrations must be backward-compatible and additive only
#   (e.g., adding nullable columns, new tables).
# - Phase 2 (Deploy): Traffic switches from active to candidate release.
# - Phase 3 (Contract): Obsolete columns/tables are removed in a separate maintenance
#   migration only after the previous slot is retired.
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Configuration & Configurable Overrides (for testing & production)
# ------------------------------------------------------------------------------
DEPLOY_IMAGE="${1:-${DEPLOY_IMAGE:-}}"

DOCKER_CMD="${DOCKER_CMD:-docker}"
CURL_CMD="${CURL_CMD:-curl}"
JQ_CMD="${JQ_CMD:-jq}"

NGINX_CONTAINER="${NGINX_CONTAINER:-devsecops-nginx}"
NETWORK_NAME="${NETWORK_NAME:-devsecops-network}"
APP_PORT="${APP_PORT:-5000}"
HEALTH_URL="${HEALTH_URL:-http://localhost/health}"

PROBE_TIMEOUT_SECS="${PROBE_TIMEOUT_SECS:-30}"
POST_SWITCH_TIMEOUT_SECS="${POST_SWITCH_TIMEOUT_SECS:-30}"

SLOT_BLUE="devsecops-app-blue"
SLOT_GREEN="devsecops-app-green"

CANDIDATE_CONTAINER=""
ACTIVE_CONTAINER=""
CANDIDATE_SLOT=""
ACTIVE_SLOT=""
SWITCH_PERFORMED=false
CANDIDATE_CREATED=false
PRIOR_ROUTING_CONFIG=""

DEPLOY_LOCK_PATH="${DEPLOY_LOCK_PATH:-/tmp/devsecops-deploy.lock}"
LOCK_ACQUIRED=false

# ------------------------------------------------------------------------------
# Logging Helpers (Strictly avoids logging secrets)
# ------------------------------------------------------------------------------
log_info() {
    echo "[INFO] $(date +'%Y-%m-%d %H:%M:%S') - $*"
}

log_warn() {
    echo "[WARN] $(date +'%Y-%m-%d %H:%M:%S') - $*" >&2
}

log_error() {
    echo "[ERROR] $(date +'%Y-%m-%d %H:%M:%S') - $*" >&2
}

# ------------------------------------------------------------------------------
# Atomic Deployment Lock Helpers
# ------------------------------------------------------------------------------
acquire_lock() {
    if command -v flock >/dev/null 2>&1; then
        exec 200>"$DEPLOY_LOCK_PATH"
        if ! flock -n 200; then
            log_error "Concurrent deployment detected: exclusive lock already held on '$DEPLOY_LOCK_PATH'. Aborting."
            exit 1
        fi
        LOCK_ACQUIRED=true
    else
        # POSIX mkdir atomic directory lock fallback
        local lock_dir="${DEPLOY_LOCK_PATH}.d"
        if ! mkdir "$lock_dir" 2>/dev/null; then
            local existing_pid
            existing_pid=$(cat "$lock_dir/pid" 2>/dev/null || true)
            if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
                log_error "Concurrent deployment detected: lock held by active PID $existing_pid ('$lock_dir'). Aborting."
                exit 1
            else
                log_warn "Detected stale deployment lock from inactive PID (${existing_pid:-unknown}). Reclaiming lock..."
                rm -rf "$lock_dir"
                if ! mkdir "$lock_dir" 2>/dev/null; then
                    log_error "Failed to acquire deployment lock at '$lock_dir'. Aborting."
                    exit 1
                fi
            fi
        fi
        echo "$$" > "$lock_dir/pid"
        LOCK_ACQUIRED=true
    fi
    log_info "Acquired exclusive deployment lock."
}

release_lock() {
    if [ "$LOCK_ACQUIRED" = true ]; then
        if command -v flock >/dev/null 2>&1; then
            flock -u 200 2>/dev/null || true
            rm -f "$DEPLOY_LOCK_PATH" 2>/dev/null || true
        else
            rm -rf "${DEPLOY_LOCK_PATH}.d" 2>/dev/null || true
        fi
        LOCK_ACQUIRED=false
        log_info "Released exclusive deployment lock."
    fi
}

# ------------------------------------------------------------------------------
# Error and Signal Trap Handlers
# ------------------------------------------------------------------------------
cleanup_on_exit() {
    local exit_code=$?
    if [ "$SWITCH_PERFORMED" = false ] && [ "$CANDIDATE_CREATED" = true ] && [ -n "$CANDIDATE_CONTAINER" ]; then
        # Guard: Never remove active production container or core infra containers
        if [ "$CANDIDATE_CONTAINER" != "$ACTIVE_CONTAINER" ] && \
           [ "$CANDIDATE_CONTAINER" != "$NGINX_CONTAINER" ] && \
           [ "$CANDIDATE_CONTAINER" != "devsecops-mysql" ]; then
            # Verify candidate container is not in live upstream before stopping
            local cur_up
            cur_up=$($DOCKER_CMD exec "$NGINX_CONTAINER" cat /etc/nginx/conf.d/upstream.conf 2>/dev/null | sed -e 's/#.*//' || true)
            if ! echo "$cur_up" | grep -E -q "^[[:space:]]*server[[:space:]]+${CANDIDATE_CONTAINER}(:[0-9]+)?;" ; then
                log_warn "Deployment terminated before switch. Cleaning up candidate container '$CANDIDATE_CONTAINER'..."
                $DOCKER_CMD stop "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
                $DOCKER_CMD rm -f "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
            else
                log_warn "Candidate '$CANDIDATE_CONTAINER' appears in live upstream. Skipping removal to avoid disruption."
            fi
        fi
    fi
    release_lock
    exit "$exit_code"
}

trap cleanup_on_exit EXIT INT TERM

# ------------------------------------------------------------------------------
# 1. Parameter Validation & Lock Acquisition
# ------------------------------------------------------------------------------
if [ -z "$DEPLOY_IMAGE" ]; then
    log_error "Missing required parameter: DEPLOY_IMAGE. Usage: $0 <deploy-image>"
    exit 1
fi

acquire_lock

log_info "Initiating Blue/Green deployment for image: $DEPLOY_IMAGE"

# ------------------------------------------------------------------------------
# 2. Inspect Nginx and Determine Active / Inactive Slots
# ------------------------------------------------------------------------------
if ! $DOCKER_CMD ps --filter "name=^/${NGINX_CONTAINER}$" --format '{{.Names}}' | grep -q "^${NGINX_CONTAINER}$"; then
    log_error "Reverse proxy container '$NGINX_CONTAINER' is not running. Cannot proceed."
    exit 1
fi

UPSTREAM_CONF=$($DOCKER_CMD exec "$NGINX_CONTAINER" cat /etc/nginx/conf.d/upstream.conf 2>/dev/null || true)
CLEAN_UPSTREAM=$(echo "$UPSTREAM_CONF" | sed -e 's/#.*//')

if [ -n "$(echo "$CLEAN_UPSTREAM" | tr -d '[:space:]')" ]; then
    HAS_BLUE=false
    HAS_GREEN=false
    HAS_LEGACY_DEVSECOPS=false
    HAS_LEGACY_APP=false

    # Parse recognized active upstream server directives strictly
    if echo "$CLEAN_UPSTREAM" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app-blue(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        HAS_BLUE=true
    fi
    if echo "$CLEAN_UPSTREAM" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app-green(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        HAS_GREEN=true
    fi
    if echo "$CLEAN_UPSTREAM" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        HAS_LEGACY_DEVSECOPS=true
    fi
    if echo "$CLEAN_UPSTREAM" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+app(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        HAS_LEGACY_APP=true
    fi

    UPSTREAM_MATCHES=0
    [ "$HAS_BLUE" = true ] && UPSTREAM_MATCHES=$((UPSTREAM_MATCHES + 1))
    [ "$HAS_GREEN" = true ] && UPSTREAM_MATCHES=$((UPSTREAM_MATCHES + 1))
    [ "$HAS_LEGACY_DEVSECOPS" = true ] && UPSTREAM_MATCHES=$((UPSTREAM_MATCHES + 1))
    [ "$HAS_LEGACY_APP" = true ] && UPSTREAM_MATCHES=$((UPSTREAM_MATCHES + 1))

    if [ "$UPSTREAM_MATCHES" -gt 1 ]; then
        if [ "$HAS_BLUE" = true ] && [ "$HAS_GREEN" = true ]; then
            log_error "Ambiguous upstream configuration: both '$SLOT_BLUE' and '$SLOT_GREEN' found in /etc/nginx/conf.d/upstream.conf."
        else
            log_error "Ambiguous upstream configuration: multiple active backend server directives found in /etc/nginx/conf.d/upstream.conf."
        fi
        log_error "Aborting deployment to avoid split-brain or unintended routing state."
        exit 1
    elif [ "$HAS_BLUE" = true ]; then
        ACTIVE_SLOT="blue"
        ACTIVE_CONTAINER="$SLOT_BLUE"
        CANDIDATE_SLOT="green"
        CANDIDATE_CONTAINER="$SLOT_GREEN"
        PRIOR_ROUTING_CONFIG="$UPSTREAM_CONF"
    elif [ "$HAS_GREEN" = true ]; then
        ACTIVE_SLOT="green"
        ACTIVE_CONTAINER="$SLOT_GREEN"
        CANDIDATE_SLOT="blue"
        CANDIDATE_CONTAINER="$SLOT_BLUE"
        PRIOR_ROUTING_CONFIG="$UPSTREAM_CONF"
    elif [ "$HAS_LEGACY_DEVSECOPS" = true ]; then
        log_info "Detected legacy single container 'devsecops-app' in modular upstream."
        ACTIVE_SLOT="legacy"
        ACTIVE_CONTAINER="devsecops-app"
        CANDIDATE_SLOT="blue"
        CANDIDATE_CONTAINER="$SLOT_BLUE"
        PRIOR_ROUTING_CONFIG="$UPSTREAM_CONF"
    elif [ "$HAS_LEGACY_APP" = true ]; then
        log_info "Detected legacy alias 'app' in modular upstream."
        ACTIVE_SLOT="legacy"
        ACTIVE_CONTAINER="devsecops-app"
        CANDIDATE_SLOT="blue"
        CANDIDATE_CONTAINER="$SLOT_BLUE"
        PRIOR_ROUTING_CONFIG="$UPSTREAM_CONF"
    else
        log_error "Unknown active upstream configuration in /etc/nginx/conf.d/upstream.conf: '$UPSTREAM_CONF'"
        exit 1
    fi
else
    # /etc/nginx/conf.d/upstream.conf is missing or empty.
    # Inspect the actual running Nginx configuration to determine the active production route.
    log_info "No modular /etc/nginx/conf.d/upstream.conf found. Inspecting active runtime Nginx configuration..."
    NGINX_ACTIVE_CONF=$($DOCKER_CMD exec "$NGINX_CONTAINER" nginx -T 2>/dev/null || $DOCKER_CMD exec "$NGINX_CONTAINER" cat /etc/nginx/nginx.conf 2>/dev/null || true)
    CLEAN_RUNTIME_CONF=$(echo "$NGINX_ACTIVE_CONF" | sed -e 's/#.*//')

    RT_BLUE=false
    RT_GREEN=false
    RT_LEGACY_DEVSECOPS=false
    RT_LEGACY_APP=false

    # Check active server directives (inside upstream blocks)
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app-blue(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        RT_BLUE=true
    fi
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app-green(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        RT_GREEN=true
    fi
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+devsecops-app(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        RT_LEGACY_DEVSECOPS=true
    fi
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])server[[:space:]]+app(:[0-9]+)?([[:space:]]+[^;]*)?;'; then
        RT_LEGACY_APP=true
    fi

    # Check direct proxy_pass directives (outside upstream blocks)
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://devsecops-app-blue(:[0-9]+)?/?;'; then
        RT_BLUE=true
    fi
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://devsecops-app-green(:[0-9]+)?/?;'; then
        RT_GREEN=true
    fi
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://devsecops-app(:[0-9]+)?/?;'; then
        RT_LEGACY_DEVSECOPS=true
    fi
    if echo "$CLEAN_RUNTIME_CONF" | grep -E -q '(^|[[:space:];{}])proxy_pass[[:space:]]+http://app(:[0-9]+)?/?;'; then
        RT_LEGACY_APP=true
    fi

    RT_MATCH_COUNT=0
    [ "$RT_BLUE" = true ] && RT_MATCH_COUNT=$((RT_MATCH_COUNT + 1))
    [ "$RT_GREEN" = true ] && RT_MATCH_COUNT=$((RT_MATCH_COUNT + 1))
    [ "$RT_LEGACY_DEVSECOPS" = true ] && RT_MATCH_COUNT=$((RT_MATCH_COUNT + 1))
    [ "$RT_LEGACY_APP" = true ] && RT_MATCH_COUNT=$((RT_MATCH_COUNT + 1))

    if [ "$RT_MATCH_COUNT" -gt 1 ]; then
        log_error "Ambiguous active production route detected across Nginx runtime configuration ($RT_MATCH_COUNT conflicting matches found)."
        log_error "Aborting deployment to avoid split-brain or unintended routing state."
        exit 1
    elif [ "$RT_BLUE" = true ]; then
        log_info "Discovered active blue slot route in Nginx runtime configuration."
        ACTIVE_SLOT="blue"
        ACTIVE_CONTAINER="$SLOT_BLUE"
        CANDIDATE_SLOT="green"
        CANDIDATE_CONTAINER="$SLOT_GREEN"
        PRIOR_ROUTING_CONFIG="upstream app_backend {
    server ${SLOT_BLUE}:${APP_PORT};
}
"
    elif [ "$RT_GREEN" = true ]; then
        log_info "Discovered active green slot route in Nginx runtime configuration."
        ACTIVE_SLOT="green"
        ACTIVE_CONTAINER="$SLOT_GREEN"
        CANDIDATE_SLOT="blue"
        CANDIDATE_CONTAINER="$SLOT_BLUE"
        PRIOR_ROUTING_CONFIG="upstream app_backend {
    server ${SLOT_GREEN}:${APP_PORT};
}
"
    elif [ "$RT_LEGACY_DEVSECOPS" = true ]; then
        log_info "Discovered legacy active container route ('devsecops-app') in Nginx runtime configuration."
        ACTIVE_SLOT="legacy"
        ACTIVE_CONTAINER="devsecops-app"
        CANDIDATE_SLOT="blue"
        CANDIDATE_CONTAINER="$SLOT_BLUE"
        PRIOR_ROUTING_CONFIG="upstream app_backend {
    server devsecops-app:${APP_PORT};
}
"
    elif [ "$RT_LEGACY_APP" = true ]; then
        log_info "Discovered legacy active container route ('app') in Nginx runtime configuration."
        ACTIVE_SLOT="legacy"
        ACTIVE_CONTAINER="devsecops-app"
        CANDIDATE_SLOT="blue"
        CANDIDATE_CONTAINER="$SLOT_BLUE"
        PRIOR_ROUTING_CONFIG="upstream app_backend {
    server app:${APP_PORT};
}
"
    else
        log_error "Unable to unambiguously identify active production route from Nginx configuration."
        log_error "Aborting deployment before modifying any routing or container state."
        exit 1
    fi
fi

log_info "Current active slot      : ${ACTIVE_SLOT} (${ACTIVE_CONTAINER:-none})"
log_info "Target candidate slot    : ${CANDIDATE_SLOT} (${CANDIDATE_CONTAINER})"

# ------------------------------------------------------------------------------
# 3. Resolve Database Credentials Safely (No Secret Logging)
# ------------------------------------------------------------------------------
DB_HOST="${DB_HOST:-}"
DB_NAME="${DB_NAME:-}"
DB_USER="${DB_USER:-}"
DB_PASSWORD="${DB_PASSWORD:-}"

# If not set in environment, attempt to read from SSM Parameter Store if AWS CLI is present
if [ -z "$DB_PASSWORD" ] && command -v aws >/dev/null 2>&1; then
    AWS_REGION="${AWS_REGION:-ap-south-1}"
    log_info "Fetching database parameters from AWS SSM Parameter Store ($AWS_REGION)..."
    DB_NAME=$(aws ssm get-parameter --name "/devsecops/db_name" --query "Parameter.Value" --output text --region "$AWS_REGION" 2>/dev/null || true)
    DB_USER=$(aws ssm get-parameter --name "/devsecops/db_user" --query "Parameter.Value" --output text --region "$AWS_REGION" 2>/dev/null || true)
    DB_PASSWORD=$(aws ssm get-parameter --name "/devsecops/db_password" --with-decryption --query "Parameter.Value" --output text --region "$AWS_REGION" 2>/dev/null || true)
fi

# Fallback: inspect existing running container in-memory if still empty
if [ -z "$DB_PASSWORD" ] && [ -n "$ACTIVE_CONTAINER" ]; then
    INSPECT_ENV=$($DOCKER_CMD inspect "$ACTIVE_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null || true)
    if [ -z "$DB_HOST" ]; then
        DB_HOST=$(echo "$INSPECT_ENV" | grep '^DB_HOST=' | cut -d= -f2- || true)
    fi
    if [ -z "$DB_NAME" ]; then
        DB_NAME=$(echo "$INSPECT_ENV" | grep '^DB_NAME=' | cut -d= -f2- || true)
    fi
    if [ -z "$DB_USER" ]; then
        DB_USER=$(echo "$INSPECT_ENV" | grep '^DB_USER=' | cut -d= -f2- || true)
    fi
    if [ -z "$DB_PASSWORD" ]; then
        DB_PASSWORD=$(echo "$INSPECT_ENV" | grep '^DB_PASSWORD=' | cut -d= -f2- || true)
    fi
fi

# Apply safe defaults for local prototype if not otherwise set
DB_HOST="${DB_HOST:-devsecops-mysql}"
DB_NAME="${DB_NAME:-devsecops_db}"
DB_USER="${DB_USER:-devsecops_user}"

if [ -z "$DB_PASSWORD" ]; then
    log_error "DB_PASSWORD could not be resolved from SSM or container environment. Cannot deploy."
    exit 1
fi

# ------------------------------------------------------------------------------
# 4. Pull Deployment Image and Launch Candidate Slot
# ------------------------------------------------------------------------------
log_info "Pulling image: $DEPLOY_IMAGE"
if ! $DOCKER_CMD pull "$DEPLOY_IMAGE"; then
    log_error "Failed to pull image: $DEPLOY_IMAGE. Active slot '$ACTIVE_CONTAINER' remains untouched."
    exit 1
fi

log_info "Preparing candidate slot container '$CANDIDATE_CONTAINER'..."
if [ "$CANDIDATE_CONTAINER" = "$ACTIVE_CONTAINER" ]; then
    log_error "Safety check failure: Candidate container '$CANDIDATE_CONTAINER' matches active container! Aborting."
    exit 1
fi
if [ "$CANDIDATE_CONTAINER" = "$NGINX_CONTAINER" ] || [ "$CANDIDATE_CONTAINER" = "devsecops-mysql" ]; then
    log_error "Safety check failure: Candidate container cannot be core infrastructure '$CANDIDATE_CONTAINER'! Aborting."
    exit 1
fi

# Pre-stop protection: Verify candidate is NOT actively receiving production traffic right now!
LIVE_CHECK_CONF=$($DOCKER_CMD exec "$NGINX_CONTAINER" nginx -T 2>/dev/null || $DOCKER_CMD exec "$NGINX_CONTAINER" cat /etc/nginx/nginx.conf 2>/dev/null || true)
LIVE_CLEAN_CHECK=$(echo "$LIVE_CHECK_CONF" | sed -e 's/#.*//')
if echo "$LIVE_CLEAN_CHECK" | grep -E -q "(^|[[:space:];{}])(server|proxy_pass)[[:space:]]+(http://)?${CANDIDATE_CONTAINER}(:[0-9]+)?([[:space:]]+[^;]*)?;"; then
    log_error "CRITICAL SAFETY VIOLATION: Candidate container '$CANDIDATE_CONTAINER' is actively referenced in Nginx live routing!"
    log_error "Aborting immediately without stopping or removing '$CANDIDATE_CONTAINER' to protect production traffic."
    exit 1
fi

$DOCKER_CMD stop "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
$DOCKER_CMD rm -f "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true

# Start candidate container on devsecops-network (WITHOUT stopping active slot!)
log_info "Starting candidate container '$CANDIDATE_CONTAINER' on network '$NETWORK_NAME'..."
if ! $DOCKER_CMD run -d \
    --name "$CANDIDATE_CONTAINER" \
    --network "$NETWORK_NAME" \
    --restart always \
    -e FLASK_ENV=production \
    -e APP_ENV="production-${CANDIDATE_SLOT}" \
    -e DB_HOST="$DB_HOST" \
    -e DB_PORT=3306 \
    -e DB_NAME="$DB_NAME" \
    -e DB_USER="$DB_USER" \
    -e DB_PASSWORD="$DB_PASSWORD" \
    "$DEPLOY_IMAGE" >/dev/null; then
    log_error "Failed to start candidate container '$CANDIDATE_CONTAINER'. Active slot '$ACTIVE_CONTAINER' remains untouched."
    exit 1
fi
CANDIDATE_CREATED=true

# ------------------------------------------------------------------------------
# 5. Candidate Bridge-Network Health & Database Connectivity Verification
# ------------------------------------------------------------------------------
log_info "Verifying candidate '$CANDIDATE_CONTAINER' health from reverse proxy perspective..."
CANDIDATE_HEALTHY=false
START_TIME=$(date +%s)
DEADLINE=$((START_TIME + PROBE_TIMEOUT_SECS))

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    PROBE_OUTPUT=$($DOCKER_CMD exec "$NGINX_CONTAINER" wget -qO- --timeout=3 "http://${CANDIDATE_CONTAINER}:${APP_PORT}/health" 2>/dev/null || true)
    if [ -n "$PROBE_OUTPUT" ]; then
        STATUS=""
        DB_CONN=""
        DB_MODE=""
        if command -v "$JQ_CMD" >/dev/null 2>&1; then
            STATUS=$(echo "$PROBE_OUTPUT" | $JQ_CMD -r '.status // empty' 2>/dev/null || true)
            DB_CONN=$(echo "$PROBE_OUTPUT" | $JQ_CMD -r '.database.connected // empty' 2>/dev/null || true)
            DB_MODE=$(echo "$PROBE_OUTPUT" | $JQ_CMD -r '.database.mode // empty' 2>/dev/null || true)
        else
            # Python fallback for JSON parsing if jq is absent
            PARSED=$(python -c '
import sys, json
try:
    d = json.loads(sys.argv[1])
    st = d.get("status", "")
    db = d.get("database", {})
    conn = str(db.get("connected", "")).lower()
    mode = db.get("mode", "")
    print(f"{st} {conn} {mode}")
except Exception:
    pass
' "$PROBE_OUTPUT" 2>/dev/null || true)
            STATUS=$(echo "$PARSED" | awk '{print $1}')
            DB_CONN=$(echo "$PARSED" | awk '{print $2}')
            DB_MODE=$(echo "$PARSED" | awk '{print $3}')
        fi
        DB_CONN=$(echo "$DB_CONN" | tr '[:upper:]' '[:lower:]')

        if [ "$STATUS" = "healthy" ] && [ "$DB_CONN" = "true" ] && [ "$DB_MODE" = "live_mysql" ]; then
            CANDIDATE_HEALTHY=true
            log_info "Candidate '$CANDIDATE_CONTAINER' successfully passed health check (status=healthy, db_connected=true, mode=live_mysql)."
            break
        fi
    fi
    sleep 2
done

if [ "$CANDIDATE_HEALTHY" != true ]; then
    log_error "Candidate pre-switch health check FAILED within ${PROBE_TIMEOUT_SECS}s timeout."
    log_error "Candidate was either unresponsive or failed database connectivity (expected status=healthy, connected=true, mode=live_mysql)."
    log_info "Aborting deployment. Active slot '$ACTIVE_CONTAINER' continues serving traffic without impact."
    $DOCKER_CMD stop "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
    $DOCKER_CMD rm -f "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
    exit 1
fi

# ------------------------------------------------------------------------------
# 6. Candidate Nginx Configuration Generation & Isolated Pre-Switch Validation
# ------------------------------------------------------------------------------
log_info "Validating candidate Nginx configuration in isolated directory (preventing wildcard collisions)..."

CANDIDATE_UPSTREAM_CONTENT="upstream app_backend {
    server ${CANDIDATE_CONTAINER}:${APP_PORT};
}
"

# 1. Clean and prepare scratch validation directory outside /etc/nginx/conf.d/
$DOCKER_CMD exec "$NGINX_CONTAINER" rm -rf /tmp/nginx-validate
$DOCKER_CMD exec "$NGINX_CONTAINER" mkdir -p /tmp/nginx-validate/conf.d

# 2. Replicate base Nginx configs
$DOCKER_CMD exec "$NGINX_CONTAINER" cp /etc/nginx/nginx.conf /tmp/nginx-validate/nginx.conf

# Replicate any existing conf.d configurations (e.g. app.conf, default.conf) except upstream.conf
$DOCKER_CMD exec "$NGINX_CONTAINER" sh -c '
    for f in /etc/nginx/conf.d/*.conf; do
        if [ -f "$f" ] && [ "$(basename "$f")" != "upstream.conf" ]; then
            cp "$f" /tmp/nginx-validate/conf.d/
        fi
    done
'

# 3. Write candidate upstream into test directory
printf "%s" "$CANDIDATE_UPSTREAM_CONTENT" | $DOCKER_CMD exec -i "$NGINX_CONTAINER" sh -c "cat > /tmp/nginx-validate/conf.d/upstream.conf"

# 4. Point validation nginx.conf to test conf.d
$DOCKER_CMD exec "$NGINX_CONTAINER" sed -i 's|/etc/nginx/conf.d/|/tmp/nginx-validate/conf.d/|g' /tmp/nginx-validate/nginx.conf

# 5. Run nginx -t against candidate config
if ! $DOCKER_CMD exec "$NGINX_CONTAINER" nginx -t -c /tmp/nginx-validate/nginx.conf >/dev/null 2>&1; then
    log_error "Candidate Nginx configuration validation FAILED syntax check. Aborting traffic switch."
    $DOCKER_CMD exec "$NGINX_CONTAINER" rm -rf /tmp/nginx-validate
    $DOCKER_CMD stop "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
    $DOCKER_CMD rm -f "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
    exit 1
fi

$DOCKER_CMD exec "$NGINX_CONTAINER" rm -rf /tmp/nginx-validate
log_info "Candidate Nginx configuration successfully validated."

# ------------------------------------------------------------------------------
# 7. Rollback Helper Function
# ------------------------------------------------------------------------------
perform_rollback() {
    local reason="$1"
    log_error "TRIGGERING AUTOMATED ROLLBACK: $reason"

    if $DOCKER_CMD exec "$NGINX_CONTAINER" test -s /etc/nginx/upstream.conf.previous; then
        log_info "Restoring known-good configuration from /etc/nginx/upstream.conf.previous..."
        $DOCKER_CMD exec -i "$NGINX_CONTAINER" sh -c "cat /etc/nginx/upstream.conf.previous > /etc/nginx/conf.d/upstream.conf"

        if ! $DOCKER_CMD exec "$NGINX_CONTAINER" nginx -t >/dev/null 2>&1; then
            log_error "CRITICAL: Restored Nginx configuration failed syntax validation! Manual intervention required!"
            exit 2
        fi

        if ! $DOCKER_CMD exec "$NGINX_CONTAINER" nginx -s reload >/dev/null 2>&1; then
            log_error "CRITICAL: Restored Nginx reload failed! Reverse proxy state uncertain!"
            exit 2
        fi

        log_info "Nginx restored to previous upstream. Verifying endpoint recovery..."
        sleep 2
        RECOVERY_OUTPUT=$($CURL_CMD -sf --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
        if echo "$RECOVERY_OUTPUT" | grep -q '"status":"healthy"' || echo "$RECOVERY_OUTPUT" | grep -q '"status": "healthy"'; then
            log_info "ROLLBACK VERIFIED: Production service successfully recovered and healthy on previous slot."
        else
            log_error "CRITICAL: Public health check failed after rollback! Manual investigation required!"
            exit 2
        fi
    else
        log_error "CRITICAL: No non-empty previous upstream configuration backup found (/etc/nginx/upstream.conf.previous)!"
        exit 2
    fi

    # Clean up the failed candidate container
    log_info "Cleaning up failed candidate container '$CANDIDATE_CONTAINER'..."
    $DOCKER_CMD stop "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true
    $DOCKER_CMD rm -f "$CANDIDATE_CONTAINER" >/dev/null 2>&1 || true

    log_info "Automated rollback completed successfully."
    exit 1
}

# ------------------------------------------------------------------------------
# 8. Save Known-Good Backup and Execute Atomic Traffic Switch
# ------------------------------------------------------------------------------
if [ -z "$PRIOR_ROUTING_CONFIG" ]; then
    log_error "No verified prior routing configuration available for rollback. Refusing traffic cutover."
    exit 1
fi

if ! echo "$PRIOR_ROUTING_CONFIG" | grep -E -q 'server[[:space:]]+[a-zA-Z0-9_-]+(:[0-9]+)?;' ; then
    log_error "Prior routing configuration lacks valid upstream server definition. Refusing cutover."
    exit 1
fi

log_info "Preserving verified prior routing configuration to /etc/nginx/upstream.conf.previous..."
printf "%b" "$PRIOR_ROUTING_CONFIG" | $DOCKER_CMD exec -i "$NGINX_CONTAINER" sh -c "cat > /etc/nginx/upstream.conf.previous"

if ! $DOCKER_CMD exec "$NGINX_CONTAINER" test -s /etc/nginx/upstream.conf.previous; then
    log_error "Failed to verify /etc/nginx/upstream.conf.previous backup inside reverse proxy. Refusing cutover."
    exit 1
fi

log_info "Writing candidate upstream to /etc/nginx/conf.d/upstream.conf..."
printf "%b" "$CANDIDATE_UPSTREAM_CONTENT" | $DOCKER_CMD exec -i "$NGINX_CONTAINER" sh -c "cat > /etc/nginx/conf.d/upstream.conf"

log_info "Executing atomic traffic switch (nginx -s reload)..."
SWITCH_PERFORMED=true
if ! $DOCKER_CMD exec "$NGINX_CONTAINER" nginx -s reload; then
    perform_rollback "Nginx reload failed during traffic switch"
fi

# ------------------------------------------------------------------------------
# 9. Post-Switch Verification on Public Endpoint
# ------------------------------------------------------------------------------
log_info "Verifying post-switch public endpoint health at '$HEALTH_URL'..."
POST_SWITCH_HEALTHY=false
POST_DEADLINE=$(( $(date +%s) + POST_SWITCH_TIMEOUT_SECS ))

while [ "$(date +%s)" -lt "$POST_DEADLINE" ]; do
    POST_OUTPUT=$($CURL_CMD -sf --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
    if [ -n "$POST_OUTPUT" ]; then
        STATUS=""
        DB_CONN=""
        DB_MODE=""
        if command -v "$JQ_CMD" >/dev/null 2>&1; then
            STATUS=$(echo "$POST_OUTPUT" | $JQ_CMD -r '.status // empty' 2>/dev/null || true)
            DB_CONN=$(echo "$POST_OUTPUT" | $JQ_CMD -r '.database.connected // empty' 2>/dev/null || true)
            DB_MODE=$(echo "$POST_OUTPUT" | $JQ_CMD -r '.database.mode // empty' 2>/dev/null || true)
        else
            PARSED=$(python -c '
import sys, json
try:
    d = json.loads(sys.argv[1])
    st = d.get("status", "")
    db = d.get("database", {})
    conn = str(db.get("connected", "")).lower()
    mode = db.get("mode", "")
    print(f"{st} {conn} {mode}")
except Exception:
    pass
' "$POST_OUTPUT" 2>/dev/null || true)
            STATUS=$(echo "$PARSED" | awk '{print $1}')
            DB_CONN=$(echo "$PARSED" | awk '{print $2}')
            DB_MODE=$(echo "$PARSED" | awk '{print $3}')
        fi
        DB_CONN=$(echo "$DB_CONN" | tr '[:upper:]' '[:lower:]')

        if [ "$STATUS" = "healthy" ] && [ "$DB_CONN" = "true" ] && [ "$DB_MODE" = "live_mysql" ]; then
            POST_SWITCH_HEALTHY=true
            break
        fi
    fi
    sleep 2
done

if [ "$POST_SWITCH_HEALTHY" != true ]; then
    perform_rollback "Post-switch public health check failed within ${POST_SWITCH_TIMEOUT_SECS}s timeout"
fi

# ------------------------------------------------------------------------------
# 10. Deployment Succeeded - Retain Previous Slot in Standby
# ------------------------------------------------------------------------------
log_info "=================================================================="
log_info "BLUE/GREEN DEPLOYMENT COMPLETED SUCCESSFULLY!"
log_info "Active slot is now: ${CANDIDATE_SLOT} (${CANDIDATE_CONTAINER})"
if [ -n "$ACTIVE_CONTAINER" ]; then
    log_info "Previous slot (${ACTIVE_CONTAINER}) remains RUNNING in standby."
    log_info "Instant emergency rollback remains available via Nginx upstream restore."
fi
log_info "=================================================================="
exit 0
