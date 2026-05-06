# AGENTS.md

这个目录实现 answerer adapter 和回答 prompt 模板。它只把 `AnswerRequest` 转成 provider 调用并清洗回答。

- `DeepSeekChatAnswerer` is the current non-embedding answerer path.
- `OpenAIResponsesAnswerer` remains legacy compatibility; do not make it the new default.
- Prompt templates are repo-tracked files, not inline source constants.
- `FALLBACK_ANSWER` is the shared no-context answer.
- Preserve citation cleaning and context ordering behavior; answerers receive already selected contexts.
- Prompt path priority belongs in config/wiring; do not scatter environment fallback logic across helper functions.
- `plain` template is used by evals to avoid citation artifacts; keep citation rendering configurable.
- Do not log provider payloads, raw contexts, full query text, or generated answers.
- Do not add retrieval, rerank, or evidence selection logic here.
