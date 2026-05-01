# AGENTS.md

## Purpose
这个目录只放本地开发、observability 和手工 smoke 用的容器资产，不承接生产部署或发布。

## Do Here
- 本地主入口命令是 `docker compose -f docker/compose.local.yml --profile observability up --build`；这是手工 smoke 路径，不是 CI / release。
- `infinity` 是基础服务；`app`、`prometheus`、`loki`、`alloy`、`grafana` 通过 `observability` profile 拉起本地链路。
- `app` 容器默认把源码挂载到 `/workspace`，使用 `PYTHONPATH=/workspace/src`，并以 `uvicorn ragflow_lite.app:app --reload` 运行。
- `app` 容器依赖宿主 shell 已导出的 `DEEPSEEK_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL`；不要把这些值写进仓库内 `.env`。
- 端口与访问入口保持清晰：`Infinity` 对宿主暴露 `127.0.0.1:23817` / `127.0.0.1:23820`，`app` 为 `8000`，Prometheus 为 `9090`，Loki 为 `3100`，Grafana 为 `3000`。
- `docker/app/Dockerfile.dev` 只服务本地开发镜像，不要把它扩展成生产运行镜像。
- 保留最小 observability 资产，便于手工 smoke 和按 `trace_id` / metrics 验证。

## Avoid Here
- 不要把生产部署、CI/CD、发布脚本或 secret 文件放进来。
- 不要把与本地观测无关的业务配置复制一份到这里。
- 不要把 `.env`、真实密钥或运行时产物提交进仓库。
