# WG-7 — Websocket suite false-FAIL parser fix

## Root cause

The `:8000` `test_suite` job's per-suite parser sets the `websocket` row to 0/0/0/0 → suite classified as FAIL — even though the runner logs `ALL SMOKE TESTS PASSED · 50/50 (100%)`. The websocket runner emits non-pytest format (a custom `[INFO]` log scheme via `src/scripts/run-websocket-smoke-tests.sh`) that the parser can't read.

## Approach

Minimum-blast-radius fix: teach the test_suite parser to recognize the websocket runner's success line as a green signal. A better long-term fix (run websocket smoke under pytest with junit-xml) is OOS-2.

## Steps

1. Locate parser: probably `src/cosa/agents/test_suite/test_suite_runner.py` or similar — exploration didn't open this path, so first find via:
   ```
   grep -rln '"websocket"' src/cosa/agents/test_suite/ src/cosa/rest/
   ```
2. Read the per-suite metric extraction logic.
3. Add a fallback path: when no junit-xml / pytest-format detected AND stdout contains `ALL SMOKE TESTS PASSED`, parse `Total Tests: N` and emit `passed=N`, `failed=0`, `errors=0`.
4. Add a unit test in `src/tests/unit/` covering both stdout shapes (pytest format + websocket runner format).

## Acceptance

- Unit test passes both shapes.
- Replay the 22:35-EDT websocket suite stdout through the parser → classified as PASS.
- Future `:8000` runs report websocket as PASS when the runner reports `ALL SMOKE TESTS PASSED`.

## Files

- `src/cosa/agents/test_suite/<parser_module>.py` (~20 lines)
- `src/tests/unit/test_test_suite_<parser>.py` (NEW, ~30 lines)

## Status

- [ ] Locate parser
- [ ] Read current logic
- [ ] Add fallback
- [ ] Unit test
- [ ] py_compile
