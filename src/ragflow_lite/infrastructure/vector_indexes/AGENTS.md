# AGENTS.md

这个目录实现 vector index and catalog/dataset storage surfaces. Infinity is the default runtime index; local JSON is fallback/test-double style storage.

## 关键命令
```bash
rtk cx definition --name InfinityDenseVectorIndex --from src/ragflow_lite/infrastructure/vector_indexes/infinity_dense_index.py --kind class
./.venv/bin/python -m pytest tests/unit/infrastructure/test_infinity_dense_index.py tests/unit/infrastructure/test_local_index.py
```

- `InfinityDenseVectorIndex` owns Infinity document rows, chunk rows, dataset rows and document-dataset bindings.
- `LocalJsonVectorIndex` preserves local atomic replace and signature validation behavior.
- `chunk_text_fields.py` defines localized sparse fields for hybrid chunk retrieval.
- `get_chunks(chunk_ids)` is part of topology retrieval and must stay supported.

## 关键约定
- Embedding signature validation is a real compatibility gate; do not downgrade it to a warning.
- `search_hybrid()` uses raw query embedding for dense branch, sparse chunk text for fulltext branch, Infinity `weighted_sum`, then bounded position prior.
- Chunk hybrid fields are isolated from graph candidate fields; do not merge table schemas or match-field constants.
- Keep legacy `filename^10,text` match window only for old-row sparse recall compatibility.
- Do not introduce rerank, tag API, dataset-aware query filtering, or a new primary retrieval path here.
- Do not fake Infinity behavior in tests that cross real index/query-builder boundaries.
