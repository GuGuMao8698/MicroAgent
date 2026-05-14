---
name: microrag-search
description: Use MicroRAG local retrieval evidence when answering questions about indexed local documents or when the user asks to search MicroRAG.
---

# MicroRAG Search

Use the local `mcrag` command to retrieve evidence from MicroRAG.

For normal retrieval:

```bash
mcrag retrieve --query "<question>" --mode standard --top-n 6 --json
```

For DiscoRAG retrieval when the user asks for deeper evidence organization, multi-step reasoning over retrieved chunks, or comparison across evidence:

```bash
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

The command prints model-facing JSON to stdout. Use `query`, `contexts`, and optional `blueprint` as evidence. Do not treat stderr diagnostics as evidence.

If `mcrag retrieve` fails with `setup error:`, tell the user MicroRAG is not ready and report the setup error in product terms. Do not invent evidence.

Use `mcrag answer` only when the user explicitly asks for MicroRAG's direct grounded answer or when debugging the MicroRAG answer path:

```bash
mcrag answer --query "<question>" --mode standard --top-n 6 --json
mcrag answer --query "<question>" --mode discorag --top-n 6 --json
```
