/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
//
// polling: the timer and push plumbing the multiplexer stores share.
//
// resolveRuntimeDefaults names the production clock and timers once.
// createPushPoller is the poll-plus-push loop that three stores each carried a copy of.

import type { EventBus } from "../shared/EventBus";

/** The clock and timer hooks a store accepts so a test can inject fakes. */
export interface RuntimeDefaultsOptions {
  nowFn?          : () => number;
  setIntervalFn?  : ( cb: () => void, ms: number ) => number;
  clearIntervalFn?: ( handle: number ) => void;
}

/** The clock and timer hooks after the production fallbacks are filled in. */
export interface RuntimeDefaults {
  nowFn          : () => number;
  setIntervalFn  : ( cb: () => void, ms: number ) => number;
  clearIntervalFn: ( handle: number ) => void;
}

/**
 * Fills in the production clock and timers for any hook the caller left out.
 *
 * Each fallback is the runtime clock or scheduler; tests inject a deterministic one instead.
 */
export function resolveRuntimeDefaults( opts: RuntimeDefaultsOptions ): RuntimeDefaults {
  /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
  const nowFn = opts.nowFn ?? ( () => Date.now() );
  /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime scheduler; tests inject a fake.
  const setIntervalFn = opts.setIntervalFn ?? ( ( cb: () => void, ms: number ) => globalThis.setInterval( cb, ms ) as unknown as number );
  /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the default above.
  const clearIntervalFn = opts.clearIntervalFn ?? ( ( h: number ) => globalThis.clearInterval( h ) );
  return { nowFn, setIntervalFn, clearIntervalFn };
}

/** The options `createPushPoller` takes. */
export interface PushPollerOptions {
  bus             : EventBus;
  setIntervalFn   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn : ( handle: number ) => void;
  intervalMs      : number;
  refresh         : () => Promise<void>;
  refreshAfterWrite: () => Promise<void>;
}

/** A started-or-stopped poll loop. */
export interface PushPoller {
  /** Refreshes now, then on the interval and on each push. Restarts cleanly if already running. */
  start(): void;
  /** Cancels the interval and the push subscription. Idempotent. */
  stop(): void;
}

/**
 * Builds the poll-plus-push loop a store runs.
 *
 * The timer calls `refresh`. The server push, `task_store_changed`, calls `refreshAfterWrite`.
 * The push never calls `refresh`, because that call has an in-flight guard.
 * The guard skips a call that lands during a read, and that read may predate the commit the push announces.
 * `refreshAfterWrite` waits the read out and starts one that began after the push.
 * A burst of pushes joins that one read, so it costs at most two fetches.
 * The poll stays as the safety net.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function createPushPoller( opts: PushPollerOptions ): PushPoller {
  let pollHandle     : number | null = null;
  let unsubscribePush: ( () => void ) | null = null;

  const stop = (): void => {
    if ( pollHandle !== null ) {
      opts.clearIntervalFn( pollHandle );
      pollHandle = null;
    }
    if ( unsubscribePush !== null ) {
      unsubscribePush();
      unsubscribePush = null;
    }
  };

  const start = (): void => {
    stop();
    void opts.refresh();
    pollHandle      = opts.setIntervalFn( () => void opts.refresh(), opts.intervalMs );
    unsubscribePush = opts.bus.on( "task_store_changed", () => void opts.refreshAfterWrite() );
  };

  return { start, stop };
}
