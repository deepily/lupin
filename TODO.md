# TODO

## 🌙 2026-06-07 NIGHT WRAP (Tiberius 👑, session 1f9f3c4c) — arbiter B1 DONE, NOT in production

> Session-end state: arbiter-vigilance B1 (L1–L4 + R0) + test-debt sweep + broadcast source fix all reviewer-passed, committed + PUSHED (2 selective commits), backup to DATA02. **NOT in production** — :8000 verify not run, R0 cutover not done, :8001 staged-not-enabled. Resume memento: `io/mementos/tiberius-session-resume-2026.06.07-night.md`.

**▶ NEXT SESSION — FIRST ACTIONS (descending priority):**
1. **🔝 [LUPIN] Batched :8000 e2e verify — NOW UNBLOCKED.** Rick added the `docker restart lupin-rest-test` allow-rule (`.claude/settings.local.json`) clearing the harness gate that denied a peer-authorized bounce. **Krishna 🦚 is staged + holding** (idle-confirmed, preflight green, payload ready: `test_types="e2e"`, `pytest_args="--update-snapshots"`, `--bg`). Fire him: bounce → submit → triage the 6 visual rebaselines (doc_viewer_directory_listing_docs/_io, test_visual_claude_plans_listing, dm_badge_visual_baseline, test_multiplexer_phase5_visual, visual_regression notifications) against his sweep knowledge → directed-DM verdict. Authoritative green for the whole sweep + broadcast fix + L4.
2. **[LUPIN] R0 break-before-make cutover** (Rick's call) — flip `arbiter in-process bootstrap enabled`=false → bounce :7999/:8000 (verify DISABLED log) → `systemctl --user enable --now arbiter-vigilance` + `loginctl enable-linger` → confirm :8001/health. Tiffany 💍 offered to clean-env-verify preconditions first. Supersedes the older "Deploy v2.2 arbiter on :8000" item below.
3. **[LUPIN] history.md archival** — at ~19.8k tokens (≥19k archival line); archive older entries next session before it nears the 25k limit.

**Left UNTRACKED on purpose (NOT committed tonight — separate/unreviewed):** the 4 `clayton-*.patch` files in the heartbeat-hook R&D dir, `src/rnd/v0.1.8/2026.06.07-fleet-context-pressure-assessment.md` + `2026.06.07-managing-context-memory/` (Clayton's context-pressure proposal, awaiting Rick's go — tracked in the PROPOSAL section below).

---

## 💡 2026-06-07 (Clayton 😎) — Fleet Context-Pressure Assessment Utility (PROPOSAL, Rick interested)

- [ ] **[LUPIN]** **Fleet context-pressure assessment utility** — proposal serialized + parked at Rick's request (he found it "really interesting"). On-the-fly health-check utility to surface workers running low on context + recommend reset (compact) or harvest+respawn-with-memento. **Key insight (verified):** the SDK's `get_context_usage()` is client-only and does NOT reach our tmux-CLI workers; instead read each worker's transcript JSONL (`transcript_path` in its bridge) — last assistant message's `input + cache_read + cache_creation` = true occupancy (probed María's live session: ~46% of 1M). Sensor+recommender, never auto-act (P1/P2). **Proposal doc:** `src/rnd/v0.1.8/2026.06.07-fleet-context-pressure-assessment.md`. **Source R&D:** `src/rnd/v0.1.8/2026.06.07-managing-context-memory/`. **Status: PROPOSAL — awaiting Rick's go-ahead** (3 open Qs: ship P1-only first? WARN 70 / CRIT 85%? sensor-only? — Clayton recs yes/yes/yes). Ephemeral plan: `~/.claude/plans/rustling-knitting-mccarthy.md`.

## 🔥 2026-06-06 PM (Tiberius 👑, session 060c8d6b) — heartbeat hardening follow-ups

- [ ] **[LUPIN]** **Broadcast-miss root-cause (NOT yet solved — listener layer)** — a USER BROADCAST didn't reach Tiberius while DMs still landed (2026-06-06). Initial "stale bridge > 600s / Thread A `idle_announce` removed the heartbeat" hypothesis was **REFUTED** — the live fanout threshold is `commons broadcast liveness threshold seconds = 28800` (8h), and idle was only ~77 min, so the bridge-mtime filter did NOT drop the session; `owner_user_id` also passes (un-stamped → graceful). **Real direction:** broadcasts arrive via the `cc_notification_listener` (separate from the harness direct-prompt path) → fault is in the listener/injection layer. **Anomaly found:** DUPLICATE listeners for one session (a 09:34 one + a 16:22 one, both alive, same log) on a ~14h-old `claude` process. Needs a dedicated root-cause: the broadcast dispatch path + why a 2nd listener spawns without reaping the 1st. Memory: `reference_broadcast_miss_is_listener_layer`.
- [ ] **[LUPIN]** **Interim heartbeat poker** (Rick greenlit 2026-06-06) — lightweight recurring watcher that (a) stamps idle managers' bridges to keep them broadcast-reachable + (b) detects whole-fleet-stall → escalates to Rick + DMs the manager. Mechanism lane = Tiberius; charter-doctrine lane = María (standing-pair-must-not-both-go-dark). Retire once the v2.2 arbiter is deployed live on :8000. Was about to fetch CronCreate vs standalone-script mechanism when redirected.
- [ ] **[LUPIN]** **Deploy v2.2 arbiter** (`0d7adad`, committed held) — stand up `submit_arbiter_if_absent` as a standing job on :8000 post-push + run the live :8000 standing-arbiter integration test (the scheduled post-commit handoff). + the :8000 auth-matrix run (Mr. Radio's lane, needs Rick in-band).

---

## 🔴 2026-06-06 E2E TEST-DEBT — Rachel's run unearthed 31 reds (Clayton 😎 picking up, session 19581015)

> **Source run**: Rachel 🕊️ ran the full Playwright `e2e` suite on :8000 late afternoon 2026-06-06 (job `ts-838268c5`, ~32 min). Result **484 passed / 31 failed / 1 error / 3 skipped**. Triage verdict: NONE attributable to her scroll-preservation work (touched only `notifications.js`; the two tests covering that surface passed) → classified as **pre-existing fleet test-debt / branch drift**, handed to Tiberius's crew. Full results: `io/test-suite/2026.06.06-at-16:52-EDT-e2e-results.md`; triage table: `src/rnd/v0.1.8/2026.06.06-reading-pane-scroll-position-preservation.md` §"E2E validation run + triage". **Clayton owning triage + fixes; coordinating with Tiberius 👑 + María 🌸.**

> **RESOLUTION (Clayton 😎, 2026-06-07): ALL 7 clusters fixed + Krishna L3-PASS. 6 test-side, 1 SOURCE (the broadcast bug). Zero source touched in clusters 1-5,7; cluster-6/7 = visual rebaselines. Everything HELD for the single batched :8000 `--update-snapshots` verify + Rick's commit/push.**

- [x] **[LUPIN]** `test_commons_activity_toggle` (9) — STALE TEST: helper resolved controller via dead globals `window.__notifications_controller__`/`notificationsController` (git -S: never existed) → `window.notificationsUI`. Cleared vs `0d7adad`. Krishna L3-PASS.
- [x] **[LUPIN]** `test_cc_session_strip_and_focus` (7) — ALL test-side: A conv-mode 481/522 `'true'`→`'speakerphone'` +540 `None`→`'quiet'`; B `lands_leftmost`→`_rightmost` (chronological-lock); C `+ensureDateAccordionExists` fixture; D focus-reload reclassified real-bug→fixture artifact (deliberate no-card revert @notifications.js:9933), neg-control + re-inject. Krishna L3-PASS.
- [x] **[LUPIN]** `test_doc_viewer_directory` + `test_doc_viewer_multi_repo` (10) — STALE retired `?scope=` URLs → unified `?path=lupin/<rel>` / `?path=io` / `?path=claude-plans/` (trailing slash; claude-plans IS browsable — overturned an initial not-browsable ruling). Krishna L3-PASS.
- [x] **[LUPIN]** `test_commons_recent_activity` (`.trim()` whitespace) / `test_filter_toggle` (flaky fixed-wait → `wait_for_function` poll) / `test_dm_recent_activity` (visual rebaseline). Krishna L3-PASS.
- [x] **[LUPIN]** `test_layout_mode_toolbar_centering:172` (1) — BRITTLE TEST: iframe fills body **content** width (`clientWidth` 396 ≈ frame 395.6); test compared border-box width (410.6, incl 14.6px scrollbar). Fix = compare vs `clientWidth`. Test-only. (Krishna L3 pending.)
- [x] **[LUPIN]** `test_multiplexer_phase5_visual` (1) + `test_visual_regression[notifications]` (1, the "error" = `notifications.png` snapshot mismatch surfaced at teardown) — legitimate post-unification/post-UI-change VISUAL REBASELINES → `--update-snapshots` in the batched :8000 run. No code fix.
- [x] **[LUPIN]** **BROADCAST SUPPRESSION SOURCE BUG** (Rick-greenlit TOP priority) — `broadcast_handler._parse_body` misread prose-`@`-line-with-later-colon as a directive → Rick's AFK broadcast silently skipped fleet-wide. New `_directive_mentions()` (pure @-mention run + colon, match ANY, else default = fail toward delivery). 100% line+branch, Krishna L3-PASS with fails-before/passes-after. SWEEP: single-site.

**FOLLOW-UPS (filed, non-blocking):**
- [ ] **[LUPIN]** Broadcast matcher **roster-aware hardening** (Krishna nit, Tiberius-approved follow-up): the directive discriminator is heuristic — a short prose line like `@here goes: x` parses as a directive to a nonexistent persona → skips if it's the sole line. Bias is correctly toward-delivery for realistic prose (commas/length catch it). Future fix: give `_parse_body` the persona roster so a token is only a mention if it resembles a registered persona. Today `_parse_body` only sees `local_persona_name`.
- [ ] **[LUPIN]** Bare-external-scope-root **no-slash 400** (Tiberius-queued robustness): `?path=claude-plans` (no trailing slash) → HTTP 400 while `?path=claude-plans/` lists and `?path=io` (built-in) lists at bare name. External-scope bare root should list or 301→slash. Separate from the test migration.
- [ ] **[LUPIN]** Pane-body **14.6px vertical scrollbar** in the reading pane (cluster-5 observation) — possibly intended, possibly a tiny iframe overflow; confirm whether `.content-pane-body` should scroll at all.
- [ ] **[LUPIN]** **Clean full-suite baseline**: no clean green full-suite baseline existed (06-05 reports were filtered 10–20-test runs) → this sweep is attribution-by-blast-radius. Establish a clean baseline so future attribution is before/after.

---

## ⏸️▶ 2026-06-04 RESUME-HERE (Tiberius 👑, session 1333e106) — picked up after Rick's end-of-session shutdown

> Written 2026-06-03 PM at Rick's "note where you are so we can pick up tomorrow" broadcast. Full rehydration memento: `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/27-tiberius-rehydration-memento-2026.06.03-pm.md`. Session-end state: my docs committed + branch PUSHED + backup done (Tiberius exempted from the no-push/no-backup rule); signalled María to run the global roll-ups after me.

**▶ START HERE TOMORROW (descending priority):**
1. **🔝 Rick's NEW WORKFLOW IDEA** — still un-described. ASK Rick to describe it, then capture + divide hub-spoke with María 🌸. (The reason I was standing by when shutdown was called.)
2. ~~Rachel's B3 — `notifications.py:1291` re-raise~~ → **DONE by Rachel** (`bbde599`); tree back to **100%**. Harvest now unblocked. (See Rachel's block immediately below.)
3. **Harvest (parked, proven SAFE — now UNBLOCKED)** — delete the 4 redundant legacy agent test files (weather / math / date_and_time / token_counter; `test_agents_root_tail.py` is the real coverage-bearer). Tree is green → commit after a Krishna APPROVE.
4. **E2E `:8000` (`ts-e1d42153`, scope `e2e`, auto_fix=False)** — CHECK result on resume.
5. **Optional T6 test** (Krishna non-blocking nit) — concurrent `register_question` double-insert guard (`commons_question_watcher.py:202`). Belt+suspenders.
6. **Standing gate**: Krishna 🦚 reviews ALL code before commit — no self-exemption. Never prompt Rick about pushing.

---

## 🕊️ 2026-06-03 RACHEL (session 7bca7a96) — RESUME HERE TOMORROW

**Shipped, reviewer-cleared, COMMITTED locally (`bbde599` on wip-v0.1.8, NOT pushed — held for María's push wave + Rick's word):**
- Missed-badge **Reset button** + logout dead-onclick-global fix (earlier commit `c0db33d`).
- **Confidence-overflow "22123%" fix** — clamp `similarity_pct` to [0,100] at the dot-metric boundary.
- **Send-bar code-fence rendering** — `renderMarkdownInline` delegates ```-fenced text to the block renderer.
- **Prediction-hint thumbs 👍🏼/👎🏼 → training signal** (Rick's feature): ratification-aware CBR weighting (approve boosts; downvote = negative vote / steer-away) + `POST /api/notify/prediction-vote/{id}` + `record_hint_vote` + UI controls + 4 INI keys.
- **Fixed `notifications.py:1291`** (dismiss endpoint dead `except HTTPException: raise`, Tiberius's catch) → tree back to 100%. *(→ Tiberius's "[ ] Cover notifications.py:1291" item below is DONE.)*
- Krishna 🦚 APPROVED (B1/B2/N1/B3 closed); vote-flow E2E green (`ts-852bb878`, 2/2); `prediction_engine.py` 100% line+branch.

**PICK UP TOMORROW:**
- [ ] **[LUPIN]** PUSH `bbde599` (held for María's push wave + Rick's word — do NOT push solo).
- [ ] **[LUPIN]** Thumbs-vote **Stage 3**: extend ratification weighting to multi-select + open-ended paths (Stage 1 covered yes_no + MC single-select only); add a :8000 integration test (DB-backed 👍 → approved case steers a later prediction; 👎 → steer-away).
- [ ] **[LUPIN]** Tidy (Krishna non-blocking nit): `MIN_PCT=50` hardcoded in `notifications.js` mirrors the INI `prediction hint vote min confidence threshold` — fold the threshold into the hint payload / expose to client so they can't drift.
- [ ] **[LUPIN]** Still mine (PG-D4): Global hermetic-config autouse fixture (FM-21) — design + isolation-verify; land only on a clean full-suite gate.

Design docs: `src/rnd/v0.1.8/2026.06.03-prediction-hint-thumbs-vote-training-signal.md`, `src/rnd/v0.1.8/2026.06.03-notification-markdown-and-confidence-overflow-fixes.md`.

---

## ✅🏁 2026-06-03 CoSA COVERAGE MARATHON — COMPLETE (Tiberius 👑, session 1333e106)

**DONE:** `cosa` 100% line+branch+function tree-wide (412 files, 0 miss / 0 partial); 11 test-only commits HELD on `wip-v0.1.8` (`d75bb69`→`e70e02e`), Krishna 8/8 reviewer-clean, certified + steward-ratified. Full record: `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/23-overnight-grind-certified-complete.md`.

**🔁 RICK'S MORNING GATE — session 1333e106 progress (2026-06-03):**
- [x] **[LUPIN]** PUSH the marathon CoSA commits — DONE (on origin; branch 0 ahead / 0 behind, git-verified).
- [x] **[LUPIN]** PROD BUG (a): `dispatcher.py` uninitialized `self.debug` — FIXED + de-armed (commit `71d0645`); 2 tests cover both debug arms.
- [x] **[LUPIN]** PROD BUG (b) #12: `cosa_interface.ask_yes_no` → missing `_dispatcher.ask_yes_no` — FIXED (delegates to real `ask_confirmation`) + strict-xfail de-armed (commit `71d0645`).
- [x] **[LUPIN]** Stale CLAUDE.md §PROJECT STRUCTURE — FIXED (11 real `cosa` source dirs; deleted `app` removed; commit `7526700`); María mirroring the block into PIP.
- [ ] **[LUPIN]** Global hermetic-config autouse fixture (FM-21) — **Rachel's lane** per PG-D4 (design + isolation-verify; land only on a clean full-suite gate).
- [ ] **[LUPIN]** io_files watch-note (doc 90) — candidate FM-22; promote only on recurrence WITH captured `--tb=long`. (Monitor.)
- [~] **[LUPIN]** `:8000` integration/E2E tier — **E2E SCHEDULED** this session (job `ts-e1d42153`, scope `e2e`, `auto_fix=False`); result pending.
- [ ] **[LUPIN]** HYGIENE: `.claude-session.md` (412KB) + `TODO.md` (273KB) bloat — dedicated size-management (deferred per PG-D4 ruling).

**🔧 RELOCATE PASS — MISDIAGNOSED; corrected (1333e106):**
> CORRECTION: the 1-statement gap was NOT stray agent coverage. `--cov-report=term-missing` + `git blame` proved the missing line is `notifications.py:1291` (the `except HTTPException: raise` in the new dismiss endpoint), added by **Rachel's `c0db33d`** — unrelated to the harvest. The 4-file agent harvest is coverage-SAFE (agent modules stay 100%). My earlier "stray cross-tree incidental coverage" theory was a confabulation (theorized before reading the line). Corrected lesson: doc 26 §6.
- [x] **[LUPIN]** Found the lost statement: `notifications.py:1291`, owner = Rachel's `c0db33d` (NOT agent tests).
- [ ] **[LUPIN]** Cover `notifications.py:1291` (dismiss endpoint re-raise) — **Rachel's lane**, under Krishna review; flagged to her with the exact fix. Tree is 99% until done.
- [ ] **[LUPIN]** Harvest (now proven safe) — delete the 4 redundant legacy agent test files; commit ONLY once tree is green (Rachel's line covered) + Krishna review. Lower priority.

**🤝 NEW (1333e106) — coordinate with María on Rick's new workflow idea:**
- [ ] **[LUPIN]** Coordinate with María 🌸 on Rick's **new workflow idea** (idea TBD — Rick to specify; then capture + divide with María per the hub-spoke pattern). Placeholder added 2026-06-03 at Rick's request.

**🧵 FM-7 :7999 fix follow-up (1333e106):**
- [x] **[LUPIN]** Offload 3 blocking commons handlers to `asyncio.to_thread` (get_active_sessions / get_broadcast_history / post_register_question) — Krishna-APPROVED, committed `21af084`. Removes residual sync bridge I/O from the shared event loop (FM-7 / §13B saturation).
- [ ] **[LUPIN]** OPTIONAL belt+suspenders (Krishna's non-blocking nit): unit test asserting two concurrent `register_question` calls under a stubbed cap don't double-insert — pins the T6 lock invariant (`commons_question_watcher.py:202`) now that `to_thread` permits true concurrent registration. Not a blocker; the path is lock-safe by construction.

---

## 🟣 2026-06-03 RETURN-TO (Mr. Radio 🦉, session c0aede3d) — GCP Milestone-1 infra is UP; finish the connecting steps + app deploy

**✅ DONE this session (committed LOCAL, UNPUSHED):** Milestone-1 GCP TEST infrastructure **stood up & verified** — VM `lupin-host-test` with an **operational L4 GPU** (driver 535/CUDA 12.2; docker `--gpus all` smoke ✓) + full **data plane** (Cloud SQL private-IP PG16 `lupin_db_test`/`lupin_app`; 14 secrets; Artifact Registry `lupin-images`; IAM build-sa/runtime-sa; `dev-vpc` Service-Networking peering). Adopted the standalone `terraforming-vms` app for the VM (retired my `gce-gpu-vm`/`vpc-vpn` modules). Full record + commit list + connection name: `src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.06.02-terraforming-vms-reuse-and-integration.md` §9.

**🔁 RETURN HERE NEXT (none blocking — these are the app-deploy connecting steps):**
- [ ] **[LUPIN]** Bind data-plane IAM to the VM `vm_sa` (`lupin-host-test-sa@hello-world-foo-423219.iam.gserviceaccount.com`): per-bucket objectUser, per-secret accessor, cloudsql.client, AR reader (currently granted to `runtime-sa`).
- [ ] **[LUPIN]** Seed the 12 empty provider-key secret versions from `src/conf/keys/` (anthropic/openai/groq/google/gemini/mistral/elevenlabs/kagi/hf/jwt/smtp×2). `lupin-db-password` + `lupin-notification-api-key` are already populated.
- [ ] **[LUPIN]** Deploy Lupin to the VM: build/push image → `lupin-images`, IAP-SSH, `docker compose up` with `LUPIN_CLOUD_BACKED=true` + `CLOUD_SQL_CONNECTION_NAME=hello-world-foo-423219:us-central1:lupin-pg16-test`.
- [ ] **[LUPIN]** ⚠️ **Re-enforce Secure Boot** + adopt a proper signed-driver GPU path — current Secure-Boot-OFF is a TEMPORARY exception (Rick 2026-06-02; integration doc §8). Re-enable: `gcloud resource-manager org-policies enable-enforce compute.requireShieldedVm --project=hello-world-foo-423219`.
- [ ] **[LUPIN]** PUSH the held GCP commits (Lupin `baba032`→`32c0373`; `terraforming-vms` wip-2026.06.02-deploying-lupin-to-gcp: `9310741`, `7304dab`) — awaiting Rick's word.

Filed 2026-06-03 by Mr. Radio 🦉 at Rick's request.

## 🎙️ 2026-06-03 SESSION-END (Sam 🎙️, session 68ecdfb8) — GCP M1: SDK 0.2.88 + bundled-CLI + cloud-test compose; lupin:1.1.0 built & verified

**✅ DONE (committed `2637e01`, 6 files, UNPUSHED — per Rick's no-push session-end):**
- Guided 5-decision walkthrough → plan + decisions log: `src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.06.03-m1-vm-bringup-plan.md`. Decisions: full cutover · ratify standalone-VM architecture · **mount model** (bind-mount `./src` on the VM, NOT bake) · keys = manual scp interim · CC OAuth = manual setup-token + re-auth · Secure Boot stays OFF this milestone (COS signed-driver image = untried/viable).
- `claude-agent-sdk` 0.1.56→**0.2.88**; `uv.lock` regenerated (only SDK changed); Dockerfile CC CLI `curl|bash` → **symlink to SDK-bundled `_bundled/claude`** (CLI 2.1.161).
- `docker-compose.cloud-test.yml` — Cloud SQL **Auth Proxy sidecar** (unix socket) + mount-model app (`LUPIN_CLOUD_BACKED` + Testing-GCS) + GPU model-server (cuda:0); +8 unit tests (`src/tests/unit/deploy/test_cloud_test_compose.py`), all green.
- **`lupin:1.1.0` built + verified** (candidate tag; working `1.0.0` untouched): `claude --version`→2.1.161 via symlink; SDK + all 7 CC call-site symbols import; full app import OK (168 routes); compose lints.

**🔁 RESUME HERE (continues Mr. Radio's GCP RETURN-TO above):**
- [ ] **[LUPIN]** PUSH commit `2637e01` (+ Mr. Radio's held GCP commits) — awaiting Rick's word.
- [ ] **[LUPIN]** Rick: generate CC OAuth token (`claude setup-token` on home box) → seed into the VM like the keys.
- [ ] **[LUPIN]** Phase B — repoint data-plane IAM to `vm_sa` (TF `coalesce(external_vm_sa_email, runtime_sa)`; plan §Phase B).
- [ ] **[LUPIN]** Phase D2 — push `lupin:1.1.0` to `lupin-images` (secret-scan gate).
- [ ] **[LUPIN]** Phase E — VM bring-up: clone repo to data disk, `chown -R 1001:1001`, scp keys, fetch `DB_PASSWORD`, `docker compose -f docker-compose.cloud-test.yml up`.
- [ ] **[LUPIN]** Decide model double-load on the single L4 (flip `speech to text provider = model-server` in Testing-GCS so the app defers to the model-server) — plan open item.
- [ ] **[LUPIN]** Phase G — full uvicorn boot + `/health` + bounded-CC-job E2E (needs GPU + token; user-run or at deploy).

Filed 2026-06-03 by Sam 🎙️ at Rick's session-end request.

## 🔵 2026-06-03 FOLLOW-UP (Rachel 🕊️, session 624abe39) — tmux heartbeat / self-continuation for grind workers

- [ ] **[LUPIN]** **Follow up on the tmux-heartbeat self-continuation design** → `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/20-tmux-heartbeat-self-continuation-design.md`. **Verdict**: the same `tmux send-keys` path that delivers Rick's voice messages can inject "keep going" as first-class input — no new poker needed; `_arm_idle_waiter` already IS the poker (just notifies Rick instead of nudging the worker). **Gate the poke on the Notification `idle_prompt` event** (safe-to-poke signal — fires when CC is parked at the prompt; its own output is discarded so it can't inject, only time). Pairs with `build_stop_block` (in-turn reflex, self-guarded) as the backstop. **6 open questions in the doc** — chiefly: (Q1) consecutive-poke ceiling/backoff, (Q2) work-pending signal source, (Q3) speakerphone posture for grind workers. Reconcile with the messaging-coordination plane (`2026.06.02-messaging-coordination-plane-design.md`) — may share infra. For Tiberius 👑 + María 🌸.

## 🟢 2026-06-02 (Tiberius 👑, session 1333e106) — Post-game consolidated + TTS cap shipped; next infra item pending Rick's pick

**DONE today (checkpoint, NOT pushed):**
- [x] **[LUPIN]** CoSA-campaign **post-game consolidated** with María 🌸 → `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/18-postgame-coordinated-for-rick.md` (3-list, descending: **P0** messaging-plane · **P1** completion-discipline · **P2** harvest + reap-fix · **P3** TTS-guard). María's planning-is-prompting framework companion cross-linked both ways. Corrected the "MCP saturation" → "shared :7999 + synchronous handlers" root cause before it shipped.
- [x] **[LUPIN]** **TTS spoken-brevity cap** (implements post-game P3): caller-side cap in the cosa-voice MCP layer + `override_size_limitation: bool = False` on all 5 spoken tools; `cosa voice spoken char cap = 500` in lupin-app.ini, read via ConfigurationManager **mtime-gated → runtime-tunable** (verified live 500→333→500); 11/11 unit tests. R&D: `src/rnd/v0.1.8/2026.06.02-tts-spoken-brevity-cap.md`. **Activation needs one MCP restart.**

**Progress (2026-06-02):**
- [x] **[LUPIN]** ✅ **P2 reap-path** — verified live post-MCP-restart (`dismiss_sessions` list-arg reap works via `3488b43`; spawn→dismiss→empty roster). No re-implementation needed.
- [~] **[LUPIN]** **P0 messaging-coordination plane** — DESIGN DOC done + in Rick's review: `src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md` (5 levers A–E; rec order A→D→B→C→E; no external broker this milestone). **Holding for Rick's lever/order decisions before any code.**

**Finish-unfinished triage — Rick's 4 decisions (relayed via María 2026-06-02; recorded post-game §3.7 + framework §11):**
- [ ] **[LUPIN]** **T1 — 403-queues (U4):** INVESTIGATE as a tripwire FIRST — possible real prod regression; root-cause before touching the ~37 `cosa/tests/unit/rest/` failures; do NOT test-fix a possible prod bug (G0.2). The other ~36 = routine stale-mock refresh.
- [ ] **[LUPIN]** **T2 — prod-bug #11:** FIX NOW + de-arm the xfail + re-verify (`prediction_engine.py` dead LLM-synthesis tier; armed tripwire ⇒ correct behavior known ⇒ mandated, not gated).
- [x] **[LUPIN]** **T3 — `ResearchOrchestratorAgent` (U7): KEEP + coverage-exclude** (Rick-decided; NOT deleted — closes the last Rick-only U-decision).
- [ ] **[LUPIN]** **T4 — sequencing:** io_models (79→100) + `test_suite_completion_watchdog` SOLO now (fleet-free); **Agents Tier-2 long pole GATED on the messaging fix / WAVE-3** — NO pre-fix fleet spawn (would re-create FM-7).

**Near-term solo lane (fleet-free, parallelizable with the messaging work):** prod-bug #11 · io_models · watchdog · 403-queues investigation.

## Pending Decisions

> Queue for `/plan-decide` (the **guided-decision-walkthrough** skill). One-line topics; the skill frames each live with pros/cons + a recommendation, descending priority. Detail lives in the linked design docs.

**Messaging-coordination plane (P0)** — ✅ **ALL 7 RESOLVED 2026-06-02 via `/plan-decide`** (Rick ratified every recommendation). Source `src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md` (§ Ratified Decisions). Rulings in the Decisions Log below.
- **Implementation queue — ✅ ALL 5 LEVERS COMPLETE:** A durable outbox · D pull-able inbox · B loop de-block · C express lane · E backpressure. In-process, no broker. **A ✅ · D ✅ (committed `722e624`, :8000 integration 2/2) · B ✅ · C ✅ · E ✅** — 990 unit tests green, no regressions. B/C/E committed in the wrap-up checkpoint.

**Messaging plane — follow-on (deferred design decision):**
- [ ] **[LUPIN] Lever B comprehensive sweep** — revisit moving ALL remaining sync DB/file I/O off the event loop (beyond the surgical hot-handler fix), after measuring whether colder paths still stall under load. Deferred per Rick 2026-06-02; surgical fix lands first.

## Decisions Log

> ADR-lite: `YYYY-MM-DD — decision → ruling. Why: …`. Appended by `/plan-decide` and ad-hoc.

- 2026-06-02 — TTS spoken-cap location → enforce caller-side in the cosa-voice MCP layer, NOT the notifications REST API. Why: limit agent verbosity at the tool boundary; keep the shared delivery API free for jobs/system.
- 2026-06-02 — TTS cap default + tunability → 500 chars in lupin-app.ini, ConfigurationManager mtime-gated (runtime-tunable). Why: Rick's call; adjustable without code edit or restart.
- 2026-06-02 — Over-cap behavior → REJECT (raise), not truncate; `override_size_limitation=True` bypasses. Why: no silent content loss; long-is-opt-in-and-intentional.
- 2026-06-02 — Reap path (`dismiss_sessions`) → already fixed at source (`3488b43`); verified live post-restart, not re-implemented. Why: typed-wrapper coercion fix was the whole bug.
- 2026-06-02 — T1 403-queues → investigate as a tripwire first (no test-fix until root-caused). Why: possible real prod regression (G0.2).
- 2026-06-02 — T2 prod-bug #11 → fix now + de-arm + re-verify. Why: armed tripwire ⇒ correct behavior known ⇒ mandated, not gated.
- 2026-06-02 — T3 `ResearchOrchestratorAgent` → KEEP + coverage-exclude. Why: Rick knows its status; not dead.
- 2026-06-02 — T4 Agents Tier-2 → gate on the messaging fix (no pre-fix fleet). Why: avoid re-creating FM-7.
- 2026-06-02 — MP-Scope (messaging plane) → in-process, NO external broker this milestone. Why: pain is a ~5-session fleet, not internet-scale; avoid an ops dependency before GCP.
- 2026-06-02 — MP-A client delivery → A1 durable outbox + retry/ack (idempotency_key). Why: converts transient slowness → delayed delivery instead of permanent loss.
- 2026-06-02 — MP-D AFK recovery → D1 undelivered-inbox + on-return surfacing. Why: fixes FM-18 (the 4h-invisible miss); user can pull what was missed.
- 2026-06-02 — MP-B server loop → B1 move blocking I/O off the event loop (hot handlers first). Why: stop inline file/DB I/O from starving the loop under fleet load.
- 2026-06-02 — MP-C load isolation → C1 in-process express/priority lane for interactive notify/ask. Why: keep Rick's voice alive during a fleet storm.
- 2026-06-02 — MP-E backpressure → E1 per-source cap + 429/retry-after. Why: shed excess fleet load gracefully; outbox honors retry-after.
- 2026-06-02 — MP-Order rollout → A→D→B→C→E. Why: A+D first retire the silent-loss class at lowest risk; each phase independently shippable.
- 2026-06-02 — Lever B (loop de-block) scope → **SURGICAL** (hottest handlers first: notify DB-persist + commons file writes via `run_in_executor`), NOT a comprehensive sweep. Why: lowest blast radius; targets the FM-7 hot paths; measure then expand. (Revisit item filed in Pending Decisions.)
- 2026-06-02 — Lever C (express lane) signal → **PRIORITY field** (high/urgent = express, low/medium = normal). Why: the speakerphone rider already sets interactive notifies to high; zero new concept.
- 2026-06-02 — Lever E (backpressure) source → **PER-SESSION by `sender_id`**; values in `lupin-app.ini` (per-session cap + window + retry-after), runtime-tunable (mtime-gated) + splainer. Why: isolates a runaway worker without throttling the user's interactive session.

## 🚀 ACTIVE (2026-05-30) — GCP deployment: local-dev → GCP-TEST migration (Milestone 1)

**Sam 🎙️ (session 657452e9).** Arc complete through planning + decisions: survey → straw-man plan → Cloud Run vs GCE comparison → all strategic decisions resolved with Rick → "production" wording scrubbed. Docs in `src/rnd/v0.1.8/2026.05.30-gcp-deployment/`. **Mid-session checkpoint committed (NOT pushed).**

**Milestone-1 scope (Rick-confirmed):** prove the **local-dev → GCP-_test_ migration** process. NOT production (that's a later, easy GCP→GCP horizontal clone).

**Decisions locked:** D2 single GCE g2-standard-8 + L4 VM · D1 CC OAuth = setup-token in Secret Manager (+ a token-**refresh** mechanism for CC's occasional forced re-auth) · CC **consolidated** onto the GPU VM · D8 exclude keys from image + rotate + verify history · D3 **reuse sandbox project** for now · IaC = Terraform + bash · **no staging tier** · on-demand cost (credit-covered, **tracked as real $**). Auto-settled by the VM choice: D6 single-instance · D7 image-slim deferred · D9 self-hosted Whisper · D5 vLLM via Cloud VPN.

**Resume here (next session):**
- [ ] **[LUPIN]** Pick the start point: **Phase 0** (credential-gated validation — needs Rick's sandbox `gcloud` access) OR **Phase 1** (pre-deploy hygiene — no GCP needed: `LUPIN_ROOT` fix, exclude+rotate keys, parameterize the four `cloud-run-*.sh` scripts).
- [ ] **[LUPIN]** **OPEN ITEM — `LUPIN_ENV` tension** (surfaced by the test re-scope): the cloud path is gated on literal `LUPIN_ENV == "production"`, but M1 is a *test* env selecting `[Lupin: Testing-GCS]` → either reuse the `production` value as the cloud-profile trigger, or extend the code so `testing` is cloud-backed. Resolve before cutover (plan §7.1.3 note).
- [ ] **[LUPIN]** Phase-0 validation in the sandbox project: region + L4 quota, existing `-test` buckets / Cloud SQL PG16, existing secrets, IAM/Workload-Identity.
- [ ] **[LUPIN]** Implement the D1 **token-refresh mechanism** (re-mint setup-token → update Secret Manager version → VM reloads; SSH `claude login` manual fallback).
- [ ] **[LUPIN]** Review agent-flagged plan lines §9 WS1 (~1759/1768) — `model server local mode` config-block wording in the future-GKE phase (left as future-prod per the scrub rules; revisit if M1-VM execution should read as the cloud-backed block).
- [ ] **[LUPIN]** Commit `src/rnd/README.md` GCP index links later — **deferred from this checkpoint** (multi-session conflict file; my links persist in the working tree).

Full plan + §1 Decision Ledger + resolved-decisions callout: `src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.05.30-gcp-deployment-provisioning-plan.md`. Survey + Cloud-Run-vs-GCE comparison in the same dir.

## 🔴 TOP PRIORITY (2026-05-30) — CoSA 100%-coverage grandfathering ramp gate (one-week deadline)

**Filed by Tiberius 👑 (session `ac012bd2`) per Rick's 2026-05-30 voice instruction** ("include the one-week ramp-up gate for all migrated CoSA source code to 100% coverage as a top priority"). This formalizes the `coverage inherits + grandfathering-ramp` decision that was ratified during the 2026-05-29 mono-repo fold (commit `0a01da3`) but never written as an actionable, time-boxed item — it was buried in the DONE block below.

**The gate**: the 621 CoSA files folded in as first-class Lupin source (`src/cosa/`) now inherit the **Lupin-wide 100% coverage mandate** (line + branch + function — see `feedback_100pct_coverage_multiplexer.md`, scope-expanded 2026-05-16). A grandfathering ramp was granted so the fold wasn't blocked on instant 100%. **Deadline framing: 2026-06-05** (one week from the 2026-05-29 fold).

**Formal plan (2026-05-30, ratified by Rick via interactive walk-through):** campaign doc home → `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/` (`README.md` index + `00-campaign-plan.md`); baseline currently `src/rnd/v0.1.8/2026.05.30-cosa-100pct-coverage-baseline.md` (relocates into the campaign dir once Tiffany's combined run completes). Key rulings: deadline = **milestone ramp** (config + library tier by 06-05; agents/REST ramped on a published schedule — hard-100%-by-06-05 is ~15-40 grind-days, not reachable by hand); methodology = combined (evidence-confirmed); execution = flat 3-author bounded-CC fleet (Tiffany lead) + adversarial reviewer gating commits, run overnight via the new heartbeat-poker; standing test-only commit authority granted. Baseline measured 45.3% line / 34.8% branch (corrected denominator, zero tests). Combined unit+:8000 evidence COMPLETE: **52.0% line / 41.7% branch** (REST +1,776 server-covered → hybrid); D4 tiering resolved.

**▶ RESUME / NEXT ACTION (cold-start): the off-peak launch (tonight, post-midnight EDT) via the runbook's §15 cold-start checklist** — live-verify the poker (still PENDING) → land Tier-0 `[tool.coverage]` config → spawn 3 FRESH authors + 1 reviewer (cold-brief each from `02-cold-start-runbook.md`, disjoint Tier-1 module-groups) → grind (per-batch reviewer-gate + green-gate, test-only commits). Tiffany was reaped (fact-gathering done); fleet spawns fresh. Also schedule a clean un-instrumented :8000 E2E to validate 31 parallel-session E2E failures. **Execution doc: `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/02-cold-start-runbook.md`.**

**✅ 2026-06-01 UPDATE (Tiberius 👑, session b8a9f332) — `cosa.rest` now at GENUINE 100%.** Completed `src/cosa/rest/` to tree-wide 100% (`11053/0` lines · `2958/0` branch · 2363 passed) — 35 test-only commits, **HELD (not pushed)**. Caught FM-17 (agent-vs-router conflation) via the tree-wide gate + closed the remainder. Session record: `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/17-session-end-100pct-wrap-and-reap-explanation.md`. Carried-forward items:
- [ ] **[LUPIN]** **PUSH** the held CoSA-coverage commits to remote — awaiting Rick's explicit word (~130 commits local).
- [ ] **[LUPIN]** **Ratify** (Rick): the AC12 thin-route-handler pragma grandfather precedent (per-endpoint integration-coverage verified) + the `speech.py` `app_debug` 1-line prod bug-fix (debug-only path).
- [ ] **[LUPIN]** **websocket_manager** independent reviewer post-audit (committed manager-self-audited under FM-7; tree-wide gate is the 100% proof; post-audit owed).
- [x] **[LUPIN]** ✅ **DONE 2026-06-01 (reap, process-verified):** the parked fleet's tmux sessions + 13 orphaned listeners reaped. **Root cause:** `tmux kill-session` orphaned the listener daemons (reparented to ppid=1, kept running); they **ignore SIGTERM** and **reconnected** to :7999 after a FastAPI restart — which is why they looked like un-reaped "zombies" (state-Z count was always 0; they were live orphans). Fixed via **SIGKILL by exact PID**, protecting the 3 live listeners (Tiberius/María/Krishna). The `dismiss_sessions` fix `3488b43` is committed but still needs an MCP restart to make the *proper* tool-based reap live next time.
- [ ] **[LUPIN]** **Messaging-black-hole ROOT-CAUSE** (Rick-assigned, BEFORE the next coverage batch): FM-7/11/15/18 = one unreliable coordination plane (no delivery-guarantee / load-isolation / pull-able fallback). **Layer-A confirmed 2026-06-01:** cosa-voice MCP is **stdio, per-session subprocess** (`claude mcp get cosa-voice` → Type: stdio) — so there is NO shared MCP-server bottleneck; the real bottleneck is the **shared :7999 app server + synchronous notify/commons handlers** (each handler POSTs to :7999 on a ~5s budget → under fleet load :7999 slows → every session's handler times out → black-hole). This **corrects** the earlier "MCP-server saturation" framing. Tiberius owns cosa-voice/commons infra debug; María codifies the synthesis + fix-space. **Do NOT spawn the next batch until hardened.**
- [ ] **[LUPIN]** **RETURN TO FULL POST-GAME ANALYSIS (next session — Rick-requested 2026-06-01):** resume the collaborative messaging-root-cause + framework synthesis with María (FM-7/11/15/18 as one coordination plane → fix-space). Layer-A done (above); remaining = fix-space design (delivery-guarantee / load-isolation / pull-able fallback) + roll the harvest/SIGKILL lessons into the runbook + the broader synthesis doc.
- [ ] **[LUPIN]** Broader cosa ramp continues — `rest/` done; remaining cosa subtrees (agents not-yet-100%, memory/app/tools/utils) per the 2026-06-05 ramp.

- [ ] **[LUPIN]** Baseline-measure current coverage across all migrated `src/cosa/` modules (pytest `--cov=cosa --cov-report` line+branch+function) — produce the gap list (files < 100%).
- [ ] **[LUPIN]** Triage the gap list into (a) reachable lines needing tests, (b) genuinely-unreachable defensive branches needing same-line `# pragma: no cover` + reason.
- [ ] **[LUPIN]** Write/extend tests to close every reachable gap; land same-line-reasoned pragmas on the rest. Report tabular per-module pass/coverage.
- [ ] **[LUPIN]** Wire a CI/pre-merge `--cov-fail-under=100` (or equivalent) gate over `src/cosa/` so the ramp can't silently regress after the deadline.
- [ ] **[LUPIN]** On completion: flip the grandfathering note in `feedback_100pct_coverage_multiplexer.md` from "cosa inherits with ramp" to "cosa fully gated", and update the CLAUDE.md coverage section.

**Excludes** (per the standing mandate): sub-repos `lupin-mobile`, `lupin-plugin-firefox`, and external-project bind-mounts. CoSA is in-scope as of the fold.

## 🌅 MORNING (2026-05-29) — LIVE cascade demo: Manager-Spawned Reviewers (Rick wants to see it in action)

Feature **v1 is feature-complete + live-validated** (spawn-1-reap-1 passed; collision-hardened). Rick asked to run the full cast live in the morning (off-peak 12am–9am EDT ✓).

- [ ] **[LUPIN]** Restart the cosa-voice MCP subprocess FIRST — the running one cached the pre-fix `session_spawner` during dry-runs, so the role-in-name / lowest-free-index collision fix isn't live in it yet.
- [ ] **[LUPIN]** Run a LIVE manager-spawned cascade: `spawn_sessions(3, role="reviewer", ...)` then `spawn_sessions(1, role="author", ...)` → confirm 4 distinct sessions boot (`cc-reviewer-tiberius-1/2/3`, `cc-author-tiberius-1`), each headless + speakerphone-off + own persona, posting to `dm-tiberius`; exercise `list_spawned_sessions`; then `dismiss_sessions` and confirm clean reap.
- [ ] **[LUPIN]** Optional next: wire `expected_ack_deadline` into the spawn result (María's §3.3 swap); derive reviewer tmux `name_prefix`/role surfaces if cosmetics matter.
- Design doc: `src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md` · Runbook (María): `planning-is-prompting/workflow/plan-review-cascaded-on-demand-spawn.md`

## 🗓️ NEW (2026-05-29) — Durable scheduled-job persistence across server bounces

**Problem (Rick, 2026-05-29):** Scheduled jobs (e.g. `/api/test-suite/submit` with `scheduled_at`, plus recurring maintenance like the LanceDB compaction routine) live in **server memory**. Bouncing a server — common when you schedule a night job mid-day then redeploy — silently **loses** all queued/scheduled jobs. Rick wants object permanence: scheduled + recurring jobs must survive restarts.

- [x] **[LUPIN]** ✅ **DONE 2026-05-29 (Tiberius 👑):** one-shot (`scheduled_at`) scheduled jobs now survive server bounces. The base persist→preserve→restore→fire chain already existed; closed the **missed-window gap** (a job whose `scheduled_at` passes WHILE the server is down was dropped as INTERRUPTED) via a **measured-downtime catch-up**: 60s heartbeat + clean-shutdown marker → `ServerLifecycle` table → `mark_interrupted_jobs()` preserves past-due-in-downtime jobs. Migration `e9f0a1b2c3d4`. 40/40 unit tests, 100% coverage on changed lines, live-bounce verified. Doc: `src/rnd/v0.1.8/2026.05.29-scheduled-job-bounce-survival.md`. (cosa code committed via fold `0a01da3`; parent wiring committed separately.)
- [ ] **[LUPIN]** Recurring / cron-like scheduled jobs — the OTHER half of bounce-durable scheduling (only one-shot `scheduled_at` is implemented). Design when needed.
- [ ] **[LUPIN]** First durable client of the new mechanism: the recurring LanceDB compaction routine (nightly off-peak 12am–9am EDT). **Decision 2026-05-30 (Rick):** declined an OS-crontab stopgap — will schedule the compaction *manually, day-by-day* for now. Build the in-app recurring durable-job mechanism as the proper fix when prioritized; do NOT re-propose crontab.
- [ ] **[LUPIN]** **Swap-step robustness — learned 2026-05-29 during the live `input_and_output_tbl` rebuild (82GB→679MB, ~81GB reclaimed):** a corrupt-version-chain table needs a REBUILD, not `optimize()`. On LanceDB OSS, `rename_table` is `NotImplementedError` (the method exists but fails — fails *closed*, so it's safe). The `drop_table` + `create_table`-into-the-same-dir fallback works BUT can strand a stray V1 `_versions/<n>.manifest` from the dropped table → **mixed V1/V2 manifest schemes → table unreadable → both servers crash-loop on open** (happened; recovered by quarantining the stray manifest + restart). The durable swap MUST: (a) quarantine/clean stray manifests in the target dir before serving, (b) bounce BOTH servers (they hold the table open + voice rides :7999), (c) keep a staged copy + verified backup covering the drop→create window. Reusable tool exists: `src/scripts/rebuild_lancedb_table.py` (staged build/swap/status). This belongs in the pgvector revisit note too (it's concrete evidence the append-log, not the engine, is the problem).

Filed 2026-05-29 by Tiberius 👑 (session `c9c582b7`).

## ✅ DONE (2026-05-29) — CoSA→Lupin mono-repo merge + local-venv relocation (Krishna 🦚, session `5496cbb6`)

**Phase A (local dev-venv relocation) is DONE** — commits `bf97e1a`, `eda7caf`, `6cdcb7b` on `wip-v0.1.8` (LOCAL + UNPUSHED). New root `.venv` (py3.13) mirrors the container's locked set minus pyaudio/flash-attn/autoawq (native, host-unbuildable, zero host-side imports); unit 5034/0 + WS smoke 50/50 on it; old `src/cosa/.venv` kept as fallback; production Dockerfile untouched. Full plan + weighted pros/cons: `src/rnd/v0.1.8/2026.05.29-cosa-lupin-monorepo-merge-analysis-and-plan.md`.

- [x] **[LUPIN]** ✅ **DONE 2026-05-29** — Pushed `wip-v0.1.8` (all 8 commits: venv + fold + scrub + Tiberius's durable-job/LanceDB). Verified 2026-05-30: origin synced at `2240bf6`, 0 ahead / 0 behind.
- [ ] **[LUPIN]** Container parity (no action — just expect it): the next `lupin:1.0.0` rebuild picks up `openapi-to-md` (now in root `pyproject.toml`/`uv.lock`).
- [x] **[LUPIN]** **Phase B — CoSA→Lupin git fold — DONE** (commit `0a01da3`, flatten, directly on `wip-v0.1.8`): 621 cosa files folded as first-class Lupin source; `src/cosa/.git` **MOVED** (not deleted) → `/mnt/DATA02/cosa-git-archive-2026.05.29/` (full history + 42 branches preserved, reversible); unit 5058/0 + WS smoke 50/50 on the folded tree. Decisions ratified by Rick: flatten · move-aside-not-delete · directly-on-branch (not deferred — it's a GCP prerequisite) · coverage inherits+grandfathering-ramp · namespace PRESERVE · GCS container-only · venv lean subset.
- [x] **[LUPIN]** **Doctrine scrub — DONE** (commit `6bac0bc`): `CLAUDE.md` de-submodule'd (cosa dropped from nested-repos list; firefox/mobile kept); `src/cosa/CLAUDE.md` SUPERSEDED banner; deleted 2 obsolete CoSA-separation memories + their MEMORY.md index lines; flipped the coverage memory to cosa-inherits-the-100%-gate; removed the newline-named junk file; María shipped the PIP-side doctrine (`bbcd865`).
- [ ] **[LUPIN]** **Doctrine-scrub RESIDUAL** (flagged to Rick): retire/edit the `nested-repo-management` skill — no locatable SKILL.md (likely plugin-managed); needs CoSA dropped, Firefox/Mobile kept. Plus minor staleness in 2 memory bodies (`feedback_cross_project_handoff`, `feedback_sweep_for_pattern_offenders`) + a `src/cosa/CLAUDE.local.md` banner.
- [x] **[LUPIN]** Pinged María 🌸 — she shipped the PIP refresh (`bbcd865`); axis-1 PRESERVE held with zero invocation rewrites, coverage inherited. Doctrine now consistent across all three surfaces (Lupin code, Lupin doctrine, PIP doctrine).

Filed 2026-05-29 by Krishna 🦚 (session `5496cbb6`).

## 🔬 POST-PR (2026-05-29) — Revisit: LanceDB → PostgreSQL/pgvector migration analysis

Tiberius 👑 ran a multi-agent research workflow (`wkiwwi4u4`) on moving semantic-similarity storage off LanceDB. **Verdict: the 81GB "bloat" is stale, uncompacted version history in ONE append-only log table** (`input_and_output_tbl`: 81G `_versions/`, only ~898MB live `data/`) — a missing-compaction-cron problem, NOT a vector-engine problem. The "migrate to fix the disk" premise was **refuted** adversarially. At Lupin's scale (tens of thousands of 768-dim vectors, single node) pgvector vs LanceDB query perf is a wash (both sub-10ms).

- [ ] **[LUPIN]** After this PR merges, serialize the parked draft → `src/rnd/v0.1.7/2026.05.29-lancedb-to-postgresql-pgvector-migration-analysis.md` (currently held at `~/lancedb-pgvector-analysis-DRAFT.md`, outside the repo during the PR per Rick's instruction).
- [x] **[LUPIN]** ✅ **DONE 2026-05-29** — Phase 0 disk reclaim complete: the `input_and_output_tbl` rebuild reclaimed ~81GB (82GB→679MB) via `src/scripts/rebuild_lancedb_table.py`. (The recurring-compaction *scheduling* half — wiring it into a cron so the append-log never regrows — remains tracked above under the durable scheduled-job entry, "First durable client: the recurring LanceDB compaction routine.")
- [ ] **[LUPIN]** Only THEN decide the pgvector migration on consolidation/ACID merits alone (Postgres already deployed as `lupin-postgres`, but ships only `uuid-ossp` — pgvector extension not yet installed). If migrating: move only the ~165MB of genuine vector tables, leave the append-log behind, use the `snapshot_manager` abstraction as the cutover seam.

Filed 2026-05-29 by Tiberius 👑 (session `c9c582b7`). Full draft + 6 adversarial verdicts in the parked file.

## 🟢 PHASE 7A CASCADE-COMPLETE — Run 4 closed 2026-05-20 03:30 UTC (Manager: Tiberius 🌑, session `387b9201`)

**Status**: Phase 7a Telemetry is implementer-handoff-ready. All 4 cap surfaces closed (Stage 1 + 2 + 3 + Step 9 light-review). 57% net cap utilization; 50%+ headroom preserved across every cap surface. Zero T3/T4 escalations.

**Implementer entry points**:
- Canonical design doc: [`15-phase7a-telemetry-design.md`](src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/15-phase7a-telemetry-design.md) (cascade-ratified, ~470 LOC)
- Synthesis + handoff doc: [`16-phase7a-cascade-synthesis.md`](src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/16-phase7a-cascade-synthesis.md) (NEW, ~360 LOC, this run's deliverable)
- Pre-cascade recon (background): [`14-phase7a-telemetry-pre-cascade-recon.md`](src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/14-phase7a-telemetry-pre-cascade-recon.md)
- Slicing manifest (Step 0 inputs): [`13-phase7-slicing-manifest.md`](src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md)

**Cast** (Run 4): Mr Radio 🦉 (Stage 0), Rachel 🕊️ (Stage 1), Krishna 🦚 (Stage 2 + Step 9 light-reviewer), Rio ⚡ (Stage 3), María 🌸 (Observer + doctrine consultant), Tiberius 🌑 (Manager).

**Next steps**:
- [ ] **[LUPIN]** Phase 7a code-execution plan → `17-phase7a-execution-plan.md` (post-cascade execution plan, DAG-first per Roscoe pattern) — Manager + implementer to draft
- [ ] **[LUPIN]** Phase 7a implementation (gated on Phase 6c close per slicing manifest §Where this manifest lives in the cadence) — Roscoe 🤠's Node C must ship first
- [ ] **[LUPIN-COSA]** Cross-project handoff: `/api/multiplexer/config` Pydantic extension (add `otel_collector_endpoint: str` + `otel_sampling_rate: float` fields). Filed at code-write time per [[cross-project-handoff-doc]] — handoff doc + seed TODO in CoSA TODO.md per [[lupin-only-never-cosa]]
- [ ] **[LUPIN]** Phase 7b CSP cascade (Run 5) — gated on Phase 7a implementer-handoff acceptance
- [ ] **[LUPIN]** Phase 7c Trusted Types cascade (Run 6) — gated on Phase 7b
- [ ] **[LUPIN]** Phase 7d Accessibility cascade (Run 7) — gated on Phase 7c
- [x] **[LUPIN-PIP]** v1.1 doctrine codification — ✅ **SHIPPED 2026-05-20** at PIP commit `adcd96d` (committed, NOT pushed per Rick's standing EOD directive). 7 candidates promoted + 1 placeholder (final shape after María ↔ Tiberius post-Run-4 convergence DM thread, 4 cycles, ratified 2026-05-20):
  1. Heartbeat-daemon kickoff codification → `plan-review-cascaded-common.md` §Heartbeat Handling — Daemon kickoff procedure (dual-independent default)
  2. Manager close-out self-audit sweep → `plan-review-cascaded-common.md` §Step 9 cold-context rubric Q#6 + §Manager close-out self-audit sweep sub-section (added during convergence DM as 6th candidate)
  3. Author-side grep-sweep checklist (Krishna Q-1..Q-4 anchor #2 + Tiffany-rename anchor #3) → `plan-review-cascaded-common.md` §Author-side Discipline — Grep-sweep Checklist
  4. 4-tier clarification doctrine (T1/T2/T3/T4) → `plan-review-cascaded-common.md` §Clarification Tier Vocabulary
  5. Manager proactive `commons_read` (failure-mode #6 single-loop mitigation) → `plan-review-cascaded-common.md` §Manager System Prompt self-audit item 7
  6. Observer-probe-as-mitigation channel (failure-mode #6 double-loop mitigation) → `plan-review-cascaded-common.md` §Observer-mode Probe Protocol + `plan-review-cascaded-personas.md` Persona 6 (added during convergence DM as 7th candidate)
  7. Multi-surface footer-ratification close protocol with non-adjacent + Step-9-synthesis-doc 7th-surface refinement → `plan-review-cascaded-common.md` §Multi-surface Footer-ratification Close Protocol
  8. PLACEHOLDER — explicit `[CLOSURE: …]` markers — queued for Run 5+6 evidence per Krishna's FILE-not-FOLD recommendation

  **Pre-committed re-evaluation gates** also locked at design-doc §10.18.12 (4 gates: Run 5/6 wisdom-curve slot-vs-persona controlled experiment + Run 7 forward-asymmetry re-evaluation + Run 7 `light_review_required` HARD-promotion + Run 5/6 failure-mode-#6 mitigation validation; anti-pattern of silent gate slippage forbidden).

  **Bilateral review**: 8/8 ratification checkpoints verified by Tiberius 🌑 (Lupin session `173c0b35`); two non-blocking observations filed as v1.2 polish candidates (Persona-6 Step-9 cadence M=4 borderline-usefulness; Manager-System-Prompt item-7 → Q#6 → sweep-procedure 3-hop cross-reference chain consolidation).

- [ ] **[LUPIN]** `start-cascade-heartbeat.sh --observer` convenience flag — explicit dual-launch ergonomics. Current invocation works via persona-name arg (`bash src/scripts/start-cascade-heartbeat.sh <persona>`); the v1.1 doctrine now formalizes the dual-independent kickoff (Manager daemon + Observer daemon both required when a doctrine consultant participates), so a `--observer` flag would smoothen the doctrine application. Doctrine motivation lives at `planning-is-prompting/workflow/plan-review-cascaded-common.md` §Heartbeat Handling — Daemon kickoff procedure (PIP commit `adcd96d`). Filed 2026-05-20 by Tiberius 🌑 session `173c0b35` per agreed Lupin TODO split-out from the v1.1 codification close.

- [ ] **[LUPIN]** `commons_send_to` recipient pool-key vs display-name routing gap — existing TODO. The v1.1 Observer-mode Probe Protocol now structurally exercises this gap as a regular routine (Observer DMs Manager with unread-signal pointer on every probe-mitigation event), not a fringe case. Bump priority if codification-pass DM threads surface friction. Filed forward by Tiberius 🌑 session `173c0b35` per agreed Lupin-side cross-link from the v1.1 codification close.

**Standing playbook**: commit-only no-push per [[never-auto-commit-push]]. All work uncommitted in working tree awaiting Rick's morning go-ahead.

---

## ✅ DONE 2026-05-28 — Tiberius persona emoji contrast fix: 🌑 → 👑 (Rio ⚡, session `a507b1a5`)

**Context**: Rick flagged that Tiberius's persona badge renders as a dark blob. The icon `🌑` (U+1F311 new moon — a near-black filled disc) sits on color `#3F51B5` (Material Indigo 500), giving near-zero contrast. Rick ratified the replacement `👑` (crown) — high-contrast gold-on-indigo, and it reinforces the Roman-Emperor namesake.

**The change** (config-only — no code):

- [x] **[LUPIN]** `src/conf/lupin-app.ini`: `cc session voice persona Tiberius icon` — changed `🌑` → `👑`
- [x] **[LUPIN]** `src/conf/lupin-app-splainer.ini`: paired splainer entry updated to `Default: 👑.` + change note

---

## 🎨 NEW — Retire-no-green-color-rule sweep: deferred references (filed 2026-05-28 by Rio ⚡, session `a507b1a5`)

**Context**: Rick retired the no-green persona-color rule on 2026-05-28 ("no longer in effect, remove all references"). Active config + auto-memory were cleaned this session. The following references remain and were deferred for parallel-session-safety / historical-record reasons:

- [ ] **[LUPIN]** `src/tests/unit/test_voice_persona_helpers.py` — `TestExtraColorsGreenRule` class (lines ~702-717) enforces the retired rule. **NOT touched this session: file was being modified by a parallel session.** A Lupin-context session that owns this file should remove the class (extra-colors palette currently still passes it by legacy coincidence, so it isn't red — just dead).
- [ ] **[LUPIN-COSA]** `src/cosa/rest/voice_persona_helpers.py` (lines ~301, ~423, ~513) — docstrings/comments say "Green-rule-compliant palette". Trim the green-rule wording in a CoSA-context session (per [[lupin-only-never-cosa]] — edit only from CoSA context).
- [ ] **[LUPIN]** ~18 dated R&D docs under `src/rnd/v0.1.7/` reference the rule. Mostly point-in-time historical records — recommend leaving as-is, but the current/active `2026.05.28-extra-n-overflow-personas.md` may warrant a note that the rule is retired. Rick to confirm whether historical docs should be swept.

---

## 🟢 RATIFIED — Phase 7 slicing manifest authored + 4 decisions locked (filed 2026-05-20 by Mr. Radio 🦉, session `32a6e563`)

**Filing context**: Manifest at [`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md`](src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md). Tiberius 🌑 (session `387b9201`) greenlit the draft; Rick ratified all 4 decisions via cosa-voice blocking tools 2026-05-20.

**Ratified decisions**:
1. **Sequencing**: Option A — 7a Telemetry → 7b CSP → 7c Trusted Types → 7d Accessibility
2. **Pre-cascade recon**: ON (1-2h author-side per slice, 4-8h total before any design-doc cascade fires)
3. **7b iterative-tightening**: DECOUPLED as operational close-out (not second cascade)
4. **7d audit-driven cycle**: DECOUPLED as operational close-out (not second cascade)

**Phase 7 implementation gated on Phase 6c close** — Roscoe 🤠 has Node C in flight per `12-phase6c-execution-plan.md`. Phase 7 start = Phase 6c ship.

**Phase 7a workflow progress** (Rick clarified parallel-track 2026-05-20 — planning unblocks before 6c ships):
- [x] **[LUPIN]** Author 7a Telemetry pre-cascade recon doc — RESOLVED 6 items (OTel packages, Long Tasks support, telemetry sink endpoint config, ReportingObserver, User Timing Level 3, directory stubs). Path: `14-phase7a-telemetry-pre-cascade-recon.md`. Tiberius 🌑 greenlit DM `9e011230`. ✅ DONE 2026-05-20 (Checkpoint 2)
- [x] **[LUPIN]** Stage 0 author draft — `15-phase7a-telemetry-design.md` (single cluster T, Q-T1..Q-T7, 14 ACs, 4 OSQs, ~480 LOC). Author rotation ratified via Rick's cast spin-up. ✅ DONE 2026-05-20 (Checkpoint 2)
- [ ] **[LUPIN]** Step 0 doctrine light-review by María 🌸 — IN PROGRESS, ~15-20 min wall-clock. Run 4 is first live test of Step 0 doctrine
- [ ] **[LUPIN]** Stage 1 Usability/Reuse dispatch to Rachel 🕊️ — gated on María's light-review pass
- [ ] **[LUPIN]** Author revision loop (CAP 2/2) if Stage 1 surfaces foundational findings
- [ ] **[LUPIN]** Stage 2 Ownership-Language Audit by Krishna 🦚 (NOT security per `feedback_pass2_is_ownership_audit_not_security`)
- [ ] **[LUPIN]** Stage 3 Synthesis by Rio ⚡ → `16-phase7a-cascade-synthesis.md`
- [ ] **[LUPIN]** Step 9 synthesis-and-handoff doctrine validation — Tiberius + María doctrine consultant cycle. Run 4 is first live test of Step 9 doctrine
- [ ] **[LUPIN]** Phase 7a code-execution plan → `17-phase7a-execution-plan.md` (post-cascade)
- [ ] **[LUPIN]** Phase 7a implementation (gated on Phase 6c close per slicing manifest §Where this manifest lives in the cadence)

**Cross-refs**:
- Slicing manifest: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md`
- Phase 7 row in roadmap: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` §3
- Phase 6 slicing template: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/07-phase6-slicing-manifest.md`

**Empirical anchor for Step 0 doctrine** — Tiberius's brief said my manifest's §Pre-cascade recon section is validating the Step 0 cascade-prep doctrine he and María 🌸 are codifying on the PIP side. One-line back-ref pending when Step 0 codification commits.

---

## 🟡 NEW — Phase 6c follow-on: mic-monopoly indicator on pinned sender card (filed 2026-05-19 by Tiberius 🌑, session `4e724860`)

**Filing context**: Path δ ratified by Rick 2026-05-19 via `ask_multiple_choice` (~10-min decision window) during Roscoe 🤠's Node D pre-flight recon. The cascade Section D Q-D3 designed a mic-monopoly visual cue (`data-mic-monopoly="true"` on pinned card → CSS pulsing overlay), assuming the data would arrive via `conversation_mode_changed` payload field `mic_monopoly`. Recon-D2 confirmed at code-write that no such field exists server-side AND no legacy `notifications.js` precedent exists for a separate mic-monopoly indicator. Genuine cascade-design gap. Deferred to preserve Phase 6c "multiplexer client-side port only" scope (which Q-C2 escalation already reinforced).

**System-wide-semantic question to resolve BEFORE designing the indicator**:
- What does "this session monopolizes the mic" mean as a system concept?
- Possible answers:
  - (a) TTS engine has the mic dedicated to this session (engine-state derived)
  - (b) Conversation-mode active + currently-speaking (cross-signal derivation)
  - (c) User has explicitly pinned the mic to this sender (different concept entirely)

**Once semantic ratified, decide wire path**:
- (α) Server-add `mic_monopoly: bool` to existing `conversation_mode_changed` payload (CoSA submodule edit, additive)
- (β) Separate `mic_monopoly_changed` notification.type (server-side scope expansion + new emission cadence)
- (γ) Client-derive in multiplexer from `conversation_mode_active + TTS-playing-signal` (strict client-side, semantic-drift risk)

**Files to amend when indicator lands** (per Phase 6c synthesis + execution plan):
- [ ] **[LUPIN]** `src/fastapi_app/static/js/multiplexer/shared/types.ts` — add `mic_monopoly: boolean` to `SenderRecord` (path α or β only; γ uses a derived value)
- [ ] **[LUPIN]** `src/fastapi_app/static/js/multiplexer/render/ConversationModePinRenderer.ts` — add `data-mic-monopoly="true"` attribute writing on pinned card; integrate into lastPinned-tracking across dual-emission window
- [ ] **[LUPIN]** `src/fastapi_app/static/css/multiplexer/conversation-mode-pin.css` — add `.sender-card[data-mic-monopoly="true"]` (pulsing mic icon overlay) + combination `[data-pinned-conv-mode="true"][data-mic-monopoly="true"]` (glow + pulse) selectors
- [ ] **[LUPIN]** `src/tests/unit/multiplexer/stores/sender_store_conversation_mode.test.ts` — restore AC-D3 #5 + #6 (mic_monopoly payload extraction) tests
- [ ] **[LUPIN]** `src/tests/unit/multiplexer/render/conversation_mode_pin_renderer.test.ts` — add mic-monopoly attribute lifecycle tests
- [ ] **[LUPIN]** `src/tests/smoke/test_multiplexer_phase6c_smoke.py` — add `mic_monopoly` smoke case back to AC-D10
- [ ] **[LUPIN-COSA]** (if path α/β chosen) `src/cosa/rest/routers/notifications.py` (or wherever `conversation_mode_changed` originates) — add the wire field or emit the new notification.type. Handle in CoSA-context session per `feedback_lupin_only_never_cosa`.

**Cross-refs**:
- Synthesis: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/11-phase6c-cascade-synthesis.md` §3.D
- Execution plan: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/12-phase6c-execution-plan.md` §3.D (shows deferred bits)
- Parent design: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md` Cluster D Q-D3

**Not blocking Phase 6c** — Section D ships with pin-glow + focus-flash mechanics; mic-monopoly indicator is purely additive.

---

## ✅ DONE 2026-05-17 AM — history.md archive (resolved both deferred priority-1 entries from 2026-05-15 and 2026-05-16)

**Executed by**: Tiberius 🌑 (session `2d916480`) at 2026-05-17 ~17:10 EDT, per Rick's voice approval ("affirmative Tiberius let's go ahead and archive the history before anything else") after reviewing the top-5 queues.

**Pre-archive health**: 41,266 tokens / 165.1% of 25k / 🚨 CRITICAL (4x deferred archive over two sessions — María's 2026-05-15 PM deferral + 2026-05-16 PM deferral).
**Post-archive health**: 9,854 tokens / 39.4% / ✅ HEALTHY.
**Reduction**: 31,413 tokens moved to archive (76% reduction).
**Archive file**: `history/2026-05-12-to-15-history.md` (4 days, 25 sessions).
**Retention**: 2026-05-16 only (1 day, 5 sessions — Checkpoint 5 MCP discovery / Model-server carve-out / Daily LoC Delta / doc-viewer 404 fix / voice persona stale-bridge fix).
**Boundary rationale**: token-based fallback (canonical workflow Priority 4) — 5-day retention minimum infeasible at this density.
**Index updated**: `history/README.md` row added; counts bumped 22→23 archives, 384→409 sessions; last-updated date flipped to 2026-05-17.

---

## 🚀 NEW — Model-server carve-out follow-ups (filed 2026-05-16 by Rio ⚡, session `0025f917`)

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md). Phases 0-3 + 3.6 + Part 2 bounce + Phase 5.1 smoke test all shipped this session. Verified end-to-end (9/9 smoke green; native browser ASR working). Doom-loop layers 1 + 3 structurally killed.

### Phase 4 — Compute-side cleanup (next session)

- [ ] **[LUPIN]** Strip `deploy.resources.reservations.devices` blocks from `lupin-rest-dev` + `lupin-rest-test` in `docker-compose.yml` — compute no longer needs GPU now that all 3 models live on `:7998`.
- [ ] **[LUPIN]** Add `depends_on: lupin-model-server: condition: service_healthy` to both compute services so compose-up enforces the dependency order.
- [ ] **[LUPIN]** Drop the 3 model pre-download `RUN python -c "snapshot_download..."` lines at `docker/lupin/Dockerfile:208-210` — they're no longer used (compute doesn't load models).
- [ ] **[LUPIN]** Rebuild compute image as candidate `lupin:1.0.0-noasr` (per `feedback_no_auto_promote_tags` — never auto-promote). Expected size drop ~4 GB (31.7 GB → ~27.7 GB).
- [ ] **[LUPIN]** Smoke-test the candidate; only Rick promotes `1.0.0-noasr` → `1.0.0` after verification.

### Phase 5 — Test coverage + unit tests — ✅ DONE 2026-05-17 (Tiberius 🌑, session `225e5b2d`)

**Closure doc**: [`src/rnd/v0.1.7/2026.05.16-model-server-carveout/92-phase5-closure.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/92-phase5-closure.md)
**Plan doc**: [`src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md)
**Audit doc**: [`src/rnd/v0.1.7/2026.05.16-model-server-carveout/91-phase5-smoke-audit.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/91-phase5-smoke-audit.md)

- [x] **[LUPIN]** `src/tests/unit/test_speech_to_text_provider.py` — 47 tests, 100% line+branch on `speech_to_text_provider.py`
- [x] **[LUPIN]** `fake_model_server_client` fixture in `src/tests/conftest.py` (named Fake* per parent design; opt-in not autouse so existing tests unaffected) + paired singleton-reset fixtures
- [x] **[LUPIN]** 100% on 2 new files (`speech_to_text_provider.py`, `lupin_model_server/main.py`); carveout-scoped on 3 modified files (`embedding_provider.py`, `routers/speech.py`, `fastapi_app/main.py`) per Q9 hybrid ratification
- [x] **[LUPIN]** Smoke-test audit — both existing tests (`test_embedding_api_smoke.py`, `test_model_server_smoke.py`) carveout-compatible already, no retrofit needed

### Phase 6 — Container preflight extension (next session)

- [ ] **[LUPIN]** Extend `src/tests/smoke/test_container_preflight.py` to assert `lupin-model-server` is in `docker ps` + healthy + bind-mounts present.
- [ ] **[LUPIN]** Extend `src/scripts/preflight-test-container.sh` to curl-probe `:7998/health` via the docker network.

### Phase 7 — Documentation touchpoints (next session)

- [ ] **[LUPIN]** Add a row to `CLAUDE.md` DOCUMENTATION TOUCHPOINTS for `src/lupin_model_server/` → links to `01-design.md` + `90-baseline-metrics.md`.
- [ ] **[LUPIN]** Add `docker restart lupin-model-server` recovery command to `CLAUDE.md` COMMANDS section (rare; full reload triggers ~10 s model re-load).
- [ ] **[LUPIN]** Update `~/.claude/skills/server-lifecycle/SKILL.md` — new subsection on bouncing `lupin-model-server` (shared between dev + test, transcribe/embeddings 503 during ~10-second reload window, NOT auto-bounced by AI).

### Phase 8 — Push (next session)

- [ ] **[LUPIN]** Push the checkpoint commit from this session to remote when Rick says go. Currently committed but NOT pushed per Rick's instruction.

### Cross-refs

- Auth design refinement section in `01-design.md` overrides the original R2 ratification (`ck_internal_*` retired in favor of reusing `notification-api-claude-code-dev`'s `ck_live_*` per María's brief + Rick's call).
- Two memory updates this session: new `feedback_lupin_models_always_gpu_0`; expanded scope on `feedback_100pct_coverage_multiplexer` from multiplexer-only to Lupin-wide.

---

## 🐛 NEW — Commons DM thread fragmentation via topic-case mismatch (filed 2026-05-16 by María 🌸, session `3c9fce51`)

**Filed by**: María 🌸 (Lupin session `3c9fce51`), surfaced during cross-session DM coordination with Tiberius 🌑 on 2026-05-16. Rick voice-confirmed worth filing.

**Severity**: Not lethal — DMs still deliver via push-mode persona resolution (server-side, case-insensitive). But the topic-FILE name is case-sensitive, so the asker and recipient end up reading two different topic files for what's logically one thread. Looks "quieter" than it is in the broadcast UI.

**Reproducer**: From session A, call `commons_send_to(recipient="Tiberius", body="...")`. The wrapper at `src/lupin_mcp/cosa_voice_mcp.py:2194` constructs `target_topic = f"dm-{recipient}"` literally — yielding `dm-Tiberius` (capital T). Tiberius's outbound DMs to María land on `dm-maria` (lowercase, his choice). Result: outbound traffic from María lives on `dm-Tiberius`, inbound from Tiberius lives on `dm-maria`. Two case-variant topics, not one canonical thread.

**Proposed fix** (5 LOC at `src/lupin_mcp/cosa_voice_mcp.py:2194`):

```python
# BEFORE
target_topic = topic or f"dm-{recipient}"

# AFTER (normalize to lowercase for topic-file consistency)
target_topic = topic or f"dm-{recipient.lower()}"
```

Doesn't change the recipient-resolution path — server-side persona match is already case-insensitive. Only normalizes the topic-file name.

- [ ] **[LUPIN]** Apply the lowercase normalization fix in `commons_send_to` wrapper
- [ ] **[LUPIN]** Add a unit test asserting `commons_send_to(recipient="Tiberius", ...)` and `commons_send_to(recipient="tiberius", ...)` write to the same topic
- [ ] **[LUPIN]** Consider migration: rename any existing `dm-{Capitalized}` topic files to lowercase, OR add a backward-compat read that union-merges case variants on `commons_read`
- [ ] **[Sub-bug CONFIRMED 2026-05-17T00:22Z]** Write-level message truncation observed on `commons_post` to `dm-maria` at 2026-05-17T00:18:31Z. Tiberius authored a ~4000-char reply with 5 Q&A sections; the entry on disk (`io/commons/dm-maria.md`, 34,542 bytes total) genuinely ends at "Substantive answers to your 5 questions, ranked by impact:" with NO body below — confirmed via direct `cat` inspection, not just via `commons_read`. Three hypotheses ranked: (a) bounce mid-write killed the MCP subprocess between header flush and body write — most likely given timing coincides with architecture switchover broadcast; (b) fastmcp transport-layer truncation at write time; (c) silent `CommonsStore.post()` body-length cap. Distinct from the system-reminder push-injection truncation Tiberius hypothesized (which is a SEPARATE failure mode worth documenting in MCP instructions as a "#7" — see his suggestion in his 00:20:55Z follow-up). **Investigation needed**: instrument `CommonsStore.post()` for body-length warnings; add a write-side size-limit test; possibly add a retry-on-partial-write to the wrapper. File as standalone TODO entry once Tiberius re-sends his feedback and we recover the lost content.

**Cross-refs**: 2026-05-16 fix-arc commit `f4e0370` (F1-F5) didn't touch the topic-name construction. R&D doc at `src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md` covers adjacent commons_* infrastructure.

---

## 📦 NEW — CoSA-side commit pending: Daily LoC Delta tool (filed 2026-05-16 by María 🌸, session `3c9fce51`)

**Primary doc**: [`src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md`](src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md) — status 🟢 **SHIPPED** — Reduced PIP review + post-ship docs iteration both ratified.

**User-facing README**: [`src/cosa/repo/git_loc_delta/README.md`](src/cosa/repo/git_loc_delta/README.md) — comprehensive scenarios (Use Case A: daily end-of-session ritual; Use Case B: pre-PR summary) + CLI reference + architecture + reuse map + edge cases + future enhancements.

**What's done**:
- 8 new source files under `src/cosa/repo/git_loc_delta/` (analyzer, parser, aggregator, csv_writer, formatter, exceptions, init, README)
- `src/cosa/repo/run_git_loc_delta.py` CLI entry
- 4 unit tests in `src/tests/unit/test_git_loc_delta.py` (parent Lupin)
- Post-ship: filename default flipped to mode-aware — `--branch` mode → `{repo}-{branch-slug}-loc-delta.csv` (stable per-branch, daily-overwrite-friendly); `--today` / explicit → date-stamped (archival)

All test tiers green:

| Tier | Result |
|---|---|
| T1 py_compile (9 files) | ✅ 9/9 OK |
| T2 import chain | ✅ resolved |
| T3 unit tests | ✅ 4/4 passed |
| T4 quick_smoke_test | ✅ 7/7 ✓ |
| T5 live CLI (today / --branch / --output csv) | ✅ all 3 modes verified on both Lupin + CoSA repos |

**Pending CoSA-context commit** — per `feedback_lupin_only_never_cosa`, the CoSA submodule pieces wait for a CoSA-context session:

- [ ] **[LUPIN-COSA]** Commit in a CoSA-context session: `src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md` + `src/cosa/repo/git_loc_delta/` (8 files including README.md) + `src/cosa/repo/run_git_loc_delta.py`. Suggested commit message: `[COSA] Add git_loc_delta sibling — per-day LoC analysis via git log --numstat`
- [ ] **[LUPIN]** Commit `src/tests/unit/test_git_loc_delta.py` (4 tests) + `TODO.md` (this entry) from a Lupin-context session — these live in the parent repo.

**Live verification artifacts** (current branch outputs):
- `io/git-loc-delta/lupin-wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe-loc-delta.csv` — 118 rows, 21 days, 216 commits, +147,999 / −13,171 net +134,828
- `io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` — 34 rows, 17 days, 69 commits, +12,561 / −3,272 net +9,289
- `io/git-loc-delta/2026-05-16-loc-delta.csv` — earlier date-stamped run (pre-filename-flip); can be deleted

---

## ✅ 🟢 FIX SHIPPED 2026-05-16 — Duplicate notification fan-out (filed by Rio ⚡ session `0025f917`; fixed by María 🌸 session `3c9fce51`)

**Fix R&D**: [`src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md`](src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md) — full diagnosis, fix shape, test coverage, and remaining write-side investigation flagged.

**Original filing context**: [`src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md`](src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md) — "Log-only — Bug #2" section.

**Root cause**: `CommonsActivityWatcher._tick()` was dispatching one `commons_activity` WS event per row read from the `broadcasts` / `broadcast-acks` topics. `perform_fanout` writes N per-recipient rows by design (for `target_session_id`-scoped routing). The HTTP read path `/api/commons/broadcast-history` already dedupes via `_dedupe_broadcasts_by_id` + `_dedupe_broadcast_acks_by_recipient`. The WS push path bypassed both — producer/consumer asymmetry.

**Fix**: Mirror the HTTP-path dedupes inside `CommonsActivityWatcher._tick()` between sort and dispatch. New `_dedupe_for_dispatch` helper. Cursor advancement fixed to use pre-dedupe max ts so dropped duplicates don't re-surface next tick.

**Verification (Tier T1–T4 green; T5 pending Rick's live confirmation)**:

| Tier | Result |
|---|---|
| py_compile (2 files) | ✅ OK |
| import chain | ✅ resolved |
| Targeted unit (22 watcher tests: 15 pre-existing + 7 new) | ✅ **22/22 PASS** in 0.07s |
| Full commons regression (438 tests) | ✅ **438/438 PASS** in 14.80s, **0 regressions** |
| Live :7999 broadcast smoke test | ⏳ Pending Rick's hands-on confirmation when back from snack |

**Pending Rick's EOD batch commit** (per `feedback_lupin_only_never_cosa`, the CoSA-side edit can't commit from this Lupin-context session):

- [ ] **[LUPIN-COSA]** Commit `src/cosa/rest/commons_activity_watcher.py` (added `_dedupe_for_dispatch` method ~80 LOC + tick() integration ~15 LOC). **Rick claimed EOD ownership 2026-05-16 for CoSA commits.** Suggested commit message in the R&D doc.
- [x] **[LUPIN]** `src/tests/unit/commons/test_commons_activity_watcher.py` (+170 LOC for 7 new tests) — parent Lupin, commits from a Lupin-context session.
- [x] **[LUPIN]** `src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md` (new R&D doc) — parent Lupin.

**Not-fixed-yet follow-ups** (logged in R&D §"Not-fixed-yet"):

- [ ] **[LUPIN-COSA]** Investigate the underlying write-side broadcast-acks multiplicity (Arnold's note at `_dedupe_broadcast_acks_by_recipient` docstring) — N `_post_ack` calls per single user-action. Consumer-side dedupe masks the symptom; producer-side root cause remains.
- [ ] **[LUPIN]** Investigate the completion-cards persona stamping asymmetry (4×Mr-Radio + 1×Rio for a single completion). Suggests something about recipient-side persona resolution in multi-session-same-user scenarios.

---

## ✅ DONE 2026-05-15 PM — Inter-Session DM Phase 0 implementation (María 🌸, session `3b6be6f9`)

**Primary doc**: [`src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md`](src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md) — 18 sections covering Phase 0 design, gap analysis (corrected post-Rick-feedback), REUSE pass with file:line citations, Pass 1 Fitness with 20 ACs, threats considered, Phase 0 ratification log, Testing Ownership Mandate compliance.

**Delivered**: All 8 implementation steps + 28 net-new tests + 3 retries on `:8000`. After Rick's "ultrathink" challenge corrected the parallel-mechanism scope to a Phase 3 extension, scope shrunk from ~480 LOC + 4-6 sessions to ~210 LOC + 1 session.

- [x] **[LUPIN] Phase 0 design + 4 Q-decisions ratified** — sequential walk via `ask_multiple_choice`: Q1-rev (extend `commons_ask_async` + thin `commons_send_to` wrapper), Q2-rev (fire-and-forget dispatch), Q3-rev (both addressing modes + rich `RecipientResolutionError` 422 contract per Rick's amendment), Q4-rev (same broadcasts topic + DM badge).
- [x] **[LUPIN] REUSE + Pass 1 Fitness folded** — 12 F-findings verified with file:line; 20 ACs derived (AC9 expanded to AC9a-g + AC10-AC14 after Rick flagged testing under-spec); 10 threats walked, 8 inherit Phase 3 mitigations, 2 new have explicit paths.
- [x] **[LUPIN] Steps 1+2+5** — `RegisterQuestionRequest` + new `RecipientResolutionError` Pydantic; `_resolve_dm_recipient` + `_dispatch_commons_question_received` helpers; `execute_register_question` extension + route handler wiring; `valid_types` += `"commons_question_received"`. (CoSA submodule — separate commit pending in CoSA-context session.)
- [x] **[LUPIN] Step 3** — `_register_push_mode` rich-dict return; `ask_async` recipient kwargs + metadata stamping; MCP `commons_ask_async` extended; new `commons_send_to` `@mcp.tool` wrapper. (`src/lupin_mcp/commons_ask.py` + `src/lupin_mcp/cosa_voice_mcp.py`.)
- [x] **[LUPIN] Step 4** — `commons_question_received` action branch + `_handle_commons_question_received` helper with `COMMONS PEER MESSAGE` framing + T7 isolation try/except.
- [x] **[LUPIN] Step 6** — DM badge in `_renderCommonsEntry`; `.commons-activity-dm-badge` CSS pill.
- [x] **[LUPIN] Step 7** — Test pyramid: 16 unit + 7 endpoint smoke + 5 listener smoke + 5 `:8000` integration + 3 Playwright E2E + 1 visual regression baseline (`io/test-suite/visual-baselines/test_dm_recent_activity/`). Final tally: **488/488 PASS across :7999 and :8000**.
- [x] **[LUPIN] Step 8** — INI keys — no-op for v1 (existing Phase 3 keys `commons api base url` + `commons ask async push mode enabled` cover what's needed).
- [x] **[LUPIN] Commits** — `9bbf298` (Phase 0 main implementation, 12 files, +1840/-53), `98ab544` (:8000 integration test, AC9d), `8e9e144` (Playwright E2E + visual baseline, AC9e + AC9f).
- [x] **[LUPIN-COSA] CoSA-side commit** — `src/cosa/rest/routers/commons.py` + `src/cosa/rest/routers/notifications.py` (~250 LOC) including the T7-isolation `match_persona` try/except bug fix discovered during `:8000` integration retry-3. **Rick voice-claimed ownership 2026-05-16: "I'll do that at the end of the day today."** Removed from María's priority queue per Rick's request 2026-05-16 (María session `3c9fce51`).
- [ ] **[LUPIN] PHI-4 LLM disambiguator wiring** (v1.1 follow-on) — currently the T7 try/except routes any LLM failure to 422 RecipientResolutionError. v1.1 enhancement: actually USE PHI-4 when reachable so fuzzy persona match works (e.g. "the bug-fix one" → "tiberius"). Phase 3 Q5 precedent (Haiku stubbed) suggests acceptable scope deferral.

**Reproducibility recipe** (post-CoSA-commit): María calls `commons_send_to(recipient="radio", body="...")` → Radio's tmux receives `COMMONS PEER MESSAGE` system-reminder → Radio replies via `commons_post('dm-radio', body=<reply>, metadata={'in_reply_to': <question_id>})` → María's Phase-3 watcher pushes back via `commons_answer_received`. Rick watches both in Recent Activity with `→ @radio` and `→ @maria` DM badges.

---

## ✅ DONE 2026-05-15 PM — `doc_scope` registry exposure for cosa-voice consumption (Rio ⚡, session `c1cbcd11`)

**Lupin-side work delivered via doc-viewer scope unification** (`src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md`). The original ask was a 4-field `doc_scope` dict on `get_session_info()`; Q-R2 ratification collapsed it to a single `project_name: str` field. Lupin's deliverable shrank accordingly:

- [x] **[LUPIN] Decide registry exposure mechanism** — chose Option 1 (HTTP endpoint) per Q-R1-A. Ratified during interactive Pass 1 review on 2026-05-15.
- [x] **[LUPIN] Implement `GET /api/docs/scopes`** — admin endpoint shipped in Phase 3 of doc-viewer scope unification. JWT-auth via `get_current_user`. Payload shape: `{scopes: List[{name, root, allowed_prefixes, allowed_root_files, extra_blocklist, source}]}` where `source` is `"manifest"` (when `.docview.yml` present) or `"ini-only"`. Live-verified on `:7999`.
- [x] **[LUPIN] Update `_scope_registry.py`** — registered scopes now uniform; built-in `docs`/`io` retired by Phase 4a (per Q1-D). Every scope is a regular registry entry.
- [ ] **[external — Rachel's cosa-voice session]** Wire `project_name: str` into cosa-voice's `get_session_info()` response. Out of scope for this plan; Rachel owns. Coordination handoff: cross-link `planning-is-prompting/src/rnd/2026.05.14-doc-link-scope-cross-repo.md` with the unification design.
- [x] **[LUPIN] Add smoke test** — `GET /api/docs/scopes` live-tested during Phase 3; returns all currently-registered repos including `lupin` (now manifest-sourced).

**URL shape post-migration**: `/app/docs?path=<project>/<rel>` — `scope=` query param retired (Q-R2). Rachel's MCP exposes `project_name`, not a 4-field dict.

---

## 📡 NEW — Writer-side follow-up: `owner_user_id` stamper (filed 2026-05-14 by María, session f6f865fb)

**Primary doc**: `src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md` (Option C ratified by Rick; CoSA-side filter migration landed; writer-side pending separate Lupin session).

**Context**: Broadcast UI showed only 1 of 4 personas because the listener was stamping the SERVICE-ACCOUNT user_id (`claude.code@lupin.deepily.ai`) instead of the human owner's. CoSA filter now reads a new `owner_user_id` field with graceful-degradation fallback (all 4 personas visible immediately; isolation tightens once writer lands).

- [ ] **[LUPIN] Decide owner-resolution mechanism** — recommended: env vars `LUPIN_OWNER_EMAIL` + `LUPIN_OWNER_PASSWORD` (mirrors existing listener-creds pattern). Alternatives: `~/.claude/lupin-owner.json` config file, or a `/auth/whoami-for-bridge` endpoint.
- [ ] **[LUPIN] Add `set_owner_user_id`** in `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` — mirrors existing `set_user_id` with read-modify-write field preservation.
- [ ] **[LUPIN] Add `_stamp_owner_user_id_on_bridge`** in `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — same pattern as the existing `_stamp_user_id_on_bridge` but uses HUMAN owner's credentials, called once at listener startup immediately after the existing stamp.
- [ ] **[LUPIN] Investigate §6 secondary mystery** — Rachel's listener log says her `user_id` WAS stamped but the on-disk bridge has no key. Probably a post-stamp SessionStart/`/clear` hook overwriting without field-preservation. Could clobber `owner_user_id` too if not fixed.
- [ ] **[LUPIN] Schedule `:8000` integration run** before merging both legs — verify `test_broadcast_two_session_e2e.py` passes and the live broadcast UI shows all 4 personas once writer lands.

**Independence note**: The CoSA-side change is safe to merge independently because the graceful-degradation branch handles bridges without `owner_user_id`. No coordination required between the two repos' merges.

---

## 💰 NEW — Bounded ClaudeCodeJob migration audit & plan (filed 2026-05-13 by Tiberius, session 66d534ab)

**Primary doc**: `src/rnd/v0.1.7/2026.05.13-bounded-cc-migration-audit-and-plan.md` (status: awaiting Rick's ratification on D1-D9 decision matrix)

- [ ] **[LUPIN] Ratify D1-D9 decision matrix** — 9 decisions with full pros/cons/flip-conditions/recommendations. Each migration phase (Podcast → Presentation → Deep Research per my recommendation) opens as a separate R&D doc once ratification lands.
- [ ] **[LUPIN] Phase 1 — Podcast Generator migration to bounded CC** — gated on D1 ratification. ~1 session estimated. Open as `src/rnd/v0.1.7/2026.05.13-podcast-bounded-cc/` once authorized.
- [ ] **[LUPIN] Phase 2 — Presentation Generator migration to bounded CC** — gated on Phase 1 closure + D6 (strict parser strategy).
- [ ] **[LUPIN] Phase 3 — Deep Research migration to bounded CC** — gated on Phase 2 closure + D3 (preserve progress events) + max_turns cap tuning.
- [ ] **[LUPIN] Optional 30-day Anthropic console pull** (10-min user task) — could flip D1 to Deep-Research-first if `spend_deep_research >> spend_podcast + spend_presentation`. Doc captures the model.

**Decision matrix at a glance** (full body in the doc):
- D1: Phase order (Podcast first vs Deep Research first) — recommend Podcast first
- D2: `scheduled_at` default (post-midnight) — recommend YES
- D3: Deep Research progress events (preserve via tool-use vs simplify) — recommend preserve
- D4: OpenAI sites (defer or eliminate) — recommend defer (out of scope)
- D5: Runtime Argument Expeditor (defer with trigger vs permanent stay) — recommend defer with revisit trigger
- D6: Output parser (strict/lenient/hybrid) — recommend per-migration (lenient Podcast, strict Presentation+DR)
- D7: Pool concurrency limit — recommend keep current values
- D8: `cost_usd` telemetry — recommend keep with "telemetry only" UI disclaimer
- D9: Migration marker convention — recommend `__init__.py` banner pattern

**Awaiting**: Rick reads the doc, ratifies D1-D9 en masse OR flips specific decisions. No code touches until then.

---

## ✅ DONE 2026-05-15 — history.md archive (Mr. Radio, session 23ff8512)

- [x] **[LUPIN] Archived history.md** — was 27,657 tokens / 110.6% of 25k (🚨 OVER LIMIT, 4x deferred). Cut at clean date boundary line 619/620: kept 2026.05.12-2026.05.14 in main file (13,151 tokens / 52.6% / ✅ HEALTHY); archived 2026.05.07-2026.05.12-AM as `history/2026-05-07-to-11-history.md` (14,506 tokens, 12 sessions). Banner + README index + quick stats all refreshed.

---

## 🐛 Inter-Session Commons follow-on (filed 2026-05-13 PM by Maria 🌸)

- [ ] **[LUPIN] Host-side stale-bridge sweeper daemon** (Option 2 from `src/rnd/v0.1.7/2026.05.13-broadcast-stale-bridge-phantom.md`) — once-per-hour scan of `~/.claude/sessions/cc-*.json` that deletes bridges whose host PID is dead. Tightens the activity-threshold-vs-phantom trade-off so the `commons broadcast active session threshold seconds` INI key could safely return to a shorter value. ~30-50 LOC + systemd timer or shell hook + tests.

---

## ✅ Inter-Session Commons broadcast-UI arc — FULLY CLOSED 2026-05-13 PM (Maria 🌸, session b28069a6)

12 commits today across Phase 3 + broadcast-UI bug fixes + UI iteration + Playwright test repair. End-to-end working: 5 active sessions detected, voice-first mic input wired, compose-row layout matches CC-session button refs.

- [x] **[LUPIN] Inter-Session Commons Phase 3 Steps 3-9 barrel-through** — 7 commits `27b82f1` → `ac5c4aa`. CommonsQuestionWatcher + commons_xml_models + LLM disambiguator (PHI-4 wired, Haiku stubbed per Q5) + register-question router endpoints + ask_async push-mode wiring + listener `commons_answer_received` branch + final test pyramid + lifespan wiring. **398/398 tests** green on :7999, **7/7 integration tests** green on :8000 (AC15).
- [x] **[LUPIN] Broadcast UI "no active sessions" bug** — `4cb5fe1` Option 1 graceful filter + `93b302d` Option 2 listener stamps `user_id` on bridge at startup. Diagnosis at `src/rnd/v0.1.7/2026.05.13-broadcast-ui-no-active-sessions-bug.md`.
- [x] **[LUPIN] Broadcast UI phantom dead-bridge** — `2dff191`. `_bridge_last_activity_epoch` falls back to `idle_detection.last_interaction_at`; `commons broadcast active session threshold seconds` bumped 600 → 28800 for dev-workday idle. Diagnosis at `src/rnd/v0.1.7/2026.05.13-broadcast-stale-bridge-phantom.md`.
- [x] **[LUPIN] Broadcast panel UX iteration** — 4 commits: `54c8e05` relocation above focus bar + mic, `26874fb` compose-row redesign, `300b3c0` button sizes match cc-session refs + status/aggregate artifact divs removed, `8771c33` Playwright tests repaired + 6 new compose-row tests.
- [x] **[LUPIN] Playwright broadcast E2E coverage refresh** — `8771c33`. 5 retired (preview + aggregate DOM gone), 6 new (mic-sized, send-sized, compose-row order, retired-divs-gone, panel-in-accordion, confirm-modal-XSS). Live :8000 verified: **11/11 PASSED**.
- [ ] **[LUPIN-COSA] CoSA-side commits pending** — `src/cosa/rest/routers/commons.py` (Option 1 graceful filter + stale-bridge filter), `src/cosa/rest/commons_question_watcher.py` (NEW), `src/cosa/rest/routers/notifications.py` (valid_types += "commons_answer_received"). Handle in a CoSA-context session per `feedback_lupin_only_never_cosa`.

---

## ✅ TTS preview-and-pause — IMPLEMENTED 2026-05-13 PM (Arnold)

- [x] **[LUPIN] Broadcast munger mode + JS wiring** — `multimodal text broadcast` + 20 smoke cases passing. Wired to broadcast accordion mic via `recordingMode="broadcast"`. CoSA-side commits (multimodal_munger.py) pending in a separate CoSA-context session.
- [x] **[LUPIN] TTS preview-and-pause feature** — sentence splitter + queue evolution + auto-pause + remainder resume + bubble-controls fix. INI plumbing through `/api/config/client`. Live-verified by Rick. CoSA-side commit (system.py) pending separately.
- [ ] **[LUPIN-COSA] Commit CoSA-side TTS preview + broadcast munger edits** — 2 files in `src/cosa/`: `rest/multimodal_munger.py` (broadcast mode + smoke tests), `rest/routers/system.py` (config endpoint extension). Handle in a CoSA-context session per `feedback_lupin_only_never_cosa`.

---

## 🟡 Multiplexer Phase 6c Q-decisions queue — built, awaiting Rick's pull trigger (filed 2026-05-13 PM by Rio ⚡, session `9fae8c74`)

**Status**: 15 questions queued across Clusters B, C, D. Cluster A already ratified 5/5 on 2026-05-12. Rick is working interstitially and wants to pull questions on his cadence — he'll say "next" / "ready" / "fire" and I deliver one at a time. No forced pace.

**Primary doc**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md`

### Queue contents

**Cluster B — Focus tray + focus-mode toggle (5 Qs)**:
- [ ] Q-B1 — Mount surface (`#focus-tray` placement in `multiplexer.html`)
- [ ] Q-B2 — Focus-mode toggle UI (single button vs per-card vs keyboard shortcut)
- [ ] Q-B3 — Focus-target selection (couple to conv-mode pin vs click-to-focus)
- [ ] Q-B4 — Tray contents + click-to-refocus behavior
- [ ] Q-B5 — Flash-on-focus-change animation

**Cluster C — Sender-card audio recorder (6 Qs)**:
- [ ] Q-C1 — Mount placement (`.cc-voice-input` in card footer)
- [ ] Q-C2 — `MediaRecorder` MIME type (opus default vs feature-detect chain)
- [ ] Q-C3 — Recording state machine (idle → recording → processing → ready → sent)
- [ ] Q-C4 — STT pipeline target endpoint
- [ ] Q-C5 — Send-button POST payload shape
- [ ] Q-C6 — Per-sender concurrency (single active recorder guard)

**Cluster D — Conversation-mode UI pin (4 Qs)**:
- [ ] Q-D1 — Where pin state lives (`SenderRecord` field vs DOM-only)
- [ ] Q-D2 — Top-of-list pinning mechanism (reducer sort vs `insertBefore`)
- [ ] Q-D3 — Mic-monopoly indicator wiring
- [ ] Q-D4 — Multi-sender conversation-mode race (single-pin invariant)

### Resume protocol

Trigger phrases (any of these advance the queue): "next", "next question", "ready", "fire", "give me the next". Other controls: "skip" (defer current, advance), "back up" (revisit last), "pause" (bookmark), "TOC" / "where are we" (position check).

Each delivered question must include: proposed answer + alternatives walked + per-option pros/cons + recommendation with flip-condition (per `feedback_always_include_pros_cons_recommendation`). TTS body = headline + takeaway only; pros/cons + flip-condition go in `abstract` (per `feedback_tts_body_headline_and_takeaway_only`).

### Phase 6c predecessor closure

Phase 6b CLOSED 2026-05-12 (Rachel 🕊️, session `56ee76d6`). All 22 ACs green; c8 100% on 9 TS files; boot gz = 34,647 B (5,029 B headroom under AC7 ceiling). See `97-phase6b-closure.md`.

---

## ✅ Multimodal munger — `munge_text_punctuation` strips periods + commas from prose (filed 2026-05-13 by Arnold)

- [x] ~~**[LUPIN-COSA] Prose-mode period-stripping bug at `src/cosa/rest/multimodal_munger.py:757`**~~ → **RESOLVED 2026-05-13 by Arnold** (collateral fix while resolving a related broadcast-munger issue). User-confirmed complete via voice 2026-05-13.

---

## 🚧 UNDERWAY — Inter-Session Commons Phase 3 Steps 3-9 implementation barrel-through (paused 2026-05-12 PM, session 6a054460 → resumed)

**Primary doc**: `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md` (status: 🟢 APPROVED FOR CODE-WRITE)

### Where we are (Step 3 CLOSED, Step 4 next)

**Completed in 2026-05-12 PM session**:
- ✅ All 4 plan-review passes (Pass 0 + REUSE + Pass 1 Fitness + Pass 2 Adversarial) — 20 ACs (AC1-AC15 Pass 1 + AC16-AC20 Pass 2 tests), 10 new INI keys, NEW §6 Testing Ownership Mandate, NEW §8 PHI-4 prompt envelope, Pydantic-native validation retrofit
- ✅ Status flipped to **APPROVED FOR CODE-WRITE** by Rick
- ✅ Step 1 — Q1 refactor pre-flight: `commons_topic_watcher.py` (base) + refactored `commons_ack_watcher.py` (subclass keeps Phase 2 public API). py_compile + import-chain clean. **26/26 ack-watcher tests GREEN** (AC8 gate satisfied).
- ✅ Step 2 — 10 INI keys + 10 paired splainer entries land in `lupin-app.ini` + `lupin-app-splainer.ini`. ConfigurationManager.get() resolves 10/10 with correct types.

**Completed in 2026-05-13 AM session (Maria 🌸)**:
- ✅ Step 3 — `src/cosa/rest/commons_question_watcher.py` (NEW, 354 LOC incl. docstrings; ~155 LOC pure code) subclassing `CommonsTopicWatcher`. `_InFlightQuestion` plain-data record (`topic`, `user_id`, `inject_fn`, `last_seen_ts` ISO string, `expires_at_monotonic`); `register_question` with T3 per-user + global caps + T9 collision + T4 cursor stamping; `unregister_question` with T5 uniform `QuestionNotFound`; `tick()` + `_tick_one_question` with T1 validate + T1 `_dispatched_by_question` idempotency + T6 lock-guarded lookup + T8 inject_fn isolation; override `_prune_expired_locked` to clear dispatched_by_question (memory hygiene); per-question `last_seen_ts` cursor (F3-fit). **Test file at `src/tests/unit/commons/test_commons_question_watcher.py` (43 tests).** Coverage: **100% lines + branches + functions** on the new module (124 stmts / 38 branches / 0 missing). Full commons suite regression: **254 tests, 0 failures (14.16s)**.
- ✅ Step 4 — `src/lupin_mcp/commons_xml_models.py` (NEW) + `src/tests/unit/commons/test_commons_xml_models.py` (NEW, 35 tests). PersonaInfo (BaseModel, server-side persona registry — no T2 needed); PersonaDisambiguationRequest (BaseXMLModel with `List[PersonaInfo]` + Pydantic Field constraints on `ambiguous_reference` / `context` + `@field_validator(mode="before")` for T2 sanitize-at-boundary — rejects control chars, XML-escapes `<` `>` `&`; **overrides `to_xml()`** to produce PHI-4-friendly nested-persona shape because xmltodict.unparse mishandles `List[PersonaInfo]`); PersonaDisambiguationResponse (Optional matched_persona with empty-tag → None coercion + Field-constrained confidence in [0.0, 1.0]). Coverage: **100% lines + branches** (45 stmts / 10 branches / 0 missing). 35/35 tests PASSED (0.22s).
- ✅ Step 5 — `src/lupin_mcp/commons_llm_disambiguator.py` (NEW) + `src/tests/unit/commons/test_commons_llm_disambiguator.py` (NEW, 23 tests). `CommonsLlmDisambiguator(config_mgr)` class using `LlmClientFactory.get_client(spec_key)` + BaseXMLModel round-trip + T2 active_personas whitelist + F5-fit confidence floor + T7 audit log (`commons llm disambiguator log decisions` INI-toggleable). PHI-4 errors (TimeoutError / XMLParsingError / ValidationError / ValueError) route to `_fallback_via_haiku()` which raises NotImplementedError per AC7 wired-but-stubbed → outer catches → returns None. Lazy LLM-client construction for testability. Coverage: **100% lines + branches** (63 stmts / 10 branches / 0 missing). **Also wired `src/lupin_mcp/commons_persona_matcher.py`**: added `configure_llm_disambiguator(d)` setter for main.py lifespan injection + extended `disambiguate_via_llm()` to convert string candidates → PersonaInfo and dispatch through the singleton when set; Phase 1 stub behavior preserved when singleton is None. Matcher test file +4 wiring tests; matcher module coverage stays at **100%** (24 stmts / 12 branches / 0 missing). Full commons regression after Step 5: **316 tests, 0 failures (14.51s)**.
- ✅ Step 6 — `src/cosa/rest/routers/commons.py` (MOD, CoSA-side): extended `init_commons_state()` to accept `question_watcher: Optional[CommonsQuestionWatcher]` (Phase 2 callers unaffected); NEW `RegisterQuestionRequest(BaseModel)` per AC1 with Pydantic Field constraints (topic + question_id regex `^[A-Za-z0-9_-]+$` + length 1-64, asker_session_id length 1-128, ttl_seconds 1-604800 default 3600); NEW pure-logic helpers `make_question_inject_fn` (builds the closure pushing `user_initiated_message` with `title="action:commons_answer_received"` per Q3 framing), `execute_register_question` (T3 cap → 429, T9 collision → 409, success → 201), `execute_unregister_question` (T5 uniform 404 for unknown OR wrong-owner); NEW route handlers `POST /api/commons/register-question` (201/422/409/429) and `DELETE /api/commons/register-question/{question_id}` (204/422/404) with `require_api_key_or_jwt` auth dep + `Path(..., pattern=...)` validation on the path param. NEW `_require_question_watcher()` gate (503 until Step 9 lifespan wires the singleton). Tests at `src/tests/unit/commons/test_commons_router.py` (+21 tests for Pydantic shape, inject_fn payload, execute_register/unregister happy/collision/cap/T5) + `test_commons_ac14_registration.py` (+4 AC14 route-registration smokes for POST + DELETE + method assertions). Coverage on routers/commons.py: **100% lines + branches** (157 stmts / 40 branches / 0 missing). Full commons regression after Step 6: **337 tests, 0 failures (14.54s)**.
- ✅ Step 7 — `src/lupin_mcp/commons_ask.py` (MOD): ask_async() now accepts optional push-mode kwargs (push_mode_enabled, api_base_url, auth_header, ttl_seconds, register_timeout_s, debug) per F1-fit / F2-fit / AC5. NEW `_register_push_mode()` helper fires `POST {base_url}/api/commons/register-question` with `json={topic, question_id, asker_session_id, ttl_seconds}` + auth headers + timeout; returns True on 2xx, False on non-2xx OR network error OR ImportError (silent fallback to polling-mode). Return shape now includes `push_mode_active: bool`. `ask_sync()` untouched per F10-fit. Phase 1 polling contract preserved when push-mode is disabled or fails. Tests at `src/tests/unit/commons/test_commons_ask.py` (+8 push-mode tests: default disabled, missing-url skip, missing-auth skip, success 2xx, non-2xx 409 fallback, network error fallback, trailing-slash url normalization, ImportError fallback). Coverage: **100% lines + branches** (52 stmts / 12 branches / 0 missing). Full commons regression after Step 7: **345 tests, 0 failures (14.51s)**.
- ✅ Step 8 — `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (MOD): 4th `elif action == "commons_answer_received"` branch in `_handle_action()` + NEW `_handle_commons_answer_received(notification)` method reads stamped `payload.persona_name` per F9-fit immutability (NOT a live lookup); builds Q3-framed body `"COMMONS PEER REPLY (question_id X, from @PersonaName):\n\n[body]"` wrapped in `<system-reminder>...</system-reminder>`; injects via `_inject_via_tmux(wrapped, wrap=False)`. Missing-question_id guard logs + returns without injecting (defense against malformed notifications). Missing-persona defaults to `@unknown` per F9-fit (no live lookup fallback). MODIFY `src/cosa/rest/routers/notifications.py` valid_types L359-362: added `"commons_answer_received"` alongside `commons_broadcast_ack` per AC10. Tests at `src/tests/smoke/test_cc_notification_listener.py` (+4 commons_answer_received tests: full payload + Q3 framing + wrap=False; missing question_id; missing persona defaults; no payload). Also FIXED a stale test from the 2026-05-12 speakerphone refactor (`exit_conversation_mode` action was renamed to `disable_speakerphone`). Full regression after Step 8: **387 tests, 0 failures (14.74s)** across commons unit + listener smoke.
- ✅ Step 9 — Final pyramid + lifespan: NEW `src/tests/smoke/test_ask_async_push_e2e.py` (AC13 TestClient in-process, 11 tests covering 201/409/422/422-missing/204/404/422-malformed-path + full register-tick-dispatch happy path + unregister-prevents-dispatch + AC17-style 429 cap-hit). NEW `src/tests/integration/test_commons_ask_async_push_integration.py` (AC15 scheduled-only :8000 file, 7 tests covering live-server round-trip of POST 201/409/422 + DELETE 204/404/422 + auth-required; skipif on credential env vars; submit via `POST /api/test-suite/submit` with `test_types=integration`, `pytest_args=-k test_commons_ask_async_push`, `auto_fix_on_failure=False`). MODIFY `src/fastapi_app/main.py` lifespan at L527+: extends Phase 2 commons singletons block with `CommonsQuestionWatcher` construction (reads `commons question tracker ttl/per-user-max/global-max` INI keys) + `.start()` + `init_commons_state(..., question_watcher=...)` + Phase 3 `configure_llm_disambiguator(CommonsLlmDisambiguator(config_mgr))` + matching shutdown stop. Full :7999 pyramid I can execute: py_compile + import chain + unit + smoke + listener smoke = **398 tests, 0 failures (14.83s)**. AC15 :8000 integration execution remains scheduled-only per `feedback_test_server_monopolize_mode` — awaiting user slot confirmation.

### Required next-session sequence (resume here, in order)

**Step 3** — `src/cosa/rest/commons_question_watcher.py` (NEW, ~150 LOC) — the load-bearing module:
- `_InFlightQuestion` dataclass: `user_id`, `last_seen_ts`, `inject_fn`, `expires_at_monotonic`
- `register_question(qid, uid, ttl, inject_fn, last_seen_ts=time.time())` — calls base `_register()` after T3 cap checks (per-user + global)
- `_dispatched_set: Set[Tuple[str, str]]` for T1 idempotency (cleared on `_unregister`)
- `_initialize_last_seen_ts()` — subclass impl (reads the registered topic's last entry)
- `tick()` — for each registered question, polls topic since `question.last_seen_ts`; for each new entry validates `in_reply_to` per T1 (`isinstance` + `TOPIC_RE.match` + `len ≤ 64`); checks `(qid, entry_id) not in _dispatched_set` for T1 idempotency; T6 lookup-under-lock; **dispatch inject_fn OUTSIDE lock** with T8 try-except wrap
- Custom `CapExceededError` exception for T3 429 translation
- Plus unit tests in `src/tests/unit/commons/test_commons_question_watcher.py` covering AC16 (T1 idempotency), AC17 (T3 caps), AC18 (T4 cursor), AC19 (T6 concurrency), AC20 (T8 inject_fn failure)

**Step 4** — `src/lupin_mcp/commons_xml_models.py` (NEW, ~80 LOC) — PersonaInfo + PersonaDisambiguationRequest (with `Field` + `@field_validator` for T2 sanitization) + PersonaDisambiguationResponse (with `Field(ge=0, le=1)` on confidence). Per §8 envelope. Plus unit tests.

**Step 5** — `src/lupin_mcp/commons_llm_disambiguator.py` (NEW, ~120 LOC) — `disambiguate()` using `LlmClientFactory.get_client(spec_key)` + BaseXMLModel round-trip + confidence-floor thresholding + T2 whitelist + T7 decision audit log. Stubbed Haiku fallback raises `NotImplementedError`. Plus unit tests with mocked LlmClientFactory.

**Step 6** — `src/cosa/rest/routers/commons.py` (+80 LOC) — `RegisterQuestionRequest(BaseModel)` with Pydantic Field constraints; `POST /api/commons/register-question` and `DELETE /api/commons/register-question/{question_id}` endpoints with auth dep, T3 cap checks (429), T5 uniform 404 body, lock-guard via watcher methods. AC14 router-registration smoke.

**Step 7** — `src/lupin_mcp/commons_ask.py` (+30 LOC) — `ask_async()` reads `commons api base url` from INI; fires `POST /api/commons/register-question` when push-mode enabled; try-except + warning log + polling fallback on failure (F1-fit). `ask_sync()` untouched per F10-fit.

**Step 8** — `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (+40 LOC) — 4th `elif action == "commons_answer_received"` branch + `_handle_commons_answer_received()` reading stamped `persona_name` from answer entry (F9-fit), building `COMMONS PEER REPLY` body, injecting via `_inject_via_tmux(wrap=False)`. Extend `valid_types` in `routers/notifications.py:359-362`.

**Step 9** — Final pyramid + lifespan: AC13 TestClient smoke in `src/tests/smoke/test_ask_async_push_e2e.py`; extend `main.py:527+` lifespan to instantiate + start `CommonsQuestionWatcher`; AC15 integration E2E file `src/tests/integration/test_commons_ask_async_push_integration.py` (schedulable via `/api/test-suite/submit`). **Run full pyramid + report tabular pass/fail per tier** per §6 Testing Ownership Mandate.

### Testing Ownership Mandate (mandatory at every step)

Per CLAUDE.local.md §"USER IS NEVER A TESTER" + design doc §6:

The AI runs every tier at each step appropriate to that step. Tabular pass/fail reporting before declaring any step "done". User is never asked to verify or run tests. Tier-1 (`py_compile` + import-chain + unit) and Tier-2 (`:7999` smoke + router-registration) are AI-discretionary. Tier-3 (`:8000` integration E2E, AC15) requires user slot-confirmation per `feedback_test_server_monopolize_mode` — the user-ask is slot availability, NOT budget approval, NOT tester-duty deferral.

### Standing memories that apply (mandatory)

- `feedback_approved_sequences_execute_end_to_end` — once Steps 3-9 barrel-through begins, do not re-ask between sub-steps
- `feedback_pydantic_native_validation` — all body validation declared via Pydantic Field + field_validator, never hand-rolled if/raise
- `feedback_recraft_speech_dont_pipe_terminal` — TTS message = headlines + verdict only; details in abstract
- `feedback_lupin_only_never_cosa` — code edits in `src/cosa/` are fine; git ops there are forbidden from parent context
- `feedback_never_auto_commit_push` — wait for explicit "commit" / "push" per change

### File-location cheatsheet

| Purpose | Path |
|---|---|
| Phase 3 design doc | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md` |
| Phase 3 doc-set index | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` |
| Base watcher (Step 1 ✅) | `src/cosa/rest/commons_topic_watcher.py` |
| Ack subclass (Step 1 ✅) | `src/cosa/rest/commons_ack_watcher.py` |
| INI keys (Step 2 ✅) | `src/conf/lupin-app.ini` + `lupin-app-splainer.ini` (search for "Phase 3 (push-mode") |
| Question watcher (Step 3) | `src/cosa/rest/commons_question_watcher.py` (NEW) |
| XML models (Step 4) | `src/lupin_mcp/commons_xml_models.py` (NEW) |
| Disambiguator (Step 5) | `src/lupin_mcp/commons_llm_disambiguator.py` (NEW) |
| Router endpoints (Step 6) | `src/cosa/rest/routers/commons.py` (MODIFY) |
| MCP ask_async (Step 7) | `src/lupin_mcp/commons_ask.py` (MODIFY) |
| Listener wiring (Step 8) | `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (MODIFY) + `src/cosa/rest/routers/notifications.py:359-362` |
| Lifespan (Step 9) | `src/fastapi_app/main.py:527+` (MODIFY) |
| Smoke test (Step 9 / AC13) | `src/tests/smoke/test_ask_async_push_e2e.py` (NEW) |
| Integration test (Step 9 / AC15) | `src/tests/integration/test_commons_ask_async_push_integration.py` (NEW) |

---

## 🚧 UNDERWAY — Multiplexer Phase 6c (persona modal + focus tray + audio recorder + conversation-mode UI pin)

**Resume pointer**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md`

### Where we are

Phase 6b is **CLOSED** (commits `118ed10` Phases 5A+5B; `e324e6c` Phases 6+7+8+closure + `97-phase6b-closure.md`). Phase 6c (persona modal + focus tray + audio recorder + conversation-mode UI pin) **design phase opened today** and Cluster A is fully ratified.

### Cluster A — CLOSED 2026-05-12 (5/5 ratified)

| Q | Decision |
|---|---|
| Q-A1 | Trigger = `.sender-persona-badge` chip embedded in sender card |
| Q-A2 | Modal = HTML Popover API; `popover="auto"` mode; chip carries `popovertarget` (declarative wiring) |
| Q-A3 | Close affordances = ESC + outside-click (built-in) + explicit × button |
| Q-A4 | Persona color = subtle thin top accent + tinted name text; body neutral |
| Q-A5 | Borrowed display = `(borrowed)` label only; attribution deferred (server has no `original_owner` field) |

### Remaining Q-decisions for Phase 6c design phase

- [ ] **Cluster B — Focus tray** (Q-B1..Q-B5) — mount surface, toggle UI, focus-target selection (couples to Cluster D), tray contents, flash animation
- [ ] **Cluster C — Audio recorder** (Q-C1..Q-C6) — mount placement, MediaRecorder MIME, state machine, STT endpoint, Send payload, concurrency
- [ ] **Cluster D — Conversation-mode UI pin** (Q-D1..Q-D4) — pin state location (store vs DOM), top-of-list mechanism, mic-monopoly indicator, multi-sender race

### After Q-decisions close

1. REUSE pre-pass (catalog reusable patterns from Phases 5/6a/6b)
2. Pass 1 Fitness review
3. Pass 2 Adversarial review
4. Code-execution plan
5. Implementation

Per `feedback_pip_plan_review_is_sequential` — no auto-progression between gates.

### Follow-on filed during Cluster A walk

- [ ] **[LUPIN-COSA]** Server-side extension: add `original_owner` field to `ServerVoicePersona` payload (`cosa/rest/voice_persona_helpers.py:borrowed_persona_for_sid`). When that lands, Phase 6c popover swaps `(borrowed)` → `(borrowed from {name})`. Not blocking Phase 6c.

### TTS format rule learned this session

Spoken `notify(message=…)` / `ask_multiple_choice(question=…)` body is **headline + one-sentence recommendation only**. Detail (pros/cons, flip-conditions, file paths, inventory) goes in `abstract`. Filed as `feedback_tts_body_headline_and_takeaway_only.md`. Rick told me twice during the Q-A walk; sticks now.

---

## ✅ Speakerphone (solo/chorus) — MINIMUM-VIABLE CLOSED 2026-05-13 (Arnold 🪨, session 6d663b6c)

**Resume pointer**: `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/00-index.md`

**Decision (2026-05-13)**: Per `97-phase7-execution-log.md` §7 recommendation, Phase 7 minimum-viable scope IS the close. Speakerphone solo/chorus framework is live and tested. Phase 7b (toggle widget migration) and Phase 8 (chorus UX polish) are filed as separate follow-on tickets below.

### Final phase ledger

| Phase | Status | Commit | Notes |
|---|---|---|---|
| 1 — INI key + helper | ✅ Committed | `c82ee04` | — |
| 2 + 3 — Bridge rename + server router | ✅ Committed | `8a8c31c` | CoSA-side edits in same logical change, committed separately by Rick |
| 4 — MCP tool rename + `_notify_impl` mode-conditional | ✅ Committed | `9ba4db5` | — |
| 5 — Hook layer renames (function names only) | ✅ Committed | `e17d7d7` | — |
| 5b — 4-variant rider matrix + brevity migration | ✅ Committed | `b6f1ac2` | 4-variant `_speakerphone_reminder_body(source, mode, speakerphone_on)`. Brevity + routing rules migrated from `~/.claude/CLAUDE.md` into rider. |
| 6 — CLAUDE.md migration + skill retire | ✅ Committed | `b6f1ac2` | `~/.claude/CLAUDE.md` slimmed 928→889 lines. `conversation-mode-guardrails` skill retired. Slash commands renamed. |
| 7 — Multiplexer rename + legacy notifications.js wire-fix | ✅ Committed | `b6f1ac2` | 3 multiplexer source files + 2 tests renamed; 100% c8 maintained. Legacy `notifications.js` Phase 3 wire-field regression fixed. |

**Test posture (at commit time)**: Python unit regression 4267 passed, 1 xfailed, 0 failures. Multiplexer 329/329 + c8 100/100/100/100 on touched files.

**Execution logs**: `95-phase5b-execution-log.md`, `96-phase6-execution-log.md`, `97-phase7-execution-log.md`.

### Follow-on tickets (not blocking close)

- [ ] **[LUPIN] Phase 7b — Multiplexer toggle widget migration** (separate ticket) — Migrate the 📞/🔔 toggle widget + monopoly-pin logic from legacy `notifications.js:9590-9736` into the multiplexer with mode-aware rendering, 100% c8 coverage. ~3 hours engineering + tests. Three components per `97-phase7-execution-log.md` §7: `SpeakerphoneToggle`, mode-aware affordances, localStorage + session-store getters. Toggle continues to function in legacy `notifications.js` in the meantime.

- [ ] **[LUPIN] Phase 8 — Chorus-mode UX color/glyph polish** ⏸️ **DEFERRED PER DESIGN** — `17-phase8-color-glyph-uxs-design.md` §2 explicitly requires 1-2 weeks of chorus-mode live use before scoping the (a)/(b)/(c) decision. Capture pain points in `03-open-questions.md` Q1 with timestamps during that window.

- [ ] **[LUPIN-COSA] Commit CoSA-side comment fixes from Phase 5b** — 3 files in `src/cosa/` (CoSA-context session only; not touched from parent Lupin context per `feedback_lupin_only_never_cosa`).

---

## 💰 LUPIN Cost Migration — three agents flagged for bounded-CC migration (2026-05-12)

**Empirical foundation**: `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md` confirms bounded ClaudeCodeJobs are zero per-token cost (covered by Max 200 plan). Console balance moved $0.00 across 10 probe jobs reporting $2.05 in `cost_usd` telemetry.

**Canonical policy**: `CLAUDE.md` § "COST MODEL — BOUNDED CC vs FIREWALLED SDK"
**Human-facing playbook**: `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md`
**Auto-memory rule**: `feedback_prefer_bounded_cc_over_anthropic_sdk.md`

**Three candidates** — each currently calls `AsyncAnthropic` via `ANTHROPIC_API_KEY_FIREWALLED` and is a structural fit for bounded CC (Anthropic-only, prompt-shaped, fits CC tool surface, async-batch-friendly):

- [ ] **[LUPIN] Migrate Deep Research agent (`src/cosa/agents/deep_research/`) to bounded CC** — largest current firewalled-account line-item; uses WebSearch + WebFetch natively (already in CC tool surface). Migration must default `scheduled_at` to post-midnight window per off-peak rule.

- [ ] **[LUPIN] Migrate podcast script-generation phase (`src/cosa/agents/podcast_generator/`) to bounded CC** — script phase only; audio TTS phase stays as-is. Multi-paragraph structured-text synthesis fits cleanly. Default `scheduled_at` post-midnight for non-interactive runs.

- [ ] **[LUPIN] Migrate presentation content-generation phase (`src/cosa/agents/presentation_generator/`) to bounded CC** — content/YAML phase only; pptx-assembly stays as-is. Default `scheduled_at` post-midnight.

**Migration playbook**: see `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md` § "Migration playbook" (8-step sequence: Q1–Q5 fit check → identify boundary → refactor invocation → drop firewalled-key dep → default scheduled_at → update user-facing doc → update agent banner → verify with console-balance check).

**Precedent**: BFE (`src/cosa/agents/bug_fix_expediter/`) and TFE (`src/cosa/agents/test_fix_expediter/`) — both already on bounded CC, use as code-shape reference.

**NOT migrating** (guardrails): `notification_proxy/strategies/llm_fallback.py` (high-QPS classifier) and `decision_proxy/` (latency-sensitive). Subprocess spawn overhead would break those budgets.

**Not blocking anything** — sequence pick-up after the speakerphone + commons items above settle.

---

## ✅ Inter-Session Commons Phase 3 — ALL 4 PLAN-REVIEW PASSES CLOSED 2026-05-12 PM (Tiberius 🌑, session 6a054460)

**Primary doc**: `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`

### State

- **Pass 0** ✅ — 8/8 Q-decisions ratified
- **REUSE pass** ✅ — 8 F-mappings + 4 new F-findings + 3 corrections applied
- **Pass 1 Fitness** ✅ — 13/13 findings ratified + Rick's AC15 amendment
- **Pydantic-native validation retrofit** ✅ — AC1/AC2/AC6 + §8 model use `Field` + `field_validator` declaratively (memory `feedback_pydantic_native_validation` saved)
- **Pass 2 Adversarial** ✅ — 8/8 threats T1-T8 ratified + apply phase
- **Final state**: 20 ACs (AC1-AC15 Pass 1 + AC16-AC20 Pass 2 tests), 10 new INI keys, 9 NEW files + 8 MODIFIED, NEW §6 Testing Ownership Mandate, NEW §8 PHI-4 prompt envelope, NEW Pass 2 ratifications table in §3.

### Next gate (when implementation begins)

Per CLAUDE.local.md §"THE USER IS NEVER A TESTER" + §6 Testing Ownership Mandate:

The AI executes the §6 test-pyramid tiers (`py_compile` → unit → smoke → router-registration → coverage gate → scheduled `:8000` integration E2E AC15) during + at closure of implementation. Tabular pass/fail reported per tier. The user is never asked to verify or run tests.

Implementation flow: §5 sequencing → 9 steps → at each step, the AI runs the appropriate tier → at all-steps-closure, AI runs full pyramid + reports tabular → user authorizes APPROVED FOR CODE-WRITE flip (which is really "approved for the next phase").

### Standing directive (mandatory)

Every multi-option `ask_multiple_choice` carries per-option pros + cons + a "My recommendation: X because Y" block in both spoken `question` and `abstract`, plus a "becomes correct if..." flip-condition. See memory `feedback_always_include_pros_cons_recommendation`.

---

## ✅ Inter-Session Commons Phase 2 — ALL CLOSED 2026-05-12 (session 6a054460 Tiberius 🌑, AM)

**Closure doc**: `src/rnd/v0.1.7/2026.05.09-inter-session-commons/92-phase2-closure.md`

Phase 2 is functionally complete. Phase 3 skeleton ready (see above). The original "FIRST THING NEXT SESSION" pointer below is retained as historical context.

---

## Historical resume pointer (kept for reference)

**Original pointer**: `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-phase2-execution-log.md` — steps 1-8 ✅ CLOSED, steps 9-13 ⏳ pending.

### Where we are

The Inter-Session Commons + User-Broadcast initiative landed Phase 1 (file-based commons MVP) yesterday and the Phase 2 plan-review pipeline (REUSE + Pass 1 Fitness + Pass 2 Adversarial) all closed earlier today. **Phase 2 backend implementation steps 1-8 ALL CLOSED** — the full user-broadcast surface is wired backend-side:

| Step | Artifact | Tests |
|---|---|---|
| 1 | `broadcasts` added to `RESERVED_TOPICS` in `commons_store.py` | parametric — existing test adapts |
| 2 | `src/cosa/rest/commons_rate_limiter.py` | 12 tests, 100% |
| 3 | `src/lupin_mcp/broadcast_handler.py` | 28 tests, 100% |
| 4 | `src/cosa/rest/commons_ack_watcher.py` | 26 tests, 100% |
| 5 | `src/cosa/rest/routers/commons.py` (2 endpoints) | 55 tests, 100% on pure-logic helpers |
| 6 | `cc_notification_listener._handle_action()` 3rd `elif` + `_handle_broadcast_received()` method | py_compile + import-chain clean (cross-process smoke deferred to step 9) |
| 7 | 2 new INI keys + paired splainer + `commons_broadcast_ack` registered in `notifications.py:359-362` `valid_types` | n/a |
| 8 | `main.py` lifespan wiring (startup + shutdown) + `app.include_router(commons.router)` + AC14 registration smoke | 5 tests pass |

**Aggregate: 211 tests, 100% lines + branches across 8 commons modules (622 stmts, 170 branches, 0 missing).**

### Steps remaining

- [x] **Step 9** — 2-session E2E smoke on `:7999` (`test_broadcast_two_session_e2e.py`). Closed 2026-05-12 — 1 test, 7 design-doc gates, 0.76s.
- [x] **Step 10** — UI panel: `broadcast-panel.js` + `broadcast-panel.css` + `notifications.html` insertion. Closed 2026-05-12.
- [x] **Step 11** — Playwright E2E on `:8000` (scheduled monopolize-mode). Closed 2026-05-12 — job_id `ts-436237f6`, 10 passed / 0 failed in 40.97s.
- [x] **Step 12** — Docs: NEW `src/docs/notification-types.md` + UPDATED `src/docs/rest-api-reference.md` §17c + UPDATED `src/docs/README.md`. Closed 2026-05-12.
- [x] **Step 13** — Phase 2 closure `92-phase2-closure.md` post-mortem. Closed 2026-05-12.

### What's ready to pick up tomorrow

1. **The backend is feature-complete.** All wiring is in place; the next session can immediately start step 9 (2-session E2E smoke) without re-deriving context.
2. **The design doc is APPROVED FOR CODE-WRITE** with all 14 ACs + 12 mitigations + sanitization ratified.
3. **No commit done this session** — Phase 2 steps 1-8 are uncommitted on disk per `feedback_never_auto_commit_push.md`. The work is preserved in `.claude-session.md`'s session `9a4a601d` touched-files manifest.

### Verification commands for next session

```bash
# Confirm steps 1-8 still pass
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ \
  --cov=lupin_mcp.commons_persona_matcher --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival --cov=lupin_mcp.commons_ask \
  --cov=lupin_mcp.broadcast_handler --cov=cosa.rest.commons_rate_limiter \
  --cov=cosa.rest.commons_ack_watcher --cov=cosa.rest.routers.commons \
  --cov-branch --cov-fail-under=100

# Should report: 211 passed; 100% lines + branches across 8 commons modules

# Also confirm Phase 1 smoke still passes (sanity)
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/smoke/test_commons_two_session_roundtrip.py -v
```

If both green, step 9 implementation can begin.

---

## 🚧 Phase 5b PARTIAL — CC Card Normalization (session 77e1bb27 Mr. Radio, 2026-05-11 PM)

User-authorized test-server bounce at 17:13 EDT → 3 batch-1 submissions fired sequentially → some skips suspected to be 401-cred-system fallout → 3 batch-2 submissions resubmitted at 17:59 EDT. Phase 6.8 parent commit remains gated on Phase 5b verdict.

### Batch 1 results (job_ids `ts-b37e982b`, `ts-5fea5f3c`, `ts-f5535947`)

- [x] [LUPIN] **5.8 — E2E functional** (`ts-b37e982b`, 17:16:48 → 17:18:35 EDT, 106.6s): ✅ **30 passed, 0 failed, 0 errors, 0 skipped** — AC11 GREEN. New `test_cc_card_renders_in_sibling_shape` runs clean; 2 obsolete tests deleted as planned.

- [⚠️] [LUPIN] **5.9 — E2E visual baseline regen** (`ts-5fea5f3c`, 17:31:48 → 17:32:40 EDT, 51.5s): 16 passed, 0 failed, **15 errors**, 0 skipped. The 15 "errors" are `pytest_playwright_visual_snapshot` teardown signals on `--update-snapshots` ("Snapshots updated. Please review images.") — **NOT real failures**. 15 baselines regenerated at `io/test-suite/visual-baselines/`:
  - CC-normalization-adjacent (3): `notifications.png`, `multiplexer_phase5_notifications_pane.png`, `multiplexer_phase6a_jobs_pane.png`
  - Auth/account (5): login, register, change-password, profile, landing
  - Admin (5): admin-dashboard, admin-snapshots, admin-users, admin-ratify, admin-trust
  - Dev/infra (2): dev-tools, ws_circuit_banner_open

- [x] ~~[LUPIN] **5.10 — Subscription smoke**~~ **RETIRED 2026-05-11 EVE.** Deep investigation surfaced: the `cost_usd == 0.0` premise is invalid. CC CLI always reports counterfactual API pricing as metadata regardless of which auth path actually paid for the call. With no `ANTHROPIC_API_KEY` present, Max OAuth is paying flat rate, but `total_cost_usd > 0` is still populated. Verified empirically on both host (~$0.32/call) and container (~$0.05/call). Test cannot pass on any valid CC CLI invocation. Module-level `pytest.mark.skip` added with full forensic trail in module docstring. The 4 architecture fixes applied during investigation (in-container detection, env-var URL routing, schema-drift cost extraction) are preserved as patterns for future CC-related smoke tests.

### Batch 2 in flight (resubmitted 17:59:16 EDT after user credential-system restoration)

- [ ] [LUPIN] **5.8 retry** (`ts-476c971a`, scheduled 18:01:16 EDT): identical to batch-1 5.8; sanity-check for credential-system regression. Expected: ✅ pass.

- [ ] [LUPIN] **5.9 regression** (`ts-99f2fa02`, scheduled 18:13:16 EDT): `-k visual` **WITHOUT** `--update-snapshots`. Verifies the 15 batch-1 regenerated baselines are self-consistent. Pass = 15 visual tests green against their freshly-written baselines. This closes AC11 by replacing the "manual git-diff inspection of `io/`" step with an automated self-regression check.

- [x] ~~[LUPIN] **5.10 retry**~~ — superseded by retirement above. AC10 closed-as-retired (premise invalid, no test we can make pass without changing the assertion).

### Phase 5b NET STATUS (post-retirement, 2026-05-11 EVE)

- 5.8 ✅ functional regression GREEN both batches
- 5.9 ✅ visual baselines regenerated + self-consistency confirmed (batch 2 `ts-99f2fa02` 16P/0F/0E/0S in 53.0s)
- 5.10 ✅ **RETIRED** (premise invalid — see retirement note above)

**Phase 6.8 parent commit is functionally unblocked on the CC card normalization scope.** 5.10's premise issue is pre-existing — exposed by, not caused by, this session's work.

### Follow-up filed

- [ ] [LUPIN] **TFE-to-CC design doc amendment** — `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md` should be amended to drop the "cost reduction via Max subscription" thesis OR pivot to a more verifiable invariant (e.g., "no `ANTHROPIC_API_KEY` in container env" — provable from `env | grep ANTHROPIC_API_KEY` returning empty). Defer to a follow-up session.

**Reference**: `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` Phase 5b table; report markdowns at `io/test-suite/2026.05.11-at-{17:18,17:32,17:46,18:01,18:13,18:25,19:47,19:57,20:06}-EDT-*-results.md`.

---

## ✅ DONE — Voice Persona Rename "Domi" → "Rio" (session 77e1bb27 Mr. Radio, 2026-05-11 PM)

**User directive**: name-only rename, preserve icon ⚡ / color `#880E4F` / profile "Young & energetic female" / voice_id `AZnzlk1XvdvUeBnXmlld`.

**Files edited** (4): `src/conf/lupin-app.ini` (5 lines), `src/conf/lupin-app-splainer.ini` (6 surgical edits sparing line 175 ElevenLabs catalog ref), `src/tests/unit/test_voice_persona_helpers.py` (7 hits replace_all), `src/tests/smoke/test_voice_persona_allocation.py` (2 hits replace_all). Plan doc `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` (orphaned by 68edb64b session-end) folded into this commit.

**Verification**: py_compile clean | unit 34/34 pass (0.08s) | smoke 7/7 pass (0.39s) | live `:7999` `GET /api/cosa-voice/voice-persona/pool` returns `Rio` with preserved attributes. No `:7999` bounce needed — pool query re-reads INI per request.

**Audit trail** preserved in splainer line 297 (`Renamed on 2026-05-11: Domi → Rio (label rotation only — ElevenLabs voice_id unchanged)`) and line 319 (`Renamed from 'Domi' on 2026-05-11 (label rotation only — voice_id, icon, color, and profile unchanged)`), mirroring the existing Nora→maria + Quentin→mr radio + Adam→Tiberius pattern.

**Mobile sub-repo** — deferred to mobile-context session per plan-handoff convention (parent never touches `src/lupin-mobile/` git). 4 mobile R&D docs reference "Domi" in cheat-sheets; they are frozen historical context and stay as-is.

---

## ✅ D1 RATIFIED — A-extended (2026-05-04 PM)

User ratified **Option A-extended** for D1 after investigating the legacy `/api/claude-code/ws/{task_id}` endpoint and finding it structurally defective. ClaudeCodeTransport is OUT OF SCOPE for Phase 3 + all subsequent multiplexer phases. The endpoint is queued for elimination — see `bug-fix-queue.md` "🔥 Top of Queue — IMMEDIATE" section. A future CC transport will be built only when UI surfaces a missing-functionality gap, against a properly authenticated endpoint.

**Audit trail**:
- Bug-fix-queue entry: `bug-fix-queue.md` "🔥 Top of Queue — IMMEDIATE" — 4 distinct bugs catalogued + suggested fix sequencing.
- Design doc amendment: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/04-phase3-transport-design.md` (top-of-doc banner).
- Execution log subsection: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` "Phase 3 — D1 Ratification Amendment".
- 11 file changes applied (2 deletions + 9 edits) over Phase 3 commit `703ab5a`; verification re-run with 122/122 unit tests + 12/12 smoke + tsc + ESLint + build all clean.

## ✅ Q12 RATIFIED — Single-tab application (2026-05-04 PM)

User ratified Q12 (added 2026-05-04 PM) during Phase 4 plan-review pipeline / D-G walkthrough. Multi-tab support is OUT OF SCOPE for the multiplexer; users wanting two views open a second window of the same tab. Sidesteps Phase 4 Q4 cross-tab BroadcastChannel question entirely. See `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` Q12 for the policy + rationale.

## ✅ Q2 OPTION C RATIFIED — P1 server-replay deferred (2026-05-04 PM)

During Phase 4 implementation kick-off, the design doc's pre-implementation prerequisite verifications surfaced that **server-side event replay on `auth_success` is NOT implemented** (`src/cosa/rest/routers/websocket.py:467-472` sends `auth_success` and falls straight into the receive loop; `websocket_manager.py` has no buffer/replay mechanism). Per design doc Q2 ratification this was a hard blocker requiring escalation.

User decision via `ask_multiple_choice` (verbatim voice response): **"Yeah option C sounds good just as long as it's properly documented and added as a post phase for follow-up."**

**What ships in Phase 4**: NotificationStore implements Q2 Option A as ratified (unread-count-only persistence with `schemaVersion: 1` envelope + 250ms tail debounce). Active list starts empty on construct; populated by live `notification_received` events from `auth_success` onward. Reload loses in-flight active notifications until a new event arrives.

**Audit trail**:
- Execution log: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` § "Pre-implementation prerequisite verifications" P1 row + § "P1 escalation + resolution"
- Design doc Q2 ratification text remains valid; the "server replay" assertion is amended in the execution log resolution section

### Post-Phase-4 follow-up — promote to Option A or B if dogfooding signals jarring reload UX

**Defer until**: after Phase 4 implementation lands AND dogfooding produces reload-UX feedback. If reload's "no notifications until next event" gap feels jarring, evaluate:

**Option A — Build server-side replay** (CoSA edit):
- [ ] [LUPIN-COSA] Add bounded recent-event buffer in `src/cosa/rest/websocket_manager.py` (per-user deque, e.g., 50 most recent events with TTL)
- [ ] [LUPIN-COSA] Flush buffered events to socket immediately after `auth_success` in `src/cosa/rest/routers/websocket.py` queue endpoint (lines 467-472 area)
- [ ] [LUPIN-COSA] Verify replay does not duplicate live events for clients that were never disconnected (idempotency by `id_hash` on the consumer side already handles this)
- [ ] [LUPIN] NotificationStore unit test: verify replay frames are reduced as normal (`changeKind: "added"` per `id_hash`); no special-casing required client-side
- [ ] [LUPIN] Phase 4 smoke test extended: assert active list rebuilds within 1s of `auth_success` after reload

**Option B — Pivot Q2 to full-list persistence** (no CoSA edit):
- [ ] [LUPIN] Extend NotificationStore persistence envelope schema (bump to `schemaVersion: 2`) to carry `{count, lastSeenTs, activeList: Notification[]}`
- [ ] [LUPIN] Add migration path from v1 → v2 (v1 envelopes get `activeList: []`; storage_corrupt fires on unknown future versions)
- [ ] [LUPIN] Tail-debounce active list writes too (active list churn could be larger than count churn)
- [ ] [LUPIN] Storage-volume audit: estimate worst-case envelope size against typical browser quota
- [ ] [LUPIN] NotificationStore unit tests: verify hydration from persisted active list; verify schema-migration path

**Triggering signal** (decision point): if user reports "I lost notifications on reload" during Phase 4-9 dogfooding, evaluate both options. Otherwise, accept the gap permanently — Option C stands.

### Phase 2 broadcast.ts cleanup — separate commit follow-up

**Where it lives**: `src/fastapi_app/static/js/multiplexer/shared/broadcast.ts` (53 LOC) + `src/tests/unit/multiplexer/broadcast.test.ts` (8 unit tests). Header comment of broadcast.ts already updated 2026-05-04 PM with the "INERT IN PRODUCTION per Q12" note.

**What's needed**: Phase 2 spine bundle is closed; ripping out broadcast.ts retroactively touches an approved phase boundary, so it ships as its own focused cleanup commit (not folded into the Phase 4 ratification commit).

**Suggested cleanup**:
- [ ] [LUPIN] Delete `src/fastapi_app/static/js/multiplexer/shared/broadcast.ts` + `src/tests/unit/multiplexer/broadcast.test.ts`
- [ ] [LUPIN] Delete `BROADCAST_WHITELIST` constant + any `LupinEventType` union entries that exist solely for cross-tab whitelist references (per Phase 2 design doc DC4 — those entries currently exist in `shared/types.ts` for whitelist type-checking only)
- [ ] [LUPIN] Update `02-phase1-scaffolding-design.md` + `03-phase2-foundation-design.md` with post-implementation amendment banners noting Q12 invalidates the broadcast.ts file row + AC8 cross-tab two-instance roundtrip test (mirror the D1 amendment banner pattern from Phase 3)
- [ ] [LUPIN] Re-run Phase 1+2+3+4 verification suites; expected unit-test count drops by 8 (broadcast tests gone)
- [ ] [LUPIN] Update execution log with cleanup section

**Defer until**: after Phase 4 implementation lands (avoids interleaving Phase 4 review/implementation with Phase 2 retroactive surgery).

### D2 [NON-BLOCKING] Inspect the QueueTransport auth-failure bug fix

**Where it lives**: `src/fastapi_app/static/js/multiplexer/transport/QueueTransport.ts` `onSocketOpen` catch block (look for the long-form comment starting "Auth failed (token fetch, refresh failure, etc.)"); rationale captured in 90-execution-log.md Phase 3 § "Implementation deviations" #4.

**What was caught**: Initial implementation called `wsChannel.stop()` in the catch path, but did NOT notify the CSM. Because `wsChannel.stop()` nulls handlers BEFORE closing, the wsChannel's onClose callback never fired, so the CSM stayed stuck in `connected` while the channel was dead — a real reconnect-orchestration bug.

**Fix**: catch block now ALSO sends `{type: "socket_close"}` to the CSM. Surfaced via the unit test `auth getToken() failure → socket stops; CSM enters backoff`.

**Action**: glance at the diff if you want to confirm the fix is the right shape; not blocking Phase 4.

---

Last updated: 2026-05-11 PM (Session 6d544991 Arnold — `ask_yes_no()` Neither affordance landed end-to-end; CoSA commit pending in separate context per cross-sub-project handoff. Prior session-end @ 6e8a6a03 Rachel — CC card normalization Phase 0 + plan-review closure all 3 passes; Phase 1 implementation parked READY TO BEGIN.)

---

## 🪦 CC DISPATCH RETIREMENT — Follow-ups (Session 1a8900ee, 2026-05-05)

The 6-endpoint legacy `/api/claude-code/dispatch` cluster was retired today. Two parity gaps and one mobile dependency surfaced as deliberate-disable visible artifacts.

- [ ] [LUPIN-COSA] **Restore Claude Code INTERACTIVE controls on the cj-flow path.** When `ClaudeCodeJob` (`src/cosa/agents/claude_code/job.py`) gains `inject(message)` / `interrupt()` / `end_session()` methods (with corresponding REST endpoints on `claude_code_queue.py`), un-disable the four UI stubs in `notifications.html` (the `#cc-inject-btn`/`#cc-interrupt-btn`/`#cc-end-btn`/`#cc-inject-input` elements inside `.cc-retired-banner`), restore JS handlers that POST to the new endpoints, restore the `INTERACTIVE` option in `#cc-task-type`, and update the two `test_job_dispatch.py` test docstrings (currently noted as existence-only checks). See plan: `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md`.

- [ ] [LUPIN-COSA] **Per-turn streaming on the cj-flow path** (optional follow-up). The legacy WS streamed `text` / `tool_use` / `tool_result` per turn. The cj-flow path currently emits only coarse start/complete/fail notifications. If user-facing demand surfaces, add per-turn `notify_progress` calls inside `ClaudeCodeJob._execute()` keyed by job_id, and update the dispatcher card's `#cc-response` panel (currently a retirement banner) to consume them. Not blocking; the queue path is functional without per-turn streaming.

- [x] [LUPIN-MOBILE] **Migrate `claude_code_repository.dart` off the retired endpoints.** — ✅ **VERIFIED COMPLETE 2026-05-11** (user-requested verification). Mobile production code at `src/lupin-mobile/lib/features/claude_code/data/claude_code_repository.dart:19` already POSTs to canonical `/api/claude-code/submit`; header comments L5 + L11 confirm "Canonical successor: POST /api/claude-code/submit (this file)". Q8 verdict = PRIMARY (alias `/queue/submit` live through v0.1.8 release cycle). Cross-ref handoff doc: `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md`. (UX decision for disabled INTERACTIVE controls + BLoC/repository test updates happen in the mobile session if/when needed — not blocking the canonical endpoint cutover.)

- [x] [LUPIN] **Live UI probe (manual gate).** ~~Open `/app/notifications`...~~ **RESOLVED 2026-05-11** (session 658ea35d, Mr. Radio) via CC Card Normalization Phase 5a — superseded by the normalization work which (a) deleted the `.cc-retired-banner` block + disabled inject/interrupt/end inputs entirely from the HTML, (b) renamed submit URL to canonical `/api/claude-code/submit` with `/queue/submit` alias preserved for one release cycle, and (c) verified end-to-end via 5.4/5.5 live JWT POSTs (both return `cc-{uuid8}` jobs) + 5.6 6/6 dry-run smoke + 5.11 TFE/BFE regression GREEN. The "manual" label was legacy metadata — Phase 5.7 was an AI-headless probe per test-ownership mandate. See `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` Phase 5a.

---

## 🧩 MULTIPLEXER FOLLOW-UPS (Session 658ea35d, 2026-05-11)

- [ ] [LUPIN] **Multiplexer R&D consumer notice: CC card normalization landed 2026-05-11**. The notifications-page CC card was reshaped to sibling shape (form + submit + status div; no response panel, no inject controls, no session-info row). `JobsPaneRenderer.ts` is unchanged — it's agent-agnostic via `metadata.agent_type` (`stores/JobStore.ts:215`) and CC jobs continue to render uniformly. **Phase 6b visual baseline impact**: if Phase 6b touches CC card screenshots, expect to regenerate baselines (parent already scheduled Phase 5.9 to regen Lupin-side baselines). Full context: handoff doc at `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md`. Q8 verdict = PRIMARY (alias live for one release cycle).

---

## 🪞 MCP SELF-INTROSPECTION FOLLOW-UPS (Session 2622c356, 2026-05-05 PM)

Surfaced when user called Claude "Maria" (the assigned voice persona name). Claude had no programmatic way to know its own persona — `get_session_info()` returns session metadata but no persona field. Two related extensions filed; first one IMPLEMENTED, second still pending.

### Pending

- [x] [LUPIN-MCP] **Add a "neither" / "discuss-further" option to cosa-voice `ask_yes_no()`** — ✅ **LANDED Session 6d544991 (Arnold, 2026-05-11 PM)**. Third button labelled **Neither** wired end-to-end: HTML render (notifications.js), CSS neutral gray (notifications.css), regex extension (CoSA notification_utils.py — staged for CoSA-context commit), `format_qualified_response` "neither" branch with explicit re-frame directive, MCP tool docstring updated, 4 new unit tests in test_stop_hook.py (12/12 green), 3 notification-api.md rows + 1 CLAUDE.md row. R&D doc set at `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/` (00-index, 01-design with Pass 1 Fitness + Pass 2 Adversarial inline, 02-handoff-summary, 90-execution-log). **Current session won't see docstring change** — fresh CC session required (MCP stdio subprocess restart). See ☀️ FIRST THING NEXT SESSION below for the CoSA-context commit followup.

- [x] [LUPIN-COSA OR LUPIN] **Investigate explicit conversation-mode-exit notification to MCP client.** — **RESOLVED Session 05da2b39 (2026-05-05 PM, checkpoint).** Confirmed the gap experimentally + via code audit: the displace path (Session B activates → A's listener gets `action:exit_conversation_mode` push → tmux-injected `<system-reminder>`) was fully wired and worked. The self-exit path (UI toggle / MCP `exit_conversation_mode()` / voice phrase / slash) was NOT — the router's `else:` branch only flipped the bridge and broadcast a `conversation_mode_changed` UI event, never pushing the listener-targeted action. Result: model retained the contract from prior `<system-reminder>` blocks until they scrolled out. **Fix shipped**: (a) Lupin — `conv_mode_exit_reminder()` body made reason-agnostic in `hook_common.py`. (b) CoSA — symmetric self-exit action push added to `conversation_mode.py` router (mirror of displace branch's per-session push). (c) Tests updated: `test_deactivate_pushes_ui_sync_and_self_action` + `test_body_announces_deactivation`. Auto-tier verification 100% green (3950 unit + 13 router + 41 wrap + 10 MCP + 50 WS smoke). Design + execution log: `src/rnd/v0.1.7/2026.05.05-conv-mode-self-exit-signal-gap/`. Cross-repo handoff: Lupin commit done in checkpoint; CoSA commit pending in separate context. Manual live verification deferred (would disrupt active conv-mode dialogue — surfaces naturally on next user-initiated off→on cycle).

### What landed (this session)

- ✅ **`voice_persona` added to `get_session_info()` MCP response** — implemented in `src/lupin_mcp/cosa_voice_mcp.py` (Lupin parent, not CoSA submodule as I'd initially scoped — the cosa-voice MCP server source actually lives in Lupin parent under `src/lupin_mcp/`). 5-line addition to the bridge-metadata branch at line 1289+: reads `cc_meta.get("voice_persona")` from the same session bridge that the existing `conversation_mode_active` lookup uses (None if Phase 4.5 hook allocation failed; server falls back to "Sam" for TTS). Docstring updated to list the new field. `py_compile` clean.
- ✅ **Voice Persona Self-Announcement (Phase A.5) protocol added to MCP server instructions** — appended to the `mcp = FastMCP(instructions=...)` field at line 605+. Instructs Claude to send a TTS greeting by persona `display_name` at session start: time-of-day-appropriate greeting + display_name + brief duty announcement (e.g. "Good morning, Maria reporting for duty, setting things up."). Skips if `voice_persona` is None. Fires once per Phase A startup including after /clear (persona persists across /clear).

### Activation requirement

Both changes are SERVER-SIDE in the cosa-voice MCP server source. They require the **MCP server process to be restarted** before they take effect:

- The cosa-voice MCP runs as a stdio subprocess of Claude Code (`Type: stdio` per `claude mcp get cosa-voice`). The Python process loaded `cosa_voice_mcp.py` once at startup; it does not re-read the file on disk.
- To pick up the new code, restart Claude Code (close + relaunch the CC session). `/clear` is NOT sufficient — that clears Claude's context but leaves the MCP subprocess intact.
- The CURRENT session (2622c356) won't see the changes. A fresh session opened after restart will: hook allocates persona → `get_session_info()` returns `voice_persona` → Claude reads updated instructions → Claude TTS-announces by name at Phase A.

If `claude mcp restart cosa-voice` (or similar) exists as a CLI subcommand, that would be a less disruptive path than full Claude Code restart — worth checking before next session.

---

## ☀️ FIRST THING NEXT SESSION — `ask_yes_no` Neither: CoSA-context commit + fresh-session E2E verify

**Cycle state on resume**:
- Parent Lupin scope: ✅ landed in commit `<hash>` (session 6d544991 Arnold, 2026-05-11 PM)
- CoSA scope: ⏳ **`src/cosa/utils/notification_utils.py`** modified in working tree, not committed (per `feedback_lupin_only_never_cosa` — parent context never commits CoSA)
- MCP server: ⏳ stdio subprocess holds the OLD docstring; fresh CC session required to pick up the new return-value contract documentation

**Resume actions**:
- [ ] [LUPIN-COSA] In a CoSA-context session (`cd src/cosa && claude` or equivalent): `git status` → expect `utils/notification_utils.py` modified; `git diff utils/notification_utils.py` → confirm regex extension + `format_qualified_response` "neither" branch + smoke-test additions; commit with message like "Extend ask_yes_no qualifier regex + format helper to accept 'neither' answer"
- [ ] [LUPIN] (Optional) Bump CoSA submodule pointer in parent Lupin after the CoSA commit lands
- [ ] [LUPIN] Fresh CC session E2E verify: call `ask_yes_no("test question?")` from a new session, click the new **Neither** button, confirm Claude receives `"neither"` (or `"neither [comment: ...]"` with comment). Without restart, the current session's MCP stdio subprocess still holds the old docstring.

**Read on resume**:
1. `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/00-index.md` — master nav, Q-decisions, REUSE table
2. `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/02-handoff-summary.md` — CoSA-context-session pointer with exact commit steps
3. `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/90-execution-log.md` — phase status + post-implementation verification evidence

---

## ✅ CC Card Normalization — Phases 1–5a SHIPPED (2026-05-11, session 658ea35d Mr. Radio, commit `eab6fac`)

**Cycle state**:
- Phase 0 Documentation ✅ CLOSED 2026-05-10
- `/plan-review` REUSE / Pass 1 / Pass 2 ✅ ALL CLOSED 2026-05-11
- Idempotency marker stamped: `last-reviewed-at: 2026-05-11 (commit c1cec74)` in `00-index.md`
- Phase 1–5a ✅ **DONE 2026-05-11** (Mr. Radio, commit `eab6fac`)
- Phase 5b `:8000` E2E ⏳ **IN FLIGHT** via Mr. Radio (user voice update 2026-05-11)
- Phase 6 wrap ⏳ PARTIAL — 6.1–6.7 docs DONE; 6.8 parent commit + 6.9 CoSA commit HELD for user authorization per `feedback_never_auto_commit_push`

**Action items**:
- [x] [LUPIN] Phase 1 (HTML normalization in `notifications.html`) — 8 sub-steps applied; AC1, AC1.5, AC2, AC3, AC4 GREEN per 90-execution-log.md
- [x] [LUPIN] Phase 2 (JS handler normalize) — `submitClaudeCode` + `submitClaudeCodeToQueue` rewritten; fetch URL → `/api/claude-code/submit`; statusDiv 3-color verified
- [x] [LUPIN] Phase 3 (E2E test cleanup) — 2 obsolete tests deleted; `test_cc_card_renders_in_sibling_shape` added; py_compile clean
- [x] [LUPIN-COSA] Phase 4 (URL rename + alias) — Q8 verdict = **PRIMARY**; stacked decorators register canonical `/api/claude-code/submit` + deprecated alias `/api/claude-code/queue/submit`
- [x] [LUPIN] Phase 4.5 (handoff doc finalize) — Q8 verdict populated as PRIMARY in `02-handoff-summary.md`
- [x] [LUPIN] Phase 5a verification on `:7999` — 5.1–5.6 + 5.11 all GREEN; 5.7 headless UI probe folded into 5.8
- [ ] [LUPIN] Phase 5b verification on `:8000` — **IN FLIGHT via Mr. Radio's session** (3 submissions: `-k test_job_dispatch`, `-k visual --update-snapshots`, `-k test_claude_code_max_subscription`). Tracking row at top of TODO.md "⏰ NEXT SESSION — Schedule Phase 5b" remains Mr. Radio's working record.
- [ ] [LUPIN] Phase 6.8 parent commit + 6.9 CoSA commit (CoSA-context session) — held for user authorization

**Read on resume**:
1. `~/.claude/CLAUDE.md` + `/mnt/DATA01/include/www.deepily.ai/projects/lupin/CLAUDE.md` + `CLAUDE.local.md`
2. `history.md` (this session's entry: 2026.05.11 Session 6e8a6a03 Rachel)
3. `TODO.md` (this section)
4. `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` — master nav, Q-decisions table, REUSE table with verification spot-checks
5. `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` — full design with 9 Q-N FROZEN, 8 phases, 19 ACs (all post-plan-review-applied)
6. `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` — cross-sub-project handoff for mobile + multiplexer teams
7. `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` — phase status table + REUSE/Pass1/Pass2 closure evidence

**Key ratified decisions worth knowing on resume**:
- Q1: URL renames `/queue/submit` → `/submit` with backward-compat alias (one release cycle)
- Q2: INTERACTIVE option stays as disabled `<option>` with tooltip (visual breadcrumb for future return)
- Q8 fallback: if FastAPI rejects stacked decorators, COMMENT OUT (not delete) the deviant decorator with breadcrumb; mobile + smoke tests migrate immediately
- Q9: cross-sub-project handoff via `02-handoff-summary.md` + TODO seeds in mobile + multiplexer R&D folder

**Origin plan file** (pre-merge reference): `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (approved 2026-05-10 via ExitPlanMode).

---

## ☀️ FIRST THING TOMORROW — Multiplexer Phase 6b Phase 5A → 5B (JobStore.delete + delete-button click handler)

**Cycle state on resume (2026-05-12 AM)**:
- Q-decisions ✅ CLOSED 12/12 (2026-05-07)
- REUSE pre-pass ✅ CLOSED 28 RE + 5 L3 (2026-05-07)
- Pass 1 Fitness ✅ CLOSED 14/14 (2026-05-11)
- Pass 2 Adversarial ✅ CLOSED 11/11 (2026-05-11)
- Code-execution plan ✅ AUTHORED 2026-05-11
- **Phase 1 ✅ COMMITTED** as `057dbd8` (df880556 María, 2026-05-11 PM) — store API prereqs landed
- **Phase 2 ✅ COMMITTED** as `ed4fc94` (df880556 María, 2026-05-11 PM) — interactive widget templates landed
- **Phase 3 ✅ IMPLEMENTED + uncommitted** (df880556 María, 2026-05-11 late PM) — `ActionRequiredRenderer.ts` 100% c8; 34 tests; **session-end commit will land it**
- **Phase 4 ✅ IMPLEMENTED + uncommitted** (df880556 María, 2026-05-11 late PM) — `TtsChromeRenderer.ts` 100% c8; 20 tests; batched with Phase 3 in session-end commit
- Phase 5A → 5B → 6 → 7 → 8 ⏳ **READY TO BEGIN** at Phase 5A tomorrow morning

**Resume action**:
- [x] [LUPIN] Re-audit at execute time per `feedback_audit_plans_at_execute_time` — re-grep recent feedback memories for constraints landed since 2026-05-11; surface conflicts before code edits — Done df880556 María (only `feedback_skip_arnold_yes_no_neither_ux` newer; not relevant to Phase 6b)
- [x] [LUPIN] Capture Phase 6a baseline `B6a` — Done df880556 María: `B6a = 31484` bytes (boot.65c779ac946b.js); AC7 ceiling = 39676 bytes; recorded in code-execution plan + 90-execution-log.md
- [x] [LUPIN] Verify pre-existing store API signatures — Done df880556 María: all signatures match Pass 2 file:line citations (ActionRequiredStore.respond at L182, tick at L291, expires_at at L266; AudioStore state/queueLength/pause/resume/skip at L201-218; AudioStore.stop() public method confirmed MISSING)
- [x] [LUPIN] Verify Phase 5 `NotificationsListRenderer.renderActionRequiredSection` still at lines 228-243 — Done df880556 María: confirmed at L228
- [x] [LUPIN] Verify `actionRequiredReadOnly.ts:49` still sets `data-id-hash` — Done df880556 María: confirmed exact line + correct attribute (no contract drift)
- [x] [LUPIN] **Begin Phase 1 (Step 1 of code-execution plan)**: 4 store/renderer prereq edits — Done df880556 María (checkpoint pending):
  - [x] 1.1 `ActionRequiredStore.respondAndAwait()` (Pass 2 A1, Phase 0 prereq #8) — implemented + 6 tests
  - [x] 1.2 Widen `respond()` + `respondAndAwait()` signature to `string | ReadonlyArray<string> | Record<string, string>` (Pass 2 A2, Phase 0 prereq #9) — implemented + 5 tests + ActionRequiredItem.response widened + new ActionRequiredResponse union in shared/types.ts
  - [x] 1.3 `AudioStore.stop()` (Pass 2 A6, Phase 0 prereq #10) — implemented + STOP_REQUESTED machine event + 6 tests
  - [x] 1.4 Phase 5 `NotificationsListRenderer` ownership-flag early-return guard (Pass 2 A3 Path A) — implemented at L228 + 2 tests
  - [x] 1.5 `c8 --100` on all 3 edited files: GREEN (100% lines/branches/functions/statements); 22 new unit tests; tsc + eslint clean; 489/489 multiplexer unit sweep PASS
- [x] [LUPIN] **Begin Phase 2 (templates: actionRequiredInteractive.ts + ttsChrome.ts)** — Done df880556 María (checkpoint pending):
  - [x] 2.1 `actionRequiredInteractive.ts` (NEW, 228 LOC) — switch over 5 response_types (yes_no/radio/checkbox/open_ended/open_ended_batch); addEventListener-based handler attachment; AC2e safe-write header
  - [x] 2.2 `ttsChrome.ts` (NEW, 147 LOC) — 3 controls (toggle/stop/skip) + state-driven enable matrix per AudioPlaybackState + `.is-playing-current` / `.is-paused-current` + currentTrackName + queueLength
  - [x] 2.3a 22 tests on `actionRequiredInteractive.test.ts` (≥15 floor) — all 5 happy-path renders + 5 click-dispatch + 1 unknown-response_type throws + 1 AC2e grep ban + edge cases
  - [x] 2.3b 18 tests on `ttsChrome.test.ts` (≥15 floor) — 6 state-driven renders + 4 click-dispatch + currentTrackName present/absent/empty + queueLength + .is-playing/paused-current + 1 AC2e grep ban
  - [x] 2.4 `c8 --100` GREEN on both new files (used Phase 6a `jobCard.ts:251` precedent for tagged-template phantom-branch ignores); tsc + eslint clean; 528/528 multiplexer unit sweep PASS
  - [x] Type extension: added `multiSelect?: boolean` to `ActionRequiredItem` (defaults undefined → radio path; wire-side population still Phase 0 prereq #2 pending)
- [x] [LUPIN] **Begin Phase 3 (`ActionRequiredRenderer.ts`)** — Done df880556 María 2026-05-11 late PM (session-end commit pending; uncommitted on disk):
  - [x] 3.1 `ActionRequiredRenderer.ts` (NEW, ~360 LOC) — factory + mount/unmount + `dataset.phase6bOwner="true"` ownership claim BEFORE any DOM write (Pass 2 A3) + 5 widget builders (interactive/submitting/responded/expired/cancelled) + countdown + click→`respondAndAwait` (Pass 2 A1) + onChange dispatcher + tick handler (NO RAF per Pass 2 a2)
  - [x] 3.2 34 tests on `action_required_renderer.test.ts` (≥21 AC5 floor) — 6 submit happy-path + 5 error-rollback + 6 state-machine transitions + countdown/NO-RAF spy + mount idempotency + AC2c atomic strip (1-2 MutationRecords; happy-dom microbatches replaceWith) + inline error stripe + ownership-flag + cssEscape fallback + multi-item + offline-frozen/resumed
  - [x] 3.3 `c8 --100` GREEN; tsc + eslint clean; 562/562 multiplexer unit sweep PASS
- [x] [LUPIN] **Begin Phase 4 (`TtsChromeRenderer.ts`)** — Done df880556 María 2026-05-11 late PM (session-end commit pending; uncommitted on disk, batched with Phase 3):
  - [x] 4.1 `TtsChromeRenderer.ts` (NEW, ~155 LOC) — factory + mount/unmount + dual subscription (`store_audio_state_change` AND `store_audio_chunk_decoded`) with single shared `pendingRender` flag + RAF coalescing (per Q-B9 + Pass 1 F-13); test-injectable RAF; click handlers wire to `AudioStore.pause/resume/stop/skip`; uses `replaceChildren` for atomic single-childList swap; currentTrackName intentionally omitted (Phase 0 prereq #3 pending)
  - [x] 4.2 20 tests on `tts_chrome_renderer.test.ts` (≥13 AC5b floor) — 7 state transitions + 4 control wiring + 2 storm safety (chunk_decoded × 100 → 1 RAF; state_change × 5 → 1 RAF) + mount idempotency + stop semantics (queue=0, state=idle per Phase 1.3) + mixed-event coalescing
  - [x] 4.3 `c8 --100` GREEN ON FIRST TRY (no phantom-branch issues with `replaceChildren`); tsc + eslint clean; 582/582 multiplexer unit sweep PASS
- [ ] [LUPIN] **Begin Phase 5A → 5B** per `2026.05.11-phase6b-code-execution-plan.md` Step 5 — `JobStore.delete()` then delete-button click handler on `JobsPaneRenderer`. **5A → 5B is a natural compile-time gate** (5B imports `JobStore.delete` from 5A). Q-A6 + Q-B10 follow-through; strips 4 inertness markers from `.job-delete-button`; rollback closure pattern for 5xx/network errors; 404 treated as success per Q-B10. **DOD tables**: 5A has 8 rows (5A-1..5A-8), 5B has 11 rows (5B-1..5B-11) — both must pass before commit
- [ ] [LUPIN] Phases 6-8 follow per `2026.05.11-phase6b-code-execution-plan.md` execution sequence (per-phase commits each gated on user authorization)

**Phase 5 quick-start checklist (so you can dive straight in tomorrow)**:

| What | Where | Notes |
|---|---|---|
| Read the Phase 5 plan | `2026.05.11-phase6b-code-execution-plan.md` Step 5 (lines ~256-320) | full DOD tables for 5A + 5B |
| Verify `JobStore` lacks `delete()` | `src/fastapi_app/static/js/multiplexer/stores/JobStore.ts` | already verified MISSING 2026-05-07 per execution log |
| Verify `JobsPaneRenderer` delete button is inert | `src/fastapi_app/static/js/multiplexer/render/JobsPaneRenderer.ts` + `templates/jobCard.ts:258` | inert markers: `data-phase6-pending`, `aria-disabled`, `cursor: not-allowed`, `title="Delete coming in Phase 6b"` |
| 5A signature | `JobStore.delete(idHash: string): { restoreState: () => void }` | per design § Phase 4 sub-step DOD signature |
| 5A test file | NEW `src/tests/unit/multiplexer/stores/jobstore_delete_api.test.ts` | actually goes in `src/tests/unit/multiplexer/` per existing test layout (NOT in stores/ subdir) |
| 5B test file | EDIT `src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts` (existing) | extend with ≥6 new AC5c cases |
| API endpoint | `DELETE /api/queue/<bucket>/<idHash>` | already verified exists at `queues.py:1193` (Phase 0 prereq #1 ✅) |

**Read on resume (in this order)**:
1. `~/.claude/CLAUDE.md` + `/mnt/DATA01/include/www.deepily.ai/projects/lupin/CLAUDE.md` + `CLAUDE.local.md`
2. `TODO.md` (this section)
3. **`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/2026.05.11-phase6b-code-execution-plan.md`** — THE authoritative resume target; contains full 9-phase sequence + AC scorecard + pre-exit self-audit + resume pointer
4. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (frozen design — Pass 2 closed)
5. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` § "Pass 2 Adversarial — closed 2026-05-11" (ratification record for audit trail)
6. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` Phase 6b section (per-phase progress table — Phase 1 row to populate first)
7. `history.md` (today's session entry if seeded)
8. Phase 6a precedent (only if Phase 6a patterns ambiguous): `2026.05.06-phase6a-code-execution-plan.md` + `94-phase6a-review-findings.md` § "Pass 2 Adversarial — closed"

**Phase 0 prerequisites — net status post-Pass-2** (informational; verified at execute time):
1. `DELETE /api/queue/<bucket>/<id>` exists in CoSA — ✅ verified (`queues.py:1193`)
2. `action_required` payload carries `multiSelect: bool` — ⏳ pending verification
3. `AudioStore.currentNotificationIdHash` linkage — ⏳ pending verification (preferred sync getter per Pass 1 F-11; alternative event payload field)
4. Action-required render mount surface — ⏳ pending verification (`#action-required-pane` vs inline)
5. Phase 6a CoSA `multiplexer_config.py` commit — ⏳ pending (carries from Phase 6a)
6. `JobStore.delete(idHash)` — ❌ verified MISSING 2026-05-07; lands as Phase 5A of code-execution plan
7. ~~`countdown_expires_at` payload field~~ — **STRUCK 2026-05-11 per Pass 2 A5** (redundant; use existing `expires_at: number`)
8. **NEW** — `ActionRequiredStore.respondAndAwait()` method — Phase 1.1 of code-execution plan (per Pass 2 A1)
9. **NEW** — Widen `respond()` signature to `string | ReadonlyArray<string> | Record<string, string>` — Phase 1.2 (per Pass 2 A2)
10. **NEW** — `AudioStore.stop()` method — Phase 1.3 (per Pass 2 A6)

---

## ✅ DONE — Phase 6b Pass 1 Fitness ratification (2026-05-11, session 017dc1cc, Mr. Radio)

All 14 Pass 1 findings ratified + resolutions applied to `09-phase6b-interactive-widgets-design.md`. Pass 1 closed subsection appended to `95-phase6b-review-findings.md`.

- [x] [LUPIN] Walk Pass 1 ratification — 9 turns (1 Minors batch + 8 individual Majors). Per-decision routing via cosa-voice `ask_yes_no` action-required UI per user directive ("push every decision point into the action-required UI"). All firings returned `yes`.

**Cycle state**:
- Q-decisions ✅ CLOSED 12/12 (2026-05-07)
- REUSE pre-pass ✅ CLOSED 28 RE + 5 L3 (2026-05-07)
- Pass 1 Fitness ✅ CLOSED 14/14 (2026-05-11) — all resolutions applied
- Pass 2 Adversarial ⏳ gated on user go-ahead
- Code-execution plan ⏳
- Implementation ⏳

**Resolutions applied** (full record in `95-phase6b-review-findings.md` § "Pass 1 Fitness — closed 2026-05-11"):
- F-1 → AC10b ceiling 500 → 700 (tts-chrome.css per Q-B12)
- F-2 → AC5 ≥18 cases enumerated in new sub-table (subtotal 21)
- F-3 → New "Q-B1 dispatch contract" subsection with template-internal switch
- F-4 → Q-B3 state machine extended (expired_visual + responded_default); Q-B5 ratified text rewritten (local RAF timer); new Phase 0 prereq #7 (countdown_expires_at payload)
- F-5 → AC2d grep regex replaced with unit-test contract
- F-6 → Phase 0 #6 reworded; new "Phase 4 sub-step DOD" subsection with 4A (8 rows) + 4B (11 rows) DOD tables; `delete()` returns `{ restoreState: () => void }`
- F-7 → Inertness-lift mechanism specified as single-write template swap; AC2c rewritten as MutationObserver assertion
- F-8 → AC7 post-6a baseline capture as pre-implementation step
- F-9 → AC5b ≥12 cases enumerated in new sub-table
- F-10 → Q-B9 throttling specified as renderer-side (not store-side)
- F-11 → Phase 0 #3 target API shape specified (`currentNotificationIdHash(): string | null` preferred)
- F-12 → Boot wiring "mount() is synchronous" addendum
- F-13 → Q-B9 ratified text: state-change events RAF-coalesced (not 100ms throttle); new R7 risk row; AC5b storm-safety case (b) added
- F-14 → AC10e pytest command rewritten as unified `-k "pending_count"` over both files

**Next**: when user gives go-ahead, dispatch Pass 2 Adversarial (Explore agent, clean context, walks Pass-1-resolved doc state for security/DOS/race/contract-drift cluster).

---

## ☀️ HISTORICAL — was "FIRST THING IN THE MORNING — 2026.05.08"

(Superseded by 2026-05-11 ratification above. Kept as audit trail.)

**Resume pointer (historical)**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/93-resume-here-phase6b-pass1-ratification.md` — now historical; can be removed in a future cleanup.
- **F-13** — R2 throttle covers `chunk_decoded` only; rapid state-toggle could thrash DOM.

**After Pass 1 closes**:
- [ ] [LUPIN] Pass 2 Adversarial dispatch (clean-context Explore agent; sees Pass-1-resolved doc state). Phase 6a precedent: 15 findings + 1 Layer 3 → walked individually with `ask_multiple_choice` for the Layer 3.
- [ ] [LUPIN] After Pass 2 closes: convergence re-grep + author code-execution plan at `<date>-phase6b-code-execution-plan.md` per slicing-manifest naming convention.

### Discussion topic — Broadcast messages from notifications UI

- [ ] [LUPIN] **Brief design discussion: broadcast messages from notifications UI**. Initial scope: notifications UI sends a message that fans out to **all running Claude Code sessions** (not just one targeted session). Later expansion: extend the broadcast surface to **all running agents** (Claude Agent SDK background jobs — Deep Research, Podcast Generator, Presentation, BFE, TFE, etc.). Open questions to surface before implementation: addressing model (target = "all CC sessions" vs explicit session list vs role-based?), delivery semantics (best-effort fire-and-forget vs ack-required vs idempotent retry?), payload shape (free-form text vs structured `notify_user`-shaped envelope?), UI affordance for composition (one-shot text input vs persistent broadcast pane?), permissions / rate-limiting / abuse vectors. Bring to whiteboard / cosa-voice ratification cycle if it grows past a single discussion turn. **Cross-reference**: existing per-session targeted notifications already flow via `notify_user` MCP tool; the broadcast surface is the inverse direction. **Status**: discussion only — no code, no design doc yet. Decide whether to capture as an R&D note under `src/rnd/v0.1.7/` after the discussion if scope warrants.

### Carried forward (from 2026.05.07; partly closed today)

- [ ] [LUPIN-COSA] **Commit the CoSA-side Phase 1 endpoint** — `src/cosa/rest/routers/multiplexer_config.py` (NEW) still uncommitted on CoSA side. Parent Lupin commit `362fa5d` is the documenting reference. Handle from a CoSA-context session.
- [ ] [LUPIN] **history.md archival** — was at 19,719 tokens (CRITICAL); María's parallel session added a 60-line entry today, so it's higher now. Was deferred today because María had uncommitted edits. Re-check at start of session — if María's session has committed (check `git log --oneline -5`), proceed with `/plan-history-management mode=archive`.

### What closed today (2026.05.07)

- ✅ Phase 6a AC11a baseline captured (`ts-b786315c`, baseline PNG at `io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/`, 13:59 EDT)
- ✅ Phase 6a AC11b regression GREEN (`ts-bd34af9b`, 1 passed in 5.6s, 14:48 EDT)
- ✅ Phase 6a fully CLOSED on both `:7999` and `:8000`
- ✅ Two test-suite-submit silent-drop traps documented (memories: `feedback_test_types_e2e_not_e2e_ui` + `feedback_test_suite_submit_field_pytest_args`)
- ✅ Phase 6b design doc + findings doc + resume-here doc all landed at canonical paths (`d70be64`)
- ✅ Q-decisions (12/12) + REUSE pre-pass (28 RE + 5 L3) ratified
- ⏸️ Pass 1 Fitness paused at 14 findings produced

---

## ☀️ FIRST THING IN THE MORNING — 2026.05.07

### Pending — Multiplexer Phase 6a follow-ups

- [ ] [LUPIN-COSA] **Commit the CoSA-side Phase 1 endpoint** in a CoSA-context session: `src/cosa/rest/routers/multiplexer_config.py` (NEW) — single GET endpoint `/api/multiplexer/config` returning `{multiplexer_max_meta_display_bytes:256000}` from `ConfigurationManager`. Endpoint verified live via `urllib.request` on `:7999` (parent Lupin commit `362fa5d` is the documenting reference + has the matching `main.py` register + INI key + splainer + `rest-api-reference.md` row). Per `feedback_lupin_only_never_cosa` the parent Lupin session never commits CoSA — handle this from `cd src/cosa && git commit ...` in a CoSA-context session, then bump the parent submodule pointer if applicable.

- [ ] [LUPIN] **Schedule Phase 6a AC11a Run #1 (visual baseline capture)** via `/schedule-tests` once a non-overlapping `:8000` `scheduled_at` slot opens up. Submission body: `{"test_types": "e2e", "scheduled_at": "<slot>", "pytest_args": "--update-snapshots -k multiplexer_phase6a", "auto_fix_on_failure": false}` — note two field-name traps both verified empirically: (1) `test_types` value is `"e2e"`, NOT `"e2e_ui"`; (2) the pytest-pass-through field is `pytest_args`, NOT `args` (see `feedback_test_types_e2e_not_e2e_ui.md` + `feedback_test_suite_submit_field_pytest_args.md` — both unknown values are silently dropped to a 0/0/0/0 result OR a full-sweep ignore-the-filter run, with no HTTP error). Test file: `src/tests/e2e_ui/test_multiplexer_phase6a_visual.py` (committed in `5cd8b20`, collects cleanly). Single test only — `-k multiplexer_phase6a` filter ensures the full ~285 functional + 12 visual sweep does NOT run. After the run, baseline PNG lands at `io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/` on the host filesystem (NOT committed — `io/` is gitignored at `.gitignore:68`; baseline is bind-mounted into the test container, which is how AC11b sees it).

- [ ] [LUPIN] **Schedule Phase 6a AC11b Run #2 (regression check)** at a separate `:8000` slot AFTER Run #1's baseline lands. Same submission body (`test_types: "e2e"`, `pytest_args: "-k multiplexer_phase6a"`) minus the `--update-snapshots` flag. Pass criterion: container log contains `Test suite complete` + `e2e: 1 passed, 0 errors` for Run #2.

- [ ] [LUPIN] **Open Phase 6b** when AC11a/AC11b close. Phase 6b scope per `07-phase6-slicing-manifest.md`: TTS chrome + action-required interactive widgets + delete-button handler (Q-A6 wires the disabled `×` from 6a). Phase 6c (voice-persona modal + audio recorder + focus tray + conversation-mode UI pin) follows.

- [ ] [LUPIN] **Optional**: history.md is at 19,719 tokens (CRITICAL threshold per session-end workflow). User deferred archival from this session-end. Consider invoking `/plan-history-management mode=archive` early in next session before adding new content.

---

## ☀️ FIRST THING IN THE MORNING — 2026.05.06

### ✅ Closed — Multiplexer Phase 6a Pass 1 Fitness ratification gate (2026-05-06 AM)

All 17 findings ratified via cosa-voice walkthrough (Session `5ced4868`, Mr. Radio persona): 7 Minors walked individually after the batch yes/no was rejected; 10 Majors walked individually. Apply pass complete: design doc `08-phase6a-jobs-surface-design.md` updated for all 17; Risks table + AC table updated; "Pass 1 Fitness — closed" subsection appended to `94-phase6a-review-findings.md`.

**F15 ratification produced a global side-effect**: 100% c8 coverage mandate for multiplexer TypeScript codebase. See project `CLAUDE.md` "100% COVERAGE MANDATE" subsection + `feedback_100pct_coverage_multiplexer.md` auto-memory.

### ✅ Closed — Phase 4 + Phase 5 coverage backfill (2026-05-06 PM)

**ALL 26 multiplexer TS files at 100%** lines + branches + functions + statements per `c8 --100`. **400 unit tests passing** (was 325 baseline; +75 new tests across the two backfill passes).

**Files closed in PM session (10)**: `auth/AuthManager.ts`, `stores/ActionRequiredStore.ts`, `render/html.ts`, `shared/StorageService.ts`, `stores/SenderStore.ts`, `transport/QueueTransport.ts`, `stores/AudioStore.ts`, `stores/NotificationStore.ts`, `shared/EventBus.ts`, `api/ApiClient.ts`.

**Per-file diff summary** lives at `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/91-resume-here-coverage-backfill.md` § "Files closed in PM session".

**Pattern playbook** validated across both passes:
- File-header phantom + function-declaration phantom + class closing-brace phantom — `/* c8 ignore next */` with named artifact reason
- Production-default fallbacks (`opts.x ?? defaultX()`) — `/* c8 ignore next */ // production-default fallback: <reason>` (tests always inject; the `??` arm fires only in production browsers)
- Defensive guards with provable invariants — `/* c8 ignore next */ // defensive: <invariant>` naming what makes the branch unreachable
- Tagged-template literal phantoms — `/* c8 ignore start/stop */` wrapping the template block with explicit reason
- Real behavioral branches — add targeted unit tests; never c8-ignore

**One real bug surfaced + fixed during backfill**: `AuthManager.ChainMutexLockManager.request()` line 65 — the `tail === prev.then(() => next)` comparison created a NEW promise on the right side each time, so the cleanup `if` branch was always false → memory leak (entries never removed). Fixed by assigning the chained promise to a local `chained` variable and using that for both `set()` and the comparison.

**Phase 6a code-writing cycle is unblocked from the coverage side.** Pass 2 Adversarial ratification remains as the documentation gate.

### ✅ Closed — Multiplexer Phase 6a Pass 2 Adversarial ratification (2026-05-06 PM)

All 15 Pass 2 findings + 1 Layer 3 (C-6) ratified via cosa-voice walkthrough (Session `5ced4868`, Mr. Radio persona; per `feedback_pip_plan_review_is_sequential`): 5 Minors batch-walked + 10 Majors walked individually + C-6 walked via `ask_multiple_choice`. Apply pass complete; convergence re-grep clean; Phase 6a documentation cycle CLOSED. Commit `6fd95f5`.

### ✅ Closed — Multiplexer Phase 6a code-writing cycle, Phases 0-7 (2026-05-06 PM/eve)

All 7 implementation phases shipped across 8 commits (`362fa5d` → `744b6dd`). AC1-AC10d all green on `:7999`; AC11a/AC11b await user `:8000` slot-coordination (see new Pending below). Coverage: c8 100% (lines + branches + functions + statements) on every new render file (`JobsPaneRenderer.ts`, `templates/jobCard.ts`, `templates/jobBucket.ts`). Test pyramid: 23 (renderer) + 38 (templates) + 8 (formatDuration) + 5 (smoke) + 1 (E2E authored, not yet scheduled). Build: `boot.65c779ac946b.js` gz=31484B, AC7 ceiling 60382 ✓ (+1822B vs Phase 5 baseline 29662). Full audit trail in `90-execution-log.md` Phase 6a sub-section.

### Reference — Pass 1 Fitness Findings (closed 2026-05-06)

  **Recommended ratification path** (mirrors REUSE-step pattern that worked well 2026-05-05):
  1. Mechanical batch yes/no for the 7 Minors (F1, F2, F9, F10, F11, F12, F15) via `mcp__cosa-voice__ask_yes_no`
  2. Meaningful walkthrough for the 10 Majors (F3, F4, F5, F6, F7, F8, F13, F14, F16, F17) via per-row `ask_yes_no` or `ask_multiple_choice`

  **After ratification**: I apply approved fixes to `08-phase6a-jobs-surface-design.md`, run convergence re-grep (TBD + Open-sub-question per PIP §7), append "Pass 1 Fitness — closed" subsection to `94-phase6a-review-findings.md`, then surface results before Pass 2 Adversarial fires (clean-context Agent, sees Pass-1-resolved state per Q11 amendment + sequential PIP).

  **Standout Major findings to walk first**: F3 (`hydrateHistory` rejection path unspecified), F4 (`createJobsPaneRenderer({stores})` shape contract), F7 (AC8a `data-phase6-pending` count fixture mechanism), F14 (Q-A2 "Match legacy" lacks file:line citation), F17 (Q-A7 mount sequence ordering).

  **Anchor docs to skim before the gate**:
  - `01-phase0-decisions.md` Q11 amendment (sequential PIP mandate)
  - `08-phase6a-jobs-surface-design.md` § "Q-decisions — RATIFIED" + § "Prior art referenced"
  - `94-phase6a-review-findings.md` § "Pass 1 Fitness Findings" (the table itself)
  - `feedback_pip_plan_review_is_sequential` auto-memory

---

## ☀️ FIRST THING IN THE MORNING — 2026.05.05 (or next session)

### Pending — Commit Phase 3 + begin Multiplexer Phase 4

- [ ] [LUPIN-COSA] **Commit the CoSA-side Phase 1 change** in a CoSA-context session: `src/cosa/rest/routers/pages.py` adds `/app/multiplexer` to `_ROUTE_TABLE` (mirror line 26 pattern) + `page_multiplexer()` handler (mirror lines 69-71 pattern). Parent Lupin commit (Phase 1) is the documenting reference. Verified via py_compile + GET 200 against the live :7999 server.

- [ ] [LUPIN] **Commit Phase 3 implementation in parent Lupin repo** — files to be staged: 6 new TS transport modules under `src/fastapi_app/static/js/multiplexer/transport/`, edited `boot.ts` + `shared/types.ts` under `src/fastapi_app/static/js/multiplexer/`, 5 new unit-test files under `src/tests/unit/multiplexer/`, 1 new WS smoke test under `src/tests/websocket_smoke/`, 1 new Playwright page-load smoke under `src/tests/smoke/`, `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (Phase 3 section closed), `.claude-session.md` (Phase 3 entries), `history.md`, `TODO.md`. Suggested message: `Multiplexer Phase 3 (ec746144): transport layer (ws-channel + CSM + Queue/Audio/CC-stub + boot.ts wiring) + 70 new tests; AC#7 + AC#8 green`.

- [ ] [LUPIN] **Begin Phase 4 implementation of the multiplexer rebuild** — domain stores phase. Per Q10 amendment + spine-bundle's "natural go/no-go gate at end of Phase 3 implementation": project re-scopes (or proceeds with per-phase-from-now-on cadence) before committing to 6 more design docs. Phases 1-3 spine bundle has shipped clean (Phase 3 amended 2026-05-04 PM per D1 A-extended ratification — CC out of scope) — proceed with per-phase from Phase 4. Entry artifacts a fresh-context Claude must read in order:
  1. `~/.claude/CLAUDE.md` (Layer 1)
  2. Lupin `CLAUDE.md` + `CLAUDE.local.md`
  3. `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/01-working-contract.md` (Layer 2)
  4. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` (Q1-Q11 + amendments)
  5. Phase 4 design doc — **TBD**: a draft must be authored before Phase 4 implementation starts. Per Q11 amendment: REUSE → Pass 1 (Fitness) → Pass 2 (Adversarial) → user approval gate, then 90-execution-log Phase 4 section opens.
  6. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` — review Phase 1/2/3 outcomes; specifically Phase 3's "Spec drifts" + "Implementation deviations" + "Discovered design gap" + "D1 Ratification Amendment" subsections — these inform Phase 4's stores design, especially that **CC is OUT OF SCOPE for Phase 4 + all subsequent phases** (per A-extended ratification 2026-05-04 PM) and the **server-event-type pass-through** (Phase 3 transport wrappers cast to `LupinEventType` at the boundary; Phase 4 stores need to consume specific event types like `notification_received`, `voice_persona_assigned`, `conversation_mode_change`).

  **Phase 4 scope** (per spine-bundle Phase 0 docs §"Phase plan", reduced per D1 A-extended ratification): NotificationStore, JobStore, AudioStore, ActionRequiredStore, SenderStore. XState for high-churn (TTS, action-required, connection — connection already done in Phase 3); plain reducers elsewhere (notifications list, sender map). AudioStore replaces Phase 3's debug-logger binary handler with the real PCM-decoding handler. **No ClaudeCode store and no CC transport body work** — that scope was removed by the D1 A-extended ratification.

---

## ☀️ EARLIER PENDING — carried over from 2026-05-03

### Pending

---

## ☀️ FIRST THING IN THE MORNING — 2026.05.03

### Pending

- [x] [LUPIN] **Commit the CoSA-submodule changes for the WS reconnect circuit-breaker milestone (Session 0022baba)** — committed by user on 2026-05-03 (CoSA-context session). Two files: `src/cosa/rest/routers/websocket.py` (4001/4002/4003 close-code constants + 10 queue auth-fail call sites) and `src/cosa/rest/websocket_manager.py:147` (displaced-socket close → `code=4002, reason="session_conflict_displaced"`). Parent Lupin commit `1a9e3e0` is the documenting reference.
- [x] [LUPIN] **WSChannel binary-frame regression fix** — completed Session 656c8ba2 (2026-05-03 PM). Two-line root cause: post-circuit-breaker WSChannel facade had no Blob branch in `socket.onmessage`, dropping audio chunks via JSON.parse-throws. Fixed with `onBinaryMessage` opt + Blob/ArrayBuffer branch in `ws-channel.js`, wired into audio channel in `notifications.js`. Cache-busters bumped to `v=20260503a`. 22/22 WSChannel unit tests pass (20 pre-existing + 2 new regression). 50/50 WS smoke pass. Manual end-to-end confirmed: 5 chunks reaching handleAudioChunk, TTFA 277ms.
- [ ] [LUPIN] **Archive `history.md`** — after today's 5-phase milestone, the file sits at 17,138 tokens (just over the 17k WARNING threshold). Run `/history-management mode=check` first to see velocity + recommended cut date, then `/history-management mode=archive` to slice older sessions to a dated archive in `history/`. Should reduce live file to ~8-12k tokens per project policy.
- [x] [LUPIN] **Land voice-persona /clear preservation fix** — Session d5e3cf21 (2026-05-06 AM). Root cause overturned in Phase 1.2: bug was NOT in `register_session.py` gate-3 but in `session_end.py:224-226` (unconditional `_release_voice_persona` on every SessionEnd, including `/clear`). Fixed with 3-line `reason`-guard in `session_end.py` + 8 new unit tests in `test_session_end.py`. Phase 1F removed the diagnostic prints + their pinning tests once live-verified. Live verification: bridge `assigned_at` preserved unchanged across 2 /clear cycles. Commits: `82c098b` (§0.4) + `f21b163` (Phase 1F + wrap). R&D: `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/`.

---

## ☀️ MORNING FINISHED — 2026.05.02

### Completed today

- ✅ [LUPIN] Built dev-tools voice-persona-reference page at `src/fastapi_app/static/html/test/voice-persona-reference.html` — admin-gated, fetches `/api/cosa-voice/voice-persona/pool`, renders six persona tiles with badge styling matching notification cards, ▶ Play sample button per tile, "Play all in sequence" toolbar, "currently allocated personas" footer.
- ✅ [LUPIN] Added new endpoint `POST /api/cosa-voice/voice-persona/sample` in `src/cosa/rest/routers/voice_persona.py` — JWT-protected, pool-validated voice_id (rejects out-of-pool with 400), calls ElevenLabs HTTP TTS API, returns `audio/mpeg` bytes inline.
- ✅ [LUPIN] Added card under "Audio & TTS" on `src/fastapi_app/static/html/dev-tools.html`.
- ✅ [LUPIN] Voice-leak diagnosis confirmed via reference page — leaked voice was Tiberius (H1 from plan); root cause is `/clear` preservation failure in `register_session.py`.
- ✅ [LUPIN] Serialized fix design + execution-log scaffold to `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/`.

### Pending → carried over to 2026-05-02 AM section above (test-suite post-mortem)

The 19:00 EDT all-test-suite post-mortem work from the now-stale "FIRST THING IN THE MORNING — 2026.05.02" section was deferred to make room for the bug investigation that consumed today's session. Re-prioritize before the voice-persona fix tomorrow if the post-mortem failures are blocking other work.

- [ ] [LUPIN] **Work through the 19:00 EDT 2026.05.01 all-test-suite post-mortem** — `src/rnd/v0.1.7/2026.05.01-postmortem-test-suite-19h00.md`. Categorized 10 failures (8 collapse to 3 root causes: A=auto-proxy not threaded, B=notification proxy 503, C=voice-persona pool rename echo) plus addendum on 39 skips (28 integration skips + 22 stale xfailed-now-passing markers). Cheapest-first sequence at end of doc; steps 1-3 alone should drop failure count from 10 → ~3. Note: prior session 31172845's fix for "notification 503 cascade" did not close the hole — re-investigate before assuming it's a regression.

---

## 🧰 TODO SIZE MGMT SKILL — Follow-ups (Session 92ece47c, 2026-05-01)

### Pending

- [ ] [LUPIN→PIP] **Promote `todo-size-management` skill to `planning-is-prompting/workflow/todo-size-management.md`** — Lupin-local skill landed at `.claude/commands/todo-size-management.md` and validated against current TODO.md (38% reduction, 0 pending lost). PIP currently says "TODO.md is NEVER archived" (canonical workflow doc line 268) — the promotion is a **canonical-policy change**, not a pure code addition. Author from a PIP-rooted Claude session: lift algorithm + status × age semantics from `src/rnd/v0.1.7/2026.05.01-todo-size-management/01-design.md`, update `todo-management.md` "never archive" stance to point at the new size-mgmt doc, and ensure other PIP-using projects can adopt it. Note: each project will need its own `.claude/commands/todo-size-management.md` shim (mirror `history-management` pattern).
- [ ] [LUPIN] **Manual triage pass for stale pending items** — Aggressive archival reached 19.4k tokens, still above the 8-12k retention target. Mechanical algorithm does not auto-prune `[ ]` items by design. Reviewable candidates: large OPEN/MIXED sections like `## v0.1.6 — FUTURE DEVELOPMENT` (23 pending), `## Pending — HIGH PRIORITY` (13 pending), `## Pending — Older items carrying over` (14 pending), `## Completed earlier (Sessions 85b05d1d…)` (16 pending sub-bullets) — likely many done outside the formal mark-complete flow. Pass discretion: drop / mark `[x]` / re-stamp into a current section.
- [ ] [LUPIN] **Add `/todo-size-management` to `/plan-session-end` Step 0.5** — Mirror existing history-management integration. When session-end fires, run `mode=check` first; if WARNING/CRITICAL, prompt user same way as for history.md.
- [ ] [LUPIN] **MIXED-section excision smoke test** — Add a unit test in `src/tests/unit/` that ingests a synthetic MIXED section with `[x]` parent + `[ ]` sub-bullets and confirms the sub-bullets travel with the parent (current behavior, validated live but not regression-locked).

---

## 🎙 PERSONA + CONV-MODE EXIT-REMINDER FOLLOW-UPS (Session 911b1cdc, 2026-05-01)

### Pending

- [ ] [LUPIN] **End-to-end test the cross-session conv-mode exit-reminder injection** — requires fresh listener subprocesses (existing listeners still run pre-edit code). Start two new CC sessions, enter conv mode in one, then in the other. The displaced session should receive the `<system-reminder>` block typed into its tmux pane and on its next turn stop calling `notify()` and stop wrapping replies in `<voice-message>` format.
- [ ] [LUPIN] **Frontend localStorage reconciliation for `conversation_mode_active`** — separate from this session's server-side exit-reminder fix. The browser caches per-session conv-mode state in `localStorage[notifications_conversation_modes]` and only updates from WS events; missed displace events leave stale entries. Pick fix path (A: hydrate-on-load via new `GET /api/cosa-voice/conversation-mode/active-sessions`; B: server-pushed `conversation_mode_snapshot` WS event on auth) and implement.

### What landed (this session)

- ✅ Persona `Mr. NPR` → `mr radio` rename in INI + splainer + 2 test files
- ✅ `display_name_for()` helper + `_HONORIFIC_TOKENS` set; stamped on all 3 persona-dict construction sites + defensive stamp on legacy bridges
- ✅ `_renderPersonaBadgeHTML` updated to use `display_name` with `name` fallback
- ✅ `conv_mode_exit_reminder()` helper + listener `exit_conversation_mode` action handler + `wrap=True/False` on `_inject_via_tmux`
- ✅ Conversation-mode router pushes parallel `action:exit_conversation_mode` notification at displacement time (best-effort)
- ✅ Tests: +7 `TestDisplayNameFor`, +1 pool-stamping, +7 `TestConvModeExitReminder`, +2 listener action tests; updated 3 displacement assertions for new push count

---

## 🩺 POSTMORTEM REMEDIATION FOR USER (Session 31172845, 2026-05-01)

**Plan**: `src/rnd/v0.1.7/2026.05.01-postmortem-fixes-plan.md`
**Execution log**: `src/rnd/v0.1.7/2026.05.01-postmortem-fixes-90-execution-log.md`

### User actions required

- [ ] [LUPIN] **Commit parent-Lupin changes** in this session's manifest (`.claude-session.md` Session 31172845 row). Files: `bug-fix-queue.md`, `history.md`, `TODO.md`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/lupin_cli/notifications/notify_user_sync.py`, `src/tests/integration/test_deep_research_orchestrator.py`, `src/tests/smoke/test_container_preflight.py`, `src/tests/smoke/conftest.py` (NEW), `src/tests/unit/test_*.py` (4 NEW files), `src/rnd/v0.1.7/2026.05.01-postmortem-*.md` (3 NEW files). **CAUTION**: parallel session f742b1bc has its own files in the manifest — use `git diff --cached --stat` to verify only my files staged before commit.
- [ ] [LUPIN-COSA] **Commit CoSA submodule changes** in a separate CoSA session: `src/cosa/rest/todo_fifo_queue.py` (Cluster D defensive reorder), `src/cosa/rest/routers/mock_job.py` (Cluster G presentation routing), `src/cosa/agents/test_suite/job.py` (Cluster B per-suite extra args), `src/cosa/rest/routers/test_suite.py` (Cluster C docstring).
- [ ] [LUPIN] **Schedule next `:8000` all-suite run** to validate fixes (after all commits land + container recreation if needed). Use `POST /api/test-suite/submit` with confirmed scheduled_at. Run `src/scripts/preflight-test-container.sh` from host first (Cluster C workaround).
- [x] [LUPIN] **Pick fix option for Cluster A (notification 503)** — Session 45e6bf84 (2026-05-05 PM). Investigation overturned the May-1 §Phase 5 diagnosis: the proxy DOES support WS-as-test-user (empirical proof — UUID 50c73ba7-... appears in `user_sessions` when proxy runs with the test user's env-var creds). Real root cause was silent proxy-startup failure in `EmbeddedProxyMixin._start_proxy` (5-second blind sleep + `subprocess.poll()`-only liveness check + WARNING-only abort path). Fix shipped as a 4-phase plan: WS-auth verification poll, hard abort across 7 caller sites, label re-classification (`http_error_*` → `infra_error`), full design + execution log at `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/`. Phase 4a `:7999` probes both green; Phase 4b `:8000` smoke verification scheduled.
- [ ] [LUPIN] **Pick architectural option for Cluster C** — see bug-fix-queue.md "Server-side preflight surrogate". 3 options.
- [ ] [LUPIN] **Investigate `claude-agent-sdk` install state** in test container — see bug-fix-queue.md. Reduces 12 integration skips if the SDK is now installed.

### What landed (this session)

- ✅ Phase 0: docs serialized (plan + execution log + skip-count corrections in post-mortem)
- ✅ Phase 1A: smoke skip refactor (preflight: 7 skips → 1 module-level skip)
- ⚠️ Phase 2 (Cluster D): defensive branch reorder + 15 unit tests; **real NoneType.split source still unknown** (filed)
- ✅ Phase 3 (Cluster G): presentation keyword fallback + 12 unit tests
- ✅ Phase 4 (Cluster F): notify_user_sync connect-timeout split + 2 unit tests; **smoke regression GREEN** (idle_waiter test)
- ✅ Phase 5 (Cluster A): root cause identified (filed for design conversation)
- ✅ Phase 1B: 6 obsolete pytest.mark.skip eliminated via test_phase_* → phase_* renames
- ✅ Phase 6 (Cluster B): INI-driven per-suite extra pytest_args + smoke conftest.py (5 flag registrations) + 4 unit tests
- ⚠️ Phase 7 (Cluster C): docstring + filed for architectural decision

**Net impact (when committed + scheduled run lands)**: 9 → ~3-5 smoke failures expected. 51 → ~45 skip count.

---

## 🐛 WS RESTART AUTH CASCADE — User-visible symptom resolved (Session f742b1bc, 2026-05-01)

**Bug doc**: `src/rnd/v0.1.7/2026.04.30-ws-restart-auth-cascade-bug.md` (see §Resolution)

- [ ] [LUPIN] **Land Fix 1 (cosmetic)** — `src/cosa/rest/routers/websocket.py:458-466`. Bug A (mislabeled "Token verification failed" — actually a post-verify send_json failure) + Bug B (cascading send_json on already-closed socket). Log-hygiene only, both <10 line fixes; user-visible symptom is gone but the cascade trace can still appear during a real container restart. Fits v0.1.7 spit-and-polish branch intent.
- [ ] [LUPIN] **What's bumping test file mtimes?** — even with reload now ignoring `tests/`, the underlying question is unanswered: `test_voice_persona_helpers.py` and `test_voice_persona_allocation.py` had mtimes touched at 02:08, 02:14, 09:12 today without anyone running tests. Plausible suspects: backup script, IDE indexer, hook, periodic git op. Not urgent; trace if it surfaces another way.
- [ ] [LUPIN] **Add WS-smoke regression test** (deferred) — simulate 1012 close + reconnect within 5s and assert `auth_success` received. Belongs in `src/tests/websocket_smoke/`. Lower priority now that the user-visible symptom is gone, but still worth the regression coverage.

---

## 📚 HISTORY ARCHIVE — Resolved by parallel session (Session f742b1bc, 2026-05-01)

- [x] [LUPIN] **history.md archival** — peaked at **24,126 tokens (96.5% of 25k limit)** after Session f742b1bc's checkpoint entry pushed it from 22.2k → 24.1k. User declined inline archival; deferred to next session. **Resolved mid-workflow by parallel session 31172845** — produced `history/2026-04-25-to-28-history.md` archive file; history.md now at **12,156 tokens (48.6%, HEALTHY)**. Next session-start should still verify archive looks clean before appending. — Session f742b1bc / handled by 31172845

---

## 🎯 CC SESSION FOCUS MODE — Phase 2 + design follow-ups (Session 488ca8bd, 2026-04-30)

**Plan**: `~/.claude/plans/i-want-to-start-parsed-blossom.md`
**Design**: `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md`

### 🚦 Phase 2 — gated for tonight's :8000 batch (user-coordinated)

- [ ] [LUPIN] **Schedule `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` on :8000** (12 Playwright tests across 7 classes). Submit via `/api/test-suite/submit` with the user-confirmed slot — bundling with the other test work the user is batching this evening. First run will also generate the 4 visual-regression baselines via `--update-snapshots`.
- [ ] [LUPIN] **Capture visual-regression baselines** (`__snapshots__/cc-session-strip-default-stacked.png`, `cc-session-strip-focus-mode-active.png`, `cc-strip-icon-with-conv-mode-overlay.png`, `cc-strip-icon-with-unread-badge.png`) on first scheduled run. Commit baselines after review.
- [ ] [LUPIN] **Add Phase 2 results to `90-execution-log.md`** after the scheduled run completes — pass/fail per test, timing, any flakiness, baseline-capture confirmation.

### 🛠️ Deferred design items (per design `01-design.md` §16)

- [ ] [LUPIN] **Cross-device focus sync** — current design is `localStorage` per-browser. If user wants focus state to follow them between phone + laptop, add `cc_focus_state` field to bridge file (parallel to `conversation_mode_active`) + new `focus_state_changed` WS event. Gate: wait until use case actually emerges.
- [ ] [LUPIN] **Strip overflow strategy** — currently `overflow-x: auto` with thin scrollbar. Revisit only if 8+ active CC sessions becomes routine and the horizontal scroll feels ugly. Alternatives: collapse-to-overflow-menu (hide-overflow + chevron) or two-row wrap.
- [ ] [LUPIN] **Per-card "anchor" pinning** (Q5 option-c from elicitation) — separate small feature. If reorder churn in default-stacked-view (focus mode OFF) still bothers user even with focus-mode escape route, add a per-card pin button so individual cards can be frozen at a stable stack position while others reorder around them.
- [ ] [LUPIN] **Tier 3 / Tier 4 persona theming follow-up** — already on TODO from Session 9977a1ba (held for Round 1 settling). Independent of focus mode but the strip + focus-mode work surfaces the question of how heavily to lean on persona color. Worth a single review pass after living with focus mode for a session or two.

### 🔍 Watch-fors when batch run lands

- The Playwright tests assume `window.notificationsUI._addStripIcon(...)` etc. are accessible from `page.evaluate()`. If these helper-name renames during a future refactor, the tests will need updating in lockstep — note in design doc revision log if so.
- The strip's `overflow-x: auto` will produce different visual rendering across Chromium versions; visual-regression baselines may need re-capture if the test container's Chromium minor version drifts.

---

## 🎤 CONV-MODE 3-LAYER ENFORCEMENT — Phase 6 follow-ups (Session 406cadbf, 2026-04-30)

**R&D**: `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/{01-design.md,90-execution.md}`
**Phases 1-5 status**: ✅ committed (`02af97b` → `d7a6c9f`); 176/176 tests pass; viewer URLs in history.md entry.

### 🚦 Phase 6 — User-gated multi-session live verification

- [ ] [LUPIN] **WebSocket smoke suite full run** — `./src/scripts/run-websocket-smoke-tests.sh` timed out at 120s in the AI-discretionary :7999 venue this session. No conv-mode-relevant assertions in the WS suite, regression risk low (we haven't touched the WS layer or notification routing), but should run as a final regression check before Phase 6 declares closed. User-confirmed slot for the longer run window.
- [ ] [LUPIN] **Multi-session live verification matrix** (10 rows, design doc §4 Phase 6). User confirms before execution: no parallel CC sessions outside the test, conv mode currently OFF on all sessions, :7999 acceptable for dev verification (or :8000 slot if needed). Matrix:
  1. Toggle A on → speak voice msg → A's Claude wraps input + narrates with priority=high
  2. Toggle B on (displaces A) → speak to B → A's bridge=false; A's UI unpinned; A's next turn does NOT auto-narrate
  3. **Cross-talk cue (the original symptom fix)**: A's Claude has cached belief, calls notify(priority=high, suppress_ding=True) after displacement → user hears audible ding (suppress_ding inverted)
  4. Console-only response from A while A is the holder → Layer 3 Stop-hook synthesizes narration
  5. Claude calls notify(priority=medium) while A is the holder → Layer 2 forces priority=high, suppress_ding=True
  6. Legitimate notify(notification_type=alert, priority=high) from a non-conv-mode session → pass-through with ding
  7. set_session_topic("...") while A is the holder → internal-call bypass (topic with original params)
  8. Conv mode OFF → speak voice msg → no wrapper applied (legacy behavior)
  9. Idempotency: conv_mode_wrap called twice on same string → second call no-ops
  10. Voice content containing literal `</voice-message>` or `<system-reminder>` → sanitize_for_wrap truncates from first marker

### 📋 Deferred follow-ups (NOT in scope for Phase 6, logged for future)

- [ ] [LUPIN] **MCP HTTP-fallback mutex bypass** (`src/lupin_mcp/cosa_voice_mcp.py:1295`) — Risk #7 in design doc. When the canonical conversation-mode endpoint is briefly unreachable, the MCP `enter_conversation_mode()` tool falls back to direct `set_conversation_mode()` write with NO scan-and-displace. Both sessions could end up `active=true` simultaneously. Documented limitation; long-term fix requires duplicating router scan-and-displace logic into the MCP server. Escalate if observed in practice.
- [ ] [LUPIN] **Pre/post-tool-use Layer 1 threading** — deferred from Phase 2 because adding the conv-mode reminder per tool call would inject it dozens of times per turn (noisy). Reminder fires at user-prompt-submit (natural turn boundary) only. Revisit if discipline drift is observed at tool-use boundaries.
- [ ] [LUPIN] **Phase 4 test runtime optimization** — `test_stop_hook_auto_narrate.py` ~30s due to lazy-import of `cosa_voice_mcp.strip_fenced_code_blocks` triggering MCP module init (account-validation HTTP). Optimize by extracting the helper to a lighter module without the cosa_voice_mcp import-time side effects.

---

## 🩺 POSTMORTEM FOLLOW-UPS — Session b195a160 (2026-04-30, while user at doctor)

**Postmortem doc**: `src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md`

### ✅ Closed in this session (uncommitted; please review + commit)

### ✅ Postgres bind-mount permanent relocation — DONE (uncommitted)

### ✅ uv.lock regenerated (uncommitted)

### ✅ Image rebuild — DONE (parked at candidate tag, NOT promoted)

### 🚦 Recommended next steps when you're back

1. **Smoke-verify the new image** before promoting: `docker run --rm lupin:1.0.0-bcrypt-4.3.0 /opt/venv/bin/python -c "import lupin"` (or whatever quick health probe you prefer). Bonus: confirm the `(trapped) error reading bcrypt version` log is gone on container start.
2. **Promote the tag**: `docker tag lupin:1.0.0-bcrypt-4.3.0 lupin:1.0.0`
3. **Recompose dev :7999**: `docker compose down lupin-rest-dev && docker compose up -d lupin-rest-dev`
4. **Recompose test :8000**: `docker compose down lupin-rest-test && docker compose up -d lupin-rest-test`
5. Verify each came up healthy + `LUPIN_INTERACTIVE_TESTS=true` is now in the test container env: `docker exec lupin-rest-test env | grep LUPIN_INTERACTIVE_TESTS`
6. After step 5, the Tier 3 follow-ups below should become CLOSED automatically.

### ✅ Tier 1 closures — DONE this afternoon (uncommitted)

### ✅ Tier 2 closures — DONE this afternoon (uncommitted)

### 🐳 Tier 3 — STATUS UPDATE (some closed, one pending verification)

- [ ] [LUPIN] **Cluster I config audit — `presentation_generator` agentic-router registration** — **STILL OPEN, awaiting tonight's all-test-run verification**. After today's recompose, re-run will tell us whether `EXP_PRES_MISSING` still returns "Could not match voice command". If yes → agentic-commands.json reload issue. If no → recompose closed it cleanly.

### 🐢 NEW: slow-test rewrite (DONE this afternoon, uncommitted)

### 🆕 New follow-ups — for the user (NOT applied this session)

- [ ] [LUPIN] **(Cluster J adjacent) Investigate why `:7999` cannot reach `192.168.1.21:3001`** for the runtime-argument expediter's LLM. The :8000 test container CAN reach it (yesterday's run got past the LLM call). Worth checking if a service is supposed to be running at `192.168.1.21:3001` for dev workflows.
- [ ] [LUPIN] **(Architectural) Per-test-file `pytest_args` declarations** — surfaced from Cluster D investigation. The all-suite scheduler doesn't know that `test_presentation_live*` always need `--auto-proxy --cost-cap-usd N`. Idea: declare via a pytest marker that the scheduler reads + merges. Bigger change; deferred.
- [ ] [LUPIN] **(Hygiene) `TODO.md` triage — CRITICAL** — at **31,518 tokens (126% of 25k limit)** with **199 pending items** as of Session 6562a2c9 session-start (2026-05-01). Many items likely already complete from yesterday's bug-fix-mode + post-mortem cycles. Triage pass: scan top sections, mark resolved items as `[x]` with attribution, prune Completed-section entries older than 7 days. Target: bring file under 12k tokens (8-12k retention range per history-management workflow). Surfaced but deferred at user direction during Session 6562a2c9.
- [ ] [LUPIN] **(Verification) Review the 21:30 EDT all-test-run outcome** — `ts-0fb8e488` scheduled for 2026-04-30T21:30:00-04:00. Expected delta vs yesterday's 15-failure baseline: 5–6 failures. Closes Tier 3 follow-ups if predictions hold.

---

## 🎨 PERSONA POOL — Arnold color tweak

- [ ] [LUPIN] **Repaint Arnold from dark red → orangey-peach** — current dark-red Arnold is indistinguishable from both Nora's pink-300 (`#F06292`) and Domi's pink-900 (`#880E4F`) backgrounds at low alphas in Tier 1 chrome. Goal hue family: peach / coral / orange-pink (e.g. Material orange 300 `#FFB74D`, deep-orange 200 `#FFAB91`, or a custom warm-peach `#FFAB6E`). Audit against `feedback_no_green_in_persona_pool` (peach is fine — green RGB component stays well below 30%). Update `src/conf/lupin-app.ini` persona pool entry + splainer note + any hard-coded references.

---

## 🌅 FOLLOW-UPS — for the user (Session 9977a1ba — Persona Theming Round 1 + WS cleanup)

- [ ] [LUPIN] **Persona theming Round 2 — Tier 3 widgets**: tint `.sender-conversation-mode-btn` border (when not in active conv-mode green), `.sender-gist-btn` border, `.cc-voice-input-row` chrome with `var(--persona-color, ...)`. Held until you've lived with Round 1 (Foundation + Tier 1 + Tier 2) for a session.
- [ ] [LUPIN] **Persona theming Round 3 — Tier 4 outgoing message bubbles**: replace bootstrap-blue `#007bff` outgoing-bubble background with `var(--persona-color)`. Boldest change, held for explicit go-ahead.
- [ ] [LUPIN] **frontend-design plugin polish pass** against live `:7999` after Round 1 settles. The plugin is installed but I haven't invoked it yet — a clean fit for distributing one persona color across many surfaces without it feeling overdone.
- [ ] [LUPIN] **UserPromptSubmit hook to backstop conv-mode acknowledge-receipt rule**: ~15-line hook script alongside `src/lupin_cli/claude_code/hooks/`; reads bridge file, if `conversation_mode_active` is true, emit a `<system-reminder>` block reminding Claude to ack receipt before tool work. Architecture sketched in this session, not implemented. Real-time enforcement complement to the existing static-doc layers.
- [ ] [LUPIN/CoSA] **Commit the CoSA-side companion edits** for this session's Lupin work, from inside CoSA context: (a) `src/cosa/rest/routers/voice_persona.py` + `conversation_mode.py` migrations to `push_notification`, (b) `src/cosa/rest/notification_fifo_queue.py` `payload` field addition, (c) `src/cosa/rest/routers/notifications.py` `valid_types` extension + senders-visible voice_persona stamping, (d) `src/cosa/rest/routers/speech.py` Rachel-voice-id sentinel fix.
- [ ] [LUPIN] **Existing Rachel session bridges retain old color** until released and re-allocated (color is copied into bridge at allocation time). To force the new `#7B1FA2` purple immediately on an active Rachel session, `/release` then `/allocate`.

---

## 🌅 FOLLOW-UPS — for the user (Session 78abd1aa — passlib/bcrypt mismatch)

- [ ] [LUPIN] **Rebuild `lupin:1.0.0` docker image to land `bcrypt==4.3.0`** — `pyproject.toml:69` tightened from `bcrypt>=4.0,<5` to `bcrypt==4.3.0`; `uv.lock` already pins 4.3.0; running container is on 5.0.0 only because it was built from an older lock state. Per `feedback_no_auto_promote_tags`, park the rebuild at a candidate tag (e.g. `lupin:1.0.0-bcrypt-4.3.0`) and don't overwrite the working `lupin:1.0.0` until verified. After rebuild: (a) confirm `(trapped) error reading bcrypt version` no longer fires on container startup logs, (b) re-run unit + smoke on `:7999`, (c) schedule integration suite on `:8000` to re-run the now-unxfailed `test_list_users_search_filter` and `test_update_user_roles_remove_admin` from `src/tests/integration/test_admin_users.py`. Plan: `io/plans/2026.04.29-bcrypt-passlib-version-mismatch-plan.md`.

---

## ✅ COMPLETED — Session c7333045 (2026-04-28, all-day mixed bug fix + feature work)

- [x] [LUPIN] **Bug A: Duplicate "Received:" echo** — `WebSocketManager.emit_to_user_or_listener_sync()` listener-already-in-user-fanout dedup guard. Verified live on listener log: 2 events → 1 event per voice message.
- [x] [LUPIN] **Bug B: Stop-hook gate on conversation mode** — `stop.py::main()` early-emit `{}` when `get_conversation_mode(session_id)=True`. 2 new unit tests covering both directions.
- [x] [LUPIN] **Bug: 404 from container PID-namespace** — `find_session_path_by_id` now skips `_is_pid_alive` when running in container (`/.dockerenv` exists).
- [x] [LUPIN] **Bug: UI toggle position** — moved sender-conversation-mode-btn from sender-card-header into cc-voice-input-row alongside record button.
- [x] [LUPIN] **Bug: Duplicate Lupin/Cosa pane for one session** — `build_sender_id_for_cc()` now anchors on bridge SessionStart cwd snapshot via new `_resolve_project_from_bridge_cwd()` helper. 6 new regression tests.
- [x] [LUPIN] **Feature: Corner pause button** on currently-playing notification — absolutely-positioned `.notification-corner-pause-btn`, click routes through `pauseTTS()`/`resumeTTS()` (Web Audio AudioContext-aware).
- [x] [LUPIN] **Feature: Mutex + pinning across CC sessions** (5 phases of `~/.claude/plans/drifting-skipping-porcupine.md`) — coordinated bridge files, asyncio.Lock auto-displace, `displaced=true` WS payload, in-flight TTS auto-pause, soft-glow border, sort-respecting card insertion. MCP `_flip_conversation_mode` refactored to call canonical HTTP endpoint with HTTP fallback to direct write. User-only-initiation guardrail in 3 layers (instructions block + tool docstrings + new global skill).
- [x] [LUPIN] **EmbeddingProvider HTTP-routing refactor** — `_is_in_process_engine_owner` flag + `declare_in_process_engine_owner()` classmethod, FastAPI startup wires it, runtime URL via `_resolve_server_url()` reading `LUPIN_APP_SERVER_URL` per-call. 16 new tests across 4 new test classes. SolutionSnapshot init requires zero changes.
- [x] [LUPIN] **History archive** — `2026-04-22-to-24-history.md` created (~10k tokens). Main file 21,442 → 9,889 tokens.

## 🌅 FOLLOW-UPS — for the user (Session c7333045)

- [ ] [LUPIN] **Per-session TTS queue isolation** (so B's new audio plays while A's queued audio stays paused on displacement) — current model is global `pauseTTS` on displacement, user manually resumes. Separate UX cycle.
- [ ] [LUPIN] **Toast UI for displaced sessions** — `conversation_mode_changed` event payload already carries `displaced=true, displaced_by=<sid>`; UI just doesn't render it yet.
- [ ] [LUPIN] **Hard programmatic enforcement of user-only-initiation rule** for `enter/exit_conversation_mode()` MCP tools — v1.1 documents the rule in three layers; future enhancement could add a "user-utterance attestation" field on the MCP call if drift is observed.
- [ ] [LUPIN] **E2E Playwright extension for new mutex + pinning + auto-pause scenarios** — gated behind a user-confirmed `:8000` slot per the E2E two-phase gate.
- [ ] [LUPIN] **Multi-worker uvicorn lock coordination** — module-level `asyncio.Lock` in conversation_mode router only serializes within one process. If Lupin ever moves to `--workers N`, lock must move to Redis or DB advisory lock. Not relevant today.
- [ ] [LUPIN] **Make LanceDB cleanup a schedulable evening job on the test server** — wrap `src/scripts/cleanup_lupin_lancedb.py` (the existing `Table.optimize(cleanup_older_than=...)` script that recovered 42 GB on 2026-04-27) as a `test_suite/job.py`-shaped schedulable agentic job, runnable nightly via `POST /api/test-suite/submit` with a `scheduled_at` slot. Constraint: must run on `:8000` test server (monopolize-mode) so it doesn't fight with active writers — script already accepts `--require-stopped` flag, but a scheduled wrapper should also call the canonical `_transition_to_done`/`_transition_to_dead` paths and emit completion notifications. Default cutoff `--older-than-days 7` (conservative); operators can override per-submission. Acceptance: nightly schedule runs, logs version counts before/after, surfaces total disk reclaimed in completion notification, fails fast if the test container has active LanceDB writers.

---

## 🌅 FOLLOW-UPS — for the user (Session 30072c25 — per-session voice personas)

- [ ] [LUPIN] **Experience the new persona-driven UX end-to-end** — spawn 3 concurrent `claude code` sessions in different terminals, trigger a notification from each, and confirm: (a) three distinct voices speak via TTS, (b) three distinct colored badges render in the notifications-UI sender-card headers (icon + persona name + tinted background), (c) badges persist across `/clear` (no re-roll). This is the perceptual end-to-end check the test pyramid cannot automate. Design + verification matrix at `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` and `90-execution.md`.

---

## 🌅 FOLLOW-UPS — for the user (Session 30072c25 — docker build diagnostics)

- [ ] [LUPIN] **(Optional) Route uv.lock R&D doc to external `uv` expert** — open questions (in the doc itself): did `pydantic-ai==0.6.2` ever expose a `slim` extra? did `uv` tighten extras-validation between lock-time and sync-time? should we file a `uv` bug for the lock-writer-accepts-impossible-extras inconsistency? **Lower priority now** that the build is unblocked, but the questions remain interesting for `uv` toolchain governance.

---

## ✅ COMPLETED — Session ba7138c4 (2026.04.28, all-day test-suite anomaly remediation)

- [x] [LUPIN] **WG-1 docker image rebuild + retag** — `lupin:1.0.0-fonts` built, both containers recreated, retagged to `:1.0.0` after visual-regression verification.
- [x] [LUPIN] **WG-8a orphan + dead-Calculator cleanup** — user manually nuked.
- [x] [LUPIN] **`:8000` verification re-run (ts-976bdc44)** — 4524P / 15F / 12E / 54S, completed cleanly.
- [x] [LUPIN] **WG-6 survivor verification** — both `test_notification_proxy_script_matching` and `test_tfe_error_capture_smoke` STILL FAIL → OOS-3 trigger confirmed.
- [x] [LUPIN] **OOS-4 hotfix Parts A + B** at `src/cosa/rest/running_fifo_queue.py:276,294`.
- [x] [LUPIN] **CalculatorAgent codeless replay fix** at `src/cosa/memory/solution_snapshot.py:run_code()` — user's intuition confirmed.
- [x] [LUPIN] **dev/test container parity fix** — added `~/.lupin` + `~/.claude/sessions` bind mounts to `lupin-rest-test`. Plus seeded `claude.code@lupin.deepily.ai` into `lupin_db_test`.
- [x] [LUPIN] **WG-9 forward-compat breadcrumbs** — splainer note + `_delegate_to_predictor()` stub + `05-voice-gate-policy-evolution.md`.
- [x] [LUPIN] **All 4 OOS plans drafted with prewarm forensic findings**.
- [x] [LUPIN] **Orchestration plan** at `04-execution-orchestration.md`.

## 🌅 FOLLOW-UPS — for the user (Session ba7138c4 follow-on)

- [ ] [LUPIN] **READ `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/06-resume-from-here.md` FIRST** if returning after `/clear`.
- [ ] [LUPIN] **Schedule e2e baseline regen run** — `POST /api/test-suite/submit { test_types: "e2e", pytest_args: "--update-snapshots -k visual", scheduled_at: <slot> }`. Container chromium renders subtly different from host; baselines need to lock to container rendering.
- [ ] [LUPIN] **Investigate 13 surviving smoke FAILs** — real agent failures (not infra). Includes `test_calculator_live_pipeline` which should now PASS via codeless-replay fix; needs re-run to confirm.
- [ ] [LUPIN] **Ratify OOS-3** — both WG-6 survivors confirmed STILL FAIL.
- [ ] [LUPIN] **Ratify OOS-1/2/4** — prewarm findings folded into the plan docs. OOS-1's Finding A is a one-line typo at `test_fix_expediter/job.py:549`; standalone hotfix candidate.
- [ ] [LUPIN] **CoSA submodule commit** — running_fifo_queue.py + solution_snapshot.py (this session) + 6 prior CoSA edits from c4e5d4f. Separate cosa-context session per `feedback_lupin_only_never_cosa`.
- [ ] [LUPIN] **Push parent commits** — `bb9298c` + this checkpoint pending.
- [ ] [LUPIN] **(Optional) flip TFE voice-gate timeout policy to `top_1`** for after-hours autonomous runs.
- [ ] [LUPIN] **Memory update**: expand `feedback_never_grab_gpu.md` with SolutionSnapshot constructor warning (loads ~1 GB of embedding models on cuda:0).
- [ ] [LUPIN] **T46 — delete deprecated `enter_running_loop()`** in `src/cosa/rest/running_fifo_queue.py:122` (~30 LOC; user authorized for after current job).

## 🌅 FOLLOW-UPS — for the user (Session d34f2f74 — Idle-aware Stop hook)

- [ ] [LUPIN] **Activate idle-aware Stop hook** — start a fresh CC session; the new hooks load at session boot, so this current session keeps the legacy immediate-ask behavior in memory until exit. Defaults `enabled=true, backoff_minutes=[5,10,20,40,60]` apply automatically. To override, add an `idle_detection` block to `~/.claude/settings.json` (schema in `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md`).
- [ ] [LUPIN] **Manual end-to-end checklist for idle-aware Stop hook** (post-merge verification) — see `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/90-execution.md` Phase 5 checklist (8 steps): set test schedule `[1, 2, 4]` in settings, verify "Anything else?" fires after 1 min idle, "no" advances backoff_index, prompt fires again at 2 min, user prompt resets to 0, conversation-mode skips ask. Restore default schedule afterward.
- [ ] [LUPIN] **Optional: add `~/.claude/CLAUDE.md` notification-system note for idle detection** — Phase 5 deferred this as out-of-scope (global file, cross-project risk). User can add a brief note themselves if desired.

## 🌅 FOLLOW-UPS — for the user (Session d34f2f74 — Phase 4 backlog completion)

- [ ] [LUPIN] **Migrate other 7 agent types to ContextVar dispatch** — DR done in Phase 4 backlog #1; Podcast / ClaudeCode / BFE / R2P / Presentation / R2Presentation / TestSuite still use legacy `cosa_interface.SENDER_ID = ...` module-global pattern. Dispatcher ContextVar resolvers already prefer ContextVar over self.* — each agent just needs to add a `set_dispatch_context()` helper to its `cosa_interface.py` and call it from `job.py` at execution start. Per-agent diff is ~15 LOC.
- [ ] [LUPIN] **Cleanup: 124+ stale `*-integration-e2e-remediation.json` files in `io/test-suite/`** — these are unit-test side-effect leakage from `test_artifacts_populated` writing to real filesystem before the 2026-04-29 fix. Safe to bulk-delete since the fixed test now uses `tmp_path`. Suggested: `find io/test-suite -name "*-integration-e2e-remediation.json" -mtime +1 -size -5k -delete` (the bogus files are <2KB; real production runs from test_suite agent are much larger). User discretion — historical inspection value is low.
- [ ] [LUPIN] **Container recreation needed** — cluster 2.7 fix (`LUPIN_INTERACTIVE_TESTS=true` in docker-compose.yml) requires `docker compose down && up -d` to take effect. `docker restart` doesn't pick up env-var changes. Same recreation will activate Phase 4 backlog item 2 fix (consumer-stalls heartbeat refresh).
- [ ] [LUPIN] **Recreate test+dev containers to pick up new `LUPIN_INTERACTIVE_TESTS` env var** — added to `docker-compose.yml` in cluster 2.7 fix. `docker restart` does NOT pick up env-var changes; need `docker compose down && docker compose up -d` (or `docker rm -f <name>` + `docker compose up -d`). Without recreation, `test_swe_team_proxy` will continue to self-abort even though the docker-compose.yml is correct.

---

## 📦 Cross-project — `planning-is-prompting` follow-up

- [ ] [LUPIN→PIP] **Phase 1: Lift adversarial+fitness review prompts into PIP** — author `planning-is-prompting/workflow/plan-review.md` from the spec in `src/rnd/v0.1.7/2026.04.27-promote-plan-review-pattern-to-pip.md` (§ "Phase 1 deliverable shape"). Pick up in a `planning-is-prompting`-rooted Claude session. Phase 2 (convention establishment in `p-is-p-02-documenting-the-implementation.md`) is the linchpin and must follow Phase 1 immediately.

---

## ✅ COMPLETED — Session aabece5e (2026-04-27, late evening)

- [x] [LUPIN] **Conversation mode for Claude Code (cosa-voice MCP)** — per-session toggle that, when on, makes Claude auto-`notify(full_text, suppress_ding=True)` after every turn so the user can hold a voice dialogue at a distance without re-prompting. Pattern 3 Feature Dev, ~1 week scope, executed end-to-end via plan-then-auto-mode. Four convergent activation surfaces: voice phrase ("enter/exit conversation mode" pattern-matched in cosa-voice server-instructions), slash command (`/conversation-mode-on` / `/conversation-mode-off`), MCP tool (`enter_conversation_mode()` / `exit_conversation_mode()`), UI toggle button (📞/🔔 in sender-card header). Server-canonical state in `~/.claude/sessions/cc-{PPID}.json` bridge file (extends existing schema with `conversation_mode_active: bool`). WebSocket `conversation_mode_changed` event broadcasts toggle changes to all UI tabs of the authenticated user via `emit_to_user()`. New router `src/cosa/rest/routers/conversation_mode.py` (CoSA-side per existing convention — plan deviation logged because `src/fastapi_app/routers/` doesn't exist). Bind-mount fix added live: `:7999` Docker container had no `~/.claude/sessions/` mount; added rw mount in `docker-compose.yml` and recreated container. 23 new pytest tests across 3 files, 52/52 pass. R&D doc at `src/rnd/v0.1.7/2026.04.27-conversation-mode-design.md`.

## 🌅 FOLLOW-UPS — for the user (no urgency, conversation mode work)

- [ ] [LUPIN] **Phase 6 E2E execution** — `src/tests/e2e_ui/test_conversation_mode.py` is written but not submitted. Schedule via `POST /api/test-suite/submit` with non-overlapping `scheduled_at` slot once `:8000` is free.
- [ ] [LUPIN] **Bind mount `~/.claude/sessions` on `:8000` test container** — only added to `:7999` dev today. The Phase 6 E2E run on `:8000` will need the same mount or the endpoint will 404. Add to `docker-compose.yml` line ~108 (lupin-rest-test volumes block) before scheduling Phase 6.
- [ ] [LUPIN] **CoSA submodule commit** — new file `src/cosa/rest/routers/conversation_mode.py` waits for separate CoSA-side commit per nested-repo rules.
- [ ] [LUPIN] **Watch for discipline drift in Option B** — design accepted MCP-tool + behavioral-instruction approach (Option B) over a deterministic Claude Code stop hook (Option C). If Claude consistently forgets to auto-`notify()` after every turn when conversation mode is on, escalate to Option C as belt-and-suspenders (PostAssistantTurn hook reads bridge flag and POSTs to TTS endpoint).
- [ ] [LUPIN] **Live UX validation** — actually USE conversation mode for a prolonged voice dialogue from the notification UI session pane to validate the ergonomic and the TTS hygiene defaults (strip code blocks, skip tool-call narration, no length cap). Tune defaults if needed.
- [ ] [LUPIN] **Manifest-tracking discipline** — this session never updated `.claude-session.md` while editing files; surfaced at session-end as a missing section. Worth a future session to either bake manifest-update into the auto-mode flow or relax the manifest mandate when auto-mode is the only writer.

---

## ✅ COMPLETED — Session 49c27830 (2026-04-27, afternoon — Bug Fix Mode)

- [x] [LUPIN] **Notification dispatch unification — extracted `WebSocketManager.emit_to_user_or_listener_sync` + migrated 5 sites** — Started from a USER-REPORTED bug (3 user-initiated messages from the LookML CC notifications panel UI silently dropped because `notify_user` short-circuited on `is_user_connected(target_system_id)=False` even though the `cc-listener-{job_id}` was active under a different shared service-account user_id). Day's arc: narrow fire-and-forget fix (5 unit tests) → comprehensive audit found 6 dispatch sites with duplicated logic and 2 sites missing the listener fallback entirely → planned full unification (`~/.claude/plans/dazzling-napping-frost.md`) → executed Phases A-F. Helper added at `src/cosa/rest/websocket_manager.py` as a sibling to the canonical `emit_to_user_and_admins_sync` precedent. Migrations: (1) `notify_user` fire-and-forget — replaced narrow inline fix with helper; (2) `notification_expired` SSE-timeout broadcast — gained listener fallback; (3) `notification_responded` response-submission broadcast — gained listener fallback; (4) `send_job_message` (queues.py) — collapsed 40-line dual-emit; (5) `_emit_notification_added` (notification_fifo_queue.py) — collapsed targeted-user + listener emits. Result: zero `emit_to_session_sync` calls remain in 3 migrated routers (helper is single chokepoint). Lupin unit suite 3672/0 fail (was 3638 → +34 tests across A-E). Wrapped yesterday's 7-test fix entry in bug-fix-queue.md. Files: CoSA × 4 (websocket_manager.py + 3 routers + notification_fifo_queue.py — separate user commit), Lupin × 3 (test_websocket_manager_dispatch.py NEW, test_notify_cc_listener_fallback.py UPDATED, bug-fix-queue.md / history.md).

## 🌅 FOLLOW-UPS — for the user (notification dispatch work)

- [ ] [LUPIN] **Bounce :7999 (and later :8000) onto the new bytecode** when v1.0.0 image rebuild is settled — the helper + 5 migrations are backwards-compatible but currently unloaded. Once bytecode is live, run the live :8000 probe from the plan's "Verification" section to confirm `delivered_via_listener` end-to-end.
- [ ] [LUPIN] **CoSA submodule commit** — 4 files (`websocket_manager.py`, `routers/notifications.py`, `routers/queues.py`, `notification_fifo_queue.py`) wait for separate CoSA-side commit per nested-repo rules. Plan + diagnosis lives in `~/.claude/plans/dazzling-napping-frost.md`.
- [ ] [LUPIN] **TFE/BFE post-resume proposal-review UX** — filed in bug-fix-queue.md. End-user can't make a proper accept/reject determination on proposed fixes after clicking Resume from Checkpoint; needs WHY-context per proposal, clustering, per-proposal skip vs full cancel, confidence levels.
- [ ] [LUPIN] **`:7999` uvicorn StatReload watcher recovery** — watcher hasn't fired in 24+ hours despite source touches that should trigger reload. Bouncing recovers it but the underlying mute is unresolved. Worth investigating before next `--reload`-dependent work.
- [ ] [LUPIN] **CC listener answer-response wiring** (out-of-scope feature) — CC listeners receive response-required notifications (yes/no, multiple_choice, open_ended) via the now-unified dispatch but cannot ANSWER them — no callback wiring exists between the listener and `/api/notify/response`. Filing for visibility; would unlock cross-user yes/no flows.
- [ ] [LUPIN] **Service-account → operator routing helper** — the `agent_notification_dispatcher._resolve_routing` pattern (orthogonal to today's user-or-listener helper) handles service-account → operator email swaps. Refactoring it into a shared utility alongside the new dispatch helper would eliminate another thread of dispatch ad-hoc-ery.

---

## ✅ COMPLETED — Session 09f4c557 (2026-04-27, evening)

- [x] [LUPIN] **Docker image hygiene + rebuilds — 130 GB → 31.6 GB** — Tier 0+1 (Python 3.13.7 + uv-managed venv + uv sync vs 20+ pip layers + BuildKit cache mounts), cuda-compat-12-4 purge fix (CUDA Error 804 on consumer RTX 4090s), drop recursive chown (single USER rruiz switch + --chown= per COPY + uv-cache mount uid retarget), audioop-lts fix (pydub on Python 3.13). Three rebuilds across the day: 130 → 72 → 31.6 GB. lupin:1.0.0 promoted to the audioop-fixed build. New artifacts: `pyproject.toml`, `uv.lock`, `docker/lupin/scripts/patch-pytest-playwright-visual-snapshot.py`. Plans serialized to `src/rnd/v0.1.7/`.
- [x] [LUPIN] **docker-compose.yml pinned both services to `lupin:1.0.0`** (lines 34 + 93) — dev :7999 + test :8000 bounced onto new image, both healthy. lupin:0.9.0 retained as fallback.
- [x] [LUPIN] **Lance DB cleanup script** — `src/scripts/cleanup_lupin_lancedb.py` created (uses `tbl.optimize(cleanup_older_than=...)` — modern combined compaction+cleanup API). First run with 7-day cutoff reclaimed 16.67 GB (43.4 → 26.7 GB). Pre-cleanup backup deleted after smoke tests. Script later refactored to default `--older-than-days 1` and dropped per-script backup function (Lupin has nightly ecosystem-level backups).
- [x] [LUPIN] **Disk cleanup**: removed 6 unused images (genie-in-the-box 0.6/0.7/0.8, peft 0.2/0.3, hf-tgi), 25 zombie containers, 84 GB build cache. /mnt/DATA01: 78 GB → 93 GB free.
- [x] [LUPIN] **Memory feedback rules added**: `feedback_no_auto_promote_tags.md` (park rebuild outputs at candidate tag), `feedback_backups_only_to_dedicated_drive.md` (per-script backups → dedicated drive only).
- [x] [LUPIN] **Dockerfile follow-up: added `COPY --chown=rruiz:rruiz src/lupin_cli /var/lupin/src/lupin_cli`** — lupin_cli was missing from COPY list (production worked because of bind-mount; image isn't self-contained without it). Takes effect on next rebuild.

## 🌅 FOLLOW-UPS — for the user (no urgency)

- [ ] [LUPIN] **Tonight's full test suite run on lupin:1.0.0** — user plans to run all tests this evening to validate the new image under realistic load. Surface any new regressions (especially additional Python 3.13 incompats lurking in import chains we didn't exercise during sanity boots).
- [ ] [LUPIN] **Provide dedicated backup drive's mount path** — when convenient. Future maintenance scripts that do need to back up will default there. `feedback_backups_only_to_dedicated_drive.md` captures the policy.
- [ ] [LUPIN] **Tier 2 / Tier 3 docker hygiene (rainy day)** — multi-stage builder/runtime split (drops cuda-toolkit-12-4 from runtime, ~6 GB saved); HF models via runtime mount / GCS-FUSE (~13 GB saved); pinned base-image digest + Renovate; checksum-pinned d2/MARP/Claude Code installers; BuildKit secret mounts for `src/conf/keys`. Captured as out-of-scope in `src/rnd/v0.1.7/2026.04.27-drop-recursive-chown-image-bloat-audit.md`.
- [ ] [LUPIN] **Periodic / scheduled lance cleanup** — wire `tbl.optimize(cleanup_older_than=timedelta(days=1))` into FastAPI lifespan as a daily background task. Integration point: `src/fastapi_app/main.py:388` alongside existing `clock_loop`, `websocket_heartbeat_loop`, `websocket_cleanup_loop`. Adds INI key like `solution snapshots cleanup older than days = 1`.

---

## ✅ COMPLETED — Session 6c798a07 (2026-04-25)

- [x] [LUPIN] **Podcast generator completion abstract — clickable URLs** — Listen routes to in-app `/app/audio` player page (HTML5 player + script subtitle + embedded download); Download → `/api/io/file?path=...&download=true`; View Script → `/app/docs?path=...`. Path-normalization helper `_to_rel()` handles abs / `io/` / `/` input shapes, mirrors `presentation_generator/job.py` pattern. Artifacts now store relative paths (UI job-card consumption). 6/6 podcast completion unit tests pass + 26/26 broader podcast-related. **Code in CoSA submodule** (managed separately): `src/cosa/agents/podcast_generator/job.py`. **Parent Lupin**: `src/tests/unit/test_podcast_completion_report.py` (test updates + new parametrized normalization test).
- [x] [LUPIN] **History archive** — 24,283 → 11,715 tokens (97.1% → 46.8%); created `history/2026-04-14-to-21-history.md` (12 sessions, 12,979 tokens); index updated.

---

## 🌅 FIRST THING IN THE MORNING — 2026-04-25

**Review evening test runs** (both scheduled before user stepped away):

1. **`ts-e81ca54c`** (submitted 17:42 EDT for 17:44 EDT) — `e2e --update-snapshots -k visual` regeneration. Rewrites the 12 stale visual-regression PNG baselines under `io/test-suite/visual-baselines/test_visual_regression/test_visual_page/`. On completion, the baselines are current against Phase 2+fix code. Check `docker exec lupin-rest-test tail -30 /tmp/e2e-ui-latest.log` for exit code.

2. **`ts-4139484f`** (Phase 3 validation run, scheduled 17:49:24 EDT against freshly-bounced :8000 carrying Phase 3 code at commit `2379233`) — full `e2e,integration` gate. Expected: 0 failures in integration (dispatcher test now accepts both cosa_mcp variants per 17:40 fix); 0 failures in e2e (Opus→Sonnet fix from 14:40 + fresh visual baselines from ts-e81ca54c).

   If Phase 3 gate is green → v0.1.7 async-pool ready for PR/merge.
   If new failures appear → investigate vs Phase 2 baseline (today's 17:19 EDT TFE report saved at `io/swe-team/reports/interactive.job.tester@lupin.deepily.ai/2026.04.24-at-17:19-EST-ts-ff11fb27-completed-test_fix_expediter-report.md`).

3. **Decision on prod `N=1 → N=3` bump** — separate deliberate action after morning review. Edit `[Lupin: Baseline]` from `= 1` to `= 3`, redeploy.

4. **Pre-flip FIFO audit** (8-step checklist in `92-phase-3-execution-log.md §F.1–F.8`) — required before prod bump. Grep for tests implicitly assuming "queue size 1" or "first-submitted is first-done"; categorize low/med/high; re-verify under N=3 dev.

5. **Deferred items** (non-gating, pick up as bandwidth allows):
   - 9 Phase 2 MVP unit tests still deferred (see `91-phase-2-execution-log.md` Step 2.4 rationale)
   - DR `cli.py::estimate_total_time` migration — dev utility only
   - Visual regression: commit the regenerated baselines if the tool stores them under a gitignored path (`io/test-suite/visual-baselines/`) they don't get committed; if under `src/tests/e2e_ui/__snapshots__/` they need commit. Check which path was written.

---

## 🔥 SESSION 616112aa — COMPLETE WORK (2026-04-24)

---

## 🔥 IN FLIGHT — Session 616112aa 2026-04-24

- [ ] [LUPIN] **`:8000` E2E UI gate** — re-submission `ts-249d0d40` running since 11:18:38 EDT (after bounce of stale `:8000` that was still running pre-Phase-1 code). ~40min runtime.
- [ ] [LUPIN] **`:8000` integration gate (FINAL)** — runs after E2E. ~20min.
- [ ] [LUPIN] **:8000 Phase 2 gate in flight** — ts-ff11fb27 fired 15:59 EDT against Phase 1+2+fix. Results pending. Will interpret for Phase 2 validation.
- [ ] [LUPIN] **:8000 Phase 3 re-run** (conditional) — only if Phase 2 gate is green AND conservative-re-run is desired. Phase 3 adds non-test-visible behaviour (ghost sweeper runs silent, DR path not hit by E2E, pool-status endpoint not hit by E2E). Low value; probably skip.
- [ ] [LUPIN] **v0.1.7 prod N=1 → N=3 bump** — separate deliberate action after :8000 gates validate. Not part of this session.
- [ ] [LUPIN] **Receptionist agent multiple issues** — filed 2026-04-24 in bug-fix-queue.md (active queue). Context-length overrun + BFE filter + classifier miss. Not a Phase 1/2/3 regression.
- [ ] [LUPIN] **DR cli.py estimate_total_time migration** — deferred from Phase 3. Dev utility, not production critical. Follow-up when convenient.

---

## ⚠️ SURFACED THIS SESSION — investigate in Phase 2 or follow-up

- [ ] [LUPIN] **`:7999` CPU hot loop (pre-existing)** — PID 2453 at 100% CPU for 108min of CPU time over 2h wall; consistent with 2026-04-22 TODO "push_job takes 60-200s in test env". Not a Phase 1 regression (`test_phase2_shaped_stress` proves RLock is deadlock-free). Phase 2's dispatcher refactor will touch this surface — may root-cause as a side-effect.
- [ ] [LUPIN] **Calculator live pipeline failing 0/6 on `:7999`** — all "Timeout after 120s"; 13 stale dead-queue entries with `status: pending` + empty error field (odd). Related to the `:7999` CPU issue above. Surface as a Phase 2 diagnostic target.
- [ ] [LUPIN] **`:7999` `uvicorn.run(reload=True)` may not actually reload** — process tree shows no watcher+worker split; PID 2453 elapsed time monotonically increases with no reset visible through 11 code edits this session. Either uvicorn reload isn't firing despite `LUPIN_ENV=development` setting `reload=True` in `main.py:828`, or it's reloading in-place. Needs a controlled experiment next session to confirm. If reload isn't working on `:7999`, the operational assumption baked into `feedback_fastapi_auto_reload` memory needs revisiting.

---

## 🎯 NEXT MILESTONE — Phase 2 (after Phase 1 merge)

- [ ] [LUPIN] **Read `src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/03-phase-2-dispatcher-pool-and-pool-status.md`** (design) + `91-phase-2-execution-log.md` (paired log skeleton)
- [ ] [LUPIN] **Phase 2 scope**: dispatcher refactor, `ThreadPoolExecutor` for agentic pool, `Future.add_done_callback` for completion handling, `/api/queue/pool-status` endpoint, defensive callback ghost-job protection
- [ ] [LUPIN] **Phase 2 blocks Phase 3 (ghost-job watchdog + full E2E + FIFO-audit)**

---

## 🌅 SESSION-CLOSE BRIEFING — 2026-04-22 Session 6a30b98c

### Landed this session

- ✅ [LUPIN] **E2E pause-button test fixed** — Playwright `data=<dict>` → `data=json.dumps()` + `Content-Type: application/json` header (FastAPI was silently dropping `scheduled_at` to defaults); all 14 `datetime.now().isoformat()` sites replaced with `datetime.now(timezone.utc)` to eliminate host-EDT/container-UTC mismatch.
- ✅ [LUPIN] **E2E admin cross-user retry test fixed** — seeded question "Other user failed job for admin retry test" routed to Claude Code → triggered UPE 180s blocking dialog. Reseeded with "What day is it today" (routes to DateAndTimeAgent, no UPE); test calls `/retry` directly via `admin_page.request.post()`; disabled `similarity confirmation enabled` in `[Lupin: Testing]` block to belt-and-suspenders against the 30→60→120s snapshot-confirmation path.
- ✅ [LUPIN] **E2E admin-users visual regression drift fixed** — extended `NORMALIZE_DYNAMIC_CONTENT_JS` to normalize `formatDate()` relative-time cells (CREATED, LAST LOGIN) in the admin-users table so snapshots are stable across runs.
- ✅ [LUPIN] **Integration UUID fixture cast** — dropped `::text` from `gen_random_uuid()::text` against a UUID column in `test_conftest_clean_test_db.py:71`.
- ✅ [LUPIN] **Integration harness `DB_HOST=localhost` export** — unblocks host-side `seed_test_companions.py` that defaulted to docker-internal `lupin-postgres`.
- ✅ [LUPIN] **3 dispatcher/notify fixtures** broadened `except` to `(ConnectionError, Timeout)` — 11 ERRORing tests now cleanly skip when `:7999` is unhealthy.
- ✅ [LUPIN] **`TestDispatcherMocked` xfail → skip** — dodges a CPython 3.11 + pytest-9 AST-traceback-formatter bug (`SystemError: AST constructor recursion depth mismatch`) that was aborting the integration suite at ~31% every run.

### Final green baseline across all 4 layers

| Layer | Result |
|-------|--------|
| Unit | 3549 pass / 1 xfail / 0 fail |
| WebSocket smoke | 50 / 50 |
| Integration | 228 pass / 31 skip / 0 fail / 0 error |
| E2E UI | 357 pass / 0 fail / 0 error |

### New follow-ups from Session 6a30b98c

- [ ] [LUPIN] **Move `similarity confirmation enabled = false` behind an env var** — currently in `[Lupin: Testing]` block, which means the test server auto-accepts any 90%+ snapshot match without asking. For prod-like test runs we may want this configurable per-invocation. Not urgent.
- [ ] [LUPIN] **Investigate why `push_job` takes 60-200s in test env** — even with UPE + similarity-confirm disabled, the LLM router (`deepily/ministral_8b_2410_ft_lora` via vLLM) takes noticeably long on first call per container. Cold-start vs. steady-state unclear. Not blocking.
- [ ] [LUPIN] **Consider test-fixture helper for timezone-aware ISO** — `datetime.now(timezone.utc).isoformat()` was needed in 14 sites in one file. A `_future_iso(hours=1)` helper in conftest would be DRYer. Low priority.

---

## 🌅 SESSION-CLOSE BRIEFING — 2026-04-22 Session b486e9dc

### Landed this session

- ✅ [LUPIN] **Bug A: Flip TFE DEFAULT_MODEL back to Sonnet 4.6** — `src/scripts/tfe_to_cc_phase3_live.py:41` + `notifications.js:7279` localStorage fallback + `notifications.html:925` cache-bust bumped to `v=20260422b`. Dropdown option at `:7288` preserved so Opus is still explicitly selectable. Keep `DEFAULT_EFFORT=high` per matrix 23-*.
- ✅ [LUPIN] **Bug B: LanceDB-GCS tests stop touching GPU** — class-scoped autouse monkeypatch of `EmbeddingProvider.generate_embedding` + `EmbeddingManager.generate_embedding` routes every embed call through `POST /api/embeddings/batch`. **Zero CoSA edits**, zero engine modification. Validated by xfail test running the full embedding path without OOM. 6 unrelated GCS-creds skips filed as follow-up.
- ✅ [LUPIN] **Top-10 TODO briefing serialized** — `src/rnd/v0.1.6/2026.04.22-session-start-top-10-briefing.md` captures the 2026-04-21 triage state in a stable location for future sessions.
- ✅ [LUPIN] **Memory saved** — `feedback_tests_call_server_api_not_instantiate` prevents future plans from proposing in-process engine instantiation for tests.

### New follow-ups from Session b486e9dc

- [ ] [LUPIN] **Mount host `~/.config/gcloud/` into `lupin-rest-test` container** — 6 tests in `test_lancedb_gcs_integration.py` skip because `gcs_credentials_available` fixture finds no Application Default Credentials inside the container. Fix: add bind-mount to `docker-compose.yml` `lupin-rest-test` service (mirrors the pending `gh` CLI creds mount for Phase 5 `git push`). Once landed, all 7 non-xfail tests should run and pass.
- [ ] [LUPIN] **Browser-verify Bug A on fresh localStorage** — clear `RESUME_MODEL_PREF_KEY` in dev tools, reload notifications page, open a stalled TFE card, confirm Resume dropdown defaults to "Sonnet 4.6" (not Opus).
- [ ] [LUPIN] **Validate `server_embedder` fixture pattern adopted by future integration tests** — this session sets the precedent. Any future test that needs embeddings should use the fixture rather than instantiating `ProseEmbeddingEngine` or `EmbeddingProvider` in-process. `feedback_tests_call_server_api_not_instantiate` captures the rule.

### Bug B Block 1a status update

The Block 1a item from Session 9934d315 ("5 × `test_lancedb_gcs_integration.py` — CUDA OOM") is **RESOLVED by design** — tests no longer touch GPU regardless of GCS credential availability. The 6 current skips are a separate environmental issue (ADC mount), not a fix regression.

---

## 🌅 NEXT-MORNING BRIEFING — 2026-04-22

### TL;DR

Session 9934d315 (2026-04-21 afternoon/evening) cleared a deep stack of silent test-health bugs that had been breaking dual-container mode for weeks. Two root causes, two tiny fixes, massive unlock:

1. **`auth.js` hardcoded `http://localhost:7999`** → every auth-dependent E2E test under dual-container mode (browser served by :8000) was POSTing credentials to :7999. Session cookies went to the wrong server, page loads on :8000 had no auth, screenshots captured the login redirect instead of the target page. Fixed to `${window.location.origin}`.
2. **12 integration test files hardcoded `BASE_URL = "http://localhost:7999"`** (copy-paste propagation) → every integration test was silently hitting the dev server. Fixed all 12 to use `os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )` to match the conftest pattern.

Plus the smaller straggler cleanup (Phase A.1-A.3): WS cred var rename, smoke/integration timeout bumps in `test_suite/job.py`, and `notifications.js` `renderHistoryActions` surgery.

### Pending work for 2026-04-22

**Block 1 — 6 remaining integration failures** (triaged, none are routing bugs):

- **5 × `test_lancedb_gcs_integration.py::TestLanceDBGCSIntegration::*`** — all `RuntimeError: CUDA out of memory` in `ProseEmbeddingEngine` (nomic-bert-2048 embedding model). GPU pressure from user's other workloads. **USER-RUN territory** per `feedback_never_grab_gpu`. Options: (a) force these tests onto CPU, (b) skip when CUDA unavailable via `pytest.mark.skipif`, (c) defer to a quieter GPU window.
- **1 × `test_conftest_clean_test_db.py::test_clean_test_db_removes_prior_test_users`** — `psycopg2.errors.DatatypeMismatch: column "id" is of type uuid but expression is of type text`. Pre-existing fixture bug in the meta-test. Fix: cast `gen_random_uuid()` explicitly, or use Python `uuid.uuid4()` + server-side generation.

**Block 2 — 2 remaining E2E failures** (separate root causes, NOT auth.js):

- **`test_cj_flow_pause_schedule.py::TestPauseResumeButtonClick::test_click_pause_button_updates_card`** — Playwright click-retry log shows `<div class="queue-category">`, `<div class="queue-header">`, and `<a class="lupin-nav-active">` all intercepting pointer events on the pause button. CSS z-index / pointer-events layering bug. Possibly related to parallel session b802e633's commit `82243e4` ("Fix bulk-delete 404 + truncate job-id chip") which touched `notifications.js`.
- **`test_job_history_ui.py::TestJobHistoryEdgeCases::test_admin_can_manage_other_users_jobs`** — Admin user tries to retry another user's failed job via `.retry-btn` click; Playwright times out 30s waiting for `/retry` response. Either retry endpoint is broken for admin→other-user path, the button click doesn't fire the request, or the endpoint auth boundary is mis-configured.

**Block 3 — uncommitted work from this session** (session-end will stage what's mine):

- Parent Lupin: `auth.js`, 12 integration test files, `run-websocket-smoke-tests.sh`, `notifications.js` (from Phase C earlier), `fifo_queue.py` (wait — that's CoSA), plus 5 regenerated visual baseline PNGs under `io/test-suite/visual-baselines/`, plus `test_fifo_queue_notify_abstract.py` new test file (Phase 3 Item A).
- CoSA submodule (user commits separately from CoSA session): `shared/fix_executor.py`, `bug_fix_expediter/state.py`, `bug_fix_expediter/job.py`, `test_fix_expediter/job.py`, `test_suite/job.py`, `rest/fifo_queue.py`.

### Today's landings (reference)

- Part 1 (stop.py rebaseline + TFE telemetry demotion + stderr capture) + Part 2 (BFE parity) checkpoint committed as `f533c08` at 13:20 EDT.
- Straggler Phase A+C completed earlier in afternoon.
- auth.js + integration BASE_URL bulk fix completed evening.
- Test-health final: unit **3549** / WS **50/50** / integration **226 passed, 6 failed** (all 6 pre-existing env/fixture bugs) / E2E visual **12/12** / E2E full **355 passed, 2 failed** (pause-button + admin retry, both separate bugs).

---

## 🌅 NEXT-MORNING BRIEFING — 2026-04-18

### TL;DR

Session 44581b8c spent the day walking the TFE Resume path end-to-end. Every blocker that surfaced was root-caused and fixed in order — **Bugs X1/X2 (UI jobId/toggle), 14 (watchdog routing_command), 9a (container .git), 500-char cap, showToast, 15 (SDK streaming wrap)**. Unit tests **42/42 green**. Container recreation required AFTER the .git mount (requires `docker rm -f` + `compose up -d` — a `docker restart` does NOT pick up new volume mounts). Last step — Phase 3 `FixExecutor` actually **applying** fixes — deferred to tomorrow because it needs the Bug 15 CoSA code to be live in the container.

### Boot-up sequence (strict order, tomorrow morning)

1. **Commit CoSA submodule changes** — from inside `src/cosa/`, user commits the 7 files the Bug 14 + 15 + 500-char-cap fixes touched:
   - `agents/swe_team/hooks.py` (wrap_prompt_for_streaming helper)
   - `agents/swe_team/__init__.py` (export)
   - `agents/swe_team/orchestrator.py` (3 call sites)
   - `agents/bug_fix_expediter/orchestrator.py` (2 call sites + import)
   - `agents/test_fix_expediter/orchestrator.py` (2 call sites + import)
   - `rest/test_suite_completion_watchdog.py` (Bug 14 forward fix via create_agentic_job)
   - `rest/routers/notifications.py` (500-char response_value cap removed)
2. **Bounce `lupin-rest-test`** — `docker restart lupin-rest-test` (now sufficient, not recreate — only code changed, no volume mount changes). Wait for `/health` → 200.
3. **Click Resume** on `tfe-72adc928` (the more-recent stalled row — both rows now show their `tfe-*` ID chip in the header thanks to the UI-chip work).
4. **Re-select the 11 proposals** at the voice gate (previous responses lost with `tfe-445f9e4b` and `tfe-60431542` crashes).
5. **Observe Phase 3** — each "Applying fix N/11" notification should NOW be followed by successful Edit/Write tool blocks in the worktree at `/var/lupin/.claude/worktrees/tfe-<new>/`. `Phase 3 complete: K/11 cluster(s) fixed` with K > 0.
6. **Observe Phase 5** — first time reaching `GitStrategist.commit_and_pr_multi()` from inside the container's worktree. May surface `gh` CLI / GitHub credentials follow-up (mount `~/.config/gh` into the container?).
7. **Observe Phase 6** — auto-queues a validation `TestSuiteJob` to verify the applied fixes retired their failures.

### Today's landings (reference)

- ✅ **UI Bug X1** (Resume button empty jobId) + **Bug X2** (history-card toggle ID collision, = briefing's Bug 2).
- ✅ **Bug 14** (watchdog bypassed `create_agentic_job`) — factory-routed forward fix + DB patch on `tfe-3436c5b8`. 36/36 watchdog unit tests green.
- ✅ **showToast undefined method** — swapped to `this.log` at 2 sites.
- ✅ **500-char response_value cap** (pre-existing) removed at `src/cosa/rest/routers/notifications.py:849` (XSS sanitization + empty check preserved).
- ✅ **Bug 9a** (container missing `.git` for worktree) — bind-mount added to both dev + test services in `docker-compose.yml`.
- ✅ **UI job-id chip** — clickable copy-to-clipboard on every card header + ID line in details.
- ✅ **Bug 15** (`can_use_tool` AsyncIterable requirement, upstream [#18735](https://github.com/anthropics/claude-code/issues/18735) unresolved) — `wrap_prompt_for_streaming()` helper + 7 call sites swapped with inline WORKAROUND comment + URL. 6 new unit tests (42/42 overall green).
- ✅ **Session manifest `.claude-session.md`** — created 44581b8c section mid-session after user flagged missing status.

### Postmortems filed today

- `src/rnd/v0.1.6/2026.04.17-bug-14-auto-dispatched-tfe-lacks-routing-command.md`
- `src/rnd/v0.1.6/2026.04.17-bug-9a-container-missing-git-for-worktree.md`
- `src/rnd/v0.1.6/2026.04.17-bug-15-claude-agent-sdk-streaming-mode-workaround.md`

### New follow-ups from Session d8831785 (2026-04-20)

- [ ] [LUPIN] **Flip harness `DEFAULT_MODEL` back to Sonnet** — matrix 23-*.md proved Sonnet beats Opus ~5× on this workload. `src/scripts/tfe_to_cc_phase3_live.py:40` currently says `claude-opus-4-7`; change to `claude-sonnet-4-6`. Keep `DEFAULT_EFFORT=high`.
- [ ] [LUPIN] **Flip UI localStorage fallback to Sonnet** — `src/fastapi_app/static/js/notifications.js` `renderResumeOverrideControls()` defaults to `'claude-opus-4-7'` when localStorage is empty. Change to `'claude-sonnet-4-6'`. (First-time UI users would otherwise get the worse arm by default.)
- [ ] [LUPIN] **Why does Opus default to `unclear`?** — three Opus arms (B/C/D) returned 10–11 unclear verdicts regardless of effort. Inspect a failing Opus cluster's stream-json tool-use trace to see whether the Coder subagent even attempted the edit, or returned `unclear` without trying. Most interesting unanswered question from tonight's matrix.
- [ ] [LUPIN] **Sonnet + medium arm** — find out whether effort saturates below `high`. If Sonnet+medium ≈ Sonnet+high, we've been over-spending thinking budget.
- [ ] [LUPIN] **Cross-workload matrix validation** — run the 5-arm matrix against a fresh TFE cluster set (different failure profile) to confirm the Sonnet-wins pattern isn't specific to `tfe-72adc928`.
- [ ] [LUPIN] **Tighten `confidence` prompt semantics** — `src/cosa/agents/test_fix_expediter/prompts/proposal.py` tells the LLM to "rank by confidence" but never defines WHAT the number measures. Observed values conflate "confidence in root cause" with "quality of approach". Consider splitting into two fields or pinning the semantic explicitly to one dimension (and using `risk_level` for the other).
- [ ] [LUPIN] **Revisit validator "Validation OK: ISSUES"** — harness's `validate_result_payload` still flags `verdict=fixed + commit_sha=null` as an error even though Phase B's `already_clean` verdict correctly handles that case. Update the validator to accept `already_clean` as a terminal state.
- [ ] [LUPIN] **Cache-bust discipline** — bumped `notifications.html` v=20260417c → v=20260420a tonight after forgetting to bump it with the Phase E UI change. Consider a pre-commit hook that verifies any `notifications.js` diff also touches the v= token in `notifications.html`.

### Deferred / backlog (carried from prior sessions)

- [ ] [LUPIN] **Phase 3/5/6 observation** on fresh `tfe-<resumed>` (tomorrow, step 5-7 above).
- [ ] [LUPIN] **Investigate cosa-voice `set_session_status` MCP tool** — user's earlier directive ("set session status using cosa-voice MCP at beginning of every session"). My ToolSearch found only `set_session_topic`, `get_session_info`, `notify` (has `session_name` arg). Need to find the tool they mean or confirm the startup-ritual protocol in `~/.claude/CLAUDE.md` should be updated.
- [ ] [LUPIN] **Revert 500-char cap decision** if on deep review we want it back with higher ceiling (e.g., 10k) instead of fully removed. Current state: removed, relying on XSS sanitization + empty check only.
- [ ] [LUPIN] **`gh` CLI / credentials mount** for Phase 5 in container (anticipated; worth reading tomorrow if Phase 5 trips).
- [ ] [LUPIN] **Upstream watch** — https://github.com/anthropics/claude-code/issues/18735 — when closed/fixed, delete `wrap_prompt_for_streaming()` helper and revert the 7 call sites (grep for `wrap_prompt_for_streaming` finds them all).

---

## 🌅 MORNING STATUS — 2026-04-17 11:20 EDT (historical — superseded by NEXT-MORNING BRIEFING above)

The Bug 14 decision gate captured here was answered later today (factory-routed + DB patch chosen). Kept for session-continuity reference.

---

---

## 🌅 MORNING BRIEFING — 2026-04-17

### TL;DR

Bug 12 + Bug 13 landed and **validated live tonight** via `tfe-3436c5b8`. A stalled TFE with 8 clusters + 17 proposals is waiting on `:8000` — primed for the **first real end-to-end TFE Resume** (Doc 18 D2 first half). Intentionally did NOT apply any of the proposed fixes manually tonight so you can exercise the Resume path in the morning.

### Boot-up sequence (strict order)

1. ~~**Finish your DB seed-protection migration work first**~~ ✅ DONE Session eb50bd56. `is_protected` column deployed to both DBs; 3-layer guard landed; 4 unit tests pass. Committed this session.
2. **Then bounce `lupin-rest-test`** — ✅ DONE Session eb50bd56 (`docker restart lupin-rest-test`). Seed script confirmed companions present on startup.
3. **Then click Resume** on `tfe-3436c5b8` in the UI (or `POST http://localhost:8000/api/jobs/tfe-3436c5b8/resume`).

### What to expect on Resume

- Phase 2 voice gate re-fires with its full (formerly >5000 char) abstract visible — this is the FIRST real proof the Bug 13 cap removal works in the Resume path, not just fresh runs.
- You select proposals you trust. TFE's first 4 proposals are the same 4 one-liners that keep reappearing: `PRODUCT_NAMES` entry, `len == 9 → 10` in 3 sites, `resume_from` in `all_agents`, placeholder type assertion cleanup. Retires ~27 of 38 failures if all four land.
- Phase 3 FixExecutor writes inside `.claude/worktrees/tfe-3436c5b8/` (NOT your live tree, since worktree default is now `true` + container has been bounced to pick it up).
- Phase 5 GitStrategist creates branch + commits + PR from the worktree.
- Phase 6 auto-queues a validation `TestSuiteJob` to confirm the selected fixes retired the failures.

### What Bug 9 worktree isolation DOES and does NOT cover

Covered (safe from contamination): Python + JS source edits under `src/` via FixExecutor's `Edit` / `Write` tool calls; the GitStrategist branch cut off `origin/main`.

NOT covered (reasons it might still hit your tree): visual-baseline PNG regeneration (TFE proposal 1, needs `pytest --update-snapshots` outside the FixExecutor pattern) — if you select that, it'll run `pytest` against your live Chromium install, not the worktree. Skip it unless you've stashed your dev work.

### Rollback points if you're unhappy

| target | what it undoes |
|---|---|
| `git reset --hard aed7c6d^` | drops worktree `enabled=true` flip; keeps Bug 12 + 13 + validation commits |
| `git reset --hard bcbf5af` | drops Bug 13 fix + worktree flip; keeps Bug 12 + Bug 9 scaffolding |
| `git reset --hard 67dbd21^` | reverts ALL of tonight's work back to pre-session state |

CoSA submodule changes on disk (dispatcher + orchestrator edits + new `worktree_context.py`) are NOT git-committed by me — `git checkout -- agents/...` inside `src/cosa/` reverts those independently. `src/cosa/agents/shared/worktree_context.py` is untracked; delete it manually if rolling back.

### What I did NOT do tonight (intentional)

- No manual code fixes for the 38 failures — saved for Resume to exercise
- No `pytest` runs — respected your in-flight DB work
- No test-server interaction beyond the single `aed7c6d` INI flip (the running container hasn't seen it yet)
- No CoSA git commits — yours to handle when ready

### If Resume misbehaves

1. First: verify container bounce happened after the INI flip — `docker exec lupin-rest-test grep "cosa worktree enabled" /var/lupin/src/conf/lupin-app.ini` should show `true`.
2. Second: check `git status` inside `src/cosa/` — tonight's edits are uncommitted there and expected.
3. Third: full root-cause + context in `~/.claude/plans/let-s-start-a-new-zany-thimble.md` (postmortem-style plan file) and `src/rnd/v0.1.6/2026.04.16-bug-13-*.md` (design doc — wait, I never wrote one for Bug 13; see commit `3709139` message instead).
4. Fourth: if truly stuck, the 4 one-liner fixes are safe to apply by hand — same as TFE's first 4 proposals.

### Tonight's commit chain (newest → oldest)

```
aed7c6d  worktree enabled=true (default flip)
a389bc4  session close — Bug 12+13 validated via tfe-3436c5b8
bcbf5af  checkpoint: ts-d3df4d87 scheduled for Bug 13 validation
3709139  Bug 13: remove 5000-char caps + ValidationError→stall
029a55c  checkpoint: ts-e4089cf2 scheduled
5817533  Bug 12 + Bug 9 + 34 unit tests
67dbd21  overnight forensics + Bug 12 filed
```

---

## Active TODO below

## ~~🚨 First-thing next session — archive history (still pending from 2026-04-15)~~ ✅ DONE 2026-04-16

- [ ] [LUPIN] **Previously**: Review `ts-e4089cf2` outcome (scheduled 2026-04-16 17:24:00 EDT on :8000 test server; full `all` suite ~60 min; TFE voice gate expected ~18:25-18:40 EDT). **Acceptance criteria** for Bug 12 validation:
  - [ ] Test suite completes with ~38 failures (same reproducible baseline)
  - [ ] `TestSuiteCompletionWatchdog` auto-dispatches a TFE job
  - [ ] TFE reaches Phase 2 voice gate (generates ~21 proposals across 8 clusters)
  - [ ] Voice gate fires while operator offline → MCP 503 "User is offline"
  - [ ] **POST-FIX EXPECTED**: dispatcher raises `VoiceGateTimeoutError` → orchestrator saves checkpoint → raises `StalledException` → job persisted with `state=STALLED` (NOT `completed`)
  - [ ] UI History panel shows ⏸ Resume button for the TFE row
  - [ ] DB `metadata_json["checkpoint"]` contains rehydrated proposals for Resume-to-review
  - [ ] Worktree isolation status: with `[cosa_worktree] enabled=false` (default), confirm no worktree was created (Phase 3 not reached due to stall). If stall path fails, we'd see an unintended worktree attempt — that's also useful signal.
  - **If any criterion fails**: forensic capture + patch, do NOT escalate to Doc 18 D2 (attended Resume-apply) until Phase 5 stall-validation passes clean.

- [ ] [LUPIN] **Act on overnight TFE's 21 proposals** — report at `io/swe-team/reports/interactive.job.tester@lupin.deepily.ai/2026.04.15-at-21:41-EST-ts-79829a75-completed-test_fix_expediter-report.md`. Four 1-liner wins would retire 27 of 38 failures: (1) `len(AGENTIC_AGENTS) == 9` → `== 10` in 3 sites, (2) re-capture 12 visual baselines via `--update-snapshots`, (3) add `PRODUCT_NAMES` entry for TFE Resume agent, (4) add `resume_from` key to `all_agents` profile. Option: land these directly OR re-run TFE (post-Bug-12) to get a proper stalled row.

- [ ] [LUPIN] **Review `ts-79829a75` outcome** — ✅ Ran 2026-04-15 21:05 EDT. 3647/3671 pass. Same 38 failures as morning baseline (reproducible). TFE auto-dispatched → 21 proposals → 0 selected due to Bug 12. Full forensics: `src/rnd/v0.1.6/2026.04.16-overnight-forensics-ts-79829a75.md`.
- [ ] [LUPIN] **Revert overnight INI override** — `[Lupin: Testing]` block in `src/conf/lupin-app.ini` has `test fix expediter lead model = claude-sonnet-4-6` (added for cheap overnight run). Decide whether to keep or revert to Baseline default (Opus lead).
- [ ] [LUPIN] **CoSA commit** — 9 submodule files need committing from inside `src/cosa/` repo: `agents/utils/agent_notification_dispatcher.py`, `agents/bug_fix_expediter/cosa_interface.py`, `agents/test_fix_expediter/orchestrator.py`, `agents/test_fix_expediter/state.py`, `rest/agentic_job_factory.py`, `rest/job_persistence.py`, `rest/queue_util.py`, `rest/running_fifo_queue.py`, `rest/routers/io_files.py`.

## 🆕 New follow-ups from Session f01fdc2f

- [ ] [LUPIN] **Design knob — `test fix expediter feedback timeout action`** — options: `stall` (default, current behavior), `skip` (complete with 0 selected), `auto_select_high_confidence` (select proposals ≥ 0.85 confidence). INI + splainer + config.py + orchestrator._aggregate_voice_gate timeout branch. Low priority — stall is fine today.

- [ ] [LUPIN] **`gh auth setup-git` in Dockerfile for Phase 5 `git push`** — validated 2026-04-18 Session be57a252: gh CLI + GH_TOKEN work inside container (preflight 6/6 OK), `gh pr create` will succeed on `deepily/{lupin,cosa}` (scopes `repo,workflow` sufficient). But `git push` uses its own credential path — not gh's — so the first real Phase 5 `git push -u origin <branch>` will prompt for credentials. Fix: add `RUN gh auth setup-git` after the `apt install gh` line in Dockerfile (writes `~/.gitconfig` credential helper to delegate to gh). Deferred until Phase 5 is actually reached (Phase 3 turn-budget tiers need to land successful fixes first).

- [ ] [LUPIN] **lupin.lancedb bloat — `input_and_output_tbl.lance` is 37 GB** — discovered 2026-04-18 Session be57a252 during docker build context audit. Single table accounts for ~95% of the lancedb footprint and gets `COPY`'d into every container image rebuild (Dockerfile:217). Likely uncompacted old versions / stale snapshots. Actions: (1) compact via `LANCE.compact_files()`, (2) audit what's actually persisted (may be runtime logs accumulated without rotation), (3) consider runtime bind-mount instead of COPY (mirrors the postgres-data pattern) so image stays lean. Secondary: Dockerfile COPY step for a 37 GB table probably fails silently on memory-constrained CI. Low priority if dev only, HIGH if production images hit this.

- [ ] [LUPIN] **Client-side notification dedup by idempotency_key** — tfe-8b2eaeda run showed the same `Coder: Bash` notification rendered 4× in the UI because the server fans a single notification out to multiple WebSocket subscribers (queue card + history card + conversation card + session-specific). Each gets the same `idempotency_key`; the server is behaving correctly, but the UI renders each subscriber's copy as a separate card line. Frontend (`notifications.js`) should dedup by `idempotency_key` within a sliding window (~2s) before appending. Filed 2026-04-18 Session be57a252.

- [ ] [LUPIN] **Option B: mid-flight Coder turn-budget check-in** (follow-up to Option A tiered budget) — at soft limit (e.g., 75% of max_turns), orchestrator intercepts tool-use stream, sends `ask_multiple_choice` via cosa-voice with progress summary ("Fix K/N used X/Y turns: read A files, ran B tests, made C edits"), operator picks [abort / X more turns / X*2 more turns / yes-to-all-remaining]. Requires: (1) claude-agent-sdk session restart with context injection since `max_turns` isn't live-extensible, (2) turn counter + tool-use summary extraction in orchestrator, (3) new voice-gate surface + `cosa_interface` wiring. **PRIORITY BUMPED 2026-04-19**: tfe-a1c6e15a confirmed Option A alone insufficient — Coder produced a valid 3-line fix for C6 (renamed `test_registry_has_five_agents` → `ten_agents`, updated `== 5` → `== 10`) but ran out of turns before Tester could verify → uncommitted. Operator-in-the-loop grant of 10 more turns would have saved that fix. With preserved worktrees + enriched abstract, the infrastructure to show operator the progress is now in place.

- [ ] [LUPIN] **Coder prompt audit — reduce turn spend on exploration** — tfe-a1c6e15a showed the Coder burning through 31-51 turns even on simple 3-line test-value edits. Each Coder run does many Read/Grep/Bash calls before committing to the Edit. The Coder system prompt (in `src/cosa/agents/test_fix_expediter/prompts/` — `CODER_SYSTEM_PROMPT`) should be audited for: (1) pushing the Coder to commit to an edit earlier once the diagnosis is clear, (2) capping exploration (e.g., "≤3 Read calls before first Edit"), (3) reducing verification retries. Tiered budgets alone don't address the root cause — the Coder is inherently wasteful with its turn budget. Filed 2026-04-19 Session be57a252.

- [ ] [LUPIN] **Validate Resume** (Doc 18 D2 first half, safe without Bug 9 activation) — `tfe-3436c5b8` is stalled on :8000 with full checkpoint + 17 proposals + plan_path. Click Resume in UI (or `POST http://localhost:8000/api/jobs/tfe-3436c5b8/resume`) while you're online → should rehydrate checkpoint, re-fire voice gate with the full abstract visible (this is the critical Bug 13 regression guard — the abstract length cap removal makes the resumed gate display-able for the first time). Phase 3 apply is SAFE today because `[cosa_worktree] enabled=false` — the FixExecutor path is guarded behind that flag; if resumed, voice gate answer goes through selection but Phase 3 is opt-out until you flip the flag. Fresh-stall row ready for the Resume smoke.

- [ ] [LUPIN] **TFE report rendering bug** — markdown report shows `Duration: 0.0s` and `C1 — 0 failure(s)` through `C8 — 0 failure(s)` even though `state_snapshot` has full cluster data (12 failure_indices on C1, etc.). The printer in `test_fix_expediter/job.py` or `report_writer.py` reads from a different data path than what gets persisted. Mentioned in 2026-04-16 overnight forensics + postmortem but never filed as an action item until now. Affected files: `src/cosa/agents/shared/report_writer.py` (render function) and `src/cosa/agents/test_fix_expediter/job.py` (report builder). Not blocking — cluster data is correct in the DB.

- [ ] [LUPIN] **Worktree maintenance CLI + monitoring** (Bug 9 follow-up) — (1) `src/scripts/worktree-cleanup.sh` to prune orphaned worktrees and report disk usage under `.claude/worktrees/`, (2) periodic cleanup of worktrees older than 7 days even if `auto_cleanup=false` was set, (3) telemetry for worktree disk usage in the admin dashboard. Out of scope for the initial Bug 9 landing.

- [ ] [LUPIN] **BFE dead-job race — eager snapshot + packager fallback (D1)** — `dead_queue_watchdog._submit_bfe` captures only `dead_job_id` string; BFE's later DB lookup fails if row evicted (done/dead rotation, TTL, or E2E `clean_test_db` drop). Fix: snapshot dead-job context at dispatch, have `package_dead_job()` accept snapshot-first. Files: `src/cosa/rest/dead_queue_watchdog.py:393-470`, `src/cosa/agents/bug_fix_expediter/dead_job_packager.py:38-42`, `src/cosa/agents/bug_fix_expediter/job.py:~227`.

- [ ] [LUPIN] **Full attended TFE live run (D2)** — schedule a live TFE where operator answers voice gate, selects real proposals, walks Phase 3/5/6 with real commits + PR. Prereq: overnight `ts-79829a75` outcome reviewed + Bug 9 worktree isolation ideally landed first (so operator's working tree can't contaminate PR).

- [ ] [LUPIN] **Pre-merge E2E gate (D3)** — parallel session's proposed `POST /api/test-suite/submit` with `test_types="e2e"` + `monopolize=true`. Fine to run post-archive; exercises all today's UI fixes (Bug 1 io/file, Bug 2 dedup, Bug 8 labels) but NOT the Claude Agent SDK path.

## 🔖 Carryover TODO entries (from 2026-04-14 and earlier)

- [ ] [LUPIN] **Review midnight `all` run outputs** (Session 6ae2513c — ran as `ts-d2d890ed` 2026-04-15 00:56 EDT) — SUPERSEDED by Session f01fdc2f which surfaced the SDK creds + ops routing issues. New overnight run `ts-79829a75` replaces this.

## 🔖 Resume tomorrow — active triage plan

**Triage doc**: `src/rnd/v0.1.6/2026.04.13-session-triage-and-option-c-docker-non-root.md` — 12 HIGH PRIORITY items (red), 3 TFE follow-ups (yellow), 14 older carry-overs (green). Items #1 #2 #3 closed Session 23f409c8. **Resume at item #9** (quick win: grep today's startup log for `[Watchdogs] BFE=ENABLED, TFE=ENABLED` to confirm already satisfied by rebuild), then #5 (schedule TFE Resume Live E2E) or #6 / #7 (Phase D/E follow-ups).

## Pending — HIGH PRIORITY

- [x] [LUPIN] **Voice persona rename: Domi → Rio** — ✅ **COMPLETED 2026-05-11** (user-marked complete via voice). Plan doc at `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md`. 4 files touched (`lupin-app.ini`, `lupin-app-splainer.ini`, `test_voice_persona_helpers.py`, `test_voice_persona_allocation.py`). No TTS change — `voice_id` stays at `AZnzlk1XvdvUeBnXmlld`.

- [ ] [LUPIN] **Review three scheduled TFE jobs' outcomes (23:15 / 23:20 / 23:25 EDT)** — `ts-1139f28d` dry, `ts-996dafbc` live (with env_vars fixture), `ts-d2d890ed` all. Logs inside test container: `docker exec lupin-rest-test tail -80 /tmp/{pytest-direct,all}-latest.log`. Live run's outcome informs whether `/api/agentic-jobs/submit` exists (live test skips cleanly if missing).

- [ ] [LUPIN] **Follow-up if live test skipped on missing `/api/agentic-jobs/submit`** — add a generic agentic-job submit REST endpoint (factory wrapper like test-suite's) so the live test can actually submit TFE jobs. Currently the test body is complete but depends on this endpoint. Alternative: have the test go through `TestSuiteJob → watchdog` dispatch path.

- [ ] [LUPIN] **Bug 2 — history-card scroll toggle** (deferred, awaits user devtools). DOM-id collision hypothesis: live Done card and History card render the same `id="job-details-${jobId}"`; `getElementById` returns the first match. Step 0 (devtools query: `total vs unique` count of `[id^="job-details-"]`) is the gate. Step 3 plan: namespace IDs by queueName at render time. Plan in `src/rnd/v0.1.6/2026.04.14-all-suite-aggregation-and-history-card-toggle.md`.

- [ ] [LUPIN] **Visual-regression snapshot drift** (12 `test_visual_page[chromium-*]` failures). Needs human UI review per page (login, register, change-password, profile, notifications, landing, admin-{dashboard,snapshots,users,ratify,trust}, dev-tools), then `./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual` if intentional.

- [ ] [LUPIN] **Auth 401 — test_tfe_resume_e2e + test_cross_container_auth** (8 failures). Migrate from mock-token patterns to JWT from `/auth/login` per `mock_tokens_are_legacy` memory. Not a TFE candidate — needs design decision on test-side credential helper.

- [ ] [LUPIN] **Run Option B chown to unblock backups** (USER-ONLY — needs sudo TTY) — `sudo chown -R rruiz:rruiz /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/conf/long-term-memory/lupin.lancedb/` then re-run `/plan-backup --write` and confirm exit code 0. Originally 63,345 of 67,931 LanceDB files (93%) were owned by root from Docker container writes. This is a one-shot fix; new container writes will regenerate root-owned files until Option C lands.

- [ ] [LUPIN] **CoSA submodule commits for Session 9056c113 continuation** — Phases 1+2 of doc 16 added CoSA edits that need committing: `agents/utils/agent_notification_dispatcher.py` (VoiceGateTimeoutError raise on exit_code==2), `agents/bug_fix_expediter/orchestrator.py` (stall handling in run_diagnosis + run_proposal + gate pass-through), `agents/runtime_argument_expeditor/agent_registry.py` (TFE resume entry), `agents/runtime_argument_expeditor/expeditor.py` (_handle_tfe_checkpoint_match handler). Plus whatever's still outstanding from earlier 9056c113 work not yet committed. User commits from CoSA repo context per nested-repo rule. Server is already running the old code — voice gate timeouts will not actually stall until CoSA committed + server restarted again.

- [ ] [LUPIN] **Phase D follow-ups: file-path resume + CLI flag** — Deferred from Session 9056c113 Phase D core. Need (a) `POST /api/test-fix-expediter/resume-from-file` endpoint with auto-detection for `.md` plan doc (resume from Phase 3) vs `.json` checkpoint (resume from checkpoint's ordinal) vs `tfe-*` job ID (shortcut to stalled resume) — mirrors Presentation Generator `render_only` + `yaml_path` pattern (`routers/presentation_generator.py:40,172-186`). (b) "Resume from" text input on TFE submission card in `notifications.js`. (c) `--resume <job_id>` and `--resume-from <path>` flags in `src/tests/e2e/run-tfe-live-e2e.sh`. Plan doc: `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/14-checkpoint-resume-and-completion-report.md` Steps D4b-D4d + D5.

- [ ] [LUPIN] **Phase E follow-ups: BFE completion report + BFE checkpoint-resume** — Deferred from Session 9056c113 Phase E core (skill update done, cross-agent rollout deferred). Follow the patterns now documented in `src/workflow/agentic-voice-workflow.md` v3.0 Phase 11 (completion report) + Phase 12 (checkpoint-resume). BFE already has a text summary (`bug_fix_expediter/job.py:283-290`) — wrap it with `voice_io.notify()` + rich abstract. BFE has voice gates at Phase 2 (fix selection) + Phase 5 (trust confirmation) — add `save_checkpoint()`/`load_checkpoint()` + `StalledException` catch. Reuse exception types from TFE (or extract to shared module). Podcast completion report similarly needs a voice notification if missing.

- [ ] [LUPIN] **FastAPI restart + CoSA submodule rebuild needed to activate checkpoint-resume** — Session 9056c113 edits are inside `src/cosa/` submodule. After user commits CoSA + running server picks up the new code, test the end-to-end flow: (1) submit TFE job that will stall (e.g., low `feedback_timeout_seconds` in INI), (2) verify stalled voice notification + stalled badge in UI, (3) click "▶ Resume from Checkpoint" button, (4) verify new TFE job runs from Phase 3 (skipping already-completed phases 0-2).

- [ ] [LUPIN] **TFE live E2E monopolize run (real SDK + real git)** — All infrastructure ready: `src/tests/e2e/run-tfe-live-e2e.sh --live` will exercise the full pipeline against real Claude Agent SDK + real GitOps with a bug-injector-seeded failure. Schedule via `/schedule-tests` skill after hours. Cost gate: ~$15 per run (`test fix expediter cost cap usd`). Validates everything: clustering heuristic, Phase 1 diagnosis prompts, Phase 2 proposal gates, FixExecutor retry loop, multi-cluster git strategy, Phase 6 rerun recursion guard. Until this runs, the 3119-unit-test green bar is the only validation.
- [ ] [LUPIN] **PEFT trainer run on GPU — TFE voice routing** — Training data ready: 75 templates in `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter.txt`, command registered in `src/conf/training/agent-router-agentic-commands.json`, unit tests (12) pass. USER-RUN ONLY per `feedback_never_grab_gpu` memory. When GPU free: `./src/scripts/run-agentic-intent-training.sh test` (sanity) then `full` (~3-4 hrs). Also note Session 389 left prior PEFT data regenerated — confirm whether TFE additions require a full regen or a merge.
- [ ] [LUPIN] **BFE Phase 6 LIVE E2E (parallel console state unknown)** — User was running BFE Phase 6 live E2E in a separate console during Session 1cfcdf73. Outcome unknown. Verify whether the baseline was established + results captured. Dry-run + persistence fixes already landed in Session 1b8c1cc0 (76/76 unit tests passing); remaining: real Claude Agent SDK, real git commits, known-bad mutation. Enable `bug fix expediter enabled = true` in INI + schedule as monopolized test-suite job after hours.
## Pending — TFE follow-ups (non-blocking)

- [ ] [LUPIN] **TFE Phase 0 `llm_refine` real SDK wiring** — Infrastructure in place: `llm_refine(ctx, seeds, max_clusters, refine_fn=None)` accepts async callback. MVP uses pure-Python `_cap_enforce()` fallback. Plugging in real Opus SDK call would refine clusters beyond the heuristic. Lives in `src/cosa/agents/test_fix_expediter/cluster.py`.
- [ ] [LUPIN] **TFE `agent_registry.py` entry** — Deferred during scaffolding. Factory routing works via direct elif in `agentic_job_factory.py`. Adding the `agent_registry.py` entry would enable uniform agent discovery and match the pattern used by deep_research/podcast_generator.
- [ ] [LUPIN] **`FixContext` Pydantic model (optional refactor)** — TFE currently uses `SimpleNamespace` duck-typed pass-through to `shared.FixExecutor`. Formalizing as a Pydantic model would add validation + serialization. Not blocking any work.

## Pending — v0.1.7 future work (deferred until v0.1.6 ships)

- [ ] [LUPIN] **CJ Flow: serial → async + hybrid multi-lane (Approach C)** — Resume the design conversation from Session 237. Design review for v0.1.7 wip lives at `src/rnd/v0.1.7/2026.04.21-cj-flow-async-multi-lane-design-review.md`; original Approach C design at `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` with 11-step Phase 1/2/3 breakdown. **User decision (2026-04-21)**: pursue ONLY in v0.1.7 wip branch after v0.1.6 lands; default `cj flow max concurrent agentic jobs = 3` for first deploy. Open design questions still need decisions before any code (interactive lane Y/N, cost-guardrail at dispatcher, ghost-job watchdog, pool-status endpoint phase, per-job-type pools, Approach D coupling). Reconcile against `src/workflow/agentic-voice-workflow.md` before exiting plan mode on the implementation plan.

## Pending — Older items carrying over

- [ ] [LUPIN] **Phase 11: Presentation Generator Theme Integration** — Cross-cutting theme wiring for all renderers. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/05-theme-integration-plan.md`.
- [ ] [LUPIN] **#1-Phase 4 (DEFERRED): migrate remaining 13 compliant fetch sites to authedFetch for uniformity** — Session 85b05d1d implemented Phase 2+3 (helper + 12 non-compliant migrations, commit e68d827). Pure cleanup with no user benefit; can be picked up opportunistically. Plan doc: `src/rnd/v0.1.6/2026.04.10-notifications-js-auth-token-refresh-audit.md`
- [ ] [LUPIN] **#3-Followup: sdla restart lupin-rest to propagate new pytest.ini paths into container** — Session 85b05d1d commit 824f314 relocated visual regression artifacts. Host-side test (`-k visual`) passes 12/12. The container's bind-mounted `pytest.ini` still points to the OLD inode. Next `sdla restart` picks up the new inode automatically.
- [ ] [LUPIN] **#5 Research 5-6 dead/paused jobs stuck in todo queue** — User reports 5-6 dead or paused jobs visible in todo queue. Investigation inconclusive (transient test-suite traffic hypothesis). Findings doc: `src/rnd/v0.1.6/2026.04.10-stuck-todo-jobs-investigation.md`. Needs user clarification on account + current state.
- [ ] [LUPIN] **Clean up debug code in `test_suite/job.py`** — Remove temporary debug `print()` statements (6+ lines), `loop_count`/`children_count` variables, and re-enable `os.unlink(junit_xml_path)` after confirming remediation snapshot works end-to-end.
- [ ] [LUPIN] **Remove [DIAG-JR] diagnostic logging** — In `notifications.js` (3 console.log blocks) and `notifications.py` (1 print). Remove after verifying activity log auto-expand works in production.
- [ ] [LUPIN] **TestSuiteJob: Surface stderr when subprocess crashes at startup** — When exit_code!=0 AND 0 tests found, response_text says "FAILURES DETECTED" with 0/0/0. Should include captured stdout/stderr tail so operator sees the actual error immediately. Discovered Session 8042b0d1.
- [ ] [LUPIN] **Test-Suite Job — INI-driven timeouts** — Phase 2 uses hardcoded `SUITE_TIMEOUTS_SECONDS` dict. Promote to INI config keys so operators can tune without code changes.
- [ ] [LUPIN] **Test-Suite Job — Phase 3 (conftest.py addoption)** — Consolidate `smoke_direct` into unified `smoke` runner via pytest's `pytest_addoption` hooks. ~30 min work. Not blocking. Plan: `src/rnd/2026.04.05-test-suite-agentic-job-comprehensive-expansion.md` Phase 3.
- [ ] [LUPIN] **Interrupted job re-enqueue mechanism** — `mark_interrupted_jobs()` in `job_persistence.py` marks pending/running jobs as interrupted at startup but does NOT re-enqueue them. Long-running jobs (presentation ~8min, deep research ~15min) are lost on server restart. Proposed: persist constructor args in `metadata_json` at creation time, add `requeue_interrupted_jobs()` at startup with max retry guard.
- [ ] [LUPIN] **Run Opus through test-suite endpoint** — Sonnet validated (`pr-512e5ca4`, 15 slides, $0.46). Opus has never run through `POST /api/test-suite/submit`. ~$2.43 cost.
- [ ] [LUPIN] **TestSuiteJob Manual + Automated Testing remaining items** — Pattern A implemented (Session 386). Remaining: (1) Fix voice_io dispatcher bug (`AgentNotificationDispatcher` missing `notify` attribute), (2) Manual UI verification of submit card + scheduling, (3) Verify scheduling timezone fix with live scheduled job, (4) Run live pipeline smoke test with server, (5) Integration test for `POST /api/test-suite/submit`.
- [ ] [LUPIN] **Automated E2E testing workflow** — Design standard pattern for scheduling E2E/integration test runs as monopolized jobs at user-specified times. Becomes the modus operandi for all post-coding verification.
- [ ] [LUPIN] **Full E2E re-run needed to verify 2 visual regression errors are pre-existing** (test_visual_regression.py profile + notifications)

## Completed earlier (Sessions 85b05d1d, 1b8c1cc0, etc.)

- [ ] [LUPIN] **TFE implementation** — Execute the 19-step sequence from `src/rnd/2026.04.10-test-fix-expediter-plan.md`. Precondition: BFE Phase 6 live E2E (dry-run first) baseline established in the parallel console. Steps: (1-3) extract PlanWriter/GitStrategist/FixExecutor to `src/cosa/agents/shared/`, (6) TFE scaffolding with all agentic-voice-workflow-mandated modules, (7-12) TFE phases 0-6, (13) TestSuiteCompletionWatchdog + queue hook + main init, (14) 12 INI keys + splainer, (15) proxy Q&A script, (16) live pipeline test, (17) PEFT training data generation (USER runs trainer), (18) E2E dry-run, (19) live monopolize run via `/schedule-tests`. Track progress in execution logs 90-95 in the planning dir.
- [ ] [LUPIN] **Clean up debug code in `test_suite/job.py`** — Remove temporary debug `print()` statements (6+ lines), `loop_count`/`children_count` variables, and re-enable `os.unlink(junit_xml_path)` after confirming remediation snapshot works end-to-end.
- [ ] [LUPIN] **Remove [DIAG-JR] diagnostic logging** — In `notifications.js` (3 console.log blocks) and `notifications.py` (1 print). Remove after verifying activity log auto-expand works in production.
- [ ] [LUPIN] **BFE Phase 6: LIVE E2E test of automated repair loop (non-dry-run)**. Dry-run smoke test complete (Session 1b8c1cc0, doc 09) and persistence gaps fixed (Session 1b8c1cc0, doc 10) — 76/76 unit tests passing, full loop verified end-to-end via DB inspection at $0 cost. Remaining: LIVE run with real Claude Agent SDK, real git commits, known-bad mutation. Enable `auto fix enabled = true` in INI, submit presentation gen job with intentional source-path bug, verify watchdog → BFE (real agents) → resubmit cycle completes. Schedule as monopolized test-suite job after hours.
- [ ] [LUPIN] **TFE Phase 6: LIVE E2E test of test-fix repair loop (non-dry-run)**. **Precondition**: TFE forensics fix plan (`src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md`) must land first so any failure produces real error + traceback data in `job_history` instead of "Unknown error" — without that fix this E2E is un-debuggable. **Scope**: LIVE run with real Claude Agent SDK (Opus lead + Sonnet worker), real git commits, real failing tests. Enable `test fix expediter auto fix enabled = true` in INI, submit a `test_suite` job with a known-failing test pattern (stale visual regression baselines or a deliberately broken unit test), verify the `TestSuiteCompletionWatchdog` → TFE (real agents) → cluster → diagnose → propose → voice gate → fix → git → rerun cycle completes end-to-end. Success criterion: the rerun test suite reports PASS. Schedule as monopolized test-suite job after hours via `/schedule-tests` or the test-suite REST endpoint. Expected cost: ~$2-8 per run depending on cluster count and phase depth (Opus diagnosis + Sonnet fix cycles). **Mirrors the BFE Phase 6 live E2E TODO above** — BFE targets `DeadQueueWatchdog → BFE → fix presentation` loop; TFE targets `TestSuiteCompletionWatchdog → TFE → fix tests` loop. The two loops share infrastructure (persistence, voice gates, PlanWriter, GitStrategist) but have different watchdogs, entry points, and target outcomes, tracked as separate TODO items for independent scheduling and cleaner failure isolation.
- [ ] [LUPIN] **Automated E2E testing workflow**: Design standard pattern for scheduling E2E/integration test runs as monopolized jobs at user-specified times. Becomes the modus operandi for all post-coding verification.

- [ ] [LUPIN] **Session 389 VERIFICATION — return to review today's work (NEXT SESSION)**. Two bodies of work landed in Session 389 that need end-to-end verification: (1) Voice routing training data complete coverage (5 content-gen agents, multi-placeholder expansion bug fix in xml_coordinator.py), (2) BFE Phase 5 Trust Proxy + Git Strategy (git_ops.py, run_git_strategy, 33 new tests, 2,831 unit tests passing). User shut down mid-session; resume with: summarize what was completed, verify commits landed (Lupin parent-repo + COSA nested-repo commits pending), confirm no regressions, identify any loose ends. Plan docs: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md`, `src/cosa/agents/presentation_generator/rnd/2026.04.05-voice-routing-training-data-complete-coverage.md`.

- [ ] [LUPIN] **Test-Suite Job — Phase 3 (conftest.py addoption) — DEFERRED to 2026-04-07**. Consolidate `smoke_direct` into unified `smoke` runner via pytest's `pytest_addoption` hooks (--auto-proxy, --cost-cap-usd, --group, etc.). ~30 min work. Not blocking anything. Plan: `src/rnd/2026.04.05-test-suite-agentic-job-comprehensive-expansion.md` Phase 3.
- [ ] [LUPIN] **TestSuiteJob — Surface stderr when subprocess crashes at startup**. When exit_code!=0 AND 0 tests found, response_text says "FAILURES DETECTED" with 0/0/0 — misleading. Should include captured stdout/stderr tail so operator sees the actual error immediately. Discovered Session 8042b0d1 when 142ms crash showed no diagnostic info.
- [ ] [LUPIN] **Test-Suite Job — INI-driven timeouts** (follow-up). Phase 2 uses hardcoded `SUITE_TIMEOUTS_SECONDS` dict in job.py. Promote to INI config keys so operators can tune without code changes. Original plan called for this; deferred for v1 pragmatism.
- [ ] [LUPIN] **Run PEFT trainer — training data REGENERATED & ready (USER-RUN GPU)**. Session 389 expanded training data for complete argument coverage across 5 content-gen agents: presentation_generator (5 placeholders + renderer/duration/audience/audience_context), research_to_presentation, podcast_generator, research_to_podcast, deep_research. Also added monopolize conditional_args for test_suite, target_languages multi-value conditional (es-MX/es-ES/es-AR + en/fr/de) for podcast agents. Fixed multi-placeholder expansion bug in xml_coordinator.py. 35,564 train + 4,446 test + 4,446 validate examples generated; all JSONL files validated. **When GPU free, USER runs**: `./src/scripts/run-agentic-intent-training.sh test` (1% sanity, 5-10 min) then `full` (~3-4 hrs). Plan: `src/cosa/agents/presentation_generator/rnd/2026.04.05-voice-routing-training-data-complete-coverage.md`.

- [ ] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 11: Theme Integration**. Cross-cutting theme wiring for all renderers. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/05-theme-integration-plan.md`.
- [ ] [LUPIN] **Interrupted job re-enqueue mechanism**. `mark_interrupted_jobs()` in `job_persistence.py` marks pending/running jobs as interrupted at startup but does NOT re-enqueue them. Long-running jobs (presentation ~8min, deep research ~15min) are lost on server restart. Proposed: persist constructor args in `metadata_json` at creation time, add `requeue_interrupted_jobs()` at startup with max retry guard. See postmortem plan: `~/.claude/plans/misty-noodling-babbage.md` Step 5.
- [ ] [LUPIN] **Run Opus through test-suite endpoint**. Sonnet validated (`pr-512e5ca4`, 15 slides, $0.46). Opus has never run through `POST /api/test-suite/submit` — the Apr 5 success was via rogue background bash. ~$2.43 cost.
- [ ] [LUPIN] **TestSuiteJob: Manual + Automated Testing** — Pattern A implemented (Session 386). Remaining: (1) Fix voice_io dispatcher bug (`AgentNotificationDispatcher` missing `notify` attribute — notifications fall back to CLI), (2) Manual UI verification of submit card + scheduling, (3) Verify scheduling timezone fix with live scheduled job, (4) Run live pipeline smoke test with server, (5) Integration test for `POST /api/test-suite/submit`. Plan: `src/rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md`
- [ ] [LUPIN] Full E2E re-run needed to verify 2 visual regression errors are pre-existing (test_visual_regression.py profile + notifications)
## v0.1.6 — FUTURE DEVELOPMENT

### INI Config Key Naming Convention — Standardize on Spaces (Sessions 256, 349)

### Prediction System: Validation + Documentation

- [ ] **[LUPIN] Prediction System Validation Campaign** — Unified 6-phase validation of UPE (7 slices, 87 unit + 21 E2E) and SWE proxy Layer 2 (shadow-mode capture). Phases: baseline, threshold tuning, SWE shadow-mode, gap tests (+6 E2E), visual QA, full lifecycle. 136 existing + 6 new = 142 total tests.
  - **Umbrella plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md)
  - **UPE validation plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md)
  - **SWE workload doc**: [`src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md`](src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md)
  - **Progress**: Phase 1 DONE. Phase 2 LanceDB isolation VERIFIED (Session 380) — 195/195 full suite pass, 21/21 prediction engine focused pass. Phases 3-6 can now proceed.
  - **LanceDB isolation plan**: [`src/rnd/2026.03.25-upe-lancedb-test-isolation.md`](src/rnd/2026.03.25-upe-lancedb-test-isolation.md) — implemented Session 378
  - **Implementation plan**: [`src/rnd/2026.03.26-upe-lancedb-test-isolation-and-warm-fix.md`](src/rnd/2026.03.26-upe-lancedb-test-isolation-and-warm-fix.md)
- [ ] **[LUPIN] Trust & Prediction Documentation Update** — Revise `src/docs/proxy-admin-guide.md` for Phase 3 conformal/ICRL + Phase 4 UPE prediction engine. Create `prediction-engine-reference.md`. Blocked by Prediction System Validation Campaign completion.
  - **Scope**: proxy-admin-guide.md (Sections 7, 9, 10), new prediction-engine-reference.md, docs/README.md links
  - **Umbrella plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md)

### Config Migration — Claude Agent SDK

- [ ] **[LUPIN] Phase 5: Update agentic voice workflow skill** — Ensure `/lupin-new-claude-agent-sdk-voice-workflow` scaffolds new agents with `from_config()` pattern by default. Update templates in `src/workflow/agentic-voice-workflow.md`.

### CJ Flow: Timed Execution + Monopolize + Pause/Resume (Session 381 — IN PROGRESS)

- [ ] **[LUPIN] Phase 5: Notifications UI + WebSocket integration** — JS event subscriptions (`job_paused`, `job_resumed`), event handlers, paused/scheduled visual states on job cards, pause/resume toggle button, CSS. Continue next session.
- [ ] **[LUPIN] Phase 6: Documentation + E2E validation** — `websocket-events.md` updates, manual E2E test with live server.
- **Tracking doc**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md)

### CJ Flow: Unified Job State Machine (Pre-Hybrid Fast Lane)

- [ ] **[LUPIN] Refactor fragmented state tracking** — Replace `status` field + queue position + `paused` boolean with unified `job_state` column (`pending → queued → scheduled → running → paused → completed/failed/cancelled`). Touches 15+ files: protocol, 7 job types, consumer, persistence, routers, UI. Dedicated preparatory effort before Hybrid Fast Lane.
- **Assessment doc**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine-assessment.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine-assessment.md)
- **CJ Flow hub**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md)

### CJ Flow: Hybrid Fast Lane + Bounded Agentic Pool (Session 237)

- [ ] **[LUPIN] Phase 1.1: Add RLock to FifoQueue** — `fifo_queue.py`: wrap all mutating + reading methods with `threading.RLock()`
- [ ] **[LUPIN] Phase 1.2: Add config key** — `lupin-app.ini` + `lupin-app-splainer.ini`: `cj flow max concurrent agentic jobs = 3`
- [ ] **[LUPIN] Phase 1.3: Write thread safety tests** — `test_fifo_queue_thread_safety.py`: 4 concurrency tests
- [ ] **[LUPIN] Phase 1.4: Verify Phase 1** — New + existing unit tests pass
- [ ] **[LUPIN] Phase 2.1: Agentic pool + dispatcher refactor** — `running_fifo_queue.py`: ThreadPoolExecutor, route by isinstance, new methods
- [ ] **[LUPIN] Phase 2.2: Update shutdown sequence** — `main.py`: add pool shutdown before consumer thread
- [ ] **[LUPIN] Phase 2.3: Write agentic pool tests** — `test_agentic_pool.py`: 10 pool behavior tests
- [ ] **[LUPIN] Phase 2.4: Verify Phase 2** — New + existing unit tests pass
- [ ] **[LUPIN] Phase 3.1: API endpoint** — `/api/queue/pool-status` (optional)
- [ ] **[LUPIN] Phase 3.2: Integration verification** — Manual E2E test with concurrent agentic + sync jobs
- **Prerequisite**: Unified Job State Machine refactor must complete first (freshness review of this plan against new consumer loop)
- **Tracking doc**: `src/rnd/2026.02.19-approach-c-hybrid-queue-architecture.md`

### Playwright E2E Browser Testing (Session 252)

### DataFrame CRUD with Voice I/O — UI Testing + Voice Polish

- [ ] **[LUPIN] Interactive E2E Testing of CRUD Agents** — Execute the 29-scenario testing protocol at `src/rnd/2026.02.04-headless-cc-for-dataframe-crud/testing-protocol.md`.
  - [x] Part 1: Mock pipeline tests (17/17 passed — routing, pipeline, cache, confirmation, prompt construction)
  - [x] Bug fix: CRUD agent completion — emit_job_state_transition, answer guard, done queue push (3 new tests, 532/532 pass)
  - [x] Bug fix: TTS focus mode stuck — staleness check in restoreTTSQueueState + exit in moveToRegularNotifications (Session 164)
  - [x] **Bug fix: delete_item deletes all records** — Session 189: dedup guard, multi-delete guard, infra column rejection. 6 new tests (816 total). Commit fd21f0c.
  - [x] Part 3: Curl smoke tests → **SUPERSEDED** by `test_crud_live_pipeline.py` (8-scenario automated test, Session 189)
  - [x] **Run CRUD live pipeline test** — `test_crud_live_pipeline.py --mode direct --auto-proxy`. Session 267 fixed credential mismatch (CREDENTIAL_ENV_PREFIX unified).
  - [ ] Part 2: Notifications UI tests (8 scenarios, live server) — **Leverage Playwright E2E infrastructure**
- [ ] **[LUPIN] Phase 4: End-to-End Voice Workflows + Polish** - PENDING (blocked by Phase 3 ✅)
- **Note**: Moved to v0.1.6 to leverage Playwright E2E testing infrastructure for UI test automation

### Presentation Generator Agent (Session 362 — IN PROGRESS)

- [ ] **[LUPIN] Presentation Generator Agent: Transform research docs into slide decks** — 🔄 IN PROGRESS. Phases 1-5 complete, Phase 6 beginning. Next: Phase 6 (Text Rendering: Marp Markdown).
  - **Goal**: Agentic process (Claude SDK) that transforms ~1200-word research documents or technical blog posts into 10-20 minute slide decks with presenter notes. Single orchestrator pattern (like Podcast Generator).
  - **Architecture**: 8-phase pipeline (ingest, analyze, outline, elaborate, serialize YAML, render Marp, render Mermaid visuals, deliver). 4 human-in-the-loop gates. Pluggable visual renderer registry. Theme cascade (INI -> YAML template -> per-presentation overrides).
  - **R&D directory**: [`src/rnd/2026.03.14-presentation-generator/`](src/rnd/2026.03.14-presentation-generator/00-index.md)
  - **Phase 0**: DONE — Strategy & design serialized, implementation plan & tracking created (4 docs)
  - **Phase 1**: DONE — Foundation (Job, Config, Voice I/O, CJ Flow packaging) — Session 367b
  - **Phase 2**: DONE — State models & orchestrator skeleton — Session 367b
  - **Phase 3**: DONE — Content generation: ingest & analyze
  - **Phase 4**: DONE — Content generation: outline & elaborate
  - **Phase 5**: DONE — Content generation: serialize YAML
  - **Phase 6**: Pending — Text rendering: Marp Markdown
  - **Phase 7**: Pending — Visual rendering: Mermaid + registry
  - **Phase 8**: Pending — Delivery & DR-to-Presentation chaining (Phase 8)

### CJ Flow Persistence (Sessions 357, 360, 367 — BACKEND COMPLETE)

- [ ] **[LUPIN] CJ Flow Persistence: Job History UI page** — Future scope. Backend + API complete, no browser page yet. Pick up in next session to scope a job history viewer page.

### Universal Prediction Engine: Live E2E Validation (Session 340)

- [ ] **[LUPIN] Live E2E validation of all 7 UPE slices** — **CONSOLIDATED** into [Prediction System Validation Campaign](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md). See "Prediction System: Validation + Documentation" section above.

### Render Markdown Documents as HTML + Audio Player Viewer

### Trust Proxy Documentation Update

- [ ] **[LUPIN] Update trust proxy documentation** — **CONSOLIDATED** into [Trust & Prediction Documentation Update](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md). See "Prediction System: Validation + Documentation" section above.

---

## Pending

### History Archive (Session 280)

### SWE Team Proxy: Workload Generator + Shadow-Mode Capture

### SWE Team Proxy Agent (HIGH PRIORITY)

### Disambiguate Database Names (Session 343-344)

### Before Branch Merge

### TTS Focus Mode Race Condition (Sessions 346-347)

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/fastapi_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
---


---

## 📦 Archived

- [`todo-history/2026-04-10-to-2026-05-01-todo.md`](todo-history/2026-04-10-to-2026-05-01-todo.md) — 21 CLOSED + 10 MIXED-excerpt sections, 198 closed bullets, archived 2026-05-01 (Session 92ece47c)
