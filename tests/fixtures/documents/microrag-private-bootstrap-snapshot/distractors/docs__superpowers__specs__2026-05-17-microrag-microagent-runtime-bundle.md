# MicroRAG MicroAgent Runtime Bundle

Date: 2026-05-17
Status: Draft design spec

This document specifies the boundary for moving the local reference agent
runtime into the MicroRAG source tree as an internal runtime bundle named
`microagent`. It is planning material, not an active runtime contract. Active
contracts remain in `src/ragflow_lite/**/CONTRACTS.md` and should be updated
only after source-backed behavior lands.

## Decision

MicroRAG should copy the current local reference runtime from:

```text
参考项目/claude-code
```

into a MicroRAG-owned internal bundle directory:

```text
src/ragflow_lite/microagent
```

The bundle is a physical copy of the working runtime, not a thin adapter that
continues to run from `参考项目/claude-code`. After the migration, MicroRAG
runtime launchers and default configuration must point at the internal bundle.
The old reference path may remain as a local source snapshot during the
migration, but it must no longer be the active runtime target.

Implementation should begin by copying the whole source tree from
`参考项目/claude-code` into `src/ragflow_lite/microagent`, then pruning excluded
paths and cleaning explicitly named identity-bearing files in place. Do not
hand-build a new runtime skeleton by selectively recreating files.

The external name for this runtime is `microagent`. Product-facing scripts,
configuration names, status text, tests, and documentation should use
`microagent` or `MicroAgent`, not `claude-code`, `reference_claude_code`, or
`Reference Claude Code`.

The existing launcher should be renamed rather than replaced with an unrelated
entrypoint:

```text
scripts/run_reference_claude_code.sh
-> scripts/run_microagent.sh
```

The renamed launcher keeps the same role: it starts the bundled Bun runtime,
sources the local provider environment, supports dry-run/demo behavior, and
passes runtime arguments through to the underlying agent process.

## Context

The frontend and backend agent shell already communicate with the local
reference runtime through an ACP stdio subprocess. The current launcher is:

```text
scripts/run_reference_claude_code.sh
```

The launcher currently derives the repository root from its own path, defaults
the runtime directory to:

```text
参考项目/claude-code
```

and allows that default to be overridden with:

```text
MICRORAG_REFERENCE_CLAUDE_CODE_DIR
```

It also sources:

```text
data/agent-runtime/local.env
```

before checking provider environment variables or starting the runtime. This
ordering is part of the working runtime contract and must be preserved.

Current MicroRAG code also has default runtime-path references in:

```text
src/ragflow_lite/config/settings.py
src/ragflow_lite/agent_runtime/setup.py
```

Current MicroRAG code uses several related runtime knobs. The migration must
keep their responsibilities separate instead of replacing one old variable with
one vague new variable:

```text
MICRORAG_MICROAGENT_DIR   # bundle location for the copied Bun runtime
MICRORAG_AGENT_COMMAND    # command used by the backend ACP subprocess
MICRORAG_AGENT_ARGS       # argument string passed to the ACP subprocess
MICRORAG_AGENT_CWD        # product conversation workspace cwd
MICRORAG_AGENT_CONFIG_DIR # product runtime config directory
```

`MICRORAG_MICROAGENT_DIR` locates the runtime bundle. It is not the product
conversation workspace. `MICRORAG_AGENT_CWD` continues to locate the isolated
product workspace under `data/agent-runtime/workspace` unless a later
implementation deliberately changes that contract.

Existing active contracts and tests already enforce that raw runtime branding
such as `Claude Code` and `claude-code` must not leak through the product UI or
HTTP responses. This spec extends that rule to the runtime bundle layout and
launcher surface.

## Goals

1. Make the active agent runtime a MicroRAG-owned source-tree bundle under
   `src/ragflow_lite/microagent`.
2. Stop active launch and default configuration paths from pointing at
   `参考项目/claude-code`.
