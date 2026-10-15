// The multiplexer's notification history keeps the reader's place on an arrival.
//
// Rick's report: "an update inevitably arrives and the Notifications History is scrolled once again to
// the top of the notification list." An arrival re-sorts the sender cards, so the arriving sender's card
// goes to the top and every card the reader can see shifts down by its height. With Keep place on (the
// default; the key is shared with the legacy client) the card the reader is looking at is pinned across
// that merge.
//
// happy-dom has no layout, so a card's rect is modelled: cards are stacked in DOM order, CARD_HEIGHT
// apart, and the scroll offset moves them up. The renderer may scroll only through globalThis.scrollBy,
// which the stub applies to that same offset. Assertions compare numbers and ids, never a node.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsListRenderer } from "../../../../lupin_app/static/js/multiplexer/render";
import {
  KEEP_PLACE_KEY,
  readKeepPlace,
} from "../../../../lupin_app/static/js/multiplexer/render/keepPlace";
import type { Notification, SenderRecord } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

const CARD_HEIGHT = 200;
const NAV_OFFSET  = 100;
const T0          = Date.UTC(2026, 8, 11, 18, 0);
const idFor       = (i: number) => `claude.code@lupin.deepily.ai#cafe${String(i).padStart(4, "0")}`;

let scrollY = 0;
const realRect = Element.prototype.getBoundingClientRect;

beforeEach(() => {
  scrollY = 0;
  document.body.replaceChildren();
  localStorage.clear();
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
  Element.prototype.getBoundingClientRect = function (this: Element): DOMRect {
    const parent = this.parentElement;
    if (parent === null || !this.classList.contains("sender-card")) return realRect.call(this);
    const index = Array.from(parent.children).indexOf(this);
    const top   = NAV_OFFSET + index * CARD_HEIGHT - scrollY;
    return { top, bottom: top + CARD_HEIGHT, left: 0, right: 800, width: 800, height: CARD_HEIGHT, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  };
  Object.defineProperty(globalThis, "scrollY", { get: () => scrollY, configurable: true });
  (globalThis as unknown as { scrollBy: (x: number, y: number) => void }).scrollBy = (_x: number, y: number): void => { scrollY += y; };
});

afterEach(() => {
  Element.prototype.getBoundingClientRect = realRect;
});

interface Harness {
  bus     : ReturnType<typeof createEventBusForTesting>;
  notifs  : Notification[];
  senders : SenderRecord[];
  cards   : HTMLElement;
}

function setup(senderCount: number): Harness {
  const bus     = createEventBusForTesting();
  const notifs  : Notification[] = [];
  const senders : SenderRecord[] = [];
  for (let i = 0; i < senderCount; i++) {
    senders.push({ sender_id: idFor(i), display_name: "lupin", last_active_ts: T0 + i * 1_000, unread_count: 1, conversation_mode_active: false });
    notifs.push({ id_hash: `s${i}r0`, ts: T0 + i * 1_000, sender_id: idFor(i), message: `msg ${i}`, action_required: false });
  }
  const pane = document.createElement("section");
  pane.innerHTML = `<div id="sender-cards-container"></div>`;
  document.body.appendChild(pane);
  const renderer = createNotificationsListRenderer({
    eventBus : bus,
    stores   : {
      notifications  : { list: () => notifs },
      senders        : { list: () => senders },
      predictionVote : { getVote: () => undefined, setContext: () => { /* not exercised */ }, vote: async () => true },
    },
    appTimezone : "UTC",
  });
  renderer.mount(pane);
  return { bus, notifs, senders, cards: pane.querySelector<HTMLElement>("#sender-cards-container")! };
}

const settle = (): Promise<void> => new Promise<void>(resolve => setTimeout(resolve, 0));

async function arrive(h: Harness, senderIndex: number, ts: number): Promise<void> {
  const id = idFor(senderIndex);
  h.notifs.push({ id_hash: `new-${senderIndex}-${ts}`, ts, sender_id: id, message: "update", action_required: false });
  const rec = h.senders.find(s => s.sender_id === id)!;
  rec.last_active_ts = ts;
  rec.unread_count++;
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: `new-${senderIndex}-${ts}` }, source: "test", ts: 0 });
  h.bus.emit({ type: "store_senders_changed", payload: { changeKind: "updated", sender_id: id }, source: "test", ts: 0 });
  await settle();
}

