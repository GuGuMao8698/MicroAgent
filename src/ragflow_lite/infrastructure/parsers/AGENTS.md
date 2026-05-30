# AGENTS.md

这个目录实现 document parser。它 turns stored bytes into `ParsedDocument` and parser metadata.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- Supported baseline: `txt`, `md`, `pdf`
- `CompositeParser` -- dispatches by file type, raises unsupported-type errors
- Markdown uses CommonMark/markdown-it path
- PDF uses Docling-backed `DoclingPdfParser` (see [../CONTRACTS.md](../CONTRACTS.md) for academic PDF contract)
- `BasicPdfParser` is retained for reference but not registered in `CompositeParser`

## Avoid Here
- Parser code 不应该 chunk、normalize for indexing、embed、index 或 format citations。
- 不要 log raw document contents。
