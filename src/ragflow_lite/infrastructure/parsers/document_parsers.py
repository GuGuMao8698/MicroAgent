"""文档解析实现。

当前只支持 `txt` 和 `md`，目标是把不同文件来源统一收敛为 `ParsedDocument`，
为后续 chunking 和 retrieval 提供稳定输入。
"""

from __future__ import annotations

import re

from ragflow_lite.domain.errors import DocumentParsingError, UnsupportedFileTypeError
from ragflow_lite.domain.models import DocumentAsset, ParsedDocument

LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
FENCE_PATTERN = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
ALT_FENCE_PATTERN = re.compile(r"~~~[^\n]*\n(.*?)~~~", re.DOTALL)


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

    当前只做轻量处理：保留标题、列表、链接文本和代码块内容，去掉 markdown
    控制符本身，不尝试恢复更复杂的结构语义。
    """
    # 先处理 fenced code，保留代码内容，再继续清理其它 markdown 标记。
    flattened = FENCE_PATTERN.sub(lambda match: match.group(1).strip(), text)
    flattened = ALT_FENCE_PATTERN.sub(lambda match: match.group(1).strip(), flattened)
    # 链接保留“可读文本 + URL”，这样查询既能命中文本也能命中链接地址。
    flattened = LINK_PATTERN.sub(
        lambda match: f"{match.group(1)} {match.group(2)}", flattened
    )
    flattened = re.sub(r"`([^`]+)`", r"\1", flattened)
    flattened = re.sub(r"^\s{0,3}#{1,6}\s*", "", flattened, flags=re.MULTILINE)
    flattened = re.sub(r"^\s*>\s?", "", flattened, flags=re.MULTILINE)
    flattened = re.sub(r"^\s*[-*+]\s+", "", flattened, flags=re.MULTILINE)
    flattened = re.sub(r"^\s*\d+\.\s+", "", flattened, flags=re.MULTILINE)
    flattened = re.sub(r"(\*\*|__|\*|_|~~)", "", flattened)
    return flattened


class PlainTextParser:
    """解析纯文本文件。"""

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        """把 `txt` 文件直接解码为统一文档对象。"""
        try:
            text = decode_text(raw_bytes)
        except Exception as exc:  # pragma: no cover - decode_text already guards
            raise DocumentParsingError(asset.filename) from exc

        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text=text,
            metadata={"filename": asset.filename},
        )


class MarkdownParser:
    """解析 markdown 文件并做轻量扁平化。"""

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        """把 `md` 文件转换为更适合后续索引的纯文本表示。"""
        try:
            text = flatten_markdown(decode_text(raw_bytes))
        except Exception as exc:  # pragma: no cover - decode_text already guards
            raise DocumentParsingError(asset.filename) from exc

        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text=text,
            metadata={"filename": asset.filename, "format": "markdown"},
        )


class CompositeParser:
    """按文件类型分派到具体解析器。"""

    def __init__(self) -> None:
        self._parsers = {
            "txt": PlainTextParser(),
            "md": MarkdownParser(),
        }

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        """根据文档类型选择对应解析器。"""
        parser = self._parsers.get(asset.file_type)
        if parser is None:
            raise UnsupportedFileTypeError(asset.filename)
        return parser.parse(asset, raw_bytes)