3. Rename the existing launcher to `scripts/run_microagent.sh` while preserving
   its current behavior.
4. Remove or replace copied files that expose the upstream/reference project
   identity and are not needed for runtime execution.
5. Preserve the working ACP stdio path, provider environment loading, product
   runtime workspace isolation, skills, session behavior, and pass-through
   argument behavior.
6. Keep the migration focused on physical packaging and external naming. Do not
   rewrite the agent runtime architecture.
7. Make the migration verifiable with static path checks, launcher dry-run
   checks, focused tests, and an ACP smoke check.
8. Copy `.claude/settings.json`, `.claude/skills/`, and `.claude/agents/`
   from the source runtime; do not recreate or regenerate them.
9. Keep `setup_agent_runtime()` scoped to product workspace/config/shim setup;
   do not use it as the mechanism that creates the bundled runtime tree.

## Non-Goals

- Do not rebuild the agent core in Python.
- Do not replace ACP stdio with MCP, HTTP, or a new protocol.
- Do not redesign the frontend agent shell.
- Do not change MicroRAG API schemas.
- Do not change provider secrets, provider models, or production dependency
  policy without a separate checkpoint.
- Do not rewrite the whole runtime source tree for full forensic provenance
  removal.
- Do not claim the internal runtime has been behaviorally reimplemented by
  MicroRAG.
- Do not remove legal attribution files if later investigation finds that they
  are required for license compliance.
- Do not make the product SQLite session index the conversation transcript
  source of truth.
- Do not preserve `scripts/run_reference_claude_code.sh` as an active alias
  unless a later checkpoint explicitly asks for a compatibility period.

## Target Layout

The first-stage target layout is a minimum expected preserved layout after the
source tree is copied and pruned:

```text
src/ragflow_lite/
  microagent/
    README.md (optional, MicroRAG-owned if present)
    CLAUDE.md (optional copied internal runtime doc, cleaned if present)
    AGENTS.md (optional copied internal runtime doc, cleaned if present)
    package.json
    bun.lock
    bunfig.toml
    tsconfig.base.json
    tsconfig.json
    biome.json
    vite.config.ts
    build.ts
    knip.json
    src/
    packages/
    scripts/
    vendor/
    .claude/settings.json
    .claude/skills/
    .claude/agents/
```

`src/ragflow_lite/microagent` is intentionally a Bun/TypeScript runtime bundle
inside the Python source tree. MicroRAG Python code should treat it as a runtime
asset directory, not as an importable Python subpackage.

The bundle root may include a short MicroRAG-owned `README.md` explaining the
local purpose of the directory. If present, it must be newly authored and short;
it must not copy or lightly edit the upstream README text.

Suggested README content:

```markdown
# MicroAgent Runtime Bundle

This directory contains the bundled local agent runtime used by MicroRAG's
agent shell. Product code should launch it through `scripts/run_microagent.sh`
or the MicroRAG agent runtime wiring, not by invoking files here directly.
```

## Copy Policy

### Copy First, Then Prune And Clean

The migration should use this copy-first algorithm:

1. Copy the whole source runtime tree from `参考项目/claude-code` into
   `src/ragflow_lite/microagent`.
2. Delete known exclusions and local/generated state.
3. Clean copied identity-bearing files in place.

Do not assemble the bundle by hand from a newly created skeleton. The baseline
is the working source tree plus explicit pruning.

### Must Copy From Source

The migration must copy these runtime-bearing source, package, build, and vendor
paths from the source runtime:

```text
src/
packages/
scripts/
vendor/
package.json
bun.lock
biome.json
build.ts
vite.config.ts
tsconfig.base.json
tsconfig.json
bunfig.toml
knip.json
```

The `.claude` runtime subpaths are handled by the stricter rule below: they must
be copied from the source runtime, not regenerated.

