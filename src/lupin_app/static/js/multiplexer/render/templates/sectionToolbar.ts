/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer section-toolbar parity (2026-06-23, Rachel 🕊️ / Mr. Radio lane).
//
// Carbon-copy of the legacy notifications client's floating `#section-toolbar`
// (notifications.html:32-61) — per-section visibility toggles + a
// collapse-all / expand-all pair. Legacy class names are used VERBATIM
// (`.section-toolbar`, `.toolbar-btn`, `.task-accordion-btn`) so the shared
// appearance rules apply identically; the container ORIENTATION (horizontal
// top-bar) is a mux-shell adaptation styled by `#section-toolbar` in
// `css/multiplexer/section-toolbar.css` (legacy's vertical `position:fixed` is
// bound to its 1000px centred container and does not port).
//
// SCOPE NOTE: the legacy `.layout-mode-btn` (⇆) is intentionally OMITTED — the
// mux already ships that control standalone in `#reading-pane-toolbar`
// (ReadingPaneStore-backed). Duplicating it would be a regression. See
// `06-section-toolbar-and-accordion-toggle-design.md`.
//
// NO inline onclick (mux idiom): SectionToolbarRenderer wires all clicks via a
// single delegated listener on the returned `#section-toolbar` root.

import { html } from "../html";

// One per-section visibility toggle button. `sectionId` is the target section
// element's DOM id (the toggle adds/removes `.section-hidden` on it).
export interface SectionToggleSpec {
  sectionId : string;   // DOM id of the section element to show/hide
  icon      : string;   // button glyph
  title     : string;   // tooltip / a11y label
  testid    : string;   // data-testid for E2E selection
}

// The six mux sections the toolbar toggles (Mr. Radio-ratified list:
// notifications / jobs / commons / tts / fleet / task-list). Order follows the
// page's vertical section order for intuitive mapping.
export const SECTION_TOGGLES: ReadonlyArray<SectionToggleSpec> = [
  { sectionId: "notifications-pane",     icon: "💬",  title: "Notifications",   testid: "multiplexer-section-toolbar-notifications" },
  { sectionId: "jobs-pane",              icon: "📝",  title: "Jobs",            testid: "multiplexer-section-toolbar-jobs" },
  { sectionId: "commons-activity-pane",  icon: "📡",  title: "Recent Activity", testid: "multiplexer-section-toolbar-commons" },
  { sectionId: "tts-pane",               icon: "🔊",  title: "TTS Audio",       testid: "multiplexer-section-toolbar-tts" },
  { sectionId: "fleet-status-pane",      icon: "🛰️", title: "Fleet Status",    testid: "multiplexer-section-toolbar-fleet" },
  { sectionId: "task-list-pane",         icon: "🗒️", title: "Task List",       testid: "multiplexer-section-toolbar-task-list" },
];

// Stable ids for the two accordion-action buttons (used by the renderer's
// delegated click dispatch + by E2E selectors).
export const COLLAPSE_ALL_ID = "section-toolbar-collapse-all";
export const EXPAND_ALL_ID    = "section-toolbar-expand-all";

/**
 * Build the `#section-toolbar` element (collapse-all + expand-all, then the six
 * per-section visibility toggles).
 *
 * Requires:
 *   - `toggles` is the section spec list (defaults to SECTION_TOGGLES)
 *
 * Ensures:
 *   - Returns a `.section-toolbar#section-toolbar` element with, in order:
 *     a `.task-accordion-btn#section-toolbar-collapse-all`, a
 *     `.task-accordion-btn#section-toolbar-expand-all`, then one
 *     `.toolbar-btn[data-section]` per spec (rendered `.active` — the renderer
 *     dims any persisted-hidden section on mount).
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (default-param + return-type erasure).
export function renderSectionToolbar(
  toggles: ReadonlyArray<SectionToggleSpec> = SECTION_TOGGLES,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "section-toolbar";
  root.id        = "section-toolbar";
  root.setAttribute("role", "toolbar");
  root.setAttribute("aria-label", "Section visibility and accordion controls");

  /* c8 ignore next 3 */ // tagged-template literal: c8 reports phantom branches on interpolation positions; the runtime path is straight-line and exercised by every renderSectionToolbar test.
  const accordionControls = html`
    <button class="task-accordion-btn" id="${COLLAPSE_ALL_ID}" type="button"
            data-testid="multiplexer-section-toolbar-collapse-all"
            title="Collapse all accordions">⊟</button>
    <button class="task-accordion-btn" id="${EXPAND_ALL_ID}" type="button"
            data-testid="multiplexer-section-toolbar-expand-all"
            title="Expand all accordions">⊞</button>
  ` as DocumentFragment;
  root.appendChild(accordionControls);

  for (const spec of toggles) {
    /* c8 ignore next 6 */ // tagged-template literal: c8 reports phantom branches on every interpolation line ($-expressions); the per-spec button build is straight-line and covered by the template tests (default + custom toggles).
    const btn = html`
      <button class="toolbar-btn active" type="button"
              data-section="${spec.sectionId}"
              data-testid="${spec.testid}"
              title="${spec.title}">${spec.icon}</button>
    ` as DocumentFragment;
    root.appendChild(btn);
  }

  return root;
}
