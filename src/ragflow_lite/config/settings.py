"""项目运行时配置。

当前版本只保留最小闭环所需的本地目录和基础参数，避免过早引入
环境变量框架或更复杂的配置层。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ragflow_lite.shared.observability import normalize_log_format


def _read_optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def _read_string_env(name: str, default: str) -> str:
    value = _read_optional_env(name)
    if value is None:
        return default
    return value


def _read_int_env(name: str, default: int) -> int:
    value = _read_optional_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got '{value}'.") from exc


def _read_float_env(name: str, default: float) -> float:
    value = _read_optional_env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a float, got '{value}'.") from exc


def _read_bool_env(name: str, default: bool) -> bool:
    value = _read_optional_env(name)
    if value is None:
        return default

    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be a boolean string such as true/false, got '{value}'."
    )


@dataclass(frozen=True, slots=True)
class ArkEmbeddingRuntimeConfig:
    """Ark embedding runtime configuration validated at startup."""

    api_key: str
    model: str
    dimensions: int | None


@dataclass(frozen=True, slots=True)
class DeepSeekRuntimeConfig:
    """DeepSeek non-embedding runtime configuration validated at startup."""

    api_key: str
    base_url: str
    model: str
    reasoning_effort: str
    prompt_path: str | None
    render_citations: bool


@dataclass(frozen=True, slots=True)
class DiscoRAGStructurerRuntimeConfig:
    """DiscoRAG structurer LLM runtime configuration validated at startup.

    The structurer model is used for RST extraction and inter-chunk graph
    construction.  It is decoupled from the final answer model so that a
    smaller / cheaper model can be swapped in via configuration alone.
    """

    api_key: str
    base_url: str
    model: str
    reasoning_effort: str
    timeout_seconds: float = 90.0
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("discorag_structurer_timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("discorag_structurer_max_attempts must be at least 1")


@dataclass(slots=True)
class Settings:
    """承载应用启动时需要的最小配置集合。"""

    project_root: Path
    uploads_dir: Path
    local_index_dir: Path
    temp_dir: Path
    chunk_size: int = 500
    chunk_overlap: int = 50
    app_name: str = "ragflow-lite"
    api_prefix: str = "/api/v0"
    log_level: str = field(
        default_factory=lambda: _read_string_env("RAGFLOW_LITE_LOG_LEVEL", "INFO")
    )
    log_format: str = field(
        default_factory=lambda: _read_string_env("RAGFLOW_LITE_LOG_FORMAT", "text")
    )
    metrics_enabled: bool = field(
        default_factory=lambda: _read_bool_env("RAGFLOW_LITE_METRICS_ENABLED", False)
    )
    deepseek_api_key: str | None = field(
        default_factory=lambda: _read_optional_env("DEEPSEEK_API_KEY")
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_reasoning_effort: str = "high"
    # ── DiscoRAG structurer LLM 配置 ──
    discorag_structurer_api_key: str | None = field(
        default_factory=lambda: _read_optional_env("DISCORAG_STRUCTURER_API_KEY")
    )
    discorag_structurer_base_url: str = "https://api.deepseek.com"
    discorag_structurer_model: str = "deepseek-v4-flash"
    discorag_structurer_reasoning_effort: str = "high"
    discorag_structurer_timeout_seconds: float = field(
        default_factory=lambda: _read_float_env(
            "DISCORAG_STRUCTURER_TIMEOUT_SECONDS", 90.0
        )
    )
    discorag_structurer_max_attempts: int = field(
        default_factory=lambda: _read_int_env("DISCORAG_STRUCTURER_MAX_ATTEMPTS", 2)
    )
    answer_prompt_path: str | None = field(
        default_factory=lambda: (
            _read_optional_env("RAGFLOW_LITE_ANSWER_PROMPT_PATH")
            or _read_optional_env("RAGFLOW_LITE_OPENAI_ANSWER_PROMPT_PATH")
        )
    )
    openai_render_citations: bool = field(
        default_factory=lambda: _read_bool_env(
            "RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", True
        )
    )
    ark_api_key: str | None = field(
        default_factory=lambda: _read_optional_env("ARK_API_KEY")
    )
    ark_embedding_model: str | None = field(
        default_factory=lambda: _read_optional_env("ARK_EMBEDDING_MODEL")
    )
    ark_embedding_dimensions: int = 2048
    infinity_host: str = field(
        default_factory=lambda: _read_string_env(
            "RAGFLOW_LITE_INFINITY_HOST",
            "127.0.0.1",
        )
    )
    infinity_port: int = field(
        default_factory=lambda: _read_int_env("RAGFLOW_LITE_INFINITY_PORT", 23817)
    )
    infinity_database: str = "default_db"
    infinity_document_table: str = "documents"
    infinity_chunk_table: str = "chunks"
    # ── 图候选 Infinity 检索参数 ──
    mini_internal_candidate_n: int = 60
    query_entity_limit: int = 5
    graph_initial_recall_n: int = 1024
    graph_candidate_text_weight: float = 0.05
    graph_candidate_dense_weight: float = 0.95
    graph_candidate_minimum_should_match: float = 0.3
    graph_candidate_dense_similarity_threshold: float = 0.2
    graph_candidate_fusion_normalize: str = "atan"
    infinity_graph_entity_table: str = "graph_entities"
    infinity_graph_relationship_table: str = "graph_relationships"
    # ── chunk Infinity hybrid 检索参数 ──
    chunk_initial_recall_n: int = 1024
    chunk_text_weight: float = 0.05
    chunk_dense_weight: float = 0.95
    chunk_minimum_should_match: float = 0.3
    chunk_dense_similarity_threshold: float = 0.2
    chunk_fusion_normalize: str = "atan"
    chunk_position_prior_weight: float = 0.03
    chunk_position_prior_enabled: bool = True
    # ── ACP agent runtime 配置 ──
    agent_command: str = field(
        default_factory=lambda: _read_string_env("MICRORAG_AGENT_COMMAND", "claude")
    )
    agent_args: str = field(
        default_factory=lambda: _read_string_env(
            "MICRORAG_AGENT_ARGS",
            "--acp --setting-sources project",
        )
    )
    agent_cwd: str | None = field(
        default_factory=lambda: _read_optional_env("MICRORAG_AGENT_CWD")
    )
    agent_config_dir: str | None = field(
        default_factory=lambda: _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
    )
    microagent_dir: str | None = field(
        default_factory=lambda: _read_optional_env("MICRORAG_MICROAGENT_DIR")
    )

    def __post_init__(self) -> None:
        legacy_mode = os.getenv("RAGFLOW_LITE_RETRIEVAL_MODE")
        if legacy_mode is not None and legacy_mode.strip():
            raise RuntimeError(
                "RAGFLOW_LITE_RETRIEVAL_MODE is no longer supported. "
                "Retrieval is now fixed to hybrid mode. "
                "Please remove RAGFLOW_LITE_RETRIEVAL_MODE from your environment."
            )
        normalize_log_format(self.log_format)

    @classmethod
    def default(cls, project_root: Path | None = None) -> "Settings":
        """生成默认配置。

        默认目录全部落在仓库内的 `data/` 下，便于本地直接运行和调试。
        运行期 provider 配置只从环境变量读取，不写死在仓库中。
        """
        root = project_root or Path(__file__).resolve().parents[3]
        runtime_root = root / "data" / "agent-runtime"
        default_agent_cwd = runtime_root / "workspace"
        default_agent_command = root / "scripts" / "run_microagent.sh"
        default_microagent_dir = root / "src" / "ragflow_lite" / "microagent"
        return cls(
            project_root=root,
            uploads_dir=root / "data" / "uploads",
            local_index_dir=root / "data" / "local_index",
            temp_dir=root / "data" / "tmp",
            agent_command=(
                _read_optional_env("MICRORAG_AGENT_COMMAND")
                or str(default_agent_command)
            ),
            agent_cwd=(
                _read_optional_env("MICRORAG_AGENT_CWD") or str(default_agent_cwd)
            ),
            agent_config_dir=(
                _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
                or str(runtime_root / "config")
            ),
            microagent_dir=(
                _read_optional_env("MICRORAG_MICROAGENT_DIR")
                or str(default_microagent_dir)
            ),
        )

    def require_runtime_provider_configs(
        self,
    ) -> tuple[
        ArkEmbeddingRuntimeConfig,
        DeepSeekRuntimeConfig,
        DiscoRAGStructurerRuntimeConfig,
    ]:
        """校验并返回当前 V0 运行时依赖的 provider 配置。"""
        required_settings = (
            ("DEEPSEEK_API_KEY", self.deepseek_api_key),
            ("ARK_API_KEY", self.ark_api_key),
            ("ARK_EMBEDDING_MODEL", self.ark_embedding_model),
        )
        missing_settings = [name for name, value in required_settings if value is None]
        if missing_settings:
            missing_list = ", ".join(missing_settings)
            raise RuntimeError(
                f"Missing required runtime configuration: {missing_list}. "
                "Set the missing environment variables before starting the app."
            )

        prompt_path = self.answer_prompt_path
        if prompt_path is not None:
            prompt_file = Path(prompt_path).expanduser()
            if not prompt_file.is_absolute():
                prompt_file = self.project_root / prompt_file
            prompt_path = str(prompt_file)

        # Structurer API key: explicit override wins, otherwise alias
        # DeepSeek API key.  deepseek_api_key is guaranteed non-None after
        # the required_settings guard above.
        assert self.deepseek_api_key is not None  # for type narrows
        structurer_api_key: str = (
            self.discorag_structurer_api_key or self.deepseek_api_key
        )

        return (
            ArkEmbeddingRuntimeConfig(
                api_key=self.ark_api_key,
                model=self.ark_embedding_model,
                dimensions=self.ark_embedding_dimensions,
            ),
            DeepSeekRuntimeConfig(
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                model=self.deepseek_model,
                reasoning_effort=self.deepseek_reasoning_effort,
                prompt_path=prompt_path,
                render_citations=self.openai_render_citations,
            ),
            DiscoRAGStructurerRuntimeConfig(
                api_key=structurer_api_key,
                base_url=self.discorag_structurer_base_url,
                model=self.discorag_structurer_model,
                reasoning_effort=self.discorag_structurer_reasoning_effort,
                timeout_seconds=self.discorag_structurer_timeout_seconds,
                max_attempts=self.discorag_structurer_max_attempts,
            ),
        )

    def ensure_directories(self) -> None:
        """确保运行期依赖的本地目录存在。"""
        for directory in (self.uploads_dir, self.local_index_dir, self.temp_dir):
            directory.mkdir(parents=True, exist_ok=True)
