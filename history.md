# Lupin Project History

### 2026.04.16 - Session eb50bd56 | CJ Flow Delete All buttons (5 panes) + history archive

- 🗑️ Delete All button added to each of the 5 CJ flow pane headers (todo/run/done/dead/history). Non-admins delete own jobs only; admins clear entire queue. History pane respects the active time-window filter.
- **Backend** (CoSA — user commits from inside `src/cosa/`): `DELETE /api/queue/{name}/all` + `DELETE /api/job-history/all?days=N` + `delete_job_history_bulk()` in `job_persistence.py` + `queues.py`.
- **Frontend** (Lupin): `notifications.html` (5 buttons w/ data-testid), `notifications.js` (`deleteAllQueueJobs()` method), `notifications.css` (`.queue-delete-all-btn` ghost style, red tint).
- PQW HTTP 500 env-var bug filed in `bug-fix-queue.md` (Queued).
- **Plan**: serialized to `src/rnd/v0.1.6/2026.04.16-cj-flow-delete-all-buttons.md`
- **Commit**: 29a6fd4
- **History archive**: `history.md` was at 38,821 tokens (155% of 25k limit). Archived 23 sessions (2026-04-08 to 2026-04-14) to `history/2026-04-08-to-14-history.md`. Retained 4 recent sessions (10,008 tokens). **Commit**: 2879cbf
- **PQW HTTP 500 fix**: `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD` were missing from the running `lupin-rest-dev` container (container predated the env var additions to docker-compose.yml). Fix: `docker rm -f lupin-rest-dev && docker compose up -d lupin-rest-dev`. Env vars confirmed injected; watcher confirmed running. No code changes — deployment-only fix.

---

### 2026.04.15 - Session f01fdc2f | SDK creds mount + 11 TFE/BFE observability + lifecycle fixes

**Context**: Started with operator locked out of test server (401s, companions wiped from `lupin_db_test` by E2E UI suite teardown). Morning fix cascaded into a full audit of why last night's scheduled `ts-d2d890ed` TFE auto-dispatch produced "8 clusters, 0 proposed, 0 fixed" — SDK credentials weren't mounted in test container, voice gate fired at wrong priority, stalled rows mis-persisted as failed, resume re-ran Phase 0/1 unnecessarily. Ten bugs fixed + a tonight-run scheduled.

**Root cause #1 — SDK auth**: `~/.claude/.credentials.json` mount missing from `lupin-rest-test` compose service; `claude-agent-sdk` CLI returned `"Not logged in · Please run /login"` for every Phase 1 delegation → 0 diagnoses → Phase 2 skip at `orchestrator.py:628` → 0 proposals. Fix: add compose volume mount; re-probe shows live SDK response. Validated end-to-end by replaying `io/test-suite/2026.04.15-at-00:56-EDT-all-remediation.json`: 19 proposals generated (tfe-225d4df2 / tfe-e115ec67 / tfe-152111fe).

**Root cause #2 — voice gate silence**: dispatcher hardcoded `priority="medium"`; `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE=3` left as test-container env; operator email (ricardo) wasn't the job target (interactive.job.tester was). Three separate fixes.

**Bugs landed** (Lupin parent):
- **Bug 1** (`src/cosa/rest/routers/io_files.py`): strip relative `io/` prefix so report links resolve.
- **Bug 2** (`src/fastapi_app/static/js/notifications.js`): Done/History job-card duplication — `refreshAllQueueLists` now awaits live-queue fetches before history so `exclude_ids` is populated.
- **Bug 4** (`docker-compose.yml`): remove `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE:"3"` from `lupin-rest-test` env. Also add `~/.claude/.credentials.json` mount.
- **Bug 8** UI labels (`notifications.js`): badge differentiation via `stall_reason` — `⏸ Stalled` vs `⏸ Paused` vs `✕ Stopped`.
- **Bug 10** INI + splainer (`src/conf/lupin-app*.ini`): `voice gate operator email` + `voice gate service accounts` — dispatcher swaps target_user for service accounts so TTS reaches a real human.
- **Test-harness hardening** (`src/tests/e2e_ui/conftest.py`, `src/scripts/seed_test_companions.py`): post-suite companion reseed fixture; seed script fails loud when primary admin missing from `lupin_db_dev`.

**Bugs landed** (CoSA submodule — uncommitted, user to land from inside CoSA):
- Bug 3: dispatcher `priority="high"` default + `priority` param on ask_confirmation/get_feedback/present_choices.
- Bug 5: rewrite stale TFE orchestrator phase-status docstring (Phases 2/3/5/6 are REAL, not stubs).
- Bug 6: resume phase-skip guards at phase 0/1/2 entries — `_resume_from_ordinal` honored.
- Bug 7: dispatcher normalizes empty answers to `VoiceGateTimeoutError` (not silent empty selection).
- Bug 10 dispatcher: `_resolve_routing()` helper + `_prepend_operator_routing()` abstract prefix + `response_default` param on 3 blocking methods + BFE `cosa_interface` wrapper pass-through.
- Bug 11: `JobState.STALLED` → `persist_job_stalled_from_metadata` via `queue_util` route; `running_fifo_queue` recognizes STALLED as a first-class terminal (pushes to Done, not Dead, skips auto-fix watchdog).
- Resume factory fix: `resume_job()` dropped invalid `config_mgr` kwarg that was crashing `create_agentic_job`.

