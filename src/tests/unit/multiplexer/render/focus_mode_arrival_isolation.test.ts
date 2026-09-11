// P0 8cb5c22e — focus mode must survive a message from ANOTHER persona.
//
// Rick, verbatim: "Every time a new message comes in on a different persona ...
// that flickering can become almost seizure inducing." Legacy is the reference:
// a foreign arrival only MOVES that sender's already-hidden card
// (notifications.js:25528) and a new card is flagged hidden at creation
// (notifications.js:19004). The focused card is never rebuilt or moved.
//
// These tests drive the REAL SessionStripRenderer and the REAL
// NotificationsListRenderer on one bus, wired the way boot.ts wires them, with
// focus ON and the "👁 Active" filter ON (Rick's configuration).
//
// ⚠️ Assertions compare ids, strings and booleans only — never a DOM node inside
// an assert message (a node in a failure message blows the jstest memory cap).

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsListRenderer } from "../../../../lupin_app/static/js/multiplexer/render";
import { createSessionStripRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SessionStripRenderer";
import type {
  Notification,
  SenderRecord,
  StripSession,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  document.body.replaceChildren();
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

const A = "claude.code@lupin.deepily.ai#aaaa1111";   // the focused persona
const B = "claude.code@lupin.deepily.ai#bbbb2222";   // a chatty peer
const D = "claude.code@lupin.deepily.ai#dddd4444";   // a persona with no card yet

const T0 = Date.UTC(2026, 8, 10, 21, 0);

interface Harness {
  bus        : ReturnType<typeof createEventBusForTesting>;
  notifs     : Notification[];
  senders    : SenderRecord[];
  strip      : StripSession[];
  cards      : HTMLElement;
  iconsEl    : HTMLElement;
  hideToggle : HTMLElement;
}

function persona(name: string) {
  return { name, voice_id: "v", icon: "🙂", color: "#81D4FA", borrowed: false };
}

function sender(id: string, ts: number): SenderRecord {
  return { sender_id: id, display_name: "lupin", last_active_ts: ts, unread_count: 1, conversation_mode_active: false };
}

function note(idHash: string, senderId: string, ts: number): Notification {
  return { id_hash: idHash, ts, sender_id: senderId, message: `msg ${idHash}`, action_required: false };
}

function setup(): Harness {
  const bus     = createEventBusForTesting();
  const notifs  : Notification[] = [ note("a1", A, T0 + 2_000), note("b1", B, T0 + 1_000) ];
  const senders : SenderRecord[] = [ sender(A, T0 + 2_000), sender(B, T0 + 1_000) ];
  const strip   : StripSession[] = [
    { sender_id: A, voice_persona: persona("Ava"),  assigned_at: 1, active: true },
    { sender_id: B, voice_persona: persona("Bo"),   assigned_at: 2, active: true },
    { sender_id: D, voice_persona: persona("Dee"),  assigned_at: 3, active: true },
  ];

  const main = document.createElement("main");
  main.className = "container";
  main.innerHTML = `
    <div id="cc-session-strip">
      <div id="cc-strip-icons"></div>
      <button id="cc-strip-toggle"></button>
      <button id="cc-hide-inactive-toggle"></button>
    </div>
    <section id="notifications-pane"><div id="sender-cards-container"></div></section>`;
  document.body.appendChild(main);

  // Boot wiring: the strip is constructed first so the list renderer can ask it
  // whether a card it is about to insert must be hidden.
  const stripRenderer = createSessionStripRenderer({ eventBus: bus, stores: { strip: { list: () => strip } } });
  const listRenderer  = createNotificationsListRenderer({
    eventBus : bus,
    stores   : { notifications: { list: () => notifs }, senders: { list: () => senders } },
    appTimezone       : "UTC",
    isCardFocusHidden : (senderId: string) => stripRenderer.isCardFocusHidden(senderId),
  });

  listRenderer.mount(main.querySelector<HTMLElement>("#notifications-pane")!);
  stripRenderer.mount(main);

  const h: Harness = {
    bus, notifs, senders, strip,
    cards      : main.querySelector<HTMLElement>("#sender-cards-container")!,
    iconsEl    : main.querySelector<HTMLElement>("#cc-strip-icons")!,
    hideToggle : main.querySelector<HTMLElement>("#cc-hide-inactive-toggle")!,
  };
  return h;
}

function click(el: Element): void {
  el.dispatchEvent(new Event("click", { bubbles: true }));
}

function clickIcon(h: Harness, senderId: string): void {
  const icon = h.iconsEl.querySelector(`.cc-strip-icon[data-sender-id="${senderId}"]`);
  assert.equal(icon !== null, true, `strip icon for ${senderId} exists`);
  click(icon!);
}

function cardFor(h: Harness, senderId: string): HTMLElement | null {
  return h.cards.querySelector<HTMLElement>(`.sender-card[data-sender-id="${senderId}"]`);
}

function visibleIds(h: Harness): string[] {
  return Array.from(h.cards.querySelectorAll<HTMLElement>(".sender-card"))
    .filter(c => !c.hasAttribute("data-focus-hidden"))
    .map(c => c.getAttribute("data-sender-id") ?? "");
}

function allIds(h: Harness): string[] {
  return Array.from(h.cards.querySelectorAll<HTMLElement>(".sender-card")).map(c => c.getAttribute("data-sender-id") ?? "");
}

// A message arrives the way production delivers it: both stores update, and each
// emits its own change event (NotificationStore, then SenderStore).
// Row 11793820 — NotificationsListRenderer renders once per turn, in a microtask
// queued by the store events. A microtask queued after them runs after that render.
const renderTurn = (): Promise<void> => new Promise<void>(resolve => queueMicrotask(resolve));

async function arrive(h: Harness, idHash: string, senderId: string, ts: number): Promise<void> {
  h.notifs.push(note(idHash, senderId, ts));
  const rec = h.senders.find(s => s.sender_id === senderId);
  if (rec === undefined) {
    h.senders.push(sender(senderId, ts));
  } else {
    rec.last_active_ts = ts;
    rec.unread_count++;
  }
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: idHash }, source: "test", ts: 0 });
  h.bus.emit({ type: "store_senders_changed", payload: { changeKind: "updated", sender_id: senderId }, source: "test", ts: 0 });
  await renderTurn();
}

