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
- 测试环境只使用假的 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL` 或测试注入值，不引入真实密钥。
- Infinity fake client 需要保留 hybrid 断言所需的最小查询语义：`match_dense`、多字段 `match_text(fields)`、`fusion("weighted_sum")`、`create_index` 与基本 output/filter/sort。
- hybrid retrieval 位置先验相关测试需覆盖：fusion 基础分相同时 `chunk_index` 更小者排前、fusion 分差距大于最大 boost(0.03) 时位置先验不反转排名、内部字段 `_chunk_index` 不泄漏到返回的 `RetrievedChunk.metadata`。
- 新增测试优先覆盖 provider 装配、文档 catalog 读路径、启动失败路径、维度守卫与元数据映射。
- 涉及 sparse-query 分析时，覆盖 NFKC、空白压缩、Latin 小写化、中英/数字边界分隔、技术 token 保留（`c++`/`c#`/`node.js`/`api_v1`/`gpt-4o`）与符号输入 fallback；retriever 单测断言 `embed_query()` 收到原始 query、`search_hybrid()` 收到分析后 sparse query。
- 涉及文档 catalog 时，覆盖 `list_documents` / `get_document`、`DocumentNotFoundError` 的 404 映射、`parser_strategy` 等 parser metadata 的持久化，以及 `DocumentService` / `AppServices` 的透传语义。
- 涉及 dataset baseline 时，覆盖：dataset CRUD（create/list/get/delete-empty）、重复名称 409、非空 delete 409、上传时绑定 dataset、文档重绑/解绑、`GET /documents?dataset_id=` 过滤、document list/detail/upload response 中的 `dataset_id`、binding 失败后的 rollback 清理，以及 `DatasetService` 名称校验。
- 涉及回答阶段时，覆盖 inline citation 编号契约、`<cite:n>` 到 `[n]` 的转换、空 contexts fallback 不变，以及 PDF prompt 中的 `page:` / `pages:` 行。
- 涉及 page-aware citation 与 parser strategy 时，覆盖：逐页 metadata 与空白页过滤、`page_spans` 对齐、chunker 单页/跨页/无页信息场景、PDF contexts 的 `page_start` / `page_end`、内部键不泄露，以及各 parser 写入对应 `parser_strategy`。
- 涉及结构化日志与错误处理时，覆盖：`caplog` 断言事件名和关键字段、rollback best-effort 不覆盖原始异常、`QueryService` unexpected exception 仍 wrap 为 `ProcessingError`、HTTP 错误响应 body 不变，以及 `create_app` 启动失败仍抛原异常并记日志。
- 涉及 observability 扩展时，覆盖：`X-Trace-Id` 透传/自动生成、request/trace context 绑定与清理、text/json formatter 输出、metrics toggle、关键日志带 `trace_id` / `request_id`、低基数 metrics label，以及日志中不泄露完整 query / 原始文档内容。
- 涉及异步 ingestion pipeline 时，覆盖：状态转换（`queued -> processing -> indexed / failed`）、幂等提交（相同 `Idempotency-Key` 返回已有 document / task identity）、自动单次 retry（第一次处理异常后重新入队，第二次失败才终态）、进度映射（step -> percent）、stage cache（parse/chunk 缓存命中与 miss、embed/index 不缓存）、observability（accepted/retry/cache/duration/queue_delay 指标）。
- 涉及集成测试迁移时，覆盖：`POST /documents` 必须携带 `Idempotency-Key` header、断言立即返回 `202` 与 `Location` header、再通过 `GET /documents/{id}` 轮询任务状态直至终态。
- 默认不要假设上传请求返回时文档已经 indexed；API / integration 测试应以轮询终态为主，只有明确验证同步兼容入口时才断言即时完成。
- 需要手工 smoke 时，以 `docker/AGENTS.md` 和归档中的本地运行说明为准；不要把 compose 运行产物或截图纳入仓库。
- 若补充 live integration 测试，只能做小范围、明确目的的验证，不把本地产物混入 `fixtures`。

## Avoid Here
- 不要只测 happy path，优先覆盖失败路径、边界行为和分层职责，尤其是 provider 调用失败时的 API 返回行为。
- 不要把运行时生成文件混进 `fixtures`。
- 不要为未实现能力或空壳接口写占位测试。
