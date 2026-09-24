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

// One per-section visibility toggle button.
//
// 🔴 THREE THINGS USED TO BE ONE STRING, AND THEY ARE NOT THE SAME THING (A-2 #4).
// `sectionId` was simultaneously the DOM handle, the list of elements to hide, and the
// localStorage key. Notifications is the section that proves they differ: legacy wraps its
// header and body in ONE `#section-notifications` (notifications.html:478), while this page
// made them SIBLINGS, so `💬` must hide two elements. Splitting the roles:
//
//   sectionId    the DOM handle. Stays a SINGLE, RESOLVABLE element id, because it is what
//                `data-section` carries and two e2e guards read it as one — the chevron
//                guard does `page.locator( f"#{pane}" )` off this attribute
//                (test_multiplexer_section_chevron_keyboard.py:102-103) and the toolbar
//                guard hand-copies these values into an ORDERED expected list
//                (test_multiplexer_section_toolbar.py:43). A list or a non-element key here
//                reddens both, and the chevron one would fail as "section not found" —
//                a coordinate failure wearing a defect's clothes.
//   sectionIds   EVERY element the button shows and hides. Absent ⇒ just `sectionId`.
//   persistKey   where the preference is stored. Absent ⇒ `sectionId`, which is what every
//                single-element entry has always used, so none of them changes.
//
// 🔴 THE KEY IS `notifications-header-and-pane` AND THE OBVIOUS NAMES WERE BOTH TAKEN.
// My first choice was `notifications-section` — which María 🌸 caught (2026-09-23): that is a
// LIVE ELEMENT ID in the legacy client (`notifications.html:530`, and
// test_broadcast_panel.py does getElementById on it). A "fresh" key that is somebody else's
// element id is worse than the old one: grep it and you cannot tell a storage key from an
// accordion body. `notifications-toggle` is an element id too. Measured, not guessed:
// `notifications-header-and-pane` appears NOWHERE in src/lupin_app or src/tests.
//
// It is clunky, and that is the trade taken deliberately — it names the two things it
// actually governs, which is Rick's own criterion, and a storage key is read in a debugger
// rather than aloud.
//
// ⚠️ `persistKey` IS FRESH FOR NOTIFICATIONS ON RICK'S DIRECT RULING (2026-09-19 ~19:10 EDT,
// plan §6a item 9), which REVERSED the earlier "keep the first id so saved preferences
// survive". A key should name the thing it controls, and a one-time reset of saved collapse
// state is the accepted price. The row manifest still carries the superseded version.
//
// 🔴 SO NOTIFICATIONS' SAVED PREFERENCE RESETS ONCE, ON FIRST LOAD AFTER THIS SHIPS. That is
// the ruling being honoured, NOT a bug. Do not "fix" it by falling back to the old key.
export interface SectionToggleSpec {
  sectionId  : string;   // DOM id of the section element — the `data-section` handle
  icon       : string;   // button glyph
  title      : string;   // tooltip / a11y label
  testid     : string;   // data-testid for E2E selection
  /** Every element this button shows/hides. Omitted ⇒ `[ sectionId ]`. */
  sectionIds?: ReadonlyArray<string>;
  /** Where the preference is stored. Omitted ⇒ `sectionId`. */
  persistKey?: string;
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
  // Added 2026-09-16 (parity A-2 #2a, Phase 2 A3 B4). Action Required had no
  // button, so an operator could not hide it; legacy's ⚠️ (notifications.html:45)
  // ships active. First, because the section is first on the page. It is a
  // `<div id="…-section">`, which is why the hand-list guard's page sweep had to
  // widen before it could notice the gap.
  { sectionId: "action-required-section", icon: "⚠️", title: "Action Required", testid: "multiplexer-section-toolbar-action-required" },
  // A-2 #4 — the ONE entry that owns two mounts. The header region is a SIBLING of the pane
  // here (multiplexer.html:171 vs :188), not a wrapper as in legacy, so `💬` must name both
  // or it hides the body and leaves the title bar floating. `sectionId` stays the pane: it is
  // the `data-section` handle two e2e guards resolve as an element id.
  { sectionId: "notifications-pane",     icon: "💬",  title: "Notifications",   testid: "multiplexer-section-toolbar-notifications",
    sectionIds: [ "notifications-pane", "notifications-header-region" ],
    persistKey: "notifications-header-and-pane" },
  { sectionId: "jobs-pane",              icon: "📋",  title: "CJ Flow Jobs",    testid: "multiplexer-section-toolbar-jobs" },
  { sectionId: "commons-activity-pane",  icon: "📡",  title: "Recent Activity", testid: "multiplexer-section-toolbar-commons" },
  { sectionId: "tts-pane",               icon: "🔊",  title: "TTS Audio",       testid: "multiplexer-section-toolbar-tts" },
  { sectionId: "fleet-status-pane",      icon: "🛰️", title: "Fleet Status",    testid: "multiplexer-section-toolbar-fleet" },
  // Added 2026-09-07 (row 470b7509). Placed between fleet and task-list to
  // follow the page's vertical order, which is what this list's own header
  // comment asks of a new entry.
  { sectionId: "finished-tasks-pane",    icon: "✅", title: "Finished Tasks",  testid: "multiplexer-section-toolbar-finished-tasks" },
  { sectionId: "task-list-pane",         icon: "🗒️", title: "Task List",       testid: "multiplexer-section-toolbar-task-list" },
  // Added 2026-09-06 (Clayton 😎's F2). Both panes shipped with no way to hide
  // them while legacy carried both buttons — and the holding-area one is a Rick
  // voice ruling (2026-09-02, notifications.html:51-62): "we need a toggle
  // button in the Notifications Client Toolbar that hides and unhides the
  // holding area, it needs its own toggle button." Glyphs match legacy's.
  { sectionId: "holding-area-pane",      icon: "🗃️", title: "Holding Area",    testid: "multiplexer-section-toolbar-holding-area" },
  { sectionId: "epic-board-pane",        icon: "🗂️", title: "Epic Board",      testid: "multiplexer-section-toolbar-epic-board" },
  // ---------------------------------------------------------------------
  // Phase B pre-allocation (register item 7, row f0e00f01, 2026-09-17).
  //
  // Seven entries for the seven sections Phase B will build. They ship with
  // the mounts in ONE commit because the hand-list guard asserts both
  // directions: a pane with no toggle reddens it, and a toggle naming no pane
  // reddens it too. Split across two commits, either order is red in between.
  //
  // Glyphs are the LEAD's, measured at notifications.html:43-44 and :69-74, so
  // an operator moving between the two pages reads the same symbol for the same
  // section. None collides with the ten above.
  //
  // ⚠️ THE SEVENTH LEGACY GLYPH IS DELIBERATELY ABSENT. Legacy's 📋
  // (`section-queues`) is the queue display, which this page already ships as
  // `jobs-pane` carrying that same 📋 — so six of the lead's seven toolbar rows
  // are new sections and one was built long ago. Adding a second 📋 would give
  // the operator two buttons for one pane.
  //
  // 🔴 THESE PAINT SEVEN MORE 36×36 BUTTONS. The toolbar is `flex-wrap:wrap`
  // at `width:max-content`, so ten buttons measure 414px and seventeen measure
  // 694px; the height is unchanged at 50px while it stays one row and grows
  // 40px per row if it wraps. NO VISUAL BASELINE WATCHES THIS TOOLBAR — all 37
  // baselines are element-scoped or page-level captures that exclude it — so a
  // wrap here would move every pane down 40px with nothing going red. Measure
  // the rendered width when adding an entry; do not assume the row still fits.
  { sectionId: "qa-pane",                icon: "❓", title: "Q&A Interface",   testid: "multiplexer-section-toolbar-qa" },
  { sectionId: "submit-jobs-pane",       icon: "📝", title: "Submit Agentic Jobs", testid: "multiplexer-section-toolbar-submit-jobs" },
  { sectionId: "filter-settings-pane",   icon: "⚙️", title: "Filter Settings (Admin)", testid: "multiplexer-section-toolbar-filter-settings" },
  { sectionId: "time-saved-pane",        icon: "⏱️", title: "Time Saved",      testid: "multiplexer-section-toolbar-time-saved" },
  { sectionId: "system-status-pane",     icon: "📊", title: "System Status",   testid: "multiplexer-section-toolbar-system-status" },
  { sectionId: "debug-pane",             icon: "🐛", title: "Debug Information", testid: "multiplexer-section-toolbar-debug" },
  { sectionId: "direct-tts-pane",        icon: "🔧", title: "Direct TTS Test", testid: "multiplexer-section-toolbar-direct-tts" },
];

