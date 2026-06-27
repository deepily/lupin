# Submit Agentic Jobs — Build Plan (accordion #2, TRULY ABSENT → build · HEAVIEST)

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 DRAFT for the cascaded review (run on Rick's dev server).
**Author**: research/planning pass (absent-accordion lane — heaviest of the corpus).
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#2 Submit Agentic Jobs" (lines 85-89) + master verdict row 2 (line 22).
**Decision-of-record refs**: doc `04` §Resolved ruling **(g)** — "Port ALL 7 absent accordions → total 13/13 parity … No 'obsolete' drops — strict total parity." This plan executes (g) for #2.
**Inherits** all 7 cross-cutting mandates from `00-plans-index.md §"Cross-cutting mandates"` — not restated here.
**Shares with #1 (Q&A, plan `05-`)**: the STT (`recordingManager`) + authed-fetch (`ApiClient`) seams. Plan `05-` §9 explicitly names this plan as the heavier follow-on that reuses those patterns. Build #1 FIRST as the warm-up.

---

## 1. Goal & parity target

Restore the legacy **📝 Submit Agentic Jobs** accordion in the multiplexer: a `#job-submit-pane` section
(wired into the section-toolbar as a toggle) holding **7 job-submit cards** — Claude Code, Research,
Podcast, SWE Team, Presentation, Test Suite, and TFE-Resume — each a collapsible `.job-submit-card`
reproducing the legacy DOM contract / styling of `notifications.html:146-560` (~415 lines). "Done" = every
card collapses/expands, accepts its inputs (incl. STT mic where legacy has one, schedule-for-later +
monopolize where legacy has them), validates, and POSTs the **identical body** to the **identical
pre-existing endpoint** as the legacy handler, surfacing the queue-ack into a per-card status line.
Submitted jobs appear in the existing mux `jobs-pane` via the WS `job_state_transition` stream (no manual
refresh — the legacy `refreshAllQueues()` call becomes a no-op).

## 2. Scope

The ratified ruling this executes: **(g)** total 13/13 parity — no obsolete drops.

**IN**

- New `#job-submit-pane` `<section>` in `multiplexer.html` (mux idiom: own `<header><h2>`, collapse
  delegated to the section-toolbar — mirrors fleet-status/jobs panes, NOT the legacy header-click ▼).
  Inside: 7 mount divs (one per card) the per-card renderers fill, in legacy order.
- **7 new pure-DOM card templates** (`render/templates/*SubmitCard.ts`), each modeled VERBATIM on the
  existing `templates/broadcastCard.ts` (which already reuses the `.job-submit-card` / `.job-submit-card-header`
  / `.section-content` CSS contract and the `html\`…\`` `DocumentFragment` idiom, no `.innerHTML`). Legacy
  ids + `data-testid`s string-equal where the shared CSS/e2e keys on them.
- **7 new card renderers** (`render/*SubmitCardRenderer.ts`), each modeled on `BroadcastCardRenderer.ts`:
  mount-into-root, throw-on-double-mount, `unmount()` idempotent, delegated clicks (NO inline `onclick` —
  mux no-globals rule), collapse-toggle on `data-card-open`, STT wiring (the 5 cards that have a mic),
  validation, submit via the shared helper.
- **Shared submit helper** (`render/submit/submitCardCommon.ts`) — the one piece every card lane consumes
  (§9 L0): `runSubmit({...})` (validation guard → disable button + show spinner → status text/color → POST →
  ack/err render → finally re-enable), `getSchedulingParams(prefix)` (1:1 port of `notifications.js:6089`
  `_getSchedulingParams` → `{ scheduled_at?, monopolize? }`), and `wireStt(sttBtn, inputEl, contextId,
  recording, authToken)` (the `recordingManager.startRecording({ contextId, onComplete })` idiom shared
  with Q&A). Plus a **shared schedule/monopolize control template** (`render/submit/scheduleControls.ts`)
  emitting the legacy `.schedule-section` fragment, parameterized `monopolize: true|false` (Test-Suite passes
  `false` → renders the static "🔒 Exclusive mode (always on)" label instead of a checkbox).
- **7 typed submit methods + Request/Result interfaces** on `api/ApiClient.ts` (mirroring the existing
  `broadcastToCcSessions(req): Promise<BroadcastResult>`): `submitClaudeCode`, `submitDeepResearch` (with the
  3-way variant routing), `submitPodcast`, `submitSweTeam`, `submitPresentation`, `submitTestSuite`,
  `resumeTfe`. Each wraps the existing `post<T>()` seam (Authorization + `X-Session-ID` already handled
  there) so token-refresh/abort behavior stays consistent — no hand-rolled `fetch` in any card.
- **`SubmitCardsStore`** (`stores/SubmitCardsStore.ts`) — minimal per-card **open-state** persistence
  (StorageService-backed, keyed by card id) so each card remembers collapsed/expanded across reload, mirroring
  `BroadcastStore`'s `cardOpen` bit. Emits `store_submit_cards_changed`. (No business data — the cards are
  fire-and-forget; the jobs themselves live in `JobStore`.)
- **1 new event literal** `store_submit_cards_changed` in `shared/types.ts` + payload interface.
- **1 `SECTION_TOGGLES` entry** (`sectionId: "job-submit-pane"`, icon 📝) in `templates/sectionToolbar.ts`.
- **Shared CSS lift** of the job-submit rules (`.job-submit-card`, `.job-submit-card-header`,
  `.schedule-section`, `.stt-button`, `.toggle-button`, `.loading`/`.spinner`, the per-card submit-button
  colors) from `css/notifications.css` into `css/shared/notifications-surface.css` (mandate 3 single-source).
  The broadcast card already depends on `.job-submit-card` from the shared sheet — this lift makes that
  dependency complete and explicit; the legacy heavy inline `style=""` on these nodes is normalized into the
  shared sheet during the lift.
