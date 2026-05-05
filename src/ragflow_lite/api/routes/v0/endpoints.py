from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from ragflow_lite.api.deps.providers import (
    get_dataset_service,
    get_document_service,
    get_ingestion_pipeline,
    get_query_router,
)
from ragflow_lite.api.schemas.v0 import (
    CreateDatasetRequest,
    DatasetListResponse,
    DatasetResponse,
    DocumentDatasetBindingRequest,
    DocumentDetailResponse,
    DocumentIngestionResponse,
    DocumentListResponse,
    DocumentResponse,
    ErrorResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RetrievedContextResponse,
)
from ragflow_lite.application import (
    DatasetService,
    DocumentService,
    IngestionPipeline,
)
from ragflow_lite.application.services.query_mode_router import QueryModeRouter
from ragflow_lite.domain.errors import (
    DatasetAlreadyExistsError,
    DatasetNotEmptyError,
    DatasetNotFoundError,
    DocumentNotFoundError,
    DocumentParsingError,
    EmptyDocumentError,
    IdempotencyKeyMissingError,
    ProcessingError,
    RagflowLiteError,
    UnsupportedFileTypeError,
)
from ragflow_lite.shared.observability import log_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _request_fields(request: Request) -> dict[str, str]:
    return {"method": request.method, "path": request.url.path}