// The two accordion-action buttons (collapse-all / expand-all) and their id
// constants were REMOVED on 2026-09-15: Rick ruled, on a direct ask, that this
// toolbar carries section-visibility toggles and that the collapse/expand pair
// comes off BOTH toolbars — the legacy task-owner pair and this accordion pair.
// ViewStateStore.requestBulkAccordionCollapse() is left in place and still
// tested, but nothing calls it now; NotificationsListRenderer still listens for
// the event it emits.

// 🔴 THERE IS NO COLD-HIDDEN SECTION, AND `DEFAULT_HIDDEN_SECTION_IDS` IS GONE
// (2026-09-23, row cec9dd43). Every button ships `.active`; only a persisted
// user preference dims one, applied by SectionToolbarRenderer on mount.
//
// The set existed to carry ONE member, `filter-settings-pane`, and that member
// was a misreading of the legacy page. Measured in notifications.html:
//
//   all 15 `.toolbar-btn`     ship `class="toolbar-btn active"`, the ⚙️ Filter
//                             Settings one included (:69)
//   `.section-hidden` at load appears ZERO times
//
// So legacy cold-starts with every section on axis 2 VISIBLE, Filter Settings
// among them. What made it look otherwise is `style="display: none;"` on
// `#filter-settings-section` (:1123) — but that is AXIS 1, the admin gate: a
// pre-role placeholder that `initializeFilterUI` overwrites from `isAdmin`
// alone (notifications.js:6404 `block` / :6423 `none`). Reading it as an axis-2
// cold default put the gate on a second axis that has no admin condition, so
// the pane came up hidden for EVERYONE — admins included, which is the whole
// point of the pane (María 🌸, 2026-09-23).
//
// ⚠️ The A-2 #1 note this replaces was RIGHT about Jobs for the same reason it
// was wrong about Filter Settings: it checked legacy's Job Queues button for
// `active` (:70) and never checked the ⚙️ button two lines up. Jobs' glyph
// moved 📝 → 📋 in that change (R6) and stays; 📝 is Submit Agentic Jobs (B-2).
//
// ⇒ Adding a genuinely cold-hidden section later means reintroducing this
// concept, not editing a set: nothing here approximates it any more. Check
// the legacy button for `active` FIRST — that, not an inline `display`, is
// where axis 2 states its cold default.

/**
 * Build the `#section-toolbar` element (the per-section visibility toggles).
 *
 * Requires:
 *   - `toggles` is the section spec list (defaults to SECTION_TOGGLES)
 *
 * Ensures:
 *   - Returns a `.section-toolbar#section-toolbar` element holding one
 *     `.toolbar-btn[data-section]` per spec, every one rendered `.active` —
 *     the renderer dims any persisted-hidden section on mount
 *   - holds NO `.task-accordion-btn`: the collapse-all / expand-all pair came
 *     off both toolbars on Rick's 2026-09-15 ruling
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (default-param + return-type erasure).
export function renderSectionToolbar(
  toggles: ReadonlyArray<SectionToggleSpec> = SECTION_TOGGLES,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "section-toolbar";
  root.id        = "section-toolbar";
  root.setAttribute("role", "toolbar");
  root.setAttribute("aria-label", "Section visibility controls");

  for (const spec of toggles) {
    // Every button renders `.active`, as all 15 of legacy's do. The renderer
    // re-reconciles against persisted state on mount (F-Clay-A3) and dims the
    // ones the user hid, so this is the no-flash cold-start appearance.
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
