# AGENTS.md

## Purpose
这个目录只放本地开发用的容器资产，服务于可重复的运行、观测和手工 smoke。

## Do Here
- 放本地 `docker compose` 文件、容器配置和 provisioning 资产。
- 允许默认日常 `Infinity` 服务与 `observability` profile 下的附加服务统一收敛到单一 `docker/compose.local.yml`；后续新增本地依赖也沿这个入口扩展。
- 让配置默认对齐当前仓库运行方式：源码挂载、`app` 容器通过 `infinity:23817` 访问 `Infinity`、provider secret 通过宿主环境注入。
- 预置最小 datasource / dashboard / scrape / log collection 配置，便于按 `trace_id` 和 metrics 做手工验证。

## Avoid Here
- 不要把生产部署、CI/CD、发布脚本或 secret 文件放进来。
- 不要把与本地观测无关的业务配置复制一份到这里。
- 不要把 `.env`、真实密钥或运行时产物提交进仓库。
