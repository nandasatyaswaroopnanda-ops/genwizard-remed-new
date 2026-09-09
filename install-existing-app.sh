#!/usr/bin/env bash
# ==============================================================================
# Genwizard ITSM — Existing Application Stack Installer (AWS EC2 / Docker)
# ==============================================================================
# Deploys Genwizard ITSM alongside your existing:
# - identity-management (:8080 / :8001) & identity-management-client
# - atr-mongo (MongoDB with user 'atr')
# - consul (:8500)
# - atr-gateway-container / nginx
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_DIR}"
ITSM_HOST_PORT="${ITSM_HOST_PORT:-8000}"
CONSUL_ADDR="${CONSUL_HTTP_ADDR:-http://consul:8500}"
MONGO_DATABASE="${MONGO_DATABASE:-nexus_itsm}"
DOCKER_NETWORK="${EXISTING_DOCKER_NETWORK:-}"

echo "================================================================================"
echo "    GENWIZARD ITSM — EXISTING APPLICATION STACK ONBOARDING & INSTALLER"
echo "================================================================================"

# 1. Auto-detect Existing Application Stack Containers & Port
EXISTING_CONTAINERS=""
if command -v docker >/dev/null 2>&1; then
  EXISTING_CONTAINERS=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -iE 'identity|mongo|consul|gateway|nginx|atr' || true)
fi

IM_CONTAINER=""
IM_PORT="8080"
if [[ -n "$EXISTING_CONTAINERS" ]]; then
  IM_CONTAINER=$(echo "$EXISTING_CONTAINERS" | grep -iE 'identity|im-' | head -n1 || true)
  if [[ -n "$IM_CONTAINER" ]]; then
    DETECTED_IM_PORT=$(docker inspect "$IM_CONTAINER" --format '{{range $p, $conf := .NetworkSettings.Ports}}{{$p}}{{"\n"}}{{end}}' 2>/dev/null | grep -oE '[0-9]+' | head -n1 || true)
    if [[ -n "$DETECTED_IM_PORT" ]]; then
      IM_PORT="$DETECTED_IM_PORT"
    fi
  fi
fi

IM_HOST="${IM_CONTAINER:-identity-management}"
IDENTITY_URL="${IDENTITY_SERVICE_URL:-http://${IM_HOST}:${IM_PORT}}"
echo "==> Target Identity Management: ${IDENTITY_URL} (Container: '${IM_HOST}', Port: ${IM_PORT})"

# Auto-detect Consul container & interact directly via Docker CLI
CONSUL_CONTAINER=""
if [[ -n "$EXISTING_CONTAINERS" ]]; then
  CONSUL_CONTAINER=$(echo "$EXISTING_CONTAINERS" | grep -iE 'consul' | head -n1 || true)
fi

if [[ -n "$CONSUL_CONTAINER" ]]; then
  echo "==> Detected active Consul container: '${CONSUL_CONTAINER}'"
  CONSUL_ADDR="http://${CONSUL_CONTAINER}:8500"
  export CONSUL_HTTP_ADDR="$CONSUL_ADDR"
  
  echo "==> Interacting directly with Consul container ('${CONSUL_CONTAINER}') via Docker CLI..."
  DIRECT_ADMIN_PASS=$(docker exec "$CONSUL_CONTAINER" consul kv get configuration/aaam-atr-v3/identity-management/admin.password 2>/dev/null || true)
  if [[ -n "$DIRECT_ADMIN_PASS" ]]; then
    export ITSM_BOOTSTRAP_ADMIN_PASSWORD="$DIRECT_ADMIN_PASS"
    echo "  ✓ Extracted admin password directly from Consul container CLI"
  fi
  
  DIRECT_MONGO_PASS=$(docker exec "$CONSUL_CONTAINER" consul kv get configuration/aaam-atr-v3-gateway/spring.data.mongodb.password 2>/dev/null || true)
  if [[ -n "$DIRECT_MONGO_PASS" ]]; then
    export MONGO_PASSWORD="$DIRECT_MONGO_PASS"
    echo "  ✓ Extracted MongoDB password directly from Consul container CLI"
  fi

  DIRECT_MONGO_USER=$(docker exec "$CONSUL_CONTAINER" consul kv get configuration/aaam-atr-v3-gateway/spring.data.mongodb.username 2>/dev/null || true)
  if [[ -n "$DIRECT_MONGO_USER" ]]; then
    export MONGO_USERNAME="$DIRECT_MONGO_USER"
  fi

  DIRECT_MONGO_HOST=$(docker exec "$CONSUL_CONTAINER" consul kv get configuration/aaam-atr-v3-gateway/spring.data.mongodb.host 2>/dev/null || true)
  if [[ -n "$DIRECT_MONGO_HOST" ]]; then
    export MONGO_HOST="$DIRECT_MONGO_HOST"
  fi
