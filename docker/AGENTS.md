# AGENTS.md

## 概述
这个目录只放本地开发、observability 和手工 smoke 用的容器资产，不承接生产部署、CI 或 release。

## 本地入口
```bash
docker compose -f docker/compose.local.yml --profile observability up --build
```

- `infinity` 是基础服务；`app`、Prometheus、Loki、Alloy、Grafana 通过 `observability` profile 拉起本地链路。
- `app` 容器把源码挂载到 `/workspace`，设置 `PYTHONPATH=/workspace/src`，并以 `uvicorn ragflow_lite.app:app --reload` 运行。
- `app` 容器依赖宿主 shell 已导出的 `DEEPSEEK_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL`。
- 端口保持本地 smoke 语义：Infinity `127.0.0.1:23817` / `127.0.0.1:23820`，app `8000`，Prometheus `9090`，Loki `3100`，Grafana `3000`。

## 关键约定
- `docker/app/Dockerfile.dev` 是本地开发镜像，不要扩展成生产镜像。
- 不要提交 `.env`、真实密钥、compose 运行产物、截图或本地数据卷内容。
- 不要把生产部署、CI/CD、发布脚本或与本地观测无关的业务配置复制到这里。
- 观测资产只保留能支持手工 smoke、`trace_id` 排查和 metrics 验证的最小配置。
