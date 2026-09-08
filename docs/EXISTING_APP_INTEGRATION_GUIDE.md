# Genwizard ITSM Core — Turnkey Integration Guide for Existing Application Stack

This guide details how to deploy the **Genwizard ITSM Core** image (`nexus-itsm-core:latest`) on top of an existing application stack already running:
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

### Core Permission-Bearing Groups Configured for Genwizard ITSM:

| Group Name | Purpose | Attached Permissions (Simplified, No Colons) |
|---|---|---|
| **`itsm_admin`** | Full Platform Administration | `admin_all`, `ticket_create`, `ticket_read`, `ticket_update`, `ticket_delete`, `ticket_assign`, `ticket_resolve`, `ticket_close`, `admin_routing`, `admin_slas`, `admin_config`, `users_manage`, `applications_read`, `projects_read` |
| **`itsm_user`** | Support Team Fulfiller | `ticket_create`, `ticket_read`, `ticket_update`, `ticket_assign`, `ticket_resolve`, `applications_read`, `projects_read` |
| **`itsm_read`** | Read-Only Auditor | `ticket_read`, `applications_read`, `projects_read` |
| **`IM_SAML`** | Default SSO End-User Group | `ticket_create`, `ticket_read_own`, `ticket_update` (comments & worknotes), `applications_read`, `projects_read` |
| **`ATR_SAML`** | Default SSO End-User Group (ATR SAML — alias for IM_SAML) | Same as `IM_SAML`: `ticket_create`, `ticket_read_own`, `ticket_update`, `applications_read`, `projects_read` |

### Admin User & Post-Installation DL Configuration:

- **Existing Admin User Association**: During installation, the system automatically associates your existing admin user in the existing app (`admin` or username resolved from Consul) with the **`itsm_admin`** group and permissions.
- **Dynamic Post-Installation DL Mappings**: Rather than enforcing hardcoded AD groups, you can map whatever real AD groups / Distribution Lists (DLs) your organization uses post-installation directly in your existing IM UI:
  - Go to: `https://<base-url>/identity-management/ad-groups` (or `/adGroups`)
  - Map your corporate DLs (e.g., `L1-Support-Team`, `Cloud-Admins`, `DevOps-Engineers`) to `itsm_user` or `itsm_admin`.
  - Any corporate user not explicitly in a support DL receives both the **`IM_SAML`** and **`ATR_SAML`** end-user groups upon SSO login.

> **End-User Experience**:
> When an employee whose AD groups are not added to a support DL logs in via SSO, they automatically receive both **`IM_SAML`** and **`ATR_SAML`** groups (whichever your IM platform uses).
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

### Method 3: REST API / cURL via atr-gateway
If you want to invoke the authentication and group APIs manually:

```bash
# 1. Login to get token via atr-gateway (with useDeflate=true)
curl -i -X POST "http://localhost/atr-gateway/identity-management/api/v1/auth/token?useDeflate=true" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<admin_password>"}'

# 2. Or if invoking Identity Management service directly:
TOKEN=$(curl -s -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<admin_password>"}' | jq -r .access_token)

# 3. Create the IM_SAML End-User Group
curl -X POST http://identity-management:8001/groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "IM_SAML",
    "description": "Default SSO End-User Group",
    "permissions": ["ticket_create","ticket_read_own","ticket_update","applications_read","projects_read"]
  }'

# 4. Create Support Fulfiller Group
curl -X POST http://identity-management:8001/groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "itsm_user",
    "description": "ITSM Support Fulfiller Group",
    "permissions": ["ticket_create","ticket_read","ticket_update","ticket_assign","ticket_resolve","applications_read","projects_read"]
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

### Option A: The Definitive Installer (`./install-existing-app.sh` — Recommended)

Run the single production installer on your Docker host:
```bash
./install-existing-app.sh
```
This installer:
1. **Auto-detects containers & network:** Discovers existing containers (`atr-mongo`, `atr-gateway`, `identity-management`, `consul`, `nginx`), finds their user-defined Docker network, and auto-attaches them so container DNS always works.
2. **Direct Consul Container Interaction:** Auto-detects the running Consul container and extracts Spring configuration keys (`admin.password`, `spring.data.mongodb.password`, `username`, `host`) directly via container CLI (`docker exec <consul-container> consul kv get ...`). This extracts credentials instantaneously without requiring HTTP port 8500 to be published on the host.
3. **Auto-detects IM port:** Detects whether IM is running on port 8080 or 8001.
4. **Resilient Launch:** Launches `nexus-itsm-core:latest` with `--add-host host.docker.internal:host-gateway` and the extracted Consul configuration pre-loaded.
5. **Automatic Group & Permission Sync:** Executes `bootstrap_external_im.py` inside the container. It authenticates via `atr-gateway` / IM REST APIs, and falls back to direct MongoDB synchronization in `atr-mongo`.

---

### Option B: Docker Compose Overlay

Add `nexus-itsm-core` into your existing stack using [`docker-compose.existing-app-addon.yml`](file:///Users/ritika/Downloads/application_repo/service_now_ai/docker-compose.existing-app-addon.yml):

```bash
docker compose -f docker-compose.existing-app-addon.yml up -d
```

---

### Option C: Kubernetes Cluster Deployment

If your existing stack runs in Kubernetes, apply the overlay manifest:
```bash
kubectl apply -f deploy/kubernetes/existing-cluster-overlay.yaml
```

---

## 4. Routing Configuration for Instances with Existing NGINX

When NGINX is running on the instance (handling SSL on port 443 alongside `/identity-management` and `/atr`), Genwizard ITSM integrates cleanly under `/itsm` with zero port conflicts.

### Scenario A: NGINX Runs in Docker (Matching Your Existing App Style)
Add this standard block inside your existing NGINX `server { listen 443 ssl; ... }` configuration:

```nginx
location /itsm
{
    set $upstream http://nexus-itsm-core:8000;
    proxy_pass $upstream;
    include /etc/nginx/conf.d.includes/header-csp-restricted.conf;
    proxy_hide_header ETag;
    add_header ETag "";
}
```

*Note: Genwizard ITSM has **zero external CDN dependencies**. All JS/CSS libraries are vendored locally, so it is 100% compliant with `header-csp-restricted.conf`.*

### Scenario B: NGINX Runs Natively on the Host (`systemctl nginx`)
If NGINX runs directly on the Linux host, target port `8000` via loopback:

```nginx
location /itsm {
    proxy_pass http://localhost:8000/itsm;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Port 443;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    client_max_body_size 50M;
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

Genwizard ITSM is **100% native MongoDB** (`backend/mongo_dal.py`) and uses the existing `atr-mongo` instance for all persistence:

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
