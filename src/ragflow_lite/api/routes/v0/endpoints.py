from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ragflow_lite.api.deps.providers import get_ingestion_pipeline, get_query_service
from ragflow_lite.api.schemas.v0 import (
    DocumentIngestionResponse,
    ErrorResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RetrievedContextResponse,
)
from ragflow_lite.application import IngestionPipeline, QueryService
from ragflow_lite.domain.errors import (
    DocumentParsingError,
    EmptyDocumentError,
    ProcessingError,
    RagflowLiteError,
    UnsupportedFileTypeError,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/documents",
    response_model=DocumentIngestionResponse,
    responses={
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def ingest_document(
    file: UploadFile = File(...),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
) -> DocumentIngestionResponse:
    try:
        content = await file.read()
        result = pipeline.ingest(file.filename or "", content)
        return DocumentIngestionResponse(
            document_id=result.document_id,
            file_type=result.file_type,
            chunk_count=result.chunk_count,
            status=result.status,
        )
    except RagflowLiteError as exc:
        raise _map_error(exc) from exc
    finally:
        await file.close()


@router.post(
    "/queries",
    response_model=QueryResponse,
    responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse}},
)
async def query_documents(
    payload: QueryRequest,
    query_service: QueryService = Depends(get_query_service),
) -> QueryResponse:
    try:
        result = query_service.query(payload.query, payload.top_k)
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
        raise _map_error(exc) from exc


def _map_error(error: RagflowLiteError) -> HTTPException:
    if isinstance(error, UnsupportedFileTypeError):
        return HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        )

    if isinstance(error, (DocumentParsingError, EmptyDocumentError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
