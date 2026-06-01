from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import PdfMediaAsset
from ragflow_lite.infrastructure.media.pdf_asset_store import LocalPdfMediaAssetStore


def _asset(asset_id: str = "asset_1") -> PdfMediaAsset:
    return PdfMediaAsset(
        asset_id=asset_id,
        element_id="fig_1",
        media_type="image/png",
        extension=".png",
        size_bytes=4,
        data=b"data",
    )


def test_stage_commit_and_delete_assets(tmp_path: Path) -> None:
    store = LocalPdfMediaAssetStore(tmp_path)

    staged = store.stage_assets("doc_1", [_asset()])
    committed = store.commit_assets("doc_1", staged)

    assert committed["asset_1"].exists()
    assert committed["asset_1"].read_bytes() == b"data"

    store.delete_document_assets("doc_1")

    assert not (tmp_path / "doc_1").exists()


def test_rollback_staged_assets_removes_attempt_directory(tmp_path: Path) -> None:
    store = LocalPdfMediaAssetStore(tmp_path)

    staged = store.stage_assets("doc_1", [_asset()])
    assert staged.stage_dir.exists()

    store.rollback_staged_assets(staged)

    assert not staged.stage_dir.exists()


def test_rejects_unsupported_media_type(tmp_path: Path) -> None:
    store = LocalPdfMediaAssetStore(tmp_path)
    bad = PdfMediaAsset(
        asset_id="asset_bad",
        element_id="fig_1",
        media_type="text/plain",
        extension=".txt",
        size_bytes=4,
        data=b"data",
    )

    try:
        store.stage_assets("doc_1", [bad])
    except ValueError as exc:
        assert "Unsupported media type" in str(exc)
    else:
        raise AssertionError("Expected unsupported media type to fail")
