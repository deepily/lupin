# 04 — Execution Orchestration: Closing out the 2026.04.27 incident

**Status**: Active execution plan
**Companion to**: `01-design.md` (the source plan), `90-execution-log.md` (per-WG status)
**Created**: 2026-04-28 13:50 EDT (post-checkpoint `c4e5d4f`)

## Context

The autonomous-pass checkpoint (`c4e5d4f`) landed Phase 0 + WG-2/3/4/5/7/8b/9 as code; WG-1's Dockerfile edit landed but the actual image rebuild is deferred for the user to time. Plus 4 OOS proposals exist as plan-only docs awaiting ratification, and several follow-up cleanups remain (push, CoSA submodule, pre-existing files).

User has already manually nuked the 9 dead jobs + 1 wedged Calculator on `:8000` (WG-8a complete). This doc orchestrates the remaining work into 4 sequential phases with explicit parallelism windows.

## Roles

- **[USER]** — work the user must do (long-running, host-resource-heavy, mutates shared infra, decision call, or rule-forbidden for Claude per `feedback_lupin_only_never_cosa` / `feedback_never_auto_commit_push` / `feedback_no_auto_promote_tags`).
- **[CLAUDE]** — work I can do autonomously (read, edit, test on `:7999`, draft).
- **[BOTH]** — collaborative; user makes a decision, I execute.

## Phase A — Image rebuild + baseline regen + green-light gate

**Goal**: Rebuild image with fonts, regenerate baselines, verify visual-regression all green.

| Step | Party | Action | Blocks | Parallel-safe with |
|------|-------|--------|--------|---------------------|
| **A1** | [USER] | `docker build -f docker/lupin/Dockerfile -t lupin:1.0.0-fonts .` | A5, A6, B1 | A2, A3, A4 |
| **A2** | [CLAUDE] | Pre-rebuild `:7999` sanity baseline — run unit suite + websocket smoke; record counts so post-rebuild we can detect regressions. | — | runs during A1 build |
| **A3** | [CLAUDE] | Audit the 5 pre-existing files (`notifications.css/html/js`, `session_bridge.py`, `test_session_bridge_lookup.py`) — find which prior session left them. | — | runs during A1 build |
| **A4** | [BOTH] | Discuss + flip TFE voice-gate timeout policy default. (Answer: keep `stall` or set `top_1`?) | — | runs during A1 build |
| **A5** | [USER] | Bump `docker-compose.yml` lines 34 + 98 → `image: lupin:1.0.0-fonts` and `docker compose up -d --force-recreate lupin-rest-dev` (note: NOT `docker restart`; new mounts/image require recreate). | A6 | — |
| **A6** | [CLAUDE] | Regenerate visual baselines: `./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual`. Monitor `/tmp/e2e-ui-latest.log`. ~3-5 min. | A7 | — |
| **A7** | [CLAUDE] | Visual regression verification: `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual`. Acceptance: 0 ERRORs across all 12 pages. | A8 | — |
| **A8** | [USER] | Promotion call: retag `lupin:1.0.0-fonts` → `lupin:1.0.0` (per `feedback_no_auto_promote_tags`, never auto). Optionally bump compose back to plain `:1.0.0`. | B-phase | — |

**Phase A success criteria**: All 12 visual-regression pages PASS on `:7999` with the new image; `lupin:1.0.0` tag points to the font-fixed build.

---

## Phase B — `:8000` verification re-run + survivor analysis

**Goal**: Re-run the original failing 22:35 test suite against the fixed image; verify the 23 F + 19 E count drops to ≤ 2 FAILs; analyze any survivors.

| Step | Party | Action | Blocks | Parallel-safe with |
|------|-------|--------|--------|---------------------|
| **B1** | [USER] | Pick a non-overlapping `scheduled_at` slot (`:8000` is monopolize-mode). | B2 | C-phase prep |
| **B2** | [USER] | Submit `POST /api/test-suite/submit { test_types: "all", auto_fix_on_failure: false, scheduled_at: <slot> }`. | B3 | — |
| **B3** | [CLAUDE] | Monitor the run (~75 min based on the 22:35 timing). | B4 | C1-C3 (commits + push) |
| **B4** | [CLAUDE] | Read all-results report. Count P/F/E/S. Classify any survivors. | B5 | — |
| **B5** | [CONDITIONAL] | If `test_notification_proxy_script_matching` and/or `test_tfe_error_capture_smoke` still fail → trigger OOS-3 plan (Phase D). | D-phase | — |

