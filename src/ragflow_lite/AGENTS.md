# AGENTS.md

## Purpose
这个目录承接当前后端源码，实现上传、解析、切块、索引、查询、回答主链路，并保持清晰分层。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现围绕主链路演进，避免为未来阶段提前扩张默认运行路径。
- 默认生产检索路径是 Infinity hybrid，由 `InfinityHybridRetriever` 与 `InfinityDenseVectorIndex.search_hybrid()` 承接。pure dense / pure fulltext 仅保留为 index 层内部诊断能力。
- 保持基础 inline citation、文档目录读取和 grounded answer 主链路可用，但把实现细节放回各自子层，不在源码根重复项目阶段说明。
- 仅允许把 cross-cutting observability helper 放进 `shared`，例如 logging formatter、request/trace context、Prometheus helper；不要把业务流程和 HTTP 逻辑塞进 `shared`。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。
- `infrastructure/evidence` 承接 ingestion 侧的图证据提取与持久化（`OpenAIResponsesEvidenceExtractor` + `LocalJsonGraphEvidenceStore`），作为 chunk→vector 之间的补充管线。
- query-time 图检索基础设施（`QueryGrounder`、`ChunkLookup`、`OpenAIResponsesQueryGrounder`）已落地；`MiniRAGTopologyRetriever` 拓扑检索器和 provider wiring 待实现。

## Avoid Here
- 不要把 OCR/layout/table/DeepDoc、外部 rerank、dataset-aware query filter 等尚未进入默认主链路的能力提前塞进当前实现。当前只允许已落地的基础 dataset 管理 baseline、异步 ingestion pipeline（任务状态、幂等、重试、进度、stage cache）、ingestion 侧图证据提取和 query-time 图检索基础设施，不允许顺手把 query filter / rerank / topology scoring / 新主路径一起带入。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把”暂时不知道放哪”的代码默认丢进 `shared`，尤其不要把业务编排、provider 调用或路由控制流塞进去。
