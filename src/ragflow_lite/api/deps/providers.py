"""FastAPI 依赖组装入口。

这个模块把基础设施实现装配成应用可用的服务对象，路由层只通过依赖注入
获取流程入口，不直接感知底层实现细节。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, Request

from ragflow_lite.application import (
    DatasetService,
    DocumentService,
    IngestionPipeline,
    QueryService,
    normalize_text,
)
from ragflow_lite.application.services import (
    DiscoRAGQueryService,
    EvidencePackageBuilder,
    MiniGraphFirstRetriever,
    QueryModeRouter,
)
from ragflow_lite.config import (
    DiscoRAGStructurerRuntimeConfig,
    Settings,
)
from ragflow_lite.domain.ports.interfaces import (
    IngestionStageCache,
    IngestionTaskStore,
    Retriever,
)
from ragflow_lite.infrastructure import (
    ArkMultimodalTextEmbedder,
    BackgroundTaskRunner,
    CompositeParser,
    DeepSeekChatAnswerer,
    DeepSeekChatEvidenceExtractor,
    DeepSeekChatIntraChunkDiscourseExtractor,
    InfinityDenseVectorIndex,
    InfinityHybridRetriever,
    InMemoryStageCache,
    InMemoryTaskStore,
    LocalDocumentStore,
    RecursiveCharacterChunker,
)
from ragflow_lite.infrastructure.agent import (
    AcpClient,
    AcpRuntimeConfig,
    AgentSessionStore,
)
from ragflow_lite.infrastructure.chunkers import (
    AcademicPdfChunker,
    DocumentChunker,
)
from ragflow_lite.infrastructure.evidence import (
    GraphEvidenceInfinityStore,
    InfinityGraphCandidateIndex,
    LLMDiscoRAGAnswerBlueprintBuilder,
    LLMInterChunkDiscourseGraphBuilder,
    LocalJsonGraphEvidenceIndex,
    LocalJsonGraphEvidenceStore,
)
from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    GraphCandidateInfinityConfig,
)
from ragflow_lite.infrastructure.media import LocalPdfMediaAssetStore
from ragflow_lite.infrastructure.retrievers import (
    DeepSeekChatQueryGrounder,
    DeepSeekCoTGroundingRewriter,
)
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    ChunkHybridRetrievalConfig,
)


@dataclass(slots=True)
class AppServices:
    """集中保存应用启动后可复用的核心服务对象。"""

    settings: Settings
    agent_session_store: AgentSessionStore
    acp_client_factory: Callable[[], AcpClient]
    ingestion_pipeline: IngestionPipeline
    retriever: Retriever
    query_service: QueryService
    discorag_query_service: DiscoRAGQueryService
    query_router: QueryModeRouter
    document_service: DocumentService
    dataset_service: DatasetService
    task_store: IngestionTaskStore = field(default_factory=InMemoryTaskStore)
    stage_cache: IngestionStageCache = field(default_factory=InMemoryStageCache)
    structurer_config: DiscoRAGStructurerRuntimeConfig | None = None
    _acp_client: AcpClient | None = field(default=None, init=False, repr=False)

    @property
    def acp_client(self) -> AcpClient:
        if self._acp_client is None:
            self._acp_client = self.acp_client_factory()
        return self._acp_client


def _build_acp_client(settings: Settings) -> AcpClient:
    from ragflow_lite.agent_runtime.setup import (
        SETUP_INCOMPLETE_MESSAGE,
        AgentRuntimePaths,
        build_agent_child_env,
        validate_agent_runtime_workspace,
    )

    if (
        settings.agent_cwd is None
        or settings.agent_config_dir is None
        or settings.microagent_dir is None
    ):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)

    paths = AgentRuntimePaths(
        project_root=settings.project_root,
        config_dir=Path(settings.agent_config_dir),
        workspace_dir=Path(settings.agent_cwd),
        microagent_dir=Path(settings.microagent_dir),
    )
    validate_agent_runtime_workspace(paths)
    config = AcpRuntimeConfig(
        command=settings.agent_command,
        args=settings.agent_args.split(),
        cwd=str(paths.workspace_dir),
        env=build_agent_child_env(paths),
    )
    return AcpClient(config=config)


def _build_vector_index(
    settings: Settings,
    embedder: ArkMultimodalTextEmbedder,
) -> InfinityDenseVectorIndex:
    return InfinityDenseVectorIndex(
        host=settings.infinity_host,
        port=settings.infinity_port,
        database=settings.infinity_database,
        document_table=settings.infinity_document_table,
        chunk_table=settings.infinity_chunk_table,
        embedding_dimensions=settings.ark_embedding_dimensions,
        embedding_signature=embedder.signature,
        chunk_hybrid_config=ChunkHybridRetrievalConfig(
            initial_recall_n=settings.chunk_initial_recall_n,
            text_weight=settings.chunk_text_weight,
            dense_weight=settings.chunk_dense_weight,
            minimum_should_match=settings.chunk_minimum_should_match,
            dense_similarity_threshold=settings.chunk_dense_similarity_threshold,
            fusion_normalize=settings.chunk_fusion_normalize,
            position_prior_weight=settings.chunk_position_prior_weight,
            position_prior_enabled=settings.chunk_position_prior_enabled,
        ),
    )


def _build_retriever(
    embedder: ArkMultimodalTextEmbedder,
    vector_index: InfinityDenseVectorIndex,
) -> Retriever:
    return InfinityHybridRetriever(embedder=embedder, vector_index=vector_index)


def build_services(settings: Settings) -> AppServices:
    """按照当前架构组装依赖。

    这里显式完成"配置 -> 具体实现 -> 业务流程"的连接，便于后续替换
    parser、embedder 或 index，而不需要改动路由层。
    """
    ark_runtime_config, deepseek_runtime_config, structurer_runtime_config = (
        settings.require_runtime_provider_configs()
    )

    document_store = LocalDocumentStore(settings.uploads_dir, settings.temp_dir)
    agent_session_store = AgentSessionStore(
        settings.local_index_dir / "agent_sessions.sqlite3"
    )
    parser = CompositeParser()
    generic_chunker = RecursiveCharacterChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunker = DocumentChunker(
        generic_chunker=generic_chunker,
        academic_pdf_chunker=AcademicPdfChunker(),
    )
    media_asset_store = LocalPdfMediaAssetStore(
        settings.project_root / "data" / "media" / "pdf-assets",
    )
    figure_describer = None
    if settings.figure_vlm_enabled:
        from openai import OpenAI

        assert settings.ark_figure_model is not None
        from ragflow_lite.infrastructure.vlm import ArkFigureDescriptionClient

        figure_describer = ArkFigureDescriptionClient(
            client=OpenAI(api_key=settings.ark_api_key, base_url=settings.ark_base_url),
            model=settings.ark_figure_model,
            max_image_bytes=settings.figure_vlm_max_image_bytes,
        )
    embedder = ArkMultimodalTextEmbedder(
        api_key=ark_runtime_config.api_key,
        model=ark_runtime_config.model,
        dimensions=ark_runtime_config.dimensions,
    )
    vector_index = _build_vector_index(settings, embedder)
    answerer = DeepSeekChatAnswerer(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
        instructions_path=deepseek_runtime_config.prompt_path,
        render_citations=deepseek_runtime_config.render_citations,
    )
    graph_evidence_dir = settings.local_index_dir / "graph_evidence"
    # Infinity 图候选索引：entity/relationship 混合检索（文本 + 稠密向量融合）
    graph_candidate_index = InfinityGraphCandidateIndex(
        client=vector_index.client,
        client_lock=vector_index.client_lock,
        database=settings.infinity_database,
        embedder=embedder,
        config=GraphCandidateInfinityConfig(
            entity_table=settings.infinity_graph_entity_table,
            relationship_table=settings.infinity_graph_relationship_table,
            graph_initial_recall_n=settings.graph_initial_recall_n,
            text_weight=settings.graph_candidate_text_weight,
            dense_weight=settings.graph_candidate_dense_weight,
            minimum_should_match=settings.graph_candidate_minimum_should_match,
            dense_similarity_threshold=settings.graph_candidate_dense_similarity_threshold,
            fusion_normalize=settings.graph_candidate_fusion_normalize,
        ),
    )
    # 图证据存储：同时写 JSON + Infinity candidates
    base_graph_store = LocalJsonGraphEvidenceStore(graph_evidence_dir)
    graph_store = GraphEvidenceInfinityStore(
        graph_store=base_graph_store,
        candidate_index=graph_candidate_index,
    )
    evidence_extractor = DeepSeekChatEvidenceExtractor(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
    )
    discourse_extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        api_key=structurer_runtime_config.api_key,
        base_url=structurer_runtime_config.base_url,
        model=structurer_runtime_config.model,
        reasoning_effort=structurer_runtime_config.reasoning_effort,
        timeout_seconds=structurer_runtime_config.timeout_seconds,
        max_attempts=structurer_runtime_config.max_attempts,
    )
    # chunk 辅助检索器：Infinity hybrid 作为辅助召回通道
    chunk_auxiliary_retriever = _build_retriever(embedder, vector_index)
    query_grounder = DeepSeekChatQueryGrounder(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
    )
    cot_grounding_rewriter = DeepSeekCoTGroundingRewriter(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
    )
    # 本地 JSON 图证据索引：仅用于拓扑路径扩展
    local_graph_evidence_index = LocalJsonGraphEvidenceIndex(
        evidence_dir=graph_evidence_dir,
        reload_on_query=True,
        canonicalize_cross_document=True,
    )
    # 图优先检索器：先做 query grounding，再查图索引、扩展路径，最后评分与合并 chunk
    retriever = MiniGraphFirstRetriever(
        query_grounder=query_grounder,
        entity_index=graph_candidate_index,
        relationship_index=graph_candidate_index,
        path_expander=local_graph_evidence_index,
        chunk_lookup=vector_index,
        chunk_auxiliary_retriever=chunk_auxiliary_retriever,
        cot_grounding_rewriter=cot_grounding_rewriter,
        mini_internal_candidate_n=settings.mini_internal_candidate_n,
        query_entity_limit=settings.query_entity_limit,
    )
    query_service = QueryService(
        retriever=retriever,
        answerer=answerer,
    )
    discorag_query_service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=discourse_extractor,
        inter_chunk_graph_builder=LLMInterChunkDiscourseGraphBuilder(
            api_key=structurer_runtime_config.api_key,
            base_url=structurer_runtime_config.base_url,
            model=structurer_runtime_config.model,
            reasoning_effort=structurer_runtime_config.reasoning_effort,
            timeout_seconds=structurer_runtime_config.timeout_seconds,
            max_attempts=structurer_runtime_config.max_attempts,
        ),
        blueprint_builder=LLMDiscoRAGAnswerBlueprintBuilder(
            api_key=structurer_runtime_config.api_key,
            base_url=structurer_runtime_config.base_url,
            model=structurer_runtime_config.model,
            reasoning_effort=structurer_runtime_config.reasoning_effort,
            timeout_seconds=structurer_runtime_config.timeout_seconds,
            max_attempts=structurer_runtime_config.max_attempts,
        ),
        answerer=answerer,
    )
    query_router = QueryModeRouter(
        standard_service=query_service,
        discorag_service=discorag_query_service,
    )

    task_store = InMemoryTaskStore()
    stage_cache = InMemoryStageCache()
    runner = BackgroundTaskRunner()

    pipeline = IngestionPipeline(
        document_store=document_store,
        parser=parser,
        chunker=chunker,
        embedder=embedder,
        vector_index=vector_index,
        normalizer=normalize_text,
        dataset_store=vector_index,
        task_store=task_store,
        stage_cache=stage_cache,
        runner=runner,
        evidence_extractor=evidence_extractor,
        graph_store=graph_store,
        media_asset_store=media_asset_store,
        figure_describer=figure_describer,
    )

    runner.set_handler(pipeline.process_task)

    return AppServices(
        settings=settings,
        agent_session_store=agent_session_store,
        acp_client_factory=lambda: _build_acp_client(settings),
        ingestion_pipeline=pipeline,
        retriever=retriever,
        query_service=query_service,
        discorag_query_service=discorag_query_service,
        query_router=query_router,
        document_service=DocumentService(
            catalog=vector_index,
            dataset_store=vector_index,
        ),
        dataset_service=DatasetService(store=vector_index),
        task_store=task_store,
        stage_cache=stage_cache,
        structurer_config=structurer_runtime_config,
    )


def get_services(request: Request) -> AppServices:
    """从应用状态中读取已组装好的服务容器。"""
    return request.app.state.services


def get_ingestion_pipeline(
    services: AppServices = Depends(get_services),
) -> IngestionPipeline:
    """提供文档 ingestion 主流程给路由层使用。"""
    return services.ingestion_pipeline


def get_query_service(services: AppServices = Depends(get_services)) -> QueryService:
    """提供查询回答主流程给路由层使用。"""
    return services.query_service


def get_query_router(
    services: AppServices = Depends(get_services),
) -> QueryModeRouter:
    """提供查询模式分发入口给路由层使用。"""
    return services.query_router


def get_document_service(
    services: AppServices = Depends(get_services),
) -> DocumentService:
    """提供文档目录只读服务给路由层使用。"""
    return services.document_service


def get_dataset_service(
    services: AppServices = Depends(get_services),
) -> DatasetService:
    """提供 dataset 管理服务给路由层使用。"""
    return services.dataset_service
