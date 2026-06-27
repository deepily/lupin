# Per-Accordion Audit — the 12 accordions beyond CC-Session (Notifications)

**Date**: 2026-06-26 (this session, for Rick)
**Method**: source-level audit per doc 01 §5 (rename-vs-deleted test applied to every "missing"
before concluding ABSENT). Three parallel read-only passes; every claim cites `file:line`. **Live-render
visual diff (doc 01 §7–8) still owed** for the present/remapped ones — flagged per row.
**Roots**: legacy `html/notifications.html` + `js/notifications.js`; mux `html/multiplexer.html` +
`js/multiplexer/**` + `css/multiplexer/*`. All mux equivalents confirmed mounted in `boot.ts`.

---

## Master verdict (12 accordions)

| # | Legacy section | Verdict | Mux equivalent | Headline gap |
|---|---|---|---|---|
| 6 | `section-fleet-status` | ✅ **FAITHFUL PORT** | `fleet-status-pane` (`FleetStatusRenderer`) | none functional; header-accordion→toolbar-toggle, `<h2>`vs`<h3>` |
| 7 | `section-task-list` | ✅ **PORT + SUPERSET** | `task-list-pane` (`TaskListRenderer`) | mux ADDS edit/drop controls that break legacy's read-only contract; collapse-all relocated to header |
| 3 | `action-required-section` | ⚠️ **PARTIAL + RELOCATED** | folded into `#notifications-pane` (`ActionRequiredRenderer`) | interactive core richer, but lost active/pending one-at-a-time model, empty state, count, keyboard-nav, pane-mode, toolbar toggle |
| 4 | `tts-queue-section` | ⚠️ **REMAPPED / PARTIAL** | `tts-pane` (`TtsChromeRenderer`, still `data-phase6-pending`) | reduced to global transport chrome; lost per-item active/pending queue viz, Clear-all, Focus-mode resume, count header, empty state |
| 9 | `section-queues` | ⚠️ **PARTIAL** | `jobs-pane` (`JobsPaneRenderer`+`JobStore`) | display present; **delete/delete-all/retry/time-window/pagination/filter-badge all missing** (code says "Phase 6b") |
| 1 | `section-qa` | ❌ **TRULY ABSENT** | none | whole Q&A entry point gone (moderate build) |
| 2 | `section-job-submit` | ❌ **TRULY ABSENT** | none (jobs-pane displays, can't submit) | 7 job-submit cards, ~415 HTML lines + 7 handlers (highest build) |
| 8 | `filter-settings-section` | ❌ **TRULY ABSENT** | none | admin job-ownership filter; coupled to #9's missing filter-badge |
| 10 | `section-time-saved` | ❌ **TRULY ABSENT** | none | stats dashboard + leaderboard; APIs already exist (moderate) |
| 11 | `section-status` | ❌ **TRULY ABSENT** | none (`fleet-status-pane` ≠ this) | WS/auth/session/health + config-reload/logout/missed-reset (high) |
| 12 | `section-direct-tts` | ❌ **TRULY ABSENT** | none (`tts-pane` ≠ this) | dev TTS test harness (low; decide if wanted in prod UI) |
| 13 | `section-debug` | ❌ **TRULY ABSENT** | none | on-page capped debug log (very low; likely intentional drop) |

**Tally**: 2 faithful ports · 3 partial/remapped with real regressions · **7 truly absent**. Of the 7
absent, 3 are likely intentional dev/diagnostic drops (`direct-tts`, `debug`, maybe `status`); the rest
(`qa`, `job-submit`, `filter-settings`, `time-saved`) are user-facing features needing a port decision.

---

## Detail

### #6 Fleet Status — ✅ faithful port
Same 4-state dispatch (signin / arbiter-offline / empty / table), offline toggle, live-only count, ⟳
refresh, "updated HH:MM:SS TZ" stamp (`FleetStatusRenderer.ts:159-210`); renderer cites the legacy port
(`:4-9`). Only divergence: legacy `.collapsible-section` header-click accordion + ▼ (`notifications.html:839-856`)
→ mux owns its `<header><h2>` and delegates collapse to the section-toolbar (`sectionToolbar.ts:40`).
**Owed**: live check that toolbar-toggle collapse ≈ legacy header-click UX.

### #7 Task List — ✅ port + superset (contract divergence)
Same 4-state, owner-grouping, collapse-all/expand-all on a **shared localStorage key**, ⟳, stamp
(`TaskListRenderer.ts:219-285`). **Divergence**: mux adds per-row priority/owner edit + drop-with-reason
optimistic writes (`:287-406`) — legacy is explicitly "read-only, NO mutating controls"
(`notifications.html:858-861`). Collapse-all buttons moved from floating toolbar (`notifications.html:53-54`)
to card header. **Design call for Rick**: keep the mux's added mutation controls (intentional Phase-2
expansion) or restore read-only parity?

