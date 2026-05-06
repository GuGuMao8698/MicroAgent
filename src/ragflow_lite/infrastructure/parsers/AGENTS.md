# AGENTS.md

这个目录实现 document parser。它 turns stored bytes into `ParsedDocument` and parser metadata.

- Supported parser baseline is `txt`, `md`, and native-text `pdf`.
- Markdown parsing uses the existing CommonMark/markdown-it path and preserves meaningful text.
- PDF parsing is digital-native text extraction and returns page text metadata where available.
- `CompositeParser` dispatches by file type and raises unsupported-type errors.
- Do not add OCR, layout analysis, table extraction, or DeepDoc-style parsing without an explicit task.
- Preserve `parser_strategy` metadata so ingestion/indexed documents can record how text was parsed.
- Empty/corrupted/encrypted PDF behavior is covered by tests; do not normalize all parser failures into empty text.
- Parser code should not chunk, normalize for indexing, embed, index, or format citations.
- Do not log raw document contents.
