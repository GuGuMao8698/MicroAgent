from __future__ import annotations

import pytest

from ragflow_lite.application.services.text_normalization import (
    normalize_text,
    normalize_text_content,
)
from ragflow_lite.domain.errors import EmptyDocumentError


def test_normalize_text_rejects_empty_visible_content() -> None:
    with pytest.raises(EmptyDocumentError):
        normalize_text(" \n\t\r ", "empty.txt")


def test_normalize_text_collapses_line_endings() -> None:
    normalized = normalize_text("Hello\r\n\r\nWorld\x00", "hello.txt")
    assert normalized == "Hello\n\nWorld"


def test_normalize_text_content_pure_normalization_without_empty_check() -> None:
    result = normalize_text_content("  \n\t  ")
    assert result == ""


def test_normalize_text_content_strips_and_collapses() -> None:
    result = normalize_text_content("Hello\r\n\r\n\r\nWorld\x00  ")
    assert result == "Hello\n\nWorld"
