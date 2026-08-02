"""In-memory revocation list for JWT access/refresh tokens.

Shared between the /auth router (which populates it on logout/refresh) and
resolve_dashboard_user_or_401 (which checks it on every authenticated request) - both
need the same instance, so it lives here rather than in either module.

In-memory (not Postgres) is an intentional, separate trade-off from user persistence:
revocation doesn't survive a restart or replicate across gateway instances yet.
Tracked as a known follow-up, not fixed here.
"""

_blacklist: set[str] = set()


def blacklist_token(token: str) -> None:
    _blacklist.add(token)


def is_blacklisted(token: str) -> bool:
    return token in _blacklist
