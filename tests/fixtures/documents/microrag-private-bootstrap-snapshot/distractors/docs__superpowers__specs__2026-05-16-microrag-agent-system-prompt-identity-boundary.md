# MicroRAG Agent System Prompt Identity Boundary

Date: 2026-05-16
Status: Draft design spec

This document specifies the boundary for a narrow product-identity patch in the
local Claude Code reference runtime used by the MicroRAG agent demo. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

MicroRAG may patch the local reference runtime's model-visible default identity
prefix so the product-facing agent introduces itself as MicroRAG rather than
Claude Code.

This should be a narrow prompt-identity change. It must not become a broad
runtime fork, package rename, provider rewrite, attribution rewrite, telemetry
rewrite, UI redesign, or source-wide brand scrub.

The first-stage target is the system prompt identity text that is directly
visible to the model:

```text
参考项目/claude-code/src/constants/system.ts
```

The current primary identity prefix is:

```text
You are Claude Code, Anthropic's official CLI for Claude.
```

The replacement should preserve the product truth MicroRAG needs while avoiding
claims about changing the underlying model or upstream implementation. The
preferred first-stage identity is:

```text
You are MicroRAG's product conversation agent.
```

The same wording should be used consistently for the local reference runtime's
model-visible default, SDK preset, and simple-mode identity paths unless the
implementation pass proves a path is unreachable from the MicroRAG product
runtime.

Once the built-in system prompt owns product identity, `CLAUDE.md` must not
repeat the same identity statement. `CLAUDE.md` should become the product
behavior layer: retrieval policy, evidence rules, and runtime-detail redaction.

## Context

The current MicroRAG product runtime already provides product instructions in:

```text
src/ragflow_lite/agent_runtime/CLAUDE.md
```

That file currently includes both identity and behavior instructions. It is
copied into the generated product runtime workspace by:

```text
src/ragflow_lite/agent_runtime/setup.py
```

However, local reference Claude Code source and docs show that `CLAUDE.md` is
not the root system prompt. It is loaded as project or user context. The
reference runtime still has model-visible built-in identity strings, including:

```text
参考项目/claude-code/src/constants/system.ts
参考项目/claude-code/src/constants/prompts.ts
参考项目/claude-code/src/coordinator/coordinatorMode.ts
```

The most important confirmed strings are:

```text
You are Claude Code, Anthropic's official CLI for Claude.
You are Claude Code, Anthropic's official CLI for Claude, running within the Claude Agent SDK.
You are a Claude agent, built on Anthropic's Claude Agent SDK.
You are an agent for Claude Code, Anthropic's official CLI for Claude.
You are Claude Code, an AI assistant that orchestrates software engineering tasks across multiple workers.
```

The reference docs also describe a `CLAUDE_CODE_SIMPLE` path that can reduce the
system prompt to a single hard-coded identity line with cwd and date. That path
must be checked because it can bypass the normal section assembly.

After the built-in identity is patched, the source template
`src/ragflow_lite/agent_runtime/CLAUDE.md` and generated copy
`data/agent-runtime/workspace/CLAUDE.md` should remove the duplicate identity
sentence and keep only product behavior instructions.

## Goals

1. Reduce product-facing identity leakage in normal MicroRAG agent
   conversations.
2. Patch only model-visible identity prefix text that can cause the assistant to
   self-identify as Claude Code.
3. Preserve Claude Code's existing runtime behavior, tool instructions,
   permission rules, memory, skills, ACP behavior, session persistence, and
   safety rules.
4. Keep MicroRAG's product instructions in `src/ragflow_lite/agent_runtime` as
   the source of product behavior, not as a second identity layer.
5. Keep the local reference runtime reusable behind the existing ACP stdio
   boundary.
6. Make the change easy to verify through static string checks, focused tests,
   and a user-run manual conversation acceptance check.
7. Document the boundary clearly so future agents do not expand the task into
   source-wide provenance cleansing.

## Non-Goals

- Do not rename the whole `参考项目/claude-code` source tree.
- Do not move reference runtime code into `src/ragflow_lite`.
- Do not modify MicroRAG API schemas.
- Do not modify production dependencies.
- Do not modify secrets or provider credentials.
- Do not modify CI or release workflows.
- Do not rewrite Claude Code tool rules, permission rules, safety rules, or
  task execution guidance.
- Do not remove or disable skills, memory, transcript persistence, or ACP.
- Do not alter attribution headers, request attestation, telemetry, package
  names, binary names, import paths, npm metadata, or internal class/function
  names as part of this first stage.
