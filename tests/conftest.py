from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

os.environ.setdefault("OPENAI_API_KEY", "test-openai-api-key")
os.environ.setdefault("ARK_API_KEY", "test-ark-api-key")
os.environ.setdefault("ARK_EMBEDDING_MODEL", "ep-test-model")

# ---------------------------------------------------------------------------
# 测试用假的 Infinity client（不依赖真实网络）
# ---------------------------------------------------------------------------

import polars as pl

ShowColumnsMode = Literal["dataframe", "tuple"]


class FakeInfinityTable:
    """用于测试的内存表，模拟 Infinity 的 `RemoteTable`。"""

    def __init__(
        self,
        name: str,
        columns: dict[str, Any] | None = None,
        *,
        show_columns_mode: ShowColumnsMode = "dataframe",
    ) -> None:
        self.name = name
        self.columns = columns or {}
        self.rows: list[dict[str, Any]] = []
        self._indexes: dict[str, dict[str, Any]] = {}
        self._show_columns_mode = show_columns_mode

    def insert(self, data: list[dict[str, Any]]) -> None:
        self.rows.extend(data)

    def delete(self, cond: str | None = None) -> None:
        if cond is None:
            self.rows.clear()
            return
        if "document_id" in cond:
            doc_id = cond.split("=")[1].strip().strip("'\"")
            self.rows = [r for r in self.rows if r.get("document_id") != doc_id]

    def show_columns(self) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]:
        names = []
        types = []
        for col_name, col_def in self.columns.items():
            names.append(col_name)
            col_type = col_def.get("type", "varchar")
            types.append(col_type)
        df = pl.DataFrame({"column_name": names, "column_type": types})
        if self._show_columns_mode == "tuple":
            return df, {}
        return df

    def match_dense(self, **kwargs: Any) -> _FakeQueryBuilder:
        return _FakeQueryBuilder(self, "dense", kwargs)

    def match_text(self, **kwargs: Any) -> _FakeQueryBuilder:
        return _FakeQueryBuilder(self, "text", kwargs)

    def create_index(
        self,
        index_name: str,
        index_type: Any,
        columns: Any,
    ) -> None:
        self._indexes[index_name] = {"type": index_type, "columns": columns}

    def show_blocks(self) -> list:
        return []


class _FakeQueryBuilder:
    def __init__(
        self,
        table: FakeInfinityTable,
        match_type: str,
        match_kwargs: dict[str, Any],
    ) -> None:
        self._table = table
        self._match_type = match_type
        self._match_kwargs = match_kwargs
        self._output_columns: list[str] = []

    def output(self, columns: list[str]) -> _FakeQueryBuilder:
        self._output_columns = columns
        return self

    def to_pl(self) -> tuple[pl.DataFrame, dict]:
        if self._match_type == "text":
            return self._to_pl_text()
        return self._to_pl_dense()

    def _to_pl_dense(self) -> tuple[pl.DataFrame, dict]:
        query_vec = self._match_kwargs.get("embedding_data", [])
        topn = self._match_kwargs.get("topn", 10)

        scored: list[dict[str, Any]] = []
        for row in self._table.rows:
            vec = row.get("vec", [])
            score = sum(a * b for a, b in zip(query_vec, vec, strict=False))
            if score > 0:
                result = {}
                for col in self._output_columns:
                    if col == "_distance":
                        result[col] = score
                    else:
                        result[col] = row.get(col, "")
                scored.append(result)

        scored.sort(key=lambda r: r["_distance"], reverse=True)
        scored = scored[:topn]

        if not scored:
            return pl.DataFrame(), {}

        return pl.DataFrame(scored), {}

    def _to_pl_text(self) -> tuple[pl.DataFrame, dict]:
        query_text = self._match_kwargs.get("matching_text", "")
        topn = self._match_kwargs.get("topn", 10)

        scored: list[dict[str, Any]] = []
        for row in self._table.rows:
            text = row.get("text", "")
            # 简单子串匹配模拟全文检索
            if query_text.lower() in text.lower():
                result = {}
                for col in self._output_columns:
                    if col == "_score":
                        result[col] = 1.0
                    else:
                        result[col] = row.get(col, "")
                scored.append(result)

        scored = scored[:topn]

        if not scored:
            return pl.DataFrame(), {}

        return pl.DataFrame(scored), {}


class FakeInfinityDatabase:
    def __init__(
        self,
        name: str,
        *,
        show_columns_mode: ShowColumnsMode = "dataframe",
    ) -> None:
        self.name = name
        self._tables: dict[str, FakeInfinityTable] = {}
        self._show_columns_mode = show_columns_mode

    def get_table(self, table_name: str) -> FakeInfinityTable:
        if table_name not in self._tables:
            raise RuntimeError(f"Table '{table_name}' does not exist")
        return self._tables[table_name]

    def create_table(
        self,
        table_name: str,
        columns: dict[str, Any],
        conflict_type: Any = None,
    ) -> None:
        if table_name not in self._tables:
            self._tables[table_name] = FakeInfinityTable(
                table_name,
                columns,
                show_columns_mode=self._show_columns_mode,
            )


class FakeInfinityClient:
    def __init__(self, *, show_columns_mode: ShowColumnsMode = "dataframe") -> None:
        self._databases: dict[str, FakeInfinityDatabase] = {}
        self.disconnected = False
        self._show_columns_mode = show_columns_mode

    def get_database(self, db_name: str) -> FakeInfinityDatabase:
        if db_name not in self._databases:
            self._databases[db_name] = FakeInfinityDatabase(
                db_name,
                show_columns_mode=self._show_columns_mode,
            )
        return self._databases[db_name]

    def disconnect(self) -> None:
        self.disconnected = True


def _fake_connect(*args: Any, **kwargs: Any) -> FakeInfinityClient:
    return FakeInfinityClient()


# 这里必须在导入 ragflow_lite 模块前 patch `infinity.connect`，
# 因为 `ragflow_lite/__init__.py` 会在模块级触发 `create_app()`，
# 并在导入阶段直接调用 `infinity.connect()`。
import infinity

infinity.connect = _fake_connect  # type: ignore[assignment]

from ragflow_lite.app import create_app  # noqa: E402
from ragflow_lite.config import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# pytest 固定夹具
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_infinity_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保每个测试用例里 `infinity.connect` 都保持为假的实现。"""
    import infinity as _inf

    monkeypatch.setattr(_inf, "connect", _fake_connect)


@pytest.fixture
def fake_infinity_client_factory():
    """按需创建假的 Infinity client，供单测覆盖不同返回形态。"""

    def factory(
        *,
        show_columns_mode: ShowColumnsMode = "dataframe",
    ) -> FakeInfinityClient:
        return FakeInfinityClient(show_columns_mode=show_columns_mode)

    return factory


@pytest.fixture
def fixture_documents_dir() -> Path:
    return PROJECT_ROOT / "tests" / "fixtures" / "documents"


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    settings.ensure_directories()
    return settings


@pytest.fixture
def app(app_settings: Settings):
    return create_app(app_settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
