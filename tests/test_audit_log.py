from unittest.mock import AsyncMock, patch

import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.gateway.audit import record_audit_event
from apps.gateway.db.models import AuditLog
from apps.gateway.main import app

client = TestClient(app)


# --- record_audit_event itself: verified by writing directly to the test DB via the
# db_session fixture, sidestepping fire_and_forget's timing entirely (a background
# task's completion isn't observable from a synchronous TestClient call - see the
# endpoint-level tests below, which verify wiring via mocking instead). ---


@pytest.mark.asyncio
async def test_record_audit_event_persists_a_queryable_row(db_session):
    await record_audit_event(
        actor="someone@example.com",
        action="login.success",
        resource_type="user",
        resource_id="user-123",
        result="success",
        ip_address="203.0.113.5",
        user_agent="pytest",
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.actor == "someone@example.com"))
    row = result.scalar_one()
    assert row.action == "login.success"
    assert row.resource_type == "user"
    assert row.resource_id == "user-123"
    assert row.result == "success"
    assert row.ip_address == "203.0.113.5"


@pytest.mark.asyncio
async def test_record_audit_event_never_raises_on_bad_input():
    await record_audit_event(actor="x", action="y", resource_type="z", organization_id="not-a-uuid")


# --- GET /audit-log: rows are inserted directly via the db_session fixture (not
# through fire_and_forget), and read back through a real registered user - the
# endpoint is always scoped to the caller's own organization now, so setup writes
# use that same org_id rather than arbitrary/absent ones. ---


@pytest.mark.asyncio
async def test_audit_log_endpoint_filters_by_actor_action_result(db_session):
    org_id, headers = register_and_login(client)
    await record_audit_event(
        actor="alice@example.com", action="login.success", resource_type="user", result="success", organization_id=org_id
    )
    await record_audit_event(
        actor="alice@example.com", action="login.failure", resource_type="user", result="failure", organization_id=org_id
    )
    await record_audit_event(
        actor="bob@example.com", action="login.failure", resource_type="user", result="failure", organization_id=org_id
    )

    by_actor = client.get("/audit-log", params={"actor": "alice@example.com"}, headers=headers).json()
    assert len(by_actor) == 2

    by_action = client.get("/audit-log", params={"action": "login.failure"}, headers=headers).json()
    assert {log["actor"] for log in by_action} == {"alice@example.com", "bob@example.com"}

    by_result = client.get("/audit-log", params={"result": "failure", "actor": "alice@example.com"}, headers=headers).json()
    assert len(by_result) == 1
    assert by_result[0]["action"] == "login.failure"


@pytest.mark.asyncio
async def test_audit_log_endpoint_filters_by_organization_and_resource_type(db_session):
    org_id, headers = register_and_login(client)
    other_org_id, _ = register_and_login(client)
    await record_audit_event(actor="anonymous", action="key.created", resource_type="api_key", resource_id="k1", organization_id=org_id)
    await record_audit_event(
        actor="anonymous", action="key.created", resource_type="api_key", resource_id="k2", organization_id=other_org_id
    )
    await record_audit_event(actor="anonymous", action="routing_rule.created", resource_type="routing_rule", organization_id=org_id)

    # Scoped to the caller's own organization regardless of what's asked for - the
    # other organization's audit rows are never visible through this endpoint.
    # (register_and_login's own POST /auth/login also fires a "login.success" row
    # scoped to org_id via fire_and_forget - not awaited here, so its presence isn't
    # asserted on; only the two rows written directly above are guaranteed to have
    # landed.)
    by_org = client.get("/audit-log", params={"organization_id": org_id}, headers=headers).json()
    assert {log["resource_id"] for log in by_org if log["resource_type"] == "api_key"} == {"k1"}
    assert {log["resource_type"] for log in by_org} <= {"api_key", "routing_rule", "user"}
    assert len(by_org) >= 2

    cross_org_attempt = client.get("/audit-log", params={"organization_id": other_org_id}, headers=headers)
    assert cross_org_attempt.status_code == 403

    by_resource_type = client.get("/audit-log", params={"resource_type": "api_key"}, headers=headers).json()
    assert {log["resource_id"] for log in by_resource_type} == {"k1"}


def test_audit_log_has_no_mutation_endpoints():
    # Immutability by omission: no PATCH/PUT/DELETE routes exist on this router.
    methods = {route.methods for route in app.routes if getattr(route, "path", None) == "/audit-log"}
    allowed = {m for group in methods for m in group}
    assert "DELETE" not in allowed
    assert "PUT" not in allowed
    assert "PATCH" not in allowed


# --- Endpoint wiring: each mutating endpoint is verified to call record_audit_event
# (via fire_and_forget) with the right actor/action/resource - mocked out, matching
# how tests/test_webhooks.py verifies dispatch_webhook_event wiring, so these don't
# depend on a background task's completion timing either. ---


