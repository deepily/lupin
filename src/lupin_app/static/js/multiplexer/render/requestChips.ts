/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// A manager's promote/demote REQUEST on the multiplexer board — the chip, the badge and the
// Approve/Deny wiring (row c9fafb9d, design src/rnd/2026.09.10-request-door-design.md §6).
//
// 🔴 THE WORDS AND THE BODY ARE NOT DECIDED HERE. `pendingRequestChip`, `requestVerdictBody`
// and `requestBadgeText` live in shared/task-request.js, which notifications.js reads too;
// this file only turns their answers into elements and clicks into calls.
//
// ⚠️ THE CHIP SITS ON THE VISIBLE ROW, NOT IN THE DISCLOSED CONTROLS ROW. A request is a
// question waiting on Rick, and a question hidden behind a disclosure is one he has to
// already know about to find.
//
// ⚠️ EVERY VIEWER SEES APPROVE AND DENY, as every viewer sees the verb select. The verdict
// door refuses anyone but Rick and its sentence is painted verbatim; hiding the buttons
// would be presentation pretending to be a control.

import type { EventBus } from "../shared/EventBus";
import type { StoreRequestBadgesChangedPayload } from "../shared/types";
import type { TaskItem } from "./taskListModel";
import type { RequestBadgeCounts, RequestFiledDetail, RequestVerdictResult } from "../stores/TaskRequestStore";
import {
  MOVE_DEMOTE,
  VERDICT_APPROVED,
  VERDICT_DENIED,
  TRIAGE_DATE_LABEL,
  pendingRequestChip,
  requestVerdictBody,
  requestBadgeText,
} from "../../shared/task-request.js";

/** What the chip reads before the filing detail has arrived. */
export const REQUEST_DETAIL_LOADING = "loading who asked…";

/** What the chip reads when the trail carries no filing to name. */
export const REQUEST_DETAIL_UNKNOWN = "filer and reason not on the trail";

/** The in-flight line while a verdict is on the wire. */
export const REQUEST_VERDICT_SENDING = "Sending…";

/** The narrow store surface the chips need. The production TaskRequestStore satisfies it. */
export interface RequestChipStoreLike {
  submitVerdict( taskId: string, body: Record<string, unknown> ): Promise<RequestVerdictResult>;
  cachedDetail( taskId: string, requestTs: string ): RequestFiledDetail | undefined;
  loadDetail( taskId: string, requestTs: string ): Promise<void>;
}

function button( cls: string, label: string, taskId: string ): HTMLButtonElement {
  const btn = document.createElement( "button" );
  btn.type        = "button";
  btn.className   = `task-action-btn ${ cls }`;
  btn.textContent = label;
  btn.dataset.taskId = taskId;
  return btn;
}

/**
 * The pending-request chip for one row, or null when nothing is pending.
 *
 * Requires:
 *   - task is a board row; nowMs is the caller's clock
 * Ensures:
 *   - null unless `pendingRequestChip` says the row has a pending, ruled move
 *   - `.task-request-chip` carrying data-task-id, data-request-move, data-request-ts
 *   - a `.task-request-text` ("Demote requested · 3h"), an empty `.task-request-detail` the
 *     controller fills, Approve and Deny buttons, and a `.task-request-status` line
 *   - a demote chip ALSO carries a `.task-request-triage` date input, labelled the way the
 *     demote verb's own date is — approving a demote lands the row in the holding area,
 *     which needs a triage-by date
 */
export function renderRequestChip( task: TaskItem, nowMs: number ): HTMLDivElement | null {
  const chip = pendingRequestChip( task, nowMs );
  if ( chip === null ) return null;
  const taskId    = task.id ?? "";
  const requestTs = typeof task.request_ts === "string" ? task.request_ts : "";

  const el = document.createElement( "div" );
  el.className = "task-request-chip";
  el.dataset.taskId      = taskId;
  el.dataset.requestMove = chip.move;
  el.dataset.requestTs   = requestTs;

  const text = document.createElement( "span" );
  text.className   = "task-request-text";
  text.textContent = chip.age === "" ? `⏳ ${ chip.text }` : `⏳ ${ chip.text } · ${ chip.age }`;
  el.appendChild( text );

  const detail = document.createElement( "span" );
  detail.className = "task-request-detail";
  el.appendChild( detail );

  if ( chip.needsTriageDate ) {
    const date = document.createElement( "input" );
    date.type      = "date";
    date.className = "task-action-input task-request-triage";
    date.dataset.taskId = taskId;
    date.setAttribute( "aria-label", TRIAGE_DATE_LABEL );
    date.setAttribute( "title", TRIAGE_DATE_LABEL );
    el.appendChild( date );
  }

  el.appendChild( button( "task-request-approve", "Approve", taskId ) );
  el.appendChild( button( "task-request-deny", "Deny", taskId ) );

  const status = document.createElement( "span" );
  status.className = "task-request-status";
  el.appendChild( status );
  return el;
}

