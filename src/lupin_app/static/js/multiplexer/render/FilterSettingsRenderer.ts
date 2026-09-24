/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer parity row B-3 — Queue Filter Settings.
//
// The multiplexer port of legacy's `#filter-settings-section`
// (notifications.html:1123-1149): the admin-only view-mode switch — 👤 My Jobs Only /
// 🚫 Not My Jobs / 👥 All Users' Jobs — plus the live "Currently viewing:" line.
//
// Plan §2 B-3 behaviours built here: B1 (hidden in markup, revealed for an admin only),
// B2 (header-click toggle, the chevron is a real `<button>`), B3 (disclosure NOT
// persisted though visibility IS), B7 (static header + the live Currently-viewing line),
// F1 (legacy's LONG button labels), F3 (a non-admin mode change refused AT THE SETTER —
// that half lives in NotificationStore and is not re-implemented here).
// B4 is the toolbar entry, which B-0 already shipped ("Filter Settings (Admin)").
// B6 (the badges that reveal this pane) is A-2 #11, scheduled after this row.
//
// 🔴 F1 IS A VISIBLE COPY CHANGE, AND IT IS THE KIND A PORT SHIPS SILENTLY. The mux's
// existing Mine switch elsewhere reads "Mine / Not Mine / All Users"; legacy's buttons
// here read "👤 My Jobs Only / 🚫 Not My Jobs / 👥 All Users' Jobs". Same behaviour,
// different words, and only a test that asserts the STRINGS notices.
//
// 🔴 B3 — VISIBILITY IS PERSISTED, DISCLOSURE IS NOT, AND THE TWO ARE DIFFERENT THINGS.
// Whether the pane is on screen at all is a durable preference (ViewStateStore, shared
// with the toolbar). Whether its body is expanded is a within-session affordance, which
// is why the reveal path calls setSectionVisible EXPLICITLY and the collapse chevron
// persists nothing.

import type { EventBus } from "../shared/EventBus";
import type { NotificationStore } from "../stores/NotificationStore";
import type { ViewStateStore } from "../stores/ViewStateStore";
import type { NotificationFilterMode, StoreNotificationsChangedPayload } from "../shared/types";
import { renderSectionHeader, wireSectionCollapse } from "./templates/sectionHeader";

// F1 — legacy's labels, verbatim from notifications.html:1135/1138/1141, with the ids
// legacy's CSS and its e2e tests key on.
interface ModeButtonSpec {
  mode   : NotificationFilterMode;
  id     : string;
  testid : string;
  label  : string;
}

const MODE_BUTTONS: ReadonlyArray<ModeButtonSpec> = [
  { mode: "own",    id: "filter-own-jobs",    testid: "multiplexer-filter-own-btn",    label: "👤 My Jobs Only" },
  { mode: "others", id: "filter-others-jobs", testid: "multiplexer-filter-others-btn", label: "🚫 Not My Jobs" },
  { mode: "all",    id: "filter-all-jobs",    testid: "multiplexer-filter-all-btn",    label: "👥 All Users' Jobs" },
];

// The "Currently viewing:" phrasing, legacy notifications.js. One map, so the line and
// the buttons cannot drift into describing different things.
const MODE_DISPLAY: Readonly<Record<NotificationFilterMode, string>> = {
  own    : "Your jobs only",
  others : "Other users' jobs",
  all    : "All users' jobs",
};

const SECTION_ID = "filter-settings-pane";

export interface FilterSettingsRenderer {
  /** Build the pane into `root` and subscribe. Throws on a 2nd mount. */
  mount( root: HTMLElement ): void;
  /**
   * B1/B3 — reveal the pane for an admin: un-hide it, PERSIST the visibility, and
   * repaint. A no-op for a non-admin, which is what keeps B1 true.
   */
  reveal(): void;
  /** Unsubscribe, drop handlers, empty the root. */
  unmount(): void;
}

export interface FilterSettingsRendererOptions {
  eventBus      : EventBus;
  store         : NotificationStore;
  viewState     : ViewStateStore;
  isAdmin       : () => boolean;
}

