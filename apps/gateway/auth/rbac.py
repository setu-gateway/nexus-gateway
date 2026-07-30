from enum import Enum
from typing import Callable, Set, Union

from fastapi import HTTPException, status


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    BILLING = "billing"
    SECURITY = "security"
    VIEWER = "viewer"


class Permission(str, Enum):
    CREATE_PROJECT = "create_project"
    DELETE_PROJECT = "delete_project"
    MANAGE_API_KEYS = "manage_api_keys"
    INVITE_MEMBERS = "invite_members"
    MANAGE_BILLING = "manage_billing"
    MANAGE_SETTINGS = "manage_settings"


ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.OWNER: {
        Permission.CREATE_PROJECT,
        Permission.DELETE_PROJECT,
        Permission.MANAGE_API_KEYS,
        Permission.INVITE_MEMBERS,
        Permission.MANAGE_BILLING,
        Permission.MANAGE_SETTINGS,
    },
    Role.ADMIN: {
        Permission.CREATE_PROJECT,
        Permission.DELETE_PROJECT,
        Permission.MANAGE_API_KEYS,
        Permission.INVITE_MEMBERS,
        Permission.MANAGE_SETTINGS,
    },
    Role.DEVELOPER: {
        Permission.CREATE_PROJECT,
        Permission.MANAGE_API_KEYS,
    },
    Role.BILLING: {
        Permission.MANAGE_BILLING,
    },
    Role.SECURITY: {
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_SETTINGS,
    },
    Role.VIEWER: set(),
}

# Coarse seniority used only by require_role()'s minimum-role gate. Owner and Admin are
# full-privilege tiers; Developer/Billing/Security are peer "specialized contributor"
# roles with non-overlapping permission sets - RFC-0003 lists them but doesn't define a
# strict order between them - so they rank equally, above read-only Viewer and below
# Admin/Owner. Use require_permission() instead when the distinction between them matters.
ROLE_RANK: dict[Role, int] = {
    Role.OWNER: 4,
    Role.ADMIN: 3,
    Role.DEVELOPER: 2,
    Role.BILLING: 2,
    Role.SECURITY: 2,
    Role.VIEWER: 1,
}


def has_permission(role: Union[Role, str], permission: Union[Permission, str]) -> bool:
    """Check if a given role possesses a specific permission."""
    try:
        r = Role(role) if isinstance(role, str) else role
        p = Permission(permission) if isinstance(permission, str) else permission
        return p in ROLE_PERMISSIONS.get(r, set())
    except ValueError:
        return False


def require_permission(required_permission: Permission) -> Callable:
    """FastAPI Dependency for enforcing role permissions."""

    async def permission_checker(current_user_role: str = "viewer") -> None:
        if not has_permission(current_user_role, required_permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: Requires '{required_permission.value}' permission",
            )

    return permission_checker


def require_role(required_role: Role) -> Callable:
    """FastAPI Dependency for enforcing minimum required role."""

    async def role_checker(current_user_role: str = "viewer") -> None:
        try:
            current = Role(current_user_role)
        except ValueError:
            current = None

        if current is None or ROLE_RANK[current] < ROLE_RANK[required_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role permission denied: Requires at least '{required_role.value}' role",
            )

    return role_checker
