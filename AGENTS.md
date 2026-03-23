# AGENTS.md
This file provides guidance to codex when working with code in this repository.


## Project Overview
`ragflow-lite` is a personal project to build a RAG system closer to `RAGFlow`, with a focus on document import and parsing, chunking, retrieval, grounded answers, and an ingestion pipeline that can evolve over time. Work should respect the current implementation stage instead of assuming later-stage capabilities already exist.


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


## Current Working Focus
- 当前只聚焦 `txt` / `md` 的最小同步 RAG 闭环：`upload -> parse -> normalize -> chunk -> embed -> index -> retrieve -> answer`
- 优先做最小正确改动，保持 `api`、`application`、`domain`、`infrastructure` 分层清晰
- 默认优先本地可跑通方案和本地文件持久化，先把主链路做实
- 暂不提前引入 `pdf`、`Infinity` 集成、hybrid retrieval、citation、异步任务或数据库状态管理
- 不修改 `/计划` 下的内容，除非用户明确要求