class FilterSettingsRendererImpl implements FilterSettingsRenderer {
  private readonly bus       : EventBus;
  private readonly store     : NotificationStore;
  private readonly viewState : ViewStateStore;
  private readonly isAdmin   : () => boolean;

  private root         : HTMLElement | null = null;
  private statusEl     : HTMLElement | null = null;
  private modeDisplay  : HTMLElement | null = null;
  private buttons      = new Map<NotificationFilterMode, HTMLButtonElement>();
  private unsubscribes : Array<() => void> = [];
  private clickHandler : ( ( e: Event ) => void ) | null = null;

  constructor( options: FilterSettingsRendererOptions ) {
    this.bus       = options.eventBus;
    this.store     = options.store;
    this.viewState = options.viewState;
    this.isAdmin   = options.isAdmin;
  }

  mount( root: HTMLElement ): void {
    if ( this.root !== null ) throw new Error( "FilterSettingsRenderer: already mounted" );
    this.root = root;
    root.replaceChildren();

    // B7 — a STATIC header. The title never follows state; only the body does.
    const header = renderSectionHeader( {
      icon: "⚙️", title: "Queue Filter Settings",
      testid: "multiplexer-filter-settings-header",
    } );
    root.appendChild( header.header );

    const content = document.createElement( "div" );
    content.className = "section-content";
    content.setAttribute( "data-testid", "multiplexer-filter-settings-content" );

    const label = document.createElement( "label" );
    const strong = document.createElement( "strong" );
    strong.textContent = "View Mode:";
    label.appendChild( strong );
    content.appendChild( label );

    const controls = document.createElement( "div" );
    controls.className = "filter-controls";
    for ( const spec of MODE_BUTTONS ) {
      const btn = document.createElement( "button" );
      btn.type        = "button";
      btn.id          = spec.id;
      btn.className   = "filter-button";
      btn.textContent = spec.label;
      btn.setAttribute( "data-testid", spec.testid );
      btn.setAttribute( "data-mode", spec.mode );
      controls.appendChild( btn );
      this.buttons.set( spec.mode, btn );
    }
    content.appendChild( controls );

    // B7 — the live line. Legacy keeps the label static and rewrites only the <strong>.
    const status = document.createElement( "div" );
    status.id = "filter-status";
    status.setAttribute( "data-testid", "multiplexer-filter-status" );
    status.appendChild( document.createTextNode( "Currently viewing: " ) );
    const display = document.createElement( "strong" );
    display.id = "filter-mode-display";
    display.setAttribute( "data-testid", "multiplexer-filter-mode-display" );
    status.appendChild( display );
    content.appendChild( status );

    root.appendChild( content );
    this.statusEl    = status;
    this.modeDisplay = display;

    // B2 — header-click toggle. The shared helper owns the chevron-is-a-button
    // exception; B3's "disclosure is not persisted" is satisfied by it writing only the
    // session-only `data-collapsed`, never ViewStateStore.
    this.unsubscribes.push( wireSectionCollapse( root, header ) );

    this.clickHandler = ( e: Event ): void => this.onClick( e );
    root.addEventListener( "click", this.clickHandler );

    // Repaint when the mode changes from anywhere — the jobs pane shares this mode.
    this.unsubscribes.push(
      this.bus.on<StoreNotificationsChangedPayload>( "store_notifications_changed", ( e ) => {
        if ( e.payload.changeKind === "filtered" ) this.render();
      } ),
    );

    this.applyVisibility();
    this.render();
  }

  reveal(): void {
    // B1 — a non-admin reveal is a no-op, and the refusal is the gate's second layer:
    // the pane's own `display` already refuses, and this stops the PREFERENCE being
    // written on a non-admin's behalf.
    if ( !this.isAdmin() ) return;
    // B3 — the VISIBILITY is persisted, explicitly. Without this the pane re-hides on
    // the next load and the reveal looks like it failed.
    //
    // 🔴 THIS PERSISTS AXIS 2 AND DOES NOT APPLY IT — deliberately. `.section-hidden` +
    // `hidden` belong to SectionToolbarRenderer (see applyVisibility below), so a caller
    // that wants the pane actually on screen goes through `showSection( SECTION_ID )`,
    // which persists AND applies AND re-lights the toolbar button. That is the path
    // A-2 #11's badges take. Restating its precedence rule here is exactly how this
    // element ended up with two writers on one axis in the first place.
    this.viewState.setSectionVisible( SECTION_ID, true );
    this.applyVisibility();
  }

