# MicroAgent Conversation Goal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foreground-only, conversation-scoped `/goal` runtime specified in `docs/superpowers/specs/2026-06-03-microagent-conversation-goal.md`.

**Architecture:** Add a small goal domain layer that owns `ConversationGoal` state transitions, persistence, and display text. Wire it into the existing transcript metadata path, built-in slash-command registry, model tool pool, REPL state, spinner, and turn finalization. Keep continuation foreground-only and schedule one goal-driven turn at a time from the REPL idle boundary, outside the inner `query.ts` loop.

**Tech Stack:** TypeScript, Bun test, React/Ink, existing MicroAgent `Command`, `Tool`, `AppState`, `sessionStorage`, `query.ts`, and `screens/REPL.tsx` infrastructure.

---

## Source Spec

Implement against:

- `docs/superpowers/specs/2026-06-03-microagent-conversation-goal.md`
- Commit `c35b14e docs: define goal runtime visibility`

The first implementation is explicitly not a daemon/background feature and does not add a shell CLI mirror. The only user command surface is interactive REPL `/goal`.

## Fixed Implementation Decisions

These answer the spec's open implementation questions for the first pass:

- Retry limit: 3 consecutive failed continuation attempts.
- Retry backoff: 2 seconds, then 5 seconds, then 15 seconds.
- Foreground continuation lease timeout: 30 seconds.
- Objective validation: trimmed objective must be 1 to 4000 characters.
- `/goal edit` first implementation: `/goal edit <new objective>` performs replacement. Bare `/goal edit` returns a clear usage error instead of launching a modal editor.
- `/goal <objective>` never parses inline budget syntax. Token budget support remains lower-level only in this implementation.
- Lifecycle notifications use the existing notifications context where a hook/component has access to it, and transcript-local command output where a slash command needs persistent scrollback.

## File Structure

Create:

- `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`
  - Owns `ConversationGoal`, `GoalStatus`, validation, replacement semantics, state transitions, accounting, lease acquire/release helpers, status display text, and persistence entry helpers.
- `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`
  - Pure unit tests for validation, state transitions, replacement, tombstone restore, lease CAS, and status display text.
- `src/ragflow_lite/microagent/src/commands/goal/index.ts`
  - Built-in local `/goal` command. Parses reserved words, mutates current goal state through `conversationGoal.ts`, returns user-visible lifecycle text, and never directly starts a model turn.
- `src/ragflow_lite/microagent/src/commands/__tests__/goal.test.ts`
  - Command-level tests for `/goal`, `/goal <objective>`, `/goal edit <objective>`, `/goal pause`, `/goal resume`, `/goal clear`, and invalid input.
- `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/constants.ts`
  - Exports the model-facing goal update tool name.
- `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/prompt.ts`
  - Tool description and prompt text that limits the model to `complete` or `blocked`.
- `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/GoalUpdateTool.ts`
  - Model-visible controlled update path for `complete` and `blocked` only.
- `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/__tests__/GoalUpdateTool.test.ts`
  - Tool tests for allowed statuses, rejected statuses, missing active goal, and persisted lifecycle notifications.
- `src/ragflow_lite/microagent/src/hooks/useConversationGoalController.ts`
  - Foreground REPL controller that schedules exactly one continuation after idle when an active goal is eligible.
- `src/ragflow_lite/microagent/src/hooks/__tests__/useConversationGoalController.test.tsx`
  - Hook/controller tests for idle scheduling, user input preemption, lease contention, terminal states, and retry exhaustion.

Modify:

- `src/ragflow_lite/microagent/src/types/logs.ts`
  - Add `ConversationGoalEntry` and `ConversationGoalClearedEntry` to the transcript `Entry` union.
- `src/ragflow_lite/microagent/src/utils/sessionStorage.ts`
  - Cache current goal metadata, append goal entries in `reAppendSessionMetadata()`, expose save/clear/restore helpers, and avoid metadata-only transcript creation.
- `src/ragflow_lite/microagent/src/utils/sessionRestore.ts`
  - Restore the latest effective goal state on `--resume`, `--continue`, and `/resume` paths.
- `src/ragflow_lite/microagent/src/state/AppStateStore.ts`
  - Add transient `conversationGoal` and `goalContinuation` UI state for running indicators and notification coordination. It remains a runtime cache, not durable storage.
- `src/ragflow_lite/microagent/src/commands.ts`
  - Register the built-in `goal` command so it appears in command recognition, help, and typeahead.
- `src/ragflow_lite/microagent/src/utils/processUserInput/processSlashCommand.tsx`
  - No parser rewrite. Confirm local command output handling preserves `/goal` lifecycle text as system command output.
- `src/ragflow_lite/microagent/src/utils/suggestions/commandSuggestions.ts`
  - Add focused tests that `generateCommandSuggestions('/go', commands)` returns `/goal`.
- `src/ragflow_lite/microagent/src/components/Spinner.tsx`
  - Display goal-running indicator text when a goal-driven continuation turn is running.
- `src/ragflow_lite/microagent/src/screens/REPL.tsx`
  - Start/stop the foreground continuation controller at idle boundaries, pass goal-running spinner text, pause goal on user interrupt during goal-driven turn, and emit lifecycle notifications.
- `src/ragflow_lite/microagent/src/tools.ts`
  - Include `GoalUpdateTool` in the base tool pool.
- `src/ragflow_lite/microagent/src/QueryEngine.ts`
  - Inject goal context into model-visible runtime context for goal-driven turns and call finalization hooks after query completion.
- `src/ragflow_lite/microagent/src/query.ts`
  - Keep inner loop free of goal scheduling. Expose or preserve terminal reason/usage data needed by `QueryEngine`/REPL finalization.
- `src/ragflow_lite/microagent/src/utils/__tests__/sessionStorage.test.ts`
  - Add persistence restore/tombstone tests for conversation goal metadata.
- `src/ragflow_lite/microagent/src/utils/processUserInput/__tests__/processSlashCommand.test.ts`
  - Add a registration-level test that `/goal` is recognized as a built-in slash command.

## Task 1: Pure Conversation Goal Domain

**Files:**
- Create: `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`
- Create: `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`

- [ ] **Step 1: Write failing validation and replacement tests**

Create `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`:

```ts
import { describe, expect, test } from 'bun:test'
import {
  createConversationGoal,
  replaceConversationGoal,
  validateGoalObjective,
} from '../conversationGoal.js'

describe('conversation goal domain', () => {
  test('rejects empty and oversized objectives', () => {
    expect(validateGoalObjective('   ')).toEqual({
      ok: false,
      error: 'Goal objective cannot be empty',
    })
    expect(validateGoalObjective('x'.repeat(4001))).toEqual({
      ok: false,
      error: 'Goal objective must be 4000 characters or fewer',
    })
  })

  test('creates an active goal with initial accounting', () => {
    const goal = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Ship the goal runtime',
      now: '2026-06-04T00:00:00.000Z',
      id: 'goal-1',
    })

    expect(goal).toMatchObject({
      conversationId: 'session-1',
      goalId: 'goal-1',
      revision: 1,
      objective: 'Ship the goal runtime',
      status: 'active',
      tokenBudget: null,
      tokensUsed: 0,
      timeUsedSeconds: 0,
      failureCount: 0,
      lastError: null,
      continuationOwner: null,
    })
  })

  test('replacement creates a new goal id and resets accounting', () => {
    const oldGoal = {
      ...createConversationGoal({
        conversationId: 'session-1',
        objective: 'Old objective',
        now: '2026-06-04T00:00:00.000Z',
        id: 'goal-old',
      }),
      tokensUsed: 123,
      timeUsedSeconds: 45,
      failureCount: 2,
      lastError: 'previous failure',
      continuationOwner: {
        ownerId: 'owner-old',
        processId: 123,
        acquiredAt: '2026-06-04T00:00:01.000Z',
        expiresAt: '2026-06-04T00:00:31.000Z',
      },
    }

    const newGoal = replaceConversationGoal(oldGoal, {
      objective: 'New objective',
      now: '2026-06-04T00:01:00.000Z',
      id: 'goal-new',
    })

    expect(newGoal).toMatchObject({
      conversationId: 'session-1',
      goalId: 'goal-new',
      revision: 1,
      objective: 'New objective',
      status: 'active',
      tokenBudget: null,
      tokensUsed: 0,
      timeUsedSeconds: 0,
      failureCount: 0,
      lastError: null,
      continuationOwner: null,
    })
  })
})
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
```

