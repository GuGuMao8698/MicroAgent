"""Test QueryRequest schema 的 top_n 字段、top_k 别名和路由层传参行为。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ragflow_lite.api.deps.providers import get_query_router
from ragflow_lite.api.schemas.v0 import QueryRequest

# ---------------------------------------------------------------------------
# QueryRequest schema 单元测试
# ---------------------------------------------------------------------------


class TestQueryRequestTopN:
    """验证 top_n 字段的默认值、约束和 top_k 别名行为。"""

    def test_default_top_n_is_6(self) -> None:
        """未传 top_n 和 top_k 时，默认值为 6。"""
        req = QueryRequest(query="test")
        assert req.top_n == 6
        assert req.top_k is None

    def test_explicit_top_n(self) -> None:
        """显式传入 top_n 时直接使用。"""
        req = QueryRequest(query="test", top_n=3)
        assert req.top_n == 3
        assert req.top_k is None

    def test_top_k_alias_sets_top_n(self) -> None:
        """只传 top_k 时，top_n 取 top_k 的值（别名行为）。"""
        req = QueryRequest(query="test", top_k=5)
        assert req.top_n == 5

    def test_top_n_and_top_k_same_value(self) -> None:
        """top_n 和 top_k 同时传入且值相同时，正常通过。"""
        req = QueryRequest(query="test", top_n=4, top_k=4)
        assert req.top_n == 4

    def test_conflicting_top_n_and_top_k_raises(self) -> None:
        """top_n 和 top_k 同时传入且值不同时，校验失败。"""
        with pytest.raises(ValueError, match="top_n and top_k must match"):
            QueryRequest(query="test", top_n=3, top_k=7)

    def test_top_k_overrides_default_top_n(self) -> None:
        """top_k 传入时覆盖默认 top_n=6。"""
        req = QueryRequest(query="test", top_k=8)
        assert req.top_n == 8

    def test_top_n_below_minimum_raises(self) -> None:
        """top_n < 2 时校验失败。"""
        with pytest.raises(ValueError):
            QueryRequest(query="test", top_n=1)

    def test_top_k_below_minimum_raises(self) -> None:
        """top_k < 2 时校验失败。"""
        with pytest.raises(ValueError):
            QueryRequest(query="test", top_k=1)

    def test_top_n_above_maximum_raises(self) -> None:
        """top_n > 8 时校验失败。"""
        with pytest.raises(ValueError):
            QueryRequest(query="test", top_n=9)

    def test_top_k_above_maximum_raises(self) -> None:
        """top_k > 8 时校验失败。"""
        with pytest.raises(ValueError):
            QueryRequest(query="test", top_k=9)

    def test_answer_top_n_property_returns_top_n(self) -> None:
        """answer_top_n 属性返回 top_n 的值。"""
        req = QueryRequest(query="test", top_n=5)
        assert req.answer_top_n == 5

    def test_explicit_default_top_n_conflicts_with_different_top_k(self) -> None:
        """显式 top_n=6 和不同 top_k 同传时也应视为冲突。"""
        with pytest.raises(ValueError, match="top_n and top_k must match"):
            QueryRequest(query="test", top_n=6, top_k=3)

    def test_top_k_is_excluded_from_serialization(self) -> None:
        """top_k 字段不序列化输出。"""
        req = QueryRequest(query="test", top_k=3)
        data = req.model_dump()
        assert "top_k" not in data
        assert data["top_n"] == 3


# ---------------------------------------------------------------------------
# 路由集成测试：验证 /queries 端点正确传参
# ---------------------------------------------------------------------------


class TestQueryRouteTopN:
    """验证 /queries 路由将 top_n 正确传递给 QueryModeRouter。"""

    def test_route_passes_top_n_to_router(self, client: TestClient, app) -> None:
        """POST /queries 使用 top_n 时，路由层将其传给 QueryModeRouter.query。"""
        mock_router = MagicMock()
        mock_router.query.return_value = MagicMock(
            answer="test answer",
            contexts=[],
            metadata={},
        )
        app.dependency_overrides[get_query_router] = lambda: mock_router
        try:
            response = client.post(
                "/api/v0/queries",
                json={"query": "test query", "top_n": 5},
            )
            assert response.status_code == 200
            # 路由层用 answer_top_n 的值传给 router.query 的 top_k 参数
            mock_router.query.assert_called_once_with("test query", 5, mode="standard")
        finally:
            app.dependency_overrides.pop(get_query_router, None)

    def test_route_passes_top_k_alias_to_router(self, client: TestClient, app) -> None:
        """POST /queries 使用 top_k 别名时，路由层正确传递。"""
        mock_router = MagicMock()
        mock_router.query.return_value = MagicMock(
            answer="test answer",
            contexts=[],
            metadata={},
        )
        app.dependency_overrides[get_query_router] = lambda: mock_router
        try:
            response = client.post(
                "/api/v0/queries",
                json={"query": "test query", "top_k": 3},
            )
            assert response.status_code == 200
            mock_router.query.assert_called_once_with("test query", 3, mode="standard")
        finally:
            app.dependency_overrides.pop(get_query_router, None)

    def test_route_uses_default_top_n_when_not_provided(
        self, client: TestClient, app
    ) -> None:
        """POST /queries 不传 top_n/top_k 时使用默认值 6。"""
        mock_router = MagicMock()
        mock_router.query.return_value = MagicMock(
            answer="test answer",
            contexts=[],
            metadata={},
        )
        app.dependency_overrides[get_query_router] = lambda: mock_router
        try:
            response = client.post(
                "/api/v0/queries",
                json={"query": "test query"},
            )
            assert response.status_code == 200
            mock_router.query.assert_called_once_with("test query", 6, mode="standard")
        finally:
            app.dependency_overrides.pop(get_query_router, None)
