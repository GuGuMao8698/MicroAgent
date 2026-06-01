from __future__ import annotations

from pathlib import Path

from ragflow_lite.infrastructure.vlm.ark_figure_describer import (
    ArkFigureDescriptionClient,
)


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": "A pipeline figure."})()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_describer_sends_base64_data_url(tmp_path: Path) -> None:
    image = tmp_path / "fig.png"
    image.write_bytes(b"pngdata")
    fake = FakeOpenAIClient()
    describer = ArkFigureDescriptionClient(
        client=fake,
        model="ep-test",
        max_image_bytes=1024,
    )

    result = describer.describe(
        image_path=image,
        caption="System overview.",
        section_path=["Method"],
        paper_title="Paper",
    )

    assert result.status == "succeeded"
    assert result.description == "A pipeline figure."
    assert len(fake.responses.calls) == 1


def test_describer_skips_oversized_image(tmp_path: Path) -> None:
    image = tmp_path / "large.png"
    image.write_bytes(b"x" * 20)
    describer = ArkFigureDescriptionClient(
        client=FakeOpenAIClient(),
        model="ep-test",
        max_image_bytes=10,
    )

    result = describer.describe(
        image_path=image,
        caption="Caption",
        section_path=[],
        paper_title="Paper",
    )

    assert result.status == "skipped"
    assert result.skipped_reason == "image_too_large"


def test_describer_returns_failed_on_exception(tmp_path: Path) -> None:
    class FailingClient:
        class responses:
            @staticmethod
            def create(**kwargs: object) -> None:
                raise RuntimeError("API error")

    image = tmp_path / "fig.png"
    image.write_bytes(b"data")
    describer = ArkFigureDescriptionClient(
        client=FailingClient(),
        model="ep-test",
        max_image_bytes=1024,
    )

    result = describer.describe(
        image_path=image,
        caption="Caption",
        section_path=[],
        paper_title="Paper",
    )

    assert result.status == "failed"
    assert result.error_type == "RuntimeError"