Expected: FAIL because `src/utils/conversationGoal.ts` does not exist.

- [ ] **Step 3: Implement domain types, validation, create, and replacement**

Create `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`:

```ts
import { randomUUID } from 'crypto'

export const GOAL_OBJECTIVE_MAX_LENGTH = 4000

export type GoalStatus =
  | 'active'
  | 'paused'
  | 'blocked'
  | 'usageLimited'
  | 'budgetLimited'
  | 'complete'

export type GoalContinuationOwner = {
  ownerId: string
  processId: number
  acquiredAt: string
  expiresAt: string
}

export type ConversationGoal = {
  conversationId: string
  goalId: string
  revision: number
  objective: string
  status: GoalStatus
  tokenBudget?: number | null
  tokensUsed: number
  timeUsedSeconds: number
  createdAt: string
  updatedAt: string
  lastTurnId?: string | null
  lastContinuationAt?: string | null
  continuationOwner?: GoalContinuationOwner | null
  failureCount: number
  lastError?: string | null
  blockedReason?: string | null
}

export type ConversationGoalEntry = {
  type: 'conversation-goal'
  sessionId: string
  goal: ConversationGoal
  timestamp: string
}

export type ConversationGoalClearedEntry = {
  type: 'conversation-goal-cleared'
  sessionId: string
  goalId: string
  clearedAt: string
}

export type GoalValidationResult =
  | { ok: true; objective: string }
  | { ok: false; error: string }

export function validateGoalObjective(objective: string): GoalValidationResult {
  const trimmed = objective.trim()
  if (!trimmed) {
    return { ok: false, error: 'Goal objective cannot be empty' }
  }
  if (trimmed.length > GOAL_OBJECTIVE_MAX_LENGTH) {
    return {
      ok: false,
      error: `Goal objective must be ${GOAL_OBJECTIVE_MAX_LENGTH} characters or fewer`,
    }
  }
  return { ok: true, objective: trimmed }
}

export function validateGoalTokenBudget(
  tokenBudget: number | null | undefined,
): { ok: true; tokenBudget: number | null } | { ok: false; error: string } {
  if (tokenBudget === undefined || tokenBudget === null) {
    return { ok: true, tokenBudget: null }
  }
  if (!Number.isInteger(tokenBudget) || tokenBudget <= 0) {
    return { ok: false, error: 'Goal token budget must be an integer greater than zero' }
  }
  return { ok: true, tokenBudget }
}

export function createConversationGoal(params: {
  conversationId: string
  objective: string
  now?: string
  id?: string
  tokenBudget?: number | null
}): ConversationGoal {
  const validation = validateGoalObjective(params.objective)
  if (!validation.ok) throw new Error(validation.error)
  const budget = validateGoalTokenBudget(params.tokenBudget)
  if (!budget.ok) throw new Error(budget.error)
  const now = params.now ?? new Date().toISOString()
  return {
    conversationId: params.conversationId,
    goalId: params.id ?? randomUUID(),
    revision: 1,
    objective: validation.objective,
    status: 'active',
    tokenBudget: budget.tokenBudget,
    tokensUsed: 0,
    timeUsedSeconds: 0,
    createdAt: now,
    updatedAt: now,
    lastTurnId: null,
    lastContinuationAt: null,
    continuationOwner: null,
    failureCount: 0,
    lastError: null,
    blockedReason: null,
  }
}

export function replaceConversationGoal(
  current: ConversationGoal,
  params: {
    objective: string
    now?: string
    id?: string
    tokenBudget?: number | null
  },
): ConversationGoal {
  return createConversationGoal({
    conversationId: current.conversationId,
    objective: params.objective,
    now: params.now,
    id: params.id,
    tokenBudget: params.tokenBudget,
  })
}
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
```

Expected: PASS.

- [ ] **Step 5: Add state-transition, accounting, restore, and lease tests**

Append to `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`:

```ts
import {
  acquireGoalContinuationLease,
  applyGoalAccounting,
  clearConversationGoal,
  getEffectiveConversationGoalFromEntries,
  markGoalBlocked,
  markGoalComplete,
  pauseConversationGoal,
  releaseGoalContinuationLease,
  resumeConversationGoal,
} from '../conversationGoal.js'

describe('conversation goal state transitions', () => {
  const baseGoal = () =>
    createConversationGoal({
      conversationId: 'session-1',
      objective: 'Ship',
      now: '2026-06-04T00:00:00.000Z',
      id: 'goal-1',
    })

  test('only user/runtime transitions can pause and resume', () => {
    const paused = pauseConversationGoal(baseGoal(), '2026-06-04T00:01:00.000Z')
    expect(paused.status).toBe('paused')
    expect(paused.revision).toBe(2)

    const resumed = resumeConversationGoal(paused, '2026-06-04T00:02:00.000Z')
    expect(resumed.status).toBe('active')
    expect(resumed.revision).toBe(3)
  })

  test('model update path only marks complete or blocked', () => {
    expect(markGoalComplete(baseGoal(), '2026-06-04T00:03:00.000Z').status).toBe('complete')
    const blocked = markGoalBlocked(baseGoal(), 'Need user input', '2026-06-04T00:03:00.000Z')
    expect(blocked.status).toBe('blocked')
    expect(blocked.blockedReason).toBe('Need user input')
  })

  test('token accounting moves active goal to budgetLimited', () => {
    const goal = { ...baseGoal(), tokenBudget: 100, tokensUsed: 90 }
    const updated = applyGoalAccounting(goal, {
      tokenDelta: 10,
      elapsedSeconds: 2,
      now: '2026-06-04T00:04:00.000Z',
      turnId: 'turn-1',
    })
    expect(updated.status).toBe('budgetLimited')
    expect(updated.tokensUsed).toBe(100)
    expect(updated.timeUsedSeconds).toBe(2)
    expect(updated.lastTurnId).toBe('turn-1')
  })

  test('clear tombstone wins over older goal entry', () => {
    const goal = baseGoal()
    const entries = [
      { type: 'conversation-goal' as const, sessionId: 'session-1', goal, timestamp: goal.updatedAt },
      clearConversationGoal(goal, '2026-06-04T00:05:00.000Z'),
    ]
    expect(getEffectiveConversationGoalFromEntries(entries)).toBeNull()
  })

  test('lease acquire uses goal id and revision and rejects unexpired owner', () => {
    const goal = baseGoal()
    const acquired = acquireGoalContinuationLease(goal, {
      ownerId: 'owner-a',
      processId: 111,
      nowMs: Date.parse('2026-06-04T00:00:00.000Z'),
      leaseMs: 30_000,
    })
    expect(acquired.ok).toBe(true)
    if (!acquired.ok) throw new Error('expected lease acquire')

    const denied = acquireGoalContinuationLease(acquired.goal, {
      ownerId: 'owner-b',
      processId: 222,
      nowMs: Date.parse('2026-06-04T00:00:10.000Z'),
      leaseMs: 30_000,
    })
    expect(denied.ok).toBe(false)

    const released = releaseGoalContinuationLease(acquired.goal, 'owner-a', '2026-06-04T00:00:15.000Z')
    expect(released.continuationOwner).toBeNull()
  })
})
```

- [ ] **Step 6: Implement transition, accounting, restore, and lease helpers**

Append these exports to `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`:

```ts
function bump(goal: ConversationGoal, now: string): ConversationGoal {
  return { ...goal, revision: goal.revision + 1, updatedAt: now }
}

export function pauseConversationGoal(goal: ConversationGoal, now = new Date().toISOString()): ConversationGoal {
  if (goal.status !== 'active') return goal
  return { ...bump(goal, now), status: 'paused', continuationOwner: null }
}

export function resumeConversationGoal(goal: ConversationGoal, now = new Date().toISOString()): ConversationGoal {
  if (goal.status !== 'paused' && goal.status !== 'blocked' && goal.status !== 'usageLimited') return goal
  return { ...bump(goal, now), status: 'active', failureCount: 0, lastError: null, continuationOwner: null }
}

export function markGoalComplete(goal: ConversationGoal, now = new Date().toISOString()): ConversationGoal {
  if (goal.status !== 'active') return goal
  return { ...bump(goal, now), status: 'complete', continuationOwner: null }
}

export function markGoalBlocked(
  goal: ConversationGoal,
  reason: string | undefined,
  now = new Date().toISOString(),
): ConversationGoal {
  if (goal.status !== 'active') return goal
  return {
    ...bump(goal, now),
    status: 'blocked',
    blockedReason: reason?.trim() || null,
    continuationOwner: null,
  }
}

export function applyGoalAccounting(
  goal: ConversationGoal,
  params: { tokenDelta: number; elapsedSeconds: number; now: string; turnId: string },
): ConversationGoal {
  const tokensUsed = goal.tokensUsed + Math.max(0, params.tokenDelta)
  const timeUsedSeconds = goal.timeUsedSeconds + Math.max(0, params.elapsedSeconds)
  const status =
    goal.status === 'active' &&
    goal.tokenBudget != null &&
    tokensUsed >= goal.tokenBudget
      ? 'budgetLimited'
      : goal.status
  return {
    ...bump(goal, params.now),
    status,
    tokensUsed,
    timeUsedSeconds,
    lastTurnId: params.turnId,
    continuationOwner: status === 'active' ? goal.continuationOwner ?? null : null,
  }
}

export function clearConversationGoal(
  goal: ConversationGoal,
  clearedAt = new Date().toISOString(),
): ConversationGoalClearedEntry {
  return {
    type: 'conversation-goal-cleared',
    sessionId: goal.conversationId,
    goalId: goal.goalId,
    clearedAt,
  }
}

export function conversationGoalEntry(
  goal: ConversationGoal,
  timestamp = new Date().toISOString(),
): ConversationGoalEntry {
  return {
    type: 'conversation-goal',
    sessionId: goal.conversationId,
    goal,
    timestamp,
  }
}

export function getEffectiveConversationGoalFromEntries(
  entries: Array<ConversationGoalEntry | ConversationGoalClearedEntry>,
): ConversationGoal | null {
  let current: ConversationGoal | null = null
  for (const entry of entries) {
    if (entry.type === 'conversation-goal') {
      current = entry.goal
      continue
    }
    if (entry.type === 'conversation-goal-cleared' && current?.goalId === entry.goalId) {
      current = null
    }
  }
  return current
}

export function acquireGoalContinuationLease(
  goal: ConversationGoal,
  params: { ownerId: string; processId: number; nowMs: number; leaseMs: number },
): { ok: true; goal: ConversationGoal } | { ok: false; reason: 'not-active' | 'owned' } {
  if (goal.status !== 'active') return { ok: false, reason: 'not-active' }
  const current = goal.continuationOwner
  if (current && Date.parse(current.expiresAt) > params.nowMs && current.ownerId !== params.ownerId) {
    return { ok: false, reason: 'owned' }
  }
  const acquiredAt = new Date(params.nowMs).toISOString()
  const expiresAt = new Date(params.nowMs + params.leaseMs).toISOString()
  return {
    ok: true,
    goal: {
      ...goal,
      revision: goal.revision + 1,
      updatedAt: acquiredAt,
      continuationOwner: {
        ownerId: params.ownerId,
        processId: params.processId,
        acquiredAt,
        expiresAt,
      },
    },
  }
}

export function releaseGoalContinuationLease(
  goal: ConversationGoal,
  ownerId: string,
  now = new Date().toISOString(),
): ConversationGoal {
  if (goal.continuationOwner?.ownerId !== ownerId) return goal
  return { ...bump(goal, now), continuationOwner: null }
}
```

- [ ] **Step 7: Run tests to verify pass**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ragflow_lite/microagent/src/utils/conversationGoal.ts src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts
git commit -m "feat: add conversation goal domain"
```

## Task 2: Transcript Persistence And Resume Restore

**Files:**
- Modify: `src/ragflow_lite/microagent/src/types/logs.ts`
- Modify: `src/ragflow_lite/microagent/src/utils/sessionStorage.ts`
- Modify: `src/ragflow_lite/microagent/src/utils/sessionRestore.ts`
- Test: `src/ragflow_lite/microagent/src/utils/__tests__/sessionStorage.test.ts`

- [ ] **Step 1: Write failing session metadata tests**

Create `src/ragflow_lite/microagent/src/utils/__tests__/sessionStorage.test.ts`:

```ts
import { describe, expect, test } from 'bun:test'
import {
  clearConversationGoal,
  createConversationGoal,
} from '../conversationGoal.js'
import {
  cacheConversationGoal,
  cacheConversationGoalCleared,
  getCurrentConversationGoal,
  restoreConversationGoalFromEntriesForTests,
  saveConversationGoal,
  saveConversationGoalCleared,
} from '../sessionStorage.js'

describe('conversation goal transcript metadata', () => {
  test('cache exposes the current conversation goal', () => {
    cacheConversationGoal(null)
    expect(getCurrentConversationGoal()).toBeNull()

    const goal = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Current goal',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })

    cacheConversationGoal(goal)
    expect(getCurrentConversationGoal()?.goalId).toBe('goal-1')
    expect(getCurrentConversationGoal()?.objective).toBe('Current goal')
  })

  test('latest goal metadata restores the current goal', () => {
    const first = createConversationGoal({
      conversationId: 'session-1',
      objective: 'First goal',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })
    const second = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Second goal',
      id: 'goal-2',
      now: '2026-06-04T00:01:00.000Z',
    })

    const restored = restoreConversationGoalFromEntriesForTests([
      { type: 'conversation-goal', sessionId: 'session-1', goal: first, timestamp: first.updatedAt },
      { type: 'conversation-goal', sessionId: 'session-1', goal: second, timestamp: second.updatedAt },
    ])

    expect(restored?.goalId).toBe('goal-2')
    expect(restored?.objective).toBe('Second goal')
  })

  test('clear tombstone prevents older goal resurrection', () => {
    const goal = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Clear me',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })

    const tombstone = clearConversationGoal(goal, '2026-06-04T00:01:00.000Z')
    const restored = restoreConversationGoalFromEntriesForTests([
      { type: 'conversation-goal', sessionId: 'session-1', goal, timestamp: goal.updatedAt },
      tombstone,
    ])

    expect(restored).toBeNull()
  })

  test('save helpers update in-memory cache without creating metadata-only transcripts', () => {
    const goal = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Save me',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })
    const tombstone = clearConversationGoal(goal, '2026-06-04T00:01:00.000Z')

    saveConversationGoal(goal)
    expect(getCurrentConversationGoal()?.goalId).toBe('goal-1')

    saveConversationGoalCleared(tombstone)
    expect(getCurrentConversationGoal()).toBeNull()

    cacheConversationGoal(goal)
    cacheConversationGoalCleared(tombstone)
    expect(getCurrentConversationGoal()).toBeNull()
  })
})
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/sessionStorage.test.ts
```

Expected: FAIL because `sessionStorage.ts` does not export the conversation goal metadata helpers yet.

- [ ] **Step 3: Add transcript entry types**

Modify `src/ragflow_lite/microagent/src/types/logs.ts`:

```ts
import type {
  ConversationGoalClearedEntry,
  ConversationGoalEntry,
} from 'src/utils/conversationGoal.js'
```

Then add both entries to the `Entry` union:

```ts
  | ConversationGoalEntry
  | ConversationGoalClearedEntry
```

- [ ] **Step 4: Add sessionStorage cache and save helpers**

Modify the `Project` class in `src/ragflow_lite/microagent/src/utils/sessionStorage.ts` to add:

```ts
currentConversationGoal?: ConversationGoal | null
currentConversationGoalCleared?: ConversationGoalClearedEntry | null
```

Add exports near other metadata helper exports:

```ts
import {
  type ConversationGoal,
  type ConversationGoalClearedEntry,
  type ConversationGoalEntry,
  conversationGoalEntry,
  getEffectiveConversationGoalFromEntries,
} from './conversationGoal.js'

