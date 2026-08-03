/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer WP2 (parity bridge, 2026-06-10) — CC-session strip icon template.
//
// Renders one 40×40 persona icon for the CC-session strip, ported from the
// legacy `notifications.js:_addStripIcon` markup. Per the AC2e safe-write
// invariant (shared with focusTray.ts): NO `.innerHTML =`, NO `rawHTML(`, NO
// `.outerHTML =`. All construction uses the safe `html` tagged template +
// `style.setProperty()` for the persona-color cascade.
//
// The icon carries `data-id-hash="${sender_id}"` so SessionStripRenderer can
// drive it through the shared `keyedListMerge` helper (per its F12 invariant:
// every keyed element MUST carry data-id-hash). Focus + hide-inactive
// attributes (`data-focused`, `data-inactive-hidden`) are NOT baked here —
// they are renderer-UI state applied in a separate reconcile pass.

import { html } from "../html";
import type { ManagerPersona, StripSession } from "../../shared/types";

/**
 * Derive the single-character icon initial from a persona name.
 *
 * Mirrors legacy `notifications.js:9958-9963` (first char, uppercased).
 *
 * Requires:
 *   - `name` is any string (possibly empty / whitespace).
 * Ensures:
 *   - Returns one uppercase character, or "?" when `name` has no leading
 *     non-whitespace character.
 */
export function personaInitial(name: string): string {
  const trimmed = name.trim();
  if (trimmed === "") return "?";
  return trimmed.charAt(0).toUpperCase();
}

/**
 * Idempotently apply (or clear) the manager-lineage badge on an icon button.
 *
 * Shared by both initial render and WP9's live-patch path. Always removes any
 * existing `.cc-strip-manager-badge` child first (idempotency), then re-adds
 * when `managerPersona` is non-null.
 *
 * Requires:
 *   - `button` is a `.cc-strip-icon` element.
 *   - `managerPersona` is the lineage data, or null to clear.
 * Ensures:
 *   - At most one `.cc-strip-manager-badge` child exists afterward.
 *   - `data-has-manager` reflects badge presence.
 *   - The badge text is the manager's derived initial; `--manager-color` is
 *     set to the manager color; `title` reads "Spawned by <name>".
 */
export function applyManagerBadge(button: HTMLElement, managerPersona: ManagerPersona | null): void {
  const existing = button.querySelector(".cc-strip-manager-badge");
  if (existing !== null) existing.remove();

  if (managerPersona === null) {
    button.removeAttribute("data-has-manager");
    return;
  }

  const name  = managerPersona.name;
  const label = name === "" ? "manager" : name;
  const badgeFrag = html`<span class="cc-strip-manager-badge" title="${`Spawned by ${label}`}">${personaInitial(name)}</span>` as DocumentFragment;
  const badge = badgeFrag.querySelector(".cc-strip-manager-badge") as HTMLElement;
  if (managerPersona.color !== "") {
    badge.style.setProperty("--manager-color", managerPersona.color);
  }
  button.appendChild(badge);
  button.setAttribute("data-has-manager", "true");
}

/**
 * Derive the allocation-status flag for a strip session (V9).
 *
 * Ported from the legacy strip-icon sub-badge system (notifications.js
 * :5087-5106 / :10930-10973), driven by the two server-verified inputs
 * `voice_persona.borrowed` + `StripSession.active`: a session whose persona is
 * BORROWED, or whose session is INACTIVE (released), carries a 🔉
 * allocation-status indicator; a normal active own-persona session carries
 * none. `borrowed` takes precedence over `inactive` (both render the same 🔉
 * glyph, so precedence only fixes the reported status string).
 *
 * Requires:
 *   - `session` is a StripSession with a populated `voice_persona`.
 * Ensures:
 *   - Returns "borrowed" when the persona is borrowed;
 *   - else "inactive" when the session is not active;
 *   - else null (no indicator).
 */
export function stripAllocStatus(session: StripSession): "borrowed" | "inactive" | null {
  if (session.voice_persona.borrowed) return "borrowed";
  if (!session.active) return "inactive";
  return null;
}

/**
 * Apply (or clear) the allocation-status attribute on a strip-icon button (V9).
 *
 * `data-alloc-status` drives the CSS `::before` 🔉 indicator
 * (session-strip.css) — the same data-attribute-driven pattern legacy used for
 * its `.cc-strip-icon[data-...]::before` sub-badges. Idempotent: removes the
 * attribute when the session carries no allocation flag.
 *
 * Requires:
 *   - `button` is a `.cc-strip-icon` element.
 *   - `session` is the session it represents.
 * Ensures:
 *   - `data-alloc-status` reflects `stripAllocStatus(session)` — set to the
 *     status string, or removed when null.
 */
export function applyAllocStatus(button: HTMLElement, session: StripSession): void {
  const status = stripAllocStatus(session);
  if (status === null) {
    button.removeAttribute("data-alloc-status");
    return;
  }
  button.setAttribute("data-alloc-status", status);
}

/**
 * Render one CC-session strip icon button for a strip session.
 *
 * Requires:
 *   - `session` is a StripSession with a populated `voice_persona`.
 * Ensures:
 *   - Returns a `<button class="cc-strip-icon">` carrying
 *     `data-id-hash` + `data-sender-id` = session.sender_id,
 *     `data-active` = String(session.active), the persona initial in a
 *     `.cc-strip-initial` child span (kept separate from the badge so
 *     in-place updates don't clobber it), `--persona-color` set (when the
 *     persona has a color), `title` = persona name, and a manager-lineage
 *     badge child when `session.manager_persona` is present.
 */
export function renderSessionStripIcon(session: StripSession): HTMLElement {
  const persona = session.voice_persona;
  const title   = persona.name === "" ? session.sender_id : persona.name;

  const frag = html`
    <button class="cc-strip-icon"
            type="button"
            data-id-hash="${session.sender_id}"
            data-sender-id="${session.sender_id}"
            data-active="${String(session.active)}"
            title="${title}"
            style="background-color: var(--persona-color, #888);"><span class="cc-strip-initial">${personaInitial(persona.name)}</span></button>
  ` as DocumentFragment;

  const button = frag.querySelector(".cc-strip-icon") as HTMLElement;
  if (persona.color !== "") {
    button.style.setProperty("--persona-color", persona.color);
  }
  applyManagerBadge(button, session.manager_persona ?? null);
  applyAllocStatus(button, session);

  return button;
}

/**
 * Refresh an already-rendered strip icon in place from the (possibly changed)
 * session — used by SessionStripRenderer's keyed-merge update path on
 * re-assignment. Touches only the persona-derived surfaces; leaves
 * renderer-UI attributes (`data-focused`, `data-inactive-hidden`) alone.
 *
 * Requires:
 *   - `button` is the existing `.cc-strip-icon` for `session.sender_id`.
 * Ensures:
 *   - `data-active`, `title`, `--persona-color`, the `.cc-strip-initial` text,
 *     and the manager badge all reflect the current session.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function updateSessionStripIcon(button: HTMLElement, session: StripSession): void {
  const persona = session.voice_persona;
  button.setAttribute("data-active", String(session.active));
  button.setAttribute("title", persona.name === "" ? session.sender_id : persona.name);

  if (persona.color !== "") {
    button.style.setProperty("--persona-color", persona.color);
  } else {
    button.style.removeProperty("--persona-color");
  }

  const initialEl = button.querySelector(".cc-strip-initial");
  if (initialEl !== null) initialEl.textContent = personaInitial(persona.name);

  applyManagerBadge(button, session.manager_persona ?? null);
  applyAllocStatus(button, session);
}
