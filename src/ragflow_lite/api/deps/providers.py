"""FastAPI 依赖组装入口。

这个模块把基础设施实现装配成应用可用的服务对象，路由层只通过依赖注入
获取流程入口，不直接感知底层实现细节。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from ragflow_lite.application import IngestionPipeline, QueryService, normalize_text
from ragflow_lite.config import Settings
from ragflow_lite.infrastructure import (
    CompositeParser,
    DeterministicHashEmbedder,
    ExtractiveAnswerer,
    FixedWindowChunker,
    LocalDocumentStore,
    LocalJsonVectorIndex,
)


@dataclass(slots=True)
class AppServices:
    """集中保存应用启动后可复用的核心服务对象。"""

    settings: Settings
    ingestion_pipeline: IngestionPipeline
    query_service: QueryService


def build_services(settings: Settings) -> AppServices:
    """按照当前 V0 架构组装依赖。

    这里显式完成“配置 -> 具体实现 -> 业务流程”的连接，便于后续替换
    parser、embedder 或 index，而不需要改动路由层。
    """
    document_store = LocalDocumentStore(settings.uploads_dir, settings.temp_dir)
    parser = CompositeParser()
    chunker = FixedWindowChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    embedder = DeterministicHashEmbedder(dimensions=settings.embedding_dimensions)
    vector_index = LocalJsonVectorIndex(settings.local_index_dir)
    answerer = ExtractiveAnswerer()

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
        query_service=QueryService(
            embedder=embedder,
            vector_index=vector_index,
            answerer=answerer,
        ),
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
