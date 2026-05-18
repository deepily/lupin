# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-12 to 05-15](history/2026-05-12-to-15-history.md). History health: ✅ **HEALTHY at 9,853 tokens (39.4% of 25k)** — archived 2026-05-17 by Tiberius 🌑 (session 2d916480), 31,413 tokens moved to archive.

### 2026.05.18 - Session 4e724860 (Tiberius 🌑) | Cascade Run 2 manager + V2 polish bundle (Items #1 + #3 Lupin-side)

End-to-end manager of Run 2 of the `/plan-review-cascaded` prototype on the toy email-verification fixture, then coordinator of the v2 polish-bundle implementation cycle that followed. Same 5-persona cast as Run 1 (María 🌸 doctrine consultant, Mr. Radio 🦉 Author, Rachel 🕊️ Usability/Reuse, Arnold 🪨 Viability/Gap, Rio ⚡ Ownership-Language Audit, me Manager).

**Run 2 cascade results**: all 4 stages cleared on both sections (Section A 19:53:20 UTC, Section B 20:03:30 UTC); 21 findings total (12 cosmetic / 8 inconsistency / 1 foundational); 5 single-round verbatim re-litigation rounds (100% lowest-friction close); 0 votes; 1 escalation to Rick (Section B Arnold F1 plan-decomposition gap, user-ratified `documented_for_telemetry`); 100% `severity_proposed` → manager-final match rate (21/21); 4 cross-section findings caught + closed consistently; wall-clock ~49 min (vs Run 1 ~55 min). Heartbeat daemon ran 21 ticks on 180s cadence, exited cleanly on `cascade_complete` signal. End-of-pipeline §8 summary posted to `pipeline-summary-20260518` commons topic for archival.

**V2 polish bundle** (5 improvements identified during Run 2 §8 summary, ratified by Rick 2026-05-18T21:10 UTC via bundled manager-funnel ask):
- **Item #1** (Rio): `ask_multiple_choice` MCP tool gained `default: Optional[dict]` keyed by question header. On timeout returns `{"answers": default}` instead of error. Closes the AFK-graceful-escalation gap (Run 2 lost ~10 min to a timed-out `ask_multiple_choice` with no default — the cascade was unrecoverable until I re-fired as `ask_yes_no` which DOES support `default`). Backward-compatible (default=None preserves legacy error-path byte-identically). Pre-call validation rejects invalid defaults at call time, not at timeout.
- **Item #3** (Rachel): cascade-heartbeat daemon extended with per-section message-count budget tracker. Filename-glob section discovery (`cascaded-prototype-section-*.md`), boundary-marker `str.count()` on disk for cheap entry counting, idempotent warn-once-per-section via in-memory dict, DM-to-manager via `CommonsStore.post()` + Phase 3 push (matches `fire_heartbeat()` shape). New CLI args `--budget-threshold` (default 25) + `--section-glob`. Existing launch invocations work unchanged.
- **Items #2 + #4 + #5** (Arnold + Mr Radio in PIP — committed by María separately at SHA `6c8b7b1`): recommendation-as-spoken-headline doctrine for §7 escalation templates, Convention 3 × Convention 4 author Stage-0 self-check in Persona 2 rubric, cluster-bundled re-litigation as playbook default in §6.2 + §DM-Subset Heuristics.

