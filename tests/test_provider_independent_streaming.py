import asyncio
from typing import AsyncGenerator
import pytest

from packages.plugin_sdk import ChatRequest
from packages.shared.streaming import safe_sse_stream_generator
from plugins.providers.ollama.plugin import OllamaProviderPlugin
from plugins.providers.openai.plugin import OpenAIProviderPlugin


@pytest.mark.asyncio
async def test_openai_provider_independent_streaming():
    provider = OpenAIProviderPlugin()
    chat_req = ChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "Stream"}], stream=True)

    raw_stream = await provider.chat(chat_req)
    safe_stream = safe_sse_stream_generator(raw_stream, timeout_seconds=5.0, provider_name="openai")

    chunks = [c async for c in safe_stream]
    assert len(chunks) > 0
    assert any("data: " in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_ollama_provider_independent_streaming():
    provider = OllamaProviderPlugin()
    chat_req = ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "Stream"}], stream=True)

    raw_stream = await provider.chat(chat_req)
    safe_stream = safe_sse_stream_generator(raw_stream, timeout_seconds=5.0, provider_name="ollama")

    chunks = [c async for c in safe_stream]
    assert len(chunks) > 0
    assert any("data: " in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_streaming_graceful_cancellation():
    async def cancelling_stream() -> AsyncGenerator[str, None]:
        yield "data: {\"choices\": [{\"delta\": {\"content\": \"Chunk 1\"}}]}\n\n"
        raise asyncio.CancelledError()

    safe_stream = safe_sse_stream_generator(cancelling_stream(), timeout_seconds=5.0, provider_name="test")
    collected = []

    async for chunk in safe_stream:
        collected.append(chunk)

    assert len(collected) == 2
    assert "Chunk 1" in collected[0]
    assert collected[1] == "data: [DONE]\n\n"
