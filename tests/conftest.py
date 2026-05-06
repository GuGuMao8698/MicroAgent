from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Literal

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
TESTS_PATH = PROJECT_ROOT / "tests"
EVALS_PATH = TESTS_PATH / "evals"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(TESTS_PATH) not in sys.path:
    sys.path.insert(0, str(TESTS_PATH))
if str(EVALS_PATH) not in sys.path:
    sys.path.insert(0, str(EVALS_PATH))

from eval_support import is_live_infinity_enabled, validate_deepeval_env

os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-api-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-api-key")
os.environ.setdefault("ARK_API_KEY", "test-ark-api-key")
os.environ.setdefault("ARK_EMBEDDING_MODEL", "ep-test-model")
for _name in (
    "RAGFLOW_LITE_LOG_LEVEL",
    "RAGFLOW_LITE_LOG_FORMAT",
    "RAGFLOW_LITE_METRICS_ENABLED",
):
    os.environ.pop(_name, None)

# ---------------------------------------------------------------------------
# 测试用假的 Infinity client（不依赖真实网络）
# ---------------------------------------------------------------------------

import re
from types import SimpleNamespace

import polars as pl

ShowColumnsMode = Literal["dataframe", "tuple"]


def _parse_doc_id_from_filter(cond: str) -> str | None:
    """从 SQL 风格 filter 字符串中提取并反转义 document_id。

    支持单引号转义：``''`` 还原为 ``'``。
    """
    m = re.search(r"document_id\s*=\s*'([^']*(?:''[^']*)*)'", cond)
    if m is None:
        return None
    return m.group(1).replace("''", "'")


