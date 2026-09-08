/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// FinishedTasksRenderer — the DOM-touching orchestrator (row 470b7509).
//
// The multiplexer port of the legacy Finished Tasks pane shipped at ba4bb92c.
// Like every other mux accordion this renderer OWNS its subtree: `mount(root)`
// builds the chrome (✅ Finished Tasks · count · ⟳ · updated stamp) and a
// `.section-content` body holding the controls bar and the rows container.
//
// 🔴 NO CODE REUSE (Rick, row 87812328). Nothing here imports from the legacy
// client. What is shared is the SERVER's status enum and the STYLESHEET both
// pages already link — the target is observational equivalence, reached
// independently.
//
// 🔴 THE COUNT CHIP SHOWS AN EM DASH UNTIL THE FIRST POLL RETURNS, NEVER "0".
// A 0 is a claim that something was counted; before a poll nothing has been,
// and "0 finished today" is a materially different statement from "not loaded
// yet" to the person who asked for this pane BECAUSE work was going unfinished.
//
// ⚠️ A PILL CLICK IS A CLIENT-SIDE RE-RENDER, NOT A ROUND TRIP. All three
// statuses are fetched every poll — the whole population is ~47 rows/day — so
// toggling a pill repaints from data already in hand and the control stays
// instant, which is what "at a glance" requires.

import type { EventBus } from "../shared/EventBus";
import type { StoreFinishedTasksChangedPayload } from "../shared/types";
import {
  FINISHED_DEFAULT_SHOWN,
  FINISHED_SHOWN_KEY,
  FINISHED_UNMEASURED,
  clampWindowDays,
  finishedPaneState,
  mergeShownEvents,
  parseShownStatuses,
  type FinishedEventsByStatus,
} from "./finishedTasksModel";
import {
  renderFinishedControls,
  renderFinishedSentinel,
  renderFinishedTasksTable,
} from "./templates/finishedTasksTable";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

/**
 * The pane's six sentinels, one per state.
 *
 * 🔴 SIX MESSAGES BECAUSE THERE ARE SIX FACTS. Every one of them says what was
 * or was not MEASURED, because the difference between "nothing finished" and "I
 * could not find out" is the entire product here.
 */
export const FINISHED_SENTINELS = Object.freeze( {
  error      : "Could not reach the event stream. Nothing was measured — this is not \"no finished work\".",
  unmeasured : "Loading…",
  no_filter  : "No status selected. Pick at least one pill above.",
  empty      : "Nothing reached these statuses in this window. That is a measured zero, not a missing fetch.",
  partial    : "⚠️ Partial result — at least one status failed to load. The rows below are incomplete.",
} );

export interface FinishedTasksStoreLike {
  eventsByStatus(): FinishedEventsByStatus;
  measuredStatuses(): ReadonlyArray<string>;
  error(): string | null;
  windowDays(): number;
  setWindowDays( days: number ): void;
  refresh(): Promise<void>;
}

export interface FinishedTasksRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface FinishedTasksRendererOptions {
  eventBus   : EventBus;
  store      : FinishedTasksStoreLike;
  /** Test injection — the clock for the "updated" stamp and relative ages. */
  nowDateFn? : () => Date;
  /**
   * The persistence backend. Defaults to `localStorage`.
   *
   * ⚠️ `null` IS AN ACCEPTED VALUE AND MEANS "NO PERSISTENCE", not "use the
   * default". A host with no localStorage at all is a real state — the
   * production default resolves to null there — so it is a value a caller can
   * pass and a test can drive, rather than a branch only the browser reaches.
   */
  storage?   : Pick<Storage, "getItem" | "setItem"> | null;
}

/**
 * Read the persisted SHOWN statuses, tolerating a storage that throws.
 *
 * ⚠️ A PRIVATE-MODE OR QUOTA FAILURE MUST NEVER BREAK RENDERING, which is what
 * both neighbouring keys in this client already do. A throwing `getItem` falls
 * back to the spec default exactly as a missing key does.
 */
function readShown( storage: Pick<Storage, "getItem" | "setItem"> | null ): ReadonlyArray<string> {
  if ( storage === null ) return FINISHED_DEFAULT_SHOWN;
  try {
    return parseShownStatuses( storage.getItem( FINISHED_SHOWN_KEY ) );
  } catch {
    return FINISHED_DEFAULT_SHOWN;
  }
}

/** Persist the SHOWN statuses. Write failures are swallowed, per the same rule. */
function writeShown( storage: Pick<Storage, "getItem" | "setItem"> | null, shown: ReadonlyArray<string> ): void {
  if ( storage === null ) return;
  try {
    storage.setItem( FINISHED_SHOWN_KEY, JSON.stringify( shown ) );
  } catch {
    /* a private-mode / quota failure must never break rendering */
  }
}

class FinishedTasksRendererImpl implements FinishedTasksRenderer {
  private readonly bus       : EventBus;
  private readonly store     : FinishedTasksStoreLike;
  private readonly nowDateFn : () => Date;
  private readonly storage   : Pick<Storage, "getItem" | "setItem"> | null;
  private readonly unsubscribers: Array<() => void> = [];

