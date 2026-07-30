import asyncio
from typing import AsyncGenerator
import pytest

from packages.shared.streaming import safe_sse_stream_generator


async def mock_normal_stream() -> AsyncGenerator[str, None]:
    yield "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n"
    yield "data: {\"choices\": [{\"delta\": {\"content\": \" World\"}}]}\n\n"
    yield "data: [DONE]\n\n"


async def mock_slow_stream() -> AsyncGenerator[str, None]:
    yield "data: {\"choices\": [{\"delta\": {\"content\": \"First\"}}]}\n\n"
    await asyncio.sleep(0.5)  # Intentionally exceed short timeout
    yield "data: {\"choices\": [{\"delta\": {\"content\": \"Second\"}}]}\n\n"


@pytest.mark.asyncio
async def test_safe_sse_stream_normal_flow():
    safe_gen = safe_sse_stream_generator(mock_normal_stream(), timeout_seconds=5.0)
    chunks = [c async for c in safe_gen]

    assert len(chunks) == 3
    assert "Hello" in chunks[0]
    assert "World" in chunks[1]
    assert chunks[2] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_safe_sse_stream_timeout():
    safe_gen = safe_sse_stream_generator(mock_slow_stream(), timeout_seconds=0.1)
    chunks = [c async for c in safe_gen]

    assert len(chunks) >= 2
    assert "First" in chunks[0]
    assert "timeout_error" in chunks[1]
    assert chunks[-1] == "data: [DONE]\n\n"
