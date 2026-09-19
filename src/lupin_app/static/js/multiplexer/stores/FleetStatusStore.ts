/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP12 — FleetStatusStore (F12).
//
// Owns the poll-driven fleet-state lifecycle. Ports legacy
// notifications.js:8457-8488 (fetch), 8643-8656 (toggle), 8912-8966
// (refresh/debounce/poll). Fleet status is the ONLY POLLING feature (60s) —
// everything else in the multiplexer is WS-reactive — so this store does NOT
// subscribe to the EventBus; it only emits `store_fleet_status_changed`.
//
// The DOM dispatch (sign-in / unreachable / empty / table) + the "updated"
// stamp live in FleetStatusRenderer; the grouping/format pure fns live in
// render/fleetModel.ts. This store is fetch + cache + view-toggle + timer only.
//
// Parity A-2 #5 (row 18d06df7): it also owns the fleet-size-cap dial's numbers,
// porting legacy notifications.js:9205-9349 (fetch + save) and the cap half of
// :9396-9421 (the dial rides the same refresh as the table). It emits its own
// `store_fleet_size_cap_changed`, so a save never rebuilds the table.

import type { EventBus } from "../shared/EventBus";
import type { StoreFleetSizeCapChangedPayload, StoreFleetStatusChangedPayload } from "../shared/types";
import type { FleetComposite } from "../render/fleetModel";

// Narrowed ApiClient surface (Pass 2 F4 idiom). The production ApiClient.get
// throws ApiError (carrying `.status`) on non-2xx; we map that to the legacy
// display-only sentinels rather than letting it propagate.
export interface FleetApiClient {
  get<T>( path: string ): Promise<T>;
  put<T>( path: string, body: unknown ): Promise<T>;
}

export const FLEET_STATE_ENDPOINT          = "/api/arbiter/fleet-state";
export const FLEET_SIZE_CAP_ENDPOINT       = "/api/arbiter/fleet-size-cap";
export const FLEET_STATUS_POLL_INTERVAL_MS = 60000;   // 60s auto-poll (D4)

/** Who occupies the cap right now — every session counts, managers included. */
export interface FleetLiveCounts {
  total    : number;
  managers : number;
  workers  : number;
}

/**
 * The body of GET and PUT /api/arbiter/fleet-size-cap. Fields are optional because
 * this is what the server SENT, not what it promised: the renderer paints only when
 * both numbers are finite, and hides the dial otherwise (legacy :9273-9276).
 */
export interface FleetSizeCap {
  cap?     : number;
  ceiling? : number;
  live?    : FleetLiveCounts | null;
}

export interface FleetStatusStore {
  /** Last fetched composite (any status), or null before the first refresh. */
  composite(): FleetComposite | null;
  /** Current live-only/offline view flag. */
  showOfflineFlag(): boolean;
  /** Fetch → cache → emit (stampUpdated=true). Debounced via an in-flight guard. */
  refresh(): Promise<void>;
  /** Flip the offline view + emit (stampUpdated=false — a view re-render is NOT a fetch). */
  toggleShowOffline(): void;
  /** Start the 60s poll: one immediate refresh, then the interval. Idempotent. */
  startPolling(): void;
  /** Stop the poll + clear the interval handle. Idempotent. */
  stopPolling(): void;
  /** The dial's last numbers from the server, or null before a read / after a failed one. */
  sizeCap(): FleetSizeCap | null;
  /** The cap being saved while a PUT is in flight, else null. */
  sizeCapSaving(): number | null;
  /** GET the dial's numbers, cache, emit. Never throws. */
  refreshSizeCap(): Promise<void>;
  /** PUT a new cap, then hold the SERVER's answer — or re-read on a refusal. Never throws. */
  setSizeCap( cap: number ): Promise<void>;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface FleetStatusStoreOptions {
  bus             : EventBus;
  api             : FleetApiClient;
  nowFn?          : () => number;
  setIntervalFn?  : ( cb: () => void, ms: number ) => number;
  clearIntervalFn?: ( handle: number ) => void;
  /** Where a dial failure is reported. Defaults to console.error: legacy reports through
   *  error(), not log(), because log() is gated on debug and a dial that quietly declines
   *  to paint cannot be told apart from one nobody built (legacy :9211-9213). */
  errorFn?        : ( message: string ) => void;
}

class FleetStatusStoreImpl implements FleetStatusStore {
  private readonly bus   : EventBus;
  private readonly api   : FleetApiClient;
  private readonly nowFn : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;
  private readonly errorFn         : ( message: string ) => void;

  private lastComposite : FleetComposite | null = null;
  private showOffline   = false;
  private inFlight       = false;
  private pollHandle    : number | null = null;
  private lastSizeCap   : FleetSizeCap | null = null;
  private savingCap     : number | null = null;

  constructor( opts: FleetStatusStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the default above.
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
    /* c8 ignore next */ // production-default fallback: console.error is the runtime sink; tests inject a collector.
    this.errorFn         = opts.errorFn ?? ( ( m ) => console.error( `[FleetStatusStore] ${m}` ) );
  }

