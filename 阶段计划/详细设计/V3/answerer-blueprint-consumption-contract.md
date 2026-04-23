# Answerer Blueprint 消费契约

# 参考项目

- `/home/xia/ragflow-lite/src/ragflow_lite/domain/models/entities.py`：参考 `AnswerBlueprint`、`AnswerRequest` 与 `RetrievedChunk` 的最小输入形状
- `/home/xia/ragflow-lite/src/ragflow_lite/infrastructure/answerers/openai_responses.py`：参考首个 answerer 消费方如何解释 blueprint 并回退

# 目标

定义 `Answerer` 在 `V3` 内如何消费 `DiscoRAG` 产出的 `AnswerBlueprint`，使回答生成阶段能够同时读取底层证据载体与上游规划约束，而不是只按检索分数平铺 contexts。

# 范围与非目标

本文件只定义 `AnswerBlueprint` 的消费语义、与 `AnswerRequest` / `RetrievedChunk` 的关系，以及 blueprint 缺失或无效时的回退边界。它不定义证据包如何生成、不定义块内话语结构、不定义块间关系如何抽取，也不展开具体 prompt 文案、citation 渲染规则、OpenAI/Ark 请求参数或 provider 兼容分支。`V3` 不在本文件要求实现完整 `DiscoRAG` planner，也不把 answerer 的消费契约扩展为新的检索或规划驱动器。

# 核心契约

`Answerer` 的统一输入是 `AnswerRequest`。其中 `contexts` 仍是底层证据载体，负责提供可直接引用的原始 chunk 文本；`blueprint` 则是对这些证据的组织约束，而不是上下文文本本身。首版 `AnswerBlueprint` 至少包含四类可消费信息：证据顺序 `ordered_chunk_ids`、证据角色 `chunk_roles`、全局回答约束 `answer_constraints`，以及回答展开步骤 `plan_steps`。这些字段只表达 answerer 应如何组织回答，不承载检索分数或 query-time 扩展语义。

当 `AnswerRequest.mode="standard"` 时，answerer 可以完全按普通 RAG 路径工作，不要求必须存在 blueprint；当 `mode="discorag"` 时，blueprint 应被视为“应提供输入”，answerer 必须优先使用 blueprint 的证据顺序与角色约束组织回答，而不是默认退回纯 `score` 排序。若 blueprint 缺失、仅引用未知 `chunk_id` 或无法形成有效顺序，answerer 允许回退到普通 contexts 顺序路径，但必须留下显式痕迹，而不能静默吞掉。

`Answerer` 消费 blueprint 时，至少要遵守三个原则。第一，`blueprint` 不能替代 `contexts`：每个规划项都必须仍可回到真实 chunk 证据。第二，`ordered_chunk_ids` 只允许重排已有 contexts，不允许引入额外不存在的证据。第三，回退必须可观察：answerer 至少需要在 `AnswerResult.metadata` 中标记当前回答模式、是否成功应用 blueprint，以及若发生回退则说明原因。这样后续评估和排障才能区分“普通 RAG 回答”和“DiscoRAG 规划已应用的回答”。

# 验收口径

先失败的条件是：answerer 仍只能消费裸 `query + contexts` 而无法接收 blueprint、blueprint 与底层 contexts 脱钩、`mode="discorag"` 时缺失 blueprint 却没有显式回退标记、或 blueprint 直接被当作 prompt 文案字符串而没有稳定字段语义。通过后的可观察结果是：answerer 能通过统一输入对象读取 query、contexts 和 blueprint；在普通模式下保持兼容；在 `discorag` 模式下优先使用 blueprint 重排和约束回答；当 blueprint 缺失或无效时能显式回退，并在结果 metadata 中留下可调试痕迹。

# 依赖与边界

本文件依赖 `discorag-inter-chunk-graph-and-answer-plan.md` 负责生产 `AnswerBlueprint`，并依赖 `evidence-package-contract.md` 保证底层证据仍可回查到 canonical chunk 与 provenance，但不重复定义它们的生成过程。它向下只约束 answerer 的消费边界，不规定具体 provider 的 prompt 文案或 API 请求细节。本文件只对“answerer 如何解释 blueprint 并与 contexts 协同生成回答”负责，不对“blueprint 如何生成、证据如何检索、citation 如何渲染”负责。
