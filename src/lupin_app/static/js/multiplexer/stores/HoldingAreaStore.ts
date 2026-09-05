/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Holding-area card — HoldingAreaStore (row 87812328).
//
// Owns the poll-driven holding-area lifecycle, mirroring TaskListStore. Reads
// the SHARED query string `HOLDING_AREA_QUERY` (shared/task-list-query.js) so
// the two clients cannot drift on the parameters — that module exists
// precisely because two literals had already drifted once.
//
// Fetch + cache + timer only. Grouping and sort live in
// render/holdingAreaModel.ts; the DOM dispatch lives in the renderer.
//
// ⚠️ READ-ONLY BY DESIGN AT THIS STAGE. The pane's batch verbs (approve-all /
// won't-fix-all per filer) are NOT here yet, and adding them is a deliberate
// step rather than an omission: won't-fix-all is TERMINAL and applies ONE
// reason to every row under a filer, so it wants its own review.

import type { EventBus } from "../shared/EventBus";
import type { StoreHoldingAreaChangedPayload } from "../shared/types";
import type { TaskListComposite } from "../render/taskListModel";
import { HOLDING_AREA_QUERY } from "../../shared/task-list-query.js";

/** Narrowed ApiClient surface — this store only ever reads. */
export interface HoldingAreaApiClient {
  get<T>( path: string ): Promise<T>;
}

export const HOLDING_AREA_ENDPOINT         = HOLDING_AREA_QUERY;
export const HOLDING_AREA_POLL_INTERVAL_MS = 60000;   // 60s, fleet parity

export interface HoldingAreaStore {
  /** Last fetched composite (any status), or null before the first refresh. */
  composite(): TaskListComposite | null;
  /** Fetch → cache → emit. Debounced via an in-flight guard. */
  refresh(): Promise<void>;
  /** Start the 60s poll: one immediate refresh, then the interval. Idempotent. */
  startPolling(): void;
  /** Stop the poll + clear the handle. Idempotent. */
  stopPolling(): void;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface HoldingAreaStoreOptions {
  bus              : EventBus;
  api              : HoldingAreaApiClient;
  endpoint?        : string;
  nowFn?           : () => number;
  setIntervalFn?   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn? : ( handle: number ) => void;
}

class HoldingAreaStoreImpl implements HoldingAreaStore {
  private readonly bus      : EventBus;
  private readonly api      : HoldingAreaApiClient;
  private readonly endpoint : string;
  private readonly nowFn    : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;

  private lastComposite : TaskListComposite | null = null;
  private inFlight      = false;
  private pollHandle    : number | null = null;

  constructor( opts: HoldingAreaStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: the canonical endpoint; tests inject an explicit one.
    this.endpoint = opts.endpoint ?? HOLDING_AREA_ENDPOINT;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the default above.
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
  }

  composite(): TaskListComposite | null {
    return this.lastComposite;
  }

  async refresh(): Promise<void> {
    if ( this.inFlight ) return;   // debounce: a manual tick landing on a poll can't double-fetch
    this.inFlight = true;
    try {
      this.lastComposite = await this.fetchState();
      this.emitChanged();
    } finally {
      this.inFlight = false;
    }
  }

  startPolling(): void {
    this.stopPolling();
    void this.refresh();
    this.pollHandle = this.setIntervalFn( () => void this.refresh(), HOLDING_AREA_POLL_INTERVAL_MS );
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

  private async fetchState(): Promise<TaskListComposite> {
    try {
      return await this.api.get<TaskListComposite>( this.endpoint );
    } catch ( err ) {
      const status = ( err as { status?: number } ).status;
      if ( status === 401 ) return { status: "auth_required" };
      return { status: "unreachable", tasks: null };
    }
  }

  private emitChanged( stampUpdated: boolean = true ): void {
    this.bus.emit<StoreHoldingAreaChangedPayload>( {
      type    : "store_holding_area_changed",
      payload : { stampUpdated },
      source  : "HoldingAreaStore",
      ts      : this.nowFn(),
    } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createHoldingAreaStore( opts: HoldingAreaStoreOptions ): HoldingAreaStore {
  return new HoldingAreaStoreImpl( opts );
}
