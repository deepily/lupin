# 90 — Execution Log

Session 2026-04-28 (paired with 01-design.md).

---

## Phase 0 — Documentation-First Serialization ✅

**Started**: 2026-04-28 ~12:00
**Completed**: 2026-04-28 ~12:05

Created the design doc skeleton:
- `01-design.md`
- `02-wg-{1..9}-*.md` (9 WG docs)
- `90-execution-log.md` (this file)

---

## WG-3 — BURN GPU-touching tests ✅

**Audit grep** (`grep -rln 'torch\.cuda\|mem_get_info\|EmbeddingEngine(\|cuda:0' src/tests/`):
```
src/tests/unit/test_local_embedding_engine.py        — KEEP (all GPU mocked)
src/tests/smoke/test_embedding_benchmark.py          — DELETE
src/tests/smoke/test_local_embedding_smoke.py        — DELETE
src/tests/integration/test_lancedb_gcs_integration.py — KEEP (HTTP fixture)
src/tests/logs/baseline_integration_20260311_201420.log — log file, ignore
```

**Verification**:
- `git rm` both deletion targets.
- Re-grep on `src/tests/smoke/` → clean.

**Result**: 6 prior FAILs eliminated (file removed).

---

## WG-4 — PEFT import guard ✅

**Edit**: `src/cosa/training/peft_trainer.py:12` — wrap `from peft import …` in `try/except ImportError`, set `PEFT_AVAILABLE` flag + None fallbacks.

**Verification**:
- `py_compile` clean.
- `pytest --collect-only src/tests/smoke/test_lora_env_update_smoke.py` → 6 tests collected (was failing at collection time with `ModuleNotFoundError`).

**Result**: 3 prior FAILs (collection-time import errors) resolved.

---

## WG-5 — LXML dep + audit ✅

**Audit grep**: `from peft|lxml|onnx|tensorrt|bitsandbytes|flash_attn|deepspeed|vllm|cupy|trl|auto_round import` in `src/cosa/`:
- `src/cosa/training/quantizer.py:8` — `from auto_round import AutoRound` (training-only, low risk)
- `src/cosa/training/peft_trainer.py:32-33` — `from trl import …` + `from auto_round import …` (training-only)

These are training-tier files; same operator-launched lifecycle as PEFT. Filed as backlog item (WG-5b) but not blocking.

**Edit**: `pyproject.toml` — added `lxml>=5,<6` in NLP/parsing block. Comment notes that `lxml` was in `src/cosa/requirements.txt` but `uv sync --locked --no-install-project` reads from `pyproject.toml + uv.lock`, so the dep was never reaching the image.

**Verification**: deferred to image rebuild (WG-1).

---

## WG-2 — Smoke skip discipline ✅

**Edits**:
1. `src/tests/smoke/test_container_preflight.py:31-37` — wrapped `subprocess.run(['docker', 'info'])` in `try/except (FileNotFoundError, OSError, subprocess.TimeoutExpired)`. Returns `False` on any OS error so the autouse fixture's `pytest.skip` path is taken.
2. `src/tests/smoke/utilities/live_pipeline_base.py` — added conditional `import pytest as _pytest` at module top, then converted silent `False` returns at the credential gate (line 689) and ConnectionError handler (line 789) to `_pytest.skip(...)` calls when pytest is importable. Standalone CLI usage preserved (still falls through to `print` + `return False` paths).

**Verification**:
- Both files `py_compile` clean.
- `pytest -v test_container_preflight.py` → 7/7 PASS on host (docker available; will SKIP cleanly in test container).
- `pytest -v test_calculator_live_pipeline.py` with creds **unset** → SKIPPED (was previously FAIL).

**Result**: 7 ERRORs + 9 inheriting live-pipeline FAILs converted to SKIPs.

---

## WG-1 — Docker fonts (Dockerfile edit; rebuild deferred) ✅ (partial)

**Authoritative font enumeration** via `playwright install-deps chromium --dry-run` against the existing `lupin:1.0.0` image:
- `fonts-noto-color-emoji`, `fonts-unifont`, `xfonts-cyrillic`, `xfonts-scalable`
- `fonts-liberation`, `fonts-ipafont-gothic`, `fonts-wqy-zenhei`
- `fonts-tlwg-loma-otf`, `fonts-freefont-ttf`
- Plus support libs: `libfontconfig1`, `libfreetype6`, `xvfb`, `libx11-6`, `libxcb1`, `libxext6`, `libwayland-client0`, `libatspi2.0-0`

**Edit**: `docker/lupin/Dockerfile:101-114` — added all font + display packages to apt list. Comment block expanded with WG-1 reasoning + 2026-04-28 date + refresh instruction.

