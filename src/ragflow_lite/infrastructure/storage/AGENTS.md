# AGENTS.md

这个目录实现 local document byte storage. It stores uploaded source files, not indexes or parsed documents.

- `LocalDocumentStore` writes upload bytes under configured local directories and returns `DocumentAsset`.
- It is used by ingestion before parsing/indexing.
- Keep filename/suffix handling bounded to stored document assets; do not infer parser behavior here.
- Do not store embeddings, graph evidence, task state, dataset bindings, or parsed text in this package.
- Delete operations should clean the stored document asset without deciding index/catalog rollback policy.
- Do not log raw file content or write secrets/runtime config into upload directories.
