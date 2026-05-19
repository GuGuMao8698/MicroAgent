# MicroRAG Agent Demo Shell

Date: 2026-05-14
Status: Draft design spec

This document specifies the first-stage MicroRAG agent demo shell. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

Build a MicroRAG-owned user-facing shell around an external ACP-backed agent
runtime.

The first-stage runtime boundary is:

```text
MicroRAG Web UI
-> MicroRAG backend agent adapter
-> Claude Code ACP stdio subprocess
-> Claude Code QueryEngine session runtime
-> MicroRAG skill
-> mcrag CLI
-> MicroRAG retrieval / answer services
```

The demo shell must reuse Claude Code's mature agent mechanisms instead of
rebuilding them inside MicroRAG:

- QueryEngine owns multi-turn session state.
- Claude Code JSONL transcripts own conversation persistence and resume.
- Claude Code skill loading owns first-stage agent workflow injection.
- MicroRAG SQLite or local metadata stores only UI-facing session metadata.

MicroRAG should expose a thin local CLI facade for skill calls:

```text
mcrag retrieve
mcrag answer
```

`mcrag retrieve` is the primary first-stage tool for the external agent.
Its first version must support both `standard` and `discorag` modes so the
agent demo can exercise the same retrieval choices as the existing query API.
`mcrag answer` preserves direct grounded-answer use cases and supports
debugging, fallback, and future evaluation workflows.

MCP is intentionally out of this product plan. It must not be added as a
first-stage goal, later-stage milestone, or hidden product dependency in this
spec. If MCP is reconsidered in the future, it needs a separate design decision.

## Current Implementation Facts

Current boundary checks found:

- The current public query endpoint is answer-producing. `/api/v0/queries`
  returns an answer plus contexts and metadata.
- Query requests already route by `mode`, currently `standard` or `discorag`.
- `QueryService.query()` retrieves contexts and then calls the answerer with an
  `AnswerRequest`.
- `DiscoRAGQueryService.query()` also ends at the answerer, but passes a richer
  `AnswerRequest` with `mode="discorag"` and an optional `AnswerBlueprint`.
- `AnswerRequest` is the explicit answer boundary. It carries the query,
  contexts, mode, optional blueprint, and metadata.
- `AnswerBlueprint` carries ordered chunk ids, chunk roles, constraints, and
  steps for answer-side DiscoRAG behavior.
- `AnswerResult` returns the final answer, contexts, and metadata.
- The concrete answerer consumes the context list and optional blueprint to
  build the answer prompt.
- In standard mode, the answerer can sort contexts by score.
- In DiscoRAG mode, the answerer can apply blueprint ordering when the
  blueprint is valid.
- The app currently has no packaged CLI entrypoint or dedicated CLI module.
- Claude Code's `QueryEngine` is importable inside its own repo and already
  owns session lifecycle and mutable session state.
- Claude Code persists sessions as JSONL transcripts and supports resume from
  those transcripts.
- Claude Code skills are file-based and can guide the model to use local tools.
- ACP stdio is the chosen process boundary because it avoids the visible TUI
  layer and already bridges to `QueryEngine`.

## Goals

1. Provide a MicroRAG-branded web demo where the user never sees the underlying
   Claude Code CLI, TUI, startup text, icon, or branding.
2. Reuse Claude Code's ACP, QueryEngine, transcript, resume, memory, and skill
   mechanisms where they are already fit for purpose.
3. Add the smallest MicroRAG CLI facade needed for skill-based tool use.
4. Let the external ACP-backed agent own final conversational synthesis in the
   normal agent path.
5. Keep MicroRAG's answer layer available for direct grounded-answer use and
   RAG evaluation.
6. Add a retrieval-only capability before the answerer boundary so the external
   agent can consume contexts and metadata without forcing a MicroRAG answer.
7. Keep current `/api/v0/queries` answer behavior intact unless a later,
   explicit implementation plan changes it.
8. Clean nested Git repository traces from the vendored reference runtime only
   after verifying the current Git shape.

## Non-Goals

- Do not add MCP to the product plan.
- Do not build a native MicroRAG agent runtime in this stage.
- Do not replace Claude Code's JSONL transcript and resume mechanism with a
  MicroRAG conversation database.
- Do not store complete conversation history as the primary source in
  MicroRAG SQLite.
- Do not remove or deprecate the MicroRAG answer layer.
- Do not route RAG evaluation away from the answer layer.
- Do not make `/api/v0/queries` retrieval-only.
- Do not make the first-stage UI expose detailed RAG citations or clickable
  source panels.
