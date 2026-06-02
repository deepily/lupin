# CoSA Coverage Campaign — Cold-Start Operator Runbook

**This is the STANDALONE execution doc.** A manager coming in cold (after a `/clear`) or a freshly-spawned author/reviewer worker should be able to run the entire campaign from THIS file alone, with **zero reliance on any session's chat history**. It inlines every command, threshold, gate, and contingency. `00-campaign-plan.md` is the decision-of-record (the *why*); this runbook is the *how*. Where they ever disagree, the ratified decisions in `00` win — flag the drift and reconcile.

**Status:** drafted 2026-05-30 by María 🌸 (Workflow Steward, PIP session `42a02847`) per Rick's direct Step-2 authorization, relayed + co-specced by Tiberius 👑. Framed as **workflow / practice** (not "doctrine").

**Branch:** `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment` · **Repo:** `lupin` (CoSA is in-tree at `src/cosa/` post 2026-05-29 mono-repo fold).

---

## 0. TL;DR — what to do, in order

1. **Confirm you're on the right branch** and `LUPIN_ROOT` is set (`echo $LUPIN_ROOT`).
2. **Land Tier-0 `[tool.coverage]` config** (denominator already blessed via D2) — see §6.
3. **Stand up + VERIFY the heartbeat poker** (§7) — **HARD GATE**: the push-wake primitive is already live-proven, but the poker-job loop (cadence→detect→escalate→stand_down) is **static-verified only** — run ONE live poker tap (§7.3) before spawning workers / trusting it overnight. Idle headless workers wake ONLY via push-DM, never blackboard.
4. **Spawn the fleet** (§8): 3 author personas + 1 adversarial reviewer, partitioned by disjoint module-group from the Tier order (§5).
5. **Run the grind loop** (§9) per module-group: author writes pytest → reviewer-gate → green-gate → test-only commit.
6. **Re-measure + ramp** (§10–11); post progress to `dm-tiberius`; morning summary for Rick.
7. **On stand-down**: post the `stand_down` signal (§7.4), reap workers (§8.3), revert any instrumented infra (§13).

**Two rules you must never break:** (a) **never edit production logic** to move coverage — tests + `[tool.coverage]` config + removal-of-migrated-test-code ONLY; (b) **`:8000` (the integration/E2E server) is mutated only under Rick's DIRECT word** — a peer relay does NOT authorize it (§12).

> **⚠️ CANONICAL INTERPRETER (added 2026-05-30, live-discovered by the fleet).** Run ALL pytest/coverage via the **cosa venv (Python 3.11 / pytest 9.0.2)**, NOT the lupin `.venv` (Python 3.13 / pytest 8.4.2). The 3.13 venv's pytest 8.4.2 throws `INTERNALERROR: 'tuple' object has no attribute 'value'` (`_pytest/unittest.py:382`) the instant ANY `unittest.TestCase` test fails — it silently MASKS every red, so a "green" run there is meaningless. Canonical green-gate / coverage invocation:
> ```bash
> PYTHONPATH=src src/cosa/.venv/bin/python -m pytest src/tests/unit/ src/cosa/tests/unit/ -q
> PYTHONPATH=src src/cosa/.venv/bin/python -m pytest src/cosa/tests/unit/ --cov=cosa.<group> --cov-report=term-missing -q
> ```
> **Also: "5,471 tests collected, 0 errors" is COLLECTION, not green.** Under the cosa venv the legacy baseline is heavily RED (memory alone = 91 failed / 24 passed as of 2026-05-30) — assertion-drift / stale mocks from before the mono-repo fold. Treat baseline reds as **repair targets** (fix the stale test to match the documented contract — NEVER rewrite an assertion to ratify buggy prod output; escalate genuine prod bugs to the manager per §11). A green baseline must precede coverage-add for a group.

---

## 1. Goal & methodology

**Goal:** ramp `src/cosa/` toward the **Lupin-wide 100% coverage mandate** (line + branch + function) on a **grandfathering ramp**. Deadline framing is a **milestone ramp**, NOT hard-100%-by-2026-06-05 (unreachable by hand at ~15–40 grind-days): the config + library tier are firm by 06-05; agents + REST targets follow a published ramp set from observed fleet throughput.

