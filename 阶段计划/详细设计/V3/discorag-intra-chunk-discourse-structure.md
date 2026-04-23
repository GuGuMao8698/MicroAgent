# DiscoRAG 块内话语结构提取

# 参考项目

- `/home/xia/ragflow-lite/MinerU_markdown_2601.04377v5_2047328819162181632.md`：参考 `DiscoRAG` 中 intra-chunk discourse tree 的角色与目标

# 目标

定义 `DiscoRAG` 在 `V3` 内的块内结构化最小契约，使系统能够对 evidence package 中的 top-k chunks 提取局部 discourse 结构，为后续块间关系建模与回答规划提供可解释输入。

# 范围与非目标

本文件只定义单个 chunk 内部的最小结构化产物、作用边界和可关闭性。它不定义块间 rhetorical graph、不定义最终回答计划、不定义完整研究型 RST parser，也不要求对所有候选 chunk 执行高成本推理。`V3` 不在本文件追求论文级全量结构标注或复杂训练范式。

# 核心契约

块内结构化的输入是 evidence package 中已经排序完成的 top-k chunks；输出是每个 chunk 对应的一份局部 discourse 描述。最小产物至少需要保留三个层面：chunk 内可分辨的 discourse units、这些 units 之间的局部关系，以及能指示主次或支撑关系的结构标记。它的目标不是替换原始文本，而是为后续计划层指出“这一段证据内部哪些内容是主干、哪些内容是补充、哪些局部关系值得保留”。

该能力必须保持有界与可退化。首版可以只覆盖有限数量的高价值 chunks，也可以采用较轻量的结构化方式，只要输出仍能为后续层提供局部可解释骨架。它不能在本文件扩大成完整研究型 RST 系统，不能要求所有 chunk 全量高成本解析，也不能越权去定义跨 chunk 的因果、对比或叙事顺序。

下游消费的是“局部结构化后的 chunk 证据”，而不是重新排序后的最终答案。块内结构提取只负责让单条证据更可读、更可组织，不负责决定这些证据之间的全局关系。

# 验收口径

先失败的条件是：输出仍只是原始 chunk 文本的平铺复制、结构化产物无法区分主次或局部关系、该步骤必须解析所有候选才能运行、或它已经开始承担块间关系与最终计划职责。通过后的可观察结果是：evidence package 中的 top-k chunks 能够稳定产出局部 discourse 描述；后续层可以据此区分主干证据与补充证据；关闭该能力时系统仍能退回平铺证据路径，而不会破坏主链路。

# 依赖与边界

本文件依赖 `evidence-package-contract.md` 提供稳定证据包，但不重复定义证据去重与 provenance 字段。它向上只为 `discorag-inter-chunk-graph-and-answer-plan.md` 提供块内结构化产物，不反向决定哪些证据进入检索，也不直接生成最终回答。