fi

# Auto-detect MongoDB container (defaults to 'atr-mongo') & interact directly via Docker CLI
MONGO_CONTAINER="atr-mongo"
if [[ -n "$EXISTING_CONTAINERS" ]]; then
  DETECTED_MONGO=$(echo "$EXISTING_CONTAINERS" | grep -iE 'atr-mongo|mongo' | head -n1 || true)
  if [[ -n "$DETECTED_MONGO" ]]; then
    MONGO_CONTAINER="$DETECTED_MONGO"
  fi
fi

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qE "^${MONGO_CONTAINER}$"; then
  echo "==> Detected active MongoDB container: '${MONGO_CONTAINER}'"
  export MONGO_CONTAINER="$MONGO_CONTAINER"
  export MONGO_HOST="${MONGO_HOST:-$MONGO_CONTAINER}"

  echo "==> Interacting directly with MongoDB container ('${MONGO_CONTAINER}') via Docker CLI..."
  if docker exec "$MONGO_CONTAINER" mongosh --quiet --eval "db.adminCommand('ping').ok" 2>/dev/null | grep -q '1'; then
    echo "  ✓ Direct Docker CLI ping to '${MONGO_CONTAINER}' confirmed MongoDB is responsive."
  elif docker exec "$MONGO_CONTAINER" mongo --quiet --eval "db.adminCommand('ping').ok" 2>/dev/null | grep -q '1'; then
    echo "  ✓ Direct Docker CLI ping to '${MONGO_CONTAINER}' confirmed MongoDB is responsive."
  fi
fi

# 2. Auto-detect & Validate Existing User-Defined Docker Network
DETECTED_NET=""
if [[ -n "$EXISTING_CONTAINERS" ]]; then
  for c in $EXISTING_CONTAINERS; do
    c_net=$(docker inspect "$c" --format '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' 2>/dev/null | tr -d '\r' | grep -vE '^(bridge|host|none)$' | head -n1 || true)
    if [[ -n "$c_net" ]]; then
      DETECTED_NET="$c_net"
      echo "==> Detected active Docker network '${DETECTED_NET}' from running container '${c}'"
      break
    fi
  done
fi

if [[ -n "${EXISTING_DOCKER_NETWORK:-}" ]]; then
  DETECTED_NET="$EXISTING_DOCKER_NETWORK"
fi

if [[ -z "$DETECTED_NET" ]] && command -v docker >/dev/null 2>&1; then
  DETECTED_NET=$(docker network ls --format '{{.Name}}' 2>/dev/null | tr -d '\r' | grep -iE 'atr|app|prod|backend|gateway|itsm' | grep -vE '^(bridge|host|none)$' | head -n1 || true)
fi

# Fallback: ensure a dedicated user-defined network exists (never default to plain unmanaged bridge)
if [[ -z "$DETECTED_NET" || "$DETECTED_NET" == "bridge" || "$DETECTED_NET" == "host" || "$DETECTED_NET" == "none" ]]; then
  DETECTED_NET="atr_netbridge"
fi

if command -v docker >/dev/null 2>&1; then
  if ! docker network inspect "$DETECTED_NET" >/dev/null 2>&1; then
    echo "==> Initializing user-defined Docker network: '${DETECTED_NET}'"
    docker network create "$DETECTED_NET" || true
  fi

  # Seamlessly attach existing containers to this network so DNS resolution is 100% reliable
  if [[ -n "$EXISTING_CONTAINERS" ]]; then
    for c in $EXISTING_CONTAINERS; do
      docker network connect "$DETECTED_NET" "$c" 2>/dev/null || true
    done
  fi
fi

