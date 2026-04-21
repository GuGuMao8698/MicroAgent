# Deepeval Goldens Design

## Goal

Replace the hand-maintained deepeval seed dataset with checked-in artifacts generated from the local eval document set, and add an explicit prompt-optimization path that does not make normal tests heavier.

## Decisions

- `网页/deepeval/eval集` remains the upstream source set, but because `/网页/` is ignored by Git, checked-in test inputs live under `tests/fixtures/documents`.
- Goldens are generated offline with deepeval's `Synthesizer.generate_goldens_from_docs(...)` and stored as a checked-in artifact under `tests/fixtures/evals`.
- `pytest --run-deepeval` continues to consume only the generated artifact. It does not synthesize data or optimize prompts during test execution.
- Prompt optimization is also an explicit offline step. It uses deepeval `PromptOptimizer` with `GEPA`, reads the generated Goldens artifact, and writes an optimized prompt artifact.
- Runtime prompt changes stay opt-in. The application keeps the existing default answerer instructions unless an explicit prompt-artifact path is configured.
- Infinity cleanup is an explicit maintenance command, not part of the normal deepeval test path.

## Boundaries

- Remove the old JSON eval dataset and its exact-count assertions.
- Keep the existing `/api/v0/queries` deepeval test boundary.
- Keep deepeval opt-in and separate from the fast default test path.
- Do not introduce a mandatory cloud dataset push or always-on synthetic generation.
