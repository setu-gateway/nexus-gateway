from fastapi import HTTPException
import pytest

from apps.gateway.auth.rbac import (
    Permission,
    ROLE_PERMISSIONS,
    Role,
    has_permission,
    require_permission,
    require_role,
)


def test_rbac_roles_and_permissions_matrix():
    # Owner should have all 6 permissions
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


@pytest.mark.asyncio
async def test_require_permission_dependency():
    checker = require_permission(Permission.MANAGE_BILLING)

    # Owner passes
    await checker(current_user_role="owner")

    # Developer fails with 403
    with pytest.raises(HTTPException) as exc_info:
        await checker(current_user_role="developer")
    assert exc_info.value.status_code == 403
    assert "Permission denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_role_dependency():
    role_checker = require_role(Role.OWNER)

    # Owner passes
    await role_checker(current_user_role="owner")

    # Admin fails
    with pytest.raises(HTTPException) as exc_info:
        await role_checker(current_user_role="admin")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_is_a_minimum_not_an_exact_match():
    # A route gated to the "developer" minimum should also admit higher-ranked roles.
    developer_gate = require_role(Role.DEVELOPER)
    await developer_gate(current_user_role="owner")
    await developer_gate(current_user_role="admin")
    await developer_gate(current_user_role="developer")

    # Viewer is below the "developer" minimum and should still be rejected.
    with pytest.raises(HTTPException) as exc_info:
        await developer_gate(current_user_role="viewer")
    assert exc_info.value.status_code == 403

    # Unknown/garbage role strings must fail closed, not raise a KeyError.
    with pytest.raises(HTTPException):
        await developer_gate(current_user_role="not-a-real-role")


def test_billing_and_security_roles_exist_per_rfc_0003():
    assert has_permission(Role.BILLING, Permission.MANAGE_BILLING) is True
    assert has_permission(Role.BILLING, Permission.DELETE_PROJECT) is False
    assert has_permission(Role.SECURITY, Permission.MANAGE_SETTINGS) is True
    assert has_permission(Role.SECURITY, Permission.MANAGE_BILLING) is False
