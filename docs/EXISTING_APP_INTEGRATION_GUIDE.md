# Nexus ITSM Core — Turnkey Integration Guide for Existing Application Stack

This guide details how to deploy the **Nexus ITSM Core** image (`nexus-itsm-core:latest`) on top of an existing application stack already running:
- **`identity-management`**: Existing IM backend
- **`identity-management-client`**: Existing IM frontend
- **`nginx`**: Perimeter reverse proxy
- **`atr-gateway`**: Gateway microservice
- **`atr-mongo`**: MongoDB container (user `atr`)
- **`consul`**: HashiCorp Consul key-value registry

---

## Architecture Overview

```mermaid
graph TD
    Client["Client Browser"] -->|https://domain.com/itsm| NGINX["NGINX Proxy (Existing)"]
    NGINX -->|/itsm/**| Gateway["atr-gateway (Existing)"]
    Gateway -->|/itsm/**| ITSM["nexus-itsm-core:8000 (New)"]
    
    ITSM -->|Dynamic Config / Spring Keys| Consul["consul:8500 (Existing)"]
    ITSM -->|100% Native Mongo (user: atr)| Mongo["atr-mongo:27017 (Existing)"]
    ITSM -->|Sync Groups & Roles| IM["identity-management:8001 (Existing)"]
    
    subgraph "Existing Authorization Model in IM"
        AD["AD Groups / DLs (e.g. ITSM-Admins, Service Desk)"] -->|Attached to| Groups["Groups with Permissions (itsm_admin, itsm_user, IM_SAML)"]
    end
```

---

## 1. Dynamic Consul Spring Keys Reference

`nexus-itsm-core` resolves all its operational credentials and connection parameters automatically from the existing Spring Cloud Consul keys at runtime:

| Parameter | Consul Key Path | Description | Default Fallback |
|---|---|---|---|
| **Admin Password** | `configuration/aaam-atr-v3/identity-management/admin.password` | Admin user password (User: `admin`) | `Admin@Secure2026!` |
| **Mongo Host** | `configuration/aaam-atr-v3-gateway/spring.data.mongodb.host` | Hostname/port of MongoDB instance | `atr-mongo` |
| **Mongo Username** | `configuration/aaam-atr-v3-gateway/spring.data.mongodb.username` | MongoDB username | `atr` |
| **Mongo Password** | `configuration/aaam-atr-v3-gateway/spring.data.mongodb.password` | MongoDB password for user `atr` | Env `MONGO_PASSWORD` |
| **Mongo Auth DB** | `configuration/aaam-atr-v3-gateway/spring.data.mongodb.authentication_database` | Authentication database | `admin` |
| **Platform DNS** | `configuration/aaam-atr-v3-gateway/dns` | Base platform URL (e.g. `portal.company.com`) | `http://localhost:8080` |

---

## 2. Authorization Architecture: DLs, Groups & Permissions

In your Identity Management service:
1. **Roles are Groups**: There is no separate role table; a role in IM is a **Group** that contains attached permissions.
2. **AD Groups are DLs**: Active Directory groups are the Distribution Lists (DLs) added to IM.
3. **Groups are Attached to DLs**: To each AD Group (DL), one or more permission-bearing Groups are attached.

### Core Permission-Bearing Groups Configured for Nexus ITSM:

| Group Name | Purpose | Attached Permissions (Simplified, No Colons) |
|---|---|---|
| **`itsm_admin`** | Full Platform Administration | `admin_all`, `ticket_create`, `ticket_read`, `ticket_update`, `ticket_delete`, `ticket_assign`, `ticket_resolve`, `ticket_close`, `admin_routing`, `admin_slas`, `admin_config`, `users_manage`, `applications_read`, `projects_read` |
| **`itsm_user`** | Support Team Fulfiller | `ticket_create`, `ticket_read`, `ticket_update`, `ticket_assign`, `ticket_resolve`, `applications_read`, `projects_read` |
| **`itsm_read`** | Read-Only Auditor | `ticket_read`, `applications_read`, `projects_read` |
| **`IM_SAML`** | Default SSO End-User Group | `ticket_create`, `ticket_read_own`, `ticket_update` (comments & worknotes), `applications_read`, `projects_read` |

### Admin User & Post-Installation DL Configuration:

- **Existing Admin User Association**: During installation, the system automatically associates your existing admin user in the existing app (`admin` or username resolved from Consul) with the **`itsm_admin`** group and permissions.
- **Dynamic Post-Installation DL Mappings**: Rather than enforcing hardcoded AD groups, you can map whatever real AD groups / Distribution Lists (DLs) your organization uses post-installation directly in your existing IM UI:
  - Go to: `https://<base-url>/identity-management/adGroups`
  - Map your corporate DLs (e.g., `L1-Support-Team`, `Cloud-Admins`, `DevOps-Engineers`) to `itsm_user` or `itsm_admin`.
  - Any corporate user not explicitly in a support DL receives the default **`IM_SAML`** end-user group upon SSO login.

