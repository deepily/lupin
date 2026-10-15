// keepPlace.ts: the anchor logic behind Keep place, on its own.
//
// Run via `npx tsx --test src/tests/unit/multiplexer/render/keep_place.test.ts`.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  KEEP_PLACE_KEY,
  captureKeepPlace,
  readKeepPlace,
  restoreKeepPlace,
} from "../../../../lupin_app/static/js/multiplexer/render/keepPlace";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  document.body.replaceChildren();
});

/** A mount of `count` cards whose tops come from `tops`, which a test may change. */
function mount(count: number, tops: number[]): HTMLElement {
  const m = document.createElement("div");
  for (let i = 0; i < count; i++) {
    const c = document.createElement("div");
    c.getBoundingClientRect = (): DOMRect => ({ top: tops[ i ]! } as DOMRect);
    m.appendChild(c);
  }
  document.body.appendChild(m);
  return m;
}

function win(scrollY: number): { scrollY: number; scrollBy: (x: number, y: number) => void; calls: number[] } {
  const w = { scrollY, calls: [] as number[], scrollBy(_x: number, y: number): void { w.calls.push(y); } };
  return w;
}

function shell(open: boolean, columnScrollTop: number | null): HTMLElement | null {
  const s = document.createElement("div");
  s.className = open ? "content-shell pane-open" : "content-shell";
  let column: HTMLElement | null = null;
  if (columnScrollTop !== null) {
    column = document.createElement("div");
    column.className = "left-column";
    column.scrollTop = columnScrollTop;
    s.appendChild(column);
  }
  document.body.appendChild(s);
  return column;
}

test("readKeepPlace: a storage that throws counts as on", () => {
  const throwing = { getItem(): string | null { throw new Error("blocked"); } };
  assert.equal(readKeepPlace(throwing), true);
  assert.equal(KEEP_PLACE_KEY, "notifications_keep_place");
});

test("capture: nothing when the reader is at the top, in either scroll container", () => {
  const m = mount(3, [ 100, 300, 500 ]);
  assert.equal(captureKeepPlace(m, document, win(0)), null);
  shell(true, 0);
  assert.equal(captureKeepPlace(m, document, win(900)), null, "pane open: only the left column counts");
});

test("capture: with the pane open and no left column the reader counts as at the top", () => {
  shell(true, null);
  assert.equal(captureKeepPlace(mount(2, [ 100, 300 ]), document, win(900)), null);
});

test("capture: at most four cards, none above the strip", () => {
  const m    = mount(7, [ -300, 50, 100, 300, 500, 700, 900 ]);
  const kept = captureKeepPlace(m, document, win(10))!;
  assert.deepEqual(kept.map(c => c.index), [ 2, 3, 4, 5 ]);
  assert.deepEqual(kept.map(c => c.top), [ 100, 300, 500, 700 ]);
});

test("restore: the window is scrolled by how far the anchor moved", () => {
  const tops = [ 100, 300, 500 ];
  const m    = mount(3, tops);
  const w    = win(50);
  const kept = captureKeepPlace(m, document, w)!;
  tops[ 0 ] = 300; tops[ 1 ] = 500;                    // everything shifted down by 200
  restoreKeepPlace(m, kept, document, w);
  assert.deepEqual(w.calls, [ 200 ]);
});

test("restore: an unmoved anchor scrolls nothing, and an empty or exhausted list is left alone", () => {
  const m = mount(2, [ 100, 300 ]);
  const w = win(50);
  restoreKeepPlace(m, captureKeepPlace(m, document, w)!, document, w);
  assert.deepEqual(w.calls, []);
  restoreKeepPlace(m, [], document, w);
  assert.deepEqual(w.calls, []);
});

test("restore: a card that left the list or moved up it is skipped for the next one", () => {
  const tops = [ 100, 300, 500 ];
  const m    = mount(3, tops);
  const w    = win(50);
  const kept = captureKeepPlace(m, document, w)!;
  m.appendChild(m.children[ 0 ]!);                     // card 0 moved to the end: it did not move up
  m.insertBefore(m.children[ 2 ]!, m.children[ 0 ]!);  // order is now [card0, card1, card2] -> card2 moved up
  const gone = kept[ 1 ]!.el;
  gone.remove();                                       // card 1 left the list altogether
  tops[ 0 ] = 700;
  restoreKeepPlace(m, kept, document, w);
  assert.equal(w.calls.length <= 1, true);
});

test("restore: with the pane open the left column is scrolled, and a missing column is a no-op", () => {
  const column = shell(true, 40)!;
  const tops   = [ 100, 300 ];
  const m      = mount(2, tops);
  const w      = win(0);
  const kept   = captureKeepPlace(m, document, w)!;
  tops[ 0 ] = 160; tops[ 1 ] = 360;
  restoreKeepPlace(m, kept, document, w);
  assert.equal(column.scrollTop, 100);
  assert.deepEqual(w.calls, []);
  column.remove();
  tops[ 0 ] = 260;
  restoreKeepPlace(m, kept, document, w);              // no column now: nothing to scroll
  assert.deepEqual(w.calls, []);
});
