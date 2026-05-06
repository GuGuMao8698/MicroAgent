from __future__ import annotations

import pytest
from ragflow_lite.infrastructure.nlp.ragflow_tokenizer import (
    RAGFlowTokenizerUnavailableError,
    fine_grained_tokenize,
    tokenize,
)


class _FakeBackend:
    """轻量 fake，用于验证 facade 委托行为。"""

    def __init__(self) -> None:
        self.tokenize_calls: list[str] = []
        self.fine_calls: list[str] = []

    def tokenize(self, text: str) -> str:
        self.tokenize_calls.append(text)
        return f"TOK::{text}"

    def fine_grained_tokenize(self, tokens: str) -> str:
        self.fine_calls.append(tokens)
        return f"FINE::{tokens}"


class TestTokenize:
    def test_delegates_to_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _FakeBackend()
        monkeypatch.setattr(
            "ragflow_lite.infrastructure.nlp.ragflow_tokenizer._load_backend",
            lambda: backend,
        )
        assert tokenize("TypeScript C++") == "TOK::TypeScript C++"
        assert backend.tokenize_calls == ["TypeScript C++"]

    def test_raises_clear_error_when_backend_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> object:
            raise RAGFlowTokenizerUnavailableError(
                "RAGFlow tokenizer backend is unavailable"
            )

        monkeypatch.setattr(
            "ragflow_lite.infrastructure.nlp.ragflow_tokenizer._load_backend",
            _raise,
        )
        with pytest.raises(
            RAGFlowTokenizerUnavailableError, match="RAGFlow tokenizer backend"
        ):
            tokenize("TypeScript")


class TestFineGrainedTokenize:
    def test_delegates_to_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _FakeBackend()
        monkeypatch.setattr(
            "ragflow_lite.infrastructure.nlp.ragflow_tokenizer._load_backend",
            lambda: backend,
        )
        assert fine_grained_tokenize("typescript c++") == "FINE::typescript c++"
        assert backend.fine_calls == ["typescript c++"]
