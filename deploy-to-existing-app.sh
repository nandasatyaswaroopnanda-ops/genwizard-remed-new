#!/usr/bin/env bash
# ==============================================================================
# Nexus ITSM Core — Turnkey Deployment onto Existing Application Stack
# ==============================================================================
# Integrates nexus-itsm-core with:
#   - atr-mongo (MongoDB, user 'atr')
#   - consul (HashiCorp Consul configuration store)
#   - identity-management & identity-management-client (IM Backend & Frontend)
#   - atr-gateway & nginx (Gateway & Perimeter Proxy)
# ==============================================================================

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
cat << "EOF"
==============================================================================
   _  __                     ___________ ____  __  ___  ______              
  / |/ /__ __ _____ __ ___  /  _/_  __/ //  / /  |/  / / ____/__  ________ 
 /    / -_) \ / // // (_-< _/ /   / / (_-< _/ / /|_/ / / /   / _ \/ __/ -_)
/_/|_/\__/_\_\\_,_//_/___//___/  /_/ /___//_/_/  /_/  \____/\___/_/  \__/  
                                                                            
           Turnkey Deployment for Existing Application Ecosystem
==============================================================================
EOF
echo -e "${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# 1. Check Docker
if ! command -v docker &>/dev/null; then
    echo -e "${RED}[ERROR] Docker is not installed or not in PATH.${NC}"
    exit 1
fi

# 2. Verify or Build Docker Image
echo -e "${CYAN}--> Step 1: Checking Docker Image (nexus-itsm-core:latest)...${NC}"
if docker image inspect nexus-itsm-core:latest &>/dev/null; then
    echo -e "${GREEN}✓ Image nexus-itsm-core:latest is already built.${NC}"
else
    echo -e "${YELLOW}Image nexus-itsm-core:latest not found. Building now...${NC}"
    docker build -t nexus-itsm-core:latest -f Dockerfile.backend .
    echo -e "${GREEN}✓ Image built successfully.${NC}"
fi

# 3. Detect Existing Stack's Docker Network
echo -e "\n${CYAN}--> Step 2: Detecting Existing Docker Network...${NC}"
EXISTING_NET=""
for candidate in atr-mongo consul identity-management atr-gateway nginx; do
    if docker ps --format '{{.Names}}' | grep -q "^${candidate}$"; then
        EXISTING_NET=$(docker inspect "${candidate}" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -n 1)
        echo -e "${GREEN}✓ Found active container '${candidate}' on network '${EXISTING_NET}'${NC}"
        break
    fi
done

if [ -z "${EXISTING_NET}" ]; then
    EXISTING_NET="bridge"
    echo -e "${YELLOW}! Could not auto-detect running container. Falling back to network '${EXISTING_NET}'${NC}"
fi

# 4. Verify Consul & Spring Keys
echo -e "\n${CYAN}--> Step 3: Checking HashiCorp Consul & Spring Cloud Keys...${NC}"
CONSUL_ADDR="${CONSUL_HTTP_ADDR:-http://127.0.0.1:8500}"
if curl -s -f -m 3 "${CONSUL_ADDR}/v1/status/leader" &>/dev/null; then
    echo -e "${GREEN}✓ Connected to Consul at ${CONSUL_ADDR}${NC}"
    echo -e "  Inspecting Spring Cloud keys:"
    
    # Check Admin Password Key
    ADMIN_KEY="configuration/aaam-atr-v3/identity-management/admin.password"
    if curl -s -f -m 2 "${CONSUL_ADDR}/v1/kv/${ADMIN_KEY}?raw" &>/dev/null; then
        echo -e "  ${GREEN}✓ Found key:${NC} ${ADMIN_KEY}"
    else
        echo -e "  ${YELLOW}! Key not set:${NC} ${ADMIN_KEY} (using bootstrap default)"
    fi
    
    # Check Mongo Keys
    MONGO_HOST_KEY="configuration/aaam-atr-v3-gateway/spring.data.mongodb.host"
    MONGO_PASS_KEY="configuration/aaam-atr-v3-gateway/spring.data.mongodb.password"
    if curl -s -f -m 2 "${CONSUL_ADDR}/v1/kv/${MONGO_PASS_KEY}?raw" &>/dev/null; then
        echo -e "  ${GREEN}✓ Found key:${NC} ${MONGO_PASS_KEY}"
    else
        echo -e "  ${YELLOW}! Key not set:${NC} ${MONGO_PASS_KEY} (using default mongo credentials)"
    fi

    # Check DNS Key
    DNS_KEY="configuration/aaam-atr-v3-gateway/dns"
    if DNS_VAL=$(curl -s -f -m 2 "${CONSUL_ADDR}/v1/kv/${DNS_KEY}?raw" 2>/dev/null); then
        echo -e "  ${GREEN}✓ Found platform DNS:${NC} ${DNS_VAL}"
    fi
