---
capability: rest-services-test-run-guards
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.pytest_args_policy.PytestArgsRejected@c0efc34408
  - cosa.rest.pytest_args_policy.parse_and_validate@0650014a67
  - cosa.rest.pytest_args_policy.find_per_test_timeout@e15fca9765
  - cosa.rest.pytest_args_policy.validate_timeout_against_suite_budget@5aca5735a3
  - cosa.rest.suite_run_token.token_enabled@6ff7f11f50
  - cosa.rest.suite_run_token.issue@1293ddf4df
  - cosa.rest.suite_run_token.check@a3fbd661f8
  - cosa.rest.suite_run_token.revoke@f0888b7c21
  - cosa.rest.suite_run_token.clear@36345180a8
  - cosa.rest.venue_idle.check@7b448f00a1
  - cosa.rest.venue_idle.format_report@4bcd4ebe98
  - cosa.rest.venue_idle.main@27b7072641
---
# Test-run guards: pytest args, suite token, venue idle

Three small controls around a scheduled test run. See [[scheduled-test-suite]] for the job that uses them.

## What it does
- `parse_and_validate( pytest_args_string, project_root )` shlex-parses a caller's `pytest_args` and returns the token list. Every token must be a known flag, a value bound to a flag, or a test path inside a permitted root; anything else raises `PytestArgsRejected`. `None` or blank returns `[]`.
- `find_per_test_timeout( tokens )` returns the `--timeout` value as a float, in either `--timeout 5400` or `--timeout=5400` form, or `None`.
- `validate_timeout_against_suite_budget` raises `PytestArgsRejected` when that timeout is under the whole-suite budget of a suite in `test_types`. Without `--timeout` it returns `None`.
- `suite_run_token.issue( parent_id, ttl_seconds )` returns a URL-safe token and stores only its digest and expiry. A second `issue` for the same parent replaces the first.
- `check( parent_id, token, active_monopolizer )` returns `( True, None )` or `( False, reason )`. The reasons are `token_unknown`, `token_mismatch`, `token_expired` and `not_active_monopolizer`.
- `token_enabled` is False unless the INI key `v2 parent stamp token enabled` is true. `revoke( parent_id )` forgets one parent; `clear` forgets all.
- `venue_idle.check( port )` reads `GET /api/busy` and returns `( verdict, report_text, signals )`. `format_report` renders the same text; `main` prints it and returns exit code 0 for `IDLE`, 1 for `BUSY` and 2 for `UNKNOWN`.

## Don't
- Don't read `UNKNOWN` as idle. A signal that could not be read is `UNKNOWN`, and `BUSY` wins over it.
- Don't add a flag to the allowlist without a reason. A flag outside the sets is refused.
- Don't log the token. `check` returns a fixed reason word, never the token.

## Invariants
- `issue` raises `ValueError` for an empty parent id or a non-positive TTL.
