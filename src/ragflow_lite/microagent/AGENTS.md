# AGENTS.md

This file belongs to the bundled MicroAgent runtime source tree. It is not the
MicroRAG product conversation instruction source. Product conversation context
remains owned by `data/agent-runtime/workspace`.

## Bundle Scope

This directory is a pruned Bun/TypeScript runtime bundle copied into MicroRAG
for the local agent shell. Keep these notes focused on maintaining the bundled
runtime source tree. Product-facing agent identity, prompts, session context,
and workspace instructions belong under `data/agent-runtime/workspace`, not in
this bundle.

Do not restore repository-maintenance surfaces that were deliberately pruned
from the copy, including external repo metadata, generated dependency folders,
local state, documentation-site material, and hook-era maintenance files, unless
the MicroRAG runtime bundle plan is explicitly updated.

## Commands

Run commands from this directory with Bun.

```bash
bun install
bun run dev
bun run dev:inspect
echo "say hello" | bun run src/entrypoints/cli.tsx -p
bun run build
bun run build:vite
bun test
bun run lint
bun run lint:fix
bun run format
bun run check
bun run check:fix
bun run typecheck
bun run precheck
bun run check:bundle
bun run check:unused
bun run rcs
```

Keep `package.json` scripts aligned with retained files in the bundle. If a
script target is pruned, remove the script instead of leaving a dead command.

## Runtime Shape

- Runtime: Bun, ESM, TypeScript/TSX, React/Ink terminal UI.
- Build entry: `build.ts`, with `src/entrypoints/cli.tsx` as the CLI entry.
- Vite build path: `vite.config.ts` plus `scripts/post-build.ts`.
- Dev path: `scripts/dev.ts` injects `MACRO.*` defines before running the CLI.
- Feature flags are accessed through `feature("FLAG_NAME")` from `bun:bundle`
  and are controlled by build defaults or `FEATURE_*` environment variables.
- Generated output belongs in `dist/`, which is excluded from the copied bundle.

## Key Entrypoints

- `src/entrypoints/cli.tsx`: lightweight CLI entry that handles fast paths such
  as version, prompt dump, MCP modes, daemon modes, bridge modes, background
  session commands, and then loads the full CLI.
- `src/main.tsx`: Commander-based CLI definition and REPL/headless dispatch.
- `src/entrypoints/init.ts`: startup initialization.
- `src/query.ts` and `src/QueryEngine.ts`: streaming model turn loop and
  conversation orchestration.
- `src/screens/REPL.tsx`: Ink REPL surface for interactive sessions.
- `src/context.ts` and `src/utils/claudemd.ts`: runtime context and instruction
  discovery. Do not use these files to define MicroRAG product conversation
  identity; that lives in the product runtime workspace.

## Retained Packages

The bundle keeps the workspace packages needed by the local runtime, including
`packages/builtin-tools`, `packages/agent-tools`, `packages/mcp-client`,
`packages/acp-link`, `packages/remote-control-server`, the `packages/@ant/*`
runtime packages, and native helper packages such as `audio-capture-napi`,
`color-diff-napi`, `image-processor-napi`, `modifiers-napi`, and
`url-handler-napi`.

`node_modules` directories are excluded recursively. Reinstall dependencies in
the bundle when local runtime development needs them.

## Runtime Areas

- Tool registry: `src/tools.ts`, `src/Tool.ts`, `src/constants/tools.ts`, and
  `packages/builtin-tools/src/tools/`.
- ACP runtime: `src/services/acp/` and `packages/acp-link/`.
- Remote control runtime: `src/bridge/` and `packages/remote-control-server/`.
- UI runtime: `src/ink.ts`, `src/components/`, and `packages/@ant/ink/`.
- State runtime: `src/state/` and `src/bootstrap/state.ts`.
- Provider layer: `src/services/api/` and `src/utils/model/providers.ts`.

## Bundle Maintenance Notes

- Preserve `.claude/settings.json`, `.claude/skills`, and `.claude/agents` as
  runtime-bearing bundle material, but do not inspect or copy local state files
  such as settings-local files, credentials, caches, history, transcripts,
  projects, todos, or skill drafts.
- Keep changes scoped to this bundle when the task is a bundle cleanup. Launcher,
  Python settings, tests, contracts, and ignore rules are separate MicroRAG
  integration surfaces.
- Keep comments and docstrings sparse. Add Chinese explanatory text only when it
  captures a non-obvious runtime constraint.
