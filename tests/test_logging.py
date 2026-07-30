import io
import json
import logging
import pytest

from packages.shared.logging.logger import (
    JSONFormatter,
    clear_context,
    get_logger,
    set_request_id,
    set_trace_id,
    setup_structured_logging,
)


@pytest.fixture(autouse=True)
def reset_logging_context():
    clear_context()
    yield
    clear_context()


def test_json_formatter_keys():
    formatter = JSONFormatter(service_name="gateway")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test structured log message",
        args=(),
        exc_info=None,
    )

    formatted_output = formatter.format(record)
    parsed = json.loads(formatted_output)

    assert "timestamp" in parsed
    assert parsed["level"] == "INFO"
    assert "trace_id" in parsed
    assert "request_id" in parsed
    assert parsed["service"] == "gateway"
    assert parsed["message"] == "Test structured log message"


def test_json_formatter_context_vars():
    set_trace_id("trace-abc-123")
    set_request_id("req-xyz-789")

    formatter = JSONFormatter(service_name="gateway")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.WARNING,
        pathname="test.py",
        lineno=20,
        msg="Context var trace test",
        args=(),
        exc_info=None,
    )

    formatted_output = formatter.format(record)
    parsed = json.loads(formatted_output)

    assert parsed["trace_id"] == "trace-abc-123"
    assert parsed["request_id"] == "req-xyz-789"
    assert parsed["level"] == "WARNING"


def test_setup_structured_logging(capsys):
    setup_structured_logging(service_name="gateway", level="INFO")
    logger = get_logger("gateway")

    logger.info("Executing gateway request lifecycle")

    captured = capsys.readouterr()
    log_line = captured.out.strip()

    parsed = json.loads(log_line)
    assert parsed["service"] == "gateway"
    assert parsed["message"] == "Executing gateway request lifecycle"
    assert parsed["level"] == "INFO"
