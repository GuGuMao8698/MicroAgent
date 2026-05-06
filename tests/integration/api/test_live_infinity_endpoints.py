from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

_CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}


pytestmark = pytest.mark.live_infinity


class FakeDeepSeekAnswerClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    def complete(self, instructions: str, input_text: str) -> str:
        return self.output_text


class FakeArkMultimodalEmbeddingsAPI:
    def create(self, **kwargs: Any) -> Any:
        text = kwargs["input"][0]["text"]
        dimensions = kwargs.get("dimensions")
        return type(
            "FakeResponse",
            (),
            {
                "data": type(
                    "FakeData",
                    (),
                    {"embedding": _vector_for_text(text, dimensions)},
                )()
            },
        )()


class FakeArkClient:
    def __init__(self) -> None:
        self.multimodal_embeddings = FakeArkMultimodalEmbeddingsAPI()


def _vector_for_text(text: str, dimensions: int | None) -> list[float]:
    size = dimensions or 8
    vector = [0.0] * size
    lowered = text.lower()

    if "txt" in lowered or "md" in lowered or "文件类型" in text or "支持" in text:
        vector[0] = 4.0
        vector[1] = 1.0

    if not any(vector):
        vector[-1] = 1.0

    return vector


def _install_fake_answerer_client(client: Any, output_text: str) -> None:
    client.app.state.services.query_service.answerer.client = FakeDeepSeekAnswerClient(
        output_text=output_text
    )


def _install_fake_ark_client(client: Any) -> None:
    services = client.app.state.services
    assert (
        services.ingestion_pipeline.embedder
        is services.retriever.chunk_auxiliary_retriever.embedder
    )
    services.ingestion_pipeline.embedder.client = FakeArkClient()


def _unique_key() -> str:
    return f"key-{uuid4().hex}"


def _upload_fixture_document(
    client: Any,
    fixture_documents_dir: Path,
    fixture_name: str,
) -> Any:
    suffix = Path(fixture_name).suffix
    return client.post(
        "/api/v0/documents",
        files={
            "file": (
                fixture_name,
                (fixture_documents_dir / fixture_name).read_bytes(),
                _CONTENT_TYPES[suffix],
            )
        },
        headers={"Idempotency-Key": _unique_key()},
    )


def _wait_for_document_terminal_state(
    client: Any,
    document_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/api/v0/documents/{document_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"indexed", "failed"}:
            return payload
        time.sleep(0.05)

    raise AssertionError(
        f"Document {document_id} did not reach terminal status. Last payload: {last_payload}"
    )


def test_real_infinity_handles_upload_and_query(
    client: Any,
    fixture_documents_dir: Path,
) -> None:
    vector_index = client.app.state.services.ingestion_pipeline.vector_index
    assert vector_index._client.__class__.__name__ != "FakeInfinityClient"

    _install_fake_ark_client(client)
    _install_fake_answerer_client(
        client,
        "项目支持 txt 和 md 文件格式<cite:1>。",
    )

    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt"
    )

    assert upload_response.status_code == 202
    final_payload = _wait_for_document_terminal_state(
        client, upload_response.json()["document_id"]
    )
    assert final_payload["status"] == "indexed"

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "项目支持 txt 和 md 文件格式[1]。"
    assert payload["contexts"]
    assert any(
        "txt" in context["text"] or "md" in context["text"]
        for context in payload["contexts"]
    )