- Do not make citation or source drill-down a first-stage UI feature; the
  retrieval result only needs stable identifiers that make that future UI
  possible.
- Do not add team memory, daemon, remote-control, or RCS as first-stage work.
- Do not perform broad source-code brand scrubbing.
- Do not move the reference TypeScript runtime into `src/ragflow_lite` as if it
  were a normal Python package.

## Architecture

### Process Boundary

The external runtime runs behind an ACP stdio process boundary.

MicroRAG owns:

- starting or attaching to the ACP subprocess;
- mapping UI sessions to Claude Code session ids and transcript paths;
- forwarding user messages and receiving streamed agent events;
- hiding subprocess stderr/stdout details from the user-facing UI;
- applying a small branding patch when protocol metadata would otherwise leak
  `claude-code` or `Claude Code` into the MicroRAG UI;
- reporting process startup, failure, restart, and interruption status in
  MicroRAG terms.
- redacting or remapping raw ACP runtime fields before they reach the web UI.

Claude Code owns:

- QueryEngine session state;
- transcript persistence;
- resume behavior;
- skill discovery and skill prompt loading;
- memory loading;
- permission state;
- read-file cache;
- token usage accounting;
- abort handling.

The first-stage backend should treat ACP as an implementation detail. The web
client talks only to MicroRAG endpoints or WebSocket/SSE channels.

Raw ACP/runtime fields are backend-only unless explicitly remapped into a
MicroRAG-owned UI field. Backend-only fields include:

```text
agentInfo
cwd
runtime command and args
raw session ids
transcript_path
_meta
raw stderr
raw error.message
```

The UI must not directly render raw ACP `agentInfo`, runtime cwd, transcript
paths, command lines, stderr, or unprocessed error messages. Any runtime error
that reaches the UI must be rewritten in MicroRAG terms.

Validation should include a UI-visible text check that no first-stage demo
screen contains `Claude Code`, `claude-code`, raw runtime paths, or raw
subprocess command lines.

### Session Persistence

Claude Code JSONL transcripts are the conversation source of truth.

MicroRAG local metadata is an index over that runtime state, not a replacement
for it.

Suggested MicroRAG metadata fields:

```text
agent_sessions
  id
  title
  claude_session_id
  transcript_path
  runtime_cwd
  created_at
  updated_at
  last_error
  ui_metadata_json
```

Rules:

- UI session creation starts or associates a Claude Code session.
- Resume uses the Claude session id and transcript path.
- The UI may cache last message previews, titles, or status, but the transcript
  remains authoritative.
- A new-session action must be available so demos can start cleanly.
- The new-session action should create a fresh Claude Code session/transcript.
  Historical transcript resume should be explicit; the first stage does not
  require deleting historical transcripts as a reset mechanism.
- If transcript loading fails, the UI should show a recoverable session error
  instead of inventing a partial conversation from UI metadata.
- UI metadata must not be used to reconstruct or patch conversation history
  when the underlying transcript cannot be loaded.

### Skill And CLI Surface

Claude Code skills should invoke a deterministic local MicroRAG CLI.

The first-stage skill should live under the Claude Code-managed skill location,
not under MicroRAG's normal Python package tree and not as a native tool patch.
The concrete path may be a Claude Code project skill or another configured
Claude Code skill directory, for example:

```text
.claude/skills/microrag-search/SKILL.md
```

MicroRAG does not own skill storage, does not reimplement Claude Code's skill
loader, and does not store skill content in its own database. MicroRAG only
exposes `mcrag` as a deterministic local command that Claude Code-managed
skills can call.

The skill should teach the agent when and how to call:

```bash
mcrag retrieve --query "<question>" --mode standard --top-n 6 --json
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

The CLI must print machine-readable JSON to stdout and send logs or diagnostics
to stderr. This keeps the command safe for skill use and future automation.

`mcrag answer` should also exist:

```bash
mcrag answer --query "<question>" --mode standard --top-n 6 --json
mcrag answer --query "<question>" --mode discorag --top-n 6 --json
```

`mcrag answer` calls the answer-included service path and exists because the
answer layer remains a real product and evaluation capability.

### Retrieval-Only Capability

The external agent path should not call the answerer by default.

Add a retrieval-only service boundary before `Answerer.answer()`:

```text
query
-> grounding / retrieval / DiscoRAG evidence and blueprint orchestration
-> RetrievalResultForAgent
-> external ACP-backed agent synthesis
```

The retrieval-only CLI output consumed by the model must be a model-facing
payload, not a debug envelope. It should place the highest-value answer
evidence near the beginning and keep operational metadata out of the model
context.

Standard mode returns only the query and current answer-facing context shape:

```json
{
  "query": "...",
  "contexts": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "text": "...",
      "score": 0.0,
      "metadata": {}
    }
  ]
}
```

Standard mode must preserve every top-n context returned by the retrieval
service. It may reorder contexts for LLM attention, but it must not drop,
rewrite, or prune evidence chunks after MiniRAG retrieval has selected them.
Because standard mode has no blueprint at the end of the payload, context order
uses a U-shaped attention layout:

```text
highest-score context
remaining contexts in descending score order, starting from the third item
second-highest-score context
```

For example, score order `c1, c2, c3, c4, c5` becomes model-facing order
`c1, c3, c4, c5, c2`. If fewer than three contexts are returned, preserve the
score order.

DiscoRAG mode returns the query, the same current answer-facing context shape,
and the final answer-facing `AnswerBlueprint` fields used by the answerer. The
blueprint is placed last because it is the second-most-important model-facing
content after the contexts and benefits from end-of-context attention:

```json
{
  "query": "...",
  "contexts": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "text": "...",
      "score": 0.0,
      "metadata": {}
    }
  ],
  "blueprint": {
    "chunk_roles": {},
    "answer_constraints": [],
    "plan_steps": [],
    "ordered_chunk_ids": []
  }
}
```

DiscoRAG mode must also preserve every final top-n context selected for answer
synthesis. It must not drop chunks after DiscoRAG has built the answer-facing
context set. Because the bottom of the payload is reserved for the blueprint,
DiscoRAG contexts are ordered by descending score so the strongest evidence is
near the front of the whole JSON payload, while the final blueprint occupies
the high-attention tail.

Within `blueprint`, fields are ordered from lower to higher importance so the
most important DiscoRAG product lands closest to the end of the payload:

```text
chunk_roles
answer_constraints
plan_steps
ordered_chunk_ids
```

`ordered_chunk_ids` is last because it is the strongest signal of the final
DiscoRAG evidence order. `plan_steps` is next-most important, followed by
answer constraints and then chunk role annotations.

The retrieval-only boundary must preserve these invariants:

- retrieval-only does not generate a final answer;
- retrieval-only does not call `Answerer.answer()`;
- standard mode does not include a `blueprint` field;
- DiscoRAG mode includes the final answer-facing blueprint fields:
  `chunk_roles`, `answer_constraints`, `plan_steps`, and
  `ordered_chunk_ids`;
- DiscoRAG mode does not expose intermediate DiscoRAG processing details such
  as promotions, source selection, supplemental discourse chunks, graph paths,
  RST structures, or builder metadata;
- contexts use the current `RetrievedChunk` serialization consumed by the
  answer layer: `chunk_id`, `document_id`, `text`, `score`, and `metadata`;
- model-facing JSON does not include `mode`, top-level operational `metadata`,
  debug state, degraded state, graph internals, or future placeholder fields;
- operational state, setup errors, degraded retrieval state, rewrite quality
  state, and debug details belong in CLI exit codes, stderr diagnostics,
  backend logs, or UI status surfaces rather than the model-facing payload;
- low-quality retrieval notices must be surfaced by deterministic backend or
  frontend UI behavior, not inserted into answer prompts or agent-facing
  retrieval JSON;
- retrieval rewrite state is internal retrieval/runtime state. It must not be
  copied into model-facing payloads, inserted into answer prompts, or exposed as
  raw top-level response metadata;
- the same context-ordering policy should be shared by `mcrag retrieve` and
  the answer-included path where applicable, so the external agent path and
  MicroRAG answer path do not drift;
- answerer-specific prompt text is not part of the retrieval-only contract.

### Runtime State Channels

The system must keep three channels separate:

```text
model-facing payload:
  query, contexts, optional final blueprint

runtime/UI state:
  setup errors, degraded retrieval state, post-rewrite low-quality state,
  session status, recoverable runtime errors

debug/log metadata:
  raw retrieval metadata, source selection internals, graph traces, timings,
  raw ACP details
