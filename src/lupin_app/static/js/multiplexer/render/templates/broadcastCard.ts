/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane C (v0.1.9 focus-bar parity, 2026-06-24) — broadcastCard template.
//
// Pure markup for the "Broadcast to all CC sessions" compose card — the
// multiplexer port of the legacy `notifications.html:692-726` +
// `broadcast-panel.js` control. Returns a DocumentFragment (the `html` helper
// idiom) so the component-isolation parity harness can render it ALONE, with
// NO renderer mount. BroadcastCardRenderer wires all behavior (collapse toggle,
// 🎤 STT, recipient chips, Send → confirm modal) onto these EXISTING elements
// via delegated clicks — NO inline onclick (mux no-globals rule).
//
// Mirrors the legacy ids verbatim where the legacy CSS keys on them
// (#broadcast-recipients-row / -label / -refresh, #broadcast-textarea,
// #broadcast-send-button) and adds `data-testid` hooks for the e2e_ui sweep.
// The status line (#broadcast-submit-status) reflects recipients/filtered_out
// after a send (AC2) — the current legacy HTML routes ack-feedback to the
// standard notification stream, so this is the mux's compose-local receipt.

import { html } from "../html";

// The card body sub-fragment is built separately so the recipient CHIPS (which
// the renderer injects dynamically between the label and the ↻ refresh button)
// have a stable insertion anchor.

/**
 * Build the broadcast compose card.
 *
 * Requires:
 *   - `cardOpen` reflects the persisted card-open state (BroadcastStore).
 *
 * Ensures:
 *   - Returns a fresh DocumentFragment containing #broadcast-submit-card.
 *   - The card carries `data-card-open` = "true"|"false"; the toggle glyph is
 *     seeded to match. Section visibility is CSS-driven off `data-card-open`
 *     (broadcast.css `[data-card-open="false"] .section-content { display:none }`
 *     — the CommonsActivityRenderer collapse idiom), so the renderer only flips
 *     the attribute + glyph on toggle.
 *   - The Send button starts disabled (no body, no recipients yet).
 */
export function renderBroadcastCard( cardOpen: boolean ): DocumentFragment {
  // Compute the cardOpen-driven bits in plain code (not inside the tagged
  // template) so their branches are normal, fully-coverable lines.
  const openAttr = cardOpen ? "true" : "false";
  const glyph    = cardOpen ? "▼" : "▶";
  /* c8 ignore next 46 */ // tagged-template literal: c8 reports phantom branches on each $-interpolation position (commonsActivityEntry.ts:74 pattern); the runtime path is straight-line and exercised by both (open + closed) template-test fixtures.
  return html`
    <div class="job-submit-card broadcast-submit-card"
         id="broadcast-submit-card"
         data-testid="multiplexer-broadcast-card"
         data-card-open="${openAttr}">
      <div class="job-submit-card-header"
           id="broadcast-submit-header"
           role="button" tabindex="0">
        <h4>📢 Broadcast to all CC sessions</h4>
        <button class="toggle-button"
                id="broadcast-submit-toggle"
                data-testid="multiplexer-broadcast-toggle"
                type="button">${glyph}</button>
      </div>
      <div class="section-content"
           id="broadcast-submit-section">
        <div id="broadcast-panel-body">
          <div id="broadcast-recipients-row"
               data-testid="multiplexer-broadcast-recipients-row">
            <span id="broadcast-recipients-label">Sending to:</span>
            <button type="button"
                    id="broadcast-recipients-refresh"
                    data-testid="multiplexer-broadcast-refresh-btn"
                    title="Refresh active session list">↻ refresh</button>
          </div>
          <div id="broadcast-compose-row">
            <button type="button"
                    id="broadcast-stt-button"
                    data-testid="multiplexer-broadcast-stt-btn"
                    class="stt-button broadcast-stt"
                    title="Click to record (30s max, ESC to cancel)">🎤</button>
            <textarea id="broadcast-textarea"
                      data-testid="multiplexer-broadcast-textarea"
                      placeholder="Message body — use @PersonaName: lines for persona-specific directives. Markdown supported."></textarea>
            <button id="broadcast-send-button"
                    data-testid="multiplexer-broadcast-send-btn"
                    class="response-submit-button broadcast-send"
                    type="button"
                    disabled>Send</button>
          </div>
          <div id="broadcast-submit-status"
               data-testid="multiplexer-broadcast-status"></div>
        </div>
      </div>
    </div>
  ` as DocumentFragment;
}