**Methodology — HYBRID (D1, evidence-confirmed 2026-05-30):**
- **REST is credited to the server suites** (integration/E2E executes it). The combined run showed REST = +1,776 lines, ~70% of the whole integration delta → do NOT write redundant unit tests for REST lines the server suites already cover.
- **Everything else is unit-only**: `agents`, `memory`, `repo`, `orchestration`, `utils`, `config`, `tools`, `crud`. (Orchestration's server-delta was **+0** — the "integration-likely" guess was refuted; it's unit-only.)

**Measurement ports:** unit/coverage on **`:7999`**; integration/E2E on **`:8000`** (governance-gated, §12).

---

## 2. Baseline & target (the number you're moving)

| Metric | Value | Source |
|---|---|---|
| Unit-tier baseline | **45.3% line / 34.8% branch** | `:7999`, measurement-corrected (raw 26.9% was denominator-inflated; pure config hygiene fixed it, zero tests) |
| Combined (unit + integ/E2E) | **52.0% line / 41.7% branch** | lower bound — threaded-async uvicorn coverage may undercount |
| Remaining target | **≈ 19,659 missing lines + 7,247 missing branches across 408 files** | post-Tier-0 denominator |

Re-measure periodically (§10) to track real coverage against these numbers. Baseline detail: `01-baseline-and-denominator.md` (relocating into this dir once Tiffany's run finalizes; until then at `../2026.05.30-cosa-100pct-coverage-baseline.md`).

---

## 3. Denominator (D2) — what counts, what's excluded, what gets migrated

**Excluded from the denominator (Tier-0 cleanup, blessed):**
- Test files themselves.
- `training/` (GPU code — the never-grab-GPU mandate; same-line-reasoned exclusion).

**Scaffolding to harvest → migrate → delete (NOT permanently excluded):**
- `quick_smoke_test` blocks and `if __name__ == "__main__":` blocks: harvest their assertions → write real pytest → mark the old block for deletion → **delete only after the pytest replacement is online + green**. Retire the `exclude_also` regex once all are ported.
- **All legacy tests** (non-pytest unit/integration, standalone scripts): same pipeline — harvest → pytest → mark-for-delete → delete-after-green.

**Permitted source edit (the ONLY one):** removing migrated/superseded **test** code after its replacement is green. This is not a production-logic edit.

---

## 4. Roles & topology (D3 — flat)

| Role | Who | Responsibility |
|---|---|---|
| **Manager** | Tiberius 👑 (this seat — may be a cold-rehydrated session) | Directs authors, gates commits, holds the heartbeat poker, posts progress + morning summary, arbitrates reviewer/author disputes |
| **Lead author** | Tiffany 💍 | Partitions modules into disjoint groups, senior review, owns shared fixtures/`conftest` coordination |
| **Authors ×3 total** | Tiffany + 2 spawned | Write pytest per assigned disjoint module-group |
| **Adversarial reviewer ×1** | spawned persona | Audits each batch for hollow/padded tests; **scored on VALID hollow-tests-caught**; authors may contest; Manager arbitrates borderline (guards against over-rejection to pad the score) |

Tiered topology (Tiffany as sub-manager) is reserved for a **6+** fleet — nested-spawn reaping is unverified; do not use it here.

---

## 5. Tier plan & 3-author disjoint partition (D4 — evidence-resolved)

Authors are partitioned by **disjoint module-group** → test-only direct commits are **collision-free by construction** (no shared files). Only shared fixtures/`conftest` need light coordination (route through Tiffany).

| Tier | Scope | ~Missing lines | Sequencing |
|---|---|---|---|
| **Tier 1 — library** (best ROI, fully unit-only) | memory (~1,785) + repo (1,772) + utils (~432) + config (102) + tools (61) + crud (33) | **≈ 4,185** | **Firm by 2026-06-05** |
| **Tier 2 — agents** (the long pole; LLM/mock-heavy; server barely touches it) | agents | **≈ 8,365** | Ramped; **split across ≥2 authors** |
| **Tier 3 — REST unit-only remainder + orchestration** | REST remainder (small under hybrid credit) + orchestration (~291, unit-only) | small | Last |

**Concrete Tier-1 partition template** (disjoint — adjust counts to live `coverage report`):
- **Author A:** `memory` (~1,785)
- **Author B:** `repo` (1,772)
- **Author C (Tiffany/lead):** `utils` + `config` + `tools` + `crud` (~628) **+** floats to the heaviest remaining group / owns shared fixtures.

For Tier 2, split `agents` by sub-package (e.g. router/agent-base vs. concrete agents vs. LLM-client mocks) so the three authors stay disjoint.

---

## 6. Tier-0 config (do this first)

Land the `[tool.coverage]` config (denominator per D2 — already blessed by Rick). It's currently staged as a measurement proposal; commit it as the first test-only batch. This sets `source = cosa`, the Tier-0 `omit` (test files, `training/`), and the `exclude_also` regex for the not-yet-migrated scaffolding blocks.

---

## 7. The heartbeat poker (keep-alive supervision)

The poker taps the **manager** on a cadence so a long unattended grind doesn't strand. It is a CJ-Flow agentic job; the **class logic is already covered** (unit + smoke + integration + e2e + factory tests via an injectable `FakeClock` + fake gateway). What you instantiate here is a **live** run.

### 7.1 Exact invocation (code-grounded — `cosa/rest/agentic_job_factory.py` → `HeartbeatPokerJob`)

```python
from cosa.rest.agentic_job_factory import create_agentic_job

job = create_agentic_job(
    command   = "agent router go to heartbeat poker",
    args_dict = {
        "recipients": [
            { "identifier": "tiberius", "identifier_type": "persona", "role": "manager" },
        ],
        "cadence_seconds"          : 300,                       # campaign default (factory default is 180); relax further overnight if steady
        "termination_topic"        : "coverage-campaign-control",
        "termination_signal_kinds" : [ "stand_down" ],          # list OR comma-string both accepted
        "workstream_id"            : "cosa-coverage-campaign",
        # optional (defaults shown): "deadman_consecutive_pokes": 3, "max_duration_seconds": 43200
    },
    user_id    = "<rick_user_id>",                              # resolve to Rick's authenticated OWNER user_id at submit (owner-resolution) — NEVER the service account
    user_email = "ricardo.felipe.ruiz@gmail.com",
    session_id = "<manager_session_id>",                        # the gateway auto-wires from this
)
```

The factory auto-wires `commons = LupinCommonsGateway.from_environment( sender_session_id=session_id )`. Gateway class: `cosa/agents/heartbeat_poker_commons_gateway.py`. Job class: `cosa/agents/heartbeat_poker_job.py`.

### 7.2 How it behaves

- **Poke = push-wake.** Each cadence tick, `send_to(<recipient>)` posts to `dm-<slug>` **and** fires `/api/commons/register-question` — the `register-question` call is the actual **wake-push** that reaches an idle headless session (a blackboard `commons_post` alone would NOT wake it — see §8.2).
- **Streak reset.** `last_post_ts` reads the **global** `commons_who()` → **ANY** commons post by the recipient (to any topic) resets the manager's silence streak. The manager just has to be visibly active on commons.
- **Dead-man's-switch.** After **3 consecutive silent pokes**, it **escalates** (fires a `notify()` alarm) but **never auto-exits** — silence may just mean heads-down tool work; the human is the brake, not the engine.
- **Hard cap.** `max_duration_seconds` (default 43,200 = 12h) is defense-in-depth.

### 7.3 VERIFY before spawning the fleet (HARD GATE)

**Verification status — be precise; a cold operator decides trust from this:**
- **Push-wake primitive — LIVE-PROVEN (2026-05-30):** a `commons_send_to` → `/api/commons/register-question` push woke an idle headless session (Tiffany's), observed directly. The wake mechanism works.
- **Poker-job loop end-to-end — STATIC-VERIFIED ONLY:** the cadence → detect → escalate → `stand_down` chain is covered by unit/smoke/integration/e2e/factory tests (injectable `FakeClock` + fake gateway), but has NOT been run live against real wall-clock + real sessions. The combined-coverage measurement did **NOT** exercise the poker — that run was coverage instrumentation, no poker involved.

**Therefore, before trusting the poker unattended overnight, run ONE live poker tap** — the §7 live-E2E / lightweight scripted stand-in recipient (a tiny process that posts-when-poked): real push → recipient posts → poker scores it → streak resets → clean exit on `stand_down`; plus the silent-recipient variant to confirm the dead-man's-switch escalation fires. This live-verify is the HARD gate; do not skip it on the first live run.

### 7.4 Stand-down (clean exit)

Post the termination signal to the watched topic:

```python
commons_post(
    topic    = "coverage-campaign-control",
    body     = "campaign complete — standing down the poker",
    metadata = { "kind": "stand_down" },
)
```

The poker sees a `stand_down`-kind post on `coverage-campaign-control` → stops poking → exits 0.

---

## 8. Worker lifecycle

### 8.1 Spawn
Use `spawn_sessions` to bring up the 3 author personas + 1 reviewer. Give each a cold-readable seat brief that points at **this runbook** + its assigned disjoint module-group (§5).

### 8.2 Wake / dispatch — PUSH, never blackboard (load-bearing)
**Idle headless (spawned) sessions wake ONLY via push** — `commons_send_to(recipient=<persona>, body=...)`. A blackboard `commons_post` does **NOT** wake an idle session; it sits unread until that session happens to poll. This stranded a dispatch ~3h on 2026-05-30 (`feedback_waking_idle_spawned_sessions.md`). Every task hand-off and every nudge to an idle worker is a push-DM.

### 8.3 Reap — HARVEST-ON-UNPRODUCTIVE (mandate, not optional)
Harvest a worker the MOMENT it stops contributing — honest-stopped, stalled, context-saturated, superseded by a fresh spawn, or done with its tier. Do NOT let idle/parked workers accumulate. **Leading-indicator ALARM:** when fresh spawns start landing on `extra-N` personas, the named persona pool is EXHAUSTED → harvest is overdue → reap before spawning more.

**The reap + its known trap (learned 2026-06-01 — see `17-session-end-100pct-wrap-and-reap-explanation.md`):**
- **Clean path:** `dismiss_sessions(session_names=None)` reaps ALL of this manager's spawns incl. their listeners (no zombies).
- ⚠️ `dismiss_sessions(session_names=[...])` (targeted/list form) is **BUGGED** on the running server — the untyped FastMCP param char-iterates the list → every entry is one char → no-op. Fix committed (`3488b43`) but needs an MCP-server **RESTART** to go live. Until then targeted reap silently does nothing.
- **tmux-kill workaround** (`tmux kill-session -t cc-<role>-<mgr>-N`) orphans the session's voice **listener** (PG-6 zombie) → you MUST also `kill` the matching `cc_notification_listener` proc (match by `--session-id`), and NEVER kill the live human / manager / steward listeners.
- ⚠️ **Killing the orphaned listener: use SIGKILL by exact PID, not SIGTERM.** The listeners **ignore SIGTERM** (a plain `kill` is a silent no-op). Resolve PIDs with `pgrep -af cc_notification_listener` (note: bare `pgrep cc_notification_listener` without `-f` matches comm=`python3` → returns 0; always use `-f`), exclude the keep-`--session-id`s, then `kill -9 <pids>`. Verify Z-state separately: `ps -eo stat | grep -c Z`.
- ⚠️ **"They came back after I restarted FastAPI" ≠ respawn — it's orphans RECONNECTING.** Orphaned listeners are live daemons that re-establish their :7999 WS on server restart, so they reappear in the notifications client looking un-reaped (they were never state-Z zombies). Same PIDs across the restart = orphans, not new procs. SIGKILL-by-PID is the fix; then the client clears on next refresh (they can't reconnect once dead).
- If no clean-reap is available, **escalate the MCP-restart to the user EARLY** — do NOT silently park-and-accumulate (2026-06-01: ~14 sessions gathered dust because the restart wasn't pushed for in time; my own miss).

Reap before the host accumulates phantom bridges.

---

## 9. The grind loop (per module-group)

For each disjoint module-group, the assigned author runs:

1. **Harvest first.** Before writing new tests, harvest assertions from any legacy test / smoke / `__main__` block covering this module (D2). Mark the superseded block for deletion (don't delete yet).
2. **Write pytest** — meaningful assertions only; DbC docstrings; **NO padding**; **NEVER edit production logic** to move coverage; `# pragma: no cover` only on genuinely-unreachable defensive branches, **same-line-reasoned**.
3. **Reviewer-gate.** The adversarial reviewer audits the batch for hollow/padded tests. Only reviewer-approved batches proceed. Author may contest; Manager arbitrates borderline.
4. **Green-gate.** Full **unit** suite passes on `:7999` before any commit (D7).
5. **Test-only commit** (Manager's authority, §11). Then **delete** the marked-superseded legacy/smoke blocks — only now that the pytest replacement is online + green.
6. Report the module-group result to `dm-tiberius`.

---

## 10. Verification & re-measure cadence (D7)

- **Per-batch green-gate** (above) — non-negotiable before every commit.
- **Periodic combined re-measure** — re-run the combined (unit + integ/E2E) measurement occasionally to track real coverage vs. the §2 target and to confirm the hybrid credit still holds as tests land. The combined run requires `:8000` → governance-gated (§12).

---

## 11. Commit authority (D6) — scope

**Standing TEST-ONLY batch-commit authority is granted to the Manager (Tiberius)** for the overnight grind. A batch may contain ONLY:
- new / changed **test** files,
- `[tool.coverage]` config,
- **removal of migrated/superseded test code** (after its replacement is green).

A batch may contain **ZERO production-logic edits**. Commits land on `wip-v0.1.8`; each batch is green-gated + reviewer-gated. This is a **bounded, reversible** exception to the no-auto-commit rule, scoped to this campaign. If a coverage gap genuinely requires a production change (e.g., an untestable seam), STOP and escalate to Rick — do not edit production logic to close it.

---

## 12. Governance gates — calibrated to blast radius

The authorization bar **scales with reversibility / blast radius** (the reusable governance principle this campaign surfaced):

| Action | Bar |
|---|---|
| **Irreversible / shared-infra mutation** (e.g., bouncing or instrumenting the `:8000` integration server) | **Rick's DIRECT word** (a USER BROADCAST or direct message). A peer RELAY does NOT satisfy it. Tiffany correctly refused a peer-relayed `:8000` authorization on 2026-05-30 — that's the gate working as intended. |
| **Reversible doc-authoring / test-writing under an explicit current user instruction** | The Manager's honest confirmation suffices. |
| **Unit/coverage measurement** | `:7999` — freely, it's ours. |

When in doubt about which bucket an action falls in, treat it as the higher bar and ask.

---

## 13. Revert procedures

**Coverage-instrumented `:8000` server** (used only during a combined re-measure):
1. Before instrumenting, the runner backs up `run-fastapi-lupin-test.sh` (revert path secured).
2. Instrumented startup writes parallel data to `/var/lupin/io/coverage/` (host-visible + gitignored).
3. **After measuring, REVERT** `run-fastapi-lupin-test.sh` — never leave the test container running under coverage. Restore from the backup.

**Contingency: container left instrumented** → run the revert (restore the backed-up `run-fastapi-lupin-test.sh`) and bounce `lupin-rest-test` back to its normal startup.

---

## 14. Contingency tree

| Symptom | Action |
|---|---|
| Worker idle / stalled / unresponsive | **Push-DM** it (`commons_send_to`) — never blackboard. If still silent after a push, check for a phantom bridge (`commons_who(retention_hours=1)`); reap + re-spawn if dead. |
| A batch goes **red** (unit suite fails) | **Do NOT commit.** Fix the failing test (or revert the offending test addition); re-run the green-gate; only commit when green. |
| `:8000` container left **instrumented** under coverage | Run the revert script (§13); bounce `lupin-rest-test`. |
| **Poker dies** / stops tapping the manager | Fall back to the manual background-waiter backstop (old `cascade_heartbeat_scheduler.py` is the hot fallback) and re-launch the poker (§7); investigate the exit. |
| **Parallel-session E2E failures** during a combined run | Known noise vector: the 2026-05-30 run's 31 E2E failures / 26 errors traced to **another session's uncommitted edits** to `test_cc_session_strip_and_focus.py` + `test_commons_activity_toggle.py` — NOT a coverage regression. Schedule a **clean, un-instrumented `:8000` E2E** once that session lands to get a valid verdict. Integration (248 tests) was clean. |
| Dead-man's-switch fires (3 silent pokes) | It escalated, didn't kill the job. Check whether workers are genuinely heads-down vs. phantom; push-DM to confirm; decide whether to continue or stand down. |
| Uncertain whether an action needs Rick's direct word | Treat as the higher governance bar (§12); ask. |

---

## 15. Cold-start checklist (for a freshly-/clear'd manager)

- [ ] `echo $LUPIN_ROOT` set; on branch `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment`.
- [ ] Read THIS runbook end-to-end (you should need nothing else).
- [ ] Tier-0 `[tool.coverage]` config landed (§6).
- [ ] Heartbeat poker launched; **poker-job loop live-verified via one live tap — PENDING** (§7.3) before trusting unattended — HARD gate. (Push-wake primitive already live-proven 2026-05-30.)
- [ ] Fleet spawned: 3 authors + 1 reviewer, disjoint groups assigned (§5, §8.1).
- [ ] Each worker briefed to wake via push-DM and to follow the grind loop (§9).
- [ ] Grind running; per-batch reviewer-gate + green-gate enforced; test-only commits (§11).
- [ ] Progress posted to `dm-tiberius`; morning summary queued for Rick.
- [ ] Governance: no `:8000` mutation without Rick's direct word; no production-logic edits.
- [ ] On completion: `stand_down` posted (§7.4), workers reaped (§8.3), any instrumented infra reverted (§13).

---

## 16. Guardrails recap (D5)

- Meaningful tests only; **no padding**; **never edit production logic** to game coverage.
- DbC docstrings on test helpers; same-line-reasoned `# pragma: no cover` only for genuinely-unreachable defensive branches.
- `:7999` for unit/coverage; `:8000` only under Rick's **direct** authorization.
- Test-only commits; per-batch green-gate + reviewer-gate.
- All idle-worker coordination via **push-DM** (`commons_send_to`), never blackboard.
- **HARVEST is a mandate, not cleanup** (§8.3): reap unproductive / idle / superseded / context-saturated workers IMMEDIATELY; `extra-N` personas appearing = pool-exhaustion alarm = harvest overdue.
- **Mandated work is never user-gated** (`mandated-work-never-user-gated` memory): difficulty / lateness / size are NOT defer-triggers — finish in-scope work to conclusion. The user is gated ONLY for outward/irreversible acts (push), a real prod-behavior change, a genuine requirement ambiguity, or scope expansion. The early-stop valve trips only on a real prod bug (→ tripwire) or a true ambiguity (→ ask), never on complexity.
- **NEVER surface push-readiness** (`never-surface-push-readiness` memory): don't ask "ready to push?", don't say "held for your push", don't offer it. The push is the user's ALONE at session-end; held commits stay held SILENTLY.
- **Run the TREE-WIDE coverage gate before declaring "complete"** (`run-tree-wide-gate-before-coverage-complete` memory): assigned-lane 100% ≠ tree-wide 100% (FM-17: agent-pkg done ≠ its router-wrapper done). Read the full `--cov` TOTAL + every sub-100% row from the redirect log, not a grep-summary.

---

## Cross-references

- **Decision-of-record (the *why*):** `00-campaign-plan.md` (ratified D1–D8, fleet, reviewer, §7 live-E2E regression task, §8 workflow-capture role).
- **Baseline + denominator:** `01-baseline-and-denominator.md` (currently `../2026.05.30-cosa-100pct-coverage-baseline.md`).
- **Poker class spec:** `../2026.05.22-heartbeat-poker-d1d4-class-spec.md`; generic abstraction: `../2026.05.20-generic-heartbeat-poker-abstraction-design.md`.
- **Push-not-blackboard waking:** `feedback_waking_idle_spawned_sessions.md` (memory).
- **Code:** factory `cosa/rest/agentic_job_factory.py` (`agent router go to heartbeat poker` branch); job `cosa/agents/heartbeat_poker_job.py`; gateway `cosa/agents/heartbeat_poker_commons_gateway.py`.
- **Reusable cross-repo workflow** (authored AFTER end-to-end validation, NOT yet): "heartbeat-poker-supervised overnight fleet grind" — owner María 🌸 (Workflow Steward).

---

*Drafted by María 🌸 for review by Tiberius 👑. Structural note: this doc absorbs the `02-heartbeat-poker-run-config` slot the README reserved — the exact poker run-config lives in §7 here so the runbook stays standalone. Split it back out if you'd prefer a separate per-run config doc.*
