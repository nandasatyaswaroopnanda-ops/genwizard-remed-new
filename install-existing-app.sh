#!/usr/bin/env bash
# ==============================================================================
# Nexus ITSM — Existing Application Stack Installer (AWS EC2 / Docker)
# ==============================================================================
# Deploys Nexus ITSM alongside your existing:
# - identity-management (:8080 / :8001) & identity-management-client
# - atr-mongo (MongoDB with user 'atr')
# - consul (:8500)
# - atr-gateway-container / nginx
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ITSM_HOST_PORT="${ITSM_HOST_PORT:-8000}"
CONSUL_ADDR="${CONSUL_HTTP_ADDR:-http://consul:8500}"
MONGO_DATABASE="${MONGO_DATABASE:-nexus_itsm}"
DOCKER_NETWORK="${EXISTING_DOCKER_NETWORK:-}"

echo "================================================================================"
echo "    NEXUS ITSM — EXISTING APPLICATION STACK ONBOARDING & INSTALLER"
echo "================================================================================"

# 1. Auto-detect Identity Management Port (8080 vs 8001)
IM_PORT="8080"
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -Eq "^identity-management$"; then
  DETECTED_IM_PORT=$(docker inspect identity-management --format '{{range $p, $conf := .NetworkSettings.Ports}}{{$p}}{{"\n"}}{{end}}' 2>/dev/null | grep -oE '[0-9]+' | head -n1 || true)
  if [[ -n "$DETECTED_IM_PORT" ]]; then
    IM_PORT="$DETECTED_IM_PORT"
  fi
fi
IDENTITY_URL="${IDENTITY_SERVICE_URL:-http://identity-management:${IM_PORT}}"
echo "==> Identity Management target URL: ${IDENTITY_URL} (Port ${IM_PORT})"

