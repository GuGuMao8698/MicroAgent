"""Agent session and message HTTP endpoints.

Routes in this module manage MicroRAG agent sessions backed by the ACP
client subprocess. All responses strip backend-only identifiers before
reaching the UI.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ragflow_lite.api.schemas.agent import (
    CreateSessionRequest,
    ResumeSessionResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionResponse,
)

router = APIRouter(tags=["agent"])


def _session_to_response(session: object) -> SessionResponse:
    """Map a session metadata object to its UI-safe response."""
    return SessionResponse(
        id=session.id,  # type: ignore[attr-defined]
        title=session.title,  # type: ignore[attr-defined]
        created_at=session.created_at,  # type: ignore[attr-defined]
        updated_at=session.updated_at,  # type: ignore[attr-defined]
        last_error=session.last_error,  # type: ignore[attr-defined]
    )


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(request: Request) -> list[SessionResponse]:
    services = request.app.state.services
    sessions = services.agent_session_store.list_sessions()
    return [_session_to_response(s) for s in sessions]


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(body: CreateSessionRequest, request: Request) -> SessionResponse:
    services = request.app.state.services
    acp_client = services.acp_client

    acp_client.ensure_ready()
    session_result = acp_client.new_session()
    claude_session_id: str = session_result["sessionId"]

    session = services.agent_session_store.create_session(
        title=body.title,
        claude_session_id=claude_session_id,
        transcript_path=session_result.get("transcript_path", ""),
        runtime_cwd=session_result.get("cwd", ""),
    )
    return _session_to_response(session)


@router.post(
    "/sessions/{session_id}/resume",
    response_model=ResumeSessionResponse,
)
def resume_session(session_id: str, request: Request) -> ResumeSessionResponse:
    services = request.app.state.services
    session = services.agent_session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        services.acp_client.ensure_ready()
        services.acp_client.resume_session(session.claude_session_id)
    except RuntimeError as exc:
        services.agent_session_store.mark_error(session_id, str(exc))
        return ResumeSessionResponse(
            session_id=session_id,
            status="recoverable_error",
            last_error=str(exc),
        )

    return ResumeSessionResponse(session_id=session_id, status="resumed")


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, request: Request) -> None:
    services = request.app.state.services
    deleted = services.agent_session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
)
def send_message(
    session_id: str,
    body: SendMessageRequest,
    request: Request,
) -> SendMessageResponse:
    services = request.app.state.services
    session = services.agent_session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        services.acp_client.ensure_ready()
        services.acp_client.resume_session(session.claude_session_id)
    except RuntimeError as exc:
        services.agent_session_store.mark_error(session_id, str(exc))
        return SendMessageResponse(
            session_id=session_id,
            status="recoverable_error",
        )

    try:
        result = services.acp_client.send_message(
            session.claude_session_id, body.message
        )
    except RuntimeError as exc:
        services.agent_session_store.mark_error(session_id, str(exc))
        return SendMessageResponse(
            session_id=session_id,
            status="recoverable_error",
        )

    return SendMessageResponse(
        session_id=session_id,
        status="sent",
        message=result.get("message"),
    )