```

Open-ended metadata dictionaries must not be used as an implicit bridge from
retrieval internals into prompts, agent-facing JSON, or user-visible UI. Any
state that the UI needs must be mapped through an explicit MicroRAG-owned field
or event.

The existing retrieval rewrite degraded notice behavior is superseded by this
spec. Post-rewrite low-quality retrieval remains a real runtime state, but it
must be surfaced by deterministic backend/frontend UI behavior. It must not be
rendered by `format_retrieval_rewrite_notice()`, inserted into answerer prompts,
or included in `mcrag retrieve` model-facing JSON.

### Answer Layer

The answer layer stays.

It remains responsible for direct MicroRAG grounded answers:

```text
query
-> retrieval / DiscoRAG orchestration
-> AnswerRequest
-> Answerer.answer()
-> AnswerResult
```

The answer layer also remains necessary for RAG evaluation. Evaluation flows
that score answer relevance, faithfulness, contextual precision, contextual
recall, or prompt behavior still need a stable answer-producing path.

Answer-included model input must follow the same model-facing evidence
principles as `mcrag retrieve` where applicable:

- standard answer prompts preserve all top-n contexts and use the standard
  attention-aware context ordering policy;
- DiscoRAG answer prompts preserve all final top-n contexts, place contexts
  before the final blueprint, and place `ordered_chunk_ids` at the end of the
  blueprint section;
- low-quality retrieval notices are not inserted into answer prompts;
- answer text should not contain deterministic retrieval-quality warning text,
  so RAG evaluation scores the answer rather than a system warning.

The new external-agent path must not make the answer layer look obsolete. The
system should have two explicit capability surfaces:

```text
retrieval-only:
  for ACP-backed agent synthesis

answer-included:
  for MicroRAG direct answers, API clients, debugging, fallback, and RAG evals
