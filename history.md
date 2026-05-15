# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-07 to 05-11](history/2026-05-07-to-11-history.md). History health: ✅ **HEALTHY at 13,151 tokens (52.6% of 25k)** — archived 2026-05-15 by Mr. Radio (session 23ff8512), 14,506 tokens moved to archive.

### 2026.05.15 - Session 3b6be6f9 (María 🌸) | Notifications UI three-fix arc: Recent-Activity refresh observability + focus-tray reload persistence + header-toggle children-wipe (with sweep of 2 latent same-pattern callers)

Chorus session continuation. Rick's morning `@all` broadcast assigned María the Commons blackboard lead role; status read confirmed Phase 3 fully closed 2026-05-13 (398 unit/smoke + 7 integration green), with the open follow-on backlog being the 4× persona-completion dup bug + `owner_user_id` writer stamper + stale-bridge sweeper. Rick then voice-redirected to three notifications-UI bugs ahead of the queue, fixed sequentially across the session. All three fixed and live-confirmed; no R&D doc per `feedback_skip_rnd_doc_for_trivial_fixes`.

**Bug 1 — `#commons-recent-activity-refresh` silent on click**: handler was wired correctly (`_initCommonsRecentActivity` → `addEventListener("click", …)` → `_loadCommonsRecentActivity`) but produced zero console output because `this.log()` is debug-gated and the happy path had no logs — only `this.error()` (unconditional) fired on `!resp.ok` or thrown exceptions. Rick was correctly unable to tell whether the click was firing. **Fix**: 3 unconditional `console.log` lines on the success path (click registered, load start with window value, load complete with entries count) per the existing `wsDiag` + Firefox-hack precedent for diagnostic logging that bypasses the debug flag.

**Bug 2 — focus-tray state dropped on every page reload**: persistence + restore were FULLY wired already (localStorage key `notifications_cc_focus_state`, constructor read, save-on-enter, save-on-exit, belt-and-suspenders `_restoreCcUiAfterLoad` after `loadConversationHistory()`). Root cause: **`_exitFocusMode()` always wrote the wiped state to localStorage**, and three call sites fired during init churn — `_removeStripIcon` on icon WS dealloc/re-add, `_clearAllStripIcons` on history-window change or bulk-clear, and `_restoreCcUiAfterLoad`'s stale-discard branch when the focused card hadn't hydrated yet at restore-check time. The design comment near `_restoreCcUiAfterLoad` had explicitly named WS-event icon churn as a known failure mode but the belt-and-suspenders restore couldn't recover from a localStorage that was already wiped.

**Fix shape — Option B (intent-preserving exit)** ratified via `ask_multiple_choice`: added `persist = true` parameter to `_exitFocusMode( persist = true )`; `_saveCcFocusState()` now gated on `persist`. Three auto-exit sites pass `persist=false`; the explicit user-toggle path at `_handleStripToggleClick` stays default `true`. Net: explicit toggle-off persists OFF; transient auto-exits during init churn preserve user intent so the next reload can re-apply focus.

**Bug 3 — Recent Activity header toggle nuked all entry contents (with sweep of 2 latent same-pattern callers)**:

After landing Bug 1 + Bug 2 and Rick voice-confirming, he reported a third bug: toggling the `#commons-recent-activity-header` accordion wiped the entire entries list, and subsequent refresh-button clicks logged only `[COMMONS-ACTIVITY] refresh clicked` — no `load start`, no `load complete`. Root-cause traced to `toggleSection()` at `notifications.html:1057-1068`: function does `sectionId.replace('-section', '-toggle')` to find the toggle-button id. The inline `onclick="toggleSection('commons-recent-activity-body')"` at L701 passes a body id that has no `-section` substring, so `replace` returns the input unchanged, `toggle === content`, and `toggle.textContent = '▶'` wipes the body div's children (including `#commons-recent-activity-entries`). Refresh's `if ( !entriesEl ) return;` then early-exits silently.

**Sweep finding via grep**: of 19 `toggleSection(...)` callers in `notifications.html`, three pass non-`-section` ids — today's `commons-recent-activity-body` (L701) PLUS two latent same-pattern bugs at `action-required-content` (L528) and `tts-queue-content` (L552). All three are sibling-header-above-content layout, so the same fallback applies cleanly to all of them.