> **End-User Experience**:
> When an employee whose AD groups are not added to a support DL logs in via SSO, they automatically receive the default **`IM_SAML`** group.
> In the portal, they see only:
> - **Create Ticket**
> - **My Tickets** (and can update comments & worknotes)
> - **Applications** & **Projects**
---

## 2.1 How Groups and Permissions are Created in Existing Identity Management

There are **3 distinct ways** the groups (`IM_SAML`, `itsm_admin`, `itsm_user`, `itsm_read`) and their attached permissions are created and the existing admin user is configured:

### Method 1: Automated Turnkey Installer (`./install-existing-app.sh` — Recommended)
Run the dedicated existing stack installer on your EC2 host:
```bash
./install-existing-app.sh
```
What it executes:
1. Auto-detects the Docker network of your running containers (`atr-mongo`, `identity-management`, `consul`).
2. Connects to `atr-mongo` using credentials resolved from Consul Spring keys (`configuration/aaam-atr-v3-gateway/spring.data.mongodb.*`).
3. Provisions/updates the required groups (`IM_SAML`, `itsm_admin`, `itsm_user`, `itsm_read`) and clean permissions (`ticket_create`, `admin_all`, etc.) in the existing IM database.
4. Associates your existing admin user with the `itsm_admin` group.
5. Initializes and indexes ITSM's own operational collections (`incidents`, `service_requests`, `change_requests`, `users`, `projects`, `applications`, `sla_policies`) in isolated database `nexus_itsm` in `atr-mongo`.
6. Starts the container on the detected Docker network.

---

### Method 2: Direct MongoDB Shell Script (`mongosh`)
If you want to seed the collections directly in `atr-mongo` using `mongosh`:
```bash
docker exec -i atr-mongo mongosh -u atr -p <mongo_password> --authenticationDatabase admin < scripts/seed_im_mongo.js
```
*This script idempotently creates/refreshes the 4 groups with their simplified permission arrays, associates your existing admin user with `itsm_admin`, and creates ITSM collection indexes in `nexus_itsm`.*

---

### Method 3: REST API / cURL
If you want to invoke the `identity-management` REST API manually:

```bash
# 1. Login to get JWT
TOKEN=$(curl -s -X POST http://identity-management:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<admin_password_from_consul>"}' | jq -r .access_token)

# 2. Create the IM_SAML End-User Group
curl -X POST http://identity-management:8001/groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "IM_SAML",
    "description": "Default SSO End-User Group",
    "permissions": ["ticket_create","ticket_read_own","ticket_update","applications_read","projects_read"]
  }'

# 3. Create Support Fulfiller Group
curl -X POST http://identity-management:8001/groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "itsm_user",
    "description": "ITSM Support Fulfiller Group",
    "permissions": ["ticket_create","ticket_read","ticket_update","ticket_assign","ticket_resolve","applications_read","projects_read"]
  }'

# 4. Attach Corporate Support DL to Group (Optional Post-Install)
curl -X POST http://identity-management:8001/ad-mappings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ad_group_name": "<your-corporate-dl-name>",
    "target_role": "itsm_user",
    "description": "Corporate Support Team DL"
  }'
```

---

### Method 4: Via the `identity-management-client` UI (Post-Installation)
If an administrator prefers using the existing web interface:
1. Log in to `identity-management-client` as `admin`.
2. Groups and permissions (`IM_SAML`, `itsm_admin`, `itsm_user`, `itsm_read`) are automatically provisioned by the installer.
3. Navigate to **AD Groups / Distribution Lists** $\rightarrow$ **Add Mapping**:
   - Map your administrative DL (e.g. `IT-Platform-Admins`) $\rightarrow$ Select Group: `itsm_admin`.
   - Map your support DL (e.g. `Corporate-ServiceDesk`, `Cloud-Operations`) $\rightarrow$ Select Group: `itsm_user`.
   - Click **Save**.
4. Corporate users not belonging to a support DL automatically receive the `IM_SAML` end-user role upon login.

---

## 3. Turnkey Deployment Options

### Option A: One-Command Automated Deploy Script

Run the automated turnkey script on your Docker host:
```bash
./deploy-to-existing-app.sh
```
This script:
1. Detects your existing Docker network (where `atr-mongo` and `consul` are running).
2. Verifies reachability of the Spring Consul keys.
3. Runs `nexus-itsm-core:latest` attached to the existing network.
4. Executes the IM group and AD group bootstrap.

---

### Option B: Docker Compose Overlay