`bun run dev` depends on `scripts/dev.ts` and `scripts/defines.ts`.
The runtime entry path reaches `src/entrypoints/cli.tsx` and loads
`src/utils/performanceShim.js` before the full CLI. Build and post-build support
also rely on files such as `build.ts`, `scripts/post-build.ts`,
`scripts/vite-plugin-feature-flags.ts`, `scripts/vite-plugin-import-meta-require.ts`,
and `vite.config.ts`.

`vendor/` must be copied because runtime/build assets such as
`vendor/audio-capture/` are part of the source bundle. `vendor/audio-capture-src/`
is an open classification item: retain it if implementation needs native addon
rebuild support; otherwise document why it was pruned.

### Copy Then Clean

Copy these files from the source runtime, then clean them in place:

```text
package.json
CLAUDE.md
AGENTS.md
```

`package.json` is required for local execution and `bun run dev`, but it must be
reviewed for source-project metadata such as repository URLs, homepage, bugs,
funding, old package names, and bin names such as `ccb`, `ccb-bun`, or
`claude-code-best`. Preserve runtime scripts needed by MicroAgent.

`CLAUDE.md` and `AGENTS.md`, if present in the source runtime, should be copied
into the bundle root as internal runtime docs, then cleaned of stale
source-project framing, external links, outdated commands, and duplicate
identity wording. Do not treat either file as the product conversation
instruction source.

### Preserve By Default

Tooling and build-control dotfiles that do not expose strong project identity
should be preserved by default because the bundled runtime may rely on them:

```text
.tool-versions
.dockerignore
.editorconfig
.npmrc
.mintignore
bunfig.toml
bun.lock
tsconfig.base.json
tsconfig.json
biome.json
knip.json
```

Only remove one of these files after inspecting it and proving that it is not
needed for local execution, build behavior, formatting, or dependency
resolution, or that it contains unsafe local/private configuration.

The implementation pass must verify these lists against the current source tree
before pruning. If the runtime requires another top-level file, preserve it and
record why it is needed.

### `.claude` Copy Boundary

The reference runtime currently expects some `.claude` subpaths to exist. These
runtime-bearing `.claude` subpaths must be copied from the source runtime:

```text
参考项目/claude-code/.claude/settings.json
参考项目/claude-code/.claude/skills/
参考项目/claude-code/.claude/agents/
```

into `src/ragflow_lite/microagent/.claude/`:

```text
.claude/settings.json
.claude/skills/
.claude/agents/
```

Do not recreate, regenerate, or hand-author replacement content for those three
paths during this migration. Copy them first, then inspect the copied content
for secrets, machine-local absolute paths, local-only permissions, and old
reference-runtime names. If unsafe content is found, report the exact risk and
make the smallest cleanup needed in the copied file or subtree; do not replace
the subtree with a newly designed equivalent.

`skills/` and `agents/` must be copied as runtime assets. During
implementation, remove identity-heavy README files, examples, caches, or docs
from those copied subtrees only after confirming they are not needed by the
working runtime.

Do not copy local-only or generated runtime state under `.claude`, including:

```text
.claude/settings.local.json
.claude/.credentials*
.claude/.cache/
.claude/cache/
.claude/history/
.claude/transcripts/
.claude/projects/
.claude/todos/
```

If the source tree contains another `.claude` state directory not listed here,
classify it before copying. The default is to exclude local state and copy only
runtime configuration, skills, and agents needed for deterministic startup.

`.claude/skills/.drafts/` is an open classification item. It is inside a
must-copy skills tree, but implementation should decide whether this hidden
draft bucket is useful runtime material or local working residue before final
acceptance.

### Exclude

The migration must not copy nested repository state, generated dependencies,
or upstream project management surfaces:

```text
.git/
.github/
.vscode/
.husky/
.deepeval/
dist/
node_modules/
docs/
spec/
tests/
teach-me/
```

The migration should exclude or replace strong identity, GitHub presentation, or
contribution-facing files that are not needed to run the bundled runtime:

```text
README.md
README_EN.md
SECURITY.md
DEV-LOG.md
Friends.md
codecov.yml
contributors.svg
.impeccable.md
docs.json
mint.json
```

