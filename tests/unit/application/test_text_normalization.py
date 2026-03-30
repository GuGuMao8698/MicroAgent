from __future__ import annotations

import pytest

from ragflow_lite.application.services.text_normalization import normalize_text
from ragflow_lite.domain.errors import EmptyDocumentError


def test_normalize_text_rejects_empty_visible_content() -> None:
    with pytest.raises(EmptyDocumentError):
        normalize_text(" \n\t\r ", "empty.txt")


def test_normalize_text_collapses_line_endings() -> None:
    normalized = normalize_text("Hello\r\n\r\nWorld\x00", "hello.txt")
    assert normalized == "Hello\n\nWorld"
