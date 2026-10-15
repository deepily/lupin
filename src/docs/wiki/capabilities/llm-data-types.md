---
capability: llm-data-types
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.llm_data_types.MessageRole@aaf662ef6f
  - cosa.agents.llm_data_types.LlmMessage@b80df7c346
  - cosa.agents.llm_data_types.LlmRequest@95abe76bea
  - cosa.agents.llm_data_types.LlmResponse@e75f3e7e96
  - cosa.agents.llm_data_types.LlmStreamChunk@d510da1d0c
---
# LLM data types

Five small dataclasses describe a model call: the request, the response, one message, one stream chunk and the message role. Each validates itself when built, so a bad value fails at the boundary.

## What it does
- `MessageRole` is an enum with `system`, `user` and `assistant`.
- `LlmMessage` holds a role, content and a metadata dict. Blank content raises `ValueError`.
- `LlmRequest` holds either a `prompt` or a list of `messages`, never both and never neither. It also carries the sampling settings: temperature, `max_tokens`, `top_p`, penalties, `stop` and `stream`.
- `LlmRequest` rejects a temperature outside 0 to 2, a non-positive `max_tokens`, a `top_p` outside 0 to 1 and a penalty beyond 2 either way.
- `LlmResponse` holds the text, token counts, timing, model, provider, finish reason and an optional cost estimate.
- `LlmResponse` fills `total_tokens` from the other two counts when it is zero. It computes `tokens_per_second` when duration and completion tokens are both positive.
- `LlmStreamChunk` holds one piece of streamed text, an `is_final` flag and an index. A negative index raises `ValueError`.

## Invariants
- Token counts and duration are never negative.
- Every `metadata` field defaults to an empty dict.