`CLAUDE.md` and `AGENTS.md` from the reference runtime may be copied into the
MicroRAG bundle as part of moving the runtime body. If copied, they live at the
bundle root as internal runtime docs. They must be reviewed and cleaned like
other copied identity-bearing files: remove stale source-project framing,
replace external-facing names with MicroAgent/MicroRAG wording where
appropriate, and keep only instructions that are still relevant to the bundled
runtime.

Do not assume these copied files become the product conversation instruction
source. Product conversation behavior instructions should continue to be owned
by the generated product runtime workspace under:

```text
data/agent-runtime/workspace
```

The implementation pass must inspect the current `agent_runtime/setup.py`
behavior before deciding whether a source template needs to be created,
renamed, or left untouched. Do not introduce a new instruction-ownership layer
only to satisfy this migration.

### Legal Files

The initial shallow investigation did not find top-level `LICENSE`, `NOTICE`,
`COPYING`, or `PATENTS` files in `参考项目/claude-code`. The implementation pass
must still check for legal files before copying.

If legal files exist, they must be handled separately from brand cleanup. Do not
delete or rewrite required license or attribution files only because they expose
upstream identity. Preserve the minimum legally required attribution in the
bundle or in a MicroRAG-controlled attribution file.

## Launcher Migration

Rename:

```text
scripts/run_reference_claude_code.sh
```

to:

```text
scripts/run_microagent.sh
```

The renamed launcher must:

1. Resolve the repository root from the script location.
2. Default the runtime directory to `src/ragflow_lite/microagent`.
3. Preserve pass-through behavior for arguments, including ACP invocations such
   as `--acp --setting-sources project`.
4. Source `data/agent-runtime/local.env` before checking provider environment
   variables or starting the runtime.
5. Preserve the required environment variable checks unless a later runtime
   investigation proves a variable is obsolete.
6. Preserve `MICRORAG_AGENT_CWD`, `CLAUDE_CONFIG_DIR`, and child `PATH` setup.
7. Replace user-visible text such as `Reference Claude Code` with `MicroAgent`.
8. Keep dry-run behavior available through `MICRORAG_DEMO_DRY_RUN=1`.
9. Fail with MicroAgent-oriented error text when the internal bundle or
   `node_modules` is missing.
10. Use the same `MICRORAG_AGENT_ARGS` value for dry-run reporting and real
    launch behavior.

The old environment override:

```text
MICRORAG_REFERENCE_CLAUDE_CODE_DIR
```

should be replaced with:

```text
MICRORAG_MICROAGENT_DIR
```

No compatibility alias is required in the first implementation unless tests or
current code reveal an active caller outside the repository that must be
preserved.

### Environment Precedence

Use this first-stage precedence:

1. `MICRORAG_MICROAGENT_DIR`, when set, overrides the bundle directory used by
   `scripts/run_microagent.sh`.
2. Otherwise, `scripts/run_microagent.sh` uses
   `<repo>/src/ragflow_lite/microagent`.
3. The launcher exports `MICRORAG_AGENT_COMMAND` only when the backend/demo path
   needs to start the ACP subprocess through the renamed script. The value
   should point to `scripts/run_microagent.sh`, not to `claude`.
4. `MICRORAG_AGENT_ARGS` remains the argument string passed to the ACP
   subprocess. Its default should stay `--acp --setting-sources project` unless
   a later implementation deliberately revises that contract. The no-args live
   path must not print one args source in dry-run and execute another hard-coded
   args source.
5. `MICRORAG_AGENT_CWD` remains the product conversation workspace cwd. It
   should default to `data/agent-runtime/workspace`, not to the MicroAgent
   bundle directory, unless a focused implementation check proves the current
   ACP transport requires the runtime bundle as cwd.
6. `MICRORAG_AGENT_CONFIG_DIR` remains the product config directory and should
   default to `data/agent-runtime/config`.

