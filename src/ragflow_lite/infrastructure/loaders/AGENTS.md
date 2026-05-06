# AGENTS.md

这个目录目前只有 package marker。不要把新 loader 放到这里，除非先确认它是稳定基础设施边界。

- Current upload/document byte handling lives in `infrastructure/storage` and application ingestion.
- Parser dispatch lives in `infrastructure/parsers`.
- Do not use this empty package as a dumping ground for one-off import scripts or fixture loaders.
- If a future loader becomes real, add tests and update this file with its concrete contract.
