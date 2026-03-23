"""FastAPI 应用入口。

这里负责把配置、依赖组装和路由挂载串起来，保持启动逻辑集中，
避免把初始化细节分散到路由或业务层。
"""

from __future__ import annotations

from fastapi import FastAPI

from ragflow_lite.api.deps.providers import build_services
from ragflow_lite.api.routes.v0 import router as v0_router
from ragflow_lite.config.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并初始化应用实例。

    如果没有显式传入配置，就使用项目默认目录。测试也通过这个入口
    注入临时目录配置，避免和真实运行数据互相污染。
    """
    resolved_settings = settings or Settings.default()
    resolved_settings.ensure_directories()

    app = FastAPI(title=resolved_settings.app_name)
    app.state.services = build_services(resolved_settings)
    app.include_router(v0_router, prefix=resolved_settings.api_prefix)
    return app


app = create_app()
