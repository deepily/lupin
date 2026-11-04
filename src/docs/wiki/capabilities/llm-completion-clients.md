---
capability: llm-completion-clients
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.llm_client.LlmClient@83c24255c3
  - cosa.agents.llm_completion.LlmCompletion@91250e5345
  - cosa.agents.llm_completion.CompletionStreamingContext@d2a8afebda
  - cosa.agents.llm_client_factory.LlmClientFactory.AgentWrapper@ca8ae7ddbc
  - cosa.agents.prompt_formatter.PromptFormatter@f898ac04f4
  - cosa.agents.raw_output_formatter.RawOutputFormatter@5eb75a99f7
---
# LLM completion clients and formatters

Four classes call a model and two shape what goes in or comes out. Callers use `run` on each and do not manage event loops.

## What it does
- `LlmCompletion` posts a prompt to an OpenAI-compatible completions URL and returns the text with code fences removed and whitespace stripped.
- `LlmCompletion` first asks the server for the prompt's token count and lowers `max_tokens` to fit the window. If the count cannot be had, it sends the request unchanged.
- `run` takes an optional `timeout` that covers the whole call, both HTTP requests included. It raises the builtin `TimeoutError`.
- `CompletionStreamingContext` is the async context manager that `run_stream` returns. Its `stream_text` yields the response in chunks.
- `LlmClient` is the wider client. In completion mode it wraps `LlmCompletion`, otherwise a `pydantic_ai` agent. It counts tokens and prints timing.
- `LlmClient.run` works from sync and async code. From a running event loop it moves the work to a separate thread.
- `LlmClientFactory.AgentWrapper` gives a `pydantic_ai` agent a plain synchronous `run` and returns the response data.
- `PromptFormatter` picks one of three formats for a model: instruction completion, special token or JSON message. It fills a template file with instructions, input and output.
- `RawOutputFormatter` asks a model to rephrase raw agent output. It reads the `rephrased-answer` tag and returns that text.

## Don't
- Don't build a `RawOutputFormatter` for a routing command with no formatter template. It raises `KeyError` or `FileNotFoundError`.