**Phase B success criteria**: e2e ERRORs = 0 (visual baselines fresh); smoke FAILs ≤ 2 (only WG-6 survivors permitted, if any); websocket suite classified PASS (not 0/0/0/0); 0 jobs orphaned in run.

---

## Phase C — Commits, push, cleanups (parallelizable with B)

**Goal**: Land all the autonomous-pass work outside the parent Lupin checkpoint, plus tidy up the working tree.

| Step | Party | Action | Notes |
|------|-------|--------|-------|
| **C1** | [USER] | CoSA submodule commit: `cd src/cosa && git add … && git commit -m …`. 6 files: `training/peft_trainer.py`, `agents/test_fix_expediter/{config,orchestrator}.py`, `agents/test_suite/job.py`, `rest/{running_fifo_queue,queue_consumer}.py`. (Per `feedback_lupin_only_never_cosa`, I cannot do this from parent.) | Standalone CoSA-context session needed. |
| **C2** | [USER] | Push parent: `git push origin wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`. (Per `feedback_never_auto_commit_push`, I cannot do this autonomously.) | After C1 ideally — submodule pointer should be in sync. |
| **C3** | [BOTH] | Triage 5 pre-existing files. Output of A3 audit will tell us which prior session they belong to. Options: (a) ask the prior session's owner to commit them, (b) commit them in this session if they're orphaned, (c) revert if unwanted. | Decision after A3 evidence. |

**Phase C success criteria**: Working tree only has `:memory:/` stray dir left; both parent + submodule are committed + pushed.

---

## Phase D — OOS ratification + per-OOS implementation

**Goal**: Decide which OOS items to implement and in what order; then execute each as its own plan-mode cycle.

| OOS | Recommended order | Why |
|-----|-------------------|-----|
| **OOS-1** | 1st | Highest leverage. Without it, every TFE run produces inflated proposal lists with false-zero clusters. The 22:35 incident exposed it directly. |
| **OOS-4** | 2nd | Defensive — finds the rogue dead-queue routing path that bypasses `_transition_to_dead`. Subsumes WG-8c. Class-of-bugs fix. |
| **OOS-2** | 3rd | Pure refactor (websocket pytest+junit-xml). Eliminates WG-7's stdout-pattern fallback as a maintenance trap. Lower urgency. |
| **OOS-3** | Conditional | Only if Phase B surfaces non-trivial WG-6 survivors. Likely 0 effort if Phase B is clean. |

| Step | Party | Action |
|------|-------|--------|
| **D1** | [USER] | Per OOS: ratify the plan (or request edits). |
| **D2** | [CLAUDE] | Per ratified OOS: enter plan-mode cycle, write the code, run the tests, checkpoint. |

Each OOS is **its own** plan-mode + ratification + code-write cycle. Don't bundle.

**Phase D success criteria**: OOS-1 + OOS-4 land; OOS-2 in queue (lower priority); OOS-3 closed (either zero work needed or escalated to its own bug-fix-mode).

---

## Critical-path summary

```
A1 (build, ~30 min) ──→ A5 (recreate) ──→ A6 (regen) ──→ A7 (verify visual) ──→ A8 (promote)
                                                                                       │
                                                                                       ▼
                                                                          B1 (slot) ─→ B2 (submit) ─→ B3 (monitor, ~75 min) ─→ B4 (analyze)
                                                                                                                                       │
                                                                                                                                       ▼
                                                                                                                            B5 (OOS-3 trigger? cond.)

PARALLEL during A1:        A2 (sanity baseline) ‖ A3 (file audit) ‖ A4 (TFE policy chat)
PARALLEL during B3:        C1 (CoSA commit) ‖ C2 (push) ‖ C3 (pre-existing triage)
```

**Total elapsed**: ~30 min (build) + ~5 min (compose recreate + baseline regen) + ~5 min (verify) + slot-wait + 75 min (re-run) + analysis ≈ 2 hours of wall clock + scheduling waits.

**Total active human time**: probably 15-20 minutes (kicking off the build, swapping compose, retagging, scheduling, ratifying).

## What's NOT in this plan

- Implementing the OOS items themselves — each gets its own plan cycle in Phase D2, post-ratification.
- Live UX validation (a separate non-blocking task already in TODO.md).
- The PIP cross-project plan-review lift (TODO.md item #1, separate `planning-is-prompting`-rooted session).