If implementation proves the current code uses `agent_cwd` for both runtime
process cwd and product conversation cwd, split or document that behavior before
changing defaults. Do not silently point user conversation state at the copied
source bundle.

If the launcher needs to `cd` into `src/ragflow_lite/microagent` to start Bun,
that cwd is the runtime process cwd only. `MICRORAG_AGENT_CWD` still names the
separate product conversation workspace under `data/agent-runtime/workspace`.

## MicroRAG Runtime Wiring

Update active runtime-bundle paths and backend command defaults in:

```text
src/ragflow_lite/config/settings.py
src/ragflow_lite/agent_runtime/setup.py
```

The default bundle location should become:

```text
src/ragflow_lite/microagent
```

The runtime path override should use:

```text
MICRORAG_MICROAGENT_DIR
```

Backend settings should also be reviewed for `MICRORAG_AGENT_COMMAND`. If the
backend still defaults to `claude`, the migration should either default it to
the renamed launcher or explicitly prove that the launcher is injected before
the backend ACP subprocess starts. A successful migration cannot leave a normal
backend path that bypasses `src/ragflow_lite/microagent`.

The current implementation mismatches to eliminate are:

- `Settings.agent_command` defaulting to `claude`;
- `Settings.default()` defaulting agent cwd to `参考项目/claude-code`;
- `default_agent_runtime_paths()` defaulting workspace to `参考项目/claude-code`;
- the launcher printing `MICRORAG_AGENT_ARGS` in dry-run while the live no-args
  Bun path executes hard-coded args.

Do not use `agent_cwd` wording ambiguously in new code or tests. After the
migration, tests should distinguish:

- runtime bundle directory: `src/ragflow_lite/microagent`;
- product conversation cwd: `data/agent-runtime/workspace`;
- product config directory: `data/agent-runtime/config`;
- backend ACP command: the renamed launcher or an explicit command that starts
  the renamed bundle.

`setup_agent_runtime()` may continue to prepare the product workspace, config
directory, and local shims. It must not become the mechanism that creates or
populates `src/ragflow_lite/microagent`; bundle creation is a source-tree copy
and prune operation.

References to `MICRORAG_REFERENCE_CLAUDE_CODE_DIR`,
`run_reference_claude_code`, and `参考项目/claude-code` should be removed from
active runtime paths and tests. Historical docs may mention the old path only
when clearly describing pre-migration context.

Active contract files should be updated only after implementation lands and
verification proves the new behavior:

```text
src/ragflow_lite/infrastructure/CONTRACTS.md
```

Update `src/ragflow_lite/api/CONTRACTS.md` only if product-visible API wording,
branding redaction, or route behavior changes.

## Identity Cleanup Boundary

This migration cleans external and copied-file identity surfaces. It does not
promise a full source-wide identity rewrite.

The implementation must remove or replace:

- copied upstream README content;
- copied upstream repo metadata;
- copied project instructions such as `AGENTS.md` and `CLAUDE.md` when they
  contain stale source-project framing;
- launcher user-visible text that says `Reference Claude Code`;
- active MicroRAG config names that say `reference_claude_code`;
- active paths that point at `参考项目/claude-code`.

The implementation may leave internal runtime source strings such as class
names, protocol names, or model-prompt identity strings for a separate prompt
identity pass unless they are directly exposed through the product launcher,
HTTP API, or UI shell.

If the implementation finds model-visible identity strings in the bundle that
already have a dedicated spec, keep this migration focused and link the follow-up
rather than mixing prompt behavior changes into the physical packaging task.

## Packaging And Tooling Boundary

Because `src/ragflow_lite/microagent` is a TypeScript/Bun project inside the
Python package tree, implementation must verify that ordinary Python tooling
does not accidentally treat it as Python source.

The implementation should check:

1. Whether `pyproject.toml` package discovery includes non-Python data under
   `src/ragflow_lite/microagent`.
