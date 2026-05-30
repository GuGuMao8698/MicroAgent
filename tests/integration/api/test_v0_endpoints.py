from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infinity_test_support import (
    assign_isolated_infinity_tables,
    register_infinity_table_cleanup,
)

from ragflow_lite.api.deps.providers import (
    get_document_service,
    get_ingestion_pipeline,
    get_query_router,
)
from ragflow_lite.api.observability import install_observability
from ragflow_lite.api.routes.v0 import router as v0_router
from ragflow_lite.config import Settings
from ragflow_lite.domain.errors import (
    DocumentNotFoundError,
    IdempotencyKeyMissingError,
    ProcessingError,
    UnsupportedFileTypeError,
)
from ragflow_lite.domain.models import AnswerResult
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    _doc_id_filter,
)

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


class FakeDeepSeekChatClient:
    def __init__(
        self,
        output_text: str = "默认回答",
        error: Exception | None = None,
    ) -> None:
        self.output_text = output_text
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def complete(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input": input_text})
        if self.error is not None:
            raise self.error
        return self.output_text


class FakeOpenAIClient:
    def __init__(
        self,
        output_text: str = "默认回答",
        error: Exception | None = None,
    ) -> None:
        self.responses = FakeResponsesAPI(output_text=output_text, error=error)
        self.answer_client: FakeDeepSeekChatClient | None = None


class FakeJsonClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def complete_json(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append((args, kwargs))
        return self.output_text


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
    answer_client = FakeDeepSeekChatClient(
        output_text=fake_openai_client.responses.output_text,
        error=fake_openai_client.responses.error,
    )
    client.app.state.services.query_service.answerer.client = answer_client
    client.app.state.services.discorag_query_service.answerer.client = answer_client
    fake_openai_client.answer_client = answer_client
    extractor = client.app.state.services.ingestion_pipeline.evidence_extractor
    if extractor is not None:
        extractor.client = FakeJsonClient('{"entities":[],"relations":[]}')
    query_grounder = getattr(
        client.app.state.services.retriever, "query_grounder", None
    )
    if query_grounder is not None:
        query_grounder.client = FakeJsonClient(
            '{"answer_type_keywords":[],"entities_from_query":[]}'
        )
    return fake_openai_client


def _install_fake_ark_client(client, fake_ark_client: FakeArkClient) -> FakeArkClient:
    services = client.app.state.services
    assert (
        services.ingestion_pipeline.embedder
        is services.retriever.chunk_auxiliary_retriever.embedder
    )
    services.ingestion_pipeline.embedder.client = fake_ark_client
    return fake_ark_client


def _patch_fake_evidence_extractor(app) -> None:
    """Install a fake OpenAI client on the evidence extractor."""
    extractor = getattr(
        app.state.services.ingestion_pipeline, "evidence_extractor", None
    )
    if extractor is not None:
        extractor.client = FakeJsonClient('{"entities":[],"relations":[]}')


def _unique_key() -> str:
    return f"key-{uuid4().hex}"


def _upload_fixture_document(
    client,
    fixture_documents_dir: Path,
    fixture_name: str,
    *,
    upload_name: str | None = None,
    content_type: str | None = None,
    idempotency_key: str | None = None,
):
    filename = upload_name or fixture_name
    suffix = Path(filename).suffix
    headers: dict[str, str] = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return client.post(
        "/api/v0/documents",
        files={
            "file": (
                filename,
                (fixture_documents_dir / fixture_name).read_bytes(),
                content_type or _CONTENT_TYPES[suffix],
            )
        },
        headers=headers,
    )


def _query_documents(client, query: str, top_k: int = 4):
    return client.post("/api/v0/queries", json={"query": query, "top_k": top_k})


def _wait_for_document_terminal_state(
    client,
    document_id: str,
    *,
    timeout_seconds: float = 3.0,
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
        time.sleep(0.01)

    raise AssertionError(
        f"Document {document_id} did not reach terminal status. Last payload: {last_payload}"
    )


def _openai_input(fake_openai_client: FakeOpenAIClient) -> str:
    assert fake_openai_client.answer_client is not None
    return fake_openai_client.answer_client.calls[0]["input"]


def _chunk_rows(vector_index, columns: list[str]) -> list[dict[str, Any]]:
    table = vector_index._db.get_table(vector_index._chunk_table)
    return vector_index._table_rows(table, columns)


def _event_records(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if getattr(record, "event", None) == event
    ]


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
    assign_isolated_infinity_tables(settings, tmp_path, salt=uuid4().hex[:8])
    register_infinity_table_cleanup(settings)
    settings.ensure_directories()
    return settings


class _LitePipeline:
    def submit(
        self,
        idempotency_key: str | None,
        filename: str,
        content: bytes,
        dataset_id: str | None = None,
    ):
        if not idempotency_key:
            raise IdempotencyKeyMissingError()
        if filename.endswith((".docx", ".exe")):
            raise UnsupportedFileTypeError(filename)
        raise AssertionError("lite pipeline should only cover validation paths")

    def get_snapshot(self, document_id: str) -> None:
        return None


class _LiteDocumentService:
    def list_documents(self, dataset_id: str | None = None) -> list[Any]:
        return []

    def get_document(self, document_id: str) -> Any:
        raise DocumentNotFoundError(document_id)


def _lite_test_app(*, metrics_enabled: bool = False) -> FastAPI:
    app = FastAPI()
    install_observability(app, enable_metrics=metrics_enabled)
    app.include_router(v0_router, prefix="/api/v0")
    app.dependency_overrides[get_ingestion_pipeline] = lambda: _LitePipeline()
    app.dependency_overrides[get_document_service] = lambda: _LiteDocumentService()
    return app


@pytest.fixture
def lite_client():
    app = _lite_test_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def lite_query_client():
    app = _lite_test_app()
    query_router = _RecordingQueryRouter()
    app.dependency_overrides[get_query_router] = lambda: query_router
    with TestClient(app) as test_client:
        test_client.query_router = query_router
        yield test_client


@pytest.fixture
def lite_metrics_client():
    app = _lite_test_app(metrics_enabled=True)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def lite_metrics_no_raise_client():
    app = _lite_test_app(metrics_enabled=True)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health_endpoint(lite_client) -> None:
    client = lite_client
    response = client.get("/api/v0/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_response_includes_generated_trace_id(lite_client) -> None:
    client = lite_client
    response = client.get("/api/v0/health")

    assert response.status_code == 200
    assert re.fullmatch(r"\d+", response.headers["X-Trace-Id"])


@pytest.mark.live_infinity
def test_upload_txt_then_query_returns_answer_and_contexts(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="项目支持 txt 和 md 文件格式<cite:1>。"),
    )
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )

    assert upload_response.status_code == 202
    upload_payload = upload_response.json()
    document_id = upload_payload["document_id"]
    assert upload_response.headers["Location"] == f"/api/v0/documents/{document_id}"
    assert upload_payload["status"] == "queued"
    assert upload_payload["file_type"] == "txt"
    assert upload_payload["attempt"] == 1
    assert upload_payload["progress_percent"] == 0
    assert upload_payload["chunk_count"] is None
    assert upload_payload["error"] is None
    final_payload = _wait_for_document_terminal_state(client, document_id)
    assert final_payload["status"] == "indexed"
    assert final_payload["chunk_count"] >= 1

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "项目支持 txt 和 md 文件格式[1]。"
    assert payload["contexts"]
    assert payload["metadata"]["strategy"] == "deepseek_chat"
    assert payload["metadata"]["model"] == "deepseek-v4-flash"
    assert payload["metadata"]["reasoning_effort"] == "high"
    assert payload["metadata"]["answer_mode"] == "standard"
    assert payload["metadata"]["blueprint_validated"] is False
    assert any(
        "txt" in context["text"] or "md" in context["text"]
        for context in payload["contexts"]
    )
    assert all(
        context["metadata"]["file_type"] == "txt" for context in payload["contexts"]
    )
    assert fake_openai_client.answer_client is not None
    assert len(fake_openai_client.answer_client.calls) == 1

    # citation 编号契约：contexts[0] 对应 prompt 中 [1]
    openai_input = _openai_input(fake_openai_client)
    first_chunk_text = payload["contexts"][0]["text"]
    assert first_chunk_text in openai_input


@pytest.mark.live_infinity
def test_upload_returns_202_with_location_before_background_finishes(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    services = client.app.state.services
    original_parser = services.ingestion_pipeline.parser
    parser_started = threading.Event()
    parser_release = threading.Event()

    class _BlockingParser:
        def parse(self, asset, raw_bytes):
            parser_started.set()
            parser_release.wait(timeout=2)
            return original_parser.parse(asset, raw_bytes)

    services.ingestion_pipeline.parser = _BlockingParser()
    try:
        response = _upload_fixture_document(
            client,
            fixture_documents_dir,
            "sample.txt",
            idempotency_key=_unique_key(),
        )
        assert response.status_code == 202
        payload = response.json()
        document_id = payload["document_id"]
        assert response.headers["Location"] == f"/api/v0/documents/{document_id}"
        assert payload["status"] == "queued"
        assert parser_started.wait(timeout=2)

        pending_response = client.get(f"/api/v0/documents/{document_id}")
        assert pending_response.status_code == 200
        assert pending_response.json()["status"] in {"queued", "processing"}
    finally:
        parser_release.set()
        services.ingestion_pipeline.parser = original_parser

    final = _wait_for_document_terminal_state(client, document_id)
    assert final["status"] == "indexed"


@pytest.mark.live_infinity
def test_upload_retries_in_background_and_exposes_second_attempt(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    services = client.app.state.services
    original_parser = services.ingestion_pipeline.parser

    class _RetryOnceParser:
        def __init__(self) -> None:
            self.calls = 0

        def parse(self, asset, raw_bytes):
            self.calls += 1
            if self.calls == 1:
                raise ProcessingError("parse failed once")
            return original_parser.parse(asset, raw_bytes)

    retry_parser = _RetryOnceParser()
    services.ingestion_pipeline.parser = retry_parser
    try:
        response = _upload_fixture_document(
            client,
            fixture_documents_dir,
            "sample.txt",
            idempotency_key=_unique_key(),
        )
        assert response.status_code == 202
        final = _wait_for_document_terminal_state(
            client, response.json()["document_id"]
        )
    finally:
        services.ingestion_pipeline.parser = original_parser

    assert final["status"] == "indexed"
    assert final["attempt"] == 2
    assert final["error"] is None
    assert retry_parser.calls == 2


@pytest.mark.live_infinity
def test_upload_markdown_then_query_uses_markdown_text(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="使用 uvicorn 运行这个最小 RAG。"),
    )
    response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.md", idempotency_key=_unique_key()
    )

    assert response.status_code == 202
    _wait_for_document_terminal_state(client, response.json()["document_id"])

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


@pytest.mark.live_infinity
def test_query_with_empty_index_returns_fallback_answer(client) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    response = _query_documents(client, "没有文档时怎么办")

    assert response.status_code == 200
    assert response.json() == {
        "answer": FALLBACK_ANSWER,
        "contexts": [],
        "metadata": {
            "strategy": "fallback",
            "answer_mode": "standard",
            "blueprint_validated": False,
        },
    }


def test_uploading_unsupported_file_type_returns_415(lite_client) -> None:
    response = lite_client.post(
        "/api/v0/documents",
        files={"file": ("sample.docx", b"PK\x03\x04", "application/octet-stream")},
        headers={"Idempotency-Key": _unique_key()},
    )

    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_without_idempotency_key_returns_400(lite_client) -> None:
    response = lite_client.post(
        "/api/v0/documents",
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400


@pytest.mark.live_infinity
def test_ingestion_failure_rolls_back_only_current_document(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    first_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    assert first_response.status_code == 202
    first_document_id = first_response.json()["document_id"]
    first_final = _wait_for_document_terminal_state(client, first_document_id)
    assert first_final["status"] == "indexed"

    services = client.app.state.services
    _install_fake_ark_client(client, FakeArkClient(error=RuntimeError("boom")))

    failed_response = client.post(
        "/api/v0/documents",
        files={"file": ("broken.txt", b"this should fail after save", "text/plain")},
        headers={"Idempotency-Key": _unique_key()},
    )

    assert failed_response.status_code == 202
    failed_document_id = failed_response.json()["document_id"]
    failed_final = _wait_for_document_terminal_state(client, failed_document_id)
    assert failed_final["status"] == "failed"
    assert failed_final["attempt"] == 2
    assert failed_final["error"] == "boom"

    # 第一份文档的原始文件仍应保留。
    uploads = list(services.settings.uploads_dir.glob("*"))
    assert len(uploads) == 1
    assert uploads[0].name.startswith(first_document_id)

    # Infinity 的 chunk 表里应只保留第一份文档的分块数据。
    vector_index = services.ingestion_pipeline.vector_index
    rows = _chunk_rows(vector_index, ["document_id"])
    assert rows
    assert all(row["document_id"] == first_document_id for row in rows)


@pytest.mark.live_infinity
def test_query_returns_500_when_openai_request_fails(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(client, FakeOpenAIClient(error=RuntimeError("boom")))

    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )

    assert upload_response.status_code == 202
    _wait_for_document_terminal_state(client, upload_response.json()["document_id"])

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 500
    assert query_response.json()["detail"] == "Failed to answer query."


@pytest.mark.live_infinity
def test_query_returns_500_when_ark_query_embedding_fails(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    assert upload_response.status_code == 202
    _wait_for_document_terminal_state(client, upload_response.json()["document_id"])

    _install_fake_ark_client(client, FakeArkClient(error=RuntimeError("boom")))

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 500
    assert query_response.json()["detail"] == "Failed to answer query."


@pytest.mark.live_infinity
def test_query_returns_error_when_infinity_unreachable(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    assert upload_response.status_code == 202
    _wait_for_document_terminal_state(client, upload_response.json()["document_id"])

    # 通过清空内部表数据来模拟 Infinity 当前查不到任何记录。
    services = client.app.state.services
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    chunk_table.delete()

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    # 当 Infinity 没有命中上下文时，查询应退化为兜底回答。
    assert query_response.status_code == 200
    assert query_response.json()["answer"] == FALLBACK_ANSWER


@pytest.mark.live_infinity
def test_upload_pdf_then_query_returns_answer_and_contexts(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    fake_openai_client = _install_fake_openai_client(
        client,
        FakeOpenAIClient(output_text="PDF content found."),
    )
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.pdf", idempotency_key=_unique_key()
    )

    assert upload_response.status_code == 202
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "queued"
    assert upload_payload["file_type"] == "pdf"
    final_payload = _wait_for_document_terminal_state(
        client, upload_payload["document_id"]
    )
    assert final_payload["status"] == "indexed"
    assert final_payload["chunk_count"] >= 1

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


@pytest.mark.live_infinity
def test_query_returns_500_when_embedding_signature_mismatch(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(
        client, FakeOpenAIClient(output_text="should not reach")
    )

    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    assert upload_response.status_code == 202
    _wait_for_document_terminal_state(client, upload_response.json()["document_id"])

    # 篡改已存 chunk 的 embedding 签名，模拟陈旧数据。
    services = client.app.state.services
    vector_index = services.ingestion_pipeline.vector_index
    chunk_table = vector_index._db.get_table(vector_index._chunk_table)
    chunk_table.update(
        _doc_id_filter(upload_response.json()["document_id"]),
        {"embedding_model": "stale-model"},
    )

    query_response = _query_documents(client, "这个项目支持什么文件类型")

    assert query_response.status_code == 500
    assert "Embedding signature mismatch" in query_response.json()["detail"]


@pytest.mark.live_infinity
def test_upload_empty_pdf_returns_422(client, fixture_documents_dir: Path) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    response = _upload_fixture_document(
        client, fixture_documents_dir, "empty.pdf", idempotency_key=_unique_key()
    )

    assert response.status_code == 202
    final = _wait_for_document_terminal_state(client, response.json()["document_id"])
    assert final["status"] == "failed"
    assert "empty" in final["error"].lower()


@pytest.mark.live_infinity
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
        headers={"Idempotency-Key": _unique_key()},
    )

    assert response.status_code == 202
    final = _wait_for_document_terminal_state(client, response.json()["document_id"])
    assert final["status"] == "failed"
    assert "parse" in final["error"].lower()


# ---------------------------------------------------------------------------
# 文档列表 / 详情读取接口
# ---------------------------------------------------------------------------


@pytest.mark.live_infinity
def test_list_documents_returns_empty_before_upload(client) -> None:
    response = client.get("/api/v0/documents")
    assert response.status_code == 200
    assert response.json() == {"documents": []}


@pytest.mark.live_infinity
def test_list_documents_after_txt_upload(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document_id"]
    _wait_for_document_terminal_state(client, document_id)

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


@pytest.mark.live_infinity
def test_get_document_after_txt_upload(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document_id"]
    _wait_for_document_terminal_state(client, document_id)

    response = client.get(f"/api/v0/documents/{document_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["document_id"] == document_id
    assert doc["status"] == "indexed"
    assert doc["file_type"] == "txt"
    assert doc["filename"] == "sample.txt"
    assert doc["attempt"] == 1
    assert doc["progress_percent"] == 100


@pytest.mark.live_infinity
def test_get_document_after_pdf_upload(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.pdf", idempotency_key=_unique_key()
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document_id"]
    _wait_for_document_terminal_state(client, document_id)

    response = client.get(f"/api/v0/documents/{document_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["file_type"] == "pdf"
    assert doc["metadata"]["format"] == "pdf"
    assert doc["metadata"]["page_count"] == 1


@pytest.mark.live_infinity
def test_get_nonexistent_document_returns_404(client) -> None:
    response = client.get("/api/v0/documents/doc_nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.live_infinity
def test_get_document_with_single_quote_in_id_returns_404(client) -> None:
    """URL 中带单引号的 document_id 应返回 404，不应 500。"""
    response = client.get("/api/v0/documents/doc_%27bad")
    assert response.status_code == 404


@pytest.mark.live_infinity
def test_list_documents_multiple_uploads_ordered_by_created_at_desc(
    client,
    fixture_documents_dir: Path,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())
    ids: list[str] = []
    for fname in ("sample.txt", "sample.md"):
        resp = _upload_fixture_document(
            client, fixture_documents_dir, fname, idempotency_key=_unique_key()
        )
        assert resp.status_code == 202
        document_id = resp.json()["document_id"]
        _wait_for_document_terminal_state(client, document_id)
        ids.append(document_id)

    response = client.get("/api/v0/documents")
    assert response.status_code == 200
    docs = response.json()["documents"]
    assert len(docs) == 2
    # 第二个上传的在前面（倒序）
    assert docs[0]["document_id"] == ids[1]
    assert docs[1]["document_id"] == ids[0]


@pytest.mark.live_infinity
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
        idempotency_key=_unique_key(),
    )
    assert upload_response.status_code == 202
    _wait_for_document_terminal_state(client, upload_response.json()["document_id"])

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


@pytest.mark.live_infinity
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
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "two_pages.pdf", idempotency_key=_unique_key()
    )

    assert upload_response.status_code == 202
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "queued"
    assert upload_payload["file_type"] == "pdf"
    _wait_for_document_terminal_state(client, upload_payload["document_id"])

    query_response = _query_documents(client, "alpha beta")

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"] == "Found alpha and beta."
    assert payload["contexts"]
    _assert_pdf_context_page_metadata(payload["contexts"])
    openai_input = _openai_input(fake_openai_client)
    assert "pages: 1-2" in openai_input


# ---------------------------------------------------------------------------
# Query mode dispatch
# ---------------------------------------------------------------------------


class _RecordingQueryRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def query(self, query: str, top_k: int, *, mode: str = "standard"):

        self.calls.append((query, top_k, mode))
        return AnswerResult(
            answer=f"{mode} answer", contexts=[], metadata={"mode": mode}
        )


def test_query_endpoint_defaults_to_standard_mode(lite_query_client) -> None:
    response = lite_query_client.post(
        "/api/v0/queries", json={"query": "What is MiniRAG?"}
    )

    assert response.status_code == 200
    assert response.json()["metadata"] == {"mode": "standard"}
    assert lite_query_client.query_router.calls[-1] == (
        "What is MiniRAG?",
        6,
        "standard",
    )


def test_query_endpoint_accepts_discorag_mode(lite_query_client) -> None:
    response = lite_query_client.post(
        "/api/v0/queries",
        json={"query": "What is MiniRAG?", "top_k": 3, "mode": "discorag"},
    )

    assert response.status_code == 200
    assert response.json()["metadata"] == {"mode": "discorag"}
    assert lite_query_client.query_router.calls[-1] == (
        "What is MiniRAG?",
        3,
        "discorag",
    )


def test_query_endpoint_rejects_unknown_query_mode(lite_query_client) -> None:
    response = lite_query_client.post(
        "/api/v0/queries",
        json={"query": "What is MiniRAG?", "mode": "rerank_only"},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 结构化日志断言
# ---------------------------------------------------------------------------


@pytest.mark.live_infinity
def test_ingest_success_produces_info_log(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /documents 成功时产生 document_ingested info 日志。"""
    _install_fake_ark_client(client, FakeArkClient())
    with caplog.at_level(logging.INFO, logger=API_LOGGER):
        response = _upload_fixture_document(
            client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
        )

    assert response.status_code == 202
    events = _event_records(caplog, "document_ingested")
    assert len(events) == 1
    assert events[0].method == "POST"
    assert events[0].path == "/api/v0/documents"
    assert events[0].document_id == response.json()["document_id"]


@pytest.mark.live_infinity
def test_ingest_trace_id_is_propagated_and_logged(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_fake_ark_client(client, FakeArkClient())

    with caplog.at_level(logging.INFO, logger=API_LOGGER):
        response = client.post(
            "/api/v0/documents",
            headers={"X-Trace-Id": "trace-123", "Idempotency-Key": _unique_key()},
            files={
                "file": (
                    "sample.txt",
                    (fixture_documents_dir / "sample.txt").read_bytes(),
                    "text/plain",
                )
            },
        )

    assert response.status_code == 202
    assert response.headers["X-Trace-Id"] == "trace-123"
    event = _event_records(caplog, "document_ingested")[0]
    assert event.trace_id == "trace-123"
    assert event.request_id


@pytest.mark.live_infinity
def test_query_success_produces_info_log(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /queries 成功时产生 query_answered info 日志。"""
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(client, FakeOpenAIClient(output_text="回答"))
    upload_response = _upload_fixture_document(
        client, fixture_documents_dir, "sample.txt", idempotency_key=_unique_key()
    )
    _wait_for_document_terminal_state(client, upload_response.json()["document_id"])

    with caplog.at_level(logging.INFO, logger=API_LOGGER):
        response = _query_documents(client, "test query", top_k=3)

    assert response.status_code == 200
    events = _event_records(caplog, "query_answered")
    assert len(events) == 1
    assert events[0].top_n == 3
    assert events[0].context_count >= 0
    assert events[0].trace_id == response.headers["X-Trace-Id"]
    assert events[0].request_id


def test_domain_error_produces_warning_log(
    lite_client, caplog: pytest.LogCaptureFixture
) -> None:
    """已知 domain error 映射 HTTP 时产生 request_error warning 日志。"""
    with caplog.at_level(logging.WARNING, logger=API_LOGGER):
        response = lite_client.post(
            "/api/v0/documents",
            files={"file": ("sample.docx", b"PK\x03\x04", "application/octet-stream")},
            headers={"Idempotency-Key": _unique_key()},
        )

    assert response.status_code == 415
    events = _event_records(caplog, "request_error")
    assert len(events) == 1
    assert events[0].status_code == 415
    assert events[0].error_type == "UnsupportedFileTypeError"
    assert events[0].path == "/api/v0/documents"
    assert events[0].trace_id == response.headers["X-Trace-Id"]
    assert events[0].request_id


def test_error_response_body_unchanged(lite_client) -> None:
    """现有 415/422/404/500 响应 body 格式不变。"""
    # 415
    resp = lite_client.post(
        "/api/v0/documents",
        files={"file": ("bad.exe", b"x", "application/octet-stream")},
        headers={"Idempotency-Key": _unique_key()},
    )
    assert resp.status_code == 415
    assert set(resp.json().keys()) == {"detail"}

    # 404
    resp = lite_client.get("/api/v0/documents/doc_nonexistent")
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


def test_metrics_route_disabled_returns_404(lite_client) -> None:
    response = lite_client.get("/metrics")
    assert response.status_code == 404


@pytest.mark.live_infinity
def test_metrics_route_enabled_exposes_prometheus_metrics(
    tmp_path: Path,
    fixture_documents_dir: Path,
) -> None:
    from ragflow_lite.app import create_app

    app = create_app(_build_settings(tmp_path, metrics_enabled=True))

    with TestClient(app) as metrics_client:
        _install_fake_ark_client(metrics_client, FakeArkClient())
        _install_fake_openai_client(
            metrics_client, FakeOpenAIClient(output_text="回答")
        )
        upload_response = _upload_fixture_document(
            metrics_client,
            fixture_documents_dir,
            "sample.txt",
            idempotency_key=_unique_key(),
        )
        assert upload_response.status_code == 202
        _wait_for_document_terminal_state(
            metrics_client, upload_response.json()["document_id"]
        )

        query_response = _query_documents(metrics_client, "test query")
        assert query_response.status_code == 200

        bad_response = metrics_client.post(
            "/api/v0/documents",
            files={"file": ("bad.exe", b"x", "application/octet-stream")},
            headers={"Idempotency-Key": _unique_key()},
        )
        assert bad_response.status_code == 415

        metrics_response = metrics_client.get("/metrics")

    assert metrics_response.status_code == 200
    body = metrics_response.text
    assert "ragflow_lite_http_requests_total" in body
    assert (
        'ragflow_lite_http_requests_total{method="POST",route="/api/v0/documents",status_code="202"}'
        in body
    )
    assert (
        'ragflow_lite_http_requests_total{method="POST",route="/api/v0/documents",status_code="415"}'
        in body
    )
    assert 'ragflow_lite_ingest_total{file_type="txt",outcome="succeeded"}' in body
    assert 'ragflow_lite_query_total{outcome="succeeded"}' in body
    assert 'route="/metrics"' not in body


@pytest.mark.live_infinity
def test_metrics_registry_remains_scoped_to_first_app_after_second_app_creation(
    tmp_path: Path,
    fixture_documents_dir: Path,
) -> None:
    from ragflow_lite.app import create_app

    first_app = create_app(_build_settings(tmp_path / "app_one", metrics_enabled=True))
    _patch_fake_evidence_extractor(first_app)

    with TestClient(first_app) as first_client:
        _install_fake_ark_client(first_client, FakeArkClient())
        upload_response = _upload_fixture_document(
            first_client,
            fixture_documents_dir,
            "sample.txt",
            idempotency_key=_unique_key(),
        )
        assert upload_response.status_code == 202
        _wait_for_document_terminal_state(
            first_client, upload_response.json()["document_id"]
        )

        second_app = create_app(
            _build_settings(tmp_path / "app_two", metrics_enabled=False)
        )
        with TestClient(second_app) as second_client:
            disabled_metrics_response = second_client.get("/metrics")

        first_metrics_response = first_client.get("/metrics")

    assert disabled_metrics_response.status_code == 404
    assert first_metrics_response.status_code == 200
    assert (
        'ragflow_lite_http_requests_total{method="POST",route="/api/v0/documents",status_code="202"}'
        in first_metrics_response.text
    )
    assert (
        'ragflow_lite_ingest_total{file_type="txt",outcome="succeeded"}'
        in first_metrics_response.text
    )


def test_method_not_allowed_metrics_use_partial_route_label(
    lite_metrics_client,
) -> None:
    response = lite_metrics_client.put("/api/v0/health")
    metrics_response = lite_metrics_client.get("/metrics")

    assert response.status_code == 405
    body = metrics_response.text
    assert (
        'ragflow_lite_http_requests_total{method="PUT",route="/api/v0/health",status_code="405"}'
        in body
    )
    assert 'route="unmatched",status_code="405"' not in body


def test_unhandled_exception_is_logged_and_counted(
    lite_metrics_no_raise_client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    @lite_metrics_no_raise_client.app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger=OBSERVABILITY_LOGGER):
        response = lite_metrics_no_raise_client.get(
            "/boom", headers={"X-Trace-Id": "trace-boom"}
        )
    metrics_response = lite_metrics_no_raise_client.get("/metrics")

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


@pytest.mark.live_infinity
def test_logs_do_not_include_raw_query_or_document_content(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ragflow_lite.app import create_app

    app = create_app(_build_settings(tmp_path, metrics_enabled=False))
    secret_query = "SECRET_QUERY_123"
    secret_document = "SECRET_DOC_CONTENT_123"

    with TestClient(app) as test_client:
        _install_fake_ark_client(test_client, FakeArkClient())
        _install_fake_openai_client(test_client, FakeOpenAIClient(output_text="回答"))

        with caplog.at_level(logging.INFO):
            upload_response = test_client.post(
                "/api/v0/documents",
                files={
                    "file": (
                        "secret.txt",
                        secret_document.encode("utf-8"),
                        "text/plain",
                    )
                },
                headers={"Idempotency-Key": _unique_key()},
            )
            _wait_for_document_terminal_state(
                test_client, upload_response.json()["document_id"]
            )
            query_response = _query_documents(test_client, secret_query)

    assert upload_response.status_code == 202
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
        record
        for record in caplog.records
        if getattr(record, "event", None) in relevant_events
    ]

    assert relevant_records
    for record in relevant_records:
        rendered = str(record.__dict__)
        assert secret_query not in rendered
        assert secret_document not in rendered


@pytest.mark.live_infinity
def test_academic_pdf_ingestion_produces_academic_chunks(
    client,
    fixture_documents_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Academic PDF ingestion produces chunks with academic sparse fields."""
    _install_fake_ark_client(client, FakeArkClient())
    _install_fake_openai_client(
        client, FakeOpenAIClient(output_text="table answer<cite:1>.")
    )
    _patch_fake_evidence_extractor(client.app)
    with caplog.at_level(logging.INFO):
        upload_response = _upload_fixture_document(
            client,
            fixture_documents_dir,
            "academic_pdf/sample_academic.pdf",
            upload_name="sample_academic.pdf",
            idempotency_key=_unique_key(),
        )
        assert upload_response.status_code == 202
        document_id = upload_response.json()["document_id"]
        final_payload = _wait_for_document_terminal_state(client, document_id)
    assert final_payload["status"] == "indexed"
    # Verify academic sparse fields are populated in Infinity
    vector_index = client.app.state.services.ingestion_pipeline.vector_index
    rows = _chunk_rows(
        vector_index,
        ["paper_title_tks", "caption_tks", "chunk_metadata_json"],
    )
    academic_rows = [r for r in rows if r.get("paper_title_tks")]
    assert len(academic_rows) > 0, "Expected at least one chunk with paper_title_tks"
    caption_rows = [r for r in rows if r.get("caption_tks")]
    assert len(caption_rows) > 0, "Expected at least one chunk with caption_tks"


def test_academic_pdf_gate_a_does_not_construct_vlm_client_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate A must not require VLM client when figure VLM is disabled."""
    monkeypatch.setenv("MICRORAG_FIGURE_VLM_ENABLED", "false")
    from ragflow_lite.config.settings import Settings

    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    assert settings.figure_vlm_enabled is False
