from __future__ import annotations

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
    assert services.ingestion_pipeline.embedder is services.retriever.embedder
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
        FakeOpenAIClient(output_text="项目支持 txt 和 md 文件格式<cite:1>。"),
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
    assert payload["answer"] == "项目支持 txt 和 md 文件格式[1]。"
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
    assert all(
        context["metadata"]["file_type"] == "txt" for context in payload["contexts"]
    )
    assert len(fake_openai_client.responses.calls) == 1
    assert fake_openai_client.responses.calls[0]["model"] == "gpt-5.4-mini"

    # citation 编号契约：contexts[0] 对应 prompt 中 [1]
    openai_input = fake_openai_client.responses.calls[0]["input"]
    first_chunk_text = payload["contexts"][0]["text"]
    assert first_chunk_text in openai_input


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
    openai_input = fake_openai_client.responses.calls[0]["input"]
    assert "Quick Start" in openai_input
    assert "uvicorn ragflow_lite.app:app --reload" in openai_input
    assert "ragflowlite.app" not in openai_input


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
        files={"file": ("sample.docx", b"PK\x03\x04", "application/octet-stream")},
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

    # 第一份文档的原始文件仍应保留。
    uploads = list(services.settings.uploads_dir.glob("*"))
    assert len(uploads) == 1
    assert uploads[0].name.startswith(first_document_id)

    # Infinity 的 chunk 表里应只保留第一份文档的分块数据。
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    assert all(row["document_id"] == first_document_id for row in chunk_table.rows)


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


def test_query_returns_error_when_infinity_unreachable(
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

    # 通过清空内部表数据来模拟 Infinity 当前查不到任何记录。
    services = client.app.state.services
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    chunk_table.rows.clear()

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    # 当 Infinity 没有命中上下文时，查询应退化为兜底回答。
    assert query_response.status_code == 200
    assert query_response.json()["answer"] == FALLBACK_ANSWER


def test_upload_pdf_then_query_returns_answer_and_contexts(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="PDF content found."),
    )
    upload_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.pdf",
                (fixture_documents_dir / "sample.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "indexed"
    assert upload_payload["file_type"] == "pdf"
    assert upload_payload["chunk_count"] >= 1

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "PDF test", "top_k": 4},
    )

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "PDF content found."
    assert payload["contexts"]
    assert any(
        "Hello from PDF test page" in context["text"] for context in payload["contexts"]
    )
    assert all(
        context["metadata"]["file_type"] == "pdf" for context in payload["contexts"]
    )


def test_query_returns_500_when_embedding_signature_mismatch(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(
        client, FakeOpenAIClient(output_text="should not reach")
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

    # 篡改已存 chunk 的 embedding 签名，模拟陈旧数据。
    services = client.app.state.services
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    for row in chunk_table.rows:
        row["embedding_model"] = "stale-model"

    query_response = client.post(
        "/api/v0/queries",
        json={"query": "这个项目支持什么文件类型", "top_k": 4},
    )

    assert query_response.status_code == 500
    assert "Embedding signature mismatch" in query_response.json()["detail"]


def test_upload_empty_pdf_returns_422(client, fixture_documents_dir: Path) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "empty.pdf",
                (fixture_documents_dir / "empty.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()


def test_upload_encrypted_pdf_returns_422(client) -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret")
    buf = BytesIO()
    writer.write(buf)
    encrypted_bytes = buf.getvalue()

    _install_fake_ark_client(client, FakeArkClient())
    response = client.post(
        "/api/v0/documents",
        files={"file": ("encrypted.pdf", encrypted_bytes, "application/pdf")},
    )

    assert response.status_code == 422
    assert "parse" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 文档列表 / 详情读取接口
# ---------------------------------------------------------------------------


def test_list_documents_returns_empty_before_upload(client) -> None:
    response = client.get("/api/v0/documents")
    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_list_documents_after_txt_upload(
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

    response = client.get("/api/v0/documents")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["documents"]) == 1
    doc = payload["documents"][0]
    assert doc["document_id"] == document_id
    assert doc["filename"] == "sample.txt"
    assert doc["file_type"] == "txt"
    assert doc["size_bytes"] > 0
    assert doc["created_at"]
    # txt 上传不产生 parser extras，metadata 为空
    assert doc["metadata"] == {}


def test_get_document_after_txt_upload(
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

    response = client.get(f"/api/v0/documents/{document_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["document_id"] == document_id
    assert doc["filename"] == "sample.txt"
    assert doc["file_type"] == "txt"


def test_get_document_after_pdf_upload(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    upload_response = client.post(
        "/api/v0/documents",
        files={
            "file": (
                "sample.pdf",
                (fixture_documents_dir / "sample.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert upload_response.status_code == 200
    document_id = upload_response.json()["document_id"]

    response = client.get(f"/api/v0/documents/{document_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["file_type"] == "pdf"
    assert doc["metadata"]["format"] == "pdf"
    assert doc["metadata"]["page_count"] == 1


def test_get_nonexistent_document_returns_404(client) -> None:
    response = client.get("/api/v0/documents/doc_nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_document_with_single_quote_in_id_returns_404(client) -> None:
    """URL 中带单引号的 document_id 应返回 404，不应 500。"""
    response = client.get("/api/v0/documents/doc_%27bad")
    assert response.status_code == 404


def test_list_documents_multiple_uploads_ordered_by_created_at_desc(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    ids: list[str] = []
    for fname in ("sample.txt", "sample.md"):
        resp = client.post(
            "/api/v0/documents",
            files={
                "file": (
                    fname,
                    (fixture_documents_dir / fname).read_bytes(),
                    "text/plain",
                )
            },
        )
        assert resp.status_code == 200
        ids.append(resp.json()["document_id"])

    response = client.get("/api/v0/documents")
    assert response.status_code == 200
    docs = response.json()["documents"]
    assert len(docs) == 2
    # 第二个上传的在前面（倒序）
    assert docs[0]["document_id"] == ids[1]
    assert docs[1]["document_id"] == ids[0]
