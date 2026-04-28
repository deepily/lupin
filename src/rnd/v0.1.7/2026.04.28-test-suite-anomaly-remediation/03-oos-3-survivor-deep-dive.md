# OOS-3 — Deep root-cause for any WG-6 survivors (PROPOSAL — awaiting ratification)

**Status**: Plan only. **Conditional**: this OOS is only triggered if the verification re-run still shows these tests failing after WG-1/2/5 land. If they pass, OOS-3 is closed without code work.

## Survivor candidates

Two smoke tests fail in the 22:35 report with assertions that aren't obviously environmental:

### Survivor 1: `test_notification_proxy_script_matching`

**Captured stdout snippet**:
```
- Notification Proxy Script Matching Smoke Test (script=deep_research, tier=all)
  Loading script: deep_research (/var/lupin/src/conf/notification-proxy-scripts/deep-research.json)
```

Test fails with bare `assert False = quick_smoke_test()`. The full traceback isn't in the 22:35 report — only the captured stdout up to the failure point. We don't know which scenario or rule failed.

### Survivor 2: `test_tfe_error_capture_smoke`

**Captured stdout snippet**:
```
- TFE Forensic Error Capture Smoke Test
Part 1: Persistence allowlist check...
```

Test fails with bare `assert False = quick_smoke_test()`. Full traceback truncated.

## Proposed approach

### Phase 0 — Trigger gate

Run a fresh `pytest src/tests/smoke/test_notification_proxy_script_matching.py src/tests/smoke/test_tfe_error_capture_smoke.py -v -s` against `:7999` after WG-5's `lxml` lands and the candidate image is built. Capture the **full** stdout/stderr/traceback.

If both pass: close OOS-3.
If either fails: capture evidence and proceed to Phase 1.

### Phase 1 — Survivor 1 diagnosis (notification proxy script)

The test loads `src/conf/notification-proxy-scripts/deep-research.json` and exercises script-matching rules. Hypotheses:

1. The JSON file's schema drifted from what the matcher expects.
2. A new prompt/notification field was added to deep-research's notification flow that the script doesn't anticipate.
3. The matcher's confidence threshold is too high after a recent tuning.

**Investigation steps**:
- Read the JSON file — check schema_version field (if any).
- Read `src/cosa/agents/test_fix_expediter/orchestrator.py` for any 2026-04-XX changes to deep-research notification structure.
- Run the test with `LUPIN_DEBUG=1` (or the smoke test's `--debug` flag if supported) to surface per-scenario match attempts.

**Likely fix shapes**:
- Update the JSON to match current notification structure (data fix).
- Add a deprecation/migration note if the schema needs new fields.

### Phase 2 — Survivor 2 diagnosis (TFE error capture)

The test exercises TFE's persistence allowlist. Hypotheses:

1. The persistence layer's allowlist drifted (a new persisted artifact type was added but not allowlisted).
2. The test expects an in-memory store but the configuration switched it to PostgreSQL recently.
3. A missing migration for a new `tfe_*` table.

**Investigation steps**:
- Read `src/cosa/rest/test_suite_completion_watchdog.py` and TFE persistence code for recent changes.
- Run the smoke test with `--debug` (if supported) to see exactly which allowlist entry rejected.
- Check `lupin-app.ini` for `tfe persistence allowlist` (or similar) keys.

**Likely fix shapes**:
- Add the missing allowlist entry.
- Or update the test's expected allowlist if the production allowlist intentionally tightened.

## Files likely to change

Unknown until Phase 0 evidence is captured. Most likely candidates:
- `src/conf/notification-proxy-scripts/deep-research.json` (Survivor 1)
- `src/cosa/agents/test_fix_expediter/<persistence>.py` (Survivor 2)
- The test files themselves (only if expected values drifted intentionally)

## Acceptance criteria

- For each survivor that fails Phase 0:
  - A captured stack trace and root-cause document in the execution log.
  - One-line fix or, if non-trivial, a follow-up ticket with explicit scope.
  - Test passes at `:7999` after fix.

## Estimated effort

XS-S, conditional. If both pass Phase 0: 0 effort. Each surviving failure: 1-3 hours.

## Out of scope (for OOS-3)

- Refactoring either smoke test's structure (separate ticket).
- Tightening or relaxing the TFE persistence allowlist for non-test reasons (separate ticket).