export function getCurrentConversationGoal(): ConversationGoal | null {
  return getProject().currentConversationGoal ?? null
}

export function cacheConversationGoal(goal: ConversationGoal | null): void {
  const project = getProject()
  project.currentConversationGoal = goal
  if (goal) project.currentConversationGoalCleared = null
}

export function cacheConversationGoalCleared(entry: ConversationGoalClearedEntry): void {
  const project = getProject()
  project.currentConversationGoal = null
  project.currentConversationGoalCleared = entry
}

export function saveConversationGoal(goal: ConversationGoal): void {
  const project = getProject()
  project.currentConversationGoal = goal
  project.currentConversationGoalCleared = null
  if (!project.sessionFile) return
  appendEntryToFile(project.sessionFile, conversationGoalEntry(goal))
}

export function saveConversationGoalCleared(entry: ConversationGoalClearedEntry): void {
  const project = getProject()
  project.currentConversationGoal = null
  project.currentConversationGoalCleared = entry
  if (!project.sessionFile) return
  appendEntryToFile(project.sessionFile, entry)
}

export function restoreConversationGoalFromEntriesForTests(
  entries: Array<ConversationGoalEntry | ConversationGoalClearedEntry>,
): ConversationGoal | null {
  return getEffectiveConversationGoalFromEntries(entries)
}
```

In `Project.reAppendSessionMetadata()`, append goal metadata after existing cached session metadata:

```ts
if (this.currentConversationGoal) {
  appendEntryToFile(this.sessionFile, conversationGoalEntry(this.currentConversationGoal))
} else if (this.currentConversationGoalCleared) {
  appendEntryToFile(this.sessionFile, this.currentConversationGoalCleared)
}
```

- [ ] **Step 5: Restore goal metadata during resume**

Extend `restoreSessionMetadata()` in `src/ragflow_lite/microagent/src/utils/sessionStorage.ts`:

```ts
export function restoreSessionMetadata(meta: {
  customTitle?: string
  tag?: string
  agentName?: string
  agentColor?: string
  agentSetting?: string
  mode?: 'coordinator' | 'normal'
  worktreeSession?: PersistedWorktreeSession | null
  prNumber?: number
  prUrl?: string
  prRepository?: string
  conversationGoal?: ConversationGoal | null
}): void {
  const project = getProject()
  // existing assignments stay as-is
  if (meta.conversationGoal !== undefined) {
    project.currentConversationGoal = meta.conversationGoal
    project.currentConversationGoalCleared = null
  }
}
```

Update `loadTranscriptFile()` metadata scanning to collect `conversation-goal` and `conversation-goal-cleared` entries into an ordered list and return `conversationGoal` as the latest effective state. Apply the same helper in both normal metadata scan and pre-boundary metadata recovery paths.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts src/utils/__tests__/sessionStorage.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ragflow_lite/microagent/src/types/logs.ts src/ragflow_lite/microagent/src/utils/sessionStorage.ts src/ragflow_lite/microagent/src/utils/sessionRestore.ts src/ragflow_lite/microagent/src/utils/__tests__/sessionStorage.test.ts
git commit -m "feat: persist conversation goals"
```

## Task 3: App State And Lifecycle Display Helpers

**Files:**
- Modify: `src/ragflow_lite/microagent/src/state/AppStateStore.ts`
- Modify: `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`
- Test: `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`

- [ ] **Step 1: Write failing display helper tests**

Append to `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`:

```ts
import {
  formatGoalLifecycleNotification,
  formatGoalSummary,
  shortGoalObjective,
} from '../conversationGoal.js'

describe('conversation goal display helpers', () => {
  test('shortens long objective labels', () => {
    expect(shortGoalObjective('x'.repeat(90))).toBe(`${'x'.repeat(77)}...`)
  })

  test('formats lifecycle notifications from runtime state', () => {
    const goal = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Ship visible goals',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })

    expect(formatGoalLifecycleNotification('started', goal)).toBe('Goal started: Ship visible goals')
    expect(formatGoalLifecycleNotification('complete', { ...goal, status: 'complete' })).toBe(
      'Goal complete: Ship visible goals',
    )
  })

  test('summary shows terminal states', () => {
    const goal = {
      ...createConversationGoal({
        conversationId: 'session-1',
        objective: 'Finish',
        id: 'goal-1',
        now: '2026-06-04T00:00:00.000Z',
      }),
      status: 'complete' as const,
    }
    expect(formatGoalSummary(goal)).toContain('Status: complete')
    expect(formatGoalSummary(goal)).toContain('Objective: Finish')
  })
})
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
```

Expected: FAIL because display helpers are not implemented.

- [ ] **Step 3: Add display helpers**

Append to `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`:

```ts
export type GoalLifecycleEvent =
  | 'started'
  | 'replaced'
  | 'paused'
  | 'resumed'
  | 'cleared'
  | 'complete'
  | 'blocked'
  | 'budgetLimited'
  | 'usageLimited'

export function shortGoalObjective(objective: string, max = 80): string {
  const normalized = objective.replace(/\s+/g, ' ').trim()
  if (normalized.length <= max) return normalized
  return `${normalized.slice(0, Math.max(0, max - 3))}...`
}

export function formatGoalLifecycleNotification(event: GoalLifecycleEvent, goal: ConversationGoal): string {
  const label = shortGoalObjective(goal.objective)
  switch (event) {
    case 'started':
      return `Goal started: ${label}`
    case 'replaced':
      return `Goal replaced: ${label}`
    case 'paused':
      return `Goal paused: ${label}`
    case 'resumed':
      return `Goal resumed: ${label}`
    case 'cleared':
      return `Goal cleared: ${label}`
    case 'complete':
      return `Goal complete: ${label}`
    case 'blocked':
      return goal.blockedReason ? `Goal blocked: ${label} (${goal.blockedReason})` : `Goal blocked: ${label}`
    case 'budgetLimited':
      return `Goal budget limited: ${label}`
    case 'usageLimited':
      return `Goal usage limited: ${label}`
  }
}

export function formatGoalSummary(goal: ConversationGoal | null): string {
  if (!goal) {
    return [
      'No current goal.',
      '',
      'Usage:',
      '/goal <objective>',
      '/goal',
      '/goal edit <new objective>',
      '/goal pause',
      '/goal resume',
      '/goal clear',
    ].join('\n')
  }
  return [
    `Goal: ${shortGoalObjective(goal.objective)}`,
    `Status: ${goal.status}`,
    `Objective: ${goal.objective}`,
    `Goal ID: ${goal.goalId}`,
    `Tokens: ${goal.tokensUsed}${goal.tokenBudget ? ` / ${goal.tokenBudget}` : ''}`,
    `Time used: ${goal.timeUsedSeconds}s`,
    goal.blockedReason ? `Blocked reason: ${goal.blockedReason}` : null,
    '',
    'Actions:',
    '/goal edit <new objective>',
    '/goal pause',
    '/goal resume',
    '/goal clear',
  ]
    .filter((line): line is string => line !== null)
    .join('\n')
}
```

- [ ] **Step 4: Add AppState runtime cache**

Modify `src/ragflow_lite/microagent/src/state/AppStateStore.ts`.

Add imports:

```ts
import type { ConversationGoal } from '../utils/conversationGoal.js'
```

Add to `AppState`:

```ts
  conversationGoal: ConversationGoal | null
  goalContinuation: {
    runningGoalId: string | null
    runningObjective: string | null
    ownerId: string | null
  }
```

Add to `getDefaultAppState()`:

```ts
    conversationGoal: null,
    goalContinuation: {
      runningGoalId: null,
      runningObjective: null,
      ownerId: null,
    },
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
cd src/ragflow_lite/microagent && bun run typecheck
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ragflow_lite/microagent/src/state/AppStateStore.ts src/ragflow_lite/microagent/src/utils/conversationGoal.ts src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts
git commit -m "feat: add goal display state"
```

## Task 4: Built-In `/goal` Slash Command

