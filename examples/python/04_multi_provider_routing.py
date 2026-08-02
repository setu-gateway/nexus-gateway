"""Calling multiple providers through one client - the core value of a gateway.

Run: python 04_multi_provider_routing.py

Same client, same code shape, different `model` string per provider - the
gateway resolves each to the right upstream provider and API format. Add real
provider API keys to the gateway's .env for genuinely different model
"personalities" here; with none configured, every provider returns its own
labeled mock response, which is still enough to see each one being reached.

Note: the response's `model` field is the actual upstream model ID that
answered - it can differ from what you requested for two different reasons:
normal unified-ID-to-upstream-ID translation (e.g. "llama3" -> "llama3.2",
same provider), or the gateway's routing policy failing over to a genuinely
different *provider* if it currently has a higher trust score (see
/features/routing). This script prints it either way so it's never a silent
surprise; to force an exact provider instead of policy-based routing, use
POST /routing/replay - see 06_provider_comparison.py.
"""

from setu_gateway import SetuAPIError, SetuClient, SetuConnectionError

# One unified model ID per provider - see /providers/openai etc. for the full catalog.
MODELS = ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro", "groq-llama-3.3", "llama3"]


def main() -> None:
    client = SetuClient()
    prompt = "Say which model you are, in five words or fewer."

    for model in MODELS:
        try:
            response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
            content = response["choices"][0]["message"]["content"]
            served_by = response.get("model", "?")
            print(f"{model:20s} -> {content}  [served by: {served_by}]")
        except SetuAPIError as e:
            print(f"{model:20s} -> API error {e.status_code}: {e.body}")
        except SetuConnectionError as e:
            print(f"{model:20s} -> could not reach gateway: {e}")


if __name__ == "__main__":
    main()