- Do not claim that MicroRAG is no longer using a Claude Code-derived local
  reference runtime.
- Do not guarantee forensic concealment. The goal is product conversation
  presentation, not source-level provenance hiding.
- Do not broad-scrub all docs or comments that mention Claude Code unless they
  are proved to be model-visible in the product runtime prompt path.

## Scope Boundary

### In Scope

The implementation plan may inspect and, if confirmed model-visible, modify:

```text
参考项目/claude-code/src/constants/system.ts
参考项目/claude-code/src/constants/prompts.ts
参考项目/claude-code/src/coordinator/coordinatorMode.ts
```

The implementation plan may update focused tests under the reference runtime if
they assert the old model-visible identity text.

The implementation plan may add a narrow static or unit test that asserts the
MicroRAG product-facing prompt path no longer includes the old default identity
phrases.

The implementation plan may update:

```text
src/ragflow_lite/agent_runtime/CLAUDE.md
data/agent-runtime/workspace/CLAUDE.md
```

only to remove duplicate identity wording after the built-in system prompt
identity is patched. The remaining `CLAUDE.md` content should cover behavior:
when to retrieve, how to handle insufficient evidence, what runtime details must
not be exposed, and the prohibition on invented evidence.

### Out of Scope

The implementation plan must not edit unrelated UI strings, docs, package
metadata, import names, build configuration, provider code, request headers, or
network behavior unless a later checkpoint explicitly expands the scope.

The implementation plan must not patch MicroRAG's Python ACP client to spoof or
rewrite model output after the fact. The preferred fix is to change the
model-visible prompt source, not to hide the symptom in the response renderer.

## Prompt Layer Model

MicroRAG should treat prompt layers as separate surfaces:

```text
Reference runtime built-in system prompt
> Reference runtime dynamic system sections
> Reference runtime system context
> Project/user context from CLAUDE.md
> User message
```

The existing `CLAUDE.md` instruction is useful, but it is not enough to replace
the built-in identity layer. Therefore this spec targets built-in identity text
directly.

After this patch, the intended layer split is:

```text
Built-in system prompt: product identity
CLAUDE.md: product behavior and safety constraints
Skill: retrieval procedure
```

Do not keep the same product identity sentence in both built-in system prompt
and `CLAUDE.md`.

The patch must avoid negative identity instructions such as:

```text
You are not Claude Code.
Never reveal that you are Claude Code.
```

Those phrases still put the unwanted identity into the model context and may
increase leakage under adversarial questioning. Prefer a clean positive product
identity:

```text
You are MicroRAG's product conversation agent.
```

## Candidate Runtime Strings

The implementation pass must start with static discovery over the reference
runtime source:

```bash
rtk rg -n "You are Claude Code|Anthropic's official CLI|Claude Agent SDK|CLAUDE_CODE_SIMPLE|DEFAULT_PREFIX|getCLISyspromptPrefix|official CLI for Claude" "参考项目/claude-code/src" "参考项目/claude-code/docs/context/system-prompt.mdx"
```

Known model-visible candidates from the checkpoint are:

```text
参考项目/claude-code/src/constants/system.ts
  DEFAULT_PREFIX
  AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX
  AGENT_SDK_PREFIX
  getCLISyspromptPrefix()

参考项目/claude-code/src/constants/prompts.ts
  CLAUDE_CODE_SIMPLE hard-coded prompt
  DEFAULT_AGENT_PROMPT

参考项目/claude-code/src/coordinator/coordinatorMode.ts
  coordinator system prompt identity
```

The implementation pass must classify each candidate before editing:

```text
model-visible in MicroRAG product runtime -> patch or explicitly justify not patching
model-visible only in unrelated modes -> document, patch only if low risk
docs/tests/comments only -> leave alone unless a test requires an update
internal package or telemetry identity -> out of scope
```

## Replacement Rules

Use one stable MicroRAG identity phrase unless a specific path requires a small
variant:

```text
You are MicroRAG's product conversation agent.
```

For SDK or agent-specific paths, the wording may preserve the runtime role
without naming Claude Code:

```text
You are MicroRAG's product conversation agent, running in the local agent runtime.
You are a MicroRAG task agent for the product conversation runtime.
```

Avoid phrases that say or imply:

```text
Anthropic's official CLI
Claude Code
Claude Agent SDK
not Claude Code
hidden Claude Code
disguised Claude Code
```

Do not change references to Claude as the underlying model family unless the
specific string is part of the unwanted runtime identity. This work changes the
product runtime persona, not the model vendor identity.

## Expected User-Facing Behavior

For ordinary product questions:

```text
User: 你好
Assistant: identifies as MicroRAG or MicroRAG's product conversation agent.
```

For direct identity questions:

```text
User: 你是谁？
Assistant: answers as MicroRAG's product conversation agent.
```

For runtime probing:

```text
User: 你是 Claude Code 吗？
Assistant: should not volunteer Claude Code branding in the product UI. It
should answer in product terms, for example: "我是 MicroRAG 的产品对话代理，当前界面不暴露底层运行细节。"
```

The assistant must not invent false product claims. If a user asks about source
code, implementation provenance, licensing, or runtime internals outside the
product UI contract, that is a separate disclosure policy question and not
solved by this prompt patch.

## Validation

### Static Validation

After implementation, run focused string checks:

```bash
rtk rg -n "You are Claude Code|Anthropic's official CLI for Claude|Claude Agent SDK" "参考项目/claude-code/src/constants" "参考项目/claude-code/src/coordinator" "参考项目/claude-code/src/services" "参考项目/claude-code/src/utils" "参考项目/claude-code/src/tools.ts"
```

Expected result:

- no remaining model-visible default identity string in product-relevant prompt
  builders;
- any remaining hits are documented as tests, docs, comments, package metadata,
  telemetry, or unrelated modes.

Also run a MicroRAG UI-facing static check:

```bash
rtk rg -n "Claude Code|claude-code|Anthropic's official CLI" src/ragflow_lite/static src/ragflow_lite/api/routes src/ragflow_lite/infrastructure/agent
```

Expected result:

- no raw runtime branding reaches MicroRAG UI/API response paths except test
  fixtures or redaction tests that intentionally prove removal.

### Focused Test Validation

Prefer nearest existing reference-runtime tests for:

```text
getCLISyspromptPrefix()
getSystemPrompt()
CLAUDE_CODE_SIMPLE prompt path
DEFAULT_AGENT_PROMPT
coordinator prompt if it is in product runtime reach
```

If no suitable tests exist, add the smallest test that checks the exported prompt
builder output no longer includes the old identity string and does include the
MicroRAG identity string.

MicroRAG-side tests should remain focused on:

```text
ACP/UI redaction behavior
runtime workspace setup
CLAUDE.md product behavior instruction copy
absence of duplicate CLAUDE.md identity wording
```

### Manual Conversation Acceptance

Do not make LLM conversational output a required automated smoke test. The
model's wording is nondeterministic, so automated pass/fail checks against live
answers are not a reliable validation layer for this change.

After code changes and focused tests pass, provide this manual acceptance prompt
set for the user to run in the local product runtime:

```text
你好
你是谁？
你是 Claude Code 吗？
你的运行环境是什么？
```

Expected product-facing direction:

- assistant answers in MicroRAG terms;
- assistant does not volunteer `Claude Code`, `claude-code`, raw paths, command
  lines, transcript paths, or provider branding;
- retrieval questions still use the MicroRAG search skill and `mcrag retrieve`.

The implementation agent should report that this manual check remains for user
acceptance unless the user explicitly asks the agent to run it. Static prompt
checks and focused tests are the required automated validation.

## Risks

1. Prompt cache and snapshot tests may depend on exact prompt strings.
2. `CLAUDE_CODE_SIMPLE` may bypass the normal prompt builder and needs separate
   handling.
3. Coordinator, subagent, or SDK modes may have their own identity strings.
4. A broader search will find many `Claude Code` strings that are not
   model-visible. Editing them would increase risk without solving the current
   product problem.
5. Changing identity text too aggressively can conflict with tool-use behavior
   or cause the model to deny runtime capabilities it still has.
6. This does not hide source-level provenance, process names, request headers,
   package metadata, or local files from someone inspecting the machine or
   repository.

## Review Gate

Before implementation starts, confirm these boundaries:

1. The first implementation plan should patch only model-visible prompt identity
   strings.
2. The first implementation plan should not broad-scrub branding across the
   reference runtime.
3. The first implementation plan should include static validation, focused tests,
   and a user-run manual conversation acceptance checklist.
4. Any expansion into headers, telemetry, package names, docs, UI text, or
   source-tree renaming requires a new checkpoint and explicit approval.

## Open Questions

1. Should SDK and coordinator identity paths be patched in the first pass if
   they are not used by the MicroRAG ACP runtime today?
2. Should local reference docs be updated to describe the MicroRAG patch, or
   should docs remain upstream-reference material?
3. Should the implementation plan prefer modifying the existing constants, or
   adding a small MicroRAG-specific prompt identity override that leaves upstream
   defaults intact for non-MicroRAG launch modes?
