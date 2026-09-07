# Nexus ITSM — Enterprise IT Service Management Platform & Control Plane

Nexus ITSM is a next-generation IT Service Management (ITSM) control plane inspired by ServiceNow, designed from the ground up to make **Project → Assignment Group → SLA Policy** a first-class, dynamic configuration chain throughout the entire platform.

Nexus features a zero-code administration control plane, a 6-tier assignment routing engine, multi-version SLA engine with business calendar support, full Incident/Request/Change workflows, role-based access control, universal multi-project selection with cascading filters, custom timezone and date range engine, and a first-class **AI Knowledge Assistant / Support Copilot** integrating with enterprise ChatCompletion APIs.

> ### 📚 Core Documentation Guides
> - **[Executive Architecture & Platform Comparison (ServiceNow vs. Nexus ITSM)](docs/EXECUTIVE_ARCHITECTURE_AND_SERVICENOW_COMPARISON.md)**: Leadership-level decision brief, comprehensive side-by-side comparison matrix, 3-year TCO & ROI model (\$2.16M savings), and architecture blueprints.
> - **[Complete Architecture, Codebase & Maintenance Reference Guide](docs/ARCHITECTURE_AND_MAINTENANCE_GUIDE.md)**: Deep dive into all source code files (`backend/`, `frontend/`, `identity_service/`, `scripts/`, `deploy/`), core engines, developer maintenance playbooks, day-to-day operations CLI cheat sheet, and step-by-step post-installation guide for instances where NGINX and existing stacks are already running.
> - **[Turnkey Integration Guide for Existing Application Stack](docs/EXISTING_APP_INTEGRATION_GUIDE.md)**: Production deployment instructions alongside `atr-mongo`, `identity-management`, `consul`, and `nginx` with zero port conflicts.

## Enterprise Identity, Distribution Lists, and Data Stores

The portal supports Keycloak SSO for all `@accenture.com` users. When `KEYCLOAK_ISSUER` is set, the SPA starts the Keycloak authorization-code flow and the API validates the signed bearer token against the realm JWKS. A user is provisioned on first login with `employee` access. Realm/client roles `administrator`, `admin`, or `itsm-admin` grant administration rights; `support_member`, `support`, `itsm-support`, and `group_manager` grant support rights.

Admin-only APIs configure the operational model:

- `POST /api/admin/applications` and `PUT /api/admin/applications/{id}`
- `POST /api/admin/projects` and project-to-assignment-group mappings
- `POST /api/admin/groups` and `POST /api/admin/groups/{id}/distribution-lists`

An assignment group may have any number of DLs. Every DL is configured as either `support` or `administrator`, independently of its notification setting. Configure Keycloak's groups mapper to emit each member DL email (for example `/payments-support@accenture.com`) in `groups` or `distribution_lists`; the portal maps that membership to the configured support/admin privilege.

MongoDB is the exclusive, primary datastore across the entire Nexus ITSM platform (configured via `MONGO_URL` and `MONGO_DATABASE`). There is zero dependency on SQLite or PostgreSQL. All relational tables (Incidents, Service Requests, Changes, Applications, Projects, Assignment Groups, SLAs, Routing Rules, Taxonomy, Users, Custom Groups, AD Mappings, Audits, etc.) are stored natively as BSON documents within the `nexus_itsm` database under user `mongo-atr`. Atomic sequential ticket IDs are guaranteed via MongoDB `$inc` counters, allowing seamless multi-pod scalability in Kubernetes.

For the KM integration, configure the IM endpoint and client credentials in the AI admin API using `env:NAME` secret references. The service first exchanges the IM credentials for a short-lived token and exposes it only as `{{short_token}}` while interpolating the KM payload. The short token is never stored in the database or returned from an API.

---

## 🏛 Architecture & Configuration Model

```
Application
    ↓
Project
    ↓
Routing Rules (6-Tier Evaluation Engine)
    ↓
Assignment Group
    ↓
SLA Policy (Versioning v1, v2 + Precedence Hierarchy)
    ↓
Business Calendar (Working Hours & Statutory Holidays)
    ↓
Workflow & Approvals (Standard, Normal, Emergency)
    ↓
Notification Policy (Customer-visible vs Strict Internal Work Notes)
```

