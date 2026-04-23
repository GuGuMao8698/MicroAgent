# 证据包契约

# 目标

定义 `MiniRAG` 检索上下文到 `DiscoRAG` 证据组织层之间的统一桥接产物，使后续模块只消费一份稳定、去重、可回查 provenance 的 evidence package，而不需要理解检索实现细节。

# 范围与非目标

本文件只定义 evidence package 的角色、最小字段语义与排序边界。它不定义 ingestion、不定义 query grounding、不定义块内话语结构提取，也不保留旧方案中围绕多路 route 的分数组合前提。`V3` 不在本文件复活 `CoT / HyDE / multi-route` 的候选包语义，也不把最终回答排序混入这里。

# 核心契约

evidence package 的输入是 `MiniRAG` 产出的检索上下文；输出是一份可直接交给 `DiscoRAG` 的稳定证据列表。每条证据至少需要包含：canonical chunk id、原始 chunk 文本或可回查引用、来源 provenance、与 query 相关的实体/关系摘要，以及在本批证据中的稳定顺序。若多个命中最终指向同一 canonical chunk，桥接层必须在这里完成去重，而不是把重复文本继续交给后续规划层。

该契约只吸收旧 `candidate-dedup-and-score-composition.md` 中仍然有价值的部分：稳定 canonical 身份、命中证据保留、去重后顺序与 provenance 回查。它不再保留“多路 route score composition”这一旧假设，也不要求不同 route 的原始分值天然可比。首版允许用更直接的证据顺位规则组织输出，但必须让后续层看得见每条证据为何被保留、来自哪些图路径或局部命中。

evidence package 的职责是把检索产物整理为“可被结构化阅读”的证据输入，而不是替 `DiscoRAG` 生成 discourse 计划。它必须对外表现为统一桥接层：上游无论采用何种具体图检索细节，下游只会接收到一份稳定的 evidence package，而不是检索实现的内部中间态。

# 验收口径

先失败的条件是：同一 canonical chunk 在输出中重复出现、证据丢失 provenance 或无法回查对应路径/实体、桥接层仍依赖旧的多路 route score 语义、或后续层必须回到检索内部才能理解输出。通过后的可观察结果是：`MiniRAG` 检索上下文能够收敛为一份稳定证据包；每条证据都能追溯到来源 chunk 与局部命中理由；`DiscoRAG` 可以只消费这份产物而无需理解检索执行细节。

# 依赖与边界

本文件依赖 `minirag-query-grounding-and-topology-retrieval.md` 交付统一检索上下文，但不反向规定图检索实现。它向上只服务 `discorag-intra-chunk-discourse-structure.md` 与 `discorag-inter-chunk-graph-and-answer-plan.md`，并保持自身不越权到回答生成层。本文件只对“如何把检索结果收敛成稳定证据包”负责，不对“块内结构怎么抽、块间关系怎么组织、最终提示词如何编写”负责。
