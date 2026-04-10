from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from ragflow_lite.shared import observability


def _make_record(**extra: object) -> logging.LogRecord:
    logger = logging.getLogger("tests.observability")
    return logger.makeRecord(
        "tests.observability",
        logging.INFO,
        __file__,
        10,
        "message",
        (),
        None,
        extra=extra,
    )


@contextmanager
def _isolated_root_logger() -> Iterator[logging.Logger]:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    for handler in original_handlers:
        root_logger.removeHandler(handler)

    try:
        yield root_logger
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if handler not in original_handlers:
                handler.close()
        root_logger.setLevel(original_level)
        for handler in original_handlers:
            root_logger.addHandler(handler)


def test_snowflake_trace_ids_are_unique_and_increasing(
    monkeypatch,
) -> None:
    values = iter(
        [
            1_700_000_000_000_000_000,
            1_700_000_000_000_000_000,
            1_700_000_000_001_000_000,
        ]
    )
    monkeypatch.setattr(observability.time, "time_ns", lambda: next(values))
    generator = observability.SnowflakeIdGenerator(worker_id=7)

    first = generator.next_id()
    second = generator.next_id()
    third = generator.next_id()

    assert first.isdigit()
    assert second.isdigit()
    assert third.isdigit()
    assert len({first, second, third}) == 3
    assert int(first) < int(second) < int(third)


def test_request_context_bind_and_clear() -> None:
    observability.clear_request_context()

    context = observability.bind_request_context("trace-123")

    assert context.trace_id == "trace-123"
    assert observability.current_trace_id() == "trace-123"
    assert observability.current_request_id() == context.request_id
    assert context.request_id

    observability.clear_request_context()

    assert observability.current_trace_id() == ""
    assert observability.current_request_id() == ""


def test_text_formatter_outputs_core_fields() -> None:
    record = _make_record(
        event="request_error",
        trace_id="trace-123",
        request_id="req-456",
        safe_field="value",
    )

    formatted = observability.TextLogFormatter().format(record)

    assert "INFO tests.observability request_error" in formatted
    assert 'trace_id="trace-123"' in formatted
    assert 'request_id="req-456"' in formatted
    assert 'safe_field="value"' in formatted


def test_json_formatter_outputs_core_fields() -> None:
    record = _make_record(
        event="query_succeeded",
        trace_id="trace-789",
        request_id="req-abc",
        top_k=3,
    )

    payload = json.loads(observability.JsonLogFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "tests.observability"
    assert payload["event"] == "query_succeeded"
    assert payload["trace_id"] == "trace-789"
    assert payload["request_id"] == "req-abc"
    assert payload["top_k"] == 3
    assert "timestamp" in payload


def test_setup_logging_replaces_managed_handler_without_duplicates() -> None:
    with _isolated_root_logger() as root_logger:
        observability.setup_logging("INFO", "text")
        observability.setup_logging("DEBUG", "json")

        handlers = [
            handler
            for handler in root_logger.handlers
            if handler.get_name() == "ragflow_lite_root_handler"
        ]

        assert len(handlers) == 1
        assert root_logger.level == logging.DEBUG
        assert isinstance(handlers[0].formatter, observability.JsonLogFormatter)


def test_setup_logging_preserves_existing_non_managed_root_handler() -> None:
    with _isolated_root_logger() as root_logger:
        host_handler = logging.StreamHandler()
        host_handler.set_name("host_handler")
        root_logger.addHandler(host_handler)

        observability.setup_logging("INFO", "text")
        observability.setup_logging("DEBUG", "json")

        assert root_logger.level == logging.DEBUG
        assert root_logger.handlers == [host_handler]
        assert not [
            handler
            for handler in root_logger.handlers
            if handler.get_name() == "ragflow_lite_root_handler"
        ]
