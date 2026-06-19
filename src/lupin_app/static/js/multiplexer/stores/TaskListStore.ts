/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — TaskListStore (Step 4, store-canonical task mgmt).
//
// Owns the poll-driven task-list lifecycle, mirroring FleetStatusStore. Reads
// the EXISTING `GET /api/tasks` endpoint (routers/tasks.py:419-477, full-row
// fidelity) — a read-only consumer; this card never touches tasks.py. Like
// fleet-status it is an autonomous-timer feature (60s), OFF the WS transports;
// it does NOT subscribe to the EventBus, it only emits `store_task_list_changed`.
//
// Fetch + cache + timer only. The DOM dispatch (auth_required / unreachable /
// empty / table) + the "updated" stamp live in TaskListRenderer; the pure
// grouping/format fns live in render/taskListModel.ts.

import type { EventBus } from "../shared/EventBus";
import type { StoreTaskListChangedPayload } from "../shared/types";
import type { TaskListComposite } from "../render/taskListModel";

// Narrowed ApiClient surface (shared with FleetStatusStore). The production
// ApiClient.get throws ApiError (carrying `.status`) on non-2xx; we map that to
// the display-only sentinels rather than letting it propagate.
export interface TaskListApiClient {
  get<T>( path: string ): Promise<T>;
}

// v1 read-contract: the whole fleet board, newest-first, capped. Rick's
// dashboard surfaces his own + the fleet's owed work (the renderer filters to
// open/non-terminal statuses), so NO owner_persona filter here. Retargetable
// to `?owner_persona=<self>&status=<open>` by editing this one constant if a
// per-session scope is later wanted (cascade §F left the exact param values to
// the consumer).
export const TASK_LIST_ENDPOINT         = "/api/tasks?limit=500";
export const TASK_LIST_POLL_INTERVAL_MS = 60000;   // 60s auto-poll (fleet parity)

export interface TaskListStore {
  /** Last fetched composite (any status), or null before the first refresh. */
  composite(): TaskListComposite | null;
  /** Fetch → cache → emit (stampUpdated=true). Debounced via an in-flight guard. */
  refresh(): Promise<void>;
  /** Start the 60s poll: one immediate refresh, then the interval. Idempotent. */
  startPolling(): void;
  /** Stop the poll + clear the interval handle. Idempotent. */
  stopPolling(): void;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface TaskListStoreOptions {
  bus             : EventBus;
  api             : TaskListApiClient;
  endpoint?       : string;
  nowFn?          : () => number;
  setIntervalFn?  : ( cb: () => void, ms: number ) => number;
  clearIntervalFn?: ( handle: number ) => void;
}

class TaskListStoreImpl implements TaskListStore {
  private readonly bus      : EventBus;
  private readonly api      : TaskListApiClient;
  private readonly endpoint : string;
  private readonly nowFn    : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;

  private lastComposite : TaskListComposite | null = null;
  private inFlight      = false;
  private pollHandle    : number | null = null;

  constructor( opts: TaskListStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: the canonical endpoint; tests inject an explicit one.
    this.endpoint = opts.endpoint ?? TASK_LIST_ENDPOINT;
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
    this.pollHandle = this.setIntervalFn( () => void this.refresh(), TASK_LIST_POLL_INTERVAL_MS );
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

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  private async fetchState(): Promise<TaskListComposite> {
    try {
      return await this.api.get<TaskListComposite>( this.endpoint );
    } catch ( err ) {
      const status = ( err as { status?: number } ).status;
      if ( status === 401 ) return { status: "auth_required" };
      return { status: "unreachable", tasks: null };
    }
  }

  private emitChanged(): void {
    this.bus.emit<StoreTaskListChangedPayload>( {
      type    : "store_task_list_changed",
      payload : { stampUpdated: true },
      source  : "TaskListStore",
      ts      : this.nowFn(),
    } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTaskListStore( opts: TaskListStoreOptions ): TaskListStore {
  return new TaskListStoreImpl( opts );
}
