# AGENTS.md

这个目录实现 graph evidence extraction, canonical graph view, candidate indexing, path expansion and intra-chunk discourse extraction.

## 关键命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_graph_evidence_infinity_store.py tests/unit/infrastructure/test_infinity_graph_candidate_index.py
```

- Extractors call LLMs and validate strict JSON structures; they should accept one document's chunks at a time.
- `GraphEvidenceInfinityStore` dual-writes JSON graph evidence and Infinity candidate rows.
- `InfinityGraphCandidateIndex` owns `graph_entities` / `graph_relationships` candidate tables and uses Infinity hybrid scoring; `query_relationships()` materializes full `MiniRelationshipCandidate` objects via `_relationship_candidate_from_row()` with `RELATIONSHIP_OUTPUT_FIELDS` and defensive JSON parsers, not empty shells.
- `LocalJsonGraphEvidenceIndex` is the query-time graph view and BFS path expander; cross-document canonicalization is query-time unless explicitly changed.

## 关键约定
- Keep provider calls, schema validation, persistence, candidate indexing and canonicalization separated.
- `GraphEvidenceInfinityStore` writes JSON first, then Infinity; on candidate-index failure it restores previous JSON state and deletes current candidate rows.
- Candidate rows consume existing `canonical_id`; do not move canonicalization into write-time without an explicit contract change.
- `selected_for_discourse` evidence must be consumed first by discourse extraction.
- Reject unknown chunk references and malformed provider JSON rather than repairing silently.
- `RELATIONSHIP_OUTPUT_FIELDS` must include all fields needed for endpoint pair edge voting (`source_entity_id`, `target_entity_id`, `source_entity_name`, `target_entity_name`, `description`, `keywords`, `weight`, `source_chunk_ids`); missing fields break `_edge_vote_count()` pair fallback.
- Do not log raw provider payloads, chunk text, graph extraction input, or full responses.
