from __future__ import annotations

from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.domain.models import (
    EvidencePackage,
    GroundedQuery,
    RetrievedChunk,
    TopologyPath,
    TopologyRetrievalResult,
)


def _chunk(
    chunk_id: str,
    document_id: str = "doc1",
    text: str = "text",
    score: float = 0.5,
    metadata: dict | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        score=score,
        metadata=metadata or {},
    )


def _path(
    path_id: str,
    source_chunk_ids: list[str] | None = None,
    relation_ids: list[str] | None = None,
    document_id: str = "doc1",
) -> TopologyPath:
    return TopologyPath(
        path_id=path_id,
        document_id=document_id,
        entity_ids=["e1"],
        relation_ids=relation_ids or [],
        source_chunk_ids=source_chunk_ids or [],
        score=0.8,
    )


def _grounded_query() -> GroundedQuery:
    return GroundedQuery(
        query="what is X",
        answer_type_keywords=["definition"],
        entities_from_query=["X"],
    )


def _result(
    chunks: list[RetrievedChunk] | None = None,
    paths: list[TopologyPath] | None = None,
    metadata: dict | None = None,
) -> TopologyRetrievalResult:
    return TopologyRetrievalResult(
        query="what is X",
        grounded_query=_grounded_query(),
        chunks=chunks or [],
        paths=paths or [],
        metadata=metadata or {},
    )


class TestBasicConversion:
    def test_converts_chunks_and_paths_to_evidence_package(self):
        chunks = [
            _chunk("c1", text="hello", score=0.9),
            _chunk("c2", text="world", score=0.7),
        ]
        paths = [_path("p1", source_chunk_ids=["c1"], relation_ids=["r1"])]
        result = _result(chunks, paths)

        package = EvidencePackageBuilder().build(result)

        assert isinstance(package, EvidencePackage)
        assert package.query == "what is X"
        assert package.grounded_query is result.grounded_query
        assert len(package.items) == 2

        item1 = package.items[0]
        assert item1.canonical_chunk_id == "c1"
        assert item1.text == "hello"
        assert item1.score == 0.9
        assert item1.order == 0
        assert "topology_path" in item1.retained_reasons
        assert "p1" in item1.topology_path_ids
        assert "r1" in item1.topology_relation_ids

        item2 = package.items[1]
        assert item2.canonical_chunk_id == "c2"
        assert "baseline_retrieval" in item2.retained_reasons
        assert item2.topology_path_ids == []
        assert item2.topology_relation_ids == []


class TestDeduplication:
    def test_duplicate_chunk_keeps_first_text_score_and_order(self):
        chunks = [
            _chunk("c1", text="first", score=0.9),
            _chunk("c1", text="second", score=0.3),
        ]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        assert len(package.items) == 1
        item = package.items[0]
        assert item.text == "first"
        assert item.score == 0.9
        assert item.order == 0

    def test_duplicate_chunk_merges_reasons(self):
        chunks = [
            _chunk("c1", text="first"),
            _chunk("c1", text="second"),
        ]
        paths = [_path("p1", source_chunk_ids=["c1"], relation_ids=["r1"])]
        result = _result(chunks, paths)

        package = EvidencePackageBuilder().build(result)

        item = package.items[0]
        assert "topology_path" in item.retained_reasons
        assert "baseline_retrieval" in item.retained_reasons

    def test_duplicate_chunk_merges_topology_ids(self):
        chunks = [
            _chunk("c1", text="first"),
            _chunk("c1", text="second"),
        ]
        paths = [
            _path("p1", source_chunk_ids=["c1"], relation_ids=["r1", "r2"]),
            _path("p2", source_chunk_ids=["c1"], relation_ids=["r3"]),
        ]
        result = _result(chunks, paths)

        package = EvidencePackageBuilder().build(result)

        item = package.items[0]
        assert set(item.topology_path_ids) == {"p1", "p2"}
        assert set(item.topology_relation_ids) == {"r1", "r2", "r3"}


class TestBaselineOnly:
    def test_no_paths_all_items_get_baseline_reason(self):
        chunks = [
            _chunk("c1", text="a"),
            _chunk("c2", text="b"),
        ]
        result = _result(chunks, paths=[])

        package = EvidencePackageBuilder().build(result)

        for item in package.items:
            assert item.retained_reasons == ["baseline_retrieval"]
            assert item.topology_path_ids == []
            assert item.topology_relation_ids == []