  unmount(): void {
    for ( const off of this.unsubscribes ) off();
    this.unsubscribes.length = 0;
    if ( this.root !== null && this.clickHandler !== null ) {
      this.root.removeEventListener( "click", this.clickHandler );
    }
    this.clickHandler = null;
    if ( this.root !== null ) this.root.replaceChildren();
    this.root = this.statusEl = this.modeDisplay = null;
    this.buttons.clear();
  }

  // B1 — the ADMIN GATE, and it is the ONLY axis this renderer writes.
  //
  // 🔴 LEGACY HAS TWO MECHANISMS ON THIS ELEMENT AND THE FIGHT BETWEEN THEM *IS* THE
  // GATE. I had this backwards twice. Measured in notifications.js and notifications.css:
  //
  //   axis 1  inline `style.display`      — set by initializeFilterUI:6404/6423 from
  //                                         isAdmin ALONE. Never touched again.
  //   axis 2  `.section-hidden` + `hidden` — the user's per-section toggle, owned by
  //                                         SectionToolbarRenderer (toggle, showSection
  //                                         and the mount reconcile).
  //
  // `.section-hidden` carries `display: none !important` (section-toolbar.css:39,
  // mirroring notifications.css:111), so axis 2 outranks axis 1 when it says HIDDEN,
  // and axis 1 outranks ordinary CSS when IT says hidden. Net rule, both surfaces:
  // **the pane is visible only when BOTH axes say visible.**
  //
  // That is why a non-admin clicking the ⚙️ toolbar button sees nothing in legacy: the
  // click clears axis 2, and the inline `display:none` from axis 1 is still standing.
  // The button needs no admin gate of its own because the pane already refuses.
  //
  // My first cut set axis 1 only and called axis 2 a collision; my second cut "fixed" it
  // by moving to axis 2 and DELETED THE GATE — a non-admin ⚙️ click then revealed the
  // pane (María, 2026-09-23). Both cuts came from reading the two writers as a bug
  // instead of measuring which one wins and when.
  //
  // So: axis 1 here, from isAdmin only, exactly as legacy. Axis 2 is the toolbar's and
  // this renderer does not touch it — one writer per axis, no precedence to restate.
  private applyVisibility(): void {
    if ( this.root === null ) return;
    this.root.style.display = this.isAdmin() ? "block" : "none";
  }

  private onClick( e: Event ): void {
    const target = ( e.target as Element | null )?.closest( "button[data-mode]" );
    if ( target === null || target === undefined ) return;
    // No null check on the attribute: the selector above is `button[data-mode]`, so an
    // element that matched HAS it. The guard I wrote here first was an unreachable
    // branch — a claim about a state the DOM query cannot return — and coverage said so.
    const mode = target.getAttribute( "data-mode" ) as NotificationFilterMode;
    // F3 — the store decides. A refusal returns false and this repaints from the store's
    // ACTUAL mode, so a refused click leaves the buttons showing what is really in force
    // rather than what was clicked.
    this.store.setFilterMode( mode );
    this.render();
  }

  // No mounted-check: every caller is mount(), the click handler or the bus
  // subscription, and unmount() removes both of the latter before dropping the root.
  // The guard that was here could not fire.
  private render(): void {
    const mode = this.store.filterMode();
    for ( const [ m, btn ] of this.buttons ) {
      btn.classList.toggle( "active", m === mode );
      btn.setAttribute( "aria-pressed", String( m === mode ) );
    }
    if ( this.modeDisplay !== null ) this.modeDisplay.textContent = MODE_DISPLAY[ mode ];
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line — c8 reports ONE location for this "branch" where a real conditional carries two.
export function createFilterSettingsRenderer(
  options: FilterSettingsRendererOptions,
): FilterSettingsRenderer {
  return new FilterSettingsRendererImpl( options );
}
