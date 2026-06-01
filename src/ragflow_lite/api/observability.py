from __future__ import annotations

import logging
import time

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.routing import Match

from ragflow_lite.shared.observability import (
    bind_metrics_state,
    bind_request_context,
    clear_metrics_state,
    clear_request_context,
    current_trace_id,
    log_event,
    metrics_enabled,
    record_http_request,
    record_http_request_exception,
    record_http_requests_in_progress,
    render_metrics,
    setup_metrics,
)

TRACE_HEADER_NAME = "X-Trace-Id"
_UNMATCHED_ROUTE_LABEL = "unmatched"

logger = logging.getLogger(__name__)

metrics_router = APIRouter(include_in_schema=False)


def _request_fields(request: Request) -> dict[str, str | int]:
    return {
        "method": request.method,
        "path": request.url.path,
        "status_code": 500,
    }


def resolve_route_label(request: Request) -> str:
    partial_match_path: str | None = None

    for route in request.app.router.routes:
        match, _scope = route.matches(request.scope)
        path = getattr(route, "path", None)
        if not isinstance(path, str) or not path:
            continue
        if match is Match.FULL:
            return path
        if match is Match.PARTIAL and partial_match_path is None:
            partial_match_path = path

    return partial_match_path or _UNMATCHED_ROUTE_LABEL


async def observability_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    context = bind_request_context(request.headers.get(TRACE_HEADER_NAME))
    metrics_token = bind_metrics_state(request.app.state.metrics_state)
    request.state.request_id = context.request_id
    request.state.trace_id = context.trace_id
    request.state.route_label = resolve_route_label(request)

    track_http_metrics = metrics_enabled() and request.state.route_label != "/metrics"
    started_at = time.perf_counter()
    request.state.request_started_at = started_at
    if track_http_metrics:
        record_http_requests_in_progress(
            method=request.method,
            route=request.state.route_label,
            delta=1,
        )

    response: Response | None = None
    try:
        response = await call_next(request)
        response.headers[TRACE_HEADER_NAME] = context.trace_id
        if track_http_metrics:
            record_http_request(
                method=request.method,
                route=request.state.route_label,
                status_code=response.status_code,
                duration_seconds=time.perf_counter() - started_at,
            )
        return response
    finally:
        if track_http_metrics:
            record_http_requests_in_progress(
                method=request.method,
                route=request.state.route_label,
                delta=-1,
            )
        clear_metrics_state(metrics_token)
        clear_request_context()


async def request_unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> PlainTextResponse:
    route_label = getattr(request.state, "route_label", resolve_route_label(request))
    error_type = type(exc).__name__
    trace_id = getattr(request.state, "trace_id", "") or current_trace_id()
    request_id = getattr(request.state, "request_id", "")
    metrics_token = bind_metrics_state(request.app.state.metrics_state)
    log_event(
        logger,
        logging.ERROR,
        "request_unhandled_exception",
        exc_info=exc,
        trace_id=trace_id,
        request_id=request_id,
        **_request_fields(request),
        error_type=error_type,
    )
    try:
        if metrics_enabled() and route_label != "/metrics":
            record_http_request_exception(
                method=request.method,
                route=route_label,
                exception_type=error_type,
            )
            started_at = getattr(request.state, "request_started_at", None)
            if isinstance(started_at, float):
                record_http_request(
                    method=request.method,
                    route=route_label,
                    status_code=500,
                    duration_seconds=time.perf_counter() - started_at,
                )
    finally:
        clear_metrics_state(metrics_token)

    return PlainTextResponse(
        "Internal Server Error",
        status_code=500,
        headers={TRACE_HEADER_NAME: trace_id},
    )


@metrics_router.get("/metrics")
async def metrics(request: Request) -> Response:
    return Response(
        content=render_metrics(request.app.state.metrics_state),
        media_type=CONTENT_TYPE_LATEST,
    )


def install_observability(app: FastAPI, *, enable_metrics: bool) -> None:
    app.state.metrics_state = setup_metrics(enable_metrics)
    app.middleware("http")(observability_middleware)
    app.add_exception_handler(Exception, request_unhandled_exception_handler)
    if enable_metrics:
        app.include_router(metrics_router)
