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
// 🔴 THE BATCH VERBS ENTER HERE, AND THE LOOP IS SEQUENTIAL ON PURPOSE. The
// refusals worth reading are authorization refusals, and firing eight at once
// against one allowlist check produces eight identical 403s in a race whose
// order is not reproducible. One at a time is slower and its failure report is
// stable — and stability is the whole value of a report nobody can re-run,
// because the rows it describes have already moved.
//
// ⚠️ THE ID LIST IS READ OFF THE RENDERED DOM AT PRESS TIME, NOT FROM THE STORE.
// The pane repaints every poll; a list captured earlier goes stale the moment a
// peer approves something, and the batch would then act on ids that had already
// moved. What is on screen is what the operator pressed the button about.
//
// Parity A-2 #8 (row c1bb2be7) — the flow-ratio gate (render/flowRatioPanel.ts): its
// readout rides the header after the count and the request badge, and its operator
// cluster sits in the body above the rows. The truncation banner leads the rows, fed
// THIS pane's own query so its own `limit` is read.

import type { EventBus } from "../shared/EventBus";
import type { StoreHoldingAreaChangedPayload } from "../shared/types";
import type { TaskListComposite } from "./taskListModel";
import { formatFleetTimestamp } from "./fleetModel";
import { groupHeldRowsByFiler } from "./holdingAreaModel";
import { holdingGroupChevron, renderHoldingAreaGroups } from "./templates/holdingAreaTable";
import {
  holdingBatchNeeds,
  holdingBatchExtras,
  holdingBatchInFlightStatus,
  holdingBatchFinalStatus,
  HOLDING_BATCH_BLANK_REASON,
  HOLDING_BATCH_NO_ROWS,
} from "./holdingAreaBatch";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";
import { wireRequestPane, type RequestBoardStoreLike, type RequestPaneWiring } from "./requestChips";
import { wirePressHoldGuard, type PressHoldGuard } from "./pressHoldGuard";
import { captureOperatorState, restoreOperatorState } from "./operatorState";
import { TaskRowController, type TaskRowRecorderLike } from "./taskRowController";
import type { TaskMutation, TaskPatchFields } from "../stores/TaskListStore";
import type { TransitionExtras } from "./taskVerbs";
import { BADGE_HOLDING_AREA } from "../../shared/task-request.js";
import { HOLDING_AREA_QUERY } from "../../shared/task-list-query.js";
import { createFlowRatioPanel, type FlowRatioStoreLike } from "./flowRatioPanel";
import { renderTruncationBanner } from "./templates/truncationBanner";

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
  /**
   * The read to use after writing. `refresh()` may join a fetch that BEGAN
   * before this caller's writes landed, so it can resolve without ever having
   * been able to observe them; this one guarantees a read that started later.
   *
   * 🔴 IT IS ON THE SEAM ON PURPOSE. A fake store that implements only
   * `refresh()` cannot tell the two apart, which is precisely why the guard
   * written for the erased report could not see the defect (Clayton 😎, F1).
   */
  refreshAfterWrite(): Promise<void>;
  /**
   * POST one row's transition. Resolves to a result and NEVER rejects — a batch
   * is a loop, and a throwing body abandons every row after the first refusal.
   */
  transitionTask(
    id: string, toStatus: string, extras: TransitionExtras,
  ): Promise<{ ok: boolean; message?: string }>;
  /** PATCH one row's fields. Resolves to a result and never rejects, like transitionTask. */
  patchTask( id: string, fields: TaskPatchFields ): Promise<{ ok: boolean; message?: string }>;
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
  /** Test injection — the timer behind the press-hold guard's deferred release. Defaults to `setTimeout`. */
  setTimeoutFn? : ( cb: () => void, ms: number ) => unknown;
  /**
   * Row c9fafb9d — managers' promote requests. Supplies the badge count beside this pane's
   * count chip and the Approve/Deny behind each row's pending chip.
   *
   * ⚠️ OPTIONAL FOR TESTS ONLY. Boot always passes it; a pane built without it shows a
   * pending chip whose buttons do nothing, and the boot guard is what keeps that off the page.
   */
  requestStore? : RequestBoardStoreLike;
  /** Test injection for the row mic — production uses the `recordingManager` singleton. */
  recorder?     : TaskRowRecorderLike;
  /** The bearer token the row mic's dictation upload carries. Boot passes the cached access token. */
  getAuthToken? : () => string | null;
  /**
   * Parity A-2 #8 — the flow-ratio gate's store. Boot always passes it; a pane built
   * without it has no ratio readout and no operator cluster, which is what the tests of
   * the rest of this pane want.
   */
  flowRatio?    : FlowRatioStoreLike;
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
  private readonly setTimeoutFn : ( ( cb: () => void, ms: number ) => unknown ) | undefined;
  private readonly requestStore : RequestBoardStoreLike | null;
  private readonly recorder     : TaskRowRecorderLike | undefined;
  private readonly getAuthToken : ( () => string | null ) | undefined;
  private readonly flowRatio    : FlowRatioStoreLike | null;
  private requests : RequestPaneWiring | null = null;
  // Parity A-2 #0 — the shared row controls. Null while unmounted.
  private rows : TaskRowController | null = null;
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private pressGuard : PressHoldGuard | null = null;
  private mounted   = false;

  // 🔴 THE GUARD IS THIS SET, NOT THE DISABLED ATTRIBUTE. Disabling both batch
  // buttons is the operator-facing affordance and it is genuinely load-bearing —
  // Approve-All and Won't-Fix-All act on the SAME rows, so leaving the other live
  // mid-batch lets a group be closed halfway through being approved, a race
  // between two verbs over one set of ids decided by whichever transition the
  // server happens to see last. But `disabled` is a property on an element this
  // pane repaints, and the batch survives only because nothing else repaints it
  // meanwhile — a poll tick landing mid-batch would hand the operator live
  // buttons again. A set keyed by filer cannot be repainted away.
  private readonly batchesInFlight = new Set<string>();

  // The last batch report per filer, so a render can put it back. This is STATE,
  // not a cache of the DOM: the status line the groups template emits is empty
  // on every build, so anything painted into it is lost at the next render and
  // the report is the one message whose whole job is to be read afterwards.
  private readonly batchReports = new Map<string, string>();

  // Row 52142a84 — the filers whose group the operator has OPENED. Every group
  // starts collapsed, so the empty set is the page-load state Rick asked for.
  // Kept here rather than in the DOM because the 60s poll rebuilds every group;
  // an open group must survive the repaint or it would snap shut under the reader.
  private readonly expandedFilers = new Set<string>();

  constructor( opts: HoldingAreaRendererOptions ) {
    this.bus   = opts.eventBus;
    this.store = opts.store;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
    this.setTimeoutFn = opts.setTimeoutFn;
    this.requestStore = opts.requestStore ?? null;
    this.recorder     = opts.recorder;
    this.getAuthToken = opts.getAuthToken;
    this.flowRatio    = opts.flowRatio ?? null;
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

    // The holding area's badge counts PROMOTE requests: a badge sits on the list the row is
    // in NOW, and a row asking to be promoted is still here.
    if ( this.requestStore !== null ) {
      const requests = wireRequestPane( {
        bus : this.bus, store : this.requestStore, countEl : this.countEl, container : this.container,
        badgeKey : BADGE_HOLDING_AREA, testid : "multiplexer-holding-area-request-badge",
      } );
      this.requests = requests;
      this.unsubscribers.push( requests.dispose );
    }

    // ⚠️ DELEGATED ON THE CONTAINER, WHICH OUTLIVES EVERY REPAINT. The batch
    // buttons are rebuilt on every poll, so a listener bound to a button would be
    // silently discarded 60 seconds later — a control that works once and then
    // stops, which is the hardest kind of dead control to notice.
    //
    // 🔴 THE ROW CONTROLS WERE DEAD HERE UNTIL A-2 #0. This pane paints the shared
    // row — verbs, ⋯, 📄, id cell, priority, owner — and listened only for the two
    // batch buttons, so every per-row control rendered and reached no handler.
    // Legacy's `_wireHoldingAreaControls` routes chips, id copy, 📄 and row
    // controls, plus `_wireVerbSelects` for `change`; the shared controller is
    // that route. A header click no control claims toggles that filer's group
    // (row 52142a84); any other unclaimed click is ignored.
    const rows = new TaskRowController( {
      container    : this.container,
      logLabel     : "[holding-area]",
      recorder     : this.recorder,
      getAuthToken : this.getAuthToken,
      setTimeoutFn : this.setTimeoutFn,
      writer       : {
        patchTask      : ( id, fields ) => this.rowWrite( this.store.patchTask( id, fields ) ),
        transitionTask : ( id, toStatus, extras ) => this.rowWrite( this.store.transitionTask( id, toStatus, extras ) ),
      },
    } );
    this.rows = rows;
    const onClick = ( e: Event ): void => {
      if ( this.requests !== null && this.requests.handleClick( e.target ) ) return;
      if ( rows.handleClick( e.target ) ) return;
      if ( this.handleGroupToggle( e.target ) ) return;
      this.handleBatchClick( e.target );
    };
    const onChange  = ( e: Event ): void => rows.handleChange( e.target );
    const onKeydown = ( e: Event ): void => {
      const k = e as KeyboardEvent;
      // Enter / Space on a focused group header toggles it, as the task list's does.
      if ( ( k.key === "Enter" || k.key === " " ) && this.handleGroupToggle( k.target ) ) {
        k.preventDefault();
        return;
      }
      rows.handleKeydown( k );
    };
    this.container.addEventListener( "click", onClick );
    this.container.addEventListener( "change", onChange );
    this.container.addEventListener( "keydown", onKeydown );
    // ⚠️ EXPLICITLY UNSUBSCRIBED RATHER THAN LEFT TO GARBAGE COLLECTION. Detaching
    // the element does drop this listener in practice; registering the removal is
    // what makes the teardown OBSERVABLE, and a leak invisible from the DOM is
    // exactly the defect that survived sixteen passing tests on this pane.
    const containerAtMount = this.container;
    this.unsubscribers.push( () => {
      containerAtMount.removeEventListener( "click", onClick );
      containerAtMount.removeEventListener( "change", onChange );
      containerAtMount.removeEventListener( "keydown", onKeydown );
    } );

    // Parity A-2 #8 — appended to the header's title AFTER wireRequestPane put the badge
    // behind the count, so the order reads count · badge · Gate, as legacy's <h3> does.
    const body: HTMLElement[] = [];
    if ( this.flowRatio !== null ) {
      const flow = createFlowRatioPanel( { bus: this.bus, store: this.flowRatio } );
      this.countEl.parentElement!.appendChild( flow.readout );
      body.push( flow.controls );
      this.unsubscribers.push( flow.dispose );
    }

    root.replaceChildren( header.header, ...body, this.container );
    this.collapseOff = wireSectionCollapse( root, header );
    this.pressGuard  = wirePressHoldGuard( this.container, { setTimeoutFn: this.setTimeoutFn } );

    this.renderFromStore( false );

    this.unsubscribers.push(
      this.bus.on<StoreHoldingAreaChangedPayload>(
        "store_holding_area_changed",
        ( e ) => this.renderFromStore( e.payload.stampUpdated ),
      ),
    );
  }

  unmount(): void {
    this.rows?.dispose();
    this.rows = null;
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    this.pressGuard?.dispose();
    this.pressGuard = null;
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
    this.requests = null;
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
    // A press in flight holds the paint (parity A-1b): replacing the pressed node would
    // swallow the click. The release replays this call, reading the store afresh.
    if ( this.pressGuard!.hold( () => this.renderFromStore( stampUpdated ) ) ) return;
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

    // Parity A-1a — read the batch reason (keyed by FILER, not task id), a verb, a
    // disclosure, a refusal and the caret off the markup this paint is about to discard.
    const operatorState = captureOperatorState( this.container );

    // Parity A-2 #8 — the truncation banner leads, over the empty message as over the
    // groups: an empty page that the server cut short is not an empty queue.
    const banner = renderTruncationBanner( composite, HOLDING_AREA_QUERY, total );
    if ( total === 0 ) {
      this.container.replaceChildren( ...banner, messageEl( "holding-area-empty", HOLDING_AREA_EMPTY_MESSAGE ) );
    } else {
      this.container.replaceChildren( ...banner, renderHoldingAreaGroups( groups, undefined, [], this.expandedFilers ) );
    }
    this.hydrateRequests();
    // Parity A-1a — restored after hydrate, as the Task List does. Into the empty
    // message there is nothing to restore into, and every step skips.
    // Since A-2 #0 this pane has row handlers, so a chosen verb and a pending priority
    // are restored through the shared controller as well as the refusal stripe.
    restoreOperatorState( this.container, operatorState, this.rows!.operatorStateHandlers() );

    // 🔴 THE BATCH REPORT IS RE-APPLIED HERE, BECAUSE EVERY RENDER REBUILDS THE
    // GROUPS AND THE STATUS LINE INSIDE THEM COMES BACK EMPTY. Painting the
    // report once into the DOM meant it survived only until the next render —
    // and the 60s poll renders. Fixing the batch's own refresh ordering alone
    // would have narrowed that window without closing it, because the erasing
    // render does not have to be the batch's.
    //
    // ⚠️ Pruned to the filers still on screen, or a filer that drains away
    // leaves its report in this map for the life of the pane.
    const present = new Set( groups.map( ( g ) => g.filer ) );
    for ( const filer of Array.from( this.batchReports.keys() ) ) {
      if ( !present.has( filer ) ) this.batchReports.delete( filer );
    }
    for ( const filer of Array.from( this.expandedFilers ) ) {
      if ( !present.has( filer ) ) this.expandedFilers.delete( filer );
    }
    for ( const [ filer, message ] of this.batchReports ) this.applyGroupStatus( filer, message );

    if ( stampUpdated ) this.stampUpdated();
  }

  /**
   * Adapt this store's never-rejecting write to the controller's mutation handle.
   *
   * ⚠️ NO OPTIMISTIC EDIT, SO NOTHING TO RESTORE — see HoldingAreaStore's header. A
   * refusal becomes a rejection carrying the server's words, which the controller
   * paints into the row stripe; a success takes a read that began after the write,
   * so the repaint shows what the server stored.
   *
   * Ensures:
   *   - `done` rejects with an Error whose message is the store's refusal text
   *   - `done` resolves only after `refreshAfterWrite()` has resolved
   */
  private rowWrite( result: Promise<{ ok: boolean; message?: string }> ): TaskMutation {
    const done = result.then( async ( r ) => {
      /* c8 ignore next */ // `?? ""` RHS: the store's result type always carries a message when ok is false.
      if ( !r.ok ) throw new Error( r.message ?? "" );
      await this.store.refreshAfterWrite();
    } );
    return { restoreState: () => {}, done };
  }

  /** Fill the pending chips this paint built — filer, reason, and any refusal they carried. */
  private hydrateRequests(): void {
    if ( this.requests !== null && this.container !== null ) this.requests.hydrate( this.container );
  }

  // -------------------------------------------------------------------------
  // The per-filer accordion (row 52142a84)
  // -------------------------------------------------------------------------

  /**
   * A click or key on a group header's bar → open or close that filer's group.
   *
   * ⚠️ THE BATCH CONTROLS LIVE ON THE SAME BAR, so a target inside a button or an
   * input is NOT a toggle: pressing "Approve all" or typing a reason must never
   * fold the group away from under the operator.
   *
   * Ensures:
   *   - returns false for anything that is not bare header bar
   *   - otherwise flips `.collapsed`, aria-expanded and the chevron IN PLACE (no
   *     repaint, so nothing typed elsewhere is lost), records the choice for the
   *     next repaint, and returns true
   */
  private handleGroupToggle( target: EventTarget | null ): boolean {
    /* c8 ignore next */ // defensive: a click whose target is not an element cannot reach a header.
    if ( !( target instanceof Element ) ) return false;
    const header = target.closest<HTMLElement>( ".holding-area-group-header" );
    if ( header === null ) return false;
    if ( target.closest( "button, input, select, textarea, a" ) !== null ) return false;
    const group = header.closest<HTMLElement>( ".holding-area-group" );
    /* c8 ignore next */ // defensive: the template always nests the header inside its group.
    if ( group === null ) return false;
    /* c8 ignore next */ // `?? ""` RHS: the template stamps data-filer on every group.
    const filer    = group.dataset.filer ?? "";
    const expanded = group.classList.contains( "collapsed" );
    group.classList.toggle( "collapsed", !expanded );
    header.setAttribute( "aria-expanded", expanded ? "true" : "false" );
    header.querySelector( ".holding-area-group-chevron" )!.textContent = holdingGroupChevron( expanded );
    if ( expanded ) this.expandedFilers.add( filer );
    else this.expandedFilers.delete( filer );
    return true;
  }

  // -------------------------------------------------------------------------
  // The batch verbs
  // -------------------------------------------------------------------------

  /**
   * Container click → is this one of the two batch buttons, and if so, which.
   *
   * Ensures:
   *   - a click on anything else is a no-op
   *   - a click on a batch button's own text still resolves (closest, not ===)
   *   - a filer-less button is a no-op rather than a batch over an empty scope
   */
  private handleBatchClick( target: EventTarget | null ): void {
    const el = target as Element | null;
    /* c8 ignore next */ // defensive: a click whose target is not an element cannot reach a button.
    if ( el === null || typeof el.closest !== "function" ) return;
    const btn = el.closest<HTMLButtonElement>( ".holding-approve-all, .holding-wont-fix-all" );
    if ( btn === null ) return;
    const verb = btn.classList.contains( "holding-approve-all" ) ? "approve" : "wont_fix";
    void this.runBatch( btn.dataset.filer ?? "", verb );
  }

  /**
   * One filer's rendered group.
   *
   * 🔴 MATCHED IN JAVASCRIPT, NOT BUILT INTO A SELECTOR STRING. A filer label is
   * store-sourced free text — a quote, a bracket or a backslash in a persona name
   * is legal and would either break an attribute selector outright or make it
   * match something else. The legacy card reaches for `CSS.escape`; comparing
   * `dataset.filer` needs no escaping at all and so cannot be malformed by its
   * input, which is the stronger property rather than the more convenient one.
   */
  private groupFor( filer: string ): HTMLElement | null {
    if ( this.container === null ) return null;
    for ( const g of Array.from( this.container.querySelectorAll<HTMLElement>( ".holding-area-group" ) ) ) {
      if ( g.dataset.filer === filer ) return g;
    }
    return null;
  }

  /**
   * The full row ids in one filer's group, read off the rendered DOM.
   *
   * 🔴 KEYED ON THE VERB SELECT, WHICH EVERY ROW HAS, AND FILTERED ON APPROVE
   * BEING LEGAL. Two separate traps live here and the legacy card fell into the
   * first. (1) A "which rows are here" lookup must key on a control present on
   * every row UNCONDITIONALLY — keying on a per-verb button meant that when five
   * buttons merged into one Submit the selector matched NOTHING and the batch
   * reported success over zero rows. (2) The group scope ALONE would widen the
   * batch to rows no verb is legal on; today that is invisible because this pane
   * is fed a held-rows-only query, which is precisely the kind of accident that
   * stops being invisible on the day the query changes.
   *
   * Ensures: [] for an unknown filer, and never a throw.
   */
  private heldRowIdsForFiler( filer: string ): string[] {
    const group = this.groupFor( filer );
    if ( group === null ) return [];
    const ids: string[] = [];
    for ( const sel of Array.from( group.querySelectorAll<HTMLSelectElement>( ".task-verb-select[data-task-id]" ) ) ) {
      const approve = sel.querySelector<HTMLOptionElement>( 'option[value="approve"]' );
      if ( approve === null || approve.disabled ) continue;
      /* c8 ignore next */ // the `?? ""` right-hand side is unreachable BY CONSTRUCTION: the query is `.task-verb-select[data-task-id]`, an attribute-PRESENCE selector, so every element it returns carries the attribute and `dataset.taskId` is always a string. An id-less row renders `data-task-id=""` — present and empty — which this selector matches and the `id !== ""` test below rejects; that path IS exercised.
      const id = sel.dataset.taskId ?? "";
      if ( id !== "" ) ids.push( id );
    }
    return ids;
  }

  /**
   * Show or clear one group's inline status line, AND remember it so the next
   * render can put it back. A missing group is a no-op in the DOM but is still
   * remembered — the group may be absent only because a render is mid-flight.
   *
   * Ensures:
   *   - the message is recorded and survives subsequent renders
   *
   * ⚠️ THERE IS DELIBERATELY NO CLEAR PATH. The first cut of this carried an
   * `if ( message === "" ) delete` arm, and the coverage gate caught it: NOTHING
   * calls it. Every caller passes a real sentence — an in-flight count, a final
   * report, a blank-reason refusal, a no-rows refusal — and a new batch on the
   * same filer OVERWRITES rather than needing a clear first. It was a defensive
   * branch invented for a caller that does not exist, which is the shape this
   * branch has spent the night removing from other people's code.
   */
  private paintGroupStatus( filer: string, message: string ): void {
    this.batchReports.set( filer, message );
    this.applyGroupStatus( filer, message );
  }

  /** The DOM half alone — used by the render to restore a remembered report. */
  private applyGroupStatus( filer: string, message: string ): void {
    const el = this.groupFor( filer )?.querySelector<HTMLElement>( ".holding-area-group-status" );
    if ( el != null ) el.textContent = message;
  }

  /** Take one filer's BOTH batch buttons out of service, or put them back. */
  private setBatchControls( filer: string, disabled: boolean ): void {
    const group = this.groupFor( filer );
    if ( group === null ) return;
    for ( const b of Array.from( group.querySelectorAll<HTMLButtonElement>(
      ".holding-approve-all, .holding-wont-fix-all" ) ) ) {
      b.disabled = disabled;
    }
  }

  /** The group's batch reason box, trimmed, or "" when it is not rendered. */
  private batchReason( filer: string ): string {
    const input = this.groupFor( filer )?.querySelector<HTMLInputElement>( ".holding-wont-fix-all-reason" );
    return input == null ? "" : input.value.trim();
  }

  /**
   * Apply one transition to every eligible row in a filer's group, then report
   * what actually happened.
   *
   * 🔴 THE FINAL LINE IS PAINTED AFTER THE REFRESH, AND THAT IS A DELIBERATE
   * DIVERGENCE FROM THE CARBON COPY. The legacy card paints its report and then
   * refreshes on the very next line — and the refresh rebuilds every group from
   * scratch, status span included, so the partial-failure report its own
   * docstring calls the whole point of the method is erased before anyone can
   * read it. It is invisible whenever the batch fully succeeds, because then the
   * group is gone anyway; it costs exactly the case the report exists for.
   * Painting after the repaint puts the sentence on the group that survived,
   * which is the group carrying the rows that were refused.
   *
   * ⚠️ THE IN-FLIGHT COUNT COUNTS ATTEMPTS, NOT SUCCESSES, and the line is
   * repainted after EVERY row rather than only at the end. `not_approved →
   * queued` IS the promotion, so with the approval gate enforcing, each row of a
   * batch approve asks Rick and waits out its own timeout — eight rows can hold
   * the pane for eight timeouts, and one static line painted before that wait is
   * indistinguishable from a dead pane.
   *
   * Ensures:
   *   - a blank required reason refuses BEFORE any request leaves the browser
   *   - a group with no eligible rows says so and posts nothing
   *   - a second press while a batch runs is ignored
   *   - both batch buttons are dead for the length of the batch and live after
   *   - every row is attempted, whatever the ones before it returned
   *   - the pane refreshes exactly once, after all rows have been attempted
   */
  private async runBatch( filer: string, verb: string ): Promise<void> {
    if ( filer === "" ) return;
    const needs = holdingBatchNeeds( verb );
    /* c8 ignore next */ // defensive: handleBatchClick only ever passes one of the two known verbs.
    if ( needs === null ) return;
    if ( this.batchesInFlight.has( filer ) ) return;

    const reason = needs.reason ? this.batchReason( filer ) : "";
    if ( needs.reason && reason === "" ) {
      this.paintGroupStatus( filer, HOLDING_BATCH_BLANK_REASON );
      return;
    }

    const ids = this.heldRowIdsForFiler( filer );
    if ( ids.length === 0 ) {
      this.paintGroupStatus( filer, HOLDING_BATCH_NO_ROWS );
      return;
    }

    const extras = holdingBatchExtras( verb, reason );
    this.batchesInFlight.add( filer );
    this.paintGroupStatus( filer, holdingBatchInFlightStatus( needs.pastLabel, 0, ids.length ) );
    this.setBatchControls( filer, true );

    let ok = 0;
    let failed = 0;
    let firstError: string | null = null;
    try {
      for ( const id of ids ) {
        const result = await this.store.transitionTask( id, needs.status, extras );
        if ( result.ok ) {
          ok += 1;
        } else {
          failed += 1;
          if ( firstError === null ) firstError = result.message ?? "";
        }
        this.paintGroupStatus( filer, holdingBatchInFlightStatus( needs.pastLabel, ok + failed, ids.length ) );
      }
    } finally {
      this.setBatchControls( filer, false );
      this.batchesInFlight.delete( filer );
    }

    // `refresh()` here would JOIN a poll whose fetch began before these
    // transitions landed — correct data for that poll, stale for this batch.
    await this.store.refreshAfterWrite();
    this.paintGroupStatus( filer, holdingBatchFinalStatus( needs.pastLabel, ok, failed, ids.length, firstError ) );
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
