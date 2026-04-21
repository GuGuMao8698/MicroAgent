# AGENTS.md

## Purpose
这个目录负责测试与夹具，覆盖主链路、分层边界和关键契约回归。

## Do Here
- 在 `unit` 放模块级和边界级测试。
- `unit/test_eval_gating.py` 测试门控基础设施本身（marker、option、env 校验），不依赖 `deepeval` 包。
- 在 `integration` 放 API 和主链路集成测试。
- 在 `evals` 放可选的 `deepeval` 评估测试；`eval_support.py` 提供共享基础设施，本地结果读取入口为 `evals/summarize_results.py`。
- 在 `fixtures/documents` 放 `txt`、`md`、`pdf` 样例，以及边界/异常样例。
- 默认测试路径使用 fake Infinity、fake Ark、fake/stub OpenAI，保持快速和稳定。
- 真实 Infinity 回归测试使用 `@pytest.mark.live_infinity`，并只在显式传入 `--run-live-infinity` 时运行。
- `deepeval` 测试使用 `@pytest.mark.deepeval`，并要求真实 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL`；需要官方结果导出时，运行 `DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval`。一键导出全部本地分析产物时，运行 `./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw --export-all`：它会写入 `latest.*` 滚动视图和按时间戳保留的 `summary/failed/metrics` 历史文件；若已有上一轮时间戳 summary，还会自动生成 compare。若要显式指定基线，再追加 `--baseline <raw-export-or-summary>`。
- Infinity fake client 需要保留当前断言所需的最小查询语义：`match_dense`、`match_text(fields)`、`fusion("weighted_sum")`、`create_index`、`list_indexes` 和基本 `output` / `filter` / `sort`。
- 新增测试优先守住这些高风险点：真实 Infinity 集成、provider / answerer 装配与重试、启动失败路径、维度守卫、文档 catalog 与 dataset 读写契约、异步 ingestion 状态机、inline citation 与 PDF 页信息、结构化日志与 observability。
- 涉及 sparse-query 分析时，覆盖 NFKC、空白压缩、Latin 小写化、中英/数字边界分隔、技术 token 保留（`c++`/`c#`/`node.js`/`api_v1`/`gpt-4o`）与符号输入 fallback；retriever 单测断言 `embed_query()` 收到原始 query、`search_hybrid()` 收到分析后 sparse query。
- 涉及异步上传的 API / integration 测试时，以 `POST /documents` 返回 `202 + Location + queued` 为起点，并通过 `GET /documents/{id}` 轮询至终态；同时保留 `Idempotency-Key`、自动单次 retry 和相关 metrics 断言。
- 需要手工 smoke 时，以 `docker/AGENTS.md` 和归档中的本地运行说明为准；不要把 compose 运行产物或截图纳入仓库。
- 若补充 live integration 测试，只做小范围、明确目的的验证，不把本地产物混入 `fixtures`。

## Avoid Here
- 不要只测 happy path，优先覆盖失败路径、边界行为和分层职责，尤其是 provider 调用失败时的 API 返回行为。
- 不要把运行时生成文件混进 `fixtures`。
- 不要为未实现能力或空壳接口写占位测试。