2. Whether `ruff`, `pytest`, or import-time package initialization traverses the
   bundle unexpectedly.
3. Whether the repository `.gitignore` or package build config needs an entry to
   exclude `node_modules`, `dist`, or cache files under the new bundle path.

The first-stage target is local development correctness. Shipping the Bun
runtime inside a Python wheel or source distribution is a separate release
packaging decision and should not be assumed unless explicitly verified.

## Test And Verification Plan

### Static Checks

After implementation, run checks equivalent to:

```bash
rg -n "run_reference_claude_code|reference_claude_code|MICRORAG_REFERENCE_CLAUDE_CODE_DIR|Reference Claude Code" scripts src tests src/ragflow_lite/infrastructure/CONTRACTS.md
rg -n "参考项目/claude-code" scripts src tests
rg -n "MICRORAG_AGENT_ARGS|agent_args" scripts src tests
find src/ragflow_lite/microagent \( -name .git -o -name node_modules -o -name dist -o -path '*/.claude/settings.local.json' -o -path '*/.claude/.credentials*' -o -path '*/.claude/cache*' -o -path '*/.claude/history*' -o -path '*/.claude/transcripts*' -o -path '*/.claude/projects*' -o -path '*/.claude/todos*' \) -print
```

Expected results:

- no active runtime code or script references to the old launcher name;
- no active runtime code defaulting to `参考项目/claude-code`;
- `MICRORAG_AGENT_ARGS` remains visible in launcher/backend/test coverage;
- no nested `.git`, `node_modules`, `dist`, or copied `.claude` local state in
  the copied bundle.

Historical planning docs may still mention old paths. Do not treat matches in
`docs/superpowers/specs`, archived plans, or earlier rollout notes as active
runtime failures unless they are presented as current instructions.

`rg -n "Claude Code|claude-code"` may still find internal runtime-source
strings. The implementation report must classify those hits as either:

- external/product-facing and fixed; or
- internal runtime-source identity left for a separate prompt identity pass.

### Focused Tests

Update and run the nearest existing tests:

```bash
pytest tests/unit/test_microagent_script.py
pytest tests/unit/agent_runtime/test_setup.py
pytest tests/unit/api/test_acp_wiring.py
pytest tests/unit/cli/test_mcrag_cli.py
pytest tests/integration/api/test_ui_shell.py
```

`tests/unit/test_reference_claude_code_script.py` should be renamed or replaced
by `tests/unit/test_microagent_script.py` as part of the launcher rename.
`tests/helpers/agent_runtime.py` should be updated before dependent API,
integration, and CLI tests are trusted.

Expected coverage after update:

- `scripts/run_microagent.sh` launches from `src/ragflow_lite/microagent`;
- `data/agent-runtime/local.env` is sourced before provider checks;
- dry-run output uses `MicroAgent` naming;
- missing bundle or missing `node_modules` errors use MicroAgent naming;
- `default_agent_runtime_paths()` and related setup helpers use
  `MICRORAG_MICROAGENT_DIR` for bundle location and no longer depend on
  `MICRORAG_REFERENCE_CLAUDE_CODE_DIR`;
- `MICRORAG_AGENT_ARGS` stays the default ACP argument source and is used by the
  real launch path;
- backend startup cannot bypass `src/ragflow_lite/microagent` through a default
  `claude` command;
- API and UI shell still reject raw runtime branding in product responses.

### Runtime Smoke

Run a dry-run launcher check:

```bash
MICRORAG_DEMO_DRY_RUN=1 bash scripts/run_microagent.sh
```

Expected result:

- output names `MicroAgent`;
- output shows the runtime directory under `src/ragflow_lite/microagent`;
- output does not instruct users to run the old launcher.

Run an ACP startup smoke when the local environment is available:

```bash
bash scripts/run_microagent.sh --acp --setting-sources project
```

Expected result:

- the process starts from the internal bundle directory;
- the ACP child inherits provider environment from
  `data/agent-runtime/local.env`;
