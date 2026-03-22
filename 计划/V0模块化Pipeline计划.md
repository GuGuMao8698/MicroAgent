# ragflow-lite V0 模块化 Pipeline 计划

更新时间：2026-03-22

## 1. 文档定位

这份文档是 `ragflow-lite` 的 V0 执行规格，用来指导后续实现阶段的结构设计与边界控制。

它的目标不是重复总路线图，而是把 V0 明确收紧为一条可落地、可验证、可扩展的最小后端主链路。

这份文档默认服务两个用途：

- 后续自己按文档直接开工实现。
- 面试或项目讲解时，用来说明为什么 V0 要先做成“模块化同步 pipeline”，而不是先堆接口、后补抽象。

说明：

- 本文档是 V0 的补充规格，不替代 [计划.md](./计划.md)。
- 本文档暂不改写 [计划.md](./计划.md) 和 [ragflow对传统rag的改进.md](./ragflow对传统rag的改进.md)。
- 如果后续正式采用本文档作为实现依据，需要再回头同步主计划里的阶段定义，避免文档口径不一致。

## 2. 一句话结论

V0 不追求一步到位接近 `RAGFlow` 的全部能力，而是先做成一个**同步编排的向量 RAG 基座**：

`upload -> parse -> normalize -> chunk -> embed -> index -> retrieve -> answer`

重点不是“功能先堆出来”，而是从第一天就把主链路拆成稳定模块，让后续的 `Infinity`、`hybrid retrieval`、`citation`、异步任务编排都能在现有骨架上演进，而不是推倒重来。

## 3. V0 目标与边界

### 3.1 V0 要完成什么

V0 只解决下面这件事：

给定一个 `txt`、`md` 或 `pdf` 文件，系统可以同步完成接收、解析、切块、向量化、写入索引，并在查询时完成向量检索和回答生成。

### 3.2 V0 包含内容

- `txt`、`md`、`pdf` 文件上传
- 基础文本抽取与格式识别
- 文本标准化
- chunking
- embedding
- 向量索引写入
- 向量检索
- 基于检索上下文的回答生成
- 最小健康检查接口
- 最小错误处理与最小回滚策略

### 3.3 V0 明确不包含

- hybrid retrieval
- rerank
- 正式 citation
- 异步任务状态跟踪
- 失败重试机制
- OCR
- layout / table parsing
- dataset 管理
- 复杂权限模型
- 检索评测系统

### 3.4 V0 的边界原则

- V0 只做“向量检索路径”，不在这一阶段引入全文检索和融合排序。
- V0 的 `contexts` 仅作为调试和开发观察字段，不视作 citation 能力。
- V0 的 ingestion 采用“同步编排、局部可异步 I/O”的实现方式，不提前引入任务队列和 Redis 状态机。
- V0 从第一天就预留适配接口，但不为了未来能力过度设计。

## 4. 为什么 V0 必须先做成模块化 Pipeline

如果 V0 只是若干 API 加若干工具函数，短期可以跑通 demo，但后面会非常容易在下面几个方向上返工：

- `Infinity` 接入时，需要替换或扩展索引写入与检索能力。
- `hybrid retrieval` 接入时，需要同时保留向量路径和关键词路径。
- `citation` 接入时，需要更稳定的 chunk 和文档元数据边界。
- 异步 ingestion 接入时，需要把现有主链路拆成可编排阶段。

因此，V0 的核心目标不只是“能上传并问答”，而是先建立一条职责明确的主链路骨架：

- 路由层负责请求接收、参数校验、错误映射。
- pipeline 层负责串联主流程。
- 各阶段模块只做单一职责，不跨层偷拿逻辑。

## 5. V0 数据流

V0 固定采用下面这条主链路：

```text
upload -> parse -> normalize -> chunk -> embed -> index -> retrieve -> answer
```

对应解释如下：

1. `upload`
   接收上传文件，生成 `document_id`，把文件保存到受控目录。
2. `parse`
   根据文件类型选择解析器，抽取原始文本和基础元数据。
3. `normalize`
   做最小必要的文本清洗，例如空字符清理、换行规整、基础元数据整理。
4. `chunk`
   把解析后的文本切分成可索引的 chunk。
5. `embed`
   为每个 chunk 生成向量。
6. `index`
   把 chunk 及其向量写入向量索引。
7. `retrieve`
   对查询生成向量，在向量索引中召回相关 chunk。
8. `answer`
   把召回结果作为上下文喂给生成模型，返回回答和调试用 `contexts`。

## 6. 模块划分与职责

V0 固定保留以下模块边界。

### 6.1 Parser

职责：

- 根据文件类型选择对应解析器
- 输出统一的 `ParsedDocument`
- 屏蔽 `txt`、`md`、`pdf` 的底层差异

V0 支持的最小 parser：

- `PlainTextParser`
- `MarkdownParser`
- `BasicPdfParser`

