> Part 5 of 5 of the [Test-Suite Scheduling Guide](../test-suite-scheduling-guide.md): troubleshooting and related docs.

## 10. Troubleshooting

### TestSuiteJob is queued but never runs

**Check 1**: Is there another monopolize job ahead of it? Check the run queue for
anything with `monopolize=true`. If yes, wait for it to finish.

**Check 2**: Is the `scheduled_at` in the future? Jobs wait in the todo queue
until the clock catches up.

**Check 3**: Is the FastAPI server actually running? `curl http://localhost:7999/health`.

### TestSuiteJob crashes at startup

The shell script may be missing or the pytest invocation may fail before running
any tests. Check `/tmp/{suite}-junit-*.xml` for partial output. Check the FastAPI
log for `[TestSuiteJob] Running: bash ...` lines showing the exact command.

Common causes:
- **Script path wrong**: `SUITE_SCRIPTS` dict in `job.py` points at a moved script
- **Permissions**: script not executable (`chmod +x`)
- **Missing dependencies**: pytest plugins uninstalled, Playwright browsers missing

### Remediation snapshot is empty when tests clearly failed

**Check 1**: Is the JUnit XML being produced? `/tmp/{suite}-junit-*.xml` should
exist. If not, `--junit-xml` arg isn't being passed — check `_run_suite()` in
`job.py`.

**Check 2**: Is `_parse_junit_xml()` finding the `<testsuite>` elements?
Malformed XML can cause silent parse failures. Inspect the file manually.

**Check 3**: Is the snapshot being persisted to `artifacts["remediation_snapshot"]`?
Check the job instance after completion: `job.artifacts.get("remediation_snapshot")`.

### Test suites are running but TFE never fires

**Check 1**: `test fix expediter auto fix enabled = true`? And was the
submission's `auto_fix_on_failure` field omitted (or set to `true`)? Passing
`auto_fix_on_failure: false` on the submission disables TFE for that run only,
even when the INI default is `true`.

**Check 2**: Is the snapshot `all_passed = false`? If all tests actually passed,
there's nothing for TFE to fix.

**Check 3**: Are both watchdogs initialized? Look for the unified summary at
server startup: `[Watchdogs] BFE=ENABLED, TFE=ENABLED`. Absent or showing
`DISABLED` → `init_watchdogs()` in `src/cosa/rest/watchdogs.py` wasn't reached
or one of the watchdog constructors raised. Check the FastAPI startup log.

**Check 4**: Is the metadata recursion guard tripped? Check
`completed_job.metadata.get("triggered_by_tfe")` — if set, the watchdog skips.

See also [TFE guide section 8 troubleshooting](../test-fix-expediter-guide/04-troubleshooting-and-code-map.md#8-troubleshooting).

### Overlapping scheduled runs

Two TestSuiteJobs scheduled for 23:00 run **sequentially**, not in parallel. The
second one starts when the first finishes. If both take 30 minutes, the second
finishes around 23:30-0:00.

**Fix**: Stagger your scheduled times. Use `scheduled_at` with explicit timestamps
rather than relative times like "in 2 hours" that might collide.

### Timezone confusion

All times are stored as **ISO datetime strings with explicit timezone offsets**
(e.g., `2026-04-10T23:00:00-04:00`). The `/schedule-tests` skill reads
`app timezone` from `lupin-app.ini` (default `America/New_York`) when parsing
user utterances like "11pm."

If you see jobs running at unexpected times, check:
1. Is `app timezone` set correctly in `lupin-app.ini`?
2. Is your laptop's timezone correct?
3. Did daylight saving time just change? EDT vs `EST` matters.

Report filenames use `EST`/EDT via `ZoneInfo("America/New_York")` with the `%Z`
format specifier, so you can tell the suffix from filenames directly.

### Cancellation hangs

If you click "Cancel" on a running TestSuiteJob and nothing happens for more than
10 seconds, the subprocess may be ignoring SIGTERM. The poll loop in `_run_suite()`
sends `process.terminate()`, waits 10s, then `process.kill()`. If it's stuck,
`ps` for the PID manually and kill it:

```bash
ps -ef | grep run-e2e-ui-tests
kill -9 <pid>
```

The TestSuiteJob will then return a cancelled result dict.

---

## Related Documentation

- **[Test Fix Expediter Guide](../test-fix-expediter-guide.md)** — TFE consumes remediation snapshots produced here
- **[Bug Fix Expediter Guide](../bug-fix-expediter-guide.md)** — BFE handles crashed TestSuiteJobs (dead queue path)
- **[Shared Fix Primitives Reference](../shared-fix-primitives-reference.md)**. Shared expediter machinery
- **[REST API Reference](../../rest-api-reference.md)** — `/api/v2/submit` and the retired-door table
- **`/schedule-tests` skill**: `~/.claude/skills/schedule-tests/SKILL.md`. Voice-driven scheduling
- **`src/tests/AUTH-TESTING-GUIDE.md`** — test credentials + env var setup
- **Live E2E driver**: `src/tests/e2e/run-tfe-live-e2e.sh`. Bash script that exercises TestSuiteJob → TFE end-to-end
- **R&D**: `src/rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md` *(removed; recover: `git show b113a3a7^:src/rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md`)* — original design doc