// Focus on A with the "👁 Active" filter on — Rick's configuration.
function focusOnA(h: Harness): void {
  click(h.hideToggle);
  clickIcon(h, A);
  assert.deepEqual(visibleIds(h), [ A ], "precondition: only the focused card is visible");
}

async function flushMutations(): Promise<void> {
  await new Promise<void>(resolve => setTimeout(resolve, 0));
}

// ===========================================================================
// The defect
// ===========================================================================

test("focus + Active: a message from another persona leaves only the focused card visible", async () => {
  const h = setup();
  focusOnA(h);

  await arrive(h, "b2", B, T0 + 5_000);

  assert.deepEqual(visibleIds(h), [ A ]);
});

test("focus + Active: a message from a persona with no card yet creates that card hidden", async () => {
  const h = setup();
  focusOnA(h);

  await arrive(h, "d1", D, T0 + 6_000);

  assert.equal(cardFor(h, D) !== null, true, "the new persona's card exists");
  assert.deepEqual(visibleIds(h), [ A ]);
});

test("focus + Active: the focused card stays the SAME node across a foreign arrival", async () => {
  const h = setup();
  focusOnA(h);
  const before = cardFor(h, A);

  await arrive(h, "b2", B, T0 + 5_000);
  await arrive(h, "d1", D, T0 + 6_000);

  const sameNode = cardFor(h, A) === before;
  assert.equal(sameNode, true, "the focused card was not rebuilt");
});

