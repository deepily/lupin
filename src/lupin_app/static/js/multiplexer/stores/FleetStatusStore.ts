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

import type { EventBus } from "../shared/EventBus";
import type { StoreFleetStatusChangedPayload } from "../shared/types";
import type { FleetComposite } from "../render/fleetModel";

// Narrowed ApiClient surface (Pass 2 F4 idiom). The production ApiClient.get
// throws ApiError (carrying `.status`) on non-2xx; we map that to the legacy
// display-only sentinels rather than letting it propagate.
export interface FleetApiClient {
  get<T>( path: string ): Promise<T>;
}

export const FLEET_STATE_ENDPOINT          = "/api/arbiter/fleet-state";
export const FLEET_STATUS_POLL_INTERVAL_MS = 60000;   // 60s auto-poll (D4)

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
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface FleetStatusStoreOptions {
  bus             : EventBus;
  api             : FleetApiClient;
  nowFn?          : () => number;
  setIntervalFn?  : ( cb: () => void, ms: number ) => number;
  clearIntervalFn?: ( handle: number ) => void;
}

class FleetStatusStoreImpl implements FleetStatusStore {
  private readonly bus   : EventBus;
  private readonly api   : FleetApiClient;
  private readonly nowFn : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;

  private lastComposite : FleetComposite | null = null;
  private showOffline   = false;
  private inFlight       = false;
  private pollHandle    : number | null = null;

  constructor( opts: FleetStatusStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the default above.
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
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

  private emitChanged( stampUpdated: boolean ): void {
    this.bus.emit<StoreFleetStatusChangedPayload>( {
      type    : "store_fleet_status_changed",
      payload : { stampUpdated },
      source  : "FleetStatusStore",
      ts      : this.nowFn(),
    } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFleetStatusStore( opts: FleetStatusStoreOptions ): FleetStatusStore {
  return new FleetStatusStoreImpl( opts );
}
