/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — BroadcastAckTallyRenderer (row 4f320c27 M1).
//
// The tally half of the legacy `broadcast-panel.js` aggregate panel, which the
// multiplexer never received: BroadcastCardRenderer ported only the COMPOSE half,
// so after a send the mux showed nothing about who had answered.
//
// 🔴 ONE DIFFERENCE FROM LEGACY, AND IT IS THE POINT OF THE WHOLE ROW. Legacy held
// `receivedAcks` in a module-local Map, so closing the page lost the tally outright.
// Here the acks are PERSISTED server-side and AckStore.hydrate replays them, so the
// tally survives a reload. That is the only behaviour that distinguishes hydration
// from live folding, and it is what the Playwright reload case exercises.
//
// WHAT IS PORTED VERBATIM, because the legacy strings are what the user knows:
//   summary     timed out  -> "R/E sessions acknowledged — N timed out"
//               complete   -> "✅ All N session(s) acknowledged"
//               partial    -> "R/E complete"
//   ack row     icon (fallback 👤) · persona (fallback the session id's first 8) ·
//               "[status]" (fallback "?") · the body summary
//   pending row "waiting on: a, b" — shown only while partial AND not timed out
//
// 🔴 EVERY STRING GOES IN THROUGH textContent, NEVER innerHTML. `body_summary` and
// `persona_name` are server-side text that originates in another seat's payload —
// legacy marked this T10 and it is the same hazard here.
//
// EXPECTED vs RECEIVED. "Expected" is BroadcastStore's recipient list, the same
// source legacy's `expectedSessions` came from. A reload rehydrates recipients from
// /api/commons/active-sessions, which means the expected set is the CURRENT roster
// rather than the one captured at send time — a seat reaped since the broadcast
// drops out of the denominator. Legacy had the same property for a different reason
// (it kept no history at all). Recorded rather than silently accepted: a tally that
// reads 3/3 after a reap and 3/4 before it is the same tally, honestly.

import type { EventBus } from "../shared/EventBus";
import type { AckStore, BroadcastAck } from "../stores/AckStore";
import type { BroadcastStore } from "../stores/BroadcastStore";
import type { StoreBroadcastAcksChangedPayload } from "../shared/types";

// Legacy AUTO_DISMISS_MS. A partial tally at the deadline goes to the timed-out
// state; a complete one is dismissed quietly.
const DEFAULT_TIMEOUT_MS = 30_000;

export interface BroadcastAckTallyRenderer {
  /** Build the tally into `root` and subscribe. Throws on a 2nd mount. */
  mount( root: HTMLElement ): void;
  /** Begin tallying `broadcastId`: render, and start the timeout clock. */
  track( broadcastId: string ): void;
  /** Stop tallying and clear the panel (the card was dismissed). */
  dismiss(): void;
  /** Unsubscribe, cancel the timer, empty the root. */
  unmount(): void;
  /** The broadcast currently being tallied, or null. */
  trackedBroadcastId(): string | null;
}

export interface BroadcastAckTallyRendererOptions {
  eventBus        : EventBus;
  ackStore        : AckStore;
  broadcastStore  : BroadcastStore;
  timeoutMs      ?: number;
  setTimeoutFn   ?: ( cb: () => void, ms: number ) => unknown;
  clearTimeoutFn ?: ( id: unknown ) => void;
}

function shortId( sessionId: string | null ): string {
  return sessionId ? sessionId.slice( 0, 8 ) : "unknown";
}

function el( tag: string, className: string, text: string ): HTMLElement {
  const node = document.createElement( tag );
  node.className   = className;
  // 🔴 textContent, never innerHTML — see the T10 note in the file header.
  node.textContent = text;
  return node;
}

class BroadcastAckTallyRendererImpl implements BroadcastAckTallyRenderer {
  private readonly bus            : EventBus;
  private readonly ackStore       : AckStore;
  private readonly broadcastStore : BroadcastStore;
  private readonly timeoutMs      : number;
  private readonly setTimeoutFn   : ( cb: () => void, ms: number ) => unknown;
  private readonly clearTimeoutFn : ( id: unknown ) => void;

  private root        : HTMLElement | null = null;
  private unsubscribe : ( () => void ) | null = null;
  private broadcastId : string | null = null;
  private timerId     : unknown = null;
  private timedOut    = false;

  constructor( options: BroadcastAckTallyRendererOptions ) {
    this.bus            = options.eventBus;
    this.ackStore       = options.ackStore;
    this.broadcastStore = options.broadcastStore;
    // Both arms are exercised: most tests pass an explicit timeoutMs, and one omits
    // it so the production default is measured rather than assumed.
    this.timeoutMs      = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    /* c8 ignore next */ // production-default fallback: the runtime timer; tests always inject deterministic ones.
    this.setTimeoutFn   = options.setTimeoutFn ?? ( ( cb, ms ) => globalThis.setTimeout( cb, ms ) );
    /* c8 ignore next */ // production-default fallback: the runtime timer; tests always inject deterministic ones.
    this.clearTimeoutFn = options.clearTimeoutFn ?? ( ( id ) => globalThis.clearTimeout( id as never ) );
  }

  mount( root: HTMLElement ): void {
    if ( this.root ) throw new Error( "BroadcastAckTallyRenderer: already mounted" );
    this.root = root;
    this.unsubscribe = this.bus.on<StoreBroadcastAcksChangedPayload>(
      "store_broadcast_acks_changed",
      ( e ) => {
        // Another broadcast's tally changing must not repaint this one.
        if ( e.payload.broadcast_id === this.broadcastId ) this.render();
      },
    );
    this.render();
  }