**Plan artifacts** (`src/rnd/v0.1.6/`):
- `2026.04.10-test-fix-expediter/18-post-tfe-validation-cleanup.md` (10-step plan doc; 18 in the TFE numbered series) + index updated.
- `2026.04.15-tfe-empty-clusters-and-bfe-dead-job-race.md` (earlier draft superseded by 18-).

**Validated end-to-end**:
- tfe-225d4df2 (dry_run=true, 1st resume): Phase 0+1 skipped ✓, voice gate auto-bypassed by dry_run ✓, status=completed with 2/2/2 dry synthetic successes.
- tfe-e115ec67 (dry_run=false, pre-op-routing): voice gate fired but MCP 503 (interactive.job.tester offline) → exposed Bug 10 + Bug 11.
- tfe-152111fe (post-op-routing): request correctly targets `ricardo.felipe.ruiz@gmail.com` → MCP 200 + `[NOTIFY-QUEUE] Notification queued` → TTS spoken → 5-min timeout → `status=stalled`, checkpoint intact, no error, re-resumable.

**Tonight** (scheduled before session-end at 19:27 EDT): `ts-79829a75` @ 19:30 EDT, `test_types=all`, `auto_fix_on_failure=true`, cheap-tier TFE via temporary `[Lupin: Testing]` INI override (`test fix expediter lead model = claude-sonnet-4-6`). TFE will auto-dispatch on failures; voice gate routes to ricardo via Bug 10; if unanswered, stalls cleanly per Bug 11 for morning resume per Bug 6.

**Deferred** (picked up next session):
- Bug 8b (wire Pause/Stop buttons end-to-end).
- Bug 9 (TFE/BFE Phase 3/5 in git worktree for isolation).
- `feedback_timeout_action` knob (stall/skip/auto_select_high_confidence).
- D1 BFE dead-job race (eager snapshot + packager fallback).
- D2 full TFE live attended (Phase 3/5/6 real commits + PR).
- D3 pre-merge E2E gate.

**Files touched this session** (Lupin parent, 8 modified + 3 new):
- `docker-compose.yml`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/fastapi_app/static/js/notifications.js`, `src/scripts/seed_test_companions.py`, `src/tests/e2e_ui/conftest.py`, `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md`, `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/18-post-tfe-validation-cleanup.md` (new), `src/rnd/v0.1.6/2026.04.15-tfe-empty-clusters-and-bfe-dead-job-race.md` (new).
- **Not mine**: `src/tests/e2e_ui/test_job_history_ui.py`, `src/rnd/v0.1.6/2026.04.15-done-card-toggle-id-collision.md` (parallel session artifact).

**⚠️ Follow-up for next session**:
1. Archive history.md — this entry pushed us past 25k token limit (was 95.3% before write).
2. Morning: check tonight's `ts-79829a75` outcome; resume `tfe-*` stalled row via UI Resume button; answer voice gate → validate Phase 3/5/6.
3. Revert `[Lupin: Testing]` cheap-tier INI override once overnight run completes (or keep if desired).
4. Land the 9 CoSA-side changes from inside the CoSA repo.

---

### 2026.04.14 - Session 6ae2513c | TFE Resume E2E live path + env-vars API + test-suite scheduling

**Context**: Two scheduled TFE Resume E2E runs (21:00 + 21:39 EDT) had silently failed with `ConnectionError`. Root cause: scheduled pytest subprocesses executed inside `lupin-rest-test` where the server lives on internal port 7999, but `conftest.py` (via caller-set env var with `:8000` default) was hitting the host-side mapping. Secondary: `test_live_stall_and_resume` was a `pytest.skip()` placeholder with no body; needed real stall/resume plumbing; and no way to pass env vars through the test-suite scheduling API.

**Phase 1 — Unblock scheduled runs**:
- `src/cosa/agents/test_suite/job.py`: subprocess env now sets `LUPIN_TEST_BASE_URL=http://localhost:$PORT` (defaults 7999) so container-side pytest reaches the server. Caller-set value wins.
- `src/tests/integration/test_tfe_resume_e2e.py`: added `test_resume_from_checkpoint_happy_path_if_available` — queries `/api/job-history?status=stalled`, exercises resume endpoint if a stalled TFE job exists, skips cleanly otherwise.
- Host-side verified: `9 passed, 2 skipped` in 0.38s (was `9 errors`).

**Phase 2 — Real live stall-and-resume body**:
- `src/cosa/agents/test_fix_expediter/config.py`: `from_config()` now honors `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE` env var, overriding the INI value for `feedback_timeout_seconds`. Round-trip verified (300 → 3).
- `src/tests/integration/test_tfe_resume_e2e.py`: replaced `pytest.skip()` placeholder with real body — `_poll_job_state` helper, submits TFE job via `/api/agentic-jobs/submit`, polls for STALLED, calls `/api/jobs/{id}/resume-from-checkpoint`, asserts response shape. Gated by `TFE_RESUME_E2E_LIVE=1` + `TFE_REMEDIATION_SNAPSHOT_FIXTURE=<path>`.
- `src/tests/e2e/run-tfe-resume-e2e.sh`: `--live` mode exports the timeout override + warns if fixture missing.