```

### Product Surface

First-stage UI scope:

- session list;
- current chat view;
- send message;
- stream or poll agent output;
- show lightweight skill-call status;
- start new session;
- resume previous session;
- show recoverable runtime errors.

Deferred UI scope:

- clickable RAG citation panel;
- per-sentence citations;
- source text drill-down;
- graph or blueprint visualization;
- multi-user permissions;
- model/provider configuration UI.

## CLI Contract

### `mcrag retrieve`

Purpose: return retrieval evidence for external agent synthesis.

Required behavior:

- accepts `--query`;
- accepts `--mode standard|discorag`;
- accepts `--top-n`;
- accepts `--json`;
- supports both `standard` and `discorag` in the first version;
- exits non-zero on unrecoverable errors;
- writes JSON payload to stdout only;
- writes diagnostics to stderr only;
- does not call the answerer.
- fails with a clear setup error when the required local MicroRAG app or
  service dependency is not running; it should not silently start background
  services in the first version.

### `mcrag answer`

Purpose: return MicroRAG's own grounded answer.

Required behavior:

- accepts the same core query flags as `mcrag retrieve`;
- returns answer, contexts, and metadata;
- reuses the existing answer-included service path;
- remains suitable for RAG evaluation and direct debugging.

### Naming

Use `mcrag` as the executable name for the first-stage local CLI. It is short,
does not expose the internal Python package name, and matches the visible
MicroRAG product name better than `ragflow_lite`.

## Data Flow

### Normal Agent Query

```text
User sends message in MicroRAG UI
-> backend forwards message to ACP runtime
-> Claude Code QueryEngine handles turn state
-> microrag-search skill instructs local retrieval when needed
-> agent invokes mcrag retrieve --json
-> MicroRAG returns model-facing evidence JSON
-> agent synthesizes the final conversational answer
-> backend streams answer to UI
-> Claude Code persists transcript
-> MicroRAG updates UI metadata index
```

### Direct Answer Query

```text
caller invokes /api/v0/queries or mcrag answer
-> QueryModeRouter selects standard or discorag
-> service retrieves contexts and metadata
-> service applies the shared answer-facing context ordering policy
-> answerer consumes AnswerRequest
-> answer-included response returns answer, contexts, metadata
```

### Evaluation Query

```text
eval harness calls answer-included path
-> answerer produces a final answer
-> eval metrics score answer and contexts
```

RAG evaluation should not depend on the external ACP-backed agent path.
Deterministic low-quality retrieval warnings should be kept out of the answer
text used for RAG evaluation. If evaluations need to inspect degraded retrieval
state, that state should be provided as structured side-channel metadata rather
than prompt text or generated answer text.

## Error Handling

- ACP process startup failure should be reported as a MicroRAG agent runtime
  error.
- ACP protocol errors should not leak raw Claude Code branding into the UI.
- Raw ACP `agentInfo`, raw stderr, raw subprocess command lines, raw cwd,
  transcript paths, and raw runtime error messages must not be rendered in the
  UI.
- `mcrag retrieve` unrecoverable failures should be visible to the agent as
  command failure, with structured stderr where practical.
- If `mcrag retrieve` cannot reach the required local MicroRAG service, it
  should exit non-zero and print a clear setup error to stderr.
- Degraded retrieval and post-rewrite low-quality retrieval states must be
  explicit in backend/runtime metadata and UI status, but not in model-facing
  retrieval JSON.
- Answerer failures affect `mcrag answer` and `/api/v0/queries`, not
  retrieval-only results.
- Transcript resume failure should show a session-level recovery prompt.

## Validation

Design-level validation before implementation:

- verify the reference runtime can start in ACP mode without showing TUI output
  in the user-facing UI;
- verify ACP metadata can be hidden or patched if it would reach the UI;
- verify UI-visible output contains no `Claude Code`, `claude-code`, raw
  runtime paths, transcript paths, raw stderr, raw command lines, or raw ACP
  `agentInfo`;
- verify a project skill can invoke a local command and the command JSON can be
  consumed by the agent;
- verify `mcrag retrieve` does not call `Answerer.answer()`;
- verify `mcrag answer` still calls the answer layer;
- verify existing answer-included RAG evaluation entrypoints keep working;
- verify nested Git state under the reference runtime before deleting any
  `.git` directory or gitlink.

Implementation-level validation should include focused unit tests for the
retrieval-only service, CLI JSON behavior, answer path preservation, and ACP
adapter session metadata mapping.

Implementation-level validation must also cover:

- answerer prompts no longer contain `Retrieval rewrite notice:`;
- backend or frontend UI state still exposes post-rewrite low-quality retrieval
  as a deterministic status;
- answer text and evaluation answer text do not include deterministic
  retrieval-quality warning text;
- standard model-facing contexts preserve every top-n chunk and apply the
  standard U-shaped ordering;
- DiscoRAG model-facing contexts preserve every final top-n chunk and sort
  contexts by descending score before the final blueprint;
- DiscoRAG blueprint serialization exposes only `chunk_roles`,
  `answer_constraints`, `plan_steps`, and `ordered_chunk_ids`, in that order;
- DiscoRAG blueprint prompt/JSON placement keeps contexts before blueprint and
  `ordered_chunk_ids` at the payload tail;
- invalid or incomplete blueprint/context alignment fails or falls back
  explicitly; it must not silently drop chunks or partially repair planner
  output;
- `mcrag retrieve` stdout omits `mode`, top-level operational `metadata`,
  degraded state, source selection, retrieval rewrite state, graph internals,
  and debug traces;
- API/UI paths that need degraded retrieval state receive it through explicit
  runtime/UI fields rather than answer prompts or model-facing JSON;
- session resume uses Claude Code transcript state and never reconstructs
  conversation history from MicroRAG UI metadata;
- nested Git cleanup is blocked until `.git`, submodule, and gitlink preflight
  checks have been run.

## Resolved Design Choices

- `mcrag retrieve` supports both `standard` and `discorag` in the first version.
- Skills are managed by Claude Code in a Claude Code-specific skill location.
- `mcrag retrieve` fails clearly with a setup error if the required local
  MicroRAG app or service is not running.
- Claude Code transcripts are the conversation source of truth; MicroRAG
  SQLite or local metadata stores only UI-facing metadata.
- First-stage UI does not include citation or source drill-down; retrieval
  results only preserve identifiers needed for that future feature.
- First-stage UI includes a new-session action so demos can start from a clean
  transcript.
- `mcrag retrieve` stdout is model-facing evidence, not a debug envelope.
- Standard model-facing JSON contains `query` and `contexts` only.
- DiscoRAG model-facing JSON contains `query`, `contexts`, and `blueprint`.
- Standard mode omits `blueprint` entirely.
- Model-facing JSON omits `mode` and top-level operational `metadata`.
- Context chunks are never dropped after MiniRAG retrieval or DiscoRAG
  answer-context selection has produced the top-n evidence set.
- Low-quality retrieval notices are shown by deterministic frontend/backend
  behavior instead of being inserted into LLM prompts.
- Raw ACP runtime fields and Claude Code branding are backend-only and must not
  be rendered by the MicroRAG UI.
- MicroRAG does not own or reimplement Claude Code skill storage/loading; it
  only exposes the `mcrag` CLI used by Claude Code-managed skills.
- Retrieval rewrite degraded state is not prompt text. It is runtime/UI state.
