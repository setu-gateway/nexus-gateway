"""Comparing multiple providers' responses to the same prompt, side by side.

Run: python 06_provider_comparison.py

/routing/replay isn't wrapped by the SDK, so this uses httpx directly. Unlike
Time Machine, replay is a one-shot diagnostic call - nothing is stored, and it
isn't recorded to analytics.

Passing an explicit `model` alongside `providers` sends that exact model
string to every provider listed (rather than each provider's own name as a
placeholder, which is what happens if you omit `model` here - harmless with
no provider API keys configured since nothing validates it, but a real
provider would reject a nonsense model name).

Anthropic is disabled by default (see /providers/anthropic) - expect its
result to report `success: false` unless you've enabled it.
"""

import os

import httpx

BASE_URL = os.environ.get("SETU_BASE_URL", "http://localhost:8000")


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        resp = client.post(
            "/routing/replay",
            json={
                "providers": ["openai", "anthropic", "gemini", "groq"],
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "What makes a good API gateway? One sentence."}],
            },
        )
        resp.raise_for_status()

        for result in resp.json()["results"]:
            if result["success"]:
                print(f"{result['provider']:12s} ({result['latency_ms']:.0f}ms): {result['response']['choices'][0]['message']['content']}")
            else:
                print(f"{result['provider']:12s} FAILED: {result['error']}")


if __name__ == "__main__":
    main()
