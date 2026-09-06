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
// 🔴 THE WRITE SURFACE IS ONE VERB AND IT NEVER THROWS. `transitionTask` posts
// one row's state change and returns `{ ok }` or `{ ok, message }`. A batch is a
// LOOP over it, and a loop whose body can throw stops on its first refusal — so
// the eight rows after a 403 would never be attempted and the operator would be
// told nothing about them. Returning a result rather than raising is what makes
// "3 of 8 closed — 5 refused" expressible at all.
//
// ⚠️ NO OPTIMISTIC EDIT HERE, AND THAT IS A DIVERGENCE FROM TaskListStore RATHER
// THAN AN OMISSION. That store clones-and-merges the row before the request so a
// single edit repaints instantly. A BATCH cannot: the renderer reads its id list
// off the rendered DOM on purpose (a cached list goes stale the moment a peer
// approves something), so an optimistic removal per row would repaint the pane
// mid-loop and pull the remaining rows out from under the walk. The pane
// refreshes ONCE, after every row has been attempted.

import type { EventBus } from "../shared/EventBus";
import type { StoreHoldingAreaChangedPayload } from "../shared/types";
import type { TaskListComposite } from "../render/taskListModel";
import { deriveTaskActor } from "../render/taskListModel";
import { HOLDING_AREA_QUERY } from "../../shared/task-list-query.js";

/**
 * Narrowed ApiClient surface. `get` feeds the poll; `post` carries the batch
 * verbs' per-row transition. The production ApiClient satisfies both
 * structurally, so the stores factory hands it over unchanged.
 */
export interface HoldingAreaApiClient {
  get<T>( path: string ): Promise<T>;
  post<T>( path: string, body: unknown ): Promise<T>;
}

/**
 * One row's transition outcome. A refusal is a VALUE, never an exception — see
 * the file header: a batch is a loop, and a throwing body abandons every row
 * after the first refusal.
 */
export type HoldingTransitionResult =
  | { ok: true }
  | { ok: false; message: string };

/**
 * Turn whatever the api client threw into the sentence the operator reads.
 *
 * 🔴 THE SERVER'S OWN WORDS, VERBATIM, WHENEVER THERE ARE ANY. The refusals
 * worth reading here are authorization refusals, and a 403 from the transition
 * door carries the actor it saw and the allowlist it checked against — a
 * client-authored "permission denied" throws away the only two facts that tell
 * the operator what to do next.
 *
 * ⚠️ THE PREFIX IS RECONSTRUCTED, NOT GUESSED AT. `ApiError.message` is
 * `HTTP <status> <url>: <body>`, and both halves of that prefix are public
 * fields on the error — so the body is recovered by removing a string this
 * function BUILDS from `.status` and `.url`, never by splitting on the first
 * colon (which a URL contains).
 *
 * ⚠️ A NON-JSON ERROR BODY COLLAPSES TO THE BARE STATUS, WHICH IS THE LEGACY
 * BEHAVIOUR AND IS KEPT DELIBERATELY. An HTML error page is not a message to an
 * operator, and the two clients reporting the same 500 differently is a worse
 * outcome than either wording.
 *
 * Ensures:
 *   - an ApiError with a JSON `detail` string → that detail
 *   - an ApiError with a non-string `detail` → that detail, JSON-stringified
 *   - an ApiError with a non-JSON body → the bare status, e.g. "502"
 *   - anything else (a transport throw, which carries no status) → an
 *     "unreachable: …" line, so an outage never reads as a refusal
 *   - never throws, whatever it is handed
 */
export function holdingRefusalMessage( err: unknown ): string {
  const e = err as { status?: unknown; url?: unknown; message?: unknown };
  const text = typeof e?.message === "string" ? e.message : String( err );

  if ( typeof e?.status !== "number" ) return `unreachable: ${ text }`;

  const prefix = `HTTP ${ e.status } ${ typeof e.url === "string" ? e.url : "" }: `;
  const body   = text.startsWith( prefix ) ? text.slice( prefix.length ) : text;

  try {
    const parsed = JSON.parse( body ) as { detail?: unknown };
    const detail = parsed?.detail;
    if ( typeof detail === "string" ) return detail;
    if ( detail !== undefined )       return JSON.stringify( detail );
  } catch {
    /* non-JSON error body — the status alone is the message, as in the legacy card */
  }
  return String( e.status );
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
  /**
   * POST one row's state change. Resolves to a result, NEVER rejects — see the
   * file header for why a batch cannot tolerate a throwing loop body.
   *
   * Requires:
   *   - id is a FULL row id (not the 8-char display prefix)
   *   - extras carries the transition's own fields (`reason` for won't-fix)
   * Ensures:
   *   - a 2xx resolves `{ ok: true }`
   *   - any failure resolves `{ ok: false, message }` carrying the server's own
   *     words where it gave any
   *   - the cached composite is NOT edited and no change event is emitted; the
   *     caller refreshes once, after the whole batch
   */
  transitionTask( id: string, toStatus: string, extras: Record<string, string> ): Promise<HoldingTransitionResult>;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface HoldingAreaStoreOptions {
  bus              : EventBus;
  api              : HoldingAreaApiClient;
  endpoint?        : string;
  nowFn?           : () => number;
  /** The signed-in email the audit trail records, through `deriveTaskActor`. */
  actorProvider?   : () => string | null;
  setIntervalFn?   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn? : ( handle: number ) => void;
}

class HoldingAreaStoreImpl implements HoldingAreaStore {
  private readonly bus      : EventBus;
  private readonly api      : HoldingAreaApiClient;
  private readonly endpoint : string;
  private readonly nowFn    : () => number;
  private readonly actorProvider : () => string | null;
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
    /* c8 ignore next */ // production-default fallback: an unauthenticated construction records "anonymous"; tests inject an explicit provider.
    this.actorProvider = opts.actorProvider ?? ( () => null );
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

  async transitionTask(
    id       : string,
    toStatus : string,
    extras   : Record<string, string>,
  ): Promise<HoldingTransitionResult> {
    // ⚠️ `authority: "user_direct"` IS NOT DECORATION. The store's audit trail
    // keys provenance off it, and a batch is still a human pressing a button
    // once per group — the same authority a per-row Submit carries. Recording it
    // as anything weaker would make an operator's decision read as automation.
    const body = {
      to_status : toStatus,
      ...extras,
      actor     : deriveTaskActor( this.actorProvider() ),
      authority : "user_direct",
    };
    try {
      await this.api.post<unknown>( `/api/tasks/${ encodeURIComponent( id ) }/transition`, body );
      return { ok: true };
    } catch ( err ) {
      return { ok: false, message: holdingRefusalMessage( err ) };
    }
  }

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