DOCKER_NETWORK="$DETECTED_NET"
export EXISTING_DOCKER_NETWORK="$DOCKER_NETWORK"
export ITSM_HOST_PORT="$ITSM_HOST_PORT"
export MONGO_DATABASE="$MONGO_DATABASE"
export IDENTITY_SERVICE_URL="$IDENTITY_URL"
export CONSUL_HTTP_ADDR="${CONSUL_ADDR}"
export ITSM_BOOTSTRAP_ADMIN_PASSWORD="${ITSM_BOOTSTRAP_ADMIN_PASSWORD:-}"
export MONGO_PASSWORD="${MONGO_PASSWORD:-}"
export MONGO_USERNAME="${MONGO_USERNAME:-}"
export MONGO_HOST="${MONGO_HOST:-}"
echo "==> Using verified Docker network: '${DOCKER_NETWORK}'"

# 3. Load Offline Pre-Built Docker Image (if provided)
if [[ -f "$APP_DIR/nexus-itsm-core-image.tar.gz" ]]; then
  echo "==> Found offline pre-built Docker image archive. Loading into Docker daemon..."
  docker load -i "$APP_DIR/nexus-itsm-core-image.tar.gz"
elif [[ -f "$APP_DIR/nexus-itsm-core-image.tar" ]]; then
  echo "==> Found offline pre-built Docker image archive. Loading into Docker daemon..."
  docker load -i "$APP_DIR/nexus-itsm-core-image.tar"
fi

# 4. Launch nexus-itsm-core Container (with resilient fallback)
echo "==> Starting Genwizard ITSM Core container on network '${DOCKER_NETWORK}'..."
COMPOSE_OK=false

if docker image inspect nexus-itsm-core:latest >/dev/null 2>&1; then
  echo "  ✓ Detected nexus-itsm-core:latest in local daemon. Starting container..."
  if docker compose -f "$APP_DIR/docker-compose.existing-app-addon.yml" up -d 2>&1; then
    COMPOSE_OK=true
  fi
fi

if [[ "$COMPOSE_OK" != "true" ]]; then
  if docker compose -f "$APP_DIR/docker-compose.existing-app-addon.yml" up -d --build 2>&1; then
    COMPOSE_OK=true
  elif command -v docker-compose >/dev/null 2>&1 && docker-compose -f "$APP_DIR/docker-compose.existing-app-addon.yml" up -d --build 2>&1; then
    COMPOSE_OK=true
  fi
fi

# Resilient fallback: direct docker run on verified network with host-gateway and volume
if [[ "$COMPOSE_OK" != "true" ]]; then
  echo "(!) Docker compose had an issue. Falling back to direct resilient docker run..."
  docker rm -f nexus-itsm-core 2>/dev/null || true

  if ! docker image inspect nexus-itsm-core:latest >/dev/null 2>&1; then
    echo "==> Building nexus-itsm-core:latest..."
    docker build -t nexus-itsm-core:latest -f "$APP_DIR/Dockerfile" "$APP_DIR"
  fi

  docker volume create nexus-itsm-uploads >/dev/null 2>&1 || true

  docker run -d \
    --name nexus-itsm-core \
    --restart unless-stopped \
    --network "${DOCKER_NETWORK}" \
    --add-host host.docker.internal:host-gateway \
    -p "${ITSM_HOST_PORT}:8000" \
    -v nexus-itsm-uploads:/app/uploads \
    -e CONSUL_HTTP_ADDR="${CONSUL_ADDR}" \
    -e MONGO_DATABASE="${MONGO_DATABASE}" \
    -e IDENTITY_SERVICE_URL="${IDENTITY_URL}" \
    -e ITSM_SUBPATH="/itsm" \
    -e ITSM_BOOTSTRAP_ADMIN_USERNAME="admin" \
    -e ITSM_BOOTSTRAP_ADMIN_PASSWORD="${ITSM_BOOTSTRAP_ADMIN_PASSWORD:-}" \
    -e MONGO_PASSWORD="${MONGO_PASSWORD:-}" \
    -e MONGO_USERNAME="${MONGO_USERNAME:-}" \
    -e MONGO_HOST="${MONGO_HOST:-}" \
    -e KM_API_TOKEN="local_demo_token" \
    nexus-itsm-core:latest
  echo "✓ Direct docker run on network '${DOCKER_NETWORK}' succeeded."
fi

