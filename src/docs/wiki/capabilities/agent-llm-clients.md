---
capability: agent-llm-clients
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.llm_client_factory.LlmClientFactory@5d763bec1a
  - cosa.agents.llm_client_factory.LlmClientFactory.get_client@cf9b95d876
  - cosa.agents.base_llm_client.LlmClientInterface@de0959601e
  - cosa.agents.chat_client.ChatClient@9726b133d2
  - cosa.agents.completion_client.CompletionClient@ef6a1ebf81
  - cosa.agents.completion_client.CompletionClient.run_async@6000cce0ae
  - cosa.agents.completion_client.clean_llm_response@ba1097590b
  - cosa.agents.gemini_vertex_client.GeminiVertexClient@dd7f926f66
  - cosa.agents.token_counter.TokenCounter.count_tokens@3ef189b0ea
  - cosa.agents.llm_exceptions.LlmError@8fe765a832
  - cosa.agents.base_llm_client.BaseLlmClient@a26bd9fbe7
  - cosa.agents.model_registry.ModelRegistry@2fce02b33f
---
# Agent LLM clients

`LlmClientFactory().get_client( key )` returns the client an agent uses to send a prompt to a model; every client answers `run( prompt )` and `await run_async( prompt )` with a string, whatever the vendor.

## What it does
- The factory is a singleton. `get_client` first looks `key` up in the INI through `ConfigurationManager`, and otherwise reads it as `vendor:model` (the colon is the only vendor delimiter; `_parse_model_descriptor` reads a string with no colon that starts `llm_deepily_` as a Deepily model, and any other string with no colon as a local vLLM model id).
- A configured spec picks the client by its prefix. `vllm://host:port@model` with prompt format `instruction_completion` or `special_token` gives a `CompletionClient`; any other `vllm://` spec gives a `ChatClient`. `vertex://location@model` gives a `GeminiVertexClient`. Anything else gives a `ChatClient`.
- `ChatClient` goes through pydantic_ai; `CompletionClient` posts to an OpenAI-style completions URL and strips code fences from the reply with `clean_llm_response`.
- `TokenCounter` uses tiktoken, or `len( text ) // 4` when it is missing. `LlmError` and its subclasses are defined, and only the docstrings of `base_llm_client.py` and `model_registry.py` promise them. No client raises one: the one non-test `raise Llm*Error` in `src/cosa` is `ModelRegistry.get_model_config` (`LlmConfigError`), which the factory never calls (grep, outside tests, 2026-10-07).

## Invariants
- A `vertex://` spec without `@` raises `ValueError`, and so does the location `us-central1` (it returns 404 for these models; use `global`).
- On the `vendor:model` path, a cloud vendor's key comes from its environment variable, else `get_api_key`. The OpenAI key is always resolved afresh, because other vendors write that variable.
- `CompletionClient.run_async` rebuilds its generation arguments by hand: only `temperature`, `max_tokens`, `stop`, `top_p`, `stream` and `timeout` pass through, and `max_tokens` falls back to 64. Only the `vendor:model` path adds the INI defaults (`llm client default temperature`, `llm client default max tokens`, 1024).

## How to extend
- A new hosted vendor needs a `VENDOR_CONFIG` row and a default URL in the `defaults` dict of `_load_vendor_urls`; the INI key `llm vendor url <vendor>` only overrides a vendor already in that dict. A new client shape subclasses `LlmClientInterface` and gets a branch in `get_client`, as `GeminiVertexClient` did.

## Don't
- Don't build `ChatClient` or `CompletionClient` directly for a configured model; go through `get_client`, which picks the client and its URL.
- Don't expect `BaseLlmClient` or `ModelRegistry` to be in the path: the factory returns `LlmClientInterface` clients, and only their unit tests import them (`agents/__init__.py` has the imports commented out).
- Don't expect more than 64 tokens from a configured `vllm://` completion spec unless its `_params` set `max_tokens`.
