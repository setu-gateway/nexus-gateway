import hashlib
import json
from typing import Any


def compute_cache_key(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    top_p: float | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Exact-match cache key (Epic 5.1): provider + model + messages (system prompt
    included, since it's just another message) + temperature + top_p + tools.

    Two requests differing in any of these fields are, by definition, different
    requests and must not share a cache entry - sort_keys makes the hash independent
    of incidental dict-ordering so equivalent requests always collide correctly.
    """
    payload = {
        "provider": provider.lower(),
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "tools": tools,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
