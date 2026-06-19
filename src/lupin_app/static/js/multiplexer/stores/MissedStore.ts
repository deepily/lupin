/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP15 — MissedStore (F7, messaging-coordination plane lever D).
//
// Surfaces "N missed while away" — the count of notifications that accumulated
// while the user was offline. Ports legacy notifications.js:14705-14750
// (`_surfaceMissedNotifications` + `resetMissedNotifications`).
//
// Two inputs mutate the count:
//   1. `auth_success` — on (re)connect the server includes `undelivered_count`.
//      Post-WP0 the WS frame is FLAT (`{type, timestamp, ...data}`, no nested
//      `data` key); QueueTransport.onMessage emits the EventBus payload as the
//      frame minus `type`+`timestamp`, so this consumer reads the count directly
//      off `payload.undelivered_count` (shared/types.ts ServerFrameEnvelope).
//   2. `reset()` — soft-dismiss (`is_hidden=True`, reversible, NO confirm per
//      Rick / commit bbde599). POSTs the dismiss endpoint and adopts the
//      post-dismiss `undelivered_count` (0 on success).

import type { EventBus } from "../shared/EventBus";
import type { LupinEvent, StoreMissedChangedPayload } from "../shared/types";

// Narrowed ApiClient surface (Pass 2 F4 idiom — depend only on what we use).
// The production ApiClient satisfies this structurally.
export interface MissedApiClient {
  post<T>( path: string, body: unknown ): Promise<T>;
}

// auth_success payload — the count lives flat under `undelivered_count` (the
// transport emits the frame minus `type`+`timestamp`; no nested `data` envelope).
interface AuthSuccessPayload {
  undelivered_count? : unknown;
}

// Dismiss endpoint response — notifications.py:1305 §dismiss
// `{ status, dismissed_count, undelivered_count, timestamp }`.
interface DismissResponse {
  undelivered_count? : unknown;
}

export const DISMISS_ENDPOINT = "/api/notifications/undelivered/dismiss";

/**
 * Coerce an arbitrary server value to a non-negative integer count.
 *
 * Requires: nothing.
 * Ensures: returns `floor(n)` for a finite n > 0; otherwise 0 (parity with
 *          legacy `Number(count) || 0`, hardened against negatives/fractions).
 */
export function coerceCount( v: unknown ): number {
  const n = Number( v );
  if ( !Number.isFinite( n ) || n <= 0 ) return 0;
  return Math.floor( n );
}

export interface MissedStore {
  count(): number;
  /**
   * Soft-dismiss the missed notifications. No-op (returns 0) when the count is
   * already zero. On success adopts the post-dismiss count (0). Rejects if the
   * POST fails — the count is left unchanged so the badge stays for a retry.
   */
  reset(): Promise<number>;
  /** Test/cleanup helper: detach EventBus listeners. */
  disposeForTesting(): void;
}

export interface MissedStoreOptions {
  bus    : EventBus;
  api    : MissedApiClient;
  nowFn? : () => number;
}

class MissedStoreImpl implements MissedStore {
  private readonly bus   : EventBus;
  private readonly api   : MissedApiClient;
  private readonly nowFn : () => number;

  private undeliveredCount = 0;
  private readonly unsubscribers: Array<() => void> = [];

  constructor( opts: MissedStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    this.unsubscribers.push(
      this.bus.on<AuthSuccessPayload>( "auth_success", ( e ) => this.onAuthSuccess( e ) ),
    );
  }

  count(): number {
    return this.undeliveredCount;
  }

  async reset(): Promise<number> {
    if ( this.undeliveredCount <= 0 ) return 0;
    // POST with no body; ApiClient sends the Authorization header.
    const resp = await this.api.post<DismissResponse>( DISMISS_ENDPOINT, {} );
    const remaining = coerceCount( resp.undelivered_count );
    this.setCount( remaining );
    return remaining;
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    for ( const off of this.unsubscribers ) off();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Reducer
  // -------------------------------------------------------------------------

  private onAuthSuccess( e: LupinEvent<AuthSuccessPayload> ): void {
    // payload may be undefined if the server frame carried no count — coerce
    // handles undefined → 0 (defensive; the live flat frame carries the count).
    const next = coerceCount( e.payload?.undelivered_count );
    this.setCount( next );
  }

  private setCount( next: number ): void {
    // Always emit so the renderer reconciles even on a 0→0 auth_success (the
    // badge stays hidden) and on a real change. The renderer is idempotent.
    this.undeliveredCount = next;
    this.bus.emit<StoreMissedChangedPayload>( {
      type    : "store_missed_changed",
      payload : { count: next },
      source  : "MissedStore",
      ts      : this.nowFn(),
    } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createMissedStore( opts: MissedStoreOptions ): MissedStore {
  return new MissedStoreImpl( opts );
}
