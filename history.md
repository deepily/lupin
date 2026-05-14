# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-03 to 05-06](history/2026-05-03-to-06-history.md). History health: 🚨 **CRITICAL at 22857 tokens (91.4% of 25k)** — archive must run next session before adding new content.

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

### 2026.05.11 → 2026.05.12 AM - Session 9a4a601d (Rachel 🕊️) | Inter-Session Commons: Phase 1 wrap + Phase 2 plan-review pipeline + Phase 2 backend (steps 1-8)

**Persona**: Rachel 🕊️ (calm & clear female, #7B1FA2)

**Accomplishments**:

- **Phase 1 (file-based commons MVP) — landed steps 4-8** (started by Tiberius 🌑 earlier in the day with steps 3a + 3b). Authored `commons_archival.py` (24h rotation daemon, 117 stmts, 26 branches, 100%) + `commons_ask.py` (hybrid-grace ask_sync + ask_async, 29 stmts, 8 branches, 100%) + 5 MCP tool registrations on the existing cosa-voice server (`commons_post`, `commons_read`, `commons_who`, `commons_ask_sync`, `commons_ask_async`) + `LUPIN_COMMONS_TEST_OVERRIDE` JSON env-var hatch for the AC12 config-toggle subprocess test + reusable `mcp_stdio_test_client.py` helper. Final Phase 1 milestone: **88 tests / 100% lines + branches across all 4 commons modules** (309 stmts, 80 branches, 0 missing); all 14 ACs + 4 deviations documented in `92-phase1-closure.md`.

- **Phase 2 design draft authored** — `03-phase2-user-broadcast-design.md` (568 LOC, 14 ACs, 16 sections, 15 open questions, 3 deviation flags) modeled on the Phase 1 design template. UI panel + 2 endpoints + listener action + live ack aggregation via the canonical `notification_queue_update` envelope, per the 2026-04-29 ws-event-cleanup mandate.

- **Phase 2 plan-review pipeline — REUSE + Pass 1 Fitness + Pass 2 Adversarial all CLOSED.** Plan APPROVED FOR CODE-WRITE.
  - **REUSE**: 10 prior-art mappings confirmed with file:line citations; surfaced 4 corrections C1-C4 (most critically F10 — the WS-event mechanism was wrong; should be a custom notification type, not a top-level event).
  - **Pass 1 Fitness**: 20 fitness findings applied across AC1-AC14 including 2 implementation-blocking bugs (F8 — server-pseudo-sid `broadcast@` would fail `_HEADER_RE` regex; F20 — stale filenames in AC12 coverage gate) and 1 HIGH-severity security gap (F5 — same-user scoping missing from fanout filter). 13/15 open questions closed; D2 + D3 deviations ratified.
  - **Pass 2 Adversarial**: 12 threats walked (T1-T12), 11 ACs hardened inline. Sanitization step ratified (endpoint reject `<system-reminder>` substrings + listener belt-and-suspenders re-check; preserves wrapper format per `feedback_sanitize_at_boundary_not_format_strip`). 2 NEW threats surfaced via code inspection: T8 bridge `Path` leak in `find_active_voice_persona_sessions` return-tuple + T9 broadcast_id collision TOCTOU race — both mitigated.

- **Phase 2 backend implementation — steps 1-8 all CLOSED** with 100% coverage on every new pure-logic module. The full user-broadcast surface is wired backend-side: rate limiter + listener-side orchestrator + ack watcher daemon + 2 FastAPI endpoints + listener `_handle_action` 3rd `elif` branch + 2 new INI keys + `commons_broadcast_ack` registered in `notifications.py` `valid_types` + `main.py` lifespan startup/shutdown wiring + `app.include_router(commons.router)` + AC14 router-registration smoke test.

- **Memory cleanup** — User flagged the `feedback_bug_fix_mode_for_multi_phase.md` rule as misapplied (bug-fix mode is for bug fixes, not new feature implementation). Deleted the memory file + removed the MEMORY.md index entry + scrubbed the citation from the Phase 2 design doc.

**Files modified** (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`):

Phase 1 (steps 4-8):
- `src/lupin_mcp/commons_archival.py` (NEW)
- `src/lupin_mcp/commons_ask.py` (NEW)
- `src/lupin_mcp/cosa_voice_mcp.py` (MODIFIED — 5 `@mcp.tool` shims + `LUPIN_COMMONS_TEST_OVERRIDE` hatch)
- `src/tests/helpers/mcp_stdio_test_client.py` (NEW)
- `src/tests/unit/commons/test_commons_archival.py` (NEW)
- `src/tests/unit/commons/test_commons_ask.py` (NEW)
- `src/tests/unit/commons/test_commons_mcp_subprocess.py` (NEW)
- `src/tests/unit/commons/test_commons_mcp_config_toggle_subprocess.py` (NEW)
- `src/tests/unit/commons/test_commons_store.py` (branch-coverage backfill)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/{90-execution-log.md,00-index.md,91-resume-here-phase1-step{4,5,6,7,8}.md,92-phase1-closure.md}` — Phase 1 tracking

Phase 2 (design + steps 1-8):
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md` (NEW + REUSE/Pass 1/Pass 2 walks)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-phase2-execution-log.md` (NEW)
- `src/lupin_mcp/commons_store.py` (MODIFIED — `broadcasts` added to `RESERVED_TOPICS`)
- `src/cosa/rest/commons_rate_limiter.py` (NEW)
- `src/lupin_mcp/broadcast_handler.py` (NEW)
- `src/cosa/rest/commons_ack_watcher.py` (NEW)
- `src/cosa/rest/routers/commons.py` (NEW — 2 endpoints + pure-logic helpers)
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (MODIFIED — 3rd `elif` + `_handle_broadcast_received` method)
- `src/cosa/rest/routers/notifications.py` (MODIFIED — `commons_broadcast_ack` in valid_types)
- `src/conf/lupin-app.ini` + `src/conf/lupin-app-splainer.ini` (2 new keys + paired explanations)
- `src/fastapi_app/main.py` (MODIFIED — 3 commons singletons + lifespan startup/shutdown + router include)
- `src/tests/unit/commons/{test_commons_rate_limiter,test_broadcast_handler,test_commons_ack_watcher,test_commons_router,test_commons_ac14_registration}.py` (NEW × 5)
- `TODO.md` (resume-pointer section at top)
- `MEMORY.md` (removed bug-fix-mode-for-multi-phase entry per user)

**Status**:

- ✅ Phase 1 milestone COMPLETE (commit pending in next session — uncommitted on disk).
- ✅ Phase 2 plan APPROVED FOR CODE-WRITE; design + REUSE + Pass 1 + Pass 2 all closed.
- ✅ Phase 2 steps 1-8 CLOSED; aggregate suite: **211 tests, 100% lines + branches across 8 commons modules (622 stmts, 170 branches, 0 missing)**.
- ⏳ Phase 2 steps 9-13 pending (2-session E2E smoke + UI + Playwright + docs + closure post-mortem). Resume pointer in TODO.md.
- ⏳ No commit this session per user direction (no-push handled by next-session commit).

**Commits**: This session-end commit (parent Lupin; CoSA untouched).

---

### 2026.05.11 EOD - Session 77e1bb27 (Mr. Radio) | Speakerphone-mode thought exercise — design serialized to R&D

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Voice-driven design exploration** — Think-out-loud session on a contemplated refactor of cosa-voice "conversation mode" from monopoly-enforced single-session toggle to per-session **speakerphone vs phone** render-mode toggle. Many sessions can be on speakerphone simultaneously; the cosa-voice TTS queue serializes playback at the user's ear; each persona's voice carries disambiguation. At-distance becomes the default interaction mode. The `<voice-message>` + `<system-reminder>` micro-prompt is preserved and load-bearing — the rider's content varies by per-session speakerphone state, the wrapping mechanism itself is unchanged. CLAUDE.md slims to always-on notification rules; speakerphone-conditional rules migrate into the MCP-server-built per-turn rider.

- **Plan serialized to R&D** — `src/rnd/v0.1.7/2026.05.11-per-session-speakerphone-mode.md` captures the full design exploration with a status banner marking it as 💭 **NOT approved for implementation** — thought exercise only. Post-serialization addendum at top of the doc documents the user's refinement: **preserve the monopoly plumbing as a runtime-flag-gated fallback** rather than tearing it out. Both paths stay first-class and tested per `feedback_feature_flag_preserves_old_path`.

- **Memory note added** — `feedback_exit_plan_mode_is_not_user_approval.md` protects against future false-positive reads of `ExitPlanMode`'s framework-default "approved" return value as actual user consent. Lesson captured after the user clarified mid-flow that they had been elsewhere when `ExitPlanMode` resolved; I had started TaskCreate scaffolding + a `find /` of the R&D dir structure before they redirected to serialize-only.

**Files modified** (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`):

- `src/rnd/v0.1.7/2026.05.11-per-session-speakerphone-mode.md` (NEW — design + addendum, 8 phases + verification matrix + risk register, all marked "if/when revisited")
- `history.md` (this entry)
- `.claude-session.md` (Checkpoint 3 touched-files block — speakerphone thought exercise)

**Status**:

- 💭 Speakerphone-mode plan **NOT** scheduled for implementation — captured for possible future revisit per user direction.
- ⏸️ No code touched, no tests run, no `:7999` bounce, no `:8000` scheduling.
- ✅ Memory feedback note landed; index updated.

**Commits**: This session-end commit only (parent Lupin; CoSA untouched).

---

### 2026.05.11 late PM - Session df880556 (María) | Multiplexer Phase 6b Phase 1 — store API prereqs + Phase 5 ownership-flag guard

**Persona**: María 🌸 (warm inquisitive female, #F06292)

#### Checkpoint | 2026.05.11 23:00 EDT | Phase 6b Phase 1 — store API prereqs landed; ready for Phase 2

**Accomplishments**:

- **Phase 6b code-execution pre-flight** — Re-audited feedback memories since 2026-05-11 plan author time (only `feedback_skip_arnold_yes_no_neither_ux` newer; not relevant); captured **`B6a = 31484` bytes** baseline from `boot.65c779ac946b.js` (Phase 6a closure artifact, built 2026-05-07T01:40:36Z, unchanged by HEAD 243267b which only touched TODO.md); recorded `B6a` + **AC7 ceiling = 39676 bytes** in both `2026.05.11-phase6b-code-execution-plan.md` and `90-execution-log.md`; verified all Pass 2 file:line citations still accurate (ActionRequiredStore.respond at L182, tick at L291, expires_at at L266; AudioStore state/queueLength/pause/resume/skip at L201-218; NotificationsListRenderer.renderActionRequiredSection at L228; actionRequiredReadOnly.ts:49 sets `data-id-hash` — confirmed no contract drift); confirmed `AudioStore.stop()` public method MISSING (Phase 1.3 must add).

- **Phase 1.1 — `ActionRequiredStore.respondAndAwait()`** (Pass 2 A1, Phase 0 prereq #8) — new non-optimistic public method: validates entry exists (throws on unknown id), validates state is `pending`/`failed` (throws otherwise — terminal states reject re-submission), flips state `pending → submitting`, stops countdown interval, emits `responded-pending` change kind with response payload, awaits POST, on success emits `responded` + transitions XState actor; on rejection emits `failed` + re-throws so caller can render inline error stripe and re-enable widget for retry. 6 new unit tests cover success path, rejection path, unknown idHash, retry-after-failure, terminal-state rejection, structured POST shape verification.

- **Phase 1.2 — Widen `respond()` + `respondAndAwait()` signature** (Pass 2 A2, Phase 0 prereq #9) — both methods now accept `string | ReadonlyArray<string> | Record<string, string>`. Added new `ActionRequiredResponse` discriminated union type to `shared/types.ts`. Widened `ActionRequiredItem.response?` to match. Server-side reconnaissance: `/api/notify/response` handler at `cosa/rest/routers/notifications.py:929-1040` treats `response_value` as `Dict[str, Any]` — accepts widened shape without changes (no CoSA-context task needed). 5 new unit tests cover array (multiSelect), Record (open_ended_batch), back-compat string for both `respond()` and `respondAndAwait()`.

- **Phase 1.3 — `AudioStore.stop()`** (Pass 2 A6, Phase 0 prereq #10) — extended XState machine with new `STOP_REQUESTED` event; added transitions `playing | paused | ended | error → idle`. Public `stop(): void` no-ops from idle/decoding; otherwise sends `STOP_REQUESTED` + clears `chunksInBurst = 0`. Semantically distinct from `skip()` (which terminates at `ended`) — design contract: idle + cleared queue + no auto-resume. 6 new unit tests cover all 4 entry states (playing/paused/ended/error), idle no-op, and the stop-vs-skip semantic contrast.

- **Phase 1.4 — `NotificationsListRenderer` ownership-flag early-return guard** (Pass 2 A3 Path A) — added single-line guard at `NotificationsListRenderer.ts:228` in `renderActionRequiredSection()`: `if (this.actionRequiredMount.dataset.phase6bOwner === "true") return;`. When the Phase 6b `ActionRequiredRenderer.mount()` claims ownership of the section, this read-only path short-circuits so the interactive widget DOM survives non-tick `store_action_required_changed` events from sibling widgets. 2 new unit tests cover both branches (flag set → short-circuit preserves Phase 6b marker DOM; flag absent → Phase 5 read-only path runs normally).

- **Phase 6b types extension** — `shared/types.ts`: `ActionRequiredState` gained `submitting` + `failed` (re-tryable, NOT terminal); `ActionRequiredChangeKind` gained `responded-pending` + `failed`; `StoreActionRequiredChangedPayload` gained optional `response?: ActionRequiredResponse` + `error?: unknown` for the new change kinds. Forward-compatible: existing Phase 4/5 consumers continue to read `id_hash` + `countdownMs` without changes.

- **Phase 1 verification (all GREEN, all on `:7999`-equivalent unit harness)** — `npx tsc --noEmit` exit 0; `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; **`c8 --100`** on the 3 edited TS files (ActionRequiredStore + AudioStore + NotificationsListRenderer) = 100% lines/branches/functions/statements; full multiplexer unit sweep **489/489 PASS** (was ~467 pre-edit; **22 new tests** added: 14 ActionRequiredStore + 6 AudioStore + 2 NotificationsListRenderer).

**Files modified** (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`):

- `src/fastapi_app/static/js/multiplexer/shared/types.ts` — extended `ActionRequiredState` + `ActionRequiredChangeKind` + `StoreActionRequiredChangedPayload`; new `ActionRequiredResponse` union
- `src/fastapi_app/static/js/multiplexer/stores/ActionRequiredStore.ts` — `respondAndAwait()` + widened `respond()` + `emitWithDetails()` helper
- `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` — `stop()` public + `STOP_REQUESTED` machine event + transitions from playing/paused/ended/error → idle
- `src/fastapi_app/static/js/multiplexer/render/NotificationsListRenderer.ts` — `phase6bOwner` ownership-flag guard at L228
- `src/tests/unit/multiplexer/action_required_store.test.ts` — +14 tests (32 → 46)
- `src/tests/unit/multiplexer/audio_store.test.ts` — +6 tests (23 → 29)
- `src/tests/unit/multiplexer/render/notifications_list_renderer.test.ts` — +2 tests (25 → 27)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/2026.05.11-phase6b-code-execution-plan.md` — Phase 0 plan serialization (B6a + AC7 ceiling recorded)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` — Phase 1 closure row, AC1/AC2 ✅, AC6 partial, B6a captured marker checked
- `TODO.md` — Phase 1 resume action checkboxes marked complete; new Phase 2 entry added
- `history.md` (this entry)
- `.claude-session.md` — register df880556 María + per-Edit touched-file records

**Status**:

- ✅ Phase 6b Phase 1 (store API prereqs + Phase 5 ownership-flag guard) — CLOSED; all sub-steps 1.1-1.5 GREEN
- ⏳ Phase 2 (interactive widget templates: `actionRequiredInteractive.ts` + `ttsChrome.ts`) — gated on user go-ahead
- ⏳ Phases 3-8 (renderers + delete-button wiring + CSS port + smoke + scheduled `:8000` E2E) — sequence per `2026.05.11-phase6b-code-execution-plan.md`
- ⏳ Mr. Radio session 77e1bb27 Phase 5b batch-2 results (`ts-476c971a`/`ts-99f2fa02`/`ts-8461cdd4`) — separate concern, owned by 77e1bb27 / future session

**Commits**: `b697c4c` (this checkpoint — parent Lupin only; CoSA untouched)

#### Checkpoint | 2026.05.11 23:45 EDT | Phase 6b Phase 2 — interactive widget templates landed

**Accomplishments**:

- **Phase 2.1 — `actionRequiredInteractive.ts`** (NEW, 228 LOC) — pure DOM template producer with switch over 5 response_type variants (yes_no / multiple_choice+radio / multiple_choice+checkbox / open_ended / open_ended_batch) plus a default-throws schema-drift defense. Each sub-builder (`buildYesNo`, `buildRadio`, `buildCheckbox`, `buildOpenEnded`, `buildOpenEndedBatch`) builds its own DOM via `html\`\`` tagged template + queries the resulting elements + attaches `addEventListener` handlers (mirrors Phase 6a `jobBucket.ts:126` precedent for self-contained interactive widgets). Submit semantics: yes_no buttons fire on direct click; radio fires `onSubmit(string)` on Submit click after at least one selection; checkbox fires `onSubmit(string[])` on Submit click (empty array if nothing checked); open_ended supports both Enter-key and Submit-click; open_ended_batch builds a `Record<header, value>` from per-row inputs. AC2e safe-write invariant header documents the no-`.innerHTML`/`rawHTML(`/`.outerHTML` rule; verified by grep-ban test (strips comments first so doc-mentions don't trigger).

- **Phase 2.2 — `ttsChrome.ts`** (NEW, 147 LOC) — TTS pane chrome with 3 controls (Pause/Resume single toggle, Stop, Skip) driven by an explicit state→enable matrix table:

| state    | toggle           | stop  | skip  |
|----------|------------------|-------|-------|
| idle     | disabled         | ✗     | ✗     |
| decoding | disabled         | ✗     | ✗     |
| playing  | enabled "Pause"  | ✓     | ✓     |
| paused   | enabled "Resume" | ✓     | ✓     |
| ended    | disabled         | ✓     | ✗     |
| error    | disabled         | ✓     | ✗     |

  Plus `currentTrackName` line (rendered only when present + non-empty), `queueLength` indicator, `.is-playing-current` / `.is-paused-current` classes per Q-B8 (ported from legacy `notifications.css:4692-4712, 4718-4725`). `data-state` + `data-testid` always set for E2E observability. AC2e safe-write invariant + grep-ban test mirror the interactive template's contract.

- **Type extension — `ActionRequiredItem.multiSelect?: boolean`** — added to `shared/types.ts` to support the Pass 2 A2 dispatch contract (`multiple_choice + multiSelect:true → checkbox`, default `false`/undefined → radio). Wire-side population still gated on Phase 0 prereq #2 verification (server payload schema field name).

- **Test coverage** — 22 tests in `templates_action_required_interactive.test.ts` (≥15 floor) covering 5 happy-path renders + 5 click-dispatch scenarios + unknown-response_type throws + multi-instance independence + prompt-rendering parametric across all response_types + multiSelect-undefined defaults to radio + empty-options batch + AC2e grep ban. 18 tests in `templates_tts_chrome.test.ts` (≥15 floor) covering 6 state-driven renders + 4 click-dispatch + currentTrackName present/absent/empty + queueLength + class invariants + multi-instance independence + disabled-controls non-interactive + data-testid/data-state observability + AC2e grep ban.

- **c8 100% gate** — both new template files hit 100% lines / branches / functions / statements after applying the canonical `/* c8 ignore next N */` annotation pattern from Phase 6a `jobCard.ts:251` (tagged-template literal phantom-branch artifact: c8 reports phantom branches on `${...}` interpolations that are straight-line at runtime; pattern documented inline with reason citation). Full multiplexer unit sweep stayed clean — **528/528 PASS** (was 489/489 pre-Phase-2; 39 new tests added: 22 + 18 templates − 1 nominal duplicate).

- **Verification matrix (all GREEN, all on `:7999`-equivalent unit harness)**: `npx tsc --noEmit` exit 0; `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; `c8 --100` on both new templates exit 0; full multiplexer unit sweep 528/528 PASS.

**Files modified** (parent Lupin only — CoSA untouched):

- `src/fastapi_app/static/js/multiplexer/shared/types.ts` — added `multiSelect?: boolean` to `ActionRequiredItem`
- `src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts` — NEW (228 LOC)
- `src/fastapi_app/static/js/multiplexer/render/templates/ttsChrome.ts` — NEW (147 LOC)
- `src/tests/unit/multiplexer/render/templates_action_required_interactive.test.ts` — NEW (22 tests)
- `src/tests/unit/multiplexer/render/templates_tts_chrome.test.ts` — NEW (18 tests)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` — Phase 2 closure row + AC3/AC4/AC2e/AC6 status updates
- `TODO.md` — Phase 2 sub-step checkboxes marked done; Phase 3 entry added
- `history.md` (this entry)
- `.claude-session.md` — per-Edit touched-file records appended

**Status**:

- ✅ Phase 6b Phase 2 (interactive widget templates) — CLOSED; both new files at c8 100%; 40 new tests landed
- ⏳ Phase 3 (`ActionRequiredRenderer.ts` — consumes Phase 2 template + Phase 1 `respondAndAwait`) — gated on user go-ahead
- ⏳ Phases 4-8 — sequence per `2026.05.11-phase6b-code-execution-plan.md`

**Commits**: `ad2f479` (this checkpoint — parent Lupin only; CoSA untouched)

#### Session-end | 2026.05.12 00:30 EDT | Phase 6b Phases 3 + 4 — both renderers landed (batched commit per user direction)

**Accomplishments**:

- **Phase 3 — `ActionRequiredRenderer.ts`** (NEW, ~360 LOC) — claims pane ownership via `dataset.phase6bOwner="true"` BEFORE any DOM write (Pass 2 A3 Path A); 5 widget builders (interactive/submitting/responded/expired/cancelled) with state-driven dispatch; click handlers route to `respondAndAwait` from Phase 1 (NOT optimistic respond per Pass 2 A1); store events drive UI state transitions; tick events update countdown via `.textContent` only — NO renderer-side `requestAnimationFrame` (per Pass 2 a2; spy-asserted in tests). Includes inline error stripe rendering on `failed` state, atomic widget swap via `replaceWith` (1-2 MutationObserver records — happy-dom microbatches, browsers may behave the same; AC2c atomicity invariant verified).

- **Phase 4 — `TtsChromeRenderer.ts`** (NEW, ~155 LOC) — dual-subscription (`store_audio_state_change` AND `store_audio_chunk_decoded`) with single shared `pendingRender` flag + RAF coalescing (per Q-B9 + Pass 1 F-13); test-injectable `requestAnimationFrameFn` / `cancelAnimationFrameFn` lets storm-safety tests deterministically flush; click handlers wire to `AudioStore.pause/resume/stop/skip`; uses `replaceChildren` for atomic full-pane swap (cleaner than `replaceWith` — no phantom-branch issues); `currentTrackName` intentionally omitted (Phase 0 prereq #3 still pending verification).

- **Test coverage** — 34 tests on `action_required_renderer.test.ts` (≥21 AC5 floor) covering 6 submit happy-path + 5 error-rollback + 6 state-machine transitions + countdown/NO-RAF spy + mount idempotency + AC2c atomic strip + inline error stripe + ownership-flag + cssEscape fallback + multi-item + offline-frozen/resumed + edge cases. 20 tests on `tts_chrome_renderer.test.ts` (≥13 AC5b floor) covering 7 state transitions + 4 control wiring + 2 storm safety (chunk_decoded × 100 → 1 RAF; state_change × 5 → 1 RAF) + mount idempotency + stop semantics (Phase 1.3 contract) + mixed-event coalescing.

- **c8 100% gate** — both new renderer files at 100% lines/branches/functions/statements. `ActionRequiredRenderer.ts` required one `c8 ignore start/stop` bracket on the `cssEscape` polyfill (defensive cross-environment helper, regex-character-class branches are V8-instrumentation-implementation-dependent — mirrors `NotificationsListRenderer.ts:423` precedent). `TtsChromeRenderer.ts` hit 100% on first try (no phantom-branch issues thanks to `replaceChildren`). Full multiplexer unit sweep: **582/582 PASS** (was 528 pre-Phase-3+4; **+54 new tests**).

- **Verification matrix (all GREEN, all on `:7999`-equivalent unit harness)**: `npx tsc --noEmit` exit 0; `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; `c8 --100` on both new renderer files exit 0; full multiplexer unit sweep 582/582 PASS.

**Files modified** (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`):

- `src/fastapi_app/static/js/multiplexer/render/ActionRequiredRenderer.ts` — NEW (~360 LOC)
- `src/fastapi_app/static/js/multiplexer/render/TtsChromeRenderer.ts` — NEW (~155 LOC)
- `src/tests/unit/multiplexer/render/action_required_renderer.test.ts` — NEW (34 tests)
- `src/tests/unit/multiplexer/render/tts_chrome_renderer.test.ts` — NEW (20 tests)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` — Phase 3 + 4 closure rows
- `TODO.md` — Phase 3 + 4 sub-step checkboxes marked done; Phase 5A → 5B starting-point quick-start checklist added; resume pointer rewritten to "FIRST THING TOMORROW — Phase 5A → 5B"
- `history.md` (this entry)
- `.claude-session.md` — per-Edit touched-file records appended; status will flip to `committed` post-commit

**Status**:

- ✅ Phase 6b Phase 3 (ActionRequiredRenderer) — CLOSED (this session-end commit lands it)
- ✅ Phase 6b Phase 4 (TtsChromeRenderer) — CLOSED (batched in this commit per user direction "skip checkpoint, just start Phase 4 work")
- ⏳ Phase 5A → 5B (JobStore.delete + delete-button click handler) — **starting point for tomorrow** (resume pointer at top of TODO.md)
- ⏳ Phases 6-8 (CSS port + boot wiring + smoke + scheduled `:8000` E2E) — sequence per `2026.05.11-phase6b-code-execution-plan.md`

**Commits**: (this session-end commit hash filled in post-commit; no push per user direction)

---

### 2026.05.11 PM - Session 77e1bb27 (Mr. Radio) | Voice Persona Rename Domi→Rio implementation + Phase 5b :8000 scheduling (2 batches)

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

#### Checkpoint | 2026.05.11 18:00 EDT | Domi→Rio rename landed; Phase 5b batches 1+2 in flight

**Accomplishments**:

- **Voice Persona Rename "Domi" → "Rio"** — name-only label rotation per user directive. Inherited Phase 0 plan doc from prior session 68edb64b (`src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md`, which was orphaned uncommitted at 68edb64b session-end). User answers to the 4 open questions: icon ⚡ KEEP, color `#880E4F` KEEP, profile text "Young & energetic female" KEEP, this-session reallocation N/A (Mr. Radio active). Implementation: 4 files edited (5 hits in `lupin-app.ini` pool list + 4 key block; 6 surgical edits in `lupin-app-splainer.ini` sparing line 175's ElevenLabs catalog reference; 7 replace_all hits in `test_voice_persona_helpers.py`; 2 replace_all hits in `test_voice_persona_allocation.py`). Audit-trail rename history added to splainer line 297 (pool list) and line 319 (Rio voice id splainer), mirroring existing Nora→maria + Quentin→mr radio + Adam→Tiberius precedent. Verification: py_compile clean; unit 34/34 pass (0.08s); smoke 7/7 pass (0.39s); live `:7999` `GET /api/cosa-voice/voice-persona/pool` returns `Rio` with all preserved attributes intact. **No `:7999` bounce required** — pool query re-reads INI per request (pleasant surprise vs the plan's "out-of-scope" assumption).

- **CC Card Normalization Phase 5b — Batch 1 scheduled + post-mortem** — user explicitly authorized `lupin-rest-test` (`:8000`) bounce; refresh-test-server.sh ran clean (24s to healthy). 3 sequential submissions via `/api/test-suite/submit` at 17:13:48 EDT, scheduled for 17:16:48 / 17:31:48 / 17:46:48. Results: **5.8 GREEN** (30/30 passed, 106.6s, AC11 met; new `test_cc_card_renders_in_sibling_shape` runs clean); **5.9 baseline regen completed** (16 passed, 0 failed, 15 errors, 0 skipped — the 15 "errors" are `pytest_playwright_visual_snapshot` standard `--update-snapshots` teardown signals "Snapshots updated. Please review images.", NOT failures; 15 baselines regenerated at `io/test-suite/visual-baselines/` covering 3 CC-normalization-adjacent + 5 auth/account + 5 admin + 2 dev/infra paths); **5.10 SKIPPED** (0/0/0/2 — subscription tests gated out, user later noted 401-cred-system issues at the time as likely cause).

- **CC Card Normalization Phase 5b — Batch 2 resubmitted** — at 17:59:16 EDT user reported the credential-processing 401 issues were restored. Resubmitted same triplet structure but with 5.9 as a TRUE regression (no `--update-snapshots`) to close AC11 via self-consistency check against batch-1's regenerated baselines: **5.8 retry** `ts-476c971a` @ 18:01:16, **5.9-regression** `ts-99f2fa02` @ 18:13:16, **5.10 retry** `ts-8461cdd4` @ 18:25:16. Results expected ~18:35 EDT; next session-checkpoint or session-end revisits the done bucket.

**Files modified** (parent Lupin scope only):

- `src/conf/lupin-app.ini` — Domi→Rio rename (5 lines: pool list + 4 key block); `=` column alignment preserved. **Note**: file also carries parallel session 9a4a601d (Rachel)'s commons INI keys at lines 518-530 (cleanly separate hunk; co-committed by interleaved-file-state pragmatism with attribution in commit message).
- `src/conf/lupin-app-splainer.ini` — Domi→Rio rename (6 surgical edits: pool list + maria color disambig + 4 Rio key splainers + Arnold color disambig); line 175 ElevenLabs catalog reference deliberately preserved. **Note**: also carries Rachel's commons splainer block at lines 691-705 (cleanly separate).
- `src/tests/unit/test_voice_persona_helpers.py` — replace_all Domi→Rio (7 hits).
- `src/tests/smoke/test_voice_persona_allocation.py` — replace_all Domi→Rio (2 hits).
- `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` — plan doc orphaned by 68edb64b session-end; folded into this commit for clean audit trail.
- `TODO.md` — Phase 5b 3-job batch closure rewritten to reflect batch-1 results + batch-2 in-flight scheduling; new "✅ DONE — Voice Persona Rename Domi → Rio" section appended.
- `history.md` (this entry).
- `.claude-session.md` — register session 77e1bb27 Mr. Radio + per-Edit touched-file records.

**Status**:

- ✅ Domi → Rio rename CLOSED (4 files edited, 34/34 unit + 7/7 smoke green, live `:7999` verified)
- ✅ Phase 5b batch 1 fired + post-mortem written (5.8 GREEN; 5.9 baselines regenerated; 5.10 skipped pending credential restoration)
- ⏳ Phase 5b batch 2 fired (results @ ~18:35 EDT); revisit at next checkpoint
- ⏳ CC card normalization Phase 6.8 parent commit (separate concern, gated on Phase 5b full closure)
- ⏳ Mobile sub-repo TODO seed for "Domi" → "Rio" in cheat-sheets — deferred to mobile-context session per plan-handoff convention

**Commits**: `54f66a6` (this checkpoint commit — parent Lupin only)

#### Post-checkpoint addendum | 2026.05.11 20:00-20:15 EDT | 5.10 deep dive → test RETIRED

**Triggered by**: user request to investigate why the 5.10 subscription test was skipping in batch 1 / 2.

**Findings** (chained):

1. **Gate #1 — `_container_running()` skip**: test was authored as a host-side "deployment probe" calling `docker ps`, but `/api/test-suite/submit` schedules pytest INSIDE the container where the `docker` CLI doesn't exist → `FileNotFoundError` → fixture skipped the whole test. Fixed via `/.dockerenv` short-circuit (new `_running_inside_container()` helper).

2. **Gate #2 — `_server_reachable()` skip**: `TEST_SERVER_BASE = "http://localhost:8000"` hardcoded — but inside the container `:8000` is unreachable (container listens on `:7999` internally). Fixed via `os.environ.get("LUPIN_API_URL", "http://localhost:8000")` — aligns with `feedback_tests_parameterize_base_url.md`.

3. **Gate #3 — stale credentials (Docker bind-mount inode capture)**: `~/.claude/.credentials.json` bind-mounted as a single file → bound to host inode at container-start time. User refreshed creds at 17:52 EDT (atomic write-then-rename → new inode), but container kept seeing the pre-refresh content (hash `4cfccc...` vs host `734012...`). Fixed via test-server bounce (re-bound to current host inode). Long-term mitigation: mount the parent `~/.claude/` directory instead of just the file — directory bind mounts DO follow inode changes inside them.

4. **Gate #4 — schema-drift in `_extract_cost_usd()`**: helper looked for `cost_summary` inside `artifacts` key at top of job record, but the job-history persistence layer stores it inside `metadata_json`. Fixed two-file: (a) `src/cosa/agents/claude_code/job.py` Bounded path now puts `cost_summary` in `self.artifacts` (parity with the dry-run path); (b) `_extract_cost_usd()` now also reads `metadata_json.cost_summary.total_cost_usd`.

5. **THE PREMISE — AC10's `cost_usd == 0.0` is unsalvageable**: with all 4 gates above unblocked, the test finally executed end-to-end and the underlying CC CLI behavior surfaced: `claude -p` non-interactive mode reports `total_cost_usd > 0` on every call (~$0.05 in container, ~$0.32 on host) **even with no `ANTHROPIC_API_KEY` and valid Max OAuth credentials**. User insight (the breakthrough): the cost field is COUNTERFACTUAL API pricing reported as metadata, NOT actual billing. With no API key for the CLI to bill against, Max OAuth is paying the flat rate; the CLI just always reports "what this would cost via API" in its result envelope regardless of auth path. **The test as authored cannot pass on any valid CC CLI invocation.**

**Decision**: 5.10 RETIRED. Module-level `pytestmark = pytest.mark.skip(reason=...)` added to `src/tests/smoke/test_claude_code_max_subscription.py` with full forensic trail in module docstring. The 4 architecture fixes are preserved as patterns for future CC-related smoke tests that need to work both on host and inside the test container.

**Files modified (post-checkpoint, uncommitted)**:
- `src/tests/smoke/test_claude_code_max_subscription.py` — 5 surgical edits + module-level skip marker + forensic-trail docstring
- `src/cosa/agents/claude_code/job.py` — Bounded path artifacts dict now includes `cost_summary` (CoSA edit, separate commit context per `feedback_lupin_only_never_cosa`)
- `TODO.md` — 5.10 rows marked retired; AC10 closed; new TFE-to-CC design-doc amendment item filed
- `history.md` (this addendum)

**:8000 test server bounces this session**: 2 total (17:13 EDT for batch-2 setup, 19:55 EDT after credential refresh + CoSA cost_summary fix; queues confirmed empty before each per server-lifecycle courtesy).

**Phase 5b NET STATUS after retirement**:
- 5.8 ✅ functional regression GREEN both batches
- 5.9 ✅ visual baselines regenerated + self-consistency confirmed
- 5.10 ✅ RETIRED (premise invalid)
- Phase 6.8 parent commit functionally unblocked on CC card normalization scope.

**Caveats / Notes**:

- **Parallel session co-commit (lupin-app.ini + splainer)**: parallel session `9a4a601d` (Rachel, persona Rachel) was mid-Phase-1 implementation of inter-session-commons MCP and had already added 12 commons INI keys + 9 splainer entries to those 2 files when I started editing. Hunks are physically separate (Rachel's at lines 518+ / 691+; mine at 794-826 / 297-326). Pragmatic decision: commit both sets together with explicit attribution in commit message. Rachel's Python code (`commons_ask.py`, `commons_archival.py`, `commons` MCP shims in `cosa_voice_mcp.py`, etc.) is NOT in this commit — it remains in her manifest section for her own commit.
- **Plan doc adoption**: `2026.05.11-rename-persona-domi-to-rio.md` was authored by session 68edb64b (Domi, evening) and intended to be committed in that session-end per the entry below this one. The 68edb64b session-end commit never landed (no `Session-end 68edb64b` in `git log`), leaving the plan doc orphaned uncommitted. Adopted into this commit for clean audit trail; cross-references in the plan doc itself remain valid.
- **`:7999` server-lifecycle**: did NOT bounce — pool query re-reads INI per request, so the rename was live immediately on `GET /api/cosa-voice/voice-persona/pool` without restart. Pleasant deviation from the plan's "Out of Scope" expectation. Per server-lifecycle Rule 1 (never volunteer a `:7999` bounce), no advisory issued.

---

### 2026.05.11 EVE - Session 68edb64b | Voice Persona Rename — brainstormed alternatives to "Domi", user picked "Rio", plan doc serialized + delivered as viewer link

**Persona**: Domi ⚡ (Young & energetic female, #880E4F) — *the very persona being renamed in the plan this session produced*

**Accomplishments**:

- **Brainstormed ~30 alternative persona names** across 5 vibe-clusters (punchy/spark-coded, energy-vitality semantics, modern-bright, playful/pixie, distinctive) for the "Young & energetic female" voice slot occupied by "Domi". User selected **Rio**.
- **Plan doc serialized** at `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` per `feedback_phase0_serialization_prominence.md` and the plan-serialization mandate. Doc covers: scope (label-only — voice_id unchanged → no TTS audio change), proposed preserved attributes (icon ⚡ / color #880E4F / profile text), file inventory (5 files: lupin-app.ini + splainer + 2 test files), full sweep check (all 13 grep hits classified CHANGE / KEEP / HANDOFF), cross-project handoff plan for mobile sub-repo (zero runtime impact — just doc references), test impact per layer, 4 open questions, execution sequence, explicit out-of-scope list.
- **Document-viewer-link notification delivered** per `feedback_documentation_step_stops_at_doc.md` — closing turn was `notify()` with the markdown viewer link in the abstract; deliberately did NOT auto-progress to ExitPlanMode, batched decision questions, or implementation. Plan is parked awaiting user "go" + answers to the 4 open questions (icon rotation? color rotation? profile rephrase? this-session reallocation on next /clear?).
- **Session-topic discipline**: `set_session_topic("Voice Persona Rename — alternatives to 'Domi'")` set after MCP Phase A and before any substantive tool work, per the session-topic mandate.

**Files modified** (parent Lupin scope only):

- `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` (NEW — plan doc, ~200 lines)
- `history.md` (this entry)
- `TODO.md` (added pending entry for Rio rename implementation — see TODO.md "Pending" section)
- `.claude-session.md` (session-start manifest registration was skipped this session; entry will be appended in this commit's session-end pass if applicable)

**Status**:

- ✅ Brainstorm delivered + name selected
- ✅ Plan doc serialized + delivered via viewer link
- ⏳ User review + answers to 4 open questions before any code edits land
- ⏳ Implementation (5-file rename + test fixture updates) parked pending approval

**Commits**: this session-end commit (parent Lupin only — `no backup, no push` per user)

**Caveats / Notes**:

- Many other files are showing modified in `git status` — these are from parallel sessions today (658ea35d, 6d544991, 6e8a6a03, 017dc1cc, f9608a41) and are **out of scope** for this session's commit. Per the parallel-session-safety v2.0 mandate, this session's commit stages ONLY: the new plan doc, `history.md`, `TODO.md`.
- Session-start manifest registration was skipped this session (no `## Session: 68edb64b` block in `.claude-session.md` at session-end time). Pre-commit verification falls under the "missing manifest" path; the explicit selective-staging list above takes the place of the manifest's section.

---

### 2026.05.11 PM/EVE - Session 658ea35d | CC Card Normalization — Phases 1-5a CLOSED end-to-end; Phase 5b awaiting `:8000` user slot; commits HELD for authorization

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **All 6 implementation phases of CC card normalization landed in one session** (Phase 0 + plan-review closure inherited from Rachel @ 6e8a6a03 earlier this morning):
  - **Phase 1 (HTML normalization)** — 8 sub-steps applied to `notifications.html` + `notifications.css`. Header rename (`Dispatcher` → `Submit Claude Code Task`); INTERACTIVE comment promoted to disabled `<option>` with tooltip; deleted 5 dead UI blocks (cc-execution-mode select div, cc-response retirement-notice `<pre>`, cc-option-b-controls + 4 disabled inject/interrupt/end inputs, cc-session-info hidden row, .cc-retired-banner CSS class + section-comment header — 29 CSS lines, NOT 2 as REUSE-pre-pass hinted); inserted sibling-pattern `#cc-submit-status` div. AC1, AC1.5, AC2, AC3, AC4 all GREEN via grep.
  - **Phase 2 (JS handler normalization)** — Rewrote `submitClaudeCode()` + `submitClaudeCodeToQueue()` in `notifications.js` to mirror research handler at L2865-2949. Collapsed from 7-arg to 4-arg signature; statusDiv with 3 canonical colors (#666 neutral, #28a745 success, #dc3545 error); dropped all writes to deleted IDs (responseEl, cc-task-id, cc-status, cc-cost, cc-session-info); fetch URL switched to canonical `/api/claude-code/submit`; refreshed L40-42 + L3812 comment blocks to describe post-normalization shape. AC5, AC6 GREEN.
  - **Phase 3 (E2E test cleanup)** — Deleted 2 obsolete `test_cc_card_has_execution_mode_select` + `test_cc_card_has_session_controls` from `test_job_dispatch.py`; added `test_cc_card_renders_in_sibling_shape` asserting header text + sibling-shape DOM + INTERACTIVE-disabled invariant (Q2 FROZEN visible-breadcrumb). py_compile clean.
  - **Phase 4 (URL rename + alias)** — **Q8 VERDICT: PRIMARY** — FastAPI 0.115.12 accepted stacked-`@router.post(...)` decorators on a single handler. CoSA `claude_code_queue.py` now registers BOTH `/api/claude-code/submit` (canonical) AND `/api/claude-code/queue/submit` (deprecated alias with `deprecated=True` in OpenAPI schema, per-request deprecation log via injected `Request` parameter). Module docstring + `quick_smoke_test()` updated to assert both routes. 2 parent-side smoke-test SUBMIT_ENDPOINT constants updated. CoSA edits made from parent context (file-edits only per `feedback_cosa_edit_vs_manage_git`; CoSA git ops are a separate-context concern per `feedback_lupin_only_never_cosa`).
  - **Phase 4.5 (handoff doc finalize)** — `02-handoff-summary.md` Q8 verdict populated as `PRIMARY`; migration timeline filled with the dates/events that have landed; placeholder-vs-literal paragraph replaced with the resolved verdict announcement.
  - **Phase 5a (`:7999` AI-discretionary verification)** — 5.1-5.6 + 5.11 all GREEN: py_compile, import-chain, router smoke (Q8 verdict gate, 5/5 internal tests), live POST to canonical URL with real JWT (HTTP 200 + `cc-41cea588`), live POST to deprecated alias with real JWT (HTTP 200 + `cc-42d86fdd`), 6-scenario dry-run smoke (6/6), TFE + BFE smoke (2/2 in 31.6s). 5.7 headless UI probe folded naturally into 5.8 :8000 functional run (new sibling-shape test is the same Playwright-driven probe). AC7, AC9, AC12 GREEN.

- **`feedback_skip_arnold_yes_no_neither_ux.md` filed** at session start (with index-pointer in `MEMORY.md`) — Arnold (session 6d544991, parallel) owns the `ask_yes_no()` "neither/discuss-further" button work; that item is skipped from future unprompted top-N TODO summaries. Arnold's own end-of-day entry above is the relevant audit trail for the actual work landed there.

- **Session-topic discipline**: topic updated mid-session from session-start summary ("Session start — top 5 TODO summary") to phase-execution ("CC Card Normalization — Phases 2-6 implementation") per the auto-memory mandate "set when topic is knowable, update at task switches."

- **Notifications**: high-priority `notify()` with rich markdown abstract surfaced at top-5 summary delivery time and Phase 1 closure; conversation mode was OFF for the whole session.

**Files modified** (parent Lupin scope only — no CoSA git ops despite CoSA file edits):

- `src/fastapi_app/static/html/notifications.html` (Phase 1.1-1.7)
- `src/fastapi_app/static/css/notifications.css` (Phase 1.8)
- `src/fastapi_app/static/js/notifications.js` (Phase 2.2-2.4 + L40-42 comment refresh)
- `src/tests/e2e_ui/test_job_dispatch.py` (Phase 3.1-3.4)
- `src/cosa/rest/routers/claude_code_queue.py` (Phase 4.1-4.5 — CoSA file edit, NOT committed in CoSA submodule)
- `src/tests/smoke/test_claude_code_dry_run_smoke.py` (Phase 4.6 — SUBMIT_ENDPOINT)
- `src/tests/smoke/test_claude_code_max_subscription.py` (Phase 4.7 — SUBMIT_ENDPOINT)
- `TODO.md` (Phase 6.1 — closed manual UI probe + finalized mobile dispatch entry with canonical URL; Phase 6.2 — added Multiplexer follow-ups section)
- `src/lupin-mobile/TODO.md` (Phase 6.3 — `[LUPIN-CC-SUBMIT-RENAME]` entry seeded under the existing 2026-05-11 CC sync section; mobile session owns the actual commit)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` (Phase 6.4 — added §9 "Open follow-ups (cross-cutting)" with pointer back to handoff doc)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` (phase status table flipped; all 6 implementation phases marked DONE / 5b AWAITING USER / 6 PARTIAL)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` (untouched this session — design was final pre-implementation)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` (Phase 4.5 — Q8 verdict populated, migration timeline filled)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` (Phase 2/3/4/4.5/5a per-sub-step evidence + AC verifications + spec-drift documentation)
- `history.md` (this entry)
- `.claude-session.md` (registered session 658ea35d + per-Edit touched-file records)
- (outside repo) `~/.claude/projects/.../memory/feedback_skip_arnold_yes_no_neither_ux.md` (NEW)
- (outside repo) `~/.claude/projects/.../memory/MEMORY.md` (index updated)

**Status**:

- ✅ All AI-discretionary work CLOSED (Phases 1-5a + Phase 6 doc/tracking updates)
- ⏳ Phase 5b awaiting user slot confirmation for 3 `:8000` scheduled submissions (5.8 e2e `-k test_job_dispatch`, 5.9 e2e `-k visual` for baseline regen, 5.10 smoke `-k test_claude_code_max_subscription`)
- ⏳ Phase 6.8 parent-Lupin commit HELD for explicit user authorization per `feedback_never_auto_commit_push`
- ⏳ Phase 6.9 CoSA commit HELD — separate context per `feedback_lupin_only_never_cosa`; AI file edits at `src/cosa/rest/routers/claude_code_queue.py` are on disk awaiting a CoSA-session user-run commit
- ⏳ Phase 6.5 — `bug-fix-queue.md` checked; zero entries reference CC card normalization (no closure needed)

**Commits**:

- None this session. All work held pending user authorization (parent + CoSA in their respective contexts).

**Cycle state for the CC card normalization R&D folder**:

- Phase 0 ✅ • REUSE ✅ • Pass 1 ✅ • Pass 2 ✅ • Phase 1 ✅ • Phase 2 ✅ • Phase 3 ✅ • Phase 4 ✅ • Phase 4.5 ✅ • Phase 5a ✅ • Phase 5b ⏳ user slot • Phase 6 ⏳ partial (docs done; commits pending)

**Caveats / Notes**:

- Phase 1 → Phase 2 sequencing constraint: between the HTML deletion (Phase 1) and the JS rewrite (Phase 2) the CC submit handler would have thrown `TypeError` at `getElementById('cc-session-info').style.display` (the deleted DOM ID). Both phases landed in the same session within ~10 minutes; no `:7999` testing happened between them. Documented in the execution log "Spec drifts" subsection.
- Phase 2.1 (audit cc-inject/cc-interrupt/cc-end/cc-execution-mode event-binding lookups) became a no-op — the 2026-05-05 retirement work already replaced those bindings with a single comment block; nothing to remove. Closure recorded in execution log.
- Phase 1.8 CSS delete was 29 lines, not 2 as REUSE pre-pass implied — the parenthetical "(2 lines)" counted only `.cc-retired-banner` class-declaration lines without the section-comment header + sibling `code` rule. All within design's stated scope ("DELETE the class definition"); REUSE confirmed orphan-safe.
- 5.4 + 5.5 created 2 real CJ Flow jobs (`cc-41cea588` + `cc-42d86fdd`) with `dry_run=true`; both will complete-fast with no LLM cost. Visible in the dev `:7999` server queues.
- Parallel sessions on 2026-05-11: Rachel @ 6e8a6a03 (Phase 0 + plan-review for this CC card normalization work; committed `27f0da6` earlier this morning), Mr. Radio @ 017dc1cc (multiplexer Phase 6b Pass 1; committed `27f0da6` bundle), Tiberius @ f9608a41 (inter-session commons; uncommitted — separate scope), Arnold @ 6d544991 (cosa-voice neither/discuss; parent commit pending — see entry below), this session 658ea35d (implementation of the Rachel-authored CC card normalization plan; commits pending).

---

### 2026.05.11 PM - Session 6d544991 | `ask_yes_no()` "Neither" affordance — landed end-to-end (parent Lupin scope); CoSA commit pending separate context

**Persona**: Arnold 🪨 (gravelly male, #FFD600)

**Accomplishments**:

- **`ask_yes_no()` MCP tool gains a third "Neither" answer button** alongside Yes/No, wired end-to-end across CoSA helper + Lupin MCP + Lupin frontend + project docs. Return value `"neither"` (or `"neither [comment: ...]"`) is distinct from `"yes"`/`"no"` so Claude can branch on it explicitly. Comment field is **load-bearing** when Neither is selected — `format_qualified_response` has a dedicated branch with explicit Claude-directive: "treat as instruction to re-frame the question, not as a soft yes or no. Read the comment, then ask a clearer follow-up." Closes the open TODO filed 2026-05-07 by session 6825e6af.

- **7-phase plan executed end-to-end** (single approved sequence, no mid-impl gates): Phase 0 R&D docs → Phase 1 CoSA backend → Phase 2 MCP docstring → Phase 3 frontend HTML+CSS → Phase 4 unit tests → Phase 5 project docs → Phase 6 TODO+history+commit. Phase 7 (MCP restart for end-to-end E2E verification) is EXECUTOR: HUMAN, parked for next session.

- **Q-decisions ratified** (7): Q1 label=Neither (user-ratified via cosa-voice `ask_multiple_choice`), Q2 keyboard shortcut=none (mouse/touch only, user-ratified), Q3 return value=`"neither"` lowercase, Q4 schema=extend YES_NO response_value vocabulary (NO new ResponseType — minimum blast radius), Q5 default-on-timeout unchanged (yes/no only), Q6 comment qualifier works for all 3 buttons, Q7 visual=neutral gray (#6c757d, no green per `feedback_no_green_in_persona_pool`).

- **R&D doc set landed** at `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/` (4 files, ~13KB total): `00-index.md` (master nav, Q-table, REUSE table), `01-design.md` (full design with §2a comment-parsing-for-Neither guarantee + §3a Pass 1 Fitness/Viability self-review + §3b Pass 2 Adversarial self-review — all findings ratified inline, 0 Block / 0 Major / 2 Minor across both passes), `02-handoff-summary.md` (CoSA-context-session pointer for the working-tree commit), `90-execution-log.md` (per-phase status with verification evidence).

- **R1 (`format_qualified_response` wording) promoted from "deferred" to "applied"** during Pass 1 self-review after user voice-feedback confirmed the comment-parsing-for-Neither is load-bearing, not optional. The `if answer == "neither":` branch with re-framed copy now lives in `notification_utils.py`.

- **Cross-sub-project handoff**: One CoSA file edited (`src/cosa/utils/notification_utils.py` — regex + format branch + smoke test). Per `feedback_lupin_only_never_cosa`, the parent Lupin commit does NOT stage this file; it stays in the CoSA working tree for the next CoSA-context session to commit. The 02-handoff-summary.md doc seeds the CoSA-context TODO.

- **Tests**: 12/12 `TestExtractQualifierComment` unit tests passing (4 new `test_neither_*` methods + 8 pre-existing yes/no tests confirming additive regex). Full `test_stop_hook.py` suite: 50/50 passing. `quick_smoke_test()` in `notification_utils.py` extended with 3 neither parse cases + 1 neither format case, all green. `py_compile` clean on both `notification_utils.py` and `cosa_voice_mcp.py`.

- **MCP server restart caveat documented**: The cosa-voice MCP runs as a stdio subprocess of Claude Code (`Type: stdio`); the Python process loaded `cosa_voice_mcp.py` once at startup and does not re-read the file. Current session (6d544991) will NOT see the docstring change — fresh CC session required for end-to-end E2E verification. Phase 7 captures this as EXECUTOR: HUMAN.

**Files** (parent-Lupin scope only — CoSA file edited but NOT staged):

- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/00-index.md` (NEW — 65 LoC)
- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/01-design.md` (NEW — ~250 LoC post Pass 1 + Pass 2 additions)
- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/02-handoff-summary.md` (NEW — 70 LoC)
- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/90-execution-log.md` (NEW — phase status)
- `src/lupin_mcp/cosa_voice_mcp.py` (docstring updated for `ask_yes_no` — 3-way return value contract)
- `src/fastapi_app/static/js/notifications.js` (3rd `<button class="response-button neither">` added to yes_no render at line 13796)
- `src/fastapi_app/static/css/notifications.css` (new `.response-button.neither` neutral-gray rule)
- `src/tests/unit/test_stop_hook.py` (4 new `test_neither_*` methods in `TestExtractQualifierComment`)
- `src/docs/notification-api.md` (3 rows updated: `yes_no` table row at line 895, `ask_yes_no()` tools row at line 1646, example block return-value comment at line 1672)
- `TODO.md` (marked MCP-Neither task ✅ DONE with details; added ☀️ FIRST THING NEXT SESSION for CoSA-context commit + fresh-session E2E verify; refreshed Last-updated)
- `history.md` (this entry)
- `.claude-session.md` (registered session 6d544991 + touched files)
- (outside repo, edited) `~/.claude/CLAUDE.md` (one row updated in Available MCP Tools table at line 322; routing-table label denied by auto-classifier — acceptable, tool-description row is the load-bearing entry)
- (outside repo, plan source) `~/.claude/plans/swirling-watching-hinton.md`

**Files edited in CoSA submodule but NOT committed** (per cross-sub-project handoff):
- `src/cosa/utils/notification_utils.py` — regex extension `(yes|no)` → `(yes|no|neither)`; `format_qualified_response` "neither" branch; `quick_smoke_test` 3 neither parse + 1 neither format cases. Stays in CoSA working tree for next CoSA-context session to commit.

**Status**: Parent Lupin scope ✅ DONE. CoSA scope ⏳ pending CoSA-context-session commit. Fresh CC session ⏳ pending for end-to-end MCP-driven E2E verification.

---

### 2026.05.11 - Session 6e8a6a03 | CC notifications-card normalization — Phase 0 docs + plan-review (all 3 passes) CLOSED; Phase 1 implementation parked READY TO BEGIN

**Persona**: Rachel 🕊️ (calm & clear female, #7B1FA2)

**Accomplishments**:

- **New R&D milestone serialized** at `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/` (4 docs, 665 lines total, all Phase 0 deliverables landed before any code edits per documentation-first protocol):
  - `00-index.md` (141 LOC) — master nav, 9 Q-N FROZEN decisions table, REUSE-table with verification spot-checks, doc-conventions status, idempotency marker stamped
  - `01-design.md` (256 LOC pre-review, ~290 LOC post-review fixes) — full design: context, Q1-Q9 FROZEN, 8 phases (Phase 0/1/2/3/4/4.5/5/6) with EXECUTOR: AI/HUMAN tags, 19 ACs, risks, out-of-scope, REUSE pre-pass anchor
  - `02-handoff-summary.md` (110 LOC) — cross-sub-project handoff for Lupin mobile + multiplexer R&D teams (TL;DR / what changed / why / per-sub-project action / migration timeline / where to ask + 3-tier contact ladder)
  - `90-execution-log.md` (158 LOC pre-review, ~280 LOC post-review evidence) — phase status table, per-phase scaffolds, REUSE + Pass 1 + Pass 2 closure sections

- **`/plan-review` gate fully CLOSED 2026-05-11** — all 3 passes sequential per Q7, zero parallel dispatch:
  - **REUSE pre-pass**: 8 findings (4 reuse-as-is + 1 extend-existing + 3 genuinely-new). 3 fixes applied: elevated `.cc-retired-banner` CSS orphan cleanup to explicit Phase 1.8 + AC1.5; updated 00-index REUSE table with verbatim file:line spot-checks (notifications.js:2870-2949 research handler shape confirmed; notifications.html:272/319/381/441 sibling status divs confirmed; JobStore.ts:215 agent-agnostic confirmed; FastAPI 0.115.12 stacked-decorator support confirmed); added Risk row for `deprecated=True` repo novelty.
  - **Pass 1 Fitness**: 11 findings (0 Block / 4 Major / 7 Minor / 0 L3). 8/11 applied: M1 (Q8 verdict gate pinned to Phase 5.3) + all 7 Minors (function-name fossil note, literal mobile TODO entry shape, "one release cycle" tightened to v0.1.8+ trigger, WHO-to-contact 3-tier ladder, mobile TODO tag `[LUPIN-CC-SUBMIT-RENAME]` + section, backend coverage scope clarification, dropped `include_in_schema=False` so alias appears in OpenAPI as `deprecated: true`). M2/M3/M4 user-skipped.
  - **Pass 2 Adversarial**: 7 findings + 1 swept pattern offender (0 Block / 5 Major / 2 Minor / 0 L3). All 8 applied: A1 (AC11 visual baseline criteria falsifiable with pytest count + diff allow-list), A2 (AC5 "manual submit" → programmatic), A3 (Two-phase E2E gate `EXECUTOR: HUMAN` tag with same-line justification), A4 (Phase 6.8 `EXECUTOR: AI` + explicit 13-file allow-list), A5 (Phase 6.9 `EXECUTOR: HUMAN` for CoSA commit with nested-repo-boundary justification), a1 (mobile TODO placeholder vs literal clarification), a2 ("manual" metadata in Phase 6.1 + AC13 explained as legacy-item-name), plus swept the same "manual" pattern at Risks row 216 per `feedback_sweep_for_pattern_offenders`.

- **Idempotency marker stamped** in `00-index.md`: `last-reviewed-at: 2026-05-11 (commit c1cec74 — pre-implementation HEAD)`.

- **Zero Layer-3 Design Concerns** across all 3 passes. All 9 Q-N FROZEN decisions stand unchanged.

- **Plan file authored + serialized**: `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (drafted in plan-mode 2026-05-09/10, approved via ExitPlanMode 2026-05-10, serialized into this R&D folder).

- **New auto-memory filed**: `feedback_cross_project_handoff_doc.md` — when a change touches multiple sub-projects (mobile, multiplexer, plugin, CoSA, in-flight R&D), plan must include (1) one concise ~150-line handoff doc and (2) seed TODO entries in each affected sub-project. User-ratified 2026-05-10 during plan-mode walk.

- **Channel switch mid-pass to cosa-voice high-priority action-required UI**: at user request mid-Pass-1, all subsequent gates routed through `mcp__cosa-voice__ask_multiple_choice` with `priority="high"` instead of built-in `AskUserQuestion`, so each plan-review decision surfaces as action-required notification in the UI (user not switching between terminal and browser).

**Files**:
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` (NEW)
- `TODO.md` (modified — new "FIRST THING NEXT SESSION — CC Card Normalization Phase 1" section above Mr. Radio's parallel-session Phase 6b section; Last-updated line refreshed)
- `history.md` (this entry)
- 2 NEW auto-memory files (outside repo): `feedback_cross_project_handoff_doc.md`, MEMORY.md index updated
- 1 NEW plan file (outside repo): `~/.claude/plans/ok-so-far-so-swirling-pearl.md`

**Status**: Phase 1 implementation BLOCKED on next-session user go-ahead. Origin plan + R&D folder are self-contained — fresh-context session can pick up by reading the 4 R&D docs in order.

---

### 2026.05.11 - Session 017dc1cc | Multiplexer Phase 6b Pass 1 Fitness CLOSED — 14/14 ratified via action-required UI

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Pass 1 Fitness ratification walk completed end-to-end** — 14/14 findings ratified across 9 turns (1 Minors batch covering F-8/F-9/F-10/F-11/F-12/F-14 + 8 individual Major walks: F-1, F-2, F-3, F-4, F-5, F-6, F-7, F-13). All firings returned `yes`. Per-decision routing via cosa-voice `ask_yes_no` action-required UI per user directive ("push every decision point into the action-required UI" — much easier to parse than terminal-text gates).

- **All 14 resolutions applied** to `09-phase6b-interactive-widgets-design.md`. Net ~+220 LOC across 8 distinct edit clusters: Boot wiring (mount() is sync addendum, F-12); Inertness-lift contract rewritten as single-write template swap (F-7); new Q-B1 dispatch contract subsection (F-3); Q-B3 state machine extended with `expired_visual` + `responded_default` vertices + Q-B5 ratified text rewritten with local RAF timer + clock-skew handling (F-4); AC table row updates (AC2c MutationObserver assertion, AC2d unit-test contract, AC5/AC5b enumerations, AC7 post-6a baseline, AC10b ceiling 500→700, AC10e command fix); two new AC enumeration sub-tables totalling 34 enumerated cases (AC5 subtotal 21, AC5b subtotal 13); R7 risk row for state-change storm (F-13); Phase 0 prerequisites updated (#3 reword for target API shape, #6 reword for sub-step 4A/4B DOD, NEW #7 for `countdown_expires_at` payload field); new § "Phase 4 sub-step DOD" subsection with explicit DOD tables (8 rows for 4A, 11 rows for 4B) + `JobStore.delete` signature returning `{ restoreState: () => void }` closure.

- **Pass 1 closed subsection** appended to `95-phase6b-review-findings.md` (+~70 LOC): full 9-row ratification record table cross-referencing each finding ID to the resolution applied; doc-state delta summary; convergence re-grep note; updated cycle-state diagram.

- **Pass 2 Adversarial dispatch gated on user go-ahead** per user direction. No auto-progression. The `93-resume-here-phase6b-pass1-ratification.md` file is now historical (left in place as audit trail; can be removed in a future cleanup).

**Files** (parent-Lupin scope only):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (status header + 14 finding resolutions applied)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (NEW "Pass 1 Fitness — closed 2026-05-11" subsection)
- `TODO.md` (FIRST THING IN THE MORNING entry replaced with DONE entry + resolution checklist + historical pointer)
- `history.md` (this entry)
- `.claude-session.md` (registered session 017dc1cc + touched files)

**Phase 6b cycle state**:
- Q-decisions ✅ CLOSED 12/12 (2026-05-07)
- REUSE pre-pass ✅ CLOSED 28 RE + 5 L3 (2026-05-07)
- Pass 1 Fitness ✅ CLOSED 14/14 (2026-05-11)
- Pass 2 Adversarial ⏳ gated on user go-ahead
- Code-execution plan ⏳
- Implementation ⏳

**Commits**:
- session checkpoint pending (this commit)

**Caveats / Notes**:
- `history.md` still at CRITICAL token threshold from 2026-05-07 — archival deferred again to avoid interleaving with active parallel session activity (session `f9608a41` last touched 2026-05-11 working inter-session-commons docs). Will revisit when parallel session pipeline is idle.
- Two task-tool reminders fired during the apply-edits phase; both ignored per harness instructions (tasks #1-#9 already correctly tracked the ratification turns; task #10 in_progress through the entire apply phase).
- Parallel session `f9608a41` (inter-session-commons R&D, separate scope) has its own ongoing work — files cleanly isolated from this session's commit per `.claude-session.md` v2.0 selective staging.

---

### 2026.05.09–11 - Session f9608a41 | NEW INITIATIVE: Inter-Session Commons + User-Broadcast — Phase 0 + 1 (steps 3a+3b) landed

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Multi-day session spanning 2026.05.09 → 2026.05.10 → 2026.05.11.**

**Accomplishments**:

- **NEW initiative launched: Inter-Session Commons + User-Broadcast Channel**. AI-to-AI blackboard for Claude Code sessions + user→all broadcast surface with persona-aware directive parsing (e.g., "all sessions: /plan-session-end; @Mr. Radio: also push; @Maria: skip commit"). Reuses existing per-session voice-persona system + conv-mode listener-injection pattern + WebSocket fanout infra. Doc-set at `src/rnd/v0.1.7/2026.05.09-inter-session-commons/`.

- **Phase 0 CLOSED — 15 Q-decisions ratified** (Q1 free-form + reserved topic registry; Q1b full reserved set: broadcast-acks + presence + system-events; Q2 silent unless priority=high; Q3 defer file-locks to Phase 5; Q4 24h active + indefinite archive; Q5 free-text + `@PersonaName:` syntax; Q6 non-blocking + live aggregate; Q6b both sync + async with naming alignment to project's `_sync`/`_async` convention; Q7 manifest orthogonal; Q8 case-insensitive + punctuation-tolerant matcher + LLM-fallback stub; Q9 follow @all only when persona missing; Q10 confirm dialog; Q11 1/30s rate limit; Q12 JWT-only; Q13 reject empty body; Q14 200 with no-active-sessions status; Q15 markdown from day one). Three architectural principles captured: commons is INTRA-AI; user-as-witness not middleman; sync/async naming consistency.

- **Full plan-review pipeline (REUSE → Pass 1 Fitness → Pass 2 Adversarial) CLOSED**. REUSE: 12 findings (8 reuse-as-is, 3 extend-existing, 1 genuinely-new fcntl with documented justification — `session_bridge.py:1022-1026` no-fcntl is a NUANCED choice for idempotent read-modify-write JSON, NOT a project-wide policy; commons appropriately diverges for append-only non-idempotent posts). Pass 1: 20 fitness findings across all 8 deficiency types ratified + applied. Pass 2: 13 ownership-language findings + 5 design concerns (2 auto-resolved by Cluster A's AI-spawn-subprocess insight) ratified + applied. Plan APPROVED for code-write 2026-05-11.

- **Path correction during walks: storage at `<project_root>/io/commons/`** (was `commons/` at root; user caught it). `io/` already gitignored at `.gitignore:68` — no separate exclusion needed.

- **100% coverage mandate** ratified for commons (commons-only scope per C3; multiplexer-only memory unchanged). Coverage tooling: pytest-cov 7.1.0 + coverage 7.14.0 installed in cosa venv + added to `pyproject.toml` dev deps + `uv.lock` regenerated cleanly (only 2 deps added, 55 lines, torch/flash-attn lock UNTOUCHED) + Docker candidate image `lupin:1.0.0-pytest-cov` built (6ff1643d8796, 31.7GB) but **NOT promoted** per the no-auto-promote-tags feedback memory.

- **Phase 1 implementation steps 3a + 3b CLOSED with 100% coverage**:
  - `src/lupin_mcp/commons_persona_matcher.py` (91 LOC) + 12 unit tests + 100% coverage. Case-insensitive + punctuation/space-tolerant mechanical matcher with stable LLM-fallback hook (Phase 3 wires the actual call).
  - `src/lupin_mcp/commons_store.py` (332 LOC) + 36 unit tests + 100% coverage. CommonsStore class with `post()` / `read()` / `who()`, YAML frontmatter, inline JSON metadata, POSIX `fcntl.flock` for multi-writer safety.
  - **AC10b real-fcntl stress test PASSED**: 5 child processes × 100 posts each = exactly 500 entries in the topic file, zero corruption, all sessions represented. Empirically validates the F6 fcntl ratification.

- **Cross-repo follow-up filed** at `planning-is-prompting/TODO.md`: after Lupin lands the 5 commons MCP tools, audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog (Lupin CLAUDE.md, src/docs/, planning-is-prompting workflow docs, cosa-voice-notifications skill, etc.).

- **Phase 1 step 3 is a natural session boundary.** Steps 4-8 remain: archival daemon (step 4), 5 MCP tool registrations (step 5), INI keys (step 6), 2-session smoke (step 7), AC12+AC14 subprocess verifications (step 8). Resume pointer at `91-resume-here-phase1-step4.md`.

**Files** (parent-Lupin scope only; no CoSA edits per Phase 1 §4):

- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/01-design.md` (NEW + Phase 0 ratifications + §4.1.1 ask threading + §4.2 empty-match)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md` (NEW + REUSE §11 + Pass 1 + Pass 2 applied)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-execution-log.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/91-resume-here-phase1-step4.md` (NEW)
- `src/lupin_mcp/commons_persona_matcher.py` (NEW)
- `src/lupin_mcp/commons_store.py` (NEW)
- `src/tests/unit/commons/__init__.py` (NEW)
- `src/tests/unit/commons/test_commons_persona_matcher.py` (NEW)
- `src/tests/unit/commons/test_commons_store.py` (NEW)
- `pyproject.toml` (pytest-cov added to dev deps)
- `uv.lock` (regenerated)
- (Outside repo, planning-is-prompting) `TODO.md` (cross-repo follow-up filed)

**Commits**: none yet — held for explicit user authorization per the `feedback_never_auto_commit_push` memory.

**Docker**: `lupin:1.0.0-pytest-cov` candidate built; `lupin:1.0.0` working tag UNTOUCHED. User decides when/if to promote.

**Caveats / Notes**:
- Phase 1 plan is the deliverable from the plan-review pipeline; code-write is partial (steps 3a + 3b only).
- No `:8000` Phase 1 tests scheduled (none needed — AC10/AC10b/AC11 are all `:7999` AI-discretionary).
- Voice persona color confirmed as immutable per-allocation by user (parallel to Sam-voice fallback for missing voice data) — design coherence with the per-session-voice-personas immutability invariant.

---

### 2026.05.07 - Session e8228026 | Multiplexer Phase 6a final closure on :8000 + Phase 6b planning launched (Q-decisions + REUSE done; Pass 1 paused)

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Phase 6a fully CLOSED on both `:7999` and `:8000`** — AC11a baseline captured (job `ts-b786315c`, 13:59 EDT, PNG at `io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/`) + AC11b regression GREEN (job `ts-bd34af9b`, 1 passed in 5.6s, 14:48 EDT, `-k` filter honored: 398 deselected / 1 selected). Discovery: visual baselines are gitignored under `io/` (`.gitignore:68`), so the baseline lives host-only and bind-mounts into the test container; no commit needed for the PNG.

- **Two `/api/test-suite/submit` silent-drop traps caught + documented as durable memories**:
  - `test_types="e2e_ui"` → silently dropped to 0/0/0/0 (no HTTP error). Use `"e2e"`. Memory `feedback_test_types_e2e_not_e2e_ui.md`.
  - Pydantic field is `pytest_args` (NOT `args`). v2 silently ignores unknown fields → submit body's `"args"` was dropped → full 23-min sweep ran instead of `-k` filtered. Memory `feedback_test_suite_submit_field_pytest_args.md`. Both `TODO.md` AC11a/AC11b entries fixed at source so the next session doesn't re-hit either trap.

- **Phase 6b planning launched** — design doc `09-phase6b-interactive-widgets-design.md` (NEW, 289 LOC) at canonical R&D path. 12 Q-B decisions across 4 clusters (submit semantics, TTS chrome, delete-button, boot/CSS/scope) ratified via cosa-voice walkthrough. Q-B6 corrected mid-walk: per-notification corner buttons belong in 6b not 6c per slicing manifest line 46.

- **REUSE pre-pass closed** — 28 RE-rows (16 reuse-as-is / 9 extend-existing / 3 genuinely-new) + 5 Layer-3 concerns ratified via 4-batch cadence. **C-4 confirmed empirically**: `JobStore.delete(idHash)` does NOT exist (only `indexById.delete(id)` internal Map call at `JobStore.ts:292`). Phase 6b Phase 4 must split into sub-step 4A (extend JobStore + 100% c8 tests) + 4B (wire delete-button click handler). AC table grew: AC2d (JobStore.delete grep + tsc guard), AC5c (delete-button extension tests ≥6 cases), AC10e (cross-phase count-cascade regression).

- **Pass 1 Fitness dispatched** — clean-context Explore agent, 14 findings (0 Block / 9 Major / 5 Minor / 0 Layer 3). Ratification PAUSED at user break point. F-1 caught a real bug in my own doc work — AC10b said `tts-chrome.css ≤500` but Q-B12 ratified `≤700`. Resume via `93-resume-here-phase6b-pass1-ratification.md` (NEW, 109 LOC).

- **Phase 6b cycle state**: Q-decisions ✅ → REUSE ✅ → Pass 1 ⏸️ paused → Pass 2 ⏳ → code-execution plan ⏳ → implementation ⏳.

**Files** (parent-Lupin scope only):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (NEW, 289 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (NEW, 156 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/93-resume-here-phase6b-pass1-ratification.md` (NEW, 109 LOC)
- `TODO.md` (AC11a/AC11b field-name fixes + 2026.05.08 morning section)
- `history.md` (this entry)
- 2 NEW auto-memory files (outside repo): `feedback_test_types_e2e_not_e2e_ui.md`, `feedback_test_suite_submit_field_pytest_args.md`

**Commits**:
- `243267b` — Phase 6a AC11a/AC11b CLOSED: TODO.md test-suite submit field-name fixes
- `d70be64` — Phase 6b planning checkpoint: Q-decisions + REUSE closed; Pass 1 paused at break point
- session-end commit pending (this entry)

**Caveats / Notes**:
- `history.md` remains at CRITICAL token threshold (~22.4k). Archival deferred per user direction earlier this session because parallel session 6825e6af (María) had uncommitted edits at that time. Carried forward to 2026.05.08 morning section in `TODO.md`.
- Phase 0 prerequisites for Phase 6b implementation (verified at code-execution plan time): `DELETE /api/queue/<bucket>/<id>` exists ✅; `multiSelect` payload, `AudioStore.currentNotificationIdHash`, action-required mount surface, CoSA `multiplexer_config.py` commit, `JobStore.delete(idHash)` — all pending verification.
- Parallel session 6825e6af (María 🌸) committed her own work (`4d2579f`) mid-session; her files cleanly isolated from my commits per parallel-session-safety v2.0.

---

### 2026.05.07 - Session 6825e6af | Bug Fix Mode — Notification 503 cascade reconciliation

**Persona**: María 🌸 (warm, inquisitive female)

**Context**: User opened a bug-fix session and asked to claim "Notification 503 cascade for offline users in expediter flow" (currently In Progress with stale owner 45e6bf84 — that session closed 2026-05-05T23:25). User flagged: "I thought that we had fixed it already." First task is reconciling the bug-queue entry against actual prior fixes before deciding scope.

### Fixes

#### Reconciliation — "thought we fixed it already"

User's recollection was substantially right: session 45e6bf84 on 2026-05-05 (commit `24e4731` + checkpoint `621be65`) completed Phases 0-4a of a real root-cause fix. The May-1 bug-queue framing ("client doesn't set `response_default`, 4 fix options") was disproved on May-5 — quote from `01-design.md`: "The fix is in the test harness, not the expediter or the server." Real root cause was **silent proxy startup failure**; May-5 made `_start_proxy` raising-on-failure + made all 7 callers abort on failure. Phase 4b on `:8000` was prepared but never ran — a NEW bug surfaced ("`pytest --auto-proxy` is a no-op — `pre_run_hook` never fires under pytest discovery") and was filed Queued. The In Progress entry stayed open because the new bug blocked Phase 4b's pytest path.

User chose **Path B**: fix the new pytest bug FIRST, then run Phase 4b through the canonical pytest path. Both bug-queue entries close together on AC11.

#### Phase 5 — pytest fixture wiring (CODE + :7999 VERIFY DONE)

- **R&D doc**: appended Phase 5 section to `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` + `90-execution-log.md`. Documents why module-scoped (not session-scoped — different test files have different `PROXY_PROFILE`) and why we did NOT take the alternative of wiring through pytest entry points.
- **Code (parent repo only — no CoSA edits)**:
  - `src/tests/smoke/conftest.py` — new module-scoped autouse fixture `_auto_proxy_for_module` + registered `--proxy-debug` CLI option. Fixture introspects test module for `EmbeddedProxyMixin` subclass DEFINED in the module (filter `obj.__module__ == module.__name__` to skip imported parents like `InteractiveSmokeTest`), instantiates it, calls `_start_proxy(...)` with env-var creds, and `pytest.fail(..., pytrace=False)` on `RuntimeError` to prevent cascade. Cleanup via `_stop_proxy()` at module teardown.
  - `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — regression test for the fixture; asserts `"auto proxy"` session is registered in `/api/debug/websocket-state` with a non-empty user mapping. Marker class `AutoProxyFixtureProbe(EmbeddedProxyMixin)` drives the fixture (profile=`deep_research`).
- **Class introspection sanity** across all 6 affected test modules picked the right concrete subclass: `ProxyIntegrationTest`/`proxy_integration_test`, `ExpeditorSmokeTest`/`expeditor_smoke`, `SweTeamProxySmokeTest`/`swe_team`, `PresentationLiveSmokeTest`/`presentation_gates`, `ResearchToPresentationLiveSmokeTest`/`research_to_presentation_gates`, `PresentationRenderOnlySmokeTest`/`presentation_gates`.
- **AC9 happy-path on `:7999`**: `pytest src/tests/smoke/test_auto_proxy_fixture.py --auto-proxy -v -s` → **1 passed in 2.19s**. Proxy registered as UUID `50c73ba7-36dd-4eaf-a7e2-63256252c84f` (matches the test-user UUID quoted in May-5 design doc).
- **AC10 sad-path on `:7999`**: same command with `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=wrong-password` → **1 error in 32.33s**, `ERROR at setup of test_fixture_started_proxy`. Test body never executed (cascade prevention contract honored). pytest reported as setup ERROR not assertion FAILED — correct distinction.

#### Phase 3 — `:8000` Phase 4b scheduling (DONE)

User authorized immediate slot. First submission `ts-f04eed7f` failed at startup (exit=4) because `pytest_args = "-k 'expr1 or expr2 or expr3'"` got `.split()` on whitespace — pytest received `'expr1`, `or`, `expr2'`, etc. as positional args and crashed with `ERROR: file or directory not found: or`. Resubmitted as `ts-e6bb533b` using 55 `--ignore=src/tests/smoke/<file>.py` tokens to narrow the smoke run to 4 keepers (`test_proxy_integration`, `test_expeditor_mock_job_smoke`, `test_swe_team_proxy`, `test_auto_proxy_fixture`). `--auto-proxy --cost-cap-usd 5.00` auto-injected via INI key (Cluster B from 2026-04-30 post-mortem) — confirmed in the running pytest argv.

Pre-flight: `preflight-test-container.sh` PASSED (all probes green). Direct container inspection confirmed bind-mount visibility: container saw the new fixture (`grep _auto_proxy_for_module conftest.py = 3 matches`) and the new test file (`test_auto_proxy_fixture.py` with today's mtime). No bounce required. `:8000` pool clean before submit (0 inflight, 0 pending).

#### Phase 4b — :8000 cascade-elimination (DONE — AC11 GREEN)

- **Job**: `ts-e6bb533b::50c73ba7-...`
- **Started**: 2026-05-07T15:23:40 EDT
- **Completed**: 2026-05-07T16:11:10 EDT
- **Duration**: 47:27 (2847.86s)

| Test | Result | Duration | Notes |
|------|--------|----------|-------|
| `test_auto_proxy_fixture::test_fixture_started_proxy` | ✅ PASS | <1s | Fixture regression test green |
| `test_expeditor_mock_job_smoke::test_expeditor_mock_job_smoke` | ✅ PASS | 1620.93s (27 min) | All scenarios green |
| `test_swe_team_proxy::test_swe_team_proxy` | ✅ PASS | 383.92s (6.4 min) | All scenarios green |
| `test_proxy_integration::test_proxy_integration` | ❌ FAIL | ~13 min | 14/15 scenarios pass; **scenario 15 EXP_RTPRES_MISSING failed for an UNRELATED REASON** — voice-routing classifier mis-routes "research something and present it" → `deep_research` instead of `research_to_presentation` |

**AC11 verification — zero `http_error_503`**:

| Source | Count |
|--------|-------|
| Run log `/tmp/smoke-20260507-201109.log` | grep `http_error_503` / `HTTP 503` / `User cancelled` / `503 Service` → **0 hits** |
| `lupin-rest-test` container logs (last 50 min) | grep `503` → 5 false positives, ALL source-port substrings (`127.0.0.1:45030`, `:45032`, etc.); zero actual HTTP 503 responses |
| Proxy subprocess stats (final) | `Notifications Received=90, Responses Sent=19, Script Matcher Used=17, LLM Used=2, Skipped=71, Errors=0` |

**Cascade is eliminated.** Both bug-queue entries close.

**Per-module fixture evidence** captured mid-run:
```
python3 -m pytest src/tests/smoke/ -v --ignore=... --auto-proxy --cost-cap-usd 5.00
└── python3 -m cosa.agents.notification_proxy --profile expeditor_smoke ...
```
The `--profile expeditor_smoke` matches `ExpeditorSmokeTest.PROXY_PROFILE` for that module — proof that `_auto_proxy_for_module` correctly introspects the test class and starts the right proxy per module.

#### Bug-queue updates

- ✅ "Notification 503 cascade for offline users in expediter flow" → **CLOSED** (resolved 2026-05-07 by 6825e6af; annotated In Progress entry with full closure evidence + folded into details)
- ✅ "`pytest --auto-proxy` is a no-op — `pre_run_hook` never fires under pytest discovery" → **CLOSED** (resolved 2026-05-07 by 6825e6af; annotated Queued entry with closure evidence)
- 🆕 **NEW Queued entry filed** (per TEST OWNERSHIP MANDATE): "Voice-routing classifier mis-routes 'research something and present it' → deep_research instead of research_to_presentation" — surfaced during Phase 4b run, NOT a regression of the cascade fix.

### Session Summary

**Outcome**: Two bug-queue entries closed in one session, one new bug filed.

- **Notification 503 cascade for offline users in expediter flow** — RESOLVED. May-5 (45e6bf84) landed Phases 0-4a (test-harness raise-on-failure + 7-caller abort). May-7 (6825e6af) landed Phase 5 (module-scoped pytest fixture closing the pre_run_hook gap). Phase 4b on `:8000` (job `ts-e6bb533b`, 47:27 runtime) verified zero `http_error_503` / 0 proxy errors / 90 notifications received / 19 responses sent.
- **`pytest --auto-proxy` is a no-op** — RESOLVED in same closure. Module-scoped autouse fixture in `src/tests/smoke/conftest.py` introspects test module for the concrete `EmbeddedProxyMixin` subclass (filter `obj.__module__ == module.__name__` to skip imported parents), instantiates it, calls `_start_proxy(...)` with env-var creds, `pytest.fail(..., pytrace=False)` on `RuntimeError`. Cleanup via `_stop_proxy()` at module teardown.
- **Voice-routing classifier mis-route** (NEW) — Queued for future session; pre-existing classifier issue surfaced only because the new pytest-path coverage now exercises Scenario 15 properly.

**Files modified (parent Lupin repo only — no CoSA edits)**:
- `bug-fix-queue.md` — Active Sessions row added; "503 cascade" In Progress entry closed; "pytest --auto-proxy no-op" Queued entry closed; new "voice-routing classifier" Queued entry filed
- `history.md` — this entry
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` — Phase 5 section appended
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` — Phase 5 status + Phase 4b evidence
- `src/tests/smoke/conftest.py` — fixture + `--proxy-debug` option
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — fixture regression test

**Status**: All work complete. Awaiting user `commit` authorization. No commits made automatically.

#### Checkpoint | 2026.05.07 20:15 | 503 cascade fix (Phase 5) + Phase 4b verification + bug-queue closures

**Files** (6 in Lupin parent + manifest):
- `src/tests/smoke/conftest.py` (modified — fixture)
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` (Phase 5 section)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` (Phase 5 + Phase 4b evidence)
- `bug-fix-queue.md` (closures + new Queued entry)
- `history.md` (session entry — this file)
- `.claude-session.md` (manifest section for 6825e6af)

**Commit**: 4d2579f

#### Checkpoint | 2026.05.07 23:00 | Bounded ClaudeCodeJob redesign — plan approved + serialized + REUSE closed + Pass 1 partial (4/11)

**Topic shift mid-session**: After bug-fix work landed at `4d2579f`, user pivoted to a proactive redesign of the BOUNDED `ClaudeCodeJob` to bring it to canonical agentic-job shape. Sequence:

1. **Investigation** — surveyed retired `/api/claude-code/dispatch` cluster (closed 2026-05-05 by `73bee1b`); audited current `src/cosa/agents/claude_code/` (4 of 8 canonical files; missing `config.py`/`state.py`/`orchestrator.py`/`__main__.py`); gold-reference is `src/cosa/agents/deep_research/`.
2. **Plan mode** — drafted at `~/.claude/plans/so-it-looks-like-silly-map.md`; user revised twice (rejected facade-wrap in favor of relocation of `cosa/orchestration/claude_code/` → `cosa/agents/claude_code/`; added cross-agent regression contract after flagging TFE/BFE possible dependency, which Explore agents verified is zero-deps today). Approved via ExitPlanMode.
3. **Serialization** — Phase 0 docs landed at `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/{01-design.md,90-execution-log.md}`.
4. **Plan-review install** — `/plan-install-wizard` (mode=install) added `/plan-review` slash command to `.claude/commands/plan-review.md` with Lupin-specific customization (project=Lupin, prefix=[LUPIN], `:7999`/`:8000` venue notes, CoSA git boundary callout, auto-memory feedback-loop callout).
5. **Convention amendment** (pre-flight to plan-review): created `00-index.md` (master nav + idempotency marker home + Prior art referenced section + Open follow-ups) and `00-working-contract.md` (Layer 2 anchor — test-layer enumeration, user-involvement gate, cannot-execute rule, phase-complete definition). Reformatted `01-design.md` decisions as `Q1`/`Q2`/`Q3 FROZEN 2026-05-07` with Question/✅ Decision/Rationale/Implication structure. Added 42 `EXECUTOR: AI / HUMAN <reason>` tags throughout Phase 6 + Phase 7 + Verification section. All 5 conventions satisfied (Convention 5 false-positive Manual hits skip-logged in `00-index.md`).
6. **REUSE pre-pass (§4)** — single Explore agent grep against `src/cosa/` + `src/fastapi_app/` + `src/tests/`. 18 findings; 4 user decisions via `AskUserQuestion`: F#3 reframe `ClaudeCodeRunResult` as rename-from-`TaskResult`, F#8 INI namespace `claude code bounded job *` (anticipates future `claude code interactive job *`), F#18 `Task`/`TaskType` to `state.py`, applied F#4 + SDK_AVAILABLE re-export + #16 deferral. Convergence ✓.
7. **Pass 1 Fitness (§5)** — single Explore agent. 11 findings + zero TBDs + zero Layer-3 Design Concerns. **STRUCTURAL batch (4/4) closed via single-finding `ask_yes_no` ratification** with conversation-mode voice gates: F1 atomic-rename approach (no shim — user surfaced the overengineering), F4 canonical "all args on `__init__` + parameterless run methods + job-level routing" matching Podcast `do_all_async`/`do_review_only_async`/`do_audio_only_async` pattern (user's qualifier "how does this affect bounded vs interactive dispatch?" surfaced the cleanest answer), F8 `stream_thoughts_to_voice` removed (vestigial copy-paste), F10 baseline timing re-targeted "BEFORE Phase 1" (Phase 2a relocation could leak into siblings).
8. **Pass 1 SUSPENDED at 7 remaining findings** (4 implementation-completeness + 3 operational). Resume with `/plan-review --from=fitness`. Detail in `90-execution-log.md` § "Pass 1 — Fitness — ⏸️ PARTIALLY CLOSED 2026-05-07; SUSPENDED at 4/11 findings applied".
9. **Filed**: TODO entry for `cosa-voice ask_yes_no()` to grow a "Neither" / "Discuss further" button — surfaced because the user wanted to qualify a yes mid-flight ("yes BUT how does this differ from existing patterns?") and the only tool today is comment-text on the chosen answer.

**Files** (this checkpoint, all Lupin parent — no CoSA edits):
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-working-contract.md` (NEW)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/01-design.md` (NEW; serialized + heavily restructured during plan-review amendments + REUSE/Pass-1 fixes)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/90-execution-log.md` (NEW; phase status table + REUSE closure + Pass 1 partial breadcrumbs)
- `.claude/commands/plan-review.md` (NEW; installed via `/plan-install-wizard`)
- `TODO.md` (modified — neither-button feature request appended to Pending section)
- `.claude-session.md` (manifest section — touched-files entries added)
- `history.md` (this file — this checkpoint)

**Commit**: c1cec74

---