### #3 Action Required — ⚠️ partial + relocated
Mux interactive responder is **richer** (explicit state machine, all response types, per-item countdown,
non-optimistic submit — `ActionRequiredRenderer.ts:21-254`) but drops legacy's **presentation model**:
no `#action-required-active-slot` / `#action-required-pending-queue` / minimized cards + position badges
(grep → 0), no `#action-required-empty` "✓ No pending actions", no `#action-required-count`, no
keyboard-nav, no horizontal pane-mode, no section-toolbar toggle (`sectionToolbar.ts:35-42` omits it).
Relocated from top-level (`notifications.html:563`) into `#notifications-pane` (`multiplexer.html:110-111`)
as a bare div. **Owed**: live check whether many simultaneous items are usable without the one-at-a-time funnel.
**Inherits** the AR read-only↔interactive carve (doc 02 §4).

### #4 TTS Queue — ⚠️ remapped / partial
Legacy = collapsible section with rich header (Resume/Focus + Pause/Play + Clear + count "🔊 Playing: N")
over active-slot + pending-queue body (`notifications.html:587-628`). Mux `tts-pane` = single flat
`.tts-chrome` transport bar: Pause/Resume, Stop, Skip, "Queued: N" (`ttsChrome.ts:50-113`), `AudioStore`-driven.
**Lost**: per-item `#tts-active-slot`/`#tts-pending-queue`/`.tts-active-card`/`tts-minimized-*` (grep → 0),
Clear-all (`clearTTSQueue`), Focus-mode Resume (`toggleTTSFocusMode`), empty state, count header.
**Added**: explicit Skip + 6-state enable matrix. Note `tts-pane` still carries `data-phase6-pending="true"`
(stub). **Design call**: is single-stream transport-only an accepted redesign vs the per-item queue?

### #9 Job Queues → jobs-pane — ⚠️ partial
Strong display equivalent: 5 buckets todo/running/done/dead/history with `running→run` collapse, aria
collapse/expand, counts, single history hydrate (`JobsPaneRenderer.ts:91-181`, `jobBucket.ts`). **Missing
mutations/controls**: per-job delete is rendered **disabled** ("Delete coming in Phase 6b",
`jobCard.ts:258`); no per-bucket delete-all; no `#history-time-window` selector (1/7/14/30/all); no
load-more pagination; no retry; no `queues-filter-badge`. Port targets: `deleteAllQueueJobs`
(`notifications.js:6760`), `onHistoryTimeWindowChange` (`:6856`), `loadMoreHistory` (`:6878`), retry (`:6829`).

### #1 Q&A Interface — ❌ truly absent
Grep of `qa-input`/`submit-qa`/`submitQA`/`agent-mode`/`mode-badge`/`response-text` → 0 mux hits.
Legacy `notifications.html:83-143` (~61 lines) + `submitQA()` (`notifications.js:2915`), `setAgentMode()`
(`:20212`), metrics (`:6028`). Port: new `QaPaneRenderer` + mode-select/mic/input/tts-mode/metrics/response,
submit action, mode state; can reuse mux `audio/AudioRecorder.ts` for STT. Moderate.

### #2 Submit Agentic Jobs — ❌ truly absent (highest build)
Legacy `notifications.html:146-560` (~415 lines): 6 submit cards + TFE-resume, each with STT/dry-run/
schedule/monopolize; 7 handlers (`submitClaudeCode` `:4047`, research `:3069`, podcast `:3162`, swe `:3245`,
presentation `:3339`, test-suite `:3463`, tfe-resume `:7962`). Mux only **reuses the `.job-submit-card` CSS
class** in `broadcastCard.ts` — no dispatcher. `jobs-pane` displays jobs but offers no submit path. High build.

