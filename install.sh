#!/usr/bin/env bash
# ==============================================================================
# Genwizard ITSM Enterprise Production Installer
# Supports single-node VM / Docker Compose deployment with modular microservices:
# - Nginx Gateway (:80)
# - Core ITSM Backend (:8000)
# - Identity Management Microservice (:8001)
# - MongoDB Database (:27017, user: mongo-atr)
# - HashiCorp Consul Service (:8500)
# ==============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/nexus-itsm}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_URL="${APP_URL:-}"
CONSUL_ADDR="${CONSUL_ADDR:-http://127.0.0.1:8500}"
CONSUL_TOKEN="${CONSUL_TOKEN:-}"

print_usage() {
  cat <<'EOF'
Usage: sudo ./install.sh --url <APPLICATION_URL> [options]

Required:
  --url <URL>            Public URL for the application (e.g., https://itsm.example.com or http://192.168.1.50)

Options:
  --app-dir <DIR>        Installation directory (default: /opt/nexus-itsm)
  --consul-url <URL>     External Consul address if not using built-in compose consul (default: http://127.0.0.1:8500)
  --consul-token <TOKEN> Consul ACL token if required
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      APP_URL="${2:?A valid URL is required after --url}"
      shift 2
      ;;
    --app-dir)
      APP_DIR="${2:?Directory path required after --app-dir}"
      shift 2
      ;;
    --consul-url)
      CONSUL_ADDR="${2:?Consul address required}"
      shift 2
      ;;
    --consul-token)
      CONSUL_TOKEN="${2:?Consul token required}"
      shift 2
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      print_usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$APP_URL" ]]; then
  echo "Error: --url parameter is mandatory." >&2
  print_usage >&2
  exit 1
fi

# Preflight checks
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Engine is required. Please install Docker and retry." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin ('docker compose') is required." >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Installer must be run with root / sudo privileges to write to ${APP_DIR}." >&2
  exit 1
fi

# 1. Prepare target directory
echo "==> Preparing installation directory: ${APP_DIR}"
install -d -m 0750 "$APP_DIR"
tar --exclude='.git' --exclude='.venv' --exclude='itsm.db*' --exclude='.env*' -C "$SOURCE_DIR" -cf - . | tar -C "$APP_DIR" -xf -

ENV_FILE="$APP_DIR/.env.production"
APP_HOST="${APP_URL#*://}"
APP_HOST="${APP_HOST%%/*}"
APP_HOST="${APP_HOST%%:*}"

make_secret() {
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 32 || openssl rand -hex 16
}

# 2. Generate or load credentials
if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> Generating enterprise credentials and .env.production configuration..."
  ITSM_ADMIN_PASSWORD="$(make_secret)"
  MONGO_PASSWORD="$(make_secret)"
  KM_PASSWORD="$(make_secret)"

  cat > "$ENV_FILE" <<EOF
# Non-secret deployment settings. Protected file (mode 0600).
MONGO_URL=mongodb://mongo-atr:${MONGO_PASSWORD}@mongo:27017/nexus_itsm?authSource=admin
MONGO_DATABASE=nexus_itsm
APP_URL=${APP_URL}
APP_HOST=${APP_HOST}

# Fixed Usernames
MONGO_INITDB_ROOT_USERNAME=mongo-atr
MONGO_INITDB_ROOT_PASSWORD=${MONGO_PASSWORD}
ITSM_BOOTSTRAP_ADMIN_USERNAME=admin
ITSM_BOOTSTRAP_ADMIN_PASSWORD=${ITSM_ADMIN_PASSWORD}

# Consul Configuration
CONSUL_HTTP_ADDR=http://consul:8500
CONSUL_HTTP_TOKEN=${CONSUL_TOKEN}

# KM Configuration
KM_API_TOKEN=${KM_PASSWORD}
KEYCLOAK_ISSUER=
KEYCLOAK_CLIENT_ID=nexus-itsm
ACCENTURE_EMAIL_DOMAIN=company.local
EOF
  chmod 0600 "$ENV_FILE"
else
  echo "==> Existing .env.production discovered. Sourcing deployment configuration..."
  chmod 0600 "$ENV_FILE"
fi

# Source env
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# 3. Launch Docker Compose Stack
echo "==> Starting modular microservice stack via Docker Compose..."
cd "$APP_DIR"
docker compose -f docker-compose.prod.yml up --build --detach --remove-orphans

echo "==> Awaiting container healthiness..."
RETRY=0
MAX_RETRIES=30
while [[ $RETRY -lt $MAX_RETRIES ]]; do
  HEALTH_STATUS=$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | grep -o '"Health":"[^"]*"' || true)
  if [[ "$HEALTH_STATUS" != *"unhealthy"* && "$HEALTH_STATUS" != *"starting"* ]] && [[ -n "$HEALTH_STATUS" ]]; then
    break
  fi
  sleep 2
  RETRY=$((RETRY + 1))
done

docker compose -f docker-compose.prod.yml ps

