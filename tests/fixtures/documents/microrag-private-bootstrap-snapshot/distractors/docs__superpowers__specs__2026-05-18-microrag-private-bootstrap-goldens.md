# MicroRAG Private Bootstrap Goldens

Date: 2026-05-18
Status: Draft design spec

This document specifies the first bootstrap golden dataset for MicroRAG RAG
evaluation. It is planning material, not an active runtime contract. Active
runtime and eval contracts remain in `src/ragflow_lite/**/CONTRACTS.md`,
`tests/CONTRACTS.md`, and `tests/evals/CONTRACTS.md` until implementation
lands.

## Decision

Build a small, private, authority-aware golden dataset from MicroRAG project
documents.

The first dataset should contain 20 hard cases, not a broad 60-case synthetic
set. The goal is to validate the dataset design, authority metadata, DeepEval
field mapping, and negative-case handling before scaling the corpus.

The dataset uses two document roles:

```text
authoritative source: CONTRACTS.md and AGENTS.md files
historical distractor: docs/superpowers specs and plans
```

`CONTRACTS.md` and `AGENTS.md` files are the primary source of truth for
current behavior, project workflow, local boundaries, and eval contracts.
`docs/superpowers` files are historical design material. They may be used as
distractors, evolution evidence, or stale-plan traps, but they must not justify
a claim about current runtime behavior unless that claim is also supported by
an authoritative source.

This design intentionally borrows pressure patterns from modern comprehensive
RAG benchmarks: multi-document synthesis, distractor handling, unanswerable
questions, and source authority conflicts. It does not attempt to reproduce
CRAG, TREC RAG, RAGBench, or any public benchmark.

## Current Facts

- The current DeepEval harness evaluates one `RagEvalCase` at a time by
  uploading the fixture document, querying `/api/v0/queries`, and building an
  `LLMTestCase` from the answer and returned contexts.
- The current metric set is:
  - `AnswerRelevancyMetric`
  - `FaithfulnessMetric`
  - `ContextualRelevancyMetric`
  - `ContextualPrecisionMetric`, only when `expected_output` exists
  - `ContextualRecallMetric`, only when `expected_output` exists
- DeepEval synthetic generation can produce `input` and `expected_output`, but
  it does not produce the application `actual_output`.
- DeepEval synthetic generation context is source context, not the runtime
  `retrieval_context`. Runtime `retrieval_context` must come from MicroRAG's
  actual query result.
- Multi-document RAG uses the same DeepEval `LLMTestCase` shape. Multiple
  documents appear as multiple retrieved context strings.
- DeepEval's built-in RAG metrics do not provide a complete unanswerable-case
  metric. Negative cases need an explicit case type and a custom refusal
  judgement in a later implementation slice.
- `docs/superpowers` contains many draft specs and implementation plans. These
  files often describe future work, proposed behavior, stale branches, or
  historical decisions. They are useful distractors but unsafe as default
  answer sources.

## Goals

1. Create a first 20-case private bootstrap dataset for MicroRAG evaluation.
2. Use MicroRAG-private documents so public model pretraining is less likely to
   contain the answers.
3. Make source authority explicit in every case.
4. Preserve enough metadata to distinguish answer-source evidence from
   distractor evidence.
5. Exercise multi-document reasoning for `standard` and `discorag` query modes.
6. Include negative and unanswerable cases from the start.
7. Keep the same golden set reusable across `standard` and `discorag` runs.
8. Treat generated answers as drafts until their claims are checked against
   authoritative evidence.
9. Freeze the selected source documents into a snapshot directory so this
   dataset represents one point-in-time MicroRAG knowledge base.
10. Keep generation and evidence review inside the implementation workflow;
    the user should not need to hand-author or manually review every case.

## Non-Goals

- Do not generate 60 cases in the first slice.
- Do not treat all repository Markdown files as corpus.
- Do not treat `docs/superpowers` as an active contract source.
- Do not use public reference-project docs as MicroRAG-private evidence.
- Do not include `参考项目/**`, `data/uploads/**`, converted public papers, or
  old fixture documents in the first private corpus.
- Do not replace the existing DeepEval query-mode artifact design.
- Do not add a production dependency, schema migration, CI change, or release
  workflow change in this design.
- Do not claim that DeepEval scores alone prove golden quality.
- Do not use DeepSeek-generated `expected_output` as final golden truth without
  evidence review.
- Do not require the user to manually author the 20 questions or perform
  line-by-line case review before a first draft can be produced.

## Corpus Policy

The first implementation must copy the selected corpus files into a frozen
snapshot directory before building the packed fixture or golden artifact.
Generation, review, and eval runs for this dataset must use that snapshot, not
live `CONTRACTS.md`, `AGENTS.md`, or `docs/superpowers` paths.

Recommended snapshot layout:

```text
tests/fixtures/documents/microrag-private-bootstrap-snapshot/
  authoritative/
  distractors/
  manifest.json
```

`manifest.json` should preserve each copied file's original path, snapshot
path, role, topic, status, and content hash. After the snapshot is created,
later repository documentation changes are out of scope for this dataset. A
future refresh should create a new snapshot and a new golden revision instead
of silently mutating this one.