### 1. 6-Tier Routing Engine Hierarchy
When an Incident or Service Request is submitted, the assignment group is resolved dynamically through a 6-tier precedence chain:
1. **Explicit Routing Rule**: Matches `Application + Project + Category/Subcategory` (e.g. Category `Database` $\rightarrow$ `Database Support`).
2. **App + Project + Category Mapping**: `ProjectAssignmentMapping` record scoped to category.
3. **App + Project Mapping**: `ProjectAssignmentMapping` record scoped to project.
4. **Project Default Assignment Group**: Configured on `Project.default_assignment_group_id`.
5. **Application Default Assignment Group**: Configured on `Application.default_assignment_group_id`.
6. **Global Default Assignment Group**: Fallback to `Service Desk`.

### 2. SLA Resolution Precedence & Versioning
SLA policies are selected dynamically via:
1. `Project + Assignment Group + Priority`
2. `Project + Priority`
3. `Assignment Group + Priority`
4. `Application + Priority`
5. `Global Priority SLA`

**SLA Versioning**: Modifying an active SLA policy creates a new version (`v2`) with `effective_from` set. Existing tickets continue using the SLA version under which they were created (`v1`), ensuring audit compliance.

**Pause Conditions**: Transitioning an incident to `Pending Customer`, `Awaiting Approval`, or `Awaiting Vendor` pauses resolution SLA calculation. Transitioning back resumes calculation, logging all pause events in `pause_history`.

### 3. AI Knowledge Assistant / Support Copilot
- **Integration Abstraction**: Implements `KnowledgeProvider` and `InternalChatCompletionProvider`.
- **Configurable API Endpoint**: Admin can configure KM Base URL, API Endpoint path, authentication tokens, and request timeout.
- **Custom Payload Templating**: Payload JSON template with variable interpolation (`{{question}}`, `{{ticket_number}}`, `{{application}}`, `{{project}}`, `{{ticket_context}}`, etc.).
- **Configurable Response JSON Path**: Supports dot/bracket path extraction (e.g. `choices[0].message.content` or `response.answer`).
- **Built-in Fallback**: Provides realistic enterprise runbooks and troubleshooting steps even before external KM credentials are entered.
- **Quick Actions on Tickets**:
  - *Troubleshoot this Incident* (generates sequential diagnostics and bash commands).
  - *Summarize Ticket* (Problem, Impact, Investigation, Action, Next Steps).
  - *Find Similar Incidents* (similarity score, root cause, resolution).
  - *Generate Work Note* (drafts bulleted internal note for engineer review before posting).
  - *Draft Customer Response* (generates courteous customer status updates).
- **Security**: Strict PII and secret redaction. Internal work notes are strictly hidden from requesters.

---

## 🚀 Quick Start & Running Locally

### 1. Virtual Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env # fill the deployment values; do not commit .env
```

### 2. Database Initialization & Demo Data Seeding
```bash
PYTHONPATH=. python backend/seed_data.py
```

### 3. Run Platform Server
```bash
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Visit the application in your browser:
**`http://localhost:8000`**

---

## 🐳 Running with Docker

```bash
docker-compose up --build -d
```
Access the web UI at `http://localhost:8000`. Health check endpoint: `http://localhost:8000/health`.

## Production deployment

The production image runs as an unprivileged user, has a read-only root filesystem, drops Linux capabilities, and writes operational logs to standard output. It must run behind a TLS-terminating load balancer or reverse proxy; the EC2 Compose setup binds to loopback by default.

### Dedicated EC2 host

Install Docker Engine plus the Compose plugin, copy this repository to the host, then run:

```bash
sudo ./install.sh
# edit /opt/nexus-itsm/.env.production with Keycloak + Consul endpoints
sudo ./install.sh
```

The first invocation creates a `0600` environment file and stops. The app uses Docker named volumes for MongoDB persistent data (`mongo_data`) and uploads.

### Kubernetes

