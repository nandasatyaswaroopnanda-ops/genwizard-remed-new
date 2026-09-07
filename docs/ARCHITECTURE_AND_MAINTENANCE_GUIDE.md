# Nexus ITSM Core — Complete Architecture, Codebase & Maintenance Reference Guide

This document serves as the **definitive technical reference, installation manual, and codebase maintenance guide** for the **Nexus ITSM** platform. It details the complete system architecture, step-by-step installation and post-installation procedures for environments where **NGINX and existing services are already running**, file-by-file code responsibilities, core operational engines, and day-to-day developer recipes for ongoing platform maintenance.

> 💡 **For Executive & Leadership Presentation:**
> If you are presenting to C-suite executives, VPs, or IT leadership, please also reference **[`EXECUTIVE_ARCHITECTURE_AND_SERVICENOW_COMPARISON.md`](EXECUTIVE_ARCHITECTURE_AND_SERVICENOW_COMPARISON.md)** for the side-by-side ServiceNow feature matrix, 3-year TCO/ROI financial breakdown (\$2.16M savings), and executive migration roadmap.

---

## Table of Contents
1. [Architecture Overview & Operating Principles](#1-architecture-overview--operating-principles)
2. [Step-by-Step Installation Guide](#2-step-by-step-installation-guide)
   - [2.1 Pre-requisites & Environment Check](#21-pre-requisites--environment-check)
   - [2.2 Option A: Automated Existing Stack Installer (`install-existing-app.sh`)](#22-option-a-automated-existing-stack-installer-install-existing-appsh)
   - [2.3 Option B: Air-Gapped / Offline Installation](#23-option-b-air-gapped--offline-installation)
   - [2.4 Option C: Docker Compose Manual Deploy](#24-option-c-docker-compose-manual-deploy)
   - [2.5 Option D: Native Systemd Service (Non-Docker on Linux)](#25-option-d-native-systemd-service-non-docker-on-linux)
3. [Step-by-Step Post-Installation Guide (Instances with Existing NGINX)](#3-step-by-step-post-installation-guide-instances-with-existing-nginx)
   - [3.1 Step 1: Health Check & Process Verification](#31-step-1-health-check--process-verification)
   - [3.2 Step 2: Existing NGINX Configuration & Reverse Proxy Setup](#32-step-2-existing-nginx-configuration--reverse-proxy-setup)
   - [3.3 Step 3: Identity Management (IM) & Corporate DL Mapping](#33-step-3-identity-management-im--corporate-dl-mapping)
   - [3.4 Step 4: Knowledge Management (KM) & AI Integration Setup](#34-step-4-knowledge-management-km--ai-integration-setup)
   - [3.5 Step 5: Verify SSO Login & User Personas](#35-step-5-verify-sso-login--user-personas)
   - [3.6 Step 6: Automated Auto-Closure Cron Setup](#36-step-6-automated-auto-closure-cron-setup)
4. [Codebase Map & File-by-File Technical Deep Dive](#4-codebase-map--file-by-file-technical-deep-dive)
   - [4.1 Backend Core (`backend/`)](#41-backend-core-backend)
   - [4.2 REST API Routers (`backend/routes/`)](#42-rest-api-routers-backendroutes)
   - [4.3 Identity Service Layer (`identity_service/`)](#43-identity-service-layer-identity_service)
   - [4.4 Frontend Single Page App (`frontend/`)](#44-frontend-single-page-app-frontend)
   - [4.5 Bootstrap & Seeding Scripts (`scripts/`)](#45-bootstrap--seeding-scripts-scripts)
   - [4.6 Deployment & Containerization Files](#46-deployment--containerization-files)
5. [Core Engine Mechanics](#5-core-engine-mechanics)
   - [5.1 6-Tier Ticket Routing Engine](#51-6-tier-ticket-routing-engine)
   - [5.2 Multi-Calendar SLA Tracking Engine](#52-multi-calendar-sla-tracking-engine)
   - [5.3 Multi-Project, Multi-Application & Multi-Group Cascading Matrix](#53-multi-project-multi-application--multi-group-cascading-matrix)
   - [5.4 Universal Timezone & Custom Date Range Filtering Engine](#54-universal-timezone--custom-date-range-filtering-engine)
   - [5.5 Short-Token KM Authentication Handshake](#55-short-token-km-authentication-handshake)
   - [5.6 Ticket Auto-Closure & Automation APIs](#56-ticket-auto-closure--automation-apis)
6. [Developer Maintenance Playbooks & Recipes](#6-developer-maintenance-playbooks--recipes)
   - [6.1 Adding a New Ticket Field (Model $\to$ Schema $\to$ Route $\to$ UI)](#61-adding-a-new-ticket-field-model--schema--route--ui)
   - [6.2 Adding a New Custom Permission or Role](#62-adding-a-new-custom-permission-or-role)
   - [6.3 Adding a New REST API Endpoint](#63-adding-a-new-rest-api-endpoint)
   - [6.4 Updating Consul Configuration via CLI](#64-updating-consul-configuration-via-cli)
   - [6.5 MongoDB Backup, Migration & Restoration](#65-mongodb-backup-migration--restoration)
7. [Day-to-Day Operations CLI Cheat Sheet & Troubleshooting](#7-day-to-day-operations-cli-cheat-sheet--troubleshooting)

---

## 1. Architecture Overview & Operating Principles

```mermaid
graph TD
    User["End-User / Engineer (Browser)"] -->|HTTPS /itsm| NGINX["Perimeter NGINX (Port 443/80 - Existing)"]
    NGINX -->|Reverse Proxy /itsm/ or /api/| CORE["nexus-itsm-core (Port 8000)"]
    
    subgraph "Nexus ITSM Container / Service"
        CORE --> ROUTE["6-Tier Routing Engine"]
        CORE --> SLA["Multi-Calendar SLA Engine"]
        CORE --> WF["Workflow & State Engine"]
        CORE --> COPILOT["AI Copilot & KM Provider"]
        CORE --> DAL["Native MongoDB DAL (nexus_itsm)"]
    end

    subgraph "Existing Infrastructure Stack"
        CORE -->|Consul KV (Port 8500)| CONSUL["HashiCorp Consul"]
        CORE -->|Native Mongo (Port 27017)| MONGO["atr-mongo (Database: nexus_itsm)"]
        CORE -->|Short-Token Auth (Port 8080)| GW["atr-gateway"]
        GW -->|User/Group Sync (Port 8001)| IM["identity-management"]
    end
```

### Architectural Principles
1. **100% Native MongoDB Persistence:** Operates strictly within an isolated database `nexus_itsm` in `atr-mongo`. Zero dependency on SQLite or PostgreSQL.
2. **Zero Disruption to Existing Stack:** Never alters, drops, or overwrites existing collections (`aaam`, `atr`, etc.) in `atr-mongo`.
3. **Dynamic Consul Resolution:** Reads database credentials (`spring.data.mongodb.*`), admin password, and base platform DNS dynamically from HashiCorp Consul at runtime with automatic fallbacks.
4. **Existing NGINX Compatibility:** Seamlessly proxies under `/itsm/` (and `/api/`) alongside existing endpoints without port conflicts.
5. **Defense-in-Depth Security:** Non-root execution (`app:10001`), strict Role-Based Access Control (RBAC), sanitized file uploads (path traversal prevention), and hardened CORS policies.
6. **Short-Token Authentication Handshake:** Interacts with `atr-gateway` and Knowledge Management (KM) using standard short-lived deflated tokens (`?useDeflate=true`).
7. **No Pre-injected Hardcoded DLs:** Associates the existing admin user with `itsm_admin`. Corporate DLs can be flexibly mapped post-installation in the IM UI.
8. **Universal Multi-Project & Cascading Selection:** Native multi-select dropdowns for Projects, Applications, and Assignment Groups across all ticket management consoles.

---

## 2. Step-by-Step Installation Guide

### 2.1 Pre-requisites & Environment Check
Verify that the host server has the following existing services running:
```bash
# Check existing Docker containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```
Expected running services:
- `atr-mongo` (MongoDB on port 27017)
- `identity-management` (Port 8001)
- `consul` (Port 8500)
- `nginx` (Port 80 / 443)
- `atr-gateway-container` (Port 8080)

Extract the release archive on the server:
```bash
mkdir -p /opt/nexus-itsm && cd /opt/nexus-itsm
tar -zxvf nexus-itsm-addon.tar.gz
```

---

### 2.2 Option A: Automated Existing Stack Installer (`install-existing-app.sh`)
If the server has Docker running:
```bash
chmod +x install-existing-app.sh
./install-existing-app.sh
```
**What this script executes automatically:**
1. Auto-detects the Docker network connecting `atr-mongo`, `identity-management`, and `consul`.
2. Resolves MongoDB credentials from Consul Spring keys (`spring.data.mongodb.*`).
3. Provisions required groups (`itsm_admin`, `itsm_user`, `itsm_read`, `IM_SAML`) in Identity Management and assigns `itsm_admin` to the existing admin user.
4. Initializes collections and indexes in MongoDB database `nexus_itsm`.
5. Builds or loads and starts `nexus-itsm-core:latest` attached to the existing Docker network on port `8000`.

---

### 2.3 Option B: Air-Gapped / Offline Installation
For environments without internet access on the production host:
1. **On a machine with internet access**, build and export the Docker image:
   ```bash
   chmod +x package-offline-image.sh
   ./package-offline-image.sh
   ```
   This produces `nexus-itsm-core-image.tar.gz`.
2. **Transfer both files** to the destination server:
   - `nexus-itsm-addon.tar.gz`
   - `nexus-itsm-core-image.tar.gz`
3. **Run the installer on the offline host**:
   ```bash
   tar -zxvf nexus-itsm-addon.tar.gz
   # Place nexus-itsm-core-image.tar.gz in the extracted folder
   ./install-existing-app.sh
   ```
   The installer automatically detects `nexus-itsm-core-image.tar.gz`, executes `docker load`, and starts the container without internet access.

---

### 2.4 Option C: Docker Compose Manual Deploy
If you prefer running Docker Compose directly:
```bash
# Identify your existing docker network
NET=$(docker inspect atr-mongo --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -n1)

# Launch container
EXISTING_DOCKER_NETWORK="$NET" docker compose -f docker-compose.existing-app-addon.yml up -d
```

---

### 2.5 Option D: Native Systemd Service (Non-Docker on Linux)
If the existing environment runs Python directly on the host rather than inside Docker:

1. **Install Dependencies in Virtualenv:**
   ```bash
   cd /opt/nexus-itsm
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Create Systemd Service File (`/etc/systemd/system/nexus-itsm.service`):**
   ```ini
   [Unit]
   Description=Nexus ITSM Control Plane Service
   After=network.target nginx.service

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/nexus-itsm
   Environment="PYTHONPATH=/opt/nexus-itsm"
   Environment="MONGO_URL=mongodb://atr:YourMongoPassword@127.0.0.1:27017/nexus_itsm?authSource=admin"
   Environment="MONGO_DATABASE=nexus_itsm"
   Environment="CONSUL_HTTP_ADDR=http://127.0.0.1:8500"
   Environment="IDENTITY_SERVICE_URL=http://127.0.0.1:8001"
   ExecStart=/opt/nexus-itsm/.venv/bin/python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. **Enable and Start Service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable nexus-itsm
   sudo systemctl start nexus-itsm
   sudo systemctl status nexus-itsm
   ```

---

## 3. Step-by-Step Post-Installation Guide (Instances with Existing NGINX)

When NGINX is already running on the instance (handling SSL termination on ports 80/443 and serving existing applications like Identity Management or ATR Gateway), follow these exact steps to route traffic to Nexus ITSM without any port conflict.

### 3.1 Step 1: Health Check & Process Verification
Confirm that Nexus ITSM is running and accessible locally:
```bash
# 1. Verify process/container
curl -s http://127.0.0.1:8000/health | jq .
# Expected output:
# {
#   "status": "healthy",
#   "database": "connected (mongodb)",
#   "database_name": "nexus_itsm"
# }

# 2. Verify metadata APIs are responding
curl -s http://127.0.0.1:8000/api/projects | jq '.[0].name'
curl -s http://127.0.0.1:8000/api/applications | jq '.[0].name'
```

---

### 3.2 Step 2: Existing NGINX Configuration & Reverse Proxy Setup

Nexus ITSM is built to run cleanly under the subpath `/itsm/` (with API calls routed to `/api/` or `/itsm/api/`).

#### Scenario A: NGINX Runs in a Docker Container (`nginx`)
Edit your existing NGINX site configuration (e.g. `/etc/nginx/conf.d/default.conf` or host volume mounted to NGINX):

```nginx
# ==============================================================================
# Nexus ITSM Reverse Proxy Configuration
# Add inside the existing 'server { listen 443 ssl; ... }' block
# ==============================================================================

# 1. ITSM Web Frontend & Subpath Assets
location /itsm/ {
    # If NGINX is in same Docker network as nexus-itsm-core:
    proxy_pass http://nexus-itsm-core:8000/itsm/;
    
    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    
    # WebSocket & HTTP/1.1 support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Extended timeouts for large reports / AI queries
    proxy_connect_timeout 60s;
    proxy_send_timeout 120s;
    proxy_read_timeout 300s;
}

# 2. ITSM REST API Endpoints
location /api/ {
    proxy_pass http://nexus-itsm-core:8000/api/;
    
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Turn off buffering for real-time AI Copilot streaming
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

#### Scenario B: NGINX Runs Natively on Host (`sudo systemctl status nginx`)
If NGINX runs directly on the Linux host, target `127.0.0.1:8000`:
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
# Verify configuration syntax
sudo nginx -t

# Hot reload NGINX without dropping active connections
sudo nginx -s reload
# or
sudo systemctl reload nginx
```

---

### 3.3 Step 3: Identity Management (IM) & Corporate DL Mapping
Because zero hardcoded Active Directory groups are pre-configured, map your organization's actual Active Directory Distribution Lists (DLs) post-installation:

1. Log into your existing **Identity Management Client UI** as an administrator (`https://<domain>/identity-management/`).
2. Navigate to **AD Groups / Distribution Lists** $\rightarrow$ **Add Mapping**:
   - Map your administrative DL (e.g., `IT-System-Admins`) $\rightarrow$ select Group **`itsm_admin`**.
   - Map your engineer support DLs (e.g., `L1-ServiceDesk`, `Cloud-Operations`) $\rightarrow$ select Group **`itsm_user`**.
   - Map your compliance/auditor DLs $\rightarrow$ select Group **`itsm_read`**.
3. **Save Changes**.
4. *Note: Any corporate employee not mapped to a support DL automatically receives the default `IM_SAML` end-user persona upon SSO login.*

---

### 3.4 Step 4: Knowledge Management (KM) & AI Integration Setup
Configure external Knowledge Management and AI copilot settings:
1. Open Nexus ITSM in your browser (`https://<domain>/itsm/`).
2. Navigate to **Consul KV & KM Config** (`#/admin/consul`) or **AI Integration & Analytics** (`#/admin/ai`).
3. Configure your environment parameters:
   - **KM App Base URL:** (e.g. `https://km.internal.company.com`) — *Clearly displayed for reference*.
   - **API Endpoint:** `/api/chat/completions`
   - **KM Index:** `itsm-kb`
   - **Username & Password:** *Securely masked in the UI*.
4. Click **Save KM Configuration & Sync to Consul**.
5. Click **Test Connection** in the AI Integration page to verify connectivity.

---

### 3.5 Step 5: Verify SSO Login & User Personas
Verify both user personas work as expected:
1. **Admin / Support Persona:**
   - Log in with your corporate credentials as a user belonging to an `itsm_admin` or `itsm_user` DL.
   - Verify access to **Unified Tickets**, **Incidents**, **Service Requests**, **Change Requests**, **Analytics**, and **Administration**.
   - Test **Multi-Project Selection** in the filter bar &rarr; select 2+ projects &rarr; verify applications and assignment groups cascade accurately.
2. **End-User Persona:**
   - Log in as a regular corporate employee (belonging to `IM_SAML`).
   - Verify the simplified **Service Desk** portal appears with access strictly limited to:
     - **Create Ticket**
     - **My Tickets** (can view and submit comments / work notes)
     - **Applications** & **Projects**
   - Verify restricted menus (Administration, SLA configuration, assignment queues) are completely hidden.

---

### 3.6 Step 6: Automated Auto-Closure Cron Setup
To automatically move resolved tickets older than 48 hours to `Closed`, configure a host cron job:
```bash
crontab -e
```
Add this entry (runs daily at 02:00 AM):
```cron
0 2 * * * curl -s -X POST http://127.0.0.1:8000/api/incidents/auto-close -H "Content-Type: application/json" -H "X-User-ID: 1" -d '{"hours_in_resolved": 48}' > /dev/null 2>&1
```

---

## 4. Codebase Map & File-by-File Technical Deep Dive

### 4.1 Backend Core (`backend/`)

| File Path | Component | Detailed Responsibilities & Architecture |
| :--- | :--- | :--- |
| **`backend/main.py`** | Application Entrypoint | • FastAPI instance and lifespan event management.<br>• Mounts `/itsm` subpath static files and ASGI middleware.<br>• Configures CORS policy (`CORS_ORIGINS`).<br>• Registers all 18 modular API routers.<br>• On startup: creates MongoDB indexes in `nexus_itsm`, verifies Consul connectivity, and associates existing admin. |
| **`backend/models.py`** | Object Models & Schemas | • Defines BSON document schemas: `Incident`, `ServiceRequest`, `ChangeRequest`, `Application`, `Project`, `AssignmentGroup`, `SLAPolicy`, `Calendar`, `Taxonomy`, `AIConfiguration`, `AIAuditLog`.<br>• Implements serialization `to_dict()` methods with ISO datetime formatting. |
| **`backend/mongo_dal.py`** | MongoDB Data Access Layer | • Native MongoDB driver emulation matching SQLAlchemy session semantics (`query()`, `filter()`, `add()`, `commit()`, `all()`, `first()`).<br>• Resolves credentials dynamically from Consul Spring keys.<br>• Enforces isolation in database `nexus_itsm`. |
| **`backend/routing_engine.py`** | 6-Tier Routing Matrix | • Evaluates priority (`P1` to `P4`) based on urgency + impact.<br>• Resolves assignment queue via waterfall hierarchy: Exact $\to$ Category $\to$ App $\to$ Project Default $\to$ App Default $\to$ Global Service Desk. |
| **`backend/sla_engine.py`** | SLA Calculation Engine | • Matches active SLA policies against ticket attributes.<br>• Computes response and resolution due timestamps.<br>• Incorporates business calendars (24x7, 9x5 weekdays, company holidays).<br>• Manages timer pauses when in `Pending` state. |
| **`backend/workflow_engine.py`** | State Machine Engine | • Enforces ticket lifecycle progression.<br>• Validates status transitions for Incidents (`New` $\to$ `In Progress` $\to$ `Resolved` $\to$ `Closed`), Requests, and Changes. |
| **`backend/ai_copilot.py`** | AI Copilot & KM Provider | • Handles KM communication and runbook search.<br>• Executes two-stage short-token handshake with `atr-gateway` (`?useDeflate=true`).<br>• Built-in `EnterpriseKnowledgeFallback` if KM is unreachable. |
| **`backend/security.py`** | Security & RBAC | • JWT bearer token validation and permission verification.<br>• Resolves permissions (`ticket_create`, `admin_all`).<br>• Redacts internal work notes from end-user API responses. |
| **`backend/notification_engine.py`**| Notification Dispatcher | • Manages in-app notifications on ticket assignment, creation, and status updates. |
| **`backend/database.py`** | Session Factory | • Database session lifecycle management for route dependencies. |
| **`backend/seed_data.py`** | Default Seeder | • Seeds baseline demonstration projects, applications, sample groups, and calendars if collections are empty. |

---

### 4.2 REST API Routers (`backend/routes/`)

| File Path | Route Prefix | Responsibility & Key Endpoints |
| :--- | :--- | :--- |
| **`backend/routes/incidents.py`** | `/api/incidents` | Incident lifecycle management: create, query, assign, resolve, close, work notes, and **Batch Auto-Closure (`POST /auto-close`)**. |
| **`backend/routes/service_requests.py`** | `/api/service-requests` | Service catalog request creation, multi-stage approval workflows, fulfillment, and batch auto-closure. |
| **`backend/routes/changes.py`** | `/api/changes` | RFC management (Standard, Normal, Emergency), CAB reviews, risk assessment, schedule governance. |
| **`backend/routes/ai_chat.py`** | `/api/ai` | Chat assistant endpoints, quick actions (troubleshoot, summarize, draft response), connection test, and `/analytics` endpoint. |
| **`backend/routes/admin_projects.py`** | `/api/projects` | Project administration, project-level queue configuration, and project-scoped admin boundaries. |
| **`backend/routes/admin_applications.py`** | `/api/applications` | Application CMDB registry, technical owners, support hours, and escalation paths. |
| **`backend/routes/admin_groups.py`** | `/api/assignment-groups` | Queue management, engineer memberships, distribution lists, and on-call rosters (`Level-2` / `Level-3` support). |
| **`backend/routes/admin_slas.py`** | `/api/sla-policies` | SLA policy definition, priority targets, effective date versioning (`create_new_version`), and scoped group editing. |
| **`backend/routes/admin_calendars.py`** | `/api/calendars` | Business hour schedules (24x7, 9x5 weekdays) and company statutory holiday lists. |
| **`backend/routes/admin_routing.py`** | `/api/routing-rules` | 6-tier routing rule management with priority ordering. |
| **`backend/routes/admin_configuration.py`** | `/api/admin/configuration` | Consul KV synchronization, KM settings with masked credentials (`username`, `password`), and runtime log level toggling. |
| **`backend/routes/dashboard.py`** | `/api/dashboard` | Executive KPI metrics: MTTR, SLA compliance %, breach counts, and ticket volume breakdown. |
| **`backend/routes/attachments.py`** | `/api/attachments` | Secure file uploads and downloads with 15MB limit, whitelist extensions, and path traversal guards. |
| **`backend/routes/exports.py`** | `/api/export` | CSV export for tickets, SLA audits, and executive reporting. |
| **`backend/routes/config_io.py`** | `/api/config-io` | Complete JSON export/import of platform configuration. |
| **`backend/routes/simulator.py`** | `/api/simulator` | Interactive test sandbox to preview routing and SLA matching before creating tickets. |
| **`backend/routes/knowledge.py`** | `/api/knowledge` | Knowledge base article search and retrieval. |
| **`backend/routes/users.py`** | `/api/users` | User profile retrieval and team directory. |

---

### 4.3 Identity Service Layer (`identity_service/`)

- **`identity_service/main.py`**: Authentication service, JIT user provisioning, SAML SP metadata generation, and automatic association of `itsm_admin` with the existing admin user.
- **`identity_service/security.py`**: Evaluates user privileges, maps AD group claims to permissions, and ensures backwards compatibility between legacy colon permissions (`tickets:create`) and simplified underscore permissions (`ticket_create`).

---

### 4.4 Frontend Single Page App (`frontend/`)

- **`frontend/index.html`**: Production HTML shell featuring responsive sidebar, top navbar, global search modals, ticket detail drawers, AI Copilot drawer, and cache-busted script loading (`js/app.js?v=2.10.0`).
- **`frontend/js/app.js`**: Complete client-side application logic:
  - **Single-Page Routing:** Hash-based navigation (`#/dashboard`, `#/my-tickets`, `#/incidents`, `#/service-requests`, `#/changes`, `#/admin/ai`, `#/admin/consul`, etc.).
  - **Multi-Select Dropdown Component (`createMultiSelectDropdown`):** Reusable dropdown with search, select-all, clear, checkboxes, and count badges.
  - **Cascading Filter Engine:** Selecting projects dynamically filters applications and assignment groups (`getFilteredAssignmentGroups`).
  - **Universal Time Zone Engine:** `SUPPORTED_TIMEZONES`, `formatTicketDate(isoString, timeZone)` using `Intl.DateTimeFormat`, and timezone-aware filtering.
  - **Custom Time Range Component:** Collapsible datetime-local range picker with real-time filtering and reset.
  - **Telemetry Dashboard:** Live project-specific metrics, resolution rates, and scope badges.
  - **Role-Based UI Gating:** Dynamic view trimming hiding administration and operational queues from end-users.
- **`frontend/sso-redirect.html`**: SSO bridge page parsing incoming SAML assertions, token hydration, and automated routing.

---

### 4.5 Bootstrap & Seeding Scripts (`scripts/`)

- **`scripts/bootstrap_external_im.py`**: Non-destructive IM bootstrap script; provisions groups (`itsm_admin`, `itsm_user`, `itsm_read`, `IM_SAML`), clean permissions, and assigns `itsm_admin` to the existing admin user.
- **`scripts/seed_im_mongo.js`**: Standalone MongoDB shell script (`mongosh`) for direct database seeding.

---

### 4.6 Deployment & Containerization Files

- **`install-existing-app.sh`**: Automated turnkey installer for the existing container stack (`atr-mongo`, `identity-management`, `consul`, `nginx`).
- **`package-offline-image.sh`**: Helper script to build and export `nexus-itsm-core-image.tar.gz` for offline / air-gapped environments.
- **`docker-compose.existing-app-addon.yml`**: Docker Compose definition linking `nexus-itsm-core` into the existing Docker network.
- **`Dockerfile`**: Multi-stage production container definition running non-root (`USER app`, UID 10001).

---

## 5. Core Engine Mechanics

### 5.1 6-Tier Ticket Routing Engine
When an incident is created, `routing_engine.py` evaluates rules using a top-down waterfall hierarchy:

```
[Tier 1: Exact Match]      Project + Application + Category + Subcategory
         │ (if no match)
         ▼
[Tier 2: Category Match]   Project + Application + Category
         │ (if no match)
         ▼
[Tier 3: App Match]        Project + Application
         │ (if no match)
         ▼
[Tier 4: Project Default]  Project Default Queue (Level-2 Frontier)
         │ (if no match)
         ▼
[Tier 5: App Default]      Application Default Queue
         │ (if no match)
         ▼
[Tier 6: Global Fallback]  Global Service Desk Queue
```

---

### 5.2 Multi-Calendar SLA Tracking Engine
1. **Target Calculation:** When a ticket is created, `sla_engine.py` inspects the priority (`P1` to `P4`) and assigned queue.
2. **Business Hours:** If assigned to a `9x5 Weekdays` calendar, time elapsed outside 09:00–18:00 or on declared company holidays is excluded from SLA calculations.
3. **State Pause:** Moving a ticket to `Pending` status freezes SLA clocks. Returning to `In Progress` recalculates `due_at` by adding elapsed pause duration.

---

### 5.3 Multi-Project, Multi-Application & Multi-Group Cascading Matrix
The platform features synchronized multi-select filtering:
- **Project Selection:** Users can select 0 (All Projects), 1, or multiple projects simultaneously.
- **Cascading Applications:** The application dropdown dynamically updates to display applications supported by *any* of the selected projects.
- **Cascading Assignment Groups (`getFilteredAssignmentGroups`):** Groups are evaluated against arrays of selected projects and applications, including project prefixes (e.g. `CPM-Level-2`), metadata attributes (`projects_supported`, `applications_supported`), and fallback group lists.
- **Dynamic Scope Badge:** Visual feedback in the dashboard dynamically updates (e.g. `Project: Alpha`, `Projects: Alpha, Beta`, or `3 Projects (2 Apps)`).

---

### 5.4 Universal Timezone & Custom Date Range Filtering Engine
- **Timezone Selection:** Supports major corporate timezones (UTC, Browser Local, US Eastern/Central/Mountain/Pacific, London, Paris, India IST, Singapore, Tokyo, Sydney).
- **Localized Formatting:** Uses browser `Intl.DateTimeFormat` to render table timestamps in the active timezone without server re-fetching.
- **Custom Range Bounds:** `matchesTimeRange(createdAt, timeFilter, customStart, customEnd, timeZone)` parses ISO strings, translates calendar days into the active timezone, and applies strict timestamp comparison.

---

### 5.5 Short-Token KM Authentication Handshake
When querying AI Copilot:
1. **Stage 1 (Token Acquisition):**
   ```http
   POST /atr-gateway/identity-management/api/v1/auth/token?useDeflate=true
   Accept: */*
   Content-Type: application/json

   {"username": "admin", "password": "<consul_admin_password>"}
   ```
2. **Stage 2 (KM Query):**
   The returned short-token is placed in the `Authorization: Bearer <short_token>` header of the outgoing KM search request.
3. **Failsafe:** If KM is unavailable, `EnterpriseKnowledgeFallback` immediately returns runbook procedures without disrupting the user.

---

### 5.6 Ticket Auto-Closure & Automation APIs
Tickets in `Resolved` or `Fulfilled` status for more than a specified threshold (e.g. 48 hours) can be transitioned to `Closed` automatically via:
```bash
POST /api/incidents/auto-close
Content-Type: application/json
X-User-ID: 1

{"hours_in_resolved": 48}
```
Returns count of tickets closed and audit log entries generated.

---

## 6. Developer Maintenance Playbooks & Recipes

### 6.1 Adding a New Ticket Field (Model $\to$ Schema $\to$ Route $\to$ UI)
To add a new field (e.g. `cost_center`) to incidents:

1. **Update Database Model (`backend/models.py`):**
   ```python
   # In class Incident(Base):
   cost_center = Column(String(50), nullable=True)

   # In to_dict(self):
   "cost_center": self.cost_center,
   ```
2. **Update Request Schema (`backend/routes/incidents.py`):**
   ```python
   # In class IncidentCreateSchema(BaseModel):
   cost_center: Optional[str] = None
   ```
3. **Update Creation Logic (`backend/routes/incidents.py`):**
   ```python
   # Inside create_incident endpoint:
   cost_center=payload.cost_center,
   ```
4. **Update Frontend UI (`frontend/js/app.js`):**
   Add the input inside the incident modal and render it in the detail view drawer.

---

### 6.2 Adding a New Custom Permission or Role
1. In `scripts/bootstrap_external_im.py` and `scripts/seed_im_mongo.js`, append your new permission code (e.g. `audit_export`) to the target group in `REQUIRED_GROUPS`.
2. In `backend/security.py`, define a route dependency if you wish to protect an endpoint:
   ```python
   def require_audit_export(user: User = Depends(get_current_user)):
       if "audit_export" not in user.permissions and user.role != "itsm_admin":
           raise HTTPException(status_code=403, detail="Permission Denied")
   ```
3. Protect your route with `dependencies=[Depends(require_audit_export)]`.

---

### 6.3 Adding a New REST API Endpoint
1. Create or edit a router in `backend/routes/`:
   ```python
   from fastapi import APIRouter, Depends
   router = APIRouter(prefix="/api/my-feature", tags=["MyFeature"])

   @router.get("/")
   def list_items(db: Session = Depends(get_db)):
       return {"items": []}
   ```
2. Register the router in `backend/main.py`:
   ```python
   from backend.routes.my_feature import router as my_feature_router
   app.include_router(my_feature_router)
   ```

---

### 6.4 Updating Consul Configuration via CLI
To update runtime parameters without rebuilding code:
```bash
# Update Mongo Password in Consul
docker exec consul consul kv put configuration/aaam-atr-v3-gateway/spring.data.mongodb.password "NewSecretPassword"

# Update Base Platform DNS
docker exec consul consul kv put configuration/aaam-atr-v3-gateway/dns "portal.yourcompany.com"

# Restart container to pick up changes
docker compose -f docker-compose.existing-app-addon.yml restart nexus-itsm-core
```

---

### 6.5 MongoDB Backup, Migration & Restoration
To back up the isolated `nexus_itsm` database:
```bash
# Backup
docker exec atr-mongo mongodump -u atr -p <password> --authenticationDatabase admin --db nexus_itsm --out /data/backup/nexus_itsm_$(date +%F)

# Restore
docker exec atr-mongo mongorestore -u atr -p <password> --authenticationDatabase admin --db nexus_itsm /data/backup/nexus_itsm_YYYY-MM-DD/nexus_itsm
```

---

## 7. Day-to-Day Operations CLI Cheat Sheet & Troubleshooting

| Action | Command |
| :--- | :--- |
| **Check container health** | `docker ps --filter "name=nexus-itsm-core"` |
| **View live container logs** | `docker compose -f docker-compose.existing-app-addon.yml logs -f nexus-itsm-core` |
| **Restart container** | `docker compose -f docker-compose.existing-app-addon.yml restart nexus-itsm-core` |
| **Test NGINX config** | `sudo nginx -t` |
| **Reload NGINX** | `sudo nginx -s reload` |
| **Run full test suite** | `./.venv/bin/pytest -v` |
| **Trigger batch auto-closure** | `curl -X POST http://127.0.0.1:8000/api/incidents/auto-close -H "Content-Type: application/json" -H "X-User-ID: 1" -d '{"hours_in_resolved": 48}'` |
| **Inspect Mongo collections** | `docker exec -it atr-mongo mongosh -u atr -p --authenticationDatabase admin --eval "use nexus_itsm; show collections"` |
| **Seed Mongo manually** | `docker exec -i atr-mongo mongosh -u atr -p <pass> --authenticationDatabase admin < scripts/seed_im_mongo.js` |
| **Export offline Docker image** | `./package-offline-image.sh` |

### Common Troubleshooting Runbook

1. **Issue: NGINX returns `502 Bad Gateway` on `/itsm/` or `/api/`**
   - *Cause:* Nexus ITSM backend is not running or listening on port 8000, or NGINX cannot resolve `nexus-itsm-core`.
   - *Fix:* Check container: `docker ps --filter "name=nexus-itsm-core"`. If NGINX runs on the host, ensure `proxy_pass` targets `http://127.0.0.1:8000/`. If NGINX runs in Docker, ensure NGINX and `nexus-itsm-core` share the same Docker network.

2. **Issue: Container exits or fails to start with Mongo connection error**
   - *Cause:* `atr-mongo` host is not resolvable or Docker network is mismatched.
   - *Fix:* Verify Docker network: `docker inspect atr-mongo --format '{{json .NetworkSettings.Networks}}'`. Re-run `./install-existing-app.sh` to auto-attach to the correct network.

3. **Issue: AI Integration & Analytics shows error**
   - *Cause:* Backend analytics endpoint or KM endpoint unreachable.
   - *Fix:* Verify `GET /api/ai/analytics` returns 200. Check KM App Base URL in `#/admin/consul`.

4. **Issue: End users see administrator navigation items**
   - *Cause:* User's SAML/SSO claims assigned them to a support group.
   - *Fix:* Check user's assigned DLs in IM (`/identity-management/ad-groups` or `/adGroups`). Remove them from support DLs so they receive the default `IM_SAML` end-user role.