**Files:**
- Create: `src/ragflow_lite/microagent/src/commands/goal/index.ts`
- Create: `src/ragflow_lite/microagent/src/commands/__tests__/goal.test.ts`
- Modify: `src/ragflow_lite/microagent/src/commands.ts`
- Modify: `src/ragflow_lite/microagent/src/utils/processUserInput/__tests__/processSlashCommand.test.ts`
- Modify: `src/ragflow_lite/microagent/src/utils/suggestions/__tests__/commandSuggestions.test.ts`

- [ ] **Step 1: Write failing command behavior tests**

Create `src/ragflow_lite/microagent/src/commands/__tests__/goal.test.ts`:

```ts
import { describe, expect, test } from 'bun:test'
import goalCommand from '../goal/index.js'
import type { LocalJSXCommandContext } from '../../types/command.js'

function makeContext(): LocalJSXCommandContext {
  let state = {
    conversationGoal: null,
  } as unknown as ReturnType<LocalJSXCommandContext['getAppState']>
  return {
    getAppState: () => state,
    setAppState: updater => {
      state = updater(state)
    },
    setMessages: () => {},
    onChangeAPIKey: () => {},
    options: {
      ideInstallationStatus: null,
      theme: 'dark',
    },
  } as unknown as LocalJSXCommandContext
}

async function callGoal(args: string, context = makeContext()): Promise<string> {
  const mod = await goalCommand.load()
  const result = await mod.call(args, context)
  if (result.type !== 'text') throw new Error(`expected text result, got ${result.type}`)
  return result.value
}

describe('/goal command', () => {
  test('bare goal shows usage when no goal exists', async () => {
    await expect(callGoal('')).resolves.toContain('No current goal')
  })

  test('objective creates a goal with visible feedback', async () => {
    await expect(callGoal('Ship visible goals')).resolves.toBe('Goal started: Ship visible goals')
  })

  test('reserved edit without objective returns usage error', async () => {
    await expect(callGoal('edit')).resolves.toBe('Usage: /goal edit <new objective>')
  })
})
```

- [ ] **Step 2: Run failing command tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/commands/__tests__/goal.test.ts
```

Expected: FAIL because `commands/goal/index.ts` does not exist.

- [ ] **Step 3: Implement local command**

Create `src/ragflow_lite/microagent/src/commands/goal/index.ts`:

```ts
import type { Command } from '../../types/command.js'
import {
  createConversationGoal,
  clearConversationGoal,
  formatGoalLifecycleNotification,
  formatGoalSummary,
  pauseConversationGoal,
  replaceConversationGoal,
  resumeConversationGoal,
  validateGoalObjective,
} from '../../utils/conversationGoal.js'
import {
  getCurrentConversationGoal,
  saveConversationGoal,
  saveConversationGoalCleared,
} from '../../utils/sessionStorage.js'
import { getSessionId } from '../../bootstrap/state.js'

const RESERVED = new Set(['edit', 'pause', 'resume', 'clear'])

function splitAction(args: string): { action: string | null; rest: string } {
  const trimmed = args.trim()
  if (!trimmed) return { action: null, rest: '' }
  const [first = '', ...rest] = trimmed.split(/\s+/)
  if (!RESERVED.has(first)) return { action: null, rest: trimmed }
  return { action: first, rest: rest.join(' ').trim() }
}

const goalCommand: Command = {
  type: 'local',
  name: 'goal',
  description: 'Create, inspect, pause, resume, or clear a conversation goal',
  argumentHint: '[objective | edit <objective> | pause | resume | clear]',
  supportsNonInteractive: false,
  isSensitive: false,
  async load() {
    return {
      async call(args, context) {
        const current = getCurrentConversationGoal()
        const { action, rest } = splitAction(args)

        if (!action && !rest) {
          return { type: 'text', value: formatGoalSummary(current) }
        }

        if (action === 'edit') {
          if (!current) return { type: 'text', value: 'No current goal to edit. Use /goal <objective> to start one.' }
          if (!rest) return { type: 'text', value: 'Usage: /goal edit <new objective>' }
          const validation = validateGoalObjective(rest)
          if (!validation.ok) return { type: 'text', value: validation.error }
          const next = replaceConversationGoal(current, { objective: validation.objective })
          saveConversationGoal(next)
          context.setAppState(prev => ({ ...prev, conversationGoal: next }))
          return { type: 'text', value: formatGoalLifecycleNotification('replaced', next) }
        }

        if (action === 'pause') {
          if (!current) return { type: 'text', value: 'No current goal to pause.' }
          const next = pauseConversationGoal(current)
          saveConversationGoal(next)
          context.setAppState(prev => ({ ...prev, conversationGoal: next }))
          return { type: 'text', value: formatGoalLifecycleNotification('paused', next) }
        }

        if (action === 'resume') {
          if (!current) return { type: 'text', value: 'No current goal to resume.' }
          const next = resumeConversationGoal(current)
          saveConversationGoal(next)
          context.setAppState(prev => ({ ...prev, conversationGoal: next }))
          return { type: 'text', value: formatGoalLifecycleNotification('resumed', next) }
        }

        if (action === 'clear') {
          if (!current) return { type: 'text', value: 'No current goal to clear.' }
          const entry = clearConversationGoal(current)
          saveConversationGoalCleared(entry)
          context.setAppState(prev => ({ ...prev, conversationGoal: null }))
          return { type: 'text', value: formatGoalLifecycleNotification('cleared', current) }
        }

        const validation = validateGoalObjective(rest)
        if (!validation.ok) return { type: 'text', value: validation.error }
        const next = current
          ? replaceConversationGoal(current, { objective: validation.objective })
          : createConversationGoal({
              conversationId: getSessionId(),
              objective: validation.objective,
            })
        saveConversationGoal(next)
        context.setAppState(prev => ({ ...prev, conversationGoal: next }))
        return {
          type: 'text',
          value: formatGoalLifecycleNotification(current ? 'replaced' : 'started', next),
        }
      },
    }
  },
}

export default goalCommand
```

- [ ] **Step 4: Register the command**

Modify `src/ragflow_lite/microagent/src/commands.ts`:

```ts
import goal from './commands/goal/index.js'
```

Add `goal` to the `COMMANDS` array near other core commands:

```ts
  goal,
```

- [ ] **Step 5: Add command recognition and typeahead tests**

In `src/ragflow_lite/microagent/src/utils/processUserInput/__tests__/processSlashCommand.test.ts`, add:

```ts
import { builtInCommandNames } from '../../../commands.js'

test('/goal is recognized as a built-in command', () => {
  expect(builtInCommandNames().has('goal')).toBe(true)
})
```

In `src/ragflow_lite/microagent/src/utils/suggestions/__tests__/commandSuggestions.test.ts`, add a focused assertion using the existing helper in that file:

```ts
test('/goal appears in command suggestions', () => {
  const commands: Command[] = [
    makeCommand('goal', {
      description: 'Create, inspect, pause, resume, or clear a conversation goal',
    }),
  ]
  const results = generateCommandSuggestions('/go', commands)
  expect(results.some(result => result.displayText === '/goal')).toBe(true)
})
```

- [ ] **Step 6: Run focused command tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/commands/__tests__/goal.test.ts src/utils/processUserInput/__tests__/processSlashCommand.test.ts src/utils/suggestions/__tests__/commandSuggestions.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ragflow_lite/microagent/src/commands.ts src/ragflow_lite/microagent/src/commands/goal/index.ts src/ragflow_lite/microagent/src/commands/__tests__/goal.test.ts src/ragflow_lite/microagent/src/utils/processUserInput/__tests__/processSlashCommand.test.ts src/ragflow_lite/microagent/src/utils/suggestions/__tests__/commandSuggestions.test.ts
git commit -m "feat: add goal slash command"
```

## Task 5: Model-Facing Goal Update Tool

**Files:**
- Create: `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/constants.ts`
- Create: `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/prompt.ts`
- Create: `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/GoalUpdateTool.ts`
- Create: `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/__tests__/GoalUpdateTool.test.ts`
- Modify: `src/ragflow_lite/microagent/src/tools.ts`

- [ ] **Step 1: Write failing tool tests**

Create `src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool/__tests__/GoalUpdateTool.test.ts`:

