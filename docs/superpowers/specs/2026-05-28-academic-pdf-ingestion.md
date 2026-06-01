# Academic PDF Ingestion

Date: 2026-05-28
Status: Draft design spec

This document specifies a planned ingestion upgrade for MicroRAG. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` until implementation lands.

## Decision

Replace MicroRAG's current native-text PDF parser with a Docling-backed
academic PDF ingestion pipeline.

The target design is Docling-only for PDF parsing. It removes the existing
`pypdf` parsing path instead of keeping it as a fallback. The new pipeline
converts Docling output into MicroRAG-owned structured PDF elements, chunks
academic papers with table/figure/caption awareness, stores extracted figure
images as internal media assets, and optionally enriches every figure with a
bounded, synchronous Ark VLM description pass.

The primary demonstration target is table and figure understanding:

- table extraction and table caption preservation;
- figure caption extraction;
- internal figure image extraction;
- optional image-to-text figure description;
- retrieval that can match table/caption/figure context through universal
  sparse fields.

The implementation must not vendor RAGFlow's DeepDoc stack. RAGFlow is used as
the reference design: parse PDF into structured layout elements, keep tables
and figures as first-class media, attach captions and positions, and optionally
turn figures into text with a vision model. MicroRAG should implement that
shape through Docling and local domain boundaries, not through copied RAGFlow
internals.

## Source-Backed Reference Facts

Local reference project: `参考项目/ragflow`.

Observed RAGFlow facts:

- `rag/app/paper.py` defines `Pdf(PdfParser)` and `chunk()` as the paper
  parser entry points.
- `PdfParser` is exported from `deepdoc.parser` as `RAGFlowPdfParser`.
- `paper.py` does not simply call a generic `Parser._pdf()` result. Its
  DeepDoc path directly orchestrates inherited PDF parser internals such as
  page image loading, layout recognition, table structure recognition, text
  merging, table/figure extraction, position tagging, and cropping.
- `paper.py` treats `abstract` as an independent chunk.
- `paper.py` uses heading heuristics and title frequency to form sections. It
  does not implement a reliable named-section classifier for
  introduction/method/results/conclusion/reference.
- Table and figure handling is media-oriented: layout extraction first
  separates table/figure regions, captions are attached, images can be cropped,
  and optional visual models can describe figures.
- `paper.py` emits chunk dictionaries for indexing, not a durable paper AST.
  The useful downstream fields are text, document type, page/position metadata,
  and table/image chunk type.

Observed MicroRAG facts:

- Current PDF support is based on `BasicPdfParser` and `pypdf`.
- Current PDF parser metadata uses `parser_strategy="pdf_native_text"`.
- Current PDF tests cover native text extraction, page text metadata, empty PDF,
  corrupted PDF, encrypted PDF, and API upload/query page metadata.
- Current chunk auxiliary retrieval uses `InfinityHybridRetriever`, which sends
  tokenizer-derived sparse query text into `InfinityDenseVectorIndex.search_hybrid()`.
- Current chunk sparse fields are built from filename and chunk text only:
  `filename_kwd`, `filename_tks`, `content_tks`, and `content_sm_tks`.
- Existing contracts intentionally removed legacy raw `filename^10,text` from
  default `match_text` fields. Any academic sparse fields must stay
  tokenizer-derived and explicitly indexed.

Observed Docling facts:

- Docling's `DocumentConverter` can convert PDFs into a structured document.
- `PdfPipelineOptions` supports OCR and table structure detection through
  `do_ocr=True` and `do_table_structure=True`.
- `PdfPipelineOptions` supports formula enrichment through
  `do_formula_enrichment=True`.
- `PdfPipelineOptions` supports picture image generation through
  `generate_picture_images=True` and `images_scale`.
- Docling also supports built-in picture description options, but MicroRAG
  should use its own VLM adapter boundary so Ark configuration, retries,
  observability, and tests remain under local control.
- Ark Responses API supports base64 image input as
  `data:{mime_type};base64,{base64_data}` for images smaller than 10 MB, with a
  request body limit of 64 MB.

## Problem

MicroRAG's current PDF ingestion is good enough for native text PDFs, but it is
not a strong job-search demonstration of document understanding. Academic
papers often place important evidence in tables, figures, captions, section
headers, and formula-adjacent context. A plain text extractor can lose or blur
those boundaries.

At the same time, a full RAGFlow DeepDoc port would be oversized. It would bring
OCR, layout recognition, table structure recognition, image handling, optional
VLM enrichment, parser selection, and several model/runtime dependencies into
MicroRAG without preserving MicroRAG's current architecture boundaries.

The desired upgrade should show real engineering ability:

- introduce a heavy parser intentionally;
- keep third-party output behind local schemas;
- preserve table/figure/caption metadata as first-class retrieval signals;
- store media assets internally without leaking image bytes through the API;
- make VLM enrichment optional and failure-tolerant;
- prove the design with targeted tests and evaluation cases.

## Goals

1. Replace the registered PDF parser with a Docling-backed parser.
2. Remove `pypdf` from the active PDF ingestion path.
3. Introduce a MicroRAG-owned structured PDF intermediate representation.
4. Preserve tables as first-class elements and chunks.
5. Preserve figures as first-class elements with internal image assets.
6. Preserve table and figure captions as first-class metadata and sparse
   retrieval signals.
7. Add an academic paper chunker that consumes structured PDF elements rather
   than raw Docling objects.
8. Add universal academic sparse fields to the chunk table, populated for PDF
   chunks and empty for non-PDF chunks.
9. Keep one shared chunk table and one shared retrieval path.
10. Let standard chunk retrieval and MiniRAG auxiliary recall benefit through
    the shared `InfinityHybridRetriever`.
11. Do not change MiniRAG graph evidence schema in this slice.
12. Store figure images internally for metadata and VLM input only.
13. Do not expose media bytes, paths, or download URLs through query responses.
14. Add optional Ark VLM figure description using base64 data URL input.
15. Attempt VLM description synchronously for every extracted figure when
    enabled.
16. Keep VLM enrichment non-critical: failed figure descriptions must not fail
    document ingestion.
17. Add tests and evaluation fixtures focused on table/caption/figure
    retrieval.

## Non-Goals

- Do not vendor or port RAGFlow DeepDoc.
- Do not keep `pypdf` as a PDF parser fallback.
- Do not introduce PyMuPDF4LLM, Marker, MinerU, Unstructured, or additional PDF
  parser backends in this slice.
- Do not add a public media download endpoint.
- Do not return base64 image data in query responses.
- Do not expose local media file paths in API payloads.
- Do not add image preview UI.
- Do not add object storage, TOS upload, signed URLs, or public image hosting.
- Do not add asynchronous VLM enrichment.
- Do not add a VLM enrichment rerun endpoint.
- Do not require VLM success for document ingestion success.
- Do not make formulas a separate semantic QA guarantee.
- Do not add SQL-like table querying.
- Do not modify MiniRAG graph evidence storage, entity matching, relationship
  matching, or graph candidate retrieval.
- Do not add a PDF-specific query endpoint or query mode.
- Do not store raw JSON metadata in Infinity `match_text` fields.
- Do not add raw `text` or `filename` back to default chunk auxiliary
  `match_text` fields.

## Target Architecture

The confirmed layer boundary is:

```text
DoclingPdfParser:
  PDF bytes -> ParsedPdfDocument / PdfElement / MediaAsset