- Boot wiring (`boot.ts`): construct `SubmitCardsStore` + `.hydrate()`, construct the 7 card renderers,
  resolve the 7 mount divs, `.mount()` each; add 7 `boot_complete` handler entries + console lines.
- **Per-card behavioral fidelity** (the exact legacy payloads/endpoints — §3, §5):
  - **Claude Code** → `POST /api/claude-code/submit` — `{ prompt, project, task_type, max_turns:
    INTERACTIVE?200:50, websocket_id, dry_run, …scheduling }`.
  - **Research** → endpoint **switch** (`/api/deep-research/submit` | `…-to-presentation/submit` |
    `…-to-podcast/submit`) — `{ query, budget, dry_run, …scheduling }` (+`target_languages:['en','es-MX']`
    podcast, +`target_duration_minutes:15` presentation).
  - **Podcast** → `POST /api/podcast-generator/submit` — `{ research_source, target_languages:['en','es-MX'],
    dry_run, …scheduling }`; smart-input response handling (`queued`/`matching`/`no_matches`).
  - **SWE Team** → `POST /api/swe-team/submit` — `{ task, dry_run, websocket_id }` +optional `budget`,
    `timeout`, `trust_mode` + scheduling.
  - **Presentation** → `POST /api/presentation-generator/submit` — `{ source_path, audience,
    target_duration_minutes, dry_run, …scheduling }`.
  - **Test Suite** → `POST /api/test-suite/submit` — `{ test_types, dry_run, pytest_args?,
    auto_fix_on_failure?, scheduled_at? }` (NO `monopolize` — always exclusive); conditional file-path +
    fail-fast fields; combined-args logic; `FILE_DRIVEN_TEST_TYPES = {smoke_direct, pytest_direct}`.
  - **TFE Resume** → `POST /api/test-fix-expediter/resume-from` — `{ resume_from }`; `resumed` vs `ambiguous`
    (disambiguation candidate list, delegated-click re-submit) handling.

**OUT**

- NO new backend / endpoint / INI work — **all 7 endpoints already exist and are verified** (§3). This is a
  pure front-end port of the submit UI + dispatch.
- NO change to the legacy `notifications.js`/`.html` submit behavior or endpoints (only the CSS lift touches a
  legacy file, and only to point it at the shared sheet — behavior-neutral).
- NO progressive job-progress UI inside the cards — submitted jobs surface in the existing `jobs-pane`
  (`JobStore` ← WS `job_state_transition`). The legacy `refreshAllQueues()` after CC submit is intentionally
  dropped (the mux is already live-driven).
- NO `INTERACTIVE` Claude Code path — the legacy `<option value="INTERACTIVE" disabled>` stays disabled
  (verbatim parity; it returns "when `ClaudeCodeJob.inject/interrupt/end_session` ship", per the legacy title).
- NO STT on the Test-Suite or TFE-Resume cards (legacy has none on those two — §3); NO schedule/monopolize on
  TFE-Resume (legacy has none).