def test_login_failure_and_success_call_record_audit_event():
    client.post("/auth/register", json={"email": "audit-wiring@example.com", "password": "correct-password"})

    with patch("apps.gateway.api.auth.record_audit_event", new_callable=AsyncMock) as mock_record:
        resp = client.post("/auth/login", json={"email": "audit-wiring@example.com", "password": "wrong-password"})
    assert resp.status_code == 401
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["action"] == "login.failure"
    assert mock_record.call_args.kwargs["result"] == "failure"
    assert mock_record.call_args.kwargs["details"] == {"reason": "invalid_credentials"}

    with patch("apps.gateway.api.auth.record_audit_event", new_callable=AsyncMock) as mock_record:
        resp = client.post("/auth/login", json={"email": "audit-wiring@example.com", "password": "correct-password"})
    assert resp.status_code == 200
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["action"] == "login.success"
    assert mock_record.call_args.kwargs["result"] == "success"


def test_unknown_email_login_failure_has_no_resource_id():
    with patch("apps.gateway.api.auth.record_audit_event", new_callable=AsyncMock) as mock_record:
        resp = client.post("/auth/login", json={"email": "no-such-user@example.com", "password": "whatever"})
    assert resp.status_code == 401
    assert mock_record.call_args.kwargs["resource_id"] is None


def test_key_creation_and_revocation_call_record_audit_event():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Audit Wiring Project", "organization_id": org_id}, headers=headers).json()

    with patch("apps.gateway.api.keys.record_audit_event", new_callable=AsyncMock) as mock_record:
        key = client.post("/keys", json={"project_id": project["id"], "name": "audited key"}, headers=headers).json()
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["action"] == "key.created"
    assert mock_record.call_args.kwargs["actor"].startswith("user:")
    assert mock_record.call_args.kwargs["organization_id"] == org_id

    with patch("apps.gateway.api.keys.record_audit_event", new_callable=AsyncMock) as mock_record:
        client.delete(f"/keys/{key['id']}", headers=headers)
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["action"] == "key.revoked"


def test_key_creation_audited_with_admin_actor_when_authenticated():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Admin Actor Project", "organization_id": org_id}, headers=headers).json()
    admin_key = client.post("/keys", json={"project_id": project["id"], "name": "admin", "permissions": ["admin"]}, headers=headers).json()

    # Creating a second key using the admin-scoped API key itself (not the dashboard
    # session) attributes the audit event to that key, not the dashboard user.
    with patch("apps.gateway.api.keys.record_audit_event", new_callable=AsyncMock) as mock_record:
        client.post(
            "/keys",
            json={"project_id": project["id"], "name": "created by admin"},
            headers={"Authorization": f"Bearer {admin_key['key']}"},
        )
    assert mock_record.call_args.kwargs["actor"] == f"api_key:{admin_key['id']}"


def test_provider_reload_calls_record_audit_event():
    _, headers = register_and_login(client)
    with patch("apps.gateway.api.providers_api.record_audit_event", new_callable=AsyncMock) as mock_record:
        client.post("/providers/reload", headers=headers)
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["action"] == "provider.reload"
    assert "active_providers_count" in mock_record.call_args.kwargs["details"]


def test_routing_rule_lifecycle_calls_record_audit_event():
    org_id, headers = register_and_login(client)

    with patch("apps.gateway.api.routing_rules.record_audit_event", new_callable=AsyncMock) as mock_record:
        rule = client.post(
            "/routing-rules",
            json={"organization_id": org_id, "name": "r1", "condition_expression": "latency > 500ms", "action_type": "reject"},
            headers=headers,
        ).json()
    assert mock_record.call_args.kwargs["action"] == "routing_rule.created"
    assert mock_record.call_args.kwargs["organization_id"] == org_id

    with patch("apps.gateway.api.routing_rules.record_audit_event", new_callable=AsyncMock) as mock_record:
        client.patch(f"/routing-rules/{rule['id']}", json={"priority": 50}, headers=headers)
    assert mock_record.call_args.kwargs["action"] == "routing_rule.updated"
    assert mock_record.call_args.kwargs["details"]["priority"] == 50

    with patch("apps.gateway.api.routing_rules.record_audit_event", new_callable=AsyncMock) as mock_record:
        client.delete(f"/routing-rules/{rule['id']}", headers=headers)
    assert mock_record.call_args.kwargs["action"] == "routing_rule.deleted"


def test_organization_update_calls_record_audit_event():
    org_id, headers = register_and_login(client)

    with patch("apps.gateway.api.organizations.record_audit_event", new_callable=AsyncMock) as mock_record:
        client.patch(f"/organizations/{org_id}", json={"plan": "enterprise"}, headers=headers)
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["action"] == "organization.updated"
    assert mock_record.call_args.kwargs["details"]["plan"] == "enterprise"
