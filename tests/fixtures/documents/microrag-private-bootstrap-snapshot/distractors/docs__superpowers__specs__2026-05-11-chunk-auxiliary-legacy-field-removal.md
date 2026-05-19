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

