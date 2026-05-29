from __future__ import annotations

from ragflow_lite.application.services.model_facing_retrieval import (
    blueprint_payload,
    context_payload,
    model_facing_retrieval_payload,
    order_discorag_contexts_for_model,
    order_standard_contexts_for_model,
)
from ragflow_lite.domain.models import AnswerBlueprint, RetrievedChunk


def _chunk(
    chunk_id: str,
    *,
    score: float,
    metadata: dict[str, object] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=f"text-{chunk_id}",
        score=score,
        metadata=dict(metadata or {}),
    )


def _blueprint() -> AnswerBlueprint:
    return AnswerBlueprint(
        ordered_chunk_ids=["c1", "c3", "c2"],
        chunk_roles={"c1": "lead", "c2": "contrast"},
        answer_constraints=["只基于证据回答"],
        plan_steps=["先总结主结论", "再补充限制条件"],
        metadata={"debug": "hidden"},
    )


def test_standard_contexts_use_u_shaped_attention_order() -> None:
    contexts = [
        _chunk("c2", score=0.8, metadata={"source": "B"}),
        _chunk("c4", score=0.6, metadata={"source": "D"}),
        _chunk("c1", score=0.9, metadata={"source": "A"}),
        _chunk("c3", score=0.7, metadata={"source": "C"}),
    ]

    ordered = order_standard_contexts_for_model(contexts)

    assert [chunk.chunk_id for chunk in ordered] == ["c1", "c3", "c4", "c2"]
    assert ordered[0].metadata == {"source": "A"}
    assert ordered[-1].metadata == {"source": "B"}
    assert {id(chunk) for chunk in ordered} == {id(chunk) for chunk in contexts}


def test_standard_contexts_with_two_items_preserve_score_order() -> None:
    contexts = [
        _chunk("c2", score=0.5),
        _chunk("c1", score=0.7),
    ]

    ordered = order_standard_contexts_for_model(contexts)

    assert [chunk.chunk_id for chunk in ordered] == ["c1", "c2"]


def test_discorag_contexts_are_score_descending() -> None:
    contexts = [
        _chunk("c3", score=0.3, metadata={"kind": "tail"}),
        _chunk("c1", score=0.9, metadata={"kind": "lead"}),
        _chunk("c2", score=0.6, metadata={"kind": "middle"}),
    ]

    ordered = order_discorag_contexts_for_model(contexts)

    assert [chunk.chunk_id for chunk in ordered] == ["c1", "c2", "c3"]
    assert [chunk.metadata["kind"] for chunk in ordered] == ["lead", "middle", "tail"]
    assert {id(chunk) for chunk in ordered} == {id(chunk) for chunk in contexts}


def test_blueprint_payload_field_order_puts_ordered_ids_last() -> None:
    payload = blueprint_payload(_blueprint())

    assert list(payload.keys()) == [
        "chunk_roles",
        "answer_constraints",
        "plan_steps",
        "ordered_chunk_ids",
    ]
    assert "metadata" not in payload
    assert payload["ordered_chunk_ids"] == ["c1", "c3", "c2"]


def test_standard_payload_omits_mode_metadata_and_blueprint() -> None:
    contexts = [
        _chunk("c2", score=0.6),
        _chunk("c1", score=0.9),
        _chunk("c3", score=0.4),
    ]

    payload = model_facing_retrieval_payload(
        query="MiniRAG 是什么？",
        contexts=contexts,
        blueprint=None,
    )

    assert list(payload.keys()) == ["query", "contexts"]
    assert payload["query"] == "MiniRAG 是什么？"
    assert [item["chunk_id"] for item in payload["contexts"]] == ["c2", "c1", "c3"]
    assert list(payload["contexts"][0].keys()) == [
        "chunk_id",
        "document_id",
        "text",
        "score",
        "metadata",
    ]
    assert "mode" not in payload
    assert "metadata" not in payload
    assert "blueprint" not in payload