Build and push an immutable image tag, substitute it in `deploy/kubernetes/base.yaml`, configure MongoDB and Keycloak credentials, then apply:

```bash
kubectl apply -f deploy/kubernetes/base.yaml
kubectl apply -f deploy/kubernetes/network-policy.yaml
```

Kubernetes runs multi-pod replicas (backend: 2, identity: 2, gateway: 2) backed by MongoDB. Because MongoDB provides native atomic concurrency and high availability, multi-pod scaling works out of the box with zero SQLite locking issues.

### Consul secrets

Store application secrets in Consul KV and reference them with `consul:kv/...`, for example `consul:kv/nexus-itsm/km#token`. The app fetches these only at runtime and never sends values to the UI or logs them. Grant the injected Consul ACL token read access only to the exact application paths. The token itself is the one bootstrap secret and belongs in a protected host environment or Kubernetes Secret—never in this repository.

Before release, scan the exact built image and locked dependencies in CI (for example with Trivy and pip-audit). No application can honestly promise permanent absence of vulnerabilities; these scans and timely base-image/dependency updates are the control that keeps risk visible and remediated.

After building the image, run `./scripts/security-scan.sh nexus-itsm:local-verified`. It fails on known high/critical Python dependency findings and fixed high/critical image CVEs. Docker Scout requires Docker authentication in the CI runner.

### Identity and permissions

Use a dedicated Keycloak identity service/container or pod. The included [realm role template](deploy/keycloak/realm-roles.json) defines `itsm_admin`, `itsm_user`, and `itsm_read`. The application maps these to administrator, support-user, and read-only access respectively. Create custom AD/LDAP-mapped Keycloak groups as composite roles containing one of these standard roles; this provides custom group naming without changing application code. A local user named `admin` is bootstrapped by the installation credentials and should be created in the `itsm` realm during identity-service setup.

Swagger/OpenAPI is served by FastAPI at `/docs` and `/openapi.json`. Enable debug-level application logs temporarily through the container runtime (`LOG_LEVEL=DEBUG`) while diagnosing an issue; do not leave debug logging enabled in production because it can increase sensitive operational detail in stdout.

---

## 🧪 Automated Testing

Execute the unit and end-to-end integration tests:
```bash
PYTHONPATH=. pytest tests/ -v
```

---

## 👥 Seed Personas (Role Switcher in UI Header)

| Persona Name | Role | Access Scope |
| :--- | :--- | :--- |
| **Admin User** | `administrator` | Org-wide visibility, No-code configuration, Graph editor, Simulator, SLA Versioning |
| **Sarah Johnson** | `support_member` | Payment Application Support lead, queue management, internal work notes |
| **David Wilson** | `group_manager` | Database Support manager, workload assignment, approvals |
| **Mike Brown** | `support_member` | Cloud Operations engineer, EKS platform changes |
| **John Smith** | `employee` | Requester portal, my tickets, service catalog (cannot view internal work notes) |

---

## ⚙️ Administration & No-Code Features

1. **Visual Configuration Graph (`#/admin/graph`)**: Interactive hierarchy canvas showing App $\rightarrow$ Project $\rightarrow$ Routing $\rightarrow$ Group $\rightarrow$ SLA.
2. **Routing & SLA Simulator (`#/admin/simulator`)**: Real-time evaluation sandbox showing exact matched rules and predicted SLA targets.
3. **Configuration Validation (`#/admin/validation`)**: Automated integrity scanner detecting missing assignment groups, duplicate rules, or expired policies.
4. **Configuration Change Audits (`#/admin/audits`)**: Complete audit trail recording user, timestamp, old config, new config, effective date, and business reason.
5. **Configuration Import / Export (`#/admin/import-export`)**: JSON and YAML export/import for seamless promotion between Dev, Test, and Production.


Viewed docker-compose.existing-app-addon.yml:15-30
Edited docker-compose.existing-app-addon.yml
Viewed docker-compose.existing-app-addon.yml:30-45
Edited docker-compose.existing-app-addon.yml

In Docker, container networking is isolated by design, so running alongside your existing containers is straightforward.

