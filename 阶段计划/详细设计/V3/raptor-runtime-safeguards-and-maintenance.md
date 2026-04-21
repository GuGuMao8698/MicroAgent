# RAPTOR 运行保护与维护面

# 参考项目

- `/home/xia/ragflow-lite/ragflow/rag/utils/raptor_utils.py`：参考上游 structured data 自动跳过与前置检查边界
- `/home/xia/ragflow-lite/ragflow/internal/common/parser_config.go`：参考上游默认开关与解析配置默认值
- `/home/xia/ragflow-lite/ragflow/rag/svr/task_executor.py`：参考上游缺 embedding 跳过、错误中止与任务运行保护

# 目标

补齐 `RAPTOR` 的运行保护与维护面，使其从“能够跑通”推进到“能够长期维护”。

# 范围与非目标

本文件只定义 structured data 自动跳过、缺 embedding 跳过、重复运行保护、错误中止与清理链路。它不重新定义多层树构建逻辑，也不负责把作用范围扩到 `dataset scope`。

# 核心契约

`RAPTOR` 在进入递归构建前，应允许沿用上游的自动跳过与失败保护逻辑，避免对不适合的数据类型、缺失 embedding 字段的 chunk 或重复运行场景造成脏状态。运行失败后，应保留可观测、可排查、可清理的状态，而不是依赖人工兜底恢复。

# 验收口径

通过后的可观察结果是：structured data 自动跳过、缺 embedding 跳过、重复运行保护、错误中止与清理路径都具备可验证行为；失败后系统不会遗留难以恢复的半完成状态。

# 依赖与边界

本文件建立在“文件级入库闭环”已经存在的前提上。通用检索可见性与 `dataset scope` 扩展由其他独立文档负责。