```ts
import { describe, expect, test } from 'bun:test'
import { GoalUpdateTool } from '../GoalUpdateTool.js'
import { createConversationGoal } from 'src/utils/conversationGoal.js'

function makeContext(goal = createConversationGoal({
  conversationId: 'session-1',
  objective: 'Ship',
  id: 'goal-1',
  now: '2026-06-04T00:00:00.000Z',
})) {
  let state = { conversationGoal: goal }
  return {
    getAppState: () => state,
    setAppState: updater => {
      state = updater(state)
    },
  } as never
}

describe('GoalUpdateTool', () => {
  test('allows complete', async () => {
    const result = await GoalUpdateTool.call({ status: 'complete' }, makeContext())
    expect(result.data).toMatchObject({ success: true, status: 'complete' })
  })

  test('allows blocked with reason', async () => {
    const result = await GoalUpdateTool.call({ status: 'blocked', reason: 'Need user input' }, makeContext())
    expect(result.data).toMatchObject({ success: true, status: 'blocked' })
  })

  test('rejects runtime-owned statuses', async () => {
    const parsed = GoalUpdateTool.inputSchema.safeParse({ status: 'paused' })
    expect(parsed.success).toBe(false)
  })
})
```

- [ ] **Step 2: Run failing tool tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test packages/builtin-tools/src/tools/GoalUpdateTool/__tests__/GoalUpdateTool.test.ts
```

Expected: FAIL because the tool does not exist.

- [ ] **Step 3: Implement constants and prompt**

Create `constants.ts`:

```ts
export const GOAL_UPDATE_TOOL_NAME = 'GoalUpdate'
```

Create `prompt.ts`:

```ts
export const DESCRIPTION = 'Mark the active conversation goal complete or blocked.'

export const PROMPT = `Use this tool only for the active conversation goal.

Allowed statuses:
- complete: the objective is genuinely finished.
- blocked: progress cannot continue without user input or an external state change.

Do not use this tool to pause, resume, clear, replace, set usage limits, or set budget limits. Those transitions are owned by user/runtime policy.`
```

- [ ] **Step 4: Implement GoalUpdateTool**

Create `GoalUpdateTool.ts`:

```ts
import { z } from 'zod/v4'
import { buildTool } from 'src/Tool.js'
import { lazySchema } from 'src/utils/lazySchema.js'
import {
  formatGoalLifecycleNotification,
  markGoalBlocked,
  markGoalComplete,
} from 'src/utils/conversationGoal.js'
import {
  getCurrentConversationGoal,
  saveConversationGoal,
} from 'src/utils/sessionStorage.js'
import { DESCRIPTION, PROMPT } from './prompt.js'
import { GOAL_UPDATE_TOOL_NAME } from './constants.js'

const inputSchema = lazySchema(() =>
  z.strictObject({
    status: z.enum(['complete', 'blocked']),
    reason: z.string().optional(),
  }),
)

const outputSchema = lazySchema(() =>
  z.object({
    success: z.boolean(),
    status: z.enum(['complete', 'blocked']).optional(),
    message: z.string(),
  }),
)

type InputSchema = ReturnType<typeof inputSchema>
type OutputSchema = ReturnType<typeof outputSchema>
type Output = z.infer<OutputSchema>

export const GoalUpdateTool = buildTool<InputSchema, Output>({
  name: GOAL_UPDATE_TOOL_NAME,
  searchHint: 'mark active goal complete or blocked',
  maxResultSizeChars: 2000,
  async description() {
    return DESCRIPTION
  },
  async prompt() {
    return PROMPT
  },
  get inputSchema(): InputSchema {
    return inputSchema()
  },
  get outputSchema(): OutputSchema {
    return outputSchema()
  },
  userFacingName() {
    return 'GoalUpdate'
  },
  isConcurrencySafe() {
    return false
  },
  renderToolUseMessage() {
    return null
  },
  async call(input, context) {
    const current = getCurrentConversationGoal()
    if (!current || current.status !== 'active') {
      return { data: { success: false, message: 'No active conversation goal to update' } }
    }
    const next =
      input.status === 'complete'
        ? markGoalComplete(current)
        : markGoalBlocked(current, input.reason)
    saveConversationGoal(next)
    context.setAppState(prev => ({ ...prev, conversationGoal: next }))
    return {
      data: {
        success: true,
        status: next.status as 'complete' | 'blocked',
        message: formatGoalLifecycleNotification(next.status === 'complete' ? 'complete' : 'blocked', next),
      },
    }
  },
})
```

- [ ] **Step 5: Register the tool**

Modify `src/ragflow_lite/microagent/src/tools.ts`:

```ts
import { GoalUpdateTool } from '@claude-code-best/builtin-tools/tools/GoalUpdateTool/GoalUpdateTool.js'
```

Add `GoalUpdateTool` to `getAllBaseTools()` or the existing base tool array alongside other model-visible tools.

- [ ] **Step 6: Run focused tests and typecheck**

Run:

```bash
cd src/ragflow_lite/microagent && bun test packages/builtin-tools/src/tools/GoalUpdateTool/__tests__/GoalUpdateTool.test.ts
cd src/ragflow_lite/microagent && bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ragflow_lite/microagent/packages/builtin-tools/src/tools/GoalUpdateTool src/ragflow_lite/microagent/src/tools.ts
git commit -m "feat: add goal update tool"
```

## Task 6: Turn Integration, Accounting, And Lifecycle Finalization

**Files:**
- Modify: `src/ragflow_lite/microagent/src/QueryEngine.ts`
- Modify: `src/ragflow_lite/microagent/src/query.ts`
- Modify: `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`
- Test: `src/ragflow_lite/microagent/src/__tests__/queryConversationGoal.test.ts`

- [ ] **Step 1: Write failing goal context prompt test**

Create `src/ragflow_lite/microagent/src/__tests__/queryConversationGoal.test.ts`:

```ts
import { describe, expect, test } from 'bun:test'
import { buildGoalContinuationPrompt, createConversationGoal } from '../utils/conversationGoal.js'

describe('goal continuation prompt', () => {
  test('builds internal goal context without pretending to be user-authored', () => {
    const goal = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Finish implementation',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })

    const prompt = buildGoalContinuationPrompt(goal)

    expect(prompt.isMeta).toBe(true)
    expect(prompt.content).toContain('Continue the active conversation goal')
    expect(prompt.content).toContain('Finish implementation')
    expect(prompt.content).toContain('GoalUpdate')
  })
})
```

- [ ] **Step 2: Run failing test**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/__tests__/queryConversationGoal.test.ts
```

Expected: FAIL because `buildGoalContinuationPrompt` does not exist.

- [ ] **Step 3: Add continuation prompt helper**

Append to `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`:

```ts
export function buildGoalContinuationPrompt(goal: ConversationGoal): { content: string; isMeta: true } {
  return {
    isMeta: true,
    content: [
      '<conversation-goal>',
      `Objective: ${goal.objective}`,
      `Status: ${goal.status}`,
      goal.tokenBudget != null ? `Token budget: ${goal.tokenBudget}` : 'Token budget: none',
      `Tokens used: ${goal.tokensUsed}`,
      `Time used seconds: ${goal.timeUsedSeconds}`,
      '',
      'Continue the active conversation goal. Use GoalUpdate only when the goal is genuinely complete or blocked.',
      '</conversation-goal>',
    ].join('\n'),
  }
}
```

- [ ] **Step 4: Add QueryEngine goal-driven option**

Modify `QueryEngine.submitMessage()` options type:

```ts
options?: { uuid?: string; isMeta?: boolean; goalContinuation?: boolean }
```

Add imports in `src/ragflow_lite/microagent/src/QueryEngine.ts`:

```ts
import {
  applyGoalAccounting,
  buildGoalContinuationPrompt,
} from './utils/conversationGoal.js'
import {
  getCurrentConversationGoal,
  saveConversationGoal,
} from './utils/sessionStorage.js'
```

Before `processUserInput`, if `options?.goalContinuation` is true, load `getCurrentConversationGoal()`, require `status === 'active'`, and replace the prompt with the meta continuation prompt:

```ts
const currentGoal = options?.goalContinuation ? getCurrentConversationGoal() : null
const effectivePrompt =
  options?.goalContinuation && currentGoal?.status === 'active'
    ? buildGoalContinuationPrompt(currentGoal).content
    : prompt
const effectiveOptions =
  options?.goalContinuation && currentGoal?.status === 'active'
    ? { ...options, isMeta: true }
    : options
```

