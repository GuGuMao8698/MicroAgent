"""Thin, lazy wrapper around RAGFlow's RagTokenizer for deterministic ``*_tks`` field generation.

延迟初始化：RagTokenizer 会加载 NLTK 数据、stemmer 等重量级资源，
所以只在首次调用时才 import + 实例化，后续复用同一个实例。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol


class RAGFlowTokenizerUnavailableError(RuntimeError):
    """RAGFlow tokenizer backend 不可用（infinity 包未安装或 rag_tokenizer 缺失）。"""


class _TokenizerBackend(Protocol):
    """RagTokenizer 实例需要满足的最小接口。"""

    def tokenize(self, text: str) -> str: ...
    def fine_grained_tokenize(self, tokens: str) -> str: ...


@lru_cache(maxsize=1)
def _load_backend() -> _TokenizerBackend:
    """延迟加载 infinity.rag_tokenizer.RagTokenizer，全局只实例化一次。"""
    try:
        from infinity.rag_tokenizer import RagTokenizer
    except Exception as exc:
        raise RAGFlowTokenizerUnavailableError(
            "RAGFlow tokenizer backend is unavailable. "
            "Install or expose the infinity package with rag_tokenizer before "
            "building graph candidate token fields."
        ) from exc
    return RagTokenizer()


def tokenize(text: str) -> str:
    """粗粒度分词，用于 ``entity_name_tks`` 等字段。"""
    return _load_backend().tokenize(text)


def fine_grained_tokenize(tokens: str) -> str:
    """细粒度分词，用于 ``entity_name_ltks`` 等字段。"""
    return _load_backend().fine_grained_tokenize(tokens)
