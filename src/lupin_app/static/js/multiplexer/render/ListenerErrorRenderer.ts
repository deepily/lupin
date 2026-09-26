/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Row 8033756c — the default `listener_error` subscriber.
//
// WHAT WAS WRONG. The bus does NOT swallow listener throws: EventBus's wrapper
// catches one and `handleListenerError` re-emits it as a `listener_error` event.
// The defect is that NOBODY SUBSCRIBED. Measured at 064308fee, 2026-09-26:
// 2 catch sites, 0 that discard, 2 that re-emit, and `listener_error` was the
// only emitted event in the client with ZERO production subscribers (52 events
// have one). The error was raised correctly every time and arrived nowhere.
//
// WHAT THAT COST. Row 275e5c57: an Action Required card threw on a null persona,
// rendered nothing, and the header still counted it — an empty panel under
// "Action Required 1", with no console line anywhere. Three e2e tests went red
// at the venue and green locally, and with nothing to read the reds looked like
// flake; a `_quiet_tts` workaround bought a green over a live bug. The missing
// diagnostic is what made that outcome available.
//
// 🔴 THIS LIVES AT BOOT, NOT IN THE BUS, AND THAT IS THE WHOLE POINT.
// A `console.error` added inside `handleListenerError` would cover EventBus's
// own catch and MISS `NotificationsListRenderer`'s microtask catch, which emits
// the same `listener_error` from OUTSIDE the bus precisely because a microtask
// has no wrapper. One subscriber covers both producers, and every future one,
// for free. (Rachel 🕊️'s finding; she said she would refuse the in-bus shape and
// she is right.)
//
// POLICY: LOG AND KEEP GOING — Rick's ruling, 2026-09-26, answered not defaulted:
// "Log it and keep going but do make sure that the user is apprised of the error
// in some place on the UI that there was an error. Otherwise they might not know
// to report it." No re-throw: this bus fans one event out to as many as four
// renderers, and killing the siblings behind a bad listener is a second failure
// mode, not a fix for the first.
//
// 🔴 AND THIS SUBSCRIBER MUST NEVER THROW, FOR A REASON THAT IS EASY TO MISS.
// EventBus's recursion guard returns early when the original event is itself a
// `listener_error` — so a `listener_error` subscriber that throws vanishes with
// NO trace at all. This subscriber IS such a listener, and it touches the DOM,
// which is the most throw-prone thing it could do. Every path is therefore
// wrapped, with a last-resort write that cannot itself depend on the DOM. If
// that guarantee ever breaks, the control disappears and the suite stays green
// — which is why `the subscriber survives a DOM that throws` is asserted rather
// than reasoned about.

import type { EventBus } from "../shared/EventBus";
import type { LupinEvent, ListenerErrorPayload } from "../shared/types";
import { error as debugError } from "../shared/debugSink";
import { renderListenerErrorBadge } from "./templates/listenerErrorBadge";

/** The diagnostic sink. Injectable so a test can spy it directly rather than
 *  monkey-patching the global console. Defaults to the house writer, which
 *  tees to `console.error` AND the debug panel. */
export type ListenerErrorSink = ( message: string, ...args: unknown[] ) => void;

export interface ListenerErrorRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + clear children + reset the count. Idempotent. */
  unmount(): void;
  /** Test helper — the number of errors since the last dismiss. */
  countForTesting(): number;
}

export interface ListenerErrorRendererOptions {
  eventBus : EventBus;
  /** Defaults to debugSink.error. */
  sink?    : ListenerErrorSink;
}

class ListenerErrorRendererImpl implements ListenerErrorRenderer {
  private readonly bus  : EventBus;
  private readonly sink : ListenerErrorSink;
  private readonly unsubscribers: Array<() => void> = [];

  private root    : HTMLElement | null = null;
  private mounted = false;
  private count   = 0;

  constructor( opts: ListenerErrorRendererOptions ) {
    this.bus  = opts.eventBus;
    this.sink = opts.sink ?? debugError;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "ListenerErrorRenderer already mounted" );
    }
    this.mounted = true;
    this.root    = root;

    this.unsubscribers.push(
      this.bus.on<ListenerErrorPayload>(
        "listener_error",
        ( e ) => this.onListenerError( e ),
      ),
    );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.count   = 0;
    this.mounted = false;
  }

  countForTesting(): number {
    return this.count;
  }

  // ---------------------------------------------------------------------------
  // The handler. EVERY path inside is guarded — see the header: a throw from
  // here is erased by the bus's recursion guard, taking the control with it.
  // ---------------------------------------------------------------------------

  private onListenerError( e: LupinEvent<ListenerErrorPayload> ): void {
    try {
      const payload   = e.payload;
      const eventType = payload.originalEvent ? payload.originalEvent.type : "unknown";
      const message   = payload.error;

      // 1. THE DIAGNOSTIC. The originating event type is part of the line, not
      //    just the message: "Cannot read properties of null" is unactionable on
      //    its own, and which event carried it is the first thing a reader needs.
      this.sink( `listener threw while handling "${ eventType }": ${ message }`, payload.originalEvent );

      // 2. THE INDICATOR. One element, a count, dismissable.
      this.count += 1;
      this.paint( message, eventType );
    } catch ( err ) {
      // LAST RESORT. Reached only if the sink or the DOM write threw. It must
      // not touch either of those again, so it goes straight to console.error —
      // the one writer with no dependency of its own. Returning normally is the
      // point: a throw escaping here is invisible (EventBus recursion guard).
      /* c8 ignore next */ // the `instanceof` false arm needs a non-Error throw from the DOM, which happy-dom cannot produce; the guarded path itself IS asserted.
      const detail = err instanceof Error ? err.message : String( err );
      console.error( `[Notifications ERROR] the listener-error reporter itself failed: ${ detail }` );
    }
  }

  private paint( lastError: string, lastEventType: string ): void {
    /* c8 ignore next */ // defensive: the subscription is detached in unmount() BEFORE root is nulled.
    if ( this.root === null ) return;
    const badge = renderListenerErrorBadge(
      { count: this.count, lastError, lastEventType },
      { onDismiss: (): void => this.onDismiss() },
    );
    // replaceChildren, so repeated errors UPDATE one indicator rather than
    // stacking — the ruling's "must not stack or flap".
    this.root.replaceChildren( badge );
  }

  private onDismiss(): void {
    this.count = 0;
    /* c8 ignore next */ // defensive: the button only exists while root is set.
    if ( this.root === null ) return;
    this.root.replaceChildren();
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createListenerErrorRenderer(
  opts: ListenerErrorRendererOptions,
): ListenerErrorRenderer {
  return new ListenerErrorRendererImpl( opts );
}