def _parse_fields_boost(fields_str: str) -> list[tuple[str, float]]:
    """解析 Infinity match_text 的 fields 字符串，返回 (field, boost) 列表。

    格式示例：``"filename^3,text"`` → ``[("filename", 3.0), ("text", 1.0)]``。
    """
    result: list[tuple[str, float]] = []
    for part in fields_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "^" in part:
            name, boost = part.split("^", 1)
            result.append((name.strip(), float(boost)))
        else:
            result.append((part, 1.0))
    return result


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
        # 最近一次 hybrid 查询各分支的 topn，供单测断言。
        self.last_hybrid_text_topn: int | None = None
        self.last_hybrid_dense_topn: int | None = None
        self.last_hybrid_fusion_topn: int | None = None
        self.last_hybrid_text_fields: str | None = None
        self.last_hybrid_text_kwargs: dict[str, Any] | None = None
        self.last_hybrid_dense_kwargs: dict[str, Any] | None = None
        self.last_fusion_kwargs: dict[str, Any] | None = None

    def insert(self, data: list[dict[str, Any]]) -> None:
        self.rows.extend(data)

    def delete(self, cond: str | None = None) -> None:
        if cond is None:
            self.rows.clear()
            return
        doc_id = _parse_doc_id_from_filter(cond)
        if doc_id is not None:
            self.rows = [r for r in self.rows if r.get("document_id") != doc_id]
            return
        # 支持 dataset_id = '...' 过滤
        ds_match = re.search(r"dataset_id\s*=\s*'([^']*(?:''[^']*)*)'", cond)
        if ds_match is not None:
            ds_id = ds_match.group(1).replace("''", "'")
            self.rows = [r for r in self.rows if r.get("dataset_id") != ds_id]

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

    def output(self, columns: list[str]) -> _FakeQueryBuilder:
        return _FakeQueryBuilder(self, "scan", {"output_columns": columns})

    def create_index(
        self,
        index_name: str,
        index_info: Any,
        conflict_type: Any = None,
        index_comment: str = "",
    ) -> None:
        self._indexes[index_name] = {
            "type": getattr(index_info, "index_type", index_info),
            "columns": getattr(index_info, "target_name", None),
            "conflict_type": conflict_type,
            "comment": index_comment,
        }

    def list_indexes(self) -> Any:
        return SimpleNamespace(
            error_code=0,
            error_msg="",
            index_names=list(self._indexes.keys()),
        )

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
        self._text_kwargs: dict[str, Any] | None = None
        self._dense_kwargs: dict[str, Any] | None = None
        self._fusion_kwargs: dict[str, Any] | None = None
        self._output_columns: list[str] = []
        self._filter_cond: str | None = None
        self._sort_spec: list[list[Any]] | None = None
        if match_type == "text":
            self._text_kwargs = match_kwargs
        elif match_type == "dense":
            self._dense_kwargs = match_kwargs
        elif match_type == "scan":
            self._output_columns = match_kwargs.get("output_columns", [])

    def match_text(self, **kwargs: Any) -> _FakeQueryBuilder:
        self._text_kwargs = kwargs
        return self

    def match_dense(self, **kwargs: Any) -> _FakeQueryBuilder:
        self._dense_kwargs = kwargs
        return self

    def fusion(
        self,
        method: str,
        topn: int,
        fusion_params: dict[str, Any] | None = None,
    ) -> _FakeQueryBuilder:
        self._fusion_kwargs = {"method": method, "topn": topn}
        if fusion_params is not None:
            self._fusion_kwargs["fusion_params"] = fusion_params
        return self

    def output(self, columns: list[str]) -> _FakeQueryBuilder:
        self._output_columns = columns
        return self

    def filter(self, cond: str) -> _FakeQueryBuilder:
        self._filter_cond = cond
        return self

    def sort(self, spec: list[list[Any]]) -> _FakeQueryBuilder:
        self._sort_spec = spec
        return self

    def to_pl(self) -> tuple[pl.DataFrame, dict]:
        if self._fusion_kwargs is not None:
            return self._to_pl_fusion()
        if self._match_type == "scan":
            return self._to_pl_scan()
        if self._text_kwargs is not None:
            return self._to_pl_text(self._text_kwargs)
        if self._dense_kwargs is not None:
            return self._to_pl_dense(self._dense_kwargs)
        return pl.DataFrame(), {}

    def _rank_text_hits(
        self,
        *,
        matching_text: str,
        fields: str = "text",
        topn: int | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        """按字段 boost 对全文命中做确定性排序。"""
        field_boosts = _parse_fields_boost(fields)
        ranked: list[tuple[dict[str, Any], float]] = []
        for row in self._table.rows:
            score = 0.0
            for field, boost in field_boosts:
                if matching_text.lower() in row.get(field, "").lower():
                    score += boost
            if score > 0:
                ranked.append((row, score))

        ranked.sort(key=lambda item: item[1], reverse=True)
        if topn is not None:
            ranked = ranked[:topn]
        return ranked

    def _rank_dense_hits(
        self,
        *,
        query_vec: list[float],
        topn: int | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        """按内积得分对 dense 命中做确定性排序。"""
        ranked: list[tuple[dict[str, Any], float]] = []
        for row in self._table.rows:
            score = sum(
                a * b for a, b in zip(query_vec, row.get("vec", []), strict=False)
            )
            if score > 0:
                ranked.append((row, score))

        ranked.sort(key=lambda item: item[1], reverse=True)
        if topn is not None:
            ranked = ranked[:topn]
        return ranked

    def _to_pl_dense(self, match_kwargs: dict[str, Any]) -> tuple[pl.DataFrame, dict]:
        query_vec = match_kwargs.get("embedding_data", [])
        topn = match_kwargs.get("topn", 10)
        scored = [
            self._row_with_score(row, "_distance", score)
            for row, score in self._rank_dense_hits(query_vec=query_vec, topn=topn)
        ]

        if not scored:
            return pl.DataFrame(), {}

        return pl.DataFrame(scored), {}

    def _to_pl_scan(self) -> tuple[pl.DataFrame, dict]:
        """表扫描模式：支持 filter、sort，按 output_columns 提取字段。"""
        rows = list(self._table.rows)

        if self._filter_cond is not None:
            doc_id = _parse_doc_id_from_filter(self._filter_cond)
            if doc_id is not None:
                rows = [r for r in rows if r.get("document_id") == doc_id]

        if self._sort_spec is not None:
            for col, direction in self._sort_spec:
                # 对 _row_id 用插入顺序反转为倒序
                if col == "_row_id" and direction == SortType.Desc:
                    rows = list(reversed(rows))

        if not rows:
            return pl.DataFrame(
                schema={col: pl.Utf8 for col in self._output_columns}
            ), {}

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append({col: row.get(col, "") for col in self._output_columns})

        return pl.DataFrame(result), {}

    def _to_pl_text(self, match_kwargs: dict[str, Any]) -> tuple[pl.DataFrame, dict]:
        query_text = match_kwargs.get("matching_text", "")
        topn = match_kwargs.get("topn", 10)
        fields = match_kwargs.get("fields", "text")
        scored = [
            self._row_with_score(row, "_score", score)
            for row, score in self._rank_text_hits(
                matching_text=query_text,
                fields=fields,
                topn=topn,
            )
        ]

        if not scored:
            return pl.DataFrame(), {}

        return pl.DataFrame(scored), {}

    def _to_pl_fusion(self) -> tuple[pl.DataFrame, dict]:
        """确定性内存融合：按 chunk_id union，text/dense 分经排序后融合。"""
        topn = self._fusion_kwargs.get("topn", 10) if self._fusion_kwargs else 10
        weights_str = (
            self._fusion_kwargs.get("fusion_params", {}).get("weights", "0.5,0.5")
            if self._fusion_kwargs
            else "0.5,0.5"
        )
        text_weight, dense_weight = (float(w) for w in weights_str.split(",", 1))

        # 记录各分支 topn 供单测断言。
        self._table.last_hybrid_text_topn = (
            self._text_kwargs.get("topn") if self._text_kwargs else None
        )
        self._table.last_hybrid_dense_topn = (
            self._dense_kwargs.get("topn") if self._dense_kwargs else None
        )
        self._table.last_hybrid_fusion_topn = topn
        self._table.last_hybrid_text_fields = (
            self._text_kwargs.get("fields") if self._text_kwargs else None
        )
        self._table.last_hybrid_text_kwargs = (
            dict(self._text_kwargs) if self._text_kwargs else None
        )
        self._table.last_hybrid_dense_kwargs = (
            dict(self._dense_kwargs) if self._dense_kwargs else None
        )
        self._table.last_fusion_kwargs = (
            dict(self._fusion_kwargs) if self._fusion_kwargs else None
        )

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
        """收集全文命中，支持多字段 boost 加权，返回 chunk_id -> 加权分映射，按 topn 截断。"""
        if not self._text_kwargs:
            return {}
        query_text = self._text_kwargs.get("matching_text", "")
        topn = self._text_kwargs.get("topn")
        fields = self._text_kwargs.get("fields", "text")
        return {
            row["chunk_id"]: score
            for row, score in self._rank_text_hits(
                matching_text=query_text,
                fields=fields,
                topn=topn,
            )
        }

    def _collect_dense_scores(self) -> dict[str, tuple[float, dict[str, Any]]]:
        """收集 dense 打分，返回 chunk_id -> (score, row) 的映射，按 score 降序截断到 topn。"""
        if not self._dense_kwargs:
            return {}
        query_vec = self._dense_kwargs.get("embedding_data", [])
        topn = self._dense_kwargs.get("topn")
        return {
            row["chunk_id"]: (score, row)
            for row, score in self._rank_dense_hits(query_vec=query_vec, topn=topn)
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
from infinity.common import SortType  # noqa: E402

_REAL_INFINITY_CONNECT = infinity.connect
infinity.connect = _fake_connect  # type: ignore[assignment]

from ragflow_lite.app import create_app  # noqa: E402
from ragflow_lite.config import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# pytest 固定夹具
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-infinity",
        action="store_true",
        default=False,
        help="run tests that connect to a real Infinity instance",
    )
    parser.addoption(
        "--run-deepeval",
        action="store_true",
        default=False,
        help="run optional deepeval-backed evaluation tests",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_infinity: connect to a real Infinity instance instead of the fake client",
    )
    config.addinivalue_line(
        "markers",
        "deepeval: run optional deepeval-based RAG evaluation",
    )

    if config.getoption("--run-deepeval"):
        import importlib.util

        if importlib.util.find_spec("deepeval") is None:
            raise pytest.UsageError(
                "--run-deepeval requires the 'deepeval' package. "
                "Install it with: pip install deepeval"
            )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    skip_live_infinity = pytest.mark.skip(
        reason="need --run-live-infinity to run tests against real Infinity"
    )
    skip_deepeval = pytest.mark.skip(
        reason="need --run-deepeval to run deepeval-based evaluation tests"
    )
    run_deepeval = config.getoption("--run-deepeval")
    run_live_infinity = config.getoption("--run-live-infinity") or run_deepeval

    for item in items:
        if item.get_closest_marker("deepeval") is not None and not run_deepeval:
            item.add_marker(skip_deepeval)

        if (
            item.get_closest_marker("live_infinity") is not None
            and not run_live_infinity
        ):
            item.add_marker(skip_live_infinity)


@pytest.fixture(autouse=True)
def _patch_infinity_connect(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认保持 fake Infinity；live tests 显式切回真实连接。"""
    import infinity as _inf

    use_live_infinity = is_live_infinity_enabled(
        {marker.name for marker in request.node.iter_markers()},
        run_live_infinity=request.config.getoption("--run-live-infinity"),
    )
    connect_impl = _REAL_INFINITY_CONNECT if use_live_infinity else _fake_connect
    monkeypatch.setattr(_inf, "connect", connect_impl)


@pytest.fixture(autouse=True)
def _require_deepeval_runtime_env(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("deepeval") is None:
        return
    if not request.config.getoption("--run-deepeval"):
        return
    validate_deepeval_env(os.environ)


@pytest.fixture(autouse=True)
def _set_deepeval_plain_prompt_variant(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让 deepeval 测试使用 plain 模板（无 citation），避免引用噪声干扰评估指标。"""
    if request.node.get_closest_marker("deepeval") is None:
        return
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")


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


def _build_test_scope_suffix(tmp_path: Path) -> str:
    base_name = tmp_path.name.replace("-", "_")
    path_hash = hashlib.sha1(str(tmp_path).encode("utf-8")).hexdigest()[:10]
    return f"{base_name}_{path_hash}"


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    scope_suffix = _build_test_scope_suffix(tmp_path)
    settings.infinity_document_table = f"documents_{scope_suffix}"
    settings.infinity_chunk_table = f"chunks_{scope_suffix}"
    settings.ensure_directories()
    return settings


class _FakeDeepSeekJsonClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    def complete_json(self, *args, **kwargs):
        return self.output_text


def _install_fake_query_support_clients(app) -> None:
    """Replace query-time DeepSeek JSON clients with deterministic fakes."""
    services = app.state.services

    extractor = getattr(services.ingestion_pipeline, "evidence_extractor", None)
    if extractor is not None:
        extractor.client = _FakeDeepSeekJsonClient('{"entities":[],"relations":[]}')

    query_grounder = getattr(services.retriever, "query_grounder", None)
    if query_grounder is not None:
        query_grounder.client = _FakeDeepSeekJsonClient(
            '{"answer_type_keywords":[],"entities_from_query":[]}'
        )


@pytest.fixture
def app(app_settings: Settings):
    return create_app(app_settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    # Install fake DeepSeek JSON clients so integration tests only exercise
    # the intended storage/retrieval layer unless they opt into model calls.
    _install_fake_query_support_clients(app)

    with TestClient(app) as test_client:
        yield test_client
