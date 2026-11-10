---
capability: duplicate-check-test-code
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.is_test_code@98d7410a63
  - lupin_mcp.duplicate_check_daily.without_test_code@d90d051822
---
# Duplicate check: leaving test code out

The daily check neither judges test code nor offers it as a match. The window and the pool are in [[duplicate-check-daily-window]]; the run record is in [[duplicate-check-daily-run]].

## What it does
- `is_test_code( file, name )` takes a repository path with forward slashes and a dotted definition name.
- It is true where `symindex.spec.is_test_path` is: a directory of the path is named `tests`.
- It is also true for `conftest.py`, `*.test.ts` and `*.test.js` files, and for any definition inside a `quick_smoke_test`.
- A file name that only begins `test_` is not matched, so a production file such as `test_runner.py` is judged.
- `without_test_code( defs )` returns the definitions that are not test code, and how many it left out.

## Where it applies
- `new_definitions` drops test code from the owed set and returns the count as `test_dropped`.
- `baseline_definitions` does the same for a baseline run.
- `pool_without_earlier_versions` drops it from the comparison pool, so a definition is never paired with a test fake.
- `run` records `test_code_dropped` with `owed` and `pool` in the run record.
