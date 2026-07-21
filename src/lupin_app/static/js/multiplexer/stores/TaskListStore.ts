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
import type { TaskItem, TaskListComposite } from "../render/taskListModel";
import { deriveTaskActor } from "../render/taskListModel";

// Narrowed ApiClient surface. The production ApiClient.get throws ApiError
// (carrying `.status`) on non-2xx; refresh() maps that to the display-only
// sentinels rather than letting it propagate. Phase 2 widens this to the WRITE
// verbs the editing controls ride: PATCH (priority / owner reassignment) and
// POST (drop-with-reason via the transition endpoint). The production ApiClient
// satisfies all three structurally; the read-only fleet/get callers are
// unaffected (they only ever touch `.get`).
export interface TaskListApiClient {
  get<T>( path: string ): Promise<T>;
  patch<T>( path: string, body: unknown ): Promise<T>;
  post<T>( path: string, body: unknown ): Promise<T>;
}

// The descriptive fields the PATCH endpoint accepts from the card (D2/D3 scope):
// priority (P0–P3) and owner_persona (reassignment; null clears the owner).
// Title/body/accountable_manager/gate_class are PATCH-able server-side but out
// of the per-row editing scope, so they are not surfaced here.
export interface TaskPatchFields {
  priority?      : string;
  owner_persona? : string | null;
}

// The optimistic-mutation handle returned by patchTask/dropTask — mirrors the
// `{ restoreState }` rollback contract of JobStore.delete, plus a `done` promise
// the renderer awaits to drive the JobsPaneRenderer-style success / 404-as-
// success / rollback-on-error flow. `done` resolves on a 2xx and rejects with
// the ApiError the production ApiClient throws on non-2xx.
export interface TaskMutation {
  restoreState : () => void;
  done         : Promise<void>;
}

// v1 read-contract: the whole fleet board, newest-first, capped. Rick's
// dashboard surfaces his own + the fleet's owed work (the renderer filters to
// open/non-terminal statuses), so NO owner_persona filter here. Retargetable
// to `?owner_persona=<self>&status=<open>` by editing this one constant if a
// per-session scope is later wanted (cascade §F left the exact param values to
// the consumer).
// unscoped_audit=true: this is a DELIBERATE full-board sweep (the human's
// dashboard), so it passes the repository unscoped-size guard's escape rather
// than 400ing once the store exceeds the threshold. include_terminal=true:
// preserve the documented "any status" composite (the renderer, not the server,
// filters to open) — the human's view is never silently truncated.
// char_budget=0: the explicit opt-out from the server's response BYTE budget
// (mini-plan 02, 2026-07-21). That budget defaults to 100k chars and exists to
// protect an agent from pulling ~97k tokens into a context — but this poll is
// the human's deliberate full-board sweep, and it measured 30 of 1100 rows
// under the default. The invariant three lines above ("never silently
// truncated") is the reason this escape is named here rather than the budget
// being widened for everyone.
export const TASK_LIST_ENDPOINT         = "/api/tasks?limit=500&unscoped_audit=true&include_terminal=true&char_budget=0";
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
  /**
   * Phase 2 — optimistically PATCH a cached task's descriptive fields (priority
   * and/or owner reassignment) and fire the server PATCH. The cached row is
   * mutated in place + `store_task_list_changed` emitted (no "updated" re-stamp
   * — the edit is not a fetch) so the card repaints instantly; the returned
   * `restoreState` reverts that optimistic edit (and re-emits) for the renderer
   * to call on a non-404 failure. `actor` is derived from the authenticated user
   * (Q1) and `authority='user_direct'` is stamped server-side audit (F4). A miss
   * (no cached composite / unknown id) is a no-op: no api call, resolved `done`,
   * no-op `restoreState`.
   */
  patchTask( id: string, fields: TaskPatchFields ): TaskMutation;
  /**
   * Phase 2 — optimistically DROP a task (D3 — `transition`→`dropped`, preserving
   * the append-only audit trail) with a non-blank `reason` (server requires it).
   * The cached row is removed from the open view + emitted; `restoreState`
   * re-inserts it. Same no-op semantics as patchTask on a miss.
   */
  dropTask( id: string, reason: string ): TaskMutation;
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
  /**
   * Phase 2 — supplies the authenticated user's identity (e.g. the JWT email
   * claim) for the audit `actor` of UI edits (Q1). Boot wires
   * `() => authManager.getCurrentUserEmail()`; the store funnels the result
   * through `deriveTaskActor`. Defaults to `() => null` (→ "anonymous
   * (multiplexer)") when omitted — read-only constructions never reach the
   * write paths, so the default is an ignored production fallback.
   */
  actorProvider?  : () => string | null;
}

