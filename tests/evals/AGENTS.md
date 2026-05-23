# AGENTS.md

Eval contracts: see [CONTRACTS.md](./CONTRACTS.md).

## Directory role

Optional DeepEval workflow: goldens generation, prompt optimization, live RAG eval, and result summarization.

## Quick commands
```bash
./.venv-goldens/bin/python tests/evals/generate_goldens.py
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py --draft-goldens tests/fixtures/evals/private_bootstrap_goldens.draft.json
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py --draft-goldens tests/fixtures/evals/private_bootstrap_goldens.draft.json --output-goldens tests/fixtures/evals/synthetic_goldens.json
./.venv/bin/python tests/evals/build_private_bootstrap_eval_corpus.py --snapshot tests/fixtures/documents/microrag-private-bootstrap-snapshot --mode rebuild
./.venv/bin/python tests/evals/optimize_prompt.py
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag-21-30 ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode discorag --deepeval-corpus-mode reuse --deepeval-case-range 21:30 --deepeval-case-concurrency 4
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/discorag-21-30 --query-mode discorag --export-all
```

If the DeepEval CLI does not pass custom pytest options through in a local version, use the pytest entrypoint for ranged batches. The `RAGFLOW_LITE_EVAL_QUERY_MODE` fallback only replaces `--query-mode`; it does not replace `--deepeval-case-range`.

## File map

- [test_rag_deepeval.py](test_rag_deepeval.py) — runs live RAG eval cases against reuse/fresh corpus modes.
- [generate_goldens.py](generate_goldens.py) — synthetic golden generation (isolated `.venv-goldens`).
- [build_private_bootstrap_goldens.py](build_private_bootstrap_goldens.py) — validates the frozen private-bootstrap snapshot and draft golden artifact; use `--rebuild-snapshot` only for an intentional corpus refresh.
- [build_private_bootstrap_eval_corpus.py](build_private_bootstrap_eval_corpus.py) — rebuilds the reusable private-bootstrap eval corpus.
- [optimize_prompt.py](optimize_prompt.py) — prompt optimization against committed goldens (main `.venv`).
- [summarize_results.py](summarize_results.py) — post-processing of raw DeepEval exports.

## Boundary rules

- Keep goldens as generated artifacts; if quality is bad, regenerate rather than hand-patch rows.
- Raw DeepEval exports and local summaries are separate artifact flows.