**env_vars plumbing end-to-end (Lupin + CoSA)**:
- `src/cosa/rest/routers/test_suite.py`: `TestSuiteSubmitRequest` gains optional `env_vars: Dict[str, str]` field with prefix-allowlist description.
- `src/cosa/rest/agentic_job_factory.py`: threads `env_vars` into `TestSuiteJob` constructor.
- `src/cosa/agents/test_suite/job.py`: new constructor arg + `_filter_env_vars` classmethod (prefix allowlist: `TFE_`, `BFE_`, `LUPIN_TEST_`). Accepted vars merge into subprocess env, overriding defaults. Disallowed keys dropped with warning.

**Other**:
- `docker-compose.yml`: commented out crash-looping `lupin-pgadmin` service (`PGADMIN_DEFAULT_EMAIL=dev@lupin.local` rejected by deliverability validator); added `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE=3` to `lupin-rest-test` env block. Container bounced clean at 23:11 EDT.
- TODO.md item #2 stale "NOT COMMITTED" note replaced with commit hash `309f98c`. Triage doc `2026.04.13-session-triage-and-option-c-docker-non-root.md` marked ✅ completed.
- Deleted stale `src/conf/long-term-memory/lupin.lancedb.backup-2026-01-22/` directory (user-run sudo).

**Planning docs (new)**:
- `src/rnd/v0.1.6/2026.04.14-tfe-resume-e2e-live-implementation.md` (design)
- `src/rnd/v0.1.6/2026.04.14-tfe-resume-e2e-live-execution-log.md` (paired execution log)
- `io/test-suite/fixtures/tfe/sample-remediation-snapshot.json` (synthetic 1-failure fixture for live path)

**Scheduled at session-end (23:12 EDT)**:
- `ts-1139f28d` @ 23:15 — TFE dry run (expect `9 passed, 2 skipped`)
- `ts-996dafbc` @ 23:20 — TFE live run (env_vars with `TFE_RESUME_E2E_LIVE=1` + fixture path)
- `ts-d2d890ed` @ 23:25 — full `all` suite (60-min pyramid)

**Verified end-to-end**: py_compile on all touched files, shell syntax, YAML parse, Pydantic round-trip (`env_vars` payload), snapshot_loader.load_from_path round-trip, allowlist filter drops non-prefix keys.

---

### 2026.04.14 - Session 5a620729 | Test server force-refresh + peer queue watch + bug-fix mode bug #1 closed

#### Checkpoint 5 | 2026.04.14 23:00 EDT | Session-end — Bug #1 live-validated; NEW /api/push-agentic endpoint unblocks harness

**Context**: After CP4 shipped the BFE/TFE interactions + reports code fix, live validation via the E2E scripts revealed two pre-existing harness gaps (missing `websocket_id` on TFE, missing BFE fixture) and — deeper — the `/api/push` endpoint now routes unregistered commands through the runtime-argument-expeditor which asks for missing args via interactive notification and cancels on timeout. Unattended harness scripts can't respond, so submissions were silently cancelled before reaching the queue. Rather than retrofit `/api/push`, user proposed the cleaner architecture: a new dedicated endpoint for unattended agentic submission. Built it, scripts work end-to-end, live pipeline validated.

**New endpoint** (CoSA submodule, not committed from Lupin):
- `POST /api/push-agentic` in `src/cosa/rest/routers/queues.py` — accepts explicit `routing_command` + `args` dict + `websocket_id`. Validates required fields; passes args dict unchanged to the agent factory. No voice-path LORA parsing, no interactive Q&A. Auth identical to `/api/push`. On success returns `{ status, routing_command, websocket_id, user_id, job_id, result }`. On unknown command or construction failure returns 400 with the factory's error message.
- `push_job_agentic()` method on `TodoFifoQueue` (`src/cosa/rest/todo_fifo_queue.py`) — mirrors the non-expeditor parts of `_handle_agentic_command`: emits speculative `pending→todo` WebSocket transition with expediting=False, injects `no_confirm=true` into args, calls `create_agentic_job()` factory, overrides the job's id_hash with the speculative ID so the UI card matches, applies `scheduled_at` / `monopolize`, pushes to queue, emits "gentle-gong" for new-job UX parity.

**Lupin-side harness patches**:
- `src/tests/e2e/run-tfe-live-e2e.sh`: SUBMIT_PAYLOAD now uses `routing_command` + `websocket_id` + `question` keys, POSTs to `/api/push-agentic`.
- `src/tests/e2e/run-bfe-live-e2e.sh`: POSTs to `/api/push-agentic` (fixture file holds the full payload).
- `src/tests/fixtures/bfe/snapshot_known_bad.json` (NEW) — deep_research dry-run with `force_failure_mode=code_bug`, matching `/api/push-agentic` shape. Triggers deterministic `KeyError('source_path')` → dead queue → DeadQueueWatchdog classifies as CODE_BUG → dispatches BFE.
- `src/tests/unit/test_report_writer.py`: +2 tests for slug-sanitizer underscore-to-hyphen normalization (surfaced from user's feedback on `deadjobnotfounddryrun` run-on in CP4's first BFE report filename).

**Cosmetic slug fix** (CoSA): `src/cosa/agents/shared/report_writer.py` `_sanitize_slug()` now normalizes underscores to hyphens before applying the `[^a-z0-9\s-]` whitelist. Status tokens like `dead_job_not_found_dry_run` render as `dead-job-not-found-dry-run` in filenames.

