# CoSA 100%-Coverage Campaign — Formal Plan of Action

**Date:** 2026-05-30
**Author/Manager:** Tiberius 👑 (session `ac012bd2`)
**Lead worker:** Tiffany 💍 (`cc-author-tiberius-1`)
**Branch:** `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment`
**Status:** decisions ratified by Rick via interactive walk-through (2026-05-30); combined-coverage evidence run IN FLIGHT; D4 tiering + per-tier targets pending that number.

> **▶ To EXECUTE this campaign cold, read [`02-cold-start-runbook.md`](02-cold-start-runbook.md)** — the standalone operator runbook (every command, gate, revert, and contingency, runnable with zero chat-history). THIS doc (`00`) is the **decision-of-record** (the *why*); the runbook is the *how*. Where they disagree, the ratified decisions here win.

Cross-ref: baseline + denominator analysis → [`2026.05.30-cosa-100pct-coverage-baseline.md`](2026.05.30-cosa-100pct-coverage-baseline.md). TODO top entry: "CoSA 100%-coverage grandfathering ramp gate".

---

## 1. Context & goal

The 2026-05-29 mono-repo fold brought 621 CoSA files into Lupin as first-class source; they inherit the **Lupin-wide 100% coverage mandate** (line + branch + function) on a **grandfathering ramp** (deadline framing: 2026-06-05). This plan is the campaign to ramp `src/cosa/` toward that gate.

**Baseline (measurement-corrected, unit-tier, :7999):** 45.3% line / 34.8% branch (up from a raw, denominator-inflated 26.9% — pure config hygiene, zero tests). Real remaining target ≈ 19,659 missing lines + 7,247 missing branches across 408 files.

---

## 2. Ratified decisions

| # | Decision | Ruling |
|---|---|---|
| **D1** | Gate methodology | **HYBRID** (evidence-confirmed 2026-05-30; combined run = 52.0% line / 41.7% branch, a lower bound): **credit REST to the server suites** (+1,776 lines, 70% of the delta); ALL other modules (agents/memory/repo/orchestration/utils/config/crud) are **unit-only** (orchestration server-delta was +0 — refuted the "integ-likely" guess). |
| **D2** | Denominator | Bless Tier-0 cleanup: omit test-files + `training/` (GPU, never-grab-GPU mandate, same-line reason). Exclude `quick_smoke_test`/`__main__` **as scaffolding** → **harvest + migrate to pytest + delete one-by-one**; retire the exclusion regex once all ported. **All legacy tests** (non-pytest unit/integration, standalone scripts) likewise: harvest assertions → write pytest → mark-for-deletion → delete only after the replacement is online + green. Removing migrated/superseded test code = permitted source edit. |
| **D3** | Manager topology | **Flat** — Tiberius manages the authors directly; Tiffany = lead author (partitions modules + senior review). Tiered (Tiffany-as-sub-manager) reserved for a 6+ fleet; nested-spawn reaping unverified. |
| **Heartbeat** | Keep-alive mechanism | **New `heartbeat_poker_job`** + commons gateway (old `cascade_heartbeat_scheduler.py` as hot fallback). **HARD prerequisite** before spawning the fleet: idle headless workers only wake via push (`commons_send_to`), NOT blackboard `commons_post` (verified 2026-05-30 — see `feedback_waking_idle_spawned_sessions.md`). |
| **D5** | Quality guardrails | Strict, non-negotiable: meaningful assertions only, NO padding, NEVER edit source to inflate coverage, DbC docstrings, same-line-reasoned pragmas only. Plus a **dedicated adversarial reviewer persona** scored on **valid** hollow-tests-caught (authors may contest; Tiberius arbitrates borderline → guards against over-rejection to pad the score). |
| **D6** | Commit authority | **Standing TEST-ONLY batch-commit authority granted to Tiberius** for the overnight grind: new/changed tests + `[tool.coverage]` config + removal of migrated/superseded test code; **ZERO production-logic edits**; on `wip-v0.1.8`; each batch green-gated. Bounded, reversible exception to the no-auto-commit rule, scoped to this campaign. |
| **D7** | Verification cadence | **Per-batch green-gate** (full unit suite passes before commit) + **periodic combined re-measure** to track real coverage vs target. |
| **D8** | Deadline framing | **Milestone ramp** (not hard-100%-by-06-05, which is unreachable by hand at ~15-40 grind-days): config + library tier firm by 06-05; agents + REST targets set from the combined evidence + observed fleet throughput; published schedule. |
| **Fleet** | Structure | **3 authors, partitioned by disjoint module-group**, test-only direct commits (collision-free by construction — no shared files). Shared fixtures/`conftest` need light coordination. |
| **Reviewer** | Flow | **Reviewer gates commits, batched per module-group** — author finishes a group → reviewer audits batch for hollow/padded tests → only reviewer-approved + green batches commit. Keeps the branch clean unattended overnight. |

---

## 3. Tiering & remaining items

- **D4 — Tiering / sequencing — RESOLVED 2026-05-30 (evidence-shaped):**
  1. **Tier 1 — library (06-05 milestone, best ROI, fully unit-only):** memory (~1,785) + repo (1,772) + utils (~432) + config (102) + tools (61) + crud (33) ≈ **4,185 lines**.
  2. **Tier 2 — agents (the long pole, ramped):** ~**8,365** unit-only lines (server barely touches it; LLM/mock-heavy). Split across ≥2 authors.
  3. **Tier 3 — REST unit-only remainder + orchestration (~291):** REST is small now under the hybrid credit; orchestration is unit-only.
  - The flat 3-author fleet partitions disjoint module-groups within each tier.
