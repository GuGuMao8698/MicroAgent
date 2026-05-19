# MicroRAG Agent System Prompt Identity Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patch only the local reference runtime's model-visible identity strings so the MicroRAG product agent identifies as MicroRAG, then remove duplicate identity wording from MicroRAG `CLAUDE.md` behavior instructions.

**Architecture:** Keep identity in the reference runtime built-in system prompt layer. Keep `CLAUDE.md` as the product behavior layer, covering retrieval policy, evidence handling, and runtime-detail redaction. Do not change ACP, tools, memory, skills, providers, request headers, telemetry, package metadata, or UI behavior.

**Tech Stack:** TypeScript/Bun reference runtime under `参考项目/claude-code`, Python 3.13 MicroRAG runtime templates, pytest for MicroRAG tests, Bun test for focused reference-runtime tests, `rtk` command prefix.

---

## Source Spec

Implement only the boundaries approved in:

```text
docs/superpowers/specs/2026-05-16-microrag-agent-system-prompt-identity-boundary.md
```

## File Structure

Modify:

```text
参考项目/claude-code/src/constants/system.ts
```

Responsibility: model-visible CLI system prompt identity prefixes. Patch the three prefix constants only; do not edit attribution header behavior.

Modify:

```text
参考项目/claude-code/src/constants/prompts.ts
```

Responsibility: main system prompt assembly. Patch only the `CLAUDE_CODE_SIMPLE` identity line and `DEFAULT_AGENT_PROMPT` identity wording.

Modify:

```text
参考项目/claude-code/src/coordinator/coordinatorMode.ts
```

Responsibility: coordinator mode system prompt. Patch only the initial coordinator identity sentence if it remains model-visible.

Modify:

```text
src/ragflow_lite/agent_runtime/CLAUDE.md
data/agent-runtime/workspace/CLAUDE.md
```

Responsibility: MicroRAG product behavior instructions. Remove duplicate identity sentence once built-in system prompt owns identity. Keep retrieval, insufficient-evidence, runtime-redaction, and no-invented-evidence rules.

Create:

```text
参考项目/claude-code/src/constants/__tests__/microragIdentity.test.ts
```

Responsibility: narrow reference-runtime checks for model-visible identity strings.

Modify:

```text
tests/unit/test_agent_runtime_setup.py
```

Responsibility: MicroRAG runtime template/setup tests. Add or update focused assertions so `CLAUDE.md` copies behavior instructions but does not duplicate the identity sentence.

If `tests/unit/test_agent_runtime_setup.py` does not exist, create it with the tests shown in Task 4.

## Chosen Answers To Open Questions

1. Patch SDK and coordinator identity paths in the first pass if they are model-visible and the change is a local string replacement. This avoids leaving obvious alternate self-identity routes.
2. Do not update local reference docs in the first pass. Docs remain upstream-reference material unless a later checkpoint expands scope.
3. Directly modify the existing prompt constants and known prompt literals. Do not add a MicroRAG-specific runtime override branch in this pass, because the reference runtime is currently launched as the product runtime and the user's requested boundary is "find system prompt location and change the role part."

## Task 1: Add Focused Reference Runtime Identity Tests

Purpose: pin the desired identity behavior before editing prompt strings.

**Files:**
- Create: `参考项目/claude-code/src/constants/__tests__/microragIdentity.test.ts`
- Read: `参考项目/claude-code/src/constants/system.ts`
- Read: `参考项目/claude-code/src/constants/prompts.ts`
- Read: `参考项目/claude-code/src/coordinator/coordinatorMode.ts`

- [ ] **Step 1: Create the failing test file**

Create `参考项目/claude-code/src/constants/__tests__/microragIdentity.test.ts`:

