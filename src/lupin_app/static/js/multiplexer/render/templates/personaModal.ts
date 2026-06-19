/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node A — persona popover modal template.
//
// Renders a popover (HTML Popover API) for a sender's voice persona. The
// popover's id matches the `popovertarget` attribute on the
// `.sender-persona-badge` button rendered by senderCard.ts (Step A1) — the
// browser wires the click → open relationship declaratively.
//
// Element shape (per execution plan §3.A.4 Step A2):
//   <div id="persona-popover-${slug}" popover="auto" class="persona-popover">
//     <div class="persona-popover-accent" style="background-color:<color>"></div>
//     <div class="persona-popover-body">
//       <div class="persona-popover-name" style="color:<color>">{icon} {name}</div>
//       <div class="persona-popover-display-name" hidden?>{display_name}</div>  (omitted when same as name)
//       <div class="persona-popover-voice-id">Voice: {voice_id}</div>
//       <div class="persona-popover-borrowed" hidden?>Borrowed</div>
//     </div>
//     <button class="persona-popover-close" popovertarget="..." popovertargetaction="hide">×</button>
//   </div>
//
// `popover="auto"` enables light-dismiss (ESC + click-outside close
// automatically per Popover API spec).
//
// Color flow: persona color applied INLINE on .persona-popover-accent
// (background) and .persona-popover-name (color) per the plan §3.A.4 Step
// A2 explicit guidance — `var(--persona-color)` would inherit the sender
// card's value via cascading, but the popover lives in a separate portal
// (#persona-modal-portal) so the CSS var doesn't reach it. Inline style is
// the simplest cross-portal cascade.

import { slugifySenderId } from "./slugify";

/**
 * Input shape for the persona popover template — combines the SenderRecord's
 * `sender_id` with the persona fields. Per F-Arnold-2: signature is a
 * single combined input rather than (persona, sessionId) pair.
 */
export interface PersonaPopoverInput {
  sender_id     : string;
  name          : string;
  display_name? : string;
  voice_id      : string;
  icon          : string;
  color         : string;
  borrowed      : boolean;
}

/**
 * Render a persona-popover root for a single sender's voice persona.
 *
 * Requires:
 *   - `input.sender_id` is a non-empty string (caller's invariant).
 *   - The popover is appended to `#persona-modal-portal` by
 *     PersonaModalRenderer.
 *
 * Ensures:
 *   - Returns a `<div class="persona-popover">` with `popover="auto"` and
 *     `id="persona-popover-${slugifySenderId(input.sender_id)}"`.
 *   - Accent strip carries the inline persona color.
 *   - Name row shows `{icon} {name}` with the persona color.
 *   - `display_name` row is OMITTED when same as `name` or absent.
 *   - `voice_id` is always shown (Voice: ...).
 *   - Borrowed badge is hidden via the `hidden` attribute when
 *     `borrowed === false`.
 *   - Close button uses declarative `popovertargetaction="hide"` so the
 *     Popover API closes the modal without JS bookkeeping.
 *   - AC2e safe-write invariant: all DOM construction via
 *     document.createElement + setAttribute + textContent. No innerHTML.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderPersonaPopover( input: PersonaPopoverInput ): HTMLElement {
  const popoverId = `persona-popover-${slugifySenderId(input.sender_id)}`;

  const root = document.createElement("div");
  root.id = popoverId;
  root.className = "persona-popover";
  root.setAttribute("popover", "auto");

  // Accent strip — persona color flows via inline style.
  const accent = document.createElement("div");
  accent.className = "persona-popover-accent";
  accent.style.backgroundColor = input.color;
  root.appendChild(accent);

  // Body container.
  const body = document.createElement("div");
  body.className = "persona-popover-body";

  // Name row (icon + name; persona-color tint).
  const nameEl = document.createElement("div");
  nameEl.className = "persona-popover-name";
  nameEl.style.color = input.color;
  nameEl.textContent = input.icon === "" ? input.name : `${input.icon} ${input.name}`;
  body.appendChild(nameEl);

  // Display name (only when differs from name).
  if (input.display_name !== undefined && input.display_name !== input.name && input.display_name !== "") {
    const displayEl = document.createElement("div");
    displayEl.className = "persona-popover-display-name";
    displayEl.textContent = input.display_name;
    body.appendChild(displayEl);
  }

  // Voice ID (always shown — load-bearing for Phase 6 TTS routing context).
  const voiceEl = document.createElement("div");
  voiceEl.className = "persona-popover-voice-id";
  voiceEl.textContent = `Voice: ${input.voice_id}`;
  body.appendChild(voiceEl);

  // Borrowed badge — `hidden` attr toggled by `borrowed`.
  const borrowedEl = document.createElement("div");
  borrowedEl.className = "persona-popover-borrowed";
  borrowedEl.textContent = "Borrowed";
  if (!input.borrowed) borrowedEl.setAttribute("hidden", "");
  body.appendChild(borrowedEl);

  root.appendChild(body);

  // Close button — declarative Popover API close.
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "persona-popover-close";
  closeBtn.setAttribute("popovertarget", popoverId);
  closeBtn.setAttribute("popovertargetaction", "hide");
  closeBtn.setAttribute("aria-label", "Close persona details");
  closeBtn.textContent = "×";
  root.appendChild(closeBtn);

  return root;
}
