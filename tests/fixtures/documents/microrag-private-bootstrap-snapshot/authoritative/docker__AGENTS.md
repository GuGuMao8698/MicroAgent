# AGENTS.md

## 概述
这个目录只放本地开发、observability 和手工 smoke 用的容器资产，不承接生产部署、CI 或 release。

## 本地入口
```bash
docker compose -f docker/compose.local.yml --profile observability up --build
```

## 详细约定
参见 [CONTRACTS.md](./CONTRACTS.md)。
