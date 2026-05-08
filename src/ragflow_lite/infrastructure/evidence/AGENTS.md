# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

Active contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件保留 evidence 命令和导航；运行不变量见本地契约文件。

这个目录存放 graph evidence 相关的 extractor、store、index 和辅助模块。

## 关键命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_graph_evidence_infinity_store.py tests/unit/infrastructure/test_infinity_graph_candidate_index.py
```

## 文件地图
- `deepseek_extractor.py`: graph evidence extractor.
- `openai_extractor.py`: graph evidence extractor.
- `deepseek_discourse_extractor.py`: discourse extractor.
- `graph_evidence_infinity_store.py`: Infinity-backed evidence store.
- `infinity_graph_candidate_index.py`: Infinity candidate index.
- `local_json_graph_evidence_index.py`: local JSON graph index.
- `local_json_store.py`: local JSON evidence store.
- `graph_evidence_canonicalizer.py`: graph evidence helper module.
- `graph_candidate_fields.py`: candidate row field helpers.

## 边界提示
- Active runtime contracts for discourse extraction and evidence persistence live in [CONTRACTS.md](./CONTRACTS.md).
- 本文件只保留 evidence 目录导航、本地命令、文件角色和错层提醒。
