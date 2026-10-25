---
capability: bounded-retry-policy
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.bounded_retry.RetryPolicy@bbe64819b2
  - cosa.utils.bounded_retry.RetryPolicy.error_is_retryable@dbba3f6d70
  - cosa.utils.bounded_retry.RetryPolicy.result_is_retryable@01f72b729f
  - cosa.utils.bounded_retry.next_backoff@da2e118a02
  - cosa.utils.bounded_retry.retry_call_async@e711431abc
---
# Bounded retry policy

`RetryPolicy` and the async call in `cosa.utils.bounded_retry`. The sync `retry_call` is in [[shared-utilities]].

## What it does
- `RetryPolicy( max_attempts=3, initial_backoff=1.0, backoff_multiplier=2.0, max_backoff=30.0, deadline_seconds=None, retry_on=( Exception, ), retry_if_error=None, retry_if_result=None )` holds the bound and the delay shape. It never calls anything.
- It raises `ValueError` at construction when both `max_attempts` and `deadline_seconds` are None. It also raises when `max_attempts < 1`, when a backoff or deadline is negative, or when the multiplier is under 1.0.
- `error_is_retryable( error )` is False unless the error is an instance of `retry_on`, then asks `retry_if_error` when set. `result_is_retryable( result )` is False unless `retry_if_result` is set.
- `next_backoff( current, multiplier, maximum )` returns `min( current * multiplier, maximum )`.
- `retry_call_async( fn, policy, on_retry, sleep, now )` awaits `fn()` with the same rules as the sync `retry_call`. `on_retry( attempt, outcome, delay )` and `sleep` may be plain or async functions. The default sleep is `asyncio.sleep`.

## Don't
- Do not expect a wrapped error after retries run out. The last exception is re-raised unchanged. A value-triggered retry returns the last value instead.

## Invariants
- Callers of `retry_call` and `RetryPolicy` outside tests: `tools/search_kagi.py` only, at the last check.
