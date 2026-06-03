# MicroAgent Conversation Goal Runtime

Date: 2026-06-03
Status: Draft design spec

This document specifies a Codex-style goal mechanism for
`src/ragflow_lite/microagent`.

It is planning material, not an active runtime contract. Active contracts remain
in `src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

Add a foreground-only, conversation-scoped goal runtime to MicroAgent.

The goal mechanism is a runtime contract, not a metadata field. Each
conversation may have one current goal. While the current CLI process is alive,
an `active` goal automatically schedules continuation turns whenever the
conversation runtime becomes idle. Continuation stops only when the goal becomes
`complete`, `blocked`, `paused`, `usageLimited`, `budgetLimited`, replaced,
cleared, aborted, or fails under bounded retry/backoff rules.

The local binding object is the conversation. This intentionally adapts Codex's
thread-scoped goal model to MicroAgent's existing boundary: `QueryEngine` is one
engine per conversation, and each `submitMessage()` starts a new turn in that
conversation.

The first implementation is foreground-only. If the user exits the current CLI
process, no daemon or background worker is required to continue execution.
Resume must restore goal state, but execution only continues once a process is
running again.

## Context

Codex goal facts from the reference project:

- Goal state is bound to a thread, not to a session family or a single turn.
- A thread has one current goal row.
- Replacing a goal generates a new `goal_id` and resets accounting.
- The status set is:
  - `active`
  - `paused`
  - `blocked`
  - `usageLimited`
  - `budgetLimited`
  - `complete`
- Models can only mark a goal `complete` or `blocked`.
- User/runtime controls pause, resume, usage limit, budget limit, replacement,
  and clearing.
- Token budget is optional. Omitted or null means no token budget.
- If provided, token budget must be greater than zero.
- `budgetLimited` is triggered by token accounting, not by elapsed time.
- `timeUsedSeconds` is accounting only; Codex does not define a `timeBudget`.
- `budgetLimited` allows the current turn to wrap up but prevents further idle
  continuation.

MicroAgent facts from the current source tree:

- `src/ragflow_lite/microagent/src/QueryEngine.ts` is the conversation engine.
  It preserves state across turns in the same conversation.
- `src/ragflow_lite/microagent/src/query.ts` owns the turn loop and its
  finalization.
- `src/ragflow_lite/microagent/src/utils/sessionStorage.ts` owns transcript and
  session metadata persistence used by resume.
- `src/ragflow_lite/microagent/src/utils/autonomyFlows.ts` already has an
  `AutonomyFlowRecord.goal` field. That field is part of managed autonomy flow
  semantics and must not become the generic conversation goal store.
- `src/ragflow_lite/microagent/src/utils/autonomyRuns.ts` records autonomy run
  lifecycle, not generic conversation goal state.
- `src/ragflow_lite/microagent/src/state/AppStateStore.ts` is runtime state, not
  the durable resume store.

## Goals

1. Add a Codex-style goal runtime scoped to a MicroAgent conversation.
2. Preserve one current goal per conversation.
3. Persist goal state across turns and restore it on resume.
4. Automatically continue an active goal while the current process is alive and
   the conversation runtime is idle.
5. Keep user input, slash commands, queued commands, abort, and interrupt above
   continuation in priority.
6. Preserve Codex's full goal status set.
7. Preserve Codex's token budget semantics:
   - no default token budget;
   - null or omitted means no budget;
   - explicit budget must be greater than zero;
   - token accounting can move an active goal to `budgetLimited`;
   - elapsed time does not trigger `budgetLimited`.
8. Prevent model-side privilege escalation. The model may only mark goals
   `complete` or `blocked`.
9. Keep the generic conversation goal separate from existing autonomy flow goal
   semantics.
10. Make failures bounded so continuation cannot hot-loop.

## Non-Goals

- Do not add a first-class thread tree, descendant thread model, fork lineage,
  or Codex session-family model.
- Do not make goals continue after the current CLI process exits.
- Do not add a daemon or background job runner for this feature.
- Do not store generic conversation goals inside `AutonomyFlowRecord.goal`.
- Do not turn generic goals into managed autonomy flows.
- Do not make `AppStateStore` the durable goal source of truth.
- Do not add a default token budget such as `200000`. That number appears in
  Codex documentation as an example, not as a protocol default.
- Do not add `timeBudget` or use elapsed time to trigger `budgetLimited`.
- Do not allow `budgetLimited` goals to start new idle continuation turns.
- Do not add product telemetry, app-server notifications, or UI surfaces unless
  required by a later implementation plan.

## Data Model

Add a first-class `ConversationGoal` model.

```ts
type GoalStatus =
  | "active"
  | "paused"
  | "blocked"
  | "usageLimited"
  | "budgetLimited"
  | "complete"

