> Part 3 of 5 of the [Test-Suite Scheduling Guide](../test-suite-scheduling-guide.md): the REST API for submitting a test suite and the remediation snapshot schema.

## 5. REST API: `/api/v2/submit` (command `agent router go to test suite`)

> **`POST /api/test-suite/submit` was retired to 410 on 2026-09-29**. A test suite is
> submitted through the general v2 door, naming the command. Everything below is that door.

**Endpoint**: `POST /api/v2/submit`

**Auth**: Bearer token via `/auth/login`. Same credentials as any other
authenticated Lupin API.

**Request body**:

```json
{
  "command": "agent router go to test suite",
  "args": {
    "test_types":  "integration,e2e",
    "pytest_args": "-v -k test_auth",
    "dry_run":     false
  },
  "scheduled_at": "2026-04-10T23:00:00-04:00"
}
```

`cosa.agents.test_suite.v2_client.submit_body( … )` builds this; `src/scripts/submit-test-suite.py` is the
command-line wrapper. The suite arguments go in `args`; `scheduled_at` and `websocket_id` are directives
to the queue and stay top-level.

The wrapper's `--env KEY=VALUE` (repeatable) fills `args.env_vars`, which reach that run's pytest
process only. The suite job keeps only names that start with `TFE_`, `BFE_` or `LUPIN_TEST_`. The
wrapper asks the job's own filter and refuses any other name before it logs in.

**The live eval test has two sizes**. Inside the integration suite `test_v2_eval_live.py` runs a
short proxy, 5 utterances per command (50 asks), ruled by Rick on 2026-10-05. The
full sample is a separate scheduled run in the 10 am to 1 PM window:

```bash
src/scripts/submit-test-suite.py --test-types integration \
  --env LUPIN_TEST_V2_EVAL_LIMIT=20 \
  --env LUPIN_TEST_INTEGRATION_FILE_TIMEOUT_MINUTES=40 \
  --scheduled-at 2026-10-06T11:00:00-04:00
```

At 20 per command the file makes 200 asks. On 2026-10-05 it was measured at about 7.4 seconds per
ask and was stopped by the default 15-minute per-file cap. Which is why the run raises the cap.

