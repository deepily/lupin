---
capability: llm-model-config-and-window
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.model_registry.LlmProvider@56411fc933
  - cosa.agents.model_registry.ModelConfig@faeb4b7e74
  - cosa.agents.model_window.count_tokens@412594d65d
  - cosa.agents.model_window.get_context_window@9f7cb79902
  - cosa.agents.model_window.clamp_max_tokens@2240c5a0aa
  - cosa.agents.model_window.resolve_vllm_spec@085843bf01
  - cosa.agents.token_counter.TokenCounter@ca3c7ed826
---
# Model configuration and context window

These helpers describe a model and keep a completion inside its context window. The window is read from the serving model, never from a configured constant.

## What it does
- `LlmProvider` lists the providers: `openai`, `anthropic`, `groq`, `google` and `deepily`.
- `ModelConfig` holds a model name, provider, client class, `max_tokens` and optional per-token costs. It rejects a non-positive `max_tokens` and a negative cost.
- `count_tokens` makes one tokenize call to a vLLM server. It returns the token count and the model's window together, and caches the window.
- `get_context_window` returns the window the server reports for a model. A second call for the same server and model makes no network call.
- `clamp_max_tokens` returns the requested budget when it fits beside the prompt. Otherwise it returns the window minus the prompt and a margin of 64, and never less than 1.
- `resolve_vllm_spec` splits a `vllm://host:port@model` config value into a completions URL and a model name. Without the `@model` part it raises `ValueError`.
- `TokenCounter` counts tokens with `tiktoken` for a named model. It falls back to the `cl100k_base` encoding, then to one token per four characters.

## Don't
- Don't hard-code a context window. `count_tokens` and `get_context_window` raise `RuntimeError` when the server cannot answer, and the caller decides what to do.
