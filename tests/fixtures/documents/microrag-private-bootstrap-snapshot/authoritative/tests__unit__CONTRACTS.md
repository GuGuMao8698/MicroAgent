# tests/unit/CONTRACTS.md

Unit-wide test contracts. Navigation lives in [../AGENTS.md](../AGENTS.md).

## Determinism

Unit tests must be deterministic by default. No live Infinity or live provider dependency unless explicitly marked and justified.

## Allowed fakes

- Fake Ark embedding and DeepSeek/OpenAI structured clients are allowed at non-Infinity boundaries (e.g. `_FakeDeepSeekJsonClient` in conftest.py).

## Prohibited fakes

Do not add fake/stub/mock Infinity clients, databases, tables, query builders, or monkeypatches of `infinity.connect`. Any test crossing real Infinity SDK/table/query behavior belongs in [tests/integration](../integration) with `@pytest.mark.live_infinity`.

## Fake scope

Fake or stub behavior should be local to the test file and must not redefine production contracts.

## Shared scope

application, domain, and infrastructure test subtrees share this contract. Boundary rules unique to each subtree are documented in their respective local navigation files.
