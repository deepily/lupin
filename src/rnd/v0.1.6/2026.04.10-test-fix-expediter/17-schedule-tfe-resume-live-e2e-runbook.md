# Runbook: Schedule TFE Resume Live E2E

**Date**: 2026-04-13
**Session origin**: 9056c113 continuation (commit `a603dbd` added `pytest_direct` UI support)
**Target**: Schedule `src/tests/integration/test_tfe_resume_e2e.py` as a monopolized after-hours run

---

## Pre-flight (do once)

1. **Env vars set** in your shell (from CLAUDE.md TEST CREDENTIALS section):
   ```bash
   export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="<your email>"
   export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="<your password>"
   ```

2. **CoSA submodule commits** — at least `agents/test_suite/job.py` (pytest_direct registration).
   Multiple other CoSA files from session 9056c113 are also working-tree only; commit them together when convenient. The auto-reloading server picks up each file as it's saved.

3. **Hard-reload the notifications dashboard** once after code edits so the browser picks up the new JS / HTML (Ctrl+Shift+R or cache-disabled DevTools reload).

---

## Schedule the run

1. Open the notifications dashboard.
2. Expand the 🧪 **Run Test Suite** submit card.
3. **Test Suites** dropdown: select **"Pytest Direct (arbitrary pytest file, needs file path)"**.
4. **Test File Path**: `src/tests/integration/test_tfe_resume_e2e.py`
5. **Extra Pytest Args** (optional): `-v --tb=short` for verbose output.
6. **Dry run**: uncheck (you want a real run).
7. **📅 Schedule for later**: check → pick tonight's time (exclusive mode is already always-on for test suites).
8. Click **🧪 Run Tests**.

---

## What to expect

The scheduled job runs at the picked time via:

```
bash src/tests/run-pytest-direct.sh \
    src/tests/integration/test_tfe_resume_e2e.py \
    <your extra pytest args>
```

Which expands to `python3 -m pytest src/tests/integration/test_tfe_resume_e2e.py -v --tb=short`.

Coverage (10 tests):
- Health endpoints respond
- `POST /api/test-fix-expediter/resume-from` dispatches correctly for job IDs, plan paths, natural-language descriptions, and error paths
- `POST /api/jobs/{id}/resume-from-checkpoint` returns 404 on missing/non-stalled
- Auth required (401 without token)
- Input validation (400/422 on empty/whitespace)

Output log: `/tmp/pytest-direct-latest.log` (symlinked by the TestSuiteJob runner).

---

## If you want the FULL stall-and-resume path

The default run only exercises the endpoint-dispatch and error paths (no voice gate timeout, no actual stall). To also exercise the live stall-and-resume:

1. Temporarily set in `src/conf/lupin-app.ini`:
   ```ini
   test fix expediter feedback timeout seconds = 5
   ```

2. Add to **Extra Pytest Args**: `-v --tb=short` (env vars can't be injected via the UI).

3. The `test_live_stall_and_resume` test is still skipped by default (requires `TFE_RESUME_E2E_LIVE=1` env var). To activate it, you'd need to either:
   - Run the shell driver directly: `TFE_RESUME_E2E_LIVE=1 ./src/tests/e2e/run-tfe-resume-e2e.sh --live`
   - Or extend `run-pytest-direct.sh` to accept an env-var passthrough flag (out of scope for this runbook).

For tonight's after-hours run, the endpoint-dispatch validation is sufficient — the full stall-and-resume path is best validated interactively via the UI "Resume from Checkpoint" button when you want to manually trigger it.

---

## Verification after the run

- Check the done queue in the notifications dashboard for a `test_suite` job labeled with `pytest_direct`.
- Grep `/tmp/pytest-direct-*.log` for pass/fail counts.
- `job_history` row will have the pytest summary line in its `response_text` field.

---

## One-line summary

```
Test type: Pytest Direct
File path: src/tests/integration/test_tfe_resume_e2e.py
Schedule: tonight (after-hours)
Exclusive: on (always)
Dry run: off
```