AcademicPdfChunker:
  ParsedPdfDocument -> DocumentChunk[]

Infinity index:
  DocumentChunk metadata -> universal sparse fields

Retriever:
  no PDF-specific query path
  standard and MiniRAG auxiliary retrieval both benefit through shared chunk table
```

### Parser Boundary

`DoclingPdfParser` owns all interaction with Docling. It should:

- accept the same parser input shape as other document parsers;
- run Docling with explicit PDF pipeline options;
- translate Docling output into local `ParsedPdfDocument`, `PdfElement`, and
  `MediaAsset` data structures;
- surface parser warnings and recoverable element-level issues through metadata;
- raise existing parser/domain errors for document-level parse failure.

Docling objects must not leak into application, chunker, retriever, or answerer
interfaces.

### Intermediate Representation

The new local PDF representation should include:

```text
ParsedPdfDocument
- document_id
- filename
- parser_strategy
- title
- pages
- elements
- media_assets
- warnings

PdfElement
- element_id
- element_type
- text
- markdown
- html
- caption
- element_label
- section_path
- page_start
- page_end
- bbox
- media_asset_id
- metadata

MediaAsset
- asset_id
- document_id
- element_id
- media_type
- storage_path
- source_page
- bbox
- size_bytes
- created_at
```

The initial `element_type` vocabulary should include:

```text
title
section_heading
paragraph
table
figure
caption
formula
reference
unknown
```

The implementation may add internal values if Docling requires them, but the
chunk metadata exposed to retrieval should stay within this stable vocabulary
unless the spec is updated.

### Docling Pipeline Options

The intended Docling PDF options are:

```text
do_ocr=True
do_table_structure=True
do_formula_enrichment=True
generate_picture_images=True
images_scale=2
```

The implementation should use `DocumentConverter` with
`InputFormat.PDF` and `PdfFormatOption(pipeline_options=...)`. Do not configure
PDF options with string keys such as `"pdf"`.

### Media Asset Store

Figure images are internal assets. V1 should use file-based local storage:

```text
data/media/pdf-assets/{document_id}/{element_id}.png
```

The stored path is internal. Query responses must not include it.

`asset_id` may appear in chunk metadata for traceability, but the API must not
promise that the asset is user-downloadable.

The asset store must validate:

- media type;
- file extension;
- size bytes;
- path confinement under the configured media root;
- cleanup behavior when a document is re-indexed or deleted.

If cleanup cannot be finished in the first implementation slice, the spec must
be amended before implementation begins. Leaving orphaned media assets without
an explicit lifecycle is not acceptable.

## Academic Chunking

`AcademicPdfChunker` consumes `ParsedPdfDocument`, not raw Docling output.

It should create separate chunks for:

- abstract, when detected;
- regular text sections;
- tables;
- figures;
- references, when detected by heading or element role;
- formulas, as ordinary structured elements with no semantic QA guarantee.

### Table Chunks

Table chunks should include:

- section context;
- element label, such as `Table 2`, when available;
- caption;
- Markdown or HTML table text;
- page range;
- element metadata.

Example chunk text:

```text
Section: Results > Ablation Study
Table 2: Performance comparison across retrievers.