/** A section header's request badge, hidden until it has a count to show. */
export function renderRequestBadge( testid: string ): HTMLSpanElement {
  const badge = document.createElement( "span" );
  badge.className = "task-request-badge";
  badge.setAttribute( "data-testid", testid );
  badge.hidden = true;
  return badge;
}

/**
 * Paint one badge from the counts. The two badges read their OWN key and are never summed.
 *
 * Ensures: text from `requestBadgeText`; hidden exactly when that text is "".
 */
export function paintRequestBadge( badge: HTMLElement, counts: RequestBadgeCounts, key: string ): void {
  const text = requestBadgeText( counts, key );
  badge.textContent = text;
  badge.hidden      = text === "";
}

/**
 * `YYYY-MM-DD` from a date input → an ISO instant at 09:00 LOCAL, or null when unparseable.
 *
 * ⚠️ THE SAME CONVERSION THE DEMOTE VERB MAKES (TaskListRenderer.handleSubmitClick). A bare
 * date posted as-is is read as midnight UTC, the previous evening here.
 */
export function triageDayToIso( day: string ): string | null {
  if ( day === "" ) return null;
  const parsed = new Date( `${ day }T09:00:00` );
  return isNaN( parsed.getTime() ) ? null : parsed.toISOString();
}

export interface RequestChipController {
  /** Container click → a verdict, when the click was on a chip button. True when handled. */
  handleClick( target: EventTarget | null ): boolean;
  /** After a paint: fill every chip's filer/reason and restore any refusal it carried. */
  hydrate( container: HTMLElement ): void;
}

/**
 * One pane's chip wiring. Delegated: the pane calls `handleClick` from its container
 * listener and `hydrate` after every paint.
 *
 * 🔴 A REFUSAL IS REMEMBERED PER ROW, because the 60s poll rebuilds every chip and a
 * sentence painted once would vanish before Rick read why his click did nothing.
 */
class RequestChipControllerImpl implements RequestChipController {
  private readonly refusals = new Map<string, string>();
  private readonly inFlight = new Set<string>();

  constructor( private readonly store: RequestChipStoreLike ) {}

  handleClick( target: EventTarget | null ): boolean {
    const el = target as Element | null;
    if ( el === null || typeof el.closest !== "function" ) return false;
    const btn = el.closest<HTMLButtonElement>( ".task-request-approve, .task-request-deny" );
    if ( btn === null ) return false;
    const chip = btn.closest<HTMLElement>( ".task-request-chip" );
    /* c8 ignore next */ // defensive: both buttons are only ever built inside a chip.
    if ( chip === null ) return false;
    const verdict = btn.classList.contains( "task-request-approve" ) ? VERDICT_APPROVED : VERDICT_DENIED;
    void this.send( chip, verdict );
    return true;
  }

  hydrate( container: HTMLElement ): void {
    for ( const chip of Array.from( container.querySelectorAll<HTMLElement>( ".task-request-chip" ) ) ) {
      const taskId    = chip.dataset.taskId ?? "";
      const requestTs = chip.dataset.requestTs ?? "";
      const refusal   = this.refusals.get( taskId );
      if ( refusal !== undefined ) this.paintStatus( chip, refusal );

      const cached = this.store.cachedDetail( taskId, requestTs );
      if ( cached !== undefined ) {
        this.paintDetail( chip, cached );
        continue;
      }
      this.paintDetailText( chip, REQUEST_DETAIL_LOADING );
      void this.store.loadDetail( taskId, requestTs ).then( () => {
        // Painted onto THIS element: if a poll replaced it meanwhile, the next paint reads
        // the cache instead, and writing into a detached chip costs nothing.
        const loaded = this.store.cachedDetail( taskId, requestTs );
        if ( loaded !== undefined ) this.paintDetail( chip, loaded );
      } );
    }
  }