```typescript
import { describe, expect, test } from 'bun:test'

import {
  CLI_SYSPROMPT_PREFIXES,
  getCLISyspromptPrefix,
} from '../system.js'
import { DEFAULT_AGENT_PROMPT, getSystemPrompt } from '../prompts.js'
import { getCoordinatorSystemPrompt } from '../../coordinator/coordinatorMode.js'

const MICRORAG_IDENTITY = "You are MicroRAG's product conversation agent."

function expectMicroRAGIdentity(text: string): void {
  expect(text).toContain('MicroRAG')
  expect(text).not.toContain('You are Claude Code')
  expect(text).not.toContain("Anthropic's official CLI for Claude")
  expect(text).not.toContain('Claude Agent SDK')
}

describe('MicroRAG product identity prompt patch', () => {
  test('CLI system prompt prefixes use MicroRAG product identity', () => {
    expect(getCLISyspromptPrefix()).toBe(MICRORAG_IDENTITY)
    expect(
      getCLISyspromptPrefix({
        isNonInteractive: true,
        hasAppendSystemPrompt: true,
      }),
    ).toBe(
      "You are MicroRAG's product conversation agent, running in the local agent runtime.",
    )
    expect(
      getCLISyspromptPrefix({
        isNonInteractive: true,
        hasAppendSystemPrompt: false,
      }),
    ).toBe('You are a MicroRAG task agent for the product conversation runtime.')

    for (const prefix of CLI_SYSPROMPT_PREFIXES) {
      expectMicroRAGIdentity(prefix)
    }
  })

  test('simple system prompt path uses MicroRAG product identity', async () => {
    const previous = process.env.CLAUDE_CODE_SIMPLE
    process.env.CLAUDE_CODE_SIMPLE = '1'
    try {
      const prompt = await getSystemPrompt([], 'test-model')
      expect(prompt).toHaveLength(1)
      expect(prompt[0]).toContain(MICRORAG_IDENTITY)
      expect(prompt[0]).toContain('CWD:')
      expect(prompt[0]).toContain('Date:')
      expectMicroRAGIdentity(prompt[0])
    } finally {
      if (previous === undefined) {
        delete process.env.CLAUDE_CODE_SIMPLE
      } else {
        process.env.CLAUDE_CODE_SIMPLE = previous
      }
    }
  })

  test('default subagent prompt uses MicroRAG task agent identity', () => {
    expect(DEFAULT_AGENT_PROMPT).toContain('MicroRAG')
    expect(DEFAULT_AGENT_PROMPT).toContain('use the tools available')
    expect(DEFAULT_AGENT_PROMPT).toContain('respond with a concise report')
    expectMicroRAGIdentity(DEFAULT_AGENT_PROMPT)
  })

  test('coordinator prompt uses MicroRAG coordinator identity', () => {
    const prompt = getCoordinatorSystemPrompt()
    expect(prompt).toContain(
      'You are MicroRAG, an AI assistant that orchestrates software engineering tasks across multiple workers.',
    )
    expect(prompt).toContain('## 1. Your Role')
    expectMicroRAGIdentity(prompt)
  })
})
```

- [ ] **Step 2: Run the focused reference-runtime test and verify it fails**

Run:

```bash
cd "参考项目/claude-code" && bun test src/constants/__tests__/microragIdentity.test.ts
```

Expected:

```text
FAIL
```

Expected reason:

```text
expected ... to contain "MicroRAG"
```

The exact assertion line may vary, but failure must come from the old Claude Code identity still being present.

## Task 2: Patch Reference Runtime Model-Visible Identity Strings

Purpose: make the built-in system prompt identity layer own the MicroRAG product identity while preserving runtime behavior.

**Files:**
- Modify: `参考项目/claude-code/src/constants/system.ts`
- Modify: `参考项目/claude-code/src/constants/prompts.ts`
- Modify: `参考项目/claude-code/src/coordinator/coordinatorMode.ts`
- Test: `参考项目/claude-code/src/constants/__tests__/microragIdentity.test.ts`

- [ ] **Step 1: Patch CLI identity constants**