- NO Re-render (`submitRerender`) button — that is a control on **completed presentation job cards** in the
  jobs surface (`notifications.js:3417`), not part of the submit accordion. Out of this plan (belongs to the
  jobs-pane #9 work if ported).

## 3. Source anchors

**Legacy (reference behavior — do NOT edit; `html/notifications.html` + `js/notifications.js`):**

- **Container**: `notifications.html:146-160` — `#section-job-submit` `.collapsible-section` →
  `#job-submit-section` `.section-content`.
- **Card 1 — Claude Code** `notifications.html:154-216` (`#claude-code-submit-card`, testid
  `notifications-cc-card`): `#cc-project` select (lupin/cosa/plan), `#cc-stt-button` + `#cc-prompt` textarea,
  `#cc-task-type` (BOUNDED selected / INTERACTIVE **disabled**), `#cc-dry-run` (checked), `#cc-submit` +
  `#cc-loading.spinner`, `#cc-submit-status`, `.schedule-section` (`#cc-schedule` + `#cc-scheduled-time` +
  `#cc-monopolize`). Handler `submitClaudeCode` (`notifications.js:4047`) → `submitClaudeCodeToQueue`
  (`:4057`) → `POST /api/claude-code/submit` (`:4085`); body at `:4090-4099`; wiring `:1771,1776,1793`.
- **Card 2 — Research** `notifications.html:219-272` (`#research-submit-card`): `#research-stt-button` +
  `#research-topic`, `#research-budget` (3.00/0.50–20.00), `#research-with-podcast`,
  `#research-with-presentation`, `#research-dry-run` (checked), `.schedule-section` (`#research-schedule` /
  `-scheduled-time` / `-monopolize`), `#submit-research-job` + `#research-loading`, `#research-submit-status`.
  Handler `submitResearchJob` (`notifications.js:3069`); endpoint switch `:3102-3106`; body `:3109-3115`;
  STT wiring `:2025`.
- **Card 3 — Podcast** `notifications.html:275-319` (`#podcast-submit-card`): `#podcast-stt-button` +
  `#podcast-source`, `#podcast-dry-run` (checked), `.schedule-section`, `#submit-podcast-job` +
  `#podcast-loading`, `#podcast-submit-status`. Handler `submitPodcastJob` (`notifications.js:3162`);
  `POST /api/podcast-generator/submit` (`:3190`); body `:3199-3203`; smart-input branch `:3213-3227`; STT
  wiring `:2033`.
- **Card 4 — SWE Team** `notifications.html:322-381` (`#swe-team-submit-card`): `#swe-stt-button` +
  `#swe-task` textarea, `#swe-budget` (nullable), `#swe-timeout` (nullable), `#swe-dry-run` (checked),
  `#swe-trust-mode` (''/disabled/shadow/suggest selected/active), `.schedule-section`, `#submit-swe-job` +
  `#swe-loading`, `#swe-submit-status`. Handler `submitSweTeamJob` (`notifications.js:3245`);
  `POST /api/swe-team/submit` (`:3300`); body `:3276-3298`; STT wiring `:2071`.
- **Card 5 — Presentation** `notifications.html:384-441` (`#presentation-submit-card`, testid
  `notifications-presentation-card`): `#presentation-stt-button` + `#presentation-source`,
  `#presentation-audience` (general/beginner/expert/academic), `#presentation-duration` (15/5–60),
  `#presentation-dry-run` (checked), `.schedule-section`, `#submit-presentation-job` +
  `#presentation-loading`, `#presentation-submit-status`. Handler `submitPresentationJob`
  (`notifications.js:3339`); `POST /api/presentation-generator/submit` (`:3371`); body `:3378-3383`; STT
  wiring `:2098`.
- **Card 6 — Test Suite** `notifications.html:444-530` (`#test-suite-submit-card`, testid
  `notifications-test-suite-card`): `#test-suite-types` select with optgroups (Aggregate / Individual /
  Combined / Agentic Regression) + inline `onchange="onTestSuiteTypeChange(this.value)"`, conditional
  `#test-suite-file-path-row` (smoke_direct/pytest_direct), conditional `#test-suite-fail-fast-row` (`all`),
  `#test-suite-pytest-args`, **inline `<script>`** defining `FILE_DRIVEN_TEST_TYPES_HTML` + `onTestSuiteTypeChange`
  (`:488-501`), `#test-suite-dry-run` (checked), `#test-suite-auto-fix`, `.schedule-section` with
  `#test-suite-schedule` + `#test-suite-scheduled-time` + **static "🔒 Exclusive mode (always on)"** (NO
  monopolize checkbox), `#submit-test-suite-job` + `#test-suite-loading`, `#test-suite-submit-status`.
  Handler `submitTestSuiteJob` (`notifications.js:3463`); combined-args logic `:3489-3498`; body
  `:3512-3531`; `POST /api/test-suite/submit` (`:3533`); `FILE_DRIVEN_TEST_TYPES` set `notifications.js:12`
  (kept in sync 3 places: `.js:12`, `.html:492`, `cosa/agents/test_suite/job.py`).
- **Card 7 — TFE Resume** `notifications.html:533-557` (`#tfe-resume-submit-card`, testid
  `notifications-tfe-resume-card`): NOTE different inner markup (`.job-submit-header`/`.job-submit-body`, NOT
  the collapsible `.job-submit-card-header`/`.section-content` of the other 6 — it is **always expanded**, no
  toggle), `#tfe-resume-input` textarea, `#submit-tfe-resume-job` + `#tfe-resume-loading`,
  `#tfe-resume-submit-status`, `#tfe-resume-candidates`. Handler `submitTFEResume` (`notifications.js:7954`);
  `POST /api/test-fix-expediter/resume-from` (`:7977`); `ambiguous` → `_renderTFEResumeCandidates` (`:8021`,
  legacy uses inline `onclick` → **mux must delegate**); `resumed` branch `:8002`; pick-candidate
  `_pickTFEResumeCandidate` (`:8052`); wiring `notifications.js:2137`.
- **Scheduling helper** `notifications.js:6089-6101` — `_getSchedulingParams(prefix)`:
  `{ scheduled_at: ISO }` if `${prefix}-schedule` checked + `${prefix}-scheduled-time` set; `{ monopolize:
  true }` if `${prefix}-monopolize` checked.
- **STT pattern** (legacy) `notifications.js:3612-3677` — `recordingManager.startRecording(contextId,
  button, inputElement, options)`; the mux replaces this with the singleton `recordingManager.startRecording({
  contextId, onComplete })` (see §4).
- `css/notifications.css` — the job-submit rules to lift (grep `.job-submit-card`, `.job-submit-card-header`,
  `.schedule-section`, `.stt-button`, `.toggle-button`, `.loading`, `.spinner`; exact span confirmed at lift,
  mandate 3).

**Endpoints — ALL VERIFIED PRESENT (grep of `src/cosa/rest/routers/`):**

| Card | Method/Path | Router anchor |
|---|---|---|
| Claude Code | `POST /api/claude-code/submit` | `claude_code_queue.py:91` (`scheduled_at` field `:49`) |
| Research | `POST /api/deep-research/submit` | `deep_research.py:80` |
| Research→Podcast | `POST /api/deep-research-to-podcast/submit` | `deep_research_to_podcast.py:81` |
| Research→Presentation | `POST /api/deep-research-to-presentation/submit` | `deep_research_to_presentation.py:84` |
| Podcast | `POST /api/podcast-generator/submit` | `podcast_generator.py:453` |
| SWE Team | `POST /api/swe-team/submit` | `swe_team.py:67` |
| Presentation | `POST /api/presentation-generator/submit` | `presentation_generator.py:117` |
| Test Suite | `POST /api/test-suite/submit` | `test_suite.py:70` |
| TFE Resume | `POST /api/test-fix-expediter/resume-from` | `queues.py:1818` |

**Mux targets (add / edit):**

- ADD `js/multiplexer/render/templates/{cc,research,podcast,sweTeam,presentation,testSuite,tfeResume}SubmitCard.ts` (7 new).
- ADD `js/multiplexer/render/{Cc,Research,Podcast,SweTeam,Presentation,TestSuite,TfeResume}SubmitCardRenderer.ts` (7 new).
- ADD `js/multiplexer/render/submit/submitCardCommon.ts` + `render/submit/scheduleControls.ts` (shared; the §9 L0 lane).
- ADD `js/multiplexer/stores/SubmitCardsStore.ts` (new) — export from `stores/index.ts`.
- EDIT `js/multiplexer/api/ApiClient.ts` — +7 typed submit methods + Request/Result interfaces.
- EDIT `js/multiplexer/shared/types.ts` (`LupinEventType` union) — append `| "store_submit_cards_changed"` + payload iface.
- EDIT `js/multiplexer/render/templates/sectionToolbar.ts` (`SECTION_TOGGLES` ~35-42) — +1 entry.
- EDIT `js/multiplexer/boot.ts` (NEW-LANE MOUNT SLOT) — store hydrate + 7 renderer mounts + handlers/console lines.
- EDIT `js/multiplexer/render/index.ts` + `stores/index.ts` — barrel exports for the new factories.
- EDIT `html/multiplexer.html` — add `<section id="job-submit-pane">` + 7 mount divs; verify `<head>` shared-sheet link.
- EDIT `css/shared/notifications-surface.css` — lifted job-submit rules.
- VERIFY `html/notifications.html` `<head>` links the shared sheet BEFORE `notifications.css` (mandate 3).

**Mux non-source (confirms ABSENT):** grep across `js/multiplexer/**` — the only hit for `.job-submit-card`
is `templates/broadcastCard.ts` (the CSS-class reuse noted in doc 04:88); NO dispatcher, no `submit-*`
handler, no `#*-submit-card` mount, no per-card store/renderer exists. `jobs-pane` **displays** jobs but
offers **no submit path** (doc 04:22,88).

## 4. Dependencies & prerequisites

- **`recordingManager` (STT) — already present, no prereq** (same seam Q&A plan `05-` uses). Singleton
  `audio/recordingManager.ts`: `startRecording({ contextId, authToken?, onComplete:(text,blob)=>…, onError,
  onRecordingStart, onCancel })`, plus `insertTranscriptionText` for caret-aware fills. The 5 STT cards
  (cc/research/podcast/swe/presentation) each get a distinct `contextId` (`"cc-prompt"`, `"research-topic"`,
  …) — the single-active-recording invariant auto-cancels a prior card's recording when a new one starts.
- **`ApiClient` authed-fetch seam — already present, no prereq.** `api/ApiClient.ts` exposes `post<T>(path,
  body, opts)` with Authorization + `X-Session-ID` + `AbortSignal.any` timeout (the same path
  `broadcastToCcSessions` rides). All 7 card POSTs route through new typed methods on it. The bearer comes
  from `StorageService.getAccessToken()`; the `websocket_id`/session id (CC + SWE bodies) is the mux
  queue-session id (the same value boot resolves via StorageService, DC2).
- **All 9 endpoints exist** (§3 table) — zero backend work, zero new INI keys.
- **`JobStore` already live-renders submitted jobs** (`stores/JobStore.ts` ← WS `job_state_transition`) — so
  the legacy post-submit `refreshAllQueues()` has no mux equivalent and is dropped, not ported.
- **Carves inherited**: none. **Cross-plan order**: per ruling (g), build **after** CC-session (`03-`) + the
  3 partials, and **after** Q&A (`05-`) so the STT/authed-fetch helpers are proven on the lighter card first.
- **`FILE_DRIVEN_TEST_TYPES` single-source** (Test-Suite card): the mux must define this set ONCE
  (`render/submit/submitCardCommon.ts` or the test-suite template) and the plan adds a 4th sync site to the
  existing 3 (`.js:12`, `.html:492`, `job.py`). Flag for the reviewer (§8 Q4): a drift-prone constant.

## 5. Work breakdown

Buckets map 1:1 onto the §9 lanes. **L0 (shared) lands first** — every card lane depends on it.

### Task 0 — shared submit primitives (L0; blocks all card lanes)
- **What**: `render/submit/submitCardCommon.ts`:
  - `getSchedulingParams(prefix): { scheduled_at?: string; monopolize?: true }` — 1:1 port of
    `notifications.js:6089` (reads `${prefix}-schedule`/`-scheduled-time`/`-monopolize`).
  - `runSubmit({ button, spinner, statusEl, validate, post, onSuccess, onError? })` — encapsulates the legacy
    every-handler boilerplate: `validate()` guard (sets ⚠️ status, returns early), disable button + show
    spinner + "Submitting…" status, `await post()`, on ok `onSuccess(result)` (default: ✓ status with
    `job_id`/`queue_position`), on throw red `✗ Error: …` status (or `onError`), `finally` re-enable + hide
    spinner. Mirrors the shared shape across `submitClaudeCodeToQueue`/`submitResearchJob`/etc.
  - `wireStt(sttBtn, inputEl, contextId, recording, getAuthToken)` — `recording.startRecording({ contextId,
    authToken, onComplete:(text)=>insertTranscriptionText(inputEl,text), onError, onRecordingStart, onCancel })`
    with mic-button idle/recording state flips (shared with Q&A's pattern).
  - `FILE_DRIVEN_TEST_TYPES = new Set(['smoke_direct','pytest_direct'])` (4th sync site — §4).
  - `render/submit/scheduleControls.ts` — `renderScheduleControls(prefix, { monopolize: boolean })` returning
    the legacy `.schedule-section` fragment (schedule checkbox + `datetime-local` + monopolize checkbox), or
    with `monopolize:false` the static "🔒 Exclusive mode (always on)" span (Test-Suite). The schedule
    checkbox `change` shows/hides the datetime field via a **delegated** handler in the card renderer (NOT the
    legacy inline `onchange`).
- **Files**: `render/submit/submitCardCommon.ts`, `render/submit/scheduleControls.ts` (new).
- **ACs**: (functional) `getSchedulingParams` returns `{}` when unchecked, `{scheduled_at}` ISO when
  scheduled, `{monopolize:true}` when monopolized, both when both; `runSubmit` empty-validate short-circuits
  (no `post()` call), success path renders ack + clears spinner, error path renders `✗` + always clears
  spinner; `wireStt` calls `startRecording` with the right `contextId` and `onComplete` fills the input.
  (structural) `renderScheduleControls` DOM == legacy `.schedule-section` (ids `${prefix}-schedule` /
  `-scheduled-time` / `-monopolize`), and the `monopolize:false` variant emits the static span.
- **Oracle tier**: **T1** (scheduleControls DOM contract); rest n/a (logic, unit).

### Tasks 1–7 — the 7 card lanes (each: template + renderer + tests)

Each lane produces `templates/<x>SubmitCard.ts` (pure DOM, modeled on `broadcastCard.ts`) +
`render/<X>SubmitCardRenderer.ts` (modeled on `BroadcastCardRenderer.ts`) + unit tests. Common ACs per card:
(functional) collapse toggle flips `data-card-open` + glyph + persists via `SubmitCardsStore`; validation
guard matches legacy; submit calls the right `ApiClient` method with the **exact legacy body**; status line
renders ack/error; double-mount throws; unmount idempotent + cancels any active recording. (structural)
post-mount DOM under the card mount == legacy id/testid contract. **Oracle tier T1** (DOM contract) + n/a
(submit logic, unit). Card-specific deltas:

- **Task 1 — Claude Code** (`#claude-code-submit-card`): project select + STT prompt textarea + task-type
  (INTERACTIVE disabled) + dry-run + schedule/monopolize. Submit → `api.submitClaudeCode({ prompt, project,
  task_type, max_turns: task_type==='INTERACTIVE'?200:50, websocket_id, dry_run, …getSchedulingParams('cc') })`.
  Empty-prompt guard. `contextId:"cc-prompt"`.
- **Task 2 — Research** (`#research-submit-card`): STT topic + budget + with-podcast + with-presentation +
  dry-run + schedule/monopolize. Submit → `api.submitDeepResearch(...)` which **selects the endpoint** by the
  two checkboxes (presentation wins over podcast, both mutually exclusive per legacy `:3102-3106`) and adds
  `target_languages`/`target_duration_minutes` accordingly. Empty-topic guard. `contextId:"research-topic"`.
- **Task 3 — Podcast** (`#podcast-submit-card`): STT source + dry-run + schedule/monopolize. Submit →
  `api.submitPodcast({ research_source, target_languages:['en','es-MX'], dry_run, …sched })`. **Smart-input
  response branch**: `queued` → ✓ + clear input; `matching` → 🔍 message (keep input); `no_matches` → ⚠️
  message (legacy `:3213-3227`). `contextId:"podcast-source"`.
- **Task 4 — SWE Team** (`#swe-team-submit-card`): STT task textarea + nullable budget + nullable timeout +
  dry-run + trust-mode select + schedule/monopolize. Submit → `api.submitSweTeam({ task, dry_run,
  websocket_id })` plus optional `budget` (>0), `timeout` (>0), `trust_mode` (non-empty), `…sched`. Empty-task
  guard. `contextId:"swe-task"`.
- **Task 5 — Presentation** (`#presentation-submit-card`): STT source + audience select + duration + dry-run
  + schedule/monopolize. Submit → `api.submitPresentation({ source_path, audience, target_duration_minutes,
  dry_run, …sched })`. `contextId:"presentation-source"`.
- **Task 6 — Test Suite** (`#test-suite-submit-card`): **no STT, no monopolize checkbox** (static
  always-on). Types select with all 4 optgroups VERBATIM; **delegated `change`** (replacing inline
  `onTestSuiteTypeChange`) toggles `#test-suite-file-path-row` (when type ∈ `FILE_DRIVEN_TEST_TYPES`) and
  `#test-suite-fail-fast-row` (when type `=== 'all'`); file-path / pytest-args / dry-run / auto-fix. **Combined
  pytest_args logic** (legacy `:3489-3498`): prepend file path for file-driven types, append `--fail-fast`
  for `all`+fail-fast. Submit → `api.submitTestSuite({ test_types, dry_run, pytest_args?,
  auto_fix_on_failure? (only if checkbox present), scheduled_at? })` — **no `monopolize`**. File-driven +
  empty-path guard.
- **Task 7 — TFE Resume** (`#tfe-resume-submit-card`): **always-expanded** (no collapse toggle; `.job-submit-header`/
  `.job-submit-body` markup), **no STT/dry-run/schedule/monopolize**. Single textarea + Resume button. Submit
  → `api.resumeTfe({ resume_from })`. **Response branches**: `resumed` → ✓ status + clear input; `ambiguous`
  → render candidate rows into `#tfe-resume-candidates` (port of `_renderTFEResumeCandidates`, but
  **delegated** click → re-submit with the exact `job_id`, replacing the legacy inline `onclick`). Empty-input
  guard (legacy uses `alert()` — port to an inline status, the one sanctioned UX tidy; flag §8 Q5).

### Task 8 — `ApiClient` typed methods + interfaces
- **What**: add `SubmitJobResult` (`{ job_id, queue_position, status?, message? }`) + per-card Request
  interfaces, and 7 methods wrapping `post<T>()`. `submitDeepResearch` owns the endpoint-selection switch (so
  the renderer stays declarative). Narrow interfaces (tests stub only what they exercise), mirroring
  `broadcastToCcSessions`.
- **Files**: `api/ApiClient.ts` (convergence — §9).
- **ACs**: (functional) each method POSTs to the right path with the exact body; `submitDeepResearch` routes
  to the 3 endpoints by flags; podcast surfaces the `status` discriminator. **Oracle**: n/a (unit, stubbed fetcher).

### Task 9 — `SubmitCardsStore` + open-state persistence
- **What**: `createSubmitCardsStore({ eventBus, storage })`. State: `Record<cardId, boolean>` open-flags;
  `hydrate()` reads StorageService; `toggle(cardId)` flips + persists + emits `store_submit_cards_changed`;
  `isOpen(cardId)` getter. Default open-states match legacy (all 6 collapsible cards start **collapsed** —
  legacy `class="section-content collapsed"`; TFE-Resume has no toggle). Mirrors `BroadcastStore.cardOpen`.
- **Files**: `stores/SubmitCardsStore.ts`, `stores/index.ts`, `shared/types.ts` (event literal + payload).
- **ACs**: (functional) toggle persists across `hydrate()`; emits once per toggle; defaults collapsed.
  **Oracle**: n/a (unit).

### Task 10 — `multiplexer.html` pane + boot wiring + section-toolbar
- **What**: add `<section id="job-submit-pane" data-testid="multiplexer-job-submit-pane">` with
  `<header><h2>📝 Submit Agentic Jobs</h2></header>` + 7 mount divs (`#cc-submit-card-mount`, …) in legacy
  order, placed after `#jobs-pane` (legacy puts submit above the queues; reviewer call §8 Q6 on exact
  position). `boot.ts` NEW-LANE MOUNT SLOT: construct `SubmitCardsStore` + float `.hydrate()` (catch →
  non-fatal event, never an unhandled rejection — `JobsPaneRenderer` pattern), construct the 7 renderers
  (injecting `eventBus`, `store`, `api`, `recording`), resolve each mount div (`if null throw`), `.mount()`;
  add 7 `boot_complete` handler entries + `[multiplexer] <x>SubmitCardRenderer:mounted` console lines.
  `SECTION_TOGGLES` += `{ sectionId:"job-submit-pane", icon:"📝", title:"Submit Agentic Jobs",
  testid:"multiplexer-section-toolbar-job-submit" }`.
- **Files**: `html/multiplexer.html`, `boot.ts`, `render/templates/sectionToolbar.ts`, `render/index.ts`,
  `stores/index.ts` (convergence — §9).
- **ACs**: (functional) on boot all 7 cards render in order; the section-toolbar shows the 📝 toggle and
  hides/shows `#job-submit-pane` (persisted via ViewStateStore). (structural) pane + 7 mounts present.
  **Oracle tier**: **T1** (pane + toolbar contract).

### Task 11 — shared CSS lift
- **What**: lift `.job-submit-card`, `.job-submit-card-header`, `.section-content`(.collapsed),
  `.schedule-section`, `.stt-button`, `.toggle-button`, `.loading`/`.spinner`, the per-card submit-button
  color rules, and `.tfe-resume-candidate` from `css/notifications.css` into
  `css/shared/notifications-surface.css`; normalize the legacy inline `style=""` on these nodes into the
  shared sheet. Legacy + broadcast card keep rendering identically (both link the shared sheet). Verify both
  pages link it (mandate 3).
- **Files**: `css/shared/notifications-surface.css`, `html/multiplexer.html`, (verify) `html/notifications.html`.
- **ACs**: (structural) one copy of each rule; both pages link the shared sheet; legacy monolith no longer
  re-declares (or declares identically — T0 hash). (visual) inline-style normalization pixel-equal to legacy.
  **Oracle tier**: **T0 (CSS-hash)** + **T2 (computed-style)** (card header, mic, submit buttons, spinner).

## 6. Test strategy & venue routing

- **Unit (tsx `node:test` + happy-dom + c8 — AI-discretionary, :7999-class)** — the bulk; 100% L/B/F
  (mandate 1; `c8 ignore` only for genuinely-unreachable defensive branches with a same-line reason, per the
  existing `broadcastCard.ts`/`sectionToolbar.ts` phantom-branch pragmas):
  - `submit_card_common.test.ts`: `getSchedulingParams` matrix; `runSubmit` validate-short-circuit / success
    / error / spinner-always-cleared; `wireStt` contextId + onComplete fill; `scheduleControls` DOM (both
    `monopolize` variants).
  - 7 × `*_submit_card_template.test.ts`: ids + testids string-equal to legacy; selects' option sets/values
    VERBATIM (cc project/task-type, swe trust-mode, presentation audience, **test-suite all 4 optgroups**);
    cards 1-6 start collapsed; TFE-resume always-expanded + no schedule/STT.
  - 7 × `*_submit_card_renderer.test.ts`: mount paints contract; collapse toggle + persist; submit calls the
    right `ApiClient` method with the **exact body** (stub the client); status ack/error; STT mic →
    `startRecording` (inject fake recorder) → input filled (the 5 STT cards); double-mount throws; unmount
    cancels recording. Card-specific: **research** endpoint-switch (3 cases) + extras; **podcast** smart-input
    3-branch; **swe** nullable budget/timeout/trust inclusion rules; **test-suite** delegated type-change
    field visibility (file-path/fail-fast) + combined-args logic + no-monopolize body; **tfe** resumed vs
    ambiguous (candidate render + delegated pick re-submit).
  - `api_client.test.ts` (extend): the 7 new methods POST the right path/body; `submitDeepResearch` routing.
  - `submit_cards_store.test.ts`: toggle persist/emit/default-collapsed.
  - `section_toolbar.test.ts` (existing) extended: +1 toggle (`job-submit-pane`).
- **E2E UI + visual regression** → **:8000 scheduled** via `POST /api/test-suite/submit` (self-authorized on
  a verified-idle server; `list-pending` first; never side-door — mandate 4):
  - Playwright: `#job-submit-pane` mounts with 7 cards; each card collapses/expands + persists across reload;
    📝 toolbar toggle hides/shows + persists. **Dry-run submit per card** (every card defaults `dry_run`
    checked) → the matching endpoint returns a queued ack rendered into the card status — exercises the full
    POST path with **zero real LLM spend / no real work** (dry-run is the safe E2E lever). Mic button records
    (mock `getUserMedia`) → input filled (5 STT cards). Test-suite: type-change reveals file-path/fail-fast
    rows; TFE-resume ambiguous → candidate list click re-submits.
  - **Visual**: new golden of the pane (all 7 cards collapsed) + one expanded-card golden (see §7);
    `--update-snapshots` to baseline; version-controlled.
- **Doc touchpoints** (mandate 7): this accordion's own discrepancy→remediation doc under
  `…/2026.06.25-…-discrepancies/` (doc 04 §Next item 3). **No `src/docs/` API-doc change** — all 9 endpoints
  pre-exist (`/docs` auto-regenerates regardless). No new router/INI key → no CLAUDE.md §DOCUMENTATION
  TOUCHPOINTS row fires. (If the reviewer rules a new `ApiClient` agentic-submit surface warrants a note, the
  `rest-api-reference.md` quick-table is the only candidate — flagged, not assumed.)

## 7. Oracle & visual parity

Tiers exercised (methodology `2026.06.19-…/01-layout-parity-methodology.md`):

- **T0 CSS-hash** — the lifted job-submit rules served from the single shared sheet; hash-match vs legacy.
- **T1 DOM-contract** — per card, every legacy id + `data-testid`; the selects' option sets; the
  `.schedule-section` sub-contract; the toolbar +1 `.toolbar-btn[data-section="job-submit-pane"]`. This is the
  primary gate (7 cards × ~6-12 controls each).
- **T2 computed-style** — card-header typography + toggle glyph, mic button, the 7 distinct submit-button
  colors (legacy inline `background:` per card — `#007bff`/`#28a745`/`#6f42c1`/`#fd7e14`/`#20c997`/`#17a2b8`/`#f0ad4e`),
  spinner, schedule-section layout.
- **T3 geometry** — the form-group flex rows (label · control · checkbox clusters) and the schedule-section
  flex.
- **T4 pixel backstop** — golden 1: pane with all 7 cards collapsed (deterministic — no live data). golden 2:
  one representative card expanded (Test-Suite, the richest — exercises optgroups + conditional rows in their
  default-hidden state). Freeze any time/text so diffs are clean.

**New golden captures**: (1) legacy `:8000` reference capture of `#section-job-submit` (collapsed + one
expanded) — legacy-capture cost per mandate 2; (2) mux baselines via `--update-snapshots`. Seed identically
(all cards collapsed, dry-run checked, defaults selected) so the diff is clean. **Note** the 7-card surface is
the corpus's largest single visual target — budget the legacy capture accordingly.

## 8. Risks & open questions (for reviewers)

1. **Pane container vs 7 independent cards — confirm the structure.** Legacy nests all 7 in ONE
   `#section-job-submit` collapsible whose body holds the 7 cards (each independently collapsible). This plan
   maps that to a `#job-submit-pane` `<section>` (section-toolbar toggle = the outer accordion) + 7 lane-private
   card renderers (each its own inner collapse via `SubmitCardsStore`). That's the mux idiom (header→toolbar,
   doc 04 §#6), but it's a 2-level→2-level remap worth an explicit nod. **Recommended**: as planned.
2. **One `SubmitCardsStore` vs per-card open-state vs no store.** Card-open is pure local UI; broadcast keeps
   it in `BroadcastStore`. A single shared store (planned) is testable + consistent but is a mild cross-lane
   dependency (L0). Alternative: each renderer reads/writes its own StorageService key (no store, no event
   literal) — fewer convergence edits but diverges from the broadcast precedent. **Recommended**: the shared
   store (matches precedent, one event literal).
3. **`submitDeepResearch` endpoint-switch placement — `ApiClient` vs renderer.** Plan puts the 3-way routing
   (deep-research / →podcast / →presentation, presentation-wins) inside `ApiClient.submitDeepResearch` so the
   renderer stays declarative. Alternative: keep it in the renderer (closer to legacy `submitResearchJob`).
   **Recommended**: in `ApiClient` (keeps the network concern in the network layer).
4. **`FILE_DRIVEN_TEST_TYPES` becomes a 4th sync site.** Adding the mux copy makes 4 places that must agree
   (`.js`, `.html`, `job.py`, mux). Drift-prone. **Option**: expose the set from a tiny endpoint and hydrate it
   — OUT of strict-parity scope, but flagged; or at minimum add a cross-file comment pointer (planned).
5. **TFE-resume `alert()` → inline status (the one sanctioned UX change).** Legacy uses a blocking `alert()`
   on empty input; mux has no `alert()` idiom. Plan ports it to an inline `#tfe-resume-submit-status` message.
   Confirm this micro-deviation is acceptable (it is strictly better UX and the only non-1:1 in the plan).
6. **Pane vertical position.** Legacy column order is Q&A → **Submit Jobs** → Action-Required → TTS → Queues.
   The mux column currently runs notifications → jobs → broadcast → commons → … . Where does `#job-submit-pane`
   sit, and does the section-toolbar order need to match the legacy reading order? **Recommended**: directly
   after `#jobs-pane` (submit-then-see-them-queue affordance); reviewer confirms.
7. **Dry-run as the E2E lever — sufficient coverage?** Every card defaults `dry_run` checked, so the E2E sweep
   can hit all 7 POST paths with no real LLM spend / no real work enqueued. But dry-run exercises the
   submit/ack path, NOT live job execution. That's the right boundary for a UI-parity plan (job execution is
   already covered by each agent's own suites), but confirm the reviewer agrees the card plan stops at the
   ack.
8. **`websocket_id` source (CC + SWE bodies).** Legacy passes `this.sessionId` (CC) vs `this.queueSessionId`
   (SWE) — subtly different fields. Confirm the mux uses the correct single session id for each (the
   queue-session id is the canonical `websocket_id` target); flagged so the port doesn't silently unify two
   legacy values that the server may treat differently.

## 9. Lane decomposition & estimate

**The heaviest plan in the corpus — explicitly decomposed into 7 parallel card lanes + 1 shared-foundation
lane + 1 convergence lane.** This is a manager-orchestrated multi-worktree build (mandate 5).

| Lane | Owns (lane-private, no merge risk) | Depends on |
|---|---|---|
| **L0 — shared foundation** | `render/submit/submitCardCommon.ts`, `render/submit/scheduleControls.ts`, `SubmitCardsStore.ts`, the 7 `ApiClient` methods + interfaces | — (lands FIRST; gates L1-L7) |
| **L1 — Claude Code card** | `templates/ccSubmitCard.ts`, `CcSubmitCardRenderer.ts`, tests | L0 |
| **L2 — Research card** | `templates/researchSubmitCard.ts`, `ResearchSubmitCardRenderer.ts`, tests | L0 |
| **L3 — Podcast card** | `templates/podcastSubmitCard.ts`, `PodcastSubmitCardRenderer.ts`, tests | L0 |
| **L4 — SWE Team card** | `templates/sweTeamSubmitCard.ts`, `SweTeamSubmitCardRenderer.ts`, tests | L0 |
| **L5 — Presentation card** | `templates/presentationSubmitCard.ts`, `PresentationSubmitCardRenderer.ts`, tests | L0 |
| **L6 — Test Suite card** (richest) | `templates/testSuiteSubmitCard.ts`, `TestSuiteSubmitCardRenderer.ts`, tests | L0 |
| **L7 — TFE Resume card** | `templates/tfeResumeSubmitCard.ts`, `TfeResumeSubmitCardRenderer.ts`, tests | L0 |
| **LZ — convergence (manager-serial-merged)** | the shared-file edits below | L1-L7 complete |

**Convergence files (manager-serial-merged — mandate 5; NO lane edits these except via the manager):**

- `api/ApiClient.ts` (the 7 methods — though authored in L0, the file is shared; manager merges),
- `shared/types.ts` (event union +1 literal + payload),
- `render/templates/sectionToolbar.ts` (`SECTION_TOGGLES` +1),
- `boot.ts` (NEW-LANE MOUNT SLOT — 7 mount blocks + handlers/console lines),
- `html/multiplexer.html` (`#job-submit-pane` + 7 mount divs + `<head>` shared-sheet link),
- `css/shared/notifications-surface.css` (lifted job-submit rules),
- `render/index.ts` + `stores/index.ts` (barrel exports).

All convergence files are shared with the other corpus plans (esp. `types.ts` / `boot.ts` /
`sectionToolbar.ts` / shared CSS / barrels) → the manager merges this plan's edits serially after the
sibling plans. **Reused, untouched**: `audio/recordingManager.ts`, `audio/AudioRecorder.ts`,
`render/insertTranscriptionText.ts`, `shared/StorageService.ts`, `shared/EventBus.ts`, `stores/JobStore.ts`,
`stores/ViewStateStore.ts`.

**Recommended execution order**: L0 first (single engineer, ~0.5 day) → L1-L7 fan out in parallel worktrees
(each card is independent; L6 Test-Suite is ~1.5× the others). Manager runs LZ convergence after the lanes
merge, then the boot/html/css/toolbar edits land serially, then the full E2E + visual baseline.

**Rough size**: ~7 templates + 7 renderers + L0 + store ≈ **~1,400-1,800 new TS LOC** + ~60 HTML lines +
the CSS lift; ~7 template tests + ~7 renderer tests + ~4 support tests. **Estimate**: L0 ~0.5 day · each card
~0.5-0.75 day (L6 ~1 day) · convergence + E2E/visual ~1 day → **~5-6 engineer-days serial, ~2-2.5 days
wall-clock with 7 lanes parallelized**. This is the corpus's largest single build (doc 04: "highest build").
