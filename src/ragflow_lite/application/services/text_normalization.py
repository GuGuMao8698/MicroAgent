"""文本归一化工具。

这里集中处理 V0 阶段最小必要的文本清洗，确保后续 chunking、embedding
和检索面对的是更稳定的输入。
"""

from __future__ import annotations

import re
import unicodedata

from ragflow_lite.domain.errors import EmptyDocumentError

VISIBLE_TEXT_PATTERN = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")


def normalize_text(text: str, filename: str) -> str:
    """执行最小文本规整，并拒绝没有有效可见字符的文档。"""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\x00", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = normalized.strip()

    # V0 先用一个简单且稳定的规则过滤掉“只有空白或噪音字符”的输入。
    if not VISIBLE_TEXT_PATTERN.search(normalized):
        raise EmptyDocumentError(filename)

    return normalized