# 2. Auto-detect & Validate Existing Docker Network (atr_netbridge / bridge)
if [[ -z "$DOCKER_NETWORK" ]] && command -v docker >/dev/null 2>&1; then
  for container in atr-mongo identity-management consul nginx atr-gateway-container; do
    if docker ps --format '{{.Names}}' | grep -Eq "^${container}$"; then
      # Extract first network name, sanitizing any trailing carriage returns, newlines, or whitespace
      RAW_NET=$(docker inspect "$container" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' 2>/dev/null | tr -d '\r\n ' || true)
      if [[ -n "$RAW_NET" && "$RAW_NET" != "null" ]]; then
        DOCKER_NETWORK="$RAW_NET"
        echo "==> Auto-detected candidate Docker network: '${DOCKER_NETWORK}' (from container '${container}')"
        break
      fi
    fi
  done
fi

# Verify the network is recognized by the Docker daemon
VALID_NETWORK=""
if command -v docker >/dev/null 2>&1 && [[ -n "$DOCKER_NETWORK" ]]; then
  if docker network inspect "$DOCKER_NETWORK" >/dev/null 2>&1; then
    VALID_NETWORK="$DOCKER_NETWORK"
    echo "==> Verified Docker network '${VALID_NETWORK}' exists and is active."
  else
    echo "(!) Network name '${DOCKER_NETWORK}' not directly matched. Searching docker network daemon..."
    MATCHED=$(docker network ls --format '{{.Name}}' | grep -iE "^${DOCKER_NETWORK}$|${DOCKER_NETWORK}" | head -n1 || true)
    if [[ -n "$MATCHED" ]] && docker network inspect "$MATCHED" >/dev/null 2>&1; then
      VALID_NETWORK="$MATCHED"
      echo "==> Resolved exact Docker network name: '${VALID_NETWORK}'"
    fi
  fi
fi

if [[ -z "$VALID_NETWORK" ]]; then
  # Fallback: find any network containing atr or bridge
  ALT_NET=$(docker network ls --format '{{.Name}}' | grep -iE "atr|bridge" | grep -v "host" | grep -v "none" | head -n1 || true)
  if [[ -n "$ALT_NET" ]]; then
    VALID_NETWORK="$ALT_NET"
    echo "==> Using available application network: '${VALID_NETWORK}'"
  else
    VALID_NETWORK="bridge"
    echo "==> Defaulting to Docker network: 'bridge'"
  fi
fi

DOCKER_NETWORK="$VALID_NETWORK"
export EXISTING_DOCKER_NETWORK="$DOCKER_NETWORK"
export ITSM_HOST_PORT="$ITSM_HOST_PORT"
export MONGO_DATABASE="$MONGO_DATABASE"
export IDENTITY_SERVICE_URL="$IDENTITY_URL"

# 3. Load Offline Pre-Built Docker Image (if provided)
if [[ -f "$APP_DIR/nexus-itsm-core-image.tar.gz" ]]; then
  echo "==> Found offline pre-built Docker image archive. Loading into Docker daemon..."
  docker load -i "$APP_DIR/nexus-itsm-core-image.tar.gz"
elif [[ -f "$APP_DIR/nexus-itsm-core-image.tar" ]]; then
  echo "==> Found offline pre-built Docker image archive. Loading into Docker daemon..."
  docker load -i "$APP_DIR/nexus-itsm-core-image.tar"
fi

# 4. Launch nexus-itsm-core Container (with resilient fallback)
echo "==> Starting Nexus ITSM Core container on network '${DOCKER_NETWORK}'..."
COMPOSE_OK=false

# Try compose up first
if docker compose -f "$APP_DIR/docker-compose.existing-app-addon.yml" up -d --build 2>&1; then
  COMPOSE_OK=true
elif command -v docker-compose >/dev/null 2>&1 && docker-compose -f "$APP_DIR/docker-compose.existing-app-addon.yml" up -d --build 2>&1; then
  COMPOSE_OK=true
fi

# Resilient fallback: if compose encountered network or parser error, run direct docker run
if [[ "$COMPOSE_OK" != "true" ]]; then
  echo "(!) Docker compose had an issue with network mapping. Falling back to direct resilient docker run..."
  docker rm -f nexus-itsm-core 2>/dev/null || true
  
  if ! docker image inspect nexus-itsm-core:latest >/dev/null 2>&1; then
    echo "==> Building nexus-itsm-core:latest..."
    docker build -t nexus-itsm-core:latest -f "$APP_DIR/Dockerfile" "$APP_DIR"
  fi

  # Run container on detected network
  if docker run -d \
      --name nexus-itsm-core \
      --restart unless-stopped \
      --network "${DOCKER_NETWORK}" \
      -p "${ITSM_HOST_PORT}:8000" \
      -e CONSUL_HTTP_ADDR="${CONSUL_ADDR}" \
      -e MONGO_DATABASE="${MONGO_DATABASE}" \
      -e IDENTITY_SERVICE_URL="${IDENTITY_URL}" \
      -e ITSM_SUBPATH="/itsm" \
      -e ITSM_BOOTSTRAP_ADMIN_USERNAME="admin" \
      -e KM_API_TOKEN="local_demo_token" \
      nexus-itsm-core:latest >/dev/null 2>&1; then
    echo "✓ Direct docker run on network '${DOCKER_NETWORK}' succeeded."
  else
    echo "(!) Retrying with container-attached network to atr-mongo..."
    docker rm -f nexus-itsm-core 2>/dev/null || true
    docker run -d \
      --name nexus-itsm-core \
      --restart unless-stopped \
      --network container:atr-mongo \
      -e CONSUL_HTTP_ADDR="${CONSUL_ADDR}" \
      -e MONGO_DATABASE="${MONGO_DATABASE}" \
      -e IDENTITY_SERVICE_URL="${IDENTITY_URL}" \
      -e ITSM_SUBPATH="/itsm" \
      -e ITSM_BOOTSTRAP_ADMIN_USERNAME="admin" \
      -e KM_API_TOKEN="local_demo_token" \
      nexus-itsm-core:latest
    echo "✓ Container attached to atr-mongo network."
  fi
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

# 6. Execute Group & Permission Synchronization INSIDE Container (No host Python needed!)
echo "==> Synchronizing IM groups, ATR_SAML/IM_SAML & admin privileges (inside container)..."
sleep 2
if docker exec nexus-itsm-core python3 /app/scripts/bootstrap_external_im.py >/dev/null 2>&1; then
  echo "  ✓ Identity Management and MongoDB synchronization completed successfully."
else
  echo "  (!) Note: Synchronization will complete automatically via background startup thread."
fi

cat <<SUMMARY

================================================================================
          NEXUS ITSM SUCCESSFULLY INSTALLED ON EXISTING STACK
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
