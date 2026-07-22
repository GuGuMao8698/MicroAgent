# PROTOTYPE: Pi goal/subagent launch boundary

This throwaway runtime probe answers one question: can the pinned public interfaces of
`pi-subagents@0.35.1` and `@narumitw/pi-goal@0.20.0` guarantee that every child starts a
goal whose objective is the exact task delegated by its parent?

Run from the MicroRAG repository root after building the target Pi snapshot:

```sh
npm --prefix src/microrag_agent/prototypes/goal-subagent-boundary run prototype
```

The command installs only the two pinned extension packages into this prototype directory,
then runs the built Pi CLI with its in-memory Faux provider. It makes no model or API network
request after package installation. The runner uses `参考项目/pi` by default. Set
`PI_SNAPSHOT_ROOT=/path/to/pi` when the built snapshot is elsewhere. The snapshot must already
have its package dependencies installed and `packages/coding-agent` built, as it was for this
captured prototype.

The probe exercises four observable boundaries:

1. Current `pi-subagents` serializes a child task as `Task: <task>`, so Pi does not dispatch
   the `pi-goal` slash command and no `goal-state` entry is created.
2. Replacing only that launch argument with `/goal <task>` dispatches the real `pi-goal`
   command and appends active `goal-state`, but the print/JSON child does not wait for the
   extension-owned prompt and does not exit naturally.
3. The `/goal` parser tokenizes its argument, collapsing whitespace and removing quote
   delimiters. The persisted objective is therefore not byte-for-byte equal to the delegated
   task. It also rejects objectives longer than 4,000 characters.
4. The public delegation response status lacks `blocked`, `usage_limited`, and `budget_limited`.
   Foreground results expose an optional internal `sessionFile`, while background completion
   is delivered through a non-public watcher channel. A thin public extension therefore cannot
   map every child goal terminal state reliably.

Foreground, background, parallel, and chain launches converge on `buildPiArgs()`: foreground
parallel and chain steps call `runSync()`, while background materialized steps call their one
`buildPiArgs()` site. That shared launch sink can inject `pi-goal`, but its current string
command surface cannot preserve every delegated task exactly.

Prototype verdict: the confirmed public-only thin-adapter gate fails. A reliable design needs
a small, upstream-trackable bootstrap API in `pi-goal` that accepts the objective as structured
data, plus a narrow `pi-subagents` launch/result hook or fork that invokes it for every child
and maps persisted goal terminal states. It still does not require a Pi core fork or a copied
goal state machine.
