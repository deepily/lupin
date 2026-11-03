// keepPlace.ts: remembering and restoring each card's history scroll.
//
// A card moved in the DOM, or replaced by a fresh render (a progress-group arrival does that), has every
// scroller inside it set back to the top. These helpers write the offsets back.
//
// Run via `npx tsx --test src/tests/unit/multiplexer/render/keep_place_history_scroll.test.ts`.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  captureHistoryScroll,
  restoreHistoryScroll,
} from "../../../../lupin_app/static/js/multiplexer/render/keepPlace";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  document.body.replaceChildren();
});

/** A card with one history pane per day; a null day puts the pane outside any accordion. */
function card(key: string | null, panes: Array<{ day: string | null; top: number }>): HTMLElement {
  const c = document.createElement("div");
  if (key !== null) c.setAttribute("data-id-hash", key);
  for (const p of panes) {
    const pane = document.createElement("div");
    pane.className = "date-accordion-messages";
    pane.scrollTop = p.top;
    if (p.day === null) {
      c.appendChild(pane);
    } else {
      const day = document.createElement("div");
      day.className = "date-accordion";
      day.setAttribute("data-date-key", p.day);
      day.appendChild(pane);
      c.appendChild(day);
    }
  }
  return c;
}

function mount(...cards: HTMLElement[]): HTMLElement {
  const m = document.createElement("div");
  for (const c of cards) m.appendChild(c);
  document.body.appendChild(m);
  return m;
}

function paneOf(c: Element, day: string | null = null): HTMLElement {
  const sel = day === null ? ".date-accordion-messages" : `[data-date-key="${day}"] .date-accordion-messages`;
  return c.querySelector<HTMLElement>(sel)!;
}

test("captureHistoryScroll: remembers only the panes that are scrolled away from the top", () => {
  const m = mount(card("a", [ { day: "d1", top: 120 }, { day: "d2", top: 0 } ]), card("b", [ { day: "d1", top: 0 } ]));
  const found = captureHistoryScroll(m);
  assert.deepEqual([ ...found.entries() ], [ [ "a|d1", 120 ] ]);
});

test("captureHistoryScroll: a pane outside a day accordion is keyed by the card alone; a card with no key is skipped", () => {
  const m = mount(card("a", [ { day: null, top: 40 } ]), card(null, [ { day: "d1", top: 90 } ]));
  assert.deepEqual([ ...captureHistoryScroll(m).entries() ], [ [ "a|", 40 ] ]);
});

test("captureHistoryScroll: nothing scrolled gives an empty map", () => {
  assert.equal(captureHistoryScroll(mount(card("a", [ { day: "d1", top: 0 } ]))).size, 0);
});

test("restoreHistoryScroll: writes the offset onto the pane standing for that card and day, even a replacement", () => {
  const m = mount(card("a", [ { day: "d1", top: 120 } ]), card("b", [ { day: "d1", top: 30 } ]));
  const found = captureHistoryScroll(m);
  const fresh = card("a", [ { day: "d1", top: 0 } ]);        // a fresh render of the same card: scroll lost
  m.firstElementChild!.replaceWith(fresh);
  paneOf(m.lastElementChild!).scrollTop = 0;                  // the other card was moved: scroll lost
  restoreHistoryScroll(m, found);
  assert.equal(paneOf(fresh, "d1").scrollTop, 120);
  assert.equal(paneOf(m.lastElementChild!, "d1").scrollTop, 30);
});

test("restoreHistoryScroll: a pane already at its offset is left alone, and a pane that is gone is skipped", () => {
  const m = mount(card("a", [ { day: "d1", top: 120 }, { day: "d2", top: 60 } ]), card(null, [ { day: "d1", top: 5 } ]));
  const found = captureHistoryScroll(m);
  paneOf(m.firstElementChild!, "d2").parentElement!.remove();    // the d2 day is gone
  restoreHistoryScroll(m, found);
  assert.equal(paneOf(m.firstElementChild!, "d1").scrollTop, 120);
});

test("restoreHistoryScroll: an empty memory touches nothing", () => {
  const m = mount(card("a", [ { day: "d1", top: 50 } ]));
  restoreHistoryScroll(m, new Map());
  assert.equal(paneOf(m.firstElementChild!, "d1").scrollTop, 50);
});

test("restoreHistoryScroll: a card with no key, or a pane with no remembered offset, is skipped", () => {
  const m = mount(card("a", [ { day: "d1", top: 0 } ]), card(null, [ { day: "d1", top: 0 } ]));
  restoreHistoryScroll(m, new Map([ [ "zzz|d1", 99 ] ]));
  assert.equal(paneOf(m.firstElementChild!, "d1").scrollTop, 0);
});
