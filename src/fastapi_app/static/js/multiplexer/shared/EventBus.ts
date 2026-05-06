/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 2 — EventBus singleton.
// EventTarget-backed pub/sub with per-listener error isolation.
// All cross-module communication routes through this bus (per Phase 1 ESLint
// no-globals rule + Phase 0 Q2 directory layout).

import type {
  LupinEvent,
  LupinEventType,
  ListenerErrorPayload,
} from "./types";

type AnyListener = (e: LupinEvent<unknown>) => void;

export interface EventBus {
  on<T = unknown>(
    type: LupinEventType,
    listener: (e: LupinEvent<T>) => void,
  ): () => void;
  off(type: LupinEventType, listener: AnyListener): void;
  emit<T>(event: LupinEvent<T>): void;
}

class EventBusImpl implements EventBus {
  private readonly target = new EventTarget();
  // Map every (type, listener) pair to the wrapper actually registered on the
  // EventTarget so off() can remove the right one and so on() can return a
  // matching unsubscribe closure.
  private readonly wrappers = new Map<
    LupinEventType,
    Map<AnyListener, EventListener>
  >();

  on<T = unknown>(
    type: LupinEventType,
    listener: (e: LupinEvent<T>) => void,
  ): () => void {
    const wrapper: EventListener = (evt) => {
      const detail = (evt as CustomEvent<LupinEvent<T>>).detail;
      try {
        listener(detail);
      } catch (err) {
        this.handleListenerError(detail as LupinEvent<unknown>, err);
      }
    };

    let perType = this.wrappers.get(type);
    if (!perType) {
      perType = new Map();
      this.wrappers.set(type, perType);
    }
    perType.set(listener as AnyListener, wrapper);
    this.target.addEventListener(type, wrapper);

    return () => this.off(type, listener as AnyListener);
  }

  off(type: LupinEventType, listener: AnyListener): void {
    const perType = this.wrappers.get(type);
    if (!perType) return;
    const wrapper = perType.get(listener);
    if (!wrapper) return;
    this.target.removeEventListener(type, wrapper);
    perType.delete(listener);
    if (perType.size === 0) this.wrappers.delete(type);
  }

  emit<T>(event: LupinEvent<T>): void {
    this.target.dispatchEvent(
      new CustomEvent<LupinEvent<T>>(event.type, { detail: event }),
    );
  }

  private handleListenerError(
    originalEvent: LupinEvent<unknown>,
    err: unknown,
  ): void {
    // Avoid infinite recursion: a thrown listener on listener_error itself
    // must not re-emit listener_error.
    if (originalEvent && originalEvent.type === "listener_error") return;

    const payload: ListenerErrorPayload = {
      originalEvent,
      error: err instanceof Error ? err.message : String(err),
    };
    this.emit<ListenerErrorPayload>({
      type    : "listener_error",
      payload,
      source  : "EventBus",
      ts      : Date.now(),
    });
  }
}

// Singleton instance — every module imports from here. ESLint no-globals rule
// (Phase 1) prevents creating ad-hoc EventTargets elsewhere.
export const eventBus: EventBus = new EventBusImpl();

// Test-only factory. Production code MUST use the singleton above. Exposed so
// unit tests can build isolated buses without singleton state leaking between
// test cases.
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createEventBusForTesting(): EventBus {
  return new EventBusImpl();
}