- **Per-tier target dates** — Tier 1 by 06-05; Tiers 2-3 on a published ramp set from observed fleet throughput (D8).
- **Clean E2E re-run (flagged by Tiffany):** the combined run's 31 E2E failures / 26 errors trace to a **parallel session's uncommitted edits** to `test_cc_session_strip_and_focus.py` + `test_commons_activity_toggle.py` (cc-session-strip + broadcast-toggle UI mid-edit) — NOT coverage/our regression. Schedule a clean un-instrumented :8000 E2E once that session lands, to get a valid verdict. Integration was clean (248 passed).
- **Grind kickoff timing** — off-peak window (post-midnight EDT) per the Max-plan rolling-window rule; server is exclusively ours today + tonight.
- **Overnight check-in cadence / morning handoff** — default: authors report per module-group to `dm-tiberius`; Tiberius posts periodic progress + a morning summary for Rick.

---

## 4. Evidence run (IN FLIGHT)

Combined unit + :8000 integration/E2E coverage measurement — authorized by Rick's **direct USER BROADCAST** to Tiffany (a peer relay did NOT satisfy the shared-infra-mutation governance gate; correct enforcement of the `:8000`-human-only rule). Mechanism (staged by Tiffany in `/tmp`, executing now):

1. Back up `run-fastapi-lupin-test.sh` (revert path secured) → swap in coverage-instrumented startup (`coverage run --rcfile=coverage-server.rc -m fastapi_app.main`, writing parallel data to `/var/lupin/io/coverage/`, host-visible + gitignored).
2. `coverage-server.rc`: branch + parallel + sigterm-flush + thread concurrency, `source=cosa`, **same Tier-0 omit/exclude denominator** so the combined number is apples-to-apples with the 45.3% unit baseline.
3. Bounce `lupin-rest-test` → run integration + E2E → graceful stop (flush) → path-aliased `coverage combine` with the unit `.coverage`.
4. Emit per-module **INTEG_NEW** delta (lines executed in combined but NOT unit-only — agents / rest / orchestration). **Caveat (labeled):** threaded-async uvicorn coverage may undercount → delta reads pessimistically.
5. **REVERT** `run-fastapi-lupin-test.sh` afterward (don't leave the test container under coverage).

This delta settles D1 (which lines integration already covers → don't write redundant unit tests for them) and finalizes D4.

---

## 5. Execution sequence (post-evidence)

1. **Tier 0 config** — land the `[tool.coverage]` config (currently staged as a measurement proposal; commit once Rick blesses the denominator, which he did via D2).
2. **Stand up + VERIFY the heartbeat poker** — hard gate before spawning the fleet (else workers idle after each task, unreachable by blackboard).
3. **Spawn the fleet** — 3 author personas + 1 adversarial reviewer persona; partition by disjoint module-group from the evidence-finalized tier order.
4. **Grind** — authors write pytest tests (harvesting legacy tests first, marking superseded ones for delete-after-green); per module-group: reviewer-gate → green-gate → test-only commit.
5. **Track** — periodic combined re-measure; milestone-ramp progress posted to `dm-tiberius` + summarized for Rick.
6. **Cleanup** — delete superseded legacy/smoke blocks after their replacements are online + green; retire the `exclude_also` regex once all smoke blocks are ported.

---

## 6. Guardrails recap

- Meaningful tests only; no padding; never edit production logic to game coverage.
- Same-line-reasoned `# pragma: no cover` only for genuinely-unreachable defensive branches.
- `:7999` for unit/coverage; `:8000` only under Rick's direct authorization (exclusive grant today/tonight).
- Test-only commits; per-batch green-gate + reviewer-gate.
- All worker coordination via **push-DM** (`commons_send_to`), never blackboard, for idle sessions.

---

## 7. Live-E2E regression test (campaign task — Rick-greenlit 2026-05-30)

The `HeartbeatPokerJob` **class logic** is already covered (unit + smoke + integration + e2e + factory tests using an injectable `FakeClock` + fake gateway → cadence / dead-man / 3-exit math without real waiting). What's missing is a **live regression** that keeps the real chain working over time:

- **Scheduled `:8000` E2E, lightweight scripted stand-in recipient** (a tiny process that posts-when-poked): real `CommonsGateway` push → recipient receives heartbeat → posts → poker scores it → streak resets → clean exit on `stand_down`. Plus a **silent-recipient variant** → assert the dead-man's-switch escalation fires. Robust + repeatable (no tmux flakiness).
- Keep the full "wake a real **tmux** CC session" path as a **rarer, separately-tagged live check** — NOT in the every-run gate (the tmux-wake is the flaky part).
- Sequencing: author this once the manual combined-coverage measurement (in flight) has validated the live push→wake→detect chain end-to-end. Owner TBD (fleet author or dedicated step).

## 8. Reusable workflow capture (María 🌸 — Workflow Steward)

María loops in NOW (run → learn → codify; cascaded-plan-review precedent) to observe this first live run and later author a reusable cross-repo workflow other repos' CC instances can adopt: **"heartbeat-poker-supervised overnight fleet grind."**

- **Vocabulary:** captured as a **workflow / practice**, NOT "doctrine" (Rick's standing preference). Campaign artifacts use "workflow capture" framing.
- **Timing:** author the reusable workflow ONLY after end-to-end validation — premature generalization bit the loc-delta tool's first cut. Light orientation now; substantive authoring held until battle-tested.
- **Empirical anchors to capture:** flat-vs-tiered fleet topology (chose flat @ ~3); **push-not-blackboard waking** (idle sessions only wake via `commons_send_to`; ~3h strand today); heartbeat-poker manager-tap + dead-man's-switch; adversarial-reviewer-scored-on-valid-catches; **shared-infra governance gate** (Tiffany refused a peer-RELAYED `:8000` authorization — required Rick's DIRECT word). The governance instinct is the reusable signal worth codifying.