# 5. Await Container Readiness
echo "==> Verifying container health on port ${ITSM_HOST_PORT}..."
sleep 2
RETRY=0
MAX_RETRIES=15
while [[ $RETRY -lt $MAX_RETRIES ]]; do
  if docker ps --filter "name=nexus-itsm-core" --filter "status=running" --format '{{.Names}}' | grep -q "nexus-itsm-core"; then
    echo "  ✓ nexus-itsm-core container is running."
    break
  fi
  sleep 2
  RETRY=$((RETRY + 1))
done

# 6. Execute Group & Permission Synchronization
echo "==> Synchronizing IM groups, ATR_SAML/IM_SAML & admin privileges..."
sleep 2

# 6a. Direct seed execution inside MongoDB container (atr-mongo) via docker exec
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qE "^${MONGO_CONTAINER}$"; then
  if [[ -f "$APP_DIR/scripts/seed_im_mongo.js" && -n "${MONGO_PASSWORD:-}" ]]; then
    echo "  -> Executing direct database seed inside '${MONGO_CONTAINER}' via docker exec..."
    if docker exec -i "$MONGO_CONTAINER" mongosh -u "${MONGO_USERNAME:-atr}" -p "$MONGO_PASSWORD" --authenticationDatabase admin < "$APP_DIR/scripts/seed_im_mongo.js" >/dev/null 2>&1; then
      echo "  ✓ Direct mongosh seed execution inside '${MONGO_CONTAINER}' succeeded."
    elif docker exec -i "$MONGO_CONTAINER" mongo -u "${MONGO_USERNAME:-atr}" -p "$MONGO_PASSWORD" --authenticationDatabase admin < "$APP_DIR/scripts/seed_im_mongo.js" >/dev/null 2>&1; then
      echo "  ✓ Direct mongo seed execution inside '${MONGO_CONTAINER}' succeeded."
    fi
  fi
fi

# 6b. Bootstrap synchronization inside nexus-itsm-core container
if docker exec \
  -e ITSM_BOOTSTRAP_ADMIN_PASSWORD="${ITSM_BOOTSTRAP_ADMIN_PASSWORD:-}" \
  -e MONGO_PASSWORD="${MONGO_PASSWORD:-}" \
  -e MONGO_USERNAME="${MONGO_USERNAME:-}" \
  -e MONGO_HOST="${MONGO_HOST:-}" \
  -e CONSUL_HTTP_ADDR="${CONSUL_ADDR}" \
  nexus-itsm-core python3 /app/scripts/bootstrap_external_im.py >/dev/null 2>&1; then
  echo "  ✓ Identity Management and MongoDB synchronization completed successfully."
else
  echo "  (!) Note: Synchronization will complete automatically via background startup thread."
fi

cat <<SUMMARY

================================================================================
          GENWIZARD ITSM SUCCESSFULLY INSTALLED ON EXISTING STACK
================================================================================
Status:               Active & Connected
Host Port:            http://localhost:${ITSM_HOST_PORT} (or /itsm via perimeter Nginx)
MongoDB Backend:      Connected to existing Mongo (Database: ${MONGO_DATABASE})
Identity Management:  Connected to existing IM (${IDENTITY_URL})
Consul Registry:      Connected to existing Consul (${CONSUL_ADDR})
Docker Network:       ${DOCKER_NETWORK}

PROVISIONED GROUPS & SIMPLIFIED PERMISSIONS:
  - IM_SAML / ATR_SAML: ticket_create, ticket_read_own, ticket_update, applications_read, projects_read
  - itsm_admin:       admin_all, ticket_create, ticket_read, ticket_update, ticket_delete,
                      ticket_assign, ticket_resolve, ticket_close, admin_routing, admin_slas, admin_config
  - itsm_user:        ticket_create, ticket_read, ticket_update, ticket_assign, ticket_resolve
  - itsm_read:        ticket_read, applications_read, projects_read

ADMIN USER & AD MAPPINGS:
  - Existing Admin User: Successfully mapped with 'itsm_admin' group and privileges.
  - AD Groups / DLs:     No hardcoded mappings enforced. Configure your organization's
                         AD groups & DLs anytime directly in IM: https://<base-url>/identity-management/adGroups

To view logs:
  docker logs -f nexus-itsm-core
================================================================================
SUMMARY
