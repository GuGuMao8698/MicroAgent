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

- `V1` : `Infinity` 全文检索、并行 sparse+dense hybrid retrieval、优先复用 `Infinity` 原生 fusion / 归一化分数、基础 citation、基础文档元数据管理 : `进行中`
  说明：近期默认不把外部 `rerank` 模型当作主路径，第一版混合排序优先依赖 `Infinity` 引擎内融合分数。

- `V2` : 检索质量增强（多字段权重、回退扩召、轻量 rank feature，如 tag / PageRank 类结构化信号）、更准确的 citation、基础 dataset 管理、基础 parser strategy、日志和错误处理 : `未开始`

- `V3` : 异步 ingestion pipeline、任务状态、失败重试、幂等、进度、基础缓存和性能指标、`RAPTOR` 层级摘要检索 : `未开始`
  说明：`RAPTOR` 是树状摘要增强能力，不替代基础 chunk 检索，也不等同于 `GraphRAG`。

- `V4` : OCR/layout/table、query rewrite/multi-query/eval、或平台增强方向做深 : `未开始`


## Current Working Focus
- 公共查询主路径已收敛到 **Infinity hybrid baseline**：`InfinityHybridRetriever` 通过 `embed_query` + `search_hybrid()` 一次调用完成全文 + dense 并行检索，复用 Infinity 原生 `weighted_sum` fusion（`weights="0.05,0.95"`，`normalize="atan"`）
- `RAGFLOW_LITE_RETRIEVAL_MODE` 已移除作为公共配置项；若环境仍设置该变量，启动时直接报错提示移除
- `VectorRetriever` 和 `InfinityFullTextRetriever` 已从生产装配中移除；`InfinityDenseVectorIndex.search()` 和 `search_text()` 保留为内部回归/诊断能力
- `LocalJsonVectorIndex` 仅保留为非默认实现
- 当前继续推进 `V1` 未完成部分：基础 inline citation 已落地（模型输出内部 `<cite:n>` token，answerer 转换为用户可见的 `[n]`，清洗越界引用，返回顺序与编号对齐）；后续继续推进基础文档元数据管理；更细的字段权重与 rank feature 留在 V2
- `V1` 的 citation 指"基于 context 编号的基础 inline citation"；`V2` 的更准确 citation 才是句子级/后处理级归属

## Local Python Workflow
- 仓库包含本地 `.venv`；在仓库根运行 Python 相关命令时，默认使用这个环境。

## Local Secret Workflow
- 本机开发环境是 `WSL2 Debian`。`OPENAI_API_KEY`、`ARK_API_KEY` 和 `ARK_EMBEDDING_MODEL` 统一通过 `pass` 管理，不写入仓库内的 `.env` 或其它项目文件。
- 默认使用 `ragflow-lite-run` 启动服务；该脚本从 `ragflow-lite/openai`、`ragflow-lite/ark` 和 `ragflow-lite/ark-embedding-model` 读取配置，并以对应环境变量启动 `uvicorn ragflow_lite.app:app --reload`。
- OpenAI key 变更时，覆盖 `pass` 中的 `ragflow-lite/openai`，然后重新执行 `ragflow-lite-run`：

```bash
read -rsp "NEW OPENAI_API_KEY: " OPENAI_API_KEY; echo
printf '%s\n' "$OPENAI_API_KEY" | pass insert -m -f ragflow-lite/openai
unset OPENAI_API_KEY
```


# cx — Semantic Code Navigation

When `cx` is available in the project, prefer it over reading files directly.

In this Codex sandbox, `cx` cannot use its default cache path under `~/.cache` because that location is read-only. Use the repo wrapper [tools/cx](/home/xia/ragflow-lite/tools/cx) via `bash tools/cx ...`; it redirects `XDG_CACHE_HOME` to the repo-local `/.cache` directory and auto-selects the current repo or the nested repo that owns the target file. An explicit `--root` still takes precedence.

## Escalation hierarchy: directory overview → file overview → symbols → definition / references → read

- **Explore a directory** → `bash tools/cx overview <dir>` (~20 tokens per entry)
- **Understand a file's structure** → `bash tools/cx overview <file>` (~200 tokens)
- **Find symbols across the project** → `bash tools/cx symbols [--kind K] [--name GLOB] [--file PATH]`
- **Read a specific function/type** → `bash tools/cx definition --name <name>` (~500 tokens)
- **Find all usages of a symbol** → `bash tools/cx references --name <name>` shows every usage with enclosing function and context
- **Check blast radius before refactoring** → `bash tools/cx references --name <name> --unique` shows one row per dependent function
- **Fall back to Read tool** only when you need the full file or surrounding context beyond the symbol body

## When to use cx instead of Read

- **Exploring a new codebase** — start with `bash tools/cx overview .` to see top-level structure, then drill into subdirectories. Cheaper than `ls` + reading files.
- **Before reading a file** — run `bash tools/cx overview` first. You often don't need the full file.
- **Before editing a function** — `bash tools/cx definition --name X` gives you the exact text for Edit tool's `old_string` without reading the whole file.
- **Before refactoring** — `bash tools/cx references --name X --unique` shows which functions depend on X (one row per caller). Use without `--unique` to see every usage with context lines.
- **Understanding how a symbol is used** — `bash tools/cx references --name X` shows each usage site with the enclosing function and the source line, so you can see if it's called, used as a type, imported, etc.
- **Exploring a codebase** — use `bash tools/cx symbols` to find what you need across files, then `bash tools/cx definition` to read specific symbols. Avoid reading file after file.
- **After context compression** — if you previously read a file but the content was compressed out, use `bash tools/cx overview` to re-orient and `bash tools/cx definition` for the specific symbols you need. Don't re-read the full file.

## Quick reference

```
bash tools/cx overview PATH                                    file or directory table of contents
bash tools/cx overview DIR --full                              directory overview with signatures
bash tools/cx symbols [--kind K] [--name GLOB] [--file PATH]   search symbols project-wide
bash tools/cx definition --name NAME [--from PATH] [--kind K]  get a function/type body
bash tools/cx references --name NAME [--file PATH] [--unique]  find all usages (--unique: one per caller)
bash tools/cx lang list                                        show supported languages
bash tools/cx lang add LANG [LANG...]                          install language grammars
```

Nested repo example: `bash tools/cx overview ragflow/rag/nlp/search.py`

Short aliases: `bash tools/cx o`, `bash tools/cx s`, `bash tools/cx d`, `bash tools/cx r`

Symbol kinds: fn, method, struct, enum, trait, type, const, class, interface, module, event

Check signatures for `pub`/`export` to identify public API without reading the file.

## Missing grammars

If `bash tools/cx` reports a missing grammar (e.g. `cx: rust grammar not installed`), install it with `bash tools/cx lang add rust`. Run `bash tools/cx lang list` to see what's installed.
