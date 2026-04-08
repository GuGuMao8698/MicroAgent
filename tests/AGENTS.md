# AGENTS.md

## Purpose
这个目录负责测试与夹具，保证当前 `txt` / `md` / `pdf` 主链路和分层边界可验证。

## Do Here
- 在 `unit` 放模块级和边界级测试。
- 在 `integration` 放 API 和主链路集成测试。
- 在 `fixtures/documents` 放当前主链路需要的 `txt`、`md`、`pdf` 样例文件。
- embedding 侧测试默认使用 fake Ark client，不访问真实 Ark 网络。
- 涉及回答阶段的测试默认使用 fake / stub client，不访问真实 OpenAI 网络。
- Infinity 相关测试默认使用 fake client（在 `conftest.py` 中 patch `infinity.connect`），不访问真实 Infinity 网络。
- Infinity fake client 需要覆盖 `match_dense`、`match_text`、`fusion("weighted_sum")`、`create_index`、`output/filter/sort`（纯表扫描）与 `_score` / `_distance` 这类最小查询语义；其中 `match_text(fields)` 要支持多字段与 `^boost`，`FakeInfinityTable` 需要保留 hybrid 断言所需的观察点。
- 测试环境只使用假的 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL` 或测试注入值，不引入真实密钥。
- 为已实现的基础 PDF 文本抽取写真实测试，覆盖解析成功、损坏输入和空文本场景。
- 新增测试优先覆盖 Infinity index 适配层、provider 装配、启动失败路径、维度守卫、元数据映射、文档列表/详情读取。
- 涉及 hybrid 检索时，优先覆盖 candidate window、字段加权召回、overlap 去重、排序，以及 index 层 pure dense/fulltext 诊断回归。
- 涉及 sparse-query 分析时，覆盖 NFKC、空白压缩、Latin 小写化、中英/数字边界分隔、技术 token 保留（`c++`/`c#`/`node.js`/`api_v1`/`gpt-4o`）与符号输入 fallback；retriever 单测断言 `embed_query()` 收到原始 query、`search_hybrid()` 收到分析后 sparse query。
- 涉及文档 catalog 时，覆盖 `list_documents` 倒序、`get_document` 精确命中、`DocumentNotFoundError` 404 映射、parser metadata 写入 `parser_metadata_json`、`DocumentService` 透传语义、`AppServices` 装配。
- 涉及回答阶段时，覆盖 inline citation 指令、按 score 降序的 contexts 返回顺序与编号对齐、`<cite:n>` token 到用户可见 `[n]` 的转换、越界 token 移除、裸方括号数字原样保留，以及空 contexts fallback 不变。
- 若补充 live integration 测试，只能做小范围、明确目的的验证，不把本地产物混入 `fixtures`。

## Avoid Here
- 不要只测 happy path，优先覆盖失败路径、边界行为和分层职责，尤其是 provider 调用失败时的 API 返回行为。
- 不要把运行时生成文件混进 `fixtures`。
- 不要为未实现能力或空壳接口写占位测试。