class TestTopologyPathMapping:
    def test_chunk_referenced_by_path_gets_topology_reason(self):
        chunks = [_chunk("c1", text="in path"), _chunk("c2", text="not in path")]
        paths = [
            _path("p1", source_chunk_ids=["c1"], relation_ids=["r1"]),
            _path("p2", source_chunk_ids=["c1"], relation_ids=["r2"]),
        ]
        result = _result(chunks, paths)

        package = EvidencePackageBuilder().build(result)

        item1 = package.items[0]
        assert "topology_path" in item1.retained_reasons
        assert set(item1.topology_path_ids) == {"p1", "p2"}
        assert set(item1.topology_relation_ids) == {"r1", "r2"}

        item2 = package.items[1]
        assert "topology_path" not in item2.retained_reasons
        assert "baseline_retrieval" in item2.retained_reasons

    def test_chunk_in_path_does_not_get_baseline_reason(self):
        chunks = [_chunk("c1", text="overlap")]
        paths = [_path("p1", source_chunk_ids=["c1"])]
        result = _result(chunks, paths)

        package = EvidencePackageBuilder().build(result)

        item = package.items[0]
        assert "topology_path" in item.retained_reasons
        assert "baseline_retrieval" not in item.retained_reasons


class TestProvenanceExtraction:
    def test_metadata_fields_populated(self):
        chunks = [
            _chunk(
                "c1",
                document_id="docA",
                metadata={
                    "filename": "report.pdf",
                    "file_type": "pdf",
                    "_chunk_index": 3,
                },
            )
        ]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        prov = package.items[0].provenance
        assert prov.document_id == "docA"
        assert prov.filename == "report.pdf"
        assert prov.file_type == "pdf"
        assert prov.chunk_index == 3

    def test_missing_metadata_fields_default_to_none(self):
        chunks = [_chunk("c1", document_id="docB", metadata={})]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        prov = package.items[0].provenance
        assert prov.document_id == "docB"
        assert prov.filename is None
        assert prov.file_type is None
        assert prov.chunk_index is None

    def test_wrong_type_metadata_fields_default_to_none(self):
        chunks = [
            _chunk(
                "c1",
                metadata={
                    "filename": 123,
                    "file_type": True,
                    "_chunk_index": "not_an_int",
                },
            )
        ]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        prov = package.items[0].provenance
        assert prov.filename is None
        assert prov.file_type is None
        assert prov.chunk_index is None


class TestGroundedTerms:
    def test_entities_and_keywords_copied_to_all_items(self):
        chunks = [_chunk("c1"), _chunk("c2")]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        for item in package.items:
            assert item.grounded_entities == ["X"]
            assert item.answer_type_keywords == ["definition"]


class TestPackageMetadata:
    def test_includes_evidence_count(self):
        chunks = [_chunk("c1"), _chunk("c2"), _chunk("c3")]
        result = _result(chunks, metadata={"source": "test"})

        package = EvidencePackageBuilder().build(result)

        assert package.metadata["evidence_count"] == 3
        assert package.metadata["source"] == "test"

    def test_preserves_original_metadata(self):
        result = _result(metadata={"key": "value"})

        package = EvidencePackageBuilder().build(result)

        assert package.metadata["key"] == "value"
        assert package.metadata["evidence_count"] == 0


class TestEmptyResult:
    def test_no_chunks_produces_empty_items(self):
        result = _result(chunks=[])

        package = EvidencePackageBuilder().build(result)

        assert package.items == []
        assert package.metadata["evidence_count"] == 0


class TestOrdering:
    def test_order_matches_first_occurrence_in_chunks(self):
        chunks = [
            _chunk("c3", text="third"),
            _chunk("c1", text="first"),
            _chunk("c2", text="second"),
        ]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        by_id = {item.canonical_chunk_id: item for item in package.items}
        assert by_id["c3"].order == 0
        assert by_id["c1"].order == 1
        assert by_id["c2"].order == 2

    def test_duplicate_preserves_first_order(self):
        chunks = [
            _chunk("c1", text="first"),
            _chunk("c2", text="second"),
            _chunk("c1", text="first again"),
        ]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        by_id = {item.canonical_chunk_id: item for item in package.items}
        assert by_id["c1"].order == 0
        assert by_id["c2"].order == 1


class TestEvidenceItemMetadata:
    def test_metadata_is_shallow_copy_of_chunk_metadata(self):
        original_meta = {"key": "value", "nested": {"a": 1}}
        chunks = [_chunk("c1", metadata=original_meta)]
        result = _result(chunks)

        package = EvidencePackageBuilder().build(result)

        item_meta = package.items[0].metadata
        assert item_meta == original_meta
        assert item_meta is not original_meta
