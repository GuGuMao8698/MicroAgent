from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _make_stub_bun(bin_dir: Path, log_path: Path) -> None:
    bun = bin_dir / "bun"
    bun.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                f'printf "cwd %s\\n" "$PWD" >> "{log_path}"',
                f'printf "bun %s\\n" "$*" >> "{log_path}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    bun.chmod(0o755)


def _make_env_logging_stub_bun(
    bin_dir: Path, log_path: Path, env_names: tuple[str, ...]
) -> None:
    lines = [
        "#!/usr/bin/env bash",
        f'printf "bun %s\\n" "$*" >> "{log_path}"',
    ]
    for name in env_names:
        lines.append(
            f'if [[ -n "${{{name}:-}}" ]]; then '
            f'printf "{name}=SET\\n" >> "{log_path}"; '
            f'else printf "{name}=UNSET\\n" >> "{log_path}"; fi'
        )
    bun = bin_dir / "bun"
    bun.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bun.chmod(0o755)


def _make_script_repo(tmp_path: Path, *, with_settings: bool = True) -> Path:
    source_root = Path.cwd()
    repo_root = tmp_path / "repo"
    script_dir = repo_root / "scripts"
    microagent_dir = repo_root / "src" / "ragflow_lite" / "microagent"
    node_modules = microagent_dir / "node_modules"

    script_dir.mkdir(parents=True)
    node_modules.mkdir(parents=True)
    (microagent_dir / ".claude" / "skills" / "teach-me").mkdir(parents=True)
    (microagent_dir / ".claude" / "agents").mkdir(parents=True)
    (microagent_dir / ".claude" / "skills" / "teach-me" / "SKILL.md").write_text(
        "---\nname: teach-me\n---\n# Teach Me\n",
        encoding="utf-8",
    )
    (microagent_dir / ".claude" / "agents" / "hello-agent.md").write_text(
        "---\nname: hello-agent\n---\nhello\n",
        encoding="utf-8",
    )
    local_env = repo_root / "data" / "agent-runtime" / "local.env"
    local_env.parent.mkdir(parents=True)
    local_env.write_text("", encoding="utf-8")
    shutil.copyfile(
        source_root / "scripts" / "run_microagent.sh",
        script_dir / "run_microagent.sh",
    )
    python_bin = repo_root / ".venv" / "bin"
    python_bin.mkdir(parents=True)
    (python_bin / "python").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    (python_bin / "python").chmod(0o755)

    if with_settings:
        settings_dir = microagent_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(
            '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
            encoding="utf-8",
        )

    return repo_root


def _base_env(tmp_path: Path, log_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_stub_bun(bin_dir, log_path)
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }


def _env_only(tmp_path: Path, log_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_env_logging_stub_bun(
        bin_dir,
        log_path,
        (
            "DEEPSEEK_API_KEY",
            "ARK_API_KEY",
            "ARK_EMBEDDING_MODEL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
        ),
    )
    return {
        "HOME": os.environ["HOME"],
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
    }


def _write_required_local_env(repo_root: Path) -> None:
    local_env = repo_root / "data" / "agent-runtime" / "local.env"
    local_env.write_text(
        "\n".join(
            [
                "export DEEPSEEK_API_KEY=test-deepseek",
                "export ARK_API_KEY=test-ark",
                "export ARK_EMBEDDING_MODEL=test-embedding",
                "export ANTHROPIC_AUTH_TOKEN=test-anthropic",
                "export ANTHROPIC_BASE_URL=https://example.test",
                "export ANTHROPIC_DEFAULT_HAIKU_MODEL=haiku",
                "export ANTHROPIC_DEFAULT_SONNET_MODEL=sonnet",
                "export ANTHROPIC_DEFAULT_OPUS_MODEL=opus",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_microagent_script_acp_args_only_launch_bundle_runtime(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path)
    _write_required_local_env(repo_root)
    log_path = tmp_path / "calls.log"
    env = _base_env(tmp_path, log_path)

    result = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "run_microagent.sh"),
            "--acp",
            "--setting-sources",
            "project",
        ],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert log_path.read_text(encoding="utf-8") == (
        f"cwd {repo_root / 'src' / 'ragflow_lite' / 'microagent'}\n"
        "bun --silent run dev -- --acp --setting-sources project\n"
    )


def test_microagent_script_acp_args_source_local_env_for_agent_provider(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path)
    _write_required_local_env(repo_root)
    log_path = tmp_path / "calls.log"
    env = _env_only(tmp_path, log_path)

    result = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "run_microagent.sh"),
            "--acp",
            "--setting-sources",
            "project",
        ],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    log = log_path.read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=SET" in log
    assert "ANTHROPIC_BASE_URL=SET" in log
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=SET" in log
    assert "DEEPSEEK_API_KEY=SET" in log


