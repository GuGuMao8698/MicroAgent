# MiniRAG 查询 grounding 与拓扑召回

# 参考项目

- `/home/xia/ragflow-lite/MiniRAG/minirag/minirag.py`：参考 `mini` 查询入口与上下文返回方式
- `/home/xia/ragflow-lite/MiniRAG/minirag/operate.py`：参考 query entity/type grounding、路径扩展与 chunk 回收主流程

# 目标

定义 `MiniRAG` 主干在 `V3` 内需要承接的最小图检索边界，使系统能够从原始 query 出发，经由实体和答案类型 grounding、图中路径扩展与 chunk 回收，产出可供后续证据组织消费的结构化检索上下文骨架。

# 范围与非目标

本文件只定义 query 如何进入 `MiniRAG` 检索主线，以及检索主线最小要交付什么上下文。MiniRAG 论文主干强调的是 query grounding、图中路径扩展和 chunk 回收，而不是 `CoT`、`HyDE` 式 query expansion；当前本地 `mini` 模式已经沿着这条主线实现了 prompt 产出关键词、图中 2-hop 扩展、边筛选和 chunk 回收的启发式闭环，但它并不是一个已经抽象成独立稳定 contract 的完整 topology scoring engine。`V3` 只承接这条 `query grounding -> graph expansion -> chunk recovery` 主干，不定义 ingestion 落位、不定义证据去重包、不定义 `DiscoRAG` 计划层，也不重新引入多路 route 扇出。

# 核心契约

`MiniRAG` 图检索的输入是原始用户 query；其本地主线并不是把 query 扇出成更多查询文本，而是先借助 LLM prompt 产出 `answer_type_keywords` 与 `entities_from_query`，再把这些 grounding 结果映射到已经存在的 chunk/entity/relation 索引上，并利用图结构把局部命中扩展为更完整的证据链。V3 在这里承接的是这条已经成立的主线，而不是论文里更完整的 path ranking 与 scoring contract 全量复刻。

检索核心必须保留“路径发现 + chunk 回收”这两个阶段。路径发现负责围绕 seed 节点在有限 hop 范围内寻找与 query 相关的 entity/relation 连接；chunk 回收负责把这些路径重新映射回可供阅读和回答的文本证据。对当前本地 `mini` 主线来说，外显输出首先应被理解为一份结构化检索上下文骨架，以 `Entities + Sources` 为核心；`relationships` 在本地主线里更多承担路径筛选和排序的内部证据角色，而不是必须对外暴露的固定输出段。最小输出不是最终答案，也不是旧式多路候选包，而是后续层可以消费的一份检索上下文骨架。

该能力必须保持单 query 主路径和可独立评估。本地参考实现中已经存在 `naive / light / mini` 模式分流，但 `V3` 当前只承接 `mini` 主干，不额外设计新的图检索增强开关层；后续层只消费统一的检索上下文骨架，而不需要理解 query-time 多路 route 的执行细节。它不能在本文件内前移回答规划，也不能反向要求 `DiscoRAG` 决定检索路径。

# 验收口径

先失败的条件是：query 仍必须经过 `CoT` 或 `HyDE` 等扩展才能进入检索、图检索只返回孤立 chunk 而没有路径/实体证据、检索结果无法组织成统一上下文骨架、或输出已经混入回答计划与最终排序。通过后的可观察结果是：原始 query 可以先完成 query grounding，再进入 `MiniRAG` 检索主线；路径扩展和 chunk 回收构成稳定闭环；结果能以统一的上下文骨架交给后续层消费；评估时可独立比较“基础检索”和“MiniRAG 图检索主干”的上下文差异。若 prompt/JSON 解析失败，当前本地实现仍可能返回失败响应，因此本文件描述的是 `V3` 承接边界，不把该目标边界误写成现成的稳定引擎保证。

# 依赖与边界

本文件依赖 `minirag-index-and-evidence-storage.md` 中定义的 chunk/entity/relation 落位结果，但不重复展开其存储字段。它向下可使用现有向量命中与图遍历能力，向上只向 `evidence-package-contract.md` 交付检索上下文骨架。本文件只对“如何从 query 获得结构化检索上下文骨架”负责，不对“如何去重为稳定证据包、如何做 discourse 组织、如何生成最终回答”负责。
