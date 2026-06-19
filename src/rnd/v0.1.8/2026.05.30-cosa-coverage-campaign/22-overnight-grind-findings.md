# 22 — Overnight Grind: Findings, Prod Bugs & Pollution Ledger

> **For:** Rick's morning review (2026-06-03). Manager: Tiberius 👑 (`1333e106`).
> **Context:** all-tiers 100%-coverage marathon (Rick's pre-sleep directive, relayed by María since the broadcast rendered blank). Fleet: Rachel (prediction_engine), Cheech (io_models→rest), sam (job.py→orchestration), Krishna (reviewer).
> **Push status:** everything below is HELD on `wip-v0.1.8`. Nothing pushed.

---

## 1. Commits landed (test-only, green-gated, reviewer-gated)

| Commit | What | Coverage |
|---|---|---|
| `d75bb69` | De-poison 15 legacy test files (`sys.exit`→`pytest.skip allow_module_level`) | unblocked agents collection |
| `425cf19` | `cosa.crud_for_dataframes` test package (171 tests) | 0 → 100% line+branch+function |

**Tier-1 COMPLETE:** repo, utils, config, tools, memory (already 100% pre-campaign) + crud (committed). The runbook's "~4,185 Tier-1 miss" was almost entirely stale.

## 2. Batches DONE but HELD (commit gated on tree-green)

| Batch | Author | Coverage | Gate status |
|---|---|---|---|
| `cosa.orchestration` (+claude_code) | sam | 0 → 100% (288 stmts, 100 br, 61 tests) | awaiting Krishna audit + tree-green |
| `cosa.agents.io_models` WIRING | Cheech | → 100% (215 existing tests relocated via `git mv` into canonical roots; **zero new test lines**) | awaiting tree-green |
| `cosa.agents.test_suite/job.py` | sam | 0 → 100% (409 stmts, 110 br, 70 tests) | **RED — pollution, see §4** |
| `cosa.agents.prediction_engine` | Rachel | in progress | **RED — pollution, see §4** |

## 3. ✅ PROD BUG — RESOLVED 2026-06-03 (Rick-authorized; was tripwire-pinned)

> **RESOLVED** (Tiberius 👑 `1333e106`, 2026-06-03): `__init__` now takes `debug: bool = False` and sets `self.debug = debug`; the RateLimitEvent branch logs (debug on) or continues silently (debug off) instead of raising. Tripwire pin replaced by 2 tests covering both `debug` arms; `dispatcher.py` re-certified 100% (239 stmts / 86 branch / 0 miss). Full-tree gate green. Fix record: doc 25.

**`src/cosa/orchestration/claude_code/dispatcher.py:468`** — `_run_interactive`'s `RateLimitEvent` branch reads `self.debug`, but `ClaudeCodeDispatcher.__init__` **never initializes `self.debug`** → `AttributeError` on any rate-limit during an interactive session. Currently swallowed by the broad `except Exception` at :505 → the interactive session **dies** ("object has no attribute 'debug'") instead of logging + continuing.

- **Pinned** by `test_run_interactive_rate_limit_event_is_prod_bug` (asserts current buggy behavior so coverage is honest without masking — sanctioned tripwire doctrine).
- **Recommended fix (prod-logic → your call):** add `debug: bool = False` to `__init__` + `self.debug = debug` (matches the codebase debug convention); then flip the pin to assert graceful continue.
- **NOT touched** — prod-logic changes are gated on you; deferred to this review.

## 4. Test-isolation defects blocking the green-gate (author-owned, in flight)

Two distinct cross-test pollutions make the canonical full-tree gate red. Both are being fixed hermetically (test-only); commits resume once green.

1. **`test_job.py` ×3** (sam) — cumulative agents-tree pollution (deterministic, not random). `_patch_config_mgr`'s module-attribute monkeypatch is defeated under load; job.py's function-local `from cosa.config.configuration_manager import ConfigurationManager` resolves to the real `@singleton` (empty INI) → `_FakeConfigMgr` never installed. Passes in isolation + each half; fails only in the full agents tree. Fix: make the 3 tests bulletproof (reset+seed the singleton, or hold module identity under load). Owner: sam.
2. **`test_prediction_engine.py::test_tally_multi_select_threshold_and_fallback` ×1** (Rachel's victim) — cross-tree polluter on the `src/tests/unit/` side, **exposed** (not caused) by io_models's collection-order shift. Pre-existing latent non-hermetic leak. Owner: Cheech bisecting + fixing at the polluter.

## 5. Infra notes

- **Blank-broadcast bug** (verified across 2 sessions, Tiberius + María): USER BROADCAST send+storage OK, but the per-session system-reminder injection renders an **empty body**. Owner: cosa-voice broadcast-listener. María filed it.
- **Heartbeat pokers NOT launched** — no clean `owner_user_id` resolver exists without you awake; neither Tiberius nor María will confabulate one or submit a CJ-Flow job as you. María kept warm via manual ~10-min push-DM cadence. Real pokers deferred to morning (turn-key invocation folded into runbook §7).
- **Harvest-block deletions** (crud/job/orchestration `quick_smoke_test`/`__main__` blocks) deferred to a single campaign-end consolidated cleanup batch.

## 6. Spawn permission

You allow-listed `mcp__cosa-voice__spawn_sessions` (project `.claude/settings.local.json`) — the auto-mode classifier had blocked the "do not stop" autonomous-spawn framing. Sam (4th author) spawned cleanly afterward.
