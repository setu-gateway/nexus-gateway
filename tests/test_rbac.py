import pytest
from fastapi import HTTPException

from apps.gateway.auth.dashboard_context import DashboardUserContext, require_permission, require_role
from apps.gateway.auth.rbac import Permission, Role, has_permission, has_role_at_least


def _user(role: str) -> DashboardUserContext:
    return DashboardUserContext(
        user_id="00000000-0000-0000-0000-000000000001",
        email="test@example.com",
        organization_id="00000000-0000-0000-0000-000000000002",
        role=role,
        is_verified=True,
    )


def test_rbac_roles_and_permissions_matrix():
    # Owner should have all permissions
    assert has_permission(Role.OWNER, Permission.CREATE_PROJECT) is True
    assert has_permission(Role.OWNER, Permission.DELETE_PROJECT) is True
    assert has_permission(Role.OWNER, Permission.MANAGE_API_KEYS) is True
    assert has_permission(Role.OWNER, Permission.INVITE_MEMBERS) is True
    assert has_permission(Role.OWNER, Permission.MANAGE_BILLING) is True
    assert has_permission(Role.OWNER, Permission.MANAGE_SETTINGS) is True

    # Admin should have all except billing
    assert has_permission(Role.ADMIN, Permission.CREATE_PROJECT) is True
    assert has_permission(Role.ADMIN, Permission.DELETE_PROJECT) is True
    assert has_permission(Role.ADMIN, Permission.MANAGE_API_KEYS) is True
    assert has_permission(Role.ADMIN, Permission.INVITE_MEMBERS) is True
    assert has_permission(Role.ADMIN, Permission.MANAGE_BILLING) is False
    assert has_permission(Role.ADMIN, Permission.MANAGE_SETTINGS) is True

    # Developer can create project & manage api keys, but not delete, invite, billing, or settings
    assert has_permission(Role.DEVELOPER, Permission.CREATE_PROJECT) is True
    assert has_permission(Role.DEVELOPER, Permission.MANAGE_API_KEYS) is True
    assert has_permission(Role.DEVELOPER, Permission.DELETE_PROJECT) is False
    assert has_permission(Role.DEVELOPER, Permission.INVITE_MEMBERS) is False
    assert has_permission(Role.DEVELOPER, Permission.MANAGE_BILLING) is False

    # Viewer has no write/admin permissions
    assert has_permission(Role.VIEWER, Permission.CREATE_PROJECT) is False
    assert has_permission(Role.VIEWER, Permission.MANAGE_API_KEYS) is False
    assert has_permission(Role.VIEWER, Permission.MANAGE_BILLING) is False


def test_has_role_at_least_fails_closed_on_garbage_input():
    assert has_role_at_least("not-a-real-role", Role.VIEWER) is False


@pytest.mark.asyncio
async def test_require_permission_dependency():
    checker = require_permission(Permission.MANAGE_BILLING)

    # Owner passes
    await checker(user=_user("owner"))

    # Developer fails with 403
    with pytest.raises(HTTPException) as exc_info:
        await checker(user=_user("developer"))
    assert exc_info.value.status_code == 403
    assert "Permission denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_role_dependency():
    role_checker = require_role(Role.OWNER)

    # Owner passes
    await role_checker(user=_user("owner"))

    # Admin fails
    with pytest.raises(HTTPException) as exc_info:
        await role_checker(user=_user("admin"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_is_a_minimum_not_an_exact_match():
    # A route gated to the "developer" minimum should also admit higher-ranked roles.
    developer_gate = require_role(Role.DEVELOPER)
    await developer_gate(user=_user("owner"))
    await developer_gate(user=_user("admin"))
    await developer_gate(user=_user("developer"))

    # Viewer is below the "developer" minimum and should still be rejected.
    with pytest.raises(HTTPException) as exc_info:
        await developer_gate(user=_user("viewer"))
    assert exc_info.value.status_code == 403

    # Unknown/garbage role strings must fail closed, not raise a KeyError.
    with pytest.raises(HTTPException):
        await developer_gate(user=_user("not-a-real-role"))


def test_billing_and_security_roles_exist_per_rfc_0003():
    assert has_permission(Role.BILLING, Permission.MANAGE_BILLING) is True
    assert has_permission(Role.BILLING, Permission.DELETE_PROJECT) is False
    assert has_permission(Role.SECURITY, Permission.MANAGE_SETTINGS) is True
    assert has_permission(Role.SECURITY, Permission.MANAGE_BILLING) is False
