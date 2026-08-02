# Python SDK (`packages/sdk-python`)

Official Python client library for integrating applications with Setu Gateway.

## Install

```bash
pip install setu-gateway-sdk
```

## Usage

```python
from setu_gateway import SetuClient

client = SetuClient(api_key="sk_setu_...", base_url="https://gateway.example.com")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarize what an AI gateway does."}],
)
print(response["choices"][0]["message"]["content"])
```

`api_key` and `base_url` also fall back to the `SETU_API_KEY` / `SETU_BASE_URL`
environment variables, and `base_url` defaults to `http://localhost:8000` if neither
is set.

### Streaming

```python
for chunk in client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Count to five."}],
    stream=True,
):
    delta = chunk["choices"][0].get("delta", {})
    if "content" in delta:
        print(delta["content"], end="", flush=True)
```

### Async

```python
import asyncio
from setu_gateway import AsyncSetuClient


async def main():
    async with AsyncSetuClient(api_key="sk_setu_...") as client:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        print(response["choices"][0]["message"]["content"])


asyncio.run(main())
```

### Embeddings and models

```python
client.embeddings.create(model="text-embedding-3-small", input="hello world")
client.models.list()
```

### Errors

`SetuAPIError` is raised for non-2xx responses (`.status_code` and `.body` carry the
gateway's error detail); `SetuConnectionError` is raised when the gateway can't be
reached at all.

```python
from setu_gateway import SetuAPIError

try:
    client.chat.completions.create(model="gpt-4o", messages=[])
except SetuAPIError as e:
    print(e.status_code, e.body)
```
