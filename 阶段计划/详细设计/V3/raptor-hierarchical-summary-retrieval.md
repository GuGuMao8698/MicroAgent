# RAPTOR 层级摘要检索

# 说明

本文件不再承担 `V3` 内 `RAPTOR` 的单体详细设计。为降低单次实现压力，并让索引页能直接标记每个子能力的实际代码状态，`RAPTOR` 已拆分为 4 份独立设计文档，各自对应一个可独立实现与验收的条目。

# 拆分后的设计文档

1. [raptor-file-scope-ingestion-closure.md](./raptor-file-scope-ingestion-closure.md)：`file scope` 下的多层树构建、停止条件、任务挂载与摘要 chunk 写回
2. [raptor-generic-retrieval-visibility.md](./raptor-generic-retrieval-visibility.md)：生成后的摘要 chunk 如何通过现有通用检索链路变为候选
3. [raptor-runtime-safeguards-and-maintenance.md](./raptor-runtime-safeguards-and-maintenance.md)：structured data 自动跳过、缺 embedding 跳过、重复运行、错误中止与清理
4. [raptor-dataset-scope-expansion.md](./raptor-dataset-scope-expansion.md)：从 `file scope` 扩展到 `dataset scope` 的范围与边界

# 共同边界

上述 4 份文档共同服务于 `V3` 内完整 `RAPTOR` 的最终目标：参考上游 `RAGFlow` 的递归多层树结构，在 ingestion side 生成多层摘要 chunk，并继续沿用现有通用检索链路，而不是额外引入专门的 query-time `tree-walk API`。

具体实现时，建议按 1 -> 4 的顺序推进，并分别维护各自的状态标识与实现验收，不再把 4 个问题面耦合成一份单体设计文档。
