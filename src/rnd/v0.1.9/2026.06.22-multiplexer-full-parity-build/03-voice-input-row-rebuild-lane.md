# Lane: Voice-Input-Row Rebuild (F5 family) — Build Plan

**Worker**: Cheech 🌿 (session 6ebe2f44) · **Manager**: Tiberius 👑 (704c71b2)
**Worktree**: `/tmp/voice-input-rebuild-wt` · **Branch**: `voice-input-row-rebuild` (off `wip-v0.1.9-2026.06.21-bug-fix-implementation`)
**Date**: 2026-06-22 · **Ratified**: Rick 2026-06-22 — MATCH LEGACY, full parity.

## Charter

Rebuild legacy's inline `.cc-voice-input-row` in the multiplexer. Today the mux
renders a minimal Record-button flow appended at card **bottom**; legacy renders
an inline row **between** the card header and `.sender-card-dates` containing:
conv-mode toggle + mic + text input + send. The ratified F5 caret-splice **folds
into** the rebuilt row (reconciled, not reverted). After rebuild, **lift** the
temporary Tier-3 voice-region carve.

## Reconnaissance findings (verified, not assumed)

1. **Card lifecycle**: `NotificationsListRenderer` re-creates + replaces the whole
   `.sender-card` on every `store_senders_changed`
   (`NotificationsListRenderer.ts:234`, `existing.replaceWith(fresh)`). Any in-row
   state must survive replacement via the recorder's per-session `states` Map —
   same resilience model as today.