type ConversationGoal = {
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
}

type GoalContinuationOwner = {
  ownerId: string
  processId: number
  acquiredAt: string
  expiresAt: string
}
```

Field semantics:

- `conversationId` is the local binding object and replaces Codex's
  `thread_id`.
- `goalId` changes on replacement and invalidates stale continuations.
- `revision` increments on every persisted goal mutation and is used for
  compare-and-set updates.
- `objective` is the user-specified goal text.
- `status` controls continuation eligibility.
- `tokenBudget` is optional and defaults to null or omitted.
- `tokensUsed` is goal-level token accounting.
- `timeUsedSeconds` is goal-level elapsed-time accounting only.
- `lastTurnId` records the latest turn that advanced the goal.
- `lastContinuationAt` supports backoff and debugging.
- `continuationOwner` is a foreground-process lease for auto-continuation.
- `failureCount` and `lastError` bound repeated continuation failures.

## Persistence

Persist `ConversationGoal` as session transcript metadata through the
`sessionStorage.ts` persistence chain.

Recommended transcript entry for current goal state:

```ts
{
  type: "conversation-goal",
  goal: ConversationGoal
}
```

Recommended transcript entry for clearing a goal:

```ts
{
  type: "conversation-goal-cleared",
  goalId: string,
  clearedAt: string
}
```

The clear tombstone is required. If clearing only stops writing the metadata
entry, resume can accidentally rediscover an older goal entry and resurrect a
cleared goal.

Persistence requirements:

- Do not write an empty goal object when no goal exists.
- When a goal exists, write the current goal metadata to the session transcript.
- `reAppendSessionMetadata()` should re-stamp the current goal metadata at the
  transcript tail, consistent with existing session metadata behavior.
- Resume should restore the most recent effective goal entry.
- A later clear entry must win over an earlier goal entry.
- The restored state must include `goalId`, `objective`, `status`,
  `revision`, `tokenBudget`, `tokensUsed`, `timeUsedSeconds`,
  `continuationOwner`, `failureCount`, and error metadata.

### Pre-Materialization Rule

MicroAgent's session storage intentionally avoids metadata-only transcript
files. Goal persistence must respect that contract.

Creating a goal before any transcript materialization must start a real first
turn that carries the goal objective, causing normal session materialization.
The implementation must not create a transcript that contains only goal metadata.

Requirements:

- A goal create operation must either attach to an already materialized
  conversation transcript or immediately start the first goal-driven turn.
- Goal metadata is written as part of that real turn's session persistence path.
- If session persistence is disabled, goal persistence and resume are
  unavailable for that session and the UI/CLI must report that limitation.
- Goal create must not silently buffer a goal and then claim it is durable before
  the transcript exists.
- Tests must cover creating a goal as the first action in a new session without
  producing an orphan metadata-only transcript.

## Replacement

Replacing a goal is not an in-place objective edit.

Replacement requirements:

- Generate a new `goalId`.
- Reset `revision` to the initial revision for the new goal.
- Set `status` to `active`.
- Reset `tokensUsed` to `0`.
- Reset `timeUsedSeconds` to `0`.
- Reset `failureCount` to `0`.
- Clear `lastError`.
- Clear any `continuationOwner`.
- Preserve only the new objective and new optional `tokenBudget`.
- Invalidate any pending continuation that captured the old `goalId`.

This mirrors Codex's replacement semantics and prevents old accounting, old
failure state, or old continuation loops from contaminating the new objective.

## State Machine

Only `active` goals are eligible for idle continuation.

State ownership:

| From | To | Owner | Notes |
| --- | --- | --- | --- |
| none | active | user/runtime | create goal |
| active | complete | model | only via controlled goal update tool/API |
| active | blocked | model | only via controlled goal update tool/API |
| active | paused | user/runtime | explicit pause |
| paused | active | user/runtime | explicit resume |
| active | usageLimited | runtime | usage or repeated runtime failure limit |
| active | budgetLimited | runtime | token budget reached |
| active | active | runtime | accounting or continuation metadata update |
| any | active | user/runtime | replace goal with new `goalId` |
| any | none | user/runtime | clear goal, write tombstone |

Forbidden transitions:

- The model must not set `paused`, `usageLimited`, `budgetLimited`, or `active`.
- The model must not clear a goal.
- The runtime must not continue `paused`, `blocked`, `usageLimited`,
  `budgetLimited`, or `complete` goals.
- `budgetLimited` must not automatically resume.
- `usageLimited` means a runtime usage or safety limit stopped execution. In the
  first implementation, exhausted continuation retry budget is treated as a
  runtime usage/safety limit and maps to `usageLimited`.

## Budget And Accounting

Budget semantics must follow Codex:

- `tokenBudget` is optional.
- `tokenBudget == null` means no token budget.
- An explicitly provided `tokenBudget` must be greater than zero.
- `0` is invalid and must not mean unlimited.
- `tokensUsed` increases from measured turn token deltas.
- If the goal is `active`, `tokenBudget != null`, and
  `tokensUsed + tokenDelta >= tokenBudget`, the runtime sets
  `status = "budgetLimited"`.
- `budgetLimited` stops idle continuation.
- The current turn may receive budget-limit steering to wrap up, but it must not
  start new substantive work.
- `timeUsedSeconds` should be updated for reporting and prompt context, but it
  must not trigger `budgetLimited`.
- No `timeBudget` field is introduced in the first implementation.

## Continuation Controller

Add an explicit foreground-only goal continuation controller.

The controller is responsible for deciding whether to start another turn after
the previous turn has fully finalized. It must not live inside the inner
`query.ts` turn loop as a `while goal active` construct.

Responsibilities:

1. Observe that the current conversation runtime is idle.
2. Load the current goal from the durable goal state.
3. Confirm the goal is still `active`.
4. Confirm no active turn is running for the same conversation.
5. Confirm no user input, slash command, higher-priority queued command, abort,
   or interrupt should preempt continuation.
6. Capture the current `goalId`.
7. Re-read or revalidate the goal immediately before starting continuation.
8. Start one continuation turn.
9. Record continuation metadata.
10. Apply retry/backoff or stop conditions after errors.

The controller starts at most one continuation turn per scheduling decision. If
the next turn completes and the goal remains active, the controller may schedule
again after the runtime returns to idle.

Required guards:

- active-turn guard;
- user-input and queued-command guard;
- abort and interrupt guard;
- goal changed guard;
- continuation owner lease guard;
- status guard;
- token budget guard;
- retry/backoff guard;
- resume freshness guard;
- lifecycle-finalization guard.

### Foreground Continuation Ownership

Foreground-only does not mean single-process by assumption. Two CLI processes
can resume the same conversation. The goal controller must therefore acquire a
durable per-goal continuation lease before starting an auto-continuation turn.

Lease requirements:

- The lease is stored in `ConversationGoal.continuationOwner`.
- The lease owner includes a process id and a generated owner id.
- Acquiring a lease is a compare-and-set operation over `goalId` and `revision`.
- A process can acquire the lease only when:
  - the goal is still `active`;
  - the captured `goalId` still matches;
  - no unexpired owner lease exists, or the existing lease is stale.
- Starting a continuation turn requires re-reading the goal after lease acquire.
- Finishing, aborting, pausing, completing, blocking, replacing, or clearing the
  goal releases or invalidates the lease.
- Stale lease takeover must be bounded by an implementation-defined timeout.
- A process that fails the lease acquire must not run continuation for that goal.
- Tests must cover two foreground processes attempting to continue the same
  resumed active goal; only one may start a continuation turn.

## Turn Integration

`QueryEngine` remains the single-turn execution API. The goal controller must
only call it sequentially after the previous turn has completed finalization.

Turn start requirements:

- Load current goal.
- If status is `active`, inject goal context into the turn as internal runtime
  context.
- Establish accounting baseline for token and elapsed-time tracking.
- Record the active `goalId` for the turn.

Turn finish requirements:

- Update `tokensUsed` and `timeUsedSeconds`.
- Apply `budgetLimited` transition if token budget is reached.
- Update `lastTurnId` and `updatedAt`.
- Clear per-turn accounting state.
- If the model used the controlled update path to mark `complete` or `blocked`,
  persist that terminal state.
- Only after finalization may the controller consider another continuation.

Abort or interrupt requirements:

- Account for usage best effort.
- Do not start continuation after abort.
- Reset abort controller before any future user-requested or continuation turn.
- Keep the goal state accurate. If abort is user-driven pause, set `paused`; if
  it is runtime failure, apply the configured failure/backoff behavior.

## Continuation Prompt

Continuation must not be represented as a normal user-authored message.

The continuation turn should receive an internal context item that includes:

- objective;
- status;
- token budget, if any;
- tokens used;
- time used;
- recent progress summary if available;
- explicit instruction to continue the active goal;
- instruction to call the controlled goal update path only when the goal is
  genuinely `complete` or `blocked`.

For `budgetLimited`, continuation must not start. If budget is reached inside an
active turn, the runtime may inject budget-limit steering that tells the model to
wrap up and avoid new substantive work. Unless the goal is actually complete,
the model should not mark it `complete`.

## User And Model Interfaces

The exact CLI, slash command, or tool names can be decided in the implementation
plan, but the design requires these operations:

- create goal with objective and optional token budget;
- get current goal;
- replace current goal;
- pause current goal;
- resume paused goal;
- clear current goal;
- model-visible update path for `complete` and `blocked` only.

Validation:

- objective must be non-empty after trimming;
- token budget, when present, must be an integer greater than zero;
- create should fail if a current goal exists unless the command explicitly
  requests replacement;
- replacing must generate a new `goalId`;
- model-side update must reject every status except `complete` and `blocked`;
- resume can only move `paused` back to `active`;
- `budgetLimited` and `usageLimited` cannot be resumed by the model.
- creating a goal as the first action must start a real goal-driven turn instead
  of writing metadata only.

## Autonomy Boundary

The generic conversation goal must remain separate from autonomy flows.

Allowed reuse:

- lifecycle lessons from autonomy run claim/finalize behavior;
- active-run dedup ideas;
- failure/backoff patterns;
- queued-command preemption checks.

Forbidden coupling:

- Do not store `ConversationGoal` in `AutonomyFlowRecord`.
- Do not treat `AutonomyFlowRecord.goal` as the current conversation goal.
- Do not make generic goal continuation a managed autonomy flow step.
- Do not let autonomy flow status overwrite conversation goal status.
- Do not let conversation goal replacement mutate existing autonomy flow goals.

This separation is required because autonomy flows are task execution records
with their own trigger/source/owner semantics, while conversation goals are
runtime contracts attached to a conversation.

## Error Handling

Continuation failures must be bounded.

Requirements:

- A failed continuation increments `failureCount`.
- Consecutive failures use backoff before another continuation attempt.
- Reaching the configured retry limit moves the goal to `usageLimited`.
- The stopped state must be persisted.
- The controller must never hot-loop.
- User input should be allowed to preempt or recover from a failure state through
  explicit user/runtime operations.

## Resume Behavior

Resume must restore structured goal state from transcript metadata.

Resume requirements:

- Restore the last effective goal state for the conversation.
- Honor clear tombstones.
- Do not auto-run unless a current process is active.
- If a resumed goal is `active` and the current process becomes idle, the
  foreground controller may continue it.
- If a resumed goal is `paused`, `blocked`, `usageLimited`, `budgetLimited`, or
  `complete`, do not continue automatically.
- Do not revive stale continuation attempts from before process exit.
- Resume must not trust a stale `continuationOwner`; it may only continue after
  acquiring a fresh foreground lease.

## Testing

Focused tests should cover these behaviors before implementation is considered
complete.

Data model and persistence:

- creating a goal writes a structured `conversation-goal` metadata entry;
- creating a goal as the first action materializes a real transcript turn and
  does not create a metadata-only transcript;
- clearing writes a tombstone;
- resume restores the latest goal state;
- clear tombstone prevents old goal resurrection;
- replacement creates a new `goalId` and resets accounting;
- invalid token budgets are rejected.

State machine:

- model update accepts only `complete` and `blocked`;
- model update rejects `paused`, `usageLimited`, `budgetLimited`, and `active`;
- only `active` goals are continuation candidates;
- `budgetLimited` stops continuation;
- paused goals can be resumed only by user/runtime.

Continuation:

- active goal starts a continuation turn after the runtime becomes idle;
- no continuation starts while an active turn is running;
- user input preempts continuation;
- slash commands preempt continuation;
- queued higher-priority command preempts continuation;
- abort prevents continuation;
- goal replacement invalidates stale continuation;
- concurrent foreground processes cannot both continue the same active goal;
- repeated failures back off and eventually stop;
- exiting the current process does not require daemon continuation.

Accounting:

- token deltas update `tokensUsed`;
- token budget crossing moves active goal to `budgetLimited`;
- null token budget never triggers `budgetLimited`;
- `timeUsedSeconds` updates but does not trigger `budgetLimited`;
- `budgetLimited` permits current-turn wrap-up but prevents new continuation.

Autonomy separation:

- generic conversation goal state does not read from or write to
  `AutonomyFlowRecord.goal`;
- autonomy flow goals continue to work independently;
- existing autonomy run/flow tests remain green.

Regression and integration:

- resume tests cover goal restore;
- daemon/background tests assert no new requirement for post-exit continuation;
- turn loop tests cover finalization before continuation scheduling.

## Acceptance Criteria

The feature is complete only when all of the following are true:

1. A current goal can be created for a conversation.
2. A conversation cannot have more than one current goal.
3. Replacing a goal creates a new `goalId` and resets accounting.
4. Goal state persists across turns.
5. Resume restores goal state.
6. Active goals auto-continue in the foreground process after idle.
7. User input and queued commands preempt continuation.
8. Slash commands preempt continuation.
9. Abort and interrupt prevent continuation.
10. The model can only mark goals `complete` or `blocked`.
11. Runtime/user owns pause, resume, clear, replacement, usage limit, and budget
    limit.
12. `tokenBudget` defaults to null or omitted.
13. Explicit `tokenBudget` must be greater than zero.
14. Token budget crossing sets `budgetLimited`.
15. `budgetLimited` prevents further idle continuation.
16. `timeUsedSeconds` does not trigger `budgetLimited`.
17. Continuation failures are bounded by retry/backoff and retry exhaustion maps
    to `usageLimited`.
18. Goal creation as the first action creates a real transcript turn, not a
    metadata-only transcript.
19. Concurrent foreground processes cannot both auto-continue the same active
    goal.
20. Generic conversation goals remain separate from autonomy flow goals.
21. No daemon/background continuation is required after process exit.

## Open Implementation Questions

These questions should be answered in the implementation plan, not by changing
the design boundary:

- Exact CLI or slash-command names for goal create/get/pause/resume/clear.
- Exact storage entry type names if existing transcript type conventions require
  different naming.
- Exact retry/backoff thresholds.
- Exact foreground lease timeout.
- Exact internal prompt wording for continuation and budget-limit steering.
- Exact token accounting source in MicroAgent's provider/result model.
- Exact location of the foreground continuation controller.

## Rejected Alternatives

### Store Goal In AppStateStore

Rejected because `AppStateStore` is runtime state, not the durable resume source
of truth. A goal stored only there would not reliably survive resume.

### Store Goal In Autonomy Flow

Rejected because `AutonomyFlowRecord.goal` already belongs to managed autonomy
flow semantics. Reusing it for generic conversation goals would create two
incompatible meanings for one field.

### Inline While-Loop After Turn Finish

Rejected because it would mix current-turn finalization with next-turn startup,
weaken user input preemption, risk abort-controller reuse bugs, and blur trace
and command lifecycle boundaries.

### Daemon Or Background Continuation

Rejected for the first implementation because the approved scope is
foreground-only. A later design can add durable autonomous job execution if that
becomes an explicit product requirement.
