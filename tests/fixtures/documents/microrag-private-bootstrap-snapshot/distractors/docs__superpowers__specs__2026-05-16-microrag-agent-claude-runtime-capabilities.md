# MicroRAG Agent Claude Runtime Capabilities

Date: 2026-05-16
Status: Draft design spec, awaiting user approval

This document specifies how the MicroRAG ACP frontend should expose Claude
Code-backed skill, memory, subagent, slash command, and shell/tool capabilities.
It is planning material, not an active runtime contract. Active contracts
remain in `src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

MicroRAG must reuse Claude Code's existing runtime capabilities instead of
rebuilding them in the MicroRAG frontend or backend.

The first-stage capability boundary is:

```text
MicroRAG Web UI
-> MicroRAG backend ACP adapter
-> Claude Code ACP stdio runtime
-> Claude Code command / skill / memory / AgentTool mechanisms
-> MicroRAG product runtime workspace
-> MicroRAG skill
-> mcrag CLI
```

MicroRAG owns the product shell, session metadata, event redaction, and UI
presentation. Claude Code owns command discovery, skill loading, memory
injection, subagent dispatch, shell/tool permissions, transcript persistence,
and agent execution.

MCP is explicitly out of scope for this implementation stage. The design may
preserve a future extension point, but no MCP server setup, MCP UI, MCP skill
loading, or MCP command lifecycle should be implemented as part of this spec.

## Investigation Basis

The local investigation of `参考项目/claude-code` found these current-code
behaviors:

- The remote `/` menu is a lightweight picker over ACP
  `available_commands_update`. Selecting a command only pre-fills input; real
  execution still happens through normal prompt submission.
- `available_commands_update` carries a small UI-safe command shape:
  `name`, `description`, and optional `input.hint`. It does not carry command
  provenance such as `skill`, `plugin`, or `built-in`.
- Slash command execution is handled inside Claude Code by
  `processUserInput()` and `processSlashCommand()`, not by the web UI.
- Skills are normalized into prompt-type `Command` objects. Sources include
  directory skills, plugin skills, bundled skills, and built-in plugin skills.
  The reference runtime also has MCP-backed skill paths, but those are observed
  background only and are not part of this stage's product contract.
- The system init surface exposes command, skill, agent, and plugin names, but
  memory content is injected through prompt builders and attachment channels,
  not through the public command list.
- Memory is a file-backed prompt and attachment system. It is governed by
  environment variables, settings, prompt builders, nested memory attachments,
  and an optional background extraction path.
- Subagents are driven primarily by Claude Code's `AgentTool` machinery. Agent
  definitions may carry model, permission mode, tools, hooks, skills, memory,
  isolation, background execution, and max-turn settings.
- The local CLI has rich task, subagent, skill, and tool activity UI, but the
  chosen ACP stdio path does not expose an equivalent first-class
  skill/subagent activity stream. MicroRAG demo activity must therefore be a
  sanitized adapter-derived product surface.
- The local reference fork has feature-flagged fork-subagent behavior. Any
  fork-specific details in this spec apply to the local reference runtime, not
  necessarily to upstream Claude Code semantics.

Key local reference files from the investigation:

```text
参考项目/claude-code/packages/remote-control-server/web/components/chat/ChatInput.tsx
参考项目/claude-code/packages/remote-control-server/web/components/chat/CommandMenu.tsx
参考项目/claude-code/src/services/acp/agent.ts
参考项目/claude-code/src/services/acp/bridge.ts
参考项目/claude-code/src/utils/processUserInput/processUserInput.ts
参考项目/claude-code/src/utils/processUserInput/processSlashCommand.tsx
参考项目/claude-code/src/commands.ts
参考项目/claude-code/src/skills/loadSkillsDir.ts
参考项目/claude-code/src/memdir/memdir.ts
参考项目/claude-code/src/utils/attachments.ts
参考项目/claude-code/src/components/messages/UserCommandMessage.tsx
参考项目/claude-code/packages/builtin-tools/src/tools/SkillTool/SkillTool.ts
参考项目/claude-code/packages/builtin-tools/src/tools/SkillTool/UI.tsx
参考项目/claude-code/packages/builtin-tools/src/tools/AgentTool/AgentTool.tsx
参考项目/claude-code/packages/builtin-tools/src/tools/AgentTool/runAgent.ts
参考项目/claude-code/packages/builtin-tools/src/tools/AgentTool/loadAgentsDir.ts
```

## Goals

1. Expose Claude Code-backed slash commands in the MicroRAG ACP frontend
   without scanning or executing commands in the frontend.
2. Preserve Claude Code's skill discovery, skill prompt loading, and
   skill-to-command conversion.
3. Preserve Claude Code's memory loading, memory prompt injection, nested
   memory attachments, and memory write boundaries.
4. Preserve Claude Code's subagent and fork-agent execution machinery.
5. Preserve Claude Code's shell/tool permission and execution rules.
6. Keep MicroRAG's product runtime isolated in the product runtime workspace
   defined by the runtime-workspace-isolation spec.
7. Keep the existing MicroRAG skill path centered on `mcrag retrieve` and, when
   needed, `mcrag answer`.
8. Show visible product-safe activity for skill, subagent, and tool invocation
   during demos.
9. Keep MicroRAG UI wording, event redaction, and recoverable error display
   product-owned.
10. Make the design testable through static checks, adapter tests, and manual
   ACP conversation checks.

## Non-Goals

- Do not implement MCP in this stage.
- Do not build a native MicroRAG command registry to replace Claude Code
  commands.
- Do not build a native MicroRAG skill loader.
- Do not parse `.claude/skills/**/SKILL.md` in the frontend.
- Do not build a MicroRAG memory database or memory injection engine.
- Do not copy Claude Code's memory content into MicroRAG SQLite.
- Do not build a native MicroRAG subagent runtime.
- Do not directly expose `AgentTool` internals as product API schema.
- Do not make MicroRAG SQLite the source of conversation truth.
- Do not route first-stage work through MCP, even though the reference runtime
  contains MCP-related code paths.
- Do not expose raw Claude Code runtime details, command lines, cwd, transcript
  paths, stderr, traceback text, JSON-RPC internals, or unredacted error
  messages in the UI.

## Capability Contracts

### Slash Command Surface

The MicroRAG frontend should treat slash commands as runtime-provided
suggestions.

The expected UI flow is:

```text
User types "/"
-> frontend opens command picker
-> picker reads latest backend-provided command summaries
-> user selects a command
-> frontend pre-fills "/<command-name> "
-> user submits message
-> backend forwards normal prompt to ACP runtime
-> Claude Code runtime parses and executes slash command
```

The frontend must not execute a slash command directly when a command is
selected. Selection is a text-editing operation only.

The backend should keep a UI-safe command summary list derived from ACP runtime
events:

```text
name
description
input_hint optional
updated_at
source = runtime
```

The UI may use simple prefix matching by command name. Fuzzy ranking,
source-aware ranking, or custom command precedence is not required in this
stage.

If the runtime has not sent command summaries yet, the UI should show an empty
or loading command state instead of scanning local files.

### Skill Surface

Claude Code remains the skill runtime.

MicroRAG should provide product skill files through the isolated product
runtime workspace, as defined by the runtime-workspace-isolation spec. The
frontend and backend should not parse skill frontmatter to decide behavior.

The first-stage product skill remains a Claude Code skill that guides the agent
to call MicroRAG through the deterministic local CLI:

```text
mcrag retrieve --json
mcrag answer --json
```

The normal external-agent path should prefer retrieval-only use. Direct
MicroRAG answering stays available for debugging, direct answer workflows, and
future RAG evaluation.

The UI may display skill names and descriptions only when those names and
descriptions arrive through runtime command/skill metadata. It must not render
full `SKILL.md` bodies as product UI content.

For demo clarity, the UI must make skill invocation visible. Because the
verified ACP stdio path does not expose a native `skill_started` or
`skill_finished` event, these states are MicroRAG-derived UI states, not Claude
Code protocol enums:

```text
skill_command_dispatched
skill_permission_pending
skill_running
skill_completed
skill_failed
```

The adapter may derive them from:

```text
slash command submission with a known command name
permission_request for SkillTool
tool_call / tool_call_update for SkillTool when present
agent_message_chunk text derived from skill_progress
terminal tool_call_update status
```

If the only available evidence is flattened progress text, the backend should
create a sanitized activity row instead of leaving the demo UI silent. The row
must be labeled as product activity, for example `MicroRAG skill running`, and
must not expose raw skill file paths, raw tool input, or runtime internals.

### Memory Surface

Claude Code remains the memory runtime.

MicroRAG should not attempt to reproduce memory recall, nested memory loading,
memory extraction, or memory prompt assembly.

The UI may expose memory as a product capability state, for example:

```text
memory enabled
memory unavailable
memory runtime error
```

The UI should not display raw memory files by default. If a later product
decision adds memory viewing or editing, that must be a separate spec because
it changes privacy, permissions, and product UX.

MicroRAG SQLite may store UI metadata about a session, but it must not store a
second copy of memory content or transcript history.

### Subagent And Task Surface

Claude Code remains the subagent runtime.

MicroRAG should expose subagents through sanitized activity derived from runtime
events, not by constructing its own subagent execution engine.

The local CLI's `TaskListV2`, `BackgroundTaskStatus`,
`AsyncAgentDetailDialog`, grouped agent progress rows, and spinner tree are
evidence of Claude Code runtime semantics. They are not directly reusable
frontend payloads on the verified ACP stdio path.

On the verified ACP stdio path:

- `tool_call` for `Agent` or `Task` is reliable enough to derive
  `subagent_started`.
- `tool_call_update` with terminal status is reliable enough to derive
  `subagent_completed` or `subagent_failed`.
- `agent_progress` can arrive only as flattened `agent_message_chunk` text, so
  `subagent_running` is advisory and must be derived from an active tool call
  plus progress text, not from a first-class ACP running state.
- structured `task_state` exists in adjacent runtime code, but is not a
  dependable ACP stdio live-session input for this stage.

The first-stage frontend should support these visible states when the backend
can derive them from ACP/runtime hints:

```text
subagent started
subagent running
subagent completed
subagent failed
subagent cancelled
```

The UI should not expose internal fields such as exact agent definition paths,
tool filters, raw permission modes, transcript subdirectories, or fork
implementation flags.

Fork-specific behavior should be treated as local-reference-runtime behavior.
Do not write product copy that promises a stable upstream Claude Code fork
semantic.

### Shell And Tool Surface

Claude Code remains the shell/tool permission runtime.

MicroRAG should not add a separate browser-side shell launcher or backend
shell endpoint for this stage. If the agent uses shell/tool capabilities, those
actions should pass through Claude Code's existing permission and tool
execution rules.

The UI may show a sanitized activity state such as:

```text
tool started
tool running
tool waiting for permission
tool completed
tool failed
tool cancelled
```

The UI must not show raw commands, raw stdout/stderr, or runtime paths unless a
later explicit product decision marks a specific field as UI-safe.

### MCP Boundary

MCP is not implemented in this stage.

The implementation must not add:

```text
MCP server setup UI
MCP server configuration templates
MCP skill discovery in product runtime setup
MCP command picker grouping
MCP tool call visualization
MicroRAG-owned MCP adapters
```

The code may leave existing reference-runtime MCP behavior untouched. It should
not delete or patch Claude Code MCP internals merely to enforce this product
scope. The product scope boundary is: MicroRAG does not intentionally configure,
surface, or depend on MCP for this stage.

## Demo Activity Stream

The frontend must visibly show that skills, subagents, and tools are being
invoked. This is required for demos so a user can confirm activity without
opening logs or the hidden runtime.

This activity stream is a MicroRAG product projection. It is derived from ACP
and runtime hints, redacted by the backend, and rendered by the frontend. It is
not a pass-through clone of Claude Code's Ink UI widgets.

### Activity Signal Sources

| Source | Current ACP stdio support | MicroRAG use |
| --- | --- | --- |
| `available_commands_update` | Direct. Carries `name`, `description`, optional `input.hint`. | Drive slash picker and show command availability. |
| `tool_call` | Direct. Carries `toolCallId`, status, tool name metadata, title/kind/content when mapped. | Start tool/subagent activity rows. |
| `tool_call_update` | Direct. Carries terminal status such as completed or failed. | Complete or fail activity rows. |
| `permission_request` | Direct. | Pause activity rows in a permission-needed state. |
| `plan` | Direct for supported plan updates. | Optional plan progress display. |
| `agent_message_chunk` / thought chunks | Direct text stream. | Advisory progress text only, after redaction. |
| `skill_progress` | Flattened into text by the current ACP bridge. | Derive skill-running text only when safe. |
| `agent_progress` | Flattened into text by the current ACP bridge. | Derive subagent-running text only when safe. |
| `task_state` | Present in adjacent runtime code, not dependable on ACP stdio live sessions. | Do not depend on it in this stage. |
| `tool_use_summary` | Skipped by the current ACP bridge. | Do not depend on it in this stage. |

### Product-Derived Activity Types

The backend may expose a small product-owned activity model:

```text
activity_id
session_id
kind = skill | subagent | tool | command | permission | plan
label
status = queued | started | running | waiting_for_permission | completed | failed | cancelled
summary
source_message_id optional
source_tool_call_id optional
created_at
updated_at
```

These statuses are MicroRAG UI states. They must not be documented as native
Claude Code protocol enums.

### Demo Acceptance Rules

The first implementation plan must include checks for these user-visible demo
behaviors:

1. Selecting a slash command or skill produces a visible product-safe
   `invoked` or `started` state.
2. Permission-gated skill or tool activity visibly pauses in a permission state.
3. Tool execution visibly transitions through start, running, terminal success,
   or terminal failure states when ACP events provide those transitions.
4. Agent/Task tool calls visibly create a subagent activity row.
5. Agent/Task terminal tool-call updates visibly complete or fail that subagent
   activity row.
6. If skill or subagent progress is available only as flattened text, the
   backend synthesizes a sanitized activity row instead of leaving the UI silent.
7. The activity stream never exposes raw command lines, cwd, transcript paths,
   stderr, tracebacks, internal runtime flags, raw tool input, raw tool output,
   skill file paths, or agent definition paths.

## Backend Adapter Responsibilities

The MicroRAG backend ACP adapter should:

1. Start the runtime from the product runtime workspace.
2. Pass product runtime environment values such as `CLAUDE_CONFIG_DIR` and
   runtime cwd according to the runtime-workspace-isolation spec.
3. Subscribe to runtime session, message, command, tool, permission, plan, and
   error events.
4. Store only UI-facing session metadata in MicroRAG's metadata store.
5. Redact runtime events before sending them to the frontend.
6. Preserve Claude Code transcript persistence as the conversation source of
   truth.
7. Forward user messages as normal prompts rather than inventing command
   execution endpoints for slash commands.
8. Treat missing runtime command lists as a recoverable state.
9. Synthesize product-safe skill, subagent, tool, and permission activity rows
   when the ACP stdio path does not provide first-class activity events.

The adapter should not:

1. Parse `SKILL.md` to create its own command behavior.
2. Read memory files for prompt injection.
3. Spawn subagents itself.
4. Interpret MCP configuration.
5. Persist full transcript or memory content in SQLite.
6. Forward raw progress text into activity labels without redaction.

## Frontend Responsibilities

The MicroRAG frontend should:

1. Render a product-owned conversation shell.
2. Show slash command suggestions from backend-provided runtime summaries.
3. Pre-fill selected slash commands into the input box.
4. Submit the final text as a normal message.
5. Show sanitized task/subagent/tool activity states.
6. Show skill invocation activity during demos.
7. Show recoverable runtime status and error states in MicroRAG wording.
8. Avoid exposing raw runtime metadata.

The frontend should not:

1. Scan runtime workspace files.
2. Load `SKILL.md`.
3. Display memory files by default.
4. Execute slash commands directly from selection.
5. Implement subagent routing.
6. Implement shell execution.
7. Add MCP controls.

## Redaction Boundary

Any event crossing from backend to frontend must be treated as untrusted until
it is mapped into a MicroRAG-owned UI shape.

Backend-only fields include:

```text
raw ACP message
raw JSON-RPC error
raw error.message
stderr
traceback
runtime command
runtime args
runtime cwd
CLAUDE_CONFIG_DIR
MICRORAG_AGENT_CWD
transcript_path
agent definition path
skill file path
memory file path
MCP server config
```

UI-safe fields should be small and product-owned:

```text
session id
title
message content
sanitized status
sanitized error summary
command name
command description
command input hint
task status
activity kind
activity label
activity status
activity summary
created_at
updated_at
```

Validation must include negative checks for raw runtime identifiers and paths
in UI responses.

## Relationship To Existing Specs

This spec builds on:

```text
docs/superpowers/specs/2026-05-14-microrag-agent-demo-shell.md
docs/superpowers/specs/2026-05-15-microrag-agent-runtime-workspace-isolation.md
docs/superpowers/specs/2026-05-16-microrag-agent-system-prompt-identity-boundary.md
```

The demo-shell spec establishes ACP stdio reuse and the `mcrag` CLI skill path.
The runtime-workspace-isolation spec establishes the product runtime workspace.
The identity-boundary spec establishes that product identity belongs in the
model-visible runtime prompt layer, while product behavior belongs in
`CLAUDE.md` and skills.

This spec adds the UI/backend capability boundary for slash commands, skills,
memory, subagents, shell/tool states, and the demo activity stream.

## Implementation Scope For A Future Plan

A later implementation plan may include these slices after this spec is
approved:

1. Backend command-summary cache from ACP runtime events.
2. Frontend slash command picker backed by the command-summary cache.
3. Prompt submission path that keeps slash selection as pre-filled text.
4. Sanitized skill/subagent/tool/permission activity projection.
5. Runtime status and redacted error projection.
6. Frontend activity components that visibly animate product-derived activity
   states.
7. Tests proving the frontend does not parse skill files, memory files, or
   runtime internals.
8. Tests proving MCP is not configured or surfaced by this stage.

The implementation plan must inspect current code before choosing exact files,
because the working tree may already contain agent shell and ACP redaction
changes.

## Validation Requirements

Minimum validation for implementation:

1. Unit test: backend maps ACP command updates into UI-safe command summaries.
2. Unit test: backend redacts raw runtime error fields before returning UI
   responses.
3. Unit test: slash selection does not call a backend command-execution
   endpoint; it only updates input text.
4. Unit test or component test: command picker filters summaries by command
   name prefix.
5. Unit test or component test: selecting a command or skill creates visible
   product-safe invoked activity without directly executing a frontend command.
6. Unit test: Agent/Task `tool_call` creates a subagent activity row and
   terminal `tool_call_update` completes or fails it.
7. Unit test: flattened `agent_progress` or `skill_progress` text is redacted
   before it can become an activity label or summary.
8. Unit test: MicroRAG metadata store does not persist transcript body or
   memory content.
9. Static or unit check: product runtime setup does not configure MCP for this
   stage.
10. Static or unit check: frontend/API responses do not include raw runtime
   paths, raw `stderr`, raw JSON-RPC errors, or transcript paths.
11. Manual check: a MicroRAG agent conversation can use the product skill, show
   command suggestions, animate skill/tool/subagent activity, and avoid exposing
   Claude Code runtime internals.

## Approval Questions

This spec assumes:

1. The product should reuse Claude Code for skill, memory, subagent, slash, and
   shell/tool behavior.
2. MicroRAG should not implement MCP in this stage.
3. The first implementation should focus on ACP adapter and frontend capability
   presentation, not runtime replacement.

Implementation should not start until these assumptions are approved.
