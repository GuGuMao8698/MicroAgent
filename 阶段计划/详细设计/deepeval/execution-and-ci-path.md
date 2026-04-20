# 执行入口与 CI 路径

# 目标

为 `ragflow-lite` 的 `deepeval` 评测提供一个明确、可复跑、可接入 `CI` 的执行入口，使评测结果不再停留在零散的本地 smoke 试跑，而能成为仓库中一条清楚的质量检查路径。主设计优先固定统一命令、本地执行约定和批量评测表达，再决定是否接入平台报表或远程工作流。

# 参考项目

- `/home/xia/ragflow-lite/网页/deepeval/RAG Evaluation Quickstart.md`：参考 `evaluate()` 的本地执行形态
- `/home/xia/ragflow-lite/网页/deepeval/RAG Evaluation.md`：参考 `assert_test`、`EvaluationDataset` 和 `deepeval test run` 的 CI 路径
- `/home/xia/ragflow-lite/网页/deepeval/CLI Settings.md`：参考 `deepeval` CLI 与本地缓存 / 报表能力
- `/home/xia/ragflow-lite/阶段计划/归档/本地运行与密钥流程.md`：参考本仓库已有本地运行与密钥管理边界

# 范围与非目标

本文件只定义 `deepeval` 在本仓库中的推荐执行入口、本地运行约定，以及接入 `CI` 时应遵循的最小路径。它不定义评测集内容、不定义门控逻辑实现细节、不定义具体阈值数值，也不把 `Confident AI` 报表、历史基线平台或 tracing 诊断能力强制纳入主执行入口。

主入口明确为仓库内的 `pytest` 标记入口：通过 `@pytest.mark.deepeval`、`--run-deepeval` 和现有 `conftest.py` 门控进入执行态，并复用同一套测试组织与 live Infinity 契约。`deepeval test run` 可以作为兼容 / 复用途径存在，但它不能演变成一套脱离仓库测试组织的平行体系；同时也不能长期停留在“只有单个测试函数里循环 `metric.measure()`”的临时状态。

# 核心契约

执行入口必须体现“批量评测”而不是“手工调试”。即使主入口继续沿用 `pytest`，内部表达也应升级为 `evaluate()`、`assert_test()`、`EvaluationDataset` 或等价批量入口来组织 test cases 与 metrics 的关系，而不是在单个测试里手写一个 `for metric in metrics: metric.measure(...)` 的调试循环。原因是 `deepeval` 官方把 standalone `measure()` 明确定位为调试或自建 pipeline 的单次执行，而 `evaluate()` / `assert_test()` / `deepeval test run` 才是缓存、报告和标准化运行形态的正式表达。

本地执行入口应保持“一个仓库命令 + 一组显式前置条件”的形状。前置条件至少包括：已安装 `deepeval`；已显式开启 `deepeval` 运行选项；真实 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL` 已准备好；本地 Infinity 可连通。命令本身应稳定、可复制，并且能直接表达“这是质量评测，不是默认回归测试”。若接入 `CI`，则应沿用同一套 test case / metric 组织方式和同一条 `pytest` 组织路径，避免本地一套、CI 另一套。

`deepeval test run` 若被引入，也应复用同一批 test cases、同一组 metrics 和同一套运行时前置条件，用作兼容 CLI 或补充报告能力，而不是重建数据集装配方式。`tracing` 的定位是诊断 / 观测增强层，可用于定位某次评测失败背后的链路细节，但不是当前主执行入口，也不应替代 `pytest` 标记路径。

CI 集成的要求是复用同一组织方式，而不是另起体系。只有当本地执行入口稳定、门控清楚、评测集具备代表性后，才应把它接成 CI 中的可选 job 或受控 job；平台报表、`CONFIDENT_API_KEY`、超参数对比和多轮仿真都属于边界外增强，不影响这里定义的执行入口成立。

# 验收口径

先失败的条件是：仓库没有统一命令入口；评测只能通过进入某个测试文件手工触发单个 `measure()` 循环；`deepeval test run` 与 `pytest` 入口各自维护一套数据组织；或本地与 CI 的组织方式完全脱节。通过后的可观察结果是：仓库中存在一条清楚的 `deepeval` 主执行路径；本地运行前置条件可理解；评测能以批量 test cases 形式运行；未来接入 `CI` 时只需复用同一入口与同一批测试组织，而不是重写整套流程。

# 依赖与边界

本文件依赖门控契约、评测集设计和本仓库现有本地密钥 / Infinity 运行方式；它向下不改写这些层的内容，只定义它们如何被组合成统一的执行面。若同时保留 `pytest` 与 `deepeval test run` 两条入口，也必须明确 `pytest` 标记路径为主入口，避免文档长期分叉。
