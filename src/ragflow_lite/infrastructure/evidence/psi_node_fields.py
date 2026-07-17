from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ragflow_lite.domain.models.psi_tree import PsiNode
from ragflow_lite.infrastructure.nlp.ragflow_tokenizer import (
    tokenize as ragflow_tokenize,
)

PSI_NODE_MATCH_TEXT_FIELDS = [
    "psi_node_label_kwd^30",
    "psi_node_label_tks^20",
    "psi_keyword_tks^20",
    "psi_summary_tks^4",
    "psi_leaf_text_tks^2",
]


class PsiNodeProjectionError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class PsiNodeProjectionText:
    embedding_text: str
    psi_node_label_kwd: str
    psi_node_label_tks: str
    psi_keyword_tks: str
    psi_summary_tks: str
    psi_leaf_text_tks: str
    text_tks: str


def build_psi_node_projection_text(
    node: PsiNode,
    *,
    tokenize: Callable[[str], str] = ragflow_tokenize,
) -> PsiNodeProjectionText:
    node_label = _optional_label(node.metadata.get("node_label"))
    if node.node_type in {"root", "internal"} and node.abstract_type is None:
        raise PsiNodeProjectionError("abstract nodes require abstract_type")
    if node.abstract_type == "keyword":
        text = _required(node.keyword_text, "keyword_text")
        label = node_label or text
        return PsiNodeProjectionText(
            embedding_text=text,
            psi_node_label_kwd=label,
            psi_node_label_tks=tokenize(label),
            psi_keyword_tks=tokenize(text),
            psi_summary_tks="",
            psi_leaf_text_tks="",
            text_tks=tokenize(text),
        )
    if node.abstract_type == "summative":
        text = _required(node.summary_text or node.text, "summary_text")
        return PsiNodeProjectionText(
            embedding_text=text,
            psi_node_label_kwd=node_label,
            psi_node_label_tks=tokenize(node_label),
            psi_keyword_tks="",
            psi_summary_tks=tokenize(text),
            psi_leaf_text_tks="",
            text_tks=tokenize(text),
        )
    if node.node_type == "leaf":
        text = _required(node.text, "leaf text")
        return PsiNodeProjectionText(
            embedding_text=text,
            psi_node_label_kwd=node_label,
            psi_node_label_tks=tokenize(node_label),
            psi_keyword_tks="",
            psi_summary_tks="",
            psi_leaf_text_tks=tokenize(text),
            text_tks=tokenize(text),
        )
    raise PsiNodeProjectionError("unsupported Psi node projection shape")


def build_psi_node_projection_row(
    node: PsiNode,
    *,
    document_id: str,
    source_chunk_ids: list[str],
    vector: list[float],
    tokenize: Callable[[str], str] = ragflow_tokenize,
) -> dict[str, Any]:
    fields = build_psi_node_projection_text(node, tokenize=tokenize)
    metadata = dict(node.metadata)
    metadata.update(
        {
            "psi_node_id": node.node_id,
            "build_id": node.build_id,
            "source_document_id": node.source_document_id,
        }
    )
    return {
        "projection_row_id": projection_row_id(node.build_id, node.node_id),
        "psi_node_id": node.node_id,
        "build_id": node.build_id,
        "document_id": document_id,
        "layer": node.layer,
        "node_type": node.node_type,
        "abstract_type": node.abstract_type or "",
        "source_chunk_ids_json": json.dumps(source_chunk_ids, ensure_ascii=False),
        "embedding_text": fields.embedding_text,
        "psi_node_label_kwd": fields.psi_node_label_kwd,
        "psi_node_label_tks": fields.psi_node_label_tks,
        "psi_keyword_tks": fields.psi_keyword_tks,
        "psi_summary_tks": fields.psi_summary_tks,
        "psi_leaf_text_tks": fields.psi_leaf_text_tks,
        "text_tks": fields.text_tks,
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        "vec": vector,
    }


def _required(value: str | None, field_name: str) -> str:
    normalized = " ".join((value or "").split())
    if not normalized:
        raise PsiNodeProjectionError(f"Psi node missing required {field_name}")
    return normalized


def _optional_label(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def projection_row_id(build_id: str, node_id: str) -> str:
    if not build_id or not node_id:
        raise PsiNodeProjectionError(
            "projection row identity requires build_id and node_id"
        )
    return f"{build_id}:{node_id}"
