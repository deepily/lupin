/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Holding-area card — HoldingAreaRenderer (row 87812328).
//
// The pane's dispatch: sentinel → empty → grouped rows, plus the section header
// and its count chip. The GROUPS themselves live in
// templates/holdingAreaTable.ts; grouping and the filer label live in
// render/holdingAreaModel.ts. This file decides only WHICH of the pane's states
// to paint.
//
// 🔴 AN EMPTY HOLDING AREA IS A REAL STATE AND SAYS SO. This pane is expected to
// be empty most of the time, which is exactly when a silent blank is most likely
// to be read as "broken" and least likely to be checked. Every state paints
// something — there is no path through this file that leaves the container
// empty.
//
// ⚠️ THIS PANE DOES NOT DEGRADE TO STALE ROWS, AND THAT IS A CARBON COPY RATHER
// THAN AN OVERSIGHT. TaskListRenderer replays its last-known rows under an
// "unreachable" indicator; the legacy holding area does not, and its own
// sentinel says why in as many words — "last known state not shown". A held row
// is a row awaiting a DECISION, so showing a stale one invites an operator to
// approve something that may already have moved. The task list is a status
// display; this is a work queue.
//
// ⚠️ READ-ONLY, DELIBERATELY, AND THE STORE SAYS SO TOO. The batch verbs
// (approve-all / won't-fix-all per filer) are not wired here — won't-fix-all is
// TERMINAL and applies ONE reason to every row under a filer, so it wants its
// own review rather than riding in on a rendering commit.

import type { EventBus } from "../shared/EventBus";
import type { StoreHoldingAreaChangedPayload } from "../shared/types";
import type { TaskListComposite } from "./taskListModel";
import { formatFleetTimestamp } from "./fleetModel";
import { groupHeldRowsByFiler } from "./holdingAreaModel";
import { renderHoldingAreaGroups } from "./templates/holdingAreaTable";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

/**
 * The pane's sentinel messages, carbon-copied from notifications.js:12678-12681.
 *
 * ⚠️ `query_unavailable` IS CARRIED EVEN THOUGH TODAY'S STORE NEVER EMITS IT.
 * HoldingAreaStore maps a 401 to auth_required and everything else to
 * unreachable, so only two of these three can arrive from the live poll. It is
 * kept because the alternative is worse in both directions: dropping it makes a
 * future third status render as the generic unreachable message, which is a
 * WRONG explanation rather than a missing one, and the legacy pane distinguishes
 * them for a reason — a deploy defect and an outage want different responses.
 * It is reachable through this renderer's own input and is tested as such.
 */
export interface HoldingAreaSentinels {
  readonly auth_required      : string;
  readonly query_unavailable  : string;
  readonly unreachable        : string;
  readonly [ status: string ] : string | undefined;
}

// ⚠️ THE THREE KNOWN KEYS ARE DECLARED EXPLICITLY, and the index signature sits
// BESIDE them rather than replacing them. A bare Record<string,string> makes
// `SENTINELS.unreachable` read as `string | undefined` under this project's
// noUncheckedIndexedAccess — so the reads made BY NAME, on keys that are always
// present, would each need a non-null assertion. The index signature is what
// the dynamic `SENTINELS[ status ]` lookup needs; the named fields are what the
// direct reads need. Caught by `tsc -p`, NOT by the suite: the tests run under
// tsx, which strips types rather than checking them.
export const HOLDING_AREA_SENTINELS: HoldingAreaSentinels = Object.freeze( {
  auth_required     : "Sign-in required to read the holding area.",
  query_unavailable : "The shared query module did not load — this is a deploy defect, not an outage.",
  unreachable       : "Task store unreachable — last known state not shown.",
} );

/** The pane's genuinely-empty message. Carbon copy of notifications.js:12706. */
export const HOLDING_AREA_EMPTY_MESSAGE = "Nothing waiting on triage.";

/** What the count chip reads while a sentinel is showing — a count is not known. */
export const HOLDING_AREA_COUNT_UNKNOWN = "—";

export interface HoldingAreaStoreLike {
  composite(): TaskListComposite | null;
  refresh(): Promise<void>;
}

export interface HoldingAreaRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface HoldingAreaRendererOptions {
  eventBus   : EventBus;
  store      : HoldingAreaStoreLike;
  /** Test injection — the clock for the "updated" stamp. Defaults to `new Date()`. */
  nowDateFn? : () => Date;
}

function messageEl( className: string, text: string ): HTMLParagraphElement {
  const p = document.createElement( "p" );
  p.className = `holding-area-message ${ className }`;
  p.textContent = text;
  return p;
}

