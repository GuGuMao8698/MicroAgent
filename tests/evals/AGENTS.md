# AGENTS.md

这个目录承接 optional DeepEval workflow: goldens generation, prompt optimization, live RAG eval and result summarization.

## 命令边界
```bash
./.venv-goldens/bin/python tests/evals/generate_goldens.py
./.venv/bin/python tests/evals/optimize_prompt.py
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw --export-all
```

- Goldens generation is isolated in `.venv-goldens`.
- Prompt optimization runs in the main `.venv` because it imports repo runtime code and consumes committed goldens.
- `test_rag_deepeval.py` is both `live_infinity` and `deepeval`; it uploads fixtures, waits for terminal ingestion state, then evaluates answers.
- Raw DeepEval exports and local summaries are separate artifact flows.

## 关键约定
- Do not make deepeval part of default pytest; it always requires explicit `--run-deepeval`.
- Real `DEEPSEEK_API_KEY`, `ARK_API_KEY`, and `ARK_EMBEDDING_MODEL` are required for live eval.
- Pytest eval runs do not automatically write local summary artifacts; run `summarize_results.py` after raw export.
- `summarize_results.py --export-all` writes rolling `latest.*` files and timestamped summary/failed/metrics history.
- Keep goldens as generated artifacts; if quality is bad, regenerate rather than hand-patching rows.
- Do not mix `.venv-goldens` dependencies into the main runtime `.venv`.
