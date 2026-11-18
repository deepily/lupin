/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
//
// Page visibility and network events, forwarded onto the event bus (row 9cc37a94 item 40).
//
// The multiplexer page (boot.ts) and the console page (console/consolePage.ts) each carried
// this translation. The queue transport's reconnect logic listens for these events.

import type { EventBus } from "./EventBus";
import type { LifecyclePayload } from "./types";

/** The slice of a window the network events need. */
export interface NetworkEvents {
  addEventListener( type: "online" | "offline", listener: () => void ): void;
}

/** The lifecycle event types the queue transport listens for. */
export type LifecycleEventType = "page_hidden" | "page_visible" | "network_online" | "network_offline";

/**
 * Emit one lifecycle event on the bus, stamped with the current time.
 *
 * Requires:
 *   - source names the caller on the event
 *
 * Ensures:
 *   - the payload holds the time, and `bfcache: true` when the page came back from the back-forward cache
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function emitLifecycleEvent( bus: EventBus, type: LifecycleEventType, source: string, extra?: { bfcache?: true } ): void {
  const ts = Date.now();
  const payload: LifecyclePayload = { ts };
  if ( extra?.bfcache ) payload.bfcache = true;
  bus.emit<LifecyclePayload>( { type, payload, source, ts } );
}

/**
 * Forward visibility, online and offline events to the bus.
 *
 * Requires:
 *   - doc and win are the page's document and window; source names the caller on each event
 *
 * Ensures:
 *   - a visibility change emits page_hidden or page_visible with the current time
 *   - online and offline emit network_online and network_offline with the current time
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function attachLifecycleEvents( bus: EventBus, doc: Document, win: NetworkEvents, source: string ): void {
  const emit = ( type: LifecycleEventType ): void => emitLifecycleEvent( bus, type, source );
  doc.addEventListener( "visibilitychange", () => {
    emit( doc.visibilityState === "hidden" ? "page_hidden" : "page_visible" );
  } );
  win.addEventListener( "online",  () => emit( "network_online" ) );
  win.addEventListener( "offline", () => emit( "network_offline" ) );
}
