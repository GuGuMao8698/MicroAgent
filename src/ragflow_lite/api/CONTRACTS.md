# API Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/api`.
`AGENTS.md` in this subtree should link here instead of duplicating these
contracts.

## Scope

FastAPI HTTP interface layer: routes, schemas, dependency wiring, observability.

## HTTP Surface Contract

Reviewed at: `2026-05-08T21:00:00+08:00`
Status: Active
Owner: `routes/v0` router

Endpoints:
- `health` -- liveness check
- `POST /documents` -- ingestion, requires `Idempotency-Key` header; returns
  `202 Accepted` + `Location` header immediately, does not wait for indexing
- `GET /documents` -- document list, optional `dataset_id` query parameter filter
- `GET /documents/{id}` -- document detail; async ingestion polling entry,
  returns task status + optional catalog data
- `PATCH /documents/{id}/dataset` -- rebind/unbind dataset
- `POST /queries` -- query execution, mode routing via `mode` field
- `POST /datasets`, `GET /datasets`, `GET /datasets/{id}`, `DELETE /datasets/{id}`
  -- dataset CRUD

Mode routing:
- `POST /queries` `mode` field: `"standard"` | `"discorag"`, default `"standard"`
- Retrieval strategy parameters are NOT exposed to the HTTP layer
- Response structure must stay stable

Idempotency-Key behavior:
- Missing `Idempotency-Key` on `POST /documents` returns `400`
- Duplicate key reuses existing async task identity instead of creating a new upload

Response schemas:
- `DocumentResponse`, `DocumentListResponse`, `DocumentIngestionResponse` (202),
  `DocumentDetailResponse`, `DocumentTaskResponse`
- Unknown `document_id` returns `404`

## Observability Contract

- Route layer owns request context / trace header binding and write-back
- HTTP error mapping logged as `request_error` (warning)
- Unhandled exceptions logged as `request_unhandled_exception` (error)
- Optional `/metrics` route registration
- HTTP metrics must use low-cardinality labels; `route` label must use template
  paths, never `document_id`, query text, filenames, or other high-cardinality values

## Verification

- Route wiring: `tests/unit/api/`
- Provider wiring: `tests/unit/api/test_providers.py`
