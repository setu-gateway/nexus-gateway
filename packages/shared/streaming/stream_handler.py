import asyncio
import json
from collections.abc import AsyncGenerator

from packages.shared.logging.logger import get_logger

logger = get_logger("stream_handler")


async def safe_sse_stream_generator(
    generator: AsyncGenerator[str, None],
    timeout_seconds: float = 30.0,
    provider_name: str = "generic",
) -> AsyncGenerator[str, None]:
    """Wrap a raw provider SSE stream with timeout protection, graceful cancellation handling,
    and consistent chunk formatting.
    """
    done_sent = False
    try:
        async for chunk in _timeout_wrapper(generator, timeout_seconds):
            if "[DONE]" in chunk:
                done_sent = True
            yield chunk
    except asyncio.CancelledError:
        logger.info(f"SSE Stream cancelled gracefully by client for provider '{provider_name}'")
        return
    except asyncio.TimeoutError:
        logger.warning(f"SSE Stream timed out after {timeout_seconds}s for provider '{provider_name}'")
        err_event = {
            "error": {
                "message": f"Stream request timed out after {timeout_seconds} seconds",
                "type": "timeout_error",
                "code": 408,
            }
        }
        yield f"data: {json.dumps(err_event)}\n\n"
    except Exception as e:
        logger.error(f"Error during SSE stream from provider '{provider_name}': {e}")
        err_event = {
            "error": {
                "message": f"Stream error occurred: {str(e)}",
                "type": "server_error",
                "code": 500,
            }
        }
        yield f"data: {json.dumps(err_event)}\n\n"
    finally:
        if not done_sent:
            yield "data: [DONE]\n\n"


async def _timeout_wrapper(generator: AsyncGenerator[str, None], timeout_seconds: float):
    it = aiter(generator)
    while True:
        try:
            chunk = await asyncio.wait_for(anext(it), timeout=timeout_seconds)
            yield chunk
        except StopAsyncIteration:
            break
