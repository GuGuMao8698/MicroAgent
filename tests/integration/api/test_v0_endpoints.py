from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ragflow_lite.app import create_app
from ragflow_lite.config import Settings
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER

API_LOGGER = "ragflow_lite.api.routes.v0.endpoints"
APP_LOGGER = "ragflow_lite.app"
OBSERVABILITY_LOGGER = "ragflow_lite.api.observability"
_CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}


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


def _upload_fixture_document(
    client,
    fixture_documents_dir: Path,
    fixture_name: str,
    *,
    upload_name: str | None = None,
    content_type: str | None = None,
):
    filename = upload_name or fixture_name
    suffix = Path(filename).suffix
    return client.post(
        "/api/v0/documents",
        files={
            "file": (
                filename,
                (fixture_documents_dir / fixture_name).read_bytes(),
                content_type or _CONTENT_TYPES[suffix],
            )
        },
    )


def _query_documents(client, query: str, top_k: int = 4):
    return client.post("/api/v0/queries", json={"query": query, "top_k": top_k})


def _openai_input(fake_openai_client: FakeOpenAIClient) -> str:
    return fake_openai_client.responses.calls[0]["input"]


def _event_records(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[logging.LogRecord]:
    return [record for record in caplog.records if getattr(record, "event", None) == event]


def _assert_pdf_context_page_metadata(contexts: list[dict[str, Any]]) -> None:
    assert all(
        "page_start" in context["metadata"] and "page_end" in context["metadata"]
        for context in contexts
    )
    assert all(
        "page_texts" not in context["metadata"]
        and "page_spans" not in context["metadata"]
        for context in contexts
    )


def _build_settings(tmp_path: Path, *, metrics_enabled: bool = False) -> Settings:
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        metrics_enabled=metrics_enabled,
    )
    settings.ensure_directories()
    return settings


def test_health_endpoint(client) -> None:
    response = client.get("/api/v0/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_response_includes_generated_trace_id(client) -> None:
    response = client.get("/api/v0/health")

    assert response.status_code == 200
    assert re.fullmatch(r"\d+", response.headers["X-Trace-Id"])


def test_upload_txt_then_query_returns_answer_and_contexts(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="项目支持 txt 和 md 文件格式<cite:1>。"),
    )
    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "indexed"
    assert upload_payload["file_type"] == "txt"
    assert upload_payload["chunk_count"] >= 1

    query_response = _query_documents(client, "这个项目支持什么文件类型")

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
    openai_input = _openai_input(fake_openai_client)
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
    response = _upload_fixture_document(client, fixture_documents_dir, "sample.md")

    assert response.status_code == 200

    query_response = _query_documents(client, "如何运行这个最小 RAG")

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "使用 uvicorn 运行这个最小 RAG。"
    assert payload["contexts"]
    assert any(
        "Quick Start" in context["text"] or "uvicorn" in context["text"]
        for context in payload["contexts"]
    )
    openai_input = _openai_input(fake_openai_client)
    assert "Quick Start" in openai_input
    assert "uvicorn ragflow_lite.app:app --reload" in openai_input
    assert "ragflowlite.app" not in openai_input


def test_query_with_empty_index_returns_fallback_answer(client) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    response = _query_documents(client, "没有文档时怎么办")

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
    first_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")
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

    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")

    assert upload_response.status_code == 200

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 500
    assert query_response.json()["detail"] == "Failed to answer query."


