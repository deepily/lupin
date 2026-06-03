# 23 — Overnight Grind: CERTIFIED COMPLETE

> **For:** Rick's morning gate (2026-06-03). Manager: Tiberius 👑 (`1333e106`).
> **Outcome:** the all-tiers coverage directive, delivered on the **unit tier** — `cosa` is **100% line + branch + function tree-wide**, fully committed, HELD on the branch for Rick's push.
> **Supersedes** the mid-grind ledger in doc 22 (prod bug + pollution detail still live there).

---

## 1. 🏁 Certification (authoritative, committed tree)

Final gate, cosa `.venv` (py3.11 / pytest9), `src/tests/unit/ src/cosa/tests/unit/`, `--cov=cosa --cov-branch`, on the **committed** tree (post final-wave commits):

```
13300 passed, 2 xfailed, 0 failed (exit 0)   [241s]
coverage --skip-covered → 412 files skipped due to complete coverage
TOTAL  38,447 stmts / 0 miss · 11,172 branch / 0 BrPart = 100%
```

**Zero sub-100% rows tree-wide. Zero hollow tests** (Krishna: 8/8 batches approved, 0 hollow).

## 2. The 11 grind commits (all test-only, reviewer-gated, HELD — push is Rick's alone)

| # | Commit | Batch | Author / Gate |
|---|---|---|---|
| 1 | `d75bb69` | de-poison 15 legacy files (`sys.exit`→`pytest.skip`) | Rachel / Tiberius |
| 2 | `425cf19` | crud_for_dataframes 0→100% (171 tests) | Cheech / Krishna |
| 3 | `5b31b8d` | io_models wired 100% (215 tests relocated, 0 new) | Cheech / Tiberius |
| 4 | `9ed2f56` | FM-21 sys.modules pollution fix (test_expeditor_handlers) | Rachel / Tiberius |
| 5 | `02ecba9` | prediction_engine 0→100% (179 tests) | Rachel / Krishna |
| 6 | `ecc33cc` | orchestration 0→100% (61 tests) | sam / Krishna |
| 7 | `0278e92` | cosa.rest 99→100% (2 error-branch tests) | Cheech / Tiberius |
| 8 | `d865f35` | LLM-client family 14-17→100% (48 tests) | sam / Krishna |
| 9 | `8d0d79f` | test_suite/job.py 0→100% (70 tests) | sam / Krishna |
| 10 | `8ebcfdc` | agents/root tail 100% (25 tests) | Rachel / Krishna |
| 11 | `e70e02e` | last branch in durable guard-free companion | Cheech / Krishna×2 |

## 3. Rick's morning gate — action checklist

1. **PUSH** the 11 commits (yours alone — never auto-pushed).
2. **REAP or HOLD** the fleet — Rachel / sam / Cheech / Krishna are PARKED + available (not reaped; that's your teardown call). Clean reap: `dismiss_sessions(session_names=None)`.
3. **PROD BUGS (2) — ✅ RESOLVED 2026-06-03 (Rick-authorized, Tiberius 👑 session `1333e106`):** both fixed at source, both tripwire pins de-armed, both files certified 100% line+branch+function. Full canonical unit gate post-fix: **13,309 passed / 1 xfailed / 0 failed** (the cert's 2 xfailed → 1; Bug (b)'s strict xfail de-armed, the surviving xfail is the other pre-existing one). Fix record: doc 25.
   - **(a) `dispatcher.py:468`** reads uninitialized `self.debug` → AttributeError on any rate-limit in an interactive session, swallowed by the broad `except` → session dies. Tripwire-pinned tonight for honest coverage. One-line fix: add `debug: bool = False` to `ClaudeCodeDispatcher.__init__`. Detail in doc 22 §3. **✅ FIXED:** `__init__` now takes `debug: bool = False` + sets `self.debug = debug`; pin replaced by 2 tests covering both `debug` arms.
   - **(b) `cosa_interface.ask_yes_no`** calls `_dispatcher.ask_yes_no`, which does NOT exist on `AgentNotificationDispatcher` (only `ask_confirmation`, different signature) → AttributeError. Pinned PRE-tonight by a `strict=True` xfail in `test_suite/test_cosa_interface.py:65` (committed `533d273`, 2026-06-01, Clayton-approved). This is one of the cert's **2 xfailed** — strict, so it can't mask a pass. Fix the dispatcher method + de-arm the xfail. **✅ FIXED:** `ask_yes_no` now copies identity onto the shared dispatcher (mirrors `notify_progress`), delegates to the real `ask_confirmation` (→ bool), and returns `"yes"`/`"no"`; strict xfail + AttributeError pin removed, 4 contract tests added.
4. **CLAUDE.md §PROJECT STRUCTURE stale** — `src/cosa/app/` no longer exists.
5. **Deferred (need your gate):**
   - Harvest-block deletions — the `quick_smoke_test`/`__main__` blocks superseded by new pytest (crud/job/orchestration/agents-root) + the now-redundant shallow legacy files (test_weather_agent / token_counter / math_agent / date_and_time_agent). One consolidated cleanup pass.
   - Global hermetic-config autouse fixture (FM-21 systemic kill) — broad blast radius; needs clean isolation-verify (full suite green WITH it active AND zero currently-green tests broken) before landing, else your gate. María's steward ruling: at-source per-polluter tonight, global fixture = verified-or-deferred.
6. **io_files watch-note** — doc 90: `test_io_files_router::test_relative_io_prefix_stripped` was a one-time non-reproducing collection-order artifact (3/3 fresh-hashseed green; gate4 red self-healed via intervening peer commits). Candidate **FM-22** (order/loop-state flakiness, distinct from FM-21 config-bleed). Real-fix recipe in the note if it recurs.
7. **Integration / E2E tier** — the only remaining "all-tiers" work beyond unit. `:8000`-scheduled (monopolize mode), needs your slot — NOT an unattended overnight task.

## 4. Notes for the record

- **Spawn permission:** you allow-listed `mcp__cosa-voice__spawn_sessions` (project `.claude/settings.local.json`) — the auto-mode classifier had blocked the "do not stop" autonomous-spawn framing. 4th author (sam) spawned cleanly after.
- **Blank-broadcast bug** (verified Tiberius + María): USER BROADCAST send+storage OK, per-session injection renders empty body. Owner: cosa-voice broadcast-listener. Your all-tiers directive reached the fleet only via María's manual relay.
- **Heartbeat pokers** not launched (no clean `owner_user_id` resolver without you awake; neither Tiberius nor María would confabulate one). María kept warm via manual ~10-min push-DM cadence. Turn-key self-poke invocation folded into runbook §7 for morning.
- **Discipline held throughout:** green-before-commit (never into a flaky/red tree), no hollow tests, no skip/xfail-to-green, every prod-logic change left for you, all commits HELD (no push surfaced).

**Uncommitted on disk (within test-only authority — left for your session-end):** docs 22 (findings), 90 (watch-note), 23 (this), runbook §7 edit, TODO.md, `.claude-session.md`.
