class WebhookEvent:
    """Event types a WebhookEndpoint can subscribe to (Epic 5.7). All six are scoped to
    an organization that already exists at the moment they fire - notably
    project.created rather than organization.created, since a webhook can only be
    registered against an organization that's already there to own it."""

    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"
    KEY_CREATED = "key.created"
    KEY_REVOKED = "key.revoked"
    PROJECT_CREATED = "project.created"
    QUOTA_EXCEEDED = "quota.exceeded"

    ALL = frozenset({REQUEST_COMPLETED, REQUEST_FAILED, KEY_CREATED, KEY_REVOKED, PROJECT_CREATED, QUOTA_EXCEEDED})
