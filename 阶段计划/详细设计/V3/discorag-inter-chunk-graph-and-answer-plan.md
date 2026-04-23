# DiscoRAG 块间关系与回答计划

# 参考项目

- `/home/xia/ragflow-lite/MinerU_markdown_2601.04377v5_2047328819162181632.md`：参考 `DiscoRAG` 中 inter-chunk rhetorical graph 与 discourse-aware planning 的角色

# 目标

定义 `DiscoRAG` 在 `V3` 内的块间证据组织与回答规划契约，使系统能够基于结构化证据构建跨 chunk 关系，并产出供 answerer 消费的 answer blueprint。

# 范围与非目标

本文件只定义块间 rhetorical 关系、证据排序与回答计划的最小边界。它不定义 ingestion、不定义图检索、不定义块内结构提取细节，也不把该计划层扩展为新的检索驱动器。`V3` 不在本文件要求所有 chunk 两两建图，不引入额外的 query expansion，也不展开训练、微调或研究型扰动实验。

# 核心契约

该层的输入是 evidence package 和对应的 chunk 内局部 discourse 结构；输出是一份 answer blueprint。最小中间步骤包含两部分：一是识别证据之间的块间关系，例如支撑、补充、对比、限定或冲突；二是基于这些关系确定回答呈现顺序与主次结构。answer blueprint 至少需要明确：哪些证据是主干论点、哪些证据是限定条件或反例、回答应按怎样的证据顺序展开，以及 answerer 不应忽略的关系约束。该 blueprint 是生产端产物，用来表达“应该如何回答”；至于 answerer 具体怎样解释这些字段、怎样与底层 contexts 兼容、以及缺失时如何回退，由独立的 answerer 消费契约继续定义。

该层的职责是“检索后、回答前”的证据组织，而不是再向前发起更多检索。它不能在本文件重启 `CoT`、`HyDE` 或其他多路查询扩展，也不能把 answer blueprint 伪装成最终用户答案。answerer 仍负责把 blueprint 转成自然语言输出，但 answerer 不再独自承担证据组织与叙事顺序的全部责任。

首版必须保持有界。块间关系可以只覆盖 top-k 核心证据之间最有价值的联系，answer blueprint 可以采用较轻量的结构化表示，只要它已足以约束后续回答生成的证据顺序与保真边界。它不要求完整复刻论文中的全量研究配置，也不要求额外引入高成本的全 pair 关系推理。

# 验收口径

先失败的条件是：块间层只把 chunk 原样拼接而没有显式关系、answer blueprint 无法表达主干与限定条件、该层重新驱动检索去找更多证据、或最终答案仍完全由 answerer 在无计划条件下自由组织。通过后的可观察结果是：top-k 结构化证据能够被组织成一份可解释的回答骨架；回答生成前已经明确主干证据、补充证据和顺序约束；answerer 可以消费这份 blueprint 生成输出，而不必重新推断整套证据关系。

# 依赖与边界

本文件依赖 `evidence-package-contract.md` 提供稳定证据包，并依赖 `discorag-intra-chunk-discourse-structure.md` 提供局部结构化产物，但不重复定义它们的字段。它向上只负责交付 answer blueprint 或等价的证据组织契约；answerer 如何消费该产物、如何与底层 `contexts` 一起进入回答生成，由独立的 answerer blueprint 消费契约承接。`RAPTOR` 若后续接入，也只能作为补充证据来源，而不能反向改写本文件的回答规划边界。
