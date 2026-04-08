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
class OpenAIAnsweringRuntimeConfig:
    """OpenAI answering runtime configuration validated at startup."""

    api_key: str
    base_url: str
    model: str
    reasoning_effort: str
    store: bool
    verbosity: str


@dataclass(slots=True)
class Settings:
    """承载应用启动时需要的最小配置集合。"""

    project_root: Path
    uploads_dir: Path
    local_index_dir: Path
    temp_dir: Path
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_top_k: int = 10
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
    openai_api_key: str | None = field(
        default_factory=lambda: _read_optional_env("OPENAI_API_KEY")
    )
    openai_base_url: str = "https://code.rayinai.com/v1"
    openai_answer_model: str = "gpt-5.4-mini"
    openai_reasoning_effort: str = "medium"
    openai_store: bool = False
    openai_text_verbosity: str = "medium"
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
        return cls(
            project_root=root,
            uploads_dir=root / "data" / "uploads",
            local_index_dir=root / "data" / "local_index",
            temp_dir=root / "data" / "tmp",
        )

    def require_runtime_provider_configs(
        self,
    ) -> tuple[ArkEmbeddingRuntimeConfig, OpenAIAnsweringRuntimeConfig]:
        """校验并返回当前 V0 运行时依赖的 provider 配置。"""
        required_settings = (
            ("OPENAI_API_KEY", self.openai_api_key),
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

        openai_api_key = self.openai_api_key
        ark_api_key = self.ark_api_key
        ark_embedding_model = self.ark_embedding_model
        if openai_api_key is None or ark_api_key is None or ark_embedding_model is None:
            raise RuntimeError("Missing required runtime configuration.")

        return (
            ArkEmbeddingRuntimeConfig(
                api_key=ark_api_key,
                model=ark_embedding_model,
                dimensions=self.ark_embedding_dimensions,
            ),
            OpenAIAnsweringRuntimeConfig(
                api_key=openai_api_key,
                base_url=self.openai_base_url,
                model=self.openai_answer_model,
                reasoning_effort=self.openai_reasoning_effort,
                store=self.openai_store,
                verbosity=self.openai_text_verbosity,
            ),
        )

    def ensure_directories(self) -> None:
        """确保运行期依赖的本地目录存在。"""
        for directory in (self.uploads_dir, self.local_index_dir, self.temp_dir):
            directory.mkdir(parents=True, exist_ok=True)
