# TODO

Last updated: 2026-05-02 EDT (Session 0022baba shipped the WS reconnect circuit-breaker milestone end-to-end — 5 phases, 8 commits 234d7b7→1a9e3e0, 85 tests + 1 conditional skip across the full pyramid. Bug-fix-mode CLOSED for 0022baba. Two CoSA-submodule files await separate user-driven CoSA-context commit. Earlier same-day: Session 4ede5bad serialized the voice-persona /clear preservation fix design + dev-tools voice-persona-reference page + new `POST /api/cosa-voice/voice-persona/sample` endpoint. Earlier session ee678ca8 wrote post-mortem of 19:00 EDT all-test run. Earlier 2026-05-01: Session 92ece47c built `todo-size-management` skill + archived 21 whole CLOSED + 10 MIXED-excerpt sections to `todo-history/2026-04-10-to-2026-05-01-todo.md`; TODO.md 31.6k → 19.4k tokens (-38%); 208 pending items preserved.)

---

## ☀️ FIRST THING IN THE MORNING — 2026.05.03

### Pending

- [x] [LUPIN] **Commit the CoSA-submodule changes for the WS reconnect circuit-breaker milestone (Session 0022baba)** — committed by user on 2026-05-03 (CoSA-context session). Two files: `src/cosa/rest/routers/websocket.py` (4001/4002/4003 close-code constants + 10 queue auth-fail call sites) and `src/cosa/rest/websocket_manager.py:147` (displaced-socket close → `code=4002, reason="session_conflict_displaced"`). Parent Lupin commit `1a9e3e0` is the documenting reference.
- [ ] [LUPIN] **Archive `history.md`** — after today's 5-phase milestone, the file sits at 17,138 tokens (just over the 17k WARNING threshold). Run `/history-management mode=check` first to see velocity + recommended cut date, then `/history-management mode=archive` to slice older sessions to a dated archive in `history/`. Should reduce live file to ~8-12k tokens per project policy.
- [~] [LUPIN] **Land voice-persona /clear preservation fix** — design + execution log at `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/`. **Phase 1.1, 1.5, 2, 3 ✅ landed Session aacd24b4 (2026-05-03 AM)**. Phase 1.1 diagnostics live in `register_session.py` (gate-result, gate-2-fail, preserve-check stderr prints). Phase 2 added `_release_voice_persona_via_http` helper + invocation before bridge write. Phase 3 added `previous_persona_name` query param to `/allocate` + push-announcement, threaded from hook via URL-encoded query string. Unit tests at `src/tests/unit/test_register_session_preservation.py`: 8 passed + 1 xfailed (legacy `session_ids[]` case pinned to Phase 1.3). **Phase 1.2/1.3/1.4 still pending** — user must do one /clear on a planning session so we can read the new diagnostics from the CC transcript log to identify which gate failed; then a minimal patch + sweep of `register_session.py:699-703` (idle backoff carry-forward) lands and the xfail flips. CoSA edits: `src/cosa/rest/routers/voice_persona.py` allocate endpoint. Frontend stale-badge propagation (Fix 4) remains PARKED.

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
- [ ] [LUPIN] **Pick fix option for Cluster A (notification 503)** — see bug-fix-queue.md "Notification 503 cascade". 4 options documented (Option B is most surgical; Option C is most correct). Decision required before that bug can be fixed.
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