def test_query_returns_500_when_ark_query_embedding_fails(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")
    assert upload_response.status_code == 200

    _install_fake_ark_client(client, FakeArkClient(error=RuntimeError("boom")))

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 500
    assert query_response.json()["detail"] == "Failed to answer query."


def test_query_returns_error_when_infinity_unreachable(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")
    assert upload_response.status_code == 200

    # 通过清空内部表数据来模拟 Infinity 当前查不到任何记录。
    services = client.app.state.services
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    chunk_table.rows.clear()

    query_response = _query_documents(client, "这个项目支持什么文件类型")

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
    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.pdf")

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "indexed"
    assert upload_payload["file_type"] == "pdf"
    assert upload_payload["chunk_count"] >= 1

    query_response = _query_documents(client, "PDF test")

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
    _assert_pdf_context_page_metadata(payload["contexts"])
    openai_input = _openai_input(fake_openai_client)
    assert "page:" in openai_input


def test_query_returns_500_when_embedding_signature_mismatch(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(
        client, FakeOpenAIClient(output_text="should not reach")
    )

    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")
    assert upload_response.status_code == 200

    # 篡改已存 chunk 的 embedding 签名，模拟陈旧数据。
    services = client.app.state.services
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    for row in chunk_table.rows:
        row["embedding_model"] = "stale-model"

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 500
    assert "Embedding signature mismatch" in query_response.json()["detail"]


def test_upload_empty_pdf_returns_422(client, fixture_documents_dir: Path) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    response = _upload_fixture_document(client, fixture_documents_dir, "empty.pdf")

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
    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")
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
    # txt 上传 metadata 仅包含 parser_strategy
    assert doc["metadata"] == {"parser_strategy": "plain_text"}


def test_get_document_after_txt_upload(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")
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
    upload_response = _upload_fixture_document(client, fixture_documents_dir, "sample.pdf")
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
        resp = _upload_fixture_document(client, fixture_documents_dir, fname)
        assert resp.status_code == 200
        ids.append(resp.json()["document_id"])

    response = client.get("/api/v0/documents")
    assert response.status_code == 200
    docs = response.json()["documents"]
    assert len(docs) == 2
    # 第二个上传的在前面（倒序）
    assert docs[0]["document_id"] == ids[1]
    assert docs[1]["document_id"] == ids[0]


def test_filename_sparse_recalls_when_text_misses(
    client,
    fixture_documents_dir: Path,
) -> None:
    """上传文件名含 "manual" 的 md 文件，查询 "manual" 时通过 filename sparse 字段召回。"""
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="Found via filename."),
    )
    upload_response = _upload_fixture_document(
        client,
        fixture_documents_dir,
        "sample.md",
        upload_name="ragflow-manual.md",
    )
    assert upload_response.status_code == 200

    # "manual" 不在 sample.md 的正文中，但 filename 包含 "manual"。
    query_response = _query_documents(client, "manual")

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "Found via filename."
    assert payload["contexts"]
    assert any(
        ctx["metadata"]["filename"] == "ragflow-manual.md"
        for ctx in payload["contexts"]
    )


def test_upload_two_page_pdf_then_query_returns_page_range(
    client,
    fixture_documents_dir: Path,
) -> None:
    """上传 2-page PDF 后查询，返回的 context 应包含正确的 page_start / page_end。"""
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="Found alpha and beta."),
    )
    upload_response = _upload_fixture_document(client, fixture_documents_dir, "two_pages.pdf")

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "indexed"
    assert upload_payload["file_type"] == "pdf"

    query_response = _query_documents(client, "alpha beta")

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "Found alpha and beta."
    assert payload["contexts"]
    _assert_pdf_context_page_metadata(payload["contexts"])
    openai_input = _openai_input(fake_openai_client)
    assert "pages: 1-2" in openai_input


# ---------------------------------------------------------------------------
# 结构化日志断言
# ---------------------------------------------------------------------------


