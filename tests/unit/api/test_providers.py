from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_test_support import (
    assign_isolated_infinity_tables,
    register_infinity_table_cleanup,
)

from ragflow_lite.api.deps.providers import build_services
from ragflow_lite.app import create_app
from ragflow_lite.application.services import (
    DiscoRAGQueryService,
    EvidencePackageBuilder,
    MiniGraphFirstRetriever,
    QueryModeRouter,
)
from ragflow_lite.config import (
    ArkEmbeddingRuntimeConfig,
    DeepSeekRuntimeConfig,
    DiscoRAGStructurerRuntimeConfig,
    Settings,
)
from ragflow_lite.infrastructure import (
    ArkMultimodalTextEmbedder,
    DeepSeekChatAnswerer,
    DeepSeekChatEvidenceExtractor,
    DeepSeekChatIntraChunkDiscourseExtractor,
    InfinityDenseVectorIndex,
    InfinityHybridRetriever,
    LocalJsonGraphEvidenceStore,
)
from ragflow_lite.infrastructure import retrievers as retrievers_module
from ragflow_lite.infrastructure.evidence import (
    GraphEvidenceInfinityStore,
    InfinityGraphCandidateIndex,
    LLMDiscoRAGAnswerBlueprintBuilder,
    LLMInterChunkDiscourseGraphBuilder,
    LocalJsonGraphEvidenceIndex,
)
from ragflow_lite.infrastructure.retrievers import (
    DeepSeekChatQueryGrounder,
)


def _build_settings(tmp_path: Path) -> Settings:
    from helpers.agent_runtime import setup_test_agent_runtime

    paths = setup_test_agent_runtime(tmp_path)
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
        microagent_dir=str(paths.microagent_dir),
    )
    assign_isolated_infinity_tables(settings, tmp_path)
    settings.ensure_directories()
    return settings


def _build_live_settings(tmp_path: Path) -> Settings:
    return register_infinity_table_cleanup(_build_settings(tmp_path))


@dataclass
class _FakeVectorIndex:
    client: object = object()
    client_lock: object = object()