V0 不做的事：

- OCR fallback
- layout 分析
- 表格结构恢复

### 6.2 Chunker

职责：

- 接收 `ParsedDocument`
- 按统一策略切分 chunk
- 输出 `Chunk` 列表

V0 默认策略：

- 固定 `chunk_size`
- 固定 `chunk_overlap`
- 不引入模板化 chunking

### 6.3 Embedder

职责：

- 为 `Chunk` 批量生成 embedding
- 输出 `EmbeddedChunk`

V0 原则：

- 只暴露统一 embedding 接口
- 不把具体 embedding 服务耦合进 route 或 pipeline 逻辑

### 6.4 VectorIndex

职责：

- 写入 `EmbeddedChunk`
- 根据查询向量召回相关 chunk
- 删除或回滚某次 ingestion 产生的数据

V0 原则：

- V0 只实现向量索引路径
- 接口设计上预留未来扩展到 `Infinity` 全文检索和 hybrid retrieval 的空间
- `VectorIndex` 是后续演进中最重要的可替换点之一

### 6.5 Retriever

职责：

- 接收查询文本
- 调用 `Embedder` 生成查询向量
- 调用 `VectorIndex` 召回结果
- 输出 `RetrievedChunk` 列表

V0 原则：

- Retriever 只负责“向量检索”
- 不在 V0 内部承担 rerank、fusion、citation 组装

### 6.6 Answerer

职责：

- 接收原始查询和召回结果
- 组织 prompt
- 调用生成模型产出回答
- 返回 `AnswerResult`

V0 原则：

- 输出 `answer` 和 `contexts`
- `contexts` 只是调试字段，不宣传为 citation

### 6.7 IngestionPipeline

职责：

- 串联 `parse -> normalize -> chunk -> embed -> index`
- 对外提供统一 ingestion 入口
- 在失败时执行“当前文档级别”的最小回滚

V0 原则：

- V0 先做同步编排
- V3 再把 orchestration 升级为异步 pipeline
- 先把阶段边界做清楚，再考虑任务状态、重试和进度

## 7. 领域对象

V0 统一使用下面这组核心领域对象，后续实现阶段尽量不要再随意改名。

### 7.1 DocumentAsset

表示原始上传文件及其存储信息。

建议字段：

- `document_id`
- `filename`
- `file_type`
- `storage_path`
- `size_bytes`
- `created_at`

### 7.2 ParsedDocument

表示完成解析后的统一文档表示。

建议字段：

- `document_id`
- `file_type`
- `raw_text`
- `metadata`

### 7.3 Chunk

表示切分后的文本片段。

建议字段：

- `chunk_id`
- `document_id`
- `text`
- `index`
- `metadata`

### 7.4 EmbeddedChunk

表示已经完成向量化的 chunk。

建议字段：

- `chunk_id`
- `document_id`
- `text`
- `vector`
- `metadata`

### 7.5 RetrievedChunk

表示检索召回结果。

建议字段：

- `chunk_id`
- `document_id`
- `text`
- `score`
- `metadata`

### 7.6 AnswerResult

表示最终问答结果。

建议字段：

- `answer`
- `contexts`
- `metadata`

说明：

- `contexts` 内部元素建议直接由 `RetrievedChunk` 或其等价结构组成。
- V0 不要求 `contexts` 提供 citation 级别的来源定位能力。

## 8. 最小公共接口

V0 对外固定保留下列最小接口形状，后续实现时直接遵循。

### 8.1 `POST /api/v0/documents`

用途：

- 上传文档并同步完成 ingestion

输入：

- `multipart/form-data`
- 文件字段：`file`

行为：

- 保存上传文件
- 识别文件类型
- 解析文本
- 执行 chunking
- 生成 embeddings
- 写入向量索引

成功返回建议：

```json
{
  "document_id": "doc_xxx",
  "file_type": "pdf",
  "chunk_count": 12,
  "status": "indexed"
}
```

失败原则：

- 解析失败时，直接返回明确错误，不进入后续阶段。
- embedding 或索引写入失败时，只回滚当前文档本次 ingestion。

### 8.2 `POST /api/v0/queries`

用途：

- 针对已索引语料执行向量检索与回答生成

输入：

```json
{
  "query": "你的问题",
  "top_k": 4
}
```

行为：

- 生成查询向量
- 向量召回 `top_k` 个相关 chunk
- 基于召回结果生成回答

成功返回建议：

```json
{
  "answer": "根据当前语料，……",
  "contexts": [
    {
      "chunk_id": "chunk_1",
      "document_id": "doc_xxx",
      "text": "被召回的原始片段",
      "score": 0.91
    }
  ]
}
```

说明：

- `contexts` 只用于开发调试和最小可观察性。
- V0 不把这个字段定义成 citation。

### 8.3 `GET /api/v0/health`

用途：

- 提供最小健康检查