**User corrections captured during the session**:
1. mock_token_email_* is legacy, not canonical (CP2) — saved to auto-memory.
2. Bounce reseeding fix — 401s during CP4 weren't a transient race; mistaken env-var assumption in reseed. User patched.
3. TFE failure-path report gap — CP4 initially wrote reports on happy + stall only; missed generic exception handler in `do_all()`. Fixed in same CP4 commit.
4. voice_io decoupling education — explained that voice is one WebSocket subscriber downstream of dispatch, not an upstream gate; persistence + UI render always happen; TTS decision belongs at the voice-bridge subscriber.
5. Endpoint scope refactor — when naive INI-key rename proved insufficient (args dict discarded before reaching push_job), user proposed cleaner architecture: leave `/api/push` alone, build `/api/push-agentic` as separate unattended path. Implemented.

**Live validation** (curl-driven):
```
dr-eb1b680e (deep_research, dry-run, force_failure_mode=code_bug)
  → run queue → KeyError raised → dead queue ✓
  → DeadQueueWatchdog classified CODE_BUG → dispatched BFE ✓
  → bfe-f91fd115 now in run queue → notify breadcrumbs flowing ✓
```
15 notification rows in `lupin_db_test.notifications` with correct compound `job_id` + matching `sender_id`. **RC-1 voice_io fix validated in the wild.**

**Bug-fix mode closed**: `bug-fix-queue.md` — bug #1 moved to Completed with full summary; session `5a620729` marked `closed` in Active Sessions table.

**Files changed this checkpoint (7 Lupin-side; 3 CoSA-side uncommitted)**:
- `.claude-session.md` — CP5 section
- `bug-fix-queue.md` — bug #1 → Completed; session closed
- `TODO.md` — added 5 completed items for this session, bumped "Last updated"
- `history.md` — this entry
- `src/tests/e2e/run-bfe-live-e2e.sh` (patched endpoint)
- `src/tests/e2e/run-tfe-live-e2e.sh` (patched endpoint + websocket_id)
- `src/tests/fixtures/bfe/snapshot_known_bad.json` (new, /api/push-agentic shape)
- `src/tests/unit/test_report_writer.py` (+2 slug tests, 14 tests total now pass)
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/queues.py` (~100 lines new endpoint), `src/cosa/rest/todo_fifo_queue.py` (~95 lines push_job_agentic), `src/cosa/agents/shared/report_writer.py` (4 lines slug normalization)

**Deferred (carried to next session)**:
- **Archive history.md** — 22.4k tokens / 89.5% at session-end (critical). Most of it is this session's 5 checkpoints. First action next session.
- Unit test for `/api/push-agentic` endpoint — covered by happy-path live validation; formal pytest deferred.
- Clean full-script run of both E2E scripts end-to-end — live chain validated via direct curl; script-level polling/validation logic not yet exercised. Expected to work based on submit success.

---

#### Bug Fix Mode | 2026.04.14 14:35 EDT | Session entered bug-fix mode

User invoked `/plan-bug-fix-mode-start`. Active work: Bug #1 — BFE/TFE job cards show "No interactions recorded" and have no results-document link. Plan serialized to `src/rnd/v0.1.6/2026.04.14-bfe-tfe-interactions-and-reports.md`. Investigation phase first (Postgres query against test DB `notifications` table to pinpoint RC-1 break point) before writing any fix code. RC-2 (missing final-report generator for BFE and TFE) is orthogonal and independent of the investigation outcome.

#### Checkpoint 4 | 2026.04.14 19:30 EDT | Bug #1 code complete — RC-1 voice_io decoupling + RC-2 ReportWriter

**Investigation findings** (SQL against `lupin_db_test.notifications`):
- Test DB `notifications` table: **0 rows ever**. Entire pipeline silently dropping on test server.
- Dev DB healthy: 20+ BFE rows from Apr 10 with correct compound `job_id` (`bfe-XXX::userid`) and `sender_id` — proving code works when env is clean.
- Direct `curl POST /api/notify` with `X-API-Key` to `:8000` → persists correctly. Endpoint healthy.
- User's failing BFE job `bfe-79df11f2::...`: ran 1.04s, hit "dead job not found" dry-run branch, should have emitted ≥1 notification. Zero persisted.
- Card `has_interactions: true` is misleading — derived from `bool(session_id)`, not actual DB rows.

**RC-1 root cause** (`src/cosa/agents/utils/voice_io.py:296`): the notify() gate conflated *voice availability* with *persistence dispatch*:
```python
if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
    print( f"  {message}" ); return   # skips dispatcher → skips DB → skips WebSocket → skips UI