def test_ingest_success_produces_info_log(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /documents 成功时产生 document_ingested info 日志。"""
    _install_fake_ark_client(client, FakeArkClient())
    with caplog.at_level(logging.INFO, logger=API_LOGGER):
        response = _upload_fixture_document(client, fixture_documents_dir, "sample.txt")

    assert response.status_code == 200
    events = _event_records(caplog, "document_ingested")
    assert len(events) == 1
    assert events[0].method == "POST"
    assert events[0].path == "/api/v0/documents"
    assert events[0].chunk_count >= 1


def test_ingest_trace_id_is_propagated_and_logged(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    with caplog.at_level(logging.INFO, logger=API_LOGGER):
        response = client.post(
            "/api/v0/documents",
            headers={"X-Trace-Id": "trace-123"},
            files={
                "file": (
                    "sample.txt",
                    (fixture_documents_dir / "sample.txt").read_bytes(),
                    "text/plain",
                )
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "trace-123"
    event = _event_records(caplog, "document_ingested")[0]
    assert event.trace_id == "trace-123"
    assert event.request_id


def test_query_success_produces_info_log(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /queries 成功时产生 query_answered info 日志。"""
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(client, FakeOpenAIClient(output_text="回答"))
    _upload_fixture_document(client, fixture_documents_dir, "sample.txt")

    with caplog.at_level(logging.INFO, logger=API_LOGGER):
        response = _query_documents(client, "test query", top_k=3)

    assert response.status_code == 200
    events = _event_records(caplog, "query_answered")
    assert len(events) == 1
    assert events[0].top_k == 3
    assert events[0].context_count >= 0
    assert events[0].trace_id == response.headers["X-Trace-Id"]
    assert events[0].request_id


def test_domain_error_produces_warning_log(
    client, caplog: pytest.LogCaptureFixture
) -> None:
    """已知 domain error 映射 HTTP 时产生 request_error warning 日志。"""
    with caplog.at_level(logging.WARNING, logger=API_LOGGER):
        response = client.post(
            "/api/v0/documents",
            files={"file": ("sample.docx", b"PK\x03\x04", "application/octet-stream")},
        )

    assert response.status_code == 415
    events = _event_records(caplog, "request_error")
    assert len(events) == 1
    assert events[0].status_code == 415
    assert events[0].error_type == "UnsupportedFileTypeError"
    assert events[0].path == "/api/v0/documents"
    assert events[0].trace_id == response.headers["X-Trace-Id"]
    assert events[0].request_id


def test_error_response_body_unchanged(client) -> None:
    """现有 415/422/404/500 响应 body 格式不变。"""
    # 415
    resp = client.post(
        "/api/v0/documents",
        files={"file": ("bad.exe", b"x", "application/octet-stream")},
    )
    assert resp.status_code == 415
    assert set(resp.json().keys()) == {"detail"}

    # 404
    resp = client.get("/api/v0/documents/doc_nonexistent")
    assert resp.status_code == 404
    assert set(resp.json().keys()) == {"detail"}


def test_create_app_startup_failure_logs_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """create_app 因 provider 配置缺失时仍抛原异常，并留下启动失败日志。"""
    import sys

    from ragflow_lite.app import create_app
    from ragflow_lite.config import Settings

    app_module = sys.modules["ragflow_lite.app"]

    def _broken_build_services(settings: Settings) -> None:
        raise RuntimeError("provider config missing")

    monkeypatch.setattr(app_module, "build_services", _broken_build_services)

    with caplog.at_level(logging.ERROR, logger=APP_LOGGER):
        with pytest.raises(RuntimeError, match="provider config missing"):
            create_app(Settings.default())

    events = _event_records(caplog, "app_startup_failed")
    assert len(events) == 1


def test_metrics_route_disabled_returns_404(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path, metrics_enabled=False))

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 404


def test_metrics_route_enabled_exposes_prometheus_metrics(
    tmp_path: Path,
    fixture_documents_dir: Path,
) -> None:
    app = create_app(_build_settings(tmp_path, metrics_enabled=True))

    with TestClient(app) as metrics_client:
        _install_fake_ark_client(metrics_client, FakeArkClient())
        _install_fake_openai_client(metrics_client, FakeOpenAIClient(output_text="回答"))
        upload_response = _upload_fixture_document(
            metrics_client,
            fixture_documents_dir,
            "sample.txt",
        )
        assert upload_response.status_code == 200

        query_response = _query_documents(metrics_client, "test query")
        assert query_response.status_code == 200

        bad_response = metrics_client.post(
            "/api/v0/documents",
            files={"file": ("bad.exe", b"x", "application/octet-stream")},
        )
        assert bad_response.status_code == 415

        metrics_response = metrics_client.get("/metrics")

    assert metrics_response.status_code == 200
    body = metrics_response.text
    assert "ragflow_lite_http_requests_total" in body
    assert (
        'ragflow_lite_http_requests_total{method="POST",route="/api/v0/documents",status_code="200"}'
        in body
    )
    assert (
        'ragflow_lite_http_requests_total{method="POST",route="/api/v0/documents",status_code="415"}'
        in body
    )
    assert 'ragflow_lite_ingest_total{file_type="txt",outcome="succeeded"}' in body
    assert 'ragflow_lite_query_total{outcome="succeeded"}' in body
    assert 'route="/metrics"' not in body


