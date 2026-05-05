# AGENTS.md

## Purpose
这个目录承接当前后端源码，实现上传、解析、切块、索引、查询、回答主链路，并保持清晰分层。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现围绕主链路演进，避免为未来阶段提前扩张默认运行路径。
- 默认生产检索路径是 graph-first：`MiniGraphFirstRetriever` 先做 query grounding → graph index 查询 → path expansion → source chunk scoring（MiniRAG mini mode Counter/vote 对齐）→ source selection（budget 分配 `final_context_k` / `discourse_selection_k`），`InfinityHybridRetriever` 作为辅助 chunk 检索（auxiliary）按 MiniRAG `kwd2chunk` 候选路径放大参与评分。pure dense / pure fulltext 仅保留为 index 层内部诊断能力。
- 保持基础 inline citation、文档目录读取和 grounded answer 主链路可用，但把实现细节放回各自子层，不在源码根重复项目阶段说明。
- 仅允许把 cross-cutting observability helper 放进 `shared`，例如 logging formatter、request/trace context、Prometheus helper；不要把业务流程和 HTTP 逻辑塞进 `shared`。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。
- `infrastructure/evidence` 承接 evidence 相关底层能力：ingestion 侧图证据提取、持久化与 graph candidate sidecar，query-time hybrid entity/relationship candidate retrieval + BFS path expansion，以及 query-time 块内语篇结构提取。不要在源码根重复 provider 迁移状态或具体符号清单。
- query-time 图检索已落地：`MiniGraphFirstRetriever`（无状态，安全共享）作为默认检索器，产出 `GraphFirstSourceSelection` 合约（显式 budget 分配 answer/discourse 候选 + 可解释 selection_reason），通过下游 `EvidencePackageBuilder` → discourse extractor（优先 selected_for_discourse）→ blueprint builder → answerer 全链路传递。`QueryModeRouter` 作为 `/queries` 的分发入口，根据请求 `mode` 调度到 `standard`（`QueryService`）或 `discorag`（`DiscoRAGQueryService`）路径。

## Avoid Here
- 不要把 OCR/layout/table/DeepDoc、外部 rerank、dataset-aware query filter 等尚未进入默认主链路的能力提前塞进当前实现。当前只允许已落地的基础 dataset 管理 baseline、异步 ingestion pipeline（任务状态、幂等、重试、进度、stage cache）、ingestion 侧图证据提取和 query-time 图检索（含拓扑检索），不允许顺手把 query filter / rerank / topology scoring / 新主路径一起带入。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把”暂时不知道放哪”的代码默认丢进 `shared`，尤其不要把业务编排、provider 调用或路由控制流塞进去。
