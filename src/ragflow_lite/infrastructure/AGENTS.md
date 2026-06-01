# AGENTS.md

## 概述
这个目录实现 `domain.ports` 的底层 adapter：provider、Infinity、JSON/file storage、parser、chunker、retriever 和 answerer。

## Active Contracts
Runtime contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/infrastructure --full
rtk cx overview src/ragflow_lite/infrastructure/evidence --full
rtk cx overview src/ragflow_lite/infrastructure/vector_indexes --full
```

## 架构
```text
infrastructure/
├── answerers/       # answerer adapters and prompt templates
├── chunkers/        # fixed/recursive/academic chunking implementations
├── embedders/       # text embedding adapter
├── evidence/        # graph evidence extraction/store/index/discourse
├── ingestion/       # in-process task store/cache/runners
├── llms/            # chat completion client wrapper
├── loaders/         # currently empty compatibility package
├── media/           # local PDF media asset staging/commit/rollback/delete
├── nlp/             # RAGFlow tokenizer wrapper
├── parsers/         # txt/md/pdf (Docling-backed) parsers
├── retrievers/      # query grounding and auxiliary hybrid retrieval
├── storage/         # local document byte storage
├── vector_indexes/  # Infinity and local JSON vector indexes
└── vlm/             # optional VLM figure description adapters
```

## 关键约定
- Do not define business flow here. Infrastructure implements ports; it does not decide API shape, query mode routing, or ingestion lifecycle.
- Provider config and secrets must be injected from runtime settings/environment. Do not scatter secret reads across unrelated helpers.
- Do not log provider payloads, raw document/query text, filenames as metric labels, or full SDK responses.
- Keep provider calls, persistence, validation, tokenization, and retry policy in their nearest adapter package.
- Do not add OCR/layout/table/DeepDoc, rerank, extra embedding providers, or new primary retrieval paths unless the task explicitly opens that slice.
- If a subpackage has its own navigation file, follow that child file for local commands and file maps.
