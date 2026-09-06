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

// The mux sections the toolbar toggles. Order follows the page's vertical
// section order for intuitive mapping.
//
// 🔴 THIS LIST IS HAND-MAINTAINED ON PURPOSE, AND IT IS GUARDED IN BOTH
// DIRECTIONS. It is the INDEPENDENT side of that guard — nobody generates it —
// which is exactly what lets the check fail. Deriving it from the panes would
// make the comparison a tautology: delete a pane and it also leaves the list it
// is checked against, so the guard would agree with itself and report nothing
// (María 🌸's ruling, 2026-09-05).
//
// ⚠️ `commons-activity-pane` is NOT declared in multiplexer.html — it lives in
// `broadcastCard.ts` and is injected at runtime. So this list is NOT a scrape of
// the page, and anyone "simplifying" the guard to the page alone would delete
// that entry and a working button with it.
//
// Adding a pane? Add it here. The guard is
// `src/tests/unit/multiplexer/the_hand_lists_are_checked_against_what_boot_reaches.test.ts`.
export const SECTION_TOGGLES: ReadonlyArray<SectionToggleSpec> = [
  { sectionId: "notifications-pane",     icon: "💬",  title: "Notifications",   testid: "multiplexer-section-toolbar-notifications" },
  { sectionId: "jobs-pane",              icon: "📝",  title: "Jobs",            testid: "multiplexer-section-toolbar-jobs" },
  { sectionId: "commons-activity-pane",  icon: "📡",  title: "Recent Activity", testid: "multiplexer-section-toolbar-commons" },
  { sectionId: "tts-pane",               icon: "🔊",  title: "TTS Audio",       testid: "multiplexer-section-toolbar-tts" },
  { sectionId: "fleet-status-pane",      icon: "🛰️", title: "Fleet Status",    testid: "multiplexer-section-toolbar-fleet" },
  { sectionId: "task-list-pane",         icon: "🗒️", title: "Task List",       testid: "multiplexer-section-toolbar-task-list" },
  // Added 2026-09-06 (Clayton 😎's F2). Both panes shipped with no way to hide
  // them while legacy carried both buttons — and the holding-area one is a Rick
  // voice ruling (2026-09-02, notifications.html:51-62): "we need a toggle
  // button in the Notifications Client Toolbar that hides and unhides the
  // holding area, it needs its own toggle button." Glyphs match legacy's.
  { sectionId: "holding-area-pane",      icon: "🗃️", title: "Holding Area",    testid: "multiplexer-section-toolbar-holding-area" },
  { sectionId: "epic-board-pane",        icon: "🗂️", title: "Epic Board",      testid: "multiplexer-section-toolbar-epic-board" },
];

// Stable ids for the two accordion-action buttons (used by the renderer's
// delegated click dispatch + by E2E selectors).
export const COLLAPSE_ALL_ID = "section-toolbar-collapse-all";
export const EXPAND_ALL_ID    = "section-toolbar-expand-all";

// Lane 0c (2026-07-02, Rachel 🕊️) — sections that are HIDDEN by default on a
// cold start (no persisted user preference). Legacy hides Job Queues by default
// (06 §3 Lane 0c, Q3 RULED). Their toolbar button renders NOT `.active` (dimmed)
// so the button state stays consistent with the pane's cold-hidden default; a
// persisted user choice overrides this (F-Clay-A3), reconciled by
// SectionToolbarRenderer on mount.
export const DEFAULT_HIDDEN_SECTION_IDS: ReadonlySet<string> = new Set( [ "jobs-pane" ] );

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
    // Cold-default-hidden sections render dimmed (no `.active`); all others
    // render `.active`. The renderer re-reconciles against persisted state on
    // mount (F-Clay-A3), so this is the no-flash cold-start appearance.
    const activeClass = DEFAULT_HIDDEN_SECTION_IDS.has( spec.sectionId ) ? "toolbar-btn" : "toolbar-btn active";
    /* c8 ignore next 6 */ // tagged-template literal: c8 reports phantom branches on every interpolation line ($-expressions); the per-spec button build is straight-line and covered by the template tests (default + custom toggles).
    const btn = html`
      <button class="${activeClass}" type="button"
              data-section="${spec.sectionId}"
              data-testid="${spec.testid}"
              title="${spec.title}">${spec.icon}</button>
    ` as DocumentFragment;
    root.appendChild(btn);
  }

  return root;
}
