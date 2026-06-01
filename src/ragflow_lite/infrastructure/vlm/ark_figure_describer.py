from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FigureDescriptionResult:
    status: str  # "succeeded" | "failed" | "skipped"
    description: str | None = None
    skipped_reason: str | None = None
    error_type: str | None = None


class ArkFigureDescriptionClient:
    def __init__(self, *, client: Any, model: str, max_image_bytes: int) -> None:
        self.client = client
        self.model = model
        self.max_image_bytes = max_image_bytes

    def describe(
        self,
        *,
        image_path: Path,
        caption: str | None,
        section_path: list[str],
        paper_title: str,
    ) -> FigureDescriptionResult:
        if not image_path.exists():
            return FigureDescriptionResult(
                status="skipped", skipped_reason="missing_asset"
            )
        if image_path.stat().st_size > self.max_image_bytes:
            return FigureDescriptionResult(
                status="skipped", skipped_reason="image_too_large"
            )
        if image_path.suffix.lower() != ".png":
            return FigureDescriptionResult(
                status="skipped", skipped_reason="unsupported_type"
            )

        image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "You are describing a figure extracted from an academic paper for retrieval.\n"
            f"Paper: {paper_title}\n"
            f"Section: {' > '.join(section_path)}\n"
            f"Caption: {caption or ''}\n"
            "Return a concise factual description in the document language when clear; otherwise use English.\n"
            "Do not invent numeric values that are not visible."
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{image_data}",
                            },
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ],
            )
        except Exception as exc:
            return FigureDescriptionResult(
                status="failed", error_type=type(exc).__name__
            )

        return FigureDescriptionResult(
            status="succeeded",
            description=str(getattr(response, "output_text", "") or "").strip(),
        )