- the existing agent shell can still complete the minimal
  `initialize -> session/new -> session/prompt -> session/update` flow.

Also verify the local `mcrag` shim remains usable after runtime setup:

```bash
command -v mcrag
mcrag --help
```

## Acceptance Criteria

The migration is complete when:

1. `src/ragflow_lite/microagent` exists and contains the working runtime bundle.
2. The bundle is produced by copying the source tree into
   `src/ragflow_lite/microagent` and then pruning/cleaning the explicitly listed
   files; it is not a hand-built wrapper or adapter.
3. The bundle excludes `.git`, `.github`, `node_modules`, `dist`, upstream docs,
   tests/spec/demo docs, local `.claude` state, and upstream README files.
4. `.claude/settings.json`, `.claude/skills/`, and `.claude/agents/` are copied
   from the source runtime.
5. `package.json`, `CLAUDE.md`, and `AGENTS.md`, if retained, are copied then
   cleaned in place; `CLAUDE.md` and `AGENTS.md` remain internal runtime docs,
   not the product conversation instruction source.
6. The preserve-by-default dotfiles and config files remain unless the
   implementation report explicitly justifies removing one:
   `.tool-versions`, `.dockerignore`, `.editorconfig`, `.npmrc`, `.mintignore`,
   `bunfig.toml`, `bun.lock`, `tsconfig.base.json`, `tsconfig.json`,
   `biome.json`, and `knip.json`.
7. The bundle contains a MicroRAG-owned README or no README; it does not contain
   the upstream README text.
8. `scripts/run_microagent.sh` is the active launcher.
9. `scripts/run_reference_claude_code.sh` is no longer present as the active
   launcher.
10. Active runtime-bundle defaults point to `src/ragflow_lite/microagent`, while
   product conversation cwd defaults remain under `data/agent-runtime/workspace`
   unless implementation explicitly proves a different cwd split is required.
11. Active runtime overrides use `MICRORAG_MICROAGENT_DIR`.
12. `MICRORAG_AGENT_ARGS` remains the ACP args source and is used by real launch,
   not only dry-run output.
13. `setup_agent_runtime()` is not used to create or populate the bundled
   runtime tree.
14. Focused tests pass after being updated for the new path and names.
15. Dry-run output proves the launcher targets the internal bundle.
16. The implementation report separates verified behavior from any unverified
    full ACP/provider smoke.

## Open Implementation Notes

- Current investigation did not find `scripts/run_agent_demo.sh` in this
  checkout. Do not plan around it unless a later search finds it.
- Current investigation found only two files under
  `src/ragflow_lite/agent_runtime`: `__init__.py` and `setup.py`. The migration
  should not invent a large Python runtime framework unless implementation
  proves it is required.
- The current launcher has no wrapper-owned `--version` branch. If `--version`
  is needed as a verification proof, add it deliberately and test it; do not
  assume it already exists.
- Existing docs under `docs/superpowers/specs` are planning artifacts. They may
  mention the old runtime path as historical context, but active contracts
  should reflect the new path only after implementation lands.

## User-Facing Summary

本阶段要做的是把现在跑通的 `参考项目/claude-code` 运行时本体复制到
`src/ragflow_lite/microagent`，让它成为 MicroRAG 内部的 `MicroAgent`
runtime bundle。旧启动脚本不是另起炉灶，而是改名为
`scripts/run_microagent.sh` 并指向新内部目录。实施方式必须是先整树复制，
再 prune / clean；`.claude/settings.json`、`.claude/skills/`、
`.claude/agents/` 必须从源 runtime 复制，不能重建。复制时要清理 `.git`、
upstream README、GitHub 模板、docs、tests/spec/demo 文档、node_modules、
dist、本地 `.claude` 状态等不该进入 MicroRAG runtime bundle 的文件。
第一阶段只做物理迁移、外层改名和身份暴露面清理，不重写 agent core，
也不改变 ACP stdio 对接方式。
