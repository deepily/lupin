/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP13 — TTS preview-fraction slider template (F6).
//
// Ports the legacy `#cc-tts-fraction-slider` control (notifications.js:1613-1640
// + multiplexer.html slider DOM) to a multiplexer-idiomatic safe-write template.
//
// User-visible behavior (parity with legacy F6, commit e5a72e2):
//   - Nine stops at 12.5% increments (0/12.5/25/37.5/50/62.5/75/87.5/100).
//   - A <datalist> renders the tick marks; the value label mirrors the thumb.
//   - parseFloat (not parseInt) at the consumer so off-integer stops survive.
//
// AC safe-write invariant (mirrors ttsChrome.ts AC2e): ALL DOM writes go through
// the `html` tagged template + `.textContent` / `.value` only. NEVER `.innerHTML =`,
// `rawHTML(`, or `.outerHTML =`. Verified by the grep guard in
// templates_tts_preview_slider.test.ts.

import { html } from "../html";

// Nine canonical stops in percent (12.5% increments). Exported so the renderer
// and tests reference ONE source of truth (the one-descriptive-name rule).
export const TTS_FRACTION_STOPS_PCT: ReadonlyArray<number> = [
  0, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100,
];

export interface TtsPreviewSliderHandlers {
  /** Fired on every `input` event with the snapped percent (e.g. 37.5). */
  onInput( percent: number ): void;
}

export interface TtsPreviewSliderOpts {
  /** Initial slider position in PERCENT (0-100), already resolved by the renderer. */
  percent : number;
}

/**
 * Build the TTS preview-fraction slider control (label + range + datalist).
 *
 * Requires:
 *   - `opts.percent` is a finite number in [0, 100]
 *   - `handlers.onInput` is a function
 *
 * Ensures:
 *   - Returned HTMLElement carries `.tts-preview-slider`
 *   - Range input has min=0 / max=100 / step=12.5 and `list` → the datalist id
 *   - The datalist contains exactly TTS_FRACTION_STOPS_PCT.length <option>s
 *   - The value label shows `${percent}%`, seeded from `opts.percent`
 *   - All writes are safe (no .innerHTML / rawHTML / .outerHTML)
 */
export function renderTtsPreviewSlider(
  opts     : TtsPreviewSliderOpts,
  handlers : TtsPreviewSliderHandlers,
): HTMLElement {
  const root = document.createElement( "div" );
  root.className = "tts-preview-slider";
  root.setAttribute( "data-testid", "multiplexer-tts-preview-slider" );

  const percentStr = String( opts.percent );

  // Build datalist option fragments — one per canonical stop.
  const options = TTS_FRACTION_STOPS_PCT.map(
    ( stop ) => html`<option value="${String( stop )}"></option>`,
  );

  /* c8 ignore next 13 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders the slider (ttsChrome.ts:105 precedent).
  const frag = html`
    <label class="tts-preview-slider-label" for="cc-tts-fraction-slider">TTS preview</label>
    <input type="range"
           class="tts-preview-slider-input"
           id="cc-tts-fraction-slider"
           min="0" max="100" step="12.5"
           list="cc-tts-fraction-ticks"
           value="${percentStr}">
    <datalist id="cc-tts-fraction-ticks" class="tts-preview-slider-ticks">
      ${options}
    </datalist>
    <span class="tts-preview-slider-value" id="cc-tts-fraction-value">${percentStr}%</span>
  ` as DocumentFragment;
  root.appendChild( frag );

  const input = root.querySelector<HTMLInputElement>( ".tts-preview-slider-input" );
  /* c8 ignore next */ // defensive: html`` always produces the range input.
  if ( input !== null ) {
    input.addEventListener( "input", () => {
      // parseFloat (not parseInt) — 12.5 / 37.5 / 62.5 / 87.5 must not truncate.
      const pct = parseFloat( input.value );
      handlers.onInput( pct );
    } );
  }

  return root;
}
