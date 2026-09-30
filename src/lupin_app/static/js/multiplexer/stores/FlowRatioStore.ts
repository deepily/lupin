/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-2 #8 (row c1bb2be7) — FlowRatioStore: the Holding Area's flow-ratio gate.
//
// Ports legacy notifications.js fetchFlowRatio, fetchFlowRatioSettings,
// saveFlowRatioSettings, fetchManagerPullDisabled, saveManagerPullDisabled,
// resetFlowRatioSettings and initFlowRatioControls. Three endpoints: the ratio, its
// settings, and the manager-pull toggle. It emits `store_flow_ratio_changed`; the
// Holding Area renderer paints the header readout and the operator cluster from it.
//
// FIXED FROM LEGACY, and each one is filed in bug-fix-queue.md against legacy:
//   1. A refusal was overwritten at once by the repaint's source line. Here the
//      action's message stands until the next write.
//   2. A save that failed on the network repainted nothing, leaving the slider at a
//      value that was never saved. Here every failed write re-reads the settings.
//   3. A refused save never re-read the ratio, so a refused window drag kept showing
//      "recounting…". Here the ratio is re-read after every write, whatever its outcome.
//   4. A failed re-read hid the cluster for the life of the page, because the tick
//      only retried until the first successful paint. Here the tick retries whenever
//      the settings it holds are unusable.
//   6. The manager-pull state was read once, at bind time, with no retry. Here the
//      tick retries it until a read succeeds.
// (Defect 5, the colour's threshold, is fixed in render/flowRatioModel.ts.)

import type { EventBus } from "../shared/EventBus";
import type { StoreFlowRatioChangedPayload } from "../shared/types";
import {
  flowRatioSettingsUsable,
  type FlowRatioPayload,
  type FlowRatioSettings,
  type ManagerPullState,
} from "../render/flowRatioModel";

export interface FlowRatioApiClient {
  get<T>( path: string ): Promise<T>;
  patch<T>( path: string, body: unknown ): Promise<T>;
  delete<T>( path: string ): Promise<T>;
}

export const FLOW_RATIO_ENDPOINT          = "/api/tasks/flow-ratio";
export const FLOW_RATIO_SETTINGS_ENDPOINT = "/api/tasks/flow-ratio/settings";
export const MANAGER_PULL_ENDPOINT        = "/api/tasks/manager-pull";
export const FLOW_RATIO_POLL_INTERVAL_MS  = 60000;   // legacy's shared 60 s task-list tick

/** A settings write: the threshold as a fraction, the window in hours, or both. */
export interface FlowRatioSettingsPatch {
  allow_below?  : number;
  window_hours? : number;
}

export interface FlowRatioStore {
  /** The last ratio payload, or null before a read / after a failed one. */
  ratio(): FlowRatioPayload | null;
  /** The last settings body, or null before a read / after a failed one. */
  settings(): FlowRatioSettings | null;
  /** The last manager-pull state, or null until a read succeeds. */
  managerPull(): ManagerPullState | null;
  /** What the last write said, standing until the next write; null when none has spoken. */
  controlsMessage(): string | null;
  /** One tick: the ratio, then the settings and manager-pull state if still unread. Never throws. */
  refresh(): Promise<void>;
  saveSettings( patch: FlowRatioSettingsPatch ): Promise<void>;
  saveManagerPull( disabled: boolean ): Promise<void>;
  resetSettings(): Promise<void>;
  startPolling(): void;
  stopPolling(): void;
  disposeForTesting(): void;
}

export interface FlowRatioStoreOptions {
  bus              : EventBus;
  api              : FlowRatioApiClient;
  nowFn?           : () => number;
  setIntervalFn?   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn? : ( handle: number ) => void;
  /** Where a failed read is reported. Defaults to console.error. */
  errorFn?         : ( message: string ) => void;
}

/** The HTTP status of a rejection, or null for one that never reached the server. */
function statusOf( err: unknown ): number | null {
  const status = ( err as { status?: unknown } ).status;
  return typeof status === "number" ? status : null;
}

/** "<verb> — admin only", "<verb> (HTTP n)", or "<verb> (network)" (legacy strings). */
function refusalText( verb: string, err: unknown ): string {
  const status = statusOf( err );
  if ( status === 403 ) return `${verb} — admin only`;
  if ( status !== null ) return `${verb} (HTTP ${status})`;
  return `${verb} (network)`;
}

class FlowRatioStoreImpl implements FlowRatioStore {
  private readonly bus             : EventBus;
  private readonly api             : FlowRatioApiClient;
  private readonly nowFn           : () => number;
  private readonly setIntervalFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn : ( handle: number ) => void;
  private readonly errorFn         : ( message: string ) => void;

