from typing import Any

import httpx


async def fetch_health(base_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base_url}/health", timeout=10.0)
    return {"status_code": resp.status_code, "body": resp.json()}


async def fetch_providers(base_url: str) -> list[dict[str, Any]]:
    """Merge GET /providers (config/capabilities) with GET /providers/metrics/all
    (live health/trust data) into one row per provider - the two are separate
    endpoints server-side (apps/gateway/api/providers_api.py) but `setu providers`
    is meant to answer "what's up and how's it doing" in a single table.
    """
    async with httpx.AsyncClient() as client:
        details_resp = await client.get(f"{base_url}/providers", timeout=10.0)
        details_resp.raise_for_status()
        metrics_resp = await client.get(f"{base_url}/providers/metrics/all", timeout=10.0)
        metrics_resp.raise_for_status()

    metrics_by_name = {m["provider_name"]: m for m in metrics_resp.json()}
    merged = []
    for detail in details_resp.json():
        metric = metrics_by_name.get(detail["provider_name"], {})
        merged.append(
            {
                "name": detail["provider_name"],
                "enabled": detail["enabled"],
                "models": len(detail.get("models", [])),
                "status": metric.get("status", "unknown"),
                "trust_score": metric.get("trust_score"),
                "latency_ms": metric.get("latency_ms"),
                "success_rate": metric.get("success_rate"),
            }
        )
    return merged


async def replay_prompt(base_url: str, *, model: str | None, providers: list[str] | None, prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"messages": [{"role": "user", "content": prompt}]}
    if model:
        payload["model"] = model
    if providers:
        payload["providers"] = providers

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{base_url}/routing/replay", json=payload, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def clear_cache(base_url: str, *, project_id: str | None) -> dict[str, Any]:
    params = {"project_id": project_id} if project_id else {}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(f"{base_url}/cache", params=params, timeout=10.0)
    resp.raise_for_status()
    return resp.json()