test("focus + Active: the focused card is never detached or reinserted by a foreign arrival", async () => {
  const h = setup();
  focusOnA(h);
  const focused = cardFor(h, A);
  let touched = false;
  const observer = new MutationObserver((records) => {
    for (const r of records) {
      if (Array.from(r.removedNodes).includes(focused as Node)) touched = true;
      if (Array.from(r.addedNodes).includes(focused as Node)) touched = true;
    }
  });
  observer.observe(h.cards, { childList: true });

  await arrive(h, "b2", B, T0 + 5_000);
  await arrive(h, "d1", D, T0 + 6_000);
  await flushMutations();
  observer.disconnect();

  assert.equal(touched, false, "no childList record moved the focused card");
  assert.deepEqual(allIds(h), [ D, B, A ], "the hidden cards still sort by recency");
});

test("focus + Active: every card is inserted already carrying the right focus flag", async () => {
  const h = setup();
  focusOnA(h);

  // Record the flag of each card at the MOMENT it enters the container — the
  // legacy contract (notifications.js:19004) is "flagged at creation", so a card
  // that is inserted visible and hidden a moment later is the defect.
  const wrong: string[] = [];
  const check = (node: Node): void => {
    if (!(node instanceof HTMLElement) || !node.classList.contains("sender-card")) return;
    const id       = node.getAttribute("data-sender-id") ?? "";
    const isHidden = node.hasAttribute("data-focus-hidden");
    if (isHidden !== (id !== A)) wrong.push(`${id}:${isHidden ? "hidden" : "visible"}`);
  };
  const origAppend  = h.cards.appendChild.bind(h.cards);
  const origInsert  = h.cards.insertBefore.bind(h.cards);
  const origReplace = Element.prototype.replaceWith;
  h.cards.appendChild  = <T extends Node>(n: T): T => { check(n); return origAppend(n); };
  h.cards.insertBefore = <T extends Node>(n: T, ref: Node | null): T => { check(n); return origInsert(n, ref); };
  Element.prototype.replaceWith = function (this: Element, ...nodes: Array<Node | string>): void {
    for (const n of nodes) if (typeof n !== "string") check(n);
    origReplace.apply(this, nodes);
  };
  try {
    await arrive(h, "b2", B, T0 + 5_000);
    await arrive(h, "d1", D, T0 + 6_000);
    await arrive(h, "a2", A, T0 + 7_000);
  } finally {
    Element.prototype.replaceWith = origReplace;
  }

  assert.deepEqual(wrong, []);
  assert.deepEqual(visibleIds(h), [ A ]);
});

test("focus + Active: the focused card's own new message still shows, and it stays the only visible card", async () => {
  const h = setup();
  focusOnA(h);

  await arrive(h, "a2", A, T0 + 7_000);

  assert.deepEqual(visibleIds(h), [ A ]);
  assert.equal(cardFor(h, A)!.querySelector('[data-id-hash="a2"]') !== null, true, "the new message rendered in the focused card");
});

test("focus + Active: the active dot moves to the newest persona without rebuilding the focused card", async () => {
  const h = setup();
  focusOnA(h);
  const before = cardFor(h, A);
  assert.equal(before!.classList.contains("sender-card-active"), true, "precondition: A is the most recent sender");

  await arrive(h, "b2", B, T0 + 5_000);

  assert.equal(cardFor(h, A) === before, true, "same node");
  assert.equal(cardFor(h, A)!.classList.contains("sender-card-active"), false);
  assert.equal(cardFor(h, A)!.querySelector(".sender-active-indicator")!.textContent, "○");
  assert.equal(cardFor(h, B)!.classList.contains("sender-card-active"), true);
  assert.equal(cardFor(h, B)!.querySelector(".sender-active-indicator")!.getAttribute("title"), "Active session");
});

// ===========================================================================
// Control — switching persona DOES switch
// ===========================================================================

test("control: clicking another persona's icon switches the visible card", async () => {
  const h = setup();
  focusOnA(h);
  await arrive(h, "b2", B, T0 + 5_000);

  clickIcon(h, B);

  assert.deepEqual(visibleIds(h), [ B ]);
});

test("control: with focus OFF, a foreign arrival shows every card", async () => {
  const h = setup();

  await arrive(h, "d1", D, T0 + 6_000);

  assert.deepEqual(visibleIds(h), [ D, A, B ]);
});
