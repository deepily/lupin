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
// Collapse idiom (07 §3.A U-A3): `data-collapsed` on the SECTION ROOT (NOT the
// localStorage `taskListCollapse`; NOT the legacy `.collapsed` on the content).
// The shared sheet hides `[data-collapsed="true"] > .section-content`.
//
// SESSION-ONLY UNLESS THE CALLER OPTS IN (parity A-2 #6), mirroring legacy's
// `LUPIN_ACCORDION_PERSIST_KEYS` (notifications.html:1527-1541) — a map holding
// exactly three sections, so legacy's rule is "persist the named few, and the
// rest are session-only". `wireSectionCollapse`'s third argument is that map,
// expressed per-call-site: pass one and the section's collapse survives a
// reload, omit it and nothing is stored. Of the 8 consumers here only
// FinishedTasksRenderer passes one, because `finished-tasks-section` is the one
// section legacy's map and this client have in common.
//
// 🔴 POLARITY: legacy stores isOPEN, `ViewStateStore` stores isCOLLAPSED, and
// the two clients keep their own settled conventions rather than one borrowing
// the other's. The BEHAVIOUR is mirrored (the state survives a reload, a
// missing key means the HTML default); the stored byte is not, and copying a
// value across would invert it. The legacy file carries the same warning at its
// own point of definition for the same reason.
//
// 🔴 THE CHEVRON IS A `<button>`, AND IT USED TO BE A `<span>` FOR A REASON THAT
// COST KEYBOARD ACCESS. Rick ruled 2026-09-06 (divergence #5): the mux must
// match legacy's `button.toggle-button`, because a `<span role="button">` with
// no `tabindex` CANNOT BE FOCUSED — measured on both clients, legacy's toggle
// takes focus and the mux's did not, so a keyboard user could reach legacy's
// collapse and not the mux's. `role="button"` announces a control; it does not
// make one.
//
// ⚠️ AND THE SWAP IS NOT A ONE-WORD EDIT — the old comment here was right about
// the mechanism. `wireSectionCollapse` ignores clicks on `button, a, input,
// select` so real controls own their own clicks; make the chevron a `<button>`
// and that guard swallows chevron clicks, so the fix for the keyboard user
// would have BROKEN the mouse user. The guard therefore carries an explicit
// exception for `.toggle-button`, and a test holds both halves.

// A control the caller wants in the header's right-hand actions slot (refresh,
// clear-all, history-dropdown, updated-stamp, …). Appended in array order,
// BEFORE the collapse chevron (which stays rightmost).
export type SectionHeaderAction = HTMLElement;

export interface SectionHeaderOptions {
  /** Leading glyph (e.g. "🔔", "🛰️"), or "" for none (no glyph, no leading space). */
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
  /** The `.toggle-button` chevron BUTTON (glyph flips ▼/▶ on collapse). */
  toggleEl  : HTMLElement;
  /** Set the count chip text (number or pre-formatted string). */
  setCount( value: number | string ): void;
  /**
   * Replace the icon + title before the count chip, formatted exactly as the
   * builder formats them (an empty icon renders the bare title). For a bar
   * whose title follows state — the TTS bar reads "Paused" (parity A-2 #3d).
   */
  setTitle( icon: string, title: string ): void;
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
  // An empty icon renders the bare title — the CC Notifications bar carries
  // legacy's "Claude Code Notifications:" with no glyph (Rick's ruling 3, 2026-09-10).
  // One text node, kept so setTitle() can rewrite it in place.
  const titleNode = document.createTextNode( formatTitle( opts.icon, opts.title ) );
  h3.appendChild( titleNode );

  const countEl = document.createElement( "span" );
  countEl.className = "section-header-count";
  h3.appendChild( countEl );
  header.appendChild( h3 );

  const actionsEl = document.createElement( "div" );
  actionsEl.className = "section-header-actions";
  if ( opts.actions !== undefined ) {
    for ( const control of opts.actions ) actionsEl.appendChild( control );
  }

  // A REAL button, matching legacy's `button.toggle-button` — focusable, in the
  // tab order, and Enter/Space activated by the platform rather than by us.
  // `type="button"` so it can never submit an enclosing form. No `role` — a
  // button already has one, and restating it is how a wrong role outlives a
  // tag change.
  const toggleEl = document.createElement( "button" );
  toggleEl.type = "button";
  toggleEl.className = "toggle-button";
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
    setTitle( icon, title ) { titleNode.data = formatTitle( icon, title ); },
  };
}

function formatTitle( icon: string, title: string ): string {
  return icon === "" ? `${title} ` : `${icon} ${title} `;
}

