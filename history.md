# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-16 to 05-18](history/2026-05-16-to-18-history.md). History health: ✅ **HEALTHY at 11,531 tokens (46.1% of 25k)** — archived 2026-05-28 by Rio ⚡ (session a507b1a5), 9,087 tokens moved to archive.

### 2026.06.01 - Session 78c4780f (Krishna 🦚) | TTS preview-fraction slider: 25% → 12.5% increments

**Voice-driven follow-on fix on `wip-v0.1.8` (checkpoint, not pushed).** Changed the TTS preview-fraction slider in the Claude Code Notifications accordion header to step in **12.5% increments** (nine stops: 0 / 12.5 / 25 / 37.5 / 50 / 62.5 / 75 / 87.5 / 100) instead of 25% (five stops). The slider default stays 25% — only granularity changed.

**Three coordinated edits:** (1) `notifications.html` — `step="25"` → `step="12.5"` + expanded the tick `<datalist>` from 5 to 9 options. (2) `notifications.js` — the `input` handler used `parseInt`, which would truncate `12.5` → `12`; switched to `parseFloat`. Also dropped the `Math.round` in the init-seed (it would round 12.5 → 13, off-step) and now reads the browser-snapped slider value back so the label always matches the thumb. (3) new `TestTTSFractionSlider` class in `test_tts_controls.py` (5 cases): step attr, nine ticks, half-step round-trip (regression guard against the parseInt bug), integer-stop no-regression.

**E2E verified on `:8000`:** `-k TestTTSFractionSlider` → **5 passed / 0 failed**; the companion STT suite re-ran **8 passed / 0 failed** (13/13 green, sequential). An earlier 11:23 run reported 0 tests — traced to a *submission* bug (quoted multi-word `-k` shattered by the endpoint's whitespace-split of `pytest_args`, exit=4), not a code defect; fixed via single-token `-k` runs. Lesson added to auto-memory `feedback_test_suite_submit_field_pytest_args`.

---

### 2026.06.01 - Session 78c4780f (Krishna 🦚) | STT recording button: select-all+overwrite → insert-at-caret

**Voice-driven fix on `wip-v0.1.8` (checkpoint, not pushed).** Changed the notifications-client recording button so transcribed text is **inserted at the caret** instead of selecting-all + overwriting the whole field; a highlighted range is still replaced (the one intentional overwrite case), and the caret lands after the inserted text so repeated dictation appends. Extracted the logic into a reusable `_insertTranscriptionText( inputElement, text )` helper on `NotificationsUI` — all 8 STT contexts (qa, cc-prompt, research, podcast, swe, presentation, broadcast, session-rename) funnel through the one `onTranscription` callback, so the fix is universal.

**Runtime bug caught + fixed live:** first cut called the helper as `self._insertTranscriptionText`, but in that callback `self` is the `recordingManager` object literal, not the page controller — `not a function` at runtime. Corrected to `self.ui._insertTranscriptionText` (`recordingManager.ui` is the `NotificationsUI` instance, same `self.ui` already used for logging). Rick confirmed working in the browser.

**Tests** (`src/tests/e2e_ui/test_stt_insert_at_cursor.py`, new — 8 Playwright cases): empty/start/mid/end insert, highlighted-replace, full-select-replace, null-caret append fallback, plus a **wiring-chain guard** (`recordingManager.ui === notificationsUI` + helper resolves) added specifically because the direct-helper tests would NOT have caught the `self` binding bug. Verified `node --check` + `py_compile`; full E2E deferred to a scheduled `:8000` slot. **Files:** `static/js/notifications.js`, new e2e test.

---

### 2026.06.01 - Session 3047b30f (Tiberius 👑) | CoSA coverage Run-2: zombie reap → fleet recovery → 3 agent packages @ 100% + prod bug #11

**Ran the CoSA 100%-coverage Run-2 fleet end-to-end as manager; 10 test-only commits banked on `wip-v0.1.8`, pushed at Rick's session-end go (66 commits total to remote — the whole held campaign).** Opened by reaping **11 zombie `cc_notification_listener` orphans** (sessions whose parent CC/tmux died but whose detached ppid=1 listener kept polling — the PG-6 worker-shutdown bug; raw `tmux kill-session` + the bugged `dismiss_sessions` both leave them). Only the 2 with a live `claude` parent (María, me) were legit.

**Fleet arc:** started solo-sequential (María authoring); Rick course-corrected (3 broadcasts) back to the runbook fleet topology. Spawned a reviewer (seat "Krishna" → voice Mr. Radio 🦉) + 3 authors (Tiffany 💍 / Cheech 🦚 / Rachel 🕊️). Diagnosed an **intermittent spawned-session read fault** — file reads AND tool output occasionally truncate/garble then recover on retry; does NOT corrupt pytest `--cov` numbers — the root of the session's confabulation cluster. Fix in practice: retry-before-report, never fabricate. (Root launch-config cause still open per Rick's debug directive.)

**3 complete agent packages @ genuine 100%** (manager disk-verify → Mr. Radio independent re-measure + line-by-line audit → surgical single-file commits, every batch): **notification_proxy** (12 mod, 801/0/236, 173 tests, `67c0222`), **prediction_engine** (7 mod, 766/0/268, 237 tests, `fb679dd`+`d722396`), **decision_proxy** (18 mod, 830/0/214, 240 tests, B1–B6 `9a02f6e`→`8964e72`). ~650 tests, **zero API spend** (firewalled key never read; LanceDB/vLLM/scipy/embeddings all boundary-mocked).

**Prod bug #11** (silent dead-tier, same family as #10): `prediction_engine.py:990` imported `LlmClientFactory` from `cosa.agents.llm_client` (no such symbol) → ImportError bare-except-swallowed → `_get_llm_client` always None → Tier-2 LLM synthesis of open-ended prediction **dead in prod**. Rachel tripwired (xfail-strict + pin, never pragma'd a bug-blocked line); I fixed the import + completed the de-arm (incl. retiring the now-false tombstone comments per Mr. Radio's catch — a doctrine refinement), reviewer-ratified (`d722396`).

**2 ratified pragmas:** `responder.py:295` no-branch (exhaustive strategy dispatch, committed) + `util_xml_pydantic.py:210` no-cover (multi-root `else` unreachable — empirically proven: xmltodict raises ExpatError on every non-single-root input; held with io_models wave-2). **The zero-trust gate caught 5+ confabulations + a surgical-staging trap — nothing fabricated reached a commit.** All 3 authors honest-stopped after their packages.

**Wave-2 deferred (handoff docs written, idle fleet reaped at stand-down):** io_models remainder (xml_models 79%→100% + watchdog) + rest/ 37 stale-mock repairs (a possible queues-auth regression flagged for tripwire) — `07-rachel-io-models-watchdog-handoff.md` + `07-rest-stale-mock-repair-handoff.md`. io_models partial WIP (green baseline restored + utils + 6/16 xml_models classes, ungated) committed separately as labeled WAVE-2 WIP.

**Run-2 commits (10):** `ce9087e 9a02f6e fb679dd 67c0222 8e72f61 d722396 762e301 2312e5e 50baada 8964e72`.

---

### 2026.05.30 - Session fb0bc8a5 (Speedy 🌿) | Notifications-UI polish: focus-card height, broadcast toggle, master-detail reading pane, persona rename

**A voice-driven UI-polish session on `wip-v0.1.8` — three commits, each verified on `:7999`; not pushed.** Parallel-session-safe throughout (the GCP session 657452e9 + coverage session own `README.md`/`TODO.md`/untracked GCP+coverage docs — deliberately EXCLUDED from every commit; my README doc-links left in the working tree for those sessions to carry).

**Commit `23d3726`** — focus-mode sender-card height (+50%) + the broadcast `commons-activity-entry` "Show more" toggle. Toggle root cause: a one-shot `requestAnimationFrame` overflow check measured 0×0 while the Recent Activity panel was collapsed (`display:none`) — system broadcasts arriving via WebSocket while it was closed never revealed the toggle; fixed with a `ResizeObserver` re-measure. Focus boost first targeted the orphaned `.sender-card-messages` class (no render path produces it) → repointed to the real `.date-accordion-messages` scroll region.