  trackedBroadcastId(): string | null {
    return this.broadcastId;
  }

  track( broadcastId: string ): void {
    this.broadcastId = broadcastId;
    this.timedOut    = false;
    this.cancelTimer();
    this.timerId = this.setTimeoutFn( () => this.onDeadline(), this.timeoutMs );
    this.render();
  }

  dismiss(): void {
    this.broadcastId = null;
    this.timedOut    = false;
    this.cancelTimer();
    this.render();
  }

  unmount(): void {
    this.cancelTimer();
    if ( this.unsubscribe ) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    if ( this.root ) this.root.replaceChildren();
    this.root        = null;
    this.broadcastId = null;
    this.timedOut    = false;
  }

  private cancelTimer(): void {
    if ( this.timerId === null ) return;
    this.clearTimeoutFn( this.timerId );
    this.timerId = null;
  }

  private onDeadline(): void {
    // 🔴 NO `broadcastId === null` GUARD HERE, DELIBERATELY. Every path that clears
    // the tracked broadcast — dismiss, unmount, re-track — cancels this timer first,
    // so the guard could never fire and coverage said so: it was an unreachable
    // branch, which is a claim about a state the code cannot be in. The id is
    // captured below instead, so the non-null-ness is structural rather than
    // asserted. `track()` is the only writer, and it sets the id before arming.
    const broadcastId = this.broadcastId as string;
    this.timerId = null;
    // Legacy: a partial tally at the deadline goes TIMED OUT and stays on screen;
    // a complete one is dismissed quietly, because there is nothing left to report.
    if ( this.ackStore.countFor( broadcastId ) < this.expected().length ) {
      this.timedOut = true;
      this.render();
    } else {
      this.dismiss();
    }
  }

  private expected(): ReadonlyArray<{ session_id: string; persona_name: string | null }> {
    return this.broadcastStore.recipients().map( r => ( {
      session_id  : r.session_id,
      persona_name: r.persona_name ?? null,
    } ) );
  }

  private summaryText( received: number, expected: number ): string {
    if ( this.timedOut ) {
      return `${received}/${expected} sessions acknowledged — ${expected - received} timed out`;
    }
    if ( received === expected ) {
      return `✅ All ${expected} session${expected === 1 ? "" : "s"} acknowledged`;
    }
    return `${received}/${expected} complete`;
  }

  private render(): void {
    const root = this.root;
    if ( !root ) return;
    root.replaceChildren();
    root.classList.toggle( "timed-out", this.timedOut );
    if ( this.broadcastId === null ) return;

    const acks     = this.ackStore.acksFor( this.broadcastId );
    const expected = this.expected();
    const received = acks.length;

    const panel = document.createElement( "div" );
    panel.className = "broadcast-ack-tally";
    panel.setAttribute( "data-testid", "broadcast-ack-tally" );
    panel.setAttribute( "data-broadcast-id", this.broadcastId );
    panel.setAttribute( "data-received", String( received ) );
    panel.setAttribute( "data-expected", String( expected.length ) );
    if ( this.timedOut ) panel.setAttribute( "data-timed-out", "true" );

    const summary = el( "div", "broadcast-ack-summary", this.summaryText( received, expected.length ) );
    summary.id = "broadcast-aggregate-summary";
    summary.setAttribute( "data-testid", "broadcast-ack-summary" );
    panel.appendChild( summary );

    acks.forEach( ( ack ) => panel.appendChild( this.ackRow( ack ) ) );

    const pending = this.pendingNames( acks, expected );
    if ( pending.length > 0 ) {
      const row = el( "div", "broadcast-pending-row", `waiting on: ${pending.join( ", " )}` );
      row.setAttribute( "data-testid", "broadcast-ack-pending" );
      panel.appendChild( row );
    }

    root.appendChild( panel );
  }

  private ackRow( ack: BroadcastAck ): HTMLElement {
    const row = document.createElement( "div" );
    row.className = "broadcast-ack-row";
    row.setAttribute( "data-testid", "broadcast-ack-row" );
    if ( ack.session_id ) row.setAttribute( "data-session-id", ack.session_id );

    const icon = el( "span", "broadcast-ack-icon", ack.persona_icon || "👤" );
    // The chip carries the seat's colour when it has one; an unattributed ack is
    // left unstyled rather than given an invented default.
    if ( ack.persona_color ) icon.style.color = ack.persona_color;

    row.appendChild( icon );
    row.appendChild( el( "span", "broadcast-ack-persona", ack.persona_name || shortId( ack.session_id ) ) );
    row.appendChild( el( "span", "broadcast-ack-status", `[${ack.status || "?"}]` ) );
    row.appendChild( el( "span", "broadcast-ack-summary-text", ack.body_summary ) );
    return row;
  }

  private pendingNames(
    acks    : ReadonlyArray<BroadcastAck>,
    expected: ReadonlyArray<{ session_id: string; persona_name: string | null }>,
  ): string[] {
    // Legacy shows the pending list only while PARTIAL and NOT timed out: once the
    // deadline has passed, "waiting on" is a claim that is no longer true.
    if ( this.timedOut || acks.length >= expected.length ) return [];
    const acked = new Set( acks.map( a => a.session_id ).filter( ( s ): s is string => s !== null ) );
    return expected
      .filter( r => !acked.has( r.session_id ) )
      .map( r => r.persona_name || shortId( r.session_id ) );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line — c8 reports ONE location for this "branch" where a real conditional carries two.
export function createBroadcastAckTallyRenderer(
  options: BroadcastAckTallyRendererOptions,
): BroadcastAckTallyRenderer {
  return new BroadcastAckTallyRendererImpl( options );
}
