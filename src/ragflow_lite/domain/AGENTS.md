# AGENTS.md

## Purpose
这个目录负责稳定的业务边界，承载核心对象、抽象接口和领域错误。

## Do Here
- 在 `models` 放 `DocumentAsset`、`ParsedDocument`、`Chunk`、`EmbeddedChunk`、`RetrievedChunk`、`AnswerResult`、`IngestionResult`、`IndexedDocument`、`Dataset`、`IngestionTaskSnapshot`、`EntityEvidence`、`RelationEvidence`、`GraphEvidenceBatch`、`GraphEvidenceWriteResult`、`GroundedQuery`、`EvidenceProvenance`、`EvidenceItem`、`EvidencePackage`、`DiscourseUnit`、`IntraChunkDiscourseRelation`、`ChunkDiscourseStructure`、`IntraChunkDiscoursePackage`、`TopologyPath`、`TopologyRetrievalResult`。
- 在 `ports` 放 `Parser`、`Chunker`、`Embedder`、`VectorIndex`、`Retriever`、`Answerer`、`DocumentStore`、`DocumentCatalog`、`DatasetStore`、`IngestionTaskStore`、`IngestionStageCache`、`IngestionTaskRunner`、`EvidenceExtractor`、`GraphEvidenceStore`、`QueryGrounder`、`ChunkLookup`、`TopologyContextRetriever`、`IntraChunkDiscourseExtractor`。
- 在 `errors` 放领域级异常和统一错误语义（含 `DocumentNotFoundError`、`DatasetNotFoundError`、`DatasetAlreadyExistsError`、`DatasetNotEmptyError`、`IdempotencyKeyMissingError`）。
- 新增模型或 port 时，优先表达稳定业务边界和错误语义，不要为了容纳具体基础设施实现而扩张接口。

## Avoid Here
- 不要依赖 FastAPI、数据库客户端、文件系统或外部 SDK 细节。
- 不要把具体实现塞进 `domain`。
- 不要为了方便把流程编排、markdown 处理、索引文件格式或检索实现细节写进领域对象。
