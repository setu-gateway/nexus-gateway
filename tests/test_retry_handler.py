import httpx
import pytest

from packages.shared.network.retry import execute_with_exponential_backoff


@pytest.mark.asyncio
async def test_exponential_backoff_success_on_first_try():
    calls = 0

    async def mock_func():
        nonlocal calls
        calls += 1
        return "success"

    res = await execute_with_exponential_backoff(mock_func, max_retries=3, initial_backoff_sec=0.01)
    assert res == "success"
    assert calls == 1


@pytest.mark.asyncio
async def test_exponential_backoff_retry_then_succeed():
    calls = 0

    async def mock_transient_failure():
        nonlocal calls
        calls += 1
        if calls < 3:
            req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("500 Internal Error", request=req, response=resp)
        return "recovered"

    res = await execute_with_exponential_backoff(
        mock_transient_failure,
        max_retries=3,
        initial_backoff_sec=0.01,
        backoff_factor=1.5,
    )
    assert res == "recovered"
    assert calls == 3


@pytest.mark.asyncio
async def test_exponential_backoff_permanent_error_no_retry():
    calls = 0

    async def mock_permanent_failure():
        nonlocal calls
        calls += 1
        req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        resp = httpx.Response(401, request=req)
        raise httpx.HTTPStatusError("401 Unauthorized", request=req, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        await execute_with_exponential_backoff(
            mock_permanent_failure,
            max_retries=3,
            initial_backoff_sec=0.01,
        )

    # 401 is permanent, should not retry
    assert calls == 1
