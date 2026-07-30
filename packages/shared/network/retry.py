import asyncio
from typing import Any, Callable
import httpx

from packages.shared.logging.logger import get_logger

logger = get_logger("retry_handler")

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


async def execute_with_exponential_backoff(
    func: Callable[[], Any],
    max_retries: int = 3,
    initial_backoff_sec: float = 0.5,
    backoff_factor: float = 2.0,
    provider_name: str = "generic",
) -> Any:
    """Execute an async network call with exponential backoff retries for transient failures."""
    attempt = 0
    while True:
        try:
            return await func()
        except Exception as e:
            attempt += 1
            status_code = getattr(getattr(e, "response", None), "status_code", None)

            is_transient = (status_code in TRANSIENT_STATUS_CODES) if status_code else isinstance(
                e, (httpx.NetworkError, httpx.TimeoutException)
            )

            if attempt > max_retries or not is_transient:
                logger.error(
                    f"Provider '{provider_name}' request failed permanently after {attempt} attempts (status={status_code}): {e}"
                )
                raise e

            sleep_duration = initial_backoff_sec * (backoff_factor ** (attempt - 1))
            logger.warning(
                f"Transient failure on provider '{provider_name}' (status={status_code}, attempt={attempt}/{max_retries}). "
                f"Retrying in {sleep_duration:.2f}s..."
            )
            await asyncio.sleep(sleep_duration)
