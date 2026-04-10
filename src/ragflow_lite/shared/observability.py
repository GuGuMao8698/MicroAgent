"""轻量可观测性模块。

提供显式 logging 初始化、request-scoped trace/request context、
结构化日志 helper，以及可选 Prometheus 指标。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from traceback import TracebackException
from typing import Any, Literal

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

LogFormat = Literal["text", "json"]

_MANAGED_ROOT_HANDLER_NAME = "ragflow_lite_root_handler"
_HISTOGRAM_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# LogRecord 内建属性名，不允许作为 extra 键。
_RESERVED_LOG_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "relativeCreated",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "pathname",
        "filename",
        "module",
        "levelname",
        "levelno",
        "msecs",
        "message",
        "asctime",
        "process",
        "processName",
        "thread",
        "threadName",
        "taskName",
    }
)

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


@dataclass(slots=True, frozen=True)
class RequestContext:
    request_id: str
    trace_id: str


@dataclass(slots=True)
class SnowflakeIdGenerator:
    """生成 Snowflake 风格十进制 trace_id。"""

    worker_id: int = field(default_factory=lambda: os.getpid() & 0x3FF)
    _lock: threading.Lock = field(init=False, repr=False)
    _last_timestamp_ms: int = field(init=False, repr=False, default=-1)
    _sequence: int = field(init=False, repr=False, default=0)

    def __post_init__(self) -> None:
        if not 0 <= self.worker_id <= 0x3FF:
            raise RuntimeError("Snowflake worker_id must be between 0 and 1023.")
        self._lock = threading.Lock()

    def next_id(self) -> str:
        with self._lock:
            timestamp_ms = time.time_ns() // 1_000_000
            if timestamp_ms < self._last_timestamp_ms:
                timestamp_ms = self._last_timestamp_ms

            if timestamp_ms == self._last_timestamp_ms:
                self._sequence = (self._sequence + 1) & 0xFFF
                if self._sequence == 0:
                    timestamp_ms = max(time.time_ns() // 1_000_000, timestamp_ms + 1)
            else:
                self._sequence = 0

            self._last_timestamp_ms = timestamp_ms
            value = (timestamp_ms << 22) | (self.worker_id << 12) | self._sequence
            return str(value)


@dataclass(slots=True)
class _MetricsState:
    enabled: bool
    registry: CollectorRegistry
    http_requests_total: Counter | None = None
    http_request_duration_seconds: Histogram | None = None
    http_requests_in_progress: Gauge | None = None
    http_request_exceptions_total: Counter | None = None
    ingest_total: Counter | None = None
    query_total: Counter | None = None


_TRACE_ID_GENERATOR = SnowflakeIdGenerator()
_metrics_state_ctx: ContextVar[_MetricsState | None] = ContextVar(
    "metrics_state",
    default=None,
)


def _normalize_log_level(level: str) -> int:
    normalized = level.strip().upper()
    mapping = logging.getLevelNamesMapping()
    resolved = mapping.get(normalized)
    if not isinstance(resolved, int):
        raise RuntimeError(
            f"Unsupported RAGFLOW_LITE_LOG_LEVEL '{level}'. "
            "Use a standard logging level such as DEBUG, INFO, WARNING, ERROR or CRITICAL."
        )
    return resolved


def normalize_log_format(log_format: str) -> LogFormat:
    normalized = log_format.strip().lower()
    if normalized not in {"text", "json"}:
        raise RuntimeError(
            f"Unsupported RAGFLOW_LITE_LOG_FORMAT '{log_format}'. Use 'text' or 'json'."
        )
    return normalized  # type: ignore[return-value]


def _iso_timestamp(record: logging.LogRecord) -> str:
    timestamp = datetime.fromtimestamp(record.created, UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_field_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _safe_field_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_field_value(item) for item in value]
    return str(value)


def current_request_id() -> str:
    return request_id_ctx.get("")


def current_trace_id() -> str:
    return trace_id_ctx.get("")


def new_request_id() -> str:
    """生成一个内部 request_id 并存入 context var。"""
    rid = uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    return rid


def new_trace_id() -> str:
    """生成一个 Snowflake 风格 trace_id 并存入 context var。"""
    trace_id = _TRACE_ID_GENERATOR.next_id()
    trace_id_ctx.set(trace_id)
    return trace_id


def bind_request_context(incoming_trace_id: str | None = None) -> RequestContext:
    """绑定本次请求的 trace_id / request_id。"""
    request_id = new_request_id()
    trace_id = (incoming_trace_id or "").strip() or new_trace_id()
    if trace_id != current_trace_id():
        trace_id_ctx.set(trace_id)
    return RequestContext(request_id=request_id, trace_id=trace_id)


def clear_request_context() -> None:
    request_id_ctx.set("")
    trace_id_ctx.set("")


def _base_extra() -> dict[str, Any]:
    extra: dict[str, Any] = {}
    request_id = current_request_id()
    trace_id = current_trace_id()
    if request_id:
        extra["request_id"] = request_id
    if trace_id:
        extra["trace_id"] = trace_id
    return extra


def _record_extra(record: logging.LogRecord) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_ATTRS or key.startswith("_"):
            continue
        extra[key] = _safe_field_value(value)

    if "event" not in extra:
        extra["event"] = record.getMessage()

    request_id = extra.get("request_id") or current_request_id()
    if request_id:
        extra["request_id"] = request_id

    trace_id = extra.get("trace_id") or current_trace_id()
    if trace_id:
        extra["trace_id"] = trace_id

    return extra


def _ordered_extra_items(extra: dict[str, Any]) -> list[tuple[str, Any]]:
    preferred_order = ("trace_id", "request_id")
    items: list[tuple[str, Any]] = []
    for key in preferred_order:
        if key in extra:
            items.append((key, extra[key]))
    for key in sorted(extra):
        if key not in preferred_order:
            items.append((key, extra[key]))
    return items


class TextLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extra = _record_extra(record)
        event = str(extra.pop("event"))
        message = f"{_iso_timestamp(record)} {record.levelname} {record.name} {event}"

        formatted_fields = [
            f"{key}={json.dumps(value, ensure_ascii=False, default=str)}"
            for key, value in _ordered_extra_items(extra)
        ]
        if formatted_fields:
            message = f"{message} {' '.join(formatted_fields)}"

        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            message = f"{message}\n{exception_text}"
        elif record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        return message


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extra = _record_extra(record)
        payload: dict[str, Any] = {
            "timestamp": _iso_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "event": extra.pop("event"),
        }
        payload.update(extra)
        if record.exc_info:
            payload["exception"] = "".join(
                TracebackException.from_exception(record.exc_info[1]).format()
            )
        elif record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_root_handler(log_format: LogFormat) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_MANAGED_ROOT_HANDLER_NAME)
    formatter: logging.Formatter
    if log_format == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = TextLogFormatter()
    handler.setFormatter(formatter)
    return handler


def setup_logging(log_level: str, log_format: str) -> None:
    """初始化根 logger。

    每次调用都会替换本模块托管的 handler，避免重复挂载，同时允许测试
    在多次 create_app() 之间切换 text/json formatter。
    """
    resolved_level = _normalize_log_level(log_level)
    resolved_format = normalize_log_format(log_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    managed_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, "name", "") == _MANAGED_ROOT_HANDLER_NAME
    ]
    for handler in managed_handlers:
        root_logger.removeHandler(handler)
        handler.close()

    if root_logger.handlers:
        return

    root_logger.addHandler(_build_root_handler(resolved_format))


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: bool | BaseException | tuple[Any, Any, Any] | None = None,
    **fields: Any,
) -> None:
    """记录一条结构化日志事件，字段扁平写入 extra。

    自动跳过与 LogRecord 内建属性冲突的字段名（如 filename、message），
    以避免 ``KeyError: Attempt to overwrite ... in LogRecord``。
    """
    extra = _base_extra()
    extra["event"] = event
    for key, value in fields.items():
        if key not in _RESERVED_LOG_ATTRS:
            extra[key] = value

    resolved_exc_info = exc_info
    if isinstance(exc_info, BaseException):
        resolved_exc_info = (type(exc_info), exc_info, exc_info.__traceback__)

    logger.log(level, event, extra=extra, exc_info=resolved_exc_info)


def _build_metrics_state(enabled: bool) -> _MetricsState:
    registry = CollectorRegistry()
    if not enabled:
        return _MetricsState(enabled=False, registry=registry)

    return _MetricsState(
        enabled=True,
        registry=registry,
        http_requests_total=Counter(
            "ragflow_lite_http_requests_total",
            "Total HTTP requests handled by ragflow-lite.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        http_request_duration_seconds=Histogram(
            "ragflow_lite_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            ("method", "route", "status_code"),
            buckets=_HISTOGRAM_BUCKETS,
            registry=registry,
        ),
        http_requests_in_progress=Gauge(
            "ragflow_lite_http_requests_in_progress",
            "HTTP requests currently in progress.",
            ("method", "route"),
            registry=registry,
        ),
        http_request_exceptions_total=Counter(
            "ragflow_lite_http_request_exceptions_total",
            "Unhandled HTTP request exceptions.",
            ("method", "route", "exception_type"),
            registry=registry,
        ),
        ingest_total=Counter(
            "ragflow_lite_ingest_total",
            "Document ingestion outcomes.",
            ("outcome", "file_type"),
            registry=registry,
        ),
        query_total=Counter(
            "ragflow_lite_query_total",
            "Query outcomes.",
            ("outcome",),
            registry=registry,
        ),
    )


def setup_metrics(enabled: bool) -> _MetricsState:
    return _build_metrics_state(enabled)


def bind_metrics_state(metrics_state: _MetricsState) -> Token[_MetricsState | None]:
    return _metrics_state_ctx.set(metrics_state)


def clear_metrics_state(token: Token[_MetricsState | None]) -> None:
    _metrics_state_ctx.reset(token)


def _current_metrics_state() -> _MetricsState | None:
    return _metrics_state_ctx.get()


def metrics_enabled() -> bool:
    metrics_state = _current_metrics_state()
    return metrics_state.enabled if metrics_state is not None else False


def render_metrics(metrics_state: _MetricsState) -> bytes:
    return generate_latest(metrics_state.registry)


def record_http_requests_in_progress(method: str, route: str, delta: int) -> None:
    metrics_state = _current_metrics_state()
    if metrics_state is None:
        return
    gauge = metrics_state.http_requests_in_progress
    if gauge is None:
        return
    labels = gauge.labels(method=method, route=route)
    if delta > 0:
        labels.inc(delta)
    elif delta < 0:
        labels.dec(abs(delta))


def record_http_request(
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    metrics_state = _current_metrics_state()
    if metrics_state is None:
        return
    counter = metrics_state.http_requests_total
    histogram = metrics_state.http_request_duration_seconds
    if counter is None or histogram is None:
        return

    status = str(status_code)
    counter.labels(method=method, route=route, status_code=status).inc()
    histogram.labels(method=method, route=route, status_code=status).observe(
        duration_seconds
    )


def record_http_request_exception(
    method: str,
    route: str,
    exception_type: str,
) -> None:
    metrics_state = _current_metrics_state()
    if metrics_state is None:
        return
    counter = metrics_state.http_request_exceptions_total
    if counter is None:
        return
    counter.labels(
        method=method,
        route=route,
        exception_type=exception_type,
    ).inc()


def record_ingest_outcome(outcome: str, file_type: str) -> None:
    metrics_state = _current_metrics_state()
    if metrics_state is None:
        return
    counter = metrics_state.ingest_total
    if counter is None:
        return
    counter.labels(outcome=outcome, file_type=file_type).inc()


def record_query_outcome(outcome: str) -> None:
    metrics_state = _current_metrics_state()
    if metrics_state is None:
        return
    counter = metrics_state.query_total
    if counter is None:
        return
    counter.labels(outcome=outcome).inc()
