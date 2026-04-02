"""使用假的 Infinity client 验证 `InfinityFullTextRetriever` 的单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ragflow_lite.infrastructure.retrievers.infinity_fulltext_retriever import (
    InfinityFullTextRetriever,
)


class TestInfinityFullTextRetriever:
    def test_retrieve_delegates_to_search_text(self) -> None:
        vector_index = MagicMock()
        vector_index.search_text.return_value = []
        retriever = InfinityFullTextRetriever(vector_index=vector_index)

        retriever.retrieve("test query", top_k=5)

        vector_index.search_text.assert_called_once_with("test query", 5)

    def test_retrieve_returns_search_text_results(self) -> None:
        vector_index = MagicMock()
        chunk = MagicMock()
        chunk.document_id = "doc_1"
        vector_index.search_text.return_value = [chunk]

        retriever = InfinityFullTextRetriever(vector_index=vector_index)
        results = retriever.retrieve("test query", top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_1"

    def test_retrieve_returns_empty_for_no_match(self) -> None:
        vector_index = MagicMock()
        vector_index.search_text.return_value = []

        retriever = InfinityFullTextRetriever(vector_index=vector_index)
        results = retriever.retrieve("nonexistent", top_k=5)

        assert len(results) == 0

    def test_retrieve_propagates_exceptions(self) -> None:
        vector_index = MagicMock()
        vector_index.search_text.side_effect = RuntimeError("db error")

        retriever = InfinityFullTextRetriever(vector_index=vector_index)

        with pytest.raises(RuntimeError, match="db error"):
            retriever.retrieve("query", top_k=5)
