# AGENTS.md

## Purpose
这个目录负责测试与夹具，保证当前 `txt` / `md` / `pdf` 主链路和分层边界可验证。

## Do Here
- 在 `unit` 放模块级和边界级测试。
- 在 `integration` 放 API 和主链路集成测试。
- 在 `fixtures/documents` 放当前阶段需要的 `txt`、`md`、`pdf` 样例文件。
- embedding 侧测试默认使用 fake Ark client，不访问真实 Ark 网络。
- 涉及回答阶段的测试默认使用 fake / stub client，不访问真实 OpenAI 网络。
- 测试环境只使用假的 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL` 或测试注入值，不引入真实密钥。
- 为已实现的基础 PDF 文本抽取写真实测试，覆盖解析成功、损坏输入和空文本场景。
- 允许为实际落地的 V1 能力补测试，优先覆盖 `Retriever` 边界、依赖装配、检索回退和基础元数据行为。

## Avoid Here
- 不要只测 happy path，优先覆盖失败路径、边界行为和分层职责，尤其是 provider 调用失败时的 API 返回行为。
- 不要把运行时生成文件混进 `fixtures`。
- 不要为尚未实现的 V2/V3 或空壳能力写占位测试。