/**
 * Should a click on the header collapse the section?
 *
 * ONE predicate, exported, because there are TWO collapse call sites and they
 * had drifted into two hand-written copies of this rule. Changing the chevron
 * from a `<span>` to a `<button>` (Rick's divergence #5) broke the copy that was
 * not edited — the header still collapsed from the bar and the CHEVRON stopped
 * working, which is the shape a user reads as "the toggle is broken". A rule
 * living in two places is a rule that will be half-changed.
 *
 * Requires:
 *   - target is the click's target element, or null
 *   - toggleEl is THIS header's chevron
 *
 * Ensures:
 *   - false for a null target (a synthetic event with no target)
 *   - false for a click on a real control (button/a/input/select) that is NOT
 *     this header's chevron — those controls own their own clicks
 *   - true for the chevron itself, whose only job IS to collapse
 *   - 🔴 IDENTITY, NOT CLASS. `.toggle-button` is worn by at least one unrelated
 *     control (`broadcastCard.ts`'s `#broadcast-submit-toggle`), so a
 *     class-keyed carve-out would hand that button's clicks to the wrong
 *     handler. The chevron is identified by BEING this header's chevron.
 *   - true for anything else on the header bar (the background click)
 */
export function headerClickShouldCollapse( target: Element | null, toggleEl: HTMLElement ): boolean {
  /* c8 ignore next */ // defensive: a dispatched click always carries a target; guards synthetic events.
  if ( target === null ) return false;
  const control = target.closest( "button, a, input, select" );
  if ( control === null ) return true;
  return control === toggleEl || toggleEl.contains( control );
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
 * The slice of `ViewStateStore` a persisted section needs — the accordion flags,
 * and nothing else.
 *
 * Structural, not the whole store, so a call site cannot reach past collapse
 * into section visibility or the bulk-collapse emit, and a test can supply two
 * methods instead of standing up a store.
 */
export interface AccordionCollapseStore {
  /** True only when this id was explicitly collapsed. Default: expanded. */
  isAccordionCollapsed( accordionId: string ): boolean;
  /** Persist this id's collapsed state. Silent (no emit). */
  setAccordionCollapsed( accordionId: string, collapsed: boolean ): void;
}

/**
 * A caller's OPT-IN to persistence: which accordion id to store under, and the
 * store to put it in. One entry of legacy's `LUPIN_ACCORDION_PERSIST_KEYS`,
 * handed to the call site that owns that section instead of held in a central map.
 */
export interface SectionCollapsePersist {
  /** The `ViewStateStore` accordion id — legacy's section id, e.g. "finished-tasks-section". */
  key  : string;
  store: AccordionCollapseStore;
}

/**
 * Wire collapse: a click anywhere on the header toggles the section's collapsed
 * state, EXCEPT a click on a real interactive control (button/a/input/select) in
 * the actions slot — those own their own clicks.
 *
 * 🔴 THE CHEVRON IS THE ONE EXCEPTION TO THE EXCEPTION. It is a `<button>` (so a
 * keyboard user can reach it, which a `<span role="button">` never allowed), and
 * it has no handler of its own — collapsing IS its job. Without this carve-out
 * the control guard would swallow every chevron click and the section would only
 * collapse when you clicked the bar AROUND the chevron, which is the shape most
 * likely to be read as "the toggle is broken".
 *
 * Persistence is OPT-IN (parity A-2 #6) and off by default: omit `persist` and
 * this is exactly the session-only wiring it has always been. Pass one and the
 * section is restored from the store at wire time — BEFORE the caller's first
 * paint, which is why this reads rather than waiting for a render — and every
 * toggle is written back.
 *
 * Requires:
 *   - section is the section ROOT (the element carrying `data-collapsed`)
 *   - handle is that section's header handle
 *   - persist, when given, names an accordion id and a store to hold it
 *
 * Ensures:
 *   - with no `persist`, nothing is read or written; collapse is session-only
 *   - with `persist`, the stored state is applied to the DOM before returning
 *   - with `persist`, each toggle writes the NEW state under `persist.key`
 *   - returns an unsubscribe fn (removes the listener) for lifecycle cleanup
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-type return annotation.
export function wireSectionCollapse(
  section : HTMLElement,
  handle  : SectionHeaderHandle,
  persist?: SectionCollapsePersist,
): () => void {
  // Restore before the caller paints. A missing flag reads false (the store's
  // documented default-expanded), which is the same answer as legacy's "missing
  // key = use the section's HTML default" for a section whose default IS open.
  if ( persist !== undefined ) {
    setSectionCollapsed( section, handle, persist.store.isAccordionCollapsed( persist.key ) );
  }
  const onClick = ( e: Event ): void => {
    if ( !headerClickShouldCollapse( e.target as Element | null, handle.toggleEl ) ) return;
    const collapsed = section.getAttribute( "data-collapsed" ) === "true";
    setSectionCollapsed( section, handle, !collapsed );
    if ( persist !== undefined ) persist.store.setAccordionCollapsed( persist.key, !collapsed );
  };
  handle.header.addEventListener( "click", onClick );
  return () => handle.header.removeEventListener( "click", onClick );
}
