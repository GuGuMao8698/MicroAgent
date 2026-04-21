# RAPTOR 文件级入库闭环

# 参考项目

- `/home/xia/ragflow-lite/ragflow/rag/raptor.py`：参考上游递归聚类、逐层摘要与多层树收敛的主流程
- `/home/xia/ragflow-lite/ragflow/rag/svr/task_executor.py`：参考上游读取基础 chunk、执行 `RAPTOR` 并写回摘要 chunk 的路径
- `/home/xia/ragflow-lite/ragflow/api/db/services/document_service.py`：参考上游 `RAPTOR` 任务入队与文档解析状态协同方式

# 目标

在 `file scope` 下打通 `RAPTOR` 的最小可运行主链路：基础 chunk 进入递归多层树构建流程，生成多于一层的摘要 chunk，并写回现有存储。

# 范围与非目标

本文件只关注单文档范围内的多层树构建、停止条件、任务挂载与写回路径。它不负责摘要 chunk 如何被现有检索链路召回，也不负责 structured data 自动跳过、重复运行与 `dataset scope` 扩展。

# 核心契约

输入是已经稳定落位且带有当前 embedding 字段的单文档基础 chunk。构建流程按“向量降维 -> 聚类数选择 -> 聚类成员分配 -> 逐簇摘要 -> 摘要向量化 -> 作为下一层输入继续聚类”的闭环递归执行，直到当前层无法再有效收敛。输出是被写回现有存储的多层摘要 chunk，而不是只存在内存中的临时结果。

# 验收口径

通过后的可观察结果是：`file scope` 下能够产出多于一层的摘要 chunk；递归流程可停止；失败不会打乱原有基础 chunk 状态；摘要 chunk 已进入现有存储，供后续阶段继续消费。

# 依赖与边界

本文件依赖稳定的基础 chunk 基线、可用的 embedding 模型、可用的 chat/summarization 模型，以及可承载异步任务的 ingestion worker。检索可见性、运行保护与 `dataset scope` 均由后续独立文档定义。
