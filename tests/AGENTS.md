# AGENTS.md

## 概述
这个目录负责测试、夹具和可选评估。根文档只保留跨测试树规则；具体子树按最近 `AGENTS.md` 执行。

## 快速命令
```bash
./.venv/bin/python -m pytest tests/unit/application tests/unit/infrastructure
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw --export-all
```

## 架构
```text
tests/
├── unit/          # module and boundary tests
├── integration/   # API/live main-link tests
├── evals/         # optional deepeval scripts and tests
├── fixtures/      # committed static txt/md/pdf/eval fixtures
└── eval_support.py
```

- `unit/test_eval_gating.py` tests marker/option/env gating itself and must not require the `deepeval` package.
- `fixtures/documents` holds committed sample documents only; runtime outputs and local screenshots stay out of fixtures.
- Answerer prompt source of truth is the tracked templates under `src/ragflow_lite/infrastructure/answerers/`, not inline constants.
- Manual smoke follows `docker/AGENTS.md`; do not copy compose output into tests.

## 关键约定
- Any test crossing `create_app()`, `build_services()`, `InfinityDenseVectorIndex`, `InfinityGraphCandidateIndex`, or the real retrieval path must use live Infinity and `@pytest.mark.live_infinity`.
- Do not add fake/stub/mock Infinity clients, databases, tables, query builders, or monkeypatches of `infinity.connect`.
- Default unit tests may fake Ark embedding and DeepSeek/OpenAI structured clients only at non-Infinity boundaries.
- `deepeval` tests require `@pytest.mark.deepeval`, explicit `--run-deepeval`, and real `DEEPSEEK_API_KEY`, `ARK_API_KEY`, `ARK_EMBEDDING_MODEL`.
- Goldens generation uses `./.venv-goldens/bin/python tests/evals/generate_goldens.py`; prompt optimization uses the main `./.venv/bin/python tests/evals/optimize_prompt.py`.
- Local eval summaries are post-processing artifacts; pytest does not automatically write `latest.summary.json`.
- Prefer failure-path and boundary tests over happy-path-only coverage, especially provider failure mapping, startup failure, dimension guards, dataset/catalog behavior, async ingestion state, citation/PDF page metadata, and observability.
