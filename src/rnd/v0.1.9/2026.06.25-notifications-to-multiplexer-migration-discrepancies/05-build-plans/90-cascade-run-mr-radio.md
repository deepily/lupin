# Cascade Run — Mux-Parity MVP Re-Review (canon-correct) — Manager: Mr. Radio 🦉

**Date**: 2026-06-27
**Manager**: Mr. Radio 🦉 (session f25224cf)
**Workflow**: `planning-is-prompting/workflow/plan-review-cascaded.md` (+ siblings) — the canonical cascaded plan-review.
**Why this run exists**: a prior run (session cd637762) ran the cascade WRONG (single reviewer doing all 3 stages serially; the prohibited Workflow tool with 24 invisible subagents; steward acting as content-gate). This is the clean, canon-correct restart. Postmortem: `planning-is-prompting/src/rnd/2026.06.27-cascade-review-orthodoxy-failures-postmortem.md`. Manager rehydration memento: `2026.06.27-cascade-restart-memento-mr-radio.md`.

---

## Cast Manifest

| Role | Persona | Spawn origin | Recycled? |
|---|---|---|---|
| Manager | Mr. Radio 🦉 (f25224cf) | pre-existing | — (orchestrator; no content opinions, no votes) |
| Author (revises plan per findings) | Tiffany 💍 (`cc-author-mr-radio-1`, ca5b9f03) — acked | on-demand `spawn_sessions` | — |
| Stage 1 Reviewer (Usability / Reuse) | `cc-reviewer-mr-radio-1` (chain: Krishna → Sam → Cheech → Rachel → Arnold → Rio → *) | on-demand `spawn_sessions` | — |
| Stage 2 Reviewer (Viability / Gap) | `cc-reviewer-mr-radio-2` | on-demand `spawn_sessions` | ✓ Step 0 light-reviewer (recycled) |
| Stage 3 Reviewer (Ownership-Language) | `cc-reviewer-mr-radio-3` | on-demand `spawn_sessions` | — |
| Step 0 light-reviewer | (= Stage 2 reviewer) | (recycled) | RECYCLED |
| Step 9 light-reviewer | (TBD at Step 8 — most-impacted-section reviewer) | (recycled) | RECYCLED |
| Workflow Steward (observer-only) | María 🌸 (4adceb0e) | pre-existing | NO findings, NO arbitration, NO citation-verification — process facilitation only (Rick's realignment) |
| Heartbeat Scheduler | **NONE — WAIVED by Rick** | — | Liveness via the **Arbiter (:8001)** + the heartbeat mechanism refined this week. NO `cascade_heartbeat_scheduler.py`, NO loops. (USER BROADCAST ddaa2882, 2026-06-27.) |

**TTS axis**: spawned reviewers come up speakerphone-OFF; comms are text via `dm-mr_radio`. Shoulder-tap a reviewer with `enable_speakerphone(session_id)` if needed.
**Stage→session assignment is authoritative via the manager's role-assignment DM** (the spawn brief tells each session to await it). Reviewer-index↔stage finalized at ack.

---

## Pre-cascade Recon Checklist (standing rules gating THIS cascade)

| Rule | Applies to THIS design? | Verification |
|---|---|---|
| **100% lines/branches/functions** (Convention 6 ACTIVE) | ✅ YES | Code under review is `multiplexer/**` TS → in scope. Mux TS via `c8 --100`; `c8 ignore` only for genuinely-unreachable defensive branches with a same-line reason. Every `EXECUTOR: AI` verification names its coverage-assertion shape. |
| **Chrome-only multiplexer** | ✅ YES | ZERO Firefox detection/branches; strip legacy Firefox on every port. (00c explicitly drops the RELIABLE/Firefox whole-buffer path — confirm.) |
| **Single-source CSS** (mandate 3) | ✅ YES | No forked CSS copy; new selectors land in `static/css/shared/notifications-surface.css`; legacy + mux both consume it. (00c has no CSS surface.) |
| **Venue routing** (mandate 4) | ✅ YES | :7999 AI-discretionary (unit/smoke/parity-harness/`c8`); :8000 scheduled via `POST /api/test-suite/submit` for E2E/visual/integration. Never side-door :8000. |
| **Visible sessions only** | ✅ YES | Cast = visible `spawn_sessions` Rick can see/DM/steer. NEVER Workflow tool / Task subagents (the prior run's fatal error). |
| **Commit/merge standing; PUSH is Rick's** | ✅ YES | This run REVIEWS plans; no code commits expected. Any landing later: commit+merge reviewed-green standing; push = Rick's word. |
| **No destructive git on shared tree** | ✅ YES | Reviewers read-only; repro in /tmp; never checkout/reset/stash/clean the working tree. |
| **Doc-viewer links in abstract** | ✅ YES | Any file reference in a user-facing abstract carries `[Open: …](/app/docs?path=lupin/…)`; never in spoken TTS. |
| **Lane isolation / manage-don't-build** (mandate 5) | ✅ YES | `AudioStore.ts`, `shared/types.ts`, `boot.ts`, `multiplexer.html`, `notifications-surface.css` are convergence files → manager-serial-merge. |

**LOAD-BEARING HYPOTHESES to verify (not assert):**
- **00c (P6-c) ownership boundary** — P6 is **id-blind-but-correlated**: EMITS `store_audio_ended` (signal-OUT only), NEVER calls `TtsQueueStore.advance()` and NEVER mutates the active-id; `TtsQueueStore` subscribes + self-advances. End-of-utterance is the **cited** server frame `audio_streaming_complete` (`speech.py:818-822` OpenAI / `:1115-1119` ElevenLabs ← `AudioTransport.ts:24`), **not** a silence heuristic. Verify in plan text + cited source.
- **01 (B4 / OQ-1)** — the active-spoken id is CLIENT-SIDE, owned by `TtsQueueStore.current()` (AudioStore id-blind); B4 must CONSUME `current()` id-blind, never re-source/mutate from AudioStore; field `Notification.id_hash` (`shared/types.ts:334` ← `routers/notifications.py:859`). Confirm or refute from the plan + source — do NOT take as fact.

---

## Resolved configuration (Step 1)

- Source: workflow defaults only — lupin `CLAUDE.md` has no `## [cascaded-plan-review] Overrides`; no invocation overrides.
- `reviewer_context_scope = narrow` · `discussion_turn_cap = 3` · `step_3_gate = cast_ratified` · `manager_push_frequency = per_section_complete` · `escalation_form = notify_immediate` · `vote_electorate = four_substantive_personas` · `backflow_policy = manager_severity_tiers`.
- **Convention 6 ACTIVE** (Lupin 100% coverage mandate).
- **Heartbeat**: scheduler path WAIVED (Rick) → liveness via Arbiter + refined heartbeat; manager still performs universal-step-zero disk-read on each wake.

---

## Scope & run order (Rick-ratified — Option A, 2026-06-27)

Re-review **00c + 01** under canon; accept **00b** as-is (APPROVED, outcome sound); then verify Fleet #6 + Task List #7. Corpus 02–11 = fast-follow (not this run).

**Run order: 00c (playback) FIRST, then 01 (keystone).** *Manager call (deviates from the memento's "01 first"): 00c is upstream of 01's B4 in the dependency chain (00b → 00c → 01), María's steward seat is already live on 00c, and 00c is the smaller plan to validate the canon-correct pipeline on. Settling the 00b↔00c ownership boundary first strengthens 01's B4 review. Flagged to Rick (broadcast 813b8fc1 reply) to object on return.*

**Re: 00c's prior revision** — 00c on disk is already REVISED (APPROVE-WITH-CHANGES, Cheech 🌿; 4 conditions folded by Krishna 🦚). That revised PLAN is the valid artifact under canon re-review — we build FORWARD from it; only the prior *review* was void, not the plan (confirmed to author Tiffany 2026-06-27).

---

## Decomposition — Plan 00c (Phase-6 TTS playback) — RUNS FIRST

Input: `05-build-plans/00c-phase6-tts-playback.md`. Three independently-reviewable sections; each pipelines Stage 1 → 2 → 3.

| Section | Buckets | Scope (one line) | Notes |
|---|---|---|---|
| **00c-A** | P6-a + P6-b | Gapless PCM scheduler ported into AudioStore + pause/resume/stop on real audio | The playback core; consumes the done decode path |
| **00c-B** | P6-c | Completion-signal seam + 00b↔00c ownership boundary | **LOAD-BEARING** — OQ-P6.3 cited-not-heuristic; emit-only `store_audio_ended`; zero `TtsQueueStore` calls |
| **00c-C** | P6-d + P6-e | Boot wiring + autoplay-gesture + tests (100% L/B/F via injected AudioContext stub) | Convention-6 coverage gate; named human-judgment listen step (§6) |

## Decomposition — Plan 01 (CC-session Notifications B1–B5) — RUNS SECOND

Input: `05-build-plans/01-cc-session-B1-B5.md`. Five buckets → five reviewable sections.

| Section | Bucket | Scope (one line) | Notes |
|---|---|---|---|
| **01-A** | B1 | Section reorder + Recent-Activity re-nest; restructure push-held `4b33ceb7` | Convergence-file edit; pre-req checks §4.1 (collapse-toggle ownership w/ Rachel) |
| **01-B** | B2 | Relocate done F6 TTS-preview slider into focus-bar header | Placement-only; needs 01-C header region |
| **01-C** | B3 | Build section-header controls (count·filter·history·clear-all) | Confirm-absent-not-renamed grep first |
| **01-D** | B4 | Per-message active-TTS-gated ⏸/⏹ + proxy-ratify-link | **LOAD-BEARING** OQ-1 active-id source (hypothesis above) |
| **01-E** | B5 | CSS single-source + Oracle Tier-2/3 + golden rebaseline | Gated LAST on A–D structural green |

---

## Task board (unified store, project lupin)

| Item | Title | Status |
|---|---|---|
| `060cec7d` | Cascade-review 00c (canon re-review) | → **in_progress** (runs first) |
| `2788dff0` | Cascade-review 01 (keystone) | in_progress (runs second) |
| `91788c40` | Verify Fleet #6 + Task List #7 | queued (closes MVP) |
| `100ee443` | Cascade-review 00b | done (accepted as-is per Option A) |

Per-section review assignments minted as worker sub-tasks at stage-assignment time.

---

## Run log

- 2026-06-27 — Manager rehydrated (Mr. Radio, f25224cf); full canon read; Rick ratified Option A; Rick waived the heartbeat loop (Arbiter backstop). Phase-0 doc authored. **Cold cast spawned** (3 reviewers `cc-reviewer-mr-radio-1/2/3` + author `cc-author-mr-radio-1`; collection `dm-mr_radio`). Run order set 00c → 01 (manager call, flagged to Rick). Author **Tiffany 💍** acked (build-forward-from-revised-00c confirmed).
- 2026-06-27 — Reviewer personas resolved via bridge files (they were booting silently): **Stage 1 = Krishna 🦚** (a9d7b22c), **Stage 2 = Sam 🎙️** (cbb3d884, also Step-0 light-review), **Stage 3 = Cheech 🌿** (2bfa60fa) — 3 distinct. Stage assignments DM'd by precise session_id; **all 3 acked**. **Krishna started Stage 1 on 00c-A** (P6-a/b playback core, reuse pre-pass); Sam + Cheech standby with lenses locked; María pinged to observe. Pipeline live: 00c-A → 00c-B → 00c-C, then plan 01. Awaiting Krishna's Stage-1 findings (wakes me; no loop).