  composite(): FleetComposite | null {
    return this.lastComposite;
  }

  showOfflineFlag(): boolean {
    return this.showOffline;
  }

  async refresh(): Promise<void> {
    if ( this.inFlight ) return;   // debounce: a manual click landing on a tick can't double-fetch
    this.inFlight = true;
    try {
      this.lastComposite = await this.fetchState();
      this.emitChanged( true );
      // The dial rides the SAME refresh as the table it sits above, so the cap on
      // screen and the fleet on screen are read at the same moment (legacy :9414-9417).
      await this.refreshSizeCap();
    } finally {
      this.inFlight = false;
    }
  }

  toggleShowOffline(): void {
    this.showOffline = !this.showOffline;
    this.emitChanged( false );
  }

  startPolling(): void {
    this.stopPolling();
    void this.refresh();
    this.pollHandle = this.setIntervalFn( () => void this.refresh(), FLEET_STATUS_POLL_INTERVAL_MS );
  }

  stopPolling(): void {
    if ( this.pollHandle !== null ) {
      this.clearIntervalFn( this.pollHandle );
      this.pollHandle = null;
    }
  }

  sizeCap(): FleetSizeCap | null {
    return this.lastSizeCap;
  }

  sizeCapSaving(): number | null {
    return this.savingCap;
  }

  async refreshSizeCap(): Promise<void> {
    try {
      this.lastSizeCap = await this.api.get<FleetSizeCap>( FLEET_SIZE_CAP_ENDPOINT );
    } catch ( err ) {
      const status = ( err as { status?: number } ).status;
      this.errorFn( typeof status === "number"
        ? `Fleet size cap unavailable (HTTP ${status})`
        : `Fleet size cap fetch failed: ${err}` );
      this.lastSizeCap = null;
    }
    this.emitSizeCapChanged();
  }

  async setSizeCap( cap: number ): Promise<void> {
    this.savingCap = cap;
    this.emitSizeCapChanged();
    let persisted: FleetSizeCap | null = null;
    try {
      // 🔴 THE ANSWER IS THE SERVER'S RE-READ OF THE FILE, NOT THE VALUE SENT
      // (legacy :9323-9326), so a dial that drifted from what was persisted
      // corrects itself on this paint.
      persisted = await this.api.put<FleetSizeCap>( FLEET_SIZE_CAP_ENDPOINT, { cap } );
    } catch ( err ) {
      const status = ( err as { status?: number } ).status;
      this.errorFn( typeof status === "number"
        ? `Fleet cap not saved: ${serverDetail( err, status )}`
        : `Fleet cap save failed: ${err}` );
    }
    this.savingCap = null;
    // On a refusal, re-read the live state so the handle snaps back to the cap that is
    // actually enforced rather than sitting at a number the operator never got
    // (legacy :9383-9388). refreshSizeCap emits; the success path emits here.
    if ( persisted === null ) {
      await this.refreshSizeCap();
      return;
    }
    this.lastSizeCap = persisted;
    this.emitSizeCapChanged();
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    this.stopPolling();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  private async fetchState(): Promise<FleetComposite> {
    try {
      return await this.api.get<FleetComposite>( FLEET_STATE_ENDPOINT );
    } catch ( err ) {
      const status = ( err as { status?: number } ).status;
      if ( status === 401 ) return { status: "auth_required" };
      return { status: "unreachable", fleet_arbiter: null };
    }
  }

  private emitSizeCapChanged(): void {
    this.bus.emit<StoreFleetSizeCapChangedPayload>( {
      type    : "store_fleet_size_cap_changed",
      payload : { saving: this.savingCap !== null },
      source  : "FleetStatusStore",
      ts      : this.nowFn(),
    } );
  }

  private emitChanged( stampUpdated: boolean ): void {
    this.bus.emit<StoreFleetStatusChangedPayload>( {
      type    : "store_fleet_status_changed",
      payload : { stampUpdated },
      source  : "FleetStatusStore",
      ts      : this.nowFn(),
    } );
  }
}

/**
 * The server's own reason for a refusal, or the status when it gave none.
 *
 * The ApiClient throws ApiError( status, url, <response text> ) with the message
 * `HTTP <status> <url>: <text>`, and the arbiter refuses with a JSON `detail` the
 * operator can act on — a cap above the ceiling, a key defined twice. Legacy shows
 * that detail and falls back to `HTTP <status>` (legacy :9335-9339).
 */
function serverDetail( err: unknown, status: number ): string {
  const message = ( err as { message?: string } ).message ?? "";
  const text    = message.slice( message.indexOf( ": " ) + 2 );
  try {
    const body = JSON.parse( text ) as { detail?: unknown };
    if ( typeof body.detail === "string" ) return body.detail;
  } catch {
    /* a non-JSON error body keeps the status line */
  }
  return `HTTP ${status}`;
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFleetStatusStore( opts: FleetStatusStoreOptions ): FleetStatusStore {
  return new FleetStatusStoreImpl( opts );
}
