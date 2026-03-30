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
- `V0` : txt/md/pdf 上传、文本抽取、chunking、embedding、向量检索、回答生成 : `进行中`

- `V1` : Infinity 全文检索、hybrid retrieval、基础 citation、基础文档元数据管理 : `未开始`

- `V2` : rerank、更准确的 citation、基础 dataset 管理、基础 parser strategy、日志和错误处理 : `未开始`

- `V3` : 异步 ingestion pipeline、任务状态、失败重试、幂等、进度、基础缓存和性能指标 : `未开始`

- `V4` : OCR/layout/table、query rewrite/multi-query/eval、或平台增强方向做深 : `未开始`


## Current Working Focus
- 当前聚焦 `txt` / `md` / `pdf` 的最小同步 RAG 闭环：`upload -> parse -> normalize -> chunk -> embed -> index -> retrieve -> answer`
- V0 的 PDF 仅支持基础文本抽取（数字原生 PDF），不引入 OCR、layout、table 或 vision model
- 参考 RAGFlow 时优先借鉴轻量文本抽取思路，不要把 DeepDoc 或整仓依赖并入本仓库
- 当前 `embed` 阶段默认通过 Ark 文本 embedding 完成，应用启动依赖 `ARK_API_KEY` 和 `ARK_EMBEDDING_MODEL`，不再保留本地 hash fallback
- 当前 `answer` 阶段默认通过 OpenAI Responses API 完成 grounded answer，应用启动依赖 `OPENAI_API_KEY`，默认服务地址使用 `https://code.rayinai.com/v1`
- 优先做最小正确改动，保持 `api`、`application`、`domain`、`infrastructure` 分层清晰
- 默认优先本地可跑通方案和本地文件持久化，先把主链路做实
- 暂不提前引入 OCR/layout/table、`Infinity` 集成、hybrid retrieval、citation、异步任务或数据库状态管理
- 不修改 `/计划` 下的内容，除非用户明确要求

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

In this Codex sandbox, `cx` cannot use its default cache path under `~/.cache` because that location is read-only. Use the repo wrapper [tools/cx](/home/xia/ragflow-lite/tools/cx) via `bash tools/cx ...`; it redirects `XDG_CACHE_HOME` to the repo-local `/.cache` directory and pins `--root` to this repository.

## Escalation hierarchy: overview → symbols → definition / references → read

- **Understand a file's structure** → `bash tools/cx overview <file>` (~200 tokens)
- **Find symbols across the project** → `bash tools/cx symbols [--kind K] [--name GLOB] [--file PATH]`
- **Read a specific function/type** → `bash tools/cx definition --name <name>` (~500 tokens)
- **Find all usages of a symbol** → `bash tools/cx references --name <name>` before refactoring or tracing impact
- **Fall back to Read tool** only when you need the full file or surrounding context beyond the symbol body

## When to use cx instead of Read

- **Before reading a file** — run `bash tools/cx overview` first. You often don't need the full file.
- **Before editing a function** — `bash tools/cx definition --name X` gives you the exact text for Edit tool's `old_string` without reading the whole file.
- **Before refactoring** — `bash tools/cx references --name X` finds all usages so you know the impact before changing anything. Replaces the pattern of grepping then reading file after file.
- **Exploring a codebase** — use `bash tools/cx symbols` to find what you need across files, then `bash tools/cx definition` to read specific symbols. Avoid reading file after file.
- **After context compression** — if you previously read a file but the content was compressed out, use `bash tools/cx overview` to re-orient and `bash tools/cx definition` for the specific symbols you need. Don't re-read the full file.

## Quick reference

```
bash tools/cx overview PATH                                    file table of contents
bash tools/cx symbols [--kind K] [--name GLOB] [--file PATH]   search symbols project-wide
bash tools/cx definition --name NAME [--from PATH] [--kind K]  get a function/type body
bash tools/cx references --name NAME [--file PATH]             find all usages of a symbol
bash tools/cx lang list                                        show supported languages
bash tools/cx lang add LANG [LANG...]                          install language grammars
```

Short aliases: `bash tools/cx o`, `bash tools/cx s`, `bash tools/cx d`, `bash tools/cx r`

Symbol kinds: fn, method, struct, enum, trait, type, const, class, interface, module, event

Check signatures for `pub`/`export` to identify public API without reading the file.
