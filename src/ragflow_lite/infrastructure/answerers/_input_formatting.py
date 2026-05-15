from __future__ import annotations

from typing import Any


def format_retrieval_rewrite_notice(metadata: dict[str, Any]) -> list[str]:
    """兼容旧入口；rewrite 状态只走 runtime/UI side-channel。"""
    return []
