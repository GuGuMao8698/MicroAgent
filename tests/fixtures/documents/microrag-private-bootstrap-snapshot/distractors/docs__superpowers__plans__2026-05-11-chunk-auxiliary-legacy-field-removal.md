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

