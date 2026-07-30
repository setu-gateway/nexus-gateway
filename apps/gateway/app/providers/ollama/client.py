from typing import Any, Dict, Optional
import httpx


class OllamaClient:
    """Low-level HTTP client for local Ollama daemon."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def post_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def get_tags(self) -> Dict[str, Any]:
        url = f"{self.base_url}/api/tags"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
