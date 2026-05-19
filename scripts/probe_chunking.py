from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ragflow_lite.domain.models import DocumentAsset
from ragflow_lite.infrastructure.chunkers import RecursiveCharacterChunker
from ragflow_lite.infrastructure.chunkers.token_counter import count_cl100k_tokens
from ragflow_lite.infrastructure.parsers import CompositeParser


def _file_type(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "markdown":
        return "md"
    return suffix


def _preview(text: str, limit: int = 180) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def build_probe_payload(
    input_path: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> dict[str, Any]:
    raw_bytes = input_path.read_bytes()
    asset = DocumentAsset(
        document_id=input_path.stem or "probe-document",
        filename=input_path.name,
        file_type=_file_type(input_path),
        storage_path=input_path,
        size_bytes=len(raw_bytes),
    )
    parsed = CompositeParser().parse(asset, raw_bytes)
    chunks = RecursiveCharacterChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    ).chunk(parsed)

    chunk_rows: list[dict[str, Any]] = []
    over_budget: list[str] = []
    for chunk in chunks:
        token_count = count_cl100k_tokens(chunk.text)
        if token_count > chunk_size:
            over_budget.append(chunk.chunk_id)
        chunk_rows.append(
            {
                "id": chunk.chunk_id,
                "chunk_id": chunk.chunk_id,
                "index": chunk.index,
                "token_count": token_count,
                "char_length": len(chunk.text),
                "start_offset": chunk.metadata.get("start_offset"),
                "end_offset": chunk.metadata.get("end_offset"),
                "page_start": chunk.metadata.get("page_start"),
                "page_end": chunk.metadata.get("page_end"),
                "text_preview": _preview(chunk.text),
            }
        )

    return {
        "source_path": str(input_path),
        "parser_strategy": parsed.metadata.get("parser_strategy"),
        "file_type": asset.file_type,
        "chunk_token_budget": chunk_size,
        "chunk_overlap": chunk_overlap,
        "chunk_count": len(chunks),
        "writes_to_knowledge_base": False,
        "over_budget_chunk_ids": over_budget,
        "chunks": chunk_rows,
    }


def write_summary(payload: dict[str, Any], output_dir: Path) -> None:
    lines = [
        "# Chunk Probe Summary",
        "",
        f"- Source: `{payload['source_path']}`",
        f"- Parser: `{payload['parser_strategy']}`",
        f"- File type: `{payload['file_type']}`",
        f"- Chunk token budget: `{payload['chunk_token_budget']}`",
        f"- Chunk overlap: `{payload['chunk_overlap']}`",
        f"- Chunk count: `{payload['chunk_count']}`",
        f"- Over-budget chunk ids: `{payload['over_budget_chunk_ids']}`",
        f"- Writes to knowledge base: `{payload['writes_to_knowledge_base']}`",
        "",
        "| index | tokens | chars | offsets | pages | preview |",
        "|---:|---:|---:|---|---|---|",
    ]
    for chunk in payload["chunks"]:
        pages = f"{chunk.get('page_start')}-{chunk.get('page_end')}"
        offsets = f"{chunk.get('start_offset')}-{chunk.get('end_offset')}"
        preview = str(chunk.get("text_preview", "")).replace("|", "\\|")
        lines.append(
            f"| {chunk['index']} | {chunk['token_count']} | {chunk['char_length']} | "
            f"{offsets} | {pages} | {preview} |"
        )

    output_dir.joinpath("summary.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe parser and chunker output without indexing.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--chunk-overlap", type=int, default=0)
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_probe_payload(
        args.input,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    output_dir.joinpath("chunks.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_summary(payload, output_dir)
    print(output_dir)


if __name__ == "__main__":
    main()
