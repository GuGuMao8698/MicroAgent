# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

Active contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件保留 pipeline 命令和导航；运行不变量见本地契约文件。

这个目录存放 ingestion pipeline 相关实现文件。

## 关键命令
```bash
rtk cx definition --name IngestionPipeline --from src/ragflow_lite/application/pipelines/ingestion.py --kind class
./.venv/bin/python -m pytest tests/unit/application/test_ingestion.py
```

## 文件地图
- `ingestion.py`: ingestion pipeline implementation.
- `__init__.py`: pipeline exports.

## 边界提示
- Active runtime contracts for ingestion and task lifecycle live in [../CONTRACTS.md](../CONTRACTS.md).
- 本文件只保留 pipeline 导航、本地命令、文件角色和错层提醒。