def _log_request_event(
    request: Request,
    level: int,
    event: str,
    **fields: object,
) -> None:
    log_event(logger, level, event, **_request_fields(request), **fields)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Dataset endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/datasets",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def create_dataset(
    request: Request,
    payload: CreateDatasetRequest,
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetResponse:
    try:
        ds = dataset_service.create_dataset(payload.name, payload.description)
        return DatasetResponse(
            dataset_id=ds.dataset_id,
            name=ds.name,
            description=ds.description,
            created_at=ds.created_at,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


@router.get(
    "/datasets",
    response_model=DatasetListResponse,
    responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse}},
)
async def list_datasets(
    request: Request,
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetListResponse:
    try:
        datasets = dataset_service.list_datasets()
        return DatasetListResponse(
            datasets=[
                DatasetResponse(
                    dataset_id=ds.dataset_id,
                    name=ds.name,
                    description=ds.description,
                    created_at=ds.created_at,
                )
                for ds in datasets
            ]
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


@router.get(
    "/datasets/{dataset_id}",
    response_model=DatasetResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_dataset(
    request: Request,
    dataset_id: str,
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetResponse:
    try:
        ds = dataset_service.get_dataset(dataset_id)
        return DatasetResponse(
            dataset_id=ds.dataset_id,
            name=ds.name,
            description=ds.description,
            created_at=ds.created_at,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


@router.delete(
    "/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def delete_dataset(
    request: Request,
    dataset_id: str,
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> None:
    try:
        dataset_service.delete_dataset(dataset_id)
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/documents",
    response_model=DocumentIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def ingest_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    dataset_id: str | None = Form(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
) -> DocumentIngestionResponse:
    try:
        content = await file.read()
        snapshot = pipeline.submit(
            idempotency_key, file.filename or "", content, dataset_id=dataset_id
        )
        _log_request_event(
            request,
            logging.INFO,
            "document_ingested",
            document_id=snapshot.document_id,
            chunk_count=snapshot.chunk_count,
        )
        response.headers["Location"] = f"/api/v0/documents/{snapshot.document_id}"
        return DocumentIngestionResponse(
            document_id=snapshot.document_id,
            status=snapshot.status,
            file_type=snapshot.file_type,
            dataset_id=snapshot.dataset_id,
            attempt=snapshot.attempt,
            progress_percent=snapshot.progress_percent,
            step=snapshot.step,
            chunk_count=snapshot.chunk_count,
            error=snapshot.error,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc
    finally:
        await file.close()


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse}},
)
async def list_documents(
    request: Request,
    dataset_id: str | None = None,
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    try:
        documents = document_service.list_documents(dataset_id=dataset_id)
        return DocumentListResponse(
            documents=[
                DocumentResponse(
                    document_id=doc.document_id,
                    filename=doc.filename,
                    file_type=doc.file_type,
                    size_bytes=doc.size_bytes,
                    created_at=doc.created_at,
                    metadata=doc.metadata,
                    dataset_id=doc.dataset_id,
                )
                for doc in documents
            ]
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_document(
    request: Request,
    document_id: str,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentDetailResponse:
    try:
        # First check task store for task snapshot
        snapshot = pipeline.get_snapshot(document_id)
        if snapshot is not None:
            # Try to enrich with document catalog data
            doc = None
            try:
                doc = document_service.get_document(document_id)
            except DocumentNotFoundError:
                pass

            return DocumentDetailResponse(
                document_id=snapshot.document_id,
                status=snapshot.status,
                file_type=snapshot.file_type,
                dataset_id=doc.dataset_id if doc else snapshot.dataset_id,
                attempt=snapshot.attempt,
                progress_percent=snapshot.progress_percent,
                step=snapshot.step,
                chunk_count=snapshot.chunk_count,
                error=snapshot.error,
                filename=doc.filename if doc else snapshot.filename,
                size_bytes=doc.size_bytes if doc else None,
                created_at=doc.created_at if doc else snapshot.created_at.isoformat(),
                metadata=doc.metadata if doc else None,
            )

        # No task snapshot -- fall back to document catalog only
        doc = document_service.get_document(document_id)
        return DocumentDetailResponse(
            document_id=doc.document_id,
            status="indexed",
            file_type=doc.file_type,
            dataset_id=doc.dataset_id,
            attempt=1,
            progress_percent=100,
            step=None,
            chunk_count=None,
            error=None,
            filename=doc.filename,
            size_bytes=doc.size_bytes,
            created_at=doc.created_at,
            metadata=doc.metadata,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


@router.patch(
    "/documents/{document_id}/dataset",
    response_model=DocumentResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def bind_or_unbind_document_dataset(
    request: Request,
    document_id: str,
    payload: DocumentDatasetBindingRequest,
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    try:
        if payload.dataset_id is not None:
            document_service.bind_dataset(document_id, payload.dataset_id)
        else:
            document_service.unbind_dataset(document_id)
        doc = document_service.get_document(document_id)
        return DocumentResponse(
            document_id=doc.document_id,
            filename=doc.filename,
            file_type=doc.file_type,
            size_bytes=doc.size_bytes,
            created_at=doc.created_at,
            metadata=doc.metadata,
            dataset_id=doc.dataset_id,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/queries",
    response_model=QueryResponse,
    responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse}},
)
async def query_documents(
    request: Request,
    payload: QueryRequest,
    query_router: QueryModeRouter = Depends(get_query_router),
) -> QueryResponse:
    try:
        result = query_router.query(
            payload.query, payload.answer_top_n, mode=payload.mode
        )
        _log_request_event(
            request,
            logging.INFO,
            "query_answered",
            top_n=payload.answer_top_n,
            context_count=len(result.contexts),
        )
        return QueryResponse(
            answer=result.answer,
            contexts=[
                RetrievedContextResponse(
                    chunk_id=context.chunk_id,
                    document_id=context.document_id,
                    text=context.text,
                    score=context.score,
                    metadata=context.metadata,
                )
                for context in result.contexts
            ],
            metadata=result.metadata,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc, request) from exc


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _map_error(error: RagflowLiteError, request: Request) -> HTTPException:
    http_exc = _error_to_http(error)
    _log_request_event(
        request,
        logging.WARNING,
        "request_error",
        status_code=http_exc.status_code,
        error_type=type(error).__name__,
    )
    return http_exc


def _error_to_http(error: RagflowLiteError) -> HTTPException:
    if isinstance(error, IdempotencyKeyMissingError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

    if isinstance(error, UnsupportedFileTypeError):
        return HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        )

    if isinstance(error, (DocumentNotFoundError, DatasetNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )

    if isinstance(error, (DocumentParsingError, EmptyDocumentError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        )

    if isinstance(error, (DatasetAlreadyExistsError, DatasetNotEmptyError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )

    if isinstance(error, ProcessingError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        )

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error.",
    )
