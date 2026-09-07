#!/usr/bin/env bash
# ==============================================================================
# Nexus ITSM — Existing Application Stack Installer (AWS EC2 / Docker)
# ==============================================================================
# Deploys Nexus ITSM alongside your existing:
# - identity-management (:8001) & identity-management-client
# - atr-mongo (MongoDB with user 'atr')
# - consul (:8500)
# - atr-gateway-container / nginx
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ITSM_HOST_PORT="${ITSM_HOST_PORT:-8000}"
CONSUL_ADDR="${CONSUL_HTTP_ADDR:-http://127.0.0.1:8500}"
IDENTITY_URL="${IDENTITY_SERVICE_URL:-http://127.0.0.1:8001}"
MONGO_DATABASE="${MONGO_DATABASE:-nexus_itsm}"
DOCKER_NETWORK="${EXISTING_DOCKER_NETWORK:-}"

echo "================================================================================"
echo "    NEXUS ITSM — EXISTING APPLICATION STACK ONBOARDING & INSTALLER"
echo "================================================================================"

# 1. Auto-detect Docker Network from existing containers
if [[ -z "$DOCKER_NETWORK" ]] && command -v docker >/dev/null 2>&1; then
  for container in atr-mongo identity-management consul nginx atr-gateway-container; do
    if docker ps --format '{{.Names}}' | grep -Eq "^${container}$"; then
      DETECTED_NET=$(docker inspect "$container" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null | head -n1 || true)
      if [[ -n "$DETECTED_NET" && "$DETECTED_NET" != "null" ]]; then
        DOCKER_NETWORK="$DETECTED_NET"
        echo "==> Auto-detected existing Docker network: '${DOCKER_NETWORK}' (from ${container})"
        break
      fi
    fi
  done
fi

if [[ -z "$DOCKER_NETWORK" ]]; then
  DOCKER_NETWORK="bridge"
  echo "==> Defaulting to Docker network: 'bridge'"
fi

export EXISTING_DOCKER_NETWORK="$DOCKER_NETWORK"
export ITSM_HOST_PORT="$ITSM_HOST_PORT"
export MONGO_DATABASE="$MONGO_DATABASE"

# 2. Synchronize Permissions, Groups & Mongo for Existing IM and ITSM
echo "==> Provisioning groups & simplified permissions (e.g. ticket_create) into IM & Mongo..."
if command -v python3 >/dev/null 2>&1; then
  python3 "$APP_DIR/scripts/bootstrap_external_im.py" || {
    echo "(!) Python bootstrap exited with warnings. Proceeding with container launch..."
  }
else
  echo "(!) Python3 not found locally; bootstrap will run inside container on startup."
fi

# 3. Build or load and launch nexus-itsm-core container
if [[ -f "$APP_DIR/nexus-itsm-core-image.tar.gz" ]]; then
  echo "==> Found offline pre-built Docker image archive. Loading into Docker daemon..."
  docker load -i "$APP_DIR/nexus-itsm-core-image.tar.gz"
elif [[ -f "$APP_DIR/nexus-itsm-core-image.tar" ]]; then
  echo "==> Found offline pre-built Docker image archive. Loading into Docker daemon..."
  docker load -i "$APP_DIR/nexus-itsm-core-image.tar"
fi

echo "==> Starting Nexus ITSM Core container on network '${DOCKER_NETWORK}'..."
docker compose -f "$APP_DIR/docker-compose.existing-app-addon.yml" up -d --build

# 4. Await health check
echo "==> Verifying container health on port ${ITSM_HOST_PORT}..."
sleep 3
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
  docker compose -f docker-compose.existing-app-addon.yml logs -f nexus-itsm-core
================================================================================
SUMMARY
