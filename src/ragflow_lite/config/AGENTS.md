# AGENTS.md

## Purpose
这个目录定义 runtime settings。它是环境变量、默认路径和 provider 配置校验的入口，不保存 secret。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx definition --name Settings --from src/ragflow_lite/config/settings.py --kind class
```

## 文件说明
- [settings.py](settings.py) -- env-backed runtime configuration entrypoint. Active behavior belongs in [../CONTRACTS.md](../CONTRACTS.md).

## Avoid Here
- 不要在这里编排业务流程或引入 provider SDK 依赖。