**Deferred to user**:
- Step 3 — `docker build -f docker/lupin/Dockerfile -t lupin:1.0.0-fonts .`
- Step 5 — bump `docker-compose.yml` to `image: lupin:1.0.0-fonts`
- Step 6 — bounce dev container
- Step 7 — `./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual`
- Step 8 — re-run e2e visual to confirm 0 ERRORs
- Step 9 — promotion to `lupin:1.0.0` (user-confirmed retag, never auto)

Rationale: image rebuild is invasive (~15-30 min, full container teardown), and the user wants to time it themselves. Dockerfile edit lands now so the rebuild is trivial when they're back.

---

## WG-9 — TFE voice-gate auto-fallback policy ✅

**Edits**:
1. `src/cosa/agents/test_fix_expediter/config.py` — added `voice_gate_timeout_policy: str = "stall"` and `voice_gate_auto_ratify_top_n: int = 1` fields + INI key map entries.
2. `src/cosa/agents/test_fix_expediter/orchestrator.py:1074` — replaced bare `raise` on `VoiceGateTimeoutError` with `self._apply_voice_gate_timeout_policy(proposals)`. New helper method handles 4 modes: `stall` (re-raise), `top_1` (highest-confidence), `top_n` (sorted top-N), `none` (empty list). Unknown values fall back to `stall` with a warning.
3. `src/conf/lupin-app.ini:929-930` — added `test fix expediter voice gate timeout policy = stall` and `test fix expediter voice gate auto ratify top n = 1`.
4. `src/conf/lupin-app-splainer.ini:786-787` — added matching splainer entries.
5. `src/tests/unit/test_tfe_voice_gate_fallback.py` — NEW, 9 unit tests covering all 4 modes + tie-breaking + zero-clamp + unknown-value fallback.

**Verification**:
- All 4 files `py_compile` clean.
- 9/9 new unit tests PASS.
- 27/27 existing TFE unit tests (config + propose) still PASS — no regression.

**Result**: TFE has a non-stalling fallback for after-hours runs. Default unchanged (`stall` preserves prior production behavior); operator opts in via INI flip.

---

## WG-7 — Websocket false-FAIL parser fix ✅

**Edits**:
1. `src/cosa/agents/test_suite/job.py:828` — added fallback call to `_parse_non_pytest_stdout(suite_type, stdout)` after `_parse_junit_xml(None)` when junit_xml_path is None and counts are zero.
2. Same file, after `_parse_junit_xml` definition — added `_parse_non_pytest_stdout` static method. Recognizes the websocket runner's stdout summary (`Total Tests: N`, `Passed: X`, `Failed: Y`, `ALL SMOKE TESTS PASSED!`). Returns `None` for unrecognized formats so behavior is unchanged for other suites.
3. `src/tests/unit/test_test_suite_websocket_parser.py` — NEW, 8 unit tests covering pass / fail / partial / ambiguous / unrecognized / non-websocket cases.

**Verification**:
- 2 files `py_compile` clean.
- 8/8 new unit tests PASS.
- 93/93 existing test_suite unit tests (job + watchdog + pytest_direct) still PASS — no regression.

**Result**: 2026-04-27 22:35 EDT websocket suite (which logged `ALL SMOKE TESTS PASSED · 50/50 (100%)`) would now be classified PASS instead of FAIL.

---

## WG-8 — Run-queue orphan + consumer-stall guardrails (8b ✅; 8a/8c deferred)

### WG-8b — heartbeat observability ✅

**Edits**:
1. `src/cosa/rest/running_fifo_queue.py:__init__` — added `self.last_consumer_heartbeat_at = None` and `self._consumer_stall_threshold_seconds` (read from INI key with default 120s).
2. `src/cosa/rest/running_fifo_queue.py:get_pool_status` — appends 4 keys to payload: `last_consumer_heartbeat_at` (ISO string or None), `seconds_since_heartbeat` (float or None), `consumer_stall_threshold_secs`, `consumer_stalled` (bool).
3. `src/cosa/rest/queue_consumer.py:consumer_worker` — at the top of each loop iteration, write `running_queue.last_consumer_heartbeat_at = datetime.now()` (best-effort; `AttributeError` swallowed for Mock-backed unit tests).
4. `src/conf/lupin-app.ini` — added `cj flow consumer stall threshold seconds = 120` near the ghost-job sweeper key.
5. `src/conf/lupin-app-splainer.ini` — added matching splainer entry.
6. `src/tests/unit/test_consumer_heartbeat.py` — NEW, 6 unit tests covering: never-ticked, recent, old/stalled, threshold boundary, ISO format, backward-compat keys.

