from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk
from ragflow_lite.infrastructure.vector_indexes import LocalJsonVectorIndex

LOCAL_INDEX_LOGGER = "ragflow_lite.infrastructure.vector_indexes.local_json_index"
EMBEDDING_SIGNATURE = {
    "provider": "ark",
    "model": "ep-test-model",
    "dimensions": 4,
}


def test_local_json_index_persists_searches_and_deletes(tmp_path: Path) -> None:
    index = LocalJsonVectorIndex(tmp_path, embedding_signature=EMBEDDING_SIGNATURE)
    asset = DocumentAsset(
        document_id="doc_alpha",
        filename="alpha.txt",
        file_type="txt",
        storage_path=tmp_path / "alpha.txt",
        size_bytes=12,
    )
    embedded_chunk = EmbeddedChunk(
        chunk_id="chunk_doc_alpha_0",
        document_id="doc_alpha",
        text="rag pipeline with citations later",
        index=0,
        vector=[1.0, 0.0, 0.0, 0.0],
        metadata={"filename": "alpha.txt"},
    )

    index.index_document(asset, [embedded_chunk])

    index_files = list(tmp_path.glob("*"))
    assert [path.suffix for path in index_files] == [".json"]
    payload = json.loads(index_files[0].read_text(encoding="utf-8"))
    assert payload["embedding_signature"] == EMBEDDING_SIGNATURE

    results = index.search([1.0, 0.0, 0.0, 0.0], top_k=3)
    assert len(results) == 1
    assert results[0].document_id == "doc_alpha"
    assert results[0].metadata["filename"] == "alpha.txt"

    index.delete_document("doc_alpha")
    assert list(tmp_path.glob("*.json")) == []


def test_local_json_index_rejects_missing_embedding_signature(tmp_path: Path) -> None:
    index = LocalJsonVectorIndex(tmp_path, embedding_signature=EMBEDDING_SIGNATURE)
    index_path = tmp_path / "doc_alpha.json"
    index_path.write_text(
        json.dumps(
            {
                "document": {"document_id": "doc_alpha", "filename": "alpha.txt"},
                "chunks": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProcessingError, match="missing embedding signature"):
        index.search([1.0, 0.0, 0.0, 0.0], top_k=3)


def test_local_json_index_rejects_incompatible_embedding_signature(tmp_path: Path) -> None:
    index = LocalJsonVectorIndex(tmp_path, embedding_signature=EMBEDDING_SIGNATURE)
    index_path = tmp_path / "doc_alpha.json"
    index_path.write_text(
        json.dumps(
            {
                "document": {"document_id": "doc_alpha", "filename": "alpha.txt"},
                "embedding_signature": {
                    "provider": "ark",
                    "model": "ep-old-model",
                    "dimensions": 4,
                },
                "chunks": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProcessingError, match="Re-upload the document or rebuild"):
        index.search([1.0, 0.0, 0.0, 0.0], top_k=3)


def test_local_json_index_logs_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    index = LocalJsonVectorIndex(tmp_path, embedding_signature=EMBEDDING_SIGNATURE)
    asset = DocumentAsset(
        document_id="doc_alpha",
        filename="alpha.txt",
        file_type="txt",
        storage_path=tmp_path / "alpha.txt",
        size_bytes=12,
    )
    embedded_chunk = EmbeddedChunk(
        chunk_id="chunk_doc_alpha_0",
        document_id="doc_alpha",
        text="alpha",
        index=0,
        vector=[1.0, 0.0, 0.0, 0.0],
        metadata={},
    )

    def _explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "ragflow_lite.infrastructure.vector_indexes.local_json_index.NamedTemporaryFile",
        _explode,
    )

    with caplog.at_level(logging.ERROR, logger=LOCAL_INDEX_LOGGER):
        with pytest.raises(Exception, match="doc_alpha"):
            index.index_document(asset, [embedded_chunk])

    record = next(
        record for record in caplog.records if record.event == "local_index_write_failed"
    )
    assert record.document_id == "doc_alpha"
    assert record.error_type == "OSError"