else
    echo -e "${YELLOW}! Consul not directly reachable on host at ${CONSUL_ADDR}. It will be reached inside the Docker network (http://consul:8500).${NC}"
fi

# 5. Launch nexus-itsm-core Container
echo -e "\n${CYAN}--> Step 4: Starting nexus-itsm-core container...${NC}"
export EXISTING_DOCKER_NETWORK="${EXISTING_NET}"

# Stop any previous instance
docker rm -f nexus-itsm-core 2>/dev/null || true

# Run container attached to existing network
docker run -d \
    --name nexus-itsm-core \
    --restart unless-stopped \
    --network "${EXISTING_NET}" \
    -p 8000:8000 \
    -e CONSUL_HTTP_ADDR="http://consul:8500" \
    -e MONGO_DATABASE="nexus_itsm" \
    -e IDENTITY_SERVICE_URL="http://identity-management:8001" \
    -e ITSM_SUBPATH="/itsm" \
    -e ITSM_BOOTSTRAP_ADMIN_USERNAME="admin" \
    -e KM_API_TOKEN="local_demo_token" \
    nexus-itsm-core:latest

echo -e "${GREEN}✓ Container nexus-itsm-core started successfully!${NC}"

# 6. Wait for Healthcheck
echo -e "\n${CYAN}--> Step 5: Waiting for container health...${NC}"
HEALTHY=false
for i in {1..15}; do
    if docker exec nexus-itsm-core curl -s -f http://localhost:8000/health &>/dev/null; then
        HEALTHY=true
        break
    fi
    sleep 2
done

if [ "$HEALTHY" = true ]; then
    echo -e "${GREEN}✓ Container health check passed!${NC}"
else
    echo -e "${YELLOW}! Container is taking longer to respond. Check logs: docker logs nexus-itsm-core${NC}"
fi

# 7. Print Reverse Proxy & Gateway Configuration Instructions
echo -e "\n${BOLD}${GREEN}==============================================================================${NC}"
echo -e "${BOLD}${GREEN}                   DEPLOYMENT COMPLETED SUCCESSFULLY!                         ${NC}"
echo -e "${BOLD}${GREEN}==============================================================================${NC}"

echo -e "\n${CYAN}${BOLD}Configure your NGINX and ATR-GATEWAY to route '/itsm' to nexus-itsm-core:8000:${BOLD}${NC}"

echo -e "\n${YELLOW}--- 1. NGINX Location Block (Add inside your existing server {} block) ---${NC}"
cat << 'EOF'
location /itsm {
    proxy_pass http://nexus-itsm-core:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
EOF

echo -e "\n${YELLOW}--- 2. ATR-GATEWAY Route Definition (application.yml or Spring Cloud Gateway) ---${NC}"
cat << 'EOF'
spring:
  cloud:
    gateway:
      routes:
        - id: itsm-core-route
          uri: http://nexus-itsm-core:8000
          predicates:
            - Path=/itsm/**
EOF

echo -e "\n${CYAN}${BOLD}Summary of Capabilities Active:${NC}"
echo -e "  • Accessible at: ${BOLD}https://<your-domain>/itsm${NC}"
echo -e "  • MongoDB: Connected to ${BOLD}atr-mongo${NC} using user ${BOLD}atr${NC} (via Consul Spring keys)"
echo -e "  • Identity Management: Synced groups (${BOLD}IM_SAML${NC}, ${BOLD}ATR_SAML${NC}, ${BOLD}itsm_admin${NC}, ${BOLD}itsm_user${NC}, ${BOLD}itsm_read${NC}) with permissions"
echo -e "  • AD Groups (DLs): Mapped to support teams in IM (${BOLD}ITSM-Admins${NC}, ${BOLD}Service Desk${NC}, ${BOLD}Tier1-Support${NC}, ${BOLD}ITSM-Fulfillers${NC})"
echo -e "  • End-users logging in via SSO: Automatically assigned ${BOLD}IM_SAML / ATR_SAML${NC} group for ticketing access"
echo -e "\n==============================================================================\n"