```
`is_voice_available()` itself calls `_cosa_interface.notify_progress()` as a probe and caches the result. One probe failure for any reason locks `_voice_available = False` for the process lifetime — every subsequent notify becomes a bare `print()`. That was the full explanation for the empty test DB.

**RC-1 fix**: removed the `is_voice_available()` clause from `notify()`'s gate. Two legitimate CLI modes preserved: `_cosa_interface is None` (standalone/tests/pre-configure race) and `_force_cli_mode` (explicit `set_cli_mode(True)` opt-out). Rationale documented: TTS is one subscriber downstream of the WebSocket fanout; gating *dispatch* on *voice availability* was a layering error. The TTS decision belongs at the voice-bridge subscriber.

**RC-2 fix**: no final report existed for BFE or TFE — only intermediate plans via PlanWriter. Surface infrastructure (`renderReportLinkSection()` in notifications.js, `artifacts["report_path"]` extraction in `queues.py:348-352`) was already in place but unused.
- NEW `src/cosa/agents/shared/report_writer.py` — agent-agnostic markdown writer. Path: `{project_root}/io/swe-team/reports/{email}/YYYY.MM.DD-at-HH:MM-EST-{slug}-{agent}-report.md`. America/New_York zoneinfo handles EST/EDT automatically; `EST` in the filename is a fixed token per the project filename convention.
- `src/cosa/agents/bug_fix_expediter/job.py` — added `_write_final_report()` with full artifact serialization (dead_job_context, diagnosis, proposed_fixes, selected_fix, fix_result, resubmitted_job_id, stall checkpoint, failure traceback). Wired into **five** terminal exits: dry-run dead-job-not-found, live dead-job-not-found, happy path, stall, and `do_all()` generic exception handler.
- `src/cosa/agents/test_fix_expediter/job.py` — same pattern, TFE-specific artifacts (source_test_suite_job_id, cluster_count, fix_count, validation_run_job_id, orchestrator.clusters + proposed_fixes). Wired into **three** exits: happy, stall, generic exception.
- Both helpers populate `self.artifacts["report_path"]` → UI `renderReportLinkSection()` fires → "📋 View Full Report" link opens at `/app/docs?path=...`.

**User correction #1**: early Explore agent asserted `mock_token_email_*` was canonical. Wrong. `src/cosa/rest/auth.py:80-125` dispatches on `auth mode=jwt` (from `lupin-app.ini:497` in `[Lupin: Baseline]`, inherited by every configured env). Mock tokens are legacy dev-mode only. Canonical paths are JWT from `/auth/login` or global `X-API-Key`. Saved as `feedback_mock_tokens_are_legacy.md`.

**User correction #2**: TFE/BFE did not write a final report on generic failure — only happy path and stall. Fixed in this checkpoint by adding a `status="failed"` report-write in both `do_all()` exception handlers. Reports stash `failure_message` + `failure_traceback` (first 4000 chars) in artifacts and render a `## Failure` section. Failure is the case where the report matters *most*; gap closed.

**Tests (new, all passing)**:
- `src/tests/unit/test_report_writer.py` (12 tests): slug sanitization boundary cases, path shape (regex match on full filename), content assertions (title + agent + body), empty-body placeholder, email partitioning, agent suffix.
- `src/tests/unit/test_voice_io_notify_decoupling.py` (6 regression tests): dispatches when configured, prints when cosa_interface None, respects `_force_cli_mode`, falls back on dispatcher raise, **does not invoke `is_voice_available()` probe** (explicit — pins the bad gate stays removed), dispatches even when `_voice_available = False` is cached.
- **Totals**: 30 of 30 passing across `test_report_writer.py` (12) + `test_voice_io_notify_decoupling.py` (6) + `test_peer_proxy.py` (12 unchanged from CP2/CP3).

**Files changed this checkpoint (6 Lupin-side; 4 CoSA-side uncommitted)**:
- `.claude-session.md` — CP4 manifest section
- `bug-fix-queue.md` — session registered + bug #1 claimed
- `history.md` — this entry
- `src/rnd/v0.1.6/2026.04.14-bfe-tfe-interactions-and-reports.md` (new — serialized plan)
- `src/tests/unit/test_report_writer.py` (new — 12 tests)
- `src/tests/unit/test_voice_io_notify_decoupling.py` (new — 6 regression tests)
- **Uncommitted, CoSA submodule** (user commits separately per nested-repo rules): `src/cosa/agents/utils/voice_io.py`, `src/cosa/agents/shared/report_writer.py` (new, ~160 lines), `src/cosa/agents/bug_fix_expediter/job.py` (+130 lines), `src/cosa/agents/test_fix_expediter/job.py` (+105 lines)

**Next**: User restarts test server, dispatches a fresh BFE run (likely another dead-job-not-found dry run to match original scenario), and checks the card:
1. Notification Conversation should show the notify breadcrumbs from the run (RC-1 validated).
2. "📋 View Full Report" link renders on the done card → opens populated markdown report (RC-2 validated).

If both surface: bug #1 passes live verification, ready for /plan-bug-fix-mode-wrap.

---

#### Checkpoint 3 | 2026.04.14 14:05 EDT | Peer Queue Watch live — three bug fixes + root-cause discovery

**Context**: User tested the freshly-shipped Peer Queue Watch UI and hit three issues in sequence, each peeling back a layer. Fix-as-you-go session resulting in a working end-to-end drain-notification pipeline AND a bonus fix for the user's pre-existing test-UI admin lockout.

**Bug 1 — empty host combo box**:
- **Symptom**: "Peer host field isn't editable and isn't populated with any pre-slug addresses."
- **Root cause**: `peer-queue-watch.js` guarded `DOMContentLoaded` init with `if ( !( await requireAdmin() ) ) return;` — but `auth.js:517-525`'s `requireAdmin()` has no explicit `return` (returns `undefined`), so `!undefined === true` short-circuited every init and `populateHostSelector()` never ran.
- **Fix**: populate UI and wire buttons FIRST, then `await requireAdmin()` inside a try/catch (auth.js handles redirect on failure). Hard-reload picks up new JS immediately.

