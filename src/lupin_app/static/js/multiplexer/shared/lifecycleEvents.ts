/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
//
// Page visibility and network events, forwarded onto the event bus (row 9cc37a94 item 40).
//
// The multiplexer page (boot.ts) and the console page (console/consolePage.ts) each carried
// this translation. The queue transport's reconnect logic listens for these events.

import type { EventBus } from "./EventBus";

/** The slice of a window the network events need. */
export interface NetworkEvents {
  addEventListener( type: "online" | "offline", listener: () => void ): void;
}

/** The lifecycle event types the queue transport listens for. */
export type LifecycleEventType = "page_hidden" | "page_visible" | "network_online" | "network_offline";

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
  const emit = ( type: LifecycleEventType ): void => {
    const ts = Date.now();
    bus.emit( { type, payload : { ts }, source, ts } );
  };
  doc.addEventListener( "visibilitychange", () => {
    emit( doc.visibilityState === "hidden" ? "page_hidden" : "page_visible" );
  } );
  win.addEventListener( "online",  () => emit( "network_online" ) );
  win.addEventListener( "offline", () => emit( "network_offline" ) );
}
