from typing import Any, AsyncGenerator, Dict, Optional
import httpx

from packages.shared.network import execute_with_exponential_backoff


class OpenAIClient:
    """Low-level HTTP client for OpenAI API with exponential backoff retries."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def post_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"

        async def _call():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()

        return await execute_with_exponential_backoff(_call, provider_name="openai")

    async def post_embeddings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/embeddings"

        async def _call():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()

        return await execute_with_exponential_backoff(_call, provider_name="openai")
