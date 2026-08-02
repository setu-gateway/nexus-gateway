import hashlib
import hmac
import secrets


def generate_webhook_secret() -> str:
    return f"whsec_{secrets.token_hex(24)}"


def sign_payload(secret: str, payload_bytes: bytes) -> str:
    """HMAC-SHA256 signature over the raw request body, hex-encoded - a receiver
    recomputes this over the bytes it received and compares with hmac.compare_digest
    to verify a delivery genuinely came from this gateway."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def verify_signature(secret: str, payload_bytes: bytes, signature: str) -> bool:
    expected = sign_payload(secret, payload_bytes)
    return hmac.compare_digest(expected, signature)