**Verification**:
- 3 files `py_compile` clean.
- 6/6 new unit tests PASS.
- 58/58 regression tests (consumer_timed + agentic_pool + fifo_queue_thread_safety + running_queue_threshold) still PASS.

### WG-8a — orphan cleanup (DEFERRED)

User-confirmed action (mutates `:8000` queue state). Plan:
```
DELETE /api/queue/run/<orphan-id>     # 1 stuck Calculator
DELETE /api/queue/dead/<id>           # × 8 reaped Calculators
DELETE /api/queue/dead/<test_suite-id> # if user wants the 21:06 test_suite gone too
```

### WG-8c — empty-error audit (DEFERRED, merged into OOS-4)

The 8 Calculator dead jobs have `error=""`. Per running_fifo_queue.py:702 `_transition_to_dead` sets `job.error`. So the empty-error path is somewhere else — needs runtime evidence to reproduce. Folded into OOS-4 (the test_suite-job-in-dead investigation) since both probably share the same code path.

---

## WG-6 — Survivor FAIL investigation (DEFERRED, gated by re-run)

The 22:35 report's two captured failure modes:
- `test_simple_agents_instantiation_smoke` → `lxml not found` (WG-5 should resolve after image rebuild).
- `test_notification_proxy_script_matching` → ambiguous, fails loading `deep-research.json`.
- `test_tfe_error_capture_smoke` → ambiguous, fails at "Persistence allowlist check".

Status: blocked on the verification re-run (T15). Re-evaluate after.

---

## Verification — :8000 re-run (DEFERRED, user-coordinated)

Submission template:
```
POST /api/test-suite/submit
{
    "test_types"          : "all",
    "auto_fix_on_failure" : false,
    "scheduled_at"        : "<USER-CONFIRMED SLOT>"
}
```

Acceptance:
- 0 ERRORs in e2e suite (visual-regression all green; gated on WG-1 image rebuild)
- smoke FAILs ≤ 2 (only WG-6 leftovers permitted)
- websocket suite classified PASS (was 0/0/0/0 FAIL — WG-7 fixes parser)
- 0 jobs orphaned in run after run completes
- TFE either auto-ratifies (if WG-9 default flipped) or stalls cleanly without losing proposals

---

## Summary table (autonomous-session deliverables)

| WG | Status | Files touched | Tests added | Tests passing |
|----|--------|---------------|-------------|---------------|
| Phase 0 | ✅ | 11 doc stubs | — | — |
| WG-2 | ✅ | 2 | (existing tests now SKIP correctly) | container 7/7, calc SKIP confirmed |
| WG-3 | ✅ | 2 deletes | — | smoke audit clean |
| WG-4 | ✅ | 1 | (collection now succeeds) | 6 lora tests collect |
| WG-5 | ✅ (rebuild deferred) | 1 | — | (gated on image) |
| WG-1 | ✅ Dockerfile (rebuild deferred) | 1 | — | (gated on rebuild) |
| WG-7 | ✅ | 1 + 1 NEW | 8 | 8/8 + 93/93 regression |
| WG-8b | ✅ | 4 + 1 NEW | 6 | 6/6 + 58/58 regression |
| WG-8a | DEFERRED | — | — | — |
| WG-8c | DEFERRED → OOS-4 | — | — | — |
| WG-9 | ✅ | 4 + 1 NEW | 9 | 9/9 + 27/27 regression |
| WG-6 | DEFERRED | — | — | — |
| Verify | DEFERRED | — | — | — |

**Total new tests**: 23 unit tests across WG-7 / WG-8b / WG-9.
**Total py_compile**: 11 files compile cleanly.
**Total regression suite**: 147 tests pass (no breakage).
**Total deletions**: 2 GPU-touching smoke files.

---

## What remains for the user

1. **Image rebuild** — `docker build -f docker/lupin/Dockerfile -t lupin:1.0.0-fonts .` then bump `docker-compose.yml`, bounce dev, regenerate baselines, verify, promote to `:1.0.0`.
2. **Orphan cleanup** — 1 + 8 DELETEs on `:8000` (or leave for the re-run to overwrite).
3. **`:8000` verification slot** — pick a non-overlapping `scheduled_at` and submit.
4. **(Optional)** flip the new `test fix expediter voice gate timeout policy` to `top_1` so the next after-hours run doesn't lose its proposals on timeout.
5. **Commit** — none done yet (per `feedback_never_auto_commit_push`). Suggested grouping: 7 separate commits, one per WG, with the design docs in the first commit.