  private root       : HTMLElement | null = null;
  private container  : HTMLElement | null = null;
  private controls   : HTMLElement | null = null;
  private countEl    : HTMLElement | null = null;
  private updatedEl  : HTMLElement | null = null;
  private header     : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted    = false;
  /** POSITIVE polarity: these are the statuses currently SHOWN. */
  private shown      : ReadonlyArray<string> = FINISHED_DEFAULT_SHOWN;
  /** True once a poll has resolved — gates the em dash on the count chip. */
  private measuredOnce = false;

  constructor( opts: FinishedTasksRendererOptions ) {
    this.bus   = opts.eventBus;
    this.store = opts.store;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
    /* c8 ignore start */ // production-default fallback, and it spans three lines — `ignore next` would cover only the first. The browser's localStorage; tests pass a fake, or null for a host that has none.
    this.storage = opts.storage === undefined
      ? ( typeof globalThis.localStorage === "undefined" ? null : globalThis.localStorage )
      : opts.storage;
    /* c8 ignore stop */
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "FinishedTasksRenderer already mounted" );
    this.mounted = true;
    this.root = root;

    this.shown = readShown( this.storage );

    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "finished-tasks-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-finished-tasks-refresh" );
    refreshBtn.title = "Refresh now";
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.store.refresh() );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "finished-tasks-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-finished-tasks-updated" );

    const header = renderSectionHeader( {
      icon    : "✅",
      title   : "Finished Tasks",
      testid  : "multiplexer-finished-tasks-header",
      actions : [ refreshBtn, this.updatedEl ],
    } );
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.setAttribute( "data-testid", "multiplexer-finished-tasks-count" );
    this.countEl.title = "Terminal rows in the selected window. An em dash until the first poll returns — a 0 here would be a claim nobody has measured yet.";
    this.countEl.textContent = FINISHED_UNMEASURED;

    // 🔴 THE CONTROLS LIVE IN THE BODY, NOT THE HEADER. The header collapses on
    // click, so a slider there would collapse the panel on every drag.
    this.controls = renderFinishedControls( {
      shown      : this.shown,
      windowDays : this.store.windowDays(),
    } );
    this.wireControls( this.controls );

    this.container = document.createElement( "div" );
    this.container.className = "finished-tasks-container";
    this.container.setAttribute( "data-testid", "multiplexer-finished-tasks-container" );

    const body = document.createElement( "div" );
    body.className = "section-content finished-tasks-body";
    body.append( this.controls, this.container );

    root.replaceChildren( header.header, body );
    this.collapseOff = wireSectionCollapse( root, header );

    this.renderFromStore( false );

    this.unsubscribers.push(
      this.bus.on<StoreFinishedTasksChangedPayload>(
        "store_finished_tasks_changed",
        ( e ) => {
          this.measuredOnce = true;
          this.renderFromStore( e.payload.stampUpdated );
        },
      ),
    );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.collapseOff !== null ) {
      this.collapseOff();
      this.collapseOff = null;
    }
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.container = null;
    this.controls  = null;
    this.countEl   = null;
    this.updatedEl = null;
    this.header    = null;
    this.mounted   = false;
  }

  forceRenderForTesting(): void {
    if ( this.mounted ) this.renderFromStore( true );
  }

  // -------------------------------------------------------------------------
  // Controls
  // -------------------------------------------------------------------------

  private wireControls( bar: HTMLElement ): void {
    for ( const pill of Array.from( bar.querySelectorAll( ".finished-pill" ) ) ) {
      pill.addEventListener( "click", () => this.onPillClick( pill as HTMLElement ) );
    }

    const slider = bar.querySelector( "#finished-tasks-window" ) as HTMLInputElement | null;
    const output = bar.querySelector( "#finished-tasks-window-value" ) as HTMLElement | null;
    /* c8 ignore next */ // defensive: renderFinishedControls always builds both; guards a caller passing a hand-built bar.
    if ( slider === null ) return;

    // PREVIEW ONLY — no fetch. Dragging a slider must not fire a request per
    // pixel, and the reading under the thumb must still track the thumb.
    slider.addEventListener( "input", () => {
      const days = clampWindowDays( slider.value );
      this.store.setWindowDays( days );
      if ( output !== null ) output.textContent = `${ days }d`;
    } );
    // COMMIT — the release is the fetch.
    slider.addEventListener( "change", () => {
      const days = clampWindowDays( slider.value );
      this.store.setWindowDays( days );
      if ( output !== null ) output.textContent = `${ days }d`;
      void this.store.refresh();
    } );
  }

  private onPillClick( pill: HTMLElement ): void {
    const status = pill.getAttribute( "data-status" );
    /* c8 ignore next */ // defensive: every pill this renderer builds carries data-status.
    if ( status === null ) return;

    const next = this.shown.includes( status )
      ? this.shown.filter( ( s ) => s !== status )
      : [ ...this.shown, status ];

    // 🔴 TURNING THE LAST PILL OFF RE-LIGHTS DONE. There is no useful state in
    // which this pane shows nothing on purpose, and DONE pre-lit is the ruled
    // default — so an empty selection resolves to the default rather than to a
    // blank pane the operator has to fix.
    this.shown = next.length === 0 ? FINISHED_DEFAULT_SHOWN : next;

    writeShown( this.storage, this.shown );
    this.syncPillPressedState();
    this.renderFromStore( false );
  }

  /** Push `this.shown` back onto the pills. Positive polarity: pressed = shown. */
  private syncPillPressedState(): void {
    /* c8 ignore next */ // defensive: controls is set in lockstep with mount.
    if ( this.controls === null ) return;
    for ( const pill of Array.from( this.controls.querySelectorAll( ".finished-pill" ) ) ) {
      /* c8 ignore next */ // `?? ""` unreachable: every pill renderFinishedControls builds carries data-status; the fallback exists so a hand-built bar cannot throw.
      const status = pill.getAttribute( "data-status" ) ?? "";
      pill.setAttribute( "aria-pressed", this.shown.includes( status ) ? "true" : "false" );
    }
  }

  // -------------------------------------------------------------------------
  // Dispatch (the six states)
  // -------------------------------------------------------------------------

  private renderFromStore( stampUpdated: boolean ): void {
    /* c8 ignore next */ // defensive: subscriptions detach in unmount BEFORE container is nulled.
    if ( this.container === null ) return;

    const eventsByStatus = this.store.eventsByStatus();
    const measured       = this.store.measuredStatuses();
    const error          = this.store.error();
    const visible        = mergeShownEvents( eventsByStatus, this.shown );

    this.paintPillCounts( eventsByStatus );

    // The chip counts VISIBLE rows, and shows the em dash until a poll has
    // resolved — never 0 before anything has been measured.
    if ( this.countEl !== null ) {
      this.countEl.textContent = this.measuredOnce ? String( visible.length ) : FINISHED_UNMEASURED;
    }

    const state = finishedPaneState( {
      measuredStatuses : measured,
      shown            : this.shown,
      visibleCount     : visible.length,
      error,
    } );

    const nowMs = this.nowDateFn().getTime();
    if ( state === "rows" ) {
      this.container.replaceChildren( renderFinishedTasksTable( visible, nowMs ) );
    } else if ( state === "partial" ) {
      // PARTIAL: rows AND the caveat. Rendering what we have WITHOUT saying so
      // would present an incomplete set as a complete one.
      this.container.replaceChildren(
        /* c8 ignore next */ // `?? ""` unreachable: the "partial" state is only reached when error is non-null — finishedPaneState guarantees it.
        renderFinishedSentinel( "partial", `${ FINISHED_SENTINELS.partial } (${ error ?? "" })` ),
        renderFinishedTasksTable( visible, nowMs ),
      );
    } else if ( state === "error" ) {
      this.container.replaceChildren(
        /* c8 ignore next */ // `?? ""` unreachable: the "error" state is only reached when error is non-null — finishedPaneState guarantees it.
        renderFinishedSentinel( "error", `${ FINISHED_SENTINELS.error } (${ error ?? "" })` ),
      );
    } else {
      this.container.replaceChildren( renderFinishedSentinel( state, FINISHED_SENTINELS[ state ] ) );
    }

    if ( stampUpdated ) this.stampUpdated();
  }

  /**
   * Every pill's own count, from the FULL fetch rather than the visible set — a
   * pill's number must not depend on whether it happens to be lit.
   *
   * A status that was never measured KEEPS the em dash; a measured zero shows
   * "0" and dims the pill without hiding it.
   */
  private paintPillCounts( eventsByStatus: FinishedEventsByStatus ): void {
    /* c8 ignore next */ // defensive: controls is set in lockstep with mount.
    if ( this.controls === null ) return;
    for ( const pill of Array.from( this.controls.querySelectorAll( ".finished-pill" ) ) ) {
      /* c8 ignore next */ // `?? ""` unreachable: every pill renderFinishedControls builds carries data-status; the fallback exists so a hand-built bar cannot throw.
      const status = pill.getAttribute( "data-status" ) ?? "";
      const rows   = eventsByStatus[ status ];
      const badge  = pill.querySelector( ".finished-pill-count" );
      if ( badge !== null ) {
        badge.textContent = rows === undefined ? FINISHED_UNMEASURED : String( rows.length );
      }
      pill.classList.toggle( "finished-pill-zero", rows !== undefined && rows.length === 0 );
    }
  }

  private stampUpdated(): void {
    /* c8 ignore next */ // defensive: updatedEl is set/nulled in lockstep with container, which the caller already guarded.
    if ( this.updatedEl === null ) return;
    this.updatedEl.textContent = `updated ${ this.nowDateFn().toLocaleTimeString() }`;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFinishedTasksRenderer( opts: FinishedTasksRendererOptions ): FinishedTasksRenderer {
  return new FinishedTasksRendererImpl( opts );
}