### #8 Filter Settings (Admin) — ❌ truly absent
3-button view-mode switch (own/others/all) driving `exclude_own_jobs` on queue/history fetches
(`setFilterMode` `notifications.js:6197`; call sites `:14285`,`:15258`). No mux UI/store filter mode
(grep → 0). Coupled to #9 (jobs-pane has no user-scope filter / filter badge). Low–moderate.

### #10 Time Saved — ❌ truly absent
Stats dashboard (4 stat cells + leaderboard) on `GET /api/stats/time-saved` + `/global`
(`refreshTimeSavedStats` `notifications.js:8401`, `renderTopSolutions` `:8457`). Backend exists; needs
`TimeSavedRenderer` + store + toolbar entry. Moderate (~100–150 LOC).

### #11 System Status — ❌ truly absent (mux fleet-status-pane is NOT this)
WS/auth/session/health pills + config-reload/logout/missed-reset/copy (`refreshAllStatus`
`notifications.js:1356`, sub-refreshers `:1400-1479`, `reinitializeConfig` `:1295`). Mux `fleet-status-pane`
is a different concept (multi-host fleet table). Needs `SystemStatusRenderer` bound to mux transport/auth
stores + ported admin actions. High (~200+ LOC).

### #12 Direct TTS Test — ❌ truly absent (mux tts-pane is NOT this)
Dev harness: text input + Speak-Now + instant/reliable probes + stop (`notifications.html:1136-1150`;
`directTTSTest` `notifications.js:4142`, `testTTS(...)`). `tts-pane` is production playback chrome, not a
synth-arbitrary-text test. Low (~40–60 LOC) — could fold into `tts-pane` as a dev sub-block. **Decide if a
dev harness belongs in the prod mux UI.**

### #13 Debug Info — ❌ truly absent
On-page capped (20-entry) debug log mirroring `log/error/wsDiag` (`addDebugMessage`
`notifications.js:15461`). No mux `#debug-log` (the "debug-logger" mux hits are an unrelated audio binary).
Very low (~30 LOC). Likely intentional — mux favors devtools/console.

---

## Resolved design calls (Rick, 2026-06-26 `/plan-decide`) — through-line: TOTAL 13/13 PARITY

- **(f) Action Required → FULL FUNNEL RESTORE + rich responder.** Rebuild legacy's active/pending
  one-at-a-time funnel (active slot + minimized pending cards + position badges + empty state + count +
  keyboard-nav + pane-mode + toolbar toggle), rendering the **active** item through the mux's richer
  responder (state machine / countdown / non-optimistic submit). Best-of-both, explicitly NOT either/or.
  Impl note: split `ActionRequiredRenderer`'s flat all-items list into active(full)+pending(minimized).
  Inherits the AR read-only↔interactive carve (doc 02 §4).
- **(e) TTS Queue → FULL 1:1 RESTORE (chrome + per-item queue).** Rich header (Focus Resume + Pause/Play
  + Clear-all + "Playing: N" count), active-slot + pending-queue per-item cards + reordering + empty
  state, **keeping** the mux's added Skip + 6-state matrix. **Prereq**: extend `AudioStore` to model a
  multi-item queue (today single-stream sequential) — gates the per-item viz.
- **(d) Task List → KEEP edit/drop as a documented SUPERSET.** Accept the mux's per-row priority/owner
  edit + drop-with-reason as an intentional divergence (task store = fleet control plane). Not a defect;
  update the parity contract to note Task List is deliberately a superset of legacy's read-only view.
- **(g) Port ALL 7 absent accordions → total 13/13 parity** (Q&A, Submit-Jobs, Time-Saved,
  Filter-Settings, Direct-TTS, Debug, System-Status), sequenced **after** CC-session (`03-`) + the 3
  partials. No "obsolete" drops — strict total parity.

## Next

1. Land the CC-session `03-` remediation plan (B1–B5) — accordion #5, decisions already ratified.
2. Resolve design calls (d)–(g) to scope the remaining accordions.
3. Per ported accordion: own discrepancy→remediation doc; run the doc 01 §7–8 live-render diff; 100% L/B/F + visual rebaseline.