Pass `effectivePrompt` and `effectiveOptions` to `processUserInput`.

- [ ] **Step 5: Add finalization accounting hook**

After the `for await (const message of query(...))` loop in `QueryEngine.submitMessage()`, compute a conservative token delta from the latest assistant usage available in the turn. If no reliable usage exists, use `0` and leave exact provider accounting for a later refinement:

```ts
if (options?.goalContinuation && currentGoal) {
  const latestGoal = getCurrentConversationGoal()
  if (latestGoal?.goalId === currentGoal.goalId) {
    const finalized = applyGoalAccounting(latestGoal, {
      tokenDelta: 0,
      elapsedSeconds: Math.ceil((Date.now() - startTime) / 1000),
      now: new Date().toISOString(),
      turnId: randomUUID(),
    })
    saveConversationGoal(finalized)
    setAppState(prev => ({ ...prev, conversationGoal: finalized }))
  }
}
```

Do not schedule another turn in `QueryEngine`. The controller handles scheduling.

- [ ] **Step 6: Run focused tests and typecheck**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/__tests__/queryConversationGoal.test.ts src/utils/__tests__/conversationGoal.test.ts
cd src/ragflow_lite/microagent && bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ragflow_lite/microagent/src/QueryEngine.ts src/ragflow_lite/microagent/src/query.ts src/ragflow_lite/microagent/src/utils/conversationGoal.ts src/ragflow_lite/microagent/src/__tests__/queryConversationGoal.test.ts
git commit -m "feat: integrate goals with turns"
```

## Task 7: Foreground Continuation Controller

**Files:**
- Create: `src/ragflow_lite/microagent/src/hooks/useConversationGoalController.ts`
- Create: `src/ragflow_lite/microagent/src/hooks/__tests__/useConversationGoalController.test.tsx`
- Modify: `src/ragflow_lite/microagent/src/screens/REPL.tsx`
- Modify: `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`

- [ ] **Step 1: Write failing controller eligibility tests**

Create `src/ragflow_lite/microagent/src/hooks/__tests__/useConversationGoalController.test.tsx`:

```ts
import { describe, expect, test } from 'bun:test'
import {
  createConversationGoal,
  getNextGoalRetryDelayMs,
  isGoalContinuationEligible,
} from '../../utils/conversationGoal.js'

describe('goal continuation controller helpers', () => {
  test('only active goals are eligible while idle', () => {
    const active = createConversationGoal({
      conversationId: 'session-1',
      objective: 'Ship',
      id: 'goal-1',
      now: '2026-06-04T00:00:00.000Z',
    })
    expect(isGoalContinuationEligible(active, { isLoading: false, queueLength: 0, nowMs: 0 })).toBe(true)
    expect(isGoalContinuationEligible({ ...active, status: 'paused' }, { isLoading: false, queueLength: 0, nowMs: 0 })).toBe(false)
    expect(isGoalContinuationEligible(active, { isLoading: true, queueLength: 0, nowMs: 0 })).toBe(false)
    expect(isGoalContinuationEligible(active, { isLoading: false, queueLength: 1, nowMs: 0 })).toBe(false)
  })

  test('retry backoff is bounded', () => {
    expect(getNextGoalRetryDelayMs(0)).toBe(0)
    expect(getNextGoalRetryDelayMs(1)).toBe(2000)
    expect(getNextGoalRetryDelayMs(2)).toBe(5000)
    expect(getNextGoalRetryDelayMs(3)).toBe(15000)
  })
})
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/hooks/__tests__/useConversationGoalController.test.tsx
```

Expected: FAIL because helper exports do not exist.

- [ ] **Step 3: Add controller helper exports**

Append to `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`:

```ts
export const GOAL_RETRY_LIMIT = 3
export const GOAL_RETRY_DELAYS_MS = [0, 2000, 5000, 15000] as const
export const GOAL_LEASE_MS = 30_000

export function getNextGoalRetryDelayMs(failureCount: number): number {
  return GOAL_RETRY_DELAYS_MS[Math.min(failureCount, GOAL_RETRY_DELAYS_MS.length - 1)]
}

export function isGoalContinuationEligible(
  goal: ConversationGoal | null,
  params: { isLoading: boolean; queueLength: number; nowMs: number },
): boolean {
  if (!goal || goal.status !== 'active') return false
  if (params.isLoading || params.queueLength > 0) return false
  if (goal.failureCount >= GOAL_RETRY_LIMIT) return false
  const delay = getNextGoalRetryDelayMs(goal.failureCount)
  if (!goal.lastContinuationAt) return delay === 0
  return params.nowMs - Date.parse(goal.lastContinuationAt) >= delay
}
```

- [ ] **Step 4: Implement `useConversationGoalController`**

Create `src/ragflow_lite/microagent/src/hooks/useConversationGoalController.ts`:

```ts
import { randomUUID } from 'crypto'
import { useEffect, useRef } from 'react'
import { getCommandQueueLength } from '../utils/messageQueueManager.js'
import {
  acquireGoalContinuationLease,
  GOAL_LEASE_MS,
  isGoalContinuationEligible,
  releaseGoalContinuationLease,
} from '../utils/conversationGoal.js'
import { saveConversationGoal } from '../utils/sessionStorage.js'
import { useAppState, useSetAppState } from '../state/AppState.js'

export function useConversationGoalController(params: {
  isLoading: boolean
  submitGoalContinuation: () => void
}): void {
  const goal = useAppState(s => s.conversationGoal)
  const setAppState = useSetAppState()
  const ownerIdRef = useRef(`goal-owner-${process.pid}-${randomUUID()}`)

  useEffect(() => {
    if (!isGoalContinuationEligible(goal, {
      isLoading: params.isLoading,
      queueLength: getCommandQueueLength(),
      nowMs: Date.now(),
    })) {
      return
    }

    const acquired = acquireGoalContinuationLease(goal, {
      ownerId: ownerIdRef.current,
      processId: process.pid,
      nowMs: Date.now(),
      leaseMs: GOAL_LEASE_MS,
    })
    if (!acquired.ok) return

    saveConversationGoal(acquired.goal)
    setAppState(prev => ({
      ...prev,
      conversationGoal: acquired.goal,
      goalContinuation: {
        runningGoalId: acquired.goal.goalId,
        runningObjective: acquired.goal.objective,
        ownerId: ownerIdRef.current,
      },
    }))
    params.submitGoalContinuation()

    return () => {
      const released = releaseGoalContinuationLease(acquired.goal, ownerIdRef.current)
      saveConversationGoal(released)
    }
  }, [goal, params.isLoading, params.submitGoalContinuation, setAppState])
}
```

- [ ] **Step 5: Wire controller into REPL**

In `src/ragflow_lite/microagent/src/screens/REPL.tsx`, create:

```ts
const submitGoalContinuation = useCallback(() => {
  const newAbortController = createAbortController();
  setAbortController(newAbortController);
  void onQuery(
    '<goal-continuation />',
    newAbortController,
    true,
    [],
    mainLoopModel,
    { goalContinuation: true },
  );
}, [mainLoopModel, onQuery, setAbortController]);

useConversationGoalController({
  isLoading,
  submitGoalContinuation,
});
```

Extend the local `onQuery` signature in `src/ragflow_lite/microagent/src/screens/REPL.tsx` to accept `{ goalContinuation?: boolean }` as the final argument. Pass that value through to the `QueryEngine.submitMessage()` call so `submitGoalContinuation()` reaches `QueryEngine.submitMessage(..., { goalContinuation: true })`.

- [ ] **Step 6: Run focused controller tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/hooks/__tests__/useConversationGoalController.test.tsx src/utils/__tests__/conversationGoal.test.ts
cd src/ragflow_lite/microagent && bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ragflow_lite/microagent/src/hooks/useConversationGoalController.ts src/ragflow_lite/microagent/src/hooks/__tests__/useConversationGoalController.test.tsx src/ragflow_lite/microagent/src/screens/REPL.tsx src/ragflow_lite/microagent/src/utils/conversationGoal.ts
git commit -m "feat: schedule foreground goal continuations"
```

