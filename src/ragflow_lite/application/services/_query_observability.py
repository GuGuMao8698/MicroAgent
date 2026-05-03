from __future__ import annotations

import logging

from ragflow_lite.shared.observability import log_event


def log_query_event(
    logger: logging.Logger,
    level: int,
    event: str,
    query: str,
    top_k: int,
    **fields: object,
) -> None:
    log_event(
        logger,
        level,
        event,
        top_k=top_k,
        query_length=len(query),
        **fields,
    )
