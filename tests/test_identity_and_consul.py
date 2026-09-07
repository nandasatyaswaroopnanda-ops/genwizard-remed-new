import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import User, CustomGroup, ADGroupMapping, SSOProviderConfig

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_admin_bootstrap_and_login(client):
    """Verify administrator 'admin' is bootstrapped with 'itsm_admin' role and can authenticate."""
    login_resp = client.post("/api/id/auth/login", json={
        "username": "admin",
        "password": "Admin@Secure2026!"
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token_data = login_resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    assert token_data["user"]["username"] == "admin"
    assert token_data["user"]["role"] == "itsm_admin"
    # itsm_admin must have admin:all permission
    assert "admin:all" in token_data["user"]["permissions"]

    # Verify /auth/me with Bearer token
    token = token_data["access_token"]
    me_resp = client.get("/api/id/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["username"] == "admin"
    assert me_data["role"] == "itsm_admin"


def test_local_user_lifecycle(client):
    """Test creating a new local user with standard role (itsm_user), logging in, and verifying claims."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    test_user = f"sarah_fulfiller_{uid}"
    test_email = f"sarah_{uid}@company.local"

    # 1. Login as admin to get auth token
    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    # 2. Create local user
    user_payload = {
        "username": test_user,
        "password": "SarahPassword123!",
        "full_name": "Sarah Fulfiller",
        "email": test_email,
        "role": "itsm_user",
        "employee_id": f"EMP-SARAH-{uid}"
    }
    create_resp = client.post("/api/id/users", json=user_payload, headers={"Authorization": f"Bearer {token}"})
    assert create_resp.status_code in (200, 201), f"User create failed: {create_resp.text}"
    user_data = create_resp.json()
    assert user_data["username"] == test_user
    assert user_data["role"] == "itsm_user"

    # 3. Authenticate as new local user
    user_login = client.post("/api/id/auth/login", json={
        "username": test_user,
        "password": "SarahPassword123!"
    })
    assert user_login.status_code == 200
    user_token = user_login.json()["access_token"]
    assert "tickets:update" in user_login.json()["user"]["permissions"]
    # itsm_user should not have admin:all
    assert "admin:all" not in user_login.json()["user"]["permissions"]


def test_custom_group_and_permissions(client):
    """Test creating custom groups with granular permissions and assigning users."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    grp_name = f"Security Analysts {uid}"

    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    # 1. Create a custom group
    group_payload = {
        "name": grp_name,
        "description": "L2 Security Operations Incident Handlers",
        "permissions": ["tickets:read", "tickets:update", "system:logs"]
    }
    grp_resp = client.post("/api/id/groups", json=group_payload, headers={"Authorization": f"Bearer {token}"})
    assert grp_resp.status_code in (200, 201)
    grp_data = grp_resp.json()
    assert grp_data["name"] == grp_name
    assert "system:logs" in grp_data["permissions"]
    grp_id = grp_data["id"]

    # 2. List all custom groups
    list_grp = client.get("/api/id/groups", headers={"Authorization": f"Bearer {token}"})
    assert list_grp.status_code == 200
    groups = list_grp.json()
    assert any(g["id"] == grp_id for g in groups)


def test_active_directory_group_mapping_and_claim_resolution(client):
    """Test Active Directory group mapping creation and claim resolution."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    ad_name = f"Cloud-Admins-{uid}"
    ad_dn = f"CN={ad_name},OU=Security,DC=company,DC=com"

    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    # 1. Create AD group mapping
    mapping_payload = {
        "ad_group_name": ad_name,
        "target_role": "itsm_admin",
        "priority": 10,
        "description": "Cloud Admins mapped to ITSM Admin"
    }
    map_resp = client.post("/api/id/ad-mappings", json=mapping_payload, headers={"Authorization": f"Bearer {token}"})
    assert map_resp.status_code in (200, 201)

    # 2. Test claim resolution
    resolve_payload = {
        "ad_groups": [
            ad_dn,
            "CN=General-Staff,OU=Users,DC=company,DC=com"
        ]
    }
    resolve_resp = client.post("/api/id/ad-resolve", json=resolve_payload, headers={"Authorization": f"Bearer {token}"})
    assert resolve_resp.status_code == 200
    res_data = resolve_resp.json()
    assert res_data["effective_role"] == "itsm_admin"
    assert "admin:all" in res_data["permissions"]
    assert len(res_data["matched_ad_groups"]) >= 1


def test_saml_sp_metadata_xml_generation(client):
    """Test SAML 2.0 SP Metadata XML download endpoint for B2B/B2C ESO integration."""
    resp = client.get("/api/id/sso/metadata.xml")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers.get("content-type", "")
    xml_content = resp.text
    assert "<md:EntityDescriptor" in xml_content
    assert "<md:SPSSODescriptor" in xml_content
    assert "AssertionConsumerService" in xml_content


def test_dynamic_log_level_switching(client):
    """Test changing logger level dynamically without restart on backend and identity service."""
    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    # 1. Backend log level switch to DEBUG
    resp1 = client.post(
        "/api/admin/system/log-level",
        json={"level": "DEBUG"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp1.status_code == 200
    assert resp1.json()["log_level"] == "DEBUG"

    # Query GET backend log level
    get_resp = client.get("/api/admin/system/log-level", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.status_code == 200
    assert get_resp.json()["log_level"] == "DEBUG"

    # Revert backend to INFO
    client.post("/api/admin/system/log-level", json={"level": "INFO"}, headers={"Authorization": f"Bearer {token}"})

    # 2. Identity Service log level switch to DEBUG
    resp2 = client.post(
        "/api/id/system/log-level",
        json={"level": "DEBUG"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["log_level"] == "DEBUG"

    # Revert identity service to INFO
    client.post("/api/id/system/log-level", json={"level": "INFO"}, headers={"Authorization": f"Bearer {token}"})


def test_ticket_filtering_parameters(client):
    """Test multi-column filtering parameters on GET /api/incidents."""
    # Filter by Priority
    p1_resp = client.get("/api/incidents?priority=P1", headers={"X-User-ID": "1"})
    assert p1_resp.status_code == 200
    for inc in p1_resp.json():
        assert inc["priority"] == "P1"

    # Filter by Status
    new_resp = client.get("/api/incidents?status=New", headers={"X-User-ID": "1"})
    assert new_resp.status_code == 200
    for inc in new_resp.json():
        assert inc["status"] == "New"

    # Filter by Application ID
    app_resp = client.get("/api/incidents?application_id=1", headers={"X-User-ID": "1"})
    assert app_resp.status_code == 200
    for inc in app_resp.json():
        assert inc["application_id"] == 1


def test_km_and_consul_status_endpoints(client):
    """Test KM configuration retrieval and Consul status endpoint."""
    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    # 1. Get KM Config
    km_get = client.get("/api/admin/configuration/km", headers={"Authorization": f"Bearer {token}"})
    assert km_get.status_code == 200
    km_data = km_get.json()
    assert "km_base_url" in km_data
    assert "km_index" in km_data

    # 2. Update KM Config
    km_update = client.put(
        "/api/admin/configuration/km",
        json={
            "km_base_url": "https://knowledge.company.internal",
            "api_endpoint": "/api/v2/chat",
            "username": "itsm-km-user",
            "password": "KMSecretPassword123!",
            "km_index": "enterprise-support-kb",
            "sync_to_consul": False
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert km_update.status_code == 200
    updated_km = km_update.json()
    assert updated_km["km_base_url"] == "https://knowledge.company.internal"
    assert updated_km["km_index"] == "enterprise-support-kb"
    # Verify username and password are both hidden/masked in API response
    assert updated_km.get("username") == "••••••••"
    assert updated_km.get("password") == "••••••••"

    # 3. Subsequent GET also returns KM URL visible and credentials hidden
    km_get_again = client.get("/api/admin/configuration/km", headers={"Authorization": f"Bearer {token}"})
    assert km_get_again.status_code == 200
    km_data_again = km_get_again.json()
    assert km_data_again["km_base_url"] == "https://knowledge.company.internal"
    assert km_data_again["username"] == "••••••••"
    assert km_data_again["password"] == "••••••••"

    # 4. Updating other properties with masked values does not overwrite real secrets
    km_update_masked = client.put(
        "/api/admin/configuration/km",
        json={
            "km_base_url": "https://knowledge.company.internal",
            "api_endpoint": "/api/v2/chat",
            "username": "••••••••",
            "password": "••••••••",
            "km_index": "enterprise-support-kb-v2",
            "sync_to_consul": False
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert km_update_masked.status_code == 200
    assert km_update_masked.json()["km_index"] == "enterprise-support-kb-v2"

    # 5. Consul Status Check (gracefully reports configured or not)
    consul_resp = client.get("/api/admin/configuration/consul-status")
    assert consul_resp.status_code == 200
    assert "configured" in consul_resp.json()


def test_eso_registration_with_existing_app_id(client):
    """Test seamless registration of SSO Provider using an existing corporate ESO / Azure App ID."""
    import uuid
    app_id = f"eso-app-nexus-{uuid.uuid4().hex[:6]}"
    
    payload = {
        "eso_app_id": app_id,
        "name": f"Corporate ESO Provider ({app_id})",
        "provider_type": "saml",
        "b2b_or_b2c": "b2b",
        "idp_sso_url": "https://eso.corporate.internal/saml/sso",
        "default_role": "itsm_user",
        "role_mapping_rules": {
            "ITSM-Platform-Admins": "itsm_admin",
            "ITSM-Fulfillers": "itsm_user"
        },
        "assignment_group_mapping_rules": {
            "Tier1-Support": ["Service Desk"]
        }
    }
    
    resp = client.post("/api/id/sso/register-eso", json=payload)
    assert resp.status_code == 200, f"ESO registration failed: {resp.text}"
    data = resp.json()
    assert data["success"] is True
    assert data["provider"]["eso_app_id"] == app_id
    assert "service_provider_endpoints" in data
    assert app_id in data["service_provider_endpoints"]["acs_url"]
    assert "sso_redirect_url" in data["service_provider_endpoints"]

    # Verify provider appears in public SSO providers list
    providers_resp = client.get("/api/id/sso/providers")
    assert providers_resp.status_code == 200
    prov_list = providers_resp.json()
    assert any(p["eso_app_id"] == app_id for p in prov_list)


def test_sso_claim_mapping_sandbox(client):
    """Test dry-run simulation of Keycloak / Azure AD claims mapping without modifying DB."""
    payload = {
        "claims": {
            "preferred_username": "jdoe_sso",
            "email": "jdoe@company.internal",
            "name": "John Doe",
            "realm_access": {
                "roles": ["itsm_admin", "Service Desk", "Cloud Operations"]
            }
        },
        "role_mapping_rules": {
            "itsm_admin": "itsm_admin"
        },
        "assignment_group_mapping_rules": {
            "Service Desk": ["Service Desk"]
        }
    }
    
    resp = client.post("/api/id/sso/test-claim-mapping", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["success"] is True
    preview = res["preview"]
    assert preview["extracted_email"] == "jdoe@company.internal"
    assert preview["extracted_name"] == "John Doe"
    assert preview["effective_role"] == "itsm_admin"
    assert "admin:all" in preview["permissions"]


def test_sso_login_jit_provisioning_and_assignment_groups(client):
    """Test SSO login assertion handling, JIT user provisioning, role resolution, and app group assignment."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    test_email = f"azure.sso.{uid}@enterprise.corp"

    # Ensure "Service Desk" assignment group exists
    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    # Register AD mapping in IM (simulates post-installation admin configuration)
    client.post("/api/id/ad-mappings", headers={"Authorization": f"Bearer {token}"}, json={
        "ad_group_name": "ITSM-Admins",
        "target_role": "itsm_admin",
        "description": "ITSM Admins"
    })
    
    # Process SSO Login with Azure AD style claims
    sso_login_payload = {
        "claims": {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": test_email,
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name": "Azure SSO Engineer",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups": [
                "CN=ITSM-Admins,OU=Groups,DC=corp",
                "Service Desk"
            ]
        },
        "redirect_uri": "/#dashboard"
    }

    login_resp = client.post("/api/id/sso/process-login", json=sso_login_payload)
    assert login_resp.status_code == 200, f"SSO process-login failed: {login_resp.text}"
    auth_data = login_resp.json()
    assert auth_data["success"] is True
    assert "access_token" in auth_data
    user = auth_data["user"]
    assert user["email"] == test_email
    assert user["role"] == "itsm_admin"

    # Check that the JIT token works for authenticated endpoints
    sso_token = auth_data["access_token"]
    me_resp = client.get("/api/id/auth/me", headers={"Authorization": f"Bearer {sso_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == test_email
    assert me_resp.json()["role"] == "itsm_admin"


def test_sso_redirect_static_route(client):
    """Test that the animated SSO redirect portal is served correctly."""
    resp = client.get("/sso-redirect.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Opening Nexus ITSM..." in resp.text
    assert "Enterprise IdP" in resp.text


def test_sso_end_user_not_in_im_gets_im_saml_default_role_and_redirect(client):
    """
    Verify that when an SSO user's groups are NOT added in IM:
    1. They are automatically assigned the default IM_SAML group
    2. Assigned role defaults to itsm_read with is_end_user = True
    3. Redirect URL directs to /#my-tickets
    4. Permissions include tickets:create, tickets:read_own, tickets:update, applications:read, projects:read
    5. They can query public applications and projects
    """
    import uuid
    uid = uuid.uuid4().hex[:6]
    test_email = f"enduser.{uid}@enterprise.corp"

    sso_payload = {
        "claims": {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": test_email,
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name": "Corporate Employee",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups": [
                "CN=General-Employees-DL,OU=DistributionLists,DC=corp"
            ]
        }
    }

    login_resp = client.post("/api/id/sso/process-login", json=sso_payload)
    assert login_resp.status_code == 200, f"SSO process-login failed: {login_resp.text}"
    data = login_resp.json()
    assert data["success"] is True
    assert data["redirect_url"] == "/#my-tickets"

    user = data["user"]
    assert user["email"] == test_email
    assert user["role"] == "itsm_read"
    assert user["is_end_user"] is True
    assert "IM_SAML" in user["custom_groups"]

    perms = user["permissions"]
    assert "tickets:create" in perms
    assert "tickets:read_own" in perms
    assert "tickets:update" in perms
    assert "applications:read" in perms
    assert "projects:read" in perms
    # Must NOT have broad support or admin permissions
    assert "admin:all" not in perms
    assert "tickets:delete" not in perms

    # End users must be able to query public applications and projects
    apps_resp = client.get("/api/applications")
    assert apps_resp.status_code == 200
    assert isinstance(apps_resp.json(), list)

    proj_resp = client.get("/api/projects")
    assert proj_resp.status_code == 200
    assert isinstance(proj_resp.json(), list)


def test_sso_im_ad_group_mapping_assigns_role_and_support_access(client):
    """
    Verify that roles in SSO mapping map to AD groups added in IM:
    1. Role is assigned based on the role attached to that AD group in IM
    2. Support member gets itsm_user, is_end_user = False, redirecting to /#dashboard
    """
    import uuid
    uid = uuid.uuid4().hex[:6]
    ad_group_name = f"CN=Cloud-Infrastructure-Ops-{uid},OU=Groups,DC=corp"
    test_email = f"support.engineer.{uid}@enterprise.corp"

    # 1. Admin logs in to IM and registers the AD group with target role 'itsm_user'
    admin_login = client.post("/api/id/auth/login", json={"username": "admin", "password": "Admin@Secure2026!"})
    token = admin_login.json()["access_token"]

    mapping_resp = client.post(
        "/api/id/ad-mappings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "ad_group_name": ad_group_name,
            "target_role": "itsm_user",
            "description": "Cloud Ops Tier-2 Support Engineers"
        }
    )
    assert mapping_resp.status_code in (200, 201), f"Creating AD mapping failed: {mapping_resp.text}"

    # 2. Support user logs in via SSO with this AD group
    sso_payload = {
        "claims": {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": test_email,
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name": "Cloud Ops Engineer",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups": [
                ad_group_name
            ]
        }
    }

    login_resp = client.post("/api/id/sso/process-login", json=sso_payload)
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert data["success"] is True
    assert data["redirect_url"] == "/#dashboard"

    user = data["user"]
    assert user["role"] == "itsm_user"
    assert user["is_end_user"] is False
    assert "IM_SAML" in user["custom_groups"]
    assert "tickets:update" in user["permissions"]


def test_end_user_ticket_lifecycle_and_worknotes(client):
    """
    Verify that an end user with IM_SAML can:
    1. Create tickets
    2. View their own tickets
    3. Update work notes and customer comments on their own ticket
    4. Is rejected (403) when attempting to post work notes to tickets created by other callers
    """
    import uuid
    uid = uuid.uuid4().hex[:6]
    enduser_email = f"caller.{uid}@enterprise.corp"

    # 1. End user SSO login
    sso_resp = client.post("/api/id/sso/process-login", json={
        "claims": {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": enduser_email,
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name": "Ticket Caller User",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups": ["CN=General-Users"]
        }
    })
    assert sso_resp.status_code == 200
    caller_id = sso_resp.json()["user"]["id"]

    # 2. End user queries available applications and projects to select for ticket creation
    apps_resp = client.get("/api/applications")
    assert apps_resp.status_code == 200
    apps = apps_resp.json()
    assert len(apps) > 0
    app_id = apps[0]["id"]

    projs_resp = client.get("/api/projects")
    assert projs_resp.status_code == 200
    projs = projs_resp.json()
    assert len(projs) > 0
    proj_id = projs[0]["id"]

    # 3. End user creates ticket
    create_resp = client.post("/api/incidents", headers={"X-User-ID": str(caller_id)}, json={
        "short_description": f"VPN connectivity issue {uid}",
        "description": "Unable to connect to internal portal via VPN client",
        "impact": "Low",
        "urgency": "Low",
        "application_id": app_id,
        "project_id": proj_id
    })
    assert create_resp.status_code in (200, 201), f"Create incident failed: {create_resp.text}"
    ticket = create_resp.json()
    ticket_id = ticket["id"]
    ticket_number = ticket["number"]
    assert ticket["caller_id"] == caller_id

    # 3. End user adds customer comment to their ticket
    comment_resp = client.post(
        f"/api/incidents/{ticket_id}/comments",
        headers={"X-User-ID": str(caller_id)},
        json={"comment": "I rebooted my machine but still experiencing timeout."}
    )
    assert comment_resp.status_code == 200

    # 4. End user adds worknote to their own ticket (explicitly permitted for caller)
    worknote_resp = client.post(
        f"/api/incidents/{ticket_id}/work-notes",
        headers={"X-User-ID": str(caller_id)},
        json={"note": "Caller diagnostic: ping gateway failed with 100% packet loss."}
    )
    assert worknote_resp.status_code == 200, f"Posting worknote failed: {worknote_resp.text}"

    # Verify comments exist on the ticket for caller
    view_resp = client.get(f"/api/incidents/{ticket_number}", headers={"X-User-ID": str(caller_id)})
    assert view_resp.status_code == 200
    view_data = view_resp.json()
    assert len(view_data["comments"]) >= 1

    # Verify work note was successfully recorded and visible to support/administrator
    admin_view = client.get(f"/api/incidents/{ticket_number}", headers={"X-User-ID": "1"})
    assert admin_view.status_code == 200
    admin_data = admin_view.json()
    assert any("ping gateway failed" in wn["note"] for wn in admin_data["work_notes"])

    # 5. Unauthorized 3rd-party user attempts to post work notes to this ticket
    other_uid = uuid.uuid4().hex[:6]
    other_sso = client.post("/api/id/sso/process-login", json={
        "claims": {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": f"other.{other_uid}@enterprise.corp",
            "http://schemas.microsoft.com/ws/2005/05/identity/claims/name": "Other Unrelated User",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups": ["CN=General-Users"]
        }
    })
    other_id = other_sso.json()["user"]["id"]

    unauth_resp = client.post(
        f"/api/incidents/{ticket_id}/work-notes",
        headers={"X-User-ID": str(other_id)},
        json={"note": "Malicious or unauthorized update attempt"}
    )
    assert unauth_resp.status_code == 403, f"Expected 403 Forbidden, got {unauth_resp.status_code}: {unauth_resp.text}"