In `参考项目/claude-code/src/constants/system.ts`, replace only these three constants:

```typescript
const DEFAULT_PREFIX = `You are MicroRAG's product conversation agent.`
const AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX = `You are MicroRAG's product conversation agent, running in the local agent runtime.`
const AGENT_SDK_PREFIX = `You are a MicroRAG task agent for the product conversation runtime.`
```

Do not modify:

```typescript
getCLISyspromptPrefix()
CLI_SYSPROMPT_PREFIXES
getAttributionHeader()
```

Only the constants change.

- [ ] **Step 2: Patch simple prompt and default subagent prompt**

In `参考项目/claude-code/src/constants/prompts.ts`, update the `CLAUDE_CODE_SIMPLE` path inside `getSystemPrompt()` from:

```typescript
`You are Claude Code, Anthropic's official CLI for Claude.\n\nCWD: ${getCwd()}\nDate: ${getSessionStartDate()}`,
```

to:

```typescript
`You are MicroRAG's product conversation agent.\n\nCWD: ${getCwd()}\nDate: ${getSessionStartDate()}`,
```

Then update `DEFAULT_AGENT_PROMPT` from:

```typescript
export const DEFAULT_AGENT_PROMPT = `You are an agent for Claude Code, Anthropic's official CLI for Claude. Given the user's message, you should use the tools available to complete the task. Complete the task fully—don't gold-plate, but don't leave it half-done. When you complete the task, respond with a concise report covering what was done and any key findings — the caller will relay this to the user, so it only needs the essentials.`
```

to:

```typescript
export const DEFAULT_AGENT_PROMPT = `You are a MicroRAG task agent for the product conversation runtime. Given the user's message, you should use the tools available to complete the task. Complete the task fully—don't gold-plate, but don't leave it half-done. When you complete the task, respond with a concise report covering what was done and any key findings — the caller will relay this to the user, so it only needs the essentials.`
```

Do not edit unrelated system prompt rules in the same file.

- [ ] **Step 3: Patch coordinator identity sentence**

In `参考项目/claude-code/src/coordinator/coordinatorMode.ts`, update only the first sentence returned by `getCoordinatorSystemPrompt()` from:

```typescript
return `You are Claude Code, an AI assistant that orchestrates software engineering tasks across multiple workers.
```

to:

```typescript
return `You are MicroRAG, an AI assistant that orchestrates software engineering tasks across multiple workers.
```

Do not edit worker tool capability text or coordinator instructions.

- [ ] **Step 4: Run the focused reference-runtime test and verify it passes**

Run:

```bash
cd "参考项目/claude-code" && bun test src/constants/__tests__/microragIdentity.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 5: Run the reference runtime formatter/check if focused test changed formatting**

Run:

```bash
cd "参考项目/claude-code" && bun run check src/constants/system.ts src/constants/prompts.ts src/coordinator/coordinatorMode.ts src/constants/__tests__/microragIdentity.test.ts
```

Expected:

```text
0 errors
```

If `bun run check` does not accept file arguments in this repo, run:

```bash
cd "参考项目/claude-code" && bun run check
```

Expected:

```text
0 errors
```

Do not run `bun run check:fix` unless the check output requests formatting-only changes in files touched by this task.

## Task 3: Remove Duplicate Identity From MicroRAG CLAUDE.md Behavior Layer

Purpose: avoid duplicating the MicroRAG identity in both built-in system prompt and project/user context.

**Files:**
- Modify: `src/ragflow_lite/agent_runtime/CLAUDE.md`
- Modify: `data/agent-runtime/workspace/CLAUDE.md`

- [ ] **Step 1: Update the source runtime template**

Change `src/ragflow_lite/agent_runtime/CLAUDE.md` to exactly:

