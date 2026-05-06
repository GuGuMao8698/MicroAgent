"""query_analysis 纯函数单测。"""

from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.retrievers.query_analysis import build_sparse_query


class TestNormalizationAndWhitespace:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("ＲＡＧ系统", "rag 系统"),
            ("hello\x00world", "helloworld"),
            ("hello\n\tworld", "hello world"),
            ("hello   world", "hello world"),
            ("RAG API", "rag api"),
        ],
        ids=[
            "nfkc-fullwidth",
            "null-byte-removed",
            "newline-tab-collapsed",
            "spaces-compressed",
            "latin-lowercased",
        ],
    )
    def test_build_sparse_query(self, query: str, expected: str) -> None:
        assert build_sparse_query(query) == expected


class TestCjkBoundarySplitting:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("RAG系统API", "rag 系统 api"),
            ("版本3更新", "版本 3 更新"),
            ("什么是 GPT", "什么是 gpt"),
        ],
        ids=["latin-cjk", "cjk-digit", "already-spaced-mixed"],
    )
    def test_build_sparse_query(self, query: str, expected: str) -> None:
        assert build_sparse_query(query) == expected


class TestTechTokenPreservation:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("c++", "c++"),
            ("c#", "c#"),
            ("node.js", "node.js"),
            ("api_v1", "api_v1"),
            ("gpt-4o", "gpt-4o"),
            ("如何用 c++ 写 api_v1", "如何用 c++ 写 api_v1"),
        ],
        ids=[
            "cplusplus",
            "csharp",
            "nodejs",
            "api-v1",
            "gpt-4o",
            "tech-token-in-context",
        ],
    )
    def test_build_sparse_query(self, query: str, expected: str) -> None:
        assert build_sparse_query(query) == expected


class TestFallbackAndSymbolCleanup:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("!!!@@@", "!!!@@@"),
            ("", ""),
            ("   ", ""),
            ("检索系统", "检索系统"),
            ("检索*系统?测试", "检索 系统 测试"),
            ("RAG: 检索、重排！", "rag 检索 重排"),
        ],
        ids=[
            "symbols-only-fallback",
            "empty-input",
            "whitespace-only",
            "pure-cjk",
            "special-chars-cleaned",
            "mixed-punctuation-cleaned",
        ],
    )
    def test_build_sparse_query(self, query: str, expected: str) -> None:
        assert build_sparse_query(query) == expected


def test_build_chunk_text_query_uses_ragflow_tokenizer(monkeypatch) -> None:
    from ragflow_lite.infrastructure.retrievers import query_analysis

    monkeypatch.setattr(query_analysis, "tokenize", lambda text: f"tok({text})")

    assert query_analysis.build_chunk_text_query("TypeScript 手册") == "tok(TypeScript 手册)"


def test_build_chunk_text_query_falls_back_to_sparse_query(monkeypatch) -> None:
    from ragflow_lite.infrastructure.nlp import RAGFlowTokenizerUnavailableError
    from ragflow_lite.infrastructure.retrievers import query_analysis

    def fail_tokenize(text: str) -> str:
        raise RAGFlowTokenizerUnavailableError("missing")

    monkeypatch.setattr(query_analysis, "tokenize", fail_tokenize)

    assert query_analysis.build_chunk_text_query("TypeScript 手册") == "typescript 手册"