## Task 8: Visible Running Indicator And Interrupt Policy

**Files:**
- Modify: `src/ragflow_lite/microagent/src/components/Spinner.tsx`
- Modify: `src/ragflow_lite/microagent/src/screens/REPL.tsx`
- Modify: `src/ragflow_lite/microagent/src/hooks/useCancelRequest.ts`
- Test: `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`

- [ ] **Step 1: Write failing running label test**

Append to `src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts`:

```ts
import { formatGoalRunningLabel } from '../conversationGoal.js'

describe('goal running indicator', () => {
  test('formats a distinct running label', () => {
    expect(formatGoalRunningLabel('Ship visible goals')).toBe('Continuing goal: Ship visible goals')
  })
})
```

- [ ] **Step 2: Run failing test**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
```

Expected: FAIL because `formatGoalRunningLabel` does not exist.

- [ ] **Step 3: Add running label helper**

Append to `src/ragflow_lite/microagent/src/utils/conversationGoal.ts`:

```ts
export function formatGoalRunningLabel(objective: string): string {
  return `Continuing goal: ${shortGoalObjective(objective)}`
}
```

- [ ] **Step 4: Show running label in spinner**

In `src/ragflow_lite/microagent/src/screens/REPL.tsx`, derive spinner message:

```ts
const goalRunningObjective = useAppState(s => s.goalContinuation.runningObjective);
const effectiveSpinnerMessage = goalRunningObjective
  ? formatGoalRunningLabel(goalRunningObjective)
  : spinnerMessage;
```

Pass `effectiveSpinnerMessage` to `SpinnerWithVerb`:

```tsx
overrideMessage={effectiveSpinnerMessage}
```

- [ ] **Step 5: Pause active goal on user interrupt**

Locate the existing cancel/interrupt entrypoint by searching `src/ragflow_lite/microagent/src/hooks/useCancelRequest.ts` and the REPL caller for the abort-controller reset path. In that existing entrypoint, add these imports and pause the current goal when `goalContinuation.runningGoalId` is set:

```ts
import { pauseConversationGoal } from '../utils/conversationGoal.js'
import {
  getCurrentConversationGoal,
  saveConversationGoal,
} from '../utils/sessionStorage.js'

const currentGoal = getCurrentConversationGoal()
if (currentGoal?.goalId === store.getState().goalContinuation.runningGoalId) {
  const paused = pauseConversationGoal(currentGoal)
  saveConversationGoal(paused)
  setAppState(prev => ({
    ...prev,
    conversationGoal: paused,
    goalContinuation: {
      runningGoalId: null,
      runningObjective: null,
      ownerId: null,
    },
  }))
  addNotification({
    key: `goal-paused-${paused.goalId}`,
    text: formatGoalLifecycleNotification('paused', paused),
    priority: 'high',
    color: 'warning',
  })
}
```

Keep existing abort behavior intact after this goal pause branch.

- [ ] **Step 6: Clear running state after turn finalization**

At the same point REPL ends a query and clears loading state, also clear:

```ts
setAppState(prev => ({
  ...prev,
  goalContinuation: {
    runningGoalId: null,
    runningObjective: null,
    ownerId: null,
  },
}))
```

- [ ] **Step 7: Run focused tests and typecheck**

Run:

```bash
cd src/ragflow_lite/microagent && bun test src/utils/__tests__/conversationGoal.test.ts
cd src/ragflow_lite/microagent && bun run typecheck
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ragflow_lite/microagent/src/components/Spinner.tsx src/ragflow_lite/microagent/src/screens/REPL.tsx src/ragflow_lite/microagent/src/hooks/useCancelRequest.ts src/ragflow_lite/microagent/src/utils/conversationGoal.ts src/ragflow_lite/microagent/src/utils/__tests__/conversationGoal.test.ts
git commit -m "feat: show goal runtime visibility"
```

## Task 9: Final Integration Verification

**Files:**
- Modify: `src/ragflow_lite/CONTRACTS.md` only if implementation behavior has landed and needs an active runtime contract entry.
- No code changes unless verification exposes a defect.

- [ ] **Step 1: Run all focused goal tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test \
  src/utils/__tests__/conversationGoal.test.ts \
  src/utils/__tests__/sessionStorage.test.ts \
  src/commands/__tests__/goal.test.ts \
  src/utils/processUserInput/__tests__/processSlashCommand.test.ts \
  src/utils/suggestions/__tests__/commandSuggestions.test.ts \
  packages/builtin-tools/src/tools/GoalUpdateTool/__tests__/GoalUpdateTool.test.ts \
  src/hooks/__tests__/useConversationGoalController.test.tsx \
  src/__tests__/queryConversationGoal.test.ts
```

Expected: PASS.

- [ ] **Step 2: Run typecheck**

Run:

```bash
cd src/ragflow_lite/microagent && bun run typecheck
```

Expected: PASS.

- [ ] **Step 3: Run broader MicroAgent tests**

Run:

```bash
cd src/ragflow_lite/microagent && bun test
```

Expected: PASS. If unrelated pre-existing failures appear, capture exact failing test names and output before deciding whether to fix or report.

- [ ] **Step 4: Manual REPL smoke test**

Run the local dev command used for this package:

```bash
cd src/ragflow_lite/microagent && bun run dev
```

In the REPL:

```text
/goal Write a one sentence summary of this session
/goal
/goal pause
/goal resume
/goal clear
```

Expected:

- `/goal <objective>` prints `Goal started: ...`.
- Bare `/goal` shows status and objective.
- Goal-driven continuation shows `Continuing goal: ...` while running.
- `/goal pause` prints `Goal paused: ...`.
- `/goal resume` prints `Goal resumed: ...`.
- `/goal clear` prints `Goal cleared: ...`.
- No daemon or background process continues after exiting the CLI.

- [ ] **Step 5: Update active contracts only after behavior is verified**

If all focused behavior is implemented and verified, add a concise pointer to `src/ragflow_lite/CONTRACTS.md`:

```md
- MicroAgent conversation goals are foreground-only and exposed through the interactive `/goal` REPL command. Goal state is persisted through session transcript metadata and remains separate from managed autonomy flow goals.
```

Do not move the design spec into `CONTRACTS.md`; keep the contract short and source-backed.

- [ ] **Step 6: Final commit**

If `CONTRACTS.md` changed:

```bash
git add src/ragflow_lite/CONTRACTS.md
git commit -m "docs: record microagent goal contract"
```

If no docs changed, do not create an empty commit.

## Spec Coverage Checklist

- One current goal per conversation: Task 1, Task 2, Task 4.
- Persist and restore goal state: Task 2.
- `/goal` built-in command, help, typeahead: Task 4.
- Replacement resets accounting and new `goalId`: Task 1, Task 4.
- Model can only mark `complete` or `blocked`: Task 5.
- User/runtime owns pause, resume, clear, replacement, usage limit, budget limit: Task 1, Task 4, Task 8.
- Active foreground continuation after idle: Task 7.
- User input, slash commands, queued commands, abort, interrupt preempt continuation: Task 7, Task 8.
- Token budget semantics and no time budget: Task 1, Task 6.
- Bounded failures and retry exhaustion: Task 7.
- First action avoids metadata-only transcript: Task 2, Task 4.
- Concurrent foreground processes cannot both continue same goal: Task 1, Task 7.
- Generic goals stay separate from `AutonomyFlowRecord.goal`: Task 1 through Task 9 never touch autonomy flow storage except regression tests.
- Lifecycle notifications and visible running indicator: Task 3, Task 4, Task 8.
- No daemon/background continuation after process exit: Task 7, Task 9.

## Execution Notes

- Before executing this plan, create an isolated worktree or confirm the current worktree is clean.
- Keep commits at the task boundaries above.
- Do not change production dependencies, secrets, CI/release workflow, or external API schema for this feature.
- If the REPL path is not yet using `QueryEngine.submitMessage()` for interactive turns, implement the same `goalContinuation` option at the existing `onQuery` boundary in `screens/REPL.tsx`; do not move goal scheduling into the inner `query.ts` loop.
