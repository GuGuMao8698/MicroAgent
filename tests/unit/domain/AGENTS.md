# AGENTS.md

Unit-wide rules: see `../CONTRACTS.md`.

## Directory role

Domain models and ports. Keep it small, pure, and implementation-free.

## Boundary rules

- Tests here protect field preservation, default factories, optional fields, and protocol boundaries.
- Domain tests should not need filesystem, FastAPI, Infinity, provider SDKs, or runtime environment variables.
- Do not encode infrastructure behavior in domain tests.
- Do not assert transient implementation repr/order details unless they are part of the domain contract.