成功返回建议：

```json
{
  "status": "ok"
}
```

## 9. 路由层与业务层分工

V0 必须从一开始就避免把核心业务逻辑压进路由层。

路由层职责只包括：

- 请求接收
- 参数校验
- 调用 pipeline / service
- 错误映射
- 返回响应

路由层不应该直接承担：

- 文件解析
- chunking 细节
- embedding 细节
- 索引写入与回滚逻辑
- 检索主逻辑
- prompt 拼接主逻辑

这个约束是 V0 是否真正“模块化”的关键判断标准。

## 10. `rag_api` 的参考方式

V0 可以参考 [`rag_api`](https://github.com/danny-avila/rag_api)，但只能作为**局部参考**，不能直接作为整体架构模板。

### 10.1 值得借鉴的点

- 上传文件隔离与受控存储路径
- loader/fallback 思路
- embedding 批处理失败时的最小回滚意识
- 向量存储的工厂化适配思路
- 对边界 case 的测试意识

### 10.2 不应该照搬的点

- 把大量 ingestion 与 retrieval 逻辑集中在单个 route 文件中
- 让路由层同时承担流程编排和底层细节
- 过早绑定某一种向量存储实现细节

### 10.3 对 `ragflow-lite` 的实际启示

`rag_api` 适合回答“V0 需要哪些模块和失败路径意识”，不适合直接回答“这些模块应该怎么组织到项目里”。

对 `ragflow-lite` 来说，真正要继承的是：

- 明确边界
- 控制职责
- 为未来替换底层检索后端留接口

而不是照着它的目录直接搭骨架。

## 11. V0 与后续版本的关系

V0 的设计必须显式为后续版本留出生长空间。

### 11.1 面向 V1 的预留

V1 预计加入：

- `Infinity` 全文检索
- hybrid retrieval
- 基础文档元数据管理
- 基础 citation 雏形

因此 V0 需要预留：

- 可替换的 `VectorIndex`
- 独立的 `Retriever`
- 稳定的 `Chunk` / `RetrievedChunk` 数据结构

### 11.2 面向 V2 的预留

V2 预计加入：

- rerank
- 更准确的 citation
- parser strategy

因此 V0 需要预留：

- 解析器抽象
- 召回结果的标准化结构
- 不把回答生成和 citation 混在一起

### 11.3 面向 V3 的预留

V3 预计加入：

- 异步 ingestion pipeline
- 任务状态
- 失败重试
- 进度显示

因此 V0 需要预留：

- 单独的 `IngestionPipeline`
- 明确的阶段边界
- 文档级别回滚能力

## 12. 实现验收场景

后续代码阶段，至少要通过下面这些验收场景。

### 12.1 文档 ingestion

- `txt` 文件上传后可完成解析、切块、索引写入，并能成功问答。
- `md` 文件上传后保留基本文本结构，不因解析器选择错误而失败。
- `pdf` 文件上传后可完成基础文本抽取；解析失败时返回明确错误，不进入后续阶段。

### 12.2 查询行为

- 单文档语料下查询可返回回答与原始召回片段。
- 语料为空或召回为空时，返回受控结果而不是 `500`。

### 12.3 失败处理

- embedding 或索引写入失败时，只回滚当前文档本次 ingestion，不污染其他文档。
- 单个模块失败时，错误应沿着统一边界向上返回，避免路由层拼接底层异常细节。

### 12.4 结构约束

- 模块替换不影响 pipeline 编排接口。
- 未来把 `VectorIndex` 从单纯向量索引扩展到 `Infinity` / hybrid 时，不要求重写 `Parser`、`Chunker`、`Answerer`。
- 路由层不直接承载解析、切块、索引等核心流程逻辑，职责只限请求编排与错误映射。

## 13. 默认实现假设

为了避免后续实现阶段反复做决定，V0 默认采用以下假设。

- 文档语言以中文和英文混合文本为主，但 V0 不单独引入语言检测流程。
- 查询默认在全部已索引语料上执行，不在 V0 暴露 dataset 级过滤接口。
- `top_k` 默认值由实现阶段给出一个小而稳定的值，例如 `4`。
- `chunk_size` 和 `chunk_overlap` 在 V0 使用固定配置，不做按文档类型自适应。
- `pdf` 在 V0 只追求基础文本抽取可用，不追求复杂版面质量。
- 生成模型调用失败时，应返回受控错误，而不是让检索结果直接冒充最终答案。
- 文档写入成功的判定标准是：chunk 已完成向量化并成功写入索引。

## 14. 最后结论

V0 的关键不是先把功能列表做长，而是先把主链路做成一条职责清晰、可替换、可演进的模块化 pipeline。

如果 V0 能按本文档落地，那么后续接入 `Infinity`、`hybrid retrieval`、`citation` 和异步 ingestion 时，扩展点会清楚得多，返工成本也会显著降低。
