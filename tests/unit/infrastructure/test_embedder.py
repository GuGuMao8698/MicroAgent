from __future__ import annotations

from ragflow_lite.infrastructure.embedders import DeterministicHashEmbedder


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=False)
    )


def test_hash_embedder_is_deterministic() -> None:
    embedder = DeterministicHashEmbedder(dimensions=256)

    first = embedder.embed_query("rag system 检索")
    second = embedder.embed_query("rag system 检索")

    assert first == second


def test_hash_embedder_makes_related_text_more_similar() -> None:
    embedder = DeterministicHashEmbedder(dimensions=256)

    query = embedder.embed_query("python 检索")
    related = embedder.embed_query("python 检索 pipeline")
    unrelated = embedder.embed_query("banana orange fruit")

    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)
