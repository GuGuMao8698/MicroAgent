# 测试门控与运行时契约

# 目标

为 `ragflow-lite` 的 `deepeval` 评测建立清晰的门控与运行时契约，保证质量评测只在显式请求时运行，同时不破坏默认 `pytest` 回归路径。该契约优先解决依赖导入时机、真实环境要求和 live Infinity 切换规则，而不是扩展出额外的运行模式或复杂配置矩阵。

# 参考项目

- `/home/xia/ragflow-lite/tests/conftest.py`：参考当前测试全局夹具、fake Infinity patch 与命令行 option 入口
- `/home/xia/ragflow-lite/tests/AGENTS.md`：参考测试目录对默认路径与 live 测试的现有约束
- `/home/xia/ragflow-lite/网页/deepeval/CLI Settings.md`：参考 `deepeval` CLI 与 dotenv / 本地配置边界
- `/home/xia/ragflow-lite/网页/deepeval/Environment Variables.md`：参考 `deepeval` 环境变量行为

# 范围与非目标

本文件只定义 `deepeval` 相关测试在仓库内如何被发现、何时被跳过、何时切换到真实 Infinity，以及运行时需要哪些真实环境变量。它不定义评测集内容、不定义 metric 选择、不定义 CI 工作流，也不承担生产环境配置说明。

本设计内只允许两类显式门控：`--run-live-infinity` 与 `--run-deepeval`。其中 `deepeval` 测试必须隐含依赖真实 Infinity，但真实 Infinity 测试不必都依赖 `deepeval`。默认 `pytest` 调用不应因为未安装 `deepeval` 或未提供真实密钥而在 import / collection 阶段直接失败。

# 核心契约

`deepeval` 依赖必须是“按需导入”的，而不是“全局导入后再跳过”。任何位于 `conftest.py` 顶层导入链上的 `deepeval` import 都会污染默认回归路径，因此 `deepeval` 相关类型、metric builder 或环境校验逻辑都必须被隔离到只在 `@pytest.mark.deepeval` 场景下才解析的代码路径中。最小要求是：未安装 `deepeval` 时，默认 `pytest` 仍然可以 collect 并运行非 `deepeval` 测试；显式开启 `--run-deepeval` 但缺少依赖时，失败信息必须指向缺失依赖本身，而不是暴露一串不清楚的导入栈。

`deepeval` 运行时必须要求真实 `OPENAI_API_KEY`、`ARK_API_KEY`、`ARK_EMBEDDING_MODEL`，且不得复用默认测试路径中注入的占位值。`deepeval` 测试一旦开启，Infinity 连接必须切换到真实实现，不允许继续落回 fake client；但这种切换只能影响被 `deepeval` 或 `live_infinity` marker 明确标注的测试，不能把整套测试环境一起带到 live 模式。

门控层只负责决定“这类测试是否能进入执行态”，不负责决定评测内容是否完整，也不负责生成 test cases。其职责边界是：保证默认路径稳、显式路径准、失败原因清楚。

# 验收口径

先失败的条件是：未安装 `deepeval` 时默认 `pytest` collection 直接报 `ModuleNotFoundError`；未开启 `--run-deepeval` 时 `deepeval` 测试没有被稳定跳过；开启 `deepeval` 后仍在用 fake Infinity；或缺少真实密钥时错误信息无法直接说明问题。通过后的可观察结果是：默认回归路径完全不受 `deepeval` 影响；显式开启时才解析 `deepeval` 依赖与环境；`live_infinity` 与 `deepeval` 的关系清晰且可验证；运行时错误边界可预测。

# 依赖与边界

本文件依赖 `pytest` marker / option 机制、现有 fake Infinity patch 逻辑以及仓库的测试环境约束；它向上服务 `deepeval` 详细设计中的评测集与执行入口，但不定义那些层的业务内容。即使补充 `deepeval` CLI 兼容入口，本文件也只要求同一套 marker、option 与真实运行时边界继续成立，不改写为另一套测试体系。
