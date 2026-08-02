from enum import Enum


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
    MANAGE_ROUTING = "manage_routing"
    MANAGE_WEBHOOKS = "manage_webhooks"
    MANAGE_PROVIDERS = "manage_providers"
    MANAGE_PROMPT_TEMPLATES = "manage_prompt_templates"
    RUN_EVALUATIONS = "run_evaluations"
    MANAGE_MCP_SERVERS = "manage_mcp_servers"
    VIEW_AUDIT_LOG = "view_audit_log"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OWNER: {
        Permission.CREATE_PROJECT,
        Permission.DELETE_PROJECT,
        Permission.MANAGE_API_KEYS,
        Permission.INVITE_MEMBERS,
        Permission.MANAGE_BILLING,
        Permission.MANAGE_SETTINGS,
        Permission.MANAGE_ROUTING,
        Permission.MANAGE_WEBHOOKS,
        Permission.MANAGE_PROVIDERS,
        Permission.MANAGE_PROMPT_TEMPLATES,
        Permission.RUN_EVALUATIONS,
        Permission.MANAGE_MCP_SERVERS,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.ADMIN: {
        Permission.CREATE_PROJECT,
        Permission.DELETE_PROJECT,
        Permission.MANAGE_API_KEYS,
        Permission.INVITE_MEMBERS,
        Permission.MANAGE_SETTINGS,
        Permission.MANAGE_ROUTING,
        Permission.MANAGE_WEBHOOKS,
        Permission.MANAGE_PROVIDERS,
        Permission.MANAGE_PROMPT_TEMPLATES,
        Permission.RUN_EVALUATIONS,
        Permission.MANAGE_MCP_SERVERS,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.DEVELOPER: {
        Permission.CREATE_PROJECT,
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_ROUTING,
        Permission.MANAGE_WEBHOOKS,
        Permission.MANAGE_PROMPT_TEMPLATES,
        Permission.RUN_EVALUATIONS,
        Permission.MANAGE_MCP_SERVERS,
    },
    Role.BILLING: {
        Permission.MANAGE_BILLING,
    },
    Role.SECURITY: {
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_SETTINGS,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.VIEWER: set(),
}

# Coarse seniority used only by require_role()'s minimum-role gate. Owner and Admin are
# full-privilege tiers; Developer/Billing/Security are peer "specialized contributor"
# roles with non-overlapping permission sets - RFC-0003 lists them but doesn't define a
# strict order between them - so they rank equally, above read-only Viewer and below
# Admin/Owner. Use has_permission() instead when the distinction between them matters.
ROLE_RANK: dict[Role, int] = {
    Role.OWNER: 4,
    Role.ADMIN: 3,
    Role.DEVELOPER: 2,
    Role.BILLING: 2,
    Role.SECURITY: 2,
    Role.VIEWER: 1,
}


def has_permission(role: Role | str, permission: Permission | str) -> bool:
    """Check if a given role possesses a specific permission."""
    try:
        r = Role(role) if isinstance(role, str) else role
        p = Permission(permission) if isinstance(permission, str) else permission
        return p in ROLE_PERMISSIONS.get(r, set())
    except ValueError:
        return False


def has_role_at_least(role: Role | str, required_role: Role) -> bool:
    """Check if a given role meets or exceeds required_role's seniority rank."""
    try:
        r = Role(role) if isinstance(role, str) else role
        return ROLE_RANK[r] >= ROLE_RANK[required_role]
    except (ValueError, KeyError):
        return False
