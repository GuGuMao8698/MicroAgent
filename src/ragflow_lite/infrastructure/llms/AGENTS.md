# AGENTS.md

这个目录封装 non-embedding LLM client。当前主路径是 DeepSeek Chat Completions。

- `DeepSeekChatCompletionsClient` provides text and JSON completion helpers for answerers, query grounders and evidence extractors.
- JSON mode adds the required JSON instruction and uses a large JSON token budget contract.
- Retry is limited and adapter-local.
- Keep Chat Completions request shape centralized here; do not duplicate low-level DeepSeek request construction in callers.
- Preserve structured JSON output handling; callers should validate domain schema after receiving text/JSON.
- Retry only retryable provider failures and keep the attempt count bounded.
- Do not log prompts, user query text, document chunks, response payloads, or API keys.
- Do not reintroduce Ark/OpenAI as non-embedding runtime defaults unless explicitly requested.