Add `nexus-itsm-core` into your existing stack using [`docker-compose.existing-app-addon.yml`](file:///Users/ritika/Downloads/application_repo/service_now_ai/docker-compose.existing-app-addon.yml):

```bash
EXISTING_DOCKER_NETWORK=<your_existing_network_name> docker compose -f docker-compose.existing-app-addon.yml up -d
```

---

### Option C: Kubernetes Cluster Deployment

If your existing stack runs in Kubernetes, apply the overlay manifest:
```bash
kubectl apply -f deploy/kubernetes/existing-cluster-overlay.yaml
```

---

## 4. Routing Configuration for Instances with Existing NGINX

When NGINX is already running on the instance (e.g. handling SSL on port 80/443 and routing to `identity-management`, `atr-gateway`, etc.), Nexus ITSM routes traffic cleanly under `/itsm/` and `/api/` with zero port conflicts.

### Scenario A: NGINX Runs in Docker (`nginx` container on same network)
Add the following blocks inside your existing NGINX `server { listen 443 ssl; ... }` block:

```nginx
# ==============================================================================
# Nexus ITSM Reverse Proxy Configuration (Docker Network)
# ==============================================================================

# 1. ITSM Web Application & Static Assets
location /itsm/ {
    proxy_pass http://nexus-itsm-core:8000/itsm/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    
    # WebSocket & HTTP/1.1 support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Extended timeouts
    proxy_connect_timeout 60s;
    proxy_send_timeout 120s;
    proxy_read_timeout 300s;
}

# 2. ITSM REST API Endpoints (incidents, service-requests, ai, etc.)
location /api/ {
    proxy_pass http://nexus-itsm-core:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Disable buffering for real-time AI Copilot streaming
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

### Scenario B: NGINX Runs Natively on the Host (`systemctl nginx`)
If NGINX runs directly on the Linux host, target port `8000` via loopback:

```nginx
location /itsm/ {
    proxy_pass http://127.0.0.1:8000/itsm/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

#### Test and Reload NGINX Without Downtime:
```bash
# Verify syntax
sudo nginx -t

# Hot reload without dropping connections
sudo nginx -s reload
# or
sudo systemctl reload nginx
```

### ATR-Gateway Route Definition (Optional)
If traffic passes through `atr-gateway` (Spring Cloud Gateway), add the route in `application.yml`:

```yaml
spring:
  cloud:
    gateway:
      routes:
        - id: itsm-core-route
          uri: http://nexus-itsm-core:8000
          predicates:
            - Path=/itsm/**
```

---

## 5. Verification Checklist

1. **Verify Core Container Health**:
   ```bash
   curl -i http://localhost:8000/health
   ```
   *Expected: HTTP 200 with `"status": "healthy"`, `"database": "connected (mongodb)"`*

2. **Verify Subpath HTML & Assets**:
   ```bash
   curl -i http://localhost:8000/itsm
   curl -i http://localhost:8000/itsm/static/css/style.css
   curl -i http://localhost:8000/itsm/api/applications
   ```

3. **Verify SAML Metadata under /itsm**:
   ```bash
   curl -i http://localhost:8000/itsm/api/id/saml/metadata.xml
   ```

4. **Verify IM Bootstrap**:
   Check that `IM_SAML` and `itsm_admin` groups are present in `identity-management` or `atr-mongo`:
   ```bash
   docker exec -it nexus-itsm-core python scripts/bootstrap_external_im.py
   ```

---

## 6. How Existing MongoDB is Utilized & Updated

Nexus ITSM is **100% native MongoDB** (`backend/mongo_dal.py`) and uses the existing `atr-mongo` instance for all persistence:

1. **Identity Management (IM) Collections**:
   - `custom_groups` / `groups`: Contains `IM_SAML`, `itsm_admin`, `itsm_user`, `itsm_read`, and project scoped groups with clean permissions (`ticket_create`, `ticket_read_own`, `ticket_update`, `applications_read`, `projects_read`).
   - `ad_group_mappings` / `adgroups`: Maps your existing support DLs (`ITSM-Admins`, `Service Desk`, `ITSM-Fulfillers`, `Tier1-Support`).

2. **ITSM Platform Operational Collections**:
   - Stored in MongoDB database `nexus_itsm` inside `atr-mongo`:
     - `incidents`: Incidents with SLA tracking, assignment groups, and history.
     - `service_requests`: Enterprise service catalog requests.
     - `change_requests`: RFCs with CAB workflows and risk matrix.
     - `projects` & `applications`: Hierarchical routing taxonomy.
     - `sla_policies`: Editable resolution and response targets.
     - `audit_logs`: SOC2 / ISO 27001 audit trails.
   - **Real-Time Updates**: Every ticket creation, status change, reassignment, and comment updates this existing MongoDB instance immediately with native atomic operations.
   - **No Relational Database Required**: Zero SQLite and Zero PostgreSQL dependencies.
