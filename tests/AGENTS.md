# AGENTS.md

## Purpose
这个目录负责测试与夹具，保证 V0 主链路和分层边界可验证。

## Do Here
- 在 `unit` 放模块级和边界级测试。
- 在 `integration` 放 API 和主链路集成测试。
- 在 `fixtures/documents` 放 `txt`、`md`、`pdf` 样例文件。

## Avoid Here
- 不要只测 happy path，优先覆盖失败路径、边界行为和分层职责。
- 不要把运行时生成文件混进 `fixtures`。
- 不要让测试目录结构偏离源码分层到难以对应。
