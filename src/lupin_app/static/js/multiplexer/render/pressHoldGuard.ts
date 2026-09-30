/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Press-hold repaint guard — parity row A-1b (operator-state spec §7 surface 8).
//
// Ported from legacy `_wireTaskListAccordion` (notifications.js, the `mousedown` /
// `_releaseTaskListPress` pair) and WIDENED to the Task List, Holding Area and Epic
// Board by Mr. Radio 🦉's spec ruling 4: all three paint the same shared row and all
// three repaint with `replaceChildren`.
//
// 🔴 CAPTURE CANNOT FIX THIS, WHICH IS WHY IT IS ITS OWN MECHANISM. A repaint landing
// BETWEEN a press and its release replaces the pressed node, and the click then
// reaches no handler at all — no request, no refusal, nothing. Preserving state
// cannot help: the node itself is gone. So the paint is HELD for the length of the
// press and taken the moment it ends. Do not fold this into operator-state capture.
//
// ⚠️ TWO DIVERGENCES FROM LEGACY, BOTH DELIBERATE:
//   1. The `mouseup` release is DEFERRED by one macrotask. `click` is dispatched
//      AFTER `mouseup`, so a synchronous replay inside the `mouseup` listener
//      replaces the pressed node before the click can reach it — the very window
//      the guard exists to close. `mouseleave` and a window `blur` release at once,
//      because no click on this pane follows either.
//   2. `blur` is listened for on the WINDOW, not the container. `blur` does not
//      bubble, so legacy's container listener only fires if the container div itself
//      loses focus, which it never holds. And `focusout` would be wrong the other
//      way: pressing Submit while typing in the reason box moves focus off the box
//      DURING the press, releasing the guard in exactly the case it is for. A window
//      blur is the real lost-mouseup case — the operator switched away mid-press.
//
// ⚠️ A SECOND PRESS BEFORE THE DEFERRED RELEASE RUNS (a double-click) must not be
// released by the first press's timer; a generation count makes a stale timer a no-op.

export interface PressHoldGuard {
  /**
   * Hold `paint` if a press is in flight.
   *
   * Requires:
   *   - `paint` repaints from CURRENT state when called (it is replayed later)
   *
   * Ensures:
   *   - returns true and remembers `paint` (replacing any earlier held paint, so
   *     only the LATEST is ever replayed) while a press is in flight
   *   - returns false and remembers nothing when no press is in flight; the caller
   *     paints now
   */
  hold( paint: () => void ): boolean;
  /** Detach every listener and forget any held paint. Idempotent. */
  dispose(): void;
}

export interface PressHoldGuardOptions {
  /** Schedules the deferred `mouseup` release. Defaults to `setTimeout`. */
  setTimeoutFn? : ( cb: () => void, ms: number ) => unknown;
}

/**
 * Install the press-hold guard on a pane's persistent container.
 *
 * Requires:
 *   - `container` outlives every repaint (its CHILDREN are replaced, not it)
 *
 * Ensures:
 *   - `mousedown` inside the container starts a press
 *   - `mouseup` ends it one macrotask later; `mouseleave` and a window `blur` end it now
 *   - ending a press replays the held paint exactly once, then forgets it; ending a
 *     press with nothing held is a no-op
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function wirePressHoldGuard( container: HTMLElement, opts: PressHoldGuardOptions ): PressHoldGuard {
  /* c8 ignore next */ // production-default fallback: the runtime scheduler; tests inject a fake.
  const setTimeoutFn = opts.setTimeoutFn ?? ( ( cb: () => void, ms: number ) => globalThis.setTimeout( cb, ms ) );

  let pressed    = false;
  let generation = 0;
  let held : ( () => void ) | null = null;

  const release = (): void => {
    pressed = false;
    const paint = held;
    if ( paint === null ) return;
    held = null;
    paint();
  };

  const onDown = (): void => {
    pressed = true;
    generation += 1;
  };
  const onUp = (): void => {
    const mine = generation;
    setTimeoutFn( () => { if ( mine === generation ) release(); }, 0 );
  };

  container.addEventListener( "mousedown", onDown );
  container.addEventListener( "mouseup", onUp );
  container.addEventListener( "mouseleave", release );
  window.addEventListener( "blur", release );

  return {
    hold( paint ) {
      if ( !pressed ) return false;
      held = paint;
      return true;
    },
    dispose() {
      container.removeEventListener( "mousedown", onDown );
      container.removeEventListener( "mouseup", onUp );
      container.removeEventListener( "mouseleave", release );
      window.removeEventListener( "blur", release );
      pressed = false;
      held    = null;
      generation += 1;   // a deferred release already scheduled becomes a no-op
    },
  };
}
