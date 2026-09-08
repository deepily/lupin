/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// FinishedTasksStore — fetch + cache + window + timer (row 470b7509).
//
// 🔴 THE DOOR IS `/api/tasks/events`, AND THAT IS RULING R5 RATHER THAN A
// PREFERENCE. `/api/tasks` cannot answer "which rows became terminal in the
// last 24 hours": no terminal-timestamp column exists in the schema, so its
// `updated_ts` moves on every write and an amended three-day-old row reads as
// freshly finished; and it orders by `created_ts`, so a row finished ten
// minutes ago sorts below every row created today. `task_events` is
// append-only, one row per state change, already ordered ts DESC.
//
// Like FleetStatusStore and TaskListStore this is an AUTONOMOUS 60s poller: it
// does not subscribe to the EventBus and rides none of the WS transports. It
// only emits `store_finished_tasks_changed`.

import type { EventBus } from "../shared/EventBus";
import type { StoreFinishedTasksChangedPayload } from "../shared/types";
import {
  FINISHED_STATUSES,
  FINISHED_TASKS_PAGE_LIMIT,
  FINISHED_TASKS_POLL_INTERVAL_MS,
  FINISHED_WINDOW_DEFAULT_DAYS,
  clampWindowDays,
  windowSinceIso,
  type FinishedEventsByStatus,
  type FinishedTaskEvent,
} from "../render/finishedTasksModel";

/** Narrowed ApiClient surface (the Pass 2 F4 idiom). */
export interface FinishedTasksApiClient {
  get<T>( path: string ): Promise<T>;
}

/** The `/api/tasks/events` response shape, per `_serialize_event`. */
interface EventStreamResponse {
  events : ReadonlyArray<FinishedTaskEvent>;
  count  : number;
}

export const FINISHED_TASKS_ENDPOINT = "/api/tasks/events";

export interface FinishedTasksStore {
  /** Events keyed by status. A status whose fetch FAILED is ABSENT, not empty. */
  eventsByStatus(): FinishedEventsByStatus;
  /** The statuses whose fetch actually succeeded, in FINISHED_STATUSES order. */
  measuredStatuses(): ReadonlyArray<string>;
  /** The first failure of the last refresh, or null when every call answered. */
  error(): string | null;
  /** The current window, in DAYS. */
  windowDays(): number;
  /** Set the window (clamped) WITHOUT fetching — the slider's live preview. */
  setWindowDays( days: number ): void;
  /** Fetch every status → cache → emit. Debounced by an in-flight guard. */
  refresh(): Promise<void>;
  /** Start the 60s poll: one immediate refresh, then the interval. Idempotent. */
  startPolling(): void;
  /** Stop the poll. Idempotent. */
  stopPolling(): void;
  disposeForTesting(): void;
}

export interface FinishedTasksStoreOptions {
  bus              : EventBus;
  api              : FinishedTasksApiClient;
  nowFn?           : () => number;
  setIntervalFn?   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn? : ( handle: number ) => void;
}

class FinishedTasksStoreImpl implements FinishedTasksStore {
  private readonly bus : EventBus;
  private readonly api : FinishedTasksApiClient;
  private readonly nowFn : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;

  private cache      : Record<string, ReadonlyArray<FinishedTaskEvent>> = {};
  private lastError  : string | null = null;
  private days       : number = FINISHED_WINDOW_DEFAULT_DAYS;
  private inFlight   = false;
  private pollHandle : number | null = null;

  constructor( opts: FinishedTasksStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    /* c8 ignore next */ // production-default fallback: pairs with the setInterval default above.
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
  }

  eventsByStatus(): FinishedEventsByStatus {
    return this.cache;
  }

  measuredStatuses(): ReadonlyArray<string> {
    return FINISHED_STATUSES.filter( ( s ) => this.cache[ s ] !== undefined );
  }

  error(): string | null {
    return this.lastError;
  }

  windowDays(): number {
    return this.days;
  }

  setWindowDays( days: number ): void {
    this.days = clampWindowDays( days );
  }

  async refresh(): Promise<void> {
    if ( this.inFlight ) return;   // a manual ⟳ landing on a tick must not double-fetch
    this.inFlight = true;
    try {
      const since = windowSinceIso( this.days, this.nowFn() );
      // 🔴 THE RESULT IS BUILT INTO A FRESH OBJECT AND SWAPPED IN AT THE END.
      // Mutating `this.cache` in place would let a renderer that repaints
      // mid-loop see one status from this window and two from the last one —
      // a pane showing two different clocks, which is the exact defect the epic
      // board's no-second-fetch rule exists to prevent.
      const next  : Record<string, ReadonlyArray<FinishedTaskEvent>> = {};
      let   failed: string | null = null;

      for ( const status of FINISHED_STATUSES ) {
        try {
          const qs = `to_status=${ encodeURIComponent( status ) }`
                   + `&since=${ encodeURIComponent( since ) }`
                   + `&limit=${ FINISHED_TASKS_PAGE_LIMIT }`;
          const body = await this.api.get<EventStreamResponse>( `${ FINISHED_TASKS_ENDPOINT }?${ qs }` );
          // ⚠️ A NON-ARRAY BODY LEAVES THE KEY ABSENT rather than defaulting to
          // []. `[]` is the shape that renders as "nothing finished", and a
          // malformed response has measured nothing — reporting it as a zero is
          // the one failure this pane must never produce.
          if ( Array.isArray( body?.events ) ) next[ status ] = body.events;
          else failed = failed ?? `malformed response for ${ status }`;
        } catch ( err ) {
          // 🔴 ONE STATUS'S FAILURE MUST NOT ABANDON THE OTHERS. The loop
          // continues, its key stays absent, and the renderer reports a PARTIAL
          // result — which is a different statement from either "all fine" or
          // "nothing reachable", and the operator needs to be able to tell.
          failed = failed ?? describeFailure( err, status );
        }
      }

      this.cache     = next;
      this.lastError = failed;
      this.emitChanged( true );
    } finally {
      this.inFlight = false;
    }
  }

  startPolling(): void {
    this.stopPolling();
    void this.refresh();
    this.pollHandle = this.setIntervalFn( () => void this.refresh(), FINISHED_TASKS_POLL_INTERVAL_MS );
  }

  stopPolling(): void {
    if ( this.pollHandle !== null ) {
      this.clearIntervalFn( this.pollHandle );
      this.pollHandle = null;
    }
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    this.stopPolling();
  }
  /* c8 ignore stop */

  private emitChanged( stampUpdated: boolean ): void {
    this.bus.emit<StoreFinishedTasksChangedPayload>( {
      type    : "store_finished_tasks_changed",
      payload : { stampUpdated },
      source  : "FinishedTasksStore",
      ts      : this.nowFn(),
    } );
  }
}

/**
 * A human-readable failure for one status's call.
 *
 * ⚠️ THE STATUS IS IN THE MESSAGE ON PURPOSE. "HTTP 500" tells an operator
 * nothing about WHICH of three calls failed, and the partial sentinel's whole
 * job is to say what is missing from the rows below it.
 */
function describeFailure( err: unknown, status: string ): string {
  const httpStatus = ( err as { status?: number } ).status;
  if ( httpStatus === 401 ) return `sign-in required (${ status })`;
  if ( typeof httpStatus === "number" ) return `HTTP ${ httpStatus } (${ status })`;
  const message = ( err as { message?: string } ).message;
  return `${ message ?? String( err ) } (${ status })`;
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFinishedTasksStore( opts: FinishedTasksStoreOptions ): FinishedTasksStore {
  return new FinishedTasksStoreImpl( opts );
}
