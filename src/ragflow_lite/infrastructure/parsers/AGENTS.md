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
