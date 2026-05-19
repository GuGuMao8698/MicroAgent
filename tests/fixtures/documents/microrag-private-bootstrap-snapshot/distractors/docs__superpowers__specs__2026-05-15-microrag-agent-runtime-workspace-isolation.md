# MicroRAG Agent Runtime Workspace Isolation

Date: 2026-05-15
Status: Draft design spec

This document specifies how MicroRAG should isolate the product-facing agent
runtime from the repository's developer-facing Claude Code configuration. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

MicroRAG must not use the repository root as the product agent runtime
workspace.

The repository root is a development workspace. It contains `CLAUDE.md`,
`.claude/`, and other files intended for humans and local coding agents working
on MicroRAG itself. The product-facing agent runtime must instead run from a
separate workspace owned by MicroRAG:

```text
data/agent-runtime/
  config/                         # CLAUDE_CONFIG_DIR
  workspace/                      # MICRORAG_AGENT_CWD
    CLAUDE.md                     # product agent instructions
    .claude/
      settings.json               # product agent project settings
      settings.local.json         # optional local-only override, gitignored
      skills/
        microrag-search/
          SKILL.md                # product agent retrieval skill
```

The first-stage startup boundary becomes:

```text
MicroRAG backend
-> AcpClient subprocess
-> CLAUDE_CONFIG_DIR=data/agent-runtime/config
-> cwd=data/agent-runtime/workspace
-> product-only CLAUDE.md / settings / skills
-> mcrag CLI
-> MicroRAG retrieval / answer services
```

This keeps product behavior independent from the developer's `~/.claude`
configuration and independent from the repository root's development-focused
Claude Code files.

## Context

The previous agent demo shell work added:

- `/agent` web shell;
- `/api/v0/agent/**` session and message endpoints;
- ACP client subprocess boundary;
- `mcrag retrieve`;
- a `microrag-search` skill under the repository `.claude/skills` tree.

That was enough to prove the UI/API/ACP shell shape, but it left one important
configuration ambiguity: if the product runtime starts with the repository root
as `MICRORAG_AGENT_CWD`, Claude Code may read the same
`CLAUDE.md`, `.claude/settings*.json`, skills, and memory that local developers
use while working on the repository.

That is not acceptable for the product agent. The product agent should not
inherit repository development rules such as code navigation guidance,
CONTRACTS.md maintenance rules, test commands, or local developer permissions.

## Goals

1. Keep product agent runtime configuration separate from developer Claude Code
   configuration.
2. Avoid reading the developer's real `~/.claude/settings.json`.
3. Avoid reading repository-root `CLAUDE.md` and repository-root `.claude`
   settings for product conversations.
4. Provide a product-only location for `CLAUDE.md`, `settings.json`, and
   `microrag-search` skill files.
5. Keep the first-stage runtime local-file based; do not introduce MCP.
6. Preserve the existing ACP stdio boundary and MicroRAG-owned UI/API shell.
7. Make the runtime source of settings verifiable through Claude Code status
   output and MicroRAG tests.
8. Keep the product runtime workspace generated or synchronized from
   source-controlled templates, not hand-maintained as an invisible local
   snowflake.

## Non-Goals

- Do not move the Claude Code runtime source into `src/ragflow_lite`.
- Do not use repository-root `.claude/settings.json` as product runtime
  settings.
- Do not require the product agent to read repository-root `CLAUDE.md`.
- Do not depend on the developer's `~/.claude/settings.json`.
- Do not commit secrets, user credentials, or local machine paths that are not
  intentionally part of the demo contract.
- Do not add MCP as part of this runtime isolation work.
- Do not redesign the agent UI, citation UI, or retrieval JSON shape in this
  spec.
- Do not make MicroRAG SQLite the conversation transcript source of truth.

## Settings Source Model

### Official Claude Code Behavior

Official Claude Code documentation defines settings precedence as:

```text
Managed policy
> CLI --settings
> .claude/settings.local.json
> .claude/settings.json
> ~/.claude/settings.json
```

Relevant official documentation:

- `https://code.claude.com/docs/en/settings`
- `https://code.claude.com/docs/en/cli-reference`
- `https://code.claude.com/docs/en/env-vars`
- `https://code.claude.com/docs/en/claude-directory`
- `https://code.claude.com/docs/en/commands`

