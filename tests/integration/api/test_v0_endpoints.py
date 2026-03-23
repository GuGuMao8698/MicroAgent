from __future__ import annotations

from pathlib import Path

from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER


def test_health_endpoint(client) -> None:
    response = client.get("/api/v0/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_txt_then_query_returns_answer_and_contexts(
    client,
    fixture_documents_dir: Path,
) -> None:
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
    assert payload["answer"].startswith("根据已索引文档，")
    assert payload["contexts"]
    assert any(
        "txt" in context["text"] or "md" in context["text"]
        for context in payload["contexts"]
    )


def test_upload_markdown_then_query_uses_markdown_text(
    client,
    fixture_documents_dir: Path,
) -> None:
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
    assert payload["contexts"]
    assert any(
        "Quick Start" in context["text"] or "uvicorn" in context["text"]
        for context in payload["contexts"]
    )


def test_query_with_empty_index_returns_fallback_answer(client) -> None:
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

    class FailingEmbedder:
        def __init__(self, wrapped_embedder) -> None:
            self.wrapped_embedder = wrapped_embedder

        def embed_chunks(self, chunks):
            raise RuntimeError("boom")

        def embed_query(self, query: str):
            return self.wrapped_embedder.embed_query(query)

    services = client.app.state.services
    original_embedder = services.ingestion_pipeline.embedder
    services.ingestion_pipeline.embedder = FailingEmbedder(original_embedder)

    failed_response = client.post(
        "/api/v0/documents",
        files={"file": ("broken.txt", b"this should fail after save", "text/plain")},
    )

    services.ingestion_pipeline.embedder = original_embedder

    assert failed_response.status_code == 500
    assert failed_response.json()["detail"] == "Failed to index document."

    uploads = list(services.settings.uploads_dir.glob("*"))
    indexes = list(services.settings.local_index_dir.glob("*.json"))

    assert len(uploads) == 1
    assert uploads[0].name.startswith(first_document_id)
    assert len(indexes) == 1
    assert indexes[0].stem == first_document_id
