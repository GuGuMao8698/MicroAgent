"""FastAPI 依赖组装入口。

这个模块把基础设施实现装配成应用可用的服务对象，路由层只通过依赖注入
获取流程入口，不直接感知底层实现细节。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from ragflow_lite.application import (
    DocumentService,
    IngestionPipeline,
    QueryService,
    normalize_text,
)
from ragflow_lite.config import Settings
from ragflow_lite.domain.ports.interfaces import Retriever
from ragflow_lite.infrastructure import (
    ArkMultimodalTextEmbedder,
    CompositeParser,
    FixedWindowChunker,
    InfinityDenseVectorIndex,
    InfinityHybridRetriever,
    LocalDocumentStore,
    OpenAIResponsesAnswerer,
)


@dataclass(slots=True)
class AppServices:
    """集中保存应用启动后可复用的核心服务对象。"""

    settings: Settings
    ingestion_pipeline: IngestionPipeline
    retriever: Retriever
    query_service: QueryService
    document_service: DocumentService


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
    ark_runtime_config, openai_runtime_config = (
        settings.require_runtime_provider_configs()
    )

    document_store = LocalDocumentStore(settings.uploads_dir, settings.temp_dir)
    parser = CompositeParser()
    chunker = FixedWindowChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    embedder = ArkMultimodalTextEmbedder(
        api_key=ark_runtime_config.api_key,
        model=ark_runtime_config.model,
        dimensions=ark_runtime_config.dimensions,
    )
    vector_index = _build_vector_index(settings, embedder)
    answerer = OpenAIResponsesAnswerer(
        api_key=openai_runtime_config.api_key,
        base_url=openai_runtime_config.base_url,
        model=openai_runtime_config.model,
        reasoning_effort=openai_runtime_config.reasoning_effort,
        store=openai_runtime_config.store,
        verbosity=openai_runtime_config.verbosity,
    )
    retriever = _build_retriever(embedder, vector_index)

    return AppServices(
        settings=settings,
        ingestion_pipeline=IngestionPipeline(
            document_store=document_store,
            parser=parser,
            chunker=chunker,
            embedder=embedder,
            vector_index=vector_index,
            normalizer=normalize_text,
        ),
        retriever=retriever,
        query_service=QueryService(
            retriever=retriever,
            answerer=answerer,
        ),
        document_service=DocumentService(catalog=vector_index),
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


def get_document_service(
    services: AppServices = Depends(get_services),
) -> DocumentService:
    """提供文档目录只读服务给路由层使用。"""
    return services.document_service
