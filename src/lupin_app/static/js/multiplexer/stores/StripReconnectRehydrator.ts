/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer v0.1.9 — StripReconnectRehydrator (focus-bar eager re-hydrate).
//
// Option (2) of the focus-bar repopulation design
// (src/rnd/v0.1.9/2026.07.07-focus-bar-repopulation-ux-design.md; Mr. Radio
// gate-word 2026-07-07 DM bad8be07). After a long silent window the host-side
// prune reaps genuinely-stale sessions, so SessionStripStore drops their icons
// (its reducer removes on `session_reaped`); post-resume the strip only re-adds
// an icon on a NEW `voice_persona_assigned`, so the fleet lazily refills over
// ~15-20 min. This unit closes that gap: on the queue socket's genuine reconnect
// edge it re-runs the SAME idempotent senders-visible hydrate the boot path
// already calls (boot.ts:483-486), refilling the strip immediately.
//
// Design constraints honored (gate conditions):
//   (b) MUX-ONLY — no legacy notifications.js twin; the live surface is the
//       Chrome-only multiplexer.
//   (c) Debounced once-per-reconnect-edge (`reconnecting` -> `connected` on the
//       QueueTransport ONLY), reuses the idempotent `hydrate()`, and performs NO
//       store/renderer surgery — this is a self-contained boot-level subscriber.
//
// Pattern precedent: ActionRequiredStore.onConnectionState
// (ActionRequiredStore.ts:410-417) already subscribes to the same
// `connection_state_change` event and branches on `state` — this is a
// carbon-copy of that reconnect-reactive wiring (re-hydrate instead of thaw).

import type { EventBus } from "../shared/EventBus";
import type { ConnectionStateChangePayload, LupinEvent } from "../shared/types";
import type { ServerSenderHydrationRecord } from "./SessionStripStore";

// The transport whose reconnect drives the focus-bar re-hydrate. The queue
// socket carries the notification / persona domain the strip is sourced from;
// the audio socket (AudioTransport) is irrelevant here, so its reconnects are
// ignored — this is what keeps the re-hydrate once-per-reconnect-edge when both
// sockets bounce together.
export const STRIP_REHYDRATE_TRANSPORT = "QueueTransport";

// Minimal API surface — GET returning the senders-visible snapshot (the SAME
// endpoint + record shape boot.ts hydrates the strip from). Narrowed idiom
// (Pass 2 F4): the production ApiClient.get satisfies this.
export interface StripRehydrateApiClient {
  get<T>( path: string ): Promise<T>;
}

// The two stores boot fans the senders-visible snapshot out to (boot.ts:485-486),
// narrowed to just `hydrate()` — no store surgery (gate condition c). Both
// hydrate methods are already idempotent upsert-merges.
export interface StripRehydrateStores {
  sessionStrip : { hydrate( records: ReadonlyArray<ServerSenderHydrationRecord> ): void };
  senders      : { hydrate( records: ReadonlyArray<ServerSenderHydrationRecord> ): void };
}

export interface StripReconnectRehydratorOptions {
  bus      : EventBus;
  api      : StripRehydrateApiClient;
  stores   : StripRehydrateStores;
  // Resolves the current user email at FIRE time (late-bound — auth may resolve
  // after this unit is wired). Null / empty → skip, mirroring boot's guard.
  getEmail : () => string | null;
}

export interface StripReconnectRehydrator {
  /** Test/cleanup helper: detach the EventBus listener. */
  disposeForTesting(): void;
}

class StripReconnectRehydratorImpl implements StripReconnectRehydrator {
  private readonly bus      : EventBus;
  private readonly api      : StripRehydrateApiClient;
  private readonly stores   : StripRehydrateStores;
  private readonly getEmail : () => string | null;

  // Debounce guard — a queue+audio double-bounce or a rapid flap must not fire
  // overlapping fetches; a second edge while a fetch is in flight is dropped.
  private inFlight = false;

  private readonly unsubscribers: Array<() => void> = [];

  constructor( opts: StripReconnectRehydratorOptions ) {
    this.bus      = opts.bus;
    this.api      = opts.api;
    this.stores   = opts.stores;
    this.getEmail = opts.getEmail;
    this.unsubscribers.push(
      this.bus.on<ConnectionStateChangePayload>( "connection_state_change", ( e ) => this.onConnectionState( e ) ),
    );
  }

  disposeForTesting(): void {
    for ( const off of this.unsubscribers ) off();
  }

  // -------------------------------------------------------------------------
  // Reconnect-edge detection
  // -------------------------------------------------------------------------

  private onConnectionState( e: LupinEvent<ConnectionStateChangePayload> ): void {
    const p = e.payload;
    // Queue socket only — the audio transport's reconnects don't touch the strip.
    if ( p.transport !== STRIP_REHYDRATE_TRANSPORT ) return;
    // Fire ONLY on a genuine reconnect edge: `reconnecting` -> `connected`. The
    // initial connect is `connecting` -> `connected` (boot already hydrated), and
    // every other transition is a no-op here.
    if ( p.state !== "connected" || p.prev !== "reconnecting" ) return;
    void this.rehydrate();
  }

  private async rehydrate(): Promise<void> {
    if ( this.inFlight ) return;                       // debounce overlapping edges
    const email = this.getEmail();
    if ( email === null || email === "" ) return;      // no user resolved yet — skip
    this.inFlight = true;
    try {
      const path    = `/api/notifications/senders-visible/${ encodeURIComponent( email ) }`;
      const records = await this.api.get<ServerSenderHydrationRecord[]>( path );
      // SAME fan-out as boot.ts:485-486 — idempotent merge with any live events
      // that arrived first.
      this.stores.sessionStrip.hydrate( records );
      this.stores.senders.hydrate( records );
    } catch {
      // Best-effort re-hydrate (mirrors boot's `.catch`): a failed reconnect
      // fetch must never throw — live events still populate the strip.
    } finally {
      this.inFlight = false;
    }
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createStripReconnectRehydrator( opts: StripReconnectRehydratorOptions ): StripReconnectRehydrator {
  return new StripReconnectRehydratorImpl( opts );
}
