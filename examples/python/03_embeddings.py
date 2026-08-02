"""Generating text embeddings via the Python SDK.

Run: python 03_embeddings.py
"""

from setu_gateway import SetuClient


def main() -> None:
    client = SetuClient()

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=["Setu Gateway routes LLM requests.", "It also caches responses."],
    )

    for item in response["data"]:
        vec = item["embedding"]
        print(f"embedding[{item['index']}]: dim={len(vec)}, first values={vec[:4]}")


if __name__ == "__main__":
    main()
