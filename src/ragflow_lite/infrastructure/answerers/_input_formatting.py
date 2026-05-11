from __future__ import annotations

from typing import Any


def format_retrieval_rewrite_notice(metadata: dict[str, Any]) -> list[str]:
    rewrite = metadata.get("retrieval_rewrite")
    if (
        not isinstance(rewrite, dict)
        or rewrite.get("answer_notice_required") is not True
    ):
        return []
    return [
        "Retrieval rewrite notice:",
        "- Retrieval rewrite already ran, but the available evidence still appears insufficient.",
        "- Likely causes include missing relevant documents in the knowledge base or a query that is still too ambiguous.",
        "- Tell the user that they may need to rephrase the query or add the needed documents.",
        "",
    ]