| Field | Where | Type | Default | Purpose |
|-------|-------|------|---------|---------|
| `test_types` | `args` | string, comma-separated | `"integration,e2e"` | Suite types to run. See [Section 2](01-what-it-does-and-suite-types.md#2-supported-suite-types). **An unregistered name is refused at submit**, naming it and the valid list — `e2e_ui` is the tests' directory, not a suite. Use `e2e_a`, `e2e_b` or `e2e`. |
| `pytest_args` | `args` | string, shell-style (shlex) parsed | none | Extra pytest args passed through to the script. Unbalanced quotes are refused at submit. `--bg` flag is stripped (harmful for subprocess runs). |
| `dry_run` | `args` | bool | `false` | Skips the pytest subprocess. But still queues a real job and takes the monopolize slot for a few seconds. |
| `auto_fix_on_failure` | `args` | bool | none | Per-run override for TFE auto-dispatch; omitted uses the INI default. |
| `env_vars` | `args` | object of strings | none | Extra env vars for the pytest subprocess, filtered by prefix allowlist (`TFE_`, `BFE_`, `LUPIN_TEST_`). `LUPIN_TEST_MONOPOLIZE_PARENT_TOKEN` is reserved to the runner and dropped from a request. |
| `scheduled_at` | top-level | ISO datetime string | none (run immediately) | When to run the job. Past times run immediately. Honors project timezone. |
| `websocket_id` | top-level | string | none | WebSocket session ID for notifications. |
| `parent_id_hash` | top-level | string | none | A monopolizing sweep's id, so Gate B admits its child through the hold. |

Warning: **There is no `monopolize` request field**. The job forces monopolize on in its own constructor.

**The per-run lineage token**. Where `v2 parent stamp token enabled = true` (Development and Testing only), a real sweep issues one secret for its run. It exports the secret to every suite subprocess as `LUPIN_TEST_MONOPOLIZE_PARENT_TOKEN`, beside `LUPIN_TEST_MONOPOLIZE_PARENT_ID`. A test that registers a fresh user sends the id as `parent_id_hash`. It sends the token in the `X-Lupin-Lineage-Token` header (`tests/helpers/suite_lineage.py` does both). The server honours the claim while that run holds the monopoly slot and until the token expires. The expiry is the sum of the sweep's suite budgets plus ten minutes. The sweep revokes the token on every exit. A refused token drops the stamp and names its reason in the trace field `parent_id_hash_dropped`. The exception is a claimed id that is the sweep now holding the monopoly slot. There the door answers 403 with the reason in the body. A child that lost its token therefore fails at once and does not queue behind its own sweep. Any process the suite starts can read the token.

**Response** (a v2 `AskResponse`, the fields that matter):

```json
{
  "path":           "agent",
  "status":         "waiting",
  "job_id":         "ts-abc12345",
  "queue_position": 1
}
```

`queue_position` is the todo queue's size right after the push (the number the retired door returned). It is `null` when nothing was queued.

**A refused submit is HTTP 200, not 400.** Three causes come back with
`status: "failed"` and the cause in `error`. They are an unknown suite name,
malformed `pytest_args`, and a per-test `--timeout` that contradicts the suite budget. Nothing is queued. A caller must check `status`
(`read_reply()` in `v2_client` does), not only the HTTP code.

**Polling**: Use `GET /api/get-queue/{queue}` where `queue ∈ {todo, run, done, dead}`
to find your job. Or watch the Activity Log in the web UI for real-time updates.

**Full endpoint schema**: available via the interactive Swagger UI at `/docs` on
the running server (`AskResponse` and `SubmitRequest`).

### Direct invocation via `/api/push`

The TestSuiteJob can also be submitted via the generic agentic job submission
endpoint:

```bash
curl -X POST http://localhost:7999/api/push \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "agent router go to test suite",
    "args": {
      "test_types": "all",
      "dry_run": "false"
    }
  }'
```

This is what the live E2E driver at `src/tests/e2e/run-tfe-live-e2e.sh` uses to
bootstrap its test runs.

---

## 6. Remediation Snapshot Schema (v1.0)

When a `TestSuiteJob` completes with any failures, it writes a structured JSON
artifact that describes every failure. This artifact is what TFE consumes.

**File location**: `io/test-suite/YYYY.MM.DD-at-HH:MM-TZ-{suites}-remediation.json`

**Schema**:

```json
{
  "schema_version": "1.0",
  "timestamp":      "2026.04.10-at-14:53-EDT",
  "suites_run":     ["integration", "e2e"],
  "summary": {
    "total_passed":   523,
    "total_failed":   12,
    "total_skipped":  3,
    "total_errors":   0,
    "all_passed":     false
  },
  "failures": [
    {
      "classname": "src.tests.e2e_ui.test_visual_regression.TestVisualRegression",
      "name":      "test_visual_page[login]",
      "type":      "FAILED",
      "message":   "Snapshots DO NOT match: login.png",
      "traceback": "File \"src/tests/e2e_ui/test_visual_regression.py\", line 42, in test_visual_page\n    ...",
      "suite":     "e2e"
    },
    ...
  ]
}
```

### Field reference

| Field | Type | Purpose |
|-------|------|---------|
| `schema_version` | string | Always `"1.0"`. TFE's snapshot loader checks this — other versions are rejected. |
| `timestamp` | string | When the run started (filename-safe format). |
| `suites_run` | list[string] | Suite types actually executed. Usually matches the `test_types` input but may differ if some were skipped. |
| `summary.total_passed` | int | Total passing tests across all suites. |
| `summary.total_failed` | int | Total failed tests across all suites. |
| `summary.total_skipped` | int | Total skipped tests. |
| `summary.total_errors` | int | Errors (fixture failures, collection errors) — distinct from failed. |
| `summary.all_passed` | bool | `true` iff failed+errors == 0. TFE's watchdog only fires when this is `false`. |
| `failures` | list[dict] | One entry per failing test. Empty list when `all_passed=true`. |
| `failures[].classname` | string | Dotted Python path to the test class (or module for free functions). |
| `failures[].name` | string | Test function name, including `[param]` suffix for parametrized tests. |
| `failures[].type` | string | `"FAILED"` (assertion) or `"ERROR"` (fixture/setup/collection). |
| `failures[].message` | string | Pytest failure message (first line of the traceback). |
| `failures[].traceback` | string | Full Python traceback as emitted by pytest. |
| `failures[].suite` | string | Which of `suites_run` this failure came from. |

### Producer

The snapshot is built by `TestSuiteJob._execute()` after all suites have finished.
The JUnit XML emitted by pytest (via `--junit-xml=/tmp/{suite}-junit-{timestamp}.xml`)
is parsed by `_parse_junit_xml()` into per-suite result dicts, then aggregated into
the top-level snapshot structure.

### Consumer

The `TestSuiteCompletionWatchdog` reads the snapshot from `job.artifacts["remediation_snapshot"]`
immediately after the TestSuiteJob is pushed to the done queue. If the snapshot is
valid and `all_passed=false`, it dispatches a TFE job with a pointer to the
snapshot file path.

TFE's `snapshot_loader.load_from_artifacts()` then re-reads the snapshot, validates
the schema version, strips PII from tracebacks, and builds a `TestRemediationContext`
that the cluster phase consumes. See the [TFE guide cluster section](../test-fix-expediter-guide.md#phase-0-cluster).

---
