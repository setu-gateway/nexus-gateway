import hashlib
import secrets
from typing import Tuple


def generate_api_key(prefix: str = "sk_setu_") -> Tuple[str, str]:
    """Generate a secure API key and its SHA-256 hash.
    
    Returns:
        Tuple[str, str]: (plaintext_key, hashed_key)
        - plaintext_key is shown ONLY ONCE to the user on creation.
        - hashed_key is stored in the database.
    """
    random_bytes = secrets.token_hex(24)
    plaintext_key = f"{prefix}{random_bytes}"
    hashed_key = hash_api_key(plaintext_key)
    return plaintext_key, hashed_key


def hash_api_key(plaintext_key: str) -> str:
    """Hash a plaintext API key using SHA-256."""
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def verify_api_key(plaintext_key: str, stored_hash: str) -> bool:
    """Secure constant-time verification of a plaintext API key against stored hash."""
    computed_hash = hash_api_key(plaintext_key)
    return secrets.compare_digest(computed_hash, stored_hash)


def mask_api_key(plaintext_key: str) -> str:
    """Mask plaintext key for display (e.g. sk_setu_...a1b2)."""
    if len(plaintext_key) <= 12:
        return "****"
    return f"{plaintext_key[:8]}...{plaintext_key[-4:]}"
