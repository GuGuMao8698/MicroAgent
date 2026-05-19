from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_probe_chunking_writes_isolated_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "sample.md"
    source.write_text(
        "# Probe Doc\n\n"
        "第一段用于测试 token chunk。\n\n"
        "Second paragraph checks offsets and preview output.\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "chunk-probe"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/probe_chunking.py",
            "--input",
            str(source),
            "--output-dir",
            str(output_dir),
            "--chunk-size",
            "12",
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    report_path = output_dir / "chunks.json"
    summary_path = output_dir / "summary.md"
    assert report_path.exists()
    assert summary_path.exists()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["source_path"] == str(source)
    assert payload["chunk_token_budget"] == 12
    assert payload["chunk_overlap"] == 0
    assert payload["chunk_count"] >= 1
    assert payload["writes_to_knowledge_base"] is False
    required_chunk_fields = {
        "id",
        "chunk_id",
        "index",
        "token_count",
        "char_length",
        "start_offset",
        "end_offset",
        "page_start",
        "page_end",
        "text_preview",
    }
    assert all(required_chunk_fields <= chunk.keys() for chunk in payload["chunks"])
    assert all(chunk["token_count"] <= 12 for chunk in payload["chunks"])
