# RAPTOR 通用检索可见性

# 参考项目

- `/home/xia/ragflow-lite/ragflow/internal/service/chunk.go`：参考上游将 `RAPTOR` 生成结果作为普通 chunk 检索候选返回的方式
- `/home/xia/ragflow-lite/ragflow/internal/engine/infinity/search.go`：参考上游通用检索链路的候选生成与融合边界
- `/home/xia/ragflow-lite/ragflow/api/apps/sdk/session.py`：参考上游查询侧继续沿用通用 retrieval 路径的方式

# 目标

让 `RAPTOR` 生成的摘要 chunk 不依赖专门查询 API，也能通过现有通用检索链路进入候选集合。

# 范围与非目标

本文件只定义摘要 chunk 如何被现有检索面看见、返回与继续参与后续排序。它不重新定义多层树构建本身，不新增专门的 query-time `tree-walk API`，也不在这里引入与 `RAPTOR` 强绑定的新检索分支。

# 核心契约

`RAPTOR` 生成结果应和基础 chunk 一样进入现有存储与索引，使通用检索路径能够将其视为普通候选的一部分。查询阶段仍沿用当前通用 retrieval 流程；`RAPTOR` 的作用是提供额外摘要候选，而不是替换基础 chunk 或另建一套专门查询接口。

# 验收口径

通过后的可观察结果是：不增加专门 `RAPTOR` 检索 API 的前提下，摘要 chunk 能进入现有通用检索候选；基础 chunk 路径仍保持可用；后续排序与编排链路可以继续消费这些候选。

# 依赖与边界

本文件依赖“文件级入库闭环”先产出已写回存储的摘要 chunk。运行保护、structured data 处理和 `dataset scope` 不在本文件展开。