class HoldingAreaRendererImpl implements HoldingAreaRenderer {
  private readonly bus       : EventBus;
  private readonly store     : HoldingAreaStoreLike;
  private readonly nowDateFn : () => Date;
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted   = false;

  constructor( opts: HoldingAreaRendererOptions ) {
    this.bus   = opts.eventBus;
    this.store = opts.store;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "HoldingAreaRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "holding-area-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-holding-area-refresh" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.store.refresh() );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "holding-area-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-holding-area-updated" );

    const header = renderSectionHeader( {
      icon    : "🛑",
      title   : "Holding Area",
      testid  : "multiplexer-holding-area-header",
      actions : [ refreshBtn, this.updatedEl ],
    } );
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.setAttribute( "data-testid", "multiplexer-holding-area-count" );
    this.countEl.textContent = "0";

    this.container = document.createElement( "div" );
    this.container.className = "section-content holding-area-container";
    this.container.setAttribute( "data-testid", "multiplexer-holding-area-container" );

    root.replaceChildren( header.header, this.container );
    this.collapseOff = wireSectionCollapse( root, header );

    this.renderFromStore( false );

    this.unsubscribers.push(
      this.bus.on<StoreHoldingAreaChangedPayload>(
        "store_holding_area_changed",
        ( e ) => this.renderFromStore( e.payload.stampUpdated ),
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
    this.countEl = null;
    this.updatedEl = null;
    this.header = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if ( this.mounted ) this.renderFromStore( true );
  }

  // -------------------------------------------------------------------------
  // Dispatch (the three states)
  // -------------------------------------------------------------------------

  private renderFromStore( stampUpdated: boolean ): void {
    /* c8 ignore next */ // defensive: subscriptions detach in unmount BEFORE container is nulled.
    if ( this.container === null ) return;
    const composite = this.store.composite();

    // ⚠️ A NULL COMPOSITE IS THE PRE-FIRST-POLL STATE AND IS NOT "EMPTY".
    // Painting "Nothing waiting on triage." before anything has been asked would
    // be a claim the pane has no evidence for — and it is the reassuring
    // direction, which is the one that stops a reader looking. It takes the
    // unreachable sentinel, the honest reading: no answer has arrived.
    const status   = composite === null ? "unreachable" : ( composite.status ?? "" );
    const sentinel = HOLDING_AREA_SENTINELS[ status ];
    if ( sentinel !== undefined ) {
      this.paintSentinel( sentinel );
      return;
    }

    // ⚠️ A COMPOSITE WITH NO STATUS BUT A NON-ARRAY `tasks` IS A MALFORMED
    // ANSWER, NOT AN EMPTY QUEUE. groupHeldRowsByFiler is degrade-safe and would
    // return no groups, which paints "Nothing waiting on triage." over a payload
    // nobody understood — an empty result and a broken one wearing one face.
    if ( !Array.isArray( composite!.tasks ) ) {
      this.paintSentinel( HOLDING_AREA_SENTINELS.unreachable );
      return;
    }

    const groups = groupHeldRowsByFiler( composite!.tasks );
    const total  = groups.reduce( ( n, g ) => n + g.tasks.length, 0 );
    this.setCountText( String( total ) );

    if ( total === 0 ) {
      this.container.replaceChildren( messageEl( "holding-area-empty", HOLDING_AREA_EMPTY_MESSAGE ) );
    } else {
      this.container.replaceChildren( renderHoldingAreaGroups( groups, undefined ) );
    }

    if ( stampUpdated ) this.stampUpdated();
  }

  private paintSentinel( text: string ): void {
    /* c8 ignore next */ // defensive: only reached from renderFromStore past its container-null guard.
    if ( this.container === null ) return;
    this.container.replaceChildren( messageEl( "holding-area-sentinel", text ) );
    this.setCountText( HOLDING_AREA_COUNT_UNKNOWN );
  }

  private setCountText( text: string ): void {
    if ( this.countEl !== null ) this.countEl.textContent = text;
  }

  private stampUpdated(): void {
    /* c8 ignore next */ // defensive: stampUpdated only runs from renderFromStore past its container-null guard; updatedEl is set/nulled in lockstep with container.
    if ( this.updatedEl === null ) return;
    this.updatedEl.textContent = `updated ${ formatFleetTimestamp( this.nowDateFn(), undefined ) }`;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line — c8 reports ONE location for this "branch" (240:16-43, the identifier itself) where a real conditional carries two, and the factory is called by every test in the suite.
export function createHoldingAreaRenderer( opts: HoldingAreaRendererOptions ): HoldingAreaRenderer {
  return new HoldingAreaRendererImpl( opts );
}
