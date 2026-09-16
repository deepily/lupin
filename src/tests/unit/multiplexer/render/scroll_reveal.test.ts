// Parity A-0 (row 52daee86, 2026-09-16, John 🏄🏽) — the shared scroll-reveal
// helper, ported from legacy `scrollIntoViewIfNeeded` (notifications.js:25386-25408).
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before, mock } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  scrollRevealElement,
  SCROLL_REVEAL_SETTLE_MS,
} from "../../../../lupin_app/static/js/multiplexer/render/scrollReveal";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

// happy-dom does no layout, so every rect is zeros. Each test pins the rect the
// helper reads and records the scrollIntoView calls it makes.
interface Probe {
  el    : HTMLElement;
  calls : Array<ScrollIntoViewOptions | boolean | undefined>;
}
function makeProbe( top: number, bottom: number ): Probe {
  const el    = document.createElement( "section" );
  const calls : Probe["calls"] = [];
  el.getBoundingClientRect = () => ( { top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top, toJSON: () => ( {} ) } ) as DOMRect;
  el.scrollIntoView        = ( arg?: ScrollIntoViewOptions | boolean ) => { calls.push( arg ); };
  document.body.appendChild( el );
  return { el, calls };
}

// Resolve-state probe: true once the promise has settled.
function track( p: Promise<void> ): { done: () => boolean } {
  let settled = false;
  void p.then( () => { settled = true; } );
  return { done: () => settled };
}
async function flush(): Promise<void> { await Promise.resolve(); await Promise.resolve(); }

test( "the settle delay is legacy's 300 ms", () => {
  assert.equal( SCROLL_REVEAL_SETTLE_MS, 300 );
} );

test( "an element already fully in view is NOT scrolled and resolves immediately", async () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const { el, calls } = makeProbe( 0, window.innerHeight );   // both edges exactly on the viewport bounds
    const t = track( scrollRevealElement( el ) );
    await flush();
    assert.equal( t.done(), true, "an in-view element must resolve without waiting on the timer" );
    assert.equal( calls.length, 0 );
  } finally {
    mock.timers.reset();
  }
} );

test( "an element above the viewport scrolls smooth/start and resolves only after 300 ms", async () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const { el, calls } = makeProbe( -10, 50 );
    const t = track( scrollRevealElement( el ) );
    assert.deepEqual( calls, [ { behavior: "smooth", block: "start" } ] );
    await flush();
    assert.equal( t.done(), false, "resolved before the scroll could settle — callers cannot sequence after it" );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS - 1 );
    await flush();
    assert.equal( t.done(), false );
    mock.timers.tick( 1 );
    await flush();
    assert.equal( t.done(), true );
  } finally {
    mock.timers.reset();
  }
} );

test( "an element running past the bottom of the viewport is scrolled", async () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const { el, calls } = makeProbe( 10, window.innerHeight + 1 );
    const p = scrollRevealElement( el );
    assert.equal( calls.length, 1 );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    await p;
  } finally {
    mock.timers.reset();
  }
} );

test( "a null element resolves without throwing (legacy's guard)", async () => {
  await scrollRevealElement( null );
} );
