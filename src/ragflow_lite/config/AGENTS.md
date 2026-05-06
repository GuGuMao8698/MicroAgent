# AGENTS.md

这个目录定义 runtime settings。它是环境变量、默认路径和 provider 配置校验的入口，不保存 secret。

## 关键命令
```bash
rtk cx definition --name Settings --from src/ragflow_lite/config/settings.py --kind class
```

- `Settings.default()` chooses repo-local `data/` paths for local runtime state.
- `Settings.require_runtime_provider_configs()` validates provider environment required by app wiring.
- `Settings.ensure_directories()` creates local runtime directories.
- `create_app()` consumes settings and wires services; config should not import the app to avoid cycles.

## 关键约定
- Runtime provider values come from environment only. Do not add checked-in `.env` secret loading.
- App runtime requires `DEEPSEEK_API_KEY`, `ARK_API_KEY`, and `ARK_EMBEDDING_MODEL`.
- Keep internal package/env prefix as `ragflow_lite` / `RAGFLOW_LITE_*` despite external MicroRAG naming.
- `RAGFLOW_LITE_RETRIEVAL_MODE` is explicitly rejected; query mode is request-level routing, not global env config.
- Default paths should stay under repo-local `data/` unless the user explicitly changes runtime layout.
- Relative prompt paths resolve against the project root; do not make them depend on process cwd.