def test_metrics_registry_remains_scoped_to_first_app_after_second_app_creation(
    tmp_path: Path,
    fixture_documents_dir: Path,
) -> None:
    first_app = create_app(_build_settings(tmp_path / "app_one", metrics_enabled=True))

    with TestClient(first_app) as first_client:
        _install_fake_ark_client(first_client, FakeArkClient())
        upload_response = _upload_fixture_document(
            first_client,
            fixture_documents_dir,
            "sample.txt",
        )
        assert upload_response.status_code == 200

        second_app = create_app(_build_settings(tmp_path / "app_two", metrics_enabled=False))
        with TestClient(second_app) as second_client:
            disabled_metrics_response = second_client.get("/metrics")

        first_metrics_response = first_client.get("/metrics")

    assert disabled_metrics_response.status_code == 404
    assert first_metrics_response.status_code == 200
    assert (
        'ragflow_lite_http_requests_total{method="POST",route="/api/v0/documents",status_code="200"}'
        in first_metrics_response.text
    )
    assert 'ragflow_lite_ingest_total{file_type="txt",outcome="succeeded"}' in first_metrics_response.text


def test_method_not_allowed_metrics_use_partial_route_label(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path, metrics_enabled=True))

    with TestClient(app) as test_client:
        response = test_client.put("/api/v0/health")
        metrics_response = test_client.get("/metrics")

    assert response.status_code == 405
    body = metrics_response.text
    assert (
        'ragflow_lite_http_requests_total{method="PUT",route="/api/v0/health",status_code="405"}'
        in body
    )
    assert 'route="unmatched",status_code="405"' not in body


def test_unhandled_exception_is_logged_and_counted(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(_build_settings(tmp_path, metrics_enabled=True))

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        with caplog.at_level(logging.ERROR, logger=OBSERVABILITY_LOGGER):
            response = test_client.get("/boom", headers={"X-Trace-Id": "trace-boom"})
        metrics_response = test_client.get("/metrics")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["X-Trace-Id"] == "trace-boom"

    events = _event_records(caplog, "request_unhandled_exception")
    assert len(events) == 1
    assert events[0].error_type == "RuntimeError"
    assert events[0].trace_id == "trace-boom"
    assert events[0].request_id

    body = metrics_response.text
    assert (
        'ragflow_lite_http_request_exceptions_total{exception_type="RuntimeError",method="GET",route="/boom"}'
        in body
    )
    assert (
        'ragflow_lite_http_requests_total{method="GET",route="/boom",status_code="500"}'
        in body
    )


def test_logs_do_not_include_raw_query_or_document_content(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(_build_settings(tmp_path, metrics_enabled=False))
    secret_query = "SECRET_QUERY_123"
    secret_document = "SECRET_DOC_CONTENT_123"

    with TestClient(app) as test_client:
        _install_fake_ark_client(test_client, FakeArkClient())
        _install_fake_openai_client(test_client, FakeOpenAIClient(output_text="回答"))

        with caplog.at_level(logging.INFO):
            upload_response = test_client.post(
                "/api/v0/documents",
                files={"file": ("secret.txt", secret_document.encode("utf-8"), "text/plain")},
            )
            query_response = _query_documents(test_client, secret_query)

    assert upload_response.status_code == 200
    assert query_response.status_code == 200

    relevant_events = {
        "document_ingested",
        "query_answered",
        "ingest_started",
        "ingest_succeeded",
        "query_started",
        "query_succeeded",
    }
    relevant_records = [
        record for record in caplog.records if getattr(record, "event", None) in relevant_events
    ]

    assert relevant_records
    for record in relevant_records:
        rendered = str(record.__dict__)
        assert secret_query not in rendered
        assert secret_document not in rendered
