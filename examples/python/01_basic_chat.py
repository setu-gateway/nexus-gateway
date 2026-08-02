"""Basic (non-streaming) chat completion via the Python SDK.

Run: python 01_basic_chat.py
Requires a gateway running at SETU_BASE_URL (default http://localhost:8000).
No API key needed - see /getting-started/quickstart for why.
"""

from setu_gateway import SetuClient


def main() -> None:
    client = SetuClient()  # base_url/api_key default to SETU_BASE_URL/SETU_API_KEY env vars, then localhost:8000

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "What does an AI gateway do? One sentence."},
        ],
    )

    print(response["choices"][0]["message"]["content"])
    print(f"\nTokens used: {response['usage']['total_tokens']}")


if __name__ == "__main__":
    main()
