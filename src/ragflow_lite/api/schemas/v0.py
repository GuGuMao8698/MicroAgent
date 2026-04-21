from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    status: str


class DocumentIngestionResponse(BaseModel):
    """202 Accepted response for async ingestion submission."""

    document_id: str
    status: str
    file_type: str
    dataset_id: str | None = None
    attempt: int
    progress_percent: int
    step: str | None = None
    chunk_count: int | None = None
    error: str | None = None


class DocumentTaskResponse(BaseModel):
    """Task detail response for GET /documents/{document_id}."""

    document_id: str
    status: str
    file_type: str
    dataset_id: str | None = None
    attempt: int
    progress_percent: int
    step: str | None = None
    chunk_count: int | None = None
    error: str | None = None


class DocumentDetailResponse(BaseModel):
    """Combined task + document detail for GET /documents/{document_id}."""

    document_id: str
    status: str
    file_type: str
    dataset_id: str | None = None
    attempt: int
    progress_percent: int
    step: str | None = None
    chunk_count: int | None = None
    error: str | None = None
    # Document catalog fields (present when status=indexed and document exists in catalog)
    filename: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None
    metadata: dict[str, Any] | None = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class RetrievedContextResponse(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    answer: str
    contexts: list[RetrievedContextResponse]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    size_bytes: int
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    dataset_id: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]


# Dataset schemas


class CreateDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(default="")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class DatasetResponse(BaseModel):
    dataset_id: str
    name: str
    description: str
    created_at: str


class DatasetListResponse(BaseModel):
    datasets: list[DatasetResponse]


class DocumentDatasetBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None
