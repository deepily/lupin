/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node B — focus tray template.
//
// Renders the list-of-hidden-senders surface for focus mode. Per Q-Section-B
// design + F-Arnold-B-Stage2-2: each row is a clickable button carrying the
// hidden sender's persona-color via `--persona-color` CSS custom property,
// with `currentColor` as the fallback when no persona is assigned. The
// click handler is owned by FocusTrayRenderer via event delegation (per
// OSQ-B-2: clicking a row exits focus mode).
//
// AC2e safe-write invariant: NO `.innerHTML =`, NO `rawHTML(`, NO
// `.outerHTML =`. All DOM construction uses the safe `html` tagged
// template + `style.setProperty()` for the persona-color flow.

import { html } from "../html";
import type { SenderRecord } from "../../shared/types";

/**
 * Render the focus-tray list contents for a snapshot of hidden senders.
 *
 * Requires:
 *   - `hiddenSenders` is the senders currently hidden by focus mode
 *     (caller derives this list from `SenderStore.list()` filtered against
 *     the pinned sender id).
 *
 * Ensures:
 *   - Returns a single `<div class="focus-tray-list">` root containing
 *     either one `<button class="focus-tray-row">` per hidden sender OR a
 *     single `<div class="focus-tray-empty">` placeholder when the list
 *     is empty.
 *   - Each row carries `data-sender-id` for click-delegation routing.
 *   - Each row carries an inline `style="color: var(--persona-color, currentColor);"`
 *     so the persona-color cascade works even when style files are
 *     load-order-sensitive (per F-Arnold-B-Stage2-2 currentColor fallback).
 *   - Each row's `--persona-color` is set via `style.setProperty()` AFTER
 *     template render when the sender carries a voice_persona; senders
 *     without a persona fall through to `currentColor`.
 */
export function renderFocusTray( hiddenSenders: ReadonlyArray<SenderRecord> ): HTMLElement {
  const root = document.createElement("div");
  root.className = "focus-tray-list";

  if (hiddenSenders.length === 0) {
    const emptyFrag = html`<div class="focus-tray-empty">No senders hidden by focus mode.</div>` as DocumentFragment;
    root.appendChild(emptyFrag);
    return root;
  }

  for (const sender of hiddenSenders) {
    const persona = sender.voice_persona;
    const icon    = persona?.icon ?? "";
    const name    = sender.display_name || sender.sender_id;
    const label   = icon === "" ? name : `${icon} ${name}`;

    /* c8 ignore next 5 */ // tagged-template-literal phantom branch: c8 attributes an internal `html` function value-coercion branch to this multi-line interpolation. The template has 5 interpolations (sender_id × label) all exercised by templates_focus_tray.test.ts; the html function's own branches are covered by html.test.ts.
    const rowFrag = html`
      <button class="focus-tray-row"
              data-sender-id="${sender.sender_id}"
              type="button"
              style="color: var(--persona-color, currentColor);">${label}</button>
    ` as DocumentFragment;

    const button = rowFrag.querySelector(".focus-tray-row") as HTMLElement;
    if (persona !== undefined && persona.color !== "") {
      // CSS custom property cascade: sets --persona-color ON the button
      // itself; the inline `color: var(--persona-color, currentColor)` then
      // resolves to this value. Falls through to currentColor when persona
      // is absent.
      button.style.setProperty("--persona-color", persona.color);
    }

    root.appendChild(rowFrag);
  }

  return root;
}
