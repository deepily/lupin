# 10 — Cheech 🌿 Lane Handoff: agents/test_suite/job.py (remainder)

> **Author:** Cheech 🌿 (WAVE-2 author, seat idx=1, session 8d4aed22)
> **Written:** 2026-06-01, at a clean green-line honest-stop.
> **For:** whoever (fresh author) picks up `agents/test_suite/job.py`.
> **Manager:** Tiberius 👑 (session b8a9f332). Gate: author → Tiberius disk-verify → Krishna 🦚 audit → Tiberius commits. **Authors do NOT commit.**

---

## TL;DR — lane state at stop

WAVE-2 agents-Tier-2 greenfield lane (Cheech). **Everything DONE except `test_suite/job.py`.**

| Target | State |
|---|---|
| `io_models/xml_models.py` | ✅ 99% → TRUE 100% w/ 3 manager-pragmas (SB1). +80 tests. |
| `io_models/util_xml_pydantic.py` | ✅ 99%; 1 pragma proposed (24-25, ImportError guard). |
| `tfe_to_cc/` (bundle_phase1/3 + output_contract) | ✅ genuine 100% (431/126, 60 tests, SB2). |
| `agents/utils/agent_notification_dispatcher.py` | ✅ genuine 100% (44 tests, SB3). |
| `agents/utils/proxy_agents/*` (5 modules) | ✅ genuine 100% (50 tests, SB4). |
| `agents/utils/voice_io.py` | ✅ genuine 100% (72 tests, SB5). |
| `agents/utils` PACKAGE | ✅ **777/252/100%, 190 tests, no cross-pollution.** |
| `test_suite/cosa_interface.py` | ✅ 100% + **PROD BUG tripwired** (SB6, see below). |
| `test_suite/voice_io.py` | ✅ 100% (re-export wrapper, SB6). |
| **`test_suite/job.py`** | ⬜ **UNTOUCHED — this handoff.** 1231 lines, the heaviest module in the lane. |
| Already-100%-on-disk (prior authors, skipped) | `deep_research_to_podcast`, `deep_research_to_presentation`, `test_harness/mock_job`. |

**Why I stopped here:** job.py is a 1231-line subprocess-poll-loop + fs-writing async orchestrator — orchestrator-class. Per the manager memento (06 §Fleet management / Honest-stop), this warrants fresh context + a split test-file approach. I'm deep in context after 6 sub-batches (~337 tests); pushing job.py now risks phantom tests. Clean green line + grounded handoff is the right move.

## 🚨 PROD BUG already found + tripwired (manager owns the fix — do NOT re-fix)

