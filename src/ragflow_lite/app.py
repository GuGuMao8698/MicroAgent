"""FastAPI 应用入口。

这里负责把配置、依赖组装和路由挂载串起来，保持启动逻辑集中，
避免把初始化细节分散到路由或业务层。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from ragflow_lite.api.deps.providers import AppServices, build_services
from ragflow_lite.api.observability import install_observability
from ragflow_lite.api.routes.agent import router as agent_router
from ragflow_lite.api.routes.v0 import router as v0_router
from ragflow_lite.config.settings import Settings
from ragflow_lite.shared.observability import (
    log_event,
    setup_logging,
)

logger = logging.getLogger(__name__)


class LazyApp:
    """ASGI wrapper that creates the FastAPI app on first use."""

    def __init__(self) -> None:
        self._app: FastAPI | None = None

    def _get_app(self) -> FastAPI:
        if self._app is None:
            self._app = create_app()
        return self._app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self._get_app()(scope, receive, send)


def _disconnect_vector_index(app: FastAPI) -> None:
    services: AppServices = app.state.services
    disconnect = getattr(services.ingestion_pipeline.vector_index, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "vector_index_disconnect_failed",
                exc_info=True,
            )


def _close_ingestion_runner(app: FastAPI) -> None:
    services: AppServices = app.state.services
    close = getattr(services.ingestion_pipeline.runner, "close", None)
    if callable(close):
        close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理，负责启动和关闭时的资源清理。"""
    yield
    _close_ingestion_runner(app)
    _disconnect_vector_index(app)


def _log_startup_failure() -> None:
    log_event(
        logger,
        logging.ERROR,
        "app_startup_failed",
        exc_info=True,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并初始化应用实例。

    如果没有显式传入配置，就使用项目默认目录。测试也通过这个入口
    注入临时目录配置，避免和真实运行数据互相污染。
    """
    resolved_settings = settings or Settings.default()
    setup_logging(
        log_level=resolved_settings.log_level,
        log_format=resolved_settings.log_format,
    )
    resolved_settings.ensure_directories()

    try:
        app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
        install_observability(app, enable_metrics=resolved_settings.metrics_enabled)
        services = build_services(resolved_settings)
        set_metrics_state = getattr(
            services.ingestion_pipeline.runner,
            "set_metrics_state",
            None,
        )
        if callable(set_metrics_state):
            set_metrics_state(app.state.metrics_state)
        app.state.services = services
        app.include_router(v0_router, prefix=resolved_settings.api_prefix)
        app.include_router(
            agent_router,
            prefix=f"{resolved_settings.api_prefix}/agent",
        )
        return app
    except Exception:
        _log_startup_failure()
        raise


app = LazyApp()
