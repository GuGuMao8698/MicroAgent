from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CX_WRAPPER = PROJECT_ROOT / "tools" / "cx"


def _make_fake_cx(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)

    args_file = tmp_path / "cx-args.txt"
    fake_cx = bin_dir / "cx"
    fake_cx.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"$CX_ARGS_FILE\"\n",
        encoding="utf-8",
    )
    fake_cx.chmod(fake_cx.stat().st_mode | stat.S_IXUSR)

    return bin_dir, args_file


def _run_wrapper(
    tmp_path: Path,
    args: list[str],
    *,
    cwd: Path | None = None,
) -> list[str]:
    bin_dir, args_file = _make_fake_cx(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CX_ARGS_FILE"] = str(args_file)

    completed = subprocess.run(
        ["bash", str(CX_WRAPPER), *args],
        cwd=cwd or PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    return args_file.read_text(encoding="utf-8").splitlines()


def test_wrapper_uses_project_root_for_main_repo_paths(tmp_path: Path) -> None:
    recorded_args = _run_wrapper(tmp_path, ["overview", "src/ragflow_lite/app.py"])

    assert recorded_args == [
        "--root",
        str(PROJECT_ROOT),
        "overview",
        str(PROJECT_ROOT / "src" / "ragflow_lite" / "app.py"),
    ]


def test_wrapper_uses_nested_repo_root_for_nested_paths(tmp_path: Path) -> None:
    recorded_args = _run_wrapper(
        tmp_path,
        ["overview", "ragflow/rag/nlp/search.py"],
    )

    assert recorded_args == [
        "--root",
        str(PROJECT_ROOT / "ragflow"),
        "overview",
        str(PROJECT_ROOT / "ragflow" / "rag" / "nlp" / "search.py"),
    ]


def test_wrapper_normalizes_flag_based_paths(tmp_path: Path) -> None:
    cases = [
        (
            ["symbols", "--file", "ragflow/rag/nlp/query.py"],
            [
                "--root",
                str(PROJECT_ROOT / "ragflow"),
                "symbols",
                "--file",
                str(PROJECT_ROOT / "ragflow" / "rag" / "nlp" / "query.py"),
            ],
        ),
        (
            ["references", "--name", "Dealer", "--file", "ragflow/rag/nlp/search.py"],
            [
                "--root",
                str(PROJECT_ROOT / "ragflow"),
                "references",
                "--name",
                "Dealer",
                "--file",
                str(PROJECT_ROOT / "ragflow" / "rag" / "nlp" / "search.py"),
            ],
        ),
        (
            ["definition", "--name", "Dealer", "--from", "ragflow/rag/nlp/search.py"],
            [
                "--root",
                str(PROJECT_ROOT / "ragflow"),
                "definition",
                "--name",
                "Dealer",
                "--from",
                str(PROJECT_ROOT / "ragflow" / "rag" / "nlp" / "search.py"),
            ],
        ),
    ]

    for index, (args, expected) in enumerate(cases):
        recorded_args = _run_wrapper(tmp_path / f"case-{index}", args)
        assert recorded_args == expected


def test_wrapper_respects_explicit_root_without_rewriting_paths(tmp_path: Path) -> None:
    explicit_root = PROJECT_ROOT / "ragflow"
    recorded_args = _run_wrapper(
        tmp_path,
        ["--root", str(explicit_root), "overview", "ragflow/rag/nlp/search.py"],
    )

    assert recorded_args == [
        "--root",
        str(explicit_root),
        "overview",
        "ragflow/rag/nlp/search.py",
    ]


def test_wrapper_falls_back_to_cwd_git_root_when_no_path_is_present(tmp_path: Path) -> None:
    recorded_args = _run_wrapper(
        tmp_path,
        ["symbols", "--name", "Dealer"],
        cwd=PROJECT_ROOT / "ragflow",
    )

    assert recorded_args == [
        "--root",
        str(PROJECT_ROOT / "ragflow"),
        "symbols",
        "--name",
        "Dealer",
    ]