2. **Parity harness renders `renderSenderCard` in isolation**
   (`testkit/parityHarness.ts:57`) — it does NOT mount the recorder renderer. ⇒
   The full static row markup **must come from `senderCard.ts`**, not the
   behavior-only recorder. (Decisive: an empty footer here ⇒ harness geometry
   never matches ⇒ carve can't lift.)

3. **Conv-mode toggle is a direct POST** to
   `/api/cosa-voice/speakerphone/{sessionHash}` body `{on: next}`
   (legacy `notifications.js:12759`). Inbound state already flows back via the WS
   `conversation_mode_changed` / `speakerphone_changed` event the `SenderStore`
   consumes (`SenderStore.ts:238` → `handleConversationModeUpdate`). ⇒ **No new
   EventBus event, no boot.ts change** — the manager-serial files are untouched.

4. **CSS / harness loading**: `parity-harness.html` loads `lupin-base.css` +
   `notifications-surface.css` (shared, **hash-guarded** — golden goes stale if
   touched) + `notifications-list.css`, but NOT `sender-card-recorder.css`. The
   real `multiplexer.html` loads `sender-card-recorder.css` (line 26). ⇒ Port the
   legacy-faithful voice CSS into `sender-card-recorder.css` AND add one `<link>`
   to `parity-harness.html` (not a manager-serial file) so harness == real page.
   The shared sheet is left untouched (golden stays valid; legacy unchanged).

5. **Legacy row markup** (`notifications.js:13504-13521`), mux idiom (NO inline
   onclick — delegated):
   - `.cc-voice-input` (container, CC-session only) → `data-session-hash`,
     `data-sender-id`. Legacy CSS: `padding:8px 12px; border-bottom:1px dashed
     #dee2e6; background:#f0f7ff` (NOT flex; the ROW inside is flex).
   - `.cc-voice-input-row` (flex) containing:
     - `.sender-conversation-mode-btn` (+ `is-active` when active),
       `data-session-id`, title, icon (chorus: 🔊 active / 🤭 idle).
     - `.stt-button.cc-session-stt`, id `cc-session-stt-${sid}`, title
       "Click to record (30s max, ESC to cancel)", 🎤.
     - `<input type="text" class="cc-session-msg-input">`, id
       `cc-session-input-${sid}`, placeholder "Send voice/text to CC session...".
     - `.response-submit-button.cc-session-send`, id `cc-session-send-${sid}`,
       "Send".

6. **F5 splice is a pure fn** (`insertTranscriptionText.ts`) — UNCHANGED. The
   element-half (stash-before-repaint + caret restore) moves into the rebuilt
   recorder, now operating on the persistent `<input class="cc-session-msg-input">`
   (inputs support selectionStart/End/setSelectionRange — splice survives).

7. **Message-badge nesting** (`notificationItem.ts:84,94`) — already nests
   `.expired-badge`/`.abstract-indicator` inside `.message-text`. VERIFY-ONLY ✓
   (confirmed legacy-correct; no change).

## Build steps

### B1 — `senderCard.ts`: emit the static inline row between header and dates
- For CC sessions (`sender_id.includes("#")`), emit `.cc-voice-input` >
  `.cc-voice-input-row` with the 4 legacy elements (markup §5), positioned
  BETWEEN `.sender-card-header` and `.sender-card-dates` (move it OUT of the
  current bottom-append). Conv-mode `is-active` from `sender.conversation_mode_active`.
- Non-CC senders: no row (legacy parity).

### B2 — `SenderCardRecorderRenderer.ts`: operate on the existing row (no structural replaceChildren)
- Click delegation on `.cc-session-stt` (mic record/stop), `.cc-session-send`
  (send), `.sender-conversation-mode-btn` (conv-mode POST).
- Per-session `states` Map: `{ recording: bool, transcription?, stash?, caret? }`.
  On `store_senders_changed` (post card-replace): re-apply mic recording class +
  restore `.cc-session-msg-input` value from state (survives replacement).
- Record start: stash live input value+caret (ALWAYS — empty input splices "" at
  caret 0 = plain fill; non-empty = caret splice). Fold `insertTranscriptionText`
  on complete; restore focus+caret. `data-recorder-state` = `idle`|`recording`
  (the separate `ready_to_send` paint is retired — input is persistent).
- Send: POST `/api/notify` (unchanged wire shape), clear input on success.
- Conv-mode: POST `/api/cosa-voice/speakerphone/{sid}` `{on:!isActive}`; state
  reaffirmed by the WS event (optimistic class flip optional).

### B3 — CSS (`sender-card-recorder.css`) + harness link
- Port legacy-faithful rules: `.cc-voice-input` (block, padding/border-bottom/bg),
  `.cc-voice-input-row` (flex, gap 6px, align center), `.stt-button` /
  `.sender-conversation-mode-btn` (34px h, 40px min-w, flex-shrink 0),
  `.cc-session-msg-input` (flex:1), `.response-submit-button` (34px h). Retire the
  old `.record-button`/`.send-button`/`.cc-voice-input-textarea`/`ready_to_send`
  rules.
- Add `<link rel="stylesheet" href="/static/css/multiplexer/sender-card-recorder.css">`
  to `parity-harness.html` (so harness row height == legacy ~51px).

### B4 — Tests
- Rewrite `sender_card_recorder_renderer.test.ts` to the new markup + behavior
  (record/stop on mic, send, conv-mode POST, F5 splice on the input, state
  survives re-paint, error surfaces). 100% L/B/F (c8 directory-wide glob).
- Extend `templates_sender_card.test.ts`: CC card emits `.cc-voice-input-row`
  between header and dates with the 4 elements + is-active reflection; non-CC
  omits it.
- Rewrite E2E `test_multiplexer_stt_insert_at_cursor.py` to drive `.cc-session-stt`
  + read `.cc-session-msg-input` (splice contract identical).

### B5 — Lift the Tier-3 carve
- `bash src/scripts/build-multiplexer.sh` (rebuild boot.js — stale = false RED).
- Run the oracle (Tier 1/2/3 + golden conformance). If voice-region geometry now
  matches legacy, remove carve (a) (dates-region dy re-anchor) + (b) (CC card
  height exclusion) from `test_tier2_tier3.py`, restoring full absolute-geometry
  parity. Residual gap (if any) documented precisely, NOT masked.

## Acceptance (both gates)
- **Layout oracle**: Tier-1 node present + Tier-2/3 green (carve lifted or residual
  documented). Rebuild boot.js before EVERY oracle check.
- **Functional E2E**: row renders, mic records, caret-splice on re-record, send
  posts.
- **Coverage**: 100% L/B/F on new/changed TS (c8 --100, directory-wide include).
  py_compile/import-chain clean for any Python.

## Discipline
Worktree-isolated. Selective staging (only my hunks). Commit HELD locally — NO
push (Rick's alone). reproduce-not-trust before reporting green. Manager-serial
files (boot.ts / multiplexer.html / shared/*) — NOT touched by this lane (verified
in recon §3). `parity-harness.html` + `sender-card-recorder.css` are lane-owned.