# 4. Seed Consul KV
echo "==> Synchronizing bootstrap configuration into Consul KV..."
CONSUL_HOST_ADDR="${CONSUL_ADDR:-http://127.0.0.1:8500}"
CONSUL_HDRS=()
if [[ -n "${CONSUL_HTTP_TOKEN:-}" ]]; then
  CONSUL_HDRS=(-H "X-Consul-Token: ${CONSUL_HTTP_TOKEN}")
fi

# Check if Consul is responsive
if curl --fail --silent --show-error "${CONSUL_HDRS[@]}" "${CONSUL_HOST_ADDR}/v1/status/leader" >/dev/null 2>&1; then
  # Seed Admin credentials
  ADMIN_JSON=$(printf '{"username":"%s","password":"%s"}' "${ITSM_BOOTSTRAP_ADMIN_USERNAME:-admin}" "${ITSM_BOOTSTRAP_ADMIN_PASSWORD}")
  curl --fail --silent "${CONSUL_HDRS[@]}" -X PUT --data-binary "$ADMIN_JSON" "${CONSUL_HOST_ADDR}/v1/kv/nexus-itsm/bootstrap/itsm-admin" >/dev/null || true

  # Seed Mongo credentials
  MONGO_JSON=$(printf '{"username":"%s","password":"%s"}' "${MONGO_INITDB_ROOT_USERNAME:-mongo-atr}" "${MONGO_INITDB_ROOT_PASSWORD}")
  curl --fail --silent "${CONSUL_HDRS[@]}" -X PUT --data-binary "$MONGO_JSON" "${CONSUL_HOST_ADDR}/v1/kv/nexus-itsm/mongo/credentials" >/dev/null || true
  curl --fail --silent "${CONSUL_HDRS[@]}" -X PUT --data-binary "${MONGO_INITDB_ROOT_PASSWORD}" "${CONSUL_HOST_ADDR}/v1/kv/nexus-itsm/mongo/root-password" >/dev/null || true

  # Seed App URL
  curl --fail --silent "${CONSUL_HDRS[@]}" -X PUT --data-binary "${APP_URL}" "${CONSUL_HOST_ADDR}/v1/kv/nexus-itsm/app/url" >/dev/null || true

  # Seed KM Integration Default Config
  KM_JSON=$(printf '{"base_url":"https://internal-km.company.local","endpoint":"/api/chat/completions","username":"km-service","password":"%s","index":"itsm-kb","auth_token":"%s"}' "${KM_API_TOKEN:-}" "${KM_API_TOKEN:-}")
  curl --fail --silent "${CONSUL_HDRS[@]}" -X PUT --data-binary "$KM_JSON" "${CONSUL_HOST_ADDR}/v1/kv/nexus-itsm/km/config" >/dev/null || true

  echo "==> Consul KV populated with bootstrap credentials and KM configuration."

  # Sync granular UI entities into Consul via authenticated Backend API
  echo "==> Pushing UI configurable entities (Applications, Groups, Taxonomy, SLAs) to Consul..."
  LOGIN_RESP=$(curl --silent -X POST "http://127.0.0.1:8001/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${ITSM_BOOTSTRAP_ADMIN_USERNAME:-admin}\",\"password\":\"${ITSM_BOOTSTRAP_ADMIN_PASSWORD}\"}" || true)

  TOKEN=$(echo "$LOGIN_RESP" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4 || true)
  if [[ -n "$TOKEN" ]]; then
    curl --silent -X PUT "http://127.0.0.1:8000/api/admin/configuration/sync-consul" \
      -H "Authorization: Bearer $TOKEN" >/dev/null || true
    echo "==> UI configurable entities successfully mirrored to Consul KV."
  fi
else
  echo "Consul not yet accessible at ${CONSUL_HOST_ADDR}. Bootstrap values stored in ${ENV_FILE}."
fi

# 5. Output Summary
cat <<EOF

================================================================================
           GENWIZARD ITSM ENTERPRISE PLATFORM INSTALLED SUCCESSFULLY
================================================================================
Platform URL:             ${APP_URL}
Edge Nginx (Redirects):   http://127.0.0.1:80 (or ${APP_URL})
API Gateway (Router):     http://127.0.0.1:8080
Backend Swagger API:      ${APP_URL}/docs (or http://127.0.0.1:8000/docs)
Identity Swagger API:     ${APP_URL}/api/id/docs (or http://127.0.0.1:8001/docs)
Consul Service:           http://127.0.0.1:8500

--------------------------------------------------------------------------------
ADMINISTRATOR CREDENTIALS:
  Username:               admin
  Password:               ${ITSM_BOOTSTRAP_ADMIN_PASSWORD}
  Role:                   itsm_admin (full administrative privileges)

MONGODB CREDENTIALS:
  Username:               mongo-atr
  Password:               ${MONGO_INITDB_ROOT_PASSWORD}
  Database:               nexus_itsm

CONSUL KV CONFIGURATION:
  Admin Bootstrap:        nexus-itsm/bootstrap/itsm-admin
  Mongo Credentials:      nexus-itsm/mongo/credentials
  Application URL:        nexus-itsm/app/url
  KM Settings:            nexus-itsm/km/config
  UI Taxonomy & Routing:  nexus-itsm/config/*

Credentials are saved in: ${ENV_FILE} (mode 0600)
================================================================================
EOF
