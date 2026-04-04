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
        self._text_kwargs: dict[str, Any] | None = None
        self._dense_kwargs: dict[str, Any] | None = None
        self._fusion_kwargs: dict[str, Any] | None = None
        self._output_columns: list[str] = []
        if match_type == "text":
            self._text_kwargs = match_kwargs
        else:
            self._dense_kwargs = match_kwargs

    def match_text(self, **kwargs: Any) -> _FakeQueryBuilder:
        self._text_kwargs = kwargs
        return self

    def match_dense(self, **kwargs: Any) -> _FakeQueryBuilder:
        self._dense_kwargs = kwargs
        return self

    def fusion(self, method: str, **kwargs: Any) -> _FakeQueryBuilder:
        self._fusion_kwargs = {"method": method, **kwargs}
        return self

    def output(self, columns: list[str]) -> _FakeQueryBuilder:
        self._output_columns = columns
        return self

    def to_pl(self) -> tuple[pl.DataFrame, dict]:
        if self._fusion_kwargs is not None:
            return self._to_pl_fusion()
        if self._text_kwargs is not None:
            return self._to_pl_text(self._text_kwargs)
        if self._dense_kwargs is not None:
            return self._to_pl_dense(self._dense_kwargs)
        return pl.DataFrame(), {}

    def _to_pl_dense(self, match_kwargs: dict[str, Any]) -> tuple[pl.DataFrame, dict]:
        query_vec = match_kwargs.get("embedding_data", [])
        topn = match_kwargs.get("topn", 10)

        scored: list[dict[str, Any]] = []
        for row in self._table.rows:
            vec = row.get("vec", [])
            score = sum(a * b for a, b in zip(query_vec, vec, strict=False))
            if score > 0:
                scored.append(self._row_with_score(row, "_distance", score))

        scored.sort(key=lambda r: r["_distance"], reverse=True)
        scored = scored[:topn]

        if not scored:
            return pl.DataFrame(), {}

        return pl.DataFrame(scored), {}

    def _to_pl_text(self, match_kwargs: dict[str, Any]) -> tuple[pl.DataFrame, dict]:
        query_text = match_kwargs.get("matching_text", "")
        topn = match_kwargs.get("topn", 10)

        scored: list[dict[str, Any]] = []
        for row in self._table.rows:
            text = row.get("text", "")
            # 简单子串匹配模拟全文检索
            if query_text.lower() in text.lower():
                scored.append(self._row_with_score(row, "_score", 1.0))

        scored = scored[:topn]

        if not scored:
            return pl.DataFrame(), {}

        return pl.DataFrame(scored), {}

    def _to_pl_fusion(self) -> tuple[pl.DataFrame, dict]:
        """确定性内存融合：按 chunk_id union，text 固定分 1.0，dense 分按单调归一化后加权。"""
        topn = self._fusion_kwargs.get("topn", 10) if self._fusion_kwargs else 10
        weights_str = (
            self._fusion_kwargs.get("fusion_params", {}).get("weights", "0.5,0.5")
            if self._fusion_kwargs
            else "0.5,0.5"
        )
        text_weight, dense_weight = (float(w) for w in weights_str.split(",", 1))

        text_results = self._collect_text_hits()
        dense_results = self._collect_dense_scores()

        # dense 分数单调归一化到 [0, 1]
        max_dense = max((v[0] for v in dense_results.values()), default=0.0)
        if max_dense == 0:
            max_dense = 1.0

        fused: dict[str, tuple[float, dict[str, Any]]] = {}
        all_chunk_ids = set(text_results.keys()) | set(dense_results.keys())
        for cid in all_chunk_ids:
            t_score = text_results.get(cid, 0.0)
            d_score, row = dense_results.get(cid, (0.0, {}))
            norm_d = d_score / max_dense
            final = text_weight * t_score + dense_weight * norm_d
            fused[cid] = (
                final,
                row
                if cid in dense_results
                else next(r for r in self._table.rows if r["chunk_id"] == cid),
            )

        sorted_chunks = sorted(fused.items(), key=lambda x: x[1][0], reverse=True)[
            :topn
        ]

        if not sorted_chunks:
            return pl.DataFrame(), {}

        scored = [
            self._row_with_score(row, "_score", final_score)
            for _cid, (final_score, row) in sorted_chunks
        ]

        return pl.DataFrame(scored), {}

    def _collect_text_hits(self) -> dict[str, float]:
        """收集全文命中，返回 chunk_id -> 固定分 1.0 的映射。"""
        if not self._text_kwargs:
            return {}
        query_text = self._text_kwargs.get("matching_text", "")
        return {
            row["chunk_id"]: 1.0
            for row in self._table.rows
            if query_text.lower() in row.get("text", "").lower()
        }

    def _collect_dense_scores(self) -> dict[str, tuple[float, dict[str, Any]]]:
        """收集 dense 打分，返回 chunk_id -> (score, row) 的映射。"""
        if not self._dense_kwargs:
            return {}
        query_vec = self._dense_kwargs.get("embedding_data", [])
        return {
            row["chunk_id"]: (
                sum(a * b for a, b in zip(query_vec, row.get("vec", []), strict=False)),
                row,
            )
            for row in self._table.rows
            if sum(a * b for a, b in zip(query_vec, row.get("vec", []), strict=False))
            > 0
        }

    def _row_with_score(
        self, row: dict[str, Any], score_field: str, score: float
    ) -> dict[str, Any]:
        """从行数据中提取 output_columns 指定的字段，并附加分数字段。"""
        result: dict[str, Any] = {}
        for col in self._output_columns:
            if col == score_field:
                result[col] = score
            else:
                result[col] = row.get(col, "")
        return result


class FakeInfinityDatabase:
    def __init__(
        self,
        name: str,
        *,
        show_columns_mode: ShowColumnsMode = "dataframe",
    ) -> None:
        self.name = name
        self._tables: dict[str, FakeInfinityTable] = {}
        self._show_columns_mode: ShowColumnsMode = show_columns_mode

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
        self._show_columns_mode: ShowColumnsMode = show_columns_mode

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