### Authoritative Corpus

The first authoritative corpus may include:

```text
AGENTS.md
tests/AGENTS.md
tests/evals/AGENTS.md
src/ragflow_lite/AGENTS.md
src/ragflow_lite/**/AGENTS.md
src/ragflow_lite/CONTRACTS.md
src/ragflow_lite/**/CONTRACTS.md
tests/CONTRACTS.md
tests/evals/CONTRACTS.md
docker/CONTRACTS.md
```

These files may justify `expected_output` claims about:

- current runtime boundaries;
- current eval command and artifact contracts;
- local workflow constraints;
- module-level source-of-truth rules;
- query mode and DeepEval behavior already recorded in active contracts;
- current agent/runtime boundaries when recorded in active contract files.

### Historical Distractor Corpus

The first historical distractor corpus may include:

```text
docs/superpowers/specs/*.md
docs/superpowers/plans/*.md
```

These files may be used to create:

- stale-plan traps;
- old-design distractors;
- design-evolution questions;
- comparisons between planning material and active contracts.

They must not be the only support for a current-runtime claim.

### Excluded Corpus

The first private bootstrap corpus must exclude:

```text
参考项目/**
参考项目/网页/**
tests/fixtures/documents/**
data/uploads/**
MinerU_markdown_*.md
prompt生成与优化指南.md
context7.md
external/runtime-bundle/**
```

`external/runtime-bundle/**` is excluded from the first slice because it
contains copied or bundled runtime material whose source authority is mixed.
It can be reconsidered after a separate corpus review.

## Case Taxonomy

The first dataset should contain exactly 20 cases:

| Case type | Count | Purpose |
| --- | ---: | --- |
| `current_contract_qa` | 8 | Verify direct answers from authoritative contracts. |
| `multi_doc_synthesis` | 4 | Require 2-3 authoritative documents to answer fully. |
| `stale_plan_trap` | 4 | Force the answer to reject or qualify historical plan text. |
| `negative_missing_evidence` | 2 | Ask questions not answerable from authoritative sources. |
| `comparison` | 2 | Compare current contracts against historical design material. |

### `current_contract_qa`

These cases should be answerable from one or two authoritative files. They
establish the baseline that MicroRAG can answer current project-contract
questions without relying on historical plans.

The answer must not cite or depend on `docs/superpowers` when authoritative
files are sufficient.

### `multi_doc_synthesis`

These cases must require at least two authoritative files. A valid answer must
combine facts across those files and should be incomplete if only one source is
retrieved.

Examples of suitable topics:

- root working agreements plus eval-specific contracts;
- module boundary plus eval query-mode contract;
- agent runtime boundary plus answer-layer preservation;
- local workflow plus DeepEval command contract.

### `stale_plan_trap`

These cases intentionally include a historical design or plan as a distractor.
The expected answer must explain that planning material is not an active
runtime contract unless it has been reflected in active contracts or code.

Each case must include `distractor_sources` and
`why_not_answer_from_distractor`.

### `negative_missing_evidence`

These cases ask about plausible project behavior that is not supported by the
authoritative corpus. The expected answer must refuse or narrowly qualify the
answer, such as:

```text
The authoritative MicroRAG documents in this eval corpus do not establish that.
```

These cases need a future custom DeepEval metric or post-processing judgement
for refusal correctness. They should not rely only on contextual precision,
contextual recall, or faithfulness.

### `comparison`

These cases compare active contracts with historical design material. The
expected answer must separate:

```text
current contract
historical design
known uncertainty
```

This type is useful only when both sides are explicitly recorded in metadata.

## Golden Schema

The first generated artifact should remain compatible with the existing
`RagEvalCase` loader while adding metadata for source authority.

Each case should include:

```json
{
  "name": "private-bootstrap-001",
  "input": "What is the current contract for DeepEval query modes?",
  "expected_output": "...",
  "context": ["source context used to draft the golden"],
  "sourceFile": "tests/evals/CONTRACTS.md",
  "additionalMetadata": {
    "document_fixture": "microrag-private-bootstrap.md",
    "top_k": 6,
    "case_type": "multi_doc_synthesis",
    "authority_rule": "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior.",
    "required_authoritative_sources": [
      "tests/evals/CONTRACTS.md",
      "tests/CONTRACTS.md"
    ],
    "distractor_sources": [
      "docs/superpowers/specs/2026-05-18-deepeval-query-mode-artifacts-design.md"
    ],
    "why_multi_doc": "The answer must combine eval-specific mode rules with test-level gating rules.",
    "why_not_answer_from_distractor": "The spec is planning material and is not an active contract.",
    "answerability": "answerable"
  }
}
```

For unanswerable cases:

```json
{
  "additionalMetadata": {
    "case_type": "negative_missing_evidence",
    "answerability": "unanswerable",
    "acceptable_refusal": "The authoritative MicroRAG documents in this eval corpus do not establish that.",
    "required_authoritative_sources": [],
    "distractor_sources": []
  }
}
```

The existing loader currently ignores most of this metadata. That is
acceptable for the first design as long as future tooling preserves the fields
and the test harness still reads `document_fixture` and `top_k`.

