from __future__ import annotations

from typing import Any

from ragflow_lite.domain.models import Chunk, ParsedDocument

DEFAULT_SEPARATORS: list[str] = [
    "\n\n",  # paragraph / blank line
    "\n",  # line break
    "。",  # Chinese period
    "！",  # Chinese exclamation
    "？",  # Chinese question mark
    ".",  # English period
    "!",  # English exclamation
    "?",  # English question mark
    " ",  # space
    "",  # character-level fallback
]

_INTERNAL_METADATA_KEYS = frozenset({"page_spans", "page_texts"})


def _overlapping_pages(
    page_spans: list[dict[str, Any]], chunk_start: int, chunk_end: int
) -> list[int]:
    """Return sorted page numbers whose spans overlap ``[chunk_start, chunk_end)``."""
    pages: list[int] = []
    for span in page_spans:
        if chunk_start < span["end"] and span["start"] < chunk_end:
            pages.append(span["page_number"])
    return sorted(pages)


def _chunk_metadata(
    document: ParsedDocument,
    chunk_start: int,
    chunk_end: int,
) -> dict[str, Any]:
    """Build metadata dict for a chunk, stripping internal keys."""
    metadata = {
        k: v for k, v in document.metadata.items() if k not in _INTERNAL_METADATA_KEYS
    }
    metadata["start_offset"] = chunk_start
    metadata["end_offset"] = chunk_end

    page_spans = document.metadata.get("page_spans")
    if page_spans:
        pages = _overlapping_pages(page_spans, chunk_start, chunk_end)
        if pages:
            metadata["page_start"] = pages[0]
            metadata["page_end"] = pages[-1]

    return metadata


def _recursive_split(text: str, separators: list[str], chunk_size: int) -> list[str]:
    """Split *text* recursively using *separators* until every piece <= *chunk_size*.

    If *separators* is empty, fall back to a hard character-window split.
    """
    if len(text) <= chunk_size:
        return [text]

    if not separators:
        return _hard_split(text, chunk_size)

    sep = separators[0]
    remaining = separators[1:]

    if sep == "":
        # Empty-string separator: split into individual characters.
        pieces = [c for c in text if c]
    else:
        pieces = text.split(sep)
        # Re-attach the separator to each piece except the last so that
        # concatenating all pieces reconstructs the original text exactly.
        pieces = [p + sep for p in pieces[:-1]] + [pieces[-1]]

    # Filter out empty pieces that arise from consecutive separators.
    pieces = [p for p in pieces if p]

    # Recursively split any piece that still exceeds chunk_size.
    result: list[str] = []
    for piece in pieces:
        if len(piece) <= chunk_size:
            result.append(piece)
        else:
            result.extend(_recursive_split(piece, remaining, chunk_size))

    return result


def _hard_split(text: str, chunk_size: int) -> list[str]:
    """Split *text* into fixed-size character windows."""
    pieces: list[str] = []
    for i in range(0, len(text), chunk_size):
        piece = text[i : i + chunk_size]
        if piece:
            pieces.append(piece)
    return pieces


def _merge_pieces(
    pieces: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[tuple[str, int, int]]:
    """Merge *pieces* into chunks of at most *chunk_size* characters.

    Returns a list of ``(chunk_text, start_offset, end_offset)`` tuples where
    offsets are computed against the text reconstructed by joining all *pieces*.

    Overlap is implemented by prepending trailing pieces from the previous
    chunk to the beginning of the next chunk, up to approximately
    *chunk_overlap* characters.
    """
    if not pieces:
        return []

    # Pre-compute the character offset at which each piece starts.
    piece_offsets: list[int] = []
    running = 0
    for p in pieces:
        piece_offsets.append(running)
        running += len(p)
    chunks: list[tuple[str, int, int]] = []
    # current_start is the index into *pieces* where the current chunk begins.
    current_start = 0

    # We iterate through piece indices, growing the current chunk until
    # adding the next piece would exceed chunk_size.
    i = 0
    while i < len(pieces):
        # Determine how far the current chunk can extend.
        current_end = i  # exclusive index into pieces
        current_chars = 0
        j = current_start
        while j < len(pieces):
            if current_chars + len(pieces[j]) > chunk_size:
                break
            current_chars += len(pieces[j])
            current_end = j + 1
            j += 1

        # Ensure at least one piece per chunk to avoid infinite loops.
        if current_end == current_start:
            current_end = current_start + 1

        chunk_text = "".join(pieces[current_start:current_end])
        start_offset = piece_offsets[current_start]
        end_offset = piece_offsets[current_end - 1] + len(pieces[current_end - 1])
        chunks.append((chunk_text, start_offset, end_offset))

        if current_end >= len(pieces):
            break

        # Compute overlap: take trailing pieces from the current chunk
        # until we accumulate approximately chunk_overlap characters.
        overlap_len = 0
        overlap_count = 0
        for k in range(current_end - 1, current_start - 1, -1):
            if overlap_len + len(pieces[k]) > chunk_overlap:
                break
            overlap_len += len(pieces[k])
            overlap_count += 1

        # Next chunk starts with the overlap pieces.
        current_start = current_end - overlap_count
        i = current_end

    return chunks


class RecursiveCharacterChunker:
    """Recursive character text splitter.

    Splits text using a priority-ordered list of separators, falling back
    to finer separators when pieces still exceed *chunk_size*.  Produces
    deterministic chunks with optional overlap between consecutive chunks.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: list[str] | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size - 1")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators if separators is not None else DEFAULT_SEPARATORS

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        text = document.raw_text
        if not text:
            return []

        pieces = _recursive_split(text, self.separators, self.chunk_size)
        merged = _merge_pieces(pieces, self.chunk_size, self.chunk_overlap)

        chunks: list[Chunk] = []
        chunk_index = 0
        for chunk_text, start_offset, end_offset in merged:
            stripped = chunk_text.strip()
            if not stripped:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"chunk_{document.document_id}_{chunk_index}",
                    document_id=document.document_id,
                    text=stripped,
                    index=chunk_index,
                    metadata=_chunk_metadata(document, start_offset, end_offset),
                )
            )
            chunk_index += 1

        return chunks
