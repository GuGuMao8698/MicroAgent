# AGENTS.md

Eval contracts: see `CONTRACTS.md`.

## Directory role

Optional DeepEval workflow: goldens generation, prompt optimization, live RAG eval, and result summarization.

## Quick commands
```bash
./.venv-goldens/bin/python tests/evals/generate_goldens.py
./.venv/bin/python tests/evals/optimize_prompt.py
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw --export-all
```

## File map

- `test_rag_deepeval.py` — uploads fixtures, waits for terminal ingestion state, evaluates answers.
- `generate_goldens.py` — synthetic golden generation (isolated `.venv-goldens`).
- `optimize_prompt.py` — prompt optimization against committed goldens (main `.venv`).
- `summarize_results.py` — post-processing of raw DeepEval exports.

## Boundary rules

- Keep goldens as generated artifacts; if quality is bad, regenerate rather than hand-patch rows.
- Raw DeepEval exports and local summaries are separate artifact flows.
