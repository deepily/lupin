---
capability: llm-exceptions
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.llm_exceptions.LlmConfigError@1142c4f823
  - cosa.agents.llm_exceptions.LlmAPIError@b17ec57d73
  - cosa.agents.llm_exceptions.LlmTimeoutError@9bd3d46619
  - cosa.agents.llm_exceptions.LlmAuthenticationError@f36fa3b2cb
  - cosa.agents.llm_exceptions.LlmRateLimitError@217783ca6b
  - cosa.agents.llm_exceptions.LlmModelError@dcf5fc2cd0
  - cosa.agents.llm_exceptions.LlmStreamingError@8da80c2be7
  - cosa.agents.llm_exceptions.LlmValidationError@7736623029
---
# LLM exceptions

The LLM clients share one exception family under `LlmError`. Each subclass names a kind of failure, so a caller can catch one kind and let the rest through.

## What it does
- `LlmError` carries a message, an optional `error_code` and a `metadata` dict that is never `None`.
- `LlmConfigError` marks a bad or missing model configuration.
- `LlmAPIError` marks a failed API call. It adds `status_code` and `response_body`, both optional.
- `LlmAuthenticationError` is an `LlmAPIError` for bad keys, expired tokens and missing permissions.
- `LlmRateLimitError` is an `LlmAPIError` that adds `retry_after`, the seconds to wait when the API gave one.
- `LlmTimeoutError` marks a request, connection or read timeout.
- `LlmModelError` marks a model problem: an unsupported parameter, an unknown model or a bad model response.
- `LlmStreamingError` marks a stream that failed to connect, carried bad data or ended early.
- `LlmValidationError` marks an invalid request or a response that failed validation.

## Invariants
- Authentication and rate limit errors can be caught as `LlmAPIError`.
- Every class is a subclass of `LlmError`.
