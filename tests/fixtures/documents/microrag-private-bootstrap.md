# MicroRAG Private Bootstrap Corpus

This fixture is generated from a frozen corpus snapshot.
Use source headers and manifest metadata to preserve authority boundaries.

# Source: AGENTS.md

Role: authoritative
Status: active
Topic: root
SHA256: 29a49965b3e1da88819e9c925fa603d598ce405ba4590f331f0ad8aa2099cbe2

# Project Overview
`MicroRAG` 是一个结合了 `MiniRAG` 和 `DiscoRAG` 的个人项目；内部包名和运行时前缀等活跃契约见 [src/ragflow_lite/CONTRACTS.md](src/ragflow_lite/CONTRACTS.md)。

## Current Stage
deepeval评估.

## Local Workflow
- 仓库根 Python 命令默认使用本地 `.venv`。
- 本地运行、provider 环境和 Docker 契约见 [src/ragflow_lite/CONTRACTS.md](src/ragflow_lite/CONTRACTS.md) 与 [docker/CONTRACTS.md](docker/CONTRACTS.md)；根文档只保留入口指针。
- `AGENTS.md` / `CONTRACTS.md` 维护规范见 [docs/agent-doc-governance.md](docs/agent-doc-governance.md)；新增或移动契约前先按该文件判断模块边界。
- 用户显式提到`context7`时, read[context7.md](context7.md).

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

# Source: docker/AGENTS.md

Role: authoritative
Status: active
Topic: docker
SHA256: c98f91472c68bd2f940c56203b869b4d3f475517d6af0fc6bb4856eacb3acb1a

# AGENTS.md

## 概述
这个目录只放本地开发、observability 和手工 smoke 用的容器资产，不承接生产部署、CI 或 release。

## 本地入口
```bash
docker compose -f docker/compose.local.yml --profile observability up --build
```

## 详细约定
参见 [CONTRACTS.md](./CONTRACTS.md)。

# Source: docker/CONTRACTS.md

Role: authoritative
Status: active
Topic: docker
SHA256: 28f66775e3362df00f6fcf2fb1ede233f0684cad18ac1107138dd413aeeb41f6

# CONTRACTS.md

## Scope
Local-only development, observability, and smoke testing. Not for production, CI, or release.

## Local Compose Entrypoint
[compose.local.yml](compose.local.yml)

## Service Graph

| Service | Profile | Image | Ports | Volumes | Depends On |
|---|---|---|---|---|---|
| `infinity` | (base) | `infiniflow/infinity:v0.7.0-dev5` | `127.0.0.1:23817`, `127.0.0.1:23820` | `/tmp/ragflow-lite-infinity-data:/var/infinity` (host tmpfs) | — |
| `app` | `observability` | built from [app/Dockerfile.dev](app/Dockerfile.dev) | `8000` | `..:/workspace` (bind mount) | `infinity` |
| `prometheus` | `observability` | `prom/prometheus:v3.11.1` | `9090` | [prometheus/prometheus.yml](prometheus/prometheus.yml) (ro) | `app` |
| `loki` | `observability` | `grafana/loki:3.6.3` | `3100` | [loki/config.yml](loki/config.yml) (ro), named `loki-data` | — |
| `alloy` | `observability` | `grafana/alloy:latest` | — | [alloy/config.alloy](alloy/config.alloy) (ro), `/var/run/docker.sock` | `loki`, `app` |
| `grafana` | `observability` | `grafana/grafana:latest` | `3000` | named `grafana-data`, [grafana/provisioning](grafana/provisioning) (ro) | `prometheus`, `loki` |

## App Service Details

- **Working dir:** `/workspace`
- **Command:** `sh -lc 'set -a; . data/local.env; set +a; exec uvicorn ragflow_lite.app:app --host 0.0.0.0 --port 8000 --reload'`

## App Environment Variables (source: compose.local.yml)

| Variable | Value | Source |
|---|---|---|
| `PYTHONPATH` | `/workspace/src` | hardcoded |
| `DEEPSEEK_API_KEY` | from `data/local.env` | local env file |
| `ARK_API_KEY` | from `data/local.env` | local env file |
| `ARK_EMBEDDING_MODEL` | from `data/local.env` | local env file |
| `RAGFLOW_LITE_LOG_LEVEL` | `INFO` | hardcoded |
| `RAGFLOW_LITE_LOG_FORMAT` | `json` | hardcoded |
| `RAGFLOW_LITE_METRICS_ENABLED` | `true` | hardcoded |
| `RAGFLOW_LITE_INFINITY_HOST` | `infinity` | service name |
| `RAGFLOW_LITE_INFINITY_PORT` | `23817` | hardcoded |

### Provider Env Note
[src/ragflow_lite/config/settings.py](../src/ragflow_lite/config/settings.py) reads provider credentials from the process environment. The local observability app sources `data/local.env` before starting Uvicorn without committing secrets.

## Grafana Defaults
- Admin user/password: `admin` / `admin`
- Sign-up disabled

## Dockerfile.dev

Local development image only. Based on `python:3.13-slim`, installs `build-essential`, `gfortran`, `libopenblas-dev`, `pkg-config`, copies `pyproject.toml` and `src`, runs `pip install -e .`.

## Artifact/Secrets Rules
Do not commit `.env`, secrets, compose runtime artifacts, screenshots, or local volume contents.

# Source: docs/superpowers/plans/2026-05-08-discorag-repo-native-stabilization-plan.md

Role: distractor
Status: Ready for implementation after confirmation
Topic: 2026-05-08-discorag-repo-native-stabilization-plan
SHA256: 62e0abf17964805535b47aefd1c85fd76de5623db011366a2dbcda4dc3a15e95

# LLM-Backed DiscoRAG Repo-Native Stabilization Plan

Date: 2026-05-09
Status: Ready for implementation after confirmation
Spec: [../specs/2026-05-08-discorag-repo-native-stabilization.md](../specs/2026-05-08-discorag-repo-native-stabilization.md)

This is the execution checklist for the current DiscoRAG slice. The spec
defines target behavior. This plan defines implementation order, likely files,
acceptance criteria, and verification commands.

## Goal

Make the repo-native DiscoRAG path paper-faithful at the structural level:

```text
MiniRAG selects evidence.
LLM RST extracts local discourse structure.
LLM inter-chunk graph models cross-chunk rhetoric.
LLM blueprint planner organizes evidence.
Final answer contexts do not silently grow.
Promotion is bounded replacement.
Invalid structural output fails clearly with ProcessingError.
```

## Decisions Already Confirmed

- Blueprint planner invalid output should fail with a clear `ProcessingError`.
- Do not add query-level downgrade to MiniRAG/basic RAG in this slice.
- Fake-client prohibition is scoped to Infinity only.
- Runtime and public exports must not retain deterministic blueprint planner.
- Reusable code from the old planner may survive only as non-semantic parser,
  validator, or applicator helpers.
- Do not retain deterministic graph generation as runtime fallback.

## Guardrails

- Keep `docs/superpowers/` as local ignored planning material.
- Do not add `chunk_token_budget` work.
- Do not make `context_token_budget` a required DiscoRAG behavior.
- Do not let graph or blueprint planning query indexes, expand MiniRAG paths, or
  retrieve new chunks.
- Do not expose internal graph/planner knobs through `QueryModeRouter` or HTTP
  mode routing.
- Do not optimize p99 latency in this slice.
- Do not introduce a new small-model provider in this slice; reuse DeepSeek for
  the structurer role through explicit wiring.

## Task 0: Baseline Reconnaissance

Purpose: lock the current code surface before editing.

Read-only checks:

- All references to deterministic graph and deterministic blueprint builders.
- Provider wiring for `DiscoRAGQueryService`.
- Existing graph, blueprint, query-service, answerer, and provider tests.
- Current `AnswerBlueprint` domain shape.
- Current promotion executor/filtering behavior.
- Current structurer model settings and DeepSeek client construction patterns.
- Current contract text that will become stale after the LLM planner lands.

Likely files:

- `src/ragflow_lite/application/services/discorag_answer_blueprint_builder.py`
- `src/ragflow_lite/application/services/discorag_query_service.py`
- `src/ragflow_lite/application/services/inter_chunk_discourse_graph_builder.py`
- `src/ragflow_lite/application/services/__init__.py`
- `src/ragflow_lite/domain/models/entities.py`
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_parser.py`
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- `src/ragflow_lite/api/deps/providers.py`
- `src/ragflow_lite/config/settings.py`
- `src/ragflow_lite/CONTRACTS.md`
- `src/ragflow_lite/application/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- `tests/unit/application/test_discorag_answer_blueprint_builder.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py`
- `tests/unit/api/test_providers.py`

Acceptance:

- List every runtime/public deterministic blueprint reference to remove.
- Confirm whether old deterministic planner tests should be deleted, rewritten,
  or split into validator/applicator tests.
- Confirm current answerer fallback metadata shape.
- Confirm source-backed structurer settings names.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_answer_blueprint_builder.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/api/test_providers.py -q
```

## Task 1: LLM Blueprint Output Contract

Purpose: define and test the model-output contract before runtime wiring.

Likely files:

- New `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_parser.py`
- Possibly `src/ragflow_lite/domain/models/entities.py`
- New `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`
- Existing `tests/unit/application/test_discorag_answer_blueprint_builder.py` may
  be replaced or narrowed to non-semantic helper coverage.

Implementation notes:

- Parse strict JSON output from the planner model.
- Validate `final_answer_chunk_ids` against answer/discourse-visible chunk ids.
- Validate `chunk_roles` against compact role vocabulary.
- Validate `promotions` as replacement, not append.
- Validate `answer_constraints` and `plan_steps`.
- Validate referenced inter-chunk relation ids.
- Validate referenced RST unit ids.
- Reject duplicate final chunk ids.
- Reject final context count greater than `top_k`.
- Reject supplemental chunk inclusion without a valid replacement promotion.
- Reject unknown chunk, relation, or RST unit references.
- Raise `ProcessingError` for invalid/unusable output.

Acceptance:

- Valid planner output becomes an `AnswerBlueprint` plus metadata needed by
  bounded promotion/application.
- Invalid JSON raises `ProcessingError`.
- Unknown chunk ids raise `ProcessingError`.
- Unknown relation ids raise `ProcessingError`.
- Unknown RST unit ids raise `ProcessingError`.
- Budget overflow raises `ProcessingError`.
- Supplemental append raises `ProcessingError`.
- Replacement promotion is accepted only when it replaces an answer chunk with a
  supplemental discourse chunk.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

## Task 2: LLMDiscoRAGAnswerBlueprintBuilder

Purpose: replace deterministic blueprint generation with model-backed discourse
planning.

Likely files:

- New `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- `src/ragflow_lite/infrastructure/evidence/__init__.py`
- New `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
- `src/ragflow_lite/domain/ports.py` or equivalent port definitions, if needed

Implementation notes:

- Keep the builder protocol compatible with `DiscoRAGQueryService`:
  `build(package, graph, ...) -> AnswerBlueprint` if feasible.
- Prompt includes query, answer chunks, supplemental discourse chunks, compact
  RST structures, inter-chunk graph relations, and final answer budget.
- The builder calls the structurer model/client, not the answerer object.
- The builder uses the parser/validator from Task 1.
- Metadata records safe provider/model/reasoning-effort/builder provenance.
- No deterministic planner fallback.
- Empty planner output is invalid when answer candidates exist.

Acceptance:

- Builder calls the provided structurer client.
- Prompt/input contains answer candidates and supplemental discourse chunks.
- Prompt/input contains RST unit ids and relation projections.
- Prompt/input contains inter-chunk relation ids and labels.
- Parser failures surface as `ProcessingError`.
- No code path constructs the old deterministic blueprint planner.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

## Task 3: Runtime Wiring Replacement

Purpose: make runtime DiscoRAG use LLM graph and LLM blueprint structural
builders.

Likely files:

- `src/ragflow_lite/api/deps/providers.py`
- `src/ragflow_lite/config/settings.py`
- `src/ragflow_lite/config/__init__.py`
- `src/ragflow_lite/application/services/discorag_query_service.py`
- `src/ragflow_lite/application/services/__init__.py`
- `tests/unit/api/test_providers.py`
- `tests/unit/application/test_discorag_query_service.py`

Implementation notes:

- Wire `LLMInterChunkDiscourseGraphBuilder`.
- Wire `LLMDiscoRAGAnswerBlueprintBuilder`.
- Use explicit structurer settings while initially reusing DeepSeek.
- Keep answer model wiring separate.
- Remove deterministic blueprint planner from runtime construction.
- Remove deterministic blueprint planner from public application service export.
- Keep no fake Infinity clients; provider unit tests that need Infinity behavior
  should stay behind `--run-live-infinity`.

Acceptance:

- Provider tests assert `DiscoRAGQueryService` receives the LLM blueprint
  planner.
- Provider tests assert structurer settings are threaded to graph and blueprint
  builders.
- No runtime path wires the deterministic blueprint planner.
- No runtime path wires deterministic graph fallback.
- Public `application.services` exports do not expose deterministic blueprint or
  deterministic graph builders as active services.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

## Task 4: Remove Or Demote Deterministic Blueprint Code

Purpose: clean the old mechanical planner so it cannot be mistaken for runtime
DiscoRAG capability.

Likely files:

- `src/ragflow_lite/application/services/discorag_answer_blueprint_builder.py`
- `tests/unit/application/test_discorag_answer_blueprint_builder.py`
- `src/ragflow_lite/application/services/__init__.py`
- imports in provider/query-service tests

Implementation notes:

- Delete the deterministic planner if no helper code remains useful.
- If helper code remains useful, rename/extract it so it is clearly not a
  planner, for example:
  - `blueprint_context_applicator.py`
  - `answer_blueprint_validation.py`
- Do not retain a class whose job is to generate a blueprint from rules.
- Remove tests that assert deterministic relation-to-plan mapping.
- Replace tests with parser/validator/applicator behavior where relevant.

Acceptance:

- No runtime/public deterministic blueprint planner remains.
- No tests lock old mechanical label mapping as intended runtime behavior.
- Any remaining helper has no semantic planning responsibility.
- `rg "DiscoRAGAnswerBlueprintBuilder|Deterministic.*Blueprint"` returns only
  expected new compatibility references or no hits.

Suggested verification:

```bash
rg "DiscoRAGAnswerBlueprintBuilder|Deterministic.*Blueprint" src tests
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

## Task 5: Still-Relevant Review Findings

Purpose: fix review findings that remain relevant after replacing the planner.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
- `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
- `src/ragflow_lite/application/services/__init__.py`
- `src/ragflow_lite/CONTRACTS.md`
- related tests

Implementation notes:

- Add RST normalization alias: `sequences -> temporal_next`.
- Add test coverage for prompt-literal `sequences`.
- Add graph metadata for safe provider/model/structurer provenance.
- Tighten answerer fallback so partially invalid blueprint ids are invalid and
  observable.
- Remove stale deterministic graph export if still exposed.
- Do not patch the old deterministic blueprint append behavior unless helper
  extraction leaves a real applicator bug; the runtime planner should be gone.

Acceptance:

- RST prompt labels and normalizer labels are aligned.
- Graph metadata includes enough safe provenance to debug structurer wiring.
- Answerer fallback records partial invalidity instead of silently ignoring
  unknown ids.
- Public exports do not advertise deterministic graph/blueprint builders as
  active runtime services.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

## Task 6: Full-Chain Local Smoke

Purpose: verify repo-native DiscoRAG behavior without network calls.

Likely files:

- `tests/unit/application/test_discorag_local_smoke.py`
- fixtures/helpers near existing DiscoRAG tests

Implementation notes:

- Use mocked structurer clients for graph and blueprint model calls.
- Do not use deterministic graph or deterministic blueprint builders.
- Keep fake clients scoped to non-Infinity boundaries. No fake Infinity client.
- Build an evidence package with answer chunks plus supplemental discourse
  chunks.
- Make graph output include relation ids used by planner output.
- Make RST output include unit ids used by planner output.
- Planner output should promote a supplemental chunk by replacement.

Acceptance:

- MiniRAG/EvidencePackageBuilder creates answer and supplemental discourse
  chunks.
- LLM graph builder receives all discourse-visible chunks.
- LLM blueprint planner receives query, answer chunks, supplemental chunks, RST,
  graph, and budget.
- Final answer contexts are `<= top_k`.
- Supplemental chunk promotion is replacement, not append.
- Answerer receives `mode="discorag"` and a validated blueprint.
- Invalid planner output raises `ProcessingError`.
- Invalid graph output raises `ProcessingError`.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

## Task 7: Contract Promotion

Purpose: update active contracts only after source-backed behavior lands.

Likely files:

- `src/ragflow_lite/CONTRACTS.md`
- `src/ragflow_lite/application/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- possibly nearest config contract/guidance if config semantics require it

Rules:

- Promote only source-backed facts.
- Keep planning details in `docs/superpowers/`.
- Document that RST, inter-chunk graph, and blueprint planner are LLM-backed
  structural stages.
- Document no deterministic graph or blueprint runtime fallback.
- Document structurer model semantics and env/config surface.
- Document `ProcessingError` behavior for invalid planner output.
- Document answerer fallback as defensive, observable, and not a planner
  fallback.
- Do not document `chunk_token_budget`.
- Do not document `context_token_budget` as required DiscoRAG behavior.
- Keep `AGENTS.md` files as navigation only.

Acceptance:

- Active contracts describe current runtime behavior, not future work.
- Contract links and verification commands point to real tests.
- No stale deterministic graph or deterministic blueprint assumptions remain.
- Root provider contract lists the structurer env/config surface if active.

## Final Stabilization Gate

Run parser/builder floors:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Run application and answerer floors:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_evidence_package_builder.py \
  tests/unit/application/test_discorag_local_smoke.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Run provider wiring with live Infinity enabled:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Run the full unit suite:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Run core live Infinity checks:

```bash
.venv/bin/python -m pytest \
  tests/integration/infrastructure/test_live_infinity_core_paths.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py \
  tests/integration/api/test_live_infinity_endpoints.py \
  --run-live-infinity -q
```

Optional endpoint live gate:

```bash
.venv/bin/python -m pytest tests/integration/api/test_v0_endpoints.py --run-live-infinity -q
```

Current known risk: one endpoint test can time out while waiting for document
indexing to reach terminal state within 3 seconds. Treat that separately unless
this slice explicitly takes on live endpoint timing stabilization.

# Source: docs/superpowers/plans/2026-05-10-discorag-review-findings-remediation-plan.md

Role: distractor
Status: Ready for implementation after confirmation
Topic: 2026-05-10-discorag-review-findings-remediation-plan
SHA256: e67c71dfcd729e3a702cf564edc49a7095c5a8e38c3f82ad1d0d5ba794c97982

# DiscoRAG Review Findings Remediation Plan

Date: 2026-05-10
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-10-discorag-review-findings-remediation.md](../specs/2026-05-10-discorag-review-findings-remediation.md)

This plan fixes all review findings from the current LLM-backed DiscoRAG graph
and blueprint change set. It assumes the broader stabilization plan in
[2026-05-08-discorag-repo-native-stabilization-plan.md](2026-05-08-discorag-repo-native-stabilization-plan.md)
is already in progress.

## Goal

Make the current change set mergeable by enforcing:

```text
strict structural validation
promotion as true replacement
planner ordering preservation
end-to-end structurer config
safe structural provenance
no deterministic planner public surface
source-backed contracts
smoke tests that catch the reviewed regressions
```

## Task 0: Baseline And Regression Lock

Purpose: capture the current failing semantics before patching.

Read-only checks:

- Confirm current `git status` has staged deletion of deterministic graph
  builder/tests plus unstaged LLM graph/blueprint changes.
- Confirm current unit suite is green despite review findings.
- Confirm there is no fake Infinity client or `infinity.connect` monkeypatch.
- Identify all references to `DiscoRAGAnswerBlueprintBuilder` and decide which
  are test-local only.

Commands:

```bash
git status --short
rg "DiscoRAGAnswerBlueprintBuilder|DeterministicInterChunk|FakeInfinity|infinity\\.connect" src tests
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Acceptance:

- Current green tests are understood as insufficient coverage, not proof that
  reviewed issues are false.
- Any remaining deterministic planner usage is mapped to remove/keep-test-only.

## Task 1: Fix Runtime Promotion Application

Purpose: make LLM planner promotion actually affect final answer contexts.

Likely files:

- `src/ragflow_lite/application/services/discorag_query_service.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`

Implementation notes:

- Change `_contexts_with_bounded_promotion()` to consume
  `blueprint.metadata["promotions"]`.
- Treat each promotion as `replace_chunk_id -> with_chunk_id`.
- Look up `with_chunk_id` in `retrieval_result.metadata["supplemental_discourse_chunks"]`.
- Replace the matching original answer context in place when possible.
- Keep final context count bounded by the original context count.
- Keep a derived `promoted_chunk_ids` metadata list only for observability if
  useful, not as the source of truth.
- If a promotion references a missing supplemental chunk at runtime, do not
  invent a context; because parser should have validated ids, this should be an
  observable defensive no-op or `ProcessingError` depending on current service
  error style. Prefer `ProcessingError` if reachable in normal control flow.

Acceptance:

- A valid planner promotion inserts the supplemental chunk into final contexts.
- The replaced answer chunk is absent from final contexts.
- Context count remains `<= top_k`.
- Existing non-promotion queries are unchanged.
- Smoke hard-asserts the promoted path.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

## Task 2: Enforce Replacement Semantics In Blueprint Parser

Purpose: reject append-style planner output before runtime application.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_parser.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`

Implementation notes:

- For each valid promotion:
  - `replace_chunk_id` must be in original `answer_chunk_ids`;
  - `with_chunk_id` must be in `supplemental_chunk_ids`;
  - `with_chunk_id` must be in `final_answer_chunk_ids`;
  - `replace_chunk_id` must not be in `final_answer_chunk_ids`.
- Reject final lists that include both the replaced answer chunk and the
  supplemental chunk.
- Reject final lists that include supplemental chunks without matching
  promotion.
- Reject duplicate or conflicting promotions for the same `replace_chunk_id` or
  same `with_chunk_id`.
- Preserve structured promotions in metadata.
- Optionally derive `promoted_chunk_ids` as metadata for observability.

Acceptance:

- Valid replacement promotion passes.
- Append-style promotion fails with `ProcessingError`.
- Supplemental chunk without promotion fails.
- Promotion that replaces non-answer chunk fails.
- Promotion that inserts non-supplemental chunk fails.
- Duplicate/conflicting promotion fails.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

## Task 3: Preserve Planner Ordering When Filtering Blueprint

Purpose: ensure the answerer consumes planner ordering, not retrieval ordering.

Likely files:

- `src/ragflow_lite/application/services/discorag_query_service.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`

Implementation notes:

- In `_blueprint_for_contexts()`, build `ordered_chunk_ids` from
  `blueprint.ordered_chunk_ids` filtered to final context ids.
- Append any final context ids not covered by planner ordering in final context
  order as a defensive completion step.
- Keep `answer_context_chunk_ids` metadata in actual final context order.
- Do not reorder the actual `contexts` list unless Task 1's replacement
  requires local in-place replacement.

Acceptance:

- Answer-facing blueprint preserves planner relative order.
- Final contexts still remain bounded.
- Context metadata remains truthful about the actual context list.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

## Task 4: Make Graph Parser Strict

Purpose: align graph parsing with `ProcessingError` structural failure
semantics.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_parser.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py`

Implementation notes:

- Keep `unrelated` as the only whitelisted non-edge drop.
- Raise `ProcessingError` for:
  - non-object relation entries;
  - missing source/target/relation fields;
  - unknown relation labels;
  - unknown source/target chunk ids;
  - self references.
- Decide whether invalid confidence should clamp or fail. Existing spec allows
  confidence clamping, so keep clamping for numeric out-of-range confidence and
  treat non-numeric optional confidence as absent.
- Update tests that currently expect mixed valid/invalid payloads to pass.

Acceptance:

- Valid graph passes.
- Empty `relations: []` passes.
- `unrelated` entries are dropped without failure.
- Mixed valid + unknown chunk fails.
- Mixed valid + self reference fails.
- Mixed valid + invalid relation label fails.
- Mixed valid + missing fields fails.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py -q
```

## Task 5: Make Blueprint Parser Strict For All Structural Fields

Purpose: stop half-valid blueprint output from reaching the answerer.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_parser.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`

Implementation notes:

- `chunk_roles` must be an object if present.
- Every `chunk_roles` key must be known.
- Every role must be in the compact vocabulary.
- `answer_constraints` must be a list if present.
- Every constraint must be an object.
- Constraint `type` must be in vocabulary.
- Constraint `text` should be a string; reject non-string text.
- `plan_steps` must be a list if present.
- Every plan step must be an object.
- Plan step `text` should be a string; reject non-string text.
- Validate `source_chunk_ids` against known answer + supplemental chunk ids.
- Validate `source_relation_ids` and `source_rst_unit_ids` as today.
- Validate source id fields are lists of strings, not arbitrary iterables.

Acceptance:

- Invalid role fails.
- Invalid constraint type fails.
- Non-object constraint fails.
- Non-object plan step fails.
- Unknown `source_chunk_ids` fails.
- Wrong source id field type fails.
- Valid constraints and plan steps still produce `answer_constraints` and
  `plan_steps` strings for `AnswerBlueprint`.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

## Task 6: Route RST Through Structurer Config

Purpose: make the structurer model boundary end-to-end.

Likely files:

- `src/ragflow_lite/api/deps/providers.py`
- `src/ragflow_lite/config/settings.py`
- `tests/unit/api/test_providers.py`
- active contracts after behavior lands

Implementation notes:

- Construct `DeepSeekChatIntraChunkDiscourseExtractor` from
  `structurer_runtime_config`, not `deepseek_runtime_config`.
- Keep answerer construction on answer/deepseek runtime config.
- Ensure graph and blueprint builders continue to use the same structurer
  config.
- Update provider tests to assert RST, graph, and blueprint structural
  components share the structurer model/reasoning/base URL.

Acceptance:

- Changing `DISCORAG_STRUCTURER_*` affects RST, graph, and blueprint structural
  builders.
- Answerer config remains separate.
- Provider tests pass with `--run-live-infinity`.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

## Task 7: Add Safe Provenance Metadata

Purpose: make graph/blueprint structural outputs debuggable.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`

Implementation notes:

- Include provider/structurer provenance in `llm_metadata`.
- Use safe fields only:
  - `provider`;
  - `model`;
  - `reasoning_effort`;
  - `builder`;
  - optionally sanitized `base_url` or `base_url_host`.
- Never include API keys.
- If builder constructors currently do not accept provider name, add a default
  such as `provider="deepseek"` or thread it from provider wiring.

Acceptance:

- Graph metadata includes safe provider provenance.
- Blueprint metadata includes safe provider provenance.
- Tests assert no API key appears in metadata.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

## Task 8: Remove Deterministic Planner Public Export

Purpose: prevent accidental reuse of deterministic blueprint planning.

Likely files:

- `src/ragflow_lite/application/services/__init__.py`
- `tests/unit/application/test_discorag_answer_blueprint_builder.py`
- `tests/unit/application/test_discorag_query_service.py`

Implementation notes:

- Remove `DiscoRAGAnswerBlueprintBuilder` from
  `ragflow_lite.application.services` exports.
- If tests still need it as a stub, import it directly from its module or move
  the stub to test helpers.
- Do not wire it in providers.
- Keep any retained deterministic class explicitly documented as test-only until
  it can be deleted.

Acceptance:

- `from ragflow_lite.application.services import DiscoRAGAnswerBlueprintBuilder`
  no longer works or is no longer used in tests.
- Provider runtime still wires `LLMDiscoRAGAnswerBlueprintBuilder`.
- `rg "DiscoRAGAnswerBlueprintBuilder" src tests` shows only intentional
  direct test-stub references and contract warnings.

Suggested verification:

```bash
rg "DiscoRAGAnswerBlueprintBuilder" src tests
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_answer_blueprint_builder.py \
  tests/unit/application/test_discorag_query_service.py -q
```

## Task 9: Align RST Contract And Alias Tests

Purpose: keep contracts source-backed and make the `sequences` fix robust.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

Implementation notes:

- Either update contract to 7 explicit planning role buckets plus `context`
  fallback, or add the missing eighth role in implementation and tests.
- Preserve `sequences -> temporal_next`.
- Add mixed-case/whitespace alias coverage if normalizer is intended to be
  case/space tolerant.

Acceptance:

- Contract role count matches implementation.
- `sequences`, `Sequences`, and whitespace-padded variants behave as intended.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

## Task 10: Harden Full-Chain Smoke

Purpose: make smoke catch the exact regression found in review.

Likely files:

- `tests/unit/application/test_discorag_local_smoke.py`

Implementation notes:

- Replace conditional promotion assertion with hard assertions:
  - promoted supplemental chunk is present;
  - replaced answer chunk is absent;
  - final context count is bounded.
- Assert answer-facing blueprint preserves planner ordering.
- Assert both graph and blueprint builders are LLM-backed test doubles.

Acceptance:

- Smoke fails before Task 1 promotion fix.
- Smoke passes after promotion fix.
- Smoke does not use deterministic graph or deterministic blueprint builders.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

## Task 11: Promote Contracts After Source Fixes

Purpose: update active contracts only after code and tests prove behavior.

Likely files:

- `src/ragflow_lite/CONTRACTS.md`
- `src/ragflow_lite/application/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`

Rules:

- Document strict parser failure semantics.
- Document structured promotion replacement and runtime application.
- Document structurer config covers RST, graph, and blueprint.
- Document safe provenance metadata.
- Document deterministic planner public export removal.
- Fix stale role-count statement.
- Keep planning details out of active contracts.

Acceptance:

- Contracts describe current source-backed behavior only.
- No stale deterministic graph/blueprint assumptions remain.

## Final Verification Gate

Run focused tests:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Run provider wiring with live Infinity:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Run full unit suite:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Run whitespace check:

```bash
git diff --check && git diff --cached --check
```

Optional live integration check:

```bash
.venv/bin/python -m pytest \
  tests/integration/infrastructure/test_live_infinity_core_paths.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py \
  tests/integration/api/test_live_infinity_endpoints.py \
  --run-live-infinity -q
```

# Source: docs/superpowers/plans/2026-05-10-discorag-structurer-retry-timeout-repair-plan.md

Role: distractor
Status: Ready for implementation after confirmation
Topic: 2026-05-10-discorag-structurer-retry-timeout-repair-plan
SHA256: b3228bafb017610d868b4e1cdd5e2a563ec046db0205f0eee7e9da1527377ca7

# DiscoRAG Structurer Retry, Timeout, And Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded timeout retry, validation-error repair, and explicit MiniRAG direct-answer fallback for exhausted DiscoRAG structurer attempts without restoring deterministic runtime fallback.

**Architecture:** Keep strict parsers as the source of truth. Add message-based DeepSeek JSON calls, then let each structurer builder retry validation failures by appending a short repair turn to the existing conversation. Timeout retries start a fresh original attempt and stale attempts must not be consumed. If a structurer stage exhausts attempts, `DiscoRAGQueryService` explicitly degrades to MiniRAG-selected top_n chunks and returns user-visible error metadata.

**Tech Stack:** Python 3.13, pytest, DeepSeek Chat Completions via OpenAI-compatible SDK, existing `ProcessingError`, existing DiscoRAG graph/blueprint/RST builders.

---

Date: 2026-05-10
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-10-discorag-structurer-retry-timeout-repair.md](../specs/2026-05-10-discorag-structurer-retry-timeout-repair.md)

## File Structure

Files to modify:

- `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
  - Add message-based completion methods and request timeout support.
  - Keep existing `complete()` / `complete_json()` behavior as wrappers.
- `src/ragflow_lite/config/settings.py`
  - Add explicit structurer retry and timeout settings.
- `src/ragflow_lite/config/__init__.py`
  - Export new config fields if the project exports settings types there.
- `src/ragflow_lite/api/deps/providers.py`
  - Pass structurer retry/timeout config into RST, graph, and blueprint builders.
- `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
  - Create a small shared helper for attempt metadata and repair message assembly.
  - Keep it provider-neutral and schema-neutral.
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
  - Add bounded validation repair and timeout retry around RST extraction.
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
  - Add bounded validation repair and timeout retry around graph construction.
- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
  - Add bounded validation repair and timeout retry around blueprint planning.
- `src/ragflow_lite/application/services/discorag_query_service.py`
  - Catch exhausted structurer failures and answer with MiniRAG-selected final
    contexts plus explicit degraded-fallback metadata.
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
  - Update after behavior and tests land.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Document the explicit MiniRAG direct-answer fallback boundary.

Tests to modify or create:

- `tests/unit/infrastructure/test_deepseek_chat.py`
- `tests/unit/infrastructure/test_structurer_retry.py`
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`
- `tests/unit/api/test_providers.py`

## Task 0: Baseline Reconnaissance

Purpose: confirm the current code shape before adding retry behavior.

- [ ] **Step 1: Inspect current DeepSeek client symbols**

Run:

```bash
cx overview src/ragflow_lite/infrastructure/llms/deepseek_chat.py
cx definition --name DeepSeekChatCompletionsClient --from src/ragflow_lite/infrastructure/llms/deepseek_chat.py
```

Expected:

- `complete()` and `complete_json()` exist.
- They delegate to a synchronous `_complete()` call.
- `_complete()` builds a two-message request.

- [ ] **Step 2: Inspect current structurer builders**

Run:

```bash
cx definition --name DeepSeekChatIntraChunkDiscourseExtractor --from src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py
cx definition --name LLMInterChunkDiscourseGraphBuilder --from src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py
cx definition --name LLMDiscoRAGAnswerBlueprintBuilder --from src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py
```

Expected:

- Each builder has one LLM call and one parse/validation pass.
- No validation repair loop exists yet.

- [ ] **Step 3: Run current focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: existing tests pass before changes.

## Task 1: Add Message-Based DeepSeek JSON Calls

Purpose: let structurer builders express multi-turn validation repair while
preserving the current two-string convenience API.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat.py`

- [ ] **Step 1: Add failing tests for message-based JSON calls**

Add tests like:

```python
def test_deepseek_complete_messages_json_sends_messages_and_json_mode() -> None:
    client = _FakeOpenAIClient(content='{"ok": true}')
    llm = DeepSeekChatCompletionsClient(
        api_key="key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    result = llm.complete_messages_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Build graph."},
            {"role": "assistant", "content": '{"relations": []}'},
            {
                "role": "user",
                "content": "Previous JSON was invalid. Regenerate complete JSON.",
            },
        ],
        timeout_seconds=90,
    )

    assert result == '{"ok": true}'
    request = client.chat.completions.calls[0]
    assert request["messages"][2]["role"] == "assistant"
    assert request["response_format"] == {"type": "json_object"}
    assert request["timeout"] == 90
```

If the fake client currently stores calls in a different attribute, adapt only
the assertion plumbing, not the behavior under test.

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_chat.py::test_deepseek_complete_messages_json_sends_messages_and_json_mode -q
```

Expected: FAIL because `complete_messages_json()` does not exist.

- [ ] **Step 3: Implement message-based methods**

In `DeepSeekChatCompletionsClient`, add:

```python
def complete_messages(
    self,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float | None = None,
) -> str:
    return self._complete_messages(
        messages,
        response_format=None,
        max_tokens=None,
        timeout_seconds=timeout_seconds,
    )

def complete_messages_json(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    timeout_seconds: float | None = None,
) -> str:
    return self._complete_messages(
        _ensure_messages_json_instruction(messages),
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
```

Add helper:

```python
def _ensure_messages_json_instruction(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not messages:
        raise ProcessingError("DeepSeek messages must not be empty.")
    result = [dict(message) for message in messages]
    for message in result:
        if message.get("role") == "system":
            message["content"] = _ensure_json_instruction(message.get("content", ""))
            return result
    return [{"role": "system", "content": _DEEPSEEK_JSON_INSTRUCTION}, *result]
```

Make existing `complete()` and `complete_json()` delegate through the new
message methods:

```python
def complete(self, instructions: str, input_text: str) -> str:
    return self.complete_messages(
        [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text},
        ]
    )

def complete_json(...):
    return self.complete_messages_json(
        [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text},
        ],
        max_tokens=max_tokens,
    )
```

Implement `_complete_messages()` by moving the current request construction out
of `_complete()`:

```python
def _complete_messages(
    self,
    messages: list[dict[str, str]],
    response_format: dict[str, str] | None,
    max_tokens: int | None,
    timeout_seconds: float | None,
) -> str:
    request: dict[str, Any] = {
        "model": self.model,
        "messages": _validate_messages(messages),
        "reasoning_effort": self.reasoning_effort,
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    if response_format is not None:
        request["response_format"] = response_format
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
    if timeout_seconds is not None:
        request["timeout"] = timeout_seconds
    ...
```

Add `_validate_messages()`:

```python
def _validate_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not messages:
        raise ProcessingError("DeepSeek messages must not be empty.")
    validated: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ProcessingError(f"Invalid DeepSeek message role: {role!r}.")
        if not isinstance(content, str) or not content.strip():
            raise ProcessingError("DeepSeek message content must be non-empty text.")
        validated.append({"role": role, "content": content})
    return validated
```

- [ ] **Step 4: Run DeepSeek client tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_chat.py -q
```

Expected: all tests pass.

## Task 2: Add Structurer Retry Configuration

Purpose: expose timeout and attempt count explicitly on the structurer config
surface.

**Files:**

- Modify: `src/ragflow_lite/config/settings.py`
- Modify: `src/ragflow_lite/config/__init__.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_providers.py`

- [ ] **Step 1: Add failing settings/provider tests**

Add tests asserting:

```python
def test_discorag_structurer_retry_defaults_are_bounded() -> None:
    settings = Settings()
    assert settings.discorag_structurer_timeout_seconds == 90
    assert settings.discorag_structurer_max_attempts == 2
```

Add provider wiring assertions where existing provider tests inspect graph and
blueprint builders:

```python
assert services.discorag_query_service.inter_chunk_graph_builder.timeout_seconds == 90
assert services.discorag_query_service.inter_chunk_graph_builder.max_attempts == 2
assert services.discorag_query_service.blueprint_builder.timeout_seconds == 90
assert services.discorag_query_service.blueprint_builder.max_attempts == 2
```

If `DiscoRAGQueryService` stores collaborators under different names, use those
existing attributes rather than adding new public accessors just for tests.

- [ ] **Step 2: Run provider tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py -q
```

Expected: FAIL because retry settings or builder attributes do not exist.

- [ ] **Step 3: Add settings fields**

In `Settings`, add:

```python
discorag_structurer_timeout_seconds: float = 90.0
discorag_structurer_max_attempts: int = 2
```

If the project has a `DiscoRAGStructurerRuntimeConfig`, add matching fields:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Keep validation simple:

```python
if timeout_seconds <= 0:
    raise ValueError("discorag_structurer_timeout_seconds must be positive")
if max_attempts < 1:
    raise ValueError("discorag_structurer_max_attempts must be at least 1")
```

- [ ] **Step 4: Pass config into builders**

Update provider construction so all three structurer components receive:

```python
timeout_seconds=structurer_config.timeout_seconds
max_attempts=structurer_config.max_attempts
```

Do not pass answer-model config into the structurer retry fields.

- [ ] **Step 5: Run provider tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Expected: provider tests pass against live Infinity.

## Task 3: Add Shared Structurer Retry Helpers

Purpose: keep repair message construction and attempt metadata consistent
without hiding schema-specific validation in a generic helper.

**Files:**

- Create: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Test: `tests/unit/infrastructure/test_structurer_retry.py`

- [ ] **Step 1: Write failing helper tests**

Create tests:

```python
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptState,
    build_validation_repair_messages,
)


def test_build_validation_repair_messages_appends_short_feedback_only() -> None:
    messages = build_validation_repair_messages(
        instructions="Return graph JSON.",
        input_text="query: q\n\nCHUNK[1] id=chunk_a\ntext: Alpha",
        invalid_output='{"relations": [{"target_chunk_id": "missing"}]}',
        validation_error='target_chunk_id "missing" is unknown',
    )

    assert [m["role"] for m in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[1]["content"].startswith("query: q")
    assert messages[2]["content"].startswith('{"relations"')
    assert "target_chunk_id" in messages[3]["content"]
    assert "query: q" not in messages[3]["content"]
    assert "Regenerate one complete JSON object" in messages[3]["content"]
    assert "Do not output a patch" in messages[3]["content"]
```

Add attempt state test:

```python
def test_structurer_attempt_state_records_failures() -> None:
    state = StructurerAttemptState(stage="blueprint")
    state.record_failure("validation_error", "missing chunk role")
    assert state.attempts == 1
    assert state.repair_count == 1
    assert state.last_failure_type == "validation_error"
    assert state.safe_metadata()["structurer_repair_count"] == 1
```

- [ ] **Step 2: Run helper tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement helper module**

Create `structurer_retry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StructurerAttemptState:
    stage: str
    attempts: int = 0
    repair_count: int = 0
    timeout_count: int = 0
    last_failure_type: str | None = None
    failure_summaries: list[str] = field(default_factory=list)

    def record_failure(self, failure_type: str, message: str) -> None:
        self.attempts += 1
        self.last_failure_type = failure_type
        self.failure_summaries.append(f"{failure_type}: {message}")
        if failure_type == "validation_error":
            self.repair_count += 1
        elif failure_type == "timeout":
            self.timeout_count += 1

    def record_success_attempt(self) -> None:
        self.attempts += 1

    def safe_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "structurer_attempts": self.attempts,
            "structurer_repair_count": self.repair_count,
            "structurer_timeout_count": self.timeout_count,
        }
        if self.last_failure_type is not None:
            metadata["structurer_last_failure_type"] = self.last_failure_type
        return metadata
```

Add repair builder:

```python
def build_validation_repair_messages(
    *,
    instructions: str,
    input_text: str,
    invalid_output: str,
    validation_error: str,
) -> list[dict[str, str]]:
    feedback = (
        "Your previous JSON is invalid.\n\n"
        f"Validation error:\n- {validation_error}\n\n"
        "Regenerate one complete JSON object. Do not output a patch. "
        "Do not include markdown or prose outside the JSON object."
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
        {"role": "assistant", "content": invalid_output},
        {"role": "user", "content": feedback},
    ]
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: PASS.

## Task 4: Add Validation Repair To Blueprint Builder

Purpose: repair the highest-impact structurer stage first.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- Test: `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`

- [ ] **Step 1: Add failing validation-repair test**

Add a fake client that returns invalid then valid JSON. Example shape:

```python
def test_blueprint_builder_repairs_validation_error_with_multiturn_messages() -> None:
    client = _FakeStructurerClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead", "chunk_b": "support"},
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    blueprint = builder.build(_package_with_two_answer_chunks(), graph=_graph())

    assert blueprint.ordered_chunk_ids == ["chunk_a", "chunk_b"]
    assert len(client.calls) == 2
    repair_call = client.calls[1]
    assert repair_call["messages"][2]["role"] == "assistant"
    assert "chunk_roles" in repair_call["messages"][3]["content"]
    assert "query:" not in repair_call["messages"][3]["content"]
    assert "Do not output a patch" in repair_call["messages"][3]["content"]
```

- [ ] **Step 2: Run the new test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py::test_blueprint_builder_repairs_validation_error_with_multiturn_messages -q
```

Expected: FAIL because the builder does not retry.

- [ ] **Step 3: Add builder constructor fields**

Extend `LLMDiscoRAGAnswerBlueprintBuilder.__init__`:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Validate:

```python
if timeout_seconds <= 0:
    raise ValueError("timeout_seconds must be positive")
if max_attempts < 1:
    raise ValueError("max_attempts must be at least 1")
```

- [ ] **Step 4: Implement blueprint attempt loop**

Refactor `build()` so it constructs the original `input_text` once and calls a
private helper:

```python
raw_json = self._complete_and_repair_json(
    client=client,
    instructions=_BLUEPRINT_INSTRUCTIONS,
    input_text=input_text,
    parse=lambda candidate: parse_llm_discorag_blueprint(
        candidate,
        answer_chunk_ids=answer_chunk_ids,
        supplemental_chunk_ids=supplemental_chunk_ids,
        known_relation_ids=known_relation_ids,
        known_rst_unit_ids=known_rst_unit_ids,
        top_k=top_k,
        llm_metadata=self._provenance_metadata(),
    ),
)
```

The helper should:

```python
messages = [
    {"role": "system", "content": instructions},
    {"role": "user", "content": input_text},
]
last_error: ProcessingError | None = None
for attempt_index in range(self.max_attempts):
    raw_json = (
        client.complete_json(..., timeout_seconds=self.timeout_seconds)
        if attempt_index == 0
        else client.complete_messages_json(messages, timeout_seconds=self.timeout_seconds)
    )
    try:
        return parse(raw_json)
    except ProcessingError as exc:
        last_error = exc
        if attempt_index >= self.max_attempts - 1:
            break
        messages = build_validation_repair_messages(
            instructions=instructions,
            input_text=input_text,
            invalid_output=raw_json,
            validation_error=str(exc),
        )
raise ProcessingError(f"LLM DiscoRAG blueprint builder failed after ...") from last_error
```

Keep the repair turn short; do not append full original input to the repair user
turn.

- [ ] **Step 5: Add exhausted attempts test**

Add:

```python
def test_blueprint_builder_raises_after_repair_attempts_exhausted() -> None:
    client = _FakeStructurerClient(
        responses=[
            '{"final_answer_chunk_ids": ["chunk_a"], "chunk_roles": {}, "promotions": []}',
            '{"final_answer_chunk_ids": ["chunk_a"], "chunk_roles": {}, "promotions": []}',
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=2)

    with pytest.raises(ProcessingError, match="failed after 2 attempts"):
        builder.build(_package_with_two_answer_chunks(), graph=_graph())
```

- [ ] **Step 6: Run blueprint builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: PASS.

## Task 5: Add Validation Repair To Inter-Chunk Graph Builder

Purpose: repair graph schema failures without deterministic graph fallback.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- Test: `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`

- [ ] **Step 1: Add failing graph repair test**

Add:

```python
def test_graph_builder_repairs_unknown_target_with_multiturn_messages() -> None:
    client = _FakeStructurerClient(
        responses=[
            json.dumps(
                {
                    "relations": [
                        {
                            "source_chunk_id": "chunk_a",
                            "target_chunk_id": "missing",
                            "relation_type": "supports",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "relations": [
                        {
                            "source_chunk_id": "chunk_a",
                            "target_chunk_id": "chunk_b",
                            "relation_type": "supports",
                            "confidence": 0.8,
                        }
                    ]
                }
            ),
        ]
    )
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    graph = builder.build(_package_with_two_discourse_chunks())

    assert [rel.target_chunk_id for rel in graph.relations] == ["chunk_b"]
    assert len(client.calls) == 2
    assert "missing" in client.calls[1]["messages"][3]["content"]
    assert "query:" not in client.calls[1]["messages"][3]["content"]
```

- [ ] **Step 2: Run graph test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py::test_graph_builder_repairs_unknown_target_with_multiturn_messages -q
```

Expected: FAIL before implementation.

- [ ] **Step 3: Add constructor fields and attempt loop**

Mirror the blueprint builder fields:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Use the same repair helper:

```python
messages = build_validation_repair_messages(
    instructions=_INTER_CHUNK_INSTRUCTIONS,
    input_text=input_text,
    invalid_output=raw_json,
    validation_error=str(exc),
)
```

On success, parse with:

```python
parse_llm_inter_chunk_graph(
    raw_json,
    chunk_ids=chunk_ids,
    query=package.query,
    llm_metadata=self._provenance_metadata(),
)
```

- [ ] **Step 4: Add exhausted attempts test**

Add a test where both attempts contain an unknown target and assert:

```python
with pytest.raises(ProcessingError, match="failed after 2 attempts"):
    builder.build(package)
```

- [ ] **Step 5: Run graph builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py -q
```

Expected: PASS.

## Task 6: Add Validation Repair To RST Extractor

Purpose: repair malformed intra-chunk RST output without partial success.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- Test: `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

- [ ] **Step 1: Add failing RST repair test**

Add:

```python
def test_deepseek_discourse_extractor_repairs_unknown_chunk_id() -> None:
    client = _FakeDeepSeekClient(
        responses=[
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "missing",
                            "units": [{"text": "Bad.", "role": "main"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [{"text": "Good.", "role": "main"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            ),
        ]
    )
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    package = extractor.extract(_package())

    assert package.structures[0].canonical_chunk_id == "chunk_doc_alpha_0"
    assert len(client.calls) == 2
    assert "unknown canonical_chunk_id" in client.calls[1]["messages"][3]["content"]
    assert "canonical_chunk_id: chunk_doc_alpha_0" not in client.calls[1]["messages"][3]["content"]
```

If the existing fake client accepts a single response string, update it to
accept a response list and record calls.

- [ ] **Step 2: Run RST repair test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py::test_deepseek_discourse_extractor_repairs_unknown_chunk_id -q
```

Expected: FAIL before implementation.

- [ ] **Step 3: Add extractor constructor fields**

Add:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Keep `enabled=False` behavior unchanged: disabled extractor should return empty
structures without calling the client.

- [ ] **Step 4: Implement RST attempt loop**

The extractor should build the original input once, then:

```python
for attempt_index in range(self.max_attempts):
    raw_json = (
        client.complete_json(
            instructions=DISCOURSE_INSTRUCTIONS,
            input_text=input_text,
            timeout_seconds=self.timeout_seconds,
        )
        if attempt_index == 0
        else client.complete_messages_json(
            messages,
            timeout_seconds=self.timeout_seconds,
        )
    )
    try:
        payload = _load_payload(raw_json)
        return self._load_structures(payload, selected_items)
    except ProcessingError as exc:
        if attempt_index >= self.max_attempts - 1:
            raise ProcessingError("DeepSeek discourse extractor failed after ...") from exc
        messages = build_validation_repair_messages(
            instructions=DISCOURSE_INSTRUCTIONS,
            input_text=input_text,
            invalid_output=raw_json,
            validation_error=str(exc),
        )
```

Do not restore silent dropping of unknown chunk ids.

- [ ] **Step 5: Run RST extractor tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: PASS.

## Task 7: Add Timeout Retry Coverage

Purpose: prove timeout retries are fresh attempts and validation repair remains
separate from timeout behavior.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Modify: the three builder/extractor files if needed
- Test:
  - `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
  - `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
  - `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

- [ ] **Step 1: Add fake timeout exception**

In each relevant test file or shared test helper, define:

```python
class FakeTimeoutError(TimeoutError):
    pass
```

The fake client should raise it on the first call and return valid JSON on the
second call.

- [ ] **Step 2: Add blueprint timeout retry test**

```python
def test_blueprint_builder_retries_timeout_with_fresh_original_request() -> None:
    client = _FakeStructurerClient(
        responses=[
            FakeTimeoutError("request timed out"),
            _valid_blueprint_json(),
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    blueprint = builder.build(_package_with_two_answer_chunks(), graph=_graph())

    assert blueprint.ordered_chunk_ids
    assert len(client.calls) == 2
    assert "messages" not in client.calls[1] or len(client.calls[1]["messages"]) == 2
```

The second attempt should be a fresh original request, not a validation repair
conversation containing an assistant invalid output.

- [ ] **Step 3: Add graph and RST timeout retry tests**

Use the same pattern:

```python
responses=[FakeTimeoutError("request timed out"), valid_json]
```

Assert the second call is not a repair conversation.

- [ ] **Step 4: Implement timeout handling if needed**

In each builder/extractor attempt loop:

```python
except Exception as exc:
    if _is_timeout_error(exc):
        if attempt_index >= self.max_attempts - 1:
            raise ProcessingError("... timed out after ...") from exc
        messages = original_messages
        continue
    raise ProcessingError("... call failed: ...") from exc
```

Add a local helper in `structurer_retry.py`:

```python
def is_timeout_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    return isinstance(exc, TimeoutError) or "timeout" in name or "timedout" in name
```

If the DeepSeek client already retries timeout-like exceptions internally, keep
the builder-level timeout retry focused on timeout exceptions that escape the
client.

- [ ] **Step 5: Run timeout-focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: PASS.

## Task 8: Add Explicit MiniRAG Fallback For Exhausted Structurer Attempts

Purpose: when DiscoRAG structuring still fails after bounded retry, answer with
MiniRAG-selected `top_n` chunks and make the degraded state obvious to callers.

**Files:**

- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`

- [ ] **Step 1: Add failing query-service fallback test for blueprint exhaustion**

Add a test that makes `blueprint_builder.build()` raise `ProcessingError` after
its own retry loop has already exhausted attempts:

```python
class ExhaustedBlueprintBuilder:
    def build(self, package: IntraChunkDiscoursePackage, *, graph: InterChunkDiscourseGraph | None = None) -> AnswerBlueprint:
        raise ProcessingError(
            "LLM DiscoRAG blueprint builder failed after 2 attempts: "
            "chunk_roles keys must exactly match final_answer_chunk_ids."
        )


def test_discorag_query_service_falls_back_to_minirag_contexts_when_blueprint_exhausts() -> None:
    answer_chunks = [_chunk("chunk_a"), _chunk("chunk_b")]
    supplemental_chunk = _chunk("chunk_supplemental")
    supplemental_chunk.metadata["selected_for_answer"] = False
    supplemental_chunk.metadata["selected_for_discourse"] = True
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=ExhaustedBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    assert answerer.last_request.mode == "standard"
    assert answerer.last_request.blueprint is None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_a",
        "chunk_b",
    ]
    assert "chunk_supplemental" not in [
        chunk.chunk_id for chunk in answerer.last_request.contexts
    ]
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    error = result.metadata["discorag_error"]
    assert error["stage"] == "blueprint"
    assert error["attempts"] == 2
    assert error["max_attempts"] == 2
    assert error["user_visible"] is True
    assert "chunk_roles" in error["message"]
```

If the existing test fakes use different names, keep the same assertions and
adapt only the fixture wiring.

- [ ] **Step 2: Add failing tests for RST and graph exhaustion stages**

Add two smaller tests:

```python
class ExhaustedDiscourseExtractor:
    def extract(self, package: EvidencePackage) -> IntraChunkDiscoursePackage:
        raise ProcessingError(
            "DeepSeek discourse extractor failed after 2 attempts: "
            "unknown canonical_chunk_id 'missing'."
        )


def test_discorag_query_service_fallback_metadata_identifies_rst_stage() -> None:
    ...
    result = service.query("q", top_k=2)
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["discorag_error"]["stage"] == "rst_extraction"
    assert "canonical_chunk_id" in result.metadata["discorag_error"]["message"]
```

```python
class ExhaustedGraphBuilder:
    def build(self, package: IntraChunkDiscoursePackage) -> InterChunkDiscourseGraph:
        raise ProcessingError(
            "LLM inter-chunk graph builder failed after 2 attempts: "
            "target_chunk_id 'missing' is unknown."
        )


def test_discorag_query_service_fallback_metadata_identifies_graph_stage() -> None:
    ...
    result = service.query("q", top_k=2)
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["discorag_error"]["stage"] == "inter_chunk_graph"
    assert "target_chunk_id" in result.metadata["discorag_error"]["message"]
```

- [ ] **Step 3: Run the new fallback tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_falls_back_to_minirag_contexts_when_blueprint_exhausts \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_fallback_metadata_identifies_rst_stage \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_fallback_metadata_identifies_graph_stage -q
```

Expected: FAIL because the service currently raises `ProcessingError`.

- [ ] **Step 4: Add stage-specific exhausted failure handling**

In `DiscoRAGQueryService.query()`, keep retrieval first. Then catch
`ProcessingError` around each structurer stage separately so the service knows
which business step failed:

```python
try:
    discourse_package = self.discourse_extractor.extract(evidence_package)
except ProcessingError as exc:
    return self._answer_with_minirag_fallback(
        query=query,
        retrieval_result=retrieval_result,
        stage="rst_extraction",
        exc=exc,
        top_k=top_k,
    )

try:
    inter_chunk_graph = self.inter_chunk_graph_builder.build(discourse_package)
except ProcessingError as exc:
    return self._answer_with_minirag_fallback(
        query=query,
        retrieval_result=retrieval_result,
        stage="inter_chunk_graph",
        exc=exc,
        top_k=top_k,
    )

try:
    blueprint = self.blueprint_builder.build(discourse_package, graph=inter_chunk_graph)
except ProcessingError as exc:
    return self._answer_with_minirag_fallback(
        query=query,
        retrieval_result=retrieval_result,
        stage="blueprint",
        exc=exc,
        top_k=top_k,
    )
```

Do not catch `ProcessingError` from `_contexts_with_bounded_promotion()` or
`_blueprint_for_contexts()` in this fallback block. Those failures occur after a
supposedly valid blueprint and should stay hard failures unless explicitly
classified later.

- [ ] **Step 5: Implement fallback answer helper**

Add a private helper:

```python
def _answer_with_minirag_fallback(
    self,
    *,
    query: str,
    retrieval_result: TopologyRetrievalResult,
    stage: str,
    exc: ProcessingError,
    top_k: int,
) -> AnswerResult:
    metadata = _discorag_fallback_metadata(
        stage=stage,
        exc=exc,
        source_selection=retrieval_result.metadata.get("source_selection"),
    )
    result = self.answerer.answer(
        AnswerRequest(
            query=query,
            contexts=retrieval_result.chunks,
            mode="standard",
            blueprint=None,
            metadata=metadata,
        )
    )
    result.metadata.update(metadata)
    log_query_event(
        logger,
        logging.ERROR,
        "query_degraded_to_minirag",
        query,
        top_k,
        outcome="degraded",
        error_type=type(exc).__name__,
    )
    record_query_outcome("degraded")
    return result
```

Use `retrieval_result.chunks` exactly. Do not append
`supplemental_discourse_chunks`.

- [ ] **Step 6: Implement explicit fallback metadata helper**

Add:

```python
def _discorag_fallback_metadata(
    *,
    stage: str,
    exc: ProcessingError,
    source_selection: object,
) -> dict[str, object]:
    attempts, max_attempts, failure_type = _parse_structurer_failure(str(exc))
    return {
        "mode": "discorag",
        "answer_mode": "minirag_fallback",
        "discorag_degraded": True,
        "source_selection": source_selection,
        "discorag_error": {
            "stage": stage,
            "error_type": type(exc).__name__,
            "failure_type": failure_type,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "message": str(exc),
            "user_visible": True,
        },
    }
```

Add a conservative parser:

```python
def _parse_structurer_failure(message: str) -> tuple[int | None, int | None, str]:
    match = re.search(r"failed after (\\d+) attempts", message)
    attempts = int(match.group(1)) if match else None
    failure_type = "timeout" if "timeout" in message.lower() else "validation_error"
    return attempts, attempts, failure_type
```

If later builder exceptions expose structured metadata instead of message text,
replace this parser with structured fields. Do not block this task on a new
exception hierarchy.

- [ ] **Step 7: Run query-service tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

Expected: PASS.

## Task 9: Full-Chain Smoke For Repaired Blueprint And Explicit Fallback

Purpose: prove DiscoRAG can recover from one blueprint validation failure
without runtime deterministic repair, and can visibly degrade to MiniRAG direct
answer when structurer attempts are exhausted.

**Files:**

- Modify: `tests/unit/application/test_discorag_local_smoke.py`

- [ ] **Step 1: Add smoke fake that fails blueprint once**

Extend the smoke blueprint fake so the first output misses a role or ordering id,
and the second output is valid.

Example expected behavior:

```python
assert fake_blueprint_client.call_count == 2
assert answerer.last_request.blueprint is not None
assert answerer.last_request.blueprint.metadata["structurer_repair_count"] == 1
assert len(answerer.last_request.contexts) <= top_k
assert "promoted_supplemental_chunk" in final_context_ids
assert "replaced_answer_chunk" not in final_context_ids
```

- [ ] **Step 2: Run the smoke test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: FAIL until builder repair metadata and fake wiring are implemented.

- [ ] **Step 3: Update smoke fixture wiring**

Ensure the smoke uses:

- LLM-backed graph test double;
- LLM-backed blueprint builder or realistic fake client path;
- no deterministic graph builder;
- no deterministic blueprint planner;
- promotion still replacement-only.

- [ ] **Step 4: Run smoke test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: PASS.

- [ ] **Step 5: Add smoke for exhausted structurer fallback**

Add a smoke case where the blueprint fake fails both attempts and the service
falls back to MiniRAG-selected contexts:

```python
def test_discorag_local_smoke_falls_back_to_minirag_when_blueprint_exhausts() -> None:
    ...
    result = service.query("How should the answer be organized?", top_k=2)
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"
    assert result.metadata["discorag_error"]["user_visible"] is True
    assert [chunk.chunk_id for chunk in result.contexts] == [
        "answer_chunk_a",
        "answer_chunk_b",
    ]
```

The fallback smoke must prove supplemental discourse chunks were not appended
to final answer contexts.

- [ ] **Step 6: Run smoke test again**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: PASS.

## Task 10: Contract Promotion

Purpose: document only behavior that has landed and passed tests.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- Modify: `src/ragflow_lite/application/CONTRACTS.md` if the service boundary
  needs an explicit note.

- [ ] **Step 1: Update evidence contract**

Add source-backed wording:

```markdown
## Structurer Retry Boundary

DiscoRAG structurer calls use bounded attempts. Validation failures are repaired
by asking the same structurer model to regenerate a complete JSON object using
multi-turn context and a short validation feedback turn. Timeout retries start a
fresh original attempt. Parsers remain strict; runtime services do not patch
invalid structure.
```

Include current defaults only if they are in code:

```markdown
The default structurer timeout is 90 seconds and the default max attempts is 2.
```

- [ ] **Step 2: Update application contract only if needed**

If `DiscoRAGQueryService` behavior is unchanged, keep this short:

```markdown
`DiscoRAGQueryService` consumes validated structurer outputs. It does not
append missing blueprint chunks or repair invalid promotions. When RST, graph,
or blueprint structurer attempts are exhausted, it visibly degrades to MiniRAG
direct answer with `AnswerResult.metadata["discorag_degraded"] == True` and a
user-visible `discorag_error` block.
```

- [ ] **Step 3: Check contract wording against source**

Run:

```bash
rg "structurer.*timeout|structurer.*attempt|complete_messages_json|ProcessingError" src/ragflow_lite docs/superpowers
```

Expected: contract wording matches actual source behavior.

## Task 11: Final Verification Gate

Purpose: prove the retry/repair slice did not regress the existing DiscoRAG
stabilization work.

- [ ] **Step 1: Run focused structurer tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

Expected: PASS.

- [ ] **Step 2: Run application DiscoRAG tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Expected: PASS.

- [ ] **Step 3: Run live provider gate**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Expected: PASS against live Infinity.

- [ ] **Step 4: Run full unit suite**

Run:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Expected: PASS. Existing live-gated tests may be skipped in the non-live full
unit command.

- [ ] **Step 5: Run whitespace checks**

Run:

```bash
git diff --check && git diff --cached --check
```

Expected: no output and exit code 0.

## Self-Review Checklist

- Spec coverage:
  - Message-based DeepSeek calls: Task 1.
  - 90-second timeout config: Task 2 and Task 7.
  - Validation repair with short multi-turn feedback: Task 3, Task 4, Task 5,
    Task 6.
  - Timeout fresh attempt behavior: Task 7.
  - Exhausted structurer fallback to MiniRAG top_n contexts with explicit user
    visible error metadata: Task 8 and Task 9.
  - No `compact` mode: documented as a non-goal in the spec and omitted from
    tasks.
  - No deterministic runtime repair: Task 9 and Task 11 keep the existing
    DiscoRAG checks.
  - Contract promotion: Task 10.
- Placeholder scan:
  - No TBD or open-ended implementation placeholders remain.
  - Test names and commands are concrete.
- Type consistency:
  - `timeout_seconds` and `max_attempts` are used consistently across settings
    and builders.
  - `complete_messages_json()` is the message-based JSON entrypoint used by
    repair attempts.

# Source: docs/superpowers/plans/2026-05-10-discorag-structurer-review-remediation-plan.md

Role: distractor
Status: Ready for implementation after confirmation
Topic: 2026-05-10-discorag-structurer-review-remediation-plan
SHA256: ec5a649145ba68dc352a0a84926eb9b068d657c672b2325e7634e2edfdb47def

# DiscoRAG Structurer Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the reviewed gaps in the committed DiscoRAG structurer retry / timeout / fallback slice, then simplify leftover scaffolding without changing the accepted architecture.

**Architecture:** Keep strict parsers and LLM repair. Add structured exhausted-attempt signaling so only exhausted structurer failures degrade to MiniRAG direct answer. Make structurer timeout ownership explicit by disabling low-level DeepSeek retries for structurer calls, wire retry settings through providers, harden RST validation, and finish with small behavior-preserving simplifications.

**Tech Stack:** Python 3.13, pytest, DeepSeek Chat Completions through OpenAI-compatible SDK, existing `ProcessingError`, existing `DiscoRAGQueryService`, existing RST / graph / blueprint structurer builders.

---

Date: 2026-05-10
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-10-discorag-structurer-review-remediation.md](../specs/2026-05-10-discorag-structurer-review-remediation.md)

## File Structure

Files to modify:

- `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
  - Add `timeout_seconds` to `complete_json()`.
  - Add `max_retries` override to message/string completion methods.
  - Preserve existing retry defaults for non-structurer callers.
- `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
  - Add `StructurerAttemptsExhaustedError`.
  - Make `StructurerAttemptState` produce structured exhausted errors or trim it to the used shape.
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
  - Disable low-level retries for structurer calls.
  - Raise structured exhausted errors.
  - Validate constructor retry settings.
  - Reject missing and duplicate chunk structures.
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
  - Disable low-level retries for structurer calls.
  - Raise structured exhausted errors.
- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
  - Disable low-level retries for structurer calls.
  - Raise structured exhausted errors.
  - Remove unused `all_items` local in the simplification task.
- `src/ragflow_lite/api/deps/providers.py`
  - Pass structurer retry config into RST, graph, and blueprint builders.
- `src/ragflow_lite/application/services/discorag_query_service.py`
  - Catch only `StructurerAttemptsExhaustedError` for MiniRAG fallback.
  - Remove regex parsing of free-form error messages.
  - Record success observability for degraded fallback.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Promote final fallback boundary after code and tests pass.
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
  - Promote final retry/timeout/exhaustion boundary after code and tests pass.

Tests to modify:

- `tests/unit/infrastructure/test_deepseek_chat.py`
- `tests/unit/infrastructure/test_structurer_retry.py`
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
- `tests/unit/api/test_providers.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`

## Task 0: Baseline And Failing-Test Confirmation

Purpose: prove the reviewed issues are real before patching.

- [ ] **Step 1: Verify current unpushed range**

Run:

```bash
rtk git status --short --branch
rtk git log --oneline --max-count=12
```

Expected:

- branch is ahead of `origin/main`;
- no unrelated working-tree edits are mixed into this remediation task.

- [ ] **Step 2: Reproduce the `complete_json(timeout_seconds=...)` signature failure**

Run:

```bash
rtk .venv/bin/python - <<'PY'
from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

class _Completions:
    def create(self, **request):
        raise AssertionError("SDK should not be reached before signature is accepted")

class _Chat:
    completions = _Completions()

class _Client:
    chat = _Chat()

client = DeepSeekChatCompletionsClient(
    api_key="k",
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash",
    reasoning_effort="high",
    client=_Client(),
)
try:
    client.complete_json("Return JSON.", "{}", timeout_seconds=90)
except TypeError as exc:
    print(type(exc).__name__)
    print(exc)
PY
```

Expected before Task 1: prints `TypeError` with `unexpected keyword argument 'timeout_seconds'`.

- [ ] **Step 3: Run focused baseline tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/api/test_providers.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: current tests may pass despite the signature failure. Record the result in the handoff.

## Task 1: Fix DeepSeek Timeout API And Disable Low-Level Retry For Structurers

Purpose: make one structurer attempt equal one SDK request while preserving default DeepSeek retry behavior for non-structurer calls.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat.py`

- [ ] **Step 1: Add failing test for `complete_json(timeout_seconds=...)`**

Add:

```python
def test_complete_json_passes_timeout_through() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    result = client.complete_json("Return JSON.", "{}", timeout_seconds=90)

    assert result == '{"ok": true}'
    assert completions.requests[0]["timeout"] == 90
```

- [ ] **Step 2: Add failing test for disabling low-level retry**

Add:

```python
class _TimeoutLikeError(Exception):
    pass


def test_complete_json_can_disable_low_level_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions(
        '{"ok": true}',
        failures=[_TimeoutLikeError("request timeout")],
    )
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep",
        sleeps.append,
    )

    with pytest.raises(_TimeoutLikeError):
        client.complete_json(
            "Return JSON.",
            "{}",
            timeout_seconds=90,
            max_retries=0,
        )

    assert len(completions.requests) == 1
    assert sleeps == []
```

- [ ] **Step 3: Add control test that default retry still works**

Add:

```python
def test_complete_json_keeps_default_low_level_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions(
        '{"ok": true}',
        failures=[_TimeoutLikeError("request timeout")],
    )
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep",
        sleeps.append,
    )

    result = client.complete_json("Return JSON.", "{}", timeout_seconds=90)

    assert result == '{"ok": true}'
    assert len(completions.requests) == 2
    assert sleeps == [0.5]
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py::test_complete_json_passes_timeout_through \
  tests/unit/infrastructure/test_deepseek_chat.py::test_complete_json_can_disable_low_level_retry \
  tests/unit/infrastructure/test_deepseek_chat.py::test_complete_json_keeps_default_low_level_retry -q
```

Expected before implementation: at least the first two tests fail.

- [ ] **Step 5: Implement `timeout_seconds` and `max_retries` passthrough**

Change method signatures:

```python
def complete(
    self,
    instructions: str,
    input_text: str,
    *,
    max_retries: int | None = None,
) -> str:
    ...

def complete_json(
    self,
    instructions: str,
    input_text: str,
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str:
    ...

def complete_messages(
    self,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str:
    ...

def complete_messages_json(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str:
    ...
```

Thread `max_retries` into `_complete_messages()`:

```python
def _complete_messages(
    self,
    messages: list[dict[str, str]],
    response_format: dict[str, str] | None,
    max_tokens: int | None,
    timeout_seconds: float | None,
    max_retries: int | None,
) -> str:
    retry_limit = _MAX_DEEPSEEK_RETRIES if max_retries is None else max_retries
    if retry_limit < 0:
        raise ProcessingError("DeepSeek max_retries must be non-negative.")

    ...

    for attempt in range(retry_limit + 1):
        ...
        if attempt >= retry_limit or not _should_retry_error(exc):
            raise
```

Ensure `complete_json()` passes both values:

```python
return self.complete_messages_json(
    [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
    ],
    max_tokens=max_tokens,
    timeout_seconds=timeout_seconds,
    max_retries=max_retries,
)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_chat.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 7: Commit**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/llms/deepseek_chat.py tests/unit/infrastructure/test_deepseek_chat.py
rtk git commit -m "fix(deepseek): bound structurer timeout attempts"
```

## Task 2: Add Structured Exhausted-Attempt Exception

Purpose: replace regex-based fallback detection with an explicit exception type.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Test: `tests/unit/infrastructure/test_structurer_retry.py`

- [ ] **Step 1: Add tests for structured exhausted exception**

Add:

```python
def test_structurer_attempt_state_builds_exhausted_error() -> None:
    state = StructurerAttemptState(stage="blueprint", max_attempts=2)
    state.record_failure("validation_error", "missing role")
    state.record_failure("validation_error", "still missing role")

    error = state.exhausted_error()

    assert isinstance(error, StructurerAttemptsExhaustedError)
    assert error.stage == "blueprint"
    assert error.failure_type == "validation_error"
    assert error.attempts == 2
    assert error.max_attempts == 2
    assert "still missing role" in error.message
    assert "failed after 2 attempts" in str(error)
```

Add:

```python
def test_structurer_exhausted_error_safe_metadata() -> None:
    error = StructurerAttemptsExhaustedError(
        stage="inter_chunk_graph",
        failure_type="timeout",
        attempts=2,
        max_attempts=2,
        message="timeout",
    )

    assert error.safe_metadata() == {
        "stage": "inter_chunk_graph",
        "error_type": "StructurerAttemptsExhaustedError",
        "failure_type": "timeout",
        "attempts": 2,
        "max_attempts": 2,
        "message": "timeout",
        "user_visible": True,
    }
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: FAIL because the exception and `max_attempts` state are not implemented yet.

- [ ] **Step 3: Implement structured exception and state integration**

Add:

```python
from ragflow_lite.domain.errors import ProcessingError


class StructurerAttemptsExhaustedError(ProcessingError):
    def __init__(
        self,
        *,
        stage: str,
        failure_type: str,
        attempts: int,
        max_attempts: int,
        message: str,
    ) -> None:
        self.stage = stage
        self.failure_type = failure_type
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.message = message
        super().__init__(
            f"{stage} structurer failed after {attempts} attempts: {message}"
        )

    def safe_metadata(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "error_type": type(self).__name__,
            "failure_type": self.failure_type,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "message": self.message,
            "user_visible": True,
        }
```

Update `StructurerAttemptState`:

```python
@dataclass
class StructurerAttemptState:
    stage: str
    max_attempts: int
    attempts: int = 0
    repair_count: int = 0
    timeout_count: int = 0
    last_failure_type: str | None = None
    failure_summaries: list[str] = field(default_factory=list)

    def exhausted_error(self) -> StructurerAttemptsExhaustedError:
        failure_type = self.last_failure_type or "validation_error"
        message = self.failure_summaries[-1] if self.failure_summaries else "unknown"
        return StructurerAttemptsExhaustedError(
            stage=self.stage,
            failure_type=failure_type,
            attempts=self.attempts,
            max_attempts=self.max_attempts,
            message=message,
        )
```

- [ ] **Step 4: Update older state tests**

Where tests construct `StructurerAttemptState(stage="blueprint")`, pass
`max_attempts=2`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/evidence/structurer_retry.py tests/unit/infrastructure/test_structurer_retry.py
rtk git commit -m "feat(discorag): add structured structurer exhaustion error"
```

## Task 3: Wire Structured Exhaustion And No Low-Level Retry Into Structurers

Purpose: make RST, graph, and blueprint builders use the same explicit exhaustion semantics.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- Modify: `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- Modify: `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- Test: `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- Test: `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- Test: `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`

- [ ] **Step 1: Add tests that structurer fresh attempts disable low-level retry**

In each builder test file, assert the first fresh call records `max_retries=0`.

Example for graph:

```python
def test_graph_builder_disables_low_level_retry_for_structurer_attempts() -> None:
    client = _FakeClient(outputs=['{"relations": []}'])
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    builder.build(_make_discourse_package())

    assert client.calls[0]["max_retries"] == 0
```

Use the local fixture names in each file.

- [ ] **Step 2: Add tests that exhausted builders raise `StructurerAttemptsExhaustedError`**

Example for blueprint:

```python
def test_blueprint_builder_raises_structured_exhaustion_after_validation_failures() -> None:
    client = _FakeClient(outputs=["{}", "{}"])
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=2)

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        builder.build(_make_discourse_package(), graph=_make_graph())

    assert exc_info.value.stage == "blueprint"
    assert exc_info.value.failure_type == "validation_error"
    assert exc_info.value.attempts == 2
    assert exc_info.value.max_attempts == 2
```

Add equivalent tests for:

- RST stage: `stage == "rst_extraction"`
- graph stage: `stage == "inter_chunk_graph"`

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: FAIL until builders pass `max_retries=0` and raise the structured exception.

- [ ] **Step 4: Implement state usage in RST extractor**

Import:

```python
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptState,
    build_validation_repair_messages,
    is_timeout_error,
)
```

Add constructor guards:

```python
if timeout_seconds <= 0:
    raise ValueError("timeout_seconds must be positive")
if max_attempts < 1:
    raise ValueError("max_attempts must be at least 1")
```

Inside `extract()`:

```python
attempt_state = StructurerAttemptState(
    stage="rst_extraction",
    max_attempts=self.max_attempts,
)
```

For fresh and repair calls:

```python
raw_json = client.complete_json(
    instructions=instructions,
    input_text=input_text,
    timeout_seconds=self.timeout_seconds,
    max_retries=0,
)
```

```python
raw_json = client.complete_messages_json(
    repair_messages,
    timeout_seconds=self.timeout_seconds,
    max_retries=0,
)
```

On timeout:

```python
attempt_state.record_failure("timeout", str(exc) or "timeout")
if attempt_index >= self.max_attempts - 1:
    raise attempt_state.exhausted_error() from exc
repair_messages = None
continue
```

On validation error:

```python
attempt_state.record_failure("validation_error", str(exc))
if attempt_index >= self.max_attempts - 1:
    raise attempt_state.exhausted_error() from exc
```

On success:

```python
attempt_state.record_success_attempt()
```

Do not catch non-timeout call errors as exhausted. Continue wrapping them in
plain `ProcessingError("... call failed ...")`.

- [ ] **Step 5: Implement equivalent state usage in graph builder**

Use:

```python
attempt_state = StructurerAttemptState(
    stage="inter_chunk_graph",
    max_attempts=self.max_attempts,
)
```

Pass `max_retries=0` to both `complete_json()` and `complete_messages_json()`.

Raise `attempt_state.exhausted_error()` only after timeout or validation
attempt exhaustion.

- [ ] **Step 6: Implement equivalent state usage in blueprint builder**

Use:

```python
attempt_state = StructurerAttemptState(
    stage="blueprint",
    max_attempts=self.max_attempts,
)
```

Pass `max_retries=0` to both `complete_json()` and `complete_messages_json()`.

Raise `attempt_state.exhausted_error()` only after timeout or validation
attempt exhaustion.

- [ ] **Step 7: Run focused builder tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

Run:

```bash
rtk git add \
  src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py \
  src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py \
  src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py
rtk git commit -m "fix(discorag): use structured structurer exhaustion"
```

## Task 4: Wire Structurer Retry Config Through Providers

Purpose: make settings overrides real at runtime.

**Files:**

- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_providers.py`

- [ ] **Step 1: Add provider test for retry config wiring**

Extend `test_build_services_non_live_structurer_boundary`:

```python
settings.discorag_structurer_timeout_seconds = 12.5
settings.discorag_structurer_max_attempts = 3
```

Then assert:

```python
assert de.timeout_seconds == 12.5
assert de.max_attempts == 3
assert gb.timeout_seconds == 12.5
assert gb.max_attempts == 3
assert bb.timeout_seconds == 12.5
assert bb.max_attempts == 3
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_providers.py::test_build_services_non_live_structurer_boundary -q
```

Expected: FAIL because providers do not forward the values.

- [ ] **Step 3: Pass config into the three constructors**

In `build_services()`, update RST:

```python
discourse_extractor = DeepSeekChatIntraChunkDiscourseExtractor(
    api_key=structurer_runtime_config.api_key,
    base_url=structurer_runtime_config.base_url,
    model=structurer_runtime_config.model,
    reasoning_effort=structurer_runtime_config.reasoning_effort,
    timeout_seconds=structurer_runtime_config.timeout_seconds,
    max_attempts=structurer_runtime_config.max_attempts,
)
```

Update graph and blueprint builder constructors the same way.

- [ ] **Step 4: Run provider tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_providers.py -q
```

Expected: pass. If live Infinity tests are gated separately, do not claim live coverage from this command.

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add src/ragflow_lite/api/deps/providers.py tests/unit/api/test_providers.py
rtk git commit -m "fix(providers): wire structurer retry settings"
```

## Task 5: Harden RST Structure Coverage

Purpose: make RST validation strict enough to trigger repair for incomplete or duplicate model output.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- Test: `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

- [ ] **Step 1: Add missing-selected-chunk test**

Add:

```python
def test_discourse_extractor_rejects_missing_selected_chunk_structure() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(
            [
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [{"text": "MiniRAG retrieves chunks.", "role": "claim"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                },
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [{"text": "MiniRAG retrieves chunks.", "role": "claim"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                },
            ]
        ),
        max_attempts=2,
    )

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        extractor.extract(_make_evidence_package_with_two_selected_chunks())

    assert exc_info.value.stage == "rst_extraction"
    assert "missing" in exc_info.value.message.lower()
```

Use existing fixture names rather than introducing a second fixture style.

- [ ] **Step 2: Add duplicate-selected-chunk test**

Add:

```python
def test_discourse_extractor_rejects_duplicate_chunk_structure() -> None:
    payload = {
        "chunks": [
            {
                "canonical_chunk_id": "chunk_doc_alpha_0",
                "units": [{"text": "MiniRAG retrieves chunks.", "role": "claim"}],
                "relations": [],
                "main_unit_indexes": [0],
                "supporting_unit_indexes": [],
            },
            {
                "canonical_chunk_id": "chunk_doc_alpha_0",
                "units": [{"text": "Duplicate structure.", "role": "claim"}],
                "relations": [],
                "main_unit_indexes": [0],
                "supporting_unit_indexes": [],
            },
        ]
    }
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient([payload, payload]),
        max_attempts=2,
    )

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        extractor.extract(_make_evidence_package())

    assert "duplicate" in exc_info.value.message.lower()
```

- [ ] **Step 3: Add constructor guard tests**

Add:

```python
def test_discourse_extractor_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        DeepSeekChatIntraChunkDiscourseExtractor(timeout_seconds=0)


def test_discourse_extractor_rejects_zero_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        DeepSeekChatIntraChunkDiscourseExtractor(max_attempts=0)
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: new tests fail before implementation.

- [ ] **Step 5: Implement exact coverage validation**

Inside `_load_structures()`:

```python
items_by_id = {item.canonical_chunk_id: item for item in items}
expected_ids = set(items_by_id)
seen_ids: set[str] = set()
structures_by_id: dict[str, ChunkDiscourseStructure] = {}

for raw in payload["chunks"]:
    ...
    if canonical_chunk_id in seen_ids:
        raise ProcessingError(
            "Discourse extractor returned duplicate canonical_chunk_id "
            f"{canonical_chunk_id!r}."
        )
    seen_ids.add(canonical_chunk_id)
    ...

missing_ids = expected_ids - seen_ids
if missing_ids:
    raise ProcessingError(
        "Discourse extractor missing structures for selected chunks: "
        f"{sorted(missing_ids)!r}."
    )

extra_ids = seen_ids - expected_ids
if extra_ids:
    raise ProcessingError(
        "Discourse extractor returned unknown canonical_chunk_id values: "
        f"{sorted(extra_ids)!r}."
    )
```

Return in selected item order after validation.

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py tests/unit/infrastructure/test_deepseek_discourse_extractor.py
rtk git commit -m "fix(discorag): validate RST chunk coverage"
```

## Task 6: Narrow QueryService Fallback To Structured Exhaustion

Purpose: prevent runtime bugs and plain `ProcessingError`s from being hidden by MiniRAG fallback.

**Files:**

- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_local_smoke.py`

- [ ] **Step 1: Change existing plain ProcessingError test expectation**

Update `test_discorag_query_service_propagates_blueprint_processing_error` to:

```python
def test_discorag_query_service_propagates_blueprint_processing_error() -> None:
    answerer = RecordingAnswerer()
    error = ProcessingError("corrupt discourse plan")
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=FailingBlueprintBuilder(error=error),
        answerer=answerer,
    )

    with pytest.raises(ProcessingError) as exc_info:
        service.query("q", top_k=1)

    assert exc_info.value is error
    assert answerer.last_request is None
```

- [ ] **Step 2: Update exhausted fallback stubs to raise structured errors**

Change `_ExhaustedBlueprintBuilder`, `_ExhaustedDiscourseExtractor`, and
`_ExhaustedGraphBuilder` to raise:

```python
StructurerAttemptsExhaustedError(
    stage="blueprint",
    failure_type="validation_error",
    attempts=2,
    max_attempts=2,
    message="chunk_roles keys must exactly match final_answer_chunk_ids.",
)
```

Use the corresponding stage names for RST and graph.

- [ ] **Step 3: Add metadata test without regex dependency**

Add:

```python
def test_discorag_query_service_fallback_metadata_uses_structured_error() -> None:
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    result = service.query("q", top_k=1)

    error = result.metadata["discorag_error"]
    assert error["stage"] == "blueprint"
    assert error["error_type"] == "StructurerAttemptsExhaustedError"
    assert error["failure_type"] == "validation_error"
    assert error["attempts"] == 2
    assert error["max_attempts"] == 2
    assert error["user_visible"] is True
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

Expected: FAIL until QueryService catches the structured exception only.

- [ ] **Step 5: Implement structured catch**

Import:

```python
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptsExhaustedError,
)
```

Change catches from:

```python
except ProcessingError as exc:
```

to:

```python
except StructurerAttemptsExhaustedError as exc:
```

Delete `_parse_structurer_failure()` and remove the `re` import.

Change fallback metadata construction:

```python
def _discorag_fallback_metadata(
    *, exc: StructurerAttemptsExhaustedError, source_selection: object
) -> dict[str, object]:
    return {
        "mode": "discorag",
        "answer_mode": "minirag_fallback",
        "discorag_degraded": True,
        "source_selection": source_selection,
        "discorag_error": exc.safe_metadata(),
    }
```

Change `_answer_with_minirag_fallback()` to take only `exc`, not a separate
`stage`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: pass after smoke stubs are updated to structured exhausted errors.

- [ ] **Step 7: Commit**

Run:

```bash
rtk git add \
  src/ragflow_lite/application/services/discorag_query_service.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py
rtk git commit -m "fix(discorag): fallback only on exhausted structurer attempts"
```

## Task 7: Record Degraded Fallback As Successful Outcome

Purpose: make observability match user-facing behavior.

**Files:**

- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`

- [ ] **Step 1: Add failing metric/log test for fallback success**

Add:

```python
def test_discorag_query_service_records_success_for_minirag_fallback(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        result = service.query("q", top_k=1)

    assert result.metadata["discorag_degraded"] is True
    assert "query_succeeded" in _event_names(caplog)
    assert outcomes == ["succeeded"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_records_success_for_minirag_fallback -q
```

Expected: FAIL because fallback returns before success accounting.

- [ ] **Step 3: Factor success recording**

Add helper:

```python
def _record_success(self, query: str, top_k: int, result: AnswerResult) -> None:
    log_query_event(
        logger,
        logging.INFO,
        "query_succeeded",
        query,
        top_k,
        outcome="succeeded",
        context_count=len(result.contexts),
        degraded=result.metadata.get("discorag_degraded") is True,
    )
    record_query_outcome("succeeded")
```

Use it in normal path:

```python
self._record_success(query, top_k, result)
return result
```

Pass `top_k` into `_answer_with_minirag_fallback()` and call the helper before
returning:

```python
result.metadata.update(metadata)
self._record_success(query, top_k, result)
return result
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add src/ragflow_lite/application/services/discorag_query_service.py tests/unit/application/test_discorag_query_service.py
rtk git commit -m "fix(discorag): record degraded fallback success"
```

## Task 8: Simplify After Correctness Fixes

Purpose: remove leftover scaffolding and unused code once behavior is correct.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- Modify: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Test: focused tests from prior tasks

- [ ] **Step 1: Remove unused blueprint local**

Delete:

```python
all_items = _dedupe_items(answer_items + supplemental_items)
```

If `_dedupe_items()` has no remaining references, delete `_dedupe_items()` too.

Verify:

```bash
rtk rg -n "_dedupe_items|all_items" src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py
```

Expected: no unused `all_items`; `_dedupe_items` remains only if still used.

- [ ] **Step 2: Simplify `StructurerAttemptState` only after it is runtime-used**

Inspect:

```bash
rtk rg -n "StructurerAttemptState|safe_metadata|failure_summaries" src/ragflow_lite tests
```

If `safe_metadata()` is no longer used after structured errors are introduced,
delete it and its tests. Keep only fields used by the builders and
`exhausted_error()`.

Do not remove `StructurerAttemptsExhaustedError`.

- [ ] **Step 3: Run simplification-focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/application/test_discorag_query_service.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

Run:

```bash
rtk git add \
  src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py \
  src/ragflow_lite/infrastructure/evidence/structurer_retry.py \
  tests/unit/infrastructure/test_structurer_retry.py
rtk git commit -m "refactor(discorag): simplify structurer retry scaffolding"
```

## Task 9: Contract Promotion

Purpose: update active contracts after behavior is proven.

**Files:**

- Modify: `src/ragflow_lite/application/CONTRACTS.md`
- Modify: `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`

- [ ] **Step 1: Update infrastructure evidence contract**

Ensure the contract says:

- RST, graph, and blueprint are structurer stages.
- Validation repair is LLM-based, not deterministic.
- Timeout retry is structurer-owned.
- Structurer calls disable low-level DeepSeek retry.
- Exhausted attempts raise `StructurerAttemptsExhaustedError`.
- Plain parser `ProcessingError` inside an attempt triggers repair when attempts remain.

- [ ] **Step 2: Update application contract**

Ensure the contract says:

- `DiscoRAGQueryService` catches only `StructurerAttemptsExhaustedError` for
  MiniRAG fallback.
- Fallback contexts are exactly `retrieval_result.chunks`.
- Supplemental discourse chunks do not append to fallback contexts.
- Runtime invariant `ProcessingError`s remain hard failures.
- Fallback metadata is user-visible.

- [ ] **Step 3: Run contract residue scan**

Run:

```bash
rtk rg -n "regex|failed after \\(\\d\\+\\)|all ProcessingError|any ProcessingError|deterministic fallback|append supplemental" \
  src/ragflow_lite/application/CONTRACTS.md \
  src/ragflow_lite/infrastructure/evidence/CONTRACTS.md \
  docs/superpowers/specs/2026-05-10-discorag-structurer-review-remediation.md \
  docs/superpowers/plans/2026-05-10-discorag-structurer-review-remediation-plan.md
```

Expected: no stale wording that says fallback catches all `ProcessingError`s or
that supplemental chunks append to answer contexts.

- [ ] **Step 4: Commit**

Run:

```bash
rtk git add src/ragflow_lite/application/CONTRACTS.md src/ragflow_lite/infrastructure/evidence/CONTRACTS.md
rtk git commit -m "docs(contracts): promote structurer exhaustion boundary"
```

## Task 10: Final Verification Gate

Purpose: prove the remediation is ready to push.

- [ ] **Step 1: Run focused remediation gate**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/api/test_providers.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: pass.

- [ ] **Step 2: Run live Infinity provider gate**

Run only if local Infinity is running:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Expected: pass. If Infinity is unavailable, report this as unverified instead
of claiming live provider coverage.

- [ ] **Step 3: Run full unit suite**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit -q
```

Expected: pass.

- [ ] **Step 4: Run diff hygiene checks**

Run:

```bash
rtk git diff --check
rtk git diff --cached --check
```

Expected: both pass.

- [ ] **Step 5: Review final commit range**

Run:

```bash
rtk git log --oneline --max-count=20
rtk git status --short --branch
```

Expected:

- remediation commits sit on top of the current unpushed DiscoRAG commits;
- no accidental unstaged runtime edits remain unless intentionally left for the
  user.

## Implementation Notes

- Prefer `StructurerAttemptsExhaustedError` over string predicates. A string
  predicate is acceptable only as an emergency stopgap and should not survive
  the final plan.
- Do not catch `ProcessingError` broadly in `DiscoRAGQueryService` for fallback.
- Do not re-enable deterministic graph or blueprint fallback.
- Do not change the answerer fallback behavior in this slice except as required
  by tests that observe MiniRAG fallback metadata.
- Keep commits task-sized so review can bisect easily.

# Source: docs/superpowers/plans/2026-05-11-chunk-auxiliary-legacy-field-removal.md

Role: distractor
Status: historical
Topic: 2026-05-11-chunk-auxiliary-legacy-field-removal
SHA256: e6b6292379adcf9f577f6364e51aa24ee1acdbe0b5fa30cc63d48b47b4282f7b

# Chunk Auxiliary Legacy Field Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove legacy `filename^10,text` sparse matching from chunk auxiliary retrieval while rejecting legacy chunk schemas before they can break query execution.

**Architecture:** Keep `chunks.filename` and `chunks.text` as storage columns, but remove them from the default chunk auxiliary `match_text` field list. Tighten `InfinityDenseVectorIndex` initialization so chunk tables without `filename_kwd`, `filename_tks`, `content_tks`, `content_sm_tks`, or their fulltext indexes fail fast. Leave MiniRAG graph candidate retrieval untouched.

**Tech Stack:** Python, pytest, Infinity SDK, existing `rtk` command wrapper.

---

## File Structure

- Modify: `src/ragflow_lite/infrastructure/vector_indexes/chunk_text_fields.py`
  - Owns chunk auxiliary text field constants and field generation.
- Modify: `src/ragflow_lite/infrastructure/vector_indexes/infinity_dense_index.py`
  - Owns Infinity chunk table schema, fulltext index creation, schema validation, and `search_hybrid()`.
- Modify: `tests/unit/infrastructure/test_chunk_text_fields.py`
  - Unit coverage for chunk text field generation and default sparse field string.
- Modify: `tests/unit/infrastructure/test_infinity_dense_index.py`
  - Unit coverage for `ChunkHybridRetrievalConfig` defaults.
- Modify: `tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py`
  - Convert legacy compatibility validation into legacy schema rejection validation.
- Optional Modify: `src/ragflow_lite/infrastructure/vector_indexes/CONTRACTS.md`
  - Only if implementation changes need a nearby active runtime contract update.

## Task 1: Remove Legacy Field String From Unit Contract

**Files:**
- Modify: `tests/unit/infrastructure/test_chunk_text_fields.py`
- Modify: `tests/unit/infrastructure/test_infinity_dense_index.py`
- Modify: `src/ragflow_lite/infrastructure/vector_indexes/chunk_text_fields.py`

- [ ] **Step 1: Update the field-string unit test expectation**

In `tests/unit/infrastructure/test_chunk_text_fields.py`, change
`test_chunk_match_text_fields_are_localized_ragflow_boosts` to assert only the
tokenizer-derived fields:

```python
def test_chunk_match_text_fields_are_localized_ragflow_boosts() -> None:
    assert (
        fields.CHUNK_FIELD_MATCH_TEXT_FIELDS
        == "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
    )
```

- [ ] **Step 2: Update the config default unit test expectation**

In `tests/unit/infrastructure/test_infinity_dense_index.py`, change
`test_chunk_hybrid_config_defaults_match_spec` to assert the same default:

```python
def test_chunk_hybrid_config_defaults_match_spec() -> None:
    config = ChunkHybridRetrievalConfig()

    assert config.initial_recall_n == 1024
    assert config.text_weight == 0.05
    assert config.dense_weight == 0.95
    assert config.minimum_should_match == 0.3
    assert config.dense_similarity_threshold == 0.2
    assert config.fusion_normalize == "atan"
    assert config.position_prior_weight == 0.03
    assert config.position_prior_enabled is True
    assert (
        config.match_text_fields
        == "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
    )
```

- [ ] **Step 3: Run the two tests and verify they fail before implementation**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_chunk_text_fields.py::test_chunk_match_text_fields_are_localized_ragflow_boosts \
  tests/unit/infrastructure/test_infinity_dense_index.py::test_chunk_hybrid_config_defaults_match_spec -q
```

Expected: both tests fail because `CHUNK_FIELD_MATCH_TEXT_FIELDS` still
contains `filename^10,text`.

- [ ] **Step 4: Remove the legacy fallback from the runtime field constant**

In `src/ragflow_lite/infrastructure/vector_indexes/chunk_text_fields.py`,
replace the current legacy constant composition with:

```python
CHUNK_FIELD_MATCH_TEXT_FIELDS = (
    "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
)
```

Remove `CHUNK_LEGACY_MATCH_TEXT_FIELDS` unless another non-runtime test still
needs it. If it remains, name it clearly so it cannot be confused with the
active default, for example:

```python
LEGACY_CHUNK_MATCH_TEXT_FIELDS_FOR_TESTS = "filename^10,text"
```

Do not use the legacy constant in `CHUNK_FIELD_MATCH_TEXT_FIELDS`.

- [ ] **Step 5: Run the focused unit tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_chunk_text_fields.py \
  tests/unit/infrastructure/test_infinity_dense_index.py -q
```

Expected: all tests in both files pass.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
rtk git add \
  src/ragflow_lite/infrastructure/vector_indexes/chunk_text_fields.py \
  tests/unit/infrastructure/test_chunk_text_fields.py \
  tests/unit/infrastructure/test_infinity_dense_index.py
rtk git commit -m "refactor: remove legacy chunk match fields"
```

## Task 2: Add Fail-Fast Schema Validation For Chunk Auxiliary Fields

**Files:**
- Modify: `src/ragflow_lite/infrastructure/vector_indexes/infinity_dense_index.py`
- Test: `tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py`

- [ ] **Step 1: Convert the live legacy compatibility test into a rejection test**

In `tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py`,
rename `test_legacy_chunk_table_creates_only_legacy_indexes` to:

```python
def test_legacy_chunk_table_is_rejected_when_auxiliary_fields_are_missing(
    app_settings: Settings,
) -> None:
```

Replace the body after the manual legacy table creation with an assertion that
constructing `InfinityDenseVectorIndex` fails:

```python
        with pytest.raises(
            RuntimeError,
            match=(
                "Chunk table .* is missing required auxiliary text columns"
                "|Chunk table .* is missing required fulltext indexes"
            ),
        ):
            InfinityDenseVectorIndex(
                host=app_settings.infinity_host,
                port=app_settings.infinity_port,
                database=app_settings.infinity_database,
                document_table=doc_table,
                chunk_table=chunk_table,
                embedding_dimensions=8,
                embedding_signature=_LEGACY_EMBEDDING_SIGNATURE,
            )
```

Remove assertions that legacy indexes exist or that new-column indexes are
absent. The new contract is rejection, not partial compatibility.

- [ ] **Step 2: Run the converted live test and verify it fails before implementation**

Run:

```bash
rtk .venv/bin/python -m pytest --run-live-infinity \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py::test_legacy_chunk_table_is_rejected_when_auxiliary_fields_are_missing -q
```

Expected before implementation: the test fails because
`InfinityDenseVectorIndex` still accepts a legacy table by filtering required
indexes down to existing columns.

- [ ] **Step 3: Add required auxiliary column constants**

In `src/ragflow_lite/infrastructure/vector_indexes/infinity_dense_index.py`,
near the existing module constants, add:

```python
_REQUIRED_CHUNK_AUXILIARY_TEXT_COLUMNS = {
    "filename_kwd",
    "filename_tks",
    "content_tks",
    "content_sm_tks",
}
```

If the file already has a better local constants section, place it there.

- [ ] **Step 4: Add a required column validation helper**

In `InfinityDenseVectorIndex`, add this method near
`_validate_chunk_table_dimensions()`:

```python
    def _validate_chunk_auxiliary_text_columns(self) -> None:
        """Require tokenizer-derived chunk text columns for auxiliary retrieval."""
        available_columns = self._chunk_column_names()
        missing_columns = sorted(
            _REQUIRED_CHUNK_AUXILIARY_TEXT_COLUMNS - available_columns
        )
        if missing_columns:
            raise RuntimeError(
                f"Chunk table '{self._chunk_table}' is missing required auxiliary "
                f"text columns: {', '.join(missing_columns)}. "
                "Drop and recreate the table, or re-ingest documents with the "
                "current chunk auxiliary schema."
            )
```

- [ ] **Step 5: Call the column validation during table setup**

In `_ensure_tables()`, after `_validate_chunk_table_dimensions()` and before
`_ensure_fulltext_index()`, call:

```python
        self._validate_chunk_table_dimensions()
        self._validate_chunk_auxiliary_text_columns()
        self._ensure_fulltext_index()
```

Do not remove `_validate_chunk_table_dimensions()`.

- [ ] **Step 6: Make fulltext index creation strict for active columns**

In `_ensure_fulltext_index()`, remove the migration-window filtering block:

```python
            # 迁移窗口：只为表中实际存在的列创建全文索引。
            available_columns = self._chunk_column_names()
            required_indexes = {
                index_name: column_name
                for index_name, column_name in required_indexes.items()
                if column_name in available_columns
            }
```

Keep `required_indexes` as the full active set:

```python
            required_indexes = {
                f"{self._chunk_table}_text_fulltext_idx": "text",
                f"{self._chunk_table}_filename_fulltext_idx": "filename",
                f"{self._chunk_table}_filename_kwd_fulltext_idx": "filename_kwd",
                f"{self._chunk_table}_filename_tks_fulltext_idx": "filename_tks",
                f"{self._chunk_table}_content_tks_fulltext_idx": "content_tks",
                f"{self._chunk_table}_content_sm_tks_fulltext_idx": "content_sm_tks",
            }
```

Rationale: `text` and `filename` remain stored columns and can keep fulltext
indexes if already part of the schema, but they are no longer query-time
fallback fields in `CHUNK_FIELD_MATCH_TEXT_FIELDS`.

- [ ] **Step 7: Run the converted legacy rejection test**

Run:

```bash
rtk .venv/bin/python -m pytest --run-live-infinity \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py::test_legacy_chunk_table_is_rejected_when_auxiliary_fields_are_missing -q
```

Expected: pass. The legacy table should be rejected before any query can run.

- [ ] **Step 8: Run focused unit tests again**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_chunk_text_fields.py \
  tests/unit/infrastructure/test_infinity_dense_index.py \
  tests/unit/infrastructure/test_infinity_hybrid_retriever.py -q
```

Expected: pass.

- [ ] **Step 9: Commit Task 2**

Run:

```bash
rtk git add \
  src/ragflow_lite/infrastructure/vector_indexes/infinity_dense_index.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py
rtk git commit -m "fix: reject legacy chunk auxiliary schema"
```

## Task 3: Verify Retrieval Flow Still Works On Current Schema

**Files:**
- No planned production edits.
- Possible test-only adjustment if live tests reveal ranking assumptions tied
  to removed legacy fields.

- [ ] **Step 1: Run live Infinity core path tests**

Run:

```bash
rtk .venv/bin/python -m pytest --run-live-infinity \
  tests/integration/infrastructure/test_live_infinity_core_paths.py -q
```

Expected: pass. If
`test_live_dense_index_covers_document_dataset_and_retrieval_lifecycle` fails
only because chunk ranking changed, inspect whether the old assertion relied
on raw `filename` or `text` fallback scoring. Do not weaken assertions until
the actual returned chunks and metadata have been inspected.

- [ ] **Step 2: Run API integration tests that exercise upload and query**

Run:

```bash
rtk .venv/bin/python -m pytest --run-live-infinity \
  tests/integration/api/test_v0_endpoints.py \
  tests/integration/api/test_live_infinity_endpoints.py -q
```

Expected: pass. Pay close attention to:

```text
test_upload_markdown_then_query_uses_markdown_text
test_filename_sparse_recalls_when_text_misses
test_real_infinity_handles_upload_and_query
```

Filename-only sparse recall should still work through `filename_kwd` and
`filename_tks`.

- [ ] **Step 3: If filename sparse recall fails, inspect the inserted chunk row**

If `test_filename_sparse_recalls_when_text_misses` fails, inspect whether the
new chunk row contains populated tokenizer fields before changing scoring:

```python
table = vector_index._db.get_table(vector_index._chunk_table)
rows = vector_index._table_rows(
    table,
    [
        "chunk_id",
        "filename",
        "filename_kwd",
        "filename_tks",
        "content_tks",
        "content_sm_tks",
    ],
)
```

Expected: `filename_kwd` equals the filename and `filename_tks` is non-empty.
If those fields are empty, fix field generation or write path. If they are
populated but ranking changed, adjust only the test expectation that depended
on legacy fallback weighting.

- [ ] **Step 4: Run MiniGraphFirstRetriever unit tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: pass. These tests use fake auxiliary retrievers and should confirm
the graph-first merge and source selection behavior is unchanged.

- [ ] **Step 5: Commit any retrieval-flow test adjustments**

Only if Task 3 required test expectation changes, run:

```bash
rtk git add tests/integration tests/unit/application
rtk git commit -m "test: update chunk auxiliary retrieval expectations"
```

If no files changed, skip this commit.

## Task 4: Update Nearby Runtime Contract If Needed

**Files:**
- Optional Modify: `src/ragflow_lite/infrastructure/vector_indexes/CONTRACTS.md`
- Optional Modify: nearest existing contract file if the vector index contract
  is documented elsewhere.

- [ ] **Step 1: Check for an existing vector index contract file**

Run:

```bash
rtk ls src/ragflow_lite/infrastructure/vector_indexes
rtk rg -n "chunk auxiliary|CHUNK_FIELD_MATCH_TEXT_FIELDS|filename_kwd|content_tks|legacy" \
  src/ragflow_lite/infrastructure src/ragflow_lite/application
```

Expected: identify whether a nearby `CONTRACTS.md` already documents chunk
auxiliary fields or legacy compatibility.

- [ ] **Step 2: Update only the nearest active contract if it exists**

If `src/ragflow_lite/infrastructure/vector_indexes/CONTRACTS.md` exists, add a
short active contract section:

```markdown
## Chunk Auxiliary Text Fields

Owner: `InfinityDenseVectorIndex`, `chunk_text_fields.py`

Source of truth:
- Default chunk auxiliary `match_text` uses only tokenizer-derived fields:
  `filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks`.
- `filename` and `text` remain stored columns, but are not default
  `match_text` fallback fields.
- Chunk tables missing `filename_kwd`, `filename_tks`, `content_tks`, or
  `content_sm_tks` are incompatible and must fail during initialization.

Verification:
- `tests/unit/infrastructure/test_chunk_text_fields.py`
- `tests/unit/infrastructure/test_infinity_dense_index.py`
- `tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py`
```

If no vector-index-specific contract file exists, update the nearest existing
infrastructure contract with the same concise section. Do not add a broad root
`AGENTS.md` note for this detail.

- [ ] **Step 3: Run documentation sanity check**

Run:

```bash
rtk rg -n "filename\\^10,text|legacy chunk table remains|filename / text chunk table remains|old schema compatible" \
  src docs tests
```

Expected: no active runtime contract should still say legacy chunk schema is
compatible. Test files may mention legacy schema only as rejected behavior.

- [ ] **Step 4: Commit contract update if any file changed**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure
rtk git commit -m "docs: document chunk auxiliary field contract"
```

If no contract file needed an update, skip this commit.

## Task 5: Final Verification

**Files:**
- No planned edits.

- [ ] **Step 1: Run focused local verification**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_chunk_text_fields.py \
  tests/unit/infrastructure/test_infinity_dense_index.py \
  tests/unit/infrastructure/test_infinity_hybrid_retriever.py \
  tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: pass.

- [ ] **Step 2: Run live Infinity regression verification**

Run:

```bash
rtk .venv/bin/python -m pytest --run-live-infinity \
  tests/integration/infrastructure/test_live_infinity_core_paths.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py \
  tests/integration/api/test_v0_endpoints.py \
  tests/integration/api/test_live_infinity_endpoints.py -q
```

Expected: pass. If the local Infinity service is not running, record the exact
failure and do not claim live verification passed.

- [ ] **Step 3: Optional deepeval verification**

Run only if retrieval quality drift validation is requested for this slice:

```bash
rtk .venv/bin/python -m pytest --run-deepeval \
  tests/evals/test_rag_deepeval.py -q
```

Expected: pass, or document metric/context drift explicitly.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
rtk git diff --stat
rtk git diff -- src tests docs
```

Expected:

- `CHUNK_FIELD_MATCH_TEXT_FIELDS` no longer contains `filename^10,text`.
- Legacy chunk table behavior is rejection, not partial compatibility.
- `chunks.filename` and `chunks.text` remain in the storage schema.
- Graph candidate field constants are unchanged.

- [ ] **Step 5: Final commit if needed**

If there are uncommitted verification or documentation changes, commit them:

```bash
rtk git add src tests docs
rtk git commit -m "test: verify chunk auxiliary legacy removal"
```

If the previous task commits already covered all changes, skip this commit.

# Source: docs/superpowers/plans/2026-05-11-minirag-gated-retrieval-rewrite.md

Role: distractor
Status: Ready for implementation after confirmation
Topic: 2026-05-11-minirag-gated-retrieval-rewrite
SHA256: d7eaaa1273b9d2474a8f8e64d41f5491e5c8f5b0c1e3be648013c0de7edbd707

# MiniRAG Gated Retrieval Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic gated CoT grounding enhancement inside MiniRAG retrieval, with cached initial-candidate fallback and explicit observability, without adding public API knobs or a multi-query planner.

**Architecture:** Keep `/queries`, `QueryModeRouter`, `DiscoRAGQueryService`, and answerers mostly unchanged. Add typed domain models plus a narrow `CoTGroundingRewriter` port, implement deterministic gate/rewrite helpers in the application layer, and let `MiniGraphFirstRetriever` orchestrate one optional rewrite cycle. Infrastructure rewriters generate only `solution_steps`; the existing grounding layer remains responsible for extracting MiniRAG entities, relations, and answer-type keywords.

**Tech Stack:** Python 3.13, dataclasses, Protocol ports, pytest, existing DeepSeek Chat and OpenAI Responses clients, existing MiniRAG/DiscoRAG domain models.

---

Date: 2026-05-11
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-11-minirag-gated-retrieval-rewrite.md](../specs/2026-05-11-minirag-gated-retrieval-rewrite.md)

## File Structure

Files to modify:

- `src/ragflow_lite/domain/models/entities.py`
  - Add `InitialCandidateSnapshot`, `GroundingGateDecision`, `CoTGroundingResult`, `EnrichedGroundingInput`, and `PostRewriteAssessment`.
- `src/ragflow_lite/domain/models/__init__.py`
  - Export the new domain models.
- `src/ragflow_lite/domain/ports/interfaces.py`
  - Add a narrow `CoTGroundingRewriter` protocol.
- `src/ragflow_lite/application/services/retrieval_rewrite.py`
  - Create deterministic gate, enriched input rendering, rewrite metadata helpers, post-rewrite assessment, and result-merge helpers.
- `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
  - Add optional `cot_grounding_rewriter`, run the initial pass once, snapshot it, gate it, optionally rewrite once, and merge enriched results.
- `src/ragflow_lite/application/services/__init__.py`
  - Export application helper symbols only if existing package style requires it.
- `src/ragflow_lite/infrastructure/retrievers/cot_grounding.py`
  - Create provider-neutral JSON parsing and validation helpers for `solution_steps`.
- `src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py`
  - Implement DeepSeek-backed `CoTGroundingRewriter`.
- `src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py`
  - Implement OpenAI Responses-backed `CoTGroundingRewriter`.
- `src/ragflow_lite/infrastructure/retrievers/__init__.py`
  - Export the new rewriters.
- `src/ragflow_lite/api/deps/providers.py`
  - Wire a DeepSeek CoT rewriter into `MiniGraphFirstRetriever` without exposing any public API field.
- `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
  - Add answer-facing degraded retrieval notice rendering from `AnswerRequest.metadata`.
- `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
  - Add the same degraded retrieval notice rendering.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Update only after behavior and tests land.

Tests to modify or create:

- `tests/unit/domain/test_minirag_topology_models.py`
- `tests/unit/application/test_retrieval_rewrite.py`
- `tests/unit/application/test_mini_graph_first_retriever.py`
- `tests/unit/infrastructure/test_cot_grounding.py`
- `tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py`
- `tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/infrastructure/test_deepseek_chat_answerer.py`
- `tests/unit/infrastructure/test_openai_responses_answerer.py`
- `tests/unit/api/test_providers.py`
- `tests/unit/api/test_v0_routes.py`

## Task 0: Baseline Reconnaissance

Purpose: confirm the current code shape before writing behavior changes.

- [ ] **Step 1: Inspect current MiniRAG symbols**

Run:

```bash
cx overview src/ragflow_lite/application/services/mini_graph_first_retriever.py
cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --all
```

Expected:

- `MiniGraphFirstRetriever.retrieve_context(query, top_k)` owns grounding, graph lookup, auxiliary retrieval, scoring, and selection.
- No rewrite gate or CoT rewriter parameter exists yet.

- [ ] **Step 2: Inspect current domain models and ports**

Run:

```bash
cx definition --name GroundedQuery --from src/ragflow_lite/domain/models/entities.py
cx definition --name TopologyRetrievalResult --from src/ragflow_lite/domain/models/entities.py
cx definition --name GraphFirstSourceSelection --from src/ragflow_lite/domain/models/entities.py
cx definition --name QueryGrounder --from src/ragflow_lite/domain/ports/interfaces.py
```

Expected:

- `GroundedQuery` has `query`, `answer_type_keywords`, `entities_from_query`, and `metadata`.
- `TopologyRetrievalResult` has `query`, `grounded_query`, `chunks`, `paths`, `source_selection`, and `metadata`.
- `QueryGrounder.ground(query)` remains a narrow basic grounding port.

- [ ] **Step 3: Run current focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_minirag_topology_models.py \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/infrastructure/test_deepseek_query_grounder.py \
  tests/unit/infrastructure/test_openai_query_grounder.py -q
```

Expected: all selected tests pass before changes.

## Task 1: Add Retrieval Rewrite Domain Models And Port

Purpose: define typed contracts before wiring behavior.

**Files:**

- Modify: `src/ragflow_lite/domain/models/entities.py`
- Modify: `src/ragflow_lite/domain/models/__init__.py`
- Modify: `src/ragflow_lite/domain/ports/interfaces.py`
- Test: `tests/unit/domain/test_minirag_topology_models.py`

- [ ] **Step 1: Add failing domain model tests**

Add to `tests/unit/domain/test_minirag_topology_models.py`:

```python
from ragflow_lite.domain.models import (
    CoTGroundingResult,
    EnrichedGroundingInput,
    GraphFirstSourceSelection,
    GroundingGateDecision,
    GroundedQuery,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
    RetrievedChunk,
)
from ragflow_lite.domain.ports.interfaces import CoTGroundingRewriter


def test_retrieval_rewrite_models_preserve_snapshot_and_status() -> None:
    grounded = GroundedQuery(
        query="What improves MiniRAG recall?",
        answer_type_keywords=["mechanism"],
        entities_from_query=["MiniRAG"],
    )
    chunk = RetrievedChunk(
        chunk_id="chunk_a",
        document_id="doc1",
        text="MiniRAG uses graph evidence.",
        score=1.0,
        metadata={"selected_for_answer": True},
    )
    selection = GraphFirstSourceSelection(
        sources=[],
        final_context_k=2,
        discourse_selection_k=4,
        context_token_budget=None,
        omitted_source_count=0,
    )

    snapshot = InitialCandidateSnapshot(
        query="What improves MiniRAG recall?",
        grounded_query=grounded,
        candidates=[chunk],
        source_selection=selection,
        metadata={"source": "initial"},
    )
    gate = GroundingGateDecision(
        should_rewrite=True,
        route="rewrite",
        reason="selected_answer_candidate_count_below_threshold",
        signals={"selected_answer_candidate_count": 0, "threshold": 1},
    )
    rewrite = CoTGroundingResult(
        status="succeeded",
        strategy="cot_grounding",
        original_query="What improves MiniRAG recall?",
        solution_steps=["Identify MiniRAG recall mechanisms."],
        attempts=1,
        failure_reason=None,
    )
    enriched = EnrichedGroundingInput(
        original_query=snapshot.query,
        solution_steps=rewrite.solution_steps,
    )
    assessment = PostRewriteAssessment(
        gate_passed=False,
        reason="selected_answer_candidate_count_below_threshold",
        signals={"selected_answer_candidate_count": 0, "threshold": 1},
    )

    assert snapshot.candidates == [chunk]
    assert gate.route == "rewrite"
    assert rewrite.solution_steps == ["Identify MiniRAG recall mechanisms."]
    assert enriched.original_query == snapshot.query
    assert assessment.gate_passed is False


def test_cot_grounding_rewriter_is_protocol() -> None:
    from typing import Protocol

    assert issubclass(CoTGroundingRewriter, Protocol)
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_minirag_topology_models.py::test_retrieval_rewrite_models_preserve_snapshot_and_status \
  tests/unit/domain/test_minirag_topology_models.py::test_cot_grounding_rewriter_is_protocol -q
```

Expected: FAIL because the models and protocol are not defined or exported.

- [ ] **Step 3: Add dataclasses**

Add to `src/ragflow_lite/domain/models/entities.py` near the MiniRAG topology models:

```python
@dataclass
class InitialCandidateSnapshot:
    query: str
    grounded_query: GroundedQuery
    candidates: list[RetrievedChunk]
    source_selection: GraphFirstSourceSelection | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass
class GroundingGateDecision:
    should_rewrite: bool
    route: Literal["accept", "rewrite"]
    reason: str
    signals: Metadata = field(default_factory=dict)


@dataclass
class CoTGroundingResult:
    status: Literal["succeeded", "failed"]
    strategy: Literal["cot_grounding"]
    original_query: str
    solution_steps: list[str]
    attempts: int
    failure_reason: str | None = None


@dataclass
class EnrichedGroundingInput:
    original_query: str
    solution_steps: list[str]


@dataclass
class PostRewriteAssessment:
    gate_passed: bool
    reason: str
    signals: Metadata = field(default_factory=dict)
```

If `Literal` is not already imported, add:

```python
from typing import Any, Literal
```

- [ ] **Step 4: Export the models**

Add the five classes to the import list and `__all__` in `src/ragflow_lite/domain/models/__init__.py`:

```python
CoTGroundingResult,
EnrichedGroundingInput,
GroundingGateDecision,
InitialCandidateSnapshot,
PostRewriteAssessment,
```

and:

```python
"CoTGroundingResult",
"EnrichedGroundingInput",
"GroundingGateDecision",
"InitialCandidateSnapshot",
"PostRewriteAssessment",
```

- [ ] **Step 5: Add the port**

Add to `src/ragflow_lite/domain/ports/interfaces.py`:

```python
class CoTGroundingRewriter(Protocol):
    def rewrite(self, query: str) -> CoTGroundingResult:
        """Return retrieval-facing solution steps for a normalized user query."""
```

Update imports in the same file:

```python
from ragflow_lite.domain.models import CoTGroundingResult
```

- [ ] **Step 6: Run domain tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/domain/test_minirag_topology_models.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add \
  src/ragflow_lite/domain/models/entities.py \
  src/ragflow_lite/domain/models/__init__.py \
  src/ragflow_lite/domain/ports/interfaces.py \
  tests/unit/domain/test_minirag_topology_models.py
git commit -m "feat: add retrieval rewrite domain contracts"
```

Expected: commit succeeds.

## Task 2: Add Deterministic Gate And Metadata Helpers

Purpose: make rewrite triggering local, deterministic, and testable.

**Files:**

- Create: `src/ragflow_lite/application/services/retrieval_rewrite.py`
- Test: `tests/unit/application/test_retrieval_rewrite.py`

- [ ] **Step 1: Add failing gate tests**

Create `tests/unit/application/test_retrieval_rewrite.py`:

```python
from __future__ import annotations

from ragflow_lite.application.services.retrieval_rewrite import (
    assess_post_rewrite,
    build_retrieval_rewrite_metadata,
    decide_grounding_gate,
)
from ragflow_lite.domain.models import (
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    InitialCandidateSnapshot,
    RetrievedChunk,
)


def _chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc1",
        text=f"text {chunk_id}",
        score=1.0,
        metadata={},
    )


def _source(chunk_id: str, *, selected_for_answer: bool) -> GraphFirstSource:
    return GraphFirstSource(
        chunk_id=chunk_id,
        rank=0,
        score=1.0,
        score_components={"test": 1.0},
        supporting_entity_ids=[],
        supporting_relation_ids=[],
        supporting_path_ids=[],
        auxiliary_chunk_hit=False,
        selected_for_answer=selected_for_answer,
        selected_for_discourse=selected_for_answer,
        selection_reason="test",
    )


def _snapshot(selected_answer_count: int) -> InitialCandidateSnapshot:
    sources = [
        _source(f"chunk_{index}", selected_for_answer=index < selected_answer_count)
        for index in range(4)
    ]
    return InitialCandidateSnapshot(
        query="What improves MiniRAG recall?",
        grounded_query=GroundedQuery(
            query="What improves MiniRAG recall?",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        candidates=[_chunk(source.chunk_id) for source in sources if source.selected_for_answer],
        source_selection=GraphFirstSourceSelection(
            sources=sources,
            final_context_k=4,
            discourse_selection_k=8,
            context_token_budget=None,
            omitted_source_count=0,
        ),
    )


def test_gate_accepts_when_selected_answer_candidates_meet_threshold() -> None:
    decision = decide_grounding_gate(_snapshot(selected_answer_count=2), requested_top_n=4)

    assert decision.should_rewrite is False
    assert decision.route == "accept"
    assert decision.signals["selected_answer_candidate_count"] == 2
    assert decision.signals["selected_answer_candidate_threshold"] == 2


def test_gate_rewrites_when_selected_answer_candidates_are_below_threshold() -> None:
    decision = decide_grounding_gate(_snapshot(selected_answer_count=1), requested_top_n=4)

    assert decision.should_rewrite is True
    assert decision.route == "rewrite"
    assert decision.reason == "selected_answer_candidate_count_below_threshold"
    assert decision.signals["selected_answer_candidate_count"] == 1
    assert decision.signals["selected_answer_candidate_threshold"] == 2


def test_gate_uses_ceil_half_top_n_threshold() -> None:
    assert decide_grounding_gate(_snapshot(1), requested_top_n=2).should_rewrite is False
    assert decide_grounding_gate(_snapshot(1), requested_top_n=3).should_rewrite is True
    assert decide_grounding_gate(_snapshot(2), requested_top_n=3).should_rewrite is False
    assert decide_grounding_gate(_snapshot(3), requested_top_n=5).should_rewrite is False
    assert decide_grounding_gate(_snapshot(3), requested_top_n=8).should_rewrite is True


def test_post_rewrite_assessment_does_not_request_recursive_rewrite() -> None:
    assessment = assess_post_rewrite(_snapshot(selected_answer_count=1), requested_top_n=4)

    assert assessment.gate_passed is False
    assert assessment.reason == "selected_answer_candidate_count_below_threshold"


def test_retrieval_rewrite_metadata_records_failed_fallback() -> None:
    metadata = build_retrieval_rewrite_metadata(
        enabled=True,
        triggered=True,
        strategy="cot_grounding",
        status="failed",
        gate_reason="selected_answer_candidate_count_below_threshold",
        attempts=2,
        failure_reason="invalid structured output",
        fallback_source="initial_candidate_snapshot",
        initial_candidate_count=1,
        enriched_candidate_count=0,
        post_rewrite_gate_passed=None,
        post_rewrite_gate_reason=None,
        answer_notice_required=False,
    )

    assert metadata["retrieval_rewrite"]["status"] == "failed"
    assert metadata["retrieval_rewrite"]["fallback_source"] == "initial_candidate_snapshot"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_retrieval_rewrite.py -q
```

Expected: FAIL because `retrieval_rewrite.py` does not exist.

- [ ] **Step 3: Implement deterministic gate and metadata helpers**

Create `src/ragflow_lite/application/services/retrieval_rewrite.py`:

```python
from __future__ import annotations

from math import ceil
from typing import Any, Literal

from ragflow_lite.domain.models import (
    GroundingGateDecision,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
)

RewriteStatus = Literal["not_triggered", "succeeded", "failed", "degraded"]


def _selected_answer_candidate_count(snapshot: InitialCandidateSnapshot) -> int:
    if snapshot.source_selection is None:
        return len(snapshot.candidates)
    return sum(1 for source in snapshot.source_selection.sources if source.selected_for_answer)


def _threshold(requested_top_n: int) -> int:
    return ceil(requested_top_n / 2)


def decide_grounding_gate(
    snapshot: InitialCandidateSnapshot,
    *,
    requested_top_n: int,
) -> GroundingGateDecision:
    selected_count = _selected_answer_candidate_count(snapshot)
    threshold = _threshold(requested_top_n)
    signals: dict[str, Any] = {
        "selected_answer_candidate_count": selected_count,
        "selected_answer_candidate_threshold": threshold,
        "requested_top_n": requested_top_n,
    }
    if selected_count < threshold:
        return GroundingGateDecision(
            should_rewrite=True,
            route="rewrite",
            reason="selected_answer_candidate_count_below_threshold",
            signals=signals,
        )
    return GroundingGateDecision(
        should_rewrite=False,
        route="accept",
        reason="selected_answer_candidate_count_meets_threshold",
        signals=signals,
    )


def assess_post_rewrite(
    snapshot: InitialCandidateSnapshot,
    *,
    requested_top_n: int,
) -> PostRewriteAssessment:
    decision = decide_grounding_gate(snapshot, requested_top_n=requested_top_n)
    return PostRewriteAssessment(
        gate_passed=not decision.should_rewrite,
        reason=decision.reason,
        signals=decision.signals,
    )


def build_retrieval_rewrite_metadata(
    *,
    enabled: bool,
    triggered: bool,
    strategy: str | None,
    status: RewriteStatus,
    gate_reason: str | None,
    attempts: int,
    failure_reason: str | None,
    fallback_source: str | None,
    initial_candidate_count: int,
    enriched_candidate_count: int,
    post_rewrite_gate_passed: bool | None,
    post_rewrite_gate_reason: str | None,
    answer_notice_required: bool,
) -> dict[str, Any]:
    return {
        "retrieval_rewrite": {
            "enabled": enabled,
            "triggered": triggered,
            "strategy": strategy,
            "status": status,
            "gate_reason": gate_reason,
            "attempts": attempts,
            "failure_reason": failure_reason,
            "fallback_source": fallback_source,
            "initial_candidate_count": initial_candidate_count,
            "enriched_candidate_count": enriched_candidate_count,
            "post_rewrite_gate_passed": post_rewrite_gate_passed,
            "post_rewrite_gate_reason": post_rewrite_gate_reason,
            "answer_notice_required": answer_notice_required,
        }
    }
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_retrieval_rewrite.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/ragflow_lite/application/services/retrieval_rewrite.py tests/unit/application/test_retrieval_rewrite.py
git commit -m "feat: add deterministic retrieval rewrite gate"
```

Expected: commit succeeds.

## Task 3: Add CoT Grounding Parser And Rewriters

Purpose: generate only `solution_steps`, validate shape, and retry once at the rewriter layer.

**Files:**

- Create: `src/ragflow_lite/infrastructure/retrievers/cot_grounding.py`
- Create: `src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py`
- Create: `src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py`
- Modify: `src/ragflow_lite/infrastructure/retrievers/__init__.py`
- Test: `tests/unit/infrastructure/test_cot_grounding.py`
- Test: `tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py`
- Test: `tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py`

- [ ] **Step 1: Add parser tests**

Create `tests/unit/infrastructure/test_cot_grounding.py`:

```python
from __future__ import annotations

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    parse_cot_grounding_result,
    render_enriched_grounding_input,
)


def test_parse_cot_grounding_result_accepts_solution_steps_only() -> None:
    result = parse_cot_grounding_result(
        '{"original_query":"What improves MiniRAG recall?",'
        '"solution_steps":["Identify recall failure.", "Map entities and relations."]}',
        expected_query="What improves MiniRAG recall?",
        attempts=1,
    )

    assert result.status == "succeeded"
    assert result.solution_steps == [
        "Identify recall failure.",
        "Map entities and relations.",
    ]
    assert result.original_query == "What improves MiniRAG recall?"


def test_parse_cot_grounding_result_rejects_direct_retrieval_parameters() -> None:
    with pytest.raises(ProcessingError, match="must not include retrieval fields"):
        parse_cot_grounding_result(
            '{"original_query":"Q","solution_steps":["step"],"entities":["MiniRAG"]}',
            expected_query="Q",
            attempts=1,
        )


def test_parse_cot_grounding_result_rejects_mismatched_query() -> None:
    with pytest.raises(ProcessingError, match="original_query does not match"):
        parse_cot_grounding_result(
            '{"original_query":"Different","solution_steps":["step"]}',
            expected_query="Q",
            attempts=1,
        )


def test_parse_cot_grounding_result_rejects_empty_steps() -> None:
    with pytest.raises(ProcessingError, match="solution_steps"):
        parse_cot_grounding_result(
            '{"original_query":"Q","solution_steps":["   "]}',
            expected_query="Q",
            attempts=1,
        )


def test_render_enriched_grounding_input_contains_query_and_steps() -> None:
    rendered = render_enriched_grounding_input(
        original_query="What improves MiniRAG recall?",
        solution_steps=["Identify recall failure.", "Map entities and relations."],
    )

    assert "Original query:" in rendered
    assert "What improves MiniRAG recall?" in rendered
    assert "Solution steps:" in rendered
    assert "1. Identify recall failure." in rendered
    assert "2. Map entities and relations." in rendered


def test_cot_grounding_instructions_do_not_request_entities_or_relations() -> None:
    assert "solution_steps" in COT_GROUNDING_INSTRUCTIONS
    assert '"entities"' not in COT_GROUNDING_INSTRUCTIONS
    assert '"relations"' not in COT_GROUNDING_INSTRUCTIONS
    assert "answer_type_keywords" not in COT_GROUNDING_INSTRUCTIONS
```

- [ ] **Step 2: Add DeepSeek rewriter tests**

Create `tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.retrievers import DeepSeekCoTGroundingRewriter


class _FakeDeepSeekClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, str]] = []

    def complete_json(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        output = self.outputs.pop(0)
        if output == "__raise__":
            raise RuntimeError("provider failed")
        return output


def test_deepseek_cot_rewriter_returns_solution_steps() -> None:
    client = _FakeDeepSeekClient(
        ['{"original_query":"Q","solution_steps":["Clarify Q."]}']
    )
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.solution_steps == ["Clarify Q."]
    assert result.attempts == 1
    assert len(client.calls) == 1


def test_deepseek_cot_rewriter_retries_once_then_succeeds() -> None:
    client = _FakeDeepSeekClient(
        [
            '{"original_query":"Q","solution_steps":[]}',
            '{"original_query":"Q","solution_steps":["Clarify Q."]}',
        ]
    )
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.attempts == 2
    assert result.solution_steps == ["Clarify Q."]


def test_deepseek_cot_rewriter_returns_failed_after_exhaustion() -> None:
    client = _FakeDeepSeekClient(["not-json", "not-json"])
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "failed"
    assert result.strategy == "cot_grounding"
    assert result.solution_steps == []
    assert result.attempts == 2
    assert "invalid JSON" in (result.failure_reason or "")


def test_deepseek_cot_rewriter_rejects_empty_query_without_model_call() -> None:
    client = _FakeDeepSeekClient([])
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    with pytest.raises(Exception, match="requires a query"):
        rewriter.rewrite("   ")

    assert client.calls == []
```

- [ ] **Step 3: Add OpenAI rewriter tests**

Create `tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

from ragflow_lite.infrastructure.retrievers import OpenAIResponsesCoTGroundingRewriter


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self.outputs.pop(0))


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = _FakeResponses(outputs)


def test_openai_cot_rewriter_returns_solution_steps() -> None:
    client = _FakeClient(['{"original_query":"Q","solution_steps":["Clarify Q."]}'])
    rewriter = OpenAIResponsesCoTGroundingRewriter(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.solution_steps == ["Clarify Q."]
    assert result.attempts == 1
    request = client.responses.calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert "solution_steps" in str(request["instructions"])


def test_openai_cot_rewriter_retries_once_then_failed() -> None:
    client = _FakeClient(["not-json", "not-json"])
    rewriter = OpenAIResponsesCoTGroundingRewriter(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    result = rewriter.rewrite("Q")

    assert result.status == "failed"
    assert result.attempts == 2
    assert result.failure_reason is not None
    assert len(client.responses.calls) == 2
```

- [ ] **Step 4: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py -q
```

Expected: FAIL because new modules do not exist.

- [ ] **Step 5: Implement parser helper**

Create `src/ragflow_lite/infrastructure/retrievers/cot_grounding.py`:

```python
from __future__ import annotations

import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult

COT_GROUNDING_INSTRUCTIONS = """Create retrieval-facing solution steps for MiniRAG grounding.

Return exactly one JSON object with this shape:
{
  "original_query": "the exact user query",
  "solution_steps": ["short retrieval-facing step"]
}

Rules:
- Return solution_steps only; do not return entities, relations, keywords, or answer_type_keywords.
- Keep each step short and useful for retrieval grounding.
- Do not output markdown or prose outside the JSON object.
"""

_FORBIDDEN_FIELDS = {
    "entities",
    "relations",
    "keywords",
    "answer_type_keywords",
    "entities_from_query",
}


def parse_cot_grounding_result(
    text: str,
    *,
    expected_query: str,
    attempts: int,
) -> CoTGroundingResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProcessingError("CoT grounding returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProcessingError("CoT grounding must return a JSON object.")
    if _FORBIDDEN_FIELDS.intersection(payload):
        raise ProcessingError("CoT grounding output must not include retrieval fields.")
    original_query = payload.get("original_query")
    if not isinstance(original_query, str) or original_query.strip() != expected_query:
        raise ProcessingError("CoT grounding original_query does not match.")
    raw_steps = payload.get("solution_steps")
    if not isinstance(raw_steps, list):
        raise ProcessingError("CoT grounding output missing solution_steps.")
    steps: list[str] = []
    for step in raw_steps:
        if not isinstance(step, str) or not step.strip():
            raise ProcessingError("CoT grounding solution_steps must contain strings.")
        steps.append(step.strip())
    if not steps:
        raise ProcessingError("CoT grounding solution_steps must not be empty.")
    return CoTGroundingResult(
        status="succeeded",
        strategy="cot_grounding",
        original_query=expected_query,
        solution_steps=steps,
        attempts=attempts,
        failure_reason=None,
    )


def failed_cot_grounding_result(
    *,
    original_query: str,
    attempts: int,
    failure_reason: str,
) -> CoTGroundingResult:
    return CoTGroundingResult(
        status="failed",
        strategy="cot_grounding",
        original_query=original_query,
        solution_steps=[],
        attempts=attempts,
        failure_reason=failure_reason,
    )


def render_enriched_grounding_input(
    *,
    original_query: str,
    solution_steps: list[str],
) -> str:
    lines = ["Original query:", original_query.strip(), "", "Solution steps:"]
    lines.extend(f"{index}. {step.strip()}" for index, step in enumerate(solution_steps, start=1))
    return "\n".join(lines).strip()
```

- [ ] **Step 6: Implement DeepSeek rewriter**

Create `src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    failed_cot_grounding_result,
    parse_cot_grounding_result,
)


class DeepSeekCoTGroundingRewriter:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ProcessingError("CoT grounding max_attempts must be >= 1.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_attempts = max_attempts
        self.client = client or self._build_client(api_key, base_url)

    def rewrite(self, query: str) -> CoTGroundingResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("CoT grounding rewrite requires a query.")
        last_error = "unknown CoT grounding failure"
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = self.client.complete_json(
                    instructions=COT_GROUNDING_INSTRUCTIONS,
                    input_text=normalized_query,
                )
                return parse_cot_grounding_result(
                    text,
                    expected_query=normalized_query,
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
        return failed_cot_grounding_result(
            original_query=normalized_query,
            attempts=self.max_attempts,
            failure_reason=last_error,
        )

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

        if api_key is None or base_url is None:
            raise ProcessingError(
                "DeepSeek CoT grounding rewriter requires api_key and base_url when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )
```

- [ ] **Step 7: Implement OpenAI rewriter**

Create `src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    failed_cot_grounding_result,
    parse_cot_grounding_result,
)


class OpenAIResponsesCoTGroundingRewriter:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str,
        store: bool,
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ProcessingError("CoT grounding max_attempts must be >= 1.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        self.max_attempts = max_attempts
        self.client = client or self._build_client(api_key, base_url)

    def rewrite(self, query: str) -> CoTGroundingResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("CoT grounding rewrite requires a query.")
        last_error = "unknown CoT grounding failure"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=COT_GROUNDING_INSTRUCTIONS,
                    input=normalized_query,
                    reasoning={"effort": self.reasoning_effort},
                    store=self.store,
                )
                return parse_cot_grounding_result(
                    response.output_text,
                    expected_query=normalized_query,
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
        return failed_cot_grounding_result(
            original_query=normalized_query,
            attempts=self.max_attempts,
            failure_reason=last_error,
        )

    @staticmethod
    def _build_client(api_key: str, base_url: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)
```

- [ ] **Step 8: Export the new rewriters**

Modify `src/ragflow_lite/infrastructure/retrievers/__init__.py`:

```python
from ragflow_lite.infrastructure.retrievers.deepseek_cot_grounding_rewriter import (
    DeepSeekCoTGroundingRewriter,
)
from ragflow_lite.infrastructure.retrievers.openai_cot_grounding_rewriter import (
    OpenAIResponsesCoTGroundingRewriter,
)
```

Add to `__all__`:

```python
"DeepSeekCoTGroundingRewriter",
"OpenAIResponsesCoTGroundingRewriter",
```

- [ ] **Step 9: Run rewriter tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add \
  src/ragflow_lite/infrastructure/retrievers/cot_grounding.py \
  src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py \
  src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py \
  src/ragflow_lite/infrastructure/retrievers/__init__.py \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py
git commit -m "feat: add CoT grounding rewriters"
```

Expected: commit succeeds.

## Task 4: Refactor MiniGraphFirstRetriever Into Reusable Retrieval Pass

Purpose: create a local seam so the initial and enriched retrieval passes share the same selection code.

**Files:**

- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`

- [ ] **Step 1: Add a no-behavior-change regression test**

Add to `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
def test_mini_graph_first_retriever_without_rewriter_keeps_existing_metadata() -> None:
    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=RecordingAuxiliaryRetriever(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert result.metadata["retrieval_mode"] == "mini_graph_first"
    assert "retrieval_rewrite" not in result.metadata
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_a", "chunk_b"]
```

- [ ] **Step 2: Run the regression test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py::test_mini_graph_first_retriever_without_rewriter_keeps_existing_metadata -q
```

Expected: PASS before refactor.

- [ ] **Step 3: Extract a private `_retrieve_context_once` helper**

In `MiniGraphFirstRetriever`, keep `retrieve_context()` public and extract the current body after `_require_positive_top_k(top_k)` into a helper shaped like:

```python
def _retrieve_context_once(
    self,
    *,
    original_query: str,
    grounding_query: str,
    auxiliary_query: str,
    top_k: int,
    discourse_selection_n: int,
) -> TopologyRetrievalResult:
    grounded_query = self.query_grounder.ground(grounding_query)
    if (
        not grounded_query.entities_from_query
        and not grounded_query.answer_type_keywords
    ):
        return self._fallback_empty_grounding(
            original_query,
            grounded_query,
            top_k,
            discourse_selection_n,
            auxiliary_query=auxiliary_query,
        )
    query_entities = grounded_query.entities_from_query[: self.query_entity_limit]
    query_entity_n = len(query_entities)
    entity_candidate_n = self.mini_internal_candidate_n
    relationship_candidate_n = max(
        self.mini_internal_candidate_n,
        query_entity_n * self.mini_internal_candidate_n,
    )
    entity_candidates = self.entity_index.query_entities(
        query_entities,
        top_k=entity_candidate_n,
    )
    relationship_candidates = self.relationship_index.query_relationships(
        auxiliary_query,
        grounded_query.answer_type_keywords,
        top_k=relationship_candidate_n,
    )
    relation_paths = self.path_expander.expand_paths(
        seed_entity_ids=_entity_ids(entity_candidates),
        seed_relation_ids=_relation_ids(relationship_candidates),
        max_hops=self.path_hop_limit,
    )
    paths = _merge_trimmed_no_path_candidates(
        entity_candidates,
        relation_paths,
        relationship_candidates,
    )[: self.path_candidate_k]
    auxiliary_chunks = self._retrieve_auxiliary_chunks(auxiliary_query, answer_top_n)
    supports = _score_source_chunks(
        entity_candidates=entity_candidates,
        relationship_candidates=relationship_candidates,
        paths=paths,
        auxiliary_chunks=auxiliary_chunks,
    )
    selection = self._build_source_selection(
        supports,
        answer_top_n,
        discourse_selection_n=discourse_selection_n,
    )
    answer_chunk_ids = [
        source.chunk_id
        for source in selection.sources
        if source.selected_for_answer
    ]
    discourse_only_chunk_ids = [
        source.chunk_id
        for source in selection.sources
        if source.selected_for_discourse and not source.selected_for_answer
    ]
    chunks = self._resolve_chunks_with_selection(
        answer_chunk_ids,
        auxiliary_chunks,
        selection,
        answer_top_n,
    )
    supplemental_chunks = self._resolve_supplemental_discourse_chunks(
        discourse_only_chunk_ids,
        auxiliary_chunks,
        selection,
    )
    return TopologyRetrievalResult(
        query=original_query,
        grounded_query=grounded_query,
        chunks=chunks,
        paths=paths,
        metadata={
            "retrieval_mode": "mini_graph_first",
            "source_selection": self._source_selection_summary(selection),
            "supplemental_discourse_chunks": supplemental_chunks,
        },
        source_selection=selection,
    )
```

For the existing normal path, call:

```python
return self._retrieve_context_once(
    original_query=query,
    grounding_query=query,
    auxiliary_query=query,
    top_k=answer_top_n,
    discourse_selection_n=discourse_selection_n,
)
```

Preserve the existing empty-grounding fallback behavior by updating `_fallback_empty_grounding()` only as needed to accept `original_query` and `auxiliary_query` while returning `TopologyRetrievalResult.query == original_query`.

- [ ] **Step 4: Run existing MiniRAG tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: PASS. This task should not add rewrite behavior yet.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/ragflow_lite/application/services/mini_graph_first_retriever.py tests/unit/application/test_mini_graph_first_retriever.py
git commit -m "refactor: isolate MiniRAG retrieval pass"
```

Expected: commit succeeds.

## Task 5: Integrate Gate And Failed-Rewrite Fallback

Purpose: snapshot initial candidates, trigger a deterministic gate, call the rewriter, and fall back to cached initial candidates on rewrite failure.

**Files:**

- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Modify: `src/ragflow_lite/application/services/retrieval_rewrite.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`

- [ ] **Step 1: Add fake rewriter helpers**

Add near the test fakes in `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
@dataclass
class FailingCoTRewriter:
    calls: list[str] = field(default_factory=list)

    def rewrite(self, query: str) -> CoTGroundingResult:
        self.calls.append(query)
        return CoTGroundingResult(
            status="failed",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=[],
            attempts=2,
            failure_reason="invalid structured output",
        )
```

Update imports:

```python
from ragflow_lite.domain.models import CoTGroundingResult
```

- [ ] **Step 2: Add failing fallback test**

Add:

```python
def test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query() -> None:
    grounder = EmptyGrounder()
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    rewriter = FailingCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    assert auxiliary_retriever.calls == [("ambiguous question", 30)]
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_0"]
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["status"] == "failed"
    assert rewrite["attempts"] == 2
    assert rewrite["failure_reason"] == "invalid structured output"
    assert rewrite["fallback_source"] == "initial_candidate_snapshot"
```

- [ ] **Step 3: Run the test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py::test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query -q
```

Expected: FAIL because `cot_grounding_rewriter` is not accepted and metadata is absent.

- [ ] **Step 4: Add optional rewriter constructor parameter**

In `MiniGraphFirstRetriever.__init__()`, add:

```python
cot_grounding_rewriter: CoTGroundingRewriter | None = None,
```

Store:

```python
self.cot_grounding_rewriter = cot_grounding_rewriter
```

Import the protocol:

```python
from ragflow_lite.domain.ports.interfaces import CoTGroundingRewriter
```

- [ ] **Step 5: Add snapshot helper**

In `src/ragflow_lite/application/services/retrieval_rewrite.py`, add:

```python
from ragflow_lite.domain.models import InitialCandidateSnapshot, TopologyRetrievalResult


def snapshot_initial_candidates(result: TopologyRetrievalResult) -> InitialCandidateSnapshot:
    return InitialCandidateSnapshot(
        query=result.query,
        grounded_query=result.grounded_query,
        candidates=list(result.chunks),
        source_selection=result.source_selection,
        metadata=dict(result.metadata),
    )
```

- [ ] **Step 6: Implement failed-rewrite fallback orchestration**

In `MiniGraphFirstRetriever.retrieve_context()`:

```python
initial_result = self._retrieve_context_once(
    original_query=query,
    grounding_query=query,
    auxiliary_query=query,
    top_k=answer_top_n,
    discourse_selection_n=discourse_selection_n,
)
if self.cot_grounding_rewriter is None:
    return initial_result

snapshot = snapshot_initial_candidates(initial_result)
gate = decide_grounding_gate(snapshot, requested_top_n=answer_top_n)
if not gate.should_rewrite:
    initial_result.metadata.update(
        build_retrieval_rewrite_metadata(
            enabled=True,
            triggered=False,
            strategy=None,
            status="not_triggered",
            gate_reason=gate.reason,
            attempts=0,
            failure_reason=None,
            fallback_source=None,
            initial_candidate_count=len(snapshot.candidates),
            enriched_candidate_count=0,
            post_rewrite_gate_passed=None,
            post_rewrite_gate_reason=None,
            answer_notice_required=False,
        )
    )
    return initial_result

rewrite = self.cot_grounding_rewriter.rewrite(snapshot.query)
if rewrite.status == "failed":
    initial_result.metadata.update(
        build_retrieval_rewrite_metadata(
            enabled=True,
            triggered=True,
            strategy="cot_grounding",
            status="failed",
            gate_reason=gate.reason,
            attempts=rewrite.attempts,
            failure_reason=rewrite.failure_reason,
            fallback_source="initial_candidate_snapshot",
            initial_candidate_count=len(snapshot.candidates),
            enriched_candidate_count=0,
            post_rewrite_gate_passed=None,
            post_rewrite_gate_reason=None,
            answer_notice_required=False,
        )
    )
    return initial_result
```

Keep the successful rewrite branch temporarily returning `initial_result` with a comment only if it is unreachable in this task's tests. Do not leave the branch incomplete after Task 6.

- [ ] **Step 7: Run the fallback test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py::test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query -q
```

Expected: PASS.

- [ ] **Step 8: Run focused MiniRAG tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add \
  src/ragflow_lite/application/services/retrieval_rewrite.py \
  src/ragflow_lite/application/services/mini_graph_first_retriever.py \
  tests/unit/application/test_mini_graph_first_retriever.py
git commit -m "feat: fall back to initial candidates when rewrite fails"
```

Expected: commit succeeds.

## Task 6: Implement Successful Rewrite And Candidate Merge

Purpose: use `original_query + solution_steps` for enriched grounding and auxiliary retrieval, merge candidates, and keep final-window bounds.

**Files:**

- Modify: `src/ragflow_lite/application/services/retrieval_rewrite.py`
- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Test: `tests/unit/application/test_retrieval_rewrite.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`

- [ ] **Step 1: Add successful rewriter and enriched grounder test fakes**

Add to `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
@dataclass
class SuccessfulCoTRewriter:
    calls: list[str] = field(default_factory=list)

    def rewrite(self, query: str) -> CoTGroundingResult:
        self.calls.append(query)
        return CoTGroundingResult(
            status="succeeded",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=["Identify missing MiniRAG relation evidence."],
            attempts=1,
            failure_reason=None,
        )


@dataclass
class EnrichedAwareGrounder:
    calls: list[str] = field(default_factory=list)

    def ground(self, query: str) -> GroundedQuery:
        self.calls.append(query)
        if "Solution steps:" in query:
            return GroundedQuery(
                query=query,
                answer_type_keywords=["relation"],
                entities_from_query=["EnrichedMiniRAG"],
            )
        return GroundedQuery(
            query=query,
            answer_type_keywords=["mechanism"],
            entities_from_query=[],
        )
```

- [ ] **Step 2: Add successful rewrite test**

Add:

```python
def test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass() -> None:
    grounder = EnrichedAwareGrounder()
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=4)
    rewriter = SuccessfulCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=2)

    assert rewriter.calls == ["ambiguous question"]
    assert len(grounder.calls) == 2
    assert grounder.calls[0] == "ambiguous question"
    assert "Original query:" in grounder.calls[1]
    assert "ambiguous question" in grounder.calls[1]
    assert "Solution steps:" in grounder.calls[1]
    assert "Identify missing MiniRAG relation evidence." in grounder.calls[1]
    assert len(result.chunks) <= 2
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["status"] in {"succeeded", "degraded"}
    assert rewrite["initial_candidate_count"] >= 1
    assert rewrite["enriched_candidate_count"] >= 1
```

- [ ] **Step 3: Add no-solution-steps failure test**

Add:

```python
@dataclass
class EmptyStepsCoTRewriter:
    def rewrite(self, query: str) -> CoTGroundingResult:
        return CoTGroundingResult(
            status="succeeded",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=[],
            attempts=1,
            failure_reason=None,
        )


def test_success_status_with_empty_steps_is_treated_as_rewrite_failure() -> None:
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    retriever = MiniGraphFirstRetriever(
        query_grounder=EmptyGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=EmptyStepsCoTRewriter(),
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert result.metadata["retrieval_rewrite"]["status"] == "failed"
    assert result.metadata["retrieval_rewrite"]["fallback_source"] == "initial_candidate_snapshot"
    assert auxiliary_retriever.calls == [("ambiguous question", 30)]
```

- [ ] **Step 4: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py::test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass \
  tests/unit/application/test_mini_graph_first_retriever.py::test_success_status_with_empty_steps_is_treated_as_rewrite_failure -q
```

Expected: FAIL because successful rewrite branch is not implemented.

- [ ] **Step 5: Add enriched input helper**

In `src/ragflow_lite/application/services/retrieval_rewrite.py`, add:

```python
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult, EnrichedGroundingInput
from ragflow_lite.infrastructure.retrievers.cot_grounding import render_enriched_grounding_input


def build_enriched_grounding_input(
    *,
    snapshot: InitialCandidateSnapshot,
    rewrite: CoTGroundingResult,
) -> EnrichedGroundingInput:
    if rewrite.status != "succeeded":
        raise ProcessingError("CoT grounding rewrite did not succeed.")
    if rewrite.original_query.strip() != snapshot.query.strip():
        raise ProcessingError("CoT grounding original_query does not match snapshot.")
    steps = [step.strip() for step in rewrite.solution_steps if step.strip()]
    if not steps:
        raise ProcessingError("CoT grounding solution_steps must not be empty.")
    return EnrichedGroundingInput(original_query=snapshot.query, solution_steps=steps)


def render_enriched_query(input_value: EnrichedGroundingInput) -> str:
    return render_enriched_grounding_input(
        original_query=input_value.original_query,
        solution_steps=input_value.solution_steps,
    )
```

- [ ] **Step 6: Implement merge helper**

In `src/ragflow_lite/application/services/retrieval_rewrite.py`, add:

```python
from ragflow_lite.domain.models import RetrievedChunk, TopologyRetrievalResult


def merge_retrieval_results(
    *,
    initial: TopologyRetrievalResult,
    enriched: TopologyRetrievalResult,
    top_k: int,
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    for source_name, chunks in (
        ("initial", initial.chunks),
        ("enriched", enriched.chunks),
    ):
        for chunk in chunks:
            existing = merged.get(chunk.chunk_id)
            source_set = set()
            if existing is not None:
                source_set.update(existing.metadata.get("retrieval_rewrite_sources", []))
                if existing.score >= chunk.score:
                    target = existing
                else:
                    target = chunk
            else:
                target = chunk
            source_set.add(source_name)
            target.metadata = dict(target.metadata)
            target.metadata["retrieval_rewrite_sources"] = sorted(source_set)
            merged[chunk.chunk_id] = target
    return sorted(merged.values(), key=lambda chunk: chunk.score, reverse=True)[:top_k]
```

This smallest merge rule keeps current behavior when rewrite is not triggered and preserves source metadata when rewrite is triggered.

- [ ] **Step 7: Complete successful rewrite branch**

In `MiniGraphFirstRetriever.retrieve_context()`:

```python
try:
    enriched_input = build_enriched_grounding_input(snapshot=snapshot, rewrite=rewrite)
    enriched_query = render_enriched_query(enriched_input)
except ProcessingError as exc:
    initial_result.metadata.update(
        build_retrieval_rewrite_metadata(
            enabled=True,
            triggered=True,
            strategy="cot_grounding",
            status="failed",
            gate_reason=gate.reason,
            attempts=rewrite.attempts,
            failure_reason=str(exc),
            fallback_source="initial_candidate_snapshot",
            initial_candidate_count=len(snapshot.candidates),
            enriched_candidate_count=0,
            post_rewrite_gate_passed=None,
            post_rewrite_gate_reason=None,
            answer_notice_required=False,
        )
    )
    return initial_result

enriched_result = self._retrieve_context_once(
    original_query=query,
    grounding_query=enriched_query,
    auxiliary_query=enriched_query,
    top_k=answer_top_n,
    discourse_selection_n=discourse_selection_n,
)
merged_chunks = merge_retrieval_results(
    initial=initial_result,
    enriched=enriched_result,
    top_k=answer_top_n,
)
```

Build a final `TopologyRetrievalResult` using `enriched_result` as the base, replacing `.chunks` with `merged_chunks`, and then Task 7 will add post-rewrite assessment metadata.

- [ ] **Step 8: Run successful rewrite tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py::test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass \
  tests/unit/application/test_mini_graph_first_retriever.py::test_success_status_with_empty_steps_is_treated_as_rewrite_failure -q
```

Expected: PASS.

- [ ] **Step 9: Run full MiniRAG tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add \
  src/ragflow_lite/application/services/retrieval_rewrite.py \
  src/ragflow_lite/application/services/mini_graph_first_retriever.py \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py
git commit -m "feat: run enriched MiniRAG retrieval after CoT rewrite"
```

Expected: commit succeeds.

## Task 7: Add Post-Rewrite Assessment And Answer-Facing Notice

Purpose: mark successful rewrite as degraded when final evidence is still weak, without recursive rewrite.

**Files:**

- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Modify: `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
- Modify: `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat_answerer.py`
- Test: `tests/unit/infrastructure/test_openai_responses_answerer.py`

- [ ] **Step 1: Add post-rewrite degraded metadata test**

Add to `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
def test_post_rewrite_gate_failure_marks_notice_without_second_rewrite() -> None:
    grounder = EnrichedAwareGrounder()
    rewriter = SuccessfulCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=ManyAuxiliaryRetriever(chunk_count=1),
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["post_rewrite_gate_passed"] is False
    assert rewrite["answer_notice_required"] is True
```

- [ ] **Step 2: Add answerer notice tests**

In `tests/unit/infrastructure/test_deepseek_chat_answerer.py`, add a fake client test:

```python
def test_deepseek_answerer_includes_retrieval_rewrite_notice() -> None:
    client = _FakeDeepSeekClient("Evidence is still limited.")
    answerer = DeepSeekChatAnswerer(client=client, instructions="Answer.")
    request = AnswerRequest(
        query="ambiguous question",
        contexts=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="limited evidence",
                score=1.0,
                metadata={},
            )
        ],
        mode="discorag",
        metadata={
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": "selected_answer_candidate_count_below_threshold",
            }
        },
    )

    answerer.answer(request)

    sent_input = client.calls[0]["input_text"]
    assert "Retrieval rewrite notice:" in sent_input
    assert "retrieval rewrite already ran" in sent_input
    assert "available evidence still appears insufficient" in sent_input
```

In `tests/unit/infrastructure/test_openai_responses_answerer.py`, add the equivalent assertion against the fake response input:

```python
def test_openai_answerer_includes_retrieval_rewrite_notice() -> None:
    client = _FakeClient("Evidence is still limited.")
    answerer = OpenAIResponsesAnswerer(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
        instructions="Answer.",
    )
    request = AnswerRequest(
        query="ambiguous question",
        contexts=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="limited evidence",
                score=1.0,
                metadata={},
            )
        ],
        mode="discorag",
        metadata={
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": "selected_answer_candidate_count_below_threshold",
            }
        },
    )

    answerer.answer(request)

    sent_input = client.responses.calls[0]["input"]
    assert "Retrieval rewrite notice:" in sent_input
    assert "retrieval rewrite already ran" in sent_input
```

If existing fake client names differ, adapt only the fake plumbing.

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py::test_post_rewrite_gate_failure_marks_notice_without_second_rewrite \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py::test_deepseek_answerer_includes_retrieval_rewrite_notice \
  tests/unit/infrastructure/test_openai_responses_answerer.py::test_openai_answerer_includes_retrieval_rewrite_notice -q
```

Expected: FAIL because notice metadata and rendering are not implemented.

- [ ] **Step 4: Add post-rewrite assessment metadata**

In successful rewrite branch of `MiniGraphFirstRetriever.retrieve_context()`:

```python
merged_result = TopologyRetrievalResult(
    query=query,
    grounded_query=enriched_result.grounded_query,
    chunks=merged_chunks,
    paths=enriched_result.paths,
    source_selection=enriched_result.source_selection,
    metadata=dict(enriched_result.metadata),
)
merged_snapshot = snapshot_initial_candidates(merged_result)
assessment = assess_post_rewrite(merged_snapshot, requested_top_n=answer_top_n)
answer_notice_required = not assessment.gate_passed
merged_result.metadata.update(
    build_retrieval_rewrite_metadata(
        enabled=True,
        triggered=True,
        strategy="cot_grounding",
        status="succeeded" if assessment.gate_passed else "degraded",
        gate_reason=gate.reason,
        attempts=rewrite.attempts,
        failure_reason=None,
        fallback_source=None,
        initial_candidate_count=len(snapshot.candidates),
        enriched_candidate_count=len(enriched_result.chunks),
        post_rewrite_gate_passed=assessment.gate_passed,
        post_rewrite_gate_reason=assessment.reason,
        answer_notice_required=answer_notice_required,
    )
)
return merged_result
```

- [ ] **Step 5: Add answerer notice helper**

In both answerers, add:

```python
def _format_retrieval_rewrite_notice(metadata: dict[str, Any]) -> list[str]:
    rewrite = metadata.get("retrieval_rewrite")
    if not isinstance(rewrite, dict) or rewrite.get("answer_notice_required") is not True:
        return []
    return [
        "Retrieval rewrite notice:",
        "- Retrieval rewrite already ran, but the available evidence still appears insufficient.",
        "- Likely causes include missing relevant documents in the knowledge base or a query that is still too ambiguous.",
        "- Tell the user that they may need to rephrase the query or add the needed documents.",
        "",
    ]
```

Then in `_build_input()` after the question block and before blueprint/context blocks:

```python
notice_lines = _format_retrieval_rewrite_notice(request.metadata)
if notice_lines:
    lines.extend(notice_lines)
```

- [ ] **Step 6: Run notice tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py::test_post_rewrite_gate_failure_marks_notice_without_second_rewrite \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py::test_deepseek_answerer_includes_retrieval_rewrite_notice \
  tests/unit/infrastructure/test_openai_responses_answerer.py::test_openai_answerer_includes_retrieval_rewrite_notice -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add \
  src/ragflow_lite/application/services/mini_graph_first_retriever.py \
  src/ragflow_lite/infrastructure/answerers/deepseek_chat.py \
  src/ragflow_lite/infrastructure/answerers/openai_responses.py \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py
git commit -m "feat: surface degraded retrieval rewrite notices"
```

Expected: commit succeeds.

## Task 8: Wire Provider And Preserve API Boundary

Purpose: enable the feature in service wiring while keeping `/queries` schema unchanged.

**Files:**

- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_providers.py`
- Test: `tests/unit/api/test_v0_routes.py`

- [ ] **Step 1: Add provider wiring test**

Add to `tests/unit/api/test_providers.py` near MiniGraphFirstRetriever wiring tests:

```python
def test_build_services_wires_cot_grounding_rewriter_non_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragflow_lite.api.deps import providers as providers_module

    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setattr(
        providers_module,
        "DeepSeekCoTGroundingRewriter",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    settings = _build_settings(tmp_path)

    services = build_services(settings)

    assert services.retriever.cot_grounding_rewriter is not None
    assert services.retriever.cot_grounding_rewriter.model == settings.deepseek_model
```

If `_fake_mini_graph_first_retriever` returns a `SimpleNamespace(**kwargs)`, this assertion shape will work with existing non-live patching.

- [ ] **Step 2: Add API schema non-change test**

Add or extend in `tests/unit/api/test_v0_routes.py`:

```python
def test_query_request_does_not_expose_retrieval_rewrite_strategy() -> None:
    from ragflow_lite.api.schemas.v0 import QueryRequest

    fields = set(QueryRequest.model_fields)

    assert "rewrite_strategy" not in fields
    assert "retrieval_rewrite" not in fields
    assert "cot_grounding" not in fields
```

- [ ] **Step 3: Run tests and verify they fail where wiring is missing**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_providers.py::test_build_services_wires_cot_grounding_rewriter_non_live \
  tests/unit/api/test_v0_routes.py::test_query_request_does_not_expose_retrieval_rewrite_strategy -q
```

Expected:

- Provider test FAILS because `DeepSeekCoTGroundingRewriter` is not wired.
- API schema test PASSES if schema is unchanged.

- [ ] **Step 4: Wire DeepSeek rewriter**

In `src/ragflow_lite/api/deps/providers.py`, import:

```python
from ragflow_lite.infrastructure.retrievers import (
    DeepSeekChatQueryGrounder,
    DeepSeekCoTGroundingRewriter,
)
```

Construct next to `query_grounder`:

```python
cot_grounding_rewriter = DeepSeekCoTGroundingRewriter(
    api_key=deepseek_runtime_config.api_key,
    base_url=deepseek_runtime_config.base_url,
    model=deepseek_runtime_config.model,
    reasoning_effort=deepseek_runtime_config.reasoning_effort,
)
```

Pass to `MiniGraphFirstRetriever`:

```python
cot_grounding_rewriter=cot_grounding_rewriter,
```

- [ ] **Step 5: Run provider/API tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_providers.py::test_build_services_wires_cot_grounding_rewriter_non_live \
  tests/unit/api/test_v0_routes.py::test_query_request_does_not_expose_retrieval_rewrite_strategy -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ragflow_lite/api/deps/providers.py tests/unit/api/test_providers.py tests/unit/api/test_v0_routes.py
git commit -m "feat: wire gated retrieval rewrite provider"
```

Expected: commit succeeds.

## Task 9: Verify DiscoRAG Boundary And Update Contracts

Purpose: prove `DiscoRAGQueryService` receives resolved retrieval results and document the landed behavior.

**Files:**

- Modify: `tests/unit/application/test_discorag_query_service.py`
- Modify: `src/ragflow_lite/application/CONTRACTS.md`

- [ ] **Step 1: Add DiscoRAG boundary test**

Add to `tests/unit/application/test_discorag_query_service.py`:

```python
def test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata() -> None:
    retrieval_result = TopologyRetrievalResult(
        query="ambiguous question",
        grounded_query=GroundedQuery(
            query="ambiguous question",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        chunks=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="retrieved evidence",
                score=1.0,
                metadata={"selected_for_answer": True, "selected_for_discourse": True},
            )
        ],
        paths=[],
        metadata={
            "retrieval_rewrite": {
                "enabled": True,
                "triggered": True,
                "status": "failed",
                "fallback_source": "initial_candidate_snapshot",
            },
            "supplemental_discourse_chunks": {},
        },
    )
    retriever = FakeTopologyRetriever(result=retrieval_result)
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=FakeDiscourseExtractor(),
        inter_chunk_graph_builder=FakeInterChunkGraphBuilder(),
        blueprint_builder=FakeBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("ambiguous question", top_k=1)

    assert answerer.last_request is not None
    assert answerer.last_request.metadata["retrieval_rewrite"]["status"] == "failed"
    assert retriever.calls == [("ambiguous question", 1)]
```

Adapt fake class names to the existing test file helpers.

- [ ] **Step 2: Run boundary test and verify it fails if metadata is dropped**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata -q
```

Expected: PASS if existing metadata propagation already preserves `retrieval_rewrite`; otherwise FAIL and implement the minimal propagation fix in `DiscoRAGQueryService`.

- [ ] **Step 3: Update application contract after tests pass**

Add a short section to `src/ragflow_lite/application/CONTRACTS.md`:

```markdown
## MiniRAG Retrieval Rewrite

- Retrieval rewrite is an internal MiniRAG capability owned by `MiniGraphFirstRetriever`.
- `/queries` does not expose a rewrite strategy field; routing remains `standard` or `discorag`.
- The deterministic gate uses final answer candidates, not internal graph/path/discourse-only candidates.
- `cot_grounding` may produce only explicit `solution_steps`; the grounding layer extracts entities, relations, and answer-type keywords.
- CoT rewrite may run at most once. Post-rewrite assessment may mark retrieval degraded but must not trigger recursive rewrite.
- If CoT rewrite exhausts attempts, retrieval falls back to the cached initial candidate snapshot and must not rerun raw-query MiniRAG retrieval.
- DiscoRAG receives the resolved MiniRAG retrieval result and does not own rewrite decisions.
```

- [ ] **Step 4: Run contract-adjacent focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/unit/application/test_discorag_query_service.py src/ragflow_lite/application/CONTRACTS.md
git commit -m "docs: document MiniRAG retrieval rewrite boundary"
```

Expected: commit succeeds.

## Task 10: Final Focused Verification

Purpose: run the minimal affected suite and make sure no boundary regressed.

- [ ] **Step 1: Run domain and application tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_minirag_topology_models.py \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/application/test_discorag_query_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run infrastructure rewriter and answerer tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Expected: PASS.

- [ ] **Step 3: Run provider and route boundary tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_providers.py \
  tests/unit/api/test_v0_routes.py -q
```

Expected: PASS.

- [ ] **Step 4: Run import smoke for touched modules**

Run:

```bash
.venv/bin/python - <<'PY'
from ragflow_lite.application.services.mini_graph_first_retriever import MiniGraphFirstRetriever
from ragflow_lite.application.services.retrieval_rewrite import decide_grounding_gate
from ragflow_lite.infrastructure.retrievers import DeepSeekCoTGroundingRewriter, OpenAIResponsesCoTGroundingRewriter
from ragflow_lite.domain.models import InitialCandidateSnapshot, CoTGroundingResult

print("imports ok")
PY
```

Expected:

```text
imports ok
```

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intentional files are modified, or the working tree is clean after commits.

## Self-Review Notes

Spec coverage:

- Deterministic local gate is covered by Tasks 2, 5, and 6.
- `solution_steps`-only CoT output is covered by Task 3.
- Initial candidate snapshot and no duplicate raw-query retrieval are covered by Task 5.
- Successful enriched grounding and auxiliary retrieval are covered by Task 6.
- Post-rewrite degraded notice and no recursive rewrite are covered by Task 7.
- API/router/DiscoRAG boundary preservation is covered by Tasks 8 and 9.
- Contract update after behavior lands is covered by Task 9.

Implementation choices made by this plan:

- Use typed domain models rather than metadata-only contracts.
- Add `CoTGroundingRewriter` as a sibling port instead of widening `QueryGrounder`.
- Keep the first merge rule minimal: dedupe by `chunk_id`, preserve highest score, attach source metadata, then trim to `top_k`.
- Wire DeepSeek rewriter in `build_services()` because current runtime provider wiring already uses DeepSeek for query grounding.

# Source: docs/superpowers/plans/2026-05-18-deepeval-query-mode-artifacts.md

Role: distractor
Status: historical
Topic: 2026-05-18-deepeval-query-mode-artifacts
SHA256: 94e53c6650260688885de06c7ca44f5c67955da76b53d9fdbaa1d94a804ea370

# DeepEval Query Mode Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add run-level `standard` / `discorag` query-mode selection to the DeepEval RAG harness and make local DeepEval artifacts mode-aware.

**Architecture:** Keep query mode as evaluation run metadata, not golden-case metadata. Reuse the existing `/api/v0/queries` production `mode` field, and add a small test-support helper for mode resolution and payload construction. Update the summary script so `query_mode` is carried in normalized summaries, `run_id` includes mode exactly once, rolling latest files are mode-specific, and automatic baseline discovery is same-mode only.

**Tech Stack:** Python, pytest, DeepEval CLI exports, FastAPI test client, local JSON artifact scripts.

---

## File Structure

- Modify `tests/eval_support.py`: define the eval query-mode contract and helper functions used by `tests/conftest.py`, `tests/evals/test_rag_deepeval.py`, and unit tests.
- Modify `tests/conftest.py`: add `--query-mode` as an optional pytest argument with valid choices; leave `--run-deepeval` gating unchanged.
- Modify `tests/evals/test_rag_deepeval.py`: resolve selected mode and include `"mode"` in the `/api/v0/queries` request payload.
- Modify `tests/evals/summarize_results.py`: add `--query-mode`, mode-aware metadata, mode-aware latest/history paths, same-mode automatic baseline discovery, and explicit cross-mode baseline reporting.
- Modify `tests/unit/test_summarize_results.py`: cover summary/artifact/compare mode semantics.
- Create `tests/unit/test_eval_query_mode.py`: cover query-mode resolution and eval request payload construction without running live DeepEval.
- Modify `tests/evals/AGENTS.md`: update local eval commands to show mode-specific raw export and summary commands.
- Modify `tests/evals/CONTRACTS.md`: record the run-level query-mode and artifact contracts after implementation.
- Modify `tests/AGENTS.md`: update the top-level eval command pointers if they still mention mode-agnostic `data/deepeval/raw`.

Do not modify production API schema, production routes, golden fixtures, metric thresholds, CI configuration, secrets, or runtime dependencies.

### Task 1: Add Shared Query-Mode Helpers

**Files:**
- Modify: `tests/eval_support.py`
- Create: `tests/unit/test_eval_query_mode.py`

- [ ] **Step 1: Write failing unit tests for query-mode resolution and payload construction**

Create `tests/unit/test_eval_query_mode.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from eval_support import build_eval_query_payload, resolve_eval_query_mode


@dataclass(frozen=True, slots=True)
class _Case:
    question: str
    top_k: int


def test_resolve_eval_query_mode_defaults_to_standard() -> None:
    assert resolve_eval_query_mode(None, {}) == "standard"


def test_resolve_eval_query_mode_uses_env_fallback() -> None:
    assert (
        resolve_eval_query_mode(
            None,
            {"RAGFLOW_LITE_EVAL_QUERY_MODE": "discorag"},
        )
        == "discorag"
    )


def test_resolve_eval_query_mode_cli_value_wins_over_env() -> None:
    assert (
        resolve_eval_query_mode(
            "standard",
            {"RAGFLOW_LITE_EVAL_QUERY_MODE": "discorag"},
        )
        == "standard"
    )


@pytest.mark.parametrize("value", ["rerank", "", " standard "])
def test_resolve_eval_query_mode_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ValueError, match="Unsupported eval query mode"):
        resolve_eval_query_mode(None, {"RAGFLOW_LITE_EVAL_QUERY_MODE": value})


def test_build_eval_query_payload_includes_run_level_mode() -> None:
    payload = build_eval_query_payload(
        _Case(question="What matters?", top_k=6),
        query_mode="discorag",
    )

    assert payload == {
        "query": "What matters?",
        "top_k": 6,
        "mode": "discorag",
    }
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_query_mode.py -q
```

Expected: FAIL because `resolve_eval_query_mode` and `build_eval_query_payload` do not exist in `eval_support.py`. If the local environment is missing the existing `deepeval` dependency needed by `eval_support.py`, report that dependency guard separately and continue with the implementation steps in a configured `.venv`.

- [ ] **Step 3: Implement the helper functions**

In `tests/eval_support.py`, add imports and helpers near the existing constants:

```python
from typing import TYPE_CHECKING, Any, Literal, Mapping, Protocol
```

Replace the current import line if needed so it includes `Literal` and `Protocol`.

Add the mode contract below `_DEFAULT_DEEPEVAL_REASONING_EFFORT`:

```python
EvalQueryMode = Literal["standard", "discorag"]
EVAL_QUERY_MODES: tuple[EvalQueryMode, ...] = ("standard", "discorag")
EVAL_QUERY_MODE_ENV_VAR = "RAGFLOW_LITE_EVAL_QUERY_MODE"
_DEFAULT_EVAL_QUERY_MODE: EvalQueryMode = "standard"
```

Add the small protocol and helpers after `RAG_EVAL_CASES = _load_rag_eval_cases()`:

```python
class _EvalQueryCase(Protocol):
    question: str
    top_k: int


def resolve_eval_query_mode(
    cli_value: str | None,
    env: Mapping[str, str | None],
) -> EvalQueryMode:
    raw_mode = cli_value if cli_value is not None else env.get(EVAL_QUERY_MODE_ENV_VAR)
    if raw_mode is None:
        return _DEFAULT_EVAL_QUERY_MODE
    if raw_mode in EVAL_QUERY_MODES:
        return raw_mode
    allowed = ", ".join(EVAL_QUERY_MODES)
    raise ValueError(f"Unsupported eval query mode: {raw_mode!r}. Expected one of: {allowed}.")


def build_eval_query_payload(
    case: _EvalQueryCase,
    *,
    query_mode: EvalQueryMode,
) -> dict[str, Any]:
    return {
        "query": case.question,
        "top_k": case.top_k,
        "mode": query_mode,
    }
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_query_mode.py -q
```

Expected: PASS.

### Task 2: Wire Query Mode Through Pytest and the DeepEval Request

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/evals/test_rag_deepeval.py`
- Test: `tests/unit/test_eval_query_mode.py`

- [ ] **Step 1: Add pytest option wiring**

In `tests/conftest.py`, update the import from `eval_support`:

```python
from eval_support import EVAL_QUERY_MODES, validate_deepeval_env
```

In `pytest_addoption`, after `--run-deepeval`, add:

```python
    parser.addoption(
        "--query-mode",
        choices=EVAL_QUERY_MODES,
        default=None,
        help=(
            "query mode for deepeval RAG evaluation runs "
            "(standard or discorag); defaults to standard, or "
            "RAGFLOW_LITE_EVAL_QUERY_MODE when the option is omitted"
        ),
    )
```

- [ ] **Step 2: Update DeepEval test request payload**

In `tests/evals/test_rag_deepeval.py`, update the import from `eval_support`:

```python
from eval_support import (  # noqa: E402
    RAG_EVAL_CASES,
    build_deepeval_judge_model,
    build_eval_query_payload,
    build_metrics_for_case,
    build_rag_test_case,
    resolve_eval_query_mode,
)
```

Add the pytest request fixture to the test signature:

```python
def test_single_turn_rag_eval_produces_quality_snapshot(
    client: Any,
    fixture_documents_dir: Path,
    case: Any,
    request: pytest.FixtureRequest,
) -> None:
```

Replace the query request block:

```python
    query_response = client.post(
        "/api/v0/queries",
        json={"query": case.question, "top_k": case.top_k},
    )
```

with:

```python
    query_mode = resolve_eval_query_mode(
        request.config.getoption("--query-mode"),
        os.environ,
    )
    query_response = client.post(
        "/api/v0/queries",
        json=build_eval_query_payload(case, query_mode=query_mode),
    )
```

Add `query_mode` to the printed snapshot so the run output is inspectable:

```python
        "e2e": {
            "case": case.name,
            "query_mode": query_mode,
            "has_reference": case.has_reference,
            "document_status": final_payload["status"],
            "context_count": len(payload["contexts"]),
            "answer_length": len(payload["answer"]),
        },
```

- [ ] **Step 3: Verify pytest accepts both modes without running live eval**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode standard -q
```

Expected: collection succeeds. If the environment lacks `deepeval`, expected failure is a pytest usage error from the existing `--run-deepeval requires the 'deepeval' package` guard; do not treat that as a query-mode implementation failure.

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode discorag -q
```

Expected: collection succeeds under the same dependency condition.

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode rerank -q
```

Expected: pytest exits with an invalid choice error for `--query-mode`.

### Task 3: Add Mode Metadata and Run-ID Handling to Summary Script

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_summarize_results.py`

- [ ] **Step 1: Write failing tests for mode metadata and run id**

In `tests/unit/test_summarize_results.py`, update the import list:

```python
from evals.summarize_results import (
    apply_query_mode_to_run_id,
    build_comparison_report,
    build_failed_results_report,
    build_metric_averages_report,
    build_results_summary,
    default_output_path,
    find_previous_summary_path,
    main,
    resolve_results_path,
)
```

Add these tests after `test_resolve_results_path_selects_latest_timestamped_export`:

```python
def test_apply_query_mode_to_run_id_appends_mode_once() -> None:
    assert apply_query_mode_to_run_id("20260518_170000", "standard") == (
        "20260518_170000.standard"
    )
    assert apply_query_mode_to_run_id("20260518_170000.standard", "standard") == (
        "20260518_170000.standard"
    )


def test_default_output_path_uses_mode_aware_latest_files() -> None:
    assert default_output_path("summary", run_id="latest", query_mode="standard").name == (
        "latest.standard.summary.json"
    )
    assert default_output_path("failed", run_id="latest", query_mode="discorag").name == (
        "latest.discorag.failed.json"
    )


def test_default_output_path_uses_run_id_without_double_mode_suffix() -> None:
    path = default_output_path(
        "summary",
        run_id="20260518_170000.discorag",
        query_mode="discorag",
    )

    assert path.name == "20260518_170000.discorag.summary.json"
```

Add a metadata assertion to `test_build_results_summary_preserves_case_metrics_and_reasons` after `summary = build_results_summary(payload)` by wrapping metadata in the script later through `load_summary_document`; keep this test focused on raw conversion. Add a new main-level test instead:

```python
def test_main_adds_mode_metadata_and_source_results_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_dir = tmp_path / "raw" / "standard"
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "20260518_170000"
    raw_path.write_text(
        json.dumps(
            {
                "testFile": "tests/evals/test_rag_deepeval.py",
                "runDuration": 1.0,
                "evaluationCost": 0.0,
                "testCases": [],
            }
        ),
        encoding="utf-8",
    )
    summary_output = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_results.py",
            "--results",
            str(raw_dir),
            "--query-mode",
            "standard",
            "--summary-output",
            str(summary_output),
        ],
    )

    main()

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["run_id"] == "20260518_170000.standard"
    assert summary["query_mode"] == "standard"
    assert summary["source_results_path"] == str(raw_path)
```

- [ ] **Step 2: Run the targeted summary tests and verify they fail**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: FAIL because `apply_query_mode_to_run_id`, `query_mode` support on `default_output_path`, and `--query-mode` are not implemented.

- [ ] **Step 3: Implement mode constants and output path helpers**

In `tests/evals/summarize_results.py`, add near the current constants:

```python
QUERY_MODES = ("standard", "discorag")
QueryMode = str
_RUN_ID_RE = re.compile(r"^\d{8}_\d{6}(?:\.(standard|discorag))?$")
```

Replace `default_output_path` with:

```python
def default_output_path(
    report_kind: str,
    *,
    run_id: str = "latest",
    query_mode: QueryMode | None = None,
) -> Path:
    dirs = {
        "summary": DEFAULT_SUMMARY_DIR,
        "failed": DEFAULT_FAILED_DIR,
        "metrics": DEFAULT_METRICS_DIR,
        "compare": DEFAULT_COMPARE_DIR,
    }
    try:
        output_dir = dirs[report_kind]
        suffix = _REPORT_SUFFIXES[report_kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported report kind: {report_kind}") from exc

    if run_id == "latest":
        if query_mode not in QUERY_MODES:
            raise ValueError("query_mode is required for latest deepeval outputs.")
        return output_dir / f"latest.{query_mode}{suffix}"
    return output_dir / f"{run_id}{suffix}"
```

Add run-id helper functions below `infer_run_id`:

```python
def apply_query_mode_to_run_id(run_id: str, query_mode: QueryMode) -> str:
    if query_mode not in QUERY_MODES:
        raise ValueError(f"Unsupported query mode: {query_mode!r}")
    mode_suffix = f".{query_mode}"
    if run_id.endswith(mode_suffix):
        return run_id
    for mode in QUERY_MODES:
        if run_id.endswith(f".{mode}"):
            raise RuntimeError(
                f"Run id {run_id!r} already carries query mode {mode!r}, "
                f"not {query_mode!r}."
            )
    return f"{run_id}.{query_mode}"


def query_mode_from_run_id(run_id: str) -> str | None:
    for mode in QUERY_MODES:
        if run_id.endswith(f".{mode}"):
            return mode
    return None
```

- [ ] **Step 4: Add query-mode metadata during summary loading**

Change `load_summary_document` signature:

```python
def load_summary_document(
    path: Path,
    *,
    query_mode: QueryMode | None = None,
    source_results_path: Path | None = None,
) -> dict[str, Any]:
```

Replace the tail of `load_summary_document`:

```python
    summary.setdefault("run_id", infer_run_id(path))
    return summary
```

with:

```python
    summary.setdefault("run_id", infer_run_id(path))
    existing_mode = summary.get("query_mode")
    if query_mode is not None:
        if existing_mode is not None and existing_mode != query_mode:
            raise RuntimeError(
                f"Summary query_mode {existing_mode!r} does not match requested "
                f"query_mode {query_mode!r}."
            )
        summary["query_mode"] = query_mode
        summary["run_id"] = apply_query_mode_to_run_id(str(summary["run_id"]), query_mode)
    elif existing_mode is None:
        inferred_mode = query_mode_from_run_id(str(summary["run_id"]))
        if inferred_mode is not None:
            summary["query_mode"] = inferred_mode

    if source_results_path is not None:
        summary["source_results_path"] = str(source_results_path)
    return summary
```

- [ ] **Step 5: Add `--query-mode` to the CLI**

In `main()`, add:

```python
    parser.add_argument(
        "--query-mode",
        choices=QUERY_MODES,
        default="standard",
        help="Query mode represented by this DeepEval run: standard or discorag.",
    )
```

Replace:

```python
    summary_path = resolve_results_path(args.results)
    summary = load_summary_document(summary_path)
    run_id = str(summary.get("run_id") or infer_run_id(summary_path))
```

with:

```python
    summary_path = resolve_results_path(args.results)
    summary = load_summary_document(
        summary_path,
        query_mode=args.query_mode,
        source_results_path=summary_path,
    )
    run_id = str(summary.get("run_id") or apply_query_mode_to_run_id(infer_run_id(summary_path), args.query_mode))
```

- [ ] **Step 6: Run the targeted summary tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: existing tests may still fail where they expect old mode-agnostic latest names; those failures are addressed in the next task.

### Task 4: Make Export-All Outputs Mode-Aware and Disable New Mode-Agnostic Latest Files

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_summarize_results.py`

- [ ] **Step 1: Replace old export-all latest expectations**

Rename `test_main_export_all_writes_latest_and_timestamped_outputs_with_auto_baseline` to:

```python
def test_main_export_all_writes_mode_aware_latest_and_timestamped_outputs_with_auto_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
```

In that test, make the previous summary mode-aware:

```python
    previous_summary = {
        "run_id": "20260421_224937.standard",
        "query_mode": "standard",
        "test_file": "tests/evals/test_rag_deepeval.py",
        "cases": [
            {
                "name": "case-a",
                "success": False,
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.5,
                        "success": False,
                    }
                ],
            }
        ],
    }
    (summary_dir / "20260421_224937.standard.summary.json").write_text(
        json.dumps(previous_summary),
        encoding="utf-8",
    )
```

Change the argv in that test to include mode:

```python
            "--query-mode",
            "standard",
```

Change output reads to mode-aware files:

```python
    latest_summary = json.loads(
        (summary_dir / "latest.standard.summary.json").read_text(encoding="utf-8")
    )
    timestamped_summary = json.loads(
        (summary_dir / "20260421_234301.standard.summary.json").read_text(encoding="utf-8")
    )
    latest_failed = json.loads(
        (failed_dir / "latest.standard.failed.json").read_text(encoding="utf-8")
    )
    latest_metrics = json.loads(
        (metrics_dir / "latest.standard.metrics.json").read_text(encoding="utf-8")
    )
    latest_compare = json.loads(
        (compare_dir / "latest.standard.compare.json").read_text(encoding="utf-8")
    )
```

Update assertions:

```python
    assert latest_summary["run_id"] == "20260421_234301.standard"
    assert latest_summary["query_mode"] == "standard"
    assert latest_summary["source_results_path"] == str(raw_path)
    assert timestamped_summary["run_id"] == "20260421_234301.standard"
    assert latest_failed["run_id"] == "20260421_234301.standard"
    assert latest_failed["query_mode"] == "standard"
    assert latest_failed["failed_cases"] == 0
    assert latest_metrics["query_mode"] == "standard"
    assert latest_metrics["metrics"]["answer_relevancy"]["average_score"] == 1.0
    assert latest_compare["run_id"] == "20260421_234301.standard"
    assert latest_compare["query_mode"] == "standard"
    assert latest_compare["baseline_run_id"] == "20260421_224937.standard"
    assert latest_compare["baseline_query_mode"] == "standard"
    assert not (summary_dir / "latest.summary.json").exists()
    assert not (failed_dir / "latest.failed.json").exists()
    assert not (metrics_dir / "latest.metrics.json").exists()
    assert not (compare_dir / "latest.compare.json").exists()
```

- [ ] **Step 2: Update report builders to carry query mode**

In `tests/evals/summarize_results.py`, update `build_failed_results_report` return value:

```python
    return {
        "run_id": summary.get("run_id"),
        "query_mode": summary.get("query_mode"),
        "test_file": summary.get("test_file"),
        "total_cases": len(cases),
        "failed_cases": len(failed_cases),
        "cases": failed_cases,
    }
```

Update `build_metric_averages_report` return value:

```python
    return {
        "run_id": summary.get("run_id"),
        "query_mode": summary.get("query_mode"),
        "test_file": summary.get("test_file"),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "pass_rate": pass_rate,
        "run_duration": summary.get("run_duration"),
        "evaluation_cost": summary.get("evaluation_cost"),
        "metrics": rendered_metrics,
    }
```

Update existing tests `test_build_failed_results_report_keeps_only_failed_cases` and `test_build_metric_averages_report_aggregates_scores_and_pass_rates` by adding `"query_mode": None` to expected report dictionaries unless the input summary includes an explicit mode.

- [ ] **Step 3: Update export-all targets**

In `main()`, replace export-all target construction:

```python
        summary_targets.extend(
            [DEFAULT_SUMMARY_OUTPUT, default_output_path("summary", run_id=run_id)]
        )
```

with:

```python
        summary_targets.extend(
            [
                default_output_path("summary", run_id="latest", query_mode=args.query_mode),
                default_output_path("summary", run_id=run_id, query_mode=args.query_mode),
            ]
        )
```

Replace failed and metrics target construction similarly:

```python
        failed_targets.extend(
            [
                default_output_path("failed", run_id="latest", query_mode=args.query_mode),
                default_output_path("failed", run_id=run_id, query_mode=args.query_mode),
            ]
        )
        metrics_targets.extend(
            [
                default_output_path("metrics", run_id="latest", query_mode=args.query_mode),
                default_output_path("metrics", run_id=run_id, query_mode=args.query_mode),
            ]
        )
```

Replace compare export-all targets:

```python
            compare_targets.extend(
                [
                    default_output_path("compare", run_id="latest", query_mode=args.query_mode),
                    default_output_path("compare", run_id=run_id, query_mode=args.query_mode),
                ]
            )
```

- [ ] **Step 4: Run the summary tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: remaining failures should be limited to baseline discovery and compare metadata, handled in Task 5.

### Task 5: Restrict Automatic Compare to Same-Mode History and Report Cross-Mode Baselines Explicitly

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_summarize_results.py`

- [ ] **Step 1: Add failing tests for same-mode automatic baseline discovery**

In `tests/unit/test_summarize_results.py`, replace `test_find_previous_summary_path_ignores_latest_and_current_run` with:

```python
def test_find_previous_summary_path_uses_same_mode_history_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "latest.standard.summary.json").write_text("{}", encoding="utf-8")
    older_standard = tmp_path / "20260421_224937.standard.summary.json"
    newer_discorag = tmp_path / "20260421_234301.discorag.summary.json"
    current_standard = tmp_path / "20260422_010203.standard.summary.json"
    older_standard.write_text("{}", encoding="utf-8")
    newer_discorag.write_text("{}", encoding="utf-8")
    current_standard.write_text("{}", encoding="utf-8")

    resolved = find_previous_summary_path(
        run_id="20260422_010203.standard",
        query_mode="standard",
        summary_dir=tmp_path,
    )

    assert resolved == older_standard
```

Add explicit cross-mode and legacy compare tests after `test_build_comparison_report_handles_zero_or_missing_baseline_percent_delta`:

```python
def test_build_comparison_report_records_cross_mode_baseline() -> None:
    summary = {
        "run_id": "20260518_173000.discorag",
        "query_mode": "discorag",
        "cases": [{"name": "case-a", "success": True, "metrics": []}],
    }
    baseline = {
        "run_id": "20260518_170000.standard",
        "query_mode": "standard",
        "cases": [{"name": "case-a", "success": False, "metrics": []}],
    }

    report = build_comparison_report(summary, baseline)

    assert report["query_mode"] == "discorag"
    assert report["baseline_query_mode"] == "standard"


def test_build_comparison_report_marks_legacy_baseline_mode_unknown() -> None:
    summary = {
        "run_id": "20260518_173000.discorag",
        "query_mode": "discorag",
        "cases": [{"name": "case-a", "success": True, "metrics": []}],
    }
    baseline = {
        "run_id": "20260421_170000",
        "cases": [{"name": "case-a", "success": False, "metrics": []}],
    }

    report = build_comparison_report(summary, baseline)

    assert report["query_mode"] == "discorag"
    assert report["baseline_query_mode"] == "unknown"
```

- [ ] **Step 2: Run summary tests and verify failures**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: FAIL because `find_previous_summary_path` does not accept `query_mode`, and compare reports lack mode fields.

- [ ] **Step 3: Update same-mode baseline discovery**

Change `find_previous_summary_path` signature:

```python
def find_previous_summary_path(
    *,
    run_id: str,
    query_mode: QueryMode,
    summary_dir: Path | None = None,
) -> Path | None:
```

Replace candidate filtering with:

```python
    candidates = sorted(
        child
        for child in summary_dir.iterdir()
        if child.is_file()
        and child.name.endswith(_REPORT_SUFFIXES["summary"])
        and _RUN_ID_RE.fullmatch(infer_run_id(child))
        and infer_run_id(child) != run_id
        and query_mode_from_run_id(infer_run_id(child)) == query_mode
    )
```

Update the automatic baseline call in `main()`:

```python
        baseline_ref = find_previous_summary_path(
            run_id=run_id,
            query_mode=args.query_mode,
        )
```

- [ ] **Step 4: Update compare metadata**

In `build_comparison_report`, update the return object:

```python
    return {
        "run_id": current_metrics.get("run_id"),
        "query_mode": summary.get("query_mode", "unknown"),
        "baseline_run_id": baseline_metrics.get("run_id"),
        "baseline_query_mode": baseline_summary.get("query_mode", "unknown"),
        "pass_rate": _build_delta_payload(
            current_metrics.get("pass_rate"),
            baseline_metrics.get("pass_rate"),
        ),
        "metrics": metrics,
    }
```

- [ ] **Step 5: Preserve explicit baseline behavior**

Keep this existing flow:

```python
    if baseline_ref is not None:
        baseline_path = resolve_results_path(baseline_ref)
        baseline_summary = load_summary_document(baseline_path)
        comparison_report = build_comparison_report(summary, baseline_summary)
```

Do not pass `query_mode=args.query_mode` when loading `baseline_summary`; explicit cross-mode and legacy baselines must preserve their own `query_mode` or remain `unknown`.

- [ ] **Step 6: Run summary tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: PASS after expected dictionaries are updated for new `query_mode` and `baseline_query_mode` fields.

### Task 6: Update Eval Documentation and Contracts

**Files:**
- Modify: `tests/evals/AGENTS.md`
- Modify: `tests/evals/CONTRACTS.md`
- Modify: `tests/AGENTS.md`

- [ ] **Step 1: Update eval quick commands**

In `tests/evals/AGENTS.md`, replace the Quick commands block with:

```markdown
## Quick commands
```bash
./.venv-goldens/bin/python tests/evals/generate_goldens.py
./.venv/bin/python tests/evals/optimize_prompt.py
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode discorag
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/discorag --query-mode discorag --export-all
```
```

If Markdown fencing becomes nested incorrectly during editing, keep the outer file valid by closing the code fence exactly once after the last command.

- [ ] **Step 2: Add fallback command note**

In `tests/evals/AGENTS.md`, add this paragraph after Quick commands:

```markdown
If the DeepEval CLI does not pass custom pytest options through in a local version, use `RAGFLOW_LITE_EVAL_QUERY_MODE=standard` or `RAGFLOW_LITE_EVAL_QUERY_MODE=discorag` with the same `DEEPEVAL_RESULTS_FOLDER` value and omit `--query-mode` from the `deepeval test run` command.
```

- [ ] **Step 3: Update eval contracts**

In `tests/evals/CONTRACTS.md`, add after Gate requirements:

```markdown
## Query mode

- DeepEval RAG evaluation runs target exactly one query mode: `standard` or `discorag`.
- Preferred selector: `--query-mode standard` or `--query-mode discorag`.
- Fallback selector when a DeepEval CLI version does not forward custom pytest options: `RAGFLOW_LITE_EVAL_QUERY_MODE`.
- If both are available, the explicit pytest option wins.
- Query mode is run-level metadata. It must not be added to `RagEvalCase` or the golden fixture schema.
- The eval request body sent to `/api/v0/queries` includes `mode`.
```

Replace Summary artifacts section with:

```markdown
## Summary artifacts

- `summarize_results.py --export-all --query-mode <mode>` writes mode-specific rolling latest files and timestamped history.
- Raw DeepEval exports should be separated by mode under `data/deepeval/raw/standard/` and `data/deepeval/raw/discorag/`.
- New rolling files use names such as `latest.standard.summary.json`, `latest.discorag.failed.json`, `latest.standard.metrics.json`, and `latest.discorag.compare.json`.
- Timestamped history files derive from `run_id = <timestamp>.<mode>` and do not append mode a second time.
- Mode-agnostic rolling files such as `latest.summary.json` are legacy inputs only and must not be written by the current export flow.
- Default compare discovers only previous summaries with the same `query_mode`.
- Explicit `--baseline` may compare across modes and reports both `query_mode` and `baseline_query_mode`; legacy baselines without mode metadata are reported as `baseline_query_mode: "unknown"`.
- Pytest eval runs do NOT automatically write summary artifacts. Run `summarize_results.py` after raw export.
```

- [ ] **Step 4: Update top-level test command pointers**

In `tests/AGENTS.md`, replace old mode-agnostic eval raw/summary commands with:

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
```

Keep the file concise and point details back to `tests/evals/AGENTS.md` if needed.

- [ ] **Step 5: Verify documentation mentions no new mode-agnostic latest outputs**

Run:

```bash
rtk rg -n "latest\\.summary\\.json|data/deepeval/raw(\\s|$)|summarize_results.py --results data/deepeval/raw --export-all" tests/AGENTS.md tests/evals/AGENTS.md tests/evals/CONTRACTS.md
```

Expected: no active command should write `latest.summary.json` or summarize from `data/deepeval/raw` without `/standard` or `/discorag`. Legacy references in contracts are acceptable only when explicitly described as legacy inputs.

### Task 7: Final Validation

**Files:**
- Verify only; no edits expected.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_query_mode.py tests/unit/test_summarize_results.py -q
```

Expected: PASS.

- [ ] **Step 2: Run eval collection checks for both modes**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode standard -q
```

Expected: collection succeeds if `deepeval` is installed. If `deepeval` is not installed in `.venv`, report the existing dependency guard as unverified live/eval collection, not as a code failure.

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode discorag -q
```

Expected: collection succeeds under the same dependency condition.

- [ ] **Step 3: Verify invalid mode rejection**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode rerank -q
```

Expected: pytest rejects `rerank` as an invalid choice.

- [ ] **Step 4: Run a broader impacted-unit sweep**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py tests/unit/test_summarize_results.py tests/unit/test_eval_query_mode.py -q
```

Expected: PASS, unless the environment lacks `deepeval` and `test_eval_artifact_scripts.py` is skipped by its existing `pytest.importorskip("deepeval")`.

- [ ] **Step 5: Record unverified live execution**

Do not run live DeepEval by default. In the completion report, state that these formal live commands remain opt-in unless the user explicitly requests them:

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval --query-mode standard
```

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval --query-mode discorag
```

## Self-Review Notes

- Spec coverage: The tasks cover run-level mode selection, request payload propagation, shared goldens, mode-aware raw/summary/failed/metrics/compare artifacts, source path metadata, same-mode automatic compare, explicit cross-mode baseline reporting, legacy baseline `unknown`, and unchanged `--run-deepeval` gating.
- Non-goals preserved: No task modifies production API schema, `/api/v0/queries` response schema, golden schema, metrics thresholds, tracing, dashboards, dependencies, CI, or secrets.
- Type consistency: The plan uses `EvalQueryMode` in `tests/eval_support.py` for pytest/runtime query payloads, and script-local `QueryMode = str` in `tests/evals/summarize_results.py` to avoid runtime dependency coupling from the standalone summary script back into pytest helpers.

# Source: docs/superpowers/plans/2026-05-19-microrag-private-bootstrap-goldens.md

Role: distractor
Status: historical
Topic: 2026-05-19-microrag-private-bootstrap-goldens
SHA256: d0c56fed79c7faad752a317dc55cbcc774052045dac0e22914fc8830391a6dae

# MicroRAG Private Bootstrap Goldens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 20-case private, authority-aware MicroRAG bootstrap golden dataset from frozen project-document snapshots.

**Architecture:** Add a pure Python helper module for corpus discovery, snapshot creation, packed fixture assembly, and golden metadata validation. Add a small CLI wrapper that builds the snapshot/fixture and validates a draft golden artifact before it can replace the active DeepEval fixture.

**Tech Stack:** Python stdlib, pytest, existing `tests/eval_support.py`, existing DeepEval artifact format, local `.venv` for tests and `.venv-goldens` only if future LLM generation is wired.

---

## File Structure

### Create

- `tests/evals/private_bootstrap_goldens.py`
  - Owns corpus policy constants, manifest data structures, snapshot copying,
    packed fixture assembly, and static golden validation.
  - Pure stdlib. It must not import `deepeval`, runtime app code, network
    clients, or provider SDKs.

- `tests/evals/build_private_bootstrap_goldens.py`
  - CLI wrapper around `private_bootstrap_goldens.py`.
  - Builds a frozen snapshot and packed fixture.
  - Validates a supplied draft golden JSON before writing or replacing an
    output artifact.
  - Does not call DeepSeek or any LLM in this first implementation.

### Modify

- `tests/unit/test_eval_artifact_scripts.py`
  - Add unit tests for manifest creation, excluded path filtering, packed
    fixture source headers, validation success, and validation failures.

- `tests/evals/AGENTS.md`
  - Add a short command entry for the private bootstrap builder.

- `tests/evals/CONTRACTS.md`
  - Add the active contract only after implementation lands: private bootstrap
    goldens use a frozen snapshot, packed fixture, source-authority metadata,
    and static validation before replacement.

### Generated by the implementation flow

- `tests/fixtures/documents/microrag-private-bootstrap.md`
  - Packed Markdown fixture generated from the frozen snapshot.

- `tests/fixtures/documents/microrag-private-bootstrap-snapshot/`
  - Frozen corpus snapshot.

- `tests/fixtures/evals/private_bootstrap_goldens.draft.json`
  - Draft 20-case artifact used during generation/review.

- `tests/fixtures/evals/synthetic_goldens.json`
  - Existing active artifact. Replace only after validation and collect-only
    pass.

---

## Task 1: Add Corpus Policy And Snapshot Manifest Helpers

**Files:**
- Create: `tests/evals/private_bootstrap_goldens.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add failing tests for corpus role classification**

Append these imports near the other `evals.*` imports in
`tests/unit/test_eval_artifact_scripts.py`:

```python
from evals.private_bootstrap_goldens import (
    CorpusRole,
    classify_corpus_path,
    discover_corpus_paths,
)
```

Append this test near the existing artifact helper tests:

```python
def test_private_bootstrap_classifies_allowed_and_excluded_paths() -> None:
    assert classify_corpus_path(Path("AGENTS.md")) == CorpusRole.AUTHORITATIVE
    assert (
        classify_corpus_path(Path("src/ragflow_lite/CONTRACTS.md"))
        == CorpusRole.AUTHORITATIVE
    )
    assert (
        classify_corpus_path(Path("tests/evals/AGENTS.md"))
        == CorpusRole.AUTHORITATIVE
    )
    assert (
        classify_corpus_path(
            Path("docs/superpowers/specs/2026-05-18-example.md")
        )
        == CorpusRole.DISTRACTOR
    )
    assert (
        classify_corpus_path(
            Path("docs/superpowers/plans/2026-05-19-example.md")
        )
        == CorpusRole.DISTRACTOR
    )

    assert classify_corpus_path(Path("参考项目/网页/deepeval/Faithfulness.md")) is None
    assert classify_corpus_path(Path("tests/fixtures/documents/sample.md")) is None
    assert classify_corpus_path(Path("data/uploads/doc.md")) is None
    assert classify_corpus_path(Path("external/runtime-bundle/README.md")) is None
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_classifies_allowed_and_excluded_paths -q
```

Expected: fail with `ModuleNotFoundError: No module named 'evals.private_bootstrap_goldens'`.

- [ ] **Step 3: Create the helper module with corpus classification**

Create `tests/evals/private_bootstrap_goldens.py`:

```python
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping

PRIVATE_BOOTSTRAP_FIXTURE_NAME = "microrag-private-bootstrap.md"
PRIVATE_BOOTSTRAP_SNAPSHOT_DIR = "microrag-private-bootstrap-snapshot"
PRIVATE_BOOTSTRAP_DRAFT_GOLDENS = "private_bootstrap_goldens.draft.json"
AUTHORITY_RULE = (
    "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior."
)


class CorpusRole(StrEnum):
    AUTHORITATIVE = "authoritative"
    DISTRACTOR = "distractor"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    original_path: str
    snapshot_path: str
    role: str
    topic: str
    status: str
    sha256: str


def normalize_relative_path(path: Path) -> str:
    return path.as_posix().lstrip("./")


def classify_corpus_path(path: Path) -> CorpusRole | None:
    rel = normalize_relative_path(path)
    name = Path(rel).name

    if rel.startswith(
        (
            "参考项目/",
            "tests/fixtures/documents/",
            "data/uploads/",
            "external/runtime-bundle/",
        )
    ):
        return None
    if name.startswith("MinerU_markdown_"):
        return None
    if rel in {"prompt生成与优化指南.md", "context7.md"}:
        return None

    if name in {"AGENTS.md", "CONTRACTS.md"} and (
        rel == name
        or rel.startswith("src/ragflow_lite/")
        or rel.startswith("tests/")
        or rel.startswith("docker/")
    ):
        return CorpusRole.AUTHORITATIVE

    if rel.startswith(("docs/superpowers/specs/", "docs/superpowers/plans/")):
        if rel.endswith(".md"):
            return CorpusRole.DISTRACTOR

    return None


def discover_corpus_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if classify_corpus_path(rel) is not None:
            paths.append(path)
    return paths


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 4: Run the classification test**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_classifies_allowed_and_excluded_paths -q
```

Expected: pass.

- [ ] **Step 5: Add failing test for corpus discovery**

Append this test:

```python
def test_private_bootstrap_discovers_only_allowed_corpus_paths(tmp_path: Path) -> None:
    files = {
        "AGENTS.md": "# root agents\n",
        "src/ragflow_lite/CONTRACTS.md": "# contract\n",
        "tests/evals/AGENTS.md": "# eval agents\n",
        "docs/superpowers/specs/2026-05-18-a.md": "# spec\n",
        "docs/superpowers/plans/2026-05-19-b.md": "# plan\n",
        "参考项目/网页/deepeval/Faithfulness.md": "# public docs\n",
        "tests/fixtures/documents/sample.md": "# old fixture\n",
        "external/runtime-bundle/README.md": "# mixed authority\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    discovered = [
        path.relative_to(tmp_path).as_posix()
        for path in discover_corpus_paths(tmp_path)
    ]

    assert discovered == [
        "AGENTS.md",
        "docs/superpowers/plans/2026-05-19-b.md",
        "docs/superpowers/specs/2026-05-18-a.md",
        "src/ragflow_lite/CONTRACTS.md",
        "tests/evals/AGENTS.md",
    ]
```

- [ ] **Step 6: Run the discovery test**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_discovers_only_allowed_corpus_paths -q
```

Expected: pass. The implementation from Step 3 should already satisfy it.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add tests/evals/private_bootstrap_goldens.py tests/unit/test_eval_artifact_scripts.py
git commit -m "test: add private bootstrap corpus policy"
```

Expected: commit succeeds.

---

## Task 2: Implement Frozen Snapshot Creation

**Files:**
- Modify: `tests/evals/private_bootstrap_goldens.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add failing test for snapshot creation**

Append this test:

```python
def test_private_bootstrap_creates_frozen_snapshot_manifest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    authoritative = root / "tests" / "evals" / "CONTRACTS.md"
    distractor = root / "docs" / "superpowers" / "plans" / "2026-05-19-plan.md"
    authoritative.parent.mkdir(parents=True)
    distractor.parent.mkdir(parents=True)
    authoritative.write_text("# Eval Contracts\n\nActive eval rules.\n", encoding="utf-8")
    distractor.write_text(
        "# Historical Plan\n\nStatus: Ready for implementation after confirmation\n",
        encoding="utf-8",
    )

    snapshot_root = (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap-snapshot"
    )

    from evals.private_bootstrap_goldens import create_snapshot

    entries = create_snapshot(
        repo_root=root,
        source_paths=[authoritative, distractor],
        snapshot_root=snapshot_root,
    )

    assert [entry.role for entry in entries] == ["distractor", "authoritative"]
    assert (snapshot_root / "manifest.json").exists()
    manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["original_path"] for entry in manifest["entries"]] == [
        "docs/superpowers/plans/2026-05-19-plan.md",
        "tests/evals/CONTRACTS.md",
    ]
    assert (
        snapshot_root
        / "authoritative"
        / "tests__evals__CONTRACTS.md"
    ).read_text(encoding="utf-8") == "# Eval Contracts\n\nActive eval rules.\n"
    assert (
        snapshot_root
        / "distractors"
        / "docs__superpowers__plans__2026-05-19-plan.md"
    ).exists()
```

- [ ] **Step 2: Run the snapshot test to verify failure**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_creates_frozen_snapshot_manifest -q
```

Expected: fail with `ImportError` or `AttributeError` for `create_snapshot`.

- [ ] **Step 3: Implement snapshot helpers**

Append these functions to `tests/evals/private_bootstrap_goldens.py`:

```python
def snapshot_filename(relative_path: str) -> str:
    return relative_path.replace("/", "__")


def infer_status(text: str, *, role: CorpusRole) -> str:
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.lower().startswith("status:"):
            return stripped.split(":", 1)[1].strip() or "unknown"
    if role is CorpusRole.AUTHORITATIVE:
        return "active"
    return "historical"


def infer_topic(relative_path: str) -> str:
    path = Path(relative_path)
    if path.name in {"AGENTS.md", "CONTRACTS.md"}:
        return path.parent.as_posix() or "root"
    return path.stem


def write_manifest(snapshot_root: Path, entries: list[ManifestEntry]) -> None:
    payload = {
        "dataset": "microrag-private-bootstrap",
        "entries": [asdict(entry) for entry in entries],
    }
    (snapshot_root / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_snapshot(
    *,
    repo_root: Path,
    source_paths: Iterable[Path],
    snapshot_root: Path,
) -> list[ManifestEntry]:
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    (snapshot_root / "authoritative").mkdir(parents=True, exist_ok=True)
    (snapshot_root / "distractors").mkdir(parents=True, exist_ok=True)

    entries: list[ManifestEntry] = []
    for source_path in sorted(source_paths, key=lambda path: path.relative_to(repo_root).as_posix()):
        relative_path = normalize_relative_path(source_path.relative_to(repo_root))
        role = classify_corpus_path(Path(relative_path))
        if role is None:
            continue

        role_dir = "authoritative" if role is CorpusRole.AUTHORITATIVE else "distractors"
        target_relative = f"{role_dir}/{snapshot_filename(relative_path)}"
        target_path = snapshot_root / target_relative
        shutil.copy2(source_path, target_path)
        text = source_path.read_text(encoding="utf-8")
        entries.append(
            ManifestEntry(
                original_path=relative_path,
                snapshot_path=target_relative,
                role=role.value,
                topic=infer_topic(relative_path),
                status=infer_status(text, role=role),
                sha256=sha256_file(source_path),
            )
        )

    write_manifest(snapshot_root, entries)
    return entries
```

- [ ] **Step 4: Run the snapshot test**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_creates_frozen_snapshot_manifest -q
```

Expected: pass.

- [ ] **Step 5: Run Task 1 and Task 2 tests together**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py -k 'private_bootstrap' -q
```

Expected: all private bootstrap tests pass.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add tests/evals/private_bootstrap_goldens.py tests/unit/test_eval_artifact_scripts.py
git commit -m "feat: create private bootstrap corpus snapshot"
```

Expected: commit succeeds.

---

## Task 3: Implement Packed Fixture Assembly

**Files:**
- Modify: `tests/evals/private_bootstrap_goldens.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add failing test for packed fixture assembly**

Append this test:

```python
def test_private_bootstrap_builds_packed_fixture_from_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    authoritative = root / "AGENTS.md"
    distractor = root / "docs" / "superpowers" / "specs" / "2026-05-18-spec.md"
    distractor.parent.mkdir(parents=True)
    authoritative.write_text("# Working Agreements\n\nUse root cause fixes.\n", encoding="utf-8")
    distractor.write_text("# Draft Spec\n\nStatus: Draft design spec\n", encoding="utf-8")
    snapshot_root = root / "tests" / "fixtures" / "documents" / "microrag-private-bootstrap-snapshot"

    from evals.private_bootstrap_goldens import build_packed_fixture, create_snapshot

    create_snapshot(
        repo_root=root,
        source_paths=[authoritative, distractor],
        snapshot_root=snapshot_root,
    )
    fixture_path = root / "tests" / "fixtures" / "documents" / "microrag-private-bootstrap.md"

    build_packed_fixture(snapshot_root=snapshot_root, fixture_path=fixture_path)

    text = fixture_path.read_text(encoding="utf-8")
    assert "# MicroRAG Private Bootstrap Corpus" in text
    assert "# Source: AGENTS.md" in text
    assert "Role: authoritative" in text
    assert "# Source: docs/superpowers/specs/2026-05-18-spec.md" in text
    assert "Role: distractor" in text
    assert "Use root cause fixes." in text
    assert "Status: Draft design spec" in text
```

- [ ] **Step 2: Run the fixture test to verify failure**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_builds_packed_fixture_from_snapshot -q
```

Expected: fail with `ImportError` or `AttributeError` for `build_packed_fixture`.

- [ ] **Step 3: Implement manifest loading and packed fixture assembly**

Append these functions to `tests/evals/private_bootstrap_goldens.py`:

```python
def load_manifest(snapshot_root: Path) -> list[ManifestEntry]:
    payload = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise RuntimeError("private bootstrap manifest must contain entries.")
    return [ManifestEntry(**entry) for entry in raw_entries]


def build_packed_fixture(*, snapshot_root: Path, fixture_path: Path) -> None:
    entries = load_manifest(snapshot_root)
    parts = [
        "# MicroRAG Private Bootstrap Corpus",
        "",
        "This fixture is generated from a frozen corpus snapshot.",
        "Use source headers and manifest metadata to preserve authority boundaries.",
        "",
    ]
    for entry in entries:
        source_text = (snapshot_root / entry.snapshot_path).read_text(encoding="utf-8")
        parts.extend(
            [
                f"# Source: {entry.original_path}",
                "",
                f"Role: {entry.role}",
                f"Status: {entry.status}",
                f"Topic: {entry.topic}",
                f"SHA256: {entry.sha256}",
                "",
                source_text.rstrip(),
                "",
            ]
        )

    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run the fixture test**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_builds_packed_fixture_from_snapshot -q
```

Expected: pass.

- [ ] **Step 5: Run all private bootstrap tests**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py -k 'private_bootstrap' -q
```

Expected: all private bootstrap tests pass.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add tests/evals/private_bootstrap_goldens.py tests/unit/test_eval_artifact_scripts.py
git commit -m "feat: build private bootstrap packed fixture"
```

Expected: commit succeeds.

---

## Task 4: Add Static Golden Validation

**Files:**
- Modify: `tests/evals/private_bootstrap_goldens.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add passing and failing validator tests**

Append these tests:

```python
def _private_bootstrap_case(
    *,
    name: str,
    case_type: str,
    answerability: str = "answerable",
    required_sources: list[str] | None = None,
    distractor_sources: list[str] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "document_fixture": "microrag-private-bootstrap.md",
        "top_k": 6,
        "case_type": case_type,
        "authority_rule": "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior.",
        "required_authoritative_sources": required_sources or ["AGENTS.md"],
        "distractor_sources": distractor_sources or [],
        "answerability": answerability,
    }
    if case_type == "multi_doc_synthesis":
        metadata["required_authoritative_sources"] = required_sources or [
            "AGENTS.md",
            "tests/evals/CONTRACTS.md",
        ]
        metadata["why_multi_doc"] = "Requires root workflow and eval contract."
    if case_type == "stale_plan_trap":
        metadata["distractor_sources"] = distractor_sources or [
            "docs/superpowers/specs/2026-05-18-example.md"
        ]
        metadata["why_not_answer_from_distractor"] = (
            "The distractor is planning material, not an active contract."
        )
    if case_type == "negative_missing_evidence":
        metadata["answerability"] = "unanswerable"
        metadata["required_authoritative_sources"] = []
        metadata["acceptable_refusal"] = (
            "The authoritative MicroRAG documents in this eval corpus do not establish that."
        )
    return {
        "name": name,
        "input": f"Question for {name}?",
        "expected_output": "Answer grounded in authoritative sources.",
        "context": ["Source context."],
        "sourceFile": "microrag-private-bootstrap.md",
        "additionalMetadata": metadata,
    }


def test_private_bootstrap_validation_accepts_expected_case_distribution() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    payload = []
    payload.extend(
        _private_bootstrap_case(name=f"current-{index}", case_type="current_contract_qa")
        for index in range(8)
    )
    payload.extend(
        _private_bootstrap_case(name=f"multi-{index}", case_type="multi_doc_synthesis")
        for index in range(4)
    )
    payload.extend(
        _private_bootstrap_case(name=f"stale-{index}", case_type="stale_plan_trap")
        for index in range(4)
    )
    payload.extend(
        _private_bootstrap_case(name=f"negative-{index}", case_type="negative_missing_evidence")
        for index in range(2)
    )
    payload.extend(
        _private_bootstrap_case(
            name=f"comparison-{index}",
            case_type="comparison",
            required_sources=["AGENTS.md"],
            distractor_sources=["docs/superpowers/plans/2026-05-19-plan.md"],
        )
        for index in range(2)
    )

    validate_goldens_payload(payload)


def test_private_bootstrap_validation_rejects_stale_plan_only_answer_source() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    payload = [
        _private_bootstrap_case(
            name=f"current-{index}",
            case_type="current_contract_qa",
        )
        for index in range(20)
    ]
    payload[0]["additionalMetadata"]["required_authoritative_sources"] = [
        "docs/superpowers/specs/2026-05-18-example.md"
    ]

    with pytest.raises(RuntimeError, match="authoritative source"):
        validate_goldens_payload(payload)
```

- [ ] **Step 2: Run validator tests to verify failure**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py -k 'private_bootstrap_validation' -q
```

Expected: fail with missing `validate_goldens_payload`.

- [ ] **Step 3: Implement validation helpers**

Append this code to `tests/evals/private_bootstrap_goldens.py`:

```python
EXPECTED_CASE_COUNTS: Mapping[str, int] = {
    "current_contract_qa": 8,
    "multi_doc_synthesis": 4,
    "stale_plan_trap": 4,
    "negative_missing_evidence": 2,
    "comparison": 2,
}


def _metadata_for_case(item: Mapping[str, object], *, index: int) -> Mapping[str, object]:
    metadata = item.get("additionalMetadata", item.get("additional_metadata"))
    if not isinstance(metadata, Mapping):
        raise RuntimeError(f"private bootstrap case #{index} must include additionalMetadata.")
    return metadata


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _require_text(item: Mapping[str, object], key: str, *, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"private bootstrap case #{index} must include non-empty {key}.")
    return value


def _is_authoritative_source(path: str) -> bool:
    return classify_corpus_path(Path(path)) is CorpusRole.AUTHORITATIVE


def _is_allowed_distractor(path: str) -> bool:
    return classify_corpus_path(Path(path)) is CorpusRole.DISTRACTOR


def validate_goldens_payload(payload: object) -> None:
    if not isinstance(payload, list):
        raise RuntimeError("private bootstrap goldens must be a JSON array.")
    if len(payload) != sum(EXPECTED_CASE_COUNTS.values()):
        raise RuntimeError("private bootstrap goldens must contain exactly 20 cases.")

    counts: dict[str, int] = {case_type: 0 for case_type in EXPECTED_CASE_COUNTS}
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, Mapping):
            raise RuntimeError(f"private bootstrap case #{index} must be an object.")
        _require_text(item, "name", index=index)
        _require_text(item, "input", index=index)
        _require_text(item, "expected_output", index=index)
        metadata = _metadata_for_case(item, index=index)

        document_fixture = metadata.get("document_fixture")
        if document_fixture != PRIVATE_BOOTSTRAP_FIXTURE_NAME:
            raise RuntimeError(
                f"private bootstrap case #{index} must use {PRIVATE_BOOTSTRAP_FIXTURE_NAME}."
            )
        top_k = metadata.get("top_k")
        if not isinstance(top_k, int) or top_k <= 0:
            raise RuntimeError(f"private bootstrap case #{index} must include positive top_k.")
        case_type = metadata.get("case_type")
        if not isinstance(case_type, str) or case_type not in EXPECTED_CASE_COUNTS:
            raise RuntimeError(f"private bootstrap case #{index} has unsupported case_type.")
        counts[case_type] += 1

        required_sources = _string_list(metadata.get("required_authoritative_sources"))
        distractor_sources = _string_list(metadata.get("distractor_sources"))
        for source in required_sources:
            if not _is_authoritative_source(source):
                raise RuntimeError(
                    f"private bootstrap case #{index} required source is not an authoritative source: {source}"
                )
        for source in distractor_sources:
            if not _is_allowed_distractor(source):
                raise RuntimeError(
                    f"private bootstrap case #{index} distractor source is not allowed: {source}"
                )

        if case_type != "negative_missing_evidence" and not required_sources:
            raise RuntimeError(f"private bootstrap case #{index} needs an authoritative source.")
        if case_type == "multi_doc_synthesis" and len(required_sources) < 2:
            raise RuntimeError(f"private bootstrap case #{index} needs at least two authoritative sources.")
        if case_type == "stale_plan_trap" and not distractor_sources:
            raise RuntimeError(f"private bootstrap case #{index} needs a distractor source.")
        if case_type == "negative_missing_evidence":
            if metadata.get("answerability") != "unanswerable":
                raise RuntimeError(f"private bootstrap case #{index} must be unanswerable.")
            acceptable_refusal = metadata.get("acceptable_refusal")
            if not isinstance(acceptable_refusal, str) or not acceptable_refusal.strip():
                raise RuntimeError(f"private bootstrap case #{index} needs acceptable_refusal.")

    if counts != dict(EXPECTED_CASE_COUNTS):
        raise RuntimeError(
            f"private bootstrap case distribution must be {dict(EXPECTED_CASE_COUNTS)}, got {counts}."
        )
```

- [ ] **Step 4: Run validator tests**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py -k 'private_bootstrap_validation' -q
```

Expected: tests pass.

- [ ] **Step 5: Run full private bootstrap unit slice**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py -k 'private_bootstrap' -q
```

Expected: all private bootstrap tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add tests/evals/private_bootstrap_goldens.py tests/unit/test_eval_artifact_scripts.py
git commit -m "feat: validate private bootstrap goldens"
```

Expected: commit succeeds.

---

## Task 5: Add CLI Wrapper For Snapshot, Fixture, And Draft Validation

**Files:**
- Create: `tests/evals/build_private_bootstrap_goldens.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add failing CLI smoke test**

Append this test:

```python
def test_private_bootstrap_cli_builds_snapshot_fixture_and_validates_draft(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("# Root\n\nRoot rule.\n", encoding="utf-8")
    contracts = root / "tests" / "evals" / "CONTRACTS.md"
    plan = root / "docs" / "superpowers" / "plans" / "2026-05-19-plan.md"
    contracts.parent.mkdir(parents=True)
    plan.parent.mkdir(parents=True)
    contracts.write_text("# Eval Contract\n\nActive eval rule.\n", encoding="utf-8")
    plan.write_text("# Plan\n\nStatus: Ready for implementation after confirmation\n", encoding="utf-8")
    draft = root / "tests" / "fixtures" / "evals" / "private_bootstrap_goldens.draft.json"
    draft.parent.mkdir(parents=True)
    cases = []
    cases.extend(
        _private_bootstrap_case(name=f"current-{index}", case_type="current_contract_qa")
        for index in range(8)
    )
    cases.extend(
        _private_bootstrap_case(name=f"multi-{index}", case_type="multi_doc_synthesis")
        for index in range(4)
    )
    cases.extend(
        _private_bootstrap_case(name=f"stale-{index}", case_type="stale_plan_trap")
        for index in range(4)
    )
    cases.extend(
        _private_bootstrap_case(name=f"negative-{index}", case_type="negative_missing_evidence")
        for index in range(2)
    )
    cases.extend(
        _private_bootstrap_case(
            name=f"comparison-{index}",
            case_type="comparison",
            distractor_sources=["docs/superpowers/plans/2026-05-19-plan.md"],
        )
        for index in range(2)
    )
    draft.write_text(json.dumps(cases), encoding="utf-8")

    from evals.build_private_bootstrap_goldens import main

    main(["--repo-root", str(root), "--draft-goldens", str(draft)])

    assert (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap.md"
    ).exists()
    assert (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap-snapshot"
        / "manifest.json"
    ).exists()
```

- [ ] **Step 2: Run CLI test to verify failure**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_cli_builds_snapshot_fixture_and_validates_draft -q
```

Expected: fail with `ModuleNotFoundError: No module named 'evals.build_private_bootstrap_goldens'`.

- [ ] **Step 3: Create CLI wrapper**

Create `tests/evals/build_private_bootstrap_goldens.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from private_bootstrap_goldens import (
    PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
    PRIVATE_BOOTSTRAP_FIXTURE_NAME,
    PRIVATE_BOOTSTRAP_SNAPSHOT_DIR,
    build_packed_fixture,
    create_snapshot,
    discover_corpus_paths,
    validate_goldens_payload,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and validate the MicroRAG private bootstrap golden inputs."
    )
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--draft-goldens",
        type=Path,
        default=PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "evals"
        / PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
    )
    parser.add_argument(
        "--output-goldens",
        type=Path,
        default=None,
        help="Optional output path. If omitted, only validates the draft artifact.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    snapshot_root = (
        repo_root
        / "tests"
        / "fixtures"
        / "documents"
        / PRIVATE_BOOTSTRAP_SNAPSHOT_DIR
    )
    fixture_path = (
        repo_root / "tests" / "fixtures" / "documents" / PRIVATE_BOOTSTRAP_FIXTURE_NAME
    )

    source_paths = discover_corpus_paths(repo_root)
    entries = create_snapshot(
        repo_root=repo_root,
        source_paths=source_paths,
        snapshot_root=snapshot_root,
    )
    build_packed_fixture(snapshot_root=snapshot_root, fixture_path=fixture_path)

    draft_payload = json.loads(args.draft_goldens.read_text(encoding="utf-8"))
    validate_goldens_payload(draft_payload)
    if args.output_goldens is not None:
        args.output_goldens.parent.mkdir(parents=True, exist_ok=True)
        args.output_goldens.write_text(
            json.dumps(draft_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "snapshot": str(snapshot_root),
                "fixture": str(fixture_path),
                "sources": len(entries),
                "draft_goldens": str(args.draft_goldens),
                "output_goldens": str(args.output_goldens)
                if args.output_goldens is not None
                else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Fix import path for script and package usage**

Modify the import block in `tests/evals/build_private_bootstrap_goldens.py` to support
both direct script execution and pytest package import:

```python
try:
    from private_bootstrap_goldens import (
        PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
        PRIVATE_BOOTSTRAP_FIXTURE_NAME,
        PRIVATE_BOOTSTRAP_SNAPSHOT_DIR,
        build_packed_fixture,
        create_snapshot,
        discover_corpus_paths,
        validate_goldens_payload,
    )
except ModuleNotFoundError:
    from evals.private_bootstrap_goldens import (
        PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
        PRIVATE_BOOTSTRAP_FIXTURE_NAME,
        PRIVATE_BOOTSTRAP_SNAPSHOT_DIR,
        build_packed_fixture,
        create_snapshot,
        discover_corpus_paths,
        validate_goldens_payload,
    )
```

Remove the earlier single `from private_bootstrap_goldens import ...` block.

- [ ] **Step 5: Run CLI test**

Run:

```bash
PYTHONPATH=tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_private_bootstrap_cli_builds_snapshot_fixture_and_validates_draft -q
```

Expected: pass.

- [ ] **Step 6: Run the CLI help command**

Run:

```bash
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py --help
```

Expected: output contains `Build and validate the MicroRAG private bootstrap golden inputs.`

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add tests/evals/build_private_bootstrap_goldens.py tests/unit/test_eval_artifact_scripts.py
git commit -m "feat: add private bootstrap goldens builder"
```

Expected: commit succeeds.

---

## Task 6: Draft And Validate The 20 Private Bootstrap Cases

**Files:**
- Create: `tests/fixtures/evals/private_bootstrap_goldens.draft.json`
- Generated: `tests/fixtures/documents/microrag-private-bootstrap-snapshot/`
- Generated: `tests/fixtures/documents/microrag-private-bootstrap.md`

- [ ] **Step 1: Build the frozen snapshot and inspect manifest topics**

Run:

```bash
PYTHONPATH=tests/evals:tests:src ./.venv/bin/python - <<'PY'
import json
from pathlib import Path
from private_bootstrap_goldens import create_snapshot, discover_corpus_paths

root = Path(".").resolve()
snapshot = root / "tests/fixtures/documents/microrag-private-bootstrap-snapshot"
entries = create_snapshot(
    repo_root=root,
    source_paths=discover_corpus_paths(root),
    snapshot_root=snapshot,
)
print(json.dumps(
    [{"path": e.original_path, "role": e.role, "topic": e.topic, "status": e.status} for e in entries],
    ensure_ascii=False,
    indent=2,
))
PY
```

Expected: JSON list includes authoritative `AGENTS.md` / `CONTRACTS.md` files
and distractor `docs/superpowers` files. It must not include `参考项目/**`,
`data/uploads/**`, `tests/fixtures/documents/**`, or `external/runtime-bundle/**`.

- [ ] **Step 2: Draft the 20 cases from snapshot evidence**

Create `tests/fixtures/evals/private_bootstrap_goldens.draft.json` with exactly
20 objects. Use this distribution:

```text
current_contract_qa: 8
multi_doc_synthesis: 4
stale_plan_trap: 4
negative_missing_evidence: 2
comparison: 2
```

Every object must use this minimum shape:

```json
{
  "name": "private-bootstrap-001",
  "input": "Question grounded in the frozen MicroRAG corpus?",
  "expected_output": "Evidence-reviewed answer.",
  "expectedOutput": "Evidence-reviewed answer.",
  "context": [
    "Short evidence excerpt or evidence summary from the frozen snapshot."
  ],
  "sourceFile": "microrag-private-bootstrap.md",
  "source_file": "microrag-private-bootstrap.md",
  "additionalMetadata": {
    "document_fixture": "microrag-private-bootstrap.md",
    "top_k": 6,
    "case_type": "current_contract_qa",
    "authority_rule": "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior.",
    "required_authoritative_sources": ["AGENTS.md"],
    "distractor_sources": [],
    "answerability": "answerable"
  },
  "additional_metadata": {
    "document_fixture": "microrag-private-bootstrap.md",
    "top_k": 6,
    "case_type": "current_contract_qa",
    "authority_rule": "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior.",
    "required_authoritative_sources": ["AGENTS.md"],
    "distractor_sources": [],
    "answerability": "answerable"
  }
}
```

Use Codex to choose questions and evidence from the snapshot. Use DeepSeek only
to draft `expected_output` from the selected evidence. Then use Codex to reject
or rewrite any answer claim not supported by authoritative sources.

- [ ] **Step 3: Validate the draft artifact**

Run:

```bash
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py \
  --draft-goldens tests/fixtures/evals/private_bootstrap_goldens.draft.json
```

Expected: command exits 0 and prints JSON with `sources`, `snapshot`, and
`fixture` fields.

- [ ] **Step 4: Inspect generated packed fixture headers**

Run:

```bash
rtk rg -n "^# Source:|^Role:|^Status:" tests/fixtures/documents/microrag-private-bootstrap.md | sed -n '1,80p'
```

Expected: output shows both authoritative sources and distractor sources with
role/status headers.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add \
  tests/fixtures/evals/private_bootstrap_goldens.draft.json \
  tests/fixtures/documents/microrag-private-bootstrap.md \
  tests/fixtures/documents/microrag-private-bootstrap-snapshot
git commit -m "data: draft private bootstrap goldens"
```

Expected: commit succeeds.

---

## Task 7: Replace Active Goldens After Static Validation

**Files:**
- Modify: `tests/fixtures/evals/synthetic_goldens.json`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add active artifact unit test for private bootstrap shape**

Replace the old source-count assertion test in `tests/unit/test_eval_artifact_scripts.py`
with a private-bootstrap-aware test.

Find:

```python
def test_checked_in_goldens_artifact_has_exactly_ten_per_source_document() -> None:
    goldens = load_goldens(DEFAULT_GOLDENS_PATH)
    counts = Counter(golden.source_file for golden in goldens if golden.source_file)

    assert counts == _EXPECTED_EVAL_SOURCE_FILES
```

Replace with:

```python
def test_checked_in_goldens_artifact_is_private_bootstrap_dataset() -> None:
    payload = json.loads(DEFAULT_GOLDENS_PATH.read_text(encoding="utf-8"))

    from evals.private_bootstrap_goldens import validate_goldens_payload

    validate_goldens_payload(payload)
    goldens = load_goldens(DEFAULT_GOLDENS_PATH)

    assert len(goldens) == 20
    assert {golden.source_file for golden in goldens} == {
        "microrag-private-bootstrap.md"
    }
    assert all(golden.input.strip() for golden in goldens)
    assert all(
        golden.expected_output and golden.expected_output.strip() for golden in goldens
    )
```

- [ ] **Step 2: Run the active artifact test to verify failure**

Run:

```bash
PYTHONPATH=tests/evals:tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_checked_in_goldens_artifact_is_private_bootstrap_dataset -q
```

Expected: fail while `synthetic_goldens.json` still contains the older 60-case artifact.

- [ ] **Step 3: Replace the active artifact from the validated draft**

Run:

```bash
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py \
  --draft-goldens tests/fixtures/evals/private_bootstrap_goldens.draft.json \
  --output-goldens tests/fixtures/evals/synthetic_goldens.json
```

Expected: command exits 0 and rewrites `tests/fixtures/evals/synthetic_goldens.json`
with the validated 20-case artifact.

- [ ] **Step 4: Run active artifact tests**

Run:

```bash
PYTHONPATH=tests/evals:tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py::test_checked_in_goldens_artifact_loads_via_prompt_consumer tests/unit/test_eval_artifact_scripts.py::test_checked_in_goldens_artifact_mirrors_context_into_retrieval_context tests/unit/test_eval_artifact_scripts.py::test_checked_in_goldens_artifact_is_private_bootstrap_dataset -q
```

Expected: pass. If `test_checked_in_goldens_artifact_mirrors_context_into_retrieval_context` fails because the new artifact intentionally keeps `retrieval_context` absent, update that test to assert `context` exists and do not require synthetic context to equal runtime retrieval context.

- [ ] **Step 5: Commit Task 7**

Run:

```bash
git add tests/fixtures/evals/synthetic_goldens.json tests/unit/test_eval_artifact_scripts.py
git commit -m "data: activate private bootstrap goldens"
```

Expected: commit succeeds.

---

## Task 8: Update Eval Guidance And Run Collect-Only Validation

**Files:**
- Modify: `tests/evals/AGENTS.md`
- Modify: `tests/evals/CONTRACTS.md`

- [ ] **Step 1: Update eval AGENTS quick commands**

Add this command under `## Quick commands` in `tests/evals/AGENTS.md`:

```bash
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py --draft-goldens tests/fixtures/evals/private_bootstrap_goldens.draft.json
```

Add this bullet under `## File map`:

```markdown
- [build_private_bootstrap_goldens.py](build_private_bootstrap_goldens.py) — builds the frozen private-bootstrap snapshot, packed fixture, and validates the draft golden artifact.
```

- [ ] **Step 2: Update eval contracts**

Add this section to `tests/evals/CONTRACTS.md` after `## Goldens and venvs`:

```markdown
## Private bootstrap goldens

- The private bootstrap dataset uses `tests/fixtures/documents/microrag-private-bootstrap.md` as its packed fixture.
- The packed fixture is generated from `tests/fixtures/documents/microrag-private-bootstrap-snapshot/`.
- `CONTRACTS.md` and `AGENTS.md` snapshot entries are authoritative sources.
- `docs/superpowers` snapshot entries are historical distractors and must not be the sole support for current-runtime claims.
- `tests/fixtures/evals/private_bootstrap_goldens.draft.json` is the review-stage artifact.
- `tests/fixtures/evals/synthetic_goldens.json` remains the active DeepEval artifact consumed by `tests/eval_support.py`.
- Run `tests/evals/build_private_bootstrap_goldens.py` before replacing the active artifact.
```

- [ ] **Step 3: Run unit validation**

Run:

```bash
PYTHONPATH=tests/evals:tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py tests/unit/test_eval_support.py tests/unit/test_eval_query_mode.py -q
```

Expected: all selected unit tests pass.

- [ ] **Step 4: Run collect-only validation**

Run:

```bash
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --collect-only -q
```

Expected: pytest collects exactly 20 cases and does not run live Infinity queries.

- [ ] **Step 5: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add tests/evals/AGENTS.md tests/evals/CONTRACTS.md
git commit -m "docs: document private bootstrap eval workflow"
```

Expected: commit succeeds.

---

## Task 9: Optional Live Eval Smoke

**Files:**
- No source files modified.

- [ ] **Step 1: Confirm live env is present**

Run:

```bash
./.venv/bin/python - <<'PY'
import os
required = ["DEEPSEEK_API_KEY", "ARK_API_KEY", "ARK_EMBEDDING_MODEL"]
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"missing: {', '.join(missing)}")
print("deepeval env ready")
PY
```

Expected: prints `deepeval env ready`. If it exits with missing variables, stop
and report the missing variables. Do not claim live eval is validated.

- [ ] **Step 2: Run standard-mode live DeepEval only if env and Infinity are ready**

Run:

```bash
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard -q
```

Expected: 20 eval cases run against live Infinity in `standard` mode. If this
fails due to provider or Infinity connectivity, report the exact failing layer.

- [ ] **Step 3: Run discorag-mode live DeepEval only after standard mode succeeds**

Run:

```bash
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --query-mode discorag -q
```

Expected: 20 eval cases run against live Infinity in `discorag` mode. If this
fails, keep standard-mode results separate and report the failure boundary.

---

## Final Verification Checklist

- [ ] `PYTHONPATH=tests/evals:tests:src ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py tests/unit/test_eval_support.py tests/unit/test_eval_query_mode.py -q`
- [ ] `./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --collect-only -q`
- [ ] `git diff --check`
- [ ] Optional live standard eval, only if provider and Infinity env are ready.
- [ ] Optional live discorag eval, only after standard mode succeeds.

# Source: docs/superpowers/specs/2026-05-08-discorag-repo-native-stabilization.md

Role: distractor
Status: Draft spec
Topic: 2026-05-08-discorag-repo-native-stabilization
SHA256: e739f585769a0c3f544b263b229139626825d5cb0b902b90d88dd3cbbea1e8ec

# LLM-Backed DiscoRAG Repo-Native Stabilization

Date: 2026-05-09
Status: Draft spec
Scope: `MicroRAG` DiscoRAG stabilization with LLM-backed RST extraction,
LLM-backed inter-chunk rhetorical graph construction, and LLM-backed blueprint
planning.

This document is a planning/specification note, not an active runtime contract.
Active contracts remain in `src/ragflow_lite/**/CONTRACTS.md`.

## Decision

DiscoRAG's structural path must be LLM-backed through the three semantic
organization stages:

```text
MiniRAG retrieval
  -> EvidencePackageBuilder
  -> LLM intra-chunk RST extractor
  -> LLM inter-chunk rhetorical graph builder
  -> LLM DiscoRAG blueprint planner
  -> Answerer(mode="discorag", answer_blueprint=...)
```

The previous deterministic blueprint planner is the same class of problem as
the previous deterministic graph builder: it can produce stable mechanical
structures, but it cannot guarantee paper-faithful discourse-aware
organization. Runtime must not keep deterministic graph or deterministic
blueprint generation as fallback.

Deterministic code remains required for guards:

- JSON parsing;
- schema validation;
- relation type normalization;
- chunk id, relation id, and RST unit id validation;
- self-reference rejection;
- confidence clamping;
- final answer budget validation;
- bounded promotion application;
- answerer-side defensive fallback when an already validated blueprint cannot
  be consumed.

Those are contract guards, not graph/planner generation fallbacks.

## Paper Alignment

The DiscoRAG paper defines a discourse-aware route:

```text
retrieval
-> intra-chunk RST tree
-> inter-chunk rhetorical graph
-> discourse-driven planning / blueprint
-> answer generation
```

The paper's inter-chunk rhetorical graph is listwise model inference over the
retrieved chunks, not a local metadata rule graph.

The paper's discourse-driven planner is also model-generated. It is conditioned
on the query, chunks, RST trees, and inter-chunk graph. The repo-native
implementation should keep a structured `AnswerBlueprint` for engineering
control, but the plan itself must be produced by the structurer model and then
validated.

## Model Roles

DiscoRAG structural modules use a separate structurer-model role:

```text
structurer model:
  intra-chunk RST extraction
  inter-chunk rhetorical graph construction
  DiscoRAG blueprint planning

answer model:
  final natural language generation
```

Initial implementation may reuse the current DeepSeek provider/model for the
structurer role because no smaller dedicated model is available yet. That reuse
must be explicit in settings/provider wiring. A later small-model swap should be
a configuration change, not an architecture rewrite.

The graph builder and blueprint planner must not depend on the final answerer
object. They may use the same provider family, but their role, model name,
reasoning effort, and safe provider metadata should be observable.

## Boundary Contract

MiniRAG owns evidence selection.

DiscoRAG owns evidence organization:

- intra-chunk RST structures;
- inter-chunk rhetorical graph;
- answer blueprint planning;
- bounded promotion proposal and execution.

The structural builders and planner must not:

- query entity or relationship indexes;
- expand MiniRAG topology paths;
- change MiniRAG source selection;
- rerank standard query mode;
- retrieve additional chunks;
- append final answer contexts.

They may consume:

- query text;
- selected answer chunks;
- supplemental discourse-visible chunks;
- chunk text and stable canonical chunk ids;
- compact RST units/roles/relations;
- inter-chunk graph relations;
- MiniRAG metadata as prior context, not as a substitute for model inference.

## Budget Semantics

The final answer context budget is the public `top_n` / service `top_k` budget.

`discourse_selection_k` is a wider visibility budget for discourse
organization. By default it may be derived as `2 * top_k`.

Required behavior:

- `selected_for_answer=True` chunks form the initial final answer candidates.
- `selected_for_discourse=True` chunks form the discourse-visible evidence
  window.
- Supplemental discourse chunks are `selected_for_discourse=True` and
  `selected_for_answer=False`.
- Supplemental discourse chunks can be used by RST extraction, LLM graph
  construction, and LLM blueprint planning.
- Supplemental discourse chunks must not be appended to final contexts.
- Promotion must replace an existing final answer context and keep final answer
  context count bounded by `top_k`.

`chunk_token_budget` and `context_token_budget` are out of scope for this
stabilization.

## LLM Inter-Chunk Graph

The graph builder receives an `IntraChunkDiscoursePackage` and derives the
discourse-visible chunk set from its evidence package.

The prompt should include stable local identifiers:

```text
CHUNK[1] id=<canonical_chunk_id>
<chunk text>
```

If RST structures are available, include compact summaries:

```text
main/claim units
supporting units
condition / qualification / contrast units
available intra-chunk relations
```

Output is structured JSON:

```json
{
  "relations": [
    {
      "source_chunk_id": "chunk-c",
      "target_chunk_id": "chunk-a",
      "relation_type": "contradicts",
      "rationale": "The source updates or opposes the target claim.",
      "confidence": 0.82
    }
  ]
}
```

The allowed materialized inter-chunk relation labels are:

```text
supports
contradicts
elaborates
exemplifies
causes
results_from
enables
prevents
precedes
follows
simultaneous
background_for
generalizes
specifies
compares_with
contrasts_with
supplements
replaces
motivates
justifies
```

`UNRELATED` / `unrelated` is a paper label but must not materialize as an edge.
Unknown labels, unknown chunk ids, and self references must not enter the graph.

Graph failure semantics:

- invalid or unusable LLM graph output raises a clear `ProcessingError`;
- runtime must not call a deterministic graph builder as fallback;
- empty graph is valid only when the model returns a valid empty relation list
  or the discourse-visible chunk set is empty.

## Functional RST Projection

The RST extractor remains LLM-backed and should normalize noisy model output
into compact planning signals rather than attempting a full academic RST parser.

Target planning roles:

```text
claim
evidence
elaboration
definition
condition
qualification
contrast
context
```

Target intra-chunk relation projections:

```text
supports
elaborates
qualifies
contrasts
causes
temporal_next
example_of
defines
background_for
```

Unknown roles should degrade to `context`; unknown relation labels should be
dropped. Prompt labels and normalization aliases must stay aligned. For
example, if the prompt allows `sequences`, the normalizer must map it to
`temporal_next`.

## LLM Blueprint Planner

The blueprint planner is the third structural model stage. It consumes the query,
answer candidates, supplemental discourse chunks, RST structures, inter-chunk
graph, and final answer budget. It returns a structured plan that the answerer
can consume.

Recommended runtime class:

```text
LLMDiscoRAGAnswerBlueprintBuilder
```

The existing deterministic `DiscoRAGAnswerBlueprintBuilder` must not remain as a
runtime planner or public service export. If reusable code is needed, extract it
as non-semantic helpers such as:

```text
parse_llm_discorag_blueprint
validate_discorag_blueprint
apply_blueprint_to_contexts
```

Those helpers must not generate a plan.

### Planner Input

The planner prompt should include:

- query;
- final answer budget / `top_k`;
- answer chunk candidates;
- supplemental discourse-visible chunks;
- chunk text snippets;
- RST unit ids, unit text, roles, nuclearity, and intra-chunk relation
  projections;
- inter-chunk relation ids, source/target chunk ids, relation labels,
  confidence, and rationales;
- instruction that supplemental chunks may enter final contexts only through
  replacement promotion.

### Planner Output

Use strict JSON. Recommended shape:

```json
{
  "final_answer_chunk_ids": ["chunk-a", "chunk-c", "chunk-b"],
  "chunk_roles": {
    "chunk-a": "lead",
    "chunk-c": "support",
    "chunk-b": "caveat"
  },
  "promotions": [
    {
      "replace_chunk_id": "chunk-weak",
      "with_chunk_id": "chunk-c",
      "reason": "The supplemental chunk contains the condition required by the query.",
      "source_relation_ids": ["rel-2"],
      "source_rst_unit_ids": ["chunk-c:u1"]
    }
  ],
  "answer_constraints": [
    {
      "type": "caveat",
      "text": "Mention the condition before generalizing the answer.",
      "source_chunk_ids": ["chunk-b"],
      "source_relation_ids": ["rel-4"],
      "source_rst_unit_ids": ["chunk-b:u2"]
    }
  ],
  "plan_steps": [
    {
      "text": "State the direct answer from chunk-a.",
      "source_chunk_ids": ["chunk-a"],
      "source_relation_ids": [],
      "source_rst_unit_ids": ["chunk-a:u0"]
    }
  ],
  "metadata": {
    "planner": "llm_discorag_answer_blueprint_builder"
  }
}
```

Role vocabulary should stay compact:

```text
lead
support
background
caveat
comparison
definition
condition
context
```

Constraint vocabulary should stay compact:

```text
caveat
condition
conflict
comparison
support
background
definition
ordering
```

### Planner Validation

Validation must reject or fail clearly when:

- output is not valid JSON;
- required fields are missing;
- `final_answer_chunk_ids` is empty while answer candidates exist;
- final chunk count exceeds `top_k`;
- final chunk ids contain duplicates;
- any chunk id is unknown;
- a supplemental chunk appears in `final_answer_chunk_ids` without a matching
  valid replacement promotion;
- a promotion replaces an unknown chunk;
- a promotion replaces a supplemental chunk instead of an answer chunk;
- a promotion inserts an answer chunk as if it were supplemental;
- any referenced relation id is unknown;
- any referenced RST unit id is unknown;
- chunk roles reference chunks outside final/discourse-visible evidence;
- constraints or plan steps invent unsupported evidence.

Planner failure semantics:

- invalid or unusable LLM planner output raises a clear `ProcessingError`;
- runtime must not call a deterministic blueprint planner as fallback;
- query-level downgrade is not part of this slice;
- answerer fallback remains defensive only and should not mask planner failures.

## Answerer Consumption

The answerer receives:

- final contexts already bounded by `top_k`;
- `mode="discorag"`;
- validated `AnswerBlueprint`.

The answerer should use blueprint ordering, roles, constraints, and plan steps
when present. If the answerer receives a missing or invalid blueprint despite
upstream validation, it may fall back to score/context order as a defensive
guard, but this fallback must be observable with a reason such as:

```text
missing_blueprint
invalid_blueprint
partially_invalid_blueprint
```

Partial invalidity matters. A blueprint that contains both valid and unknown
chunk ids is invalid; the answerer must not silently ignore the unknown ids and
claim the blueprint was applied.

## Review Finding Disposition

The latest review findings are folded into this stabilization:

| Finding | Disposition |
| --- | --- |
| deterministic blueprint appends promoted ids | Replace with LLM planner and validation that forbids append promotion. Do not patch the deterministic planner as runtime code. |
| answerer only falls back when all blueprint ids are invalid | Still fix. Answerer fallback is the defensive last line and must catch partial invalidity. |
| RST prompt allows `sequences` but normalizer does not | Still fix. RST extractor remains active. |
| graph metadata omits provider/structurer provenance | Still fix. Graph builder remains active. |
| deterministic graph/blueprint stale exports | Clean runtime and public exports. |
| root contract omits structurer env/config surface | Update after source-backed behavior lands. |
| fake Infinity client concern | No fake Infinity client was found. Fake-client policy remains scoped to Infinity only. |

## Smoke And Verification

The full-chain smoke should exercise mocked structurer calls for graph and
blueprint planning, not deterministic graph or deterministic blueprint builders.

Smoke shape:

```text
MiniGraphFirstRetriever
  -> EvidencePackageBuilder
  -> fake or LLM-backed IntraChunkDiscourseExtractor
  -> LLMInterChunkDiscourseGraphBuilder with mocked response
  -> LLMDiscoRAGAnswerBlueprintBuilder with mocked response
  -> bounded promotion/application
  -> fake Answerer
```

Assertions:

- evidence package contains answer chunks and supplemental discourse chunks;
- graph builder receives all discourse-visible chunks;
- blueprint planner receives query, answer chunks, supplemental chunks, RST
  structures, graph relations, and final answer budget;
- invalid graph output does not silently become deterministic graph output;
- invalid planner output does not silently become deterministic blueprint output;
- planner output references existing relation ids and RST unit ids;
- final answer contexts stay `<= top_k`;
- promotion is replacement, not append;
- answerer receives `mode="discorag"` and a validated blueprint.

## Non-Goals

- Do not optimize p99 latency in this slice.
- Do not introduce a new small-model provider in this slice.
- Do not merge graph and blueprint model calls in this slice.
- Do not keep deterministic graph generation as runtime fallback.
- Do not keep deterministic blueprint generation as runtime fallback.
- Do not reintroduce `chunk_token_budget`.
- Do not treat `context_token_budget` as required DiscoRAG behavior.
- Do not clone the paper's benchmark setup, embedding choice, chunk size, beam
  width, or fine-tuning configuration.
- Do not expose graph/planner internals through HTTP query mode routing.
- Do not broaden fake-client policy beyond Infinity without a separate decision.

## Implementation Order

The execution plan is maintained in
[../plans/2026-05-08-discorag-repo-native-stabilization-plan.md](../plans/2026-05-08-discorag-repo-native-stabilization-plan.md).

High-level order:

1. Confirm current references and stale deterministic planner surfaces.
2. Define LLM blueprint parser/validator contract.
3. Implement LLM blueprint planner.
4. Wire runtime to LLM graph and LLM blueprint structural builders.
5. Remove deterministic graph/blueprint public runtime surfaces.
6. Fix still-relevant review findings.
7. Add full-chain smoke.
8. Promote source-backed facts into active contracts.

# Source: docs/superpowers/specs/2026-05-10-discorag-review-findings-remediation.md

Role: distractor
Status: Draft remediation spec
Topic: 2026-05-10-discorag-review-findings-remediation
SHA256: 16803e163f2e0fbe43fc8f76071bf0dd14ba91d03fc78b388c4dfe09ba471384

# DiscoRAG Review Findings Remediation

Date: 2026-05-10
Status: Draft remediation spec
Parent spec:
[2026-05-08-discorag-repo-native-stabilization.md](2026-05-08-discorag-repo-native-stabilization.md)

This document specifies how to fix the review findings found in the current
DiscoRAG LLM-backed graph/blueprint change set. It is planning material, not an
active runtime contract. Active contracts remain in `src/ragflow_lite/**/CONTRACTS.md`
and should be updated only after source-backed behavior lands.

## Decision

Fix all review findings by tightening the structural path around one rule:

```text
LLM may infer discourse structure.
Code must strictly validate, apply, and expose that structure.
Invalid structure raises ProcessingError.
No deterministic graph or blueprint planner fallback is allowed.
```

The fixes should use the recommended review direction:

- make promotion execution consume replacement pairs, not derived append lists;
- reject append-style promotion at parser time;
- fail fast on mixed-valid/mixed-invalid graph or blueprint output;
- route all DiscoRAG structural model calls through the explicit structurer
  config;
- preserve LLM planner ordering when filtering blueprints to final contexts;
- validate all provenance references, including `source_chunk_ids`;
- record safe provider/structurer provenance;
- remove deterministic planner exports from public application surfaces;
- align contracts and smoke tests with actual behavior.

## Structural Failure Semantics

The graph parser and blueprint parser are part of the structural safety
boundary. They should not silently produce a partial structure from malformed
model output.

Required behavior:

- invalid JSON raises `ProcessingError`;
- missing required fields raise `ProcessingError`;
- wrong field types raise `ProcessingError`;
- unknown chunk ids raise `ProcessingError`;
- unknown relation ids raise `ProcessingError`;
- unknown RST unit ids raise `ProcessingError`;
- invalid relation labels raise `ProcessingError`;
- invalid role or constraint vocab raises `ProcessingError`;
- invalid plan-step structure raises `ProcessingError`;
- self-referential graph edges raise `ProcessingError`;
- mixed valid/invalid output raises `ProcessingError`.

The only graph drop exception is `unrelated`: it is a valid paper label that
means no materialized edge. `unrelated` may be ignored without failure.

Empty graph output is valid only when the LLM returns a structurally valid empty
`relations` array. A non-empty relation array containing only invalid
non-`unrelated` entries is invalid.

## Promotion Contract

Promotion is a bounded replacement operation.

The blueprint parser should preserve structured promotions:

```json
{
  "replace_chunk_id": "answer-weak",
  "with_chunk_id": "supplemental-condition",
  "reason": "The supplemental chunk contains the condition required by the query.",
  "source_chunk_ids": ["supplemental-condition"],
  "source_relation_ids": ["rel-2"],
  "source_rst_unit_ids": ["supplemental-condition:u1"]
}
```

Validation requirements:

- `replace_chunk_id` must be an original answer chunk;
- `with_chunk_id` must be a supplemental discourse chunk;
- `with_chunk_id` must appear in `final_answer_chunk_ids`;
- `replace_chunk_id` must not appear in `final_answer_chunk_ids`;
- any supplemental chunk in `final_answer_chunk_ids` must be explained by a
  valid promotion;
- final answer context count must remain `<= top_k`;
- duplicate final chunk ids are invalid.

Runtime application should consume `metadata["promotions"]` as replacement
pairs. It should not depend on `metadata["promoted_chunk_ids"]` as the source of
truth because that loses the replacement target.

Recommended runtime behavior:

```text
for each valid promotion:
  replace the context with replace_chunk_id by supplemental[with_chunk_id]
preserve final context budget
preserve planner ordering when constructing answer-facing blueprint
```

`promoted_chunk_ids` may be emitted as derived metadata for observability, but
it must not replace the structured promotion contract.

## Planner Ordering Contract

`AnswerBlueprint.ordered_chunk_ids` is planner output and must keep its relative
order after final context filtering.

When `DiscoRAGQueryService` builds the answer-facing blueprint:

```text
ordered_chunk_ids =
  [cid for cid in blueprint.ordered_chunk_ids if cid in final_context_ids]
  + any final_context_ids not already covered, in final context order
```

It must not reconstruct the ordering primarily from retrieval/context order,
because that discards the LLM planner's organization.

## Provenance Reference Validation

Planner output may cite:

- `source_chunk_ids`;
- `source_relation_ids`;
- `source_rst_unit_ids`.

All three are structural references and must be validated:

- `source_chunk_ids` must be known answer or supplemental discourse chunk ids;
- `source_relation_ids` must be relation ids present in the inter-chunk graph;
- `source_rst_unit_ids` must be unit ids present in the RST package.

Unknown provenance references are invalid because they indicate invented or
untraceable evidence.

## Structurer Config Boundary

The structurer model role owns all DiscoRAG structural LLM calls:

```text
DeepSeekChatIntraChunkDiscourseExtractor
LLMInterChunkDiscourseGraphBuilder
LLMDiscoRAGAnswerBlueprintBuilder
```

Initial runtime may reuse DeepSeek, but provider wiring must pass the explicit
structurer config to all three components. The answer model config remains
separate and should not be used accidentally for RST extraction.

## Safe Provenance Metadata

Graph and blueprint builders should include safe LLM provenance in metadata:

```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "reasoning_effort": "high",
  "builder": "llm_inter_chunk_graph_builder"
}
```

If a base URL is included, it must be safe to log. Prefer host-only or sanitized
base URL metadata. Never record API keys.

## Public Surface Cleanup

The deterministic `DiscoRAGAnswerBlueprintBuilder` may remain only as a
test-local stub or a clearly non-runtime helper. It must not be exported from
`ragflow_lite.application.services`.

Runtime and public application exports must not expose deterministic graph or
deterministic blueprint builders as active services.

## Contract Alignment

Contracts should be updated after code changes land:

- `planning_role` count must match actual implementation.
- If implementation has 7 explicit planning roles plus `context` fallback,
  contracts must say that.
- If an eighth explicit role is intended, implementation and tests must add it.
- Contracts must describe structured promotion replacement, strict parser
  failure semantics, structurer config coverage, and public-surface cleanup.

## Smoke Test Requirement

The local DiscoRAG smoke must prove the promoted path actually happens.

Required assertions:

- supplemental promoted chunk is in final answer contexts;
- replaced weak answer chunk is not in final answer contexts;
- final answer context count stays `<= top_k`;
- answer-facing blueprint preserves planner ordering over final contexts;
- graph and blueprint builders are LLM-backed test doubles, not deterministic
  builders.

Conditional assertions such as `if supplemental in contexts: ...` are not
sufficient because they let a no-promotion regression pass.

## Non-Goals

- Do not optimize p99 latency.
- Do not introduce a new small-model provider.
- Do not add query-level downgrade to MiniRAG/basic RAG.
- Do not broaden fake-client policy beyond Infinity.
- Do not restore deterministic graph or blueprint planner fallback.

# Source: docs/superpowers/specs/2026-05-10-discorag-structurer-retry-timeout-repair.md

Role: distractor
Status: Draft implementation spec
Topic: 2026-05-10-discorag-structurer-retry-timeout-repair
SHA256: 241b3d4877f18ff41b814a393efae23e0350fdcade497475a761b23ff5a23d96

# DiscoRAG Structurer Retry, Timeout, And Repair

Date: 2026-05-10
Status: Draft implementation spec
Parent specs:
[2026-05-08-discorag-repo-native-stabilization.md](2026-05-08-discorag-repo-native-stabilization.md),
[2026-05-10-discorag-review-findings-remediation.md](2026-05-10-discorag-review-findings-remediation.md)

This document specifies bounded retry and repair behavior for DiscoRAG
structurer LLM calls. It is planning material, not an active runtime contract.
Active contracts remain in `src/ragflow_lite/**/CONTRACTS.md` and should be
updated only after source-backed behavior lands.

## Decision

DiscoRAG structural validation remains strict, but the first invalid or timed
out structurer attempt should not immediately fail the user-facing query.

The structural path should become:

```text
MiniRAG retrieval
→ LLM intra-chunk RST extraction
→ strict validation, with bounded LLM repair on validation failure
→ LLM inter-chunk discourse graph
→ strict validation, with bounded LLM repair on validation failure
→ LLM DiscoRAG blueprint planner
→ strict validation, with bounded LLM repair on validation failure
→ bounded promotion application
→ answerer
```

Runtime code must still not mechanically repair invalid structure. Validation
failure recovery belongs to the structurer LLM attempt loop, not to
`DiscoRAGQueryService` or answerers.

Required boundaries:

- validation errors trigger bounded LLM repair;
- small structurer tasks time out after 90 seconds by default;
- timeout retries create a fresh attempt;
- validation repair uses multi-turn messages and appends a short validation
  feedback turn;
- validation repair does not repeat the full original task in the repair turn;
- no `compact` repair mode is introduced in this slice;
- no deterministic graph or blueprint fallback is introduced;
- exhausted structurer attempts trigger an explicit DiscoRAG degraded fallback
  to MiniRAG-selected final answer chunks;
- the degraded fallback must be user-visible in answer metadata;
- contracts are promoted only after implementation and tests land.

## Current Implementation Facts

Current local investigation found:

- `DeepSeekChatCompletionsClient.complete()` and `complete_json()` are
  synchronous wrappers around `client.chat.completions.create(...)`.
- The public DeepSeek client contract accepts only `instructions` and
  `input_text`.
- The DeepSeek transport currently sends two messages: one `system` message and
  one `user` message.
- Low-level transport retry exists for retryable API/connection/timeout-like
  exceptions, but there is no schema validation repair loop.
- `DeepSeekChatIntraChunkDiscourseExtractor`,
  `LLMInterChunkDiscourseGraphBuilder`, and
  `LLMDiscoRAGAnswerBlueprintBuilder` each call the LLM once and then parse once.
- No request id, cancellation token, or server-side close mechanism exists in
  the current code.

DeepSeek Chat Completions supports a `messages` array for multi-turn
conversation, but the API is stateless. The caller must send the conversation
history needed for each attempt.

## Retry Types

### Transport Retry

Transport retry covers transient call failures, such as rate limits,
connection errors, provider timeouts, and 5xx responses.

Transport retry is already partially handled by `DeepSeekChatCompletionsClient`.
This spec does not remove that behavior. It adds explicit structurer-level
timeouts and validation repair.

### Timeout Retry

Timeout retry handles an attempt that does not return within the structurer
timeout budget.

Default policy:

```text
discorag_structurer_timeout_seconds = 90
```

Timeout behavior:

```text
attempt-1 starts
→ attempt-1 does not return within 90 seconds
→ attempt-1 is marked expired
→ attempt-2 starts with a fresh original request
→ any late attempt-1 result is ignored
```

Timeout retry must not reuse a partially available answer from the timed-out
attempt. A timeout attempt has no trustworthy assistant message for repair.

If the underlying SDK supports a request timeout, the client should pass the
timeout to the SDK request. If the SDK does not provide true server-side
cancellation, the local runtime must still treat the attempt as expired and
prevent any late result from being consumed.

This spec does not require a full async rewrite. Prefer the smallest correct
implementation that gives the structurer call a bounded request timeout and
clear retry behavior.

### Validation Repair

Validation repair handles an LLM response that returns within the timeout
budget but fails parser or schema validation.

Validation repair must not patch JSON in code. It must ask the structurer LLM
to generate a new complete JSON object, then run the same parser and validator
again.

Validation repair uses multi-turn messages:

```text
system: original structurer instructions
user: original structurer input
assistant: previous invalid JSON output
user: short validation feedback and regeneration instruction
```

The repair user turn should be short. It should include:

- that the previous JSON is invalid;
- the validation error summary;
- only the minimum constraints needed to correct the error;
- an instruction to regenerate one complete JSON object;
- an instruction not to output a patch, markdown, or prose.

The repair user turn must not repeat the complete original task or full
evidence text. The original task is already present in the message history.

The assistant message can contain the previous invalid JSON because it is the
actual previous model output in the conversation history. The repair user turn
should not duplicate that output.

## Attempt Limits

Suggested first implementation:

```text
initial attempt + 1 validation repair attempt
initial attempt + 1 timeout retry attempt
```

The configuration may expose:

```text
discorag_structurer_max_attempts = 2
discorag_structurer_timeout_seconds = 90
```

`max_attempts` counts complete attempts, including the first attempt.

Examples:

```text
max_attempts = 2

validation path:
  attempt 1 returns invalid JSON
  attempt 2 sends multi-turn repair
  attempt 2 valid → success

timeout path:
  attempt 1 times out
  attempt 2 sends fresh original request
  attempt 2 valid → success

exhausted path:
  attempt 1 invalid
  attempt 2 invalid
  raise ProcessingError with both attempt failures summarized
  DiscoRAGQueryService catches the exhausted structurer failure
  answerer receives MiniRAG-selected top_n chunks without a DiscoRAG blueprint
  AnswerResult.metadata exposes the DiscoRAG failure and degraded fallback
```

## Message API Contract

The DeepSeek client should retain existing convenience methods:

```python
complete(instructions: str, input_text: str) -> str
complete_json(instructions: str, input_text: str, *, max_tokens: int = ...) -> str
```

Add message-based methods for structurer repair:

```python
complete_messages(messages: list[dict[str, str]], *, timeout_seconds: float | None = None) -> str
complete_messages_json(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = ...,
    timeout_seconds: float | None = None,
) -> str
```

The existing methods should delegate to the message-based methods by building:

```python
[
    {"role": "system", "content": instructions},
    {"role": "user", "content": input_text},
]
```

JSON methods must continue to set `response_format={"type": "json_object"}` and
must continue to include the JSON-only instruction when needed.

## Attempt Metadata And Observability

Structurer retries should be observable without exposing secrets or full
private prompt bodies.

Each final graph, blueprint, or RST package metadata should include safe
attempt information where appropriate:

```json
{
  "structurer_attempts": 2,
  "structurer_repair_count": 1,
  "structurer_timeout_count": 0,
  "structurer_last_failure_type": "validation_error"
}
```

Do not log API keys, full raw evidence, or full model outputs in metadata.
Tests can inspect fake-client calls directly, but runtime metadata should remain
safe.

## Stage Ownership

### Client Layer

The DeepSeek client owns:

- raw SDK invocation;
- JSON response format;
- low-level retry for transport failures;
- request timeout forwarding when supported by the SDK;
- message-based completion API.

The client does not own schema-specific validation repair prompts.

### Builder Layer

Each structurer builder owns:

- original prompt construction;
- parser invocation;
- validation repair prompt construction;
- bounded repair attempts;
- stage-specific attempt metadata.

The three affected stages are:

- `DeepSeekChatIntraChunkDiscourseExtractor`;
- `LLMInterChunkDiscourseGraphBuilder`;
- `LLMDiscoRAGAnswerBlueprintBuilder`.

### Service And Answerer Layers

`DiscoRAGQueryService` and answerers remain strict consumers:

- do not append missing blueprint ordering;
- do not patch promotion metadata;
- do not invent graph edges or RST units;
- do not downgrade to deterministic planning.

If a builder exhausts its attempts and raises `ProcessingError`, the service
should not silently fail the query. It should degrade to MiniRAG direct answer
mode with explicit error metadata.

## Exhausted Structurer Fallback

When RST extraction, inter-chunk graph construction, or blueprint planning
exhausts `discorag_structurer_max_attempts`, DiscoRAG should stop the DiscoRAG
structural path and answer with the MiniRAG-selected final answer chunks.

Fallback input:

```text
retrieval_result.chunks
```

These are the `top_n` final answer contexts selected by the MiniRAG retriever.
Supplemental discourse chunks must not be appended during fallback.

Fallback answer request:

```text
query = original query
contexts = retrieval_result.chunks
mode = "standard" or an equivalent non-blueprint answer mode
blueprint = None
metadata includes explicit DiscoRAG degraded-fallback error
```

The fallback must be visible to the caller. Because `/queries` already returns
`AnswerResult.metadata`, the answer result must include a user-facing metadata
block such as:

```json
{
  "mode": "discorag",
  "answer_mode": "minirag_fallback",
  "discorag_degraded": true,
  "discorag_error": {
    "stage": "blueprint",
    "error_type": "ProcessingError",
    "failure_type": "validation_error",
    "attempts": 2,
    "max_attempts": 2,
    "message": "LLM DiscoRAG blueprint builder failed after 2 attempts: chunk_roles keys must exactly match final_answer_chunk_ids.",
    "user_visible": true
  }
}
```

The exact key names may follow existing metadata conventions, but the data must
make these facts obvious:

- the user requested DiscoRAG;
- DiscoRAG degraded to MiniRAG direct answer;
- which DiscoRAG stage failed:
  - `rst_extraction`;
  - `inter_chunk_graph`;
  - `blueprint`;
- why it failed:
  - `validation_error`;
  - `timeout`;
  - `transport_error`;
- how many attempts were made;
- what maximum attempt limit was reached;
- a concise, user-visible error message suitable for a future frontend.

This is a fallback from the DiscoRAG structural path to MiniRAG direct answer,
not a deterministic DiscoRAG repair. The service must not create a graph,
blueprint, promotion, or ordering after the structurer stage has failed.

Runtime invariant failures after a supposedly valid blueprint, such as
promotion metadata becoming inconsistent during answer-facing filtering, remain
hard `ProcessingError` failures unless they are explicitly classified as
structurer-exhaustion errors. This prevents the fallback from hiding local
runtime bugs.

## Stage-Specific Repair Guidance

### RST Extractor

Repair feedback should cover:

- unknown `canonical_chunk_id`;
- malformed `chunks` array;
- invalid or missing `units`;
- invalid unit indexes;
- invalid span fields;
- mixed valid and unknown chunk ids.

Repair message example:

```text
Your previous JSON is invalid.

Validation error:
- canonical_chunk_id "chunk_x" is not one of the provided evidence items.

Regenerate one complete JSON object using only canonical_chunk_id values from
the original evidence. Do not output a patch. Do not include markdown or prose.
```

### Inter-Chunk Graph Builder

Repair feedback should cover:

- unknown source or target chunk id;
- self-referential edge;
- invalid relation label;
- malformed relation object;
- invalid `relations` type.

Repair message example:

```text
Your previous JSON is invalid.

Validation error:
- relation[0].target_chunk_id "chunk_missing" is not in the provided chunk ids.

Regenerate one complete JSON object. Use only the valid relation labels and
exact chunk ids from the original prompt. Do not output a patch. Do not include
markdown or prose.
```

### Blueprint Builder

Repair feedback should cover:

- missing final chunk ids in `ordered_chunk_ids`;
- `chunk_roles` not exactly covering `final_answer_chunk_ids`;
- append-style promotion;
- stale or invalid promotion pairs;
- unknown relation ids;
- unknown RST unit ids;
- source references to unknown chunks.

Repair message example:

```text
Your previous JSON is invalid.

Validation error:
- chunk_roles keys must exactly match final_answer_chunk_ids.
- missing role for chunk_id "chunk_b".

Regenerate one complete JSON object. Do not output a patch. Promotions must be
replacement-only: the replaced answer chunk must be absent from
final_answer_chunk_ids and the supplemental chunk must be present.
```

## Non-Goals

- Do not add `compact` repair mode in this slice.
- Do not introduce a new small-model provider.
- Do not optimize p99 latency beyond bounded timeout behavior.
- Do not convert the whole LLM stack to async unless required by a verified SDK
  limitation.
- Do not promise server-side request cancellation if DeepSeek does not provide
  it.
- Do not add deterministic graph, RST, or blueprint fallback.
- Do not change Infinity fake-client policy.
- Do not change MiniRAG retrieval behavior.
- Do not silently fallback to MiniRAG without user-visible error metadata.

## Acceptance Criteria

The implementation is complete when:

- DeepSeek client can send message-based JSON calls while preserving existing
  `complete_json()` behavior.
- Structurer calls have a configurable timeout defaulting to 90 seconds.
- Timeout failure can retry with a fresh original request.
- Validation failure can retry with a multi-turn repair message that does not
  repeat the full original task in the repair turn.
- Repair attempts regenerate complete JSON and re-enter the same strict parser.
- Exhausted structurer attempts degrade to MiniRAG-selected final answer chunks
  and expose a user-visible DiscoRAG error in `AnswerResult.metadata`.
- Blueprint, graph, and RST builders each have focused retry tests.
- Full-chain DiscoRAG smoke proves a validation repair can succeed without
  runtime deterministic repair.
- Full-chain DiscoRAG smoke proves exhausted structurer attempts fallback to
  MiniRAG direct answer with explicit error metadata.
- Existing live Infinity provider tests still pass.

# Source: docs/superpowers/specs/2026-05-10-discorag-structurer-review-remediation.md

Role: distractor
Status: Draft remediation spec
Topic: 2026-05-10-discorag-structurer-review-remediation
SHA256: 0c97903fe2d6fcaee5a439fcb8f9648f3c3226fc6a406ed7f73b2b2caa560282

# DiscoRAG Structurer Review Remediation

Date: 2026-05-10
Status: Draft remediation spec
Parent spec:
[2026-05-10-discorag-structurer-retry-timeout-repair.md](2026-05-10-discorag-structurer-retry-timeout-repair.md)

This document specifies the follow-up fixes required after reviewing the
committed-but-unpushed DiscoRAG structurer retry / timeout / repair slice.
It is planning material, not an active runtime contract. Active contracts
remain in `src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Problem Statement

The current implementation adds the intended high-level behavior:

```text
RST structurer -> graph structurer -> blueprint structurer
  with validation repair + timeout retry
  then explicit MiniRAG fallback after exhausted attempts
```

The review found several issues that weaken the runtime contract:

- fresh structurer attempts pass `timeout_seconds` into
  `DeepSeekChatCompletionsClient.complete_json()`, but the real method does not
  accept that parameter;
- the low-level DeepSeek client can retry timeout-like errors internally, which
  multiplies the structurer timeout budget;
- new structurer retry settings are read into config but not forwarded through
  provider wiring;
- `DiscoRAGQueryService` falls back on every structurer `ProcessingError`,
  rather than only on exhausted structurer attempts;
- exhausted fallback metadata is parsed from free-form error text;
- degraded fallback answers bypass success observability;
- RST extraction accepts missing or duplicate chunk structures silently;
- RST constructor validation is weaker than graph/blueprint constructor
  validation;
- a small unused blueprint local and an unused attempt-state helper create
  avoidable code noise.

## Decision

Use structured exhausted-attempt signaling instead of string parsing.

The structurer builders should raise a dedicated exception only when their
bounded attempt loop is exhausted:

```python
StructurerAttemptsExhaustedError(
    stage="blueprint",
    failure_type="validation_error",
    attempts=2,
    max_attempts=2,
    message="chunk_roles keys must exactly match final_answer_chunk_ids",
)
```

`DiscoRAGQueryService` must only degrade to MiniRAG direct answer when it catches
that dedicated exhausted-attempt exception from one of the three structurer
stages:

- `rst_extraction`
- `inter_chunk_graph`
- `blueprint`

Plain `ProcessingError` from those collaborators must remain a hard failure.
This keeps runtime bugs visible instead of turning them into MiniRAG fallback.

## DeepSeek Timeout And Retry Semantics

Structurer-level timeout ownership must be explicit.

Current risk:

```text
DeepSeek client internal retry: _MAX_DEEPSEEK_RETRIES = 2
Structurer max attempts:       discorag_structurer_max_attempts = 2
Timeout per SDK request:       discorag_structurer_timeout_seconds = 90

Worst case per stage:
90s * 3 low-level SDK attempts * 2 structurer attempts = 540s
```

That violates the intended small-task bound:

```text
90s * 2 structurer attempts = 180s max per structurer stage
```

Required behavior:

- normal non-structurer LLM calls may keep low-level transient retry by default;
- DiscoRAG structurer calls must disable low-level DeepSeek retry;
- each structurer attempt must correspond to one SDK request;
- timeout retry remains owned by the structurer builder;
- timeout metadata must reflect structurer attempts, not hidden transport
  retries.

Recommended API:

```python
complete_json(
    instructions: str,
    input_text: str,
    *,
    max_tokens: int = ...,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str

complete_messages_json(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = ...,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str
```

`max_retries=None` preserves the existing default. Structurer builders pass
`max_retries=0`.

## Config Wiring

`DiscoRAGStructurerRuntimeConfig` already exposes:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Provider wiring must pass these values into:

- `DeepSeekChatIntraChunkDiscourseExtractor`
- `LLMInterChunkDiscourseGraphBuilder`
- `LLMDiscoRAGAnswerBlueprintBuilder`

This makes `DISCORAG_STRUCTURER_TIMEOUT_SECONDS` and
`DISCORAG_STRUCTURER_MAX_ATTEMPTS` real operator controls, not dead settings.

## RST Strictness

`DeepSeekChatIntraChunkDiscourseExtractor._load_structures()` must require exact
coverage of the selected evidence chunks.

Invalid outputs:

- missing structure for a selected chunk;
- duplicate `canonical_chunk_id`;
- unknown `canonical_chunk_id`.

All invalid outputs should raise `ProcessingError` inside the builder attempt
loop, triggering validation repair when attempts remain.

The extractor constructor must also reject:

- `timeout_seconds <= 0`
- `max_attempts < 1`

matching graph and blueprint builder behavior.

## Query Fallback Boundary

Fallback is allowed only for exhausted structurer attempts:

```text
StructurerAttemptsExhaustedError
  -> DiscoRAGQueryService catches it
  -> answerer receives retrieval_result.chunks
  -> mode="standard"
  -> blueprint=None
  -> metadata exposes explicit degraded DiscoRAG error
```

Fallback is not allowed for:

- plain `ProcessingError` from a structurer collaborator;
- promotion application errors;
- answer-facing blueprint filtering errors;
- answerer failures;
- retrieval failures;
- service-local invariant bugs.

## Fallback Metadata

Fallback metadata must be structured and user-visible:

```json
{
  "mode": "discorag",
  "answer_mode": "minirag_fallback",
  "discorag_degraded": true,
  "discorag_error": {
    "stage": "blueprint",
    "error_type": "StructurerAttemptsExhaustedError",
    "failure_type": "validation_error",
    "attempts": 2,
    "max_attempts": 2,
    "message": "...",
    "user_visible": true
  }
}
```

This metadata must not be reconstructed by regex-parsing free-form exception
strings.

## Observability

A degraded MiniRAG fallback is still a successful user-facing answer.

Required behavior:

- normal DiscoRAG success records success;
- degraded MiniRAG fallback records success too;
- degraded path remains distinguishable via metadata and, if logging supports
  it, a `degraded=true` field or event.

Hard failures still record failure.

## Simplification Boundary

After the correctness fixes land:

- remove the unused `all_items` local from
  `LLMDiscoRAGAnswerBlueprintBuilder.build()`;
- make `StructurerAttemptState` runtime-useful by using it to produce
  `StructurerAttemptsExhaustedError`, or delete unused state fields if the
  implementation does not need them;
- do not introduce a large generic retry framework unless it removes real
  duplication without obscuring stage-specific parsing.

## Non-Goals

- Do not restore deterministic graph or blueprint fallback.
- Do not add compact repair mode.
- Do not change MiniRAG retrieval behavior.
- Do not change answer budget semantics.
- Do not change Infinity fake-client policy.
- Do not convert the structurer path to async in this slice.

## Acceptance Criteria

- `DeepSeekChatCompletionsClient.complete_json(..., timeout_seconds=90)` works
  and forwards `timeout` to the SDK request.
- Structurer calls disable low-level DeepSeek retry so one structurer attempt is
  one SDK request.
- Provider wiring passes `timeout_seconds` and `max_attempts` to all three
  structurer components.
- Exhausted attempts raise `StructurerAttemptsExhaustedError` with structured
  stage, failure type, attempts, max attempts, and message.
- `DiscoRAGQueryService` falls back only on
  `StructurerAttemptsExhaustedError`.
- Plain `ProcessingError` from a structurer collaborator propagates.
- Fallback metadata is structured and user-visible without regex parsing.
- Degraded fallback records success observability.
- RST extraction rejects missing and duplicate selected chunk structures.
- Focused tests and full unit tests pass.
- Simplification removes or wires previously unused scaffolding.

# Source: docs/superpowers/specs/2026-05-11-chunk-auxiliary-legacy-field-removal.md

Role: distractor
Status: Draft design spec
Topic: 2026-05-11-chunk-auxiliary-legacy-field-removal
SHA256: 3191c76dc59b27329e1829ca34fb58aab004dd39a4982d3f665c5da47a494dff

# Chunk Auxiliary Legacy Field Removal

Date: 2026-05-11
Status: Draft design spec

This document specifies a narrow cleanup for chunk auxiliary retrieval. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

Remove the query-time legacy chunk text fallback fields from auxiliary chunk
retrieval:

```text
filename^10,text
```

After this change, the default chunk auxiliary `match_text` fields should be:

```text
filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks
```

The change must also remove legacy chunk table compatibility as an active
runtime behavior. A chunk table that lacks the tokenizer-derived text fields
must fail during dependency initialization or schema validation, not later
during query execution.

## Current Implementation Facts

- `CHUNK_FIELD_MATCH_TEXT_FIELDS` currently includes both tokenizer-derived
  fields and the legacy fallback `filename^10,text`.
- `InfinityDenseVectorIndex.search_hybrid()` passes
  `ChunkHybridRetrievalConfig.match_text_fields` directly to
  `chunk_table.match_text(...)`.
- `build_chunk_text_fields()` already generates `filename_kwd`,
  `filename_tks`, `content_tks`, and `content_sm_tks`.
- New chunk table creation already includes those four columns.
- `_chunk_to_row()` already writes those four columns for each embedded chunk.
- `_ensure_fulltext_index()` currently filters required fulltext indexes by
  columns that actually exist. This preserves a legacy migration window for
  chunk tables that only have `filename` and `text`.
- Current schema validation only fail-fasts on `vec` dimension compatibility.
  It does not fail-fast when chunk tokenizer columns or their fulltext indexes
  are absent.
- `filename` and `text` are still required storage columns. They are used by
  chunk lookup, answer context rendering, and evidence package construction.
- Graph candidate retrieval has separate entity and relationship field
  contracts and should not change in this cleanup.

## Problem

The legacy fallback fields still participate in query-time sparse scoring for
new documents:

```text
filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks,filename^10,text
```

This means `filename` and raw `text` continue to affect auxiliary retrieval
weights even after tokenizer-derived fields are available. That keeps old
retrieval semantics alive and makes the chunk auxiliary contract harder to
reason about.

Removing only the fallback string is not enough. Existing legacy chunk tables
may lack the new tokenizer-derived columns. If the code still allows those
tables through initialization, retrieval can fail later when
`search_hybrid()` calls Infinity `match_text(...)` with missing fields. New
ingestion into such a table can also fail because `_chunk_to_row()` writes the
new columns and there is no in-repo schema migration or backfill path.

## Goals

1. Remove `filename^10,text` from default chunk auxiliary `match_text` fields.
2. Keep chunk auxiliary sparse matching limited to tokenizer-derived fields.
3. Treat legacy chunk schemas without tokenizer-derived fields as incompatible.
4. Fail fast during vector index initialization when required chunk text
   columns or fulltext indexes cannot be guaranteed.
5. Preserve `filename` and `text` as stored chunk columns.
6. Preserve `get_chunks()` output shape and answer context rendering.
7. Leave graph candidate retrieval untouched.
8. Make the affected tests explicit before implementation starts.

## Non-Goals

- Do not delete `chunks.filename`.
- Do not delete `chunks.text`.
- Do not change `RetrievedChunk.text`.
- Do not change answerer context formatting.
- Do not change `EvidencePackageBuilder`.
- Do not change `graph_entities` or `graph_relationships`.
- Do not add a schema migration, backfill, or online table rewrite in this
  slice.
- Do not add a public API option for legacy retrieval compatibility.
- Do not change dense retrieval weights, fusion method, position prior, or
  MiniRAG source scoring.

## Target Runtime Contract

### Chunk Auxiliary Fields

The only default sparse fields for chunk auxiliary retrieval should be:

```text
filename_kwd^30
filename_tks^20
content_tks^2
content_sm_tks
```

The legacy fields must not appear in the default field string:

```text
filename^10
text
```

`filename` and `text` remain stored columns. They are not part of the default
`match_text` field list.

### Schema Enforcement

`InfinityDenseVectorIndex` should reject a chunk table that does not contain
all required auxiliary text columns:

```text
filename_kwd
filename_tks
content_tks
content_sm_tks
```

It should also require fulltext indexes for those columns, plus any other
non-legacy active sparse columns required by the chunk auxiliary contract.

The previous behavior of silently skipping missing tokenizer columns should be
removed for the active runtime path. A legacy table should produce a clear
startup or initialization error that tells the operator to rebuild or
re-ingest the chunk table.

### Data Columns That Must Stay

The following columns must remain part of the chunk storage contract:

```text
filename
text
```

They are still needed because:

- `get_chunks()` resolves selected graph chunk ids back to `RetrievedChunk`
  objects with `text`.
- Answerers render chunk `text` as context.
- Metadata and answer context rendering still use `filename`.

### Graph Candidate Boundary

This cleanup does not alter MiniRAG graph candidate retrieval.

Entity matching remains based on entity fields:

```text
entity_name_kwd^30
entity_name_tks^20
entity_type_tks^2
```

Relationship matching remains based on relationship fields:

```text
relationship_endpoint_kwd^30
relationship_endpoint_tks^20
relationship_keyword_tks^20
relationship_description_tks^2
```

Graph candidates continue to reference chunks through `source_chunk_ids`.
Selected chunk ids continue to resolve through the canonical chunk lookup.

## Proposed Implementation Shape

1. Update `CHUNK_FIELD_MATCH_TEXT_FIELDS` to remove
   `CHUNK_LEGACY_MATCH_TEXT_FIELDS`.
2. Remove or demote the legacy field constant so it cannot be accidentally
   reused as part of the default runtime contract.
3. Replace `_ensure_fulltext_index()` migration-window filtering with strict
   validation for active chunk auxiliary columns.
4. Add a clear schema validation error for missing tokenizer-derived columns.
5. Add or update tests so legacy tables without tokenizer-derived fields are
   rejected instead of accepted.
6. Update tests that pin the default field string.
7. Leave graph candidate tests and behavior unchanged.

The implementation should stay inside the chunk auxiliary retrieval and
Infinity dense index surface unless a nearby contract file needs a matching
update after code lands.

## Test Impact

### Must Update

- `tests/unit/infrastructure/test_chunk_text_fields.py`
  - Update the default field string expectation to:
    `filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks`.
- `tests/unit/infrastructure/test_infinity_dense_index.py`
  - Update `ChunkHybridRetrievalConfig.match_text_fields` default expectation.

### Must Change If Legacy Schema Is Rejected

- `tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py`
  - Current purpose: prove a legacy `filename` / `text` chunk table remains
    partially compatible.
  - New purpose should become one of:
    - assert legacy schema is rejected with a clear error, or
    - remove this test if no legacy compatibility contract remains.

### Must Re-Run For Retrieval Safety

These tests do not directly pin the field string, but they exercise real
retrieval behavior or query results that could move after sparse weights
change:

- `tests/integration/infrastructure/test_live_infinity_core_paths.py`
  - Especially `test_live_dense_index_covers_document_dataset_and_retrieval_lifecycle`.
- `tests/integration/api/test_v0_endpoints.py`
  - Especially `test_upload_markdown_then_query_uses_markdown_text`.
  - Especially `test_filename_sparse_recalls_when_text_misses`.
- `tests/integration/api/test_live_infinity_endpoints.py`
  - Especially `test_real_infinity_handles_upload_and_query`.
- `tests/evals/test_rag_deepeval.py`
  - Use only when evaluating retrieval quality drift is in scope.

### Expected To Stay Unchanged

- `tests/unit/infrastructure/test_infinity_hybrid_retriever.py`
  - Uses mocked `vector_index.search_hybrid()` and does not pin field strings.
- `tests/unit/application/test_mini_graph_first_retriever.py`
  - Uses fake auxiliary retrievers and graph fixtures; does not depend on
    Infinity field strings.
- Provider wiring tests that do not inspect chunk sparse fields.

## Validation Plan

Minimum local validation:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_chunk_text_fields.py \
  tests/unit/infrastructure/test_infinity_dense_index.py \
  tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

Schema and retrieval regression validation with live Infinity:

```bash
rtk .venv/bin/python -m pytest --run-live-infinity \
  tests/integration/infrastructure/test_live_infinity_core_paths.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py \
  tests/integration/api/test_v0_endpoints.py \
  tests/integration/api/test_live_infinity_endpoints.py
```

Optional retrieval quality validation:

```bash
rtk .venv/bin/python -m pytest --run-deepeval \
  tests/evals/test_rag_deepeval.py
```

## Risks

- Existing local or deployed Infinity chunk tables with legacy schema will stop
  working until rebuilt.
- If strict schema validation is incomplete, an old table may still pass
  initialization and fail later during query execution.
- Sparse ranking may shift because raw `filename` and raw `text` no longer
  contribute to `match_text`.
- Filename-only recall should still work through `filename_kwd` and
  `filename_tks`, but it must be verified with live Infinity.
- Any local data kept only in legacy tables must be re-ingested, because this
  slice does not include migration or backfill.

## Operational Note

For local development, the expected recovery path from a legacy chunk schema is
to drop/recreate the affected Infinity chunk table and re-ingest documents.
This spec does not define an automated migration command.

# Source: docs/superpowers/specs/2026-05-11-minirag-gated-retrieval-rewrite.md

Role: distractor
Status: Draft design spec
Topic: 2026-05-11-minirag-gated-retrieval-rewrite
SHA256: 212a86d9db6ce48d26487c7843de771197bce0099f7d3b18a099d8ad1ba10fc2

# MiniRAG Gated Retrieval Rewrite

Date: 2026-05-11
Status: Draft design spec

This document specifies a gated retrieval rewrite feature for MiniRAG. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

Add an internal MiniRAG retrieval rewrite path that triggers only when the
first raw-query retrieval result is judged below expectation.

The feature is not a complete multi-query planner. It does not expose a new
HTTP parameter, does not add a new `/queries` mode, and does not introduce
LangGraph, LlamaIndex, HyDE, Step-Back, or a parallel multi-route retrieval
framework.

The first implementation should use one strategy:

```text
cot_grounding
```

`cot_grounding` asks the LLM to produce explicit, retrieval-facing steps for
solving the user query. These are structured grounding steps, not hidden model
chain-of-thought. The output is used as additional input to the grounding
layer, while the grounding layer remains responsible for extracting MiniRAG
retrieval parameters such as entities, relations, and answer-type keywords.
The original user query remains in the retrieval input set.

The intended high-level flow is:

```text
raw query
-> MiniRAG initial retrieval
-> cache initial candidates
-> quality gate
-> if acceptable:
     continue with initial candidates
-> if below expectation:
     request CoT grounding rewrite
     retry once if rewrite output fails
     if rewrite succeeds:
       use raw query + solution_steps for enriched grounding and retrieval
       merge enriched candidates with cached initial candidates
       apply MiniRAG final output window
       assess the final selected candidates without triggering another rewrite
     if rewrite still fails:
       record failure metadata
       continue with cached initial candidates
-> downstream DiscoRAG evidence organization and answering
```

## Current Implementation Facts

Current boundary re-check found:

- Root `AGENTS.md` is navigational, and `CLAUDE.md` points to `AGENTS.md`.
- Active runtime contracts remain under `src/ragflow_lite/**/CONTRACTS.md`.
- `docs/superpowers/specs` and `docs/superpowers/plans` are planning material,
  not runtime contract sources.
- `/queries` still routes only by `mode`, currently `standard` or `discorag`.
- The current active MiniRAG path is centered on
  `MiniGraphFirstRetriever.retrieve_context()`.
- `MiniGraphFirstRetriever` already owns the relevant sequence:
  grounding, entity index lookup, relationship index lookup, path expansion,
  auxiliary chunk retrieval, scoring, and final selection.
- `DiscoRAGQueryService` starts after retrieval. It should not become the owner
  of retrieval rewrite decisions.
- Existing `QueryGrounder` implementations produce basic grounded query data,
  but they do not own rewrite gating, retry state, initial-candidate caching,
  or rewrite failure fallback.
- Current DiscoRAG degraded fallback handles exhausted structurer attempts. It
  is a different fallback path from this feature's rewrite failure fallback.
- No current code references LangGraph or LlamaIndex.
- The top-level `阶段计划` directory is not part of the current repo tree used
  for this spec.

## Goals

1. Improve recall when the first raw-query MiniRAG retrieval is weak because
   the user query is vague, under-specified, or poorly aligned with indexed
   entity/relation wording.
2. Preserve the original query as a first-class retrieval input.
3. Add CoT-derived grounding only as a bounded retrieval enhancement.
4. Cache initial raw-query candidates before triggering the rewrite path.
5. Avoid repeating the same raw-query MiniRAG retrieval when rewrite fails.
6. Make gate decisions, rewrite attempts, failures, and fallback source
   observable in metadata.
7. Preserve existing MiniRAG final output budgets and DiscoRAG downstream
   contracts.

## Non-Goals

- Do not add a public API field for rewrite strategy.
- Do not add a new `QueryModeRouter` mode.
- Do not move retrieval rewrite into `DiscoRAGQueryService`.
- Do not turn this into a full query decomposition or multi-query planner.
- Do not add HyDE, Step-Back, or mixed rewrite strategies in this slice.
- Do not add LangGraph or LlamaIndex in this slice.
- Do not add support for new document formats.
- Do not bypass MiniRAG final output windows.
- Do not use deterministic fallback text as a fake CoT rewrite result.
- Do not treat hidden model chain-of-thought as a runtime contract.
- Do not let CoT rewrite directly output MiniRAG retrieval parameters such as
  entities, relations, or answer-type keywords.

## Core Concepts

### Initial Candidate Snapshot

The first raw-query MiniRAG pass must produce a reusable snapshot before the
rewrite gate triggers.

The snapshot should represent the candidates and selection state that would
have continued into the downstream path if no rewrite were attempted.

The snapshot should be sufficient to continue the query without running the
same raw-query retrieval again.

Suggested conceptual fields:

```text
InitialCandidateSnapshot
  query: str
  grounded_query: GroundedQuery
  candidates: list[RetrievedChunk]
  source_selection: GraphFirstSourceSelection | None
  metadata: dict
```

The exact type shape can be adjusted during implementation, but the contract
must preserve one rule: rewrite failure falls back to this snapshot, not to a
new raw-query retrieval.

### Grounding Gate Decision

The gate decides whether the initial retrieval result is acceptable or should
trigger `cot_grounding`.

The gate must be deterministic and local. It must not call an LLM or use an
LLM-assisted judge. SuperMew is only a reference for the `route +
rewrite_needed + trace` shape, not for its LLM binary relevance grader.

Suggested conceptual fields:

```text
GroundingGateDecision
  should_rewrite: bool
  route: "accept" | "rewrite"
  reason: str
  signals: dict
```

The first implementation should use structural signals from the initial
candidate snapshot. Examples include:

- no entity or relationship matches;
- fewer selected answer candidates than `ceil(requested_top_n / 2)`;
- weak source selection metadata;
- empty or low-confidence auxiliary retrieval;
- explicit retriever fallback reason.

The selected-answer-candidate count must be computed from final candidates
selected for answer, not from all internal graph, path, auxiliary, or
discourse-only candidates. Examples:

```text
top_n = 2 -> trigger when selected_answer_candidate_count < 1
top_n = 3 -> trigger when selected_answer_candidate_count < 2
top_n = 4 -> trigger when selected_answer_candidate_count < 2
top_n = 5 -> trigger when selected_answer_candidate_count < 3
top_n = 8 -> trigger when selected_answer_candidate_count < 4
```

The gate should be conservative. It should not trigger CoT rewrite for every
query. Prompt-based strictness controls are out of scope because they can swing
the gate between optimistic under-triggering and pessimistic over-triggering.

### CoT Grounding Result

`cot_grounding` produces explicit retrieval-facing steps. These steps describe
how to approach the user's question for retrieval purposes.

Suggested conceptual fields:

```text
CoTGroundingResult
  status: "succeeded" | "failed"
  strategy: "cot_grounding"
  original_query: str
  solution_steps: list[str]
  attempts: int
  failure_reason: str | None
```

The field name `solution_steps` is intentional. It should not be documented as
hidden chain-of-thought. It is a structured, explicit output requested for
retrieval grounding.

`CoTGroundingResult` must not include entity, relation, answer-type, or keyword
fields. Those are grounding outputs, not CoT rewrite outputs. The grounding
layer consumes the original query plus `solution_steps` and then extracts the
MiniRAG retrieval parameters.

### Enriched Grounding Input

Successful CoT rewrite must create one explicit enriched grounding input before
calling the grounding layer.

Suggested conceptual fields:

```text
EnrichedGroundingInput
  original_query: str
  solution_steps: list[str]
```

Required invariants:

- `original_query` must be the normalized raw user query from the initial
  candidate snapshot.
- `solution_steps` must come from the successful `CoTGroundingResult`.
- `solution_steps` must contain at least one non-empty step after trimming.
- the enriched grounding input must contain both `original_query` and
  `solution_steps`;
- the implementation must not call the grounding layer with only
  `solution_steps`;
- the implementation must not treat an empty or unusable `solution_steps` result
  as a successful rewrite;
- if `CoTGroundingResult.original_query` does not match the snapshot query, the
  rewrite result must be treated as invalid.

One acceptable rendering for grounding is:

```text
Original query:
<original_query>

Solution steps:
1. <solution_steps[0]>
2. <solution_steps[1]>
...
```

The exact rendering can be chosen during implementation, but this contract is
fixed: triggered successful rewrite means grounding receives the original query
and the CoT solution steps together.

### Post-Rewrite Assessment

The initial gate may trigger at most one CoT rewrite cycle. After a successful
rewrite and enriched MiniRAG retrieval, the implementation may evaluate the same
deterministic gate signals again, but only as a post-rewrite assessment.

Post-rewrite assessment must not trigger a second rewrite.

If the post-rewrite result still fails the gate, the system should continue with
the chunks produced by enriched MiniRAG retrieval and mark the retrieval as
degraded.

Suggested conceptual fields:

```text
PostRewriteAssessment
  gate_passed: bool
  reason: str
  signals: dict
```

If `gate_passed` is false, metadata should record that rewrite already ran and
still did not produce enough retrieval evidence. The answerer must receive an
explicit user-facing notice so it can tell the user that retrieval rewrite was
attempted but the available knowledge still appears insufficient.

The notice should be separate from normal answer content and should not invent
missing facts. It should communicate:

- retrieval rewrite was triggered;
- rewrite completed and enriched MiniRAG retrieval ran;
- the post-rewrite result still did not satisfy the deterministic gate;
- possible causes include missing relevant documents in the knowledge base or a
  query that is still too ambiguous;
- the user may need to rephrase the query or add the needed documents.

## Detailed Behavior

### Normal Path

When the gate decides the initial result is acceptable:

```text
raw query
-> initial MiniRAG retrieval
-> initial candidate snapshot
-> gate accepts
-> continue with initial candidates
```

Metadata should record that rewrite was evaluated and not triggered.

Suggested metadata:

```text
retrieval_rewrite.enabled = true
retrieval_rewrite.triggered = false
retrieval_rewrite.gate_reason = "<reason>"
```

### Triggered And Successful Rewrite Path

When the gate decides the initial result is below expectation:

```text
raw query
-> initial MiniRAG retrieval
-> initial candidate snapshot
-> gate triggers rewrite
-> cot_grounding structured output
-> enriched grounding from raw query + solution_steps
-> enriched MiniRAG retrieval
-> merge cached initial candidates + enriched candidates
-> apply final MiniRAG output window
-> post-rewrite assessment without recursive rewrite
-> downstream DiscoRAG
```

The original query must remain part of the retrieval input set. The CoT
grounding output enhances the query; it does not replace it.

The enriched retrieval pass should enhance both graph grounding and auxiliary
chunk retrieval:

- graph grounding should build an `EnrichedGroundingInput` from the initial
  snapshot query plus `solution_steps`, pass the rendered input to the grounding
  layer, and let the grounding layer extract entity, relation, and answer-type
  retrieval parameters;
- auxiliary chunk retrieval should use an enriched text query built from the
  original query plus `solution_steps`;
- the original query must remain in the auxiliary retrieval input so the
  enhanced query stays anchored to the user's wording.

The final selected chunks must remain bounded by the existing MiniRAG final
window. Additional candidate sources may expand the pool, but they must not
unboundedly append to final answer contexts.

If post-rewrite assessment still fails the gate, the enriched final selected
chunks still continue into DiscoRAG. The system must not run another CoT rewrite.
Instead, it must attach answer-facing degraded retrieval metadata and an
instruction for the answerer to explicitly tell the user that retrieval rewrite
was attempted but available evidence still appears insufficient.

### Triggered But Failed Rewrite Path

When CoT grounding fails:

```text
raw query
-> initial MiniRAG retrieval
-> initial candidate snapshot
-> gate triggers rewrite
-> cot_grounding attempt 1 fails
-> cot_grounding attempt 2 fails
-> record failure metadata
-> use initial candidate snapshot
-> downstream DiscoRAG
```

Failure must not cause a second raw-query MiniRAG retrieval. The cached initial
candidate snapshot is the fallback source.

Suggested metadata:

```text
retrieval_rewrite.enabled = true
retrieval_rewrite.triggered = true
retrieval_rewrite.strategy = "cot_grounding"
retrieval_rewrite.status = "failed"
retrieval_rewrite.attempts = 2
retrieval_rewrite.failure_reason = "<summary>"
retrieval_rewrite.fallback_source = "initial_candidate_snapshot"
```

## Retry And Failure Rules

The first implementation should allow:

```text
initial CoT grounding attempt + 1 retry
```

Rewrite failures include:

- invalid structured output;
- missing or empty `solution_steps`;
- `CoTGroundingResult.original_query` does not match the initial snapshot query;
- provider timeout;
- provider exception;
- empty usable grounding result.

After attempts are exhausted:

- record failure metadata;
- preserve the original exception summary at a safe level of detail;
- continue with `InitialCandidateSnapshot`;
- do not retry raw-query retrieval;
- do not fail the whole `/queries` request only because rewrite failed.

## Candidate Merge And Budget Rules

The feature may increase candidate sources, but it must not increase final
answer contexts beyond the MiniRAG final output budget.

Merge rules should preserve:

- stable chunk identity;
- deduplication by canonical chunk id;
- source metadata for whether a chunk came from the initial pass, enriched
  graph pass, enriched auxiliary pass, or multiple passes;
- final ordering semantics that are explicit and test-covered.

This spec does not mandate the final scoring formula. The plan should choose
the smallest formula that preserves current behavior when rewrite is not
triggered and gives enriched candidates a clear, observable source trail when
rewrite is triggered.

## Layer Boundaries

### API Layer

No API schema change is required for the first implementation.

`POST /queries` should continue to accept the existing request shape and route
only by `mode`.

### Query Router

`QueryModeRouter` should remain a mode dispatcher. It should not learn
retrieval rewrite policy.

### MiniRAG Retrieval Layer

`MiniGraphFirstRetriever` is the preferred owner of the feature because it
already coordinates grounding, graph evidence lookup, auxiliary retrieval, and
final selection.

The enriched retrieval behavior should stay inside this layer: CoT grounding
may enrich graph lookup inputs and auxiliary chunk retrieval inputs, but it
should not create a separate planner above `MiniGraphFirstRetriever`.

If the implementation needs new ports, prefer a wrapper or sibling component
around `QueryGrounder` rather than forcing gate, retry, and cache semantics into
the existing basic `QueryGrounder.ground(query)` contract.

### DiscoRAG Layer

`DiscoRAGQueryService` should receive the final MiniRAG-selected retrieval
result after the rewrite decision has already been resolved.

It should not initiate CoT rewrite, rerun MiniRAG, or own rewrite failure
fallback.

The existing DiscoRAG degraded fallback for exhausted structurer attempts is
separate from this feature. This feature's fallback is retrieval-level fallback
to `InitialCandidateSnapshot`.

### Answerer Layer

Answerers should not need to know the CoT grounding text. They may receive
metadata that explains rewrite status, but the answer contract should not depend
on the rewrite internals.

There is one answer-facing exception: when CoT rewrite succeeds but the
post-rewrite assessment still fails the deterministic gate, the answerer must
receive a degraded retrieval notice. The notice should be delivered through a
dedicated metadata or instruction path, not by mixing the CoT solution steps into
the answer prompt.

This may require a dedicated prompt fragment or answerer instruction used only
for this condition. The fragment should require the final answer to explicitly
tell the user that retrieval rewrite already ran but the retrieved evidence is
still likely insufficient, and that likely causes are missing knowledge-base
documents or an ambiguous query.

## Observability

The feature should expose enough metadata to debug the path taken without
requiring prompt logs.

At minimum:

```text
retrieval_rewrite.enabled
retrieval_rewrite.triggered
retrieval_rewrite.strategy
retrieval_rewrite.status
retrieval_rewrite.gate_reason
retrieval_rewrite.attempts
retrieval_rewrite.failure_reason
retrieval_rewrite.fallback_source
retrieval_rewrite.initial_candidate_count
retrieval_rewrite.enriched_candidate_count
retrieval_rewrite.post_rewrite_gate_passed
retrieval_rewrite.post_rewrite_gate_reason
retrieval_rewrite.answer_notice_required
```

Successful triggered rewrite should record that final candidates may contain
initial-only, enriched-only, and shared sources.

Triggered rewrite followed by failed post-rewrite assessment should record that
rewrite already ran, no second rewrite was attempted, and an answer-facing
degraded retrieval notice is required.

Failed triggered rewrite should record that downstream processing used the
initial candidate snapshot.

## Risks

### Scope Drift

The main risk is turning `cot_grounding` into a full multi-query planner. The
first implementation must stop at gated grounding enhancement.

### Over-Triggering

If the gate is too eager, simple queries may become slower and less precise.
The first gate should be conservative, observable, and deterministic. It must
not rely on prompt wording such as "strict" to tune rewrite frequency.

### Candidate Merge Drift

The new path adds candidate sources. The final window prevents unbounded final
context growth, but merge, dedupe, ordering, and metadata propagation still
need focused tests.

### Output Boundary Drift

The LLM may produce verbose reasoning text. The runtime contract should accept
only structured `solution_steps`, not arbitrary prose as a hidden decision
source and not direct entity, relation, or answer-type extraction.

### Fallback Ambiguity

Rewrite failure fallback and DiscoRAG structurer fallback are separate. Metadata
must make it clear which fallback happened.

### Recursive Rewrite Drift

The rewrite path must not recurse. A successful rewrite may be followed by a
post-rewrite assessment, but that assessment is only for observability and
answer-facing warning behavior. It must not trigger another CoT rewrite.

## Validation Requirements

Implementation should add focused tests before changing behavior.

Required coverage:

- gate not triggered keeps current MiniRAG output behavior;
- gate is deterministic and does not call an LLM judge;
- gate triggers when selected answer candidates are fewer than
  `ceil(requested_top_n / 2)`;
- gate candidate-count logic uses final answer candidates, not internal graph,
  path, auxiliary, or discourse-only candidates;
- gate triggered snapshots initial candidates before CoT rewrite;
- successful CoT rewrite uses raw query plus `solution_steps`;
- successful CoT rewrite calls the grounding layer with an input containing both
  the original query and `solution_steps`;
- successful CoT rewrite never calls the grounding layer with only
  `solution_steps`;
- empty `solution_steps` or mismatched `CoTGroundingResult.original_query` is
  treated as rewrite failure, not success;
- grounding layer, not CoT rewrite, extracts entity/relation/answer-type
  retrieval parameters;
- enriched and initial candidates are deduped and remain final-window bounded;
- post-rewrite assessment can mark the result degraded but never triggers a
  second rewrite;
- post-rewrite gate failure still sends enriched MiniRAG chunks into DiscoRAG;
- post-rewrite gate failure adds answer-facing metadata or instructions that
  require the final answer to tell the user rewrite already ran but evidence
  remains insufficient;
- failed first CoT attempt retries once;
- exhausted CoT attempts record failure metadata;
- exhausted CoT attempts continue with cached initial candidates;
- exhausted CoT attempts do not rerun raw-query MiniRAG retrieval;
- `DiscoRAGQueryService` receives a resolved retrieval result and does not own
  rewrite decisions;
- `/queries` request schema and mode routing stay unchanged.

Likely test files:

- `tests/unit/application/test_mini_graph_first_retriever.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/domain/test_minirag_topology_models.py`
- `tests/unit/infrastructure/test_deepseek_query_grounder.py`
- `tests/unit/infrastructure/test_openai_query_grounder.py`
- `tests/unit/api/test_v0_routes.py`

Provider wiring may also require:

- `tests/unit/api/test_providers.py`

## Open Questions For Plan

The implementation plan should decide:

1. Whether `InitialCandidateSnapshot`, `GroundingGateDecision`, and
   `CoTGroundingResult` become typed domain models or structured metadata first.
2. Whether CoT grounding is implemented as a wrapper around `QueryGrounder` or a
   sibling port.
3. The exact candidate merge ordering rule.
4. The exact metadata path used to surface rewrite observability.
5. The exact answerer metadata or instruction path for post-rewrite degraded
   retrieval notices.

# Source: docs/superpowers/specs/2026-05-18-deepeval-query-mode-artifacts-design.md

Role: distractor
Status: Draft design spec
Topic: 2026-05-18-deepeval-query-mode-artifacts-design
SHA256: 2e8a230ac7276bceb0705220c4b474aea043d8eb092533dd386425495ad3f92f

# DeepEval Query Mode Artifacts

Date: 2026-05-18
Status: Draft design spec

This document specifies the next DeepEval adaptation slice: single-mode RAG
evaluation for the current `standard` and `discorag` query modes, with
mode-aware artifact storage. It is planning material, not an active runtime
contract. Active contracts remain in `tests/evals/CONTRACTS.md`,
`tests/CONTRACTS.md`, and `src/ragflow_lite/**/CONTRACTS.md` until the
implementation lands.

## Decision

Add a run-level query mode selector for DeepEval RAG evaluation.

Each evaluation run targets exactly one mode:

```text
standard
discorag
```

The selected mode is part of the run configuration, not part of the golden
dataset. The same goldens must be reusable for both modes unless a future
golden-generation design explicitly changes the dataset scope.

Mode must also become part of the run identity and local artifact naming so
`standard` and `discorag` runs do not overwrite each other's latest summary,
failed-case, metrics, or compare outputs.

Cross-mode comparison is not automated in this slice. Default compare behavior
compares only same-mode historical runs. Cross-mode comparison may be performed
only when the user explicitly supplies a baseline path.

Run identity must carry mode directly:

```text
run_id = <timestamp>.<mode>
```

History files then use:

```text
<run_id>.<kind>.json
```

They must not append mode a second time.

## Current Facts

- DeepEval docs do not define a native `standard` / `discorag` selector.
- DeepEval docs describe evaluation as test cases plus metrics. Scores are
  `0-1`, default metric threshold is generally `0.5`, and a test case passes
  only when all selected metrics pass.
- DeepEval docs document `DEEPEVAL_RESULTS_FOLDER` as an export directory for
  timestamped JSON run output, but do not define a per-mode folder or suffix
  convention.
- The repository currently gates live DeepEval runs with `--run-deepeval`;
  `--run-deepeval` implies live Infinity.
- The current test harness posts `query` and `top_k` to `/api/v0/queries`; it
  does not pass `mode`.
- The API already accepts `QueryRequest.mode` as `standard` or `discorag`, and
  the route already forwards it to `QueryModeRouter`.
- The current summary script already supports raw DeepEval exports, normalized
  summaries, rolling latest files, timestamped history files, and explicit
  baselines for compare.
- The current compare payload is mode-agnostic, so mode must be carried by
  run id, output path, and summary metadata before compare output is trusted.

## Goals

1. Let the user choose the evaluated query mode for a run.
2. Keep DeepEval default-off and live-Infinity-gated.
3. Reuse the same golden cases for both modes.
4. Pass the selected mode through the `/api/v0/queries` request body.
5. Add mode-aware run identity so artifacts remain readable and non-overwriting.
6. Preserve existing summary, failed-case, metrics, and compare workflows.
7. Make same-mode historical comparison the default.
8. Allow explicit cross-mode comparison only when the user provides a baseline.

## Non-Goals

- Do not generate or redesign goldens in this slice.
- Do not add `mode` to `RagEvalCase` or the golden fixture schema.
- Do not run both modes in one DeepEval invocation.
- Do not add a new production query API field.
- Do not change `/api/v0/queries` response schema.
- Do not add SuperMew-style `rag_trace`.
- Do not add OpenTelemetry, Tempo, Jaeger, or span-level tracing.
- Do not change metric thresholds in this slice.
- Do not automate cross-mode comparison.
- Do not build a Grafana dashboard or Loki query helper in this slice.

## Run Mode Contract

The eval harness should accept one selected query mode:

```text
standard | discorag
```

Recommended pytest option:

```text
--query-mode standard
--query-mode discorag
```

Debug-oriented pytest runs may default to `standard`, because it is the
baseline query path. Formal DeepEval export commands must specify mode
explicitly.

Preferred mode input:

```text
--query-mode standard
--query-mode discorag
```

Fallback mode input, only if `deepeval test run` does not pass custom pytest
options through:

```text
RAGFLOW_LITE_EVAL_QUERY_MODE=standard
RAGFLOW_LITE_EVAL_QUERY_MODE=discorag
```

If both are present, the explicit pytest option should win.

The test request payload must include the selected mode:

```json
{
  "query": "...",
  "top_k": 6,
  "mode": "standard"
}
```

or:

```json
{
  "query": "...",
  "top_k": 6,
  "mode": "discorag"
}
```

The route and application services already support this mode dispatch. The
implementation should not add another application service selector.

## Artifact Layout

Raw DeepEval exports should be separated by mode:

```text
data/deepeval/raw/standard/
data/deepeval/raw/discorag/
```

Summary-family artifacts should stay under the existing directories but use
mode-specific latest files:

```text
data/deepeval/summary/latest.standard.summary.json
data/deepeval/summary/latest.discorag.summary.json

data/deepeval/failed/latest.standard.failed.json
data/deepeval/failed/latest.discorag.failed.json

data/deepeval/metrics/latest.standard.metrics.json
data/deepeval/metrics/latest.discorag.metrics.json

data/deepeval/compare/latest.standard.compare.json
data/deepeval/compare/latest.discorag.compare.json
```

Timestamped history files should also include mode:

```text
data/deepeval/summary/20260518_170000.standard.summary.json
data/deepeval/summary/20260518_173000.discorag.summary.json
```

The exact timestamp part should continue to follow the existing summary
script's run-id behavior. The mode must be part of `run_id`, not an additional
suffix layered on top of `run_id`.

Mode-agnostic rolling files must not be written in this slice:

```text
data/deepeval/summary/latest.summary.json
data/deepeval/failed/latest.failed.json
data/deepeval/metrics/latest.metrics.json
data/deepeval/compare/latest.compare.json
```

The summary script may continue to read legacy mode-agnostic normalized
summaries as explicit baselines, but it should not create new ones.

When `--results` points to a raw export directory such as
`data/deepeval/raw/standard`, the summary script must select the newest raw
DeepEval export in that directory and record the selected source path in
summary metadata. Users may still pass a specific raw JSON file to avoid
directory selection.

## Summary Schema

Normalized summary documents should include run-level mode metadata:

```json
{
  "run_id": "20260518_170000.standard",
  "query_mode": "standard",
  "source_results_path": "data/deepeval/raw/standard/20260518_170000.json",
  "cases": []
}
```

Case names should remain the original golden case names. Mode belongs in
run-level metadata, not in case names or golden-case attributes.

The summary script should preserve mode metadata when loading an already
normalized summary.

## Compare Semantics

Default compare behavior:

```text
current standard run -> previous standard summary
current discorag run -> previous discorag summary
```

If the user supplies `--baseline`, the script may compare against that file
even when modes differ. In that case the compare report must include enough
metadata to make the comparison explicit:

```json
{
  "query_mode": "discorag",
  "baseline_query_mode": "standard"
}
```

The script must not silently compare a `standard` run against a `discorag`
baseline discovered automatically from latest files or timestamped history.

Legacy normalized summaries without `query_mode` may be used only when supplied
explicitly as `--baseline`. They should be reported as:

```json
{
  "baseline_query_mode": "unknown"
}
```

Legacy mode-agnostic summaries must not participate in automatic baseline
discovery.

## Threshold Semantics

This slice does not change metric thresholds.

The correct contract is:

- DeepEval metrics have documented default thresholds, commonly `0.5`.
- This repository constructs metric objects in `tests/eval_support.py`.
- The accepted behavior for this slice is to keep the current metric
  construction unchanged.
- Any future threshold change must be explicit in `tests/evals/CONTRACTS.md`
  and covered by targeted tests.

Do not describe pass/fail as entirely "DeepEval built-in" if repository code
explicitly configures metric objects.

## Commands

Recommended raw export commands:

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval --query-mode standard
```

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval --query-mode discorag
```

Fallback raw export commands if DeepEval CLI does not pass custom pytest
options through:

```bash
RAGFLOW_LITE_EVAL_QUERY_MODE=standard \
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval
```

```bash
RAGFLOW_LITE_EVAL_QUERY_MODE=discorag \
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval
```

Recommended summary commands:

```bash
./.venv/bin/python tests/evals/summarize_results.py \
  --results data/deepeval/raw/standard \
  --query-mode standard \
  --export-all
```

```bash
./.venv/bin/python tests/evals/summarize_results.py \
  --results data/deepeval/raw/discorag \
  --query-mode discorag \
  --export-all
```

## Risks

### Mode-Leaking Goldens

Putting mode into the golden fixture would fragment the dataset and make
same-question comparisons harder. Mode belongs to the run, not the case.

### Compare Against the Wrong Baseline

Current compare logic is mode-agnostic. If mode is not included in run identity
and output naming, compare results can look valid while comparing unrelated
evaluation targets.

### Latest File Overwrite

Only separating raw exports is not enough. If summary, failed-case, metrics, or
compare latest files remain mode-agnostic, one mode can overwrite the other.
This slice stops writing new mode-agnostic latest files.

### Threshold Drift

Changing thresholds while adding mode support would make it unclear whether
score movement came from query mode behavior or metric policy. Threshold changes
must be a separate slice.

### Cross-Mode Interpretation

Cross-mode comparison is useful but easy to misread. `standard` and `discorag`
may trade off answer quality, contextual precision, and recall differently.
Automatic cross-mode comparison should wait until same-mode historical
evaluation is stable.

## Acceptance Criteria

- `--query-mode standard` sends `"mode": "standard"` to `/api/v0/queries`.
- `--query-mode discorag` sends `"mode": "discorag"` to `/api/v0/queries`.
- Goldens remain shared and mode-free.
- Summary documents include run-level `query_mode`.
- Summary documents record the selected raw export source path when `--results`
  is a directory.
- Raw exports can be stored under mode-specific folders.
- `latest.standard.*.json` and `latest.discorag.*.json` do not overwrite each
  other.
- Mode-agnostic `latest.*.json` files are not written.
- `run_id` includes mode exactly once.
- Timestamped history file names derive from `run_id` and do not append mode a
  second time.
- Default compare discovers only same-mode historical summaries.
- Explicit `--baseline` can compare across modes and records both modes.
- Explicit legacy baselines without mode metadata are accepted as
  `baseline_query_mode: "unknown"`.
- Existing explicit output path behavior remains usable.
- Existing `--run-deepeval` gating remains unchanged.

## Implementation Notes

Likely file touch points:

- `tests/conftest.py`: add and validate `--query-mode`.
- `tests/evals/test_rag_deepeval.py`: read selected mode and pass it in query
  payloads; fall back to `RAGFLOW_LITE_EVAL_QUERY_MODE` when needed.
- `tests/evals/summarize_results.py`: add `--query-mode`, mode-aware latest
  paths, mode-aware run id handling, newest-file directory selection, legacy
  baseline handling, and same-mode baseline discovery.
- `tests/evals/AGENTS.md`: update commands after implementation.
- `tests/evals/CONTRACTS.md`: record the mode and artifact contracts after
  implementation.

Tests should focus on:

- option validation;
- query payload mode propagation;
- summary mode metadata;
- source raw export path metadata;
- mode-aware latest path selection;
- no new mode-agnostic latest outputs;
- run id mode suffix applied exactly once;
- same-mode baseline discovery;
- explicit cross-mode baseline reporting.
- explicit legacy baseline reporting as unknown mode.

Live DeepEval execution remains an opt-in validation step and should not be
required for unit tests.

# Source: docs/superpowers/specs/2026-05-18-microrag-private-bootstrap-goldens.md

Role: distractor
Status: Draft design spec
Topic: 2026-05-18-microrag-private-bootstrap-goldens
SHA256: 4b8642ca829bbfa2c00a7a91920cbce9f72305b35c2b6709b5fa7d4c28b86269

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

# Source: src/ragflow_lite/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite
SHA256: 4f09083208bd7bf9fe9b1a415d20bad51b360491bd14fb2b4d1803aba3b2c1cf

# AGENTS.md

## 概述
这个目录是后端源码根，只维护分层边界和源码级导航。具体实现约束应写到最近的子目录 [AGENTS.md](./AGENTS.md)。

## Active Contracts
Runtime contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite --full
rtk cx overview src/ragflow_lite/application/services --full
rtk cx overview src/ragflow_lite/infrastructure --full
```

## 架构
```text
src/ragflow_lite/
├── api/             # FastAPI routes, schemas, deps
├── application/     # ingestion/query orchestration and services
├── config/          # env-backed runtime settings
├── domain/          # models, ports, domain errors
├── infrastructure/  # parser/chunker/embedder/index/provider/storage adapters
└── shared/          # cross-cutting logging/metrics/request helpers only
```

## 关键约定
- 不要在源码根重复具体符号清单、provider 迁移状态或阶段流水账；这些内容会漂移，应下沉到最近子目录或阶段文档。
- 不要跨层放置代码：route 不编排 parser/index/answer，domain 不依赖 FastAPI/SDK/文件系统，infrastructure 不反向决定业务流程。
- 不要把尚未进入默认主链路的 OCR/layout/table/DeepDoc、外部 rerank、dataset-aware query filter 或新检索主路径顺手塞入当前实现。
- 新增 abstraction 前先确认它表达稳定 port、消除真实重复或形成明确 extension point；不要为单一 provider 预建框架。
- 后端源码目录不放测试夹具、运行数据、临时脚本或 compose 产物。

# Source: src/ragflow_lite/CONTRACTS.md

Role: authoritative
Status: Active
Topic: src/ragflow_lite
SHA256: 69063e9539d623cc5bcad3ddbef3f22d66ffc898678b4db94bdc24beddac7a28

# Package-Level Active Contracts

This file owns active runtime contracts for `src/ragflow_lite`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Active Module Contracts

Child modules that own their own CONTRACTS.md:

- [api/CONTRACTS.md](api/CONTRACTS.md) -- HTTP surface, endpoints, schemas, status codes, observability
- [application/CONTRACTS.md](application/CONTRACTS.md) -- DiscoRAG budget, service boundary
- [infrastructure/CONTRACTS.md](infrastructure/CONTRACTS.md) -- adapter defaults, provider wiring, embedding/vector-index contracts

## Package Boundary Contract

Reviewed at: `2026-05-08T16:00:00+08:00`
Status: Active

Source of truth:
- Package name: `ragflow_lite` (internal Python package).
- Environment variable prefix: `RAGFLOW_LITE_*`.
- API prefix: `/api/v0` (configurable via `Settings.api_prefix`).

Mode routing and provider wiring:
- Default query path and dispatch semantics are owned by [application/CONTRACTS.md](application/CONTRACTS.md).
- Infinity hybrid chunk retrieval is an auxiliary retrieval capability, not an independently selectable HTTP strategy.
- Retrieval mode is fixed to hybrid; `RAGFLOW_LITE_RETRIEVAL_MODE` is rejected at startup if set.
- All runtime provider config comes from host environment (`DEEPSEEK_API_KEY`, `ARK_API_KEY`, `ARK_EMBEDDING_MODEL`); no secrets are read from or committed in the source tree.
- `Settings.require_runtime_provider_configs()` validates required env vars at startup and raises if missing.

Layering:
- HTTP surface is only in `api`.
- Business orchestration is only in `application`.
- Stable domain objects and ports are only in `domain`.
- External SDK, Infinity, filesystem, and provider details are only in `infrastructure`.
- `shared` is restricted to cross-cutting helpers (logging, request context, metrics); it must not hold business orchestration, provider calls, or routing control flow.

## Documentation Rule

All active runtime contracts in this subtree follow the governance standard:
source-backed, dated, owned, and verifiable. See [docs/agent-doc-governance.md](../../docs/agent-doc-governance.md)
for the full governance standard. AGENTS.md files in child directories must not duplicate
active semantics; they may only point to the nearest CONTRACTS.md.

# Source: src/ragflow_lite/api/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/api
SHA256: 898f8cf628de5bd9802347ada568d2d44f7a4e9b87a786604dda4d268fdc3168

# AGENTS.md

## Purpose
这个目录负责 FastAPI HTTP 接口层，只处理 HTTP 入口附近的职责。

## Active Contracts
Runtime contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/api --full
rtk cx overview src/ragflow_lite/api/routes --full
```

## 架构
```text
api/
├── routes/v0/    # HTTP endpoints (health, documents, queries, datasets)
├── schemas/      # request/response models
├── deps/         # dependency wiring, service lookup, route-layer adapters
└── observability.py  # route-level metrics helpers
```

## Avoid Here
- 不要在这里编排 parser、chunking、embedding、index、answer 主流程。
- 不要把领域对象和基础设施实现混放到 `api`。

# Source: src/ragflow_lite/api/CONTRACTS.md

Role: authoritative
Status: Active
Topic: src/ragflow_lite/api
SHA256: dc2087e7e4af1045371b0f084db6d0085d448107073ad7ee5eb238300d868c29

# API Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/api`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Scope

FastAPI HTTP interface layer: routes, schemas, dependency wiring, observability.

## HTTP Surface Contract

Reviewed at: `2026-05-08T21:00:00+08:00`
Status: Active
Owner: [routes/v0](routes/v0) router

Endpoints:
- `health` -- liveness check
- `POST /documents` -- ingestion, requires `Idempotency-Key` header; returns
  `202 Accepted` + `Location` header immediately, does not wait for indexing
- `GET /documents` -- document list, optional `dataset_id` query parameter filter
- `GET /documents/{id}` -- document detail; async ingestion polling entry,
  returns task status + optional catalog data
- `PATCH /documents/{id}/dataset` -- rebind/unbind dataset
- `POST /queries` -- query execution, mode routing via `mode` field
- `POST /datasets`, `GET /datasets`, `GET /datasets/{id}`, `DELETE /datasets/{id}`
  -- dataset CRUD
- No agent/session/message endpoints or agent UI shell are exposed.

Mode routing:
- `POST /queries` `mode` field: `"standard"` | `"discorag"`, default `"standard"`
- Retrieval strategy parameters are NOT exposed to the HTTP layer
- Response structure must stay stable

Idempotency-Key behavior:
- Missing `Idempotency-Key` on `POST /documents` returns `400`
- Duplicate key reuses existing async task identity instead of creating a new upload

Response schemas:
- `DocumentResponse`, `DocumentListResponse`, `DocumentIngestionResponse` (202),
  `DocumentDetailResponse`, `DocumentTaskResponse`
- Unknown `document_id` returns `404`

## Observability Contract

- Route layer owns request context / trace header binding and write-back
- HTTP error mapping logged as `request_error` (warning)
- Unhandled exceptions logged as `request_unhandled_exception` (error)
- Optional `/metrics` route registration
- HTTP metrics must use low-cardinality labels; `route` label must use template
  paths, never `document_id`, query text, filenames, or other high-cardinality values

## Verification

- Route wiring: [tests/unit/api](../../../tests/unit/api)
- Provider wiring: [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)

# Source: src/ragflow_lite/application/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/application
SHA256: 03bff5341949ccf0760e4d2714b572b290a02502aa52d50ebaa64f0d3e503e3f

# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

## 概述
这个目录是业务编排层，存放 ingestion 与 query 相关的 application 代码。

## 契约

Active contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/application --full
rtk cx overview src/ragflow_lite/application/services --full
rtk cx definition --name IngestionPipeline --from src/ragflow_lite/application/pipelines/ingestion.py --kind class
```

## 架构
```text
application/
├── pipelines/   # ingestion pipeline files
├── services/    # application service files
└── use_cases/   # reserved for a future stable use-case boundary
```

## 文件地图
- [pipelines/](pipelines/): ingestion 相关目录。
- [services/](services/): query、document、dataset、DiscoRAG 相关目录。
- [use_cases/](use_cases/): 预留目录；只有在形成稳定 use-case 边界后再启用。

## 边界提示
- 子目录导航文件只保留导航、命令、文件角色和错层提醒。

## 禁区
- 不要在 application 层直接 import FastAPI, Infinity SDK, provider SDK, or local JSON storage.
- 不要在这里放 parser selection、provider retry policy、table/index DDL 之类的 adapter 细节。
- 不要把 [use_cases/](use_cases/) 当成“暂时不知道放哪”的目录。

# Source: src/ragflow_lite/application/CONTRACTS.md

Role: authoritative
Status: Active
Topic: src/ragflow_lite/application
SHA256: b298930f0f28add2866d839b29015278ed2c45111a26957f3a8fe5db7c58f37c

# Application Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/application`.
[AGENTS.md](./AGENTS.md) files in this subtree should link here instead of duplicating these
contracts.

## DiscoRAG Structural Pipeline Contract

Reviewed at: `2026-05-09T21:00:00+08:00`
Status: Active
Owner: `DiscoRAGQueryService`, `LLMDiscoRAGAnswerBlueprintBuilder`

Source of truth:
- Inter-chunk discourse graph is LLM-backed (listwise inference), no deterministic fallback.
- `LLMInterChunkDiscourseGraphBuilder` replaces the former `DeterministicInterChunkDiscourseGraphBuilder`.
- Paper relation set: 21 labels including `unrelated`; 20 non-`unrelated` labels materialize as graph edges.
- `unrelated` is parsed and dropped, never materialized as `InterChunkDiscourseRelation`.
- Graph builder consumes `IntraChunkDiscoursePackage` via the `InterChunkDiscourseGraphBuilder` port (sync).
- Structurer model is configured independently from answer model via `DiscoRAGStructurerRuntimeConfig`.
- Blueprint planner is LLM-backed via `LLMDiscoRAGAnswerBlueprintBuilder`. `DiscoRAGAnswerBlueprintBuilder` is retained only as a test stub.

Invariant:
- Validation failure (unparseable JSON, all relations invalid) must raise `ProcessingError`, not silently return an empty or deterministic graph.
- Single invalid relations are dropped; per-category drop counts are observable in graph metadata.
- LLM model/provider metadata is observable in `graph.metadata["llm"]`.
- Blueprint maps 20 materialized labels to planning semantics: conflict (`contradicts`, `contrasts_with`, `replaces`), support (`supports`, `justifies`), background (`background_for`), elaboration (`elaborates`, `supplements`, `specifies`, `exemplifies`).
- Promotion triggers: `contradicts`, `contrasts_with`, `replaces`. `qualifies` is not in the paper set and no longer triggers promotion.
- RST signals (nuclearity, planning_role, rst_relation) influence blueprint constraints and lead selection when compatible with graph-derived ordering.
- Blueprint planner validation failure raises `ProcessingError`; no deterministic blueprint fallback in runtime.
- Answerer blueprint fallback (missing/invalid blueprint → score ordering) is a defensive last line with observable reason (`missing_blueprint`, `invalid_blueprint`). It is NOT a planner fallback; partially invalid blueprints (containing unknown chunk IDs) are treated as invalid.

Forbidden stale interpretations:
- Do not retain or reintroduce `DeterministicInterChunkDiscourseGraphBuilder` as runtime fallback.
- Do not reintroduce `DiscoRAGAnswerBlueprintBuilder` as runtime planner (test-only stub).
- Do not treat `qualifies` as a valid inter-chunk relation label for promotion or constraints.
- Do not treat `chunk_token_budget` or `context_token_budget` as required DiscoRAG behavior.
- Do not use [docs/superpowers/plans](../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py](../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py](../../../tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py)
- [tests/unit/application/test_discorag_answer_blueprint_builder.py](../../../tests/unit/application/test_discorag_answer_blueprint_builder.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../tests/unit/application/test_discorag_local_smoke.py)
- [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)

## DiscoRAG Budget Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `MiniGraphFirstRetriever`, `DiscoRAGQueryService`

Source of truth:
- Public final answer context budget: normalized `QueryRequest.top_n` after `top_k` alias handling.
- `MiniGraphFirstRetriever` derives the effective discourse-visible budget per request; the resulting `GraphFirstSourceSelection.discourse_selection_k` records that budget.

Invariant:
- `QueryRequest.top_n` is normalized before application services consume the request.
- `top_n` is the final answer context budget.
- Default `top_n=6` means final answer contexts are bounded to 6.
- When no explicit discourse budget override is provided, the effective `discourse_selection_k` defaults to `2 * top_n`.
- Default `top_n=6` means RST / inter-chunk graph visibility is 12 chunks.
- Supplemental discourse chunks participate in RST, inter-chunk graph, and blueprint construction.
- Supplemental discourse chunks do not append to final answer contexts.
- Promotion is bounded replacement, not append.

Forbidden stale interpretations:
- Do not treat `discourse_selection_k` as equal to `top_n`.
- Do not reintroduce extractor-local defaults such as `max_chunks=5`.
- Do not use historical [docs/superpowers/plans](../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/application/test_mini_graph_first_retriever.py](../../../tests/unit/application/test_mini_graph_first_retriever.py)
- [tests/unit/application/test_discorag_query_service.py](../../../tests/unit/application/test_discorag_query_service.py)
- stale scan for `max_chunks: int = 5` and `discourse_selection_n == top_n`

## Application Service Boundary Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `QueryModeRouter`, `QueryService`, `MiniGraphFirstRetriever`

Invariant:
- `QueryModeRouter` dispatches by query mode only; retrieval, evidence, and answer logic stay in downstream services.
- `QueryService` remains generic over `Retriever` + `Answerer`; do not couple it to graph-first or provider-specific internals.
- `GraphFirstSourceSelection` is an internal application contract; downstream collaborators may consume its metadata, but public API surfaces must not expose its full internal shape.

## DiscoRAG Degraded Fallback Contract

Reviewed at: `2026-05-11T12:00:00+08:00`
Status: Active
Owner: `DiscoRAGQueryService`

Source of truth:
- When RST extraction, inter-chunk graph construction, or blueprint planning exhausts structurer attempts, `DiscoRAGQueryService` catches `StructurerAttemptsExhaustedError` and degrades to MiniRAG direct answer.
- Fallback uses `retrieval_result.chunks` exactly as contexts, `mode="standard"`, `blueprint=None`.
- Result metadata includes `discorag_degraded == True` and a user-visible `discorag_error` block from `exc.safe_metadata()` with stage, error_type, failure_type, attempts, max_attempts, message, and `user_visible=True`.
- Fallback does not append supplemental discourse chunks and does not use a blueprint.
- Degraded fallback records success observability (`record_query_outcome("succeeded")`, `query_succeeded` log with `degraded=True`).

Invariant:
- Only `StructurerAttemptsExhaustedError` from structurer stages (rst_extraction, inter_chunk_graph, blueprint) triggers fallback.
- Plain `ProcessingError` from structurer collaborators propagates as hard failure.
- Runtime invariant failures after a valid blueprint (e.g. promotion runtime errors from `_contexts_with_bounded_promotion`, blueprint-context consistency errors from `_blueprint_for_contexts`) remain hard errors and propagate upward.
- Non-`ProcessingError` exceptions also propagate upward and do not trigger fallback.
- Fallback metadata is structured and user-visible without regex parsing.

Forbidden stale interpretations:
- Do not catch all `ProcessingError` for structurer fallback; only `StructurerAttemptsExhaustedError` qualifies.
- Do not treat post-blueprint runtime errors as recoverable; they remain hard errors.
- Do not use regex to extract fallback metadata from exception messages.

Verification:
- [tests/unit/application/test_discorag_query_service.py](../../../tests/unit/application/test_discorag_query_service.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../tests/unit/application/test_discorag_local_smoke.py)

## Retrieval Payload Contract

Reviewed at: 2026-07-18
Status: Active
Owner: `RetrievalPayloadService`

Source of truth: `RetrievalPayloadService` and `model_facing_retrieval.py`.

- `mcrag retrieve` is a generic retrieval-only CLI used by repository tooling; it is not an agent runtime or session API.
- Standard payloads use U-shaped score ordering. DiscoRAG payloads use score-descending contexts followed by the final blueprint.
- Model-facing payloads omit operational metadata, degraded state, graph internals, and debug traces.
- DiscoRAG retrieval without a blueprint raises `ProcessingError`; failures are explicit and never silently downgraded.

Verification:
- [tests/unit/application/test_retrieval_payload_service.py](../../../tests/unit/application/test_retrieval_payload_service.py)
- [tests/unit/cli/test_mcrag_cli.py](../../../tests/unit/cli/test_mcrag_cli.py)

## Contract E: MiniRAG Retrieval Rewrite Contract

Reviewed at: 2026-05-14
Status: Active
Owner: `MiniGraphFirstRetriever`

### Source of truth
`MiniGraphFirstRetriever.retrieve_context()`, `retrieval_rewrite.py` helpers, CoT grounding rewriters.

### Invariant
- Retrieval rewrite is an internal MiniRAG capability owned by `MiniGraphFirstRetriever`.
- `/queries` does not expose a rewrite strategy field; routing remains `standard` or `discorag`.
- The deterministic gate uses final answer candidates (`selected_for_answer`), not internal graph/path/discourse-only candidates. Threshold: `selected_answer_candidate_count < ceil(requested_top_n / 2)`.
- `cot_grounding` may produce only explicit `solution_steps`; the grounding layer extracts entities, relations, and answer-type keywords.
- CoT rewrite may run at most once. Post-rewrite assessment may mark retrieval degraded but must not trigger recursive rewrite.
- If CoT rewrite exhausts attempts, retrieval falls back to the cached initial candidate snapshot and must not rerun raw-query MiniRAG retrieval.
- `DiscoRAGQueryService` receives the resolved MiniRAG retrieval result and does not own rewrite decisions.
- Retrieval rewrite metadata remains a runtime side-channel for callers that need degraded retrieval state.
- `format_retrieval_rewrite_notice` in `infrastructure/answerers/_input_formatting.py` does not emit prompt text; answerer prompts do not include deterministic degraded-retrieval notices.

### Forbidden stale interpretations
- `cot_grounding` does not output entities, relations, or answer-type keywords directly.
- Post-rewrite assessment is observation-only; it never triggers a second rewrite.
- Rewrite failure and DiscoRAG structurer exhaustion are separate fallback paths.
- Do not treat hidden model chain-of-thought as a runtime contract.
- Do not infer retrieval quality warnings from generated answer text; use structured runtime/UI state instead.

### Verification
```
.venv/bin/python -m pytest tests/unit/application/test_retrieval_rewrite.py tests/unit/application/test_mini_graph_first_retriever.py tests/unit/application/test_discorag_query_service.py -q
```

# Source: src/ragflow_lite/application/pipelines/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/application/pipelines
SHA256: 47c58d7b430e788f02b4c059e578495d323a868bf83f96fd3033c297ca243b89

# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

Active contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件保留 pipeline 命令和导航；运行不变量见本地契约文件。

这个目录存放 ingestion pipeline 相关实现文件。

## 关键命令
```bash
rtk cx definition --name IngestionPipeline --from src/ragflow_lite/application/pipelines/ingestion.py --kind class
./.venv/bin/python -m pytest tests/unit/application/test_ingestion.py
```

## 文件地图
- [ingestion.py](ingestion.py): ingestion pipeline implementation.
- [__init__.py](__init__.py): pipeline exports.

## 边界提示
- 本文件只保留 pipeline 导航、本地命令、文件角色和错层提醒。

# Source: src/ragflow_lite/application/services/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/application/services
SHA256: 3efcae1e030968dad58c8896f7358a43140612bc7b732ba0f2a35671cc238161

# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

Active contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只保留服务导航、本地命令和所有权指引；运行不变量见本地契约文件。

这个目录存放 query、document、dataset 和 DiscoRAG 相关的 application service 文件。

## 关键命令
```bash
rtk cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --kind class
rtk cx references --name QueryService --file src/ragflow_lite/application/services/query_service.py --unique
```

## 文件地图
- [query_service.py](query_service.py): standard query service.
- [discorag_query_service.py](discorag_query_service.py): DiscoRAG query service.
- [query_mode_router.py](query_mode_router.py): query mode router.
- [mini_graph_first_retriever.py](mini_graph_first_retriever.py): graph-first retriever service.
- [evidence_package_builder.py](evidence_package_builder.py): evidence package helper.
- [discorag_answer_blueprint_builder.py](discorag_answer_blueprint_builder.py): DiscoRAG answer blueprint helper.
- [document_service.py](document_service.py): document service.
- [dataset_service.py](dataset_service.py): dataset service.
- [text_normalization.py](text_normalization.py): text normalization helpers.
- [_query_observability.py](_query_observability.py): query observability helpers.

## 边界提示
- 本文件只保留服务导航、本地命令、文件角色和错层提醒。

# Source: src/ragflow_lite/config/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/config
SHA256: 38041bf0edad078879c7ff8d980c25103f4a082544f4389ca370dbb326320532

# AGENTS.md

## Purpose
这个目录定义 runtime settings。它是环境变量、默认路径和 provider 配置校验的入口，不保存 secret。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx definition --name Settings --from src/ragflow_lite/config/settings.py --kind class
```

## 文件说明
- [settings.py](settings.py) -- env-backed runtime configuration entrypoint. Active behavior belongs in [../CONTRACTS.md](../CONTRACTS.md).

## Avoid Here
- 不要在这里编排业务流程或引入 provider SDK 依赖。

# Source: src/ragflow_lite/domain/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/domain
SHA256: 6cb21ca97658ee0206cf69536d9898751dbf7a4ecc27345893d936078fc3ca34

# AGENTS.md

## Purpose
这个目录负责稳定的业务边界，承载核心对象、抽象接口和领域错误。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/domain --full
rtk cx symbols --kind class --name '*' --file src/ragflow_lite/domain/models
rtk cx symbols --kind class --name '*' --file src/ragflow_lite/domain/ports
```

## 架构
```text
domain/
├── models/   # stable domain objects (Document, Chunk, retrieval/answer types, ingestion task, graph evidence, DiscoRAG types)
├── ports/    # stable abstract interfaces (parser, chunker, embedder, vector/retrieval, answerer, store, evidence, discourse)
└── errors/   # domain-level exceptions (DocumentNotFound, DatasetNotFound, IdempotencyKeyMissing, etc.)
```

## Avoid Here
- 不要依赖 FastAPI、数据库客户端、文件系统或外部 SDK 细节。
- 不要把具体实现塞进 `domain`。

# Source: src/ragflow_lite/infrastructure/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure
SHA256: c96b5ce9d748cfee0be98ad1e1db2f2dd58bc63937ecbb50788c7f9a894d5a96

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
├── chunkers/        # fixed/recursive chunking implementations
├── embedders/       # text embedding adapter
├── evidence/        # graph evidence extraction/store/index/discourse
├── ingestion/       # in-process task store/cache/runners
├── llms/            # chat completion client wrapper
├── loaders/         # currently empty compatibility package
├── nlp/             # RAGFlow tokenizer wrapper
├── parsers/         # txt/md/native-pdf parsers
├── retrievers/      # query grounding and auxiliary hybrid retrieval
├── storage/         # local document byte storage
└── vector_indexes/  # Infinity and local JSON vector indexes
```

## 关键约定
- Do not define business flow here. Infrastructure implements ports; it does not decide API shape, query mode routing, or ingestion lifecycle.
- Provider config and secrets must be injected from runtime settings/environment. Do not scatter secret reads across unrelated helpers.
- Do not log provider payloads, raw document/query text, filenames as metric labels, or full SDK responses.
- Keep provider calls, persistence, validation, tokenization, and retry policy in their nearest adapter package.
- Do not add OCR/layout/table/DeepDoc, rerank, extra embedding providers, or new primary retrieval paths unless the task explicitly opens that slice.
- If a subpackage has its own navigation file, follow that child file for local commands and file maps.

# Source: src/ragflow_lite/infrastructure/CONTRACTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure
SHA256: 3f010158a492f1bbe533f42892bc3274b700ca972e099226aa2e589117bba640

# Infrastructure Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/infrastructure`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Scope

Infrastructure adapters implementing `domain.ports`: providers, Infinity,
JSON/file storage, parser, chunker, retriever, and answerer.

Leaf adapter folders that do NOT get their own CONTRACTS.md (too small,
single-purpose):

- [answerers/](answerers/)
- [chunkers/](chunkers/)
- [embedders/](embedders/)
- [ingestion/](ingestion/)
- [llms/](llms/)
- [loaders/](loaders/)
- [nlp/](nlp/)
- [parsers/](parsers/)
- [retrievers/](retrievers/)
- [storage/](storage/)
- [vector_indexes/](vector_indexes/)

## Adapter Boundary Contract

Reviewed at: `2026-05-09T21:00:00+08:00`
Status: Active
Owner: `build_services` in [../api/deps/providers.py](../api/deps/providers.py)

Default vector index:
- `InfinityDenseVectorIndex` is the default runtime vector index.
- `LocalJsonVectorIndex` is fallback / test-double style storage; it is not the
  default runtime path.

Embedding dimension:
- Current embedding dimension contract is `2048`
  (`Settings.ark_embedding_dimensions`, wired through `ArkEmbeddingRuntimeConfig.dimensions`).
- `EmbeddingSignature` dicts (`{"provider": "ark", "model": ..., "dimensions": ...}`)
  are compatibility guards used at index write time, not documentation-only metadata.

Provider wiring:
- Embedding: `ArkMultimodalTextEmbedder` (Ark SDK).
- Non-embedding LLM: `DeepSeekChatCompletionsClient` via `DeepSeekChatAnswerer`,
  `DeepSeekChatEvidenceExtractor`, `DeepSeekChatIntraChunkDiscourseExtractor`,
  `DeepSeekChatQueryGrounder`.
- Structurer LLM: `LLMInterChunkDiscourseGraphBuilder` and `LLMDiscoRAGAnswerBlueprintBuilder`
  both use `DiscoRAGStructurerRuntimeConfig`, decoupled from the answer model.
- OpenAI Responses adapters (`OpenAIResponsesAnswerer`, `OpenAIResponsesEvidenceExtractor`,
  `OpenAIResponsesQueryGrounder`) remain legacy; they are not the default runtime path.
- Default model: `deepseek-v4-flash` with `reasoning_effort="high"`.

Logging boundary:
- Infrastructure may translate low-level exceptions and log bounded adapter outcomes.
- Application layer owns main workflow outcome logs.

## Chunk Auxiliary Text Fields

Reviewed at: `2026-05-11T16:00:00+08:00`
Status: Active
Owner: `InfinityDenseVectorIndex`, `chunk_text_fields.py`

Source of truth:
- Default chunk auxiliary `match_text` uses only tokenizer-derived fields:
  `filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks`.
- `filename` and `text` remain stored columns, but are not default
  `match_text` fallback fields.
- Chunk tables missing `filename_kwd`, `filename_tks`, `content_tks`, or
  `content_sm_tks` are incompatible and must fail during initialization
  (`_validate_chunk_auxiliary_text_columns` raises `RuntimeError`).

Invariant:
- `CHUNK_FIELD_MATCH_TEXT_FIELDS` must not include `filename` or `text`.
- Schema validation runs in `_ensure_tables` before any query path is active.

Forbidden stale interpretations:
- Do not add `filename^10,text` back to default chunk auxiliary `match_text`.
- Do not treat legacy chunk tables (lacking tokenizer-derived fields) as compatible.

Verification:
- [tests/unit/infrastructure/test_chunk_text_fields.py](../../../tests/unit/infrastructure/test_chunk_text_fields.py)
- [tests/unit/infrastructure/test_infinity_dense_index.py](../../../tests/unit/infrastructure/test_infinity_dense_index.py)
- [tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py](../../../tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py)

## Known Submodule Contracts

- [evidence/CONTRACTS.md](evidence/CONTRACTS.md) -- graph evidence extraction, candidate indexing, storage, canonicalization, intra-chunk discourse extraction, inter-chunk graph building, and blueprint planning.

## Verification

- Provider wiring: [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)
- Embedding signature guards: [tests/unit/infrastructure](../../../tests/unit/infrastructure) (check for embedder-related test files)
- Vector index: [tests/unit/infrastructure](../../../tests/unit/infrastructure) (check for index-related test files)

# Source: src/ragflow_lite/infrastructure/answerers/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/answerers
SHA256: ad5c72767045b108c0ad8f984894bfca6ccb83f734845216a5d726a7a0ea439f

# AGENTS.md

这个目录实现 answerer adapter 和回答 prompt 模板。它只把 `AnswerRequest` 转成 provider 调用并清洗回答。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- answerer adapters -- implement `Answerer` port
- prompt templates -- repo-tracked files (not inline source constants)
- `FALLBACK_ANSWER` -- shared no-context answer

## Avoid Here
- 不要添加 retrieval、rerank 或 evidence selection 逻辑。
- 不要 log provider payloads、raw contexts、full query text 或 generated answers。

# Source: src/ragflow_lite/infrastructure/chunkers/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/chunkers
SHA256: 3c353ae2144697d03224ca8ae39aa88315f1c8e7f745107b4519e8c1cf6b2200

# AGENTS.md

这个目录实现 document chunking。它 consumes normalized `ParsedDocument` and emits stable `Chunk` objects.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- `RecursiveCharacterChunker` -- preserves paragraph/CJK punctuation behavior
- `FixedWindowChunker` -- simple baseline
- Both propagate document metadata, excluding internal parser metadata keys

## Avoid Here
- 不要在 chunker 里做 parsing、normalization、embedding、indexing 或 citation formatting。

# Source: src/ragflow_lite/infrastructure/embedders/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/embedders
SHA256: 093f0f1e368a5c5f6e6d11a73498be6ac7e2aa3888aeb428cff98ee89757cb6b

# AGENTS.md

这个目录实现 text embedding adapter。它 converts chunks/query text into normalized dense vectors.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- embedding adapter -- implements chunk and query embedding
- `embed_query()` must receive the raw user query for dense retrieval

## Avoid Here
- 不要添加第二个 embedding provider 或 provider registry。
- 不要 log raw text sent to embedding API 或 returned vectors。
- Sparse/fulltext query rewriting 属于 retriever，不在这里。

# Source: src/ragflow_lite/infrastructure/evidence/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/evidence
SHA256: c8b2bcd73fc64a659fce51e76f2a0ba07ab2d3fc2a82da8a208a7a4ce9e094be

# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

Active contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件保留 evidence 命令和导航；运行不变量见本地契约文件。

这个目录存放 graph evidence 相关的 extractor、store、index 和辅助模块。

## 关键命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_graph_evidence_infinity_store.py tests/unit/infrastructure/test_infinity_graph_candidate_index.py
```

## 文件地图
- [deepseek_extractor.py](deepseek_extractor.py): graph evidence extractor.
- [openai_extractor.py](openai_extractor.py): graph evidence extractor.
- [deepseek_discourse_extractor.py](deepseek_discourse_extractor.py): discourse extractor.
- [graph_evidence_infinity_store.py](graph_evidence_infinity_store.py): Infinity-backed evidence store.
- [infinity_graph_candidate_index.py](infinity_graph_candidate_index.py): Infinity candidate index.
- [local_json_graph_evidence_index.py](local_json_graph_evidence_index.py): local JSON graph index.
- [local_json_store.py](local_json_store.py): local JSON evidence store.
- [graph_evidence_canonicalizer.py](graph_evidence_canonicalizer.py): graph evidence helper module.
- [graph_candidate_fields.py](graph_candidate_fields.py): candidate row field helpers.

## 边界提示
- 本文件只保留 evidence 目录导航、本地命令、文件角色和错层提醒。

# Source: src/ragflow_lite/infrastructure/evidence/CONTRACTS.md

Role: authoritative
Status: Active for graph evidence and Psi tree artifacts
Topic: src/ragflow_lite/infrastructure/evidence
SHA256: e66e43cbae12ed0edd0daade3ca7cd23bff85be2d553fc91bef03367a8c56fae

# Evidence Infrastructure Active Contracts

Reviewed at: `2026-05-08T19:54:53+08:00`
Status: Active

This file owns active runtime contracts for
`src/ragflow_lite/infrastructure/evidence`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Qualification

`evidence` is an independent infrastructure submodule, not an ordinary leaf
adapter folder.

It owns several implementation families:

- graph evidence extractors;
- graph evidence stores;
- graph candidate row builders and Infinity candidate index;
- local JSON graph evidence index;
- graph evidence canonicalization;
- intra-chunk discourse extraction for DiscoRAG;
- LLM inter-chunk discourse graph builder and output parser;
- LLM DiscoRAG blueprint planner and output parser.

The parent [../CONTRACTS.md](../CONTRACTS.md) owns adapter-wide defaults. This file
owns only evidence-submodule semantics.

## Graph Evidence Extraction Contract

Owners:
- `DeepSeekChatEvidenceExtractor`
- `OpenAIResponsesEvidenceExtractor`

Source of truth:
- Extractors consume source chunks and produce `GraphEvidenceBatch` objects.
- Empty chunk input is rejected before a model call.
- Extracted evidence must reference known source chunks.
- Relation endpoints must match extracted entity names. The DeepSeek-backed
  runtime path uses one bounded validation-repair turn for invalid graph evidence
  JSON and still fails if the regenerated output remains invalid.

Runtime boundary:
- DeepSeek-backed extraction is the current provider-wired path.
- OpenAI Responses extraction remains a legacy adapter path.

Verification:
- [tests/unit/infrastructure/test_deepseek_evidence_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_evidence_extractor.py)
- [tests/unit/infrastructure/test_openai_evidence_extractor.py](../../../../tests/unit/infrastructure/test_openai_evidence_extractor.py)
- provider wiring assertions in [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## Graph Candidate And Storage Contract

Owners:
- [graph_candidate_fields.py](graph_candidate_fields.py)
- `InfinityGraphCandidateIndex`
- `GraphEvidenceInfinityStore`
- `LocalJsonGraphEvidenceStore`
- `LocalJsonGraphEvidenceIndex`

Source of truth:
- Candidate rows include `candidate_id`, `canonical_id`, `document_id`,
  `candidate_kind`, source fields, vector fields, and JSON metadata.
- `canonical_id` comes from metadata when present and falls back to the source
  entity or relation id.
- Relationship candidate output must preserve relationship fields needed to
  rebuild `MiniRelationshipCandidate`.
- Entity candidate queries merge rows by `canonical_id` and keep the strongest
  score.
- Provider wiring uses `GraphEvidenceInfinityStore` to combine document evidence
  storage with the Infinity graph candidate index.
- Local JSON graph evidence storage/indexing is a local fallback and test path,
  not the default runtime candidate index.

Verification:
- [tests/unit/infrastructure/test_graph_candidate_fields.py](../../../../tests/unit/infrastructure/test_graph_candidate_fields.py)
- [tests/unit/infrastructure/test_infinity_graph_candidate_index.py](../../../../tests/unit/infrastructure/test_infinity_graph_candidate_index.py)
- [tests/unit/infrastructure/test_graph_evidence_infinity_store.py](../../../../tests/unit/infrastructure/test_graph_evidence_infinity_store.py)
- provider wiring assertions in [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## Canonicalization Contract

Owner: [graph_evidence_canonicalizer.py](graph_evidence_canonicalizer.py)

Source of truth:
- Cross-document canonicalization merges same-name entities into canonical
  entities.
- Directed relationships are merged by canonical endpoints.
- Canonical metadata records member ids and source document information.
- Relations with missing endpoints and entities with empty names are skipped.

Verification:
- [tests/unit/infrastructure/test_graph_evidence_canonicalizer.py](../../../../tests/unit/infrastructure/test_graph_evidence_canonicalizer.py)

## Intra-Chunk Discourse Extraction Contract

Owner: `DeepSeekChatIntraChunkDiscourseExtractor`

Source of truth:
- The extractor consumes `EvidencePackage.items`.
- `selected_for_discourse=True` marks retriever-selected discourse-visible
  evidence.

Invariant:
- Default extractor behavior has no local chunk cap.
- All retriever-selected discourse-visible chunks are eligible for RST
  extraction.
- Explicit caps are opt-in and must be visible in metadata.
- Metadata always includes `selected_chunk_ids` and `skipped_chunk_ids`.
- `skipped_chunk_ids` may be empty; explicit caps make non-empty skipped ids
  observable when chunks are excluded.

Forbidden stale interpretations:
- `max_chunks=5` is not a valid default.
- A local extractor cap is not the source of DiscoRAG discourse-window semantics.
- RST extraction must not silently shrink MiniRAG's discourse-visible window.

Verification:
- [tests/unit/infrastructure/test_deepseek_discourse_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_discourse_extractor.py)
- provider wiring assertions in [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## Structurer Retry Boundary

Reviewed at: `2026-05-11T12:00:00+08:00`
Status: Active
Owner: `LLMInterChunkDiscourseGraphBuilder`, `LLMDiscoRAGAnswerBlueprintBuilder`, `DeepSeekChatIntraChunkDiscourseExtractor`

Source of truth:
- DiscoRAG structurer calls use bounded attempts controlled by `DiscoRAGStructurerRuntimeConfig.timeout_seconds` (default 90) and `max_attempts` (default 2), wired through providers.
- Structurer calls pass `max_retries=0` to `DeepSeekChatCompletionsClient`, ensuring one structurer attempt equals one SDK request.
- Validation failures are repaired by asking the same structurer model to regenerate a complete JSON object using multi-turn context and a short validation feedback turn (`build_validation_repair_messages` in [structurer_retry.py](structurer_retry.py)).
- Timeout retries start a fresh original attempt (reset `repair_messages = None`).
- `StructurerAttemptState` tracks attempts, failure type, and failure summaries per stage.
- Exhausted attempts raise `StructurerAttemptsExhaustedError` (extends `ProcessingError`) with structured `stage`, `failure_type`, `attempts`, `max_attempts`, `message`, and `safe_metadata()`.
- Plain `ProcessingError` inside an attempt triggers repair when attempts remain.
- `is_timeout_error()` classifies exceptions by class name and message content.
- RST extraction rejects missing, duplicate, and unknown chunk structures; incomplete LLM output triggers validation repair.
- Parsers remain strict; runtime services do not patch invalid structure.

Invariant:
- One structurer attempt = one SDK request (no hidden transport retries).
- Exhausted attempts raise `StructurerAttemptsExhaustedError`; the caller decides fallback policy.
- Plain `ProcessingError` from parser validation triggers repair when attempts remain, exhaustion when budget is spent.
- Validation repair uses `complete_messages_json()` (multi-turn); fresh attempts use `complete_json()` (single-turn).
- Builders do not fall back to deterministic output on exhaustion.
- Provider wiring forwards `timeout_seconds` and `max_attempts` from `DiscoRAGStructurerRuntimeConfig` to all three structurer constructors.

Forbidden stale interpretations:
- Do not re-enable low-level DeepSeek retry for structurer calls.
- Do not catch `StructurerAttemptsExhaustedError` as a generic `ProcessingError` in application services; use the specific type.

Verification:
- [tests/unit/infrastructure/test_structurer_retry.py](../../../../tests/unit/infrastructure/test_structurer_retry.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_deepseek_discourse_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_discourse_extractor.py)
- [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## LLM Inter-Chunk Discourse Graph Contract

Reviewed at: `2026-05-09T20:00:00+08:00`
Status: Active
Owner: `LLMInterChunkDiscourseGraphBuilder`, `parse_llm_inter_chunk_graph`

Source of truth:
- `LLMInterChunkDiscourseGraphBuilder` implements the `InterChunkDiscourseGraphBuilder` port (sync).
- Uses structurer model via `DeepSeekChatCompletionsClient.complete_json()` for listwise graph inference.
- Prompt uses stable `CHUNK[N] id=<canonical_chunk_id>` identifiers; includes compact RST summaries when structures are available.
- `parse_llm_inter_chunk_graph()` validates raw LLM JSON against discourse-visible chunk IDs.
- Paper relation labels: 21 including `unrelated` (`PAPER_INTER_CHUNK_RELATION_TYPES`); 20 materialized (`MATERIALIZED_RELATION_TYPES`).

Invariant:
- No deterministic graph fallback. `DeterministicInterChunkDiscourseGraphBuilder` is not wired in runtime.
- `unrelated` relations are dropped, not materialized. Omitted pairs are treated as unrelated.
- Invalid relations (bad chunk IDs, self-references, unknown types) are individually dropped; drop counts per category are observable in metadata.
- Overall unusable output (parse failure or all relations invalid) raises `ProcessingError`.
- `DiscourseUnit` has functional RST projections: `nuclearity` (nucleus/satellite/joint), `rst_relation` (9 normalized labels), `planning_role` (7 compact roles: claim, evidence, definition, condition, qualification, contrast, procedure; plus `context` fallback for unmapped roles).

Forbidden stale interpretations:
- Do not reintroduce `DeterministicInterChunkDiscourseGraphBuilder` as runtime fallback.
- Do not treat `qualifies` as a valid inter-chunk relation label.

Verification:
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../../tests/unit/application/test_discorag_local_smoke.py)

## LLM DiscoRAG Blueprint Planner Contract

Reviewed at: `2026-05-09T21:00:00+08:00`
Status: Active
Owner: `LLMDiscoRAGAnswerBlueprintBuilder`, `parse_llm_discorag_blueprint`

Source of truth:
- `LLMDiscoRAGAnswerBlueprintBuilder` implements the `BlueprintBuilder` port (sync).
- Uses structurer model via `DeepSeekChatCompletionsClient.complete_json()` for discourse-aware blueprint planning.
- Builder consumes `IntraChunkDiscoursePackage` and `InterChunkDiscourseGraph`; derives answer/supplemental chunks and top_k budget from the evidence package.
- Prompt includes: query, top_k budget, answer candidates, supplemental discourse chunks with CHUNK[N] identifiers, RST unit details (id, role, nuclearity, rst_relation), intra-chunk RST relations, and inter-chunk graph relations with synthesized IDs.
- `parse_llm_discorag_blueprint()` validates raw LLM JSON: chunk IDs, relation IDs, RST unit IDs, budget, role/constraint vocabularies, promotion replacement semantics.

Invariant:
- No deterministic blueprint planner fallback. `DiscoRAGAnswerBlueprintBuilder` is retained only as a test stub; it is not wired in runtime providers.
- Blueprint validation failure (unparseable JSON, unknown chunk/relation/RST IDs, budget overflow, invalid promotion) raises `ProcessingError`.
- Promotions are strictly replacement (answer chunk out, supplemental chunk in); append is rejected.
- Supplemental chunks in `final_answer_chunk_ids` require a valid matching promotion.
- Role vocabulary: lead, support, background, caveat, comparison, definition, condition, context.
- Constraint vocabulary: caveat, condition, conflict, comparison, support, background, definition, ordering.
- Structurer model is configured via `DiscoRAGStructurerRuntimeConfig` (same config as graph builder, decoupled from answer model).

Forbidden stale interpretations:
- Do not reintroduce `DiscoRAGAnswerBlueprintBuilder` as runtime planner.
- Do not treat `ProcessingError` from planner as a signal to downgrade to basic RAG.
- Do not use [docs/superpowers/plans](../../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../../tests/unit/application/test_discorag_local_smoke.py)
- [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

# Source: src/ragflow_lite/infrastructure/ingestion/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/ingestion
SHA256: 72fad2e2836f713296fe48fd0790bc4e4d2b02cc385210da3b8129ac0fa855ec

# AGENTS.md

这个目录提供 ingestion task 的单进程内存实现。它是 runtime adapter，不是分布式队列。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- `InMemoryTaskStore` -- tracks task state and idempotency key ownership
- `InMemoryStageCache` -- stores parse/chunk stage artifacts only
- `InlineTaskRunner` -- synchronous, useful for tests
- `BackgroundTaskRunner` -- in-process async runner

## Avoid Here
- 这些实现是 thread-safe in-process helpers；不提供跨进程、持久化或分布式队列保证。
- 不要添加 database、broker 或 persistence 依赖。

# Source: src/ragflow_lite/infrastructure/llms/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/llms
SHA256: 1e96aa97897a0135bd1e780033b17c686e3bd8f9d25b0ff821a668a54bdf4220

# AGENTS.md

这个目录封装 non-embedding LLM client。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- Chat Completions client wrapper -- text and JSON completion helpers for answerers, query grounders, evidence extractors
- JSON mode adds required JSON instruction

## Avoid Here
- 不要在 callers 里重复低-level request construction。
- 不要 log prompts、user query text、document chunks、response payloads 或 API keys。

# Source: src/ragflow_lite/infrastructure/loaders/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/loaders
SHA256: 97e3daa16ea5c937692feb342ff61b827caea42809da04b4a82f1c17215f41c5

# AGENTS.md

这个目录目前只有 package marker。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 注意
- 不要把新 loader 放到这里，除非先确认它是稳定基础设施边界。
- 当前 upload/document byte handling 在 [../storage](../storage) 和 application ingestion。
- Parser dispatch 在 [../parsers](../parsers)。
- 不要把这里当作一次性 import scripts 或 fixture loaders 的堆放地。

# Source: src/ragflow_lite/infrastructure/nlp/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/nlp
SHA256: 2032f9e78377f6264dd19c393bc21037a8618373932237a7a2cd948d9a243acd

# AGENTS.md

这个目录封装 RAGFlow tokenizer backend。它 supports sparse/fulltext fields and query text analysis.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- Public helpers: `tokenize()` and `fine_grained_tokenize()`
- Backend loading errors raise `RAGFlowTokenizerUnavailableError`
- Tokenizer dependency is isolated here for testability

## Avoid Here
- 不要为 sparse fields 静默 fallback 到其他 tokenizer。
- Query normalization 规则属于 [../retrievers/query_analysis.py](../retrievers/query_analysis.py)，不在这里。
- 不要 log raw user queries 或 document text。

# Source: src/ragflow_lite/infrastructure/parsers/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/parsers
SHA256: 0db27f6f2e4a1a18456098e6117dcc98cf13b1a8badd962796fec58fcc366085

# AGENTS.md

这个目录实现 document parser。它 turns stored bytes into `ParsedDocument` and parser metadata.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- Supported baseline: `txt`, `md`, native-text `pdf`
- `CompositeParser` -- dispatches by file type, raises unsupported-type errors
- Markdown uses CommonMark/markdown-it path
- PDF uses digital-native text extraction with page metadata

## Avoid Here
- 不要添加 OCR、layout analysis、table extraction 或 DeepDoc-style parsing。
- Parser code 不应该 chunk、normalize for indexing、embed、index 或 format citations。
- 不要 log raw document contents。

# Source: src/ragflow_lite/infrastructure/retrievers/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/retrievers
SHA256: eaae781e609daeaae488260baeedb52d33f2b7db2d501045efed835630098547

# AGENTS.md

这个目录实现 query grounding, sparse query analysis and auxiliary hybrid retrieval.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_query_analysis.py tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

## 文件说明
- [query_analysis.py](query_analysis.py) -- NFKC/whitespace/lowercase/CJK-boundary/tech-token sparse query normalization
- query grounding adapters -- produce structured JSON from raw queries
- hybrid retriever -- auxiliary chunk retrieval for graph-first flow

## Avoid Here
- 不要添加 rerank、citation assembly 或新的 primary retrieval path。
- 不要把 hybrid/fusion tuning 暴露为 HTTP API 或 public service configuration。
- 不要 log raw query text 或 provider payloads。

# Source: src/ragflow_lite/infrastructure/storage/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/storage
SHA256: fdf8ad6f3ddc7bf14c00e2516864fd1edfff5f8a1954998ebd31134d36f90572

# AGENTS.md

这个目录实现 local document byte storage。它 stores uploaded source files, not indexes or parsed documents.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- `LocalDocumentStore` -- writes upload bytes under configured local directories, returns `DocumentAsset`
- Used by ingestion before parsing/indexing

## Avoid Here
- 不要在这里存储 embeddings、graph evidence、task state、dataset bindings 或 parsed text。
- 不要从 storage 推断 parser behavior。
- 不要 log raw file content 或写入 secrets/runtime config 到 upload directories。

# Source: src/ragflow_lite/infrastructure/vector_indexes/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/infrastructure/vector_indexes
SHA256: 5e95f034a0c1921e2ec2ae4227dd374e1b48c90baf845bda426c56f9ac94543e

# AGENTS.md

这个目录实现 vector index and catalog/dataset storage surfaces.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/infrastructure/vector_indexes --full
./.venv/bin/python -m pytest tests/unit/infrastructure/test_infinity_dense_index.py tests/unit/infrastructure/test_local_index.py
```

## 文件说明
- Infinity dense index -- document rows, chunk rows, dataset rows, document-dataset bindings
- Local JSON vector index -- fallback/test-double with atomic replace
- [chunk_text_fields.py](chunk_text_fields.py) -- localized sparse fields for hybrid chunk retrieval

## Avoid Here
- 不要引入 rerank、tag API、dataset-aware query filtering 或新的 primary retrieval path。
- 不要在 tests 里伪造跨 real index/query-builder 边界的 Infinity behavior。

# Source: src/ragflow_lite/shared/AGENTS.md

Role: authoritative
Status: active
Topic: src/ragflow_lite/shared
SHA256: 6e15f24e1b7b94c9c20f78a816c5f41eb1a8d3d557719f810c61f1a185831366

# AGENTS.md

## Purpose
这个目录只承接跨层复用、且不属于某一业务层的轻量基础能力。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/shared --full
```

## 文件说明
- [observability.py](observability.py) -- Prometheus metrics helpers, structured logging, request/trace context
  - Ingestion task metrics: `ingest_task_accepted_total`, `ingest_task_retry_total`, `ingest_stage_cache_total`, `ingest_task_duration_seconds`, `ingest_task_queue_delay_seconds`
- [__init__.py](__init__.py) -- package marker

## Avoid Here
- 不要把业务流程、路由编排、provider 调用或 repository 逻辑放进来。
- 不要在这里引入重量级 observability framework。

# Source: tests/AGENTS.md

Role: authoritative
Status: active
Topic: tests
SHA256: 0b1ef2c6fd66f1e16502e62f0f6b62bad04427006492f03a0c50d248e5fa055f

# AGENTS.md

Active test harness semantics: see [CONTRACTS.md](./CONTRACTS.md).

## Directory role

Tests, fixtures, and optional evaluation. Root AGENTS covers cross-tree navigation; subtree-specific rules live in the nearest [AGENTS.md](./AGENTS.md) or [CONTRACTS.md](./CONTRACTS.md).

## Quick commands
```bash
./.venv/bin/python -m pytest tests/unit/application tests/unit/infrastructure
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
```

## Architecture
```text
tests/
├── unit/          # module and boundary tests
├── integration/   # API/live main-link tests
├── evals/         # optional deepeval scripts and tests
├── fixtures/      # committed static txt/md/pdf/eval fixtures
└── eval_support.py
```

## File map notes

- [unit/test_eval_gating.py](unit/test_eval_gating.py) tests marker/option/env gating itself and must not require the `deepeval` package.
- [fixtures/documents](fixtures/documents) holds committed sample documents only; runtime outputs and local screenshots stay out of fixtures.
- Answerer prompt source of truth is the tracked templates under [src/ragflow_lite/infrastructure/answerers](../src/ragflow_lite/infrastructure/answerers), not inline constants.
- Manual smoke follows [docker/AGENTS.md](../docker/AGENTS.md); do not copy compose output into tests.

## Boundary rules

- Prefer failure-path and boundary tests over happy-path-only coverage, especially provider failure mapping, startup failure, dimension guards, dataset/catalog behavior, async ingestion state, citation/PDF page metadata, and observability.

# Source: tests/CONTRACTS.md

Role: authoritative
Status: active
Topic: tests
SHA256: 1e4c3c67065e1d744a24085313ceb08ac364333901d13f048042b6bff959637c

# tests/CONTRACTS.md

Source-backed test harness semantics. Navigation lives in [AGENTS.md](./AGENTS.md).

## CLI gates

| Option | Default | Effect |
|---|---|---|
| `--run-live-infinity` | `false` | Enables tests marked `@pytest.mark.live_infinity`. |
| `--run-deepeval` | `false` | Enables tests marked `@pytest.mark.deepeval`. Requires the `deepeval` package. |

`run_deepeval` implies `run_live_infinity`:
```python
run_live_infinity = config.getoption("--run-live-infinity") or run_deepeval
```
(conftest.py `pytest_collection_modifyitems`)

Without the relevant flag, marked tests are skipped automatically.

## Markers

Registered in `pytest_configure` (conftest.py):

- `live_infinity` — test connects to a real Infinity instance.
- `deepeval` — optional deepeval-based RAG evaluation.

## Placeholder environment defaults

conftest.py sets these placeholder values via `os.environ.setdefault`:

| Variable | Placeholder |
|---|---|
| `DEEPSEEK_API_KEY` | `test-deepseek-api-key` |
| `OPENAI_API_KEY` | `test-openai-api-key` |
| `ARK_API_KEY` | `test-ark-api-key` |
| `ARK_EMBEDDING_MODEL` | `ep-test-model` |

conftest.py clears `RAGFLOW_LITE_LOG_LEVEL`, `RAGFLOW_LITE_LOG_FORMAT`, `RAGFLOW_LITE_METRICS_ENABLED` from the environment.

## deepeval prompt variant

conftest.py `_set_deepeval_plain_prompt_variant` monkeypatches `RAGFLOW_LITE_OPENAI_RENDER_CITATIONS=false` for any item marked `deepeval`, keeping citation rendering disabled during metric evaluation.

## Fixture document path

`fixture_documents_dir` returns [tests/fixtures/documents](fixtures/documents).

## Scoped app settings and client fixtures

- `app_settings` (conftest.py): creates `Settings` with `tmp_path`, calls `assign_isolated_infinity_tables`, `register_infinity_table_cleanup`, `ensure_directories`.
- `app`: `create_app(app_settings)`, installs fake DeepSeek JSON clients.
- `client`: `TestClient(app)`, installs fake query support clients.

## Live Infinity cleanup helpers

Source: [infinity_test_support.py](infinity_test_support.py).

- `assign_isolated_infinity_tables(settings, tmp_path)`: uses `tmp_path` hash for table name suffix (6 tables per settings).
- `register_infinity_table_cleanup(settings)`: registers settings + table names for session-end cleanup.
- `drop_registered_infinity_tables()`: drops all registered tables (called in `pytest_sessionfinish` when `run_live_infinity` or `run_deepeval`).
- `clear_registered_infinity_tables()`: clears registrations without dropping (called in `pytest_sessionfinish` when no live gate).
- `_LIVE_TABLE_PREFIXES`: `("documents_", "chunks_", "graph_entities_", "graph_relationships_")`.

## Session finish behavior

`pytest_sessionfinish` (conftest.py):
- If `run_live_infinity` or `run_deepeval`: calls `drop_registered_infinity_tables()`.
- Otherwise: calls `clear_registered_infinity_tables()`.

## Placeholder detection

[eval_support.py](eval_support.py) `_PLACEHOLDER_ENV_VALUES = {"test-deepseek-api-key", "test-ark-api-key", "ep-test-model"}`. Used by `validate_deepeval_env` to reject placeholder credentials.

# Source: tests/evals/AGENTS.md

Role: authoritative
Status: active
Topic: tests/evals
SHA256: 7306c819ac43f7727a1099021fad589bcb58cbe59d360cbf8ab51d9397066318

# AGENTS.md

Eval contracts: see [CONTRACTS.md](./CONTRACTS.md).

## Directory role

Optional DeepEval workflow: goldens generation, prompt optimization, live RAG eval, and result summarization.

## Quick commands
```bash
./.venv-goldens/bin/python tests/evals/generate_goldens.py
./.venv/bin/python tests/evals/build_private_bootstrap_goldens.py --draft-goldens tests/fixtures/evals/private_bootstrap_goldens.draft.json
./.venv/bin/python tests/evals/optimize_prompt.py
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode discorag
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/discorag --query-mode discorag --export-all
```

If the DeepEval CLI does not pass custom pytest options through in a local version, use `RAGFLOW_LITE_EVAL_QUERY_MODE=standard` or `RAGFLOW_LITE_EVAL_QUERY_MODE=discorag` with the same `DEEPEVAL_RESULTS_FOLDER` value and omit `--query-mode` from the `deepeval test run` command.

## File map

- [test_rag_deepeval.py](test_rag_deepeval.py) — uploads fixtures, waits for terminal ingestion state, evaluates answers.
- [generate_goldens.py](generate_goldens.py) — synthetic golden generation (isolated `.venv-goldens`).
- [build_private_bootstrap_goldens.py](build_private_bootstrap_goldens.py) — builds the frozen private-bootstrap snapshot, compatibility packed fixture, and validates the draft golden artifact.
- [optimize_prompt.py](optimize_prompt.py) — prompt optimization against committed goldens (main `.venv`).
- [summarize_results.py](summarize_results.py) — post-processing of raw DeepEval exports.

## Boundary rules

- Keep goldens as generated artifacts; if quality is bad, regenerate rather than hand-patch rows.
- Raw DeepEval exports and local summaries are separate artifact flows.

# Source: tests/evals/CONTRACTS.md

Role: authoritative
Status: active
Topic: tests/evals
SHA256: 6da2768d6e1f383e75898243f66160a785b7d432e894233c83de1c6cb2be5179

# tests/evals/CONTRACTS.md

Eval-specific contracts. Navigation lives in [AGENTS.md](./AGENTS.md).

## Gate requirements

- deepeval tests require `@pytest.mark.deepeval` and explicit `--run-deepeval`.
- Live evals also require live Infinity (`--run-deepeval` implies `--run-live-infinity`; see [tests/CONTRACTS.md](../CONTRACTS.md)).

## Query mode

- DeepEval RAG evaluation runs target exactly one query mode: `standard` or `discorag`.
- Preferred selector: `--query-mode standard` or `--query-mode discorag`.
- Fallback selector when a DeepEval CLI version does not forward custom pytest options: `RAGFLOW_LITE_EVAL_QUERY_MODE`.
- If both are available, the explicit pytest option wins.
- Query mode is run-level metadata. It must not be added to `RagEvalCase` or the golden fixture schema.
- The eval request body sent to `/api/v0/queries` includes `mode`.

## Environment validation

`validate_deepeval_env` (eval_support.py) checks that these env vars are set and not placeholder values:

- `DEEPSEEK_API_KEY`
- `ARK_API_KEY`
- `ARK_EMBEDDING_MODEL`

Placeholder detection uses `_PLACEHOLDER_ENV_VALUES = {"test-deepseek-api-key", "test-ark-api-key", "ep-test-model"}`.

## Goldens and venvs

- Goldens generation: `.venv-goldens/bin/python tests/evals/generate_goldens.py`. Do not mix `.venv-goldens` dependencies into the main runtime `.venv`.
- Prompt optimization: main `.venv/bin/python tests/evals/optimize_prompt.py` (imports repo runtime code, consumes committed goldens).
- `_RAG_EVAL_GOLDENS_PATH = tests/fixtures/evals/synthetic_goldens.json` ([eval_support.py](../eval_support.py)).

## Private bootstrap goldens

- The private bootstrap dataset uses `tests/fixtures/documents/microrag-private-bootstrap-snapshot/` as its active eval corpus fixture.
- DeepEval live runs upload every file listed in the snapshot manifest as a separate runtime document before running the private bootstrap cases.
- `tests/fixtures/documents/microrag-private-bootstrap.md` is a generated compatibility/inspection packed fixture. It must not be treated as proof of cross-document retrieval.
- The packed fixture is generated from `tests/fixtures/documents/microrag-private-bootstrap-snapshot/`.
- `CONTRACTS.md` and `AGENTS.md` snapshot entries are authoritative sources.
- `docs/superpowers` snapshot entries are historical distractors and must not be the sole support for current-runtime claims.
- `tests/fixtures/evals/private_bootstrap_goldens.draft.json` is the review-stage artifact.
- `tests/fixtures/evals/synthetic_goldens.json` remains the active DeepEval artifact consumed by `tests/eval_support.py`.
- Private bootstrap golden metadata must include `corpus_fixture = "microrag-private-bootstrap-snapshot"` and `document_fixture = "microrag-private-bootstrap.md"`; `document_fixture` is compatibility metadata, not the active knowledge-base input.
- Run `tests/evals/build_private_bootstrap_goldens.py` before replacing the active artifact.

## Default deepeval model

Source: eval_support.py.

| Setting | Default | Env override |
|---|---|---|
| Model | `deepseek-v4-flash` | `DEEPEVAL_MODEL` |
| Base URL | `https://api.deepseek.com` | `DEEPEVAL_BASE_URL` |
| Reasoning effort | `high` | `DEEPEVAL_REASONING_EFFORT` |

## Summary artifacts

- `summarize_results.py --export-all --query-mode <mode>` writes mode-specific rolling latest files and timestamped history.
- Raw DeepEval exports should be separated by mode under `data/deepeval/raw/standard/` and `data/deepeval/raw/discorag/`.
- New rolling files use names such as `latest.standard.summary.json`, `latest.discorag.failed.json`, `latest.standard.metrics.json`, and `latest.discorag.compare.json`.
- Timestamped history files derive from `run_id = <timestamp>.<mode>` and do not append mode a second time.
- Mode-agnostic rolling files such as `latest.summary.json` are legacy inputs only and must not be written by the current export flow.
- Default compare discovers only previous summaries with the same `query_mode`.
- Explicit `--baseline` may compare across modes and reports both `query_mode` and `baseline_query_mode`; legacy baselines without mode metadata are reported as `baseline_query_mode: "unknown"`.
- Pytest eval runs do NOT automatically write summary artifacts. Run `summarize_results.py` after raw export.

# Source: tests/integration/AGENTS.md

Role: authoritative
Status: active
Topic: tests/integration
SHA256: 8991d516a73b75a6bd751a4525e432791c4a70639a95365624304137e6f9fe97

# AGENTS.md

Integration contracts: see [CONTRACTS.md](./CONTRACTS.md).

## Directory role

API and live-system boundary tests. Correct place for real Infinity-backed endpoint and core path checks.

## Quick commands
```bash
./.venv/bin/python -m pytest tests/integration --run-live-infinity
```

## Architecture
```text
tests/integration/
├── api/              # request/response contracts, async document lifecycle
└── infrastructure/   # real Infinity SDK/table/index/query behavior
```

## Boundary rules

- Keep integration tests narrow and purposeful; broad quality evaluation belongs in [tests/evals](../evals).
- These tests may require local services and exported runtime provider keys depending on the path under test.

# Source: tests/integration/CONTRACTS.md

Role: authoritative
Status: active
Topic: tests/integration
SHA256: 4d018dcc43582f7779c3e0c01ec8bea7623e4a40b61b59aa1d04681824474b06

# tests/integration/CONTRACTS.md

Integration test contracts. Navigation lives in [AGENTS.md](./AGENTS.md).

## Live Infinity marker

Tests requiring a real Infinity instance must use `@pytest.mark.live_infinity` and run only with `--run-live-infinity`. Without the flag, marked tests are skipped. See [tests/CONTRACTS.md](../CONTRACTS.md) for gate semantics.

## Endpoint lifecycle

- `POST /documents` returns `202 + Location + queued`; clients poll `GET /documents/{id}` to terminal state.
- Keep live table cleanup isolated to the test scope; do not mix local runtime data with committed fixtures.

## Table isolation

Integration tests use `assign_isolated_infinity_tables(settings, tmp_path)` to generate scoped table names (hash-based suffix from `tmp_path`). Tables are registered for cleanup and dropped at session end when `run_live_infinity` is active. See [tests/CONTRACTS.md](../CONTRACTS.md) for cleanup helpers.

## No fake Infinity

Do not replace live Infinity behavior with fakes in this tree. Tests that claim live storage/index/query behavior must use the real Infinity SDK.

# Source: tests/unit/CONTRACTS.md

Role: authoritative
Status: active
Topic: tests/unit
SHA256: a92134e8a1ee689be419c8118ed4b76c3970922ea66e23fd9fff50302a5f7945

# tests/unit/CONTRACTS.md

Unit-wide test contracts. Navigation lives in [../AGENTS.md](../AGENTS.md).

## Determinism

Unit tests must be deterministic by default. No live Infinity or live provider dependency unless explicitly marked and justified.

## Allowed fakes

- Fake Ark embedding and DeepSeek/OpenAI structured clients are allowed at non-Infinity boundaries (e.g. `_FakeDeepSeekJsonClient` in conftest.py).

## Prohibited fakes

Do not add fake/stub/mock Infinity clients, databases, tables, query builders, or monkeypatches of `infinity.connect`. Any test crossing real Infinity SDK/table/query behavior belongs in [tests/integration](../integration) with `@pytest.mark.live_infinity`.

## Fake scope

Fake or stub behavior should be local to the test file and must not redefine production contracts.

## Shared scope

application, domain, and infrastructure test subtrees share this contract. Boundary rules unique to each subtree are documented in their respective local navigation files.

# Source: tests/unit/application/AGENTS.md

Role: authoritative
Status: active
Topic: tests/unit/application
SHA256: 0e11dadb4745a6c6895081d06abee56cc0ee160c8b7b74984bdb053d0e0ec340

# AGENTS.md

Unit-wide rules: see [../CONTRACTS.md](../CONTRACTS.md).

## Directory role

Application orchestration contract tests. Uses fakes to verify collaboration order, state machines, error semantics, and metadata passing.

## Quick commands
```bash
./.venv/bin/python -m pytest tests/unit/application
./.venv/bin/python -m pytest tests/unit/application/test_ingestion.py tests/unit/application/test_mini_graph_first_retriever.py
```

## File map

- [test_ingestion.py](test_ingestion.py) — idempotency, retry, task transitions, stage cache, rollback, progress, observability.
- [test_mini_graph_first_retriever.py](test_mini_graph_first_retriever.py) — graph-first budget, scoring, fallback, source-selection.

## Boundary rules

- Mock collaborators, not the behavior being specified. If the assertion is about routing, idempotency, metadata, or state transitions, keep that semantic explicit.
- Do not introduce provider SDK, FastAPI route models, or Infinity SDK dependencies into unit application tests.
- Query service tests should keep `QueryService` generic and graph/fusion-agnostic.
- Router tests should assert dispatch and rejection only; retrieval or answer behavior belongs elsewhere.

# Source: tests/unit/domain/AGENTS.md

Role: authoritative
Status: active
Topic: tests/unit/domain
SHA256: f61ed181bb9c3317c1ef620a77e746741a061e34d1bd1af2c6a68a46c351b0d9

# AGENTS.md

Unit-wide rules: see [../CONTRACTS.md](../CONTRACTS.md).

## Directory role

Domain models and ports. Keep it small, pure, and implementation-free.

## Boundary rules

- Tests here protect field preservation, default factories, optional fields, and protocol boundaries.
- Domain tests should not need filesystem, FastAPI, Infinity, provider SDKs, or runtime environment variables.
- Do not encode infrastructure behavior in domain tests.
- Do not assert transient implementation repr/order details unless they are part of the domain contract.

# Source: tests/unit/infrastructure/AGENTS.md

Role: authoritative
Status: active
Topic: tests/unit/infrastructure
SHA256: 7c93201a705ef6bd1a020bbf7a05cd6abc6f40ada7b234786630a65af3a5976c

# AGENTS.md

Unit-wide rules: see [../CONTRACTS.md](../CONTRACTS.md).

## Directory role

Infrastructure adapters and low-level text/index/provider contracts. Heaviest unit subtree.

## Quick commands
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure
./.venv/bin/python -m pytest tests/unit/infrastructure/test_query_analysis.py tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

## File map

These tests protect adapter contracts: tokenizer behavior, sparse query normalization, chunking, parsing, provider wrappers, local JSON stores, Infinity config surfaces, and graph/vector candidate row builders.

## Boundary rules

- Preserve raw-query versus sparse-query assertions: dense embedding gets raw query, hybrid sparse branch gets analyzed query.
- Sparse-query tests must cover NFKC, whitespace, Latin lowercase, CJK boundaries, tech tokens, and symbol fallback.
- Parser tests must preserve native-PDF boundaries and failure behavior; do not normalize corrupted/encrypted PDFs into success.
- Provider adapter tests should validate strict JSON handling and no-call behavior for empty input.
- Local JSON index/store tests should preserve atomic replace, delete, and signature validation semantics.
