class ProviderException(Exception):
    """Base exception for all provider SDK errors."""

    def __init__(self, message: str, provider_name: str = "generic", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.status_code = status_code


class ProviderAuthenticationError(ProviderException):
    """Raised when authentication with the provider fails."""

    def __init__(self, message: str = "Invalid provider API key or credentials", provider_name: str = "generic"):
        super().__init__(message, provider_name=provider_name, status_code=401)


class ProviderRateLimitError(ProviderException):
    """Raised when provider rate limits are exceeded."""

    def __init__(self, message: str = "Provider rate limit exceeded", provider_name: str = "generic"):
        super().__init__(message, provider_name=provider_name, status_code=429)


class ProviderTimeoutError(ProviderException):
    """Raised when a request to the provider times out."""

    def __init__(self, message: str = "Provider request timed out", provider_name: str = "generic"):
        super().__init__(message, provider_name=provider_name, status_code=408)


class ProviderNotFoundError(ProviderException):
    """Raised when requested provider or model is not found."""

    def __init__(self, message: str = "Requested provider or model not found", provider_name: str = "generic"):
        super().__init__(message, provider_name=provider_name, status_code=404)
