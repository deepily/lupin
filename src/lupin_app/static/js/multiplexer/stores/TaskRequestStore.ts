/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Promote/demote REQUESTS on the board — TaskRequestStore (row c9fafb9d).
//
// Three jobs, one door family (`/api/tasks/request-badges`, `/request-verdict`, `/events`):
//   1. poll the two badge counts on the boards' 60s cadence,
//   2. send Rick's verdict on one row and resolve to a result, never a throw,
//   3. read who filed a pending request and why, once per filing.
//
// Design: src/rnd/2026.09.10-request-door-design.md §6. The chip's wording and the verdict
// body live in shared/task-request.js, so this client and notifications.js cannot drift.
//
// ⚠️ NOTHING HERE IS A CONTROL. Every viewer can press Approve or Deny; the verdict door
// refuses anyone but Rick's account and this store hands its words back verbatim.

import type { EventBus } from "../shared/EventBus";
import type { StoreRequestBadgesChangedPayload } from "../shared/types";
import { holdingRefusalMessage } from "./HoldingAreaStore";
import {
  REQUEST_BADGES_PATH,
  requestVerdictPath,
  requestEventsPath,
  requestFiledDetail,
} from "../../shared/task-request.js";

export interface TaskRequestApiClient {
  get<T>( path: string ): Promise<T>;
  post<T>( path: string, body: unknown ): Promise<T>;
}

/** The request-badges response: `{ task_area, holding_area }`, or null before/without one. */
export type RequestBadgeCounts = Record<string, unknown> | null;

/** Who filed a request and why, or null when the trail carries no filing. */
export type RequestFiledDetail = { filer: string; reason: string } | null;

/** A verdict's outcome. A refusal is a VALUE carrying the server's own words. */
export type RequestVerdictResult = { ok: true } | { ok: false; message: string };

export const TASK_REQUEST_POLL_INTERVAL_MS = 60000;   // the boards' cadence

export interface TaskRequestStore {
  /** The last badge counts, or null before the first poll or after a failed one. */
  counts(): RequestBadgeCounts;
  /** Fetch the counts → cache → emit. A collision joins the fetch in flight. */
  refresh(): Promise<void>;
  /** One immediate refresh, then the 60s interval. Idempotent. */
  startPolling(): void;
  stopPolling(): void;
  /**
   * POST one verdict. Resolves, never rejects.
   *
   * Ensures:
   *   - a 2xx resolves `{ ok: true }`, then refreshes the badges and runs `afterVerdict`
   *     (an approval MOVED the row, so both boards must re-read)
   *   - a failure resolves `{ ok: false, message }` with the server's own sentence and
   *     refreshes nothing — the row did not move
   */
  submitVerdict( taskId: string, body: Record<string, unknown> ): Promise<RequestVerdictResult>;
  /**
   * The cached filing detail for one request, or `undefined` when it has not been read.
   * Keyed by id AND request_ts, so a re-filed request is read afresh.
   */
  cachedDetail( taskId: string, requestTs: string ): RequestFiledDetail | undefined;
  /**
   * Read the filing detail once and cache it. Resolves, never rejects.
   *
   * ⚠️ A FAILED READ IS NOT CACHED. Caching it would pin "filer unknown" on the chip for
   * the life of the page over what was an outage; the next paint asks again.
   */
  loadDetail( taskId: string, requestTs: string ): Promise<void>;
  disposeForTesting(): void;
}

export interface TaskRequestStoreOptions {
  bus              : EventBus;
  api              : TaskRequestApiClient;
  /** Re-read the boards after a verdict landed. Boot passes both panes' refreshes. */
  afterVerdict?    : () => Promise<void>;
  nowFn?           : () => number;
  setIntervalFn?   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn? : ( handle: number ) => void;
}

class TaskRequestStoreImpl implements TaskRequestStore {
  private readonly bus             : EventBus;
  private readonly api             : TaskRequestApiClient;
  private readonly afterVerdict    : () => Promise<void>;
  private readonly nowFn           : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;

  private lastCounts : RequestBadgeCounts = null;
  private inFlight   : Promise<void> | null = null;
  private pollHandle : number | null = null;
  private readonly details = new Map<string, RequestFiledDetail>();

  constructor( opts: TaskRequestStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    this.afterVerdict = opts.afterVerdict ?? ( async () => { /* nothing else to re-read */ } );
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject nowFn.
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the default above.
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
  }

  counts(): RequestBadgeCounts {
    return this.lastCounts;
  }

  async refresh(): Promise<void> {
    if ( this.inFlight !== null ) return this.inFlight;
    const run = ( async () => {
      try {
        // ⚠️ A FAILED READ CLEARS THE COUNTS RATHER THAN KEEPING THE LAST ONES. A stale "2
        // requests" after the store stopped answering tells Rick something is waiting that
        // may already be answered; each pane's own sentinel reports the outage itself.
        try {
          this.lastCounts = await this.api.get<RequestBadgeCounts>( REQUEST_BADGES_PATH );
        } catch {
          this.lastCounts = null;
        }
        this.bus.emit<StoreRequestBadgesChangedPayload>( {
          type    : "store_request_badges_changed",
          payload : { known: this.lastCounts !== null },
          source  : "TaskRequestStore",
          ts      : this.nowFn(),
        } );
      } finally {
        this.inFlight = null;
      }
    } )();
    this.inFlight = run;
    return run;
  }

  startPolling(): void {
    this.stopPolling();
    void this.refresh();
    this.pollHandle = this.setIntervalFn( () => void this.refresh(), TASK_REQUEST_POLL_INTERVAL_MS );
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

  async submitVerdict( taskId: string, body: Record<string, unknown> ): Promise<RequestVerdictResult> {
    try {
      await this.api.post<unknown>( requestVerdictPath( taskId ), body );
    } catch ( err ) {
      return { ok: false, message: holdingRefusalMessage( err ) };
    }
    // 🔴 THE RE-READ WAITS ON A LANDED VERDICT, NEVER ON A SENT ONE. An approval moved the
    // row between panes, and a denial took a count off a badge; both are true only now.
    await this.refresh();
    await this.afterVerdict();
    return { ok: true };
  }

  cachedDetail( taskId: string, requestTs: string ): RequestFiledDetail | undefined {
    return this.details.get( `${ taskId }@${ requestTs }` );
  }

  async loadDetail( taskId: string, requestTs: string ): Promise<void> {
    try {
      const body = await this.api.get<{ events?: unknown }>( requestEventsPath( taskId ) );
      this.details.set( `${ taskId }@${ requestTs }`, requestFiledDetail( body ) );
    } catch {
      /* not cached on purpose — see the interface */
    }
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTaskRequestStore( opts: TaskRequestStoreOptions ): TaskRequestStore {
  return new TaskRequestStoreImpl( opts );
}