Official docs also define `CLAUDE_CONFIG_DIR` as the way to override the default
Claude configuration directory. MicroRAG should use this to avoid the real
developer home config directory.

### Local Reference Runtime Behavior

The local reference runtime under `参考项目/claude-code` supports these settings
sources:

```text
userSettings
projectSettings
localSettings
flagSettings
policySettings
```

The local reference runtime merges them in this order:

```text
userSettings -> projectSettings -> localSettings -> flagSettings -> policySettings
```

The local reference runtime also supports:

```text
--setting-sources project,local
```

That option is the preferred first-stage guard for avoiding ordinary user
settings when the selected runtime supports it. `flagSettings` and
`policySettings` may still be present; the goal is to remove dependency on the
developer's home settings, not to bypass managed policy.

## Runtime Directory Layout

The product runtime should use:

```text
data/agent-runtime/config
data/agent-runtime/workspace
```

`data/agent-runtime/config` is passed as `CLAUDE_CONFIG_DIR`.

`data/agent-runtime/workspace` is passed as `MICRORAG_AGENT_CWD`.

The runtime workspace contains the product-facing agent files:

```text
data/agent-runtime/workspace/
  CLAUDE.md
  .claude/
    settings.json
    skills/
      microrag-search/
        SKILL.md
```

The repository-root files remain development-facing:

```text
CLAUDE.md
.claude/settings.local.json
.claude/skills/*
AGENTS.md
docs/
src/
tests/
```

The product runtime must not rely on those repository-root files being loaded.

## Source-Control Strategy

Runtime workspace files should not be edited only under `data/` as hidden local
state. They should be generated or synchronized from source-controlled
templates.

Preferred source layout:

```text
src/ragflow_lite/agent_runtime/
  CLAUDE.md
  settings.json
  skills/
    microrag-search/
      SKILL.md
```

At app startup or through a setup command, MicroRAG copies those files into:

```text
data/agent-runtime/workspace/
```

This keeps the runtime workspace reproducible while avoiding use of
repository-root `.claude`.

The copied runtime files are product assets, not developer instructions.
`AGENTS.md` and repository-root `CLAUDE.md` must not be copied into the product
runtime workspace.

## Product Agent Instructions

The product runtime `CLAUDE.md` should be short and product-focused.

It should say:

- the agent is MicroRAG's product conversation agent;
- it answers user questions using MicroRAG retrieval when document evidence is
  needed;
- it should use the `microrag-search` skill for document search;
- it must not expose the underlying runtime, ACP, command lines, internal paths,
  Claude Code branding, or developer workflow details;
- it must not invent evidence when retrieval fails.

It should not contain:

- repository development rules;
- test commands;
- `cx` navigation rules;
- AGENTS.md maintenance rules;
- CONTRACTS.md governance;
- implementation plans or commit instructions.

## Product Settings

The product runtime `settings.json` should be minimal.

It should allow only the commands needed for the first-stage product demo.
The first expected command surface is the MicroRAG retrieval CLI:

```text
mcrag retrieve --mode discorag
```

If console scripts are not reliably available to the runtime process, the skill
may use an absolute Python invocation derived from the configured project root
instead:

```text
<project_root>/.venv/bin/python -m ragflow_lite.cli.mcrag
```

When using the Python module path, the runtime environment must provide either:

- an editable install of MicroRAG; or
- `PYTHONPATH=<project_root>/src`.

The exact permission syntax must be validated against the selected Claude Code
runtime. Official Claude Code and the local reference runtime may differ in
small schema details.

## Skill Strategy

The product runtime should own its own `microrag-search` skill under:

```text
data/agent-runtime/workspace/.claude/skills/microrag-search/SKILL.md
```

The skill should instruct the agent to call MicroRAG DiscoRAG retrieval, not to
use repository development tools or MicroRAG's direct answer layer.

The skill should follow the same operational style as the `find-docs` skill:

- a clear trigger description;
- a short workflow;
- one deterministic command path;
- explicit stdout/stderr evidence rules;
- explicit setup-error handling;
- a short list of common mistakes.

The first-stage product skill is DiscoRAG-only. It should prefer this
deterministic CLI call:

```bash
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

If using absolute Python invocation:

```bash
<project_root>/.venv/bin/python -m ragflow_lite.cli.mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

The skill must tell the agent:

- stdout JSON is evidence;
- stderr diagnostics are not evidence;
- `setup error:` means MicroRAG is not ready;
- the agent must not invent evidence;
- `contexts` are retrieved evidence chunks;
- `blueprint` is DiscoRAG's answer planning constraints and evidence
  organization;
- standard mode is not part of the product skill;
- `mcrag answer` is not part of the product skill.

## Backend Configuration

The backend should set or document these runtime values:

```bash
CLAUDE_CONFIG_DIR=<project_root>/data/agent-runtime/config
MICRORAG_AGENT_CWD=<project_root>/data/agent-runtime/workspace
MICRORAG_AGENT_COMMAND=claude
MICRORAG_AGENT_ARGS="--acp --setting-sources project,local"
PYTHONPATH=<project_root>/src
```

If the chosen runtime does not support `--setting-sources`, MicroRAG should use:

```bash
CLAUDE_CONFIG_DIR=<project_root>/data/agent-runtime/config
MICRORAG_AGENT_ARGS="--acp"
```

and verify via `/status` that the real developer home settings are not loaded.

The current `MICRORAG_AGENT_ARGS` parser uses whitespace splitting. Therefore
first-stage args must avoid shell quoting requirements and inline JSON. Use real
files for settings instead of `--settings '{"json": ...}'`.

## Verification

Verification must prove both product behavior and configuration isolation.

Minimum checks:

1. Runtime workspace setup creates:
   - `data/agent-runtime/config`;
   - `data/agent-runtime/workspace/CLAUDE.md`;
   - `data/agent-runtime/workspace/.claude/settings.json`;
   - `data/agent-runtime/workspace/.claude/skills/microrag-search/SKILL.md`.
2. The generated product `CLAUDE.md` does not contain repository development
   guidance such as `AGENTS.md`, `CONTRACTS.md`, `cx`, pytest commands, git
   workflow, or code-review workflow.
3. The generated product `settings.json` is valid JSON and contains no secrets.
4. The generated product skill calls MicroRAG CLI and does not mention
   developer-only instructions.
5. The generated product skill is DiscoRAG-only and does not contain
   `--mode standard`.
6. The generated product skill does not contain `mcrag answer`.
7. `MICRORAG_AGENT_CWD` resolves to the runtime workspace, not repository root.
8. `CLAUDE_CONFIG_DIR` resolves to `data/agent-runtime/config`, not
   `~/.claude`.
9. Manual runtime verification runs `/status` and confirms settings sources do
   not include the real developer home settings.
10. The web UI can still load `/agent`.
11. `POST /api/v0/agent/sessions` starts ACP using the isolated cwd and config
   environment.
12. UI-visible strings still do not include `Claude Code`, `claude-code`,
    raw runtime cwd, command args, or transcript paths.

## Failure Handling

If the runtime workspace is missing, MicroRAG should fail clearly in product
terms:

```text
MicroRAG agent setup is incomplete. Runtime workspace is missing.
```

The UI should not expose:

- absolute internal command lines;
- raw ACP error messages;
- developer home config paths;
- raw traceback text;
- Claude Code branding.

If `/status` or equivalent manual validation shows that `~/.claude/settings.json`
or repository-root `.claude/settings.json` is loaded, the runtime isolation is
not complete and the product demo should not be considered ready.

## Open Questions

1. Should MicroRAG generate runtime workspace files automatically during app
   startup, or should it provide an explicit setup command such as
   `mcrag agent setup`?
2. Should the product runtime workspace live under `data/agent-runtime`, or
   should it be moved under a named app-data path outside the repository for
   packaging?
3. Should the first GUI skill action send a slash-style prompt such as
   `/microrag-search`, or a natural-language instruction asking the agent to use
   the skill?

## Acceptance Criteria

- Product ACP runtime no longer uses the repository root as cwd.
- Product ACP runtime no longer depends on repository-root `.claude/settings*`.
- Product ACP runtime no longer depends on real `~/.claude/settings.json`.
- Product runtime instructions, settings, and skills are reproducible from
  source-controlled templates.
- Product `microrag-search` skill exposes only DiscoRAG retrieval and does not
  expose `mcrag answer`.
- Manual `/status` verification can identify the loaded settings sources.
- The existing `/agent` UI and `/api/v0/agent/**` routes continue to work.
- The implementation has tests for generated workspace files, visible redaction,
  and backend runtime configuration.
