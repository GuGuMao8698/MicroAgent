"""轻量可观测性模块。

提供一次性 logging 初始化、request-scoped request_id
和结构化日志 helper。不引入外部日志库。
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

_INIT_DONE = False

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


def setup_logging() -> None:
    """初始化根 logger，默认 INFO 级别。幂等，多次调用无副作用。"""
    global _INIT_DONE  # noqa: PLW0603
    if _INIT_DONE:
        return
    _INIT_DONE = True
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def new_request_id() -> str:
    """生成一个内部 request_id 并存入 context var。"""
    rid = uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    return rid


def _current_request_id() -> str:
    return request_id_ctx.get("")


def _base_extra() -> dict[str, Any]:
    rid = _current_request_id()
    return {"request_id": rid} if rid else {}


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """记录一条结构化日志事件，字段扁平写入 extra。

    自动跳过与 LogRecord 内建属性冲突的字段名（如 filename、message），
    以避免 ``KeyError: Attempt to overwrite ... in LogRecord``。
    """
    extra = _base_extra()
    extra["event"] = event
    for k, v in fields.items():
        if k not in _RESERVED_LOG_ATTRS:
            extra[k] = v
    logger.log(level, event, extra=extra)
