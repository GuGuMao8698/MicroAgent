# AGENTS.md

这个目录实现 Ark text embedding adapter。它 converts chunks/query text into normalized dense vectors.

- `ArkMultimodalTextEmbedder` implements both chunk and query embedding.
- The current runtime embedding dimension contract is `2048`.
- Embedding signatures are consumed by vector indexes as compatibility gates.
- Keep vector normalization deterministic and strict; invalid provider vectors should fail loudly.
- `embed_query()` must receive the raw user query for dense retrieval.
- Sparse/fulltext query rewriting belongs to retriever query analysis, not the embedder.
- Do not add a second embedding provider or provider registry unless explicitly requested.
- Do not log raw text sent to the embedding API or returned vectors.
