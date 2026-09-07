"""Tests for Existing Application Integration:
1. Consul Spring keys resolution (MongoDB host/user/pass/auth_db, admin.password, dns).
2. Subpath /itsm hosting and routing (API, static files, index, and SSO redirect).
3. DL-to-Group-to-Permission mapping architecture in Identity Management.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.mongo_dal import resolve_mongo_config, resolve_platform_dns
from identity_service.main import bootstrap_default_groups, bootstrap_admin_user, extract_and_map_claims
from backend.database import SessionLocal
from backend.models import CustomGroup, ADGroupMapping, User

client = TestClient(app)


def test_consul_spring_mongo_keys_resolution():
    """Verify that resolve_mongo_config retrieves the exact Spring Cloud Consul keys."""
    mock_responses = {
        "http://consul:8500/v1/kv/configuration/aaam-atr-v3-gateway/spring.data.mongodb.password": "SecretMongoPass!123",
        "http://consul:8500/v1/kv/configuration/aaam-atr-v3-gateway/spring.data.mongodb.host": "atr-mongo:27017",
        "http://consul:8500/v1/kv/configuration/aaam-atr-v3-gateway/spring.data.mongodb.username": "atr",
        "http://consul:8500/v1/kv/configuration/aaam-atr-v3-gateway/spring.data.mongodb.authentication_database": "admin",
    }

    def mock_get(url, params=None, headers=None, timeout=None):
        mock_resp = MagicMock()
        val = mock_responses.get(url)
        if val is not None:
            mock_resp.status_code = 200
            mock_resp.text = val
        else:
            mock_resp.status_code = 404
            mock_resp.text = ""
        return mock_resp

    with patch("os.getenv") as mock_env, patch("requests.get", side_effect=mock_get):
        def fake_env(k, d=""):
            if k == "CONSUL_HTTP_ADDR":
                return "http://consul:8500"
            if k == "MONGO_DATABASE":
                return "nexus_itsm"
            if k == "MONGO_URL":
                return ""
            return d
        mock_env.side_effect = fake_env

        mongo_url, db_name = resolve_mongo_config()
        assert "mongodb://atr:SecretMongoPass!123@atr-mongo:27017/nexus_itsm?authSource=admin" == mongo_url
        assert db_name == "nexus_itsm"


def test_consul_spring_admin_password_resolution():
    """Verify that bootstrap_admin_user reads admin.password from Consul key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "CustomAdminPass2026!"
    mock_resp.json.side_effect = Exception("Not JSON")

    with patch("os.getenv") as mock_env, patch("requests.get", return_value=mock_resp):
        def fake_env(k, d=""):
            if k == "CONSUL_HTTP_ADDR":
                return "http://consul:8500"
            if k == "ITSM_BOOTSTRAP_ADMIN_USERNAME":
                return "admin"
            if k in ["ITSM_BOOTSTRAP_ADMIN_PASSWORD", "ADMIN_PASSWORD"]:
                return ""
            return d
        mock_env.side_effect = fake_env

        bootstrap_admin_user()

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").first()
            assert admin is not None
            assert admin.role == "itsm_admin"
        finally:
            db.close()


