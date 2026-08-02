"""Streaming a chat completion token-by-token via the Python SDK.

Run: python 02_streaming.py

Note: OpenAI, Groq, and Ollama stream incrementally end-to-end. Anthropic and
Gemini currently deliver the full answer as a single chunk rather than
token-by-token (see /support/troubleshooting) - the code below works
identically either way, it's just less visually "typed out" for those two.
"""

from setu_gateway import SetuClient


def main() -> None:
    client = SetuClient()

    stream = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Count from 1 to 5, one number per line."}],
        stream=True,
    )

    for chunk in stream:
        delta = chunk["choices"][0].get("delta", {})
        if "content" in delta:
            print(delta["content"], end="", flush=True)
    print()


if __name__ == "__main__":
    main()