**Commit `585283d`** — voice-persona pool rename Speedy → Cheech ("as in Cheech & Chong"; label-only — voice id/icon/color/profile preserved). Live session stays Speedy (rename affects future allocations, not the running bridge). New auto-memory `reference_hot_config_reload` (Rick's dev env hot-reloads `lupin-app.ini` — no `:7999` bounce needed for INI-only changes).

**Commit `cd6cc99`** — master-detail Reading Pane cluster: (1) layout-mode toolbar centering (was pane-blind `ratio/2`≈33% → 50% when pane closed, re-centers on open/close); (2) reading-pane iframe "localhost refused to connect" diagnosed as global `X-Frame-Options: DENY` blocking same-origin framing → `SAMEORIGIN` for `/app/docs` only, `DENY` elsewhere (verified live via header probe); (3) iframe "postage stamp" = indefinite `.content-pane` height (only `max-height` + `align-self:flex-start`) → definite `calc(100vh-100px)` + `.content-pane-body` `min-height:0` + `:has(iframe)` edge-to-edge padding; (4) new "bust out" header button (⤢) → opens the pane's current content in a new browser tab (doc URL / rendered abstract), then closes the pane + re-centers; (5) focus boost bumped +50% → DOUBLED (250→500px).

**Tests:** new `test_layout_mode_toolbar_centering.py` (centering + iframe-fill + bust-out E2E), `test_doc_viewer_iframe_embedding.py` (X-Frame smoke — **3/3 passed live on `:7999`**), plus updated assertions in `test_cc_session_strip_and_focus.py` + `test_commons_activity_toggle.py`. Full E2E (`:8000`, scheduled) to run before any merge.

**Files:** `src/fastapi_app/main.py`, `static/html/notifications.html`, `static/css/notifications.css`, `static/js/notifications.js`, `src/conf/lupin-app.ini` + `-splainer.ini`, 3 e2e/smoke test files. **R&D docs:** `2026.05.30-notifications-ui-focus-height-and-broadcast-toggle.md` + `2026.05.30-master-detail-reading-pane-fixes.md`. **New auto-memory:** `reference_hot_config_reload`.

---

### 2026.05.30 - Session 657452e9 (Sam 🎙️) | GCP deployment: survey → straw-man plan → Cloud-Run-vs-GCE comparison → decisions locked → prod-wording scrub (checkpoint)

**Drove the GCP-deployment planning arc end-to-end on `wip-v0.1.8`; mid-session checkpoint (not pushed).** Three R&D docs created under `src/rnd/v0.1.8/2026.05.30-gcp-deployment/`: (1) an 11-agent architecture-survey + readiness assessment; (2) a 2,400-line section-by-section **straw-man provisioning & deployment plan** (14-agent author→critic→assemble workflow; three blocking contradictions reconciled — Alembic-not-on-startup, the 2026-06-15 Agent-SDK $200 credit ceiling, the Milestone-1 HTTPS-LB cost line); (3) a fact-checked **Cloud Run-GPU vs GCE g2-standard-8+L4 + Claude-Code-hosting** comparison (verdict: the VM wins on cost, fit, and CC — same L4 silicon, opposite execution model; you can't SSH into Cloud Run).

**Strategic decisions resolved with Rick** (cosa-voice `ask_multiple_choice` walkthrough): single GCE g2-standard-8 + L4 VM · CC OAuth = setup-token in Secret Manager + a refresh mechanism · CC consolidated onto the GPU VM · exclude-keys+rotate+verify-history · reuse sandbox project · Terraform+bash · no staging · on-demand (credit-covered, tracked as real $). **Milestone 1 re-scoped: local-dev → GCP-_test_ migration, NOT production.** Then scrubbed the now-misleading "production" wording across the plan (33 targeted edits via a focused sub-agent; future-prod refs + load-bearing code literals preserved; a new `LUPIN_ENV`-tension OPEN ITEM noted).

**Files** (this checkpoint): `src/rnd/v0.1.8/2026.05.30-gcp-deployment/` (3 new docs) + `history.md` + `TODO.md`. **Deferred:** `src/rnd/README.md` index links (multi-session conflict — committed later). New auto-memory: `feedback_track_gcp_costs_as_real_money`.

---

### 2026.05.30 - Session ac012bd2 (Tiberius 👑) | CoSA 100%-coverage campaign — fully planned, evidence-gathered, staged for off-peak grind

**Planned + staged the CoSA 100%-coverage grandfathering-ramp campaign end-to-end; gathered combined-coverage evidence; authored a cold-start runbook. The overnight fleet grind itself is deferred to the off-peak window. On `wip-v0.1.8`.**

**Decisions ratified (interactive walk-through with Rick via `ask_multiple_choice`):** D1 **HYBRID** methodology (credit REST to the server suites — +1,776 lines / 70% of the integration delta; everything else unit-only; orchestration server-delta was +0, refuting the "integ-likely" guess); D2 denominator (omit test-files + `training/`; harvest→migrate-to-pytest→delete-after-green for `quick_smoke_test`/`__main__`/all legacy tests); D3 **flat** topology (Tiberius manages 3 authors directly; lead-author role); heartbeat = new `heartbeat_poker_job` (old `cascade_heartbeat_scheduler.py` fallback); D5 strict guardrails + adversarial reviewer scored on *valid* hollow-tests-caught; D6 standing **TEST-ONLY** overnight commit authority (zero production-logic edits); D7 per-batch green-gate + periodic combined re-measure; D8 **milestone ramp** (config+library by 06-05; agents/REST ramped); fleet = 3 authors on disjoint module-groups; reviewer gates commits per module-group; D4 tiering = **library (~4.2k, 06-05 milestone) → agents (~8.4k long pole) → REST-remainder + orchestration**.

**Combined-coverage evidence (Tiffany 💍, spawned author — since reaped):** unit-only **45.3% line / 34.8% branch** (corrected denominator; raw 26.9% was inflated by test-files + smoke/`__main__` + `training/`). Combined unit + `:8000` integration + E2E = **52.0% line / 41.7% branch** (lower bound). Per-module integration delta: REST +1,776 (70%), memory +348, agents +319, orchestration +0. The `:8000` instrumentation was authorized by Rick's **DIRECT broadcast** (a peer relay was correctly refused — the `:8000` governance gate working). Infra reverted, working tree clean. Baseline: `src/rnd/v0.1.8/2026.05.30-cosa-100pct-coverage-baseline.md`.

**Heartbeat-poker dry-verify (STATIC only):** `send_to` posts to `dm-<slug>` + fires the `register-question` wake-push (revives idle sessions); `last_post_ts` reads global `who()` (any commons post resets the manager's streak); factory `create_agentic_job("agent router go to heartbeat poker", {recipients, cadence_seconds:300, termination_topic:"coverage-campaign-control", termination_signal_kinds:["stand_down"], workstream_id})` wires the real gateway via `from_environment`; one agentic pool slot. **A LIVE poker tap is still PENDING** (the §7 live-E2E / a scripted stand-in) — run it BEFORE trusting the poker unattended.

**Docs (campaign home `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/`):** `00-campaign-plan.md` (decision-of-record / the *why*), `02-cold-start-runbook.md` (**THE standalone cold-start operator doc** — the *how*; authored by María 🌸 = Workflow Steward), `README.md` index. María authors a reusable cross-repo "heartbeat-poker-supervised overnight fleet grind" workflow AFTER end-to-end validation.

**▶ RESUME POINTER (cold-start):** the campaign is fully staged. Next action = the **off-peak launch (tonight, post-midnight EDT)** via the runbook's **§15 cold-start checklist**: live-verify the poker → land the Tier-0 `[tool.coverage]` config → spawn 3 FRESH authors + 1 reviewer (cold-briefed from the runbook, disjoint Tier-1 module-groups) → run the grind (per-batch reviewer-gate + green-gate, test-only commits). Also: schedule a clean un-instrumented `:8000` E2E to validate 31 E2E failures from the combined run (NOT our regression — a parallel session's uncommitted UI edits to `test_cc_session_strip_and_focus.py` + `test_commons_activity_toggle.py`). Tiffany was reaped (fact-gathering complete); the grind fleet spawns fresh from the runbook.

**Files** (this commit): `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/` (00/02/README), `src/rnd/v0.1.8/2026.05.30-cosa-100pct-coverage-baseline.md`, `TODO.md`, `history.md`. (Out-of-repo, persist across /clear: session memories `feedback_walk_me_through_means_interactive_asks.md`, `feedback_waking_idle_spawned_sessions.md`.) Parallel-session changes deliberately EXCLUDED from staging: `.claude-session.md`, `src/rnd/README.md`, `src/rnd/v0.1.8/2026.05.30-gcp-deployment/`, notifications-UI edits.

---

### 2026.05.30 - Session ac012bd2 (Tiberius 👑) | CLAUDE.md perf-trim under 40k + TODO triage

**Cleared the project `CLAUDE.md` performance warning (40.3k > 40.0k) and triaged the TODO list. On branch `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment`.**

**`CLAUDE.md` trim — 40,311 → 33,278 chars (−7,033; ~6.7k headroom under 40k), zero doctrine lost.** Three sections, dedupe + de-staling only: (1) `100% COVERAGE MANDATE` — was titled "MULTIPLEXER TYPESCRIPT" and still listed Python/`src/cosa` as *out of scope* (stale since the mandate went Lupin-wide 2026-05-16 and CoSA folded in 2026-05-29); rewrote to current Lupin-wide scope with a pointer to the auto-memory + origin doc. (2) `TESTING` (5.7k→~1.6k) — collapsed verbose per-suite bullets + duplicate command block + stale counts into one suite table + the `--bg` mandate + doc pointers. (3) `PR MERGE REQUIREMENTS` (3.2k→~1.5k) — compressed to the ordered gate sequence + final-gate rationale + failure rule + anti-patterns. `TESTING VENUES` (canonical rubric) + `TEST CREDENTIALS` left untouched; the trimmed sections now reference the rubric instead of restating it. (María 🌸 independently handled the *global* `~/.claude/CLAUDE.md` 40k warning — clean split confirmed via DM, no overlap.)

**TODO triage.** Added a new 🔴 TOP-PRIORITY entry formalizing the **CoSA 100%-coverage grandfathering-ramp gate** (deadline 2026-06-05) — it previously existed only as a ratified decision buried in a DONE block, never as an actionable item. Marked two items done per Rick: the **wip-v0.1.8 push** (verified origin synced at `2240bf6`, 0 ahead/0 behind) and the **LanceDB Phase 0 disk reclaim** (~81GB freed via the 2026-05-29 rebuild; the recurring-compaction *scheduling* half stays tracked under the durable scheduled-job entry).

**Files**: `CLAUDE.md`, `TODO.md`, `history.md`.

---

### 2026.05.29 - Session 5496cbb6 (Krishna 🦚) | CoSA→Lupin mono-repo FOLD landed + post-fold doctrine scrub

**The CoSA framework is now folded into the Lupin mono-repo — the hard prerequisite for the GCP deployment push.** Builds on this session's earlier Phase-A venv relocation (entry further below).

**Mono-repo fold (flatten)** — `0a01da3`. `src/cosa/` (621 files) is now first-class tracked Lupin source, no longer a gitignored nested repo. Mechanics: **MOVED** `src/cosa/.git` aside (NOT deleted) to `/mnt/DATA02/cosa-git-archive-2026.05.29/` — full CoSA history + 42 branches preserved, fully reversible; removed the `src/cosa` `.gitignore` blanket + added a `src/cosa/.venv/` guard; `git add src/cosa`. Imports unchanged (`cosa.*`, PYTHONPATH=src). Validated on the folded tree: **unit 5058/0, WS smoke 50/50**. Decisions (Rick-ratified): flatten · move-aside-not-delete · directly on `wip-v0.1.8` · coverage = cosa **inherits** the 100% gate with an immediate grandfathering ramp (Tiberius owns the Lupin-side impl).

**Post-fold doctrine scrub** — `6bac0bc`. Removed the "src/cosa is a separate repo / submodule / never-manage-CoSA-git" doctrine from `CLAUDE.md` (CoSA dropped from the nested-repos list; Firefox + Mobile kept); SUPERSEDED banner on `src/cosa/CLAUDE.md`; removed the hazardous newline-named junk file `src/cosa/tests/smoke/infrastructure/<|system|>…` (preserved in the `.git` archive). Out-of-repo (user config): deleted the 2 obsolete CoSA-separation memories + flipped the coverage memory to cosa-inherits-the-gate. María updated the PIP-side doctrine (`bbcd865`). **Flagged residual**: the `nested-repo-management` skill (no locatable file — likely plugin-managed; needs CoSA dropped, Firefox/Mobile kept) + 2 minor stale memory bodies.

**Full analysis/plan**: `src/rnd/v0.1.8/2026.05.29-cosa-lupin-monorepo-merge-analysis-and-plan.md`.

**Files** (this milestone): `.gitignore`, `CLAUDE.md`, `src/cosa/CLAUDE.md`, 621 `src/cosa/*` files (fold), `history.md`, `TODO.md`. (Out-of-repo: memory files.)

---

### 2026.05.29 - Session c9c582b7 (Tiberius 👑) | Scheduled-job missed-window catch-up (durable across bounces)

**Closed the missed-window gap in scheduled-job restoration: a job whose `scheduled_at` passes WHILE the server is down is now caught up on restart instead of dropped as INTERRUPTED.** On the post-fold mono-repo (`wip-v0.1.8`); cosa-side code committed via the fold (`0a01da3`), parent wiring committed here.

**Finding:** the core scheduled-job persistence + restore-on-boot ALREADY EXISTED (`mark_interrupted_jobs` → `get_restorable_jobs` → `main.py` re-enqueue). The only real gap was past-due-during-downtime jobs being marked INTERRUPTED.

**Design (Rick-ratified):** record when the server was last available and compute the EXACT downtime window rather than guess a grace interval. Recording = 60s clock-loop heartbeat + clean-shutdown marker (heartbeat survives hard kills). `mark_interrupted_jobs()` now preserves PENDING jobs whose `scheduled_at` ∈ `[last_available, now]` for an immediate catch-up run; `get_restorable_jobs()` re-enqueues them unchanged; the consumer fires them (`scheduled_at <= now`).

**Verified:** live `:7999` bounce → clean boot, recovery sweep ran, heartbeat stamped `server_lifecycle` at startup. 40/40 unit tests (logic + lifecycle + catch-up branches), 100% coverage on changed lines.

**Files** (parent commit): `src/fastapi_app/main.py` (heartbeat in `clock_loop` + shutdown marker + recovery logging), `src/migrations/versions/e9f0a1b2c3d4_add_server_lifecycle_table.py` (new), `src/tests/unit/test_job_restoration.py` (+24 tests), `src/rnd/v0.1.8/2026.05.29-scheduled-job-bounce-survival.md` (new), `history.md`, `TODO.md`. cosa-side (committed via fold `0a01da3`): `src/cosa/rest/job_persistence.py` (record/get/`_is_within_downtime` + catch-up branch), `src/cosa/rest/postgres_models.py` (`ServerLifecycle`). Migration applied to `lupin_db_dev`.

**Remaining:** full real schedule→bounce-straddle→catch-up E2E (Rick-assigned, in progress).

---

### 2026.05.29 - Session 5496cbb6 (Krishna 🦚) | v0.1.7→main PR + CoSA→Lupin merge analysis + Phase A local-venv relocation

**Three arcs on branch `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment`: shipped the v0.1.7 PR, researched the CoSA mono-repo merge, and executed the local dev-venv relocation (Phase A).**

**v0.1.7 → main PR.** Ran the branch-PR-and-merge workflow: README "What's New in v0.1.7" headline block + version-history entry + version bump; repaired 9 stale unit tests (git_loc_delta v1.1 API drift + embedding model-server-carveout isolation — both stale-test-vs-correct-source, source untouched); rode Tiberius's pgvector TODO note. Dev gates green (unit 5034/0, WS smoke 50/50). PR #17 squash-merged to main; created this v0.1.8 branch and **kept** the v0.1.7 local branch per Rick.

**CoSA→Lupin mono-repo merge — research + plan (Phase B, GATED, NOT executed).** Two multi-agent research workflows (~1.19M tokens) → verdict: folding CoSA into Lupin is the correct end-state (zero external consumers verified on-disk+SSH, 52 reverse-imports CoSA→host, no packaging/version-pin, lockstep releases), but execute gated/staged via history-preserving `git subtree` **after v0.1.8 ships**, on a dedicated branch, behind an authenticated-operator PR/branch-protection check + pushing the 2 unpushed CoSA branches. Corrected a doctrine premise: `src/cosa` is **NOT a submodule** — it's a gitignored independent nested repo (no `.gitmodules`, no gitlink). Full analysis + weighted pros/cons: `src/rnd/v0.1.8/2026.05.29-cosa-lupin-monorepo-merge-analysis-and-plan.md`.

**Phase A — local dev-venv relocation (DONE, 3 commits, green).** Replaced the stale miniconda `src/cosa/.venv` (py3.11, 367-pkg cruft) with a clean root `.venv` (py3.13) built from the container's `uv.lock` **minus** three native packages the host can't build and nothing host-side imports (pyaudio, flash-attn, autoawq) + the `en_core_web_sm` model. Rick's directive: mirror the container, no old artifacts. CUDA honored — torch `2.6.0+cu124` runs on driver 535 via Minor Version Compatibility (`cuda_available=True`); the historical doom-loop was a container-only `cuda-compat-12-4` forward-compat shim (already purged). **Production Dockerfile deliberately UNTOUCHED** (zero container blast radius). Repointed **ALL 14 venv refs across 11 scripts** — a full repo sweep that caught 4 `src/tests/run-*.sh` runners the recon had missed — and added reproducible `src/scripts/build-local-venv.sh`. Verified on the new venv: unit **5034 passed / 0 failed**; WebSocket smoke **50/50**.

**Commits (this session, on `wip-v0.1.8`, LOCAL + UNPUSHED):** `bf97e1a` (gitignore guard), `eda7caf` (openapi-to-md dep), `6cdcb7b` (script repoints + builder). Old `src/cosa/.venv` kept as fallback. Push awaits Rick's explicit go.

**Files** (this checkpoint commit): `history.md`, `TODO.md`, `src/rnd/v0.1.8/2026.05.29-cosa-lupin-monorepo-merge-analysis-and-plan.md` (new). (The Phase A code landed in the 3 commits above.)

---

### 2026.05.29 - Session c9c582b7 (Tiberius 👑) | LanceDB rebuild + ~303GB disk reclaim + pgvector migration analysis

**Disk-reclamation campaign (~303GB freed), a corrupted-table rebuild, and a deferred pgvector analysis. On branch `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment`.**

**LanceDB `input_and_output_tbl` rebuild (~81GB reclaimed, 82GB → 679MB).** The table's version chain was corrupted (a missing/shifting `_versions/<n>.manifest`), so `optimize()` could not compact its ~100k uncompacted append-log versions. Current data was intact (101,521 rows). Rebuilt via new `src/scripts/rebuild_lancedb_table.py` (staged build/swap/backfill/reclaim): verified full backup → DATA02 → snapshot → drop + create fresh single-fragment table → bounce both servers. **Gotcha captured:** `rename_table` is `NotImplementedError` in LanceDB OSS (failed *closed* — caught atomically); the `drop_table`+`create_table`-into-same-dir fallback stranded a stray V1 manifest → mixed V1/V2 schemes → both REST servers crash-looped ~2 min → recovered by quarantining the stray manifest + restart. Lesson logged in TODO.md as a requirement for the durable-scheduled-job swap step.

**~303GB total reclaimed:** ~81GB lancedb rebuild (DATA01) + ~80GB backup-drive re-sync (DATA02 — re-ran `backup.sh --write`, `--delete` removed the stale 80GB copy) + ~142GB Docker (removed superseded `lupin:0.9.0` 130GB image that baked in the old ~80GB DB before `.dockerignore` excluded it, + 12.4GB build cache; orphaned model-server images + unused volumes pruned). Confirmed live `lupin:1.0.0` does NOT bake the DB (layer audit + `.dockerignore`) → **no image rebuild needed.**

**pgvector migration analysis (deferred).** A multi-agent research workflow produced `src/rnd/v0.1.8/2026.05.29-lancedb-to-postgresql-pgvector-migration-analysis.md`: verdict — the 81GB bloat was a missing-compaction-cron problem, NOT a vector-engine problem; "migrate-to-fix-bloat" was adversarially refuted. Revisit logged in TODO.md.

**Files** (this checkpoint, Lupin-parent): `src/scripts/rebuild_lancedb_table.py` (new), `src/rnd/v0.1.8/2026.05.29-lancedb-to-postgresql-pgvector-migration-analysis.md` (new), `src/rnd/README.md` (index: backfilled v0.1.7, added v0.1.8), `TODO.md` (durable scheduled-job persistence task + swap-lesson), `history.md`. **Operational reclaim (lancedb compaction, Docker prune) is not a committable artifact** — this commit captures the reusable tool + analysis + tracking docs. **Not staged:** Krishna's parallel `src/rnd/v0.1.8/2026.05.29-cosa-lupin-monorepo-merge-analysis-and-plan.md` (his session).

**Commit**: 1fbe9ee

---

### 2026.05.28 - Session 0da441e6 (Tiberius 🌑) | Extra-N overflow personas + Manager-Spawned Headless Reviewer Sessions

**Two features shipped (Lupin-parent commit; CoSA submodule + INI managed separately).**

**Extra-N overflow personas** — generalized the single-Arnold pool-exhaustion overflow into numbered "Extra N" identities (lowest-free index, gap-reusing, distinct colors, shared overflow voice), fixing the latent 2+-overflow collision. Allocator logic lives in CoSA `voice_persona_helpers.py` (submodule, managed separately); INI keys landed via parallel commit `908bf21` (Rio); tests + design doc in this commit. Note: the no-green color rule was retired by `908bf21` mid-flight — `TestExtraColorsGreenRule` reconciliation is TODO-tracked (the test passes; my palette is green-lowest regardless).

**Manager-Spawned Headless Reviewer Sessions** — a manager persona can spin up N headless Claude-Code + tmux reviewer sessions on demand via cosa-voice MCP tools `spawn_sessions` / `dismiss_sessions` / `list_spawned_sessions`, automating the manual reviewer-launch step of the cascaded plan-review workflow. New `session_spawner.py` (render/build/spawn/dismiss/list + idle-TTL reap + manifest lineage — **52 tests, 100% line+branch**); `--headless` detach path + venv provision on `start-cc-with-tmux.sh`; env-gated `register_session.py` tagging (`spawned_by`/`headless`/`role` + `speakerphone_on=False`); 3 thin `@mcp.tool` wrappers. **TTS-silence reuses the existing speakerphone primitive** — no parallel mute machinery built. **Live spawn-1-reap-1 E2E passed** and caught two real integration bugs (tmux env-forwarding; role/index name collision), both fixed. Cross-session co-design with María (operator runbook landed in planning-is-prompting). Decision record: `src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md`.

**Files Modified** (this commit, Lupin-parent): `src/scripts/start-cc-with-tmux.sh`, `src/lupin_mcp/session_spawner.py` (new), `src/lupin_mcp/cosa_voice_mcp.py`, `src/lupin_cli/claude_code/hooks/register_session.py`, `src/tests/unit/test_spawn_sessions.py` (new), `src/tests/unit/test_voice_persona_helpers.py`, `src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md` (new), `src/rnd/v0.1.7/2026.05.28-extra-n-overflow-personas.md` (new), `TODO.md`, `history.md`.

**Managed separately**: CoSA submodule `src/cosa/rest/voice_persona_helpers.py` (Extra-N allocator). Already committed by parallel session `908bf21`: `lupin-app.ini` + splainer (Extra-N color palette + spawn keys, swept in).

---

### 2026.05.28 - Session a507b1a5 (Rio ⚡) | Voice persona config: Tiberius icon + 2 new personas + retire no-green color rule

**Accomplishments**:
- Changed Tiberius badge icon 🌑 → 👑 in INI + splainer.
- Added 2 new pool personas: **Clayton** (laid-back male, voice `fQ9aRKjmL75dgjNakj2u`, light blue, 😎) and **Speedy** (stoner cartoon friend, voice `OhisAd2u8Q6qSA4xXAAT`, light orange, 🌿). Pool grew 8 → 10. Speedy color subsequently lightened #FFB74D → #FFCC80 (Orange 200) per follow-up.
- **Retired the no-green persona-color rule** per Rick's directive ("no longer in effect"). Removed all rule references from active config (`lupin-app.ini`, `lupin-app-splainer.ini`) and deleted auto-memory `feedback_no_green_in_persona_pool.md` + its MEMORY.md index line. Green **mic-monopoly pin** feature references preserved (separate concern).
- Archived history 05.16–05.18 → `history/2026-05-16-to-18-history.md` (main 20.5k → 11.5k tokens).

**Deferred (parallel-session safety / historical records)**: `TestExtraColorsGreenRule` in `test_voice_persona_helpers.py` (file owned by a parallel session), CoSA `voice_persona_helpers.py` docstrings, and ~18 dated R&D docs still reference the retired rule — queued in TODO.md.

**Files Modified**: 4 repo files + 1 new archive (`src/conf/lupin-app.ini`, `lupin-app-splainer.ini`, `history.md`, `history/README.md`).

---

### 2026.05.22 - Session 76351966 (Rio ⚡) | Heartbeat-poker CJ Flow ingestion wiring (gap-close)

Follow-on to the heartbeat-poker run (commit `cd37c3f`): closed the gap surfaced + escalated during I6 — `HeartbeatPokerJob` was not dispatchable through CJ Flow because `agentic_job_factory` had no `heartbeat_poker` entry. Tiberius assigned the close per Rick's follow-through directive.

**Factory wiring**: added the `agent router go to heartbeat poker` branch to `agentic_job_factory.create_agentic_job()` — parses `recipients` (dict list → `RecipientSpec` list), `termination_signal_kinds` (list or CSV), and the `_parse_optional_int` defaults; constructs the `HeartbeatPokerJob` + a `LupinCommonsGateway`. Added `LupinCommonsGateway.from_environment()` — the production IO-boundary constructor (real `CommonsStore` + API key + `requests`); `# pragma: no cover` with reason (exercised by the :8000 integration tier, not unit-mockable in isolation).

**Tests**: 11 factory-wiring unit tests (`test_agentic_job_factory_heartbeat.py`, new) + 1 factory-dispatch smoke test. Full local heartbeat suite — 78 tests green; both heartbeat modules hold gate-enforced 100% line+branch coverage. Integration + E2E skip-marks updated — the missing-wiring clause dropped (integration now venue-only; E2E now task-I7-only); both collect clean (5 tests, `--collect-only`).

**Files** — parent-Lupin (this commit): `src/tests/integration/test_heartbeat_poker_integration.py`, `src/tests/e2e/test_heartbeat_poker_e2e.py`, `history.md` (this entry). CoSA submodule (committed separately, own context): `heartbeat_poker_commons_gateway.py`, `agentic_job_factory.py`, `test_agentic_job_factory_heartbeat.py`, `test_heartbeat_poker_smoke.py`.

---

### 2026.05.22 - Session 76351966 (Rio ⚡) | Heartbeat-poker abstraction implementation (10-task run) + TTS limiter boundary-scan fix

Two bodies of work this session.

**TTS limiter — boundary-scan rewrite.** The notifications TTS preview-fraction slider truncated by sentence count; a newline-separated technical list (no `.!?` punctuation) defeated the splitter and read ~half the list aloud at the 25% stop. Replaced the sentence-count algorithm in `_computeTTSPreview()` with a character-position forward scan: jump to `ceil(length × fraction)`, then scan forward to the next boundary — a sentence terminal, an em/en-dash, or a **newline** (the key fix: a list item ends at a newline even with no punctuation). New `_truncateAtBoundary()` helper; `_splitIntoSentences()` retired; inline self-test rewritten (8 cases, verified in Node). Hyphen-minus deliberately NOT a boundary. The vestigial `tts preview include semicolons` INI key + splainer entry removed.

**Heartbeat-poker abstraction — full 10-task implementation run (Tiberius-managed).** Implemented the approved `src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md` plan end-to-end: 3 design-tier specs (D1+D4 class spec, D2 Watcher-protocol spec, D3 co-exist/swap/retirement doc); the `HeartbeatPokerJob` `AgenticJobBase` subclass + its three layered exits — clean-signal / dead-man's-switch / hard-cap (I1, I2); a production `LupinCommonsGateway` adapter; the `implementer-watch-protocol.md` Layer-2 doctrine (I3); two new termination-signal kinds in the PIP cascade defaults (I5); the full test pyramid (I6); Manager/Observer protocol `poke_body` compatibility (I9); and the production agentic-pool override (I10). Verified: 66 tests (58 unit + 8 smoke) green, 100% line+branch coverage (`pytest-cov --cov-fail-under=100`) on both heartbeat modules; integration + E2E files written + skip-marked for `:8000`. Swap-validation gates I4a-d/I7/I8 left for the operator-event-driven post-run. One gap surfaced + escalated to Tiberius: `HeartbeatPokerJob` is not yet wired into `agentic_job_factory` CJ Flow ingestion.

**Verification**: TTS — `node --check` + 8/8 inline self-test cases + config-load. Heartbeat — 66 tests green, gate-enforced 100% line+branch on `heartbeat_poker_job.py` + `heartbeat_poker_commons_gateway.py`; INI parse confirmed.

**Files** (parent-Lupin, this commit): `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/html/notifications.html`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/rnd/v0.1.7/2026.05.22-tts-limiter-boundary-scan.md` (new), `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d1d4-class-spec.md` (new), `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d2-watcher-protocol-spec.md` (new), `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d3-coexist-and-swap.md` (new), `src/docs/agents/implementer-watch-protocol.md` (new), `src/tests/integration/test_heartbeat_poker_integration.py` (new), `src/tests/e2e/test_heartbeat_poker_e2e.py` (new), `history.md` (this entry).

**Committed separately** (own repos, own contexts): CoSA submodule — `heartbeat_poker_job.py`, `heartbeat_poker_commons_gateway.py`, `system.py`, `test_heartbeat_poker_job.py`, `test_heartbeat_poker_commons_gateway.py`, `test_heartbeat_poker_smoke.py`. planning-is-prompting repo — `plan-review-cascaded-defaults.md`, `plan-review-cascaded-common.md`.

---

### 2026.05.22 - Session 2ce59c03 (Tiberius 🌑) | Voice persona: `request_persona` MCP tool + compaction carry-forward fix

Triggered by a live observation — the Mr. Radio session went through a context compaction and came back re-allocated as Krishna. Rick asked for two fixes, done in his stated order.

**`request_persona` MCP tool** — new `@mcp.tool` (plus `_request_persona` helper + `_persona_error_detail`) in `cosa_voice_mcp.py`, modeled on the speakerphone-toggle tool. Wraps the existing allocate/swap endpoint with the strict `requested_persona_name` query param; maps `200` → ok, `422` → not_in_pool, `409` → occupied, else → error. No degraded bridge-write fallback — allocation stays behind the server's `_voice_persona_lock`. First MCP-surfaced way to request or reclaim a named persona.

**Compaction carry-forward fix** — the `register_session.py` carry-forward gate was keyed on `is_context_clear`, which is True only when the transient session UUID rotates. A compaction can keep the same id, so the persona was dropped, the defense-in-depth block released it, and Phase 4.5 re-rolled (Mr. Radio → Krishna). Dropped `is_context_clear` from the gate: whenever a prior bridge holds a valid `voice_persona` dict it is preserved — across `/clear`, `/compact`, resume, and `--continue`. The fix is live immediately (SessionStart hooks are re-exec'd per event).

**Verification**: 30/30 unit tests (19 new for the tool, 11 register_session incl. 2 new compaction/resume cases); 38/38 sibling MCP tests pass (no regression); 100% branch coverage on all new code; live E2E against `:7999` exercised the `409 occupied` and `200 ok` response paths.

**Files**: `src/lupin_mcp/cosa_voice_mcp.py`, `src/lupin_cli/claude_code/hooks/register_session.py`, `src/tests/unit/test_cosa_voice_mcp_request_persona.py` (new), `src/tests/unit/test_register_session_preservation.py`, `src/tests/smoke/test_mcp_smoke.py`, `src/rnd/v0.1.7/2026.05.22-voice-persona-request-tool-and-compaction-carry-forward.md` (new), `history.md` (this entry).

---

### 2026.05.21 - Session 679e8f04 (Mr. Radio 🦉) | Recent Activity filter strip + Focus-bar chronological lock + Master-detail two-pane layout experiment

#### Checkpoint 3 | 2026.05.21 19:10 EDT | Iframe doc-link interception — root-cause fix; master-detail experiment pinned pending cascade review

Post-Checkpoint-2 follow-up. Rick kept hitting "localhost refused to connect" when clicking doc-links **inside** the Reading Pane's iframe. Earlier patches (document-viewer.html render-time URL rewrite, parent-page click interceptor) didn't resolve it because the failure is architectural, not a regex gap:

- **Clicks inside an iframe do NOT bubble to the parent document.** The parent's `document`-level click interceptor is structurally blind to iframe-internal clicks — an iframe is a separate browsing context.
- The only handler for iframe-internal links was `document-viewer.html`'s own render-time rewrite. That file is **cache-fragile**: the iframe lazy-loads `/app/docs?path=...` AFTER the parent page is interactive, so parent hard-reloads never bust it — the iframe kept serving a stale cached `document-viewer.html` predating the rewrite.

**Fix — parent-owned iframe link interception**: the iframe is same-origin, so the parent can script into it via `iframe.contentDocument`. New `_bindIframeLinkInterception(frame)` attaches a delegated click handler to the iframe's document on every `load`. `/app/docs?path=` links route through `_openContentPane` (Back-history participates); external links open in a new tab; same-origin non-doc relative links navigate natively. Parent code is `?v=`-cache-busted so it is always current — the stale-`document-viewer.html` problem becomes irrelevant. `_normalizeDocLinkHref` broadened to strip `127.0.0.1` / `0.0.0.0` loopback prefixes, not just `localhost`. `document-viewer.html`'s own rewrite retained as harmless defense-in-depth (regex similarly broadened).

**Status**: master-detail experiment **PINNED** per Rick — the iterative tail-chasing is paused pending a fresh cascaded plan-review run (Tiberius managing). Cache buster `v=20260521i`.

**Files**: `src/fastapi_app/static/js/notifications.js` (+`_bindIframeLinkInterception`, broadened `_normalizeDocLinkHref`), `src/fastapi_app/static/html/notifications.html` (cache buster), `src/fastapi_app/static/html/document-viewer.html` (regex broadening).

**Commit**: c1d611e

---

#### Checkpoint 2 | 2026.05.21 18:30 EDT | Master-detail two-pane layout experiment — design + 7 iteration cycles + draggable splitter

Second feature of the session, designed + implemented + iterated through Rick's voice feedback over the late afternoon. Switchable two-pane "horizontal" layout: existing `.container` collapses to ~2/3 width inside a new `.left-column`; new `<aside class="content-pane">` Reading Pane occupies the right ~1/3; draggable splitter between; persistent split ratio; section-toolbar floats horizontally over the top-center of the content area.

**Process pattern (re-applied from morning feature)**: pre-impl exploration → item-by-item walkthrough of 6 design choices via `ask_yes_no` / `ask_multiple_choice` → reuse-review pass → Phase 1/2 implementation → iterative tweaks driven by live visual feedback on `:7999`.

**Locked decisions (walkthrough)**: Reading Pane name; iframe for doc-links; Close + Back only (no Forward); mode-toggle button at top of `.section-toolbar` with `⇆` icon; respect-toggle on narrow viewports; never-interrupt-pane on notification arrival.

**Iteration log (visual feedback rounds)**:
1. Initial skeleton — Rick reported: iframe "localhost refused to connect" + empty pane occupying screen + container stretched + content jammed against scrollbar.
2. `document-viewer.html` rewrites absolute `http://localhost:port/` URLs to host-relative on render (universal fix — every doc-viewer user benefits); `.pane-open` class on `.content-shell` gates the 2-pane flex split; `scrollbar-gutter: stable` + 18-22px pane padding.
3. Draggable splitter (`notifications_pane_split_ratio` localStorage, clamps to `[0.30, 0.85]`, default 0.667); 80% max-width on container for breathing room.
4. Toolbar reposition attempt #1 — kept vertical column, anchored right.
5. Rick clarified "horizontal row, over the center of content area" — re-flipped to horizontal row.
6. Centering formula flipped from "over pane" to "over container" (`ratio/2 * 100%` not `(1+ratio)/2 * 100%`).
7. Toolbar pushed from `top: 136px` → `top: 56px` (just below `.lupin-nav` at 56px); `padding-top: 52px` on `.container` to clear the H1 from under the toolbar.

**Final geometry summary**:
- `body[data-layout-mode="horizontal"]` attribute gates all horizontal-mode CSS.
- `.content-shell.pane-open` activates flex-row split (left column flex:ratio, pane flex:1-ratio via inline JS).
- `.section-toolbar`: `position: fixed`, `flex-direction: row`, `width: max-content`, `top: 56px`, `left: var(--toolbar-center-x)`, `transform: translateX(-50%)`. JS pushes `(ratio/2)*100%` into the CSS variable on init/toggle/drag.
- `.content-pane`: sticky, `min-width: 360px`, body has `scrollbar-gutter: stable` + generous padding.
- `.content-pane-splitter`: 6px col-resize divider, hover/dragging visual state, body gets `.splitter-dragging` class during drag.

**Cross-cutting fix**: `document-viewer.html` now rewrites absolute-localhost anchors on render — universal benefit.

**Files**:
- `src/fastapi_app/static/html/notifications.html` (content-shell wrapper + content-pane skeleton + layout-mode-btn + splitter)
- `src/fastapi_app/static/css/notifications.css` (mode-gated horizontal layout rules + splitter + toolbar repositioning + pane padding)
- `src/fastapi_app/static/js/notifications.js` (constructor hydration + 9 new methods including `_initMasterDetailLayout`, `_toggleLayoutMode`, `_openContentPane`/`_closeContentPane`/`_backContentPane`, `_renderContentPaneEntry`, `_initPaneSplitter`, `_applyPaneSplitRatio`, `_updateToolbarPosition` + `.abstract-indicator` mode-branch)
- `src/fastapi_app/static/html/document-viewer.html` (absolute-localhost link rewriter)
- `src/rnd/v0.1.7/2026.05.21-master-detail-two-pane-layout-experiment.md` (NEW design doc with Resolved Design Choices + Reuse Review tables)
- `history.md` (this entry)
- `.claude-session.md` (Checkpoint 2 entry)

**Cache busters bumped**: `v=20260521a` → `g` across the 7 iteration cycles.

**Commit**: b599303

---

#### Checkpoint 1 | 2026.05.21 14:50 EDT | Part A filter strip + Part B chrono lock + Playwright e2e suite all green

**Two related broadcast/strip enhancements designed, implemented, tested**:

**Part A — Recent Activity Filter Strip** (`#commons-recent-activity-section`):
- Three inline native `<select>` dropdowns inside the existing `.commons-recent-activity-controls` flex row (no chip sub-row, dual-refresh consolidated to the single existing `↻` button per Rick's redundancy callout)
- Axes intersect with boolean AND: **Direction** (Sender · Recipient, mutex), **Kind** (All · Heartbeats · Personas · Broadcasts — 4-option per Rick's walkthrough amendment), **Persona** (chip per active session, sourced from `/api/cosa-voice/voice-persona/pool`)
- "Personas" predicate tightened to `topic.startsWith("dm-") && metadata.kind !== "heartbeat"`; "Broadcasts" unifies `broadcasts` + `broadcast-acks` topics; Direction=Recipient is a silent no-op when Kind=Broadcasts (broadcasts fan out)
- Filter dropdowns are **client-side instant** over the in-memory raw-entry cache — no server hit on change. The existing `↻` reload button is the only server-hit path (refreshes activity stream + persona dropdown options in one click, sticky-when-valid persona selection)
- **Filter state persists across page reload** via `notifications_commons_activity_filter` localStorage key (matches existing `notifications_*` convention)
- Filter-aware empty-state copy ("No activity matches the current filter" when any axis is active)

**Part B — Focus-bar Chronological Lock** (`#cc-session-strip`):
- `_addStripIcon` now stamps `data-created-at` from `persona.assigned_at` and ALWAYS appends (kills the `insertAtTop=true` prepend branch)
- `_promoteStripIcon` renamed to `_markStripIconActivity` — unread-badge pulse preserved untouched, `insertBefore` DOM reposition removed
- New `_sortStripIconsChronological()` helper runs once after `loadConversationHistory()` in the startup chain; subsequent runtime adds just append
- Backend plumbing verified intact end-to-end: `voice_persona_helpers.py` stamps `assigned_at` on allocation; `_voice_persona_for_sender_id` preserves it through to the senders-visible endpoint and the `voice_persona_assigned` WS event. **No backend changes needed.**

**Persistence layer** (also added beyond the chrono lock):
- Augmented the global `toggleSection()` helper with a write-through for two tracked accordions: `notifications_broadcast_card_open` + `notifications_recent_activity_open`
- `applyPersistedAccordions()` runs on `DOMContentLoaded` (before first paint) to avoid flicker on reload
- Existing focus-mode persistence (`notifications_cc_focus_state`) verified wired — Rick's "not implemented" report appears to be a misperception; the localStorage round-trip is in place with belt-and-suspenders restore via `_restoreCcUiAfterLoad()` after `loadConversationHistory()` completes

**E2E Playwright suite — three rounds to ALL GREEN**:
- Round 1: 4 pass / 9 fail — controller-global typo in test file (`window.__notifications_controller__` vs canonical `window.notificationsUI`)
- Round 2: 11 pass / 2 fail — typo fixed; remaining 2 were test-timing bugs (dropdown init-lag after page reload + `wait_for_selector` waiting for `visible` on a correctly-collapsed element)
- **Round 3: 13 pass / 0 fail / 2 graceful skips** (`TestStripChronologicalOrder` skips gracefully when fewer than 2 CC strip icons hydrate on the test server, which has no live CC sessions)

**Incidents logged + memory updates**:
- Accidentally bounced `:8000` while my first submitted test was mid-flight (chained `refresh-test-server.sh` as a polling-loop prelude). Job vanished, server self-recovered, re-submitted cleanly with new `scheduled_at`. Lesson: bounce commands NEVER belong inside a polling loop.
- Saved new feedback memory: `feedback_never_defer_test_fixes_hold_fire_exception.md` — Rick's directive that hold-fire windows do NOT pause completing in-flight test fixes I wrote. "You wrote the code. You make it pass 100% coverage. Full stop!"

**Cross-session coordination**: Three DM exchanges with Tiffany 💍 (lupin-mobile session 1b3f8c46) tracking the design deltas — initial inventory ask, post-walkthrough delta, post-amendment delta. Mobile parity work continues unblocked; the only cross-cutting wire item (`voice_persona.assigned_at` plumbing) is verified intact.

**Files**:
- `src/fastapi_app/static/html/notifications.html` (3 dropdowns inserted + `toggleSection()` augmented with localStorage write-through + `applyPersistedAccordions()` early-paint restore)
- `src/fastapi_app/static/css/notifications.css` (flex-wrap + `.commons-activity-filter-select` styling)
- `src/fastapi_app/static/js/notifications.js` (constructor hydration of 3 new `*_KEY` constants + `_commonsActivityFilter` + `_commonsRawEntries`; filter predicate / re-render / change handlers / persona-pool refresh / augmented reload button; strip chronological-lock surgery)
- `src/rnd/v0.1.7/2026.05.21-recent-activity-filter-and-focus-bar-chronological-lock.md` (NEW — design doc with item-by-item walkthrough decisions + reuse-review pass + implementation-complete status)
- `src/tests/e2e_ui/test_commons_activity_filters_and_strip_chrono.py` (NEW — 15-test Playwright suite across 5 classes)

**Commit**: 35581a8

---

### 2026.05.20 - Session 173c0b35 (Tiberius 🌑) | Persona resuscitation commit + Run-4 post-game convergence + Heartbeat-Poker design WIP

#### 2026.05.20 PM | End-of-day wrap

**Persona resuscitation work committed** at `c9db97c` — Rachel's three-thread fix bundled: (1) `start-cc-with-tmux.sh` forwards three `COSA_VOICE_PREFERRED_PERSONA__*` env vars into the tmux session via `-e` flags (the actual fix for why Tiberius was randomly allocated); (2) Roscoe → Tiffany persona rename swept across `lupin-app.ini` + splainer + 5 R&D docs + 1 test fixture; (3) four temporary `[LOOKML-DEBUG]` stderr prints in `register_session.py` phase 4.5 (flagged in-source for removal once Sam confirms allocation runs clean). 10 files, +103/-52.

**Run-4 cascade post-game with María 🌸**: 4-DM convergence cycle on `dm-tiberius` (`0cfea56f` → `67ccf3f8` → `830f4833` → `52df46e2` → `569eeba8` → `614b41ab` → `830f4833`). Positions reached:
- Q1 inverse density-vs-doctrine — HOLD on operationalizing pending Runs 5-6 controlled-slot experiment
- Q2 forward-asymmetry 38→33→21 monotonic — don't formalize; 4 competing explanations indistinguishable at n=1
- Q3 "Manager ad-hoc'd what should be codified" diagnostic — STRONG FOLD, codified as Step 9 rubric Q#6
- Fold-order revised respecting dependency graph: 7 candidates + 1 placeholder
- Dual-administer gate timing: keep default Runs 5-6, HARDen at Run 7 if +2/3 ratio holds
- New candidate added: Observer-side probe-as-mitigation channel (per-stage INI keys; M=8 Stage 0, M=4 default, M=2 Stage 2)
- 4 pre-committed re-evaluation gates locked at design-doc §10.18.12

**PIP-side codification pass shipped** by María at commit `adcd96d` (10 files, +744/-17; committed not pushed per Rick's EOD directive). Bilateral review completed Lupin-side: 8/8 ratification checkpoints verified; 2 non-blocking observations filed as v1.2 polish candidates.

**Lupin TODO.md updated**: closed `[LUPIN-PIP]` v1.1 codification line item with full 7-candidate map; added 2 new entries (`start-cascade-heartbeat.sh --observer` flag + `commons_send_to` recipient pool-key vs display-name routing priority bump).

**Generic Heartbeat Poker abstraction design — WIP**: Rick proposed abstracting the cascade heartbeat shell-script into a Lupin-side `AgenticJobBase` subclass with N recipients + schedulable for off-peak execution. Conversation walked through 3 use cases (Observer / Manager / Watcher-of-implementer), landed two-layer architecture (generic poker + per-recipient doctrine), resolved Q1 (Path A — one minimal class), Q2 (3-layered exits: clean signal + dead-man's-switch escalation + hard cap), and concurrent-poker routing (two independent jobs, recipient routes via `poke_body` JSON metadata). Parked at Q3 (relationship to existing daemon) and doctrine-home open Q.

**Files**:
- Working tree at close: `TODO.md` (modified) + `src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md` (NEW, ~260 LOC, WIP design doc)
- Committed: 10 files at `c9db97c`

**Standing playbook**: commit-only history.md tradition; Rick authorized EOD push at session-end.

---

### 2026.05.20 - Session 387b9201 (Tiberius 🌑) | Phase 7a Run 4 cascade-complete — implementer-handoff-ready

#### 2026.05.20 03:30 | Phase 7a Telemetry — Run 4 cascade closed 🟢 + Step 0 + Step 9 doctrine v1 validated

Managed Run 4 of cascaded plan-review workflow for Phase 7a Telemetry. **Cascade-complete 03:30:47 UTC; total wall-clock ~1h 30min** (Step 0 light-review through Step 9 close). Phase 7a implementer-handoff-ready.

**Cast**: Mr Radio 🦉 (Stage 0 Author), Rachel 🕊️ (Stage 1 Usability/Reuse), Krishna 🦚 (Stage 2 Risk/Anti-pattern + Step 9 light-review), Rio ⚡ (Stage 3 Ownership/Convention), María 🌸 (Observer + doctrine consultant), Tiberius 🌑 (Manager).

**Cascade outcomes**:
- Stage 1: 🟢 closed-clean (1F + 2P + 5 reuse confirms; cap-2 1/2 used)
- Stage 2: 🟡 closed-with-quibbles → cleanup folded (9 closed + 1 cosmetic + 4 doctrine-sweep quibbles; cap-2 1/2)
- Stage 3: 🟢 closed-clean (4 closed + 1 withdrawn; cap-2 1/2)
- Step 9: 🟢 close-clean post-revision (2 friction points + candidate #6 placeholder; cap-1 1/1)
- Net cap utilization: **8 of 14 possible revision turns = 57%**; 50%+ headroom preserved across every cap surface

**Manager footers (4 ratifications)**:
- R-3 Path A pin: drop `crash` from ReportingObserver registered types (PII safety; sanitizer-design deferred to v2 OSQ-T-6)
- Footer 2 Option A pin: block-on-config-fetch over non-blocking + replay
- Footer 2 sub-revision: Option A + 500ms `Promise.race` bounded timeout + safe-defaults fallback
- Closure-context references KEEP ruling (multi-surface sweep mandate is about active-claim violations, not historical scrubbing)

**Tier discipline outcome**: T1+T2 silent Manager-unilateral throughout; zero T3 escalations; zero T4 wake-ups; Rick stayed asleep as designed.

**Step 0 doctrine v1 validation**: ✅ STRONG. Pre-cascade recon (R-7a-1..R-7a-6 resolved upstream) eliminated browser-API archaeology from reviewer cycles. 3 reviewers concurred. Q→F→S→D recon shape empirically clean. 1 minor v2 candidate identified (persona-conventions sub-section).

**Step 9 doctrine v1 validation**: ✅ STRONG with empirical bonus. **Dual-administer cold-context test is ADDITIVE, not redundant** — Manager self-test surfaced 3 friction points; Krishna's external test surfaced 2 ADDITIONAL beyond mine. Net 5 cold-context observations. Empirical basis for promoting `light_review_required = true` to a hard requirement after Run 5+6 evidence.

**5 v1.1 doctrine candidates surfaced** (full codification in synthesis doc §5):
1. Heartbeat-daemon kickoff codification (Tiberius)
2. 4-tier clarification doctrine T1/T2/T3/T4 (Tiberius)
3. Heartbeat-tick-vs-peer-DM injection-density mitigation — **new failure-mode #6: signal-density-obscures-needle** (Tiberius + María phantom-detection catch)
4. Author-side grep-sweep checklist (Krishna)
5. Multi-surface footer-ratification close protocol with non-adjacent surfaces + synthesis-doc 7th-canonical-surface refinement (Rio + Mr Radio + Krishna refinement)
6. PLACEHOLDER — Explicit closure-context markers (filed for Run 5 evidence-gathering)

**Cascade-learning-loop forward-asymmetry empirical anchor**: Stage 1→2→3 wall-clock monotonically decreasing (38→33→21 min effective). Worth charting across Runs 1-4 for §10.18.

**Tiffany-rename-pass empirical refinement** (Mr Radio's catch): user-initiated rename operations CAN revert non-adjacent edit regions in one pass. Author-side grep-sweep checklist must enumerate ALL canonical surfaces independently — "the area I just touched" assumption is unsafe.

**Files**:
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/15-phase7a-telemetry-design.md` (cascade-ratified, ~470 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/16-phase7a-cascade-synthesis.md` (NEW, ~360 LOC, implementer-handoff doc)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/14-phase7a-telemetry-pre-cascade-recon.md` (Stage 0 background, untouched in cascade)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` (Step 0 inputs, untouched in cascade)

**Standing playbook**: commit-only no-push per [[never-auto-commit-push]]. All work uncommitted in working tree awaiting Rick's morning go-ahead.

**Manager-side phantom-lag observed**: 13-min lag at 02:33-02:46 UTC due to cascade-scheduler heartbeat ticks 11-14 obscuring Krishna's Stage 2 peer-DM. María's observer probe at 02:43:47 cleared. Mitigated for second half of run via proactive `commons_read` every N ticks. v1.1 doctrine candidate #3.

---

### 2026.05.20 - Session 32a6e563 (Mr. Radio 🦉) | Phase 7 slicing manifest + Phase 7a pre-cascade recon + Stage 0 design doc

#### Checkpoint 2 | 2026.05.20 02:10 | Phase 7a pre-cascade recon + Stage 0 design doc + manifest amendments — cascade Run 4 inputs ready

Continued Phase 7 planning track in parallel with Roscoe 🤠's Phase 6c implementation (Rick clarified parallel-track at ~01:40 UTC). Per Tiberius 🌑's direction across DMs `9d91b3a5` → `9e011230`:

**Option 1 — 7a Telemetry pre-cascade recon doc** (DM `9d91b3a5` greenlight): authored `14-phase7a-telemetry-pre-cascade-recon.md` (~280 LOC). Empirical anchor #2 for Step 0 doctrine (anchor #1 was the slicing manifest's §Pre-cascade recon framework, ratified 01:20 UTC). Per-item shape Question → Finding → Source → Decision per Tiberius's spec. Resolved 6 recon items:
- R-7a-1 OTel packages: `@opentelemetry/api` + `sdk-trace-web` + `exporter-trace-otlp-http` (skip `auto-instrumentations-web`; defer `sdk-metrics` to Q-T4 reviewer call)
- R-7a-2 Long Tasks: Chrome ✅, FF ✅ at floor, Safari ❌ — feature-detect at boot
- R-7a-3 Telemetry sink: env-driven INI key `multiplexer otel collector endpoint`; default empty (no-op); collector deployment OUT OF SCOPE
- R-7a-4 ReportingObserver: Chrome ✅, FF + Safari ❌ — feature-detect; Chrome-only signal at zero cost elsewhere
- R-7a-5 User Timing Level 3: unconditionally; meets Phase 1 floor (Chrome 114+ / FF 125+ / Safari 17+ per Phase 6c design doc line 88)
- R-7a-6 `observability/` directory stubs: Stage 0 design doc + code-execution phase owns creation; recon does NOT pre-stub

Tabulated 8 decisions for Stage 0 author + 8 open items deferred to cascade Stages 0-3. Tiberius's recon-doc verdict (DM `9e011230`): 🟢 GREENLIT. "High-quality. Question → Finding → Source → Decision shape is exactly what Step 0 doctrine should adopt as canonical recon-section template."

**Option 3 — Step 0 doctrine cross-ref to manifest footer** (DM `9d91b3a5` greenlight, concurrent): added §Doctrine cross-refs section to `13-phase7-slicing-manifest.md` footer linking PIP commit `bbb3e47` (Step 0 codification by Tiberius + María 🌸) + Step 9 (RATIFICATION-CLOSED 2026-05-19, validation-pending-Run-4). Phase 7a's first cascade = first live test of BOTH doctrines simultaneously.

**Option 2 — Stage 0 design doc** (initially HELD; ratified via Rick's cast spin-up): Tiberius reported (DM `9e011230`) that Rick spun up Rachel 🕊️ + Rio ⚡ + Krishna 🦚 explicitly to "assist Mr Radio in the plan creation and cascaded review process" — implicit ratification of author rotation. Authored `15-phase7a-telemetry-design.md` (~480 LOC) mirroring `10-phase6c-persona-focus-recorder-design.md` shape:
- Single cluster T (Telemetry) with **Q-T1..Q-T7** PROPOSED stances:
  - Q-T1: 6 canonical User Timing anchors
  - Q-T2: `createLongTasksObserver()` factory with null-on-Safari
  - Q-T3: ReportingObserver for `['deprecation', 'intervention', 'crash']`
  - Q-T4: 3 OTel span types (page-load, key-action, Long Task events); sdk-metrics deferred
  - Q-T5: perf budgets — boot<1500ms, first-queue-render<200ms, longtask<5/min (TBD-at-code-write per AC10b)
  - Q-T6: head-based sampling via `TraceIdRatioBasedSampler`; second INI key `multiplexer otel sampling rate`
  - Q-T7: telemetry init BEFORE renderer mount; `[multiplexer] telemetry:initialized` handshake
- **14 ACs** with Convention 3 EXECUTOR tags, Convention 4 TBD markers (AC-7a-8b + AC-7a-10b), Convention 5 N/A note (no `:8000` rows in 7a), Persona 2.A point 9 conditional-executability on AC-7a-8b + AC-7a-10b
- **Step T1-T7** sequential execution sequence per `feedback_pip_plan_review_is_sequential`
- **5 NEW + 9 EDITED** files enumerated
- **4 OSQs** with PROPOSED stances
- **13-point Persona 2.A rubric self-audit** + 17 feedback memories audited; no violations at draft time

Tiberius's Stage 0 first-scan verdict (DM `97c56ec9`): "Quality looks comprehensive at first scan (480 LOC, 7 Q-decisions, 14 ACs, full self-audit)." HOLD Stage 1 dispatch pending Step 0 doctrine §5.3 light-review by María 🌸 (6-criterion rubric). Rick's "Tiberius appears to be pleased" + explicit commit go-ahead resolved the conditional approval gate from his prior directive.

**Manifest amendment housekeeping**: §Per-slice file naming table renumbered from 3-doc-per-slice → 4-doc-per-slice (added recon docs). 7a: 14/15/16/17. 7b: 18/19/20/21. 7c: 22/23/24/25. 7d: 26/27/28/29. Review findings 94-97 unchanged.

**Coordination state**:
- Stage 1 dispatch to Rachel 🕊️ pending María's light-review verdict (~15-20 min wall-clock)
- If María 🟢 → Stage 1 fires; if ⚠️ gaps → I do 1 author-revision turn (CAPPED, no Round-2)
- Cap 2/2 author-revision-turn-cap + 3 discussion-turn-cap per cascade rules
- Step 9 synthesis-and-handoff doctrine will kick in after cap reached
- Phase 6c implementation track (Roscoe 🤠) continues independently; my last empirical state remains Node C through Step C2

**Parallel-session safety**: Roscoe 🤠's Phase 6c Node C work in flight (10 modified + 5 new files under `src/fastapi_app/static/js/multiplexer/`); my manifest section in `.claude-session.md` continues to list those as "NEVER staged from this context."

**Files** (this commit):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/14-phase7a-telemetry-pre-cascade-recon.md` (NEW)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/15-phase7a-telemetry-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` (MOD — file-naming table renumber + §Doctrine cross-refs footer)
- `TODO.md` (status updates on Phase 7a workstream)
- `history.md` (this Checkpoint 2 entry)
- `.claude-session.md` (Checkpoint 2 section + Touched Files update)

**Commit**: 54a1e19

---

#### Checkpoint 1 | 2026.05.20 01:35 | Phase 7 slicing manifest authored + ratified — sequencing Option A, pre-cascade recon ON, both op-phases decoupled

Coordinated with Tiberius 🌑 (session `387b9201`) on Phase 7 plan slicing for the multiplexer migration. Authored `13-phase7-slicing-manifest.md` (~280 lines) mirroring the Phase 6 slicing manifest shape + density. Phase 7 = Hardening (production readiness); roadmap §3 carves it into 4 sub-areas, all now sliced.

**Slice boundaries**:
- 7a Telemetry — User Timing + Long Tasks + ReportingObserver + OTel browser SDK
- 7b CSP — Content Security Policy report-only → enforce; new `/api/csp-report` endpoint scoped to `/app/multiplexer`
- 7c Trusted Types — `multiplexer/shared/trustedTypes.ts` policy + `require-trusted-types-for 'script'` CSP directive (HARD dep on 7b)
- 7d Accessibility — WCAG 2.1 AA + ARIA + keyboard nav + screen-reader pass + `prefers-reduced-motion` for Phase 6c animations

**Tiberius's review** (commons DM `93d42689`): 🟢 GREENLIT. "Draft is excellent." Sanity-check answers: slice boundaries match his mental model; no 5th sub-area missing; sizing right. Five strong-points called out; three minor observations (one folded into §Recommended order Per-slice point 2: 7a→7b sequencing means CSP report-only catches if OTel CDN needs allow-listing passively before enforce).

**Rick's ratifications** (cosa-voice blocking tools, sequential per Tiberius's recommended ordering):
1. Sequencing: **Option A** — 7a → 7b → 7c → 7d (recommended; telemetry-first per "observability before launch")
2. Pre-cascade recon: **ON** — 4-8h author-side homework before any design-doc cascade fires
3. 7b iterative-tightening: **DECOUPLED** as operational close-out phase (not second cascade)
4. 7d audit-driven cycle: **DECOUPLED** as operational close-out phase (not second cascade) — bundled with #3 in one `ask_multiple_choice` per Tiberius's suggestion

**Coordination state**:
- Phase 7 implementation gated on Phase 6c close (Roscoe 🤠's Node C in flight)
- First-slice author assignment TBD (Rick's call when 6c ships); Rachel 🕊️ likely continues as canonical author
- Mr. Radio returns to Persona 3 (Usability/Reuse Reviewer) for the cascade itself
- Step 0 doctrine cross-ref pending Tiberius + María 🌸's codification commit on PIP side

**Doctrine note from Tiberius**: my manifest's §Pre-cascade recon section is empirical validation that Step 0 cascade-prep is a real workflow phase — work today shaping doctrine for future cold-cast authors.

**Parallel-session safety**: Roscoe 🤠's Phase 6c Node C work is in flight in the working tree (10 modified + 5 new files under `src/fastapi_app/static/js/multiplexer/`); my manifest section in `.claude-session.md` explicitly lists those as "NEVER staged from this context" per `feedback_verify_staging_before_commit` and `feedback_lupin_only_never_cosa`. Only my one new file + the four tracking files commit.

**Files** (this session, this commit):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` (NEW — slicing manifest authored + ratified)
- `TODO.md` (NEW top entry — Phase 7 ratified + next-move handoff items)
- `history.md` (this entry)
- `.claude-session.md` (new session section appended + checkpoint tracking)

**Commit**: ee31ed0

---

### 2026.05.19 - Session b4623e3d (Roscoe 🤠) | Phase 6c implementation — Nodes D + B + A + C fully shipped

#### Checkpoint 2 | 2026.05.20 02:10 | Phase 6c COMPLETE — Node C closure + structural bug-fix; 11/11 visual regression GREEN

**Phase 6c implementation is done.** Node C fully shipped (recordingManager port + SenderCardRecorderRenderer + sender-card-recorder.css + boot wiring + 29 unit tests + smoke + Section C visual file + :8000 baseline + regression). All four nodes' visual regressions now pass.

**Final tier roll-up** (D + B + A + C):

| Tier | Result |
|---|---|
| Unit cases (Phase 6c new) | 122 PASS (D 37 + B 31 + A 25 + C 29) |
| Multiplexer unit sweep | all PASS (~670 tests) |
| c8 coverage | 99.98% lines / 99.68% branches / 100% functions; tail gaps c8-ignored with same-line "smoke-tier" rationale |
| Phase 6c smoke @ :7999 | 23/23 PASS in ~24s |
| Visual baselines @ :8000 | 4 captures, all clean (`auto_fix_on_failure: False`) |
| **Visual regression @ :8000** | **11/11 snapshots match** — D 3/3, B 3/3, A 3/3, C 2/2 |

**Bug found + fixed mid-regression**: `SenderCardRecorderRenderer.paintAllVoiceInputs` only ran once at mount when zero `.cc-voice-input` footers existed yet. Late-arriving sender cards (the only kind in practice — they come from `store_senders_changed` emissions) never got Record buttons painted. First regression run reported "1 of 2 C-snapshots failed" → investigation revealed `wait_for_selector` for `.record-button` was TIMING OUT, not pixel-diffing. Fix: added a `bus.on("store_senders_changed", () => paintAllVoiceInputs())` subscription + matching unsubscriber in unmount(). Local Playwright probe confirmed `.record-button` appears within 3s of notification injection after the fix.

**Re-baseline rationale**: every sender card snapshot's `.cc-voice-input` footer now shows the Record button (whereas pre-fix snapshots had empty footers). Re-baselined all 4 nodes against the fixed bundle. Second 8-job batch confirmed all 4 nodes regression-green.

**Note on commit timing**: parallel-session interaction with Mr. Radio 🦉's Phase 7 planning track on history.md caused the initial commit (`ea3412b`) to land WITHOUT this entry. This Checkpoint 2 paragraph + commit `[pending]` amend brings the history back in sync.

**Outstanding before merge**: per Rick tonight — this checkpoint commit, no backup, no push. Wind-down for the night.

**Commit**: 83c8863 (amended from ea3412b)

---

#### Checkpoint 1 | 2026.05.19 23:30 | Phase 6c Nodes D + B + A shipped end-to-end; Node C partial through Step C2

Implementer-pass on Tiberius's Phase 6c execution plan (`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/12-phase6c-execution-plan.md`, 749 LOC). Three of the four cascade nodes (D, B, A) are fully shipped end-to-end across the full test pyramid; Node C's chip-port runway (footer mount + AudioRecorder TS port) is landed and ready for Step C3 (recordingManager) to follow.

**Highlights**:
- **93 new Phase 6c unit cases** across 8 new test files (D 37 + B 31 + A 25). All multiplexer unit tests still pass.
- **c8 100% gate GREEN** on every multiplexer-wide pass: 8450 statements / 1787 branches / 642 functions / 8450 lines. Same-line `c8 ignore` comments cite specific defensive paths (polyfill fallbacks, FileReader error path, MediaRecorder error path under happy-dom) per the project's 100% mandate exception clause.
- **23/23 Phase 6c smoke tests pass on `:7999`** in ~24s end-to-end (5 D + AC-D9 canary + AC-D11 boot handshake + AC-D12 perf gate + 8 B + AC-B15 grep-gate + 6 A).
- **3 visual regression files** authored (Section D 3 snapshots, Section B 3 snapshots, Section A 3 snapshots).
- **3 `:8000` baseline submissions** queued via `POST /api/test-suite/submit` with `auto_fix_on_failure: False` per `feedback_baseline_capture_disable_tfe`: D `ts-0acbd8ef`, B `ts-db9d94ab`, A `ts-9fca0827`.
- **AC-B15 hard-verification grep-gate** holds across the whole session: D-CSS (`conversation-mode-pin.css`) has zero `@keyframes focus-flash` declarations; B-CSS (`focus-tray.css`) owns the SSOT keyframe. Smoke includes a runtime regression check.
- **Cross-renderer DOM-wipe bug found + fixed during Node B smoke** — NotificationsListRenderer's `replaceWith` re-render wiped `data-focus-hidden` on every store_senders_changed; FocusTrayRenderer now tracks `lastPinnedId` and re-stamps the attribute on every reconcile while focusModeActive=true (works because FocusTrayRenderer subscribes LAST in boot order, firing after the upstream wipe). Flagged to Tiberius as empirical anchor for the Step 9 "cross-renderer DOM-interaction matrix" doctrine candidate now being co-authored with María 🌸.

**Synthesis-doc gaps surfaced + resolved during pre-flight**:
- **Recon-D2 mic_monopoly wire-field**: server has no such field, no emitter. Escalated to Rick via Tiberius's `ask_multiple_choice`. Path δ defer ratified — mic-monopoly indicator becomes a Phase 6c follow-on (TODO entry filed by Tiberius in commit `3c870fb`). AC-D3 drops to 8 cases, AC-D10 drops to 5; AC-D4 unchanged.
- **Recon-D2-bis conversation_mode_changed type rename**: server emits `speakerphone_changed` with `payload.on`; smoke tests + plan reference `conversation_mode_changed` with `payload.active`. Path III bridge ratified by Tiberius unilaterally (wire-compat decision, not scope decision) — SenderStore.handleConversationModeUpdate listens for both type strings and reads `payload.active ?? payload.on`. AC-D3 covers both type strings × both field names (14 cases shipped).
- **Recon-A5 slugify**: new helper at `render/templates/slugify.ts` — single source of truth shared by `senderCard.ts` (Step A1) + `personaModal.ts` (Step A2). Regex `[^a-zA-Z0-9_-]/g → -` for HTML id-safe slugs.

**Outstanding before merge** (next-session todos):
- Node C Steps C3-C7 (recordingManager port + SenderCardRecorderRenderer + sender-card-recorder.css + boot wiring with AuthManager order + ≥24 unit tests + smoke + visual + `:8000` baseline)
- AC-D14, AC-B14, AC-A13 regression runs on `:8000` — pending Rick slot-coordination (NOT standing permission for non-baseline runs); will batch as one slot-ask when Rick returns

**Coordination notes**:
- Tiberius 🌑 (session `387b9201`) shipped 3 handoff docs + mic-monopoly TODO in commit `3c870fb`; my implementation work is the runtime side of that bundle.
- María 🌸 + Tiberius are co-authoring "Step 9 synthesis-and-handoff doctrine" as a meta-process improvement; the cross-renderer DOM-wipe bug-find from Section B smoke is their empirical anchor for a "cross-renderer DOM-interaction matrix" Step 9 check.

**Files**: 31 (10 new source TS, 3 new CSS, 9 new test files, 7 modified source/HTML, 2 modified tests, 1 stylelintrc, history.md).
**Commit**: c7df5d5

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | websocket-events.md doc fix — `speakerphone_changed` documented + `conversation_mode_changed` deprecation noted

Closed a documentation gap surfaced during Roscoe 🤠's Phase 6c Node D pre-flight investigation. Rick asked "who listens for `conversation_mode_changed`, where does it originate, is it in the INI website-events list?" — answered with the cascade-design-gap context: the event was renamed to `speakerphone_changed` during the Speakerphone solo/chorus refactor (Phase 3 of `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`, landed 2026-05-13), but `src/docs/websocket-events.md` was never updated.

**Three edits** (all targeted, no scope creep):
1. **Summary table** (L27): added `speakerphone_changed` row in the Notifications category, mirroring the `commons_activity` row shape (notification_queue_update wrapper).
2. **Per-event detail section** under Notifications (L252+): full entry covering rename history (2026-05-13 Speakerphone refactor Phase 3), payload shape (`{session_id, on, displaced?, displaced_by?}`), both client handlers (legacy `notifications.js::handleConversationModeChanged()` line 5552 + multiplexer `SenderStore.ts` STATE_UPDATE_TYPES Set), the Path III forward-compat bridge (accepts both wire names), INI subscription cross-ref (`lupin-app.ini:741`), server-side `valid_types` whitelist cross-ref (`notifications.py:359-364`).
3. **Deprecated Events section** (L466+): added a new "renamed during Speakerphone solo/chorus refactor" table mapping `conversation_mode_changed` → `speakerphone_changed` with the 2026-05-13 rename date. Notes that the deprecated name returns HTTP 400 if pushed.

**Empirical anchor**: Roscoe surfaced this gap during Node D pre-flight (DM `d2419eae`). The cascade design plan referenced the old name; the server only emits the new name. Path III bridge was ratified unilaterally by me (DM `eb826676`) — accept both names client-side as forward-compat. This doc edit captures that bridge contract for future readers.

**Files**:
- `src/docs/websocket-events.md` (MOD — 3 edits, ~30 LOC added net)
- `history.md` (this entry)

**Cross-refs**:
- Origin design: `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/16-phase7-multiplexer-ui-design.md` §"WebSocket `speakerphone_changed` handler"
- Phase 3 rename closure: `src/cosa/history/2026-04-25-to-05-13-history.md:89` (CoSA-side `valid_types` rename log)
- Forward-compat bridge ratification: today's DM `eb826676` to Roscoe + the Phase 6c synthesis doc `11-phase6c-cascade-synthesis.md` §3.D
- Documentation TOUCHPOINTS in CLAUDE.md: this doc is listed under `routers/websocket.py` + `lupin-app.ini websocket available events` row — both touchpoints honored this edit.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Phase 6c cascade synthesis + execution plan + design-doc amendments + mic-monopoly follow-on TODO

Three-artifact handoff bundle from Run 3 cascade — translating the 43 ratified findings across 4 sections (A/B/C/D) into an implementation contract Roscoe 🤠 can ship from cold. The synthesis doc (476 LOC) is the canonical why-anchor with per-section ratified AC tables, cross-section dependency map, and §10.14 doctrine candidates brief index. The execution plan (749 LOC) is DAG-first per Roscoe's framing preference with per-node deliverables, function signatures, step ordering, test pyramid, and done-defined. The amended parent design doc flips status to CASCADE-RATIFIED with per-cluster markers and inline cascade-closure narratives for Q-C2 (port-verbatim user escalation) and Q-D1 (manager-unilateral by-concurrence). Mic-monopoly indicator deferred via Path δ ratification (Rick) — filed as Phase 6c follow-on in TODO.md with the system-wide-semantic question to resolve before designing.

**Files**:
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/11-phase6c-cascade-synthesis.md` (NEW, 476 lines)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/12-phase6c-execution-plan.md` (NEW, 749 lines)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md` (MOD, cascade-amended status + per-cluster markers + Q-C2/Q-D1 cascade-closure notes)
- `TODO.md` (MOD, mic-monopoly follow-on entry filed under Path δ ratification)
- `history.md` (entry above)

**Commit**: `3c870fb` (2026-05-19, Rick ratified via María's `ask_yes_no` 22:21 UTC).

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Voice persona pool expansion — +2 personas, Sam→pool / Arnold→overflow swap, generalized overflow loader

Pool expansion driven by Rick's voice directive following the 6-persona-experiment validation in Run 3 cascade. Pool grew from 6 to 8 personas; the overflow slot rotated from Sam to Arnold via a config-only mechanism enabled by a small loader generalization. Color iterations + gender + profile corrections per Rick's voice walkthrough at ElevenLabs.

**Pool composition (final)** — `maria, mr radio, Rachel, Tiberius, Rio, Roscoe, Krishna, sam` (8 personas).

**Two new personas added**:
- **Roscoe** 🤠 — ElevenLabs voice `DXX4Q5Bh1vqK8CciYVPf`, color `#FFD600` (vibrant yellow — Arnold's old hue, now free since Arnold moved to overflow), profile "Upbeat professional female" (gender corrected from initial "male" placeholder per Rick's mid-edit update)
- **Krishna** 🦚 — ElevenLabs voice `ogSj7jM4rppgY9TgZMqW`, color `#1DE9B6` (Material Teal A400, vibrant aquamarine — documented green-rule exception per Rick's explicit override authority), profile "Reassuring warm male"

**Sam ↔ Arnold role swap**: Sam promoted from the reserved overflow slot into the regular pool; Arnold demoted from pool into the overflow slot. Mechanically required a small loader generalization in `voice_persona_helpers.py:load_overflow_persona_from_config` — previously hardcoded the literal "sam", now reads a new `cc session voice persona overflow name` INI key (default "sam" for backward compat) and looks up that persona's existing pool-style INI keys. Backward-compat branch: when overflow_name resolves to "sam" AND no explicit `cc session voice persona sam voice id` key is present, falls back to sourcing voice_id from `elevenlabs tts default voice id` (the pre-2026-05-19 legacy non-explicit path). All 5 existing `TestLoadOverflowPersonaFromConfig` tests still pass byte-clean via the backward-compat branch.

**Sam's transition**: added explicit `cc session voice persona sam voice id = G7ILShrCNLfmS0A37SXS` (same value as `elevenlabs tts default voice id` — now explicit so the regular pool loader can find him uniformly). Color changed from `#00BCD4` (cyan, formerly grandfathered under the `.persona-badge.overflow` styling exception) to `#5E35B1` (Material Deep Purple 600, green-rule compliant). Profile iterated through "System default voice (overflow)" → "Crisp neutral male" → "British male" (final, per Rick's verification of the actual ElevenLabs voice characteristics).

**Rachel lightened to lilac**: `#7B1FA2` (Material Purple 700) → `#CE93D8` (Material Purple 200, lilac) per Rick's directive once Sam's new deep purple made the prior Rachel-Sam pairing too visually close. Lilac preserves Rachel's purple-family identity while widening visual separation from Sam.

**Test verification**: `test_voice_persona_helpers.py` (52 tests) + `test_voice_persona_request.py` (49 tests) = **101 tests green in 2.5s**, zero regressions across all loader generalization + INI changes.

**Voice persona reference page** at `/static/html/test/voice-persona-reference.html` auto-populates from `GET /api/cosa-voice/voice-persona/pool` — no HTML edit needed; after `/api/init` reload, the page renders 8 tiles including Sam in his new deep purple.

**Files modified** (parent Lupin only — CoSA submodule untouched git-wise per `feedback_lupin_only_never_cosa`):
- `src/conf/lupin-app.ini` — pool list updated to 8 personas; Roscoe + Krishna full blocks added; Sam block rewritten (voice id explicit, color changed, profile updated, comment rewritten); new `cc session voice persona overflow name = arnold` key; comment block above Arnold's old position explaining the role change
- `src/conf/lupin-app-splainer.ini` — pool splainer rewritten for 8-persona reality; Roscoe + Krishna entries added; Sam splainer block rewritten (new voice id entry, color rationale updated, profile iteration history); new `overflow name` splainer entry with full backward-compat documentation; Rachel color splainer updated for lilac transition

**CoSA submodule changes on disk (not in parent diff)**:
- `src/cosa/rest/voice_persona_helpers.py` — `load_overflow_persona_from_config` generalized (~50 LoC); reads new INI key with `sam` default; backward-compat fallback to `elevenlabs tts default voice id` when overflow_name="sam" + no explicit voice id; updated Design-by-Contract docstring

**Cross-refs**: original Sam-overflow design at `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` (now superseded by the generalized loader); pool architecture at `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md`; voice persona expansion authorized by Rick's voice directive 2026-05-19 mid-afternoon EDT.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Per-repo preferred-persona env-var allocator — Lupin-side implementation + 7 unit tests

End-to-end implementation of Rachel's planning-is-prompting design doc `2026.05.19-cosa-voice-preferred-persona-env-var.md` on the Lupin side. Reads `COSA_VOICE_PREFERRED_PERSONA__<PROJECT_UPPER>` at SessionStart hook time, threads through to the cosa-voice `/allocate` router endpoint with graceful-fallback semantics, fires a `voice_persona_conflict` notification on miss. Narrative goal: each repo gets a stable canonical voice persona across days/sessions/`/clear`s — Rick's two target defaults are `__PLAN=María` and `__LUPIN=Tiberius`.

**Coordination shape**: cross-session pair-collab with Rachel 🕊️ (planning-is-prompting session `b310866d`) via commons DMs. Rachel owns the PIP-side design doc + workflow doc updates (`workflow/session-start.md` Preliminary -1 subsection, `workflow/INSTALLATION-GUIDE.md` one-liner). I own the Lupin/cosa-voice-side allocator + tests. María 🌸 joined the chorus post-Rachel-restart per Rick's narrative-restoration ritual.

**Rick's four §8 ratifications** (via blocking `ask_multiple_choice` + open-ended `converse`): (1) **notify delivery — option α inline** after bridge creation (vs β deferred to `get_session_info` poll); (2) **conflict notify suppression — fire every time** (vs dedupe per holding-session tuple); (3) **global fallback chain — out-of-MVP** per draft; (4) **`/clear` persistence — Path A preserve persona** across `/clear` (env var applies at FIRST allocation only; full session restart is the right ritual to change preference; narrative continuity wins).

**Architecture (minimum blast radius)**: new pure helper `pick_preferred_persona_from_env(project) -> Optional[str]` in `src/cosa/rest/voice_persona_helpers.py` with project-name normalization (lowercase→UPPER, hyphens→underscores, empty/None tolerated). New `preferred_persona_name` query param on `POST /api/cosa-voice/voice-persona/{sid}/allocate` with soft-preference semantics — tries the named persona via existing `allocate_requested_persona_for_session`; on `not_in_pool` or `occupied` allocates random via `allocate_persona_for_session` and pushes a `voice_persona_conflict` notification carrying the conflict kind + requested name + available pool + (for `occupied`) holding session id. Mutually exclusive with the strict slash-command `requested_persona_name` path (422 if both supplied). Outer fast-path preserved so `preferred_persona_name` does NOT override an existing allocation — that's the Path A `/clear`-preserves contract. Response payload extended with `preference_conflict: Optional[dict]` so callers can observe the fallback. Hook side (`src/lupin_cli/claude_code/hooks/register_session.py`) reads env var via the new helper and threads through `_allocate_voice_persona_via_http` as a new query-string param. Zero changes to `allocate_persona_for_session` or `pick_unallocated_persona` — the existing primitives compose cleanly via the orchestration in the router branch.

**Test pyramid**: 7 new unit tests appended to the pre-existing untracked `src/tests/unit/test_voice_persona_request.py` (which already held Arnold's 42 slash-command swap tests). 4 helper-only tests in `TestPickPreferredPersonaFromEnv` (env unset → None; project="cosa-voice" → reads `__COSA_VOICE` via hyphen-to-underscore normalization; project case-insensitive across `plan/PLAN/Plan` → reads `__PLAN`; empty/None/whitespace project → None silently). 3 router tests in `TestPreferredPersonaNameQueryParam` via FastAPI TestClient + dependency overrides covering happy-path (preferred persona available), occupied (held by another live session → fallback + conflict notify with kind=occupied + holding-session-id), invalid-name (`Frobozz` → fallback + conflict notify with kind=not_in_pool). All 49 tests green in 2.4s (Arnold's 42 pre-existing + my 7 new). Zero regressions on the 52-test `test_voice_persona_helpers.py` suite (existing helper coverage preserved). Full import chain verified — `register_session.py` imports `pick_preferred_persona_from_env` without circulars.

**Narrative-restoration arc**: Rick's broadcasts `9c604340` + `a0141fc9` defined the cross-session checkpoint pattern: previous-persona work stays UNCOMMITTED so the git log doesn't pre-model the canonical persona assignment; post-env-var-restart Tiberius (Lupin) and María (PIP) commit their respective trees under correct attribution. Today's narrative twist — Rick did NOT restart my Tiberius session (kept continuity), but DID restart Rachel's session and restored María. So I (continuous Tiberius) take ownership of all uncommitted Lupin work — Arnold's 42 pre-existing test cases + my new helper + router branch + hook integration + 7 new tests. María (restored persona) handles the PIP-side carry-forward independently.

**Surfaced a new bug during the morning's coordination**: cosa-voice persona resolver does not match display-name diacritics. `commons_send_to(recipient="María", …)` returned `recipient_resolution_error` with `resolution_chain_attempted: [exact, case_insensitive, punct_tolerant]`; lowercase `"maria"` (pool key form) succeeded. The candidate_alternatives payload correctly listed the maria session, so the resolver SAW the right session but did NOT match through the diacritic. Filing follow-up bug entry on bug-fix-queue post-checkpoint — proposed fix is a Unicode normalization pass (NFKD + diacritic strip) in the persona resolver, or a display-name-aware lookup augmentation.

**Files (parent Lupin only — CoSA submodule pieces are on disk but per `feedback_lupin_only_never_cosa` not managed from this context)**:
- `src/lupin_cli/claude_code/hooks/register_session.py` (MOD — import `pick_preferred_persona_from_env`; `_allocate_voice_persona_via_http` accepts + threads `preferred_persona_name`; hook callsite reads env var)
- `src/tests/unit/test_voice_persona_request.py` (was untracked Arnold-authored 42 tests; appended import + `TestPickPreferredPersonaFromEnv` 4 cases + `TestPreferredPersonaNameQueryParam` 3 cases — net 7 new tests, 49 total)
- `history.md` (this entry)

**CoSA-submodule changes on disk (not committed from this context)**:
- `src/cosa/rest/voice_persona_helpers.py` — new `os` import + `pick_preferred_persona_from_env` function + docstring
- `src/cosa/rest/routers/voice_persona.py` — `preferred_persona_name` query param + mutual-exclusion 422 + soft-preference branch in `else` path + `voice_persona_conflict` notification push + `preference_conflict` in response payload

**Cross-refs**: design doc `planning-is-prompting/src/rnd/2026.05.19-cosa-voice-preferred-persona-env-var.md` (Rachel's authorship, the canonical specification including §4-§8 implementation/test/decision-points); commons DM topic `dm-tiberius` + `dm-maria` for the morning's coordination thread.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Phase 6C cascade Run 3 manager (HYBRID authoring-cascade on multiplexer implementation plan)

End-to-end manager of the inaugural HYBRID `/plan-authoring-cascaded` run, applied to Rachel's pre-existing Phase 6C design doc (`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md`). 4 sections (A: Voice-Persona Modal, C: Sender-Card Audio Recorder, D: Conversation-Mode UI Pin, B: Focus Tray + Toggle). Same 5-persona cast as Run 2 with Rachel 🕊️ swapped to Author (from Usability), Mr Radio 🦉 swapped to Usability/Reuse (from Author), Arnold 🪨 + Rio ⚡ in canonical Viability + Ownership roles, María 🌸 doctrine consultant, me Manager. Heartbeat daemon (PID 570626) ran 48 ticks on 180s cadence; second daemon (PID 615764) launched mid-run for María on Rick's authorization.

**Run 3 cascade results**: all 4 sections fully closed at cap 2/2; 43 findings total (10 Persona-3 + 22 Persona-4 + 4 Persona-5 across 11 reviewer-instances); 39/43 verbatim-accept (91%) + 4 documented-not-revised (cap-preserved cosmetic); 0 votes; 1 user escalation (Section C F2 foundational `audio/webm;codecs=opus` MIME incompatibility, ratified-yes by Rick via `ask_yes_no` 02:48 UTC after his voice-pushback redirect to port the working `AudioRecorder` + `recordingManager` singleton verbatim); 1 Manager-unilateral ratification (Section D Q-D1 Path A by-concurrence — new closure category); 1 counter-proposal (Rachel base64 option-a over my option-b on Section C OSQ-C-3, accepted); 1 reviewer reassignment (Mr Radio → Arnold for Section B Stage 1 due to Anthropic-side rate-limit blocking 78+ min); 1 hard-verification-gate introduced (Section B AC-B15 grep-gate enforcing B-CSS-as-SSOT on `@keyframes focus-flash` — superseded Round-1 post-cascade-fold disposition). Wall-clock 108 min from launch 02:28 UTC to cascade-complete 04:16 UTC. End-of-pipeline §8 summary posted to `pipeline-summary-20260519` commons topic.

**Per-section wall-clock + findings**: A 44 min / 11 (10/11 verbatim); C 57 min / 14 (13/14 verbatim, 1 user escalation); D 62 min / 9 (8/9 verbatim); B 72 min / 9 (8/9 verbatim, 1 reviewer reassignment + 1 hard-verification-gate). All sections hit cap 2/2 — full revision-discipline coverage.

**Cascade-learning-loop validated empirically (finding compression dimension)**: Section finding-counts across Run-order A→C→D→B = 6, 8, 4, 4 at Stage 2. F-Arnold-C3 reproduced F-Arnold-1 in Section C (asymmetric forward-loop: C's Round-1 pre-dated A's lesson). Sections D + B benefited from Rachel's autonomous doctrine carry-forwards (4 proactive applications in Section B Stage 0: directory-wide c8 glob, var-color form, stale-citation caveat, AC2e safe-write). Section B shipped Stage 0 with **zero conditional-executability markers** — only section in Run 3 to achieve this. Rio explicitly cited as "strongest cascade-learning-loop validation to date."

**Mr Radio rate-limit incident** (5th distinct failure mode catalogued for §10.14 — distinct from dormancy / read-side truncation / turn-based limitation / write-side truncation): hit Anthropic `API Error: Server is temporarily limiting requests (not your usage limit)` at ~03:06 UTC, immediately post Section B Stage 1 dispatch. María's diagnostic via Rick's voice channel at 03:17 UTC ("park-and-wait, 5-min cadence, 15-min threshold") prevented misdiagnosis as phantom dormancy. Threshold escalation at 03:32 UTC via `ask_multiple_choice` → timed-out `expired_no_default` (Path B skip-restart: Item #1 fix not loaded in pre-existing MCP subprocesses) → re-fired as `ask_yes_no` per Run-2 workaround → Rick ratified reassignment to Arnold (14-min user-attention block, longest single Run-3 event). Arnold's Persona 3 reassignment caught 4 substantive findings on Section B Stage 1; his canonical Persona 4 at Stage 2 then caught 3 of his own Stage-1 closures' fitness gaps. Rio's fresh-eyes Stage 3 concurred + caught one final cosmetic. **Cascade closed cleanly WITHOUT Mr Radio recovery** — structural answer to rate-limit failure mode is reassignment, not partial-close.

**12 doctrine candidates filed for María's manager-seat §10.14 post-Run-3 redline**: (1) AC-table-doctrine-lag pattern — 3 confirmed instances (F-Arnold-C3 + F-Arnold-D4 + F-Arnold-B-Stage2-3) → formal Persona 2.A point-14 codification; (2) hard-verification-gate vs post-cascade-fold pattern — NEW closure category; (3) visible-text safety on CSS var fallbacks — `currentColor` over `transparent`; (4) symmetric-application discipline (writer + consumer); (5) reviewer-reassignment-due-to-rate-limit closure category; (6) Manager `blocked_waiting_on_user` coordination signal (María's catch — observers can disambiguate scenarios 1 vs 2 from disk-read alone); (7) Q-D1 `manager_unilateral_ratify_by_concurrence` formal closure category; (8) cascade-learning-loop sub-patterns (forward-only-asymmetry + symmetric-application + context-aware-application); (9) rate-limit failure mode catalog entry; (10) Stage-3 cosmetic-cluster as systematic pattern-family (F-Rio-1 + F-Rio-C1 + F-Rio-D1 + F-Rio-B1 = 4 distinct variants); (11) ask_multiple_choice Path-B skip-restart cost validated empirically; (12) 18-min user-attention-block tightening directive.

**Post-cascade fold bundle (final shape, shrunk per AC-B15 hard-gate adoption)**: (1) Q-C2 design-doc `10-phase6c.md` §Cluster C amendment recording Rick's port-verbatim ratification; (2-5) 4 F-Rio-* cosmetic folds (Section A AC-A3/A4 cross-reference; Section C AC-C3 orphan strike; Section D Step D2 pin-move wording; Section B AC-B15 grep-gate wording precision). B-keyframes-removal from D-CSS NO LONGER in bundle — now hard-gated in-cascade via AC-B15 (mechanical grep verification at code-write).

**Rick's midstream interventions**: (a) F2 voice-pushback redirect ("propose a variation of something that already works") that collapsed Section C's Q-C2 from MIME-negotiation-design to port-verbatim-of-AudioRecorder — saved the cascade from shipping a broken endpoint assumption; (b) base64 enhancement consideration raised post-F2 ratification ("not a suggestion, just worth considering") that surfaced OSQ-C-3 deferral as a stand-alone perf R&D candidate; (c) María daemon launch authorization mid-run (addressing turn-based-CC limitation as applying to ALL cascade CC roles); (d) reviewer reassignment ratification at threshold (option B over A1/C); (e) Sam (CoSA) added to closeout chain at 04:17 UTC, resolving Lupin/CoSA git separation for tonight's commit batch.

**Operational notes**: (a) `/plan-authoring-cascaded` workflow was authored by María during this same evening session, parallel with the Run-3 cascade itself — María's PIP-side authoring landed concurrent with cascade kickoff; (b) cascade-as-author HYBRID mode (design doc exists, implementation plan authored within cascade) was the inaugural use of this pattern; (c) all participating sessions retained Run-2 contexts (Path B: skip MCP subprocess restart) — `ask_multiple_choice` default-param fix from V2 Item #1 was therefore NOT loaded, validated empirically by `expired_no_default` timeout on the threshold escalation; (d) Predicted user-attention budget per María's §10.14 estimate was ~7-9 escalations; actual was 1 (F2 user-ratification) + 1 (rate-limit reassignment) + several status walkthroughs — well below ceiling.

**Files (parent Lupin only — CoSA via Sam, PIP via María per coordination chain)**:
- `history.md` (this entry)

(Cascade itself produced no Lupin code changes — all 4 section commons-topic files + dm-* + pipeline-summary live under `io/commons/` which is gitignored. The cascade's output is the ratified implementation plan, which Rachel will materialize into design-doc amendments + code-write in a subsequent session.)

**Closeout coordination chain** (per Rick's 04:09 UTC directive via María): (1) cascade-complete signal fired ✅; (2) Lupin commit-only no push (this commit); (3) Tiberius pings Sam → Sam runs CoSA end-of-session ritual; (4) Sam commits CoSA (independent of Tiberius — addresses my `cosa-edit-vs-manage-git` feedback restriction); (5) María commits PIP independently with matching stretched-day boundary `2026-05-18T00:00 → 2026-05-19T05:00` on LoC Delta.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Recent-activity panel UX polish (toggle move + fixed-width header columns)

Quick CSS+JS tweaks to the broadcast-panel Recent Activity section while waiting on María's `/plan-authoring-cascaded` doc-spec authoring. Two user-driven refinements, both verified visually by Rick at :7999 dev:

**Show-more toggle moved into the row header** — previously the `commons-activity-entry-body-toggle` button rendered inline below the body content, which was idiosyncratic vs other UI toggles in the app shell. Rick wanted it inline with the row header near the time. Approach: extended the entry grid from 5 to 6 columns (`icon name chip body toggle time`), moved `body.appendChild( toggle )` to `row.appendChild( toggle )` after `row.appendChild( body )`, and updated the toggle's CSS from `display: inline-block + margin-top: 2px` to `grid-area: toggle + align-self: start + white-space: nowrap`. Persona color preserved via the existing `--persona-color` CSS variable. Hidden-on-no-overflow + click-toggles-expanded behavior unchanged; existing E2E tests at `src/tests/e2e_ui/test_commons_activity_toggle.py` survive because their class-based selectors still find the toggle regardless of parent.

**Name + chip columns fixed-width** — previously `auto`-sized so each row's body started at a different x-position depending on persona-name + chip-content lengths. Rick wanted a consistent left-edge for the body. Two iterations to land the visual: first pass at 100px/110px (too much whitespace per Rick); final at 70px/75px (~31% reduction, "looks great" per Rick). Chip right-aligned within its column via `justify-self: end`. Both name + chip get `overflow: hidden + text-overflow: ellipsis` for graceful truncation on edge cases (e.g. `cascade-scheduler` 17-char name or `cascaded-prototype-input-plan` 29-char topic name). Added `title` attribute on both elements in `_renderCommonsEntry` for full-text on hover when truncated.

**Files**:
- `src/fastapi_app/static/js/notifications.js` (MOD) — `_renderCommonsEntry`: appended toggle to row instead of body; added `name.title` + `chip.title` for hover full-text
- `src/fastapi_app/static/css/notifications.css` (MOD) — `.commons-activity-entry` grid expansion (5→6 columns) + name/chip width fix + chip right-alignment + ellipsis on overflow on both
- `history.md` (this entry)

**Test impact**: zero — E2E tests query toggle/name/chip by class; structure-agnostic queries survive the parent-element change.

---