```markdown
# MicroRAG Product Agent

Use MicroRAG retrieval when the user asks about indexed local documents or when
document evidence is needed. Prefer the `microrag-search` skill for document
search.

Answer from retrieved evidence. If retrieval fails or the evidence is
insufficient, say that MicroRAG did not find enough evidence and ask the user to
clarify the question.

Do not expose runtime internals, command lines, local filesystem paths,
transcript files, process protocol details, provider branding, or developer
workflow details.

Do not invent evidence, citations, document facts, or source claims.
```

This removes only:

```text
You are MicroRAG's product conversation agent.
```

- [ ] **Step 2: Update the generated runtime workspace copy**

Change `data/agent-runtime/workspace/CLAUDE.md` to exactly the same content:

```markdown
# MicroRAG Product Agent

Use MicroRAG retrieval when the user asks about indexed local documents or when
document evidence is needed. Prefer the `microrag-search` skill for document
search.

Answer from retrieved evidence. If retrieval fails or the evidence is
insufficient, say that MicroRAG did not find enough evidence and ask the user to
clarify the question.

Do not expose runtime internals, command lines, local filesystem paths,
transcript files, process protocol details, provider branding, or developer
workflow details.

Do not invent evidence, citations, document facts, or source claims.
```

If `data/agent-runtime/workspace/CLAUDE.md` is untracked or gitignored, still update it because it is the current local runtime artifact the user is inspecting.

- [ ] **Step 3: Static check for duplicate identity wording in CLAUDE.md files**

Run:

```bash
rtk rg -n "You are MicroRAG's product conversation agent" src/ragflow_lite/agent_runtime/CLAUDE.md data/agent-runtime/workspace/CLAUDE.md
```

Expected:

```text
no matches
```

- [ ] **Step 4: Static check that behavior instructions remain**

Run:

```bash
rtk rg -n "Use MicroRAG retrieval|Answer from retrieved evidence|Do not expose runtime internals|Do not invent evidence" src/ragflow_lite/agent_runtime/CLAUDE.md data/agent-runtime/workspace/CLAUDE.md
```

Expected:

```text
src/ragflow_lite/agent_runtime/CLAUDE.md:3:Use MicroRAG retrieval ...
src/ragflow_lite/agent_runtime/CLAUDE.md:7:Answer from retrieved evidence ...
src/ragflow_lite/agent_runtime/CLAUDE.md:11:Do not expose runtime internals ...
src/ragflow_lite/agent_runtime/CLAUDE.md:15:Do not invent evidence ...
data/agent-runtime/workspace/CLAUDE.md:3:Use MicroRAG retrieval ...
data/agent-runtime/workspace/CLAUDE.md:7:Answer from retrieved evidence ...
data/agent-runtime/workspace/CLAUDE.md:11:Do not expose runtime internals ...
data/agent-runtime/workspace/CLAUDE.md:15:Do not invent evidence ...
```

Line numbers may shift by one if formatting changes, but all four behavior instructions must appear in both files.

## Task 4: Add MicroRAG Runtime Template Tests

Purpose: make sure future setup does not reintroduce duplicate identity wording into `CLAUDE.md`.

**Files:**
- Create or Modify: `tests/unit/test_agent_runtime_setup.py`
- Read: `src/ragflow_lite/agent_runtime/setup.py`
- Test: `tests/unit/test_agent_runtime_setup.py`

- [ ] **Step 1: Create or update the test file**

If `tests/unit/test_agent_runtime_setup.py` does not exist, create it. If it exists, append these tests without removing existing coverage:

```python
from __future__ import annotations

from pathlib import Path

from ragflow_lite.agent_runtime.setup import (
    AgentRuntimePaths,
    setup_agent_runtime,
)


def test_agent_runtime_claude_template_is_behavior_only() -> None:
    template = Path("src/ragflow_lite/agent_runtime/CLAUDE.md")
    text = template.read_text(encoding="utf-8")

    assert "You are MicroRAG's product conversation agent" not in text
    assert "Use MicroRAG retrieval" in text
    assert "Answer from retrieved evidence" in text
    assert "Do not expose runtime internals" in text
    assert "Do not invent evidence" in text


def test_setup_agent_runtime_copies_behavior_only_claude_md(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    paths = AgentRuntimePaths(
        project_root=project_root,
        config_dir=project_root / "data" / "agent-runtime" / "config",
        workspace_dir=project_root / "data" / "agent-runtime" / "workspace",
    )

    setup_agent_runtime(paths)

    text = (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "You are MicroRAG's product conversation agent" not in text
    assert "Use MicroRAG retrieval" in text
    assert "Answer from retrieved evidence" in text
    assert "Do not expose runtime internals" in text
    assert "Do not invent evidence" in text
```

- [ ] **Step 2: Run the focused MicroRAG test and verify it passes**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/test_agent_runtime_setup.py -q
```

Expected:

```text
2 passed
```

If the file already had tests, expected output may include more than two tests, but all tests in the file must pass.

## Task 5: Run Required Static Validation

Purpose: confirm no product-relevant prompt builder still contains old model-visible identity strings and no UI/API route exposes raw runtime branding unexpectedly.

**Files:**
- Read: `参考项目/claude-code/src/constants/system.ts`
- Read: `参考项目/claude-code/src/constants/prompts.ts`
- Read: `参考项目/claude-code/src/coordinator/coordinatorMode.ts`
- Read: `src/ragflow_lite/static/**`
- Read: `src/ragflow_lite/api/routes/**`
- Read: `src/ragflow_lite/infrastructure/agent/**`

- [ ] **Step 1: Run product-relevant reference-runtime identity search**

Run:

```bash
rtk rg -n "You are Claude Code|Anthropic's official CLI for Claude|Claude Agent SDK" "参考项目/claude-code/src/constants" "参考项目/claude-code/src/coordinator" "参考项目/claude-code/src/services" "参考项目/claude-code/src/utils" "参考项目/claude-code/src/tools.ts"
```

Expected:

```text
No matches in model-visible prompt builders.
```

If matches remain, classify them in the implementation report as one of:

```text
test fixture
docs/comment
package metadata
telemetry/internal request identity
unrelated mode outside current product runtime
```

If a remaining match is in a product-relevant model-visible prompt builder, return to Task 2 and patch it before continuing.

- [ ] **Step 2: Run broader source discovery for review notes**

Run:

```bash
rtk rg -n "You are Claude Code|Anthropic's official CLI|Claude Agent SDK|CLAUDE_CODE_SIMPLE|DEFAULT_PREFIX|getCLISyspromptPrefix|official CLI for Claude" "参考项目/claude-code/src" "参考项目/claude-code/docs/context/system-prompt.mdx"
```

Expected:

```text
Matches may remain in docs, tests, comments, package metadata, or unrelated implementation areas.
```

Document any remaining source-code matches that look model-visible.

- [ ] **Step 3: Run MicroRAG UI-facing branding search**

Run:

```bash
rtk rg -n "Claude Code|claude-code|Anthropic's official CLI" src/ragflow_lite/static src/ragflow_lite/api/routes src/ragflow_lite/infrastructure/agent
```

Expected:

```text
Only intentional redaction code or tests should match.
```

If production UI/API code can emit a raw brand string to the user, stop and report it as a separate finding. Do not broaden this plan into UI redaction work without user approval.

## Task 6: Run Focused Regression Tests

Purpose: verify the implementation did not break the reference prompt path or MicroRAG runtime setup path.

**Files:**
- Test: `参考项目/claude-code/src/constants/__tests__/microragIdentity.test.ts`
- Test: `tests/unit/test_agent_runtime_setup.py`
- Test: `tests/unit/test_reference_claude_code_script.py`
- Test: `tests/unit/infrastructure/test_acp_client_redaction.py`
- Test: `tests/unit/api/test_agent_routes.py`

- [ ] **Step 1: Run focused reference-runtime prompt test**

Run:

```bash
cd "参考项目/claude-code" && bun test src/constants/__tests__/microragIdentity.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 2: Run focused MicroRAG runtime/setup tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/test_agent_runtime_setup.py tests/unit/test_reference_claude_code_script.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 3: Run focused MicroRAG agent route/redaction tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/api/test_agent_routes.py -q
```

Expected:

```text
all selected tests pass
```

If existing dirty worktree changes cause unrelated failures, do not rewrite unrelated files. Capture the failing test names, error messages, and whether the failure is caused by this plan's files.

## Task 7: Final Review And Manual Acceptance Handoff

Purpose: summarize the exact implementation boundary and leave conversational validation to the user.

**Files:**
- Read: `git diff -- docs/superpowers/specs/2026-05-16-microrag-agent-system-prompt-identity-boundary.md docs/superpowers/plans/2026-05-16-microrag-agent-system-prompt-identity-boundary.md 参考项目/claude-code/src/constants/system.ts 参考项目/claude-code/src/constants/prompts.ts 参考项目/claude-code/src/coordinator/coordinatorMode.ts src/ragflow_lite/agent_runtime/CLAUDE.md data/agent-runtime/workspace/CLAUDE.md tests/unit/test_agent_runtime_setup.py`

- [ ] **Step 1: Review the final diff**

Run:

```bash
rtk git diff -- docs/superpowers/specs/2026-05-16-microrag-agent-system-prompt-identity-boundary.md docs/superpowers/plans/2026-05-16-microrag-agent-system-prompt-identity-boundary.md "参考项目/claude-code/src/constants/system.ts" "参考项目/claude-code/src/constants/prompts.ts" "参考项目/claude-code/src/coordinator/coordinatorMode.ts" src/ragflow_lite/agent_runtime/CLAUDE.md data/agent-runtime/workspace/CLAUDE.md tests/unit/test_agent_runtime_setup.py
```

Expected:

```text
Diff only changes model-visible identity strings, CLAUDE.md duplicate identity wording, focused tests, and this plan/spec documentation.
```

- [ ] **Step 2: Confirm no automated conversational smoke test was run as a pass/fail gate**

Do not run live LLM conversation prompts as automated validation. Report the manual acceptance checklist to the user:

```text
你好
你是谁？
你是 Claude Code 吗？
你的运行环境是什么？
```

Expected report language:

```text
Manual LLM conversation acceptance remains for you to run because the wording is nondeterministic.
```

- [ ] **Step 3: Summarize verification**

Final implementation report must include:

```text
Changed files:
- reference runtime identity prompt files
- MicroRAG CLAUDE.md behavior files
- focused tests

Automated validation run:
- bun test src/constants/__tests__/microragIdentity.test.ts
- pytest tests/unit/test_agent_runtime_setup.py tests/unit/test_reference_claude_code_script.py -q
- pytest tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/api/test_agent_routes.py -q
- static rg checks

Not run:
- automated/live LLM smoke test

Manual acceptance left for user:
- 你好
- 你是谁？
- 你是 Claude Code 吗？
- 你的运行环境是什么？
```

- [ ] **Step 4: Do not commit unless the user asks**

This repo already has unrelated dirty changes. Do not create a commit in the implementation pass unless the user explicitly asks for commit/push.

## Self-Review Checklist

- Spec coverage: Tasks cover identity prompt strings, duplicate `CLAUDE.md` identity removal, static validation, focused tests, and manual acceptance handoff.
- Scope boundary: Plan does not edit provider code, request headers, telemetry, package metadata, API schema, CI, or UI behavior.
- Placeholder scan: No `TBD`, `TODO`, `fill in`, or open-ended implementation placeholders are allowed in this plan.
- Type consistency: TypeScript tests import only exported prompt functions/constants or public modules named in the reference runtime source.
- Validation boundary: LLM conversation is a user-run manual acceptance checklist, not an automated smoke test.