def _fake_embedder(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(signature={"dimensions": 2048})


def _fake_answerer(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _fake_graph_store(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace()


def _fake_evidence_extractor(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace()


def _fake_query_grounder(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace()


def _fake_mini_graph_first_retriever(
    *args: object, **kwargs: object
) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _fake_pipeline(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs, process_task=lambda document_id: None)


def _patch_non_live_build_services_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragflow_lite.api.deps import providers as providers_module

    monkeypatch.setattr(providers_module, "ArkMultimodalTextEmbedder", _fake_embedder)
    monkeypatch.setattr(
        providers_module, "_build_vector_index", lambda *_: _FakeVectorIndex()
    )
    monkeypatch.setattr(providers_module, "DeepSeekChatAnswerer", _fake_answerer)
    monkeypatch.setattr(
        providers_module,
        "InfinityGraphCandidateIndex",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "LocalJsonGraphEvidenceStore",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "GraphEvidenceInfinityStore",
        _fake_graph_store,
    )
    monkeypatch.setattr(
        providers_module,
        "DeepSeekChatEvidenceExtractor",
        _fake_evidence_extractor,
    )
    monkeypatch.setattr(
        providers_module,
        "_build_retriever",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "DeepSeekChatQueryGrounder",
        _fake_query_grounder,
    )
    monkeypatch.setattr(
        providers_module,
        "LocalJsonGraphEvidenceIndex",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "MiniGraphFirstRetriever",
        _fake_mini_graph_first_retriever,
    )
    monkeypatch.setattr(
        providers_module, "QueryService", lambda **kwargs: SimpleNamespace(**kwargs)
    )
    monkeypatch.setattr(
        providers_module,
        "DiscoRAGQueryService",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "QueryModeRouter",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "IngestionPipeline",
        _fake_pipeline,
    )
    monkeypatch.setattr(
        providers_module,
        "DocumentService",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "DatasetService",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        providers_module,
        "LLMInterChunkDiscourseGraphBuilder",
        lambda **kwargs: SimpleNamespace(**kwargs, build=lambda package: None),
    )
    monkeypatch.setattr(
        providers_module,
        "LLMDiscoRAGAnswerBlueprintBuilder",
        lambda **kwargs: SimpleNamespace(
            **kwargs, build=lambda package, *, graph=None: None
        ),
    )


def test_settings_reject_missing_required_runtime_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="DEEPSEEK_API_KEY, ARK_API_KEY, ARK_EMBEDDING_MODEL",
    ):
        settings.require_runtime_provider_configs()


def test_settings_group_runtime_provider_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    ark_config, deepseek_config, structurer_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    assert ark_config == ArkEmbeddingRuntimeConfig(
        api_key="test-ark-api-key",
        model="ep-test-model",
        dimensions=2048,
    )
    assert deepseek_config == DeepSeekRuntimeConfig(
        api_key="test-deepseek-api-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        prompt_path=None,
        render_citations=True,
    )
    assert structurer_config == DiscoRAGStructurerRuntimeConfig(
        api_key="test-deepseek-api-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        timeout_seconds=90.0,
        max_attempts=2,
    )


def test_settings_reads_optional_answerer_prompt_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RAGFLOW_LITE_OPENAI_ANSWER_PROMPT_PATH",
        "/tmp/optimized_answerer_prompt.txt",
    )

    _, deepseek_config, _ = _build_settings(tmp_path).require_runtime_provider_configs()

    assert deepseek_config.prompt_path == "/tmp/optimized_answerer_prompt.txt"


def test_settings_reads_optional_render_citations_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")

    _, deepseek_config, _ = _build_settings(tmp_path).require_runtime_provider_configs()

    assert deepseek_config.render_citations is False


def test_structurer_config_falls_back_to_deepseek_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DISCORAG_STRUCTURER_API_KEY is not set, structurer aliases DEEPSEEK_API_KEY."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")
    monkeypatch.delenv("DISCORAG_STRUCTURER_API_KEY", raising=False)

    _, _, structurer_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    assert structurer_config.api_key == "test-deepseek-api-key"
    assert structurer_config.base_url == "https://api.deepseek.com"
    assert structurer_config.model == "deepseek-v4-flash"
    assert structurer_config.reasoning_effort == "high"


def test_structurer_config_uses_explicit_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DISCORAG_STRUCTURER_API_KEY is set, it overrides the DeepSeek fallback."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")
    monkeypatch.setenv("DISCORAG_STRUCTURER_API_KEY", "explicit-structurer-key")

    _, deepseek_config, structurer_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    assert deepseek_config.api_key == "test-deepseek-api-key"
    assert structurer_config.api_key == "explicit-structurer-key"


def test_structurer_config_defaults_in_settings(tmp_path: Path) -> None:
    """Verify structurer settings have correct hardcoded defaults."""
    settings = _build_settings(tmp_path)

    assert settings.discorag_structurer_base_url == "https://api.deepseek.com"
    assert settings.discorag_structurer_model == "deepseek-v4-flash"
    assert settings.discorag_structurer_reasoning_effort == "high"


def test_structurer_config_is_independent_from_deepseek_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify structurer config and deepseek config are separate objects."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    _, deepseek_config, structurer_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    # Both default to same provider but are distinct frozen configs
    assert deepseek_config is not structurer_config
    assert deepseek_config.api_key == structurer_config.api_key
    assert deepseek_config.base_url == structurer_config.base_url
    assert deepseek_config.model == structurer_config.model
    assert deepseek_config.reasoning_effort == structurer_config.reasoning_effort


@pytest.mark.live_infinity
def test_build_services_resolves_relative_answerer_prompt_path_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_relative_path = Path("tests/fixtures/evals/runtime_override.txt")
    prompt_path = tmp_path / prompt_relative_path
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Runtime override instructions.", encoding="utf-8")
    monkeypatch.setenv(
        "RAGFLOW_LITE_OPENAI_ANSWER_PROMPT_PATH",
        str(prompt_relative_path),
    )
    off_repo_dir = tmp_path / "other-working-dir"
    off_repo_dir.mkdir()
    monkeypatch.chdir(off_repo_dir)

    services = build_services(_build_live_settings(tmp_path))

    answerer = services.query_service.answerer
    assert isinstance(answerer, DeepSeekChatAnswerer)
    assert answerer.instructions == "Runtime override instructions."


@pytest.mark.live_infinity
def test_build_services_threads_render_citations_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")

    services = build_services(_build_live_settings(tmp_path))

    answerer = services.query_service.answerer
    assert isinstance(answerer, DeepSeekChatAnswerer)
    assert answerer.render_citations is False


def test_create_app_rejects_missing_ark_embedding_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(RuntimeError, match="ARK_EMBEDDING_MODEL"):
        create_app(settings)


@pytest.mark.live_infinity
def test_build_services_uses_infinity_hybrid_retriever(
    tmp_path: Path,
) -> None:
    services = build_services(_build_live_settings(tmp_path))

    # 图优先检索器作为主检索器
    assert isinstance(services.query_service.retriever, MiniGraphFirstRetriever)
    # InfinityHybridRetriever 作为 chunk 辅助检索器
    assert isinstance(
        services.query_service.retriever.chunk_auxiliary_retriever,
        InfinityHybridRetriever,
    )
    assert isinstance(services.ingestion_pipeline.embedder, ArkMultimodalTextEmbedder)
    assert (
        services.ingestion_pipeline.embedder
        is services.query_service.retriever.chunk_auxiliary_retriever.embedder
    )
    assert isinstance(
        services.ingestion_pipeline.vector_index, InfinityDenseVectorIndex
    )
    answerer = services.query_service.answerer
    assert isinstance(answerer, DeepSeekChatAnswerer)
    assert answerer.model == "deepseek-v4-flash"
    assert answerer.reasoning_effort == "high"


@pytest.mark.live_infinity
def test_build_services_wires_graph_evidence_dependencies(tmp_path: Path) -> None:
    services = build_services(_build_live_settings(tmp_path))

    # 图证据存储：GraphEvidenceInfinityStore 包装 JSON + Infinity candidates
    assert isinstance(
        services.ingestion_pipeline.graph_store, GraphEvidenceInfinityStore
    )
    assert isinstance(
        services.ingestion_pipeline.graph_store._graph_store,
        LocalJsonGraphEvidenceStore,
    )
    assert isinstance(
        services.ingestion_pipeline.graph_store._candidate_index,
        InfinityGraphCandidateIndex,
    )
    assert isinstance(
        services.ingestion_pipeline.evidence_extractor,
        DeepSeekChatEvidenceExtractor,
    )


def test_infrastructure_exports_current_runtime_components() -> None:
    from ragflow_lite import infrastructure

    assert infrastructure.__all__ == [
        "ArkMultimodalTextEmbedder",
        "BackgroundTaskRunner",
        "CompositeParser",
        "DeepSeekChatAnswerer",
        "DeepSeekChatEvidenceExtractor",
        "DeepSeekChatIntraChunkDiscourseExtractor",
        "RecursiveCharacterChunker",
        "InfinityDenseVectorIndex",
        "InfinityHybridRetriever",
        "InlineTaskRunner",
        "InMemoryStageCache",
        "InMemoryTaskStore",
        "LocalDocumentStore",
        "LocalJsonGraphEvidenceStore",
        "LocalJsonVectorIndex",
        "OpenAIResponsesAnswerer",
        "OpenAIResponsesEvidenceExtractor",
    ]
    assert retrievers_module.__all__ == [
        "DeepSeekChatQueryGrounder",
        "DeepSeekCoTGroundingRewriter",
        "InfinityHybridRetriever",
        "OpenAIResponsesCoTGroundingRewriter",
        "OpenAIResponsesQueryGrounder",
    ]
    assert not hasattr(infrastructure, "VectorRetriever")
    assert not hasattr(infrastructure, "InfinityFullTextRetriever")
    assert not hasattr(retrievers_module, "VectorRetriever")
    assert not hasattr(retrievers_module, "InfinityFullTextRetriever")


@pytest.mark.live_infinity
def test_build_services_wires_mini_graph_first_retriever(tmp_path: Path) -> None:
    """验证 build_services 组装 MiniGraphFirstRetriever 并在两个 query service 间共享。"""
    settings = _build_live_settings(tmp_path)

    services = build_services(settings)

    # 主检索器是 MiniGraphFirstRetriever
    assert isinstance(services.retriever, MiniGraphFirstRetriever)
    # 两个 query service 共享同一个检索器实例
    assert services.query_service.retriever is services.retriever
    assert services.discorag_query_service.retriever is services.retriever
    # query_grounder 正确装配
    assert isinstance(services.retriever.query_grounder, DeepSeekChatQueryGrounder)
    # Infinity 图候选索引用于 entity/relationship 查询
    assert isinstance(services.retriever.entity_index, InfinityGraphCandidateIndex)
    assert isinstance(
        services.retriever.relationship_index, InfinityGraphCandidateIndex
    )
    assert services.retriever.entity_index is services.retriever.relationship_index
    # 本地 JSON 图证据索引用于拓扑路径扩展（path_expander）
    assert isinstance(services.retriever.path_expander, LocalJsonGraphEvidenceIndex)
    assert services.retriever.path_expander._canonicalize_cross_document is True
    # chunk_lookup 使用 vector_index
    assert services.retriever.chunk_lookup is services.ingestion_pipeline.vector_index
    # chunk_auxiliary_retriever 使用 InfinityHybridRetriever
    assert isinstance(
        services.retriever.chunk_auxiliary_retriever, InfinityHybridRetriever
    )


@pytest.mark.live_infinity
def test_build_services_wires_graph_candidate_infinity_index(tmp_path: Path) -> None:
    """验证 Infinity 图候选索引作为 entity/relationship 查询路径。"""
    services = build_services(_build_live_settings(tmp_path))
    retriever = services.query_service.retriever
    assert isinstance(retriever, MiniGraphFirstRetriever)
    assert isinstance(retriever.entity_index, InfinityGraphCandidateIndex)
    assert isinstance(retriever.relationship_index, InfinityGraphCandidateIndex)
    # path_expander 使用本地 JSON 索引，不使用 Infinity 图候选索引
    assert not isinstance(retriever.path_expander, InfinityGraphCandidateIndex)
    assert isinstance(retriever.chunk_auxiliary_retriever, InfinityHybridRetriever)


def test_graph_candidate_defaults_match_spec(tmp_path: Path) -> None:
    """验证图候选 Infinity 设置的默认值与规格一致。"""
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    assert settings.mini_internal_candidate_n == 60
    assert settings.query_entity_limit == 5
    assert settings.graph_initial_recall_n == 1024
    assert settings.graph_candidate_text_weight == 0.05
    assert settings.graph_candidate_dense_weight == 0.95
    assert settings.graph_candidate_minimum_should_match == 0.3
    assert settings.graph_candidate_dense_similarity_threshold == 0.2
    assert settings.graph_candidate_fusion_normalize == "atan"
    assert settings.infinity_graph_entity_table == "graph_entities"
    assert settings.infinity_graph_relationship_table == "graph_relationships"


def test_chunk_hybrid_defaults_match_spec(tmp_path: Path) -> None:
    """验证 chunk Infinity hybrid 设置默认值与规格一致。"""
    settings = _build_settings(tmp_path)
    assert settings.chunk_initial_recall_n == 1024
    assert settings.chunk_text_weight == 0.05
    assert settings.chunk_dense_weight == 0.95
    assert settings.chunk_minimum_should_match == 0.3
    assert settings.chunk_dense_similarity_threshold == 0.2
    assert settings.chunk_fusion_normalize == "atan"
    assert settings.chunk_position_prior_weight == 0.03
    assert settings.chunk_position_prior_enabled is True


def test_build_services_non_live_keeps_discourse_extractor_uncapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    services = build_services(_build_settings(tmp_path))

    assert isinstance(
        services.discorag_query_service.discourse_extractor,
        DeepSeekChatIntraChunkDiscourseExtractor,
    )
    assert services.discorag_query_service.discourse_extractor.max_chunks is None


def test_build_services_non_live_structurer_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RST、graph、blueprint 三个结构化组件使用 structurer config，answerer 使用 deepseek config。"""
    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")
    monkeypatch.setenv("DISCORAG_STRUCTURER_API_KEY", "structurer-key")

    settings = _build_settings(tmp_path)
    settings.discorag_structurer_base_url = "https://structurer.example.com"
    settings.discorag_structurer_model = "structurer-model-v2"
    settings.discorag_structurer_reasoning_effort = "low"

    services = build_services(settings)

    # 三个结构化组件共享 structurer config
    de = services.discorag_query_service.discourse_extractor
    assert isinstance(de, DeepSeekChatIntraChunkDiscourseExtractor)
    assert de.api_key == "structurer-key"
    assert de.base_url == "https://structurer.example.com"
    assert de.model == "structurer-model-v2"
    assert de.reasoning_effort == "low"

    gb = services.discorag_query_service.inter_chunk_graph_builder
    assert gb.api_key == "structurer-key"
    assert gb.base_url == "https://structurer.example.com"
    assert gb.model == "structurer-model-v2"
    assert gb.reasoning_effort == "low"

    bb = services.discorag_query_service.blueprint_builder
    assert bb.api_key == "structurer-key"
    assert bb.base_url == "https://structurer.example.com"
    assert bb.model == "structurer-model-v2"
    assert bb.reasoning_effort == "low"

    # answerer 使用 deepseek config，与 structurer 无关
    answerer = services.query_service.answerer
    assert answerer.api_key == "deepseek-key"
    assert answerer.model != "structurer-model-v2"


@pytest.mark.live_infinity
def test_build_services_wires_discorag_query_service(tmp_path: Path) -> None:
    services = build_services(_build_live_settings(tmp_path))

    assert isinstance(services.discorag_query_service, DiscoRAGQueryService)
    assert services.discorag_query_service.retriever is services.retriever
    assert services.discorag_query_service.answerer is services.query_service.answerer
    assert isinstance(
        services.discorag_query_service.evidence_package_builder,
        EvidencePackageBuilder,
    )
    assert isinstance(
        services.discorag_query_service.discourse_extractor,
        DeepSeekChatIntraChunkDiscourseExtractor,
    )
    assert services.discorag_query_service.discourse_extractor.max_chunks is None
    assert isinstance(
        services.discorag_query_service.blueprint_builder,
        LLMDiscoRAGAnswerBlueprintBuilder,
    )
    # inter-chunk graph builder 使用 LLM structurer 实现
    assert isinstance(
        services.discorag_query_service.inter_chunk_graph_builder,
        LLMInterChunkDiscourseGraphBuilder,
    )


@pytest.mark.live_infinity
def test_build_services_wires_query_mode_router(tmp_path: Path) -> None:
    services = build_services(_build_live_settings(tmp_path))

    assert isinstance(services.query_router, QueryModeRouter)
    assert services.query_router.standard_service is services.query_service
    assert services.query_router.discorag_service is services.discorag_query_service


@pytest.mark.live_infinity
def test_build_services_embedder_dimensions_match_settings(
    tmp_path: Path,
) -> None:
    services = build_services(_build_live_settings(tmp_path))
    assert isinstance(services.ingestion_pipeline.embedder, ArkMultimodalTextEmbedder)
    assert services.ingestion_pipeline.embedder.signature["dimensions"] == 2048


def test_settings_rejects_legacy_retrieval_mode_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_RETRIEVAL_MODE", "dense")
    with pytest.raises(
        RuntimeError, match="RAGFLOW_LITE_RETRIEVAL_MODE is no longer supported"
    ):
        _build_settings(tmp_path)


@pytest.mark.live_infinity
def test_build_services_provides_document_service(tmp_path: Path) -> None:
    from ragflow_lite.application import DocumentService

    services = build_services(_build_live_settings(tmp_path))
    assert isinstance(services.document_service, DocumentService)
    assert services.document_service.catalog is services.ingestion_pipeline.vector_index


def test_settings_default_observability_and_infinity_values(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)

    assert settings.log_level == "INFO"
    assert settings.log_format == "text"
    assert settings.metrics_enabled is False
    assert settings.infinity_host == "127.0.0.1"
    assert settings.infinity_port == 23817


def test_build_services_non_live_structurer_wires_retry_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """timeout_seconds and max_attempts from settings reach all three structurer constructors."""
    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    settings = _build_settings(tmp_path)
    settings.discorag_structurer_timeout_seconds = 12.5
    settings.discorag_structurer_max_attempts = 3

    services = build_services(settings)

    de = services.discorag_query_service.discourse_extractor
    assert isinstance(de, DeepSeekChatIntraChunkDiscourseExtractor)
    assert de.timeout_seconds == 12.5
    assert de.max_attempts == 3

    gb = services.discorag_query_service.inter_chunk_graph_builder
    # Non-live path uses SimpleNamespace fake; access attributes directly
    assert gb.timeout_seconds == 12.5  # type: ignore[attr-defined]
    assert gb.max_attempts == 3  # type: ignore[attr-defined]

    bb = services.discorag_query_service.blueprint_builder
    assert bb.timeout_seconds == 12.5  # type: ignore[attr-defined]
    assert bb.max_attempts == 3  # type: ignore[attr-defined]


def test_discorag_structurer_retry_defaults_are_bounded(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    assert settings.discorag_structurer_timeout_seconds == 90.0
    assert settings.discorag_structurer_max_attempts == 2


def test_discorag_structurer_config_includes_retry_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    _, _, structurer_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    assert structurer_config.timeout_seconds == 90.0
    assert structurer_config.max_attempts == 2


def test_discorag_structurer_config_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        DiscoRAGStructurerRuntimeConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            reasoning_effort="high",
            timeout_seconds=-1.0,
        )


def test_discorag_structurer_config_rejects_zero_max_attempts() -> None:
    with pytest.raises(ValueError, match="must be at least 1"):
        DiscoRAGStructurerRuntimeConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            reasoning_effort="high",
            max_attempts=0,
        )


def test_settings_reads_observability_and_infinity_envs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("RAGFLOW_LITE_LOG_FORMAT", "json")
    monkeypatch.setenv("RAGFLOW_LITE_METRICS_ENABLED", "true")
    monkeypatch.setenv("RAGFLOW_LITE_INFINITY_HOST", "host.docker.internal")
    monkeypatch.setenv("RAGFLOW_LITE_INFINITY_PORT", "31000")

    settings = _build_settings(tmp_path)

    assert settings.log_level == "DEBUG"
    assert settings.log_format == "json"
    assert settings.metrics_enabled is True
    assert settings.infinity_host == "host.docker.internal"
    assert settings.infinity_port == 31000


def test_settings_rejects_invalid_metrics_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_METRICS_ENABLED", "maybe")

    with pytest.raises(RuntimeError, match="RAGFLOW_LITE_METRICS_ENABLED"):
        _build_settings(tmp_path)


@pytest.mark.live_infinity
def test_build_services_wires_chunk_hybrid_config(tmp_path: Path) -> None:
    settings = _build_live_settings(tmp_path)
    settings.chunk_initial_recall_n = 77
    settings.chunk_text_weight = 0.2
    settings.chunk_dense_weight = 0.8
    settings.chunk_minimum_should_match = 0.4
    settings.chunk_dense_similarity_threshold = 0.25
    settings.chunk_fusion_normalize = "atan"
    settings.chunk_position_prior_weight = 0.01
    settings.chunk_position_prior_enabled = False

    services = build_services(settings)

    vector_index = services.ingestion_pipeline.vector_index
    assert isinstance(vector_index, InfinityDenseVectorIndex)
    config = vector_index._chunk_hybrid_config
    assert config.initial_recall_n == 77
    assert config.text_weight == 0.2
    assert config.dense_weight == 0.8
    assert config.minimum_should_match == 0.4
    assert config.dense_similarity_threshold == 0.25
    assert config.fusion_normalize == "atan"
    assert config.position_prior_weight == 0.01
    assert config.position_prior_enabled is False


@pytest.mark.live_infinity
def test_chunk_and_graph_candidate_configs_are_separate(tmp_path: Path) -> None:
    settings = _build_live_settings(tmp_path)
    settings.chunk_initial_recall_n = 77
    settings.graph_initial_recall_n = 88

    services = build_services(settings)

    vector_index = services.ingestion_pipeline.vector_index
    graph_index = services.retriever.entity_index
    assert isinstance(vector_index, InfinityDenseVectorIndex)
    assert isinstance(graph_index, InfinityGraphCandidateIndex)
    assert vector_index._chunk_hybrid_config.initial_recall_n == 77
    assert graph_index._config.graph_initial_recall_n == 88


def test_build_services_wires_cot_grounding_rewriter_non_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragflow_lite.api.deps import providers as providers_module

    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setattr(
        providers_module,
        "DeepSeekCoTGroundingRewriter",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    settings = _build_settings(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    services = build_services(settings)

    assert services.retriever.cot_grounding_rewriter is not None
    assert services.retriever.cot_grounding_rewriter.model == settings.deepseek_model


def test_build_services_does_not_require_agent_runtime_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "test-model")
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    settings.ensure_directories()

    services = build_services(settings)

    assert services.settings is settings
