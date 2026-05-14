from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal, Protocol, cast

if TYPE_CHECKING:
    from ragflow_lite.domain.models import AnswerResult, RetrievedChunk
    from ragflow_lite.api.deps.providers import AppServices

CliMode = Literal["standard", "discorag"]


class ExitCodeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise CliArgumentError(f"{self.prog}: error: {message}")


class CliArgumentError(Exception):
    pass


class ServicesFactory(Protocol):
    def __call__(self) -> "AppServices": ...


def _default_services_factory() -> "AppServices":
    from ragflow_lite.api.deps.providers import build_services
    from ragflow_lite.config import Settings

    return build_services(Settings.default())


def _build_parser() -> ExitCodeParser:
    parser = ExitCodeParser(prog="mcrag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("retrieve", "answer"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--query", required=True)
        subparser.add_argument(
            "--mode",
            choices=("standard", "discorag"),
            default="standard",
        )
        subparser.add_argument("--top-n", type=int, default=6)
        subparser.add_argument(
            "--json",
            action="store_true",
            help="输出 machine-readable JSON。",
        )

    return parser


def _require_json_flag(args: argparse.Namespace, parser: ExitCodeParser) -> None:
    if args.json:
        return
    parser.error("the following arguments are required: --json")


def _context_payload(context: RetrievedChunk) -> dict[str, object]:
    return {
        "chunk_id": context.chunk_id,
        "document_id": context.document_id,
        "text": context.text,
        "score": context.score,
        "metadata": dict(context.metadata),
    }


def _answer_payload(result: AnswerResult) -> dict[str, object]:
    return {
        "answer": result.answer,
        "contexts": [_context_payload(context) for context in result.contexts],
        "metadata": dict(result.metadata),
    }


def _write_json(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def _is_ragflow_lite_error(exc: Exception) -> bool:
    from ragflow_lite.domain.errors import RagflowLiteError

    return isinstance(exc, RagflowLiteError)


def _handle_retrieve(
    args: argparse.Namespace,
    services: "AppServices",
) -> int:
    from ragflow_lite.application.services.agent_retrieval_service import (
        AgentRetrievalService,
    )

    retrieval_service = AgentRetrievalService(
        services.query_service,
        services.discorag_query_service,
    )
    result = retrieval_service.retrieve(
        query=cast(str, args.query),
        top_k=cast(int, args.top_n),
        mode=cast(CliMode, args.mode),
    )
    _write_json(result.payload)
    return 0


def _handle_answer(
    args: argparse.Namespace,
    services: "AppServices",
) -> int:
    result = services.query_router.query(
        cast(str, args.query),
        top_k=cast(int, args.top_n),
        mode=cast(CliMode, args.mode),
    )
    _write_json(_answer_payload(result))
    return 0


def main(
    argv: Sequence[str] | None = None,
    services_factory: Callable[[], "AppServices"] | None = None,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        _require_json_flag(args, parser)
    except CliArgumentError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    factory = services_factory or _default_services_factory
    try:
        services = factory()
    except Exception as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "retrieve":
            return _handle_retrieve(args, services)
        if args.command == "answer":
            return _handle_answer(args, services)
        raise RuntimeError(f"Unsupported command: {args.command}")
    except Exception as exc:
        if _is_ragflow_lite_error(exc):
            print(f"MicroRAG error: {exc}", file=sys.stderr)
            return 1
        print(f"Runtime error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