**Bug 2 — upstream connection refused**:
- **Symptom**: `ClientConnectorError: Cannot connect to host localhost:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`.
- **Root cause**: proxy runs INSIDE the `lupin-rest-dev` container where `localhost:8000` is the container itself, not the host's mapped port. Peer containers on the docker-compose network are reachable by service name + the in-container port `7999`.
- **Verified**: `docker exec lupin-rest-dev curl -fsS http://lupin-rest-test:7999/health` → 200.
- **Fix**: whitelist in `lupin-app.ini` changed from `localhost:8000,localhost:7999` → `lupin-rest-test:7999,lupin-rest-dev:7999`. JS `ALLOWED_HOSTS` restructured as `[{value, label}]` so the dropdown shows friendly labels ("lupin-rest-test:7999 (test server, host :8000)") while the `<option>` value is the canonical container hostname. Splainer updated. Added container-network clarification to `peer.py` module docstring (side effect: forces uvicorn --reload since INI files alone aren't watched).

**Bug 3 — 401 "User not found"**:
- **Symptom**: `HTTP 502: upstream http://lupin-rest-test:7999/api/get-queue/run returned 401: {"detail":"User not found"}`.
- **Investigation**: `verify_jwt_token` (`src/cosa/rest/auth.py:128-204`) decodes+validates the JWT signature (shared secret works → "`lupin-rest-test` accepted the token as genuine"), then calls `get_user_by_id(payload["sub"])`. Dev and test use SEPARATE PostgreSQL databases (`lupin_db_dev` vs `lupin_db_test`) — so the dev user's UUID doesn't exist in the test DB → 401. **JWT pass-through (plan's Option A) was fundamentally broken** — shared signing secret is necessary but not sufficient; shared user store is also required.
- **Pivot to Option B (service-account login)**: dev backend POSTs to test-server `/auth/login` with `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL`/`_PASSWORD` env vars (already set in dev container, confirmed via `docker exec lupin-rest-dev env`). Cache JWT per-host with 25min expiry (Lupin tokens are 30min). On upstream 401, invalidate cache and retry once.
- **Implementation** in `src/cosa/rest/routers/peer.py` (CoSA submodule — uncommitted):
  - NEW `_peer_jwt_cache: Dict[host, {token, expires_at}]`.
  - NEW helpers `_login_to_peer(session, host)`, `_get_peer_jwt(session, host)`, `_invalidate_peer_jwt(host)`.
  - `_fetch_queue` no longer accepts an `authorization` param — acquires its own token via `_get_peer_jwt`. On 401 retries once after cache invalidation.
  - Removed `Header` import; removed `authorization` parameter from `get_peer_queue`, `start_watcher`, and `_watcher_loop` signatures.
  - Module docstring updated to document the Option A → Option B pivot and why.

**Service-account login itself initially failed with 401 "Invalid email or password"**, revealing the real root cause:
- **Test DB was missing every seeded user**. Query: `SELECT email FROM users WHERE email = 'interactive.job.tester@lupin.deepily.ai'` → empty in `lupin_db_test`, present in `lupin_db_dev`. `src/scripts/seed_test_companions.py` is SUPPOSED to copy the companion rows at test-container startup, but clearly hadn't run successfully against the current test DB (either recent DB wipe without a container restart, or a silent failure on last startup).
- **Manually ran** `docker exec lupin-rest-test python3 /var/lupin/src/scripts/seed_test_companions.py` → 5 users seeded: `ricardo.felipe.ruiz@gmail.com` (admin+user), `admin@lupin.deepily.ai` (admin+user), `claude.code@deepily.ai` (service_account), `interactive.job.tester@lupin.deepily.ai` (user), `mock.job.tester@lupin.deepily.ai` (user). Plus 1 API key row.
- **Bonus win — test-UI admin lockout ALSO resolved** (the item flagged as out-of-scope back at session start). User was never actually "locked out" in the sense of role/permission — their user row simply didn't exist in the test DB. With the row now present, normal admin credentials log in on :8000.

**End-to-end verification from dev container**:
```
docker exec lupin-rest-dev bash -c 'TOKEN=$(curl -sS -X POST http://lupin-rest-test:7999/auth/login
  -H "Content-Type: application/json"
  -d "{\"email\":\"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL\",\"password\":\"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD\"}"
  | python3 -c "import sys,json;print(json.load(sys.stdin)[\"tokens\"][\"access_token\"])");
  curl -sS -H "Authorization: Bearer $TOKEN" http://lupin-rest-test:7999/api/get-queue/run'
→ {"run_jobs_metadata":[],"filtered_by":"50c73ba7-...","is_admin_view":false,"total_jobs":0}
```
(test run queue was already drained — user's big job collection had completed during debugging.)

**User confirmed "Pier Q watch works" from the admin UI widget.**

**Files changed this checkpoint (4 Lupin-side; 1 CoSA-side uncommitted)**:
- `src/conf/lupin-app.ini` — whitelist changed to container names
- `src/conf/lupin-app-splainer.ini` — splainer entry updated with container-network rationale
- `src/fastapi_app/static/html/admin/js/peer-queue-watch.js` — requireAdmin guard order; ALLOWED_HOSTS shape `[{value, label}]`; stale-host guard in `restoreSettings`
- `history.md` + `.claude-session.md`
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/peer.py` (Option B implementation, ~60 net lines added for service-account login + cache; `_fetch_queue` signature change; module docstring rewritten)

**Ops action (not a code change)**: ran `seed_test_companions.py` manually on `lupin-rest-test`. Users/API-keys now present in test DB. If the test DB is reset again, re-run the script or restart the container (seed hook fires on startup).

**Unit tests**: 12/12 `test_peer_proxy.py` still pass after signature change.

**Next / followups**:
- Why did the test-DB seed fail silently on last container startup? Worth investigating so this doesn't recur. Not done this session.
- CoSA-side commit of `peer.py` (Option B overhaul) + earlier `pages.py` (peer-queue-watch route) + `admin.py` (refresh-source from CP1) — yours to stage in the CoSA context.

---

#### Checkpoint 2 | 2026.04.14 12:10 EDT | Peer Queue Watch (dev UI → test server)

**Context**: User locked out of test server (:8000) admin UI; needed visibility into its running queue while a large overnight job collection was executing. Decision via `ask_multiple_choice`: architect as dev-server-side proxy + server-side watcher + admin UI widget on `:7999` (where auth works). Backend fires the high-priority voice notification so the drain alert survives the user closing the browser tab. Plan file: `~/.claude/plans/rosy-watching-quilt.md` (rewritten from Checkpoint 1's refresh-server plan).

**Key corrections during planning** (captured in memory for future work):
- **mock_token_email_* is NOT canonical**. `src/cosa/rest/auth.py:80-125` dispatches on config key `auth mode`, which is `jwt` in `[Lupin: Baseline]` (`lupin-app.ini:497`) — inherited by every configured environment. `verify_mock_token` is labeled "legacy development mode" and is not reached. CLAUDE.md + AUTH-TESTING-GUIDE.md references to mock tokens are stale; `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` env vars are **login credentials for `POST /auth/login`**, not mock-token inputs. Saved as `feedback_mock_tokens_are_legacy.md` in auto-memory.
- **Cosa-voice CAN fire from the backend**. Initial Explore agent wrongly concluded cosa-voice was MCP-only. `src/cosa/agents/utils/sync_notify.py:20-87` posts to `/api/notify` with an `X-API-Key` header — the WebSocket fanout routes it to cosa-voice for TTS. Any backend code path can trigger the voice alert via this helper.
- **JWT pass-through viable**. `jwt_service.py:25-32` reads `JWT_SECRET_KEY` with a fallback dev string; `docker-compose.yml` sets the env var on NEITHER dev nor test container, so both fall back to the same string → a JWT minted by dev verifies on test. Zero credential-juggling needed for the proxy.

**Backend (CoSA submodule — NOT committed from Lupin context)**:
- `src/cosa/rest/routers/peer.py` (new, 289 lines): four endpoints. `GET /api/admin/peer-queue/{queue_name}` proxies to `http://{host}/api/get-queue/{name}` with whitelist validation + JWT pass-through. `POST /api/admin/peer-queue-watch/{start,stop}` + `GET .../status` manage one `asyncio.Task` per admin that polls the peer and fires `sync_notify.notify(priority="high")` via `asyncio.to_thread` when `consecutive_zero >= stable_for`. Host whitelist read from config `peer queue allowed hosts`. Per-admin state dict keyed by `uid`/`email`. Pure helpers (`_is_host_allowed`, `_validate_host_and_queue`) exposed for unit testing.
- `src/cosa/rest/routers/pages.py`: added `/app/admin/peer-queue-watch` route + `_ROUTE_TABLE` entry.

**Lupin-side**:
- `src/fastapi_app/main.py`: imported `peer` router, registered via `app.include_router(peer.router)`, added shutdown handler `await peer.cancel_all_watchers_on_shutdown()` in lifespan cleanup block.
- `src/fastapi_app/static/html/admin/peer-queue-watch.html` (new): widget page with host selector, signal toggle (`run` vs `run+todo`), interval/stable-for inputs, live status panel (run/todo counts, consecutive zeros, last poll, last error), event log. Breadcrumb: Home > Admin > Dev Tools > Peer Queue Watch.
- `src/fastapi_app/static/html/admin/js/peer-queue-watch.js` (new, 218 lines): thin controller. `setInterval(10s)` polls `/status`; start/stop buttons call respective endpoints. `requireAdmin()` guard. `localStorage` persistence (key `lupin:pqw:settings`). Drain transition detected via `drained_at` timestamp change → logged in UI (voice alert already dispatched by backend). Uses existing `apiCall()` from `auth/js/auth.js:137-200`.
- `src/fastapi_app/static/html/dev-tools.html`: added "Peer Queue Monitoring" section with card linking to the new page.
- `src/conf/lupin-app.ini`: `peer queue allowed hosts = localhost:8000,localhost:7999` in `[Lupin: Baseline]`.
- `src/conf/lupin-app-splainer.ini`: matching splainer entry.

**Tests**:
- `src/tests/unit/test_peer_proxy.py` (new): 12 tests across `_is_host_allowed` (exact-match semantics, port-sensitivity, empty whitelist, substring-rejection), `_validate_host_and_queue` (HTTPException raising with correct status codes and detail text, all four queue names accepted), and `_watcher_state` isolation. All 12 pass.
- Live reachability (curl, no auth): proxy → 401, `watch/status` → 401, `/app/admin/peer-queue-watch` page → 200. Dev server auto-reloaded cleanly.
- Integration test with mocked aiohttp — deferred; the critical pure logic is covered by the unit tier, and auth/network paths are thin enough to validate in-browser.

**Auto-memory updates**:
- NEW `feedback_mock_tokens_are_legacy.md` — canonical auth paths are JWT (from `/auth/login`) or `X-API-Key`; mock tokens are rejected in every configured environment.
- MEMORY.md index updated.

**Files changed (7 Lupin-side in this checkpoint; 2 CoSA-side uncommitted)**:
- `src/conf/lupin-app.ini` (+3 lines)
- `src/conf/lupin-app-splainer.ini` (+1 line)
- `src/fastapi_app/main.py` (+9 lines: import, router register, shutdown hook)
- `src/fastapi_app/static/html/dev-tools.html` (+8 lines: monitoring section)
- `src/fastapi_app/static/html/admin/peer-queue-watch.html` (new)
- `src/fastapi_app/static/html/admin/js/peer-queue-watch.js` (new)
- `src/tests/unit/test_peer_proxy.py` (new)
- `history.md` + `.claude-session.md`
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/peer.py` (new, +289 lines), `src/cosa/rest/routers/pages.py` (+5 lines: new page route)

**Next**: User opens `http://localhost:7999/app/admin/peer-queue-watch`, clicks Start against `localhost:8000` with the current live job collection. Voice drain notification fires when the test server's run+todo queues both hit 0 for two consecutive polls. Separately, test-server admin auth lockout still to be investigated (deferred out-of-scope; likely role-seeding regression in test DB fixture).

---

**Context**: The dev server (:7999) auto-reloads source via `uvicorn --reload`, but the test server (:8000) runs with `reload=False` (main.py:813) so bind-mounted source edits are ignored until the Python process restarts. No friction-free refresh mechanism existed; manual `docker restart lupin-rest-test` + visual health poll was the only path. User requested design exploration of options (including the SIGHUP avenue — a dead end since the container runs plain uvicorn with no gunicorn master). Plan file: `~/.claude/plans/rosy-watching-quilt.md`.

#### Checkpoint 1 | 2026.04.14 11:15 EDT | Layer A + B implemented, live verification deferred

**Design choices confirmed (via ask_multiple_choice)**:
- **Scope**: Layer A (shell script + slash command) + Layer B (admin endpoint). Hook-based auto-refresh rejected — defeats snapshot semantics the user wants to preserve.
- **State**: Cold restart only. In-memory state (queues, WS sessions, consumer thread) discarded by design. `importlib.reload()` graph-walk rejected as fragile (stale closures, class identity, thread-held refs).

**Layer A — host side (committed in this checkpoint)**:
- `src/scripts/refresh-test-server.sh` (new, +62 lines) — wraps `docker restart lupin-rest-test` + polls `http://localhost:8000/health` at 500ms intervals up to 30s; on failure prints `docker logs --tail 50`; supports `--quiet` for automation.
- `.claude/commands/refresh-test.md` (new) — `/refresh-test` slash command, picked up by the harness this turn.

**Layer B — admin endpoint (CoSA submodule edit, NOT committed from this context)**:
- `src/cosa/rest/routers/admin.py` (+79 lines) — new `POST /admin/refresh-source` endpoint. Double gate: `LUPIN_ENV ∈ {test, testing}` AND config key `admin refresh source enabled = true`. Uses `BackgroundTasks` to schedule an `os.execv()` re-exec after a 0.2s sleep so the 202 response flushes before the process image is replaced. `os.execv` chosen over `sys.exit` to keep container lifecycle stable and avoid brief network teardown. Reuses existing `require_admin` dep from `cosa.rest.auth_middleware`. Added `BackgroundTasks` to the top-level fastapi import.

**Lupin-side config**:
- `src/conf/lupin-app.ini` — `admin refresh source enabled = false` in `[Lupin: Baseline]`; overridden to `true` in `[Lupin: Testing]` and `[Lupin: Testing-GCS]`.
- `src/conf/lupin-app-splainer.ini` — splainer entry matching the new key.

**Verification status**:
- Static: `py_compile.compile('.../admin.py')` → OK. `bash -n refresh-test-server.sh` → OK. Both pre-flight.
- Live: deferred — test server is currently running a large job collection per user; no container restart attempted.
- Pending: unit test for `_refresh_source_allowed()` guard function (pure, trivial to add when live verification runs).

**Files changed (5 Lupin-side in this checkpoint; 1 CoSA-side uncommitted)**:
- `src/scripts/refresh-test-server.sh` (new)
- `.claude/commands/refresh-test.md` (new)
- `src/conf/lupin-app.ini` (+3 config lines across 3 blocks)
- `src/conf/lupin-app-splainer.ini` (+1 splainer line)
- `.claude-session.md` (session 5a620729 section)
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/admin.py` (+79 lines — user to commit in cosa context per nested-repo rules)

**Next**: When test server is idle — run `./src/scripts/refresh-test-server.sh` to verify Layer A end-to-end, add unit test for Layer B guard, then `curl -X POST /admin/refresh-source` with admin JWT to verify the full re-exec path.

---


## Archives

- [2026-04-08 to 04-14](history/2026-04-08-to-14-history.md) — 23 sessions (TFE E2E, BFE Phase 6, checkpoint-resume, bug fixes)
- [2026-03-26 to 04-07](history/2026-03-26-to-04-07-history.md) — Sessions 379-a47f938e (BFE Phase 6, CJ Flow persistence, Sonnet pivot, UPE LanceDB isolation)
- [Full archive index](history/README.md)
