# AGENTS.md
This file provides guidance to codex when working with code in this repository.


## Project Overview
`ragflow-lite` is a personal project to build a RAG system closer to `RAGFlow`, with a focus on document import and parsing, chunking, retrieval, grounded answers, and an ingestion pipeline that can evolve over time. Work should respect the current implementation stage instead of assuming later-stage capabilities already exist.


## Technology Stack
- Backend: `FastAPI`
- Database: `PostgreSQL`
- Cache / state: `Redis`
- Retrieval engine: `Infinity`
- Embeddings: Ark text embedding
- Deployment: `docker-compose`


## Project Progress
- `V0` : txt/md/pdf 上传、文本抽取、chunking、embedding、向量检索、回答生成 : `进行中`

- `V1` : Infinity 全文检索、hybrid retrieval、基础 citation、基础文档元数据管理 : `未开始`

- `V2` : rerank、更准确的 citation、基础 dataset 管理、基础 parser strategy、日志和错误处理 : `未开始`

- `V3` : 异步 ingestion pipeline、任务状态、失败重试、幂等、进度、基础缓存和性能指标 : `未开始`

- `V4` : OCR/layout/table、query rewrite/multi-query/eval、或平台增强方向做深 : `未开始`


## Current Working Focus
- 当前只聚焦 `txt` / `md` 的最小同步 RAG 闭环：`upload -> parse -> normalize -> chunk -> embed -> index -> retrieve -> answer`
- 当前 `embed` 阶段默认通过 Ark 文本 embedding 完成，应用启动依赖 `ARK_API_KEY` 和 `ARK_EMBEDDING_MODEL`，不再保留本地 hash fallback
- 当前 `answer` 阶段默认通过 OpenAI Responses API 完成 grounded answer，应用启动依赖 `OPENAI_API_KEY`
- 优先做最小正确改动，保持 `api`、`application`、`domain`、`infrastructure` 分层清晰
- 默认优先本地可跑通方案和本地文件持久化，先把主链路做实
- 暂不提前引入 `pdf`、`Infinity` 集成、hybrid retrieval、citation、异步任务或数据库状态管理
- 不修改 `/计划` 下的内容，除非用户明确要求

## Local Python Workflow
- 仓库包含本地 `.venv`；在仓库根运行 Python 相关命令时，默认使用这个环境。
- 优先使用 `.venv/bin/pytest`、`.venv/bin/ruff`、`.venv/bin/basedpyright`，或在仓库根执行 `uv run ...`。
- 避免直接使用 shell 里的 `python` 或 `pytest`，它们可能解析到仓库外解释器并报出误导性的缺依赖错误，例如 `ModuleNotFoundError: fastapi`。

## Local Secret Workflow
- 当前这台机器上的本地开发环境是 `WSL2 Debian`，运行所需的 `OPENAI_API_KEY`、`ARK_API_KEY` 和 `ARK_EMBEDDING_MODEL` 不存放在仓库目录下的 `.env` 或其它项目文件中。
- 当前默认启动方式是直接执行 `ragflow-lite-run`。该命令对应本机的 `~/bin/ragflow-lite-run` 脚本，会通过 `pass show ragflow-lite/openai` 读取 key，并以 `OPENAI_API_KEY` 环境变量启动 `uvicorn ragflow_lite.app:app --reload`。
- 如果 OpenAI key 变更，使用下面的命令覆盖 `pass` 中的 `ragflow-lite/openai`，然后重新执行 `ragflow-lite-run` 重启服务：

```bash
read -rsp "NEW OPENAI_API_KEY: " OPENAI_API_KEY; echo
printf '%s\n' "$OPENAI_API_KEY" | pass insert -m -f ragflow-lite/openai
unset OPENAI_API_KEY
```
