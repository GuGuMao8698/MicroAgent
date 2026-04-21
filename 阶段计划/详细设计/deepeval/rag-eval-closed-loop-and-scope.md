# RAG 评测闭环与范围

# 目标

为 `ragflow-lite` 定义一条完整且收敛的 `deepeval` RAG 评测闭环，使仓库在保留现有 deterministic 单元 / 集成回归测试的前提下，新增一层面向检索质量与回答质量的可重复评测能力。该闭环以仓库已存在的单轮 RAG 主链路为中心，回答“评测覆盖哪些质量层、主路径怎样闭环、与现有测试怎样分层”三个问题，而不把多轮会话、平台报表或复杂调优实验并入主设计。

# 参考项目

- `/home/xia/ragflow-lite/网页/deepeval/RAG Evaluation Quickstart.md`：参考 `deepeval` 单轮 RAG 评测的最小闭环
- `/home/xia/ragflow-lite/网页/deepeval/RAG Evaluation.md`：参考 `deepeval` 对端到端评测、CI 路径和多轮能力的边界说明
- `/home/xia/ragflow-lite/tests/integration/api/test_v0_endpoints.py`：参考现有 upload -> poll -> query 主链路测试形状
- `/home/xia/ragflow-lite/tests/integration/api/test_live_infinity_endpoints.py`：参考真实 Infinity 集成测试边界

# 范围与非目标

本文件只定义 `deepeval` 在本仓库中的职责边界、质量分层以及与现有测试分层的关系。它不定义每个 metric 的具体阈值、不定义评测集样本本身的内容、不定义 CI 细节实现，也不把多轮对话评测、tracing 诊断链路或 synthetic data generation 纳入主执行范围。

主范围是单轮 `RAG` 问答，且以真实 API 主链路为载体：`POST /api/v0/documents`、轮询 `GET /api/v0/documents/{id}` 直到终态、再通过 `POST /api/v0/queries` 获取答案与 `contexts`。在这条链路上，质量判断按三层组织：

- `retriever` 质量：围绕返回 `contexts` 判断检索相关性、排序质量和覆盖边界。
- `generator` 质量：围绕最终答案判断答非所问、脱离上下文和忠实性问题。
- `E2E` 质量：把一次真实 upload -> query 闭环作为评测载体，确保检索与回答信号来自同一条仓库主链路。

`deepeval` 只在这条链路之上补充质量判断，不替代现有 API 契约测试、dataset 行为测试、异常路径测试或 fake-client 单测。

# 核心契约

`deepeval` 在 `ragflow-lite` 中承担的是“质量评测层”，而不是“主回归层”。默认 `pytest` 路径仍然依赖 fake Infinity、fake Ark 和 fake / stub OpenAI 保持快速、稳定和可离线运行；`deepeval` 评测只在显式开启时运行，并且只消费真实运行时环境与真实 Infinity 主链路。若没有显式开启或缺少 `deepeval` 依赖，默认测试路径必须仍可正常 collect、执行和通过。

完整闭环的成立条件不是“某个 metric 能跑出 `0..1` 的分数”，而是：仓库存在一组稳定的评测样本；这些样本通过统一入口构造成 `deepeval` 可执行的 test cases；`retriever`、`generator` 和 `E2E` 三层质量信号都能从同一批样本中读出；并且执行结果可以作为一次可复跑的质量快照。该快照是质量信号，不直接替代现有 deterministic 回归测试的 pass / fail 语义。

本设计的主执行范围只覆盖单轮问答。若需要多轮会话评测，应作为独立设计扩展，不反向污染当前单轮闭环的数据结构、命令入口或默认测试约束；`tracing` 只作为诊断 / 观测增强层，`synthetic` 只作为数据扩展能力，也都不进入这里定义的主执行路径。

# 验收口径

先失败的条件是：`deepeval` 与默认 `pytest` 路径纠缠，导致未安装 `deepeval` 时测试收集失败；评测只验证“分数存在”而不形成完整质量闭环；或评测样本无法代表当前仓库已实现的主链路能力。通过后的可观察结果是：默认回归测试与质量评测明确分层；显式开启后可以跑通单轮 RAG 评测；评测闭环能稳定复跑；并且 `retriever` / `generator` / `E2E` 三层职责在文档和执行面上都清楚可辨。

# 依赖与边界

本文件依赖现有 upload / query API 主链路、真实 Infinity 集成能力以及 `deepeval` 的单轮 RAG metrics；它向下约束门控方式、评测集形状和执行入口，但不直接决定样本内容或阈值细节。`LangSmith`、多轮会话、平台报表、自动调参或超参数对比都属于边界外增强项；`tracing` 与 `synthetic data generation` 也只作为补充能力存在，不改写本文件定义的主闭环。