  private lastRatio    : FlowRatioPayload | null  = null;
  private lastSettings : FlowRatioSettings | null = null;
  private lastPull     : ManagerPullState | null  = null;
  private message      : string | null            = null;
  private inFlight     = false;
  private pollHandle   : number | null = null;

  constructor( opts: FlowRatioStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the default above.
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
    /* c8 ignore next */ // production-default fallback: console.error is the runtime sink; tests inject a collector.
    this.errorFn         = opts.errorFn ?? ( ( m ) => console.error( `[FlowRatioStore] ${m}` ) );
  }

  ratio(): FlowRatioPayload | null { return this.lastRatio; }
  settings(): FlowRatioSettings | null { return this.lastSettings; }
  managerPull(): ManagerPullState | null { return this.lastPull; }
  controlsMessage(): string | null { return this.message; }

  async refresh(): Promise<void> {
    if ( this.inFlight ) return;   // a manual refresh landing on a tick cannot double-fetch
    this.inFlight = true;
    try {
      await this.readRatio();
      // The settings are re-read only until they are usable: once painted, a tick must
      // not move a slider out from under the operator's finger. Unusable — never read,
      // or a failed re-read — is retried on every tick (defect 4).
      if ( !flowRatioSettingsUsable( this.lastSettings ) ) await this.readSettings();
      if ( this.lastPull === null ) await this.readManagerPull();   // retried until read (defect 6)
      this.emit();
    } finally {
      this.inFlight = false;
    }
  }

  async saveSettings( patch: FlowRatioSettingsPatch ): Promise<void> {
    this.message = null;
    try {
      this.lastSettings = await this.api.patch<FlowRatioSettings>( FLOW_RATIO_SETTINGS_ENDPOINT, patch );
    } catch ( err ) {
      this.message = refusalText( "not saved", err );
      await this.readSettings();   // re-read on EVERY failure, the network one included (defect 2)
    }
    await this.readRatio();        // after every outcome, so no drag preview outlives it (defect 3)
    this.emit();
  }

  async saveManagerPull( disabled: boolean ): Promise<void> {
    this.message = null;
    try {
      this.lastPull = await this.api.patch<ManagerPullState>( MANAGER_PULL_ENDPOINT, { disabled } );
      this.message  = this.lastPull.disabled ? "manager pull FROZEN" : "manager pull allowed";
    } catch ( err ) {
      this.message = refusalText( "not saved", err );
      await this.readManagerPull();
    }
    this.emit();
  }

  async resetSettings(): Promise<void> {
    this.message = null;
    try {
      this.lastSettings = await this.api.delete<FlowRatioSettings>( FLOW_RATIO_SETTINGS_ENDPOINT );
      await this.readRatio();
    } catch ( err ) {
      // Legacy's reset reports a server refusal and only logs a network failure.
      if ( statusOf( err ) === null ) this.errorFn( `Flow ratio settings reset failed: ${err}` );
      else this.message = refusalText( "not reset", err );
    }
    this.emit();
  }

  startPolling(): void {
    this.stopPolling();
    void this.refresh();
    this.pollHandle = this.setIntervalFn( () => void this.refresh(), FLOW_RATIO_POLL_INTERVAL_MS );
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
  // Reads — each one fail-soft: a failure leaves null and says why
  // -------------------------------------------------------------------------

  private async readRatio(): Promise<void> {
    try {
      this.lastRatio = await this.api.get<FlowRatioPayload>( FLOW_RATIO_ENDPOINT );
    } catch ( err ) {
      this.errorFn( `Flow ratio unavailable: ${err}` );
      this.lastRatio = null;
    }
  }

  private async readSettings(): Promise<void> {
    try {
      this.lastSettings = await this.api.get<FlowRatioSettings>( FLOW_RATIO_SETTINGS_ENDPOINT );
    } catch ( err ) {
      this.errorFn( `Flow ratio settings unavailable: ${err}` );
      this.lastSettings = null;
    }
  }

  private async readManagerPull(): Promise<void> {
    try {
      this.lastPull = await this.api.get<ManagerPullState>( MANAGER_PULL_ENDPOINT );
    } catch ( err ) {
      this.errorFn( `Manager-pull read failed: ${err}` );
      this.lastPull = null;
    }
  }

  private emit(): void {
    this.bus.emit<StoreFlowRatioChangedPayload>( {
      type    : "store_flow_ratio_changed",
      payload : {},
      source  : "FlowRatioStore",
      ts      : this.nowFn(),
    } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFlowRatioStore( opts: FlowRatioStoreOptions ): FlowRatioStore {
  return new FlowRatioStoreImpl( opts );
}
