// P0 5ebd2aff (2026-09-10) — NotificationsListRenderer empty state vs cold-load
// hydration state. Run via
// `npx tsx --test src/tests/unit/multiplexer/render/notifications_list_hydration_state.test.ts`.
//
// Measured before the fix: the multiplexer painted "No notifications yet." over a
// senders-visible fetch that took 52.8 s and had been abandoned at 10 s, while
// the legacy client showed 308. A pending or failed hydration measured nothing
// and must say so.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsListRenderer } from "../../../../lupin_app/static/js/multiplexer/render";
import { HISTORY_RETRY_EVENT } from "../../../../lupin_app/static/js/multiplexer/stores/coldHistoryHydration";
import type { Notification, SenderRecord } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

type HydrationState = "idle" | "loading" | "done" | "failed";

function setup(initial: HydrationState, error: string | null = null, withHydrationSurface = true) {
  const bus = createEventBusForTesting();
  const notifList : Notification[] = [];
  const senderList: SenderRecord[] = [];
  const state = { hydration: initial, error };
  const notifications = withHydrationSurface
    ? { list: () => notifList, historyHydrationState: () => state.hydration, historyHydrationError: () => state.error }
    : { list: () => notifList };
  const renderer = createNotificationsListRenderer({
    eventBus    : bus,
    stores      : { notifications, senders: { list: () => senderList } },
    appTimezone : "UTC",
  });
  const root   = document.createElement("section");
  root.id      = "notifications-pane";
  const cards  = document.createElement("div");
  cards.id     = "sender-cards-container";
  root.appendChild(cards);
  renderer.mount(root);
  const empty = () => root.querySelector('[data-testid="multiplexer-empty-state"]');
  return { bus, renderer, root, state, notifList, empty };
}

test("loading → 'Loading notification history…', never 'No notifications yet.'", () => {
  const { empty } = setup("loading");
  assert.equal(empty()?.getAttribute("data-empty-state"), "loading");
  assert.match(empty()?.textContent ?? "", /Loading notification history/);
  assert.doesNotMatch(empty()?.textContent ?? "", /No notifications yet/);
});

test("failed → says it could not load, names the reason, says nothing was measured, offers Retry", () => {
  const { empty, root } = setup("failed", "request timed out after 10000ms");
  assert.equal(empty()?.getAttribute("data-empty-state"), "failed");
  const text = empty()?.textContent ?? "";
  assert.match(text, /Couldn't load notification history/);
  assert.match(text, /timed out after 10000ms/);
  assert.match(text, /not an empty inbox/);
  assert.doesNotMatch(text, /No notifications yet/);
  assert.ok(root.querySelector('[data-testid="multiplexer-notifications-history-retry"]') !== null);
});

test("clicking Retry emits the runner's retry event", () => {
  const { bus, root } = setup("failed", "down");
  const seen: string[] = [];
  bus.on(HISTORY_RETRY_EVENT, (e) => { seen.push(e.type); });
  (root.querySelector('[data-testid="multiplexer-notifications-history-retry"]') as HTMLButtonElement).click();
  assert.deepEqual(seen, [HISTORY_RETRY_EVENT]);
});

test("done with nothing to show → the genuine 'No notifications yet.'", () => {
  const { empty } = setup("done");
  assert.equal(empty()?.getAttribute("data-empty-state"), "empty");
  assert.match(empty()?.textContent ?? "", /No notifications yet/);
});

test("a state change REPAINTS the empty state (loading → failed → loading → done)", () => {
  const { renderer, state, empty } = setup("loading");
  state.hydration = "failed"; state.error = "down";
  renderer.forceRenderForTesting();
  assert.equal(empty()?.getAttribute("data-empty-state"), "failed");
  state.hydration = "loading"; state.error = null;
  renderer.forceRenderForTesting();
  assert.equal(empty()?.getAttribute("data-empty-state"), "loading");
  state.hydration = "done";
  renderer.forceRenderForTesting();
  assert.match(empty()?.textContent ?? "", /No notifications yet/);
});

test("a store without the hydration surface keeps the old copy (harness back-compat)", () => {
  const { empty } = setup("idle", null, false);
  assert.match(empty()?.textContent ?? "", /No notifications yet/);
});
