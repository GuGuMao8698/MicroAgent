from __future__ import annotations

from typing import Any

__all__ = ["app", "create_app"]


class _LazyAppExport:
    """包根 ASGI 导出保持轻量，实际应用在首次使用时加载。"""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        from ragflow_lite.app import app as real_app

        await real_app(scope, receive, send)

    def __getattr__(self, name: str) -> Any:
        from ragflow_lite.app import app as real_app

        return getattr(real_app, name)


def create_app(*args: Any, **kwargs: Any) -> Any:
    from ragflow_lite.app import create_app as real_create_app

    return real_create_app(*args, **kwargs)


app = _LazyAppExport()
