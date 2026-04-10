# Project Overview
`ragflow-lite` 是一个借鉴 `RAGFlow` 的个人 RAG 项目.

## Stack
- Backend: `FastAPI`
- Retrieval: `Infinity`
- Database / cache: `PostgreSQL` + `Redis`
- Embeddings: Ark text embedding
- Local deployment: `docker compose`

## Current Stage
- `V0`-`V2` 已完成。
- `V3` 异步 ingestion pipeline、任务状态、重试、幂等、进度、基础缓存与性能指标、`RAPTOR` 层级摘要检索。: `未开始`
- `V4` 保持探索位，包含 OCR/layout/table、query rewrite/multi-query/eval 或平台增强方向。: `未开始`

## Active Boundaries
根文档这里只保留仓库级现状与边界；具体实现、测试、运行和分层约束以下级 `AGENTS.md` 为准。
- 当前默认生产检索主路径仍是 Infinity hybrid；不要顺手引入 rerank、新公共配置、新 API 形态或额外检索主路径。

## Local Workflow
- 仓库根 Python 命令默认使用本地 `.venv`。
- 本地运行和 `docker/compose.local.yml` 都依赖宿主导出的 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL`；不要把 secret 写入仓库内 `.env`。

## Archive
- 归档索引见 [归档入口](归档/agents/README.md)。其中保留阶段账本、V2 实现快照和本地运行 / 密钥流程三类低频信息。

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
