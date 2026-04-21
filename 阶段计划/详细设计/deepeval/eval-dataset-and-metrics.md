# 评测集与指标

# 目标

为 `ragflow-lite` 定义一组收敛但有代表性的 `deepeval` 评测集形状与指标使用方式，使评测既能覆盖当前仓库已经落地的 RAG 主链路能力，又不会把样本设计膨胀成难以维护的 benchmark 工程。主路径优先覆盖单轮问答、真实检索上下文和可维护的种子样本，而不是追求大规模数据集或把自动生成样本并入默认执行链路。

# 参考项目

- `/home/xia/ragflow-lite/网页/deepeval/RAG Evaluation Quickstart.md`：参考 `LLMTestCase`、`retrieval_context` 和端到端 RAG metrics 的最小要求
- `/home/xia/ragflow-lite/网页/deepeval/Using the RAG Triad for RAG evaluation.md`：参考默认核心指标组应如何覆盖检索与回答质量
- `/home/xia/ragflow-lite/网页/deepeval/Introduction to LLM Metrics.md`：参考 referenceless 与 reference-based 指标的区分方式
- `/home/xia/ragflow-lite/网页/deepeval/Generate Synthetic Test Data for LLM Applications.md`：参考 synthetic data generation 的能力边界
- `/home/xia/ragflow-lite/tests/fixtures/documents`：参考现有测试夹具文档类型
- `/home/xia/ragflow-lite/tests/integration/api/test_v0_endpoints.py`：参考现有仓库已验证的问答场景

# 范围与非目标

本文件只定义 `deepeval` 评测样本应有哪些字段、主路径应覆盖哪些场景，以及各类 RAG metrics 在本仓库中的使用边界。它不定义具体阈值数值、不定义 CI 规则、不定义多轮对话 test case，也不要求把离线 `Golden` 生成器、prompt optimizer、自动样本扩写或平台侧数据集同步并入 `pytest --run-deepeval` 主执行链路。

主评测集只覆盖单轮 `LLMTestCase`。每个 case 至少包含：样本名称、待上传的 fixture 文档、查询文本，以及与样本目标相匹配的质量判断字段。主路径评测数据应来自仓库已有 fixture 与现有已验证主链路，不应凭空扩写一套和仓库实际能力脱节的“理想问答库”。

# 核心契约

`ragflow-lite` 的 `deepeval` 评测集必须同时覆盖检索侧和回答侧，而不是只跑一个回答质量分。默认核心指标组写成 `RAG triad`：`AnswerRelevancy`、`Faithfulness`、`ContextualRelevancy`。其中 `AnswerRelevancy` 用来判断回答是否对题，`Faithfulness` 用来判断回答是否忠实于检索上下文，`ContextualRelevancy` 用来判断返回 `contexts` 是否与问题相关；这三项共同构成默认执行面中的回答质量与检索质量基线。

`ContextualPrecision` 与 `ContextualRecall` 仍属于本仓库可用的检索指标，但它们是 reference-based 指标，不属于默认三件套。只有当某类样本的 `expected_output` / ground truth 可维护、且确实需要判断排序质量或覆盖度时，才启用这两项指标。它们的职责是增强对检索排序与召回完整性的判断，不应把所有 case 都强行提升为必须维护参考答案的数据形状。

样本结构必须匹配各 metric 所需字段：`AnswerRelevancy` 最小需要 `input` 与 `actual_output`；`Faithfulness` 和 `ContextualRelevancy` 还需要 `retrieval_context`；`ContextualPrecision` 与 `ContextualRecall` 则必须再具备 `expected_output`。因此数据模型必须显式区分“默认 triad 即可执行的 referenceless 样本”和“启用 reference-based 检索指标的增强样本”，不能把所有样本都压成一类最简结构，也不能把 `expected_output` 误写成所有 case 的必填项。

主路径数据来源是仓库内 checked-in 的 `Golden` artifact，而不是在 `pytest --run-deepeval` 时临时生成样本。当前执行面由 `tests/eval_support.py` 直接读取 `tests/fixtures/evals/synthetic_goldens.json`，并把 payload 转成 `RagEvalCase`；该 artifact 继续锚定仓库现有 fixture、现有 API 主链路和已验证问答场景。当前 `deepeval` seed dataset 只维护 `md` 文档样本，用最小可维护闭环覆盖真实检索与回答联合场景；`txt` 与 `pdf` 仍属于仓库的产品 / 解析测试能力，但不作为当前 `deepeval` 主评测集的一部分。

当前仓库里的 checked-in goldens 契约是 `6` 份 `md` 源文档、每份固定 `10` 条 goldens，总计 `60` 条，统一写入 `tests/fixtures/evals/synthetic_goldens.json`。这些源文档来自 `网页/deepeval/eval集`，通过 `tests/evals/generate_goldens.py` 离线同步到 `tests/fixtures/documents` 后再生成 artifact；脚本会强制每份文档必须产出正好 `10` 条 goldens，避免主评测集规模继续漂移。这批样本当前统一提供 `expected_output`，以确保默认 triad 之外，`ContextualPrecision` 与 `ContextualRecall` 也能在同一批 case 上执行；同时通过加载期校验把 `deepeval` fixture 约束为当前只接受 `md` 文档。

offline generation 的定位是产出和更新 checked-in goldens，而不是运行时依赖。`tests/evals/optimize_prompt.py` 也只离线消费同一个 `synthetic_goldens.json` 做 GEPA prompt optimization，并输出独立 prompt artifact；它不参与 `pytest --run-deepeval` 的执行流程，也不在评测运行时重新生成样本或重写 prompt。runtime deepeval 执行只消费已提交的 goldens、真实 query path 返回的 `answer` / `contexts`，以及按 case 是否含 reference 决定的 metric 组合。

# 验收口径

先失败的条件是：评测集只有一个 smoke case、无法覆盖当前仓库的主要文档类型与问答形状；样本没有按 metric 需要提供正确字段；或默认指标与增强指标的启用边界不清楚。通过后的可观察结果是：评测集能从现有 fixture 稳定生成多条单轮 test cases；默认核心指标组稳定体现 `RAG triad`；reference-based 与 referenceless metrics 的数据依赖被明确区分；并且新增样本时不会破坏现有设计边界。

# 依赖与边界

本文件依赖现有测试 fixture、checked-in goldens artifact、真实 API 主链路以及 `deepeval` 单轮 RAG metrics 定义；它向上为执行入口和 CI 提供可批量运行的 test cases。阈值策略、通过标准和基线比较虽然与本文件密切相关，但它们更属于执行层决策，不在本文件里展开成具体命令或工作流；离线 `synthetic data generation` 与离线 prompt optimization 也只作为 artifact 维护能力存在，不改变这里定义的 runtime 主数据路径。