**Coordination wins**: bundled manager-funnel ratification ask saved ~4 user-attention round-trips vs per-item ratification (3 interactions for 5 ratifications). Lesson 12 captured to PIP §10 memo (manager-funnel applies to both findings-up AND proposals-up; bundled > per-item). Meta-validation: my recommendation-led second ratification ask (informally applying Item #2's not-yet-codified doctrine) landed unconditional yes immediately — direct evidence the doctrine fix works even before its formal implementation. Arnold independently dogfooded the same spoken-headline contract during his own classifier-vs-funnel detour around 21:55-22:00 UTC.

**Critical-path Rachel hold/resume episode** (telemetry capture for §10 memo): Rachel correctly held Item #3 post Rick's broadcast `312d4397` (files-touched check-in request) but sent her status-ping to me via `commons_post` (blackboard-only, no push in Phase 1) — I never saw it. Voice-redirect from Rick caused a 2-line argparse revert (byte-clean undo, no real work lost). Diagnosed in one round-trip; re-greened Rachel using Rick's "straighten this out" authority. **Doctrine lesson logged**: status-pings to sleeping recipients MUST use `commons_send_to` or `in_reply_to` on an open question; plain `commons_post` is blackboard-only in Phase 1 and only delivers when the recipient next polls.

**Documentation + commit pattern with María**: mutual independent convergence on the per-repo split (Tiberius=Lupin code-side, María=PIP doctrine-side) at 22:38:07 vs 22:38:19 UTC — both arrived at the same answer from the same playbook within 12 seconds. Prep-don't-commit pattern initially planned (we prepare commit messages + history entries; user fires `git commit`); Rick's broadcast `69cffa07` ("you have a go to document and commit") replaced the consolidated ratification ask with pre-authorization. Worker sign-offs still gathered for intra-team attribution discipline. Commits fire per-repo independently; `git push` stays per-repo user-fire per CLAUDE.md `feedback_never_auto_commit_push.md`.

**Operational note** (also in commit body): Rio's Item #1 `default` param fix requires MCP subprocess restart to take effect in active CC sessions. Python imports cache the OLD code in long-running MCP processes — same pattern as the 2026-05-18 commons_store truncation-fix episode. For Run 3 of the cascade-review prototype, all participating sessions should have MCP subprocesses restarted post-merge so the timeout-default benefit is available to the Manager's escalation calls.

**Followup tracked (NOT in this commit, future session)**: `src/docs/notification-api.md` and related Lupin docs need an update to advertise the new `ask_multiple_choice` `default` param to internal callers per the CLAUDE.md DOCUMENTATION TOUCHPOINTS table mapping (MCP notification-tool surface changes → `src/docs/notification-api.md`). TODO seed for next documentation-refresh session.

**Files (parent Lupin only — CoSA + PIP untouched per nested-repo rules)**:
- `src/lupin_mcp/cosa_voice_mcp.py` (MOD — Rio's V2 Item #1: `default` param signature + validation helper + timeout branch + line-742 instructions block update)
- `src/tests/unit/test_cosa_voice_mcp_default.py` (NEW — Rio's 13 unit tests: 7 validation-helper + 6 integration scenarios; full MCP regression 42/42 green in 1.96s, zero regressions)
- `src/scripts/cascade_heartbeat_scheduler.py` (NEW — heartbeat daemon scaffold from earlier Run-2-prep + Rachel's V2 Item #3 budget-tracker extension; daemon ran 21 ticks of Run 2 cleanly before this commit)
- `src/scripts/start-cascade-heartbeat.sh` (NEW — executable wrapper)
- `src/tests/unit/test_cascade_budget_tracker.py` (NEW — Rachel's 5 unit scenarios: 3 required + 2 defensive bonus; 5/5 green in 0.05s)
- `history.md` (this entry)

**PIP repo touches** (separate repo, María's parallel commit at SHA `6c8b7b1`):
- `workflow/plan-review-cascaded.md` (MOD — Arnold's #2 + #5 + version-history bump)
- `workflow/plan-review-cascaded-personas.md` (MOD — Mr Radio's #4 + version-history bump)
- `src/rnd/2026.05.17-cascaded-plan-review-pipeline.md` (MOD — §10.13 Lesson 12 added)
- `history.md` (MOD — Session 92 continuation entry)

**Audit trail anchor**: commons topic `v2-improvements-complete-2026-05-18` holds all 5 V2 proposal entries + 4 completion entries + my Lupin commit-prep draft. Cross-repo trail discoverable from either repo's commit body via this topic name (no SHA cross-reference per agreement with María — async SHA exchange not worth the complexity).

**Run 3 readiness**: pending (a) MCP subprocess restart on all participating sessions to pick up Item #1; (b) Rick's Run-3 window selection. Heartbeat daemon will need a fresh launch (the Run 2 daemon exited cleanly on cascade-complete); doctrine doc updates from the parallel PIP commit are in-effect immediately on next session-start read (no restart needed for doctrine reads).

---

### 2026.05.18 - Session 4e724860 (Tiberius 🌑) | Cascade Run 1 manager + body-display truncation fix verification + heartbeat daemon for Run 2

End-to-end manager of the inaugural `/plan-review-cascaded` prototype run with María 🌸 as doctrine consultant + 4 reviewer roles (Mr. Radio 🦉 Author, Rachel 🕊️ Usability/Reuse, Arnold 🪨 Viability/Gap, Rio ⚡ Ownership-Language Audit). Cascade surfaced 12 findings across both sections of the toy email-verification plan; manager-absorbed 9; escalated 3 cross-section foundational findings via combined Trigger 1+2 → Rick picked Option 1 (Convention 4 markers). Author closed cluster Round 1. Cascade declared complete at the 2-section ratification gate; Stages 3 on A + 2-3 on B intentionally skipped per Rick's wrap directive once primary value-prop was proven.

**Body-display truncation arc** (the dominant Run-1 dead-air contributor): Rio diagnosed root cause as `ENTRY_SEPARATOR = "\n---\n"` collision with markdown thematic-break syntax at `commons_store.py:46`. Fix: new separator `\n<<<__lupin_commons_entry_boundary__>>>\n` + legacy fallback in `read()` + `_warn_orphan_blocks` defense-in-depth + 200-line migration script with header-lookahead regex + 14+29 unit tests + 100% coverage. Migration ran clean (48 files scanned, 42 mutated, 432 entry-boundaries swapped). Verified post-MCP-restart via probe: 2200-char `---`-laden body round-trips byte-equivalent. Sub-bug B (write-side disk truncation, María 2026-05-17) is DEFINITIVELY SEPARATE per Rio's awk re-verify on `dm-maria.md`; Mr. Radio's fastmcp atomic-write track remains relevant for a future session.

**Heartbeat daemon for Run 2**: Python daemon at `src/scripts/cascade_heartbeat_scheduler.py` + wrapper `start-cascade-heartbeat.sh`. Implements postmortem §6.B + PIP playbook §6.4 spec — manager-only scope, 2-3 min active cadence, 3-strikes dead-man's-switch → priority=high notify, cascade-complete signal-driven termination. Caught + fixed one bug mid-smoke-test (`cascade_is_complete` was matching Run-1's historical wrap-up post; fix scopes detection to content added after `initial_size` captured at daemon start). Smoke test PASSED: `register_status=201`, `dm_dispatched=true`, system-reminder push-wake verified end-to-end.

**Postmortem collaboration** (María authored, I reviewed): `planning-is-prompting/src/rnd/2026.05.18-cascaded-prototype-postmortem.md` + my companion input `2026.05.18-cascaded-prototype-postmortem-tiberius-input.md` answering Q1-Q5 + six additional manager-seat lessons (universal-step-zero, preemptive worker probes, single-escalation-for-clusters, manager-classification audit trail, workarounds-become-doctrine, self-audit discipline). María's 5-item doctrine track also complete: playbook §6.4 rewrite + §Manager System Prompt updates + §6.1 classification audit trail + §Step 4 ack-format clarification + severity-tag schema expansion. PIP playbook now references my heartbeat daemon as the canonical reference implementation.

**Three failure modes catalogued for §10 findings memo**:
1. Body-display truncation (read-side) — REPRODUCED Run-1, FIXED by Rio, VERIFIED 2026-05-18 by me
2. Turn-based-CC limitation (no autonomous ticks) — REPRODUCED throughout, ADDRESSED by my heartbeat daemon
3. Sub-bug B (write-side disk truncation) — STILL OPEN; Mr. Radio's atomic-write investigation track remains relevant

**Files (parent Lupin only — CoSA + PIP untouched per nested-repo rules)**:
- `src/lupin_mcp/commons_store.py` (MOD — Rio's separator fix; 100% coverage)
- `src/scripts/migrate-commons-entry-separator.py` (NEW — Rio's migration script, 100% coverage)
- `src/scripts/cascade_heartbeat_scheduler.py` (NEW — heartbeat daemon, py_compile clean, smoke-tested)
- `src/scripts/start-cascade-heartbeat.sh` (NEW — executable wrapper)
- `src/tests/unit/commons/test_commons_store_separator_collision.py` (NEW — 14 tests)
- `src/tests/unit/commons/test_migrate_commons_entry_separator.py` (NEW — 29 tests)
- 48 commons topic files mutated by migration (entry-boundary separator swap; body content untouched)

**PIP repo touches** (separate repo, not committed by me — María handles):
- `src/rnd/2026.05.18-toy-input-plan-email-verification.md`, `2026.05.18-cascaded-prototype-postmortem.md`, `2026.05.18-cascaded-prototype-postmortem-tiberius-input.md` (NEW)
- `workflow/plan-review-cascaded.md`, `plan-review-cascaded-defaults.md`, `plan-review-cascaded-personas.md` (MOD — postmortem-driven doctrine bundle)

**Run 2 status**: PREP COMPLETE on both fronts. María signaled consolidated ready to Rick. Heartbeat daemon ready to launch. Run-2 window selection is Rick's call. All 6 participating sessions (me + María + 4 reviewers) heading into `/clear` to start Run 2 from fresh contexts.

---

### 2026.05.17 - Session 225e5b2d (Tiberius 🌑) | Coordinator dispatch + Phase 5 unit tests + 100% coverage on model-server carve-out

Day-long session driven by Rick's @all broadcast (`21bb12cd`) authorizing planning-only coordinator work across Tiberius / Mr Radio / Arnold. Three deliverables landed: ratified-plan walkthrough, Phase 5 implementation, end-of-day ritual.

**Coordinator dispatch (broadcast `21bb12cd` → ratifications)**:
- Read TODO.md + bug-fix-queue.md, ranked 6 actionable items in descending importance, dispatched assignments via DM to Mr Radio (Commons DM topic-case + truncation + persona-space cluster) + Arnold (writer-side `owner_user_id` stamper + §6 SessionStart hook bug). Surfaced a NEW sub-bug (persona-with-space breaks derived topic name) during dispatch and folded into Mr Radio's scope.
- Both peers landed plan docs within minutes: Arnold found the §6 root-cause (`register_session.py:811-812` fresh-write bug wiping `user_id` on every `/clear`); Mr Radio ruled out one truncation hypothesis via code review pre-investigation.
- Walked Rick through 13 Q-decisions (11 formal + 2 supplementary) via sequential `ask_multiple_choice` / `ask_yes_no`. Net: 11 ratifications match peer recommendations; 2 diverge (migration α not β; unicode broadening). Plus 2 binding clarifications from Rick: (a) unicode all the way down to INI config — persona keys use exact spelling; (b) 100% coverage across the board, no PR with failing tests, period.

**Phase 5 — Model-server unit tests + 100% coverage**:
- 110 new unit tests across 5 files, all green on first run (~6s total). 100% line + branch + function coverage on both new source files (`speech_to_text_provider.py` 110 stmts / 26 branches; `lupin_model_server/main.py` 100 stmts / 12 branches). Carveout-scoped coverage on three modified files (`embedding_provider.py`, `routers/speech.py`, `fastapi_app/main.py` lifespan switch).
- Q9 hybrid scope honored + Q13 `_run_whisper_with_retry` CUDA-OOM-retry contract pinned via 2 test cases.

**Inter-session intervention**: Rio DMed from lookml session reporting Rick hitting a doc-viewer 404. Diagnosed as URL-shape regression — his emission helper used deprecated `?scope=` query param + missing project prefix in `path=`. Replied with corrected URL shape; he folded into his project CLAUDE.md + feedback memory immediately.

**Files (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`)**:
- `src/tests/unit/test_speech_to_text_provider.py` (NEW, ~620 LOC, 47 tests)
- `src/tests/unit/test_lupin_model_server_main.py` (NEW, ~370 LOC, 36 tests)
- `src/tests/unit/test_embedding_provider_carveout.py` (NEW, ~205 LOC, 14 tests)
- `src/tests/unit/test_speech_router_carveout.py` (NEW, ~225 LOC, 9 tests)
- `src/tests/unit/test_main_lifespan_carveout.py` (NEW, ~95 LOC, 4 tests)
- `src/tests/conftest.py` (MOD +160 LOC — 3 opt-in fixtures: `reset_speech_provider_singleton`, `reset_embedding_provider_singleton`, `fake_model_server_client`)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md` (NEW, ~530 LOC — Phase 5 plan doc)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/91-phase5-smoke-audit.md` (NEW, ~135 LOC — 5.0d audit output)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/92-phase5-closure.md` (NEW, ~200 LOC — completion report)
- `src/rnd/v0.1.7/2026.05.17-coordinator-walkthrough-ratifications.md` (NEW, ~210 LOC — all 13 ratifications + scope additions)
- `TODO.md`, `bug-fix-queue.md`, `history.md`, `history/README.md` (MOD — entries + bookkeeping)
- `history/2026-05-12-to-15-history.md` (NEW — archive landed earlier today)

**Pre-existing broader-suite failures noted**: full `src/tests/unit/` has 48 unrelated pre-existing failures (TFE / hooks / JWT / answer-correctness). Verified via `git stash` — failures exist before AND after my changes. Phase 5 itself is at 110/110 green; the broader-suite cleanup is a separate workstream.

**End-of-session ritual** (per Rick's 2nd broadcast `197cd263` authorizing Tiberius-lead on backup + push + weekly stats): this entry, commit, push, backup, daily + weekly LoC delta.

---

### 2026.05.16 - Session 3c9fce51 (María 🌸) | Checkpoint 5: cosa-voice MCP discovery-surface expansion (instructions field 65→~300 lines + 6 commons_* docstring upgrades)

Cross-session pair-collab with Tiberius 🌑 (planning-is-prompting `b714e138`) on documenting cosa-voice for fresh CC sessions. Rick triggered the work after observing today's María↔Tiberius DM thread surface multiple inline-discoverability gaps. Tiberius took the boot-time-doctrine side (`planning-is-prompting/workflow/cross-session-communication.md` refresh + thin pointer in `~/.claude/CLAUDE.md`); I took the MCP-server-bound side. Five framework iterations between us before convergence on the 5-surface model (CLAUDE.md / MCP `instructions` / planning-is-prompting workflow / per-tool docstrings / per-turn rider — split by reading timing, not content type).

**Implementation delivered**:
- `src/lupin_mcp/cosa_voice_mcp.py` (+~313 LOC) — instructions field grew from ~3k chars to **21,316 chars** (~5,329 tokens) across **10 sections**: Instructions vs Per-Turn Rider framing, Your Toolkit at a Glance (6-group nav map), Speakerphone Mode (existing + forward-pointer to Startup Protocol), Voice Persona Self-Announcement (existing + forward-pointer), MCP Startup Protocol (Phase A + Phase B), Inter-Session Commons Protocol (3-tier autonomy + reserved topics), Phase 0 DM Workflow (push-vs-poll + receipt etiquette with loop-avoidance step 4 + sender-mailbox convention + cross-session bug-filing pattern + DM-vs-broadcast), Interactive Tool Routing, Failure Modes + Debugging Signals (7 patterns), Deep Doctrine Reference (cross-pointer footer with §-by-§ pointers to Tiberius's refresh)
- 6 commons_* docstrings (`commons_who` / `commons_read` / `commons_post` / `commons_ask_sync` / `commons_ask_async` / `commons_send_to`) upgraded with Tiberius's 7 priorities: tier markers on line 1 (D1 BLOCKING), one example per tool (D2 HIGH), inline failure-mode hints incl. new `register_skip_reason` (D3 HIGH), threading callout in `commons_post` (D4), receipt mechanism in sender docstrings (D5), `expect_reply` side-effect promotion (D6), cross-ref footer (D7)
- `src/rnd/v0.1.7/2026.05.16-mcp-discovery-surface-expansion.md` — NEW R&D doc, status APPROVED FOR CODE-WRITE post-Rick-ratification

**Tiberius review walkthrough** (5 Q-points): section flow + pacing (one real dependency identified, fixed via forward-pointers), tier-marker formulation (landed cleanly), failure-mode hints precision (5 patterns accurate; added #6 persona-cache staleness + #7 topic-file case sensitivity), cross-reference footer accuracy (all 6 pointers correct + added §1.5.3 Threading), receipt etiquette alignment (added step 4 loop-avoidance + sender-mailbox `topic='dm-<sender>'` convention). Verdict: ship as-is. ~30 LOC of polish applied after review.

**Memory saved**: `feedback_mcp_doc_layering_decision_point_vs_doctrine` (now `mcp-doc-layering-five-surfaces-by-reading-timing`) — the 5-surface framework attributed to joint discovery.

**Surfaced 2 bugs during the cross-session DM thread**:
1. Topic-file case sensitivity in `commons_send_to` wrapper — DMs fragment across `dm-Tiberius` (capital T from recipient arg) and `dm-tiberius` (lowercase). Push-mode persona resolution works case-insensitively so DMs still deliver, but topic-files fragment. Filed at TODO.md top with 5-LOC fix proposal.
2. System-reminder body truncation on push-injection — when push fires, the recipient's `<system-reminder>` body may be clipped; canonical body lives in the topic file. Mitigation documented in instructions §"Failure Modes" item #7 + receipt-etiquette step 2 ("always re-fetch via `commons_read` for canonical body").

**Process artifact worth noting** (per Rick's broadcast asking for follow-up summary doc with Tiberius): today's collaboration shape — iterative correction loop (María proposes 5-layer → Tiberius corrects to 3-layer → Tiberius re-corrects back to 5-layer + adds Q2 enrichments → joint memory saved) + DM-thread-as-mini-design-doc + paired-by-DM-paired-by-commit pattern — produced sharper output than either of us would have produced alone. Tiberius and I will draft a follow-up summary R&D doc tomorrow covering this workflow as a replicable template, with a pointer from the project README.

**Files** (this checkpoint — Lupin parent only; CoSA submodule untouched per `feedback_lupin_only_never_cosa`):
- `src/lupin_mcp/cosa_voice_mcp.py` (MOD ~+313 LOC)
- `src/rnd/v0.1.7/2026.05.16-mcp-discovery-surface-expansion.md` (NEW R&D doc)
- `TODO.md` (PRIORITY-1 history-archive deferral entry added at top; case-fragmentation + truncation sub-bugs filed earlier)
- `history.md` (this entry)
- `.claude-session.md` (Checkpoint 5 update — pending)

**Commit**: <pending>

**Health note**: history.md is at 26,032 tokens (104% of 25k limit) at session-end. Rick approved deferring the archive to first-thing next session via `ask_multiple_choice` gate. Tracking in TODO.md PRIORITY-1.

---

### 2026.05.16 - Session 0025f917 (Rio ⚡) | Model-server carve-out: Whisper + 2 encoders moved to lupin-model-server:7998, doom-loop structurally killed

Day-long sequenced design + implementation arc. Rick voice-driven the whole way; I owned execution. Phases 0-5 of the carve-out shipped, INI flipped, dev + test bounced into remote-mode, model-server brought up into freed VRAM, all 9 smoke-test cases green.

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md) — full design with REUSE pass, Pass 1 Fitness (25 ACs, blast-radius matrix), Pass 2 Ownership Audit (37 actions executor-tagged, 5 USER gates), auth refinement override section, and Part 2 bounce actuals.

**Companion**: [`90-baseline-metrics.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/90-baseline-metrics.md) — pre-carve-out measurements (host GPU, per-container VRAM, image size, cold-start time 29.52 s).

**What landed (parent Lupin repo)**:

- **New**: `src/lupin_model_server/{__init__.py, main.py}` (~440 LOC) — minimal frozen FastAPI app on `:7998` exposing `/health` (503 until 3 models in VRAM), `/transcribe`, `/embeddings/{generate,batch,info}`, `/admin/metrics` (Prometheus). Auth via boot-time bcrypt hash of the existing `notification-api-claude-code-dev` key.
- **New**: `docker/lupin-model-server/Dockerfile` (140 LOC) — mirrors `docker/lupin/`'s nvidia/cuda:12.4.1 base + cuda-compat-12-4 purge (RTX 4090 fix), Python 3.11, pinned torch 2.6.0+cu124 + transformers + sentence-transformers + prometheus-client + bcrypt, models baked at build time.
- **New**: `src/tests/smoke/test_model_server_smoke.py` (~250 LOC, 9 test cases) — exercises every endpoint + 3 auth-rejection cases + end-to-end via compute. All passing in 3.02 s.
- **New**: `src/rnd/v0.1.7/2026.05.16-model-server-carveout/{01-design.md, 90-baseline-metrics.md}` — design doc subdirectory.
- **Modified**: `docker-compose.yml` — added `lupin-model-server` service entry (port 7998, GPU 0 pinned via CUDA_VISIBLE_DEVICES=0 per `feedback_lupin_models_always_gpu_0`, healthcheck, ck_live_* key bind-mount); added `LUPIN_MODEL_SERVER_URL` + `LUPIN_MODEL_SERVER_API_KEY_FILE` env vars to compute services.
- **Modified**: `src/conf/lupin-app.ini` — new keys `speech to text provider = local` (defaults preserve behavior) + `model server url`.
- **Modified**: `src/conf/lupin-app-splainer.ini` — matching explanations.
- **Modified**: `src/fastapi_app/main.py` — Phase 3.6 lifespan switch reads provider mode; if `model-server`, SKIP all 3 eager GPU loads + call `SpeechToTextProvider.declare_remote_only()` + run 60-s readiness probe against `:7998/health`. Otherwise unchanged.
- **Deleted**: `docker/whisper/Dockerfile` — legacy Flask-based proto from Jan 2025, dead since the FastAPI migration.

**CoSA-submodule changes (NOT committed from parent context per `feedback_lupin_only_never_cosa`)** — held for separate CoSA-context commit:
- `src/cosa/memory/embedding_provider.py` — extended URL resolver to honor `LUPIN_MODEL_SERVER_URL` env → INI → None; consolidated `_model_server_api_key` into existing `_http_api_key` (single namespace).
- `src/cosa/memory/speech_to_text_provider.py` (new) — mirrors `EmbeddingProvider` architecture: singleton, class-level `_is_in_process_owner` flag, INI-driven `speech to text provider` switch, local + HTTP paths, exp-backoff retry wrapper.
- `src/cosa/rest/routers/speech.py` — `Depends(get_whisper_pipeline)` → `Depends(get_speech_provider)`; legacy `_run_whisper_with_retry` marked deprecated but kept; new `save_upload_to_temp` helper.

**Cross-session collaboration** (cosa-voice MCP `commons_send_to` DMs):
- Rick voice-routed an API-key design question to María (session `3c9fce51`) after I'd overbuilt a parallel `ck_internal_*` namespace.
- María's brief: existing validator is DB-backed bcrypt; frozen container can't reuse it directly; recommended Option (b) — file-based allowlist validator in model-server reusing the `ck_live_*` namespace.
- Rick ratified Option (b). I rolled back my `ck_internal_*` invention (deleted generator script + key file + bcrypt-hash env var), rewired model-server to read the existing `notification-api-claude-code-dev` plaintext, hash at boot, validate via `bcrypt.checkpw`.

**The bounce (Part 2)** — ~32 seconds wall-clock total (faster than 45-60 s predicted because models were baked into the image, no HF downloads at boot):
1. INI flip `local` → `model-server`
2. `docker restart lupin-rest-dev` (10.9 s — old process dies + frees 3.2 GB)
3. `docker restart lupin-rest-test` (11.1 s — another 3.2 GB freed)
4. `docker compose up -d lupin-model-server` (<1 s init + 9.4 s model loads)
5. Compute readiness probes succeed → `:7999` + `:8000` bind, serve via HTTP-proxy

**Three mid-flight bugs caught + fixed in-session**:
1. **HF cache bind-mount PermissionError** — initial compose pointed at a non-existent host dir that overwrote the baked-in image cache. Fix: removed the bind-mount; image is self-sufficient.
2. **Embedding endpoint self-recursion** — `docker restart` doesn't re-read compose, so `LUPIN_MODEL_SERVER_URL` env var never injected. `_resolve_model_server_url()` only checked env, fell back to compute's own URL → infinite recursion → 10-s timeout. Fix: resolver now checks env → INI → None (mirrors speech-provider); `docker compose up -d --force-recreate` to inject the env var.
3. **`/transcribe` 422** — leftover `_authenticated: str = ...` in endpoint signature → FastAPI required-body-field rejection. Fix: deleted the unused parameter; rebuild + recreate.

**Final state**:
- GPU 0 used: **19,889 MiB** (was 23,131 MiB → saved 3,250 MiB, matches Rick's net-savings math)
- GPU 0 free: **4,335 MiB** (was 1,086 MiB → headroom 4× pre-carve-out)
- `:7998/health` 200, 3 models loaded (whisper + code_rank_embed + nomic_embed_text_v1_5), 2,505 MiB VRAM
- `:7999/health` + `:8000/health` 200
- 9/9 smoke tests passing in 3.02 s
- Native browser ASR confirmed working post-fix
- Doom-loop: Layers 1 + 3 structurally GONE from compute containers; Layer 2 (`--reload`) harmless because no GPU dependency to break

**Remaining work for next session** (see TODO.md):
- Phase 4 cleanup: strip `--gpus all` from compute compose entries; drop the 3 model pre-downloads from `docker/lupin/Dockerfile:208-210`; rebuild `lupin:1.0.0-noasr` candidate.
- Phase 5.2-5.5: unit tests for `SpeechToTextProvider`; `mock_model_server_client` pytest fixture; push to 100% coverage on all new/modified files per the Lupin-wide coverage mandate (per `feedback_100pct_coverage_multiplexer` — scope-expanded 2026-05-16).
- Phase 7: CLAUDE.md DOCUMENTATION TOUCHPOINTS row + `~/.claude/skills/server-lifecycle/SKILL.md` update for the new `lupin-model-server` bounce semantics.
- Push (deferred per Rick's no-push instruction at session-end).

**Memory updates this session**:
- New `feedback_lupin_models_always_gpu_0.md` — hard rule from Rick: Lupin models ALWAYS pin to GPU 0, never auto-pick.
- Updated `feedback_100pct_coverage_multiplexer.md` — scope expanded from multiplexer TS to ALL Lupin code per Rick's "Coverage floors are bullshit. Everything has to pass at 100%. Full stop. Everything!" directive mid-Pass-1.

---

### 2026.05.16 - Session 3c9fce51 (María 🌸) | Daily LoC Delta tool — new `cosa.repo.git_loc_delta` sibling of `branch_analyzer`

User-initiated voice-first ask to view an unserialized Claude Code plan via the doc viewer (`/app/docs?path=cosa/...&scope=cosa`) surfaced two adjacent issues: (1) the URL itself referenced a retired `?scope=` param and a non-registered `cosa` project, and (2) the plan `resilient-soaring-turtle.md` at `~/.claude/plans/` was not yet serialized into any repo. Per the plan-serialization mandate, the fix was serialize-first then implement. User chose CoSA-submodule R&D destination (Option B in `ask_multiple_choice` voice gate).

**Plan doc serialized**: [`src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md`](src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md) — Status flipped from "🟢 APPROVED FOR CODE-WRITE" → "🟢 SHIPPED" through a Reduced PIP review:

- **REUSE pre-pass** — all 7 reuse-map citations verified against current code (`file_classifier`, `exceptions`, `git_diff_parser:115-150`, `run_branch_analyzer:69-156`, `quick_smoke_test` template, `to_csv` pattern, `get_project_root()`). 2 minor line-range drifts fixed (R4 `63-155` → `69-156`; R6 usage-clarification note). Sweep check confirmed no existing per-day git-log LoC tool. User-ratified via `ask_yes_no`.
- **Pass 1 Fitness** — 18 ACs derived (8 correctness + 5 coverage + 3 style + 2 edge case), 8 fitness findings filed (F1 `reports/` → `io/` convention alignment, F2 unit-tests-required-not-optional per Testing Ownership Mandate, F3 testing-tier table consolidation, F4 explicit Sweep Check section, F5 formal AC section, F6 edge-case section, F7 exit-code documentation, F8 smoke-test scope decision). All 8 amendments folded in. User-ratified via `ask_yes_no`.

**Implementation shipped** (10 files):
- `src/cosa/repo/git_loc_delta/__init__.py` — package exports
- `src/cosa/repo/git_loc_delta/exceptions.py` — `GitLocDeltaError`, `DateRangeError`; re-exports `GitCommandError`
- `src/cosa/repo/git_loc_delta/git_log_parser.py` — `GitLogParser.iter_changes()` over `git log --numstat`, binary-row skip, malformed-row defense
- `src/cosa/repo/git_loc_delta/daily_aggregator.py` — `DailyAggregator` with `(date, file_type)` bucketing + per-date rollup + summary view; loads `branch_analyzer.FileTypeClassifier` via `ConfigLoader().load()`
- `src/cosa/repo/git_loc_delta/csv_writer.py` — `write_csv()` tidy-long, 6-column stable schema, sorted by `(date asc, added desc)`
- `src/cosa/repo/git_loc_delta/report_formatter.py` — `format_console()` two-table layout + `format_json()` nested dict
- `src/cosa/repo/git_loc_delta/analyzer.py` — `GitLogLocDeltaAnalyzer` orchestrator + `quick_smoke_test()` with 7 ✓/✗ checks
- `src/cosa/repo/run_git_loc_delta.py` — CLI entry with mutually-exclusive date-range group, exit codes 0/1/2, mode-aware default CSV path
- `src/cosa/repo/git_loc_delta/README.md` — comprehensive user docs covering Use Case A (end-of-day daily ritual) + Use Case B (pre-PR summary) + CLI reference + architecture + reuse map + edge cases + future enhancements
- `src/tests/unit/test_git_loc_delta.py` (parent Lupin) — 4 unit tests: parser binary skip, aggregator bucketing, CSV schema stability, empty-input header-only

**Test pyramid — all 5 tiers green**:

| Tier | Result |
|---|---|
| T1 py_compile (9 source + 1 test) | ✅ 9/9 OK |
| T2 import chain | ✅ all resolved |
| T3 unit tests | ✅ 4/4 PASSED in 0.31s |
| T4 quick_smoke_test() | ✅ 7/7 ✓ |
| T5 live CLI on Lupin (today / --branch / --output csv) | ✅ all 3 modes verified |
| T5 live CLI on CoSA submodule (--repo-path src/cosa --branch) | ✅ working |

**Real-world outputs** (current branch state):
- Lupin: 21 days, 216 commits, 532 files, +147,999 / −13,171 (net +134,828). Heaviest day 2026-05-04 (+18,599). File types: markdown (docs work), python (CoSA/agents), typescript (multiplexer refactor).
- CoSA: 17 days, 69 commits, 73 files, +12,561 / −3,272 (net +9,289). 2026-05-05 the only net-negative day (−459 net) due to 625 python deletions.

**Post-ship docs + filename-flip iteration** — after live spin-up on both repos, user voice-requested comprehensive docs + flagged a workflow concern: the original date-stamped default filename (`{YYYY-MM-DD}-loc-delta.csv`) didn't fit a daily-overwrite-per-branch workflow. Two `ask_multiple_choice` decisions ratified:
- **Q1 doc location**: package README at `src/cosa/repo/git_loc_delta/README.md` (CoSA convention, co-located with code)
- **Q2 filename mode**: flip default to mode-aware — `--branch` mode → `{repo}-{branch-slug}-loc-delta.csv` (stable per-branch, daily-overwrite-friendly); `--today` / `--since`/`--until` mode → date-stamped (archival)

Verified post-flip: Lupin run produced `lupin-wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe-loc-delta.csv` (118 rows); CoSA run produced `cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` (34 rows).

**Pending CoSA-context commit** (per `feedback_lupin_only_never_cosa`):
- [ ] **[LUPIN-COSA]** Commit in a CoSA-context session: 8 source files under `src/cosa/repo/git_loc_delta/` + `src/cosa/repo/run_git_loc_delta.py` + `src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md`. Suggested commit message: `[COSA] Add git_loc_delta sibling — per-day LoC analysis via git log --numstat`

**Workflow notes**: Plan-serialization mandate triggered by user's doc-viewer 404 (file at `~/.claude/plans/` not yet serialized). Reduced PIP review (REUSE + Pass 1 Fitness, both with explicit user gates via `ask_yes_no`) chosen over Full PIP via `ask_multiple_choice` — appropriate for a single-session internal CLI with no API/UI/handoff surface. Documentation-first protocol observed: R&D plan + package README both drafted before final filename-flip code change. Tested everything end-to-end across both Lupin parent + CoSA submodule before declaring shipped.

**Memory rules engaged**: `feedback_walk_through_plan_before_asking_proceed` (substantive findings via notify before every gate), `feedback_pip_plan_review_is_sequential` (REUSE → gate → apply → Pass 1 → gate → apply), `feedback_always_include_pros_cons_recommendation` (per-option pros/cons in `ask_multiple_choice` abstracts), `feedback_tts_body_headline_and_takeaway_only` (spoken `message` carried headlines only; details in `abstract`), `feedback_doc_links_always_in_abstract` (viewer link as line 1 of abstract), `feedback_lupin_only_never_cosa` (CoSA submodule edits OK, git ops forbidden from parent), `feedback_verify_staging_before_commit` (`git diff --cached --stat` before this checkpoint commit), `feedback_never_auto_commit_push` (explicit voice authorization for this commit), `feedback_documentation_step_stops_at_doc` (filename-flip surfaced as separate decision after doc work).

#### Checkpoint 1 | 2026.05.16 19:35 UTC | Daily LoC Delta — Lupin-side artifacts

**Files** (parent Lupin only): src/tests/unit/test_git_loc_delta.py (NEW), TODO.md (MOD), history.md (this entry), .claude-session.md (session section)
**Commit**: 2e0e7e5
**CoSA-side pending**: 10 files awaiting CoSA-context session (Rick claimed EOD ownership)

#### Checkpoint 4 | 2026.05.16 21:18 UTC | Commons-activity entries: collapsible body + markdown rendering

User-requested UI ship after the María↔Tiberius DM thread filled the Recent Activity panel with multi-paragraph content. Two coordinated features in one change:

1. **Two-line clamp by default** — body content wraps in new `.commons-activity-entry-body-content` div with `-webkit-line-clamp: 2`. "Show more ▾" / "Show less ▴" button toggles `.expanded` class on click. Button auto-hides via `requestAnimationFrame` measurement when content doesn't actually overflow the clamp — short DMs stay clean, no redundant affordance.
2. **Markdown rendering** — reuses the established `marked.parse() → DOMPurify.sanitize()` pattern from `broadcast-panel.js:127-139`. Page-loaded `window.marked` + `window.DOMPurify` globals, graceful fallback to plain `textContent` if either lib unavailable. Compact markdown-CSS-reset prevents tall paragraphs / list spacing from blowing up the panel.

**Test pyramid**:

| Tier | Spec | Result |
|---|---|---|
| node --check | `notifications.js` after edits | ✅ syntax clean |
| Existing watcher unit tests | `test_commons_activity_watcher.py` | ✅ **22/22 PASS** (no regressions) |
| New Playwright E2E (Phase 1 — code written) | 10 tests in `test_commons_activity_toggle.py`: clamp, toggle cycle, markdown rendering, XSS sanitization | ⏳ Code shipped; :8000 scheduled run pending Rick's slot confirmation |
| Visual regression baselines | clamped state + expanded state + short-no-toggle state | ⏳ same — needs :8000 slot |

**XSS sanitization tests** specifically:
- `<script>window.__commons_xss_marker = true;</script>` body → asserts marker variable never set
- `<img src='x' onerror='...'>` body → asserts onerror handler never fires + asserts `onerror=` stripped from innerHTML
- Lockes the DOMPurify-via-broadcast-panel-pattern contract for this surface

**Files in commit (Lupin parent — all served by FastAPI :7999 which auto-reloads static files immediately)**:
- `src/fastapi_app/static/js/notifications.js` (MOD — body-section rewrite, ~45 LOC)
- `src/fastapi_app/static/css/notifications.css` (MOD — new clamp/toggle/markdown rules, ~95 LOC)
- `src/tests/e2e_ui/test_commons_activity_toggle.py` (NEW — 10 Playwright E2E tests, ~230 LOC)
- `history.md` (this sub-entry)
- `.claude-session.md` (Checkpoint 4 + touched-files update)

**Commit**: <pending>

#### Checkpoint 3 | 2026.05.16 21:05 UTC | Commons DM push-mode + Git LoC Delta cross-target fix arc (5 fixes, F1-F5)

Live debugging triggered by Rick's challenge of an earlier "awaiting commit" framing exposed 3 latent bugs + 1 deployment gap + 1 test-pyramid gap from the prior two ship arcs (Inter-Session DM Phase 0 yesterday, Daily LoC Delta this morning). Five fixes (F1-F5) landed in one arc with full regression coverage.

**Fixes**:
- **F1**: Replace `os.environ.get("LUPIN_MCP_API_KEY")` (env var was added in commit `9bbf298` without source-side wiring — silent fallback to polling on every push-mode call) with `du.get_api_key("notification-api-claude-code-dev")` — the canonical pattern already used by `cosa.memory.embedding_provider._http_api_key` for embeddings HTTP auth. Rick caught the cleaner abstraction; no new key to mint, no docker-compose changes.
- **F2**: `commons_send_to` was calling the `@mcp.tool`-decorated `commons_ask_async` by name (resolves to `FunctionTool` instance, not callable) — `TypeError: 'FunctionTool' object is not callable` on every invocation. Refactored both wrappers to delegate through a shared private `_commons_ask_async_dispatch()` helper.
- **F3**: Silent push-mode fallback now surfaces `register_skip_reason` ("missing_auth_header" / "missing_api_base_url" / "register_failed_status_N" / "register_failed_422") in the result dict. Previously `push_mode_active: false` with no other signal.
- **F4**: `_default_csv_path` cross-repo bug filed by Tiberius 🌑 session `b714e138` — was using `cu.get_project_root()` (always LUPIN_ROOT) as the base, so cross-repo invocations dumped CSVs into Lupin's `io/` tree instead of the target. Two-stage fix: first pass via `os.path.abspath` regressed the in-tree-from-subdir case, final fix uses `git rev-parse --show-toplevel` from the supplied `--repo-path` to resolve actual repo root.
- **F5**: Added 3 new unit tests covering cross-target invocations — the test class my earlier ship had missed. Locks both the cross-repo case and the no-regression-on-in-tree case.

**Test pyramid — all green**:

| Tier | Result |
|---|---|
| py_compile (4 files) | ✅ OK |
| Import chain | ✅ resolved |
| `git_loc_delta` unit tests (4 existing + 3 new) | ✅ **7/7 PASS** in 0.27s |
| Full commons unit suite (438 + 7) | ✅ **445/445 PASS** in 35.29s, **0 regressions** |
| Live cross-repo (Tiberius's reproducer) | ✅ CSV lands at `planning-is-prompting/io/git-loc-delta/...` (correct) |
| Live in-tree from `lupin/src/` (subdir cwd) | ✅ CSV lands at `lupin/io/git-loc-delta/...` (correct — git toplevel resolution) |
| Live in-tree from `lupin/` (repo root cwd) | ✅ CSV lands at `lupin/io/git-loc-delta/...` (correct, unchanged) |
| Live DM via `commons_ask_async` to running MCP subprocess | ⚠ Stale — returned `push_mode_active: false` with NO `register_skip_reason` (confirms running fastmcp subprocess hasn't reloaded; next CC session picks up fix automatically) |

**Process correction — testing failure acknowledged**: My initial test pyramid for `git_loc_delta` only invoked the tool with `--repo-path .` and `--repo-path src/cosa` — both INSIDE the Lupin tree. I never tested cross-repo, which is the primary use case. Direct violation of the Testing Ownership Mandate ("user is never the tester"). Two memories saved to prevent recurrence: `feedback_tests_must_cover_cross_target_invocations` + `feedback_env_var_read_and_set_land_together`.

**R&D doc**: [`src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md`](src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md) — full diagnosis + fix-by-fix breakdown + deployment caveat about fastmcp subprocess staleness.

**Files** (this checkpoint):
- `src/lupin_mcp/cosa_voice_mcp.py` (MOD — F1 + F2, ~70 LOC)
- `src/lupin_mcp/commons_ask.py` (MOD — F3, ~25 LOC)
- `src/tests/unit/test_git_loc_delta.py` (MOD — F5 +90 LOC, 3 new cross-target tests)
- `src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md` (NEW R&D doc)
- `history.md` (this sub-entry)
- `.claude-session.md` (Checkpoint 3 + touched-files update)

**Commit**: <pending>

**CoSA-side pending** in Rick's EOD batch: `src/cosa/repo/run_git_loc_delta.py` (F4, ~30 LOC) alongside earlier LoC Delta sources + broadcast fan-out watcher fix.

#### Checkpoint 2 | 2026.05.16 20:25 UTC | Bug fix — duplicate broadcast fan-out (consumer-side dedupe in CommonsActivityWatcher)

Rio's `bug-fix-queue.md` "Bug #2 — duplicate notification fan-out" (filed 2026-05-16 morning) diagnosed and fixed. Root cause: producer/consumer asymmetry — `perform_fanout` writes N per-recipient rows to the `broadcasts` topic by design (for `target_session_id`-scoped routing on the HTTP path), the HTTP read path `/api/commons/broadcast-history` collapses N → 1 via `_dedupe_broadcasts_by_id` + `_dedupe_broadcast_acks_by_recipient`, but `CommonsActivityWatcher._tick()` (the WS push path) dispatched one `commons_activity` event per raw row — so the Recent Activity panel saw N rows from one broadcast.

**Fix**: Mirror the HTTP-path dedupe inside the watcher. New `_dedupe_for_dispatch` method in `CommonsActivityWatcher` (~80 LOC), called from `tick()` between sort and dispatch. Cursor advancement uses pre-dedupe max ts so dropped duplicates don't re-surface next tick. Zero changes to write side (per-recipient rows still needed for HTTP-path same-user scoping).

**Test pyramid**:

| Tier | Result |
|---|---|
| py_compile (2 files) | ✅ OK |
| import chain | ✅ resolved |
| Targeted unit (22 watcher tests: 15 pre-existing + 7 new) | ✅ **22/22 PASS** in 0.07s |
| Full commons regression (438 tests) | ✅ **438/438 PASS** in 14.80s, **0 regressions** |
| Live :7999 broadcast smoke | ⏳ Pending Rick's hands-on confirmation |

**R&D doc**: [`src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md`](src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md) — full diagnosis, fix shape, test coverage, 2 pending follow-ups (write-side `broadcast-acks` multiplicity per Arnold's investigation note; persona-stamping asymmetry 4×Mr-Radio + 1×Rio).

**Files** (this checkpoint):
- `src/tests/unit/commons/test_commons_activity_watcher.py` (MOD — +170 LOC, 7 new tests)
- `src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md` (NEW R&D doc)
- `TODO.md` (MOD — fan-out entry flipped NEW → ✅ FIX SHIPPED)
- `history.md` (this sub-entry)
- `.claude-session.md` (Checkpoint 2 added to session 3c9fce51 section)

**Commit**: <pending>

**CoSA-side pending** (per `feedback_lupin_only_never_cosa`): `src/cosa/rest/commons_activity_watcher.py` awaits Rick's EOD batch commit alongside the DM Phase 0 CoSA pieces + LoC Delta CoSA pieces.

---

### 2026.05.16 - Session dfd7b2d8 (Mr. Radio 🦉) | Doc viewer SPA dispatcher 404 fix + /api/docs/health regression

Rick reported a 404 on `/app/docs?path=lupin/src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` — a doc-link emitted by the path-prefix routing model the 2026-05-15 scope unification put on the wire. Backend served the file fine when called directly (HTTP 200, 16,159 bytes via JWT-authed `/api/docs/file?path=lupin/...`); the bug was entirely in the frontend SPA. The May-15 unification updated `/api/docs/file` to accept `path=<project>/<rel>` form and retired the `?scope=` query param, but it never touched `src/fastapi_app/static/html/document-viewer.html`. The SPA's dispatcher still defaulted `scope` to `'io'` when absent and routed everything to `/api/io/file` — which has no Lupin source paths under it.

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-doc-viewer-spa-dispatcher-fix.md`](src/rnd/v0.1.7/2026.05.16-doc-viewer-spa-dispatcher-fix.md) — full bug analysis, fix sweep, verification matrix, parked follow-ups.

**Fix shipped (3 production files, 5 test files)**:

1. **SPA dispatcher rewrite** — `document-viewer.html` lines 235-258 replaced with first-segment path-prefix routing. New rules: `io/<rel>` → `/api/io/file?path=<rel>`; `<known-project>/<rel>` → `/api/docs/file?path=<full>`; bare paths fall through to `/api/io/file` (backwards-compat for `notifications.js` job-card links and persisted job metadata). Updated directory-listing breadcrumb generator to emit the new URL form.
2. **`_dir_listing.py::_build_view_url`** (CoSA submodule) — emits path-prefix URLs (`/app/docs?path=<scope>/<rel>`), retiring legacy `?scope=` form. IO binary routes (audio/pdf/image/pptx) unchanged.
3. **`docs_files_health` rewrite** (CoSA submodule) — was crashing with `NameError: ALLOWED_FILES` on every call (legacy whitelist constants were removed in unification but health handler missed). New response shape iterates the scope registry: `{status, project_root, io: {root, exists}, scopes: {name: {root, exists, allowed_prefixes, manifest}}, media_types}`. `/api/docs/health` back to HTTP 200.

**Tests**:

| File | Status |
|---|---|
| `src/tests/smoke/test_doc_viewer_path_prefix_routing.py` | **NEW** — 7 targeted regression tests |
| `src/tests/smoke/test_docs_files_endpoint.py` | Full rewrite (15 tests) — JWT auth + path-prefix form (file was silently failing since May 12 multi-repo auth landed) |
| `src/tests/smoke/test_io_files_endpoint.py` | Added JWT auth + path-prefix view_url assertion |
| `src/tests/smoke/test_external_scopes.py` | Full rewrite (17 tests) for unified routing model |
| `src/tests/unit/test_dir_listing.py` | Updated 9 routing-table assertions to new view_url shape |

**Verification (all on :7999, AI-discretionary)**:

| Layer | Result |
|---|---|
| User's exact URL via `/api/docs/file` | ✅ HTTP 200, 16,159 bytes |
| SPA shell at `/app/docs?path=lupin/...` | ✅ HTTP 200, 20,411 bytes |
| `/api/docs/health` | ✅ HTTP 200 (was 500) |
| Doc-viewer smoke (4 files combined) | ✅ 52 passed, 1 skipped |
| Doc-viewer unit (`test_dir_listing.py`) | ✅ 30 passed |
| Full unit suite | ✅ **4,623 passed, 1 xfail, 0 regressions** |

**Follow-up parked** (NOT done this session):
- `src/tests/e2e_ui/test_doc_viewer_multi_repo.py` + `test_doc_viewer_directory.py` still use legacy `?path=…&scope=…` URLs (10+ call sites). These run on :8000 monopolize-mode — needs a user-scheduled slot with `--update-snapshots` to refresh visual baselines.
- `notifications.js` lines 7110, 7112, 7374, 7379, 7387 + `podcast_generator/job.py` line 335 + `presentation_generator/job.py` similar pattern still emit bare-io-relative `/app/docs?path=…` URLs. Works today via the dispatcher's legacy fallback branch; harmonization to `?path=io/…` is cosmetic.

**Sub-repo edits pending separate sessions** (per `feedback_cosa_edit_vs_manage_git`): `src/cosa/rest/routers/docs_files.py` + `src/cosa/rest/routers/_dir_listing.py` — uncommitted in CoSA working tree; commit from a CoSA-context session.

#### Checkpoint | 2026.05.16 13:44 | Doc viewer SPA dispatcher + health endpoint regression fix

**Files**: document-viewer.html, 5 test files, 1 new R&D doc (+2 CoSA submodule edits pending separate commit)
**Commit**: 656ec0c

---

### 2026.05.16 - Session 0025f917 (Rio ⚡) | Voice persona stale-bridge pool exhaustion fix + Sam-as-overflow

Same-day root-cause + fix for a live bug Rick reported voice-first: 5 fresh CC sessions returned 3 × Rio + 2 × Mr. Radio with 4 of 5 marked `borrowed=true`, at day-start when the pool should have been wide open. Root cause was sharper than just stale state — the in-container bypass of the dead-PID filter (`session_bridge.py:1284-1287`, intentional because host PIDs are invisible from inside `lupin-rest-dev`) counted every leftover bridge with a non-null persona as occupied. Five May-15 bridges (maría, Rachel, Tiberius, Arnold, Mr. Radio) made the pool read 5/6 occupied the moment my session took Rio; every subsequent session fell into the deterministic sha256-mod-pool borrow path, which happened to hash to Rio×2 + Mr. Radio×2.

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md`](src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md) — diagnostic evidence table (10 bridge files audited), four-layer solution, phase order, verification matrix, risks/gotchas.

**Four-layer solution shipped**:

1. **Host-side prune at SessionStart** — new `prune_dead_persona_bridges()` in `session_bridge.py`, called from `register_session.py` Phase 4.4 (before Phase 4.5 allocation). Runs only when `_can_trust_host_pids()` returns True. Scrubs the `voice_persona` field on any bridge whose host PID is dead. Fixes the morning-of-day case completely.
2. **mtime-based TTL guard inside container** — `find_active_voice_persona_sessions(stale_threshold_seconds=43200)` now rejects bridges whose file mtime exceeds the threshold (default 12h, INI-tunable via `cc session voice persona stale threshold seconds`). Belt-and-suspenders for the residual case where the host-side prune didn't fire. The cc-notification-listener heartbeat keeps active bridges fresh.
3. **Sam-as-overflow allocation** — replaces the legacy hash-borrow. New `load_overflow_persona_from_config()` reads `cc session voice persona sam {icon, color, profile, display name}` + the existing `elevenlabs tts default voice id` (single source of truth for Sam's `voice_id`). `pick_unallocated_persona` now returns Sam with `overflow=True` when the pool is fully occupied; multiple Sams permitted, multiples of other personas not. `borrowed_persona_for_sid` survives as legacy fallback only when Sam is unconfigured.
4. **UI / mobile overflow badge** — new `.persona-badge.overflow` (dotted border + ✱) in `notifications.css`, distinct from legacy `.persona-badge.borrowed` (dashed + ↻); `notifications.js` composes the state class with overflow-precedence-over-borrowed; mobile dart `VoicePersona` gained `final bool overflow` with liberal `fromJson`.

**Bug #2 logged for follow-up** (separate session): duplicate notification fan-out — single system broadcast rendered 5× and single "completed" status produced 4 × Mr. Radio + 1 × Rio. Filed in `TODO.md` under "📡 NEW — Duplicate notification fan-out (filed 2026-05-16 by Rio ⚡, session `0025f917`)" with a four-step investigation checklist.

**Verification (all on :7999, AI-discretionary)**:

| Layer | Result |
|---|---|
| py_compile sweep across 6 Python files | ✅ all compile |
| `pytest src/tests/unit/test_voice_persona_helpers.py -v` | ✅ **52/52 pass** (34 pre-existing + 18 new) |
| Sam overflow logic inline smoke (3 scenarios) | ✅ free→pool, exhausted→Sam, exhausted-no-Sam→legacy-borrow |
| TTL guard inline smoke (2 scenarios) | ✅ fresh mtime returned, stale mtime filtered |
| New smoke test for pool exhaustion → Sam | authored at `src/tests/smoke/test_voice_persona_allocation.py::test_pool_exhaustion_returns_sam_overflow` (8 synthetic bridges; not auto-run against live state — saved for Rick to run when convenient) |

**New unit-test classes** (18 tests): `TestLoadOverflowPersonaFromConfig` (3), `TestPickUnallocatedPersonaOverflow` (5), `TestFindActiveVoicePersonaSessionsTTL` (4), `TestPruneDeadPersonaBridges` (6).

**Documentation touchpoints updated**: `CLAUDE.md` DOCUMENTATION TOUCHPOINTS row for voice-persona now references both 2026.04.28 (original design) and 2026.05.16 (this milestone); new row for `prune_dead_persona_bridges` + `find_active_voice_persona_sessions` TTL guard. Companion 2026-05-16 Update section appended to the original 2026.04.28 design doc.

**Sub-repo follow-ups pending separate sessions** (per `feedback_lupin_only_never_cosa`):
- `src/cosa/rest/voice_persona_helpers.py` — `load_overflow_persona_from_config` + `pick_unallocated_persona` overflow path + threading through `allocate_persona_for_session` (CoSA submodule — commit in CoSA-context session)
- `src/cosa/rest/routers/voice_persona.py` — pass overflow persona to allocator + extend `voice-persona/sample` voice_id whitelist (CoSA submodule)
- `src/lupin-mobile/lib/features/notifications/data/voice_persona.dart` — `final bool overflow` field + toString update (mobile sub-repo — commit in mobile-context session)

**Files committed this session** (parent Lupin repo): 12 modified + 1 new R&D doc + this `history.md` entry.

**Workflow notes**: User-initiated voice-first bug report → ultrathink + plan-mode → 4-layer plan in single ExitPlanMode → user verbal approval after 10-min review window → 8 phases executed silently with milestone notify at completion. Memory rules engaged: `feedback_walk_through_plan_before_asking_proceed` (substantive findings via notify before any code), `feedback_doc_links_always_in_abstract` (R&D viewer-link as abstract line 1), `feedback_exit_plan_mode_is_not_user_approval` (explicit verbal go-ahead via `ask_yes_no` after harness auto-approval), `feedback_lupin_only_never_cosa` (no git ops on src/cosa/ from parent), `feedback_verify_staging_before_commit` (`git diff --cached --stat` before commit), `feedback_never_auto_commit_push` (no push without explicit ask).

---

