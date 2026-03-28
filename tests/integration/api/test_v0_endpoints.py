from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER


class FakeResponsesAPI:
    def __init__(
        self,
        output_text: str = "默认回答",
        error: Exception | None = None,
    ) -> None:
        self.output_text = output_text
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return type("FakeResponse", (), {"output_text": self.output_text})()


class FakeOpenAIClient:
    def __init__(
        self,
        output_text: str = "默认回答",
        error: Exception | None = None,
    ) -> None:
        self.responses = FakeResponsesAPI(output_text=output_text, error=error)


class FakeArkMultimodalEmbeddingsAPI:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error

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
    def __init__(self, error: Exception | None = None) -> None:
        self.multimodal_embeddings = FakeArkMultimodalEmbeddingsAPI(error=error)


def _vector_for_text(text: str, dimensions: int | None) -> list[float]:
    size = dimensions or 8
    vector = [0.0] * size
    lowered = text.lower()

    if (
        "txt" in lowered
        or "md" in lowered
        or "文件类型" in text
        or "支持" in text
        or "导入" in text
    ):
        vector[0] = 4.0
        vector[1] = 1.0

    if (
        "uvicorn" in lowered
        or "quick start" in lowered
        or "运行" in text
        or "markdown" in lowered
    ):
        vector[2] = 4.0
        vector[3] = 1.0

    if not any(vector):
        vector[-1] = 1.0

    return vector


def _install_fake_openai_client(
    client,
    fake_openai_client: FakeOpenAIClient,
) -> FakeOpenAIClient:
    client.app.state.services.query_service.answerer.client = fake_openai_client
    return fake_openai_client


def _install_fake_ark_client(client, fake_ark_client: FakeArkClient) -> FakeArkClient:
    services = client.app.state.services
    assert services.ingestion_pipeline.embedder is services.query_service.embedder
    services.ingestion_pipeline.embedder.client = fake_ark_client
    return fake_ark_client


def test_health_endpoint(client) -> None:
    response = client.get("/api/v0/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_txt_then_query_returns_answer_and_contexts(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="支持 txt 和 md。"),
    )
    upload_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.txt",
                (fixture_documents_dir / "sample.txt").read_bytes(),
                "text/plain",
            )
        },
    )

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "indexed"
    assert upload_payload["file_type"] == "txt"
    assert upload_payload["chunk_count"] >= 1

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "支持 txt 和 md。"
    assert payload["contexts"]
    assert payload["metadata"] == {
        "strategy": "openai_responses",
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "store": False,
    }
    assert any(
        "txt" in context["text"] or "md" in context["text"]
        for context in payload["contexts"]
    )
    assert len(fake_openai_client.responses.calls) == 1
    assert fake_openai_client.responses.calls[0]["model"] == "gpt-5.4-mini"


def test_upload_markdown_then_query_uses_markdown_text(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="使用 uvicorn 运行这个最小 RAG。"),
    )
    response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.md",
                (fixture_documents_dir / "sample.md").read_bytes(),
                "text/markdown",
            )
        },
    )

    assert response.status_code == 200

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "如何运行这个最小 RAG", "top_k": 4},
    )

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "使用 uvicorn 运行这个最小 RAG。"
    assert payload["contexts"]
    assert any(
        "Quick Start" in context["text"] or "uvicorn" in context["text"]
        for context in payload["contexts"]
    )
    assert "Quick Start" in fake_openai_client.responses.calls[0]["input"]


def test_query_with_empty_index_returns_fallback_answer(client) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    response = client.post(
        "/api/v0/queries", json={"query": "没有文档时怎么办", "top_k": 4}
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": FALLBACK_ANSWER,
        "contexts": [],
        "metadata": {"strategy": "fallback"},
    }


def test_uploading_unsupported_file_type_returns_415(client) -> None:
    response = client.post(
        "/api/v0/documents",
        files={"file": ("sample.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


def test_ingestion_failure_rolls_back_only_current_document(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    first_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.txt",
                (fixture_documents_dir / "sample.txt").read_bytes(),
                "text/plain",
            )
        },
    )
    assert first_response.status_code == 200
    first_document_id = first_response.json()["document_id"]

    services = client.app.state.services
    _install_fake_ark_client(client, FakeArkClient(error=RuntimeError("boom")))

    failed_response = client.post(
        "/api/v0/documents",
        files={"file": ("broken.txt", b"this should fail after save", "text/plain")},
    )

    assert failed_response.status_code == 500
    assert failed_response.json()["detail"] == "Failed to index document."

    uploads = list(services.settings.uploads_dir.glob("*"))
    indexes = list(services.settings.local_index_dir.glob("*.json"))

    assert len(uploads) == 1
    assert uploads[0].name.startswith(first_document_id)
    assert len(indexes) == 1
    assert indexes[0].stem == first_document_id


def test_query_returns_500_when_openai_request_fails(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(client, FakeOpenAIClient(error=RuntimeError("boom")))

    upload_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.txt",
                (fixture_documents_dir / "sample.txt").read_bytes(),
                "text/plain",
            )
        },
    )

    assert upload_response.status_code == 200

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    assert query_response.status_code == 500
    assert query_response.json()["detail"] == "Failed to answer query."


def test_query_returns_500_when_ark_query_embedding_fails(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    upload_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.txt",
                (fixture_documents_dir / "sample.txt").read_bytes(),
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 200

    _install_fake_ark_client(client, FakeArkClient(error=RuntimeError("boom")))

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    assert query_response.status_code == 500
    assert query_response.json()["detail"] == "Failed to answer query."


def test_query_returns_reindex_error_when_index_signature_is_missing(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    upload_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.txt",
                (fixture_documents_dir / "sample.txt").read_bytes(),
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 200

    document_id = upload_response.json()["document_id"]
    services = client.app.state.services
    index_path = services.settings.local_index_dir / f"{document_id}.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload.pop("embedding_signature")
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    assert query_response.status_code == 500
    assert "missing embedding signature metadata" in query_response.json()["detail"]
