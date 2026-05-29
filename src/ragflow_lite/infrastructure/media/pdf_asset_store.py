from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ragflow_lite.domain.models import PdfMediaAsset


@dataclass(slots=True)
class StagedPdfAssets:
    document_id: str
    stage_dir: Path
    asset_paths: dict[str, Path]


class LocalPdfMediaAssetStore:
    def __init__(
        self, media_root: Path, *, max_asset_bytes: int = 10 * 1024 * 1024
    ) -> None:
        self.media_root = media_root
        self.max_asset_bytes = max_asset_bytes

    def stage_assets(
        self, document_id: str, assets: list[PdfMediaAsset]
    ) -> StagedPdfAssets:
        stage_dir = self.media_root / ".staging" / document_id / uuid4().hex
        stage_dir.mkdir(parents=True, exist_ok=True)
        asset_paths: dict[str, Path] = {}
        for asset in assets:
            self._validate_asset(asset)
            path = stage_dir / f"{asset.asset_id}{asset.extension}"
            data = asset.data or b""
            path.write_bytes(data)
            self._assert_path_confined(path)
            asset_paths[asset.asset_id] = path
        return StagedPdfAssets(
            document_id=document_id, stage_dir=stage_dir, asset_paths=asset_paths
        )

    def commit_assets(
        self, document_id: str, staged: StagedPdfAssets
    ) -> dict[str, Path]:
        committed_dir = self.media_root / document_id
        committed_dir.mkdir(parents=True, exist_ok=True)
        committed: dict[str, Path] = {}
        for asset_id, staged_path in staged.asset_paths.items():
            committed_path = committed_dir / staged_path.name
            shutil.move(str(staged_path), committed_path)
            self._assert_path_confined(committed_path)
            committed[asset_id] = committed_path
        self.rollback_staged_assets(staged)
        return committed

    def rollback_staged_assets(self, staged: StagedPdfAssets) -> None:
        if staged.stage_dir.exists():
            shutil.rmtree(staged.stage_dir)

    def delete_document_assets(self, document_id: str) -> None:
        committed_dir = self.media_root / document_id
        if committed_dir.exists():
            shutil.rmtree(committed_dir)

    def _validate_asset(self, asset: PdfMediaAsset) -> None:
        if asset.media_type != "image/png" or asset.extension != ".png":
            raise ValueError(f"Unsupported media type for asset '{asset.asset_id}'.")
        if asset.size_bytes > self.max_asset_bytes:
            raise ValueError(f"Asset '{asset.asset_id}' exceeds size limit.")

    def _assert_path_confined(self, path: Path) -> None:
        path.resolve().relative_to(self.media_root.resolve())
