# MiniRAG 索引与证据存储

# 参考项目

- `/home/xia/ragflow-lite/MiniRAG/minirag/minirag.py`：参考文档插入、异步入库与图谱更新入口
- `/home/xia/ragflow-lite/MiniRAG/minirag/operate.py`：参考实体/关系抽取与图索引更新路径

# 目标

定义 `MiniRAG` 主干在 `V3` 内需要承接的最小 ingestion 能力边界，使系统能够把原始文档收敛为可检索的 chunk、entity、relation 与对应存储身份，为后续图检索和证据组织提供统一输入。

# 范围与非目标

本文件只定义 `MiniRAG` 主干在 ingestion 侧的最小数据落位关系、状态边界和可追踪性要求。MiniRAG 论文强调的是由 `chunk + entity/relation` 支撑的图索引方向，让后续检索不只依赖纯 chunk 向量匹配；当前本地实现已经落了文档入队、chunk 落位、entity/relation 抽取、图与向量存储 upsert 这条主干，但并没有把论文中更完整的 first-class `chunk node` 异构图、逐边语义描述等结构全部显式落成当前主线。`V3` 只承接这条已经成立的 ingestion 主干，不定义 query-time 扩展、不定义图检索策略、不定义证据组织、不定义 `RAPTOR` 层级摘要，也不把未在本地主线完整显式落地的更强异构图增强写成硬前置。

# 核心契约

`MiniRAG` ingestion 的输入是已经通过基础解析与分块的文档内容；V3 目标上希望把它收敛为四类彼此可追踪的最小产物：chunk、从 chunk 中抽取的 entity、entity 之间的 relation，以及这些对象在图存储与向量存储中的可回查身份。chunk 仍是最小文本证据单元；entity 与 relation 是围绕 chunk 建立的图索引补充，而不是新的最终回答载体。

从本地实现看，chunk 会先进入 `text_chunks` / `chunks_vdb` 等独立存储，再由后续流程执行 entity/relation 抽取并写入图和向量索引；这些对象之间已经能通过 `source_id` 等线索回查来源 chunk，但当前外显边界仍主要表现为内部状态推进和多存储 upsert，而不是一个已经独立抽象好的外部完成协议。因而本文件中的 `chunk` 身份、来源回查和图映射，更适合被理解为 `V3` 希望收敛的目标边界，而不是当前仓库已经对外承诺的成型 API。

`V3` 在这里要保留的是 `MiniRAG` 已成立的语义增强主干，而不是把它再削弱成纯 chunk 检索。该能力只负责把证据写进后续可检索的最小结构：文本 chunk 继续保留为独立文本证据单元，entity 与 relation 进入图侧，必要的向量化索引同步更新。它不能在本文件内扩展为 query planner，不能要求 `CoT`、`HyDE` 一类查询扩展前置参与，也不能把论文中更强但本地主线尚未完整显式落地的 `chunk node` 异构图或 `RAPTOR` 摘要节点一并写成首版契约。

# 验收口径

先失败的条件是：文档经过 ingestion 后只有文本 chunk 而没有可追踪的 entity/relation 结构、对象落位后无法回查来源文档和 chunk 身份、或系统必须依赖额外 query-time 扩展才能使用这些存储产物。通过后的可观察结果是：同一文档能够稳定产出 chunk 集合；chunk 可继续映射出 entity 与 relation；文本、图和向量侧身份能够互相回查；`V3` 后续图检索能够主要消费这里收敛出的落位结果，而不需要反复回到 ingestion 过程补信息。

# 依赖与边界

本文件依赖 `smart-chunking-baseline.md` 提供稳定 chunk 基线，以及当前仓库已有的文档存储、向量存储和异步 ingestion 承载环境，但不重复定义这些组件的内部实现。`minirag-query-grounding-and-topology-retrieval.md` 只消费这里收敛出的文本与图索引；`RAPTOR` 只能在后续增量中基于这里的 chunk 结果再构造层级摘要，不能反向改写本文件定义的最小承接边界。
