"""文档解析实现。

当前支持 `txt`、`md` 和 `pdf`（数字原生），目标是把不同文件来源统一收敛为 `ParsedDocument`，
为后续 chunking 和 retrieval 提供稳定输入。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from ragflow_lite.domain.errors import DocumentParsingError, UnsupportedFileTypeError
from ragflow_lite.domain.models import DocumentAsset, ParsedDocument
from ragflow_lite.shared.observability import log_event

# 固定策略 ID：file_type -> parser_strategy 的默认映射。
PARSER_STRATEGY_MAP: dict[str, str] = {
    "txt": "plain_text",
    "md": "markdown_flatten",
    "pdf": "docling_academic_pdf",
}

MARKDOWN_PARSER = MarkdownIt("commonmark").enable("strikethrough")
INLINE_MARK_OPEN_TO_CLOSE = {
    "em_open": "em_close",
    "strong_open": "strong_close",
    "s_open": "s_close",
}
INLINE_MARK_CLOSE_TYPES = set(INLINE_MARK_OPEN_TO_CLOSE.values())

logger = logging.getLogger(__name__)


def _metadata_for(
    asset: DocumentAsset,
    **extra_fields: int | str | list[dict[str, int | str]],
) -> dict[str, int | str | list[dict[str, int | str]]]:
    metadata: dict[str, int | str | list[dict[str, int | str]]] = {
        "filename": asset.filename,
        "parser_strategy": PARSER_STRATEGY_MAP[asset.file_type],
    }
    metadata.update(extra_fields)
    return metadata


def _log_parser_failed(
    asset: DocumentAsset,
    *,
    parser_strategy: str,
    error_type: str,
) -> None:
    log_event(
        logger,
        logging.ERROR,
        "parser_failed",
        document_filename=asset.filename,
        file_type=asset.file_type,
        parser_strategy=parser_strategy,
        error_type=error_type,
    )


def decode_text(raw_bytes: bytes) -> str:
    """按统一策略把原始字节解码成文本。

    优先尝试 `utf-8-sig`，这样可以兼容带 BOM 的文本文件；若失败，则退回
    `utf-8` 的替换模式，尽量保留可读内容而不是直接报错。
    """
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw_bytes.decode("utf-8", errors="replace")


def flatten_markdown(text: str) -> str:
    """把 markdown 扁平化为更适合索引的纯文本。

    当前使用 CommonMark 解析并抽取可索引文本，保留标题、列表、链接文本和
    代码内容，不把 markdown 控制符误写进索引文本。
    """
    blocks: list[str] = []

    for token in MARKDOWN_PARSER.parse(text):
        rendered = _render_block_token(token)
        if rendered:
            blocks.append(rendered)

    return "\n".join(blocks)


def _render_block_token(token: Token) -> str:
    if token.type == "inline":
        return _render_inline_tokens(token.children or [])

    if token.type in {"fence", "code_block"}:
        return token.content.rstrip("\n")

    if token.children:
        return _render_inline_tokens(token.children)

    if token.content:
        return token.content

    return ""


def _render_inline_tokens(tokens: Sequence[Token]) -> str:
    fragments: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token.type in {"text", "code_inline"}:
            fragments.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            fragments.append("\n")
        elif token.type == "inline":
            fragments.append(_render_inline_tokens(token.children or []))
        elif token.type == "link_open":
            close_index = _find_matching_close(tokens, index, "link_open", "link_close")
            if close_index is None:
                href = token.attrGet("href")
                if href:
                    fragments.append(href)
            else:
                fragments.append(_render_link(token, tokens[index + 1 : close_index]))
                index = close_index
        elif token.type in INLINE_MARK_OPEN_TO_CLOSE:
            close_index = _find_matching_close(
                tokens,
                index,
                token.type,
                INLINE_MARK_OPEN_TO_CLOSE[token.type],
            )
            if close_index is None:
                if token.content:
                    fragments.append(token.content)
            else:
                fragments.append(_render_inline_tokens(tokens[index + 1 : close_index]))
                index = close_index
        elif token.type in INLINE_MARK_CLOSE_TYPES | {"link_close"}:
            pass
        elif token.children:
            fragments.append(_render_inline_tokens(token.children))
        elif token.content:
            fragments.append(token.content)

        index += 1

    return "".join(fragments)


def _find_matching_close(
    tokens: Sequence[Token],
    start_index: int,
    open_type: str,
    close_type: str,
) -> int | None:
    depth = 0

    for index in range(start_index, len(tokens)):
        token = tokens[index]

        if token.type == open_type:
            depth += 1
        elif token.type == close_type:
            depth -= 1
            if depth == 0:
                return index

    return None


def _render_link(open_token: Token, nested_tokens: Sequence[Token]) -> str:
    text = _render_inline_tokens(nested_tokens).strip()
    href = open_token.attrGet("href") or ""

    if text and href:
        return f"{text} {href}"
    if text:
        return text
    return str(href)


class PlainTextParser:
    """解析纯文本文件。"""

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        """把 `txt` 文件直接解码为统一文档对象。"""
        try:
            text = decode_text(raw_bytes)
        except Exception as exc:  # pragma: no cover - decode_text already guards
            _log_parser_failed(
                asset,
                parser_strategy=PARSER_STRATEGY_MAP[asset.file_type],
                error_type=type(exc).__name__,
            )
            raise DocumentParsingError(asset.filename) from exc

        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text=text,
            metadata=_metadata_for(asset),
        )


class MarkdownParser:
    """解析 markdown 文件并做轻量扁平化。"""

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        """把 `md` 文件转换为更适合后续索引的纯文本表示。"""
        try:
            text = flatten_markdown(decode_text(raw_bytes))
        except Exception as exc:  # pragma: no cover - decode_text already guards
            _log_parser_failed(
                asset,
                parser_strategy=PARSER_STRATEGY_MAP[asset.file_type],
                error_type=type(exc).__name__,
            )
            raise DocumentParsingError(asset.filename) from exc

        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text=text,
            metadata=_metadata_for(asset, format="markdown"),
        )


class CompositeParser:
    """按文件类型分派到具体解析器。"""

    def __init__(self, *, pdf_backend: Any = None) -> None:
        from ragflow_lite.infrastructure.parsers.docling_pdf_adapter import (
            DoclingPdfBackend,
            DoclingPdfParser,
        )

        pdf_parser = (
            DoclingPdfParser(backend=pdf_backend)
            if isinstance(pdf_backend, DoclingPdfBackend)
            else DoclingPdfParser()
        )
        self._parsers: dict[
            str, PlainTextParser | MarkdownParser | DoclingPdfParser
        ] = {
            "txt": PlainTextParser(),
            "md": MarkdownParser(),
            "pdf": pdf_parser,
        }

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        """根据文档类型选择对应解析器。"""
        parser = self._parsers.get(asset.file_type)
        if parser is None:
            raise UnsupportedFileTypeError(asset.filename)
        return parser.parse(asset, raw_bytes)
