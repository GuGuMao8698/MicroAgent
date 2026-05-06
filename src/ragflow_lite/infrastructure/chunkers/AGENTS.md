# AGENTS.md

这个目录实现 document chunking。它 consumes normalized `ParsedDocument` and emits stable `Chunk` objects.

- `RecursiveCharacterChunker` is the preferred local splitter and preserves paragraph/CJK punctuation behavior.
- `FixedWindowChunker` remains a simple baseline.
- Both chunkers propagate document metadata while excluding internal parser metadata keys such as `page_spans` and `page_texts`.
- Page metadata is derived from normalized character spans and must survive cross-page chunks.
- Chunk ids must stay stable and deterministic for the same parsed document.
- Keep `chunk_size` / `chunk_overlap` validation strict; do not silently accept invalid overlap.
- Preserve `page_start`, `page_end`, and page range metadata when `page_spans` is available.
- Do not introduce external chunking dependencies unless explicitly approved.
- Do not perform parsing, normalization, embedding, indexing, or citation formatting in chunkers.
