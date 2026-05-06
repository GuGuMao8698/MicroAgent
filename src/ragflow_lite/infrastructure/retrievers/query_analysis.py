"""保守的 sparse-query 清洗，为 Infinity 全文分支提供更稳定的查询文本。"""

from __future__ import annotations

import re
import unicodedata

from ragflow_lite.infrastructure.nlp import (
    RAGFlowTokenizerUnavailableError,
    tokenize,
)

_CJK_BOUNDARY_LTR = re.compile(
    r"(?<=[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])(?=[a-zA-Z0-9])"
)
_CJK_BOUNDARY_RTL = re.compile(
    r"(?<=[a-zA-Z0-9])(?=[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])"
)
_ASCII_TECH_RE = re.compile(r"[a-z0-9][a-z0-9._#+-]*")
_MULTI_SPACE_RE = re.compile(r" {2,}")
_LATIN_UPPER_RE = re.compile(r"[A-Z]")


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF


def _extract_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if _is_cjk(ch):
            start = i
            while i < len(text) and _is_cjk(text[i]):
                i += 1
            tokens.append(text[start:i])
        else:
            m = _ASCII_TECH_RE.match(text, i)
            if m:
                tokens.append(m.group())
                i = m.end()
            else:
                i += 1
    return tokens


def build_sparse_query(query: str) -> str:
    """对原始 query 做保守清洗，生成适合 Infinity match_text 的 sparse query。

    规则固定为保守清洗：
    1. NFKC 归一化
    2. 去除 null、折叠换行/制表为空格、压缩连续空白
    3. 中英文/数字边界插入空格
    4. 仅 Latin 字母小写化
    5. 安全 token 提取（中文片段 + ASCII 技术 token，后者允许内部 . _ # + -）
    6. 提取为空时回退到 strip 后的归一化原串
    """
    text = unicodedata.normalize("NFKC", query)
    text = text.replace("\x00", "")
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = _MULTI_SPACE_RE.sub(" ", text)

    text = _CJK_BOUNDARY_LTR.sub(" ", text)
    text = _CJK_BOUNDARY_RTL.sub(" ", text)

    text = _LATIN_UPPER_RE.sub(lambda m: m.group().lower(), text)

    tokens = _extract_tokens(text)
    if not tokens:
        fallback = text.strip()
        return fallback if fallback else query.strip()
    return " ".join(tokens)


def build_chunk_text_query(query: str) -> str:
    """Build match_text query for RAGFlow-tokenized chunk fields."""
    try:
        tokenized = tokenize(query)
    except RAGFlowTokenizerUnavailableError:
        return build_sparse_query(query)
    normalized = tokenized.strip()
    return normalized if normalized else build_sparse_query(query)
