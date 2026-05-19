from __future__ import annotations

from functools import lru_cache

import tiktoken
from tiktoken import Encoding


@lru_cache(maxsize=1)
def _cl100k_base() -> Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_cl100k_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_cl100k_base().encode(text))
