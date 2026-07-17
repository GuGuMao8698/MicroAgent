from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services.query_mode_router import QueryModeRouter
from ragflow_lite.domain.models import AnswerResult, RetrievedChunk


def _result(answer: str) -> AnswerResult:
    return AnswerResult(
        answer=answer,
        contexts=[
            RetrievedChunk(
                chunk_id=f"{answer}_chunk",
                document_id="doc_alpha",
                text=f"{answer} text",
                score=1.0,
            )
        ],
        metadata={"answer": answer},
    )


@dataclass
class RecordingQueryPath:
    answer: str
    calls: list[tuple[str, int]] = field(default_factory=list)

    def query(self, query: str, top_k: int) -> AnswerResult:
        self.calls.append((query, top_k))
        return _result(self.answer)


def test_query_mode_router_defaults_to_standard() -> None:
    standard = RecordingQueryPath("standard")
    discorag = RecordingQueryPath("discorag")
    router = QueryModeRouter(standard_service=standard, discorag_service=discorag)

    result = router.query("q", top_k=4)

    assert result.answer == "standard"
    assert standard.calls == [("q", 4)]
    assert discorag.calls == []


def test_query_mode_router_dispatches_explicit_standard() -> None:
    standard = RecordingQueryPath("standard")
    discorag = RecordingQueryPath("discorag")
    router = QueryModeRouter(standard_service=standard, discorag_service=discorag)

    result = router.query("q", top_k=2, mode="standard")

    assert result.answer == "standard"
    assert standard.calls == [("q", 2)]
    assert discorag.calls == []


def test_query_mode_router_dispatches_discorag() -> None:
    standard = RecordingQueryPath("standard")
    discorag = RecordingQueryPath("discorag")
    router = QueryModeRouter(standard_service=standard, discorag_service=discorag)

    result = router.query("q", top_k=3, mode="discorag")

    assert result.answer == "discorag"
    assert standard.calls == []
    assert discorag.calls == [("q", 3)]


def test_query_mode_router_rejects_unknown_runtime_mode() -> None:
    router = QueryModeRouter(
        standard_service=RecordingQueryPath("standard"),
        discorag_service=RecordingQueryPath("discorag"),
    )

    with pytest.raises(ValueError, match="Unsupported query mode"):
        router.query("q", top_k=1, mode="rerank_only")


def test_query_mode_router_rejects_public_psi_mode() -> None:
    router = QueryModeRouter(
        standard_service=RecordingQueryPath("standard"),
        discorag_service=RecordingQueryPath("discorag"),
    )

    with pytest.raises(ValueError, match="Unsupported query mode"):
        router.query("q", top_k=1, mode="psi")
