"""本地确定性 embedding 实现。

V0 阶段不接外部模型服务，改用可重复、零依赖的哈希向量方案验证主链路。
它不追求语义效果接近真实 embedding，只追求流程稳定、结果可测。
"""

from __future__ import annotations

import hashlib
import math
import re

from ragflow_lite.domain.models import Chunk, EmbeddedChunk

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """把文本切成适合当前哈希向量方案的 token。

    英文按连续单词切分，中文按单字切分，保证中英文内容都能参与最小检索。
    """
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


class DeterministicHashEmbedder:
    """把文本映射为确定性的稀疏哈希向量。"""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """批量为 chunk 生成向量表示。"""
        return [
            EmbeddedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=chunk.text,
                index=chunk.index,
                vector=self._embed_text(chunk.text),
                metadata=dict(chunk.metadata),
            )
            for chunk in chunks
        ]

    def embed_query(self, query: str) -> list[float]:
        """为查询文本生成与 chunk 同空间的向量。"""
        return self._embed_text(query)

    def _embed_text(self, text: str) -> list[float]:
        """使用哈希桶和符号位构造固定维度向量。"""
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # 桶索引决定 token 落到哪一维，保证固定维度且无需词表。
            bucket = int.from_bytes(digest[:8], "big") % self.dimensions
            # 符号位让不同 token 不只会单向累加，减少哈希冲突带来的偏置。
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]
