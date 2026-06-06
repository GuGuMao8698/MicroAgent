# MicroAgent Conversation Goal Remediation

Date: 2026-06-06
Status: Draft remediation spec
Parent spec:
[2026-06-03-microagent-conversation-goal.md](2026-06-03-microagent-conversation-goal.md)
Parent plan:
[../plans/2026-06-04-microagent-conversation-goal.md](../plans/2026-06-04-microagent-conversation-goal.md)

This document specifies the remediation work required after review of the
current conversation-goal implementation in
`/home/xia/ragflow-lite/.claude/worktrees/feat+conversation-goal` at
`ca9d9fb`.

It does not replace the parent goal-runtime spec. It narrows the repair work
needed to make the implementation match the original foreground-only,
conversation-scoped `/goal` runtime contract.

It is planning material, not an active runtime contract. Active contracts remain
in `src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands and passes verification.

## Decision

Use the reviewer-recommended repair direction:

1. Rebase or replay the implementation onto current `main` so the accepted
   goal spec and plan docs are preserved.
2. Collapse goal continuation into one canonical runtime path:
   the REPL controller schedules a continuation request, and the runtime owns
   prompt injection, meta/user authorship, accounting, and finalization.
3. Make lease cleanup and finalization current-state checked. Cleanup must never
   write an older active goal snapshot over a newer completed, blocked, paused,
   cleared, budget-limited, or usage-limited state.
4. Connect continuation accounting and bounded-failure behavior to the live
   runtime path.
5. Fix goal-specific type errors introduced by the implementation.
6. Replace synthetic acceptance tests with targeted integration tests for the
   highest-risk surfaces.
7. Run manual REPL smoke only after the runtime path and tests are corrected.
8. Update `CONTRACTS.md` only after verified behavior lands.

The remediation must prefer small, source-backed corrections over redesigning
the goal feature. The parent spec remains the authority for feature semantics.

## Review Findings Being Remediated

The review found the following issues in the implementation worktree:

1. Lease cleanup can resurrect stale active goals.
2. REPL goal continuation is submitted as a normal user message instead of
   using the intended runtime/meta continuation path.
3. Goal accounting is not connected to the live continuation path. The current
   REPL path bypasses accounting entirely; the unused `QueryEngine` branch would
   use `tokenDelta = 0` and a synthetic turn id if wired.
4. Goal-specific TypeScript regressions were introduced on top of pre-existing
   missing-mock typecheck debt.
5. Tests are too synthetic for session resume, tombstones, `/goal`
   discoverability, slash dispatch, and tool persistence.
6. The implementation branch is based before the committed goal spec and plan.
   A raw merge or diff can drop those docs unless the implementation is replayed
   onto current `main` or the docs are explicitly preserved.
7. `GoalUpdateTool` tests do not prove real persisted state transitions.
8. Retry/backoff and `usageLimited` lifecycle fields exist in domain code and
   tests but are not wired into the runtime on continuation start, success, or
   failure.

## Non-Goals

- Do not add daemon or background goal continuation.
- Do not add a shell CLI mirror such as `microagent goal ...`.
- Do not turn conversation goals into managed autonomy flows.
- Do not store or derive current conversation goal state from
  `AutonomyFlowRecord.goal`.
- Do not add a full debug trace UI, lease inspector, token dashboard, or
  user-facing internal event timeline.
- Do not expand the fix into unrelated REPL, query, or session-storage
  refactors.
- Do not treat pre-existing missing `tests/mocks/*` typecheck debt as part of
  this remediation, except to keep new goal code from adding additional type
  errors.

## Required Remediation Order

The work must be done in this order because later fixes depend on earlier
runtime boundaries.

1. Preserve the approved spec and plan docs while moving the implementation onto
   current `main`.
2. Rewire goal continuation into a single canonical runtime path.
3. Make lease release and goal finalization current-state checked.
4. Implement real continuation bookkeeping: start stamp, success accounting,
   failure accounting, retry/backoff, and `usageLimited`.
5. Fix goal-specific TypeScript regressions.
6. Add integration tests for real persistence/resume and real `/goal` surfaces.
7. Tighten `GoalUpdateTool` tests to assert persisted transitions.
8. Re-run focused tests, typecheck with goal-error audit, full test command as
   feasible, and manual REPL smoke.
9. Update active contracts only after source-backed behavior is verified.

## Remediation Requirements

### 1. Branch And Documentation Preservation

The implementation must be applied on top of current `main` at or after
`aad5186 docs: plan microagent conversation goals`.

Required behavior:

- The remediation branch must contain:
  - `docs/superpowers/specs/2026-06-03-microagent-conversation-goal.md`;
  - `docs/superpowers/plans/2026-06-04-microagent-conversation-goal.md`;
  - this remediation spec.
- A diff from the remediation branch base to head must not delete those files.
- If the existing implementation commits are cherry-picked or rebased, conflicts
  must be resolved in favor of preserving the accepted docs.
- `docs/superpowers/` is ignored by git, so any new or preserved spec/plan file
  that should be committed must be added with `git add -f`.

Acceptance tests and checks:

- `git merge-base main HEAD` is at or after `aad5186`, or the branch is otherwise
  demonstrably replayed onto a commit containing the accepted spec and plan.
- `git diff --name-status <base>..HEAD -- docs/superpowers` does not show
  deletion of the parent spec, parent plan, or remediation spec.
- `git status --short` has no accidental ignored-doc omissions after force-add.

### 2. Canonical Goal Continuation Path

Goal continuation must have one runtime path. The REPL controller may decide
that a goal continuation should be scheduled, but it must not construct a fake
user message containing the internal goal prompt.

Required behavior:

- The controller submits a continuation request with an explicit
  `goalContinuation: true` marker or equivalent typed option.
- `QueryEngine` or the existing query boundary owns:
  - loading the latest active goal;
  - building the internal continuation prompt;
  - marking the prompt as runtime/meta input;
  - associating the continuation with the active `goalId` and lease owner;
  - finalization and accounting.
- The internal `<conversation-goal>` prompt must not be persisted as normal
  user-authored text.
- Normal user prompts, slash commands, queued commands, and scheduled tasks must
  keep their existing path and priority.
- The slash command `/goal <objective>` continues to update goal state and
  return control to the runtime. It must not directly start a turn.
- If the runtime path is `REPL.tsx -> query(...)` rather than
  `QueryEngine.submitMessage()`, the remediation must implement the same typed
  continuation option at that actual boundary. The invariant is the typed
  continuation boundary, not the name of the function.

Rejected approach:

- Do not keep `createUserMessage({ content: buildGoalContinuationPrompt(...) })`
  as the foreground continuation mechanism. That makes runtime-owned context
  look like user-authored transcript input.

Acceptance tests:

- A goal-driven continuation reaches the query boundary with an explicit
  continuation marker.
- The internal prompt is marked meta/runtime-owned.
- The user transcript does not contain a normal user message whose content is
  the raw `<conversation-goal>` prompt.
- Normal user prompts still create normal user-authored transcript entries.

### 3. Current-State Checked Lease Cleanup

Lease release and cleanup must never append a stale active snapshot over a newer
goal state.

Required behavior:

- Lease acquire remains compare-and-set over active `goalId`, `revision`, and
  owner state.
- Lease cleanup must reload current goal state before writing.
- Cleanup may release a lease only when the current goal still matches:
  - same `goalId`;
  - same revision captured by the lease, or an explicitly documented successor
    revision that still represents the same leased continuation;
  - same `continuationOwner.ownerId`;
  - status still eligible for lease release.
- If the current goal is `complete`, `blocked`, `paused`, `usageLimited`,
  `budgetLimited`, cleared, replaced, or owned by another continuation, cleanup
  must no-op.
- Finalization paths that change a goal to stopped or terminal status must
  clear or invalidate the lease without allowing a later cleanup to overwrite
  that state.
- A stale cleanup must not write a new transcript metadata entry.

Recommended implementation shape:

- Add a helper near goal persistence or domain code, for example
  `releaseCurrentGoalContinuationLease(ownerId, expectedGoalId, expectedRevision)`.
- That helper should:
  - read `getCurrentConversationGoal()`;
  - verify the expected lease identity;
  - save only the latest verified goal;
  - return a structured result such as `released`, `stale`, `missing`, or
    `ownerMismatch`.

Acceptance tests:

- If a continuation marks the goal `complete`, subsequent effect cleanup does
  not restore `active`.
- If a continuation marks the goal `blocked`, cleanup does not restore `active`.
- If a user interrupt pauses the goal, cleanup does not restore `active`.
- If `/goal clear` writes a tombstone while a lease exists, cleanup does not
  resurrect the cleared goal.
- If `/goal <objective>` replaces the goal while an old lease exists, cleanup
  does not mutate the replacement.
- Normal cleanup for an unchanged active leased goal releases the lease exactly
  once.

### 4. Continuation Accounting And Retry Lifecycle

Continuation runtime bookkeeping must be connected to the live continuation
path.

Required behavior at continuation start:

- Reload current goal after lease acquire.
- Persist `lastContinuationAt` for the starting turn.
- Reset or preserve failure fields according to the current retry state:
  - starting a retry must not erase previous failure count until success;
  - replacing or manually resuming may reset failure count as specified by the
    parent spec.
- Record enough identity to associate finalization with the active goal and
  lease.

Required behavior on continuation success:

- Apply actual token usage from the completed turn when available.
- Use a real turn/message identity when available.
- If the repo lacks a stable turn id at the selected boundary, use the best
  existing persisted assistant or result message UUID and document that choice
  in code comments and tests.
- Clear `lastError`.
- Reset or decrement `failureCount` to the chosen success policy. The first
  remediation policy is reset to `0` on successful continuation.
- If `tokensUsed >= tokenBudget`, persist `budgetLimited` and prevent further
  idle continuation.
- If the model marked the goal `complete` or `blocked`, preserve that terminal
  state and do not apply an active-only accounting transition over it.

Required behavior on continuation runtime failure:

- Increment `failureCount`.
- Persist `lastError` with a sanitized, user-safe summary.
- Preserve retry/backoff by updating the goal so
  `isGoalContinuationEligible()` will not immediately hot-loop.
- When `failureCount` reaches the retry limit, persist `usageLimited`, clear the
  lease, and emit a visible stopped/limited notification.
- A failure path must not clear tombstones, resurrect replaced goals, or
  overwrite terminal states.

Required behavior for token accounting:

- `tokenBudget` remains optional. Null or omitted means no token budget.
- `timeUsedSeconds` remains accounting only and must not trigger
  `budgetLimited`.
- `budgetLimited` prevents further idle continuation.

Acceptance tests:

- Successful continuation increments `tokensUsed` from real or explicitly
  bridged usage.
- Crossing `tokenBudget` sets `budgetLimited`.
- `timeUsedSeconds` alone does not set `budgetLimited`.
- Successful continuation records a real persisted turn/message identifier or
  the documented bridge identifier.
- Runtime failure increments `failureCount` and records `lastError`.
- Repeated failures transition to `usageLimited` and stop continuation.
- Success resets `failureCount` to `0`.
- A model `complete` or `blocked` update is not overwritten by accounting.

### 5. Type Safety Remediation

The remediation must remove goal-specific TypeScript errors introduced by the
implementation.

Known goal-specific errors:

- `sessionStorage.ts` uses `conversationGoalEntries` from a returned structure
  whose declared type does not include that property.
- `commands/__tests__/goal.test.ts` narrows `LocalCommandCall` to a text-only
  return shape that is incompatible with `LocalCommandResult`.
- `commands/__tests__/goal.test.ts` contains an implicit `any` in an app-state
  updater callback.

Required behavior:

- Update the relevant return type for transcript/session loading so
  `conversationGoalEntries` is explicitly declared.
- Type command test helpers using `LocalCommandResult` or a narrow helper that
  first asserts `result.type === "text"` before reading `value`.
- Type app-state updater callbacks using the local `AppState` type or the
  existing app-state setter type.
- The remediation does not have to fix pre-existing missing `tests/mocks/*`
  typecheck errors, but it must leave no new goal-specific typecheck errors.

Acceptance checks:

- `bun run typecheck` may still fail on pre-existing missing-mock debt, but it
  must not report goal-specific errors in:
  - `src/utils/sessionStorage.ts`;
  - `src/commands/__tests__/goal.test.ts`;
  - new goal files.
- Capture the filtered typecheck output in the implementation report.

### 6. Persistence And Resume Integration Tests

The original helper-only persistence tests are not enough. Add focused tests
that exercise real persistence seams without requiring a full manual REPL.

Required coverage:

- Saving a goal writes a `conversation-goal` metadata entry to the session
  transcript when a session file exists.
- Clearing a goal writes a `conversation-goal-cleared` tombstone.
- Loading or restoring a transcript with multiple goal entries restores the
  latest effective goal.
- A clear tombstone prevents older goal resurrection.
- Replacing a goal followed by an old lease cleanup does not mutate the
  replacement.
- Creating a goal before transcript materialization must not create a
  metadata-only durable transcript. It must either schedule a real
  continuation turn or report that durable persistence is unavailable, according
  to the parent spec.

Recommended seam:

- Prefer testing `restoreSessionMetadata()` and `loadTranscriptFile()` or a
  small exported test helper that reads through the same metadata scanner.
- Avoid tests that only call `getEffectiveConversationGoalFromEntries()` unless
  paired with at least one real session-storage scan or restore test.

### 7. `/goal` Discoverability And Slash Dispatch Tests

The remediation must prove that `/goal` is visible and dispatchable through the
real command surfaces.

Required coverage:

- Built-in command registry includes `goal`.
- Help command receives the built-in command list and can render or expose
  `/goal`.
- Typeahead uses the real command list and suggests `/goal` for `/go`.
- `processSlashCommand()` recognizes `/goal` through the real registry and
  returns local command output without starting a model turn directly.
- Bare `/goal` shows current state or usage hint.
- `/goal <objective>` preserves free-form objective text and emits
  `Goal started` or `Goal replaced`.
- `/goal edit`, `/goal pause`, `/goal resume`, and `/goal clear` remain
  user/runtime operations.

Testing constraint:

- A helper that hand-builds `[{ name: "goal" }]` is acceptable only for pure
  suggestion formatting. It does not count as the required real-registry
  acceptance test.

### 8. GoalUpdateTool Persisted Transition Tests

`GoalUpdateTool` tests must prove that the model-facing tool changes persisted
goal state only through allowed statuses.

Required coverage:

- Calling the tool with `complete` persists a `complete` goal and updates app
  state.
- Calling the tool with `blocked` persists a `blocked` goal with the provided
  reason and updates app state.
- Calling the tool when no active goal exists returns failure and does not write
  a new goal entry.
- Schema rejects `paused`, `active`, `usageLimited`, and `budgetLimited`.
- The tool cannot clear, resume, pause, replace, or set runtime-owned limits.

### 9. Verification And Contract Update

Verification must distinguish pre-existing test harness debt from
goal-specific regressions.

Required verification:

- Focused goal tests pass.
- New integration tests pass.
- A typecheck audit shows no goal-specific errors, even if pre-existing
  missing-mock errors remain.
- Full `bun test` is attempted. If unrelated pre-existing failures remain,
  report exact failures and classify them.
- Manual REPL smoke is run after automated tests:
  - `/goal`;
  - `/goal <objective>`;
  - `/goal pause`;
  - `/goal resume`;
  - `/goal clear`;
  - observe `Continuing goal: ...` during a goal-driven turn;
  - interrupt a goal-driven turn and confirm the goal pauses.
- Confirm no daemon/background continuation exists after CLI exit.

Contract update:

- Update `src/ragflow_lite/CONTRACTS.md` only after the above behavior is
  verified.
- The contract entry must be short and source-backed. It should state that
  MicroAgent conversation goals are foreground-only, exposed through the
  interactive `/goal` REPL command, persisted through session transcript
  metadata, and separate from managed autonomy-flow goals.

## Acceptance Criteria

This remediation is complete only when all of the following are true:

1. The implementation branch is based on or replayed onto current `main` and
   preserves the parent spec, parent plan, and this remediation spec.
2. REPL goal continuation no longer creates a fake normal user message for the
   internal goal prompt.
3. A typed goal-continuation request reaches the canonical query/runtime
   boundary.
4. The internal goal prompt is treated as runtime/meta input.
5. Lease cleanup reloads current state and no-ops on stale, terminal, stopped,
   cleared, replaced, or owner-mismatched goals.
6. A stale cleanup cannot append an older active goal entry.
7. Goal finalization records real or explicitly bridged turn identity.
8. Goal finalization applies actual or explicitly bridged token usage.
9. Token budget crossing sets `budgetLimited`.
10. Elapsed time accounting does not set `budgetLimited`.
11. Continuation failures increment failure state and apply retry/backoff.
12. Retry exhaustion sets `usageLimited` and stops idle continuation.
13. Success clears `lastError` and resets `failureCount` to `0`.
14. Model `complete` and `blocked` states are not overwritten by accounting or
    cleanup.
15. Goal-specific TypeScript errors introduced by the implementation are fixed.
16. Persistence tests cover real session metadata save, clear tombstone, and
    restore behavior.
17. `/goal` tests cover real built-in registry, slash dispatch, help/typeahead
    visibility, and command output.
18. `GoalUpdateTool` tests prove persisted `complete` and `blocked`
    transitions.
19. Focused goal tests pass.
20. Typecheck audit reports no goal-specific errors.
21. Manual REPL smoke passes.
22. `CONTRACTS.md` is updated only after verified source behavior lands.

## Evidence References From Review

The remediation was scoped from review and read-only exploration of
implementation commit `ca9d9fb`.

Key evidence:

- `useConversationGoalController.ts` cleanup releases the closed-over
  `acquired.goal` snapshot.
- `REPL.tsx` builds `buildGoalContinuationPrompt(goal)`, wraps it in
  `createUserMessage(...)`, and calls `onQuery(...)` without a continuation
  option.
- `QueryEngine.submitMessage()` has a `goalContinuation` option, but no live
  REPL call path sets it.
- `QueryEngine` has real usage aggregation, while the current goal accounting
  branch uses `tokenDelta = 0` and a synthetic id and is not live.
- `sessionStorage.ts` carries `conversationGoalEntries` at runtime but misses
  type coverage in the load return shape.
- Real `/goal` visibility should be tested through the built-in command
  registry, help/typeahead, and slash-command dispatch path.
- The implementation branch merge-base with `aad5186` is `6d84231`, so
  remediation must preserve docs when replaying or rebasing.

## Implementation Handoff Notes

- Start from a clean worktree based on current `main`.
- Preserve user work in `.claude/worktrees/`; do not delete existing worktrees.
- Fix runtime path issues before adding contract docs.
- Keep changes scoped to MicroAgent goal runtime files and directly related
  tests.
- Use TDD for each remediation slice:
  - stale cleanup reproduction first;
  - continuation meta-path test before rewiring;
  - accounting/retry tests before runtime bookkeeping;
  - typecheck audit after type fixes;
  - integration tests after runtime path is corrected.