  private async send( chip: HTMLElement, verdict: string ): Promise<void> {
    const taskId = chip.dataset.taskId ?? "";
    const move   = chip.dataset.requestMove ?? "";
    if ( taskId === "" || this.inFlight.has( taskId ) ) return;

    let triageByIso: string | null = null;
    if ( verdict === VERDICT_APPROVED && move === MOVE_DEMOTE ) {
      const day = chip.querySelector<HTMLInputElement>( ".task-request-triage" )?.value ?? "";
      triageByIso = triageDayToIso( day );
    }
    const built = requestVerdictBody( verdict, move, { triageByIso } );
    if ( !built.ok ) {
      this.remember( chip, taskId, built.message );
      return;
    }

    this.inFlight.add( taskId );
    this.setButtons( chip, true );
    this.paintStatus( chip, REQUEST_VERDICT_SENDING );
    try {
      const result = await this.store.submitVerdict( taskId, built.body );
      if ( result.ok ) {
        this.refusals.delete( taskId );
        this.paintStatus( chip, "" );
      } else {
        this.remember( chip, taskId, result.message );
      }
    } finally {
      this.inFlight.delete( taskId );
      this.setButtons( chip, false );
    }
  }

  private remember( chip: HTMLElement, taskId: string, message: string ): void {
    this.refusals.set( taskId, message );
    this.paintStatus( chip, message );
  }

  private setButtons( chip: HTMLElement, disabled: boolean ): void {
    for ( const b of Array.from( chip.querySelectorAll<HTMLButtonElement>( ".task-request-approve, .task-request-deny" ) ) ) {
      b.disabled = disabled;
    }
  }

  private paintStatus( chip: HTMLElement, text: string ): void {
    const el = chip.querySelector<HTMLElement>( ".task-request-status" );
    if ( el !== null ) el.textContent = text;
  }

  private paintDetail( chip: HTMLElement, detail: RequestFiledDetail ): void {
    if ( detail === null ) { this.paintDetailText( chip, REQUEST_DETAIL_UNKNOWN ); return; }
    const by = detail.filer === "" ? "" : `by ${ detail.filer }`;
    this.paintDetailText( chip, [ by, detail.reason ].filter( ( s ) => s !== "" ).join( " — " ) || REQUEST_DETAIL_UNKNOWN );
  }

  private paintDetailText( chip: HTMLElement, text: string ): void {
    const el = chip.querySelector<HTMLElement>( ".task-request-detail" );
    if ( el !== null ) el.textContent = text;
  }
}

/** The store surface a whole pane needs: the chip's, plus the badge counts. */
export interface RequestBoardStoreLike extends RequestChipStoreLike {
  counts(): RequestBadgeCounts;
}

export interface RequestPaneWiring {
  /** Call first from the pane's container click listener; true means the click was ours. */
  handleClick( target: EventTarget | null ): boolean;
  /** Call after every paint that may have built rows. */
  hydrate( container: HTMLElement ): void;
  /** Detach the badge subscription. */
  dispose(): void;
}

export interface RequestPaneWiringOptions {
  bus      : EventBus;
  store    : RequestBoardStoreLike;
  /** The pane's section-header count chip; the badge is placed straight after it. */
  countEl  : HTMLElement;
  /** BADGE_HOLDING_AREA or BADGE_TASK_AREA — the ONE count this pane shows. */
  badgeKey : string;
  testid   : string;
}

/**
 * Everything one pane needs for requests: its badge beside the count chip, repainted on
 * every badge poll, and a chip controller for its rows.
 *
 * 🔴 ONE HELPER FOR BOTH PANES, so the holding area and the task list cannot disagree on
 * how a badge repaints or how a verdict is sent — only on WHICH count they show.
 *
 * Ensures:
 *   - the badge is the count chip's next sibling, painted from the store's current counts
 *   - every `store_request_badges_changed` repaints it from the store, until dispose()
 */
export function wireRequestPane( opts: RequestPaneWiringOptions ): RequestPaneWiring {
  const badge = renderRequestBadge( opts.testid );
  opts.countEl.after( badge );
  const paint = (): void => paintRequestBadge( badge, opts.store.counts(), opts.badgeKey );
  paint();
  const off        = opts.bus.on<StoreRequestBadgesChangedPayload>( "store_request_badges_changed", paint );
  const controller = new RequestChipControllerImpl( opts.store );
  return {
    handleClick : ( target ) => controller.handleClick( target ),
    hydrate     : ( container ) => controller.hydrate( container ),
    dispose     : off,
  };
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createRequestChipController( store: RequestChipStoreLike ): RequestChipController {
  return new RequestChipControllerImpl( store );
}