def test_microagent_script_acp_args_work_when_home_is_empty(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path)
    _write_required_local_env(repo_root)
    log_path = tmp_path / "calls.log"
    env = {
        **_env_only(tmp_path, log_path),
        "HOME": "",
    }

    result = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "run_microagent.sh"),
            "--acp",
            "--setting-sources",
            "project",
        ],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "bun --silent run dev -- --acp --setting-sources project" in (
        log_path.read_text(encoding="utf-8")
    )


def test_microagent_script_dry_run_shows_full_demo_bootstrap(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path)
    _write_required_local_env(repo_root)
    log_path = tmp_path / "calls.log"
    env = {
        **_base_env(tmp_path, log_path),
        "MICRORAG_DEMO_DRY_RUN": "1",
        "DEEPSEEK_API_KEY": "test-deepseek",
        "ARK_API_KEY": "test-ark",
        "ARK_EMBEDDING_MODEL": "test-embedding",
        "ANTHROPIC_AUTH_TOKEN": "test-anthropic",
        "ANTHROPIC_BASE_URL": "https://example.test",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "haiku",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "sonnet",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "opus",
    }

    result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "run_microagent.sh")],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "agent setup:" in result.stdout
    assert "microagent bundle:" in result.stdout
    assert "agent settings:" in result.stdout
    assert "backend:" in result.stdout
    assert "ui: http://127.0.0.1:8001/agent" in result.stdout
    assert "agent command:" in result.stdout
    assert (
        f"agent cwd: {repo_root / 'data' / 'agent-runtime' / 'workspace'}"
        in result.stdout
    )
    assert "agent args: --acp --setting-sources project" in result.stdout
    old_runtime_label = "Reference " + "Claude " + "Code"
    assert old_runtime_label not in result.stdout


def test_microagent_script_requires_bundle_settings(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path, with_settings=False)
    _write_required_local_env(repo_root)
    log_path = tmp_path / "calls.log"
    env = _base_env(tmp_path, log_path)

    result = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "run_microagent.sh"),
            "--acp",
        ],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "missing" in result.stderr
    assert "src/ragflow_lite/microagent/.claude/settings.json" in result.stderr


def test_microagent_script_uses_bundle_settings_not_product_workspace_settings(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path, with_settings=True)
    _write_required_local_env(repo_root)
    product_workspace = repo_root / "data" / "agent-runtime" / "workspace"
    (product_workspace / ".claude").mkdir(parents=True)
    (product_workspace / ".claude" / "settings.json").write_text(
        '{"product":true}\n',
        encoding="utf-8",
    )
    log_path = tmp_path / "calls.log"
    env = {
        **_base_env(tmp_path, log_path),
        "MICRORAG_DEMO_DRY_RUN": "1",
    }

    result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "run_microagent.sh")],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (
        f"agent settings: {repo_root / 'src' / 'ragflow_lite' / 'microagent' / '.claude' / 'settings.json'}"
        in result.stdout
    )