| Method | Recall | MRR |
| ... | ... | ... |
```

### Figure Chunks

Figure chunks should include:

- section context;
- element label, such as `Figure 1`, when available;
- caption;
- optional VLM visual description;
- internal `asset_id`;
- page range.

Example without VLM:

```text
Section: Method > Architecture
Figure 1: Overview of the proposed pipeline.
```

Example with VLM:

```text
Section: Method > Architecture
Figure 1: Overview of the proposed pipeline.
Visual description: The figure shows a pipeline with retrieval, graph
construction, and answer generation stages.
```

The figure image itself must not be embedded in chunk text.

### Captions

Captions are retrieval signals. A caption should be:

- preserved in chunk metadata;
- included in chunk display text when natural;
- tokenized into `caption_tks` for sparse retrieval.

Captions should not be stored only inside JSON metadata, because JSON metadata
does not participate in Infinity `match_text`.

### Section Context

`section_path` should be propagated into table and figure chunks. If Docling
does not provide a usable section hierarchy, the academic chunker may infer a
simple heading stack from heading-like elements.

The first implementation should avoid a complex named-section classifier. It
may map common section headings into `academic_role`, but it should not promise
reliable semantic classification of all paper sections.

## VLM Figure Enrichment

VLM figure enrichment is optional but first-class.

When enabled, ingestion synchronously attempts to describe every extracted
figure image. Every figure is attempted. VLM failures do not block ingestion.

### Ark Client

The VLM adapter should use an OpenAI-compatible client if possible, because
MicroRAG already depends on the OpenAI SDK.

Required configuration:

```text
MICRORAG_FIGURE_VLM_ENABLED=true|false
ARK_API_KEY
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_FIGURE_MODEL=<model-or-endpoint-id>
MICRORAG_FIGURE_VLM_TIMEOUT_SECONDS=60
MICRORAG_FIGURE_VLM_MAX_RETRIES=2
MICRORAG_FIGURE_VLM_MAX_IMAGE_BYTES=10485760
```

The image input format is:

```text
data:{mime_type};base64,{base64_data}
```

The adapter should send one image per request. It must not batch all document
figures into one request.

### Prompt Shape

The VLM prompt should be retrieval-oriented, not conversational. A suitable
default is:

```text
You are describing a figure extracted from an academic paper for retrieval.
Use the caption and section context when available.
Return a concise factual description in the document language when clear;
otherwise use English.
Do not invent numeric values that are not visible.
Focus on entities, methods, variables, axes, labels, trends, and relationships.
```

The request should include caption, section path, and paper title as text
context when available.

### Failure Policy

VLM enrichment is non-critical.

For each figure:

- `succeeded`: description text is written to metadata, chunk text, and
  `visual_description_tks`.
- `failed`: no description is written, but the figure chunk remains with
  caption and section context.
- `skipped`: VLM is disabled or image size exceeds the configured limit.

Retryable errors:

- timeout;
- rate limit;
- 5xx provider errors;
- transient network errors.

Non-retryable errors:

- missing API key;
- invalid model;
- 401/403;
- image too large;
- unsupported image type;
- malformed request caused by local code.

Metadata should record:

```text
figure_description_status
figure_description_provider
figure_description_model
figure_description_attempts
figure_description_error_type
figure_description
```

Do not log raw base64 image data or full provider payloads.

## Universal Sparse Schema

The chunk table should use one universal schema for all file types. Academic
fields exist for every row. Non-PDF rows populate them with empty strings.

New sparse fields:

```text
academic_role_kwd
section_tks
caption_tks
visual_description_tks
element_type_kwd
element_label_tks
```

Existing fields stay:

```text
filename_kwd
filename_tks
content_tks
content_sm_tks
```

The target `match_text` fields are:

```text
filename_kwd^30,
filename_tks^20,
academic_role_kwd^18,
section_tks^12,
caption_tks^10,
visual_description_tks^8,
element_type_kwd^8,
element_label_tks^6,
content_tks^2,
content_sm_tks
```

`visual_description_tks` is intentionally lower weight than `caption_tks`
because captions come from the source paper and visual descriptions come from a
model.

The implementation must update schema validation so legacy chunk tables without
the new fields fail fast before query paths become active.

## Retrieval Contract

No public query API change is planned.

Standard retrieval should continue through:

```text
QueryService -> InfinityHybridRetriever -> InfinityDenseVectorIndex.search_hybrid()
```

MiniRAG auxiliary recall should benefit through the same shared
`InfinityHybridRetriever`.

This slice must not modify:

- `QueryModeRouter`;
- public `/queries` request schema;
- MiniRAG graph evidence schema;
- graph entity or relationship keyword fields;
- DiscoRAG blueprint planning.

## Parser Migration

The active PDF parser migration includes:

- remove `pypdf` from runtime dependencies;
- add `docling`;
- remove or unregister `BasicPdfParser` for `.pdf`;
- replace `parser_strategy="pdf_native_text"` with a Docling strategy such as
  `parser_strategy="docling_academic_pdf"`;
- update PDF parser tests for Docling output semantics;
- keep failure tests for empty, corrupted, encrypted, or unsupported PDFs;
- update API integration tests that assert PDF page metadata.

If the implementation keeps `BasicPdfParser` code temporarily for git-history
or comparison reasons, it must not be registered in `CompositeParser`, and
documentation must not describe it as active runtime behavior.

## Error Handling

Document-level parse failures should fail ingestion with the existing
document-parsing error path.

Recoverable element-level failures should not fail ingestion. Examples:

- one figure image cannot be written;
- one figure VLM description fails;
- one table cannot be serialized as markdown but can be represented as text.

For recoverable failures, the parser or chunker should:

- keep the document ingestible when the remaining content is usable;
- record warning metadata;
- avoid silently dropping elements;
- avoid exposing raw provider payloads or media bytes in logs.

## Observability

Add structured logs or metrics for:

- Docling parse start/success/failure;
- number of PDF elements by type;
- number of table chunks;
- number of figure chunks;
- number of stored media assets;
- VLM figure description attempts;
- VLM success/failure/skipped counts;
- VLM retry counts;
- media asset write failures.

Logs must not contain raw document text, raw query text, image base64, local
media paths, or full provider responses.

## Testing Strategy

### Unit Tests

Parser tests:

- Docling parser maps table, figure, caption, and page metadata into local
  `PdfElement` structures.
- Docling parser stores figure image assets internally.
- PDF parser emits `parser_strategy="docling_academic_pdf"`.
- corrupted/encrypted/empty PDFs preserve explicit failure behavior.

Chunker tests:

- table elements become table chunks with caption and section path.
- figure elements become figure chunks with asset id and caption.
- VLM success adds visual description to chunk text and metadata.
- VLM failure records status but keeps the figure chunk.
- VLM disabled records skipped status.

Sparse-field tests:

- academic metadata creates `academic_role_kwd`, `section_tks`,
  `caption_tks`, `visual_description_tks`, `element_type_kwd`, and
  `element_label_tks`.
- non-PDF chunks write empty academic fields.
- no raw metadata JSON is copied into `match_text` fields.

### Integration Tests

- Upload a real academic PDF fixture and assert table and figure chunks exist.
- Query by table caption and assert the returned context includes the table
  chunk.
- Query by figure caption and assert the returned context includes the figure
  chunk.
- With fake VLM enabled, query by visual-description-only terms and assert the
  figure chunk is retrievable.
- Confirm API query responses do not include base64 images or local media file
  paths.
- Confirm legacy Infinity chunk schema without academic sparse fields fails
  fast.

### Evaluation Cases

Add targeted deepeval or local evaluation cases for:

- table caption retrieval;
- figure caption retrieval;
- visual description retrieval;
- section-scoped table question;
- non-PDF regression, ensuring text and markdown documents still ingest and
  retrieve normally.

## Demo Story

The intended interview demonstration is:

1. Show a paper PDF containing a table and a figure.
2. Ingest it with Docling-backed academic PDF ingestion.
3. Show stored chunk metadata for table and figure chunks:
   `pdf_element_type`, `caption`, `section_path`, `asset_id`, and page range.
4. If Ark VLM is enabled, show `figure_description_status="succeeded"` and the
   generated visual description.
5. Ask a table-caption question and show the table chunk is retrieved.
6. Ask a figure-caption or visual-description question and show the figure chunk
   is retrieved.
7. Explain that the public query path stayed unchanged; the improvement came
   from parser/chunker/index design.

## Pre-Implementation Verification

These items must be resolved during implementation planning or Task 0 before
code changes that depend on them:

1. Pin the exact Docling version only after dependency resolution is tested in
   the local Python 3.13 environment. Do not guess the version in this spec.
2. Verify Docling's concrete table/figure/caption object shape on a real paper
   fixture before implementing parent-child binding.
3. Verify whether the Ark OpenAI-compatible client path accepts local
   base64 data URLs with the selected figure model.

The implementation decisions are fixed:

1. If Docling exposes stable table/figure/caption parent references, use them.
   Otherwise implement a local nearest-caption heuristic bounded by page,
   vertical distance, and element type.
2. Normalize generated figure assets to PNG for internal storage unless Docling
   exposes only another supported image format. If another format is used, the
   `media_type` and extension must match.
3. Delete media assets synchronously when a document is re-indexed or deleted.
   A separate maintenance command is not part of V1.
4. Do not hard-code an Ark model id in code. Read the model from
   `ARK_FIGURE_MODEL`; demo docs may name the user's selected endpoint.

## Rejected Alternatives

### Keep pypdf as fallback

Rejected. It weakens the job-search demonstration and keeps two competing PDF
contracts alive. The selected design treats Docling as the PDF parser and keeps
fallback behavior limited to element-level degradation, not whole-parser
fallback.

### Add PyMuPDF4LLM fast path

Rejected for this slice. Fast fallback is not central to the interview story
and would add routing complexity before the Docling academic pipeline is proven.

### Add Marker or MinerU

Rejected for this slice. They may be useful external parser backends, but the
current goal is a clean Docling-only architecture with table/figure/caption
evidence.

### Public media endpoint

Rejected for this slice. It would require access control, content-type handling,
path-safety review, lifecycle rules, and API response design. Internal media
assets are enough for VLM enrichment and metadata traceability.

### Async VLM enrichment

Rejected for this slice. Async enrichment would require job state, chunk update
semantics, retry queues, and re-index behavior. The selected design uses
synchronous full-pass attempts with non-blocking per-figure failures.

### VLM all-or-fail

Rejected. A single provider failure should not fail an otherwise parseable
document. VLM description is an enrichment, not parser correctness.

## Acceptance Checklist

- `pypdf` is no longer an active runtime PDF parser dependency.
- `.pdf` documents route to Docling-backed parsing.
- Parsed PDFs produce MicroRAG-owned `PdfElement` structures.
- Table chunks include caption, section path, and page metadata.
- Figure chunks include caption, internal asset id, and page metadata.
- Extracted figure images are stored internally and not returned as base64.
- Ark VLM enrichment can be enabled through configuration.
- Every figure is synchronously attempted when VLM is enabled.
- VLM failures do not fail document ingestion.
- VLM success populates `visual_description_tks`.
- Universal academic sparse fields are present in the chunk table.
- Existing standard and MiniRAG auxiliary retrieval use the same shared chunk
  table and benefit from the new sparse fields.
- MiniRAG graph evidence schema is unchanged.
- API query responses do not expose local image paths or raw image bytes.
- Tests cover parser, chunker, sparse fields, integration retrieval, and VLM
  success/failure behavior.
