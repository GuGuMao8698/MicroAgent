# ragflow对传统rag的改进

一句话结论：

`ragflow-lite` 不是传统 RAG demo 的照搬版；它已经吸收了 `RAGFlow` 对传统 RAG 的几项核心后端改进，当前重点是 `hybrid retrieval`、`rerank`、`citation`、复杂文档解析和异步 ingestion pipeline，但没有追求复刻 `RAGFlow` 的全平台能力。

## 对照表

| 传统 RAG 常见做法 | RAGFlow 的改进 | ragflow-lite 是否吸收 | 对应计划位置 | 说明 |
| --- | --- | --- | --- | --- |
| 只做向量检索 | 做混合检索，把关键词检索和向量检索 / rerank 结合起来 | 已吸收 | [计划.md](./计划.md) 的“阶段二：做出 v0 和 v1” | 计划里明确提出 `Elasticsearch`、`hybrid retrieval`，已经不是“只做 embedding + cosine search”的传统路径。 |
| 召回后直接把结果塞给生成模型 | 在召回之后加入 `rerank`，提升排序质量 | 已吸收 | [计划.md](./计划.md) 的“阶段三：做出 v2” | 这说明项目不满足于“能搜到”，而是开始关注“哪个结果应该排在前面”。 |
| 回答没有可靠出处，或者只给很粗的来源 | 强调 `grounded citations` / `traceable citations`，让回答可以追溯到 chunk 和来源 | 已吸收 | [计划.md](./计划.md) 的“主项目定义”“阶段二”“阶段三” | `citation` 被当成正确性机制，而不是前端展示细节。 |
| 默认输入是干净文本，文档解析不是重点 | 面向复杂文档做更强的 document understanding | 已吸收 | [计划.md](./计划.md) 的“阶段二”“阶段三”“阶段五” | 计划从一开始就覆盖 `pdf`，后续还有 `OCR fallback`、`layout`、`table`，明显不是只吃纯文本。 |
| 用固定长度、固定重叠的方式切块 | 更强调 template-based / strategy-based chunking | 部分吸收 | [计划.md](./计划.md) 的“主项目定义”“阶段三” | 计划已经有 `chunking` 和 `parser strategy`，但还没有明确写成类似 `RAGFlow` 那种系统化、模板化的 chunking 能力。 |
| 用同步脚本把 `extract -> embed -> index` 一次跑完 | 做可编排、异步、带任务管理的 ingestion pipeline | 已吸收 | [计划.md](./计划.md) 的“阶段四：做出 v3” | 计划已经明确写出 `extract -> chunk -> embed -> index`，并加入状态跟踪、失败重试、幂等、进度。 |
| 主要凭最终问答效果“感觉”好不好来调参 | 更重视 retrieval test、检索调优和可解释调参 | 部分吸收 | [计划.md](./计划.md) 的“阶段五：做出 v4” | 计划里提到了 `eval`，但还不是前期主线，说明已经意识到评测重要，但还未前置到核心流程。 |
| 没有知识图谱增强 | 提供 `GraphRAG` 作为可选增强能力 | 暂未吸收为主线 | [计划.md](./计划.md) 的整体路线 | 这不代表计划过时，只代表当前优先把主链路做强，而不是一开始就上更重、更贵的高级增强。 |

## 当前最关键的借鉴点

当前最能体现 `RAGFlow` 思路、也最有求职证明力的，不是 `GraphRAG`、`Agent`、`MCP` 这些更高层的平台能力，而是下面这四项：

- `hybrid retrieval`
- `rerank`
- `citation`
- `async ingestion pipeline`

这四项合在一起，才让 `ragflow-lite` 不再是“上传文件 + 调 LLM”的壳。它们直接对应了知识库后端里最重要的几个问题：

- 能不能比单一路径向量检索更稳定地召回相关内容。
- 能不能把更相关的 chunk 排到前面，而不是随便拼接上下文。
- 能不能让回答有可追溯引用，降低“答得像对，其实没依据”的风险。
- 能不能把 ingestion 做成一个可以观察、可以重试、可以扩展的工程系统，而不是一次性脚本。

如果目标是进入英飞流的 `Python 实习生` 岗位，这四项比 `GraphRAG`、`Agent`、`MCP` 更适合作为当前主线，因为它们最能证明自己理解了 `RAGFlow` 的核心后端价值：`检索质量`、`回答可追溯性`、`复杂文档处理` 和 `工程化 pipeline`。

## 当前没有吸收，但不是问题

下面这些能力当前没有系统吸收，或者没有被放进主线，但这并不说明 `ragflow-lite` 不像 `RAGFlow`，更不说明这份计划已经过时：

- 尚未系统吸收 `template-based chunking`。
- 尚未把 `retrieval eval` 做成前期主线。
- 尚未把 `GraphRAG / RAPTOR / tag / cross-language search` 纳入核心路线。
- 尚未涉及 `Agent / MCP / Memory` 这类平台扩展。
- 尚未涉及 `Infinity` 这类底层文档引擎实现。

这恰恰说明 `ragflow-lite` 的定位是清楚的：

- 它是一个**面向英飞流 `Python 实习生` 岗位的裁剪版后端项目**。
- 它不是 `RAGFlow` 的全量复刻。
- 它也不是传统 RAG 的照抄版。

换句话说，`ragflow-lite` 的策略不是“把 `RAGFlow` 的所有功能都缩小一遍”，而是优先吸收其中最能体现 Python 后端工程能力、最能形成招聘证明力的那部分。

## 小结

`ragflow-lite` 已经吸收了 `RAGFlow` 对传统 RAG 的核心后端改进，但当前聚焦的是最能体现 Python 后端工程能力的主链路，而不是全平台高级能力。

## 参考依据

- 本地计划：[计划.md](./计划.md)
- `RAGFlow` README：
  - Deep document understanding
  - Template-based chunking
  - Grounded citations
  - Multiple recall paired with fused re-ranking
- `RAGFlow` retrieval test 文档：
  - 普通 chunk 使用 hybrid search
  - 检索调优和 retrieval test 是重要环节
- `RAGFlow` construct knowledge graph 文档：
  - `GraphRAG` 是知识图谱增强能力
  - 它适合 multi-hop 问答，但成本更高，属于可选增强而不是唯一主路径