def test_consul_dns_resolution():
    """Verify that resolve_platform_dns retrieves DNS from Consul."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "https://portal.enterprise.com"

    with patch("os.getenv") as mock_env, patch("requests.get", return_value=mock_resp):
        def fake_env(k, d=""):
            if k == "CONSUL_HTTP_ADDR":
                return "http://consul:8500"
            return ""
        mock_env.side_effect = fake_env

        dns = resolve_platform_dns()
        assert dns == "https://portal.enterprise.com"


def test_itsm_subpath_routing():
    """Verify that /itsm subpath routes seamlessly resolve index, static, api, and sso."""
    # 1. /itsm and /itsm/
    r1 = client.get("/itsm")
    assert r1.status_code == 200
    assert "text/html" in r1.headers.get("content-type", "")

    r2 = client.get("/itsm/")
    assert r2.status_code == 200
    assert "text/html" in r2.headers.get("content-type", "")

    # 2. /itsm/static/css/style.css
    r3 = client.get("/itsm/static/css/style.css")
    assert r3.status_code == 200

    # 3. /itsm/api/applications
    r4 = client.get("/itsm/api/applications")
    assert r4.status_code == 200
    assert isinstance(r4.json(), list)

    # 4. /itsm/sso-redirect.html and /itsm/sso
    r5 = client.get("/itsm/sso-redirect.html")
    assert r5.status_code == 200
    assert "text/html" in r5.headers.get("content-type", "")

    r6 = client.get("/itsm/sso")
    assert r6.status_code == 200


def test_dl_to_group_to_permission_architecture():
    """
    Verify the IM authorization architecture:
    1. Roles are groups having permissions attached (itsm_admin, itsm_user, itsm_read, IM_SAML).
    2. AD groups are the DLs added in IM to which groups are attached.
    3. User in AD group gets the attached group and its permissions.
    4. End-user not in IM gets IM_SAML group and end-user permissions.
    """
    bootstrap_default_groups()

    db = SessionLocal()
    try:
        # Check groups and attached permissions
        im_saml = db.query(CustomGroup).filter(CustomGroup.name == "IM_SAML").first()
        assert im_saml is not None
        perms_saml = json.loads(im_saml.permissions)
        assert "ticket_create" in perms_saml
        assert "tickets:create" in perms_saml
        assert "ticket_read_own" in perms_saml
        assert "ticket_update" in perms_saml

        itsm_admin_grp = db.query(CustomGroup).filter(CustomGroup.name == "itsm_admin").first()
        assert itsm_admin_grp is not None
        perms_admin = json.loads(itsm_admin_grp.permissions)
        assert "admin_all" in perms_admin
        assert "admin:all" in perms_admin

        # Verify admin user has itsm_admin attached
        admin_u = db.query(User).filter(User.username == "admin").first()
        assert admin_u is not None
        admin_groups = [cg.custom_group.name for cg in admin_u.custom_groups if cg.custom_group]
        assert "itsm_admin" in admin_groups

        # Add custom AD group / DL mapping post-installation
        custom_dl = ADGroupMapping(
            ad_group_name="ITSM-Admins",
            target_role="itsm_admin",
            custom_group_id=itsm_admin_grp.id,
            description="Dynamically configured post-install AD Group",
            active=True
        )
        db.add(custom_dl)
        db.commit()

        # Test SSO login with DL ITSM-Admins
        claims_admin = {
            "email": "lead.admin@corp.local",
            "name": "Lead Admin",
            "memberOf": ["CN=ITSM-Admins,OU=Groups,DC=corp"]
        }
        res_admin = extract_and_map_claims(claims_admin, None, db)
        assert res_admin["user"]["role"] == "itsm_admin"
        # Admin gets admin permissions
        assert "ticket_create" in res_admin["user"]["permissions"]
        assert "admin_all" in res_admin["user"]["permissions"]

        # Test SSO login for end-user (no DL in IM) -> gets IM_SAML
        claims_enduser = {
            "email": "employee@corp.local",
            "name": "Standard Employee",
            "memberOf": ["CN=All-Employees,OU=DistLists,DC=corp"]
        }
        res_enduser = extract_and_map_claims(claims_enduser, None, db)
        assert res_enduser["user"]["is_end_user"] is True
        assert "IM_SAML" in res_enduser["user"]["custom_groups"]
        assert "ticket_create" in res_enduser["user"]["permissions"]
        assert "tickets:create" in res_enduser["user"]["permissions"]
        assert "ticket_read_own" in res_enduser["user"]["permissions"]
        assert "admin_all" not in res_enduser["user"]["permissions"]
        assert "admin:all" not in res_enduser["user"]["permissions"]
    finally:
        db.close()