const order = (h: Harness): string[] => Array.from(h.cards.children).map(c => c.getAttribute("data-id-hash") ?? "");

function topOf(h: Harness, senderIndex: number): number {
  const card = h.cards.querySelector<HTMLElement>(`[data-id-hash="${idFor(senderIndex)}"]`)!;
  return card.getBoundingClientRect().top;
}

test("the newest sender is first, so the layout model below starts from a known order", async () => {
  const h = setup(5);
  await settle();
  assert.deepEqual(order(h), [4, 3, 2, 1, 0].map(idFor));
});

test("an update from a card below the view moves it to the top and the reader keeps their place", async () => {
  const h = setup(5);
  await settle();
  scrollY = 450;                                  // cards 2 (at 50) and 1 (at 250) are on screen
  const before2 = topOf(h, 2);
  const before1 = topOf(h, 1);
  await arrive(h, 0, T0 + 60_000);
  assert.equal(order(h)[0], idFor(0), "the card did move to the top");
  assert.equal(topOf(h, 2), before2);
  assert.equal(topOf(h, 1), before1);
});

test("at the top of the list nothing is compensated", async () => {
  const h = setup(5);
  await settle();
  scrollY = 0;
  await arrive(h, 0, T0 + 60_000);
  assert.equal(scrollY, 0);
  assert.equal(topOf(h, 0), NAV_OFFSET);
});

test("with Keep place off the view is left to shift, as it always was", async () => {
  localStorage.setItem(KEEP_PLACE_KEY, "false");
  const h = setup(5);
  await settle();
  scrollY = 450;
  const before2 = topOf(h, 2);
  await arrive(h, 0, T0 + 60_000);
  assert.equal(scrollY, 450);
  assert.equal(topOf(h, 2), before2 + CARD_HEIGHT);
});

test("an update from the card the reader is looking at is not used as its own anchor", async () => {
  const h = setup(5);
  await settle();
  scrollY = 450;                                  // card 1 is the first card at or below the strip
  const before0 = topOf(h, 0);
  await arrive(h, 1, T0 + 60_000);
  assert.equal(order(h)[0], idFor(1));
  assert.equal(topOf(h, 0), before0, "the first card that did not move is the anchor");
});

test("Keep place is on when nothing was stored, off only for the stored word false", () => {
  assert.equal(readKeepPlace(localStorage), true);
  localStorage.setItem(KEEP_PLACE_KEY, "true");
  assert.equal(readKeepPlace(localStorage), true);
  localStorage.setItem(KEEP_PLACE_KEY, "false");
  assert.equal(readKeepPlace(localStorage), false);
  assert.equal(readKeepPlace(null), true);
  assert.equal(KEEP_PLACE_KEY, "notifications_keep_place", "the legacy client reads the same key");
});

// A browser that blocks storage must not break the list: the preference reads as on.
for (const [label, getter] of [
  ["throws on access", (): Storage => { throw new Error("blocked"); }],
  ["is absent", (): undefined => undefined],
] as const) {
  test(`when localStorage ${label} the arrival still renders and the reader's place is kept`, async () => {
    const h = setup(5);
    await settle();
    scrollY = 450;
    const before2 = topOf(h, 2);
    const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    Object.defineProperty(globalThis, "localStorage", { get: getter, configurable: true });
    try {
      await arrive(h, 0, T0 + 60_000);
    } finally {
      if (original !== undefined) Object.defineProperty(globalThis, "localStorage", original);
    }
    assert.equal(order(h)[0], idFor(0));
    assert.equal(topOf(h, 2), before2);
  });
}
