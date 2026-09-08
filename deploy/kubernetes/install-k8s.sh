#!/usr/bin/env bash
# ==============================================================================
# Genwizard ITSM Kubernetes Cluster Installer
# Deploys modular microservices to Kubernetes:
# - Namespace & ServiceAccounts
# - HashiCorp Consul Service
# - MongoDB (user: mongo-atr)
# - Identity Management Service (replicas: 2)
# - ITSM Core Backend Service (replicas: 2)
# - Nginx Gateway Service (replicas: 2)
# - Ingress Controller Routing
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_URL="${APP_URL:-}"
NAMESPACE="${NAMESPACE:-nexus-itsm}"

print_usage() {
  cat <<'EOF'
Usage: ./deploy/kubernetes/install-k8s.sh --url <APPLICATION_URL> [options]

Required:
  --url <URL>            Public URL or FQDN for the application (e.g. https://itsm.example.com)

Options:
  --namespace <NAME>     Kubernetes namespace (default: nexus-itsm)
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      APP_URL="${2:?URL required after --url}"
      shift 2
      ;;
    --namespace)
      NAMESPACE="${2:?Namespace required after --namespace}"
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
  echo "Error: --url parameter is required." >&2
  print_usage >&2
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "Error: kubectl CLI is required to deploy to Kubernetes." >&2
  exit 1
fi

APP_HOST="${APP_URL#*://}"
APP_HOST="${APP_HOST%%/*}"
APP_HOST="${APP_HOST%%:*}"

make_secret() {
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 32 || openssl rand -hex 16
}

ADMIN_PASS="$(make_secret)"
MONGO_PASS="$(make_secret)"
KM_PASS="$(make_secret)"

echo "==> Deploying Genwizard ITSM to Kubernetes namespace: ${NAMESPACE}"
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Generate populated manifests in a temp directory
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

sed -e "s|itsm.local|${APP_HOST}|g" \
    -e "s|http://itsm.local|${APP_URL}|g" \
    -e "s|REPLACE_ADMIN_PASSWORD|${ADMIN_PASS}|g" \
    -e "s|REPLACE_MONGO_PASSWORD|${MONGO_PASS}|g" \
    -e "s|REPLACE_KM_TOKEN|${KM_PASS}|g" \
    "${SCRIPT_DIR}/base.yaml" > "${TMP_DIR}/applied.yaml"

kubectl apply -n "${NAMESPACE}" -f "${TMP_DIR}/applied.yaml"

echo "==> Awaiting deployment rollout..."
kubectl rollout status deployment/consul -n "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/mongo -n "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/nexus-identity -n "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/nexus-backend -n "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/nexus-gateway -n "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/nexus-nginx -n "${NAMESPACE}" --timeout=120s

# Seed Consul KV via kubectl exec into the Consul pod
echo "==> Seeding initial bootstrap credentials into Consul KV..."
CONSUL_POD="$(kubectl get pod -n "${NAMESPACE}" -l app.kubernetes.io/name=consul -o jsonpath='{.items[0].metadata.name}')"

ADMIN_JSON=$(printf '{"username":"admin","password":"%s"}' "${ADMIN_PASS}")
kubectl exec -n "${NAMESPACE}" "${CONSUL_POD}" -- consul kv put nexus-itsm/bootstrap/itsm-admin "${ADMIN_JSON}"
MONGO_JSON=$(printf '{"username":"mongo-atr","password":"%s"}' "${MONGO_PASS}")
kubectl exec -n "${NAMESPACE}" "${CONSUL_POD}" -- consul kv put nexus-itsm/mongo/credentials "${MONGO_JSON}"
kubectl exec -n "${NAMESPACE}" "${CONSUL_POD}" -- consul kv put nexus-itsm/mongo/root-password "${MONGO_PASS}"
kubectl exec -n "${NAMESPACE}" "${CONSUL_POD}" -- consul kv put nexus-itsm/app/url "${APP_URL}"

KM_JSON=$(printf '{"base_url":"https://internal-km.company.local","endpoint":"/api/chat/completions","username":"km-service","password":"%s","index":"itsm-kb","auth_token":"%s"}' "${KM_PASS}" "${KM_PASS}")
kubectl exec -n "${NAMESPACE}" "${CONSUL_POD}" -- consul kv put nexus-itsm/km/config "${KM_JSON}"

cat <<EOF

================================================================================
           GENWIZARD ITSM KUBERNETES DEPLOYMENT COMPLETED SUCCESSFULLY
================================================================================
Namespace:                ${NAMESPACE}
Platform URL:             ${APP_URL}
Ingress Host:             ${APP_HOST}
Backend Swagger API:      ${APP_URL}/docs
Identity Swagger API:     ${APP_URL}/api/id/docs

--------------------------------------------------------------------------------
ADMINISTRATOR CREDENTIALS:
  Username:               admin
  Password:               ${ADMIN_PASS}
  Role:                   itsm_admin (full administrative privileges)

MONGODB CREDENTIALS:
  Username:               mongo-atr
  Password:               ${MONGO_PASS}
  Database:               nexus_itsm

CONSUL KV CONFIGURATION:
  Admin Bootstrap:        nexus-itsm/bootstrap/itsm-admin
  Mongo Credentials:      nexus-itsm/mongo/credentials
  Application URL:        nexus-itsm/app/url
  KM Settings:            nexus-itsm/km/config
================================================================================
EOF
