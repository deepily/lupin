---
capability: utils-expect-raises
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.expect_raises.expect_raises@819b399b2a
---
# Expect a guard to raise

One helper in `cosa.utils.expect_raises` proves a guard fires. A smoke test calls a function that should be refused and requires the refusal.

## What it does
- `expect_raises( exception_type, fn, *args, **kwargs )` calls `fn` and returns the exception it raised, when that is `exception_type` or a subclass.
- If `fn` returns quietly it raises `AssertionError` naming the function and the expected type, so a guard that stayed silent is a failure.

## Don't
- Don't write a private "assert raises" for a smoke test. Two copies, in `vertex_logging` and `dm_quality_judge.xml_models_v2`, were folded into this one.
- Don't use it in pytest tests. `pytest.raises` already does that job.

## Invariants
- An exception of another type propagates unchanged; it is never reported as "did not raise".
- The `vertex_logging` canary-law smoke test and the DM judge v2 extraction controls both call it.