def test_discorag_payload_places_blueprint_after_contexts() -> None:
    contexts = [
        _chunk("c2", score=0.6),
        _chunk("c1", score=0.9),
        _chunk("c3", score=0.4),
    ]

    payload = model_facing_retrieval_payload(
        query="DiscoRAG 如何组织证据？",
        contexts=contexts,
        blueprint=_blueprint(),
    )

    assert list(payload.keys()) == ["query", "contexts", "blueprint"]
    assert [item["chunk_id"] for item in payload["contexts"]] == ["c2", "c1", "c3"]
    assert list(payload["blueprint"].keys()) == [
        "chunk_roles",
        "answer_constraints",
        "plan_steps",
        "ordered_chunk_ids",
    ]
    assert "metadata" not in payload["blueprint"]


def test_model_facing_payload_preserves_explicit_standard_ordering() -> None:
    contexts = [
        _chunk("c2", score=0.6),
        _chunk("c1", score=0.9),
        _chunk("c3", score=0.4),
    ]

    ordered_contexts = order_standard_contexts_for_model(contexts)
    payload = model_facing_retrieval_payload(
        query="MiniRAG 是什么？",
        contexts=ordered_contexts,
        blueprint=None,
    )

    assert [item["chunk_id"] for item in payload["contexts"]] == ["c1", "c3", "c2"]


def test_context_payload_deep_copies_metadata() -> None:
    chunk = _chunk("c1", score=0.9, metadata={"source": "A", "nested": {"rank": 1}})

    payload = context_payload(chunk)
    payload["metadata"]["source"] = "mutated"
    payload["metadata"]["nested"]["rank"] = 9

    assert chunk.metadata["source"] == "A"
    assert payload["metadata"] is not chunk.metadata
    assert chunk.metadata["nested"]["rank"] == 1
    assert payload["metadata"]["nested"] is not chunk.metadata["nested"]


def test_blueprint_payload_deep_copies_mutable_fields() -> None:
    blueprint = _blueprint()

    payload = blueprint_payload(blueprint)
    payload["chunk_roles"]["c1"] = "mutated"
    payload["answer_constraints"].append("新增约束")
    payload["plan_steps"][0] = "mutated step"
    payload["ordered_chunk_ids"].append("c4")

    assert blueprint.chunk_roles["c1"] == "lead"
    assert blueprint.answer_constraints == ["只基于证据回答"]
    assert blueprint.plan_steps == ["先总结主结论", "再补充限制条件"]
    assert blueprint.ordered_chunk_ids == ["c1", "c3", "c2"]


from ragflow_lite.application.services.metadata_sanitizer import (
    INTERNAL_METADATA_KEYS,
    sanitize_chunk_metadata,
)


def test_sanitize_chunk_metadata_strips_internal_pdf_fields() -> None:
    metadata = {
        "paper_title": "Paper",
        "caption": "Figure caption",
        "asset_id": "asset_1",
        "storage_path": "/tmp/secret.png",
        "raw_provider_payload": {"secret": True},
        "raw_docling_object": object(),
    }

    sanitized, stats = sanitize_chunk_metadata(metadata)

    assert sanitized == {
        "paper_title": "Paper",
        "caption": "Figure caption",
        "asset_id": "asset_1",
    }
    assert set(stats["internal_fields_stripped"]) >= {
        "storage_path",
        "raw_provider_payload",
        "raw_docling_object",
    }
    assert "storage_path" in INTERNAL_METADATA_KEYS


def test_context_payload_uses_metadata_sanitizer() -> None:
    chunk = RetrievedChunk(
        chunk_id="chunk_1",
        document_id="doc_1",
        text="Body",
        score=1.0,
        metadata={"caption": "safe", "base64": "unsafe"},
    )

    payload = context_payload(chunk)

    assert payload["metadata"] == {"caption": "safe"}