Here is how container ports work and the two ways to tackle them without conflicts:

---

### 1. Why Container Ports Do Not Conflict Internally
Inside Docker, **each container has its own private IP address and virtual network interface**:
- `nexus-itsm-core` listens internally on port `8000`.
- Even if another container (like `atr-gateway` or `identity-management-client`) is also listening internally on port `8000`, **they will never conflict** because they exist in separate network namespaces.
- Containers on the same Docker network talk directly via container name:
  - `http://identity-management:8001`
  - `http://consul:8500`
  - `mongodb://atr-mongo:27017`
  - `http://nexus-itsm-core:8000`

Host port conflicts only happen if two containers try to publish the **same port to the EC2 host machine** (e.g., `-p 8000:8000` when the host already has port `8000` in use).

---

### 2. How to Tackle Host Ports on Your EC2 Instance

You have two clean approaches:

#### Approach A: Route via Your Existing Nginx / ATR Gateway (Recommended — Zero Host Ports)
Because your existing `nginx` (or `atr-gateway`) container is already published to the EC2 host on ports `80` / `443`, **you do not need to expose any port on the host for `nexus-itsm-core` at all**:

1. In [`docker-compose.existing-app-addon.yml`](file:///Users/ritika/Downloads/application_repo/service_now_ai/docker-compose.existing-app-addon.yml), simply omit the `ports:` section or don't publish it to the host.
2. In your existing `nginx` configuration (e.g., `/etc/nginx/conf.d/default.conf`), add this location block:
   ```nginx
   # Forward ITSM Portal traffic internally over the Docker network
   location /itsm/ {
       proxy_pass http://nexus-itsm-core:8000/;
       proxy_http_version 1.1;
       proxy_set_header Connection "";
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```
3. Reload Nginx:
   ```bash
   docker exec -it nginx nginx -s reload
   ```
   Now, users simply visit `https://<your-ec2-ip-or-domain>/itsm/` and traffic routes internally with zero host port exposure.

---

#### Approach B: Map to an Unused Host Port (For Direct Access / Debugging)
If you want to access the ITSM portal directly on its own port on the EC2 instance, map it to any unused port (e.g. `8090`, `8888`, or `9000`):

```bash
# Example: Run on host port 8090 instead of 8000
ITSM_HOST_PORT=8090 docker compose -f docker-compose.existing-app-addon.yml up -d
```
Or to bind only to EC2 localhost (accessible via SSH tunnel or local curl without opening firewall ports):
```bash
ITSM_HOST_PORT=127.0.0.1:8090 docker compose -f docker-compose.existing-app-addon.yml up -d
```

---

### 3. Quick Checklist for Your EC2 Instance

1. **Check which host ports are currently in use on your EC2 instance**:
   ```bash
   sudo ss -tulpn | grep LISTEN
   # or
   docker ps --format "table {{.Names}}\t{{.Ports}}"
   ```

2. **Verify your existing Docker network name**:
   ```bash
   docker inspect identity-management --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}'
   ```

3. **Check container names & internal URLs**:
   If your identity management container is named differently (e.g. `im-backend` instead of `identity-management`), you can override it in your environment:
   ```bash
   IDENTITY_SERVICE_URL=http://<your-im-container-name>:<internal-port> \
   CONSUL_HTTP_ADDR=http://<your-consul-container-name>:8500 \
   EXISTING_DOCKER_NETWORK=<your-network-name> \
   docker compose -f docker-compose.existing-app-addon.yml up -d
   ```

   ---------------------install in running instance --------

Ran command: `find . -maxdepth 2 -not -path '*/.*'`
Viewed Dockerfile:1-31
Viewed Dockerfile:18-25
Edited Dockerfile
Ran command: `tar --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='*.log' \
    --exclude='uploads/*' \
    --exclude='*.db*' \
    --exclude='nexus-itsm-*.tar.gz' \
    -czvf nexus-itsm-addon.tar.gz .`
Ran command: `ls -lh nexus-itsm-addon.tar.gz`
Ran command: `mkdir -p /Users/ritika/.gemini/antigravity/brain/e53cc1ce-25f4-4981-ad93-5f65b7015623/scratch/test_extract && tar -xzvf nexus-itsm-addon.tar.gz -C /Users/ritika/.gemini/antigravity/brain/e53cc1ce-25f4-4981-ad93-5f65b7015623/scratch/test_extract > /dev/null && ls -la /Users/ritika/.gemini/antigravity/brain/e53cc1ce-25f4-4981-ad93-5f65b7015623/scratch/test_extract`
Ran command: `rm -rf /Users/ritika/.gemini/antigravity/brain/e53cc1ce-25f4-4981-ad93-5f65b7015623/scratch/test_extract`
Ran command: `ls -lh nexus-itsm-addon.tar.gz install-existing-app.sh docker-compose.existing-app-addon.yml`
Viewed install-existing-app.sh:1-104
Viewed docker-compose.existing-app-addon.yml:1-69

The deployable standalone package has been built, verified, and packaged into **[`nexus-itsm-addon.tar.gz`](file:///Users/ritika/Downloads/application_repo/service_now_ai/nexus-itsm-addon.tar.gz)** (526 KB).

It is ready to be transferred to your target AWS EC2 server where your existing containers (`identity-management`, `identity-management-client`, `nginx`, `atr-gateway-container`, `consul`, `atr-mongo`) are already running.

---

### Package Summary

- **Archive File:** [`nexus-itsm-addon.tar.gz`](file:///Users/ritika/Downloads/application_repo/service_now_ai/nexus-itsm-addon.tar.gz)
- **Turnkey Installer:** [`install-existing-app.sh`](file:///Users/ritika/Downloads/application_repo/service_now_ai/install-existing-app.sh)
- **Docker Compose Add-on:** [`docker-compose.existing-app-addon.yml`](file:///Users/ritika/Downloads/application_repo/service_now_ai/docker-compose.existing-app-addon.yml)
- **Permissions Seed Format:** Colon-free simplified permissions (`ticket_create`, `ticket_read`, `ticket_update`, `admin_all`, etc.)
- **Existing IM UI Endpoints & Collections Targeted:**
  - `groups` &rarr; `/identity-management/groups`
  - `permissions` &rarr; `/identity-management/permissions`
  - `adGroups` &rarr; `/identity-management/adGroups`
- **MongoDB Safety:** Operates strictly within isolated database `nexus_itsm` without modifying or affecting your existing MongoDB collections.

---

## Detailed Step-by-Step Installation & Run Guide

### Step 1: Copy Archive to Target AWS EC2 Server
From your local machine / terminal, use `scp` (or your preferred file transfer tool) to copy the archive to your target EC2 instance:

```bash
scp -i /path/to/your-key.pem nexus-itsm-addon.tar.gz ec2-user@<TARGET-EC2-IP>:~/
```

---

### Step 2: SSH into EC2 & Untar Package
Connect to your EC2 instance and extract the archive into a dedicated directory:

```bash
ssh -i /path/to/your-key.pem ec2-user@<TARGET-EC2-IP>

# Create folder and untar
mkdir -p ~/nexus-itsm
tar -xzvf ~/nexus-itsm-addon.tar.gz -C ~/nexus-itsm
cd ~/nexus-itsm
```

---

### Step 3: Run the Turnkey Installer

Make the installer executable and run it:

```bash
chmod +x install-existing-app.sh
./install-existing-app.sh
```

#### What the installer does automatically:
1. **Auto-detects Docker Network:** Inspects `atr-mongo`, `identity-management`, or `consul` to discover their shared Docker network name.
2. **Seeds IM & MongoDB Non-Destructively:**
   - Synchronizes required ITSM groups (`IM_SAML`, `itsm_admin`, `itsm_user`, `itsm_read`) and Active Directory group mappings (`ITSM-Admins`, `Service Desk`) into your existing IM collections (`groups`, `adGroups`, `permissions`).
   - Creates indexes in the isolated `nexus_itsm` database without touching existing database collections.
3. **Builds & Launches `nexus-itsm-core`:**
   - Starts on host port `8000` (configurable via `export ITSM_HOST_PORT=8000`).
   - Mounts persistent attachment storage (`nexus-itsm-uploads`).
4. **Validates Healthcheck:** Polls `http://localhost:8000/health` until active.

> [!TIP]
> If your existing containers use a custom network name (e.g. `atr-network`) or port 8000 is occupied, you can override variables when running:
> ```bash
> EXISTING_DOCKER_NETWORK=atr-network ITSM_HOST_PORT=8085 ./install-existing-app.sh
> ```

---

### Step 4: Verification & Testing

#### 4.1 Check Container Status
```bash
docker ps --filter "name=nexus-itsm-core"
```
You should see:
```text
CONTAINER ID   IMAGE                    COMMAND                  STATUS                   PORTS
xxxxxxxxxxxx   nexus-itsm-core:latest   "uvicorn backend.app…"   Up (healthy)             0.0.0.0:8000->8000/tcp
```

#### 4.2 Test Endpoint Health
```bash
curl -i http://localhost:8000/health
```
Expected response:
```json
{"status":"healthy","database":"connected","consul":"connected"}
```

#### 4.3 Verify MongoDB Isolation in `atr-mongo`
Log into your existing MongoDB container to confirm your existing data is untouched and `nexus_itsm` is properly seeded:
```bash
docker exec -it atr-mongo mongosh -u atr -p --authenticationDatabase admin
```
Inside Mongo Shell:
```javascript
// Check existing databases remain intact
show dbs

// Switch to ITSM database
use nexus_itsm
show collections
// Shows: tickets, audit_logs, change_requests, incidents, oncall_schedules, etc.

// Switch to your IM database and verify simplified permissions were added
use identity_db  // or your IM database name
db.permissions.find({ code: "ticket_create" })
db.groups.find({ name: "itsm_admin" })
db.adGroups.find({ name: "ITSM-Admins" })
```

---

### Step 5: Perimeter Nginx / ATR Gateway Configuration

To route web traffic through your existing perimeter `nginx` or `atr-gateway-container` so users access ITSM at `https://<domain>/itsm/`:

#### Option A: Existing Nginx Container
Add this location block to your existing Nginx configuration (`/etc/nginx/conf.d/default.conf` or equivalent):

```nginx
location /itsm/ {
    proxy_pass http://nexus-itsm-core:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/ {
    proxy_pass http://nexus-itsm-core:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
Reload Nginx:
```bash
docker exec -it nginx nginx -s reload
```

#### Option B: ATR Gateway Container
If routing via `atr-gateway-container`, register the route for service name `nexus-itsm-core` on port `8000` via Consul or your Spring Cloud Gateway route definition:
- Route Path: `/itsm/**` &rarr; `http://nexus-itsm-core:8000/`

---

### Step 6: Testing from Browser & IM UI

1. **Check Existing IM UI:**
   - Navigate to `https://<base-url>/identity-management/groups`: Verify `IM_SAML`, `itsm_admin`, and `itsm_user` are present.
   - Navigate to `https://<base-url>/identity-management/permissions`: Verify `ticket_create`, `ticket_read`, `ticket_update`, `admin_all` are present.
   - Navigate to `https://<base-url>/identity-management/adGroups`: Verify `ITSM-Admins` and `Service Desk` mappings exist.
2. **Access ITSM Web App:**
   - Open `https://<base-url>/itsm/` (or direct host port `http://<EC2-IP>:8000`).
   - Notice the sidebar is clean (redundant Identity/Roles/SSO menus removed).
   - Test creating a ticket to confirm tickets persist to `nexus_itsm.tickets` in `atr-mongo`.

---

### Useful Management Commands

- **View Live Logs:**
  ```bash
  docker compose -f docker-compose.existing-app-addon.yml logs -f nexus-itsm-core
  ```
- **Restart Container:**
  ```bash
  docker compose -f docker-compose.existing-app-addon.yml restart nexus-itsm-core
  ```
- **Stop Add-on:**
  ```bash
  docker compose -f docker-compose.existing-app-addon.yml down
  ```