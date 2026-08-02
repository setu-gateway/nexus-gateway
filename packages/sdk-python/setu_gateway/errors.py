from typing import Any


class SetuError(Exception):
    """Base class for all errors raised by the Setu Gateway SDK."""


class SetuAPIError(SetuError):
    """The gateway responded with a non-2xx status. `status_code` and `body` are the
    raw HTTP status and parsed (or raw text) response body, for callers that want to
    branch on specific error shapes rather than just the message."""

    def __init__(self, message: str, *, status_code: int, body: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SetuConnectionError(SetuError):
    """The gateway could not be reached at all (DNS, connection refused, timeout)."""
