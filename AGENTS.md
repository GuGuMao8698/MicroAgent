# Project Overview
`ragflow-lite` is a personal project to build a RAG system closer to `RAGFlow`, with a focus on document import and parsing, chunking, retrieval, grounded answers, and an ingestion pipeline that can evolve over time. Work should respect the current implementation stage instead of assuming later-stage capabilities already exist.


## Technology Stack
- Backend: `FastAPI`
- Database: `PostgreSQL`
- Cache / state: `Redis`
- Retrieval engine: `Infinity`
- Embeddings: Ark text embedding
- Deployment: `docker-compose`


## Project Progress
- `V0` : txt/md/pdf 上传、文本抽取、chunking、embedding、向量检索、回答生成 : `已完成`

- `V1` : `Infinity` 全文检索、并行 sparse+dense hybrid retrieval、优先复用 `Infinity` 原生 fusion / 归一化分数、基础 citation、基础文档元数据管理 : `已完成`
  说明：默认不把外部 `rerank` 模型当作主路径，混合排序优先依赖 `Infinity` 引擎内融合分数。

- `V2` : 检索质量增强（多字段权重、轻量 rank feature，如 tag / PageRank 类结构化信号）、更准确的 citation、基础 dataset 管理、基础 parser strategy、结构化日志与错误处理基线 : `进行中`
  说明：当前已落地的 V2 基线集中在 retrieval quality、PDF 页感知 citation、基础 parser strategy、结构化日志与错误处理基线；基础 dataset 管理仍在推进。

- `V3` : 异步 ingestion pipeline、任务状态、失败重试、幂等、进度、基础缓存和性能指标、`RAPTOR` 层级摘要检索 : `未开始`
  说明：`RAPTOR` 是树状摘要增强能力，不替代基础 chunk 检索，也不等同于 `GraphRAG`。

- `V4` : OCR/layout/table、query rewrite/multi-query/eval、或平台增强方向做深 : `未开始`


## Current Working Focus
根文档这里只保留仓库级现状与边界；具体实现、测试、运行和分层约束以下级 `AGENTS.md` 为准。

- 当前默认生产主路径仍是 Infinity hybrid，相关改动继续以收敛默认路径和避免 scope 膨胀为前提。
- 当前 V2 的下一步最小增量仍是基础 dataset 管理；已落地能力不在这里重复展开实现细节。
- 未进入默认主链路的能力暂不扩 scope，包括 rerank、新公共配置、新 API 形态，以及额外的检索主路径。
- OCR/layout/table、异步 ingestion pipeline、任务状态与失败重试、基础缓存和性能指标、`RAPTOR` 等后续阶段能力继续按路线图推进，不提前塞进当前默认实现。

## Local Python Workflow
- 仓库包含本地 `.venv`；在仓库根运行 Python 相关命令时，默认使用这个环境。

## Local Secret Workflow
- 本机开发环境是 `WSL2 Debian`。`OPENAI_API_KEY`、`ARK_API_KEY` 和 `ARK_EMBEDDING_MODEL` 统一通过 `pass` 管理，不写入仓库内的 `.env` 或其它项目文件。
- 默认使用 `ragflow-lite-run` 启动服务；该脚本从 `ragflow-lite/openai`、`ragflow-lite/ark` 和 `ragflow-lite/ark-embedding-model` 读取配置，并以对应环境变量启动 `uvicorn ragflow_lite.app:app --reload`。
- `docker compose -f docker/compose.local.yml --profile observability up --build` 的 `app` 容器同样依赖宿主当前 shell 已导出的 `OPENAI_API_KEY`、`ARK_API_KEY` 和 `ARK_EMBEDDING_MODEL`；compose 不读取仓库内 `.env`。
- OpenAI key 变更时，覆盖 `pass` 中的 `ragflow-lite/openai`，然后重新执行 `ragflow-lite-run`：

```bash
read -rsp "NEW OPENAI_API_KEY: " OPENAI_API_KEY; echo
printf '%s\n' "$OPENAI_API_KEY" | pass insert -m -f ragflow-lite/openai
unset OPENAI_API_KEY
```


# cx — Semantic Code Navigation

Prefer cx over reading files. Escalate: overview → symbols → definition/references → Read tool.

## Quick reference

```
cx overview PATH                                    file or directory table of contents
cx overview DIR --full                              directory overview with signatures
cx symbols [--kind K] [--name GLOB] [--file PATH]   search symbols project-wide
cx definition --name NAME [--from PATH] [--kind K]  get a function/type body
cx references --name NAME [--file PATH] [--unique]   find all usages (--unique: one per caller)
cx lang list                                         show supported languages
cx lang add LANG [LANG...]                           install language grammars
```

Aliases: `cx o`, `cx s`, `cx d`, `cx r`

Kinds: fn, method, struct, enum, trait, type, const, class, interface, module, event

## Key patterns

- Start with `cx overview .`, drill into subdirectories — cheaper than ls + reading files
- `cx definition --name X` gives exact text for Edit tool's `old_string` without reading the whole file
- `cx references --name X --unique` shows one row per caller — use before refactoring to check blast radius
- After context compression, use `cx overview` / `cx definition` to re-orient — don't re-read full files
- Check signatures for `pub`/`export` to identify public API without reading the file

## Pagination

Default limits: definition 3, symbols 100, references 50. When truncated, stderr shows:

```
cx: 3/32 definitions for "X" | --from PATH to narrow | --offset 3 for more | --all
```

`--offset N` pages forward, `--all` bypasses, `--limit N` overrides. Narrowing with `--from`/`--file`/`--kind` is usually better than paging.

JSON: paginated → `{total, offset, limit, results: [...]}`, non-paginated → bare array.

## Missing grammars

If cx reports a missing grammar, install with `cx lang add <lang>`. Run `cx lang list` to see what's installed.
