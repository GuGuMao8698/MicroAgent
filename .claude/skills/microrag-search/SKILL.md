---
name: microrag-search
description: Use MicroRAG DiscoRAG retrieval evidence when answering questions about indexed local documents or when the user asks to search MicroRAG.
---

# MicroRAG Search

Retrieve local document evidence through MicroRAG's DiscoRAG mode.

## Workflow

1. Decide whether the user needs evidence from indexed MicroRAG documents.
2. Run DiscoRAG retrieval with the user's question.
3. Use stdout JSON as evidence.
4. Answer using the retrieved contexts and blueprint.
5. If retrieval fails or evidence is insufficient, say so plainly and do not invent evidence.

## Retrieve Evidence

```bash
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

## Reading the Result

The command prints model-facing JSON to stdout.

Use:
- `query` as the search query context.
- `contexts` as the retrieved evidence chunks.
- `blueprint` as DiscoRAG's answer planning constraints and evidence organization.

Treat stdout JSON as evidence. stderr diagnostics are not evidence.

## Error Handling

If the command fails with `setup error:`, tell the user MicroRAG is not ready in product terms.

If retrieval returns no usable evidence, say that MicroRAG did not find enough evidence and ask the user to clarify or provide more specific terms.

Do not invent citations, document facts, or source claims.

## Common Mistakes

- Do not use stderr diagnostics as evidence.
- Do not expose runtime internals, command paths, local filesystem paths, transcript files, or process protocol details.
