# WG-6 — Investigate 2 survivor FAILs (post WG-1/2/5)

## Survivors

After WG-1 (Docker), WG-2 (skip discipline), and WG-5 (lxml) land, two FAILs are expected to remain:

1. **`test_notification_proxy_script_matching`** — actual failure shows loading `notification-proxy-scripts/deep-research.json` then assertion fail. Likely script-content drift.
2. **`test_tfe_error_capture_smoke`** — fails at "Part 1: Persistence allowlist check..." Likely persistence/store issue.

## Approach

Investigation only — NOT a blind fix. After WG-1/2/5 land, re-run smoke. If these still fail, capture full pytest stdout/stderr per test and:
- file as separate bug-fix-mode entries with evidence
- escalate to a separate planning cycle (becomes OOS-3 if non-trivial)

## Acceptance

- Re-run smoke captures the actual failure mode for both tests.
- If both pass after WG-1/2/5: mark WG-6 done, no investigation needed.
- If either fails: evidence captured, OOS-3 plan drafted.

## Files

- TBD after re-run.

## Status

- [ ] Re-run smoke after Phase 1+2 complete
- [ ] If still failing → file evidence
- [ ] If still failing → escalate to OOS-3
