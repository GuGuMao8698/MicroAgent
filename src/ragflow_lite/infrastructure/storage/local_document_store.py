from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from ragflow_lite.domain.models import DocumentAsset


class LocalDocumentStore:
    def __init__(self, uploads_dir: Path, temp_dir: Path) -> None:
        self.uploads_dir = uploads_dir
        self.temp_dir = temp_dir

    def save_document(
        self,
        document_id: str,
        filename: str,
        file_type: str,
        content: bytes,
    ) -> DocumentAsset:
        suffix = Path(filename).suffix.lower() or f".{file_type}"
        target_path = self.path_for(document_id, suffix)
        temp_path = None

        try:
            with NamedTemporaryFile(dir=self.temp_dir, delete=False) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            os.replace(temp_path, target_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

        return DocumentAsset(
            document_id=document_id,
            filename=Path(filename).name,
            file_type=file_type,
            storage_path=target_path,
            size_bytes=len(content),
        )

    def read_document(self, asset: DocumentAsset) -> bytes:
        return asset.storage_path.read_bytes()

    def delete_document(self, document_id: str) -> None:
        for path in self.uploads_dir.glob(f"{document_id}.*"):
            path.unlink(missing_ok=True)

    def path_for(self, document_id: str, suffix: str) -> Path:
        return self.uploads_dir / f"{document_id}{suffix}"