`test_suite/cosa_interface.py:148` `ask_yes_no` calls `await _dispatcher.ask_yes_no( question=..., sender_id=..., target_user=..., session_name=..., queue_name=... )`. **`AgentNotificationDispatcher` has no `ask_yes_no` method** (only `ask_confirmation`, params: question/default/timeout/abstract/job_id/role/priority). EMPIRICALLY: every call raises `AttributeError`. Tripwire armed in `tests/.../test_suite/test_cosa_interface.py`: `@pytest.mark.xfail(strict=True)` on the correct contract + a pin on current AttributeError. Likely orphaned (re-exported as voice_io.ask_yes_no:44 but core voice_io's voice path uses `ask_confirmation`, not `ask_yes_no`). Manager fixes + de-arms.

---

## Canonical interpreter & measurement (NON-NEGOTIABLE)

cosa venv ONLY (py3.11 / pytest 9.0.2). No SDK/scipy in job.py → plain pytest-cov (NOT run-sdk-cov.sh).

```bash
PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest \
  src/cosa/tests/unit/agents/test_suite/ \
  --cov=cosa.agents.test_suite.job --cov-branch --cov-report=term-missing -p no:cacheprovider -q
```

Coverage config (`pyproject.toml [tool.coverage]`) EXCLUDES `def quick_smoke_test` (1141+) and `if __name__ == .__main__.:`. Don't test those. COST INVARIANT: boundary-mock everything; ZERO API spend; never read `ANTHROPIC_API_KEY_FIREWALLED`.

Test dir already exists: `src/cosa/tests/unit/agents/test_suite/` (with `__init__.py`, `test_cosa_interface.py`, `test_voice_io.py`). Add `test_job.py` (or split — see below).

---

## job.py method-group carve (line ranges · difficulty · mock surfaces)

Suggest splitting into **`test_job_pure.py`** (groups A-C, no async/subprocess) + **`test_job_execution.py`** (groups D-F, async + subprocess) to keep files legible — mirrors the orchestrator helper/phases split the memento recommends.

### A. Module-level + pure helpers — EASY, no mocks
- `_expand_all` (86-107): "all"→ALL_SUITE_COMPONENTS expand + dedup. Test: `["all"]`→5 components; `["all","unit"]`→dedup (unit first wins); `["unit","smoke"]` passthrough; `[]`→[].
- Constants sanity: SUITE_SCRIPTS / FILE_DRIVEN_TEST_TYPES / SUITES_SUPPORTING_JUNIT_XML / SUITE_TIMEOUTS_SECONDS / ALL_SUITE_COMPONENTS (light asserts only — don't pad).

### B. TestSuiteJob construction + config — EASY/MEDIUM
- `__init__` (130-191): needs `AgenticJobBase.__init__` to run. **Read `cosa/agents/agentic_job_base.py` first** for the super() contract (it likely generates id_hash/base_id from JOB_PREFIX, sets state). Construct with valid user_id/email/session_id; assert test_types default (`["integration","e2e"]` when falsy), pytest_args default [], monopolize, suite_results {}, cost_summary None.
- `_filter_env_vars` (199-215): allowlist (TFE_/BFE_/LUPIN_TEST_). Test: kept key, dropped non-prefixed key (prints WARNING — capsys), non-str key dropped, empty→{}, value coerced to str.
- `from_config` (218-252): mock a config_mgr with `.get(...)`; assert test_types split, pytest_args split (and the empty-default→[] arc).
- `last_question_asked` (255-263): `"[Tests] integration, e2e"`.

### C. Parsers — MEDIUM, pure (sample strings, NO mocking)
- `_synth_failure_detail` (966-982): static; assert dict shape + `traceback or "(no output captured)"` both arcs.
- `_parse_junit_xml` (983-1070): **READ 992-1070 (I stopped reading at 992).** Feed: (a) `xml_path=None`→zero counts no-raise; (b) a real junit XML temp file w/ testcases incl. <failure>/<error>/<skipped> → counts + failure_details; (c) missing file path → zeros; (d) malformed XML → zeros/no-raise. Use `tempfile` for the XML.
- `_parse_non_pytest_stdout` (1071-1140): **READ it.** websocket-runner stdout summary parsing; feed sample "50 passed" style stdout + a no-match stdout (→ None).

### D. `_write_stdout_log` (940-963) — MEDIUM, fs mock
classmethod. Mocks: patch `pathlib.Path` write_text/unlink/symlink_to OR redirect to a `tmp_path`. Test: unknown suite_type→None (symlink_path None arc); empty stdout_text→None; known suite + text → writes file, refreshes symlink, returns abs path. `datetime.now()` is called — patch it or accept the real timestamp (file goes to /tmp; prefer patching `mod.datetime`).

### E. `do_all` (265-321) + `_execute_dry_run` (563-652) — MEDIUM, async
- `do_all`: patch `asyncio.run` OR patch `self._execute` (AsyncMock). 3 arcs: success (state COMPLETED, result set); `_cancel_requested`→CANCELLED; `_execute` raises→FAILED + re-raises (assert pytest.raises). Mock `cu.get_current_datetime_iso`, `self.get_execution_duration_seconds`.
- `_execute_dry_run`: pass fake voice_io + cosa_interface (AsyncMock notify, set_job_id/clear_job_id, _get_sender_id). Patch `asyncio.sleep` (no-op). Assert mock suite_results/cost_summary/artifacts populated + the `finally: clear_job_id` runs.

### F. `_execute` (322-561) + `_run_suite` (653-927) — HARD, subprocess + fs + async
This is the bulk. Boundary-mock surfaces:
- **voice_io / cosa_interface**: inject fakes (AsyncMock `notify`, `reconfigure`, `set_job_id`, `clear_job_id`; cosa_interface `_get_sender_id`, SENDER_ID/TARGET_USER attrs). They're imported INSIDE `_execute` (line 332: `from cosa.agents.test_suite import voice_io, cosa_interface`) → patch `sys.modules` entries or patch.object on those modules.
- **`self._run_suite`**: in `_execute` tests, patch it to return canned result dicts (all-pass / has-failures / startup-crash w/ `startup_crash_output` / with `log_path` pointing at a tmp file containing text). Drives: cancel-break arc (371-377), all-passed vs failures summary, snapshot-JSON-on-failure arc (499-525), report-md write (426-496) incl. the `log_path` read (472-481 try/except FileNotFoundError) and the crash-output else (483-488), `finally: clear_job_id` (560-561).
- **fs**: patch `pathlib.Path` (mkdir/write_text/read_text) or redirect `cu.get_project_root` to a `tmp_path` so report/snapshot land in tmp. Patch `mod.datetime`/`ZoneInfo` for deterministic timestamp (or accept real).
- **`_run_suite` itself** (separate tests, real method): mock `subprocess.Popen` with a fake process exposing `.stdout.readline()` (returns lines then `""`), `.poll()` (None then 0), `.returncode`, `.terminate/.kill/.wait`, `.stdout.read()`. Mock `time.monotonic` (sequence for elapsed/timeout), `os.path.exists`, `os.environ`, `ConfigurationManager` (extra-args INI), `self._write_stdout_log`, `self._parse_junit_xml`, `self._parse_non_pytest_stdout`. Arcs to cover: unknown suite_type (675-686), script-not-found (690-700), --bg strip (704-706), INI extra-args present/absent/raises (718-740), junit-xml inject vs skip (746-750), cancel mid-poll (786-802), timeout→terminate→kill→synth-failure (804-843) incl. `TimeoutExpired` on wait, normal completion + junit parse (855-895), non-pytest stdout fallback (875-878), startup-crash tail (886-888), Popen/loop exception (897-926) incl. the `NameError` guard (904-907).

**Difficulty estimate:** A-C ≈ quick. D-E ≈ moderate. F ≈ the real work (the Popen poll-loop is the trickiest — a small fake-process helper class pays off, like the `_FakeWS`/`_FakeConnect` pattern I used in `test_base_listener.py`, which is a good reference for fake-IO-object construction).

---

## Reusable patterns from my banked work (copy these)
- **Fake async-IO object** for poll/iteration seams: see `test_base_listener.py` `_FakeWS`/`_FakeConnect`.
- **asyncio.run driver** for async methods without pytest-asyncio: `def _run(coro): return asyncio.run(coro)` (used throughout my files).
- **Module-global state reset**: autouse fixture (see `test_voice_io.py`) — job.py mutates `cosa_interface.SENDER_ID/TARGET_USER` and `voice_io._job_id`; reset between tests.
- **Real Pydantic in the loop**: kept request-model validation real in dispatcher tests; it caught bad mock shapes (sender_id dotted local-part, job_id `prefix-8hex`, MC options `{label:}`). job.py uses dicts not Pydantic, so less of a concern.
- **Tripwire**: xfail(strict=True) on correct contract + pin on current behavior; NEVER pragma a bug-blocked line. (Already applied to cosa_interface.ask_yes_no.)

## Outstanding pragma proposals (manager applies — do NOT self-apply)
1. `io_models/xml_models.py:1631` — `# pragma: no cover` (after-validator always gets coerced str; non-str raises before guard).
2. `io_models/xml_models.py:2643` — `# pragma: no branch` (ConfirmationResponse.to_xml super() always emits `</response>`).
3. `io_models/util_xml_pydantic.py:24` — `# pragma: no cover` (xmltodict hard-dep ImportError guard unreachable).

Reach Cheech at `commons_send_to(recipient="cheech")` if continuity questions arise (until reaped).
