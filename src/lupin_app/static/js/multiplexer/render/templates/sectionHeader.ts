/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane 0a (2026-07-02, Rachel 🕊️) — sectionHeader template.
//
// The uniform collapsible `.section-header` bar the 6 multiplexer accordions
// lacked (06 §3 Lane 0a / 07 §3.A). ONE builder → the legacy `.section-header`
// contract (icon + title + count + cursor:pointer + collapse chevron), so every
// accordion renders class-compatible chrome and the Layout-Parity Oracle
// measures one shape. The visual skin (solid bg, per-section colors) lives in
// the shared sheet (css/shared/notifications-surface.css); this file owns only
// the DOM structure + the session-only collapse behavior.
//
// Collapse idiom (07 §3.A U-A3): SESSION-ONLY `data-collapsed` on the SECTION
// ROOT (NOT the localStorage `taskListCollapse`; NOT the legacy `.collapsed`
// on the content). The shared sheet hides `[data-collapsed="true"] >
// .section-content`. The chevron is a `<span>` (not a `<button>`) so the
// collapse click-guard — "ignore clicks on real controls (button/a/input/
// select)" — still lets a chevron click collapse, mirroring the legacy mux
// idiom (NotificationsListRenderer's toggleSenderCard/toggleDateAccordion).

// A control the caller wants in the header's right-hand actions slot (refresh,
// clear-all, history-dropdown, updated-stamp, …). Appended in array order,
// BEFORE the collapse chevron (which stays rightmost).
export type SectionHeaderAction = HTMLElement;

export interface SectionHeaderOptions {
  /** Leading glyph (e.g. "🔔", "🛰️"). */
  icon    : string;
  /** Human title (e.g. "Notifications"). */
  title   : string;
  /** data-testid on the `.section-header` element (optional). */
  testid? : string;
  /**
   * Renderer-specific controls placed in `.section-header-actions` (left of the
   * chevron). Their own click handlers own their clicks — a click on any of
   * these does NOT collapse the section (they are `<button>`/`<a>`/`<input>`).
   */
  actions?: ReadonlyArray<SectionHeaderAction>;
}

export interface SectionHeaderHandle {
  /** The `.section-header` element (a persistent sibling above the body). */
  header    : HTMLElement;
  /** The `.section-header-count` span — update via setCount(). */
  countEl   : HTMLElement;
  /** The `.section-header-actions` container (for later dynamic controls). */
  actionsEl : HTMLElement;
  /** The `.toggle-button` chevron span (glyph flips ▼/▶ on collapse). */
  toggleEl  : HTMLElement;
  /** Set the count chip text (number or pre-formatted string). */
  setCount( value: number | string ): void;
}

/**
 * Build a uniform `.section-header` bar.
 *
 * Requires:
 *   - opts.icon / opts.title are strings
 * Ensures:
 *   - returns a handle whose `.header` is a `.section-header` element containing
 *     an `<h3>` (icon + title + `.section-header-count`), a
 *     `.section-header-actions` slot (the given actions), and a `.toggle-button`
 *     chevron (▼, expanded) as the rightmost child of the actions slot.
 */
export function renderSectionHeader( opts: SectionHeaderOptions ): SectionHeaderHandle {
  const header = document.createElement( "div" );
  header.className = "section-header";
  if ( opts.testid !== undefined ) header.setAttribute( "data-testid", opts.testid );

  const h3 = document.createElement( "h3" );
  h3.append( `${opts.icon} ${opts.title} ` );

  const countEl = document.createElement( "span" );
  countEl.className = "section-header-count";
  h3.appendChild( countEl );
  header.appendChild( h3 );

  const actionsEl = document.createElement( "div" );
  actionsEl.className = "section-header-actions";
  if ( opts.actions !== undefined ) {
    for ( const control of opts.actions ) actionsEl.appendChild( control );
  }

  const toggleEl = document.createElement( "span" );
  toggleEl.className = "toggle-button";
  toggleEl.setAttribute( "role", "button" );
  toggleEl.setAttribute( "aria-label", "Collapse section" );
  toggleEl.textContent = "▼";
  actionsEl.appendChild( toggleEl );

  header.appendChild( actionsEl );

  return {
    header,
    countEl,
    actionsEl,
    toggleEl,
    setCount( value ) { countEl.textContent = String( value ); },
  };
}

/**
 * Apply a collapsed decision to a section: flip `data-collapsed` on the section
 * root + the chevron glyph. The shared sheet hides the body when collapsed.
 */
export function setSectionCollapsed(
  section: HTMLElement,
  handle : SectionHeaderHandle,
  collapsed: boolean,
): void {
  section.setAttribute( "data-collapsed", collapsed ? "true" : "false" );
  handle.toggleEl.textContent = collapsed ? "▶" : "▼";
}

/**
 * Wire session-only collapse: a click anywhere on the header toggles the
 * section's collapsed state, EXCEPT a click on a real interactive control
 * (button/a/input/select) in the actions slot — those own their own clicks. The
 * chevron is a `<span>`, so a chevron click collapses (as intended).
 *
 * Returns an unsubscribe fn (removes the listener) for lifecycle cleanup.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-type return annotation.
export function wireSectionCollapse(
  section: HTMLElement,
  handle : SectionHeaderHandle,
): () => void {
  const onClick = ( e: Event ): void => {
    const target = e.target as Element | null;
    /* c8 ignore next */ // defensive: a dispatched click always carries a target; guards synthetic events.
    if ( target === null ) return;
    // A click on a real control (its own handler owns it) does not collapse.
    if ( target.closest( "button, a, input, select" ) !== null ) return;
    const collapsed = section.getAttribute( "data-collapsed" ) === "true";
    setSectionCollapsed( section, handle, !collapsed );
  };
  handle.header.addEventListener( "click", onClick );
  return () => handle.header.removeEventListener( "click", onClick );
}
