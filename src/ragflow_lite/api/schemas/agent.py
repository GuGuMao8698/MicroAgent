"""Pydantic request/response models for agent session endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class SessionResponse(BaseModel):
    """UI-safe session metadata — no backend identifiers."""

    id: str
    title: str
    created_at: str
    updated_at: str
    last_error: str | None = None


class ResumeSessionResponse(BaseModel):
    session_id: str
    status: str
    last_error: str | None = None


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)


class SendMessageResponse(BaseModel):
    session_id: str
    status: str
    message: str | None = None