class TaskListStoreImpl implements TaskListStore {
  private readonly bus      : EventBus;
  private readonly api      : TaskListApiClient;
  private readonly endpoint : string;
  private readonly nowFn    : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;
  private readonly actorProvider   : () => string | null;

  private lastComposite : TaskListComposite | null = null;
  private inFlight      = false;
  private pollHandle    : number | null = null;

  constructor( opts: TaskListStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: boot wires the real authManager email provider; read-only test constructions never reach the write paths.
    this.actorProvider = opts.actorProvider ?? ( () => null );
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
  // Phase 2 — optimistic mutations (PATCH priority/owner; transition→dropped)
  // -------------------------------------------------------------------------

  patchTask( id: string, fields: TaskPatchFields ): TaskMutation {
    const tasks = this.openTasksOrNull();
    if ( tasks === null ) return NOOP_MUTATION();
    const idx = tasks.findIndex( ( t ) => t.id === id );
    if ( idx < 0 ) return NOOP_MUTATION();

    const snapshot = tasks.slice();          // shallow copy for rollback
    tasks[ idx ] = { ...tasks[ idx ], ...fields };   // optimistic clone-and-merge
    this.emitChanged( false );               // repaint now; NOT a fetch → no re-stamp

    const body = { ...fields, actor: this.actor(), authority: "user_direct" };
    const done = this.api.patch<unknown>( `/api/tasks/${id}`, body ).then( () => undefined );
    return { restoreState: this.makeRestorer( snapshot ), done };
  }

  dropTask( id: string, reason: string ): TaskMutation {
    const tasks = this.openTasksOrNull();
    if ( tasks === null ) return NOOP_MUTATION();
    const idx = tasks.findIndex( ( t ) => t.id === id );
    if ( idx < 0 ) return NOOP_MUTATION();

    const snapshot = tasks.slice();
    tasks.splice( idx, 1 );                   // optimistic removal from the open view
    this.emitChanged( false );

    const body = { to_status: "dropped", reason, actor: this.actor(), authority: "user_direct" };
    const done = this.api.post<unknown>( `/api/tasks/${id}/transition`, body ).then( () => undefined );
    return { restoreState: this.makeRestorer( snapshot ), done };
  }

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

  // The cached open-task array (the live, mutable `tasks` reference), or null
  // when no good fetch is cached (pre-first-poll / auth / unreachable sentinel).
  private openTasksOrNull(): TaskItem[] | null {
    const c = this.lastComposite;
    return ( c !== null && Array.isArray( c.tasks ) ) ? c.tasks : null;
  }

  // Build a rollback closure from a pre-mutation array snapshot: refill whatever
  // tasks array is currently cached (re-read at call time so a poll that lands
  // mid-edit restores into the CURRENT composite, never a stale one) and re-emit.
  private makeRestorer( snapshot: TaskItem[] ): () => void {
    return (): void => {
      const tasks = this.openTasksOrNull();
      /* c8 ignore next */ // defensive: rollback only fires from the renderer's failure path while a composite is cached; a sentinel-replacing poll racing in between is not exercised.
      if ( tasks === null ) return;
      tasks.length = 0;
      tasks.push( ...snapshot );
      this.emitChanged( false );
    };
  }

  private actor(): string {
    return deriveTaskActor( this.actorProvider() );
  }

  private emitChanged( stampUpdated: boolean = true ): void {
    this.bus.emit<StoreTaskListChangedPayload>( {
      type    : "store_task_list_changed",
      payload : { stampUpdated },
      source  : "TaskListStore",
      ts      : this.nowFn(),
    } );
  }
}

// A no-op mutation handle for the cache-miss path (no cached composite / unknown
// id): no api call, an immediately-resolved `done`, an inert `restoreState`.
function NOOP_MUTATION(): TaskMutation {
  return { restoreState: () => { /* nothing to revert */ }, done: Promise.resolve() };
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTaskListStore( opts: TaskListStoreOptions ): TaskListStore {
  return new TaskListStoreImpl( opts );
}
