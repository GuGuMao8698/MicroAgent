# AGENTS.md

这个目录封装 RAGFlow tokenizer backend。它 supports sparse/fulltext fields and query text analysis.

- Public helpers are `tokenize()` and `fine_grained_tokenize()`.
- Backend loading errors must raise a clear `RAGFlowTokenizerUnavailableError`.
- Do not silently fall back to a different tokenizer for sparse fields; token shape affects Infinity recall.
- Keep tokenizer dependency isolated here so vector/evidence field builders can be tested with monkeypatched tokenizers.
- Query normalization rules belong in `infrastructure/retrievers/query_analysis.py`, not here.
- Do not log raw user queries or document text from tokenizer helpers.
