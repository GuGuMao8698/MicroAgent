"""FastAPI 依赖组装入口。

这个模块把基础设施实现装配成应用可用的服务对象，路由层只通过依赖注入
获取流程入口，不直接感知底层实现细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Request

from ragflow_lite.application import (
    DatasetService,
    DocumentService,
    IngestionPipeline,
    QueryService,
    normalize_text,
)
from ragflow_lite.application.services import (
    DiscoRAGAnswerBlueprintBuilder,
    DiscoRAGQueryService,
    EvidencePackageBuilder,
    MiniGraphFirstRetriever,
    QueryModeRouter,
)
from ragflow_lite.config import Settings
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
    LocalJsonGraphEvidenceStore,
    RecursiveCharacterChunker,
)
from ragflow_lite.infrastructure.evidence import (
    GraphCandidateSidecar,
    GraphEvidenceSidecarStore,
    LocalJsonGraphEvidenceHybridIndex,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_scoring import (
    GraphCandidateRetrievalConfig,
)
from ragflow_lite.infrastructure.retrievers import DeepSeekChatQueryGrounder


@dataclass(slots=True)
class AppServices:
    """集中保存应用启动后可复用的核心服务对象。"""

    settings: Settings
    ingestion_pipeline: IngestionPipeline
    retriever: Retriever
    query_service: QueryService
    discorag_query_service: DiscoRAGQueryService
    query_router: QueryModeRouter
    document_service: DocumentService
    dataset_service: DatasetService
    task_store: IngestionTaskStore = field(default_factory=InMemoryTaskStore)
    stage_cache: IngestionStageCache = field(default_factory=InMemoryStageCache)


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
    ark_runtime_config, deepseek_runtime_config = (
        settings.require_runtime_provider_configs()
    )

    document_store = LocalDocumentStore(settings.uploads_dir, settings.temp_dir)
    parser = CompositeParser()
    chunker = RecursiveCharacterChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
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
    graph_candidate_sidecar = GraphCandidateSidecar(
        sidecar_dir=settings.local_index_dir / "graph_candidate_vectors",
        embedding_signature=embedder.signature,
    )
    base_graph_store = LocalJsonGraphEvidenceStore(graph_evidence_dir)
    graph_store = GraphEvidenceSidecarStore(
        graph_store=base_graph_store,
        sidecar=graph_candidate_sidecar,
        embedder=embedder,
    )
    evidence_extractor = DeepSeekChatEvidenceExtractor(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
    )
    discourse_extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
    )
    # chunk 辅助检索器：Infinity hybrid 作为辅助召回通道
    chunk_auxiliary_retriever = _build_retriever(embedder, vector_index)
    query_grounder = DeepSeekChatQueryGrounder(
        api_key=deepseek_runtime_config.api_key,
        base_url=deepseek_runtime_config.base_url,
        model=deepseek_runtime_config.model,
        reasoning_effort=deepseek_runtime_config.reasoning_effort,
    )
    # 图候选检索配置：从 settings 构建
    graph_candidate_config = GraphCandidateRetrievalConfig(
        lexical_weight=settings.graph_candidate_lexical_weight,
        dense_weight=settings.graph_candidate_dense_weight,
        minimum_should_match=settings.graph_candidate_minimum_should_match,
        dense_similarity_threshold=settings.graph_candidate_dense_similarity_threshold,
        graph_initial_candidate_k=settings.graph_initial_candidate_k,
    )
    # 图证据混合索引：词法 + 稠密混合检索，同一实例承担实体/关系/路径扩展三个端口
    graph_evidence_index = LocalJsonGraphEvidenceHybridIndex(
        evidence_dir=graph_evidence_dir,
        sidecar=graph_candidate_sidecar,
        embedder=embedder,
        config=graph_candidate_config,
    )
    # 图优先检索器：先做 query grounding，再查图索引、扩展路径，最后评分与合并 chunk
    retriever = MiniGraphFirstRetriever(
        query_grounder=query_grounder,
        entity_index=graph_evidence_index,
        relationship_index=graph_evidence_index,
        path_expander=graph_evidence_index,
        chunk_lookup=vector_index,
        chunk_auxiliary_retriever=chunk_auxiliary_retriever,
    )
    query_service = QueryService(
        retriever=retriever,
        answerer=answerer,
    )
    discorag_query_service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=discourse_extractor,
        blueprint_builder=DiscoRAGAnswerBlueprintBuilder(),
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
    )

    runner.set_handler(pipeline.process_task)

    return AppServices(
        settings=settings,
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