**Fix shape — Option B+ (harden + sweep latents)** ratified via `ask_multiple_choice`: hardened `toggleSection` with a defensive fallback — if `toggle === content` (replace did nothing) or not found, look up `.toggle-button` inside `content.previousElementSibling` (the header div). Also guarded both `toggle.textContent = '▼'/'▶'` writes with `if (toggle)` so a missing toggle button no longer wipes the content div. Folded in a corresponding fix in `notifications.js`: moved the `[COMMONS-ACTIVITY] load start` log to BEFORE the early-exit guard (was misplaced in Bug 1's edit), and added a `console.warn` when the entries element is missing so future bail-out cases are observable instead of silent. Net effect: today's bug fixed at its root cause; two latent bugs at L528/L552 closed in the same commit without explicit caller-side changes; refresh-button observability gains a missing-element diagnostic.

**Verification table**:

| Layer | Result |
|---|---|
| `node --check notifications.js` (after bug-1 edits) | ✅ SYNTAX OK |
| `node --check notifications.js` (after bug-2 edits) | ✅ SYNTAX OK |
| `node --check notifications.js` (after bug-3 log-placement fix) | ✅ SYNTAX OK |
| Re-grep `_exitFocusMode\b` post-edit — confirms 4 auto-sites pass `false`, 1 user-site stays default | ✅ |
| Bug 1 — Rick live hard-refresh + click on `:7999` | ✅ all 3 log lines fire ("looks good") |
| Bug 2 — Rick live hard-refresh + set focus + hard-refresh on `:7999` | ✅ "that fixed it" |
| Bug 3 — `toggleSection` inline-script extracted from HTML + visually inspected post-edit | ✅ matches intent |
| Bug 3 + sweep — pending Rick's live hard-refresh + toggle-header probe (live confirmation expected this turn) | ⏳ |

**Files touched** (parent Lupin only — no CoSA edits, no other repos):

| File | Change |
|---|---|
| `src/fastapi_app/static/js/notifications.js` | 9 edits across two commits: Bug 1 = +3 unconditional `console.log` lines on Recent-Activity success path; Bug 2 = `_exitFocusMode( persist = true )` + 3 auto-exit sites pass `false`; Bug 3 = moved Bug-1's load-start log to BEFORE early-exit + added `console.warn` for missing-element case |
| `src/fastapi_app/static/html/notifications.html` | Bug 3 = hardened `toggleSection` with previous-sibling-header fallback + `if (toggle)` guards on both `textContent` writes; same fix closes latents at L528 (`action-required-content`) and L552 (`tts-queue-content`) |

**Parallel-session safety note**: at the first checkpoint (commit `7e27779`) AND at this second checkpoint, `git status` showed `bug-fix-queue.md` + `src/conf/lupin-app.ini` as pre-existing modifications from session `ea85fd64` (Mr. Radio 🦉) — both registering `retail-ai-location-strategy` as a new external doc-viewer scope + filing a related `/api/init` scope-registry hot-reload bug. Plus the untracked `src/rnd/v0.1.7/2026.05.15-rio-top-5-todo-bug-triage.md` from Rio ⚡'s morning chorus turn. All three explicitly excluded from this session's stage set per v2.0 selective-staging mandate. As a result, the "Recently Completed" section of `bug-fix-queue.md` was NOT updated to record these three fixes — Rick was notified that the queue update would require a stash-and-pop sequence to avoid bundling Mr. Radio's uncommitted work, and the queue-side documentation hand-off is deferred to whoever next has clear ownership of that file.

**Memories**: none new — all three fixes follow existing project precedents already captured in memory (`wsDiag` unconditional logging pattern; the design comment near `_restoreCcUiAfterLoad` had already named the failure mode for bug 2; `toggleSection`'s sibling-header pattern is the standard layout for `.collapsible-section` callers and the previousElementSibling fallback follows that established structural convention).

**Commit history this session**:
- `7e27779` — Bug 1 + Bug 2 (notifications.js + history.md + .claude-session.md)
- [next commit] — Bug 3 + sweep (notifications.html + notifications.js + history.md + .claude-session.md)

---

### 2026.05.15 AM - Session c4139ece (María 🌸) | Commons Blackboard summary + per-recipient broadcasts-topic dedupe fix for Recent Activity panel + new bug filed for persona-completion 4× rendering

Chorus session triggered by Rick's morning `@all` broadcast. María's assignment was the state-of-the-commons-blackboard summary; delivered via `notify` with rich abstract carrying phase status, doc-viewer links, endpoint inventory, coverage posture. Course-corrected mid-turn when Rick flagged that the spoken `message` body had piped the inventory through TTS rather than keeping it to headline + one-sentence takeaway; rule re-internalized per existing `feedback_tts_body_headline_and_takeaway_only` memory.

**Bug surfaced + fixed during the same session — broadcast-card Recent Activity duplication**:

Rick reported his single morning `@all` broadcast appeared **five times** on the broadcast card's Recent Activity stream. Investigation confirmed the dupe was in the **WRITE path of Phase 2**, not the render path:

- Phase 2's `perform_fanout` at `src/cosa/rest/routers/commons.py:329-380` writes one `broadcasts`-topic row per recipient by design (line 348: `# AC4: per-recipient broadcasts entry`) — supports the `target_session_id` branch of `_entry_passes_same_user_scoping` for normal session-receipt scoping. It became visible-as-noise once Traffic Visibility surfaced the raw topic.
- The live store file `io/commons/broadcasts.md` confirmed: six distinct `broadcast_id` values from this morning, each with 2-5 fanout rows sharing the same body. The morning `@all` (broadcast_id `0a2b0b2e…`) had 5 rows differing only in `metadata.target_session_id`.

Rick pressure-tested the proposed fix: *"How does your filter differentiate between one batch sent to @all at 10:35 and then the next batch sent to @all at 10:40?"* Verified safe via `commons.py:429` (`broadcast_id = body.broadcast_id or str(uuid.uuid4())`) — each broadcast call mints a fresh UUIDv4 server-side; dedupe collapses **within** a broadcast, never **across** broadcasts.

**Fix shape** (1 helper + 1 wire-up + 8 unit tests + 2 wire-level smoke tests + design doc subsection):

| Change | File |
|---|---|
| `_dedupe_broadcasts_by_id` helper added; wired between merge-sort and limit-cap in `execute_broadcast_history` | `src/cosa/rest/routers/commons.py` (CoSA submodule — NOT staged from parent context per nested-repo rule) |
| +8 unit tests covering: same-id collapse, distinct-id preservation, `target_session_id` strip, input non-mutation, non-`broadcasts` topic passthrough, missing/non-string `broadcast_id` defensive passthrough, end-to-end through `execute_broadcast_history`. Extended `_make_entry` with `broadcast_id` param. Added import. | `src/tests/unit/commons/test_commons_router.py` |
| +2 live-`:7999` smoke tests asserting wire-level invariants (no duplicate `broadcast_id` in response; `target_session_id` stripped from deduped rows) | `src/tests/smoke/test_commons_broadcast_history_endpoint.py` |
| Post-ship-fix subsection added — root cause, fix mechanics, safety argument, test table | `src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md` |

**Verification table**:

| Layer | Suite | Result |
|---|---|---|
| `py_compile` | `commons.py` + `test_commons_router.py` | ✅ clean |
| Unit | `src/tests/unit/commons/` (407 tests) | ✅ 407/407 |
| Unit (new) | dedupe + history (17 tests, 8 new) | ✅ 17/17 |
| Smoke (`:7999`) | `test_commons_broadcast_history_endpoint.py` (9 tests, 2 new) | ✅ 9/9 |
| Coverage gate | `cosa/rest/routers/commons.py` | **100%** (238/238 stmts, 0 missing) |
| Phase 2 contract | 119 pre-existing tests in `test_commons_router.py` | ✅ preserved, all GREEN |

**Behavior change**: 5 recipients × 1 broadcast → 1 admin-overview row (was 5 rows). Distinct broadcasts never collapse. The kept row strips `target_session_id` (represents the broadcast as a whole, not any single recipient slice). `broadcast-acks` per-recipient rows untouched — those are the intended chip-row UX.

**New bug filed** (Queued, top): persona-completion notifications duplicating 4× on the broadcast / Recent Activity card with near-identical timestamps (Rick verified post-dedupe-fix, observed `maria completed 10:14 🌸` rendered four times). Filed to `bug-fix-queue.md` with full repro context, four ranked plausible causes, and the disambiguation diagnostic the next session must run first (entry count in topic store vs DOM cards). NOT the same bug as today's per-recipient fanout — separate surface, separate root cause.

**Files touched** (parent Lupin only — CoSA-side edit to `src/cosa/rest/routers/commons.py` belongs to a CoSA-context commit):

- `src/tests/unit/commons/test_commons_router.py` (+8 unit tests, import added, `_make_entry` extended)
- `src/tests/smoke/test_commons_broadcast_history_endpoint.py` (+2 wire-level smoke tests)
- `src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md` (post-ship-fix subsection)
- `bug-fix-queue.md` (new bug filed at top of Queued; Last Updated bumped)
- `history.md` (this entry)
- `.claude-session.md` (María's section appended for parallel-session safety)

**Parallel-session safety note**: At checkpoint time, `git status` confirmed only María's tracked files appeared; no other active sessions had modified content overlapping with this commit's stage set.

---

### 2026.05.15 AM - Session 23ff8512 (Mr. Radio 🦉) | PRIORITY-1 history.md archive (4x-deferred OVER-LIMIT condition resolved) + chorus broadcast response

Two-task chorus session triggered by Rick's `@all` broadcast asking each persona to start a new session and report. Mr. Radio's assignment was the top-five Lupin TODO summary excluding the Commons blackboard project (Maria's territory). Surveyed `TODO.md` and surfaced the headline finding: history.md was **27,657 tokens / 110.6% of the 25k ceiling** — the four-times-deferred PRIORITY-1 archive task. Rick voice-replied "do this 1 thing for me right now: archive the history document."

**Archive operation** (executed via `/history-management mode=archive`):

- **Cut point**: clean date boundary at line 619/620 — between 2026.05.12 PM (Inter-Session Commons Phase 2 closure session by Tiberius) and 2026.05.11→2026.05.12-AM (Phase 1 wrap session by Rachel). No mid-date splits required.
- **Archive file created**: `history/2026-05-07-to-11-history.md` (NEW, 750 lines, 14,600 tokens, 12 sessions covering 2026.05.07 → 2026.05.12 AM). Header includes archive period, archived-on date, reason ("🚨 OVER LIMIT, fourth-deferral archive run"), and prev/next navigation links.
- **Main `history.md` truncated**: 1,359 → 619 lines; 27,657 → 13,151 tokens (110.6% → 52.6%); back to ✅ HEALTHY band with substantial headroom for next session's growth. Banner on line 3 refreshed to reflect new state.
- **`history/README.md` index updated**: added the new 2026-05-07-to-11 entry AND a previously-missing 2026-05-03-to-06 entry (oversight from a prior archive op). Quick Stats refreshed (20 → 22 archives, 359+ → 384+ sessions, last-updated → 2026-05-15).
- **`TODO.md` PRIORITY-1 entry marked ✅ DONE** with closure note documenting the final token deltas + cut location + archive filename.

**Token math**:

| Metric | Before | After |
|---|---|---|
| Tokens | 27,657 | 13,151 |
| % of 25k ceiling | 110.6% 🚨 | 52.6% ✅ |
| Lines | 1,359 | 619 |
| Health | OVER LIMIT (4× deferred) | HEALTHY |

**Chorus broadcast response (top-5 Lupin TODOs excl. Commons)**: delivered via `notify` with full detail in abstract. Headline #1 was the archive itself (now resolved this session). #2 Multiplexer Phase 6c Q-decisions queue (15 Qs across Clusters B/C/D, awaiting Rick's pull-trigger). #3 Bounded ClaudeCodeJob D1-D9 ratification (blocks 3 migration phases). #4 Rachel's `doc_scope` registry exposure for cosa-voice (Lupin owes the integration endpoint). #5 María's `owner_user_id` writer-side stamper (completes yesterday's broadcast-UI fix).

**Files touched** (parent Lupin only — no CoSA edits, no commits beyond this session-end checkpoint): `history.md` (truncated + banner + this entry), `history/2026-05-07-to-11-history.md` (NEW archive), `history/README.md` (index + stats), `TODO.md` (PRIORITY-1 closure), `.claude-session.md` (parallel-session-safety section for 23ff8512).

**Parallel-session safety note**: `git status` showed three pre-existing modified files from other sessions (`src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md` + 2 commons test files — María's territory, NOT mine). Selective staging per v2.0 mandate — only Mr. Radio's 4 archive-related files staged.

**Tests**: N/A — pure documentation operation; no code touched, no test surface affected. Final `get-token-count.sh` health check: ✅ HEALTHY 52.6%.

**Memories**: none new — task was a mechanical archive per established workflow; no surprises or new patterns surfaced.

**Commit**: pending (this session-end checkpoint)

---



Fourth bug-fix arc of the day continuing the TTS preview-and-pause evolution. After the morning's preview/Mr.-split fix (`d87e0d7`), afternoon's decouple (`efbcae3`), and evening's stop-and-slider (`5836a6f`), Rick asked for a per-session DND toggle reframed from the afternoon's parked speakerphone-toggle plan. Key reframe: **muted ≠ silent.** Notifications still arrive for historical record, just demoted from `priority='high', suppress_ding=True` to `priority='medium', suppress_ding=False`. Small ding on arrival, no full TTS.

**Implementation:**
- **Slider relocated** from `#cc-session-strip` to the Claude Code notifications `.section-header` (always-visible accordion row). Centered between filter badge and history dropdown via dual `margin-left: auto`. "History:" label removed from the history-window widget per Rick's tweak.
- **Per-session toggle** replaces legacy `sender-conversation-mode-btn`. POST hits canonical `/api/cosa-voice/speakerphone/{session_id}` with body `{on: bool}` (NOT `{active}` — caught via 422 mid-session, field-name memory saved).
- **Universal strip-icon badges**: every persona icon in `#cc-strip-icons` shows EITHER 🔊 (speakerphone, default) or 🤭 (quiet) in its bottom-right corner via `data-conv-mode="speakerphone"|"quiet"` attribute. Per Rick: "Everybody gets state rendered."
- **"Loud" → "speakerphone" rename** in all tooltips + comments (Rick: "no pejorative connotation").
- **Hook rider quiet-mode body** rewritten at `_speakerphone_reminder_body` — when speakerphone is off, rider tells Claude to call notify with `priority='medium', suppress_ding=False` instead of the legacy "stop calling notify; terminal-only" body.
- **Exit-reminder body** unified — `speakerphone_exit_reminder` now matches the steady-state quiet-mode directive (no more contradiction on transition).
- **Client-side belt-and-suspenders priority rewrite** at top of `handleNotificationUpdate` — catches the case where Claude doesn't honor the rider.
- `tts_interaction_mode` exposed via `/api/config/client` for mode-conditional icon rendering (chorus → 🔊/🤭, solo → 📞/🔔).

**Files** (Lupin only): `notifications.js`, `notifications.css`, `notifications.html`, `system.py`, `hook_common.py`, plus 4 new R&D docs at `src/rnd/v0.1.7/2026.05.14-per-session-dnd-toggle-and-slider-move-*` + the session-wrap pickup-tomorrow doc + a SUPERSEDED banner on the afternoon's parked speakerphone-toggle doc.

**Tests**: `node -c` PASS on notifications.js, `py_compile` PASS on `hook_common.py` and `system.py`. Live MCP verification at speakerphone-on (full TTS played for both test slots) + speakerphone-off (medium-priority dings + no TTS). Universal-badge rendering verified visually.

**Known pickup for tomorrow**: cc_notification_listener daemon (PID 24166) holds stale `speakerphone_exit_reminder` in `sys.modules`; restart needed to load the new body. Captured in `2026.05.14-session-wrap-pickup-tomorrow.md`.

**Memories saved this session (4 new)**: `feedback_walk_through_plan_before_asking_proceed`, `feedback_commons_post_is_blackboard_not_push`, `feedback_always_serialize_plan_to_rd_scope_post_exit`, `feedback_verify_pydantic_field_names_against_server_schema`.

**Commit**: 60697e2

---

## Session-end LoC summary (a0eaaca1 / Mr. Radio — 2026-05-14)

| Commit | Description | Files | Insertions | Deletions |
|---|---|---|---:|---:|
| `d87e0d7` | TTS preview action-required + Mr.-split + match() prefix-drop | 6 | +624 | -27 |
| `efbcae3` | Notification-list / TTS-queue decouple | 7 | +220 | -12 |
| `ea7f90f` | TTS preview-and-advance + slider + strict FIFO | 9 | +655 | -165 |
| `60697e2` | Per-session DND toggle + slider relocation + universal badges | 12 | +925 | -76 |
| **Totals** | **4 commits** | **34 file-touches** | **+2424** | **-280** |

Net delta: **+2144 lines** across the day. All Lupin parent repo; CoSA submodule untouched per nested-repo rule.

---

### 2026.05.14 Evening - Session a0eaaca1 (Mr. Radio 🦉) | TTS preview-and-advance + runtime percentage slider + strict FIFO

Third bug-fix arc of the day for the TTS preview-and-pause feature. After the morning's action-required + Mr.-split fix (`d87e0d7`) and the afternoon's notification-list decouple (`efbcae3`), Rick asked for two more shape changes: (1) stop instead of pause — the auto-pause-after-preview was the wrong default for a multi-session listener; (2) add a runtime percentage slider in the Claude Code session strip with five stops (0/25/50/75/100) acting as a "global verbosity filter."

**Implementation (7 phases, all landed):**

- **Phase 1 — Stop instead of pause + strict FIFO**: Removed `onTTSPlaybackComplete` preview-pause early-return, `resumeTTS` preview-remainder branch, `stopTTSAndAdvance` special case, `_ttsPausedAfterPreview` field, `remainderText` from item shape, and simplified playback dispatch routing. Strict FIFO in `addToTTSQueue` — every item pushes to back regardless of type (action-required no longer jumps the queue). Phase 1g added per Rick's "oldest at top" directive.
- **Phase 2 — `stage='skip'` for 0% slider**: `_computeTTSPreview` early-returns on fraction=0; `activateNextTTS` skip branch clears `.is-tts-pending`, advances queue immediately with 50ms timeout to prevent infinite-loop.
- **Phase 3 — Slider HTML + CSS**: `.cc-tts-fraction-control` inserted into `#cc-session-strip` between persona-icon tray and Focus/All buttons. New `.cc-tts-fraction-*` rule block (~50 lines).
- **Phase 4 — JS slider state wiring**: `TTS_FRACTION_PREF_KEY` localStorage key; layer user override on top of INI seed default after `/api/config/client` fetch; `input` event listener.
- **Phase 5 — Parent design doc override**: appended `## 2026-05-14 Override` to `2026.05.13-tts-preview-and-pause-design.md` tabulating superseded Q-decisions.
- **Phase 6 — Live verification**: 4 long notifies at 25% (default) — Rick confirmed FIFO order + preview-and-advance. 3 long notifies at 0% — Rick confirmed silent. 4 long notifies at 50% — Rick confirmed verbosity filter shape ("UX I was looking for").

**Files** (Lupin only): `notifications.js`, `notifications.css`, `notifications.html`, parent design doc override, new design + execution log at `src/rnd/v0.1.7/2026.05.14-tts-preview-stop-and-slider-*`.

**Tests**: `node -c` PASS. Live MCP verification at 3 slider positions confirmed by Rick.

**Commit**: ea7f90f

---

### 2026.05.14 Evening - Session f6f865fb (María 🌸) | Two bug fixes + Commons Traffic Visibility 11-step feature

Three-phase evening. **(1) Broadcast filter bug** — Rick saw 1 of 4 personas in the inter-session-commons broadcast UI. Root cause: Phase 3 Option 2 stamper wrote the LISTENER's service-account UUID, but the filter compares against the HUMAN owner's JWT UUID — every stamped bridge rejected. Option C ratified: NEW `owner_user_id` field with graceful-degradation fallback. Diagnosis: `src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md`.

**(2) Focus-bar persistence bug** — Rick reported refresh in CC-session focus mode loses focus. Belt-and-suspenders fix `_restoreCcUiAfterLoad()` shipped — but Rick's post-commit live test showed the symptom PERSISTS (`[FOCUS-RESTORE]` log not firing per his report). Bug parked to `bug-fix-queue.md` with a 3-way diagnostic decision tree for next session. Design: `src/rnd/v0.1.7/2026.05.14-focus-bar-state-persistence-restore.md`.

**(3) Commons Traffic Visibility 11-step feature** — Rick surfaced a new UX gap: zero admin visibility into broadcasts + AI-to-AI commons traffic (tonight's `notifications-ui-coord` vs `coord-notifications-js` topic mismatch demonstrated the blind spot). Design ratified via 9 Q-decisions captured one-at-a-time via `ask_multiple_choice` MCP. Built end-to-end: Recent Activity section inside the broadcast card with real-time WS push, INI-flag-gated default-on, exclude-noisy-topics filter, history-window dropdown mirroring the existing UX pattern, flat reverse-chronological, AI-replies routed broadcast-card-only. 13 ACs / 11 steps / one commit per step. Design + step plan: `src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md`.

**Lupin commits (16 total this session, in order)**: `cd62304` (broadcast filter Lupin tests + writer-stamper TODO), `0a7da69` (focus-bar first-pass — superseded by parking), `c940f72` (mid-session history+manifest), `284c9fe` (mid-session manifest backfill), `1538bbe` (focus-bar parked + diag tree to queue), `c06a2ea` (CTV Step 0 design doc), `7de7020` (CTV Step 1 INI), `ab40388` (CTV Step 2 helper tests), `5ca6662` (CTV Step 3 :7999 smoke), `30cfae7` (CTV Step 4 watcher + tests), `15599db` (CTV Step 6 HTML+CSS), `6136a88` (CTV Step 7 JS), `fe352b8` (CTV Step 8 suppression), `e28d89f` (CTV Step 9 integration scaffold), `c1496ee` (CTV Step 10 E2E scaffold), `87dbae4` (CTV Step 11 docs).

**CoSA-side uncommitted** (per `feedback_never_commit_cosa`, Rick handles): `rest/routers/commons.py` + NEW `rest/commons_activity_watcher.py` + `rest/routers/notifications.py` valid_types + `rest/routers/system.py` config-client extension. +552 / -17 across 5 files.

**LoC summary (Lupin commits only)**: **25 file changes, +2881 / -28 (net +2853)** across 16 commits. CoSA uncommitted adds another **+552 / -17 across 5 files**.

**Tests**: 87/87 commons-router unit + 15/15 activity-watcher unit + 24 new aggregator unit + 7/7 :7999 broadcast-history smoke = **133+ tests added, all green on `:7999`**. `:8000` integration + E2E UI scaffolded (Steps 9-10), user-scheduled run pending.

**Coordination**: Mr. Radio (a0eaaca1) had three coincident bug-fix arcs landing on the same `notifications.js` + `notifications.html` files (`efbcae3`, `5836a6f`, etc.). Used a Python-script-driven surgical hunk-extraction at commits `15599db` + `6136a88` + `fe352b8` to extract just my hunks from the unstaged diff, reset the file to HEAD, apply my patch, commit, then restore Arnold's working-tree state — kept the Maria-only commits clean while preserving Arnold's uncommitted work for his own context. Parallel-session-safety v2.0 mandate honored.

**Bring-live checklist**: (a) Rick commits CoSA-side in a CoSA-context session, (b) `:7999` bounce so the new `CommonsActivityWatcher` lifespan code starts the daemon. Then visit `/app/notifications` — broadcast card opens default-expanded, Recent Activity section shows all four personas' coordination chatter in real-time.

**Coordination**: Mr. Radio's TTS-rendering work (commit `efbcae3`) coincident on `notifications.js` — coordination handled via `coord-notifications-js` commons topic. Different regions (his lines 5610 + 13278, mine 9522 + 418). No conflict. Cross-topic coordination misfire (I posted on `notifications-ui-coord`, he on `coord-notifications-js`) is the "coordination bug" Rick flagged mid-session; both topics now archived.

### 2026.05.14 PM - Session a0eaaca1 (Mr. Radio 🦉) | Decouple notification-list render from TTS-queue advancement

Follow-on bug from the morning's TTS preview-and-pause shipment. Symptom: 20+ high/urgent fire-and-forget notifications backed up invisibly while TTS was paused mid-preview — Rick couldn't see them in the list, only audio was paused.

**Root cause** (Explore-verified): high/urgent fire-and-forget took a deferred render path. `addNotificationToSenderGroup` was called from inside `activateNextTTS` at `notifications.js:13281`, which is gated by `if ( this.isTTSPaused ) return;` at line 13244. My morning's preview-and-pause feature sets `isTTSPaused=true` after each preview, stranding the deferred render. Scope: high/urgent fire-and-forget only — low/medium already rendered immediately on WS arrival; action-required uses a separate render path.

**Fix**: render immediately on WS arrival in `handleNotificationUpdate` (mirrors low/medium pattern); remove the now-duplicate deferred call from `activateNextTTS`. New `.is-tts-pending` CSS class marks cards queued-for-TTS-but-not-yet-playing with a subtle amber stripe + ⏳ corner glyph; cleared when the card engages playback.

**Files** (Lupin only): `src/fastapi_app/static/js/notifications.js` (~25 lines net), `src/fastapi_app/static/css/notifications.css` (+30 lines), new design + execution docs at `src/rnd/v0.1.7/2026.05.14-notification-list-tts-decouple-*`.

**Tests**: `node -c` PASS. Live MCP verification — fired 2 long fire-and-forget notifies from session `a0eaaca1`; second arrived while first was paused mid-preview; Rick visually confirmed second card appeared in the list immediately with the amber + ⏳ pending visual.

**Coordination**: Maria (session `f6f865fb`) held focus-bar persistence work until this commit landed to avoid `notifications.js` collision. Post-commit DM posted to `coord-notifications-js` commons topic.

**Commit**: 701a76f

---

### 2026.05.14 PM - Session a0eaaca1 (Mr. Radio 🦉) | TTS preview bug-fix: action-required opt-out + Mr.-split

Two-bug fix to the 2026-05-13 TTS preview-and-pause feature. Bug A (URGENT cost burn): action-required notifications opted OUT of preview, so every long `ask_yes_no`/`ask_multiple_choice`/`converse` played in full TTS. Bug B (correctness): `_splitIntoSentences()` regex falsely split `Mr.` as a sentence, previewing only "Mr." (~16 chars of 580) for Rick's session-end message.

**Fix** in `notifications.js`: (1) removed action-required from `_computeTTSPreview` opt-out, (2) swapped response handler at 15139 to `stopTTSAndAdvance()` to avoid auto-pause stall, (3) rewrote `_splitIntoSentences` with 25-abbreviation pre-mask + `match()`→`split()` lookbehind+lookahead (fixes "Mr." + latent "3.14"-prefix-drop), (4) `Math.floor`→`Math.ceil` for previewCount, (5) inline `_tts_quick_self_test()` with 9 cases gated on `this.debug`.

**Files** (Lupin only): `src/fastapi_app/static/js/notifications.js`, new design+execution docs at `src/rnd/v0.1.7/2026.05.14-tts-preview-action-required-and-mr-split-*`, `.claude-session.md`, `bug-fix-queue.md`.

**Tests**: `node -c` PASS. Live MCP verification — long `ask_yes_no` previewed+paused with mid-pause yes click advancing queue cleanly; verbatim replay of yesterday's "Mr. Radio..." message now previews 3 sentences ending at "...tracking branch" instead of just "Mr." Cost impact: ~75-80% TTS spend savings per long action-required ask.

**Commit**: 47fa399

---

### 2026.05.13 PM - Session b28069a6 (Maria 🌸) | Commons Phase 3 + broadcast-UI arc — 12 commits

Phase 3 barrel-through `27b82f1`→`ac5c4aa` (7 commits): question watcher + xml models + LLM disambiguator + register-question endpoints + push-mode + listener branch + lifespan. 398/398 tests :7999, 7/7 integration :8000. Backend bug arc: `4cb5fe1`/`93b302d` graceful-filter + listener user_id stamping (`[]` → 5 sessions); `2dff191` phantom filter via `idle_detection.last_interaction_at` + INI 600→28800s. UI iteration: `54c8e05`/`26874fb`/`300b3c0`/`8771c33` panel relocation + mic + compose-row redesign + Playwright refresh (11/11 PASSED :8000). Co-commit attribution to Arnold's `recordingMode='broadcast'` extension in `54c8e05`. CoSA-side commits pending separately. Full details in TODO.md closure section + 2 diagnosis docs at `src/rnd/v0.1.7/2026.05.13-broadcast-*`.

---

### 2026.05.13 PM - Session 9fae8c74 (Rio ⚡) | Multiplexer Phase 6c Q-decisions queue built — pull-mode handoff

**Persona**: Rio ⚡ (Young & energetic female, #880E4F)

**Topic**: Status briefing on multiplexer Phase 6b (CLOSED 2026-05-12) + Phase 6c (DRAFT, Cluster A 5/5 ratified). Rick requested pull-based Q-decisions walkthrough for Clusters B/C/D — he'll be working interstitially across other projects and wants to advance the queue on his cadence ("next" / "ready" trigger phrases) rather than at my pace. Queue built; awaiting Rick's first pull trigger.

**Accomplishments**:

- Read `97-phase6b-closure.md` + `10-phase6c-persona-focus-recorder-design.md`; surfaced 15-question queue (Cluster B × 5, Cluster C × 6, Cluster D × 4). Confirmed Cluster A already ratified 5/5 on 2026-05-12 by Rachel 🕊️ (chip-trigger + Popover API + × button + subtle persona color + `(borrowed)` label).
- Built pull-mode protocol with explicit trigger phrases (next / ready / fire / skip / back up / pause / TOC) and committed to per-question format: proposed answer + alternatives walked + per-option pros/cons + recommendation with flip-condition, with TTS body carrying only headline + takeaway and rich detail in `abstract` (per `feedback_tts_body_headline_and_takeaway_only` + `feedback_always_include_pros_cons_recommendation`).
- TODO.md updated with full queue contents + resume protocol so the queue position survives /clear and parallel-session interleaving.
- No source files touched this session.

**Files modified** (parent Lupin only):

- `TODO.md` (Phase 6c queue position + resume protocol entry near top)
- `history.md` (this entry)

**Session-end note**: Rick is away (doctor's appointment broadcast 2026-05-13 PM) and explicitly requested "no push, no backup" on the session-end ritual. Commit prep stops at the approval gate per `feedback_never_auto_commit_push` — no auto-commit. Working tree contains other sessions' uncommitted changes (`notifications.js`, INI pair, new 2026.05.13 R&D docs) which are NOT mine to commit per parallel-session safety.

---

### 2026.05.13 Late Morning - Session 66d534ab (Tiberius 🌑) | Bounded-CC Migration Audit & Plan (post-9d55ed1 continuation)

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Topic**: After commit `9d55ed1` (notifications UI tweaks) landed, Rick asked for a deep codebase census of bounded-ClaudeCodeJob migration opportunities. Spawned an Explore agent to audit every LLM call site, classified each against the Q1-Q5 fit rubric from the cost-model doc, then ultrathunk a sequenced migration plan with full pros/cons/flip-conditions/recommendations per `feedback_always_include_pros_cons_recommendation`. Plan-only — no code touched.

**Accomplishments**:

- **Comprehensive LLM call-site census** — every `AsyncAnthropic` import + `LlmClientFactory` usage + non-Anthropic provider call mapped. Findings: 2 already on bounded CC (BFE, TFE), 3 clean candidates (Deep Research, Podcast, Presentation — all flagged in TODO.md), 1 borderline deferred (Runtime Argument Expeditor), 2 explicit-stays (notification_proxy high-QPS + decision_proxy latency-sensitive), 9 inline `LlmClientFactory` latency-violators, 4 OpenAI sites out-of-scope. Audit confirmed there are NO hidden migration opportunities beyond Rick's known set.

- **Decision matrix authored** with 9 ratifiable decisions (Rick's original 5 + 4 surfaced during deeper analysis):
  - D1 phase ordering (Podcast first vs Deep Research first vs parallel)
  - D2 `scheduled_at` default (post-midnight off-peak)
  - D3 Deep Research progress events (preserve via tool-use surfacing vs simplify to result-on-complete)
  - D4 OpenAI sites (defer vs eliminate)
  - D5 Runtime Argument Expeditor (defer with trigger vs permanent stay)
  - D6 output parser strategy (strict / lenient / hybrid per-migration)
  - D7 agentic-pool concurrency
  - D8 `cost_usd` telemetry preservation
  - D9 migration-marker convention (`__init__.py` banner vs INI key vs nothing)
  - Each carries per-option pros + cons + flip-condition + my recommendation per memory rule

- **Supporting sections in the audit doc**:
  - Quantitative cost-impact model + ordering-by-impact qualitative analysis + time-to-savings curve
  - Consolidated 9-risk register ranked by impact × probability × detection-difficulty
  - Per-phase test strategy matrix mapping every tier (py_compile/unit/smoke/WS/integration/verification/parity-check)
  - Per-phase rollback playbook (git revert is the only path; no feature flags per `feedback_feature_flag_preserves_old_path`)
  - 14-item Definition-of-Done checklist per phase

- **Session etiquette**:
  - Updated session topic via `set_session_topic("Bounded-CC Migration Audit & Plan")` after the original "Bug Fix: Notifications UI" focus pivoted
  - Saved new memory `feedback_doc_links_always_in_abstract.md` after Rick flagged that my handoff-to-Arnold notify buried the doc link past a header; resent with link as line 1 of abstract, naked syntax
  - Acknowledged Rick's two "doctor's appointment" broadcasts cleanly (one to ack receipt, one to confirm I'd continue fleshing while he was out)
  - Honored the "no code yet only thinking and planning" directive throughout

- **Handoff doc to Arnold** (`src/rnd/v0.1.7/2026.05.13-handoff-to-arnold-notifications-ui-changes.md`) — summarized the 9d55ed1 notifications.js changes (focus-bar persona-initial, pause-on-record state machine, barge-in queue-gate fix) plus a semantic-changes table flagging symbols where Arnold's speakerphone work could overlap. Arnold picked up the doc in commit `0c4e565`.

- **Top-5 TODO scan** delivered earlier in the session — voice-driven request to surface new work, with the multimodal-munger bug flagged at #1 (turned out Arnold had already fixed it as a collateral catch). Marked it ✅ in TODO.md mid-session.

- **Bug-fix-queue summary** delivered — confirmed IMMEDIATE slot empty + 8 outstanding entries split between user-gated (PEFT training, design conversations) and cleanup tasks. Recommendation: stay on Inter-Session Commons Phase 3 trajectory; none preempt that work.

**Files modified** (in this post-9d55ed1 arc):
- `TODO.md` — bounded-CC migration tasks added at top + handoff to plan-review status; munger entry marked ✅
- `src/rnd/v0.1.7/2026.05.13-bounded-cc-migration-audit-and-plan.md` (NEW)
- `history.md` — this entry
- `.claude-session.md` — session-section updated with touched files

**NOT modified** (parallel-session work visible in `git status` — left alone per `feedback_verify_staging_before_commit`):
- `src/fastapi_app/static/js/notifications.js` — Arnold's broadcast/STT work (already committed at `0c4e565`, additional uncommitted changes left for that session)
- `src/conf/lupin-app.ini` + splainer — Arnold's INI additions for broadcast munger / TTS preview
- `src/rnd/v0.1.7/2026.05.13-tts-preview-and-pause-{design,execution-log}.md` — Arnold's R&D docs

**Awaiting**: Rick's voice directive on D1-D9 (ratify all, or flip specific decisions). Once ratification lands, Phase 1 execution plan gets serialized to `src/rnd/v0.1.7/2026.05.13-podcast-bounded-cc/` (or whichever ordering Rick picks) with full Pass 0 / REUSE / Pass 1 / Pass 2 plan-review machinery per `feedback_pip_plan_review_is_sequential`.

### 2026.05.13 PM - Session 6d663b6c (Arnold 🪨) | Broadcast munger mode + TTS preview-and-pause cost-reduction feature

**Persona**: Arnold 🪨 (Gravelly male, #FFD600)

**Topic**: Two substantive features landed this session. (1) Broadcast `@mention` munger mode — a new `multimodal text broadcast` munger that preserves `@`, `_`, `.` for `@mention` syntax via phrase-preprocessing and identifier-joining tokenizer semantics. Wired to the broadcast accordion's mic via `recordingMode="broadcast"`. (2) TTS preview-and-pause cost-reduction feature — every long-form TTS message now plays only the first ~25% of its sentences (configurable via INI) and auto-pauses; user resumes via existing pause/play/stop controls, sending the remainder as a separate TTS request. Cost saving is real because both ElevenLabs and OpenAI charge at provider-request-time (not per-byte streamed) — splitting client-side before the API call is what saves dollars.

**Accomplishments**:

- **Broadcast munger mode** — new `munge_text_broadcast` method in `multimodal_munger.py`. Phrase-preprocesses `at sign`/`question mark`/`exclamation point` → `@`/`?`/`!` (multi-token map entries the per-token tokenizer can't match). Adds identifier-joining tokenizer loop where `.`/`_`/`#` collapse surrounding spaces (`file_name dot py` → `file_name.py`). OMITS the line-757 `[,.]` strip from default mode so periods and commas survive. Adds 3 ad-hoc cleanup rules (collapse comma runs, drop `,!` → `!`, drop `!.` → `!`) per Rick's voice request. 20 inline broadcast smoke cases all PASS. Full unit pyramid 4413 passed/0 failed.

- **Broadcast wiring** — `notifications.js:1925` broadcast STT button now passes `{ recordingMode: 'broadcast' }`. `handleSTTButtonClick` evolved to accept + forward an `options` parameter. `startRecording` builds the upload endpoint with `?prefix=multimodal+text+broadcast` query param when `recordingMode === 'broadcast'`. All other STT buttons (research/podcast/presentation/SWE/CC session/Q&A/MC/yn-comment/batch/job-msg) unchanged on the default path.

- **TTS preview-and-pause feature** — 12 implementation sub-tasks closed. Sentence splitter (`_splitIntoSentences`) with capital-letter lookahead regex + word-count fallback. Queue item shape evolved with `previewText`/`remainderText`/`stage` fields. `addToTTSQueue` computes preview/remainder up-front with opt-out for action-required + short messages (<100 chars). `activateNextTTS` routes by stage. `onTTSPlaybackComplete` auto-pauses after preview by transitioning to `stage='remainder'` + flipping `_ttsPausedAfterPreview` flag. `resumeTTS` detects preview-pause and sends remainder as a NEW TTS request. `stopTTSAndAdvance` drops remainder + advances. `saveTTSQueueState`/`restoreTTSQueueState` snapshot the preview-paused item so the state survives page reloads. Cost-savings telemetry (`[TTS-COST]` console logs) per Rick's Q10 recommendation. Live-verified by Rick: 4-sentence ramble correctly previewed first sentence + auto-paused.

- **Bubble-controls fix** — after preview pause, the corner play/pause/stop buttons on the individual notification card initially disappeared. Root cause: `stopTTSPlayingIndicator` only removes the pulsing border; the per-bubble corner controls are CSS-gated by `is-playing-current`/`is-paused-current` classes set via `updateAudioControlStates`. Fixed by calling `updateAudioControlStates(currentNotificationId, 'paused')` in the preview-pause block so the corner ▶ button stays visible and routes to the existing `resumeTTS` handler which already has the preview-remainder branch.

- **INI plumbing** — 4 new keys in `lupin-app.ini` under `[Lupin: Baseline]` + 4 paired splainer entries: `tts preview enabled` (master switch), `tts preview fraction` (default 0.25), `tts preview min chars` (default 100), `tts preview include semicolons` (default false). `/api/config/client` endpoint (`system.py`) extended with 4 new response fields. JS consumes them from the existing config-fetch path with conservative fallbacks if fetch fails.

- **Plan-mode iterations** — Rick approved all 10 recommendations from the TTS preview design doc (client-side split, regex-with-lookahead splitter, exclude `;` by default, INI-driven fraction, opt-out for action-required + short, both modes, drop-on-stop, symmetric resume, persist preview state, console telemetry). Ratified via voice Q&A after pros/cons matrices were added per Rick's feedback. Iteration cadence was clean — Ultraplan handoff fired but timed out; Rick approved local plan directly.

- **Earlier in session**: Tiberius's handoff doc (`2026.05.13-handoff-to-arnold-notifications-ui-changes.md`) captured into the repo. Mid-session checkpoint commit `0c4e565` landed the broadcast-munger design doc, execution log, handoff intake, TODO line-757 entry, and speakerphone subdir index status flip. María's broadcast-panel commits between Tiberius's work and mine already absorbed my notifications.js wiring edits.

**Files modified** (parent Lupin only — per `feedback_lupin_only_never_cosa`):

- `src/fastapi_app/static/js/notifications.js` — TTS preview helpers + queue evolution + auto-pause + resume routing + stop drop + persistence + bubble-controls fix + broadcast wiring (~250 lines added across many edit batches)
- `src/conf/lupin-app.ini` — 4 new TTS preview keys
- `src/conf/lupin-app-splainer.ini` — 4 paired splainer entries
- `src/rnd/v0.1.7/2026.05.13-broadcast-munger-mode-design.md` (NEW, committed in `0c4e565`)
- `src/rnd/v0.1.7/2026.05.13-broadcast-munger-mode-execution-log.md` (NEW, committed in `0c4e565`)
- `src/rnd/v0.1.7/2026.05.13-handoff-to-arnold-notifications-ui-changes.md` (intake, committed in `0c4e565`)
- `src/rnd/v0.1.7/2026.05.13-tts-preview-and-pause-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.13-tts-preview-and-pause-execution-log.md` (NEW)
- `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/00-index.md` — status flip (committed in `0c4e565`)
- `TODO.md` — line-757 prose bug entry, speakerphone status updates
- `history.md` — this entry

**CoSA side** (Rick handles in a CoSA-context session per `feedback_lupin_only_never_cosa`):
- `src/cosa/rest/multimodal_munger.py` — broadcast munger mode + 20 smoke cases
- `src/cosa/rest/routers/system.py` — `/api/config/client` extended with 4 TTS preview fields

**Out of scope** (per Rick's voice directive at session-end): no push, no backup, history archive deferred to next session (now at 91.4% CRITICAL).

### 2026.05.13 Morning - Session 66d534ab (Tiberius 🌑) | Notifications UI — persona-initial focus bar + TTS pause-on-record + barge-in queue gate

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Topic**: Two notifications-UI tweaks requested by Rick in voice/chorus mode: (1) focus-bar pill initials should show the persona's first letter, not the project's (four Lupin sessions were all showing "L"); (2) TTS queue must pause BEFORE the mic engages and resume ~750ms AFTER recording stops, so other personas can't barge in mid-record. Plan written + serialized + ratified, code landed, barge-in queue-gate bug surfaced + fixed during live testing.

**Accomplishments**:

- **Tweak 1 — focus-bar persona initial** (`notifications.js:8967-8972`). Changed `_addStripIcon` initial computation to prefer `persona?.display_name || persona?.name` over `projectName`. Single-line semantic shift; persona was already a function parameter so no new wiring needed. Pills now show T/R/M/etc. instead of four identical L's. Rick's verdict: "perfect."

- **Tweak 2 — pause-on-record + delayed resume** (`notifications.js:3406, 3414-3415, 3437-3449, 3486-3491, 3568-3571, 3608-3624`). Pause is synchronous BEFORE `new AudioRecorder(...)` in `startRecording` — pre-empts the `getUserMedia` permission/resolve window. Resume scheduled 750ms after `onRecordingStop` (or `cancelRecording` for ESC-cancel) via new `_scheduleTTSResume` helper. `TTS_RESUME_DELAY_MS=750` constant on `recordingManager` for trivial tunability. State-preserving: tracks `_ttsPausedByRecording` flag so a user-initiated manual pause is never auto-resumed. Chained recordings within the 750ms window clear the pending timeout to prevent audible flicker.

- **Barge-in queue-gate fix added during testing** (`notifications.js:3447-3454, 3613-3624`). Plan called barge-in a "known limitation"; live testing confirmed: at T-0 of a 15s countdown with mic already engaged, fresh TTS pushed straight through. Root cause: `pauseTTS()` early-returns when `!activeTTSItem` (line 13501), leaving `isTTSPaused` false — `activateNextTTS` (line 12950) then sees an open gate. Fix: (a) force `self.ui.isTTSPaused = true` after `pauseTTS()` to close the gate even when nothing was playing at pause-time; (b) after `resumeTTS()`, kick `activateNextTTS()` if `activeTTSItem` is null but `ttsQueue.length > 0`, draining backlogged messages that piled up during recording. Rick verified the fix live: "I'm preventing auto TTS for incoming notifications while I'm recording — wonderful, you've fixed barge-in for me."

- **R&D doc serialized** to `src/rnd/v0.1.7/2026.05.13-notifications-ui-persona-initial-and-tts-pause.md`. Mirrors the approved plan; "Known limitation" section replaced with "Barge-in fix" section reflecting the live-verified queue-gate edits.

- **Verification**: Node `--check` syntax pass on `notifications.js` after every edit batch. Skipped Python unit + WS smoke per change-impact-analysis carve-out — neither suite covers plain `notifications.js`; would only catch import-chain breakage that the Node parse-check already covers. UI-observable behavior verified end-to-end by Rick in chorus mode with multiple Lupin sessions active.

**Files modified**:
- `src/fastapi_app/static/js/notifications.js` (single file, 7 edits: 1 persona-initial + 6 pause/resume/gate-related)
- `src/rnd/v0.1.7/2026.05.13-notifications-ui-persona-initial-and-tts-pause.md` (NEW)
- `history.md` (this entry)
- `.claude-session.md` (session manifest section)

**Out of scope** (per memory rules): no Python touched, no INI, no CoSA, no new test files. Plain-JS frontend tweak does not engage the 100% c8 coverage mandate (that applies only to `src/fastapi_app/static/js/multiplexer/` TS).

### 2026.05.12 Late Evening - Session 6a054460 (Tiberius 🌑) | Inter-Session Commons Phase 3 — Pass 1 + Pydantic retrofit + Pass 2 closed + Steps 1-2 implementation

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Topic**: Inter-Session Commons Phase 3 (push-mode `ask_async` + LLM-fallback persona disambiguation). Picked up post-/clear from the F2-fit resume doc; drove Pass 1 to closure (F2-F13), absorbed Rick's Pydantic-native validation retrofit catch, walked Pass 2 Adversarial end-to-end (T1-T8), captured the Testing Ownership Mandate explicitly in §6, and landed Steps 1-2 of the implementation. Paused at Step 3 boundary for tomorrow's barrel-through.

**Accomplishments**:

- **Pass 1 Fitness CLOSED — 13/13 findings ratified** (one-at-a-time per sequential rule). F2-fit INI key + env-var override; F3-fit per-topic cursor on `_InFlightQuestion`; F4-fit user-scoping (Phase 2 T7 mirror, 404-on-mismatch); F5-fit XML envelope (match + confidence + INI floor); F6-fit `0 < ttl ≤ 604800`; F7-fit topic regex `^[A-Za-z0-9_-]+$`; F8-fit atomic-or-409; F9-fit stamped persona from answer entry (Phase 1 immutability); F10-fit `ask_sync` stays polling-only; F11-fit TestClient smoke + **Rick's AC15 amendment** (end-of-cycle Playwright/integration bookend); F12-fit explicit 4-module import-chain list; F13-fit template-method pattern (protected `_register`/`_unregister` on base; domain-named public methods on subclasses).

- **Pydantic-native validation retrofit** — Rick caught that F6-fit/F7-fit/T2 were framed as hand-rolled `if/raise HTTPException` chains while the rest of `cosa/rest/routers/` uses Pydantic-native. Retrofitted AC1 (`RegisterQuestionRequest(BaseModel)` with `Field(min_length, max_length, pattern, gt, le)`), AC2 (path param `Path(..., pattern=...)`), AC6 (`PersonaDisambiguationRequest` with `@field_validator(mode="before")` for T2 sanitization). New memory `feedback_pydantic_native_validation` saved as project-wide standard.

- **Pass 2 Adversarial CLOSED — 8/8 threats ratified.** T1 strict type+format validation + dispatch-once idempotency `_dispatched_set`; T2 Pydantic sanitization + output whitelist + range; T3 per-user cap (50) + global cap (1000) + reuse `commons_rate_limiter` (429 on cap-hit); T4 cursor = `time.time()` on re-register + Phase 1 polling fallback covers gap; T5 uniform 404 body for both not-found and user-mismatch (single internal path); T6 mirror Phase 2 lock pattern (lookup under lock, dispatch outside lock); T7 keep 0.7 floor + INI-toggleable decision audit log; T8 mirror Phase 2 try-except + log + continue around `inject_fn`.

- **Testing Ownership Mandate landed in §6** — explicit "user is never a tester" preamble with tier execution responsibility table; AI executes every tier; tabular pass/fail reporting; 422 for Pydantic-validated body, 400 for app-level invariants, 404 for not-found/user-mismatch, 409 for atomic-conflict, 429 for cap-hit. New ACs AC16-AC20 specifically targeting T1 idempotency, T3 caps, T4 cursor, T6 concurrency, T8 inject_fn failures. Final AC count: **20 (AC1-AC15 Pass 1 + AC16-AC20 Pass 2 tests)**; final INI key count: **10**.

- **Status flipped to APPROVED FOR CODE-WRITE** — all 4 plan-review passes closed; Rick authorized implementation start. 9-step sequence locked in §5.

- **Step 1 — Q1 refactor pre-flight CLOSED.** NEW `src/cosa/rest/commons_topic_watcher.py` (~150 LOC abstract base): owns lifecycle scaffolding (`start`/`stop`/`_run_loop`), `threading.Lock`, `_in_flight` dict, protected `_register(record_id, record)` (atomic insert-or-raise) / `_unregister(record_id)` (silent pop), `_prune_expired_locked(now)` (records must expose `expires_at_monotonic`), abstract `_initialize_last_seen_ts()` + `tick()`. REFACTOR `src/cosa/rest/commons_ack_watcher.py`: subclasses `CommonsTopicWatcher`; preserves Phase 2 public API (`register_broadcast`/`unregister_broadcast`/`is_in_flight`); re-raises base `ValueError` with domain-specific `"broadcast_id collision"` message for Phase 2 26-test compat. **py_compile ✅ + import-chain ✅ + 26/26 ack-watcher tests GREEN in 0.56s** (AC8 satisfied).

- **Step 2 — INI keys + splainer CLOSED.** 10 new keys land in `lupin-app.ini` under `[Lupin: Baseline]` + 10 paired splainer entries: `commons question tracker ttl seconds` (Q4), `llm spec key for commons persona disambiguator` (C2 + Q5), `commons llm disambiguator fallback model name` (Q5 stub), `commons llm disambiguator timeout seconds` (Q7), `commons ask async push mode enabled` (F1-fit), `commons api base url` (F2-fit), `commons llm disambiguator confidence floor` (F5-fit), `commons question tracker per user max` (T3), `commons question tracker global max` (T3), `commons llm disambiguator log decisions` (T7). **Smoke test 10/10 resolve** via `ConfigurationManager.get()` with correct types.

- **TTS brevity-mandate strengthening** captured. Rick caught two violations where notify `message` was inventorying details (recap pattern) instead of speaking headlines + verdict. Memory `feedback_recraft_speech_dont_pipe_terminal` updated with the "headlines only, ~30-50 words, no recap" mandate.

- **Resume pointer pinned for next session** — TODO.md FIRST THING NEXT SESSION block points at Steps 3-9 barrel-through with file-location cheatsheet, AC checklist, and standing-memory recap. Next session opens directly at Step 3 (`CommonsQuestionWatcher` + AC16-AC20 unit tests).

**Files modified** (parent Lupin only — per `feedback_lupin_only_never_cosa`):

- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md` — Pass 1 + Pydantic retrofit + Pass 2 applied; 20 ACs in §6; NEW Testing Ownership Mandate preamble; NEW §8 PHI-4 prompt envelope with Pydantic models; NEW §3 Pass 2 ratifications table
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` — Phase 3 row + phase table updated to Pass 2 CLOSED + resume doc marked superseded
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/91-resume-here-phase3-pass1-f2-fit.md` — superseded banner at top (kept for audit trail)
- `src/cosa/rest/commons_topic_watcher.py` (NEW) — abstract base class
- `src/cosa/rest/commons_ack_watcher.py` — refactored to subclass; domain-specific error message preserved
- `src/conf/lupin-app.ini` — 10 new Phase 3 keys
- `src/conf/lupin-app-splainer.ini` — 10 paired splainer entries
- `TODO.md` — FIRST THING NEXT SESSION block re-pointed to Steps 3-9 barrel-through with full resume context
- `/home/rruiz/.claude/projects/.../memory/feedback_pydantic_native_validation.md` (NEW memory)
- `/home/rruiz/.claude/projects/.../memory/feedback_recraft_speech_dont_pipe_terminal.md` — strengthened headlines-only mandate
- `/home/rruiz/.claude/projects/.../memory/MEMORY.md` — index updated
- `history.md` (this entry)

#### Checkpoint | 2026.05.12 Late Evening | Phase 3 — Pass 1 + Retrofit + Pass 2 closed + Steps 1-2 landed

**Files**: 12 (1 NEW base class + 1 NEW memory + 10 MOD across design doc, index, resume-doc, ack-watcher, INI, splainer, TODO, 2 memory files, manifest, history)

**Commit**: [pending]

---

### 2026.05.12 Evening - Session 83ba1e51 (Rio ⚡) | Speakerphone refactor — Phases 5b / 6 / 7 landed on disk

**Persona**: Rio ⚡ (Young & energetic female, #880E4F)

**Topic**: Resumed the speakerphone solo/chorus refactor from the prior session's stop-point (Phase 5 function renames committed at `e17d7d7`). Crushed through Phases 5b (4-variant rider matrix + brevity migration), 6 (global CLAUDE.md slim + skill retire), and 7 (multiplexer rename + legacy notifications.js wire-fix). Phase 8 (chorus UX color/glyph polish) stays deferred per the canonical plan.

**Accomplishments**:

- **Phase 5b — 4-variant rider matrix + CLAUDE.md brevity migration** (`hook_common.py` rewrite): Replaced 1-variant `_system_reminder_body(source)` with `_speakerphone_reminder_body(source, mode, speakerphone_on)`. New private helpers `_source_preamble`, `_brevity_rules`, `_routing_reminder`. **Behavior change**: rider now fires on EVERY inbound user turn (voice / terminal-typed / idle re-prompt / permission-request) when `session_id` resolves — was previously gated on `speakerphone_on=True`. Content varies by `(mode, speakerphone_on)` 4-variant matrix. Sentinel renamed `_CONV_MODE_WRAP_SENTINEL` → `_SPEAKERPHONE_WRAP_SENTINEL` (matches both ON and OFF bodies). `speakerphone_exit_reminder(mode)` now 2-variant: solo body covers displaced-or-toggled-off; chorus omits displacement framing. Caller (`cc_notification_listener._inject_exit_conversation_reminder`) reads mode via `cu.get_tts_interaction_mode()`. **Bonus bug fix**: `session_bridge.set_speakerphone` had a Phase 2 sed-rename regression — popping the v2 key (`speakerphone_on`) instead of the legacy v1 key (`conversation_mode_active`); silently masked 7 pre-existing test failures across `test_session_bridge_speakerphone.py` + `test_session_bridge_lookup.py::TestConversationMode`. Fixed (one-line pop-target change).

- **Phase 6 — Global CLAUDE.md slim + skill retire + slash-command rename**: `~/.claude/CLAUDE.md` shrank 928 → 889 lines. Three sections removed (INTERACTIVE TOOL ROUTING, CRITICAL: USER IS NOT WATCHING TERMINAL, CONVERSATION MODE & TTS RESPONSE BREVITY MANDATE) — content now lives in the per-turn server rider after Phase 5b. One pointer section added (`### SPEAKERPHONE & TTS BEHAVIOR — SERVER-RIDER-DRIVEN`) directing readers to honor the rider as authoritative. Skill `~/.claude/skills/conversation-mode-guardrails/` retired with backup at `~/.claude/.phase6-backups/`. Project-local `.claude/commands/conversation-mode-{on,off}.md` → `speakerphone-{on,off}.md` (content also updated to call `enable_speakerphone()` / `disable_speakerphone()`). Doc touchpoints fixed: `src/docs/notification-types.md` (5 edits: state-update table, action verb example, router file reference, section heading, body) + `src/docs/rest-api-reference.md` (1 edit: response field `conversation_mode_active` → `speakerphone_on`).

- **Phase 7 — Multiplexer rename + legacy notifications.js wire-fix** (100% c8 maintained): 3 multiplexer source files renamed: `types.ts` (`LupinEventType` literal `conversation_mode_change` → `speakerphone_change`), `broadcast.ts` (`BROADCAST_WHITELIST`), `SenderStore.ts` (`STATE_UPDATE_TYPES` set entry `conversation_mode_changed` → `speakerphone_changed`). 2 test files updated. c8 100/100/100/100 across all dimensions on touched files. **Audit discovery**: design doc anticipated `multiplexer/render/*` touches for a `SpeakerphoneToggle` component — code reality is the multiplexer doesn't render the toggle (lives in legacy `notifications.js:9590-9736`). Phase 7 scope-down captured in `97-phase7-execution-log.md §7`; recommended follow-up as "Phase 7b — toggle widget migration". **Pre-existing bug surfaced + fixed**: legacy `notifications.js` had been silently broken since Phase 3 — dispatch case still matched `conversation_mode_changed` (server-emitted name renamed in Phase 3) and payload field-read still expected `active` (server now emits `on`). Single-edit fix to lines 5356 + 5365 + 2 comment touchups.

- **Test posture across all 3 phases**: Python unit regression 4267 passed, 1 xfailed, 0 failures. Multiplexer 329/329 + c8 `--100` clean on touched files.

- **Per-phase execution logs** (BFE-pattern tracking per `feedback_plans_include_tracking_docs`): `95-phase5b-execution-log.md`, `96-phase6-execution-log.md`, `97-phase7-execution-log.md`.

**Files modified**: 17 parent-Lupin files (5b: hook_common, cc_notification_listener, session_bridge + 6 test files; 6: ~/.claude/CLAUDE.md ⚠️not git-tracked, 2 project-local slash commands, 2 docs; 7: 3 multiplexer TS + 2 test files + legacy notifications.js). CoSA-side: 3 comment-only edits (commons_rate_limiter.py, voice_persona.py, speakerphone.py) — Rick handles git separately per `feedback_lupin_only_never_cosa`.

**Status**: ✅ Phases 5b / 6 / 7 complete on disk, all tests green, awaiting Rick's commit auth. Phase 7b (multiplexer toggle migration) + Phase 8 (chorus UX polish) tracked in TODO.md for next session.

---

### 2026.05.12 Evening - Session 56ee76d6 (Rachel 🕊️) | Multiplexer Phase 6b CLOSED + Phase 6c design phase opened (Cluster A 5/5)

**Persona**: Rachel 🕊️ (Calm & clear female, #7B1FA2)

**Topic**: Closed Phase 6b of the multiplexer notifications-UI rebuild end-to-end (Phases 5A → 8 + closure post-mortem). Opened Phase 6c design phase (persona modal / focus tray / audio recorder / conversation-mode UI pin) and walked Cluster A through 5/5 Q-decision ratifications.

**Accomplishments**:

- **Phase 6b Phase 5A — `JobStore.delete(idHash)`** (commit `118ed10`): NEW public `delete(idHash): { restoreState: () => void }` captures bucket + index + job, splices out, deletes from `indexById`, emits `removed`; `restoreState` re-inserts at original index, restores `indexById`, emits `added`. Nonexistent idHash → no-op closure + zero events. 11 new tests covering all 8 DOD rows; c8 100% on `JobStore.ts`.

- **Phase 6b Phase 5B — Delete-button click handler on `JobsPaneRenderer`** (commit `118ed10`): NEW `JobsPaneApiClient extends JobHistoryApiClient` adds `delete<T>`. Click delegation dispatches `.job-delete-button` BEFORE card-header toggle path (preserves Pass 2 F23 invariant). `handleDeleteClick()` w/ optimistic-removal + `Set<string> deleteInFlight` idempotency + `DELETE /api/queue/${UI_STATUS_TO_SERVER_QUEUE[status]}/${idHash}` (running→run legacy map). 2xx + 404 → discard restoreState; 5xx + non-ApiError Error → restoreState + inline error stripe. `stripInertnessMarkers()` post-renderAll removes `aria-disabled`/`tabindex`/`title`. 9 new AC5c tests; c8 100%.

- **Phase 6b Phase 6 — CSS port + page shell + boot wiring** (commit `e324e6c`): NEW `action-required.css` (295 LOC ≤500) + `tts-chrome.css` (187 LOC ≤700); stylelint clean. `.stylelintrc.json` extended with 2 F28 layer-2 overrides. `multiplexer.html` gains both `<link>` entries. `BootCompletePayload.handlers` extended with optional `actionRequiredRenderer`/`ttsChromeRenderer`. `boot.ts` A7/A8 ordering: notifications → jobs → actionRequired → ttsChrome → transports LAST; 4 stable `:mounted` console lines. `boot.js` gz = **34,647 B** = B6a + 3,163 (AC7 ceiling 39,676 → 5,029 B headroom).

- **Phase 6b Phase 7 — `:7999` smoke + AC10 cross-phase sweep** (commit `e324e6c`): NEW `test_multiplexer_phase6b_smoke.py` — 6 Playwright sub-tests, 6/6 PASS in 6.76s. AC10e cascade in Phase 5 + 6a smoke: `pending_count` floor cascaded ≥3 → ==1 → **==0**; Phase 5 boot-handshake substring filter tightened. Full sweep: tsc + eslint + stylelint clean; 602/602 unit; 14/14 smoke; c8 --100 across all 9 Phase 6b TS files.

- **Phase 6b Phase 8 — `:8000` scheduled E2E AC11a + AC11b** (commit `e324e6c`): NEW `test_multiplexer_phase6b_visual.py`. AC11a baseline `ts-5b88515c` wrote 2 PNGs. AC11b regression `ts-83e38e5f` returned **2 passed, 0 errors in 9.9s — AC11 GREEN**. TFE auto-fix tripped on AC11a library-convention errors and stalled at voice gate (proposing baselines for parallel session's `test_doc_viewer_directory.py` — left for doc-viewer team).

- **Phase 6b closure post-mortem** (commit `e324e6c`): NEW `97-phase6b-closure.md` (197 lines) — field-summary header, per-phase what-landed, 24-row AC verification matrix, 8 deviation entries, 5 deferred items, idempotency marker. `07-phase6-slicing-manifest.md` gains live slice-status table.

- **Phase 6c design phase opened** — NEW `10-phase6c-persona-focus-recorder-design.md` draft (4 clusters × 20 Q-decisions). Pre-design recon completed (persona shape, legacy class names with line numbers, `--persona-color-rgb` CSS-var pre-wired).

- **Cluster A ratified (5/5)**: Q-A1 trigger = `.sender-persona-badge` chip; Q-A2 modal = HTML Popover API w/ `popover="auto"` + declarative `popovertarget`; Q-A3 close = ESC + outside-click + × button; Q-A4 color = subtle thin top accent + tinted name; Q-A5 borrowed = `(borrowed)` label only (attribution deferred — no `original_owner` server field; follow-on filed).

**Files modified**: 23 files (10 NEW + 13 MOD) under `src/fastapi_app/static/js/multiplexer/`, `src/fastapi_app/static/css/multiplexer/`, `src/tests/{unit,smoke,e2e_ui}/multiplexer/`, `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/`, plus `.stylelintrc.json`, `multiplexer.html`, `dev-tools.html`, `TODO.md`.

**Auto-memory captured**:

- NEW `feedback_baseline_capture_disable_tfe.md` — always include `auto_fix_on_failure: False` on `--update-snapshots` test-suite submits.
- NEW `feedback_tts_body_headline_and_takeaway_only.md` — spoken `notify(message=)` / `ask_multiple_choice(question=)` body is headline + one-sentence recommendation only; pros/cons/inventory go in `abstract`.
- MOD `~/.claude/skills/schedule-tests/SKILL.md` — NEW "Mode: list-pending" section documenting the auth + `/api/get-queue/todo` queue-coordination snippet.

**Commits this session**: `118ed10` (Phases 5A+5B), `e324e6c` (Phases 6+7+8+closure).

**Status**: ✅ Phase 6b end-to-end CLOSED. Phase 6c Cluster A ratified; Clusters B/C/D + REUSE + Pass 1/2 + code-execution plan + implementation are the remaining cycle.

---

### 2026.05.12 Evening - Session 02e5cd9d (Arnold 🪨) | Multi-Repo Doc Viewer — N-scope INI registry + JWT gate + secrets blocklist + source-code rendering

**Persona**: Arnold 🪨 (Gravelly male, #FFD600)

**Topic**: Extended the doc viewer to browse files across N externally-mounted repos (lupin / planning-is-prompting / lupin-mobile / lookml / par-pacific / claude-plans + the optional cosa-voice) via a new INI-driven scope registry. Universal JWT gate on `/api/docs/file` and `/api/io/file` (was previously anonymous), pattern-based secrets blocklist applied to all scopes, MEDIA_TYPES expanded to source-code extensions rendered as plain `<pre>`.

**Design doc**: [`src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md`](src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md) — approved Q&A walkthrough resolving 4+1 framing questions (scope registry shape, MEDIA_TYPES breadth, universal JWT gate, Docker mount layout).

**Accomplishments**:

- **CoSA backend (Rick commits separately)** — NEW `src/cosa/rest/routers/_scope_registry.py` (`ScopeConfig` frozen dataclass + `build_scope_registry()` + `_is_secrets_path()` + `_is_whitelisted_in_scope()` + `resolve_in_scope()`). `docs_files.py` extended with `?scope=` query, `Depends(get_current_user)`, lazy `_get_scope_registry()`, expanded MEDIA_TYPES, secrets-blocklist call. `io_files.py` got the JWT dep + secrets-blocklist call. `_dir_listing.py` now imports `_is_secrets_path` and filters blocklist-matching entries at scandir time.

- **Parent Lupin** — `src/conf/lupin-app.ini` + paired splainer: `external repos` block under `[Lupin: Baseline]` registering 7 scopes (6 reachable, cosa-voice gracefully skipped because its host path doesn't exist on this machine — registry build logs warning, doesn't abort boot). `docker-compose.yml`: two new `:ro` bind-mount lines on BOTH `lupin-rest-dev` and `lupin-rest-test` (`/projects:/var/external-projects:ro` + `~/.claude/plans:/var/external-claude/plans:ro`). `document-viewer.html`: `Authorization: Bearer <lupin_access_token>` header on every fetch, 401 → `/app/login?next=<original>` redirect, content-type dispatch extended (text/markdown* → existing markdown render; text/* → new `renderPlainText` to `<pre class="doc-code-content">` via `textContent` not innerHTML), expanded icon table for source-code extensions.

- **Containers recreated** — both `lupin-rest-dev` and `lupin-rest-test` got `docker compose up -d --force-recreate` so the new mount lines took effect (`docker restart` doesn't pick up new mounts). `:8000` preflight 6/7 green (gh auth skip is environment-dependent).

- **Tests written + run** — NEW `src/tests/unit/test_scope_registry.py` (27 tests covering frozen dataclass, secrets blocklist with word-boundary discipline, whitelist semantics, traversal block, registry build edge cases — empty list, missing path, reserved-name collision, whitespace stripping, partial registration). NEW `src/tests/smoke/test_external_scopes.py` (14 :7999 tests covering auth gate, legacy scope=docs preservation, unknown scope, traversal block, secrets blocklist, per-scope routing, source-code serving). NEW `src/tests/e2e_ui/test_doc_viewer_multi_repo.py` (8 Playwright tests covering external-scope listing, file rendering, Python source as `<pre>`, no-auth login redirect). Existing `test_doc_viewer_directory.py` migrated from `page` → `logged_in_page` because the endpoint is no longer public.

- **Self-caught smoke failure (good)** — first `_scope_registry.quick_smoke_test()` run flagged that the naive `secrets?` / `credentials?` substring patterns mis-blocked `secretive_methods.py` and `credentialism.txt`. Fixed in-loop by anchoring the patterns to word boundaries (`\bsecrets?\b` / `\bcredentials?\b`).

- **Operational hiccup → recovery** — first E2E submission used `pytest_args="-k 'doc_viewer_multi_repo and not Visual' -v"` which the runner's naive `pytest_args_raw.split()` mangled (single-quoted boolean expression turned into separate positional args → `ERROR: file or directory not found: and`). Resubmitted with `--deselect src/tests/e2e_ui/test_doc_viewer_multi_repo.py::TestExternalScopeVisual` instead — every token whitespace-safe, no shell-quote nesting. Worth noting in memory but the existing `feedback_test_suite_submit_field_pytest_args.md` already covers the silent-drop family; this is a quoting-not-fielding variant.

**Verification pyramid** (all I/me-owned, not Rick — per CLAUDE.md TEST OWNERSHIP MANDATE):

| Tier             | Venue | Suite                                                         | Result      |
|------------------|-------|---------------------------------------------------------------|-------------|
| Unit             | :7999 | `pytest src/tests/unit/test_scope_registry.py`                | 27/27 pass  |
| Module smoke     | :7999 | `_scope_registry.quick_smoke_test()` inline                   | 4/4 pass (caught + fixed regex false-positives in same loop) |
| HTTP smoke       | :7999 | `pytest src/tests/smoke/test_external_scopes.py`              | 14/14 pass  |
| Manual URL sweep | :7999 | 10 probes (design §6 + cross-scope traversal + secrets)       | 10/10 pass  |
| Preflight        | :8000 | `pytest src/tests/smoke/test_container_preflight.py`          | 6/6 pass + 1 informational skip |
| E2E functional   | :8000 | `pytest -k doc_viewer_multi_repo --deselect ...::TestExternalScopeVisual` | **6/0/0/0 all_passed=True** (20.6s) |

**Visual baseline capture**: deferred to a follow-on `--update-snapshots` run (`auto_fix_on_failure: False`) per `feedback_baseline_capture_disable_tfe`. Visual class `TestExternalScopeVisual` was deselected from this run because no PNG baseline exists in `__snapshots__/` yet. Existing `test_doc_viewer_directory.py` visual tests (now using `logged_in_page`) likewise have no PNG baselines committed — this whole tree has been working with on-first-run capture.

**Files modified** (parent Lupin — this checkpoint, included in the §9 step 13 commit):

- NEW: `src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md` (design doc, serialized before impl per Phase 0 mandate)
- NEW: `src/tests/unit/test_scope_registry.py`
- NEW: `src/tests/smoke/test_external_scopes.py`
- NEW: `src/tests/e2e_ui/test_doc_viewer_multi_repo.py`
- MOD: `src/conf/lupin-app.ini` (external-repo block under `[Lupin: Baseline]`)
- MOD: `src/conf/lupin-app-splainer.ini` (paired splainer entries)
- MOD: `src/fastapi_app/static/html/document-viewer.html` (auth header + 401 redirect + content-type dispatch + `renderPlainText` + CSS)
- MOD: `docker-compose.yml` (two `:ro` mount lines × two services)
- MOD: `src/tests/e2e_ui/test_doc_viewer_directory.py` (page → logged_in_page migration)
- MOD: `CLAUDE.md` (DOCUMENTATION TOUCHPOINTS row pointing to the design doc)
- MOD: `history.md` (this entry)

**Files modified in CoSA submodule** (Rick commits separately per `feedback_cosa_edit_vs_manage_git`):

- NEW: `src/cosa/rest/routers/_scope_registry.py` (~310 lines including inline smoke test)
- MOD: `src/cosa/rest/routers/docs_files.py` (`?scope=` + JWT dep + expanded MEDIA_TYPES + secrets blocklist + lazy registry build)
- MOD: `src/cosa/rest/routers/io_files.py` (JWT dep + secrets blocklist)
- MOD: `src/cosa/rest/routers/_dir_listing.py` (secrets-blocklist entry filter + extended view_url routing docstring)

**Auto-memory updated**:

- NEW: `feedback_multi_repo_doc_viewer.md` (4-step scope-addition checklist)
- MOD: `MEMORY.md` (index entry)

**Status**: ✅ Implementation complete, all six test tiers green. Parent Lupin commit + history/memory updates landed in this checkpoint; CoSA submodule edits staged for Rick's separate commit.

---

### 2026.05.12 PM - Session 02e5cd9d (Arnold 🪨) | Doc Viewer Directory Listing Extension — backend polymorphic dispatch + scope=docs/io parity + inline image rendering

**Persona**: Arnold 🪨 (Gravelly male, #FFD600)

**Topic**: Extended `/app/docs?path=...&scope=...` document viewer to render a clickable directory listing when `path` resolves to a whitelisted directory. Single polymorphic endpoint per scope (`/api/docs/file` and `/api/io/file`) — files return text/markdown as today, directories return JSON `{kind, scope, path, parent, entries[]}`. Per-extension `view_url` routing built server-side so frontend stays dumb. As a follow-on, added PNG (+jpg/jpeg/gif/webp) support to the io endpoint and switched inline-renderable types (pdf, images, mp3/wav) from `Content-Disposition: attachment` to `inline` so they render in the browser instead of downloading — incidentally fixed a latent PDF download bug.

**Accomplishments**:

- **Design doc serialized** — `src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md` with full context, recon, design, file map, risk register, and implementation log. Five open questions resolved via cosa-voice MCP step-through with Rick (scope=both, bare prefix root allowed, name+size only, dirs-first alphabetical, hidden always excluded).

- **Backend** — NEW `src/cosa/rest/routers/_dir_listing.py` (~130 lines) is the single source of truth for `list_directory()` + `_build_view_url()` (per-extension routing table: directories + .md/.txt/.json/.yaml/.yml → `/app/docs`, .mp3/.wav → `/app/audio`, .pdf → `/api/io/file` inline, .pptx → `&download=true`, images → `/api/io/file` inline). `docs_files.py` got the bare-prefix-root whitelist tweak (`src/rnd` AND `src/rnd/` both list) + `isdir` branch. `io_files.py` got parallel `isdir` branch + `INLINE_TYPES` set + `content_disposition_type` argument to `FileResponse` + image MEDIA_TYPES additions.

- **Frontend** — `document-viewer.html` extended with Content-Type dispatch (text → existing markdown path; application/json → new `renderDirectoryListing`), ~30 lines CSS for `.doc-dir-listing`/`.doc-dir-breadcrumb`/`.doc-dir-entry`/`.doc-dir-meta`/`.doc-dir-icon`, breadcrumb up-navigation, icon-by-extension (📁 dir, 🔊 audio, 📑 pdf, 📊 pptx, 📄 default). Padding iterated 10px → 7.5px → 5.625px → 4.21875px → 3.1640625px (Rick four 25% reductions to taste). Caught a latent empty-path JS bug at the :8000 E2E gate — `params.get('path')` returns `null` when missing but `""` when present-and-empty; `if (!path)` was rejecting both equally, killing scope=io root browsing. Fix: `params.get('path') ?? ''` (nullish-coalescing) so empty string is valid; error only fires when key is genuinely absent AND scope is docs.

- **Tests** — Three new test files + one extended (LUPIN parent): `src/tests/unit/test_dir_listing.py` (30 unit tests covering routing table + list_directory semantics), `src/tests/smoke/test_io_files_endpoint.py` (13 smoke tests covering listing JSON shape + per-extension view_url + inline disposition + download override), `src/tests/e2e_ui/test_doc_viewer_directory.py` (8 Playwright tests covering scope=docs + scope=io rendering + breadcrumb + visual regression baselines); `test_docs_files_endpoint.py` extended with +9 directory tests.

- **Verification pyramid** — 77 tests green / 2 conditional skips / 0 failed. :7999 (unit + smoke + 8-URL browser sweep) all green in 0.16s. :8000 E2E (`-k doc_viewer_directory`) green after 3 runs: 1) baseline-creation with --update-snapshots found the empty-path bug, 2) baseline refresh after fix, 3) clean verify run without --update-snapshots → 8/0/0/0.

- **OpenAPI** — regenerated `src/docs/fastapi/api.json` + `api.md` via `src/scripts/generate-api-docs.sh`. New polymorphic-endpoint summary picked up automatically.

**Status**: Implemented and tested. Visual baselines parked under `io/test-suite/visual-baselines/test_doc_viewer_directory/` (gitignored, captured at 10px padding so now slightly stale post-compression — re-submit E2E with `--update-snapshots` to refresh if needed; not blocking).

**Files modified** (parent Lupin — this checkpoint):

- NEW: `src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md`
- NEW: `src/tests/unit/test_dir_listing.py`
- NEW: `src/tests/smoke/test_io_files_endpoint.py`
- NEW: `src/tests/e2e_ui/test_doc_viewer_directory.py`
- MODIFIED: `src/fastapi_app/static/html/document-viewer.html`
- MODIFIED: `src/tests/smoke/test_docs_files_endpoint.py`
- MODIFIED: `src/docs/fastapi/api.json` (OpenAPI regen)
- MODIFIED: `src/docs/fastapi/api.md` (OpenAPI regen)

**Files modified** (CoSA submodule — separate commit by Rick per `feedback_cosa_edit_vs_manage_git`):

- NEW: `src/cosa/rest/routers/_dir_listing.py`
- MODIFIED: `src/cosa/rest/routers/docs_files.py`
- MODIFIED: `src/cosa/rest/routers/io_files.py`

#### Checkpoint | 2026.05.12 PM EDT | Doc viewer dir listing — full impl + inline image rendering (Arnold 🪨)

**Files**: 4 NEW + 4 MOD in Lupin parent (CoSA edits pending Rick's separate commit)
**Commit**: `9e1869e`

---

**Postscript (same session, ~30 min after checkpoint 1)**: ran a throwaway empirical probe (`src/scripts/probe-cc-bounded-billing-2026.05.12.py`, gitignored, deleted post-use) to definitively confirm whether bounded `ClaudeCodeJobs` bill against the firewalled Anthropic key or are covered by Rick's Max 200 plan. 10 probe jobs (2 clusters × 5: in-repo Read/Grep/Write + web search/synthesis) reported **$2.0514** in SDK-side `cost_usd` telemetry; Anthropic console credit balance moved **$0.00** confirmed by Rick at probe completion + 10 min post. Theory empirically confirmed — bounded CC path uses Max-subscription OAuth, firewalled key is never touched.

**Policy spawned from this finding** (single follow-up commit, Checkpoint 2):

- NEW R&D doc `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md` — load-bearing forensic record + migration policy + off-peak scheduling rule (9 PM – 12 AM EDT peak / 12 AM – 9 AM EDT optimal batch window).
- NEW auto-memory `feedback_prefer_bounded_cc_over_anthropic_sdk.md` (indexed in MEMORY.md).
- NEW CLAUDE.md § "COST MODEL — BOUNDED CC vs FIREWALLED SDK" between CJ FLOW and CODE STYLE; new row in the DOCUMENTATION TOUCHPOINTS table.
- NEW `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md` (indexed in src/docs/README.md) — human-onboarding decision framework + 8-step migration playbook.
- TODO.md — three migration items added under new "💰 LUPIN Cost Migration" section: Deep Research, podcast script generation, presentation content generation. NOT migrating: notification_proxy LLM fallback (high-QPS) and decision_proxy (latency-sensitive).

**Why this matters**: Lupin already migrated BFE + TFE to bounded CC on this cost assumption; now empirically grounded. Three more agents queued for migration. Net effect when all three land: removes the largest per-token Anthropic spend lines, shifts that cost into the already-paid Max 200 monthly bill.

---

### 2026.05.12 PM - Session 83ba1e51 (Rio ⚡) | Speakerphone solo/chorus — full design doc set + Q4 audit resolved (Phase 1 unblocked)

**Persona**: Rio ⚡ (Young & energetic female, #880E4F)

**Topic**: Per-session speakerphone mode thought exercise — design serialization through to Phase 1 implementation readiness. Reframed the May 11 hard-cut framing (Mr. Radio session) around `tts interaction mode = solo | chorus` with parallel preservation (both modes first-class permanent per `feedback_feature_flag_preserves_old_path`); drafted complete per-phase design doc set; resolved Q4 mode-coupling audit.

**Accomplishments**:

- **Subdirectory + canonical plan rewrite** — Created `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`. May 11 doc moved into subdir via `git mv` + restored to original content + superseded-by banner. May 12 canonical plan rewritten with parallel-preservation framing as lead narrative (replacing the May 11 hard-cut framing). INI key naming: `solo | chorus` over `per-session | monopoly` (vivid TTS-native metaphor; extensible to `duet`/`trio`/`quartet`).

- **Complete design doc set drafted (13 NEW docs)** — `00-index.md` (orientation + reading order + status snapshot), `02-background-synthesis.md` (predecessor distillation of `2026.04.27-conversation-mode-design.md` + `2026.04.30-conv-mode-three-layer-enforcement/`), `03-open-questions.md` (8 deferred questions tracker), `90-decisions-log.md` (append-only ledger). Per-phase design docs `10-phase1-ini-plumbing-design.md` through `17-phase8-color-glyph-uxs-design.md` — uniform shape: Goal / Scope / Deliverables / Implementation order / Verification / Risks / Cross-cutting concerns (memory audit + naming + doc touchpoints) / Timing / Hand-off. Plus `20-test-parameterization-matrix.md` (~85 target tests across phases, mode-parameterization patterns for both pytest and Vitest).

- **Q4 mode-coupling audit resolved → Phase 1 unblocked** — NEW `04-mode-coupling-audit.md`. Grep audit confirmed 14 mode-independent couplings (rename-only, covered by Phase 2 / 5: stop-hook auto-narrate, idle-waiter, all three `conv_mode_wrap` callsites, `_notify_impl` on-branch, `get_session_info`, bridge helpers, TTS queue, `set_session_topic`, voice_persona field, `last_autonarrated_turn_id`), surfaced 1 new finding (MCP `instructions=` block at `cosa_voice_mcp.py:598-603` + `enable_speakerphone` tool docstring at line 1436 area have hard-coded mutual-exclusion language — folded into Phase 4 §3.6 as a single mode-aware paragraph covering both branches), confirmed 3 out-of-scope items (inbound mic-routing, persona pool sizing, MCP HTTP-fallback bypass), identified 1 false-positive grep hit (CJ Flow `monopolize` field is an unrelated job-scheduling concept). Phase 4 design doc (`13-phase4-mcp-tool-rename-design.md`) updated to fold this in.

- **Cold-pickup hygiene** — `project_speakerphone_thought_exercise.md` memory rewritten to point at the index doc (not the canonical plan directly); MEMORY.md inventory line updated to reflect implementation-readiness; TODO.md pickup pointer added at top (Tiberius's Inter-Session Commons Phase 3 pointer preserved as separate track below). Index doc status snapshot now reads "✅ Q4 audit resolved; ✅ all Phase 1–8 design docs drafted; ⏸️ awaiting Rick's explicit go-ahead."

**Status**: Implementation-ready. **No code written.** Awaiting Rick's explicit go-ahead to begin Phase 1 (`10-phase1-ini-plumbing-design.md`).

**Files modified** (parent Lupin only — per `feedback_lupin_only_never_cosa`):

- 13 NEW docs in `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`: `00-index.md`, `02-background-synthesis.md`, `03-open-questions.md`, `04-mode-coupling-audit.md`, `10` through `17` per-phase design docs, `20-test-parameterization-matrix.md`, `90-decisions-log.md`
- 1 MOVED file via `git mv`: `2026.05.11-per-session-speakerphone-mode.md` (from `src/rnd/v0.1.7/` into the new subdir; restored to original content + superseded-by banner)
- 1 NEW canonical plan: `2026.05.12-tts-interaction-mode-solo-chorus.md` (the conceptual `01` slot of the subdir; created today as the rewrite of the May 11 doc with parallel-preservation framing as lead)
- `TODO.md` (MODIFIED — speakerphone pickup pointer added at top)

#### Checkpoint | 2026.05.12 PM EDT | Speakerphone solo/chorus — full design doc set + Q4 audit (Rio ⚡)

**Files**: 15 NEW docs in subdir + 1 MOVED May 11 doc + 1 MOD TODO.md

---

### 2026.05.12 PM - Session 6a054460 (Tiberius 🌑) | Inter-Session Commons Phase 3 — Pass 0 + REUSE closed; Pass 1 Fitness in flight (paused at F2-fit)

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Topic**: Inter-Session Commons + User-Broadcast — Phase 3 plan-review (D1 polling→push for `ask_async` + LLM fallback for persona matcher). Session paused mid-Pass-1 ahead of context clear; resume doc landed.

**Accomplishments**:

- **Pass 0 CLOSED — 8/8 Q-decisions ratified.** Q1 hybrid base class (refactor `CommonsAckWatcher` → `CommonsTopicWatcher` base + `Ack`/`Question` subclasses); Q2 dynamic registration (only-outstanding); Q3 `COMMONS PEER REPLY` framing (peer-attributed with persona, honors INTRA-AI principle); Q4 1-hour default TTL with per-call override; **Q5 local PHI-4 first via `LlmClientFactory` + `BaseXMLModel` Pydantic XML pattern, Haiku 4.5 stubbed for future fallback** (Rick override of original Haiku/Sonnet/tiered framing); Q6 no cache (YAGNI); Q7 configurable 5s timeout via INI; Q8 in-memory tracker matching Phase 2.

- **NEW directive captured**: every multi-option `ask_multiple_choice` carries pros + cons + "My recommendation" block + "becomes correct if..." flip-condition in BOTH spoken text AND abstract. Saved as memory `feedback_always_include_pros_cons_recommendation`.

- **REUSE pass CLOSED + applied.** 8 F-mappings confirmed with file:line citations; 4 new F-findings (F9-F12) added (`BaseXMLModel.from_xml/to_xml` round-trip at `util_xml_pydantic.py:128,245`; `notification_proxy/strategies/llm_script_matcher.py` as structurally closest disambiguator template; proposed listener verb `"commons_answer_received"`; `main.py:527+` extends-in-place for Phase 2 commons block). 3 corrections applied: **C1** F4 pivot from stale `Llm` class to `LlmClientFactory` at `cosa/agents/llm_client_factory.py:17` (canonical call template `runtime_argument_expeditor/expeditor.py:82,167-168`); **C2** new INI key `llm spec key for commons persona disambiguator = Deepily/kaitchup/Phi-4-AutoRound-GPTQ-4bit` required; **C3** Q2 sub-question RESOLVED — HTTP register endpoint wins via REUSE grounds (`conversation_mode.py:116-` is directly-applicable template; shared-file would require new primitive). New endpoint `POST /api/commons/register-question` + `DELETE .../register-question/{question_id}` locked in. §4 file touchpoints bumped from 5 NEW + 4 MODIFIED to **9 NEW + 8 MODIFIED**.

- **Pass 1 Fitness — 13 ACs derived + 13 fitness findings surfaced**. 2 blockers (F1-fit missing push-mode toggle INI; F2-fit hardcoded localhost dependency), 3 high (F3-fit cursor strategy, F4-fit same-user scoping on register/unregister, F5-fit PHI-4 prompt envelope undesigned), 6 medium (F6-fit TTL bounds, F7-fit topic regex, F8-fit concurrent register collision, F9-fit persona attribution source, F10-fit sync-mode interaction, F11-fit E2E endpoint hit), 2 low (F12-fit import chain, F13-fit base-vs-subclass naming). Walk paused per Rick's standing directive of "one finding at a time, highest severity first" — F1-fit ratified as Option A (default True + try-except + warning log + best-effort isolation matching Phase 2 `failed_recipients` pattern); F2-fit picker fired but Rick called timeout mid-picker.

- **Pre-context-clear resume doc landed.** NEW `91-resume-here-phase3-pass1-f2-fit.md` (~440 LOC) — self-contained handoff with Pass 0 + REUSE summary, F1-fit ratification rationale, F2-fit picker framing verbatim (3 options with full pros/cons/recommendation ready to re-fire), 11 remaining findings tabulated by severity with one-line fixes, process reminders (conversation-mode rules, sequential-plan-review rule, no-auto-commit, Lupin-only-not-CoSA), file-location cheatsheet, and code-references cheatsheet. Fresh-context Claude reading this doc can resume exactly at F2-fit without re-deriving any prior decisions.

**Files modified** (parent Lupin only):

- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md` (Pass 0 ratifications applied to §2; REUSE applied to §3 + §4; status banner flipped to Pass 1 IN FLIGHT)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/91-resume-here-phase3-pass1-f2-fit.md` (NEW — pre-context-clear handoff)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` (added resume doc entry; Phase 3 row updated to "Pass 1 IN FLIGHT")
- `TODO.md` (FIRST THING NEXT SESSION block repointed to the resume doc with the Pass 1 sequence + standing directive recap)
- `/home/rruiz/.claude/projects/.../memory/feedback_always_include_pros_cons_recommendation.md` (NEW memory file)
- `/home/rruiz/.claude/projects/.../memory/MEMORY.md` (entry appended to feedback section)
- `history.md` (this entry)
- `.claude-session.md` (this session's section updated with second checkpoint metadata)

#### Checkpoint | 2026.05.12 PM | Phase 3 plan-review — Pass 0 + REUSE closed; Pass 1 paused at F2-fit; resume doc landed

**Files**: 8 (1 NEW resume doc + 1 NEW memory + 6 MOD across design doc, index, TODO, history, memory index, manifest)

**Commit**: [pending]

---

### 2026.05.12 - Session 6a054460 (Tiberius 🌑) | Inter-Session Commons Phase 2 — CLOSED (steps 9-13: E2E + UI + Playwright + docs + closure)

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Topic**: Inter-Session Commons + User-Broadcast — Phase 2 closure. Picked up where session 9a4a601d (Rachel) left off (steps 1-8 backend wired, uncommitted) and drove the remaining 5 steps to closure end-to-end with explicit `:8000` bounce authorization.

**Accomplishments**:

- **Step 9 — 2-session E2E smoke (`:7999`)** ✅ — NEW `src/tests/smoke/test_broadcast_two_session_e2e.py` (~280 LOC, 1 test, 0.76s). Architecture: `mp.get_context("spawn")` forks 2 mock-listener subprocesses (Maria 🌸 / Tiberius 🌑); parent calls `execute_broadcast()` directly with DI'd deps (stub `raw_sessions_fn`, `bridge_loader`, `build_sender_id`; routing `notification_queue.push_notification` to the right child queue by `job_id`); body = default line + `@Maria:` directive. Exercises all 7 design-doc gates: HTTP response shape, `broadcasts` topic content + System Broadcast persona stamp + hyphen-only pseudo-sid, listener-specific injection content (Maria sees directive, Tiberius does not), `broadcast-acks` correlated content, AckWatcher.tick() dispatch with cursor-advance verified via second-tick==0. Full commons regression: 215 passed in 14.76s.

- **Step 10 — UI broadcast panel** ✅ — NEW `src/fastapi_app/static/js/broadcast-panel.js` (~350 LOC IIFE) + NEW `src/fastapi_app/static/css/broadcast-panel.css` (~220 LOC). Recipient chip-row populated via `GET /api/commons/active-sessions`; textarea with live markdown preview via `DOMPurify.sanitize(marked.parse(body))` (AC10 + T2); Send button gated on body-non-empty + recipients-non-empty (AC8 + F17 whitespace-trim mirror); one-step confirm modal (Q10) with sanitized preview + Confirm/Cancel; POST with Bearer auth from `localStorage.lupin_access_token`; rate-limit-aware error path reads `Retry-After`; aggregate panel with named-pending list + 5-min auto-dismiss timer + timed-out passive banner (AC9 + F18); T10 defense-in-depth — `body_summary` rendered via `.textContent`, never `.innerHTML`; T2 defense-in-depth — bare-text fallback if `marked` or `DOMPurify` fails to load. MODIFIED `notifications.html` (+30 LOC: link + script + panel insertion between presentation + test-suite cards). MODIFIED `notifications.js` (+9 LOC: `case "commons_broadcast_ack"` delegating to `window.broadcastPanel.handleAck`). DOMPurify already vendored as `purify.min.js` — design-doc speculation about adding it was unneeded.

- **`:8000` test container bounced** (explicit user authorization) — `docker restart lupin-rest-test` after verifying `inflight=0/pending=0`; container healthy after 8 health-poll attempts (~24s); post-bounce verification confirmed `/api/commons/active-sessions` + `/api/commons/broadcast-to-cc-sessions` registered in OpenAPI + `broadcast-panel.js` (19,240 bytes) + `broadcast-panel.css` (5,612 bytes) served.

- **Step 11 — Playwright E2E (`:8000` scheduled)** ✅ — NEW `src/tests/e2e_ui/test_broadcast_panel.py` (~280 LOC, **10 tests** across 4 classes): `TestBroadcastPanelRendering` (AC8 — panel + Send-gating; 3 tests), `TestBroadcastPreview` (AC10 + T2 — markdown + DOMPurify XSS hardening including bold/script/onerror; 3 tests), `TestBroadcastAggregate` (AC9 + T10 — 0/2 → 1/2 → 2/2 progression + body_summary XSS-as-text; 2 tests), `TestBroadcastSendFlow` (AC8 — Send→modal→Confirm→POST mocked end-to-end with `page.route`; 2 tests). Submitted via `/api/test-suite/submit` (`test_types=e2e`, `pytest_args="-k test_broadcast_panel -v"`, `scheduled_at=2026-05-12T10:00:00-04:00`) → job_id `ts-436237f6`. **Result: 10 passed / 0 failed / 0 errors / 0 skipped in 40.97s.** Report at `io/test-suite/2026.05.12-at-10:00-EDT-e2e-results.md`.

- **Step 12 — Documentation** ✅ — NEW `src/docs/notification-types.md` (~135 LOC) — catalog of all 10 valid `type` values across user-facing / session-control / custom state-update categories, deep section on `commons_broadcast_ack` covering trigger conditions, payload shape, UI handler delegation, TTL semantics, T10 defense-in-depth, cross-references. MODIFIED `src/docs/rest-api-reference.md` — added §17c "Inter-Session Commons" between §17b (TFE) and §18 (Decision Proxy) covering both endpoints, broadcast directive parsing rules, ack flow walkthrough, 3-key INI configuration table. Note: design doc said "section 17" but §17 was already Test Suite — used 17c to stay adjacent to TFE/BFE (other agentic submission surfaces). MODIFIED `src/docs/README.md` — added notification-types.md to WebSocket/notifications cluster.

- **Step 13 — Phase 2 closure** ✅ — NEW `src/rnd/v0.1.7/2026.05.09-inter-session-commons/92-phase2-closure.md` (~180 LOC) — post-mortem covering what landed (backend modules + REST endpoints + listener wiring + ack-watcher daemon + custom notif type + UI + INI keys + test coverage), Step 11 Playwright result table, AC verification matrix, deviations (D1 section numbering / D2 DOMPurify already vendored / D3 step 9 architecture using direct `execute_broadcast` call), deferred items (Phase 3 polling→push + LLM fallback), cross-project follow-ups, file touch summary. MODIFIED `00-index.md` — last-reviewed-at updated, Phase 2 marked CLOSED with 92-phase2-closure link added. MODIFIED `TODO.md` — top-of-file "FIRST THING NEXT SESSION" replaced with closure summary; step checklist all marked complete.

- **Aggregate test posture**: 100% coverage gate held across all 8 commons modules (622 stmts / 170 branches / 0 missing). `:7999` regression: 215 passed in 14.76s (211 unit + 3 Phase 1 smoke + 1 step 9 smoke). `:8000` scheduled: 10 passed in 40.97s.

**Files modified** (parent Lupin only — per `feedback_lupin_only_never_cosa`):

- `src/tests/smoke/test_broadcast_two_session_e2e.py` (NEW)
- `src/fastapi_app/static/css/broadcast-panel.css` (NEW)
- `src/fastapi_app/static/js/broadcast-panel.js` (NEW)
- `src/fastapi_app/static/html/notifications.html` (MODIFIED — +30 LOC panel + link + script)
- `src/fastapi_app/static/js/notifications.js` (MODIFIED — +9 LOC commons_broadcast_ack case)
- `src/tests/e2e_ui/test_broadcast_panel.py` (NEW)
- `src/docs/notification-types.md` (NEW)
- `src/docs/rest-api-reference.md` (MODIFIED — §17c added)
- `src/docs/README.md` (MODIFIED — notification-types.md entry)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/92-phase2-closure.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` (MODIFIED — Phase 2 CLOSED)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-phase2-execution-log.md` (MODIFIED — steps 9/10/11/12/13 closure rows)
- `TODO.md` (MODIFIED — top-of-file Phase 2 closure summary; old resume-pointer retained as historical context)

#### Checkpoint | 2026.05.12 10:30 EDT | Phase 2 closure (steps 9-13 + closure doc)

**Files**: 13 (3 NEW UI + 1 NEW smoke + 1 NEW Playwright + 1 NEW docs + 1 NEW closure + 2 MOD docs + 2 MOD R&D + 1 MOD TODO + 2 MOD frontend wiring)

**Commit**: f9f11f0 (post-amend with manifest checkpoint metadata; pre-amend was 3c66ffc)

---