## Fixture Strategy

The existing eval harness uploads one fixture document per case. A private
bootstrap dataset needs one of these implementation strategies:

1. A packed Markdown fixture that contains selected authoritative and
   historical excerpts with source headers.
2. A small set of per-source fixtures and a harness change that uploads all
   required corpus files before running each case.

The recommended first implementation is the packed Markdown fixture because it
keeps the first slice small and avoids changing the upload lifecycle.

The packed fixture must preserve source identity with stable section headers:

```markdown
# Source: tests/evals/CONTRACTS.md

...

# Source: docs/superpowers/specs/2026-05-18-deepeval-query-mode-artifacts-design.md

Status: Draft design spec
...
```

This is not ideal long-term because it weakens true document-boundary testing.
It is acceptable for the bootstrap slice if every case metadata still records
the original source paths.

## Generation Workflow

The first dataset should use a controlled, agent-owned generation workflow:

1. Copy selected authoritative and distractor files into the snapshot
   directory.
2. Build a corpus manifest from the frozen snapshot.
3. Select source groups for each target case type.
4. Use Codex to draft questions and required evidence metadata.
5. Use DeepSeek to draft `expected_output` from the specified evidence only.
6. Use Codex to review every answer claim against the recorded authoritative
   sources.
7. Reject any case whose answer relies only on `docs/superpowers` distractors.
8. Reject any multi-doc case that can be fully answered from a single source.
9. Reject any negative case that contains enough authoritative evidence to
   answer.
10. Write the final 20 cases to a draft golden artifact.
11. Run static validation against the snapshot manifest.
12. Run collect-only validation before live evaluation.

DeepSeek output is not golden truth by itself. It is only a draft answer until
the Codex evidence review passes. The user is not expected to hand-author the
questions or manually inspect every answer claim in the normal first-pass
workflow.

## DeepEval Mapping

At eval time:

- `input` maps to the user question.
- MicroRAG's `/api/v0/queries` answer maps to `actual_output`.
- `expected_output` maps to DeepEval expected output.
- MicroRAG returned context texts map to `retrieval_context`.

Synthetic generation context must not be mapped to runtime
`retrieval_context`.

The five existing metrics should remain the default for answerable cases:

```text
AnswerRelevancy
Faithfulness
ContextualRelevancy
ContextualPrecision
ContextualRecall
```

Negative cases require a later custom metric or post-processing rule for
refusal correctness. Until that exists, negative-case DeepEval scores must be
reported separately and interpreted cautiously.

## Validation Requirements

Before a live eval run, the generated artifact should pass static validation:

- exactly 20 cases;
- every case has `name`, `input`, `expected_output`, `document_fixture`, and
  `case_type`;
- every answerable case has at least one `required_authoritative_sources`
  entry;
- every `stale_plan_trap` case has at least one `distractor_sources` entry;
- every `multi_doc_synthesis` case has at least two
  `required_authoritative_sources` entries;
- every `negative_missing_evidence` case has `answerability=unanswerable` and
  `acceptable_refusal`;
- no case uses excluded corpus paths;
- every source path resolves through the frozen snapshot manifest;
- no expected answer contains a current-runtime claim supported only by
  `docs/superpowers`;
- collect-only pytest discovers all 20 cases.

The first live eval should run both modes separately:

```text
standard
discorag
```

Results should be compared only after mode-aware artifacts are present.

## Implementation Defaults

The first implementation plan should use these defaults unless the user
explicitly changes the scope:

- Add a static validator before replacing or regenerating the checked-in
  golden artifact.
- Keep negative-case refusal judgement as a case-type-specific report field in
  the first implementation. Do not add a custom `GEval` metric until the
  20-case bootstrap set has passed static review.
- Create a frozen snapshot directory for this dataset before generating the
  packed fixture or goldens.
- Store the packed fixture under a private-bootstrap-specific fixture name,
  such as `tests/fixtures/documents/microrag-private-bootstrap.md`, so it is
  not confused with older public or DeepEval-doc fixtures.
- Store the 20-case golden artifact separately during drafting, then replace
  the active fixture only after collect-only validation passes.
- Keep all generated source-authority metadata even if the current loader only
  consumes `document_fixture` and `top_k`.

## Risks

### Snapshot Drift

Live `CONTRACTS.md` and `AGENTS.md` files can change after the dataset is
created. That does not invalidate this bootstrap set, because the set is based
on a frozen snapshot. It only means the dataset represents that snapshot, not
the latest repository state. A future refresh should create a new snapshot and
new golden revision.

### Stale Plan Overweighting

If retrieval over-selects `docs/superpowers` distractors, the answerer may
produce plan-based answers. That is a useful failure signal, not a reason to
weaken the authority rule.

### Packed Fixture Bias

A packed Markdown fixture may make source boundaries less realistic. It is a
bootstrap trade-off. A future dataset should upload multiple source documents
when the harness supports it.

### Judge Blindness

DeepEval RAG metrics may score fluent refusal or plan-supported answers higher
than they deserve. Negative and stale-plan cases must be analyzed by case type,
not only by aggregate score.
