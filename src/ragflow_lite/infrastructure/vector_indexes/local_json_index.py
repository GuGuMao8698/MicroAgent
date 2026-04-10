"""本地 JSON 向量索引。

当前实现面向小规模语料，按文档分文件持久化，查询时扫描全部索引文件并做
相似度排序。这样实现简单、可观察，也便于验证主链路和回滚行为。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from ragflow_lite.domain.errors import IndexWriteError, ProcessingError
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk, RetrievedChunk
from ragflow_lite.shared.observability import log_event

EmbeddingSignature = dict[str, str | int | None]

logger = logging.getLogger(__name__)


class LocalJsonVectorIndex:
    """使用 JSON 文件保存文档级向量索引。"""

    def __init__(self, index_dir: Path, embedding_signature: EmbeddingSignature) -> None:
        self.index_dir = index_dir
        self.embedding_signature = dict(embedding_signature)

    def index_document(
        self,
        asset: DocumentAsset,
        embedded_chunks: list[EmbeddedChunk],
    ) -> None:
        """把单个文档的向量化结果持久化到独立 JSON 文件。"""
        payload = {
            "document": {
                "document_id": asset.document_id,
                "filename": asset.filename,
                "file_type": asset.file_type,
                "storage_path": str(asset.storage_path),
                "size_bytes": asset.size_bytes,
                "created_at": asset.created_at.isoformat(),
            },
            "embedding_signature": dict(self.embedding_signature),
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "text": chunk.text,
                    "index": chunk.index,
                    "vector": chunk.vector,
                    "metadata": chunk.metadata,
                }
                for chunk in embedded_chunks
            ],
        }
        target_path = self._path_for(asset.document_id)
        temp_path = None

        try:
            with NamedTemporaryFile(
                dir=self.index_dir,
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False)
                temp_path = Path(handle.name)
            # 先写临时文件再原子替换，避免索引文件只写入一半时被读取到。
            os.replace(temp_path, target_path)
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "local_index_write_failed",
                document_id=asset.document_id,
                error_type=type(exc).__name__,
            )
            raise IndexWriteError(asset.document_id) from exc
        finally:
            # 正常替换后临时文件已不存在；异常时这里负责兜底清理。
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def delete_document(self, document_id: str) -> None:
        """删除某个文档对应的索引文件。"""
        self._path_for(document_id).unlink(missing_ok=True)

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        """扫描本地索引并返回分数最高的若干 chunk。"""
        scored_chunks: list[RetrievedChunk] = []
        for path in sorted(self.index_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self._validate_embedding_signature(path, data.get("embedding_signature"))
            document = data.get("document", {})
            for chunk_data in data.get("chunks", []):
                score = self._cosine_similarity(query_vector, chunk_data["vector"])
                if score <= 0:
                    continue
                scored_chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk_data["chunk_id"],
                        document_id=chunk_data["document_id"],
                        text=chunk_data["text"],
                        score=score,
                        metadata={
                            **chunk_data.get("metadata", {}),
                            "filename": document.get("filename"),
                            "file_type": document.get("file_type"),
                        },
                    )
                )

        if not any(query_vector):
            return []

        # 先聚合所有文档的候选片段，再按全局分数截断 top_k。
        scored_chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        return scored_chunks[:top_k]

    def _path_for(self, document_id: str) -> Path:
        """返回某个文档对应的索引文件路径。"""
        return self.index_dir / f"{document_id}.json"

    def _validate_embedding_signature(
        self,
        path: Path,
        actual_signature: object,
    ) -> None:
        if not isinstance(actual_signature, dict):
            raise ProcessingError(
                f"Index '{path.name}' is missing embedding signature metadata. "
                "Re-upload the document or rebuild the local index."
            )

        expected_keys = tuple(self.embedding_signature.keys())
        missing_keys = [key for key in expected_keys if key not in actual_signature]
        if missing_keys:
            missing_list = ", ".join(missing_keys)
            raise ProcessingError(
                f"Index '{path.name}' is missing embedding signature fields: {missing_list}. "
                "Re-upload the document or rebuild the local index."
            )

        normalized_actual_signature = {
            key: actual_signature[key] for key in expected_keys
        }
        if normalized_actual_signature != self.embedding_signature:
            raise ProcessingError(
                f"Index '{path.name}' was built with embedding signature "
                f"{normalized_actual_signature}, but the current configuration is "
                f"{self.embedding_signature}. Re-upload the document or rebuild the local index."
            )

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        """计算两个归一化向量的余弦相似度。"""
        return float(
            sum(
                left_value * right_value
                for left_value, right_value in zip(left, right, strict=False)
            )
        )
