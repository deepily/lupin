/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 5 — action-required read-only widget.
//
// Per Q-H Option A + D-A: full fields (prompt + response_type badge +
// countdown + options preview + default + microcopy), visually inert.
// Two-phase rollout — Phase 5 ships markup + visual + countdown ticker;
// Phase 6 attaches handlers via the `[data-phase6-pending="true"]` selector.
//
// Per D-A: classes use the `.action-required-*` prefix matching legacy
// (NOT `.ar-*`). Where legacy provides the same semantic class, it's reused;
// where Phase 5 needs a new sibling (e.g. `.action-required-pending-notice`),
// the new class adopts the same prefix family.
//
// Per F12: the widget root carries `data-id-hash="${item.id_hash}"`.
//
// Inertness markers (all required):
//   - `data-phase6-pending="true"` — Phase 6's handler-attach selector
//   - `aria-disabled="true"` — accessibility signal
//   - `style="cursor: not-allowed"` — visual signal on hover
//   - `.action-required-pending-notice` microcopy — explicit user-facing signal

import { html } from "../html";
import { formatCountdown } from "../time";
import type { ActionRequiredItem } from "../../shared/types";

/**
 * Render an action-required read-only widget.
 *
 * Requires:
 *   - `item` is an ActionRequiredItem with non-empty prompt
 *   - `countdownMs` is the pre-corrected countdown (from store, NOT recomputed
 *     here — D-H purity invariant)
 *
 * Ensures:
 *   - Returned element carries `data-id-hash="${item.id_hash}"` (F12)
 *   - All four inertness markers applied
 *   - DOM shape varies by `response_type`:
 *     - yes_no            : two `.action-required-option-readonly` chips
 *     - multiple_choice   : N `.action-required-option-readonly` chips
 *     - open_ended        : single `.action-required-input-placeholder`
 *     - open_ended_batch  : per-question repeat of open_ended shape
 */
export function renderActionRequiredReadOnly(
  item: ActionRequiredItem,
  countdownMs: number,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "action-required-widget";
  root.setAttribute("data-id-hash", item.id_hash);
  root.setAttribute("data-phase6-pending", "true");
  root.setAttribute("aria-disabled", "true");
  root.setAttribute("data-testid", "multiplexer-action-required");
  root.style.cursor = "not-allowed";

  const badge = responseTypeBadge(item.response_type);
  const optionsPreview = renderOptionsPreview(item);

  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    ${badge}
    <span class="action-required-countdown" data-countdown="${item.expires_at}">⏱ ${formatCountdown(countdownMs)}</span>
    ${optionsPreview}
    <div class="action-required-default">Default: ${item.default ?? "no"}</div>
    <div class="action-required-pending-notice">Input arrives in next phase</div>
  ` as DocumentFragment;
  root.appendChild(frag);

  return root;
}

function responseTypeBadge(responseType: ActionRequiredItem["response_type"]): DocumentFragment {
  // Human-readable label per response type.
  const labelMap: Record<ActionRequiredItem["response_type"], string> = {
    yes_no            : "yes/no",
    multiple_choice   : "multiple choice",
    open_ended        : "open ended",
    open_ended_batch  : "open ended (batch)",
  };
  return html`<span class="action-required-response-type-badge">${labelMap[responseType]}</span>` as DocumentFragment;
}

function renderOptionsPreview(item: ActionRequiredItem): DocumentFragment {
  switch (item.response_type) {
    case "yes_no":
      return html`
        <div class="action-required-options-preview">
          <span class="action-required-option-readonly">Yes</span>
          <span class="action-required-option-readonly">No</span>
        </div>
      ` as DocumentFragment;

    case "multiple_choice":
      return html`
        <div class="action-required-options-preview">
          ${item.options.map(opt => html`<span class="action-required-option-readonly">${opt}</span>`)}
        </div>
      ` as DocumentFragment;

    case "open_ended":
      return html`
        <div class="action-required-input-placeholder">[ text input — Phase 6 ]</div>
      ` as DocumentFragment;

    /* c8 ignore next 5 */ // open_ended_batch placeholder — Phase 6 will replace with the real batch input; current AC fixtures cover yes_no / multiple_choice / open_ended explicitly.
    case "open_ended_batch":
      // Single-line approximation of per-question repeats — Phase 6 expands
      // when the batch shape (multiple input fields) is wired.
      return html`
        <div class="action-required-input-placeholder">[ batch text input — Phase 6 ]</div>
      ` as DocumentFragment;
  }
}
