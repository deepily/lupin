// Row 0e5bfa0e — the app timezone reaches the multiplexer, LATE, and the cards repaint.
//
// WHAT WAS BROKEN, and why "pass the option in boot" was never the whole fix.
// `createNotificationsListRenderer` has always accepted an `appTimezone` option and
// boot never passed one, so every mux timestamp rendered in the BROWSER's local zone
// whatever `app timezone` said in the INI (measured by Sam, 2026-09-15). But the value
// arrives from `/api/config/client`, and boot is SYNCHRONOUS while that fetch is not —
// at construction time the zone is always still unknown. So the renderer has to accept
// it late, and accepting it late is only half the job:
//
// 🔴 THREE CACHES EXIST TO AVOID RE-RENDERING A CARD WHOSE INPUTS HAVE NOT MOVED, and
// the zone is not one of their inputs. A setter that only assigns the field would leave
// `cardInputs` reporting "unchanged", `cardSignatures` matching the stale markup and
// `historyCache` replaying old fragments — the zone would be adopted and NOTHING on
// screen would move. That is the failure these tests are pointed at: every one asserts
// the RENDERED TEXT, never the stored value.
//
// The zones are chosen so the assertion cannot be satisfied by accident: 04:00 UTC is
// the previous calendar day in New York and the same day in Tokyo, and the three clock
// readings are 13 hours apart.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createNotificationsListRenderer,
  type NotificationsListRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render";
import type { Notification, SenderRecord } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});

// 2026-05-05T04:00Z — deliberately in the window where the three zones disagree about
// the DATE as well as the clock: 2026-05-05 in UTC and Tokyo, 2026-05-04 in New York.
const TS = Date.UTC(2026, 4, 5, 4, 0);

interface Setup {
  bus      : ReturnType<typeof createEventBusForTesting>;
  sCards   : HTMLElement;
  renderer : NotificationsListRenderer;
  /** How many times the renderer has announced a completed render. */
  renders  : () => number;
}

function setup(appTimezone?: string): Setup {
  const bus       = createEventBusForTesting();
  const notifs    : Notification[] = [
    { id_hash: "n1", ts: TS, sender_id: "sess_42", message: "hi", action_required: false },
  ];
  const senders   : SenderRecord[] = [
    { sender_id: "sess_42", display_name: "S", last_active_ts: TS, unread_count: 1, conversation_mode_active: false },
  ];

  const renderer = createNotificationsListRenderer({
    eventBus : bus,
    stores   : { notifications: { list: () => notifs }, senders: { list: () => senders } },
    ...(appTimezone === undefined ? {} : { appTimezone }),
  });

  const root     = document.createElement("section");
  const arSection = document.createElement("div");
  arSection.id   = "action-required-section";
  const sCards   = document.createElement("div");
  sCards.id      = "sender-cards-container";
  root.appendChild(arSection);
  root.appendChild(sCards);
  renderer.mount(root);

  // The renderer announces every completed render on the bus. Counting those is the
  // only honest "did it repaint?" probe here: a stray sentinel node in the mount does
  // NOT get cleared by a repaint, because keyedListMerge reconciles the keyed card
  // elements and leaves everything else alone. The first version of these tests used
  // a sentinel and two of them passed vacuously — the assertion could not have failed
  // whatever the setter did.
  let renders = 0;
  bus.on("notifications_list_rendered", () => { renders += 1; });

  return { bus, sCards, renderer, renders: () => renders };
}

/** Ensures: the rendered text of the whole card area, which is what an operator reads. */
function painted(s: Setup): string {
  return s.sCards.textContent ?? "";
}

/** Ensures: lets the renderer's queueMicrotask flush, the same way it flushes in the browser. */
async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

// ===========================================================================
// The repaint — the half a field assignment does not buy
// ===========================================================================

test("a zone arriving after the first paint REPAINTS the clock, it does not just get stored", async () => {
  const s = setup("UTC");
  s.renderer.forceRenderForTesting();
  const utc = painted(s);
  assert.ok(utc.includes("04:00"), `expected the UTC clock in the first paint, got: ${utc}`);

  s.renderer.setAppTimezone("Asia/Tokyo");
  await settle();

  const tokyo = painted(s);
  assert.ok(tokyo.includes("13:00"), `expected the Tokyo clock after the late zone, got: ${tokyo}`);
  assert.ok(!tokyo.includes("04:00"), "the UTC clock survived the repaint — a cache held the stale render");
});

test("the late zone also moves the DATE, not only the clock — New York is the previous day here", async () => {
  const s = setup("UTC");
  s.renderer.forceRenderForTesting();
  assert.ok(painted(s).includes("04:00"), "precondition: the first paint is UTC");

  s.renderer.setAppTimezone("America/New_York");
  await settle();

  const ny = painted(s);
  assert.ok(ny.includes("00:00"), `expected the New York clock, got: ${ny}`);
});

test("a renderer that never had a zone still adopts one — the no-wire case this row was filed for", async () => {
  const s = setup();                       // exactly boot's old behaviour: no appTimezone at all
  s.renderer.forceRenderForTesting();

  s.renderer.setAppTimezone("Asia/Tokyo");
  await settle();

  assert.ok(painted(s).includes("13:00"), `expected the Tokyo clock, got: ${painted(s)}`);
});

// ===========================================================================
// The negative controls — a setter that repaints on everything is its own defect
// ===========================================================================

test("setting the SAME zone is a no-op: no render is announced", async () => {
  const s = setup("Asia/Tokyo");
  s.renderer.forceRenderForTesting();
  assert.ok(painted(s).includes("13:00"), "precondition: the first paint was Tokyo");
  const before = s.renders();

  s.renderer.setAppTimezone("Asia/Tokyo");
  await settle();

  assert.equal(s.renders(), before, "a same-value set scheduled a render it did not need");
});

test("clearing the zone to undefined DOES repaint — it is a change, not a 'no value to apply'", async () => {
  const s = setup("Asia/Tokyo");
  s.renderer.forceRenderForTesting();
  const before = s.renders();

  s.renderer.setAppTimezone(undefined);
  await settle();

  assert.equal(s.renders(), before + 1, "clearing the zone was swallowed as 'no change'");
});
