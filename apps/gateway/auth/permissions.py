from collections.abc import Iterable
from ipaddress import ip_address, ip_network


class KeyPermission:
    """Operations a scoped API key can be granted (Epic 5.3). Distinct from
    apps.gateway.auth.rbac.Permission, which governs what a *human* dashboard user's
    org role can do - this governs what a *machine* API key (sk_setu_...) can do when
    calling the gateway. Plain strings rather than a Python enum so they round-trip
    through JSON columns and API payloads unchanged."""

    CHAT = "chat"
    EMBEDDINGS = "embeddings"
    MODELS_READ = "models_read"
    ANALYTICS_READ = "analytics_read"
    MCP_INVOKE = "mcp_invoke"
    ADMIN = "admin"

    ALL = frozenset({CHAT, EMBEDDINGS, MODELS_READ, ANALYTICS_READ, MCP_INVOKE, ADMIN})


def has_key_permission(granted: Iterable[str] | None, required: str) -> bool:
    """A null/empty permissions list means "unrestricted" (legacy keys, and any key
    created without explicit scoping) - otherwise the required permission must be
    listed explicitly."""
    if not granted:
        return True
    return required in granted


def ip_allowed(allowed_ips: Iterable[str] | None, client_ip: str | None) -> bool:
    """A null/empty allowlist means "any IP". Entries may be single addresses or CIDR
    ranges (e.g. "10.0.0.0/8"); an unparseable client_ip or allowlist entry is treated
    as a non-match rather than raising, so a malformed value fails closed."""
    if not allowed_ips:
        return True
    if not client_ip:
        return False
    try:
        candidate = ip_address(client_ip)
    except ValueError:
        return False
    for entry in allowed_ips:
        try:
            if "/" in entry:
                if candidate in ip_network(entry, strict=False):
                    return True
            elif candidate == ip_address(entry):
                return True
        except ValueError:
            continue
    return False
