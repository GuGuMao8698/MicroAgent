# RAPTOR 数据集级范围扩展

# 参考项目

- `/home/xia/ragflow-lite/ragflow/rag/svr/task_executor.py`：参考上游 `file scope` 与 `dataset scope` 的运行路径
- `/home/xia/ragflow-lite/ragflow/api/apps/services/dataset_api_service.py`：参考上游数据集级 `RAPTOR` 任务入口
- `/home/xia/ragflow-lite/ragflow/api/apps/kb_app.py`：参考上游数据集级任务触发与状态管理方式

# 目标

在前序能力已经稳定的前提下，将 `RAPTOR` 的作用范围从 `file scope` 扩展到 `dataset scope`。

# 范围与非目标

本文件只定义 `dataset scope` 下的任务范围、边界与风险控制。它不重新定义 `file scope` 的多层树构建，不负责首次建立通用检索可见性，也不重复展开运行保护的细节。

# 核心契约

`dataset scope` 是在既有 `file scope` 主链路、通用检索可见性与运行保护已经成立后才启用的扩展能力。它允许在更大范围内组织 `RAPTOR` 运行，但仍应保留可观测的任务状态、可排查的资源风险边界，以及与前序阶段兼容的失败保护逻辑。

# 验收口径

通过后的可观察结果是：在保留前述保护逻辑的前提下，`dataset scope` 可以工作；其任务状态、资源风险与排障边界可观测、可排查；不会反向破坏 `file scope` 已验证通过的闭环。

# 依赖与边界

本文件依赖前 3 份 `RAPTOR` 设计文档已经建立稳定主链路。若 `file scope`、通用检索可见性或运行保护尚未站稳，不应提前把 `dataset scope` 作为当前实现批次的主目标。
