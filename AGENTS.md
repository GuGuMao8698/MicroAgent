# AGENTS.md
This file provides guidance to codex when working with code in this repository.


## Project Overview
`ragflow-lite` is a personal project aiming to build a RAG system close to RAGFlow for complex documents, with a focus on document import and parsing, chunking, retrieval, grounded citations, and an ingestion pipeline that evolves toward async processing. The repository is still in an early planning stage, so current guidance should follow the project plan rather than assume an existing implementation.


## Technology Stack
- Backend: `FastAPI`
- Database: `PostgreSQL`
- Cache / state: `Redis`
- Retrieval engine: `Infinity`
- Embeddings: existing embedding API or local embedding service
- Deployment: `docker-compose`


## Project Progress
- `V0` : txt/md/pdf 上传、文本抽取、chunking、embedding、向量检索、回答生成 : `进行中`

- `V1` : Infinity 全文检索、hybrid retrieval、基础 citation、基础文档元数据管理 : `未开始`

- `V2` : rerank、更准确的 citation、基础 dataset 管理、基础 parser strategy、日志和错误处理 : `未开始`

- `V3` : 异步 ingestion pipeline、任务状态、失败重试、幂等、进度、基础缓存和性能指标 : `未开始`

- `V4` : OCR/layout/table、query rewrite/multi-query/eval、或平台增强方向做深 : `未开始`


## Concurrency Rules
