# Agent Documentation Governance

Updated: 2026-05-08 19:54:53 +0800

## Purpose

This file is the standard for maintaining `AGENTS.md` and `CONTRACTS.md` in this repository.

The goal is to keep agent guidance discoverable without letting active runtime, test, or operations semantics split across many competing files.

## File Responsibilities

- `AGENTS.md` is navigation: directory role, command entrypoints, file map, ownership hints, wrong-layer reminders, and a link to the nearest active contract.
- `CONTRACTS.md` is the active source of truth: runtime semantics, test semantics, public API behavior, provider requirements, adapter boundaries, Docker service graphs, default values, and stale-interpretation warnings.
- `CLAUDE.md` is compatibility glue. When present, it must contain exactly `@AGENTS.md`.

## Link Format

Use Markdown links for concrete file references.

Correct:

- `[CONTRACTS.md](./CONTRACTS.md)` when pointing to the local contract.
- `[../CONTRACTS.md](../CONTRACTS.md)` when pointing to the parent contract.
- `[settings.py](settings.py)` when pointing to a local source file.

Use backticks only for generic file names, symbols, commands, environment
variables, or literal values. A bare `` `CONTRACTS.md` `` means "a file named
CONTRACTS.md" and must not be used as a module-contract pointer.

## Module-Local Active Contracts

A module normally has one `CONTRACTS.md`.

Ordinary implementation leaf folders under that module should not own separate contracts. Their `AGENTS.md` files should point to the nearest module-level `CONTRACTS.md`.

A child directory may own its own `CONTRACTS.md` only when it qualifies as a real submodule with independent semantics.

This rule is about semantic ownership, not folder count.

## Independent Contract Eligibility

A directory qualifies for its own `CONTRACTS.md` when at least one of these is true:

- it has multiple child folders or implementation families;
- it owns a public API, runtime protocol, adapter boundary, test harness, provider boundary, or Docker service graph;
- it has invariants that apply to several files or child folders;
- it is consumed across module boundaries;
- it has independent verification commands or fixtures;
- keeping its details in the parent contract would make the parent contract too broad.

A directory does not qualify when:

- it is only a small group of implementation files;
- it has no deeper child modules;
- its rules are just a narrower instance of the parent module rules;
- its `AGENTS.md` only needs a directory role and file map;
- its contract would duplicate the parent `CONTRACTS.md`.

If a directory does not qualify, put active semantics in the nearest qualifying ancestor `CONTRACTS.md`, and make the local `AGENTS.md` point upward.

## AGENTS.md Rules

Keep `AGENTS.md` short.

Allowed content:

- what this directory is for;
- nearest `[CONTRACTS.md](...)` path;
- common local commands;
- file map or ownership hints;
- short wrong-layer reminders.

Forbidden content:

- public API defaults;
- runtime provider requirements;
- query budget semantics;
- test marker behavior;
- Docker service topology;
- environment variable contracts;
- long stale-interpretation warnings;
- duplicated contract paragraphs.

If text needs timestamped semantic force, it belongs in `CONTRACTS.md`, not `AGENTS.md`.

## CONTRACTS.md Rules

Write only current, source-backed facts.

Good contract content:

- exact active defaults and boundaries;
- current producer/consumer metadata contracts;
- environment or provider requirements;
- test gates and fixture behavior;
- Docker service and port contracts;
- stale interpretations that must not be revived;
- verification commands or source anchors.

Bad contract content:

- implementation walkthroughs;
- historical plan text;
- speculative future design;
- duplicate child-module details;
- details copied from old docs without checking source.

If old docs and source code disagree, do not preserve the old doc by inertia. Either document the source-backed truth, remove the stale claim, or stop and report the contradiction.

## Parent And Child Contracts

Parent contracts own cross-module invariants.

Child contracts own only their independent submodule semantics.

A parent contract may link to a qualifying child contract, but should not repeat the child contract's active details. A child contract should not redefine parent-wide rules.

## Maintenance Checklist

Before adding a new `CONTRACTS.md`:

1. Identify the module boundary it owns.
2. Check whether the nearest parent contract already owns the semantics.
3. Apply the independent contract eligibility test.
4. If it does not qualify, update the parent contract and make the local `AGENTS.md` point upward.
5. If it qualifies, keep the parent contract free of duplicated child details.

Before editing `AGENTS.md`:

1. Keep commands and navigation.
2. Move active semantics to the nearest `CONTRACTS.md`.
3. Link to the nearest contract instead of copying it.
4. Preserve `CLAUDE.md` as exactly `@AGENTS.md`.

Before retaining an existing `CONTRACTS.md`:

1. Re-run the independent contract eligibility test.
2. Verify its facts against source files or tests.
3. Remove duplicated parent or child contract content.
4. Delete or merge it if it is only a leaf-folder contract.
