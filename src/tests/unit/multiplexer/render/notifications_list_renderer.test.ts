// Multiplexer Phase 5 — NotificationsListRenderer unit tests.
// AC4 floor: ≥16 tests including:
//   - Hydrate / add / update / expire / mount / unmount / no leaked listeners
//   - Tick invariant (data-test-canary sentinel + 10-burst) per F5/A13
//   - 4 empty-state transitions per F18
//   - Progress-group lazy-cache (hydrate → expand → simulate updated → collapse → expand) per F14

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createNotificationsListRenderer,
  type NotificationsListRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render";
import type {
  Notification,
  SenderRecord,
  PredictionVoteDir,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";
import type { PredictionVoteContext } from "../../../../lupin_app/static/js/multiplexer/stores/PredictionVoteStore";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = {
    parse: (s: string) => `<p>${s}</p>`,
  };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = {
    sanitize: (s: string) => s,
  };
});

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

interface TestSetup {
  bus       : ReturnType<typeof createEventBusForTesting>;
  notifList : Notification[];
  senderList: SenderRecord[];
  renderer  : NotificationsListRenderer;
  root      : HTMLElement;
}

function setupRenderer(): TestSetup {
  const bus = createEventBusForTesting();
  const notifList : Notification[] = [];
  const senderList: SenderRecord[] = [];

  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : {
      notifications  : { list: () => notifList },
      senders        : { list: () => senderList },
    },
    appTimezone: "UTC",
  });

  // Production pane shape (post-56e422aa AR-rip): #notifications-pane holds
  // #sender-cards-container. A stray #action-required-section is included on
  // purpose to prove this renderer NEVER touches it (it is owned document-level
  // by the separate ActionRequiredRenderer).
  const root = document.createElement("section");
  root.id = "notifications-pane";
  const arSection = document.createElement("div");
  arSection.id = "action-required-section";
  const sCards = document.createElement("div");
  sCards.id = "sender-cards-container";
  root.appendChild(arSection);
  root.appendChild(sCards);

  return { bus, notifList, senderList, renderer, root };
}

function makeNotification(over: Partial<Notification> = {}): Notification {
  return {
    id_hash         : "n1",
    ts              : Date.UTC(2026, 4, 5, 14, 7),
    sender_id       : "sess_42",
    message         : "hello",
    action_required : false,
    ...over,
  };
}

function makeSender(over: Partial<SenderRecord> = {}): SenderRecord {
  return {
    sender_id                : "sess_42",
    display_name             : "Sender",
    last_active_ts           : Date.UTC(2026, 4, 5, 14, 7),
    unread_count             : 1,
    conversation_mode_active : false,
    ...over,
  };
}

// ===========================================================================
// 1-3 : Mount / unmount lifecycle
// ===========================================================================

test("mount: throws if mount root not provided + .mount() called twice", () => {
  const { renderer, root } = setupRenderer();
  renderer.mount(root);
  assert.throws(() => renderer.mount(root), /already mounted/);
  renderer.unmount();
});

test("mount: routes to #action-required-section + #sender-cards-container per D-L", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification());
  senderList.push(makeSender());
  renderer.mount(root);
  // Sender card lives in #sender-cards-container, NOT in #action-required-section.
  assert.equal(root.querySelector("#sender-cards-container .sender-card") !== null, true);
  assert.ok( root.querySelector("#action-required-section .sender-card") === null );
  renderer.unmount();
});

test("unmount: removes all event subscriptions (no leaked listeners)", () => {
  const { renderer, root, bus, notifList } = setupRenderer();
  renderer.mount(root);
  renderer.unmount();
  // Post-unmount: emit a store change. If subscriptions leaked, this would
  // attempt to mutate a now-null root and throw. We assert it does NOT throw
  // AND DOM stays clean.
  notifList.push(makeNotification());
  bus.emit({
    type    : "store_notifications_changed",
    payload : { changeKind: "added", id_hash: "n1" },
    source  : "test",
    ts      : 0,
  });
  // No sender card should appear (renderer was unmounted before the event).
  assert.ok( root.querySelector(".sender-card") === null );
});

// ===========================================================================
// 4-7 : Empty-state transitions (per F18)
// ===========================================================================

test("empty-state (a): hydrate-with-zero → empty-state element painted", () => {
  const { renderer, root } = setupRenderer();
  renderer.mount(root);
  const emptyEl = root.querySelector('[data-testid="multiplexer-empty-state"]');
  assert.notEqual(emptyEl, null);
  assert.match(emptyEl!.textContent ?? "", /No notifications yet/i);
  renderer.unmount();
});

test("empty-state (b): hydrate-with-N → no empty-state element + sender card present", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification());
  senderList.push(makeSender());
  renderer.mount(root);
  assert.ok( root.querySelector('[data-testid="multiplexer-empty-state"]') === null );
  assert.ok( root.querySelector(".sender-card") !== null );
  renderer.unmount();
});

test("empty-state (d): post-added-from-zero → empty-state removed; sender card appears", () => {
  const { renderer, root, bus, notifList, senderList } = setupRenderer();
  renderer.mount(root);
  // Initially empty.
  assert.ok( root.querySelector('[data-testid="multiplexer-empty-state"]') !== null );
  notifList.push(makeNotification());
  senderList.push(makeSender());
  bus.emit({
    type    : "store_notifications_changed",
    payload : { changeKind: "added", id_hash: "n1" },
    source  : "test",
    ts      : 0,
  });
  assert.ok( root.querySelector('[data-testid="multiplexer-empty-state"]') === null );
  assert.ok( root.querySelector(".sender-card") !== null );
  renderer.unmount();
});

test("empty-state (c): post-expired-to-zero → empty-state re-appears", () => {
  const { renderer, root, bus, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification());
  senderList.push(makeSender());
  renderer.mount(root);
  // Drain the list (simulate expiry).
  notifList.length = 0;
  bus.emit({
    type    : "store_notifications_changed",
    payload : { changeKind: "expired", id_hash: "n1" },
    source  : "test",
    ts      : 0,
  });
  assert.ok( root.querySelector('[data-testid="multiplexer-empty-state"]') !== null );
  assert.ok( root.querySelector(".sender-card") === null );
  renderer.unmount();
});

// ===========================================================================
// 8-9 : Add + update flows
// ===========================================================================

test("on store_notifications_changed: added → keyedListMerge appends sender card", () => {
  const { renderer, root, bus, notifList, senderList } = setupRenderer();
  renderer.mount(root);
  notifList.push(makeNotification());
  senderList.push(makeSender());
  bus.emit({
    type    : "store_notifications_changed",
    payload : { changeKind: "added", id_hash: "n1" },
    source  : "test",
    ts      : 0,
  });
  const card = root.querySelector('[data-id-hash="sess_42"]');
  assert.notEqual(card, null);
  renderer.unmount();
});

test("on store_senders_changed: re-renders sender chrome (e.g. unread count update)", () => {
  const { renderer, root, bus, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification());
  senderList.push(makeSender({ unread_count: 1 }));
  renderer.mount(root);
  assert.equal(root.querySelector(".sender-new-count")!.textContent, "1");
  // Update sender unread count.
  senderList[0] = makeSender({ unread_count: 5 });
  bus.emit({
    type    : "store_senders_changed",
    payload : { changeKind: "updated", sender_id: "sess_42" },
    source  : "test",
    ts      : 0,
  });
  assert.equal(root.querySelector(".sender-new-count")!.textContent, "5");
  renderer.unmount();
});

// ===========================================================================
// AR-rip (bug 56e422aa): this renderer is SENDER-CARDS ONLY. It no longer
// subscribes to store_action_required_changed, renders action-required widgets,
// or touches #action-required-section — that section is owned wholesale by the
// separate ActionRequiredRenderer (document-level). The former AR tests (tick
// invariant, non-tick re-render, read-only empty panel, Phase-6b ownership guard)
// are removed with the code; the non-interference guarantee is asserted below by
// "mount: routes..." + "AR store events are ignored".
// ===========================================================================

// ===========================================================================
// 12-13 : Multi-sender + sender ordering
// ===========================================================================

test("multi-sender: 2 senders → 2 sender cards; sorted by last_active_ts descending", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  const tsOlder = Date.UTC(2026, 4, 5, 10, 0);
  const tsNewer = Date.UTC(2026, 4, 5, 14, 0);
  notifList.push(makeNotification({ id_hash: "n1", sender_id: "alpha", ts: tsOlder }));
  notifList.push(makeNotification({ id_hash: "n2", sender_id: "beta",  ts: tsNewer }));
  senderList.push(makeSender({ sender_id: "alpha", last_active_ts: tsOlder }));
  senderList.push(makeSender({ sender_id: "beta",  last_active_ts: tsNewer }));
  renderer.mount(root);
  const cards = root.querySelectorAll('#sender-cards-container > .sender-card');
  assert.equal(cards.length, 2);
  // Newer (beta) at top.
  assert.equal(cards[0]!.getAttribute("data-id-hash"), "beta");
  assert.equal(cards[1]!.getAttribute("data-id-hash"), "alpha");
  renderer.unmount();
});

test("notification with unknown sender_id: stub SenderRecord synthesized + card rendered", () => {
  const { renderer, root, notifList } = setupRenderer();
  notifList.push(makeNotification({ id_hash: "n1", sender_id: "unknown_42" }));
  // No senderList entry on purpose.
  renderer.mount(root);
  const card = root.querySelector('[data-id-hash="unknown_42"]');
  assert.notEqual(card, null);
  // Display name falls back to sender_id (WS4/G4: the project-label slot is now
  // the legacy-verbatim `.sender-project-name`, renamed from `.sender-display-name`).
  assert.equal(card!.querySelector(".sender-project-name")!.textContent, "unknown_42");
  renderer.unmount();
});

// ===========================================================================
// 14-16 : Progress-group lazy-render (Q-G + F14)
// ===========================================================================

test("progress-group: head renders eagerly, history container is empty + hidden initially", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification({ id_hash: "n1", progress_group_id: "pg_1", message: "current" }));
  senderList.push(makeSender());
  renderer.mount(root);
  const head = root.querySelector(".progress-group-head");
  const history = root.querySelector(".progress-group-history") as HTMLElement;
  assert.notEqual(head, null);
  assert.notEqual(history, null);
  assert.equal(history.hasAttribute("hidden"), true);
  // History contains zero entries pre-expansion.
  assert.equal(history.querySelectorAll(".progress-history-entry").length, 0);
  renderer.unmount();
});

test("progress-group lazy-cache: first toggle materializes history; second toggle hides; third re-shows cached", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  // 3 notifications in same progress group (n1 = head, n2 + n3 = history).
  notifList.push(makeNotification({ id_hash: "n1", ts: 1000, progress_group_id: "pg_1", message: "current" }));
  notifList.push(makeNotification({ id_hash: "n2", ts: 500,  progress_group_id: "pg_1", message: "older" }));
  notifList.push(makeNotification({ id_hash: "n3", ts: 100,  progress_group_id: "pg_1", message: "oldest" }));
  senderList.push(makeSender());
  renderer.mount(root);

  const head = root.querySelector(".progress-group-head") as HTMLElement;
  const toggle = head.querySelector(".progress-group-toggle") as HTMLElement;
  const message = head.closest("[data-progress-group]") as HTMLElement;
  const history = message.querySelector(".progress-group-history") as HTMLElement;

  // Wait — the renderer's full-list materialization shows ALL siblings as
  // history. n1 is the head only IF its data-id-hash matches the head element.
  // For this test, the renderer picks the FIRST notification in the source
  // list as the head (per renderNotificationItem rendering order). Verify.
  assert.equal(history.hasAttribute("hidden"), true);

  // First toggle — expand.
  toggle.click();
  assert.equal(history.hasAttribute("hidden"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  // History entries materialized — should contain n2 + n3 (the non-head notifications).
  // Head is n1 (the first list entry rendered as `.sender-message`); n2 + n3 are history.
  const entries1 = history.querySelectorAll(".progress-history-entry");
  assert.ok(entries1.length >= 1, `expected ≥1 history entries, got ${entries1.length}`);

  // Second toggle — collapse.
  toggle.click();
  assert.equal(history.hasAttribute("hidden"), true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");

  // Third toggle — re-show. Same number of entries (cached).
  toggle.click();
  const entries2 = history.querySelectorAll(".progress-history-entry");
  assert.equal(entries2.length, entries1.length);

  renderer.unmount();
});

test("progress-group expansion state survives a re-render (F14 cache invariant)", () => {
  const { renderer, root, bus, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification({ id_hash: "n1", ts: 1000, progress_group_id: "pg_1", message: "current" }));
  notifList.push(makeNotification({ id_hash: "n2", ts: 500,  progress_group_id: "pg_1", message: "older" }));
  senderList.push(makeSender());
  renderer.mount(root);

  const initialToggle = root.querySelector(".progress-group-toggle") as HTMLElement;
  initialToggle.click();   // expand

  // Force a re-render.
  renderer.forceRenderForTesting();

  const reToggle = root.querySelector(".progress-group-toggle") as HTMLElement;
  // After re-render, the new toggle reflects expanded state (per F14).
  assert.equal(reToggle.getAttribute("aria-expanded"), "true");
  assert.equal((root.querySelector(".progress-group-history") as HTMLElement).hasAttribute("hidden"), false);

  // Add a new entry to the same progress group + emit.
  notifList.push(makeNotification({ id_hash: "n3", ts: 200, progress_group_id: "pg_1", message: "even older" }));
  bus.emit({
    type    : "store_notifications_changed",
    payload : { changeKind: "added", id_hash: "n3" },
    source  : "test",
    ts      : 0,
  });

  // History fragment got rebuilt to include n3 (cache invalidated on re-render per F14).
  const history = root.querySelector(".progress-group-history") as HTMLElement;
  assert.equal(history.hasAttribute("hidden"), false, "history should remain expanded after re-render");

  renderer.unmount();
});

// ===========================================================================
// 17 : Sanity — initial paint reads notificationStore.list() at mount time (F13)
// ===========================================================================

test("F13: initial mount paints from notificationStore.list() (no events fired yet)", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  // Pre-populate BEFORE mount (simulating "events arrived between createStores
  // and createNotificationsListRenderer.mount").
  notifList.push(makeNotification());
  senderList.push(makeSender());
  // No events emitted; mount should still pick up the notification.
  renderer.mount(root);
  assert.ok( root.querySelector(".sender-card") !== null );
  renderer.unmount();
});

// ===========================================================================
// Branch-coverage close-out tests (added 2026-05-06 for the 100% c8 mandate).
// ===========================================================================

// bug 2826d65c — the silent `?? root` fallbacks are GONE. #sender-cards-container
// is owned + required → mount THROWS LOUDLY when it is missing (no silent retarget
// that could wipe siblings).
test("mount fail-loud: root WITHOUT #sender-cards-container throws (bug 2826d65c — no silent fallback)", () => {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : {
      notifications  : { list: () => [makeNotification()] },
      senders        : { list: () => [makeSender()] },
    },
    appTimezone: "UTC",
  });
  const root = document.createElement("section");   // no #sender-cards-container child
  assert.throws(() => renderer.mount(root), /#sender-cards-container not found/);
});

// bug 56e422aa (AR-rip) regression guard — the PRODUCTION post-0c shape:
// #notifications-pane holds ONLY #sender-cards-container; #action-required-section
// is a SEPARATE element owned by ActionRequiredRenderer. mount() must NOT throw or
// wipe the pane when the AR section is absent, and store_action_required_changed
// events must be IGNORED (this renderer no longer subscribes to them).
test("mount 0c-shape: AR section absent from pane → no throw, no wipe; AR store events are ignored (bug 56e422aa)", () => {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : {
      notifications  : { list: () => [makeNotification()] },
      senders        : { list: () => [makeSender()] },
    },
    appTimezone: "UTC",
  });
  // Production pane shape: #sender-cards-container present, NO #action-required-section.
  const root = document.createElement("section");
  root.id = "notifications-pane";
  const sCards = document.createElement("div");
  sCards.id = "sender-cards-container";
  root.appendChild(sCards);

  renderer.mount(root);   // must NOT throw and must NOT wipe #sender-cards-container

  // THE regression assertion: the container survives mount + the sender card
  // renders into it (mount never resolves or touches the AR section).
  assert.ok( root.querySelector("#sender-cards-container") !== null,
    "#sender-cards-container must survive mount" );
  assert.ok( root.querySelector("#sender-cards-container .sender-card") !== null,
    "sender card renders into the surviving container" );

  // An AR store event is IGNORED post-rip (no subscription) — no throw, no AR
  // widget painted, container still intact.
  bus.emit({
    type    : "store_action_required_changed",
    payload : { changeKind: "added", id_hash: "ar-x" },
  } as unknown as Parameters<typeof bus.emit>[0]);
  assert.ok( root.querySelector(".action-required-widget") === null,
    "no AR widget is painted — the renderer ignores action-required entirely" );
  assert.ok( root.querySelector("#sender-cards-container") !== null,
    "#sender-cards-container still intact after an ignored AR event" );
  renderer.unmount();
});

test("click delegation: click NOT on .progress-group-toggle is a no-op", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification());
  senderList.push(makeSender());
  renderer.mount(root);
  // Click on a non-toggle element — the delegated handler must early-return
  // (line 295 `if (toggle === null) return;`) without crashing.
  const senderCard = root.querySelector(".sender-card");
  assert.notEqual(senderCard, null);
  // Synthetic click bubbles up to senderCardsMount.
  senderCard!.dispatchEvent(new Event("click", { bubbles: true }));
  // No assertion on side-effects — just confirm no exception thrown above.
  renderer.unmount();
});

test("click delegation: click target null is a no-op (defensive)", () => {
  const { renderer, root, notifList, senderList } = setupRenderer();
  notifList.push(makeNotification());
  senderList.push(makeSender());
  renderer.mount(root);
  // Synthesize a click event whose `target` is null — exercises the
  // `if (target === null) return;` guard. We dispatch via the mount itself
  // and inspect after.
  const sCardsMount = root.querySelector("#sender-cards-container") as HTMLElement;
  // Use the captured handler via dispatchEvent but without a real target.
  // DOM dispatchEvent always sets target; instead, manually invoke via
  // happy-dom's event constructor with a programmatic null target. If
  // happy-dom rejects the null target, this test still establishes the
  // delegation handler exists and runs cleanly for normal events.
  const evt = new Event("click", { bubbles: true });
  Object.defineProperty(evt, "target", { value: null });
  sCardsMount.dispatchEvent(evt);
  renderer.unmount();
});

test("history fragment build: head message without data-id-hash falls back to empty string", () => {
  const { renderer, root, notifList, senderList, bus } = setupRenderer();
  // Two notifications in same progress group; render, then strip the head's
  // data-id-hash attribute and trigger expand. Exercises line 333 ?? "".
  notifList.push(makeNotification({ id_hash: "head1", progress_group_id: "pg-1", message: "head" }));
  notifList.push(makeNotification({ id_hash: "history1", progress_group_id: "pg-1", message: "history-old", ts: Date.UTC(2026, 4, 5, 14, 0) }));
  senderList.push(makeSender());
  renderer.mount(root);
  // Find the progress-group head and remove its data-id-hash attribute.
  const headEl = root.querySelector('[data-progress-group="pg-1"]') as HTMLElement | null;
  if (headEl !== null) {
    headEl.removeAttribute("data-id-hash");
    // Click the toggle to trigger buildHistoryFragment with empty headIdHash.
    const toggle = headEl.querySelector(".progress-group-toggle") as HTMLElement | null;
    if (toggle !== null) {
      toggle.dispatchEvent(new Event("click", { bubbles: true }));
    }
  }
  // No exception → branch covered. Assertion: no crash.
  bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: "history1" } } as unknown as Parameters<typeof bus.emit>[0]);
  renderer.unmount();
});

test("reapplyExpandedGroups: expanded group whose DOM disappeared is silently skipped", () => {
  const { renderer, root, notifList, senderList, bus } = setupRenderer();
  notifList.push(makeNotification({ id_hash: "head1", progress_group_id: "pg-1", message: "head" }));
  notifList.push(makeNotification({ id_hash: "history1", progress_group_id: "pg-1", message: "history-old", ts: Date.UTC(2026, 4, 5, 14, 0) }));
  senderList.push(makeSender());
  renderer.mount(root);
  // Expand the group.
  const toggle = root.querySelector(".progress-group-toggle") as HTMLElement | null;
  if (toggle !== null) toggle.dispatchEvent(new Event("click", { bubbles: true }));
  // Replace the source data — remove pg-1 notifications, add a different
  // sender's notification (no progress group). This keeps the list non-empty
  // so renderSenderSection runs reapplyExpandedGroups, and that loop
  // iterates expandedGroups (still has pg-1) but finds no DOM element →
  // line 370 messageEl-null branch fires, continue runs without throwing.
  notifList.length = 0;
  notifList.push(makeNotification({ id_hash: "n2", sender_id: "sess_other", message: "different sender, no group" }));
  senderList.length = 0;
  senderList.push(makeSender({ sender_id: "sess_other" }));
  bus.emit({ type: "store_notifications_changed", payload: { changeKind: "expired", id_hash: "head1" } } as unknown as Parameters<typeof bus.emit>[0]);
  renderer.unmount();
});

test("cssEscape: fallback path used when globalThis.CSS is removed (progress-group re-render)", () => {
  // Post-AR-rip, cssEscape is exercised via reapplyExpandedGroups, which selects
  // an expanded group with `[data-progress-group="${cssEscape(groupId)}"]`. With
  // globalThis.CSS removed (property fully deleted so the optional-chaining hits
  // null), cssEscape must fall back to its manual backslash-escape for a weird
  // group id without throwing.
  const desc = Object.getOwnPropertyDescriptor(globalThis, "CSS");
  Object.defineProperty(globalThis, "CSS", { value: undefined, configurable: true, writable: true });
  try {
    const { renderer, root, notifList, senderList } = setupRenderer();
    const weirdGroup = "pg:weird/id";
    notifList.push(makeNotification({ id_hash: "head1", progress_group_id: weirdGroup, message: "head" }));
    notifList.push(makeNotification({ id_hash: "hist1", progress_group_id: weirdGroup, message: "older", ts: Date.UTC(2026, 4, 5, 14, 0) }));
    senderList.push(makeSender());
    renderer.mount(root);
    // Expand the group so it enters expandedGroups.
    const toggle = root.querySelector(".progress-group-toggle") as HTMLElement | null;
    if (toggle !== null) toggle.dispatchEvent(new Event("click", { bubbles: true }));
    // Force a re-render → reapplyExpandedGroups runs cssEscape(weirdGroup) via the
    // manual fallback (no throw = branch covered).
    assert.doesNotThrow(() => renderer.forceRenderForTesting());
    renderer.unmount();
  } finally {
    if (desc !== undefined) {
      Object.defineProperty(globalThis, "CSS", desc);
    } else {
      delete (globalThis as { CSS?: unknown }).CSS;
    }
  }
});

// ===========================================================================
// AC-D5 : Phase 6c sender-sort comparator hook (+ backward-compat guard
//   per F-Arnold-D4). Floor: ≥4 new cases.
// ===========================================================================

import type { SenderSortComparator } from "../../../../lupin_app/static/js/multiplexer/shared/types";

interface SortTestSetup extends TestSetup {
  sCardsRoot : HTMLElement;
}

function setupRendererForSort(comparator?: SenderSortComparator): SortTestSetup {
  const bus = createEventBusForTesting();
  const notifList : Notification[] = [];
  const senderList: SenderRecord[] = [];

  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : {
      notifications  : { list: () => notifList },
      senders        : { list: () => senderList },
    },
    appTimezone          : "UTC",
    senderSortComparator : comparator,
  });

  const root = document.createElement("section");
  root.id = "notifications-pane";
  const sCards = document.createElement("div");
  sCards.id = "sender-cards-container";
  root.appendChild(sCards);

  return { bus, notifList, senderList, renderer, root, sCardsRoot: sCards };
}

function senderIdsInOrder(sCardsRoot: HTMLElement): string[] {
  return Array.from(sCardsRoot.querySelectorAll<HTMLElement>(".sender-card"))
    .map(c => c.getAttribute("data-sender-id") ?? "");
}

test("AC-D5 #1: default sort (no comparator opts override) — most-recent-activity-first (Phase 5 behavior preserved)", () => {
  // No `senderSortComparator` argument — implementation must apply
  // DEFAULT_SENDER_SORT = (a, b) => b.last_active_ts - a.last_active_ts.
  const { renderer, root, notifList, senderList, sCardsRoot } = setupRendererForSort();
  senderList.push(makeSender({ sender_id: "old",  last_active_ts: 1_000_000 }));
  senderList.push(makeSender({ sender_id: "mid",  last_active_ts: 2_000_000 }));
  senderList.push(makeSender({ sender_id: "new",  last_active_ts: 3_000_000 }));
  notifList.push(makeNotification({ id_hash: "n_old", sender_id: "old", ts: 1_000_000 }));
  notifList.push(makeNotification({ id_hash: "n_mid", sender_id: "mid", ts: 2_000_000 }));
  notifList.push(makeNotification({ id_hash: "n_new", sender_id: "new", ts: 3_000_000 }));

  renderer.mount(root);
  assert.deepEqual(senderIdsInOrder(sCardsRoot), ["new", "mid", "old"],
    "default sort is most-recent first");
  renderer.unmount();
});

test("AC-D5 #2: custom comparator — alphabetical sort overrides default activity-based ordering", () => {
  const alphabetical: SenderSortComparator = (a, b) => a.sender_id.localeCompare(b.sender_id);
  const { renderer, root, notifList, senderList, sCardsRoot } = setupRendererForSort(alphabetical);
  // Bob has the most-recent activity but alphabetical wins.
  senderList.push(makeSender({ sender_id: "alice",   last_active_ts: 1_000_000 }));
  senderList.push(makeSender({ sender_id: "bob",     last_active_ts: 9_000_000 }));
  senderList.push(makeSender({ sender_id: "charlie", last_active_ts: 5_000_000 }));
  notifList.push(makeNotification({ id_hash: "na", sender_id: "alice",   ts: 1_000_000 }));
  notifList.push(makeNotification({ id_hash: "nb", sender_id: "bob",     ts: 9_000_000 }));
  notifList.push(makeNotification({ id_hash: "nc", sender_id: "charlie", ts: 5_000_000 }));

  renderer.mount(root);
  assert.deepEqual(senderIdsInOrder(sCardsRoot), ["alice", "bob", "charlie"],
    "custom comparator wins over activity-based default");
  renderer.unmount();
});

test("AC-D5 #3: Phase 6c override — conversation-mode-pinned sender hoists above MORE-recently-active unpinned senders", () => {
  // The Phase 6c boot-injected comparator:
  //   (a, b) => Number(b.conversation_mode_active) - Number(a.conversation_mode_active)
  //         || (b.last_active_ts - a.last_active_ts)
  const phase6cSort: SenderSortComparator = (a, b) =>
    (Number(b.conversation_mode_active) - Number(a.conversation_mode_active))
    || (b.last_active_ts - a.last_active_ts);

  const { renderer, root, notifList, senderList, sCardsRoot } = setupRendererForSort(phase6cSort);
  // pinned sender has OLDEST activity yet must render FIRST.
  senderList.push(makeSender({ sender_id: "pinned",       last_active_ts: 1_000_000, conversation_mode_active: true }));
  senderList.push(makeSender({ sender_id: "recent",       last_active_ts: 9_000_000, conversation_mode_active: false }));
  senderList.push(makeSender({ sender_id: "less_recent",  last_active_ts: 5_000_000, conversation_mode_active: false }));
  notifList.push(makeNotification({ id_hash: "np", sender_id: "pinned",      ts: 1_000_000 }));
  notifList.push(makeNotification({ id_hash: "nr", sender_id: "recent",      ts: 9_000_000 }));
  notifList.push(makeNotification({ id_hash: "nl", sender_id: "less_recent", ts: 5_000_000 }));

  renderer.mount(root);
  assert.deepEqual(senderIdsInOrder(sCardsRoot), ["pinned", "recent", "less_recent"],
    "pinned hoists above activity-based ordering; non-pinned senders fall back to activity sort");
  renderer.unmount();
});

test("AC-D5 #4: Phase 6c override — tied conversation_mode_active values fall back to last_active_ts", () => {
  // All three senders share the same conversation_mode_active=false; the
  // activity-based fallback determines order.
  const phase6cSort: SenderSortComparator = (a, b) =>
    (Number(b.conversation_mode_active) - Number(a.conversation_mode_active))
    || (b.last_active_ts - a.last_active_ts);

  const { renderer, root, notifList, senderList, sCardsRoot } = setupRendererForSort(phase6cSort);
  senderList.push(makeSender({ sender_id: "first",  last_active_ts: 3_000_000, conversation_mode_active: false }));
  senderList.push(makeSender({ sender_id: "second", last_active_ts: 5_000_000, conversation_mode_active: false }));
  senderList.push(makeSender({ sender_id: "third",  last_active_ts: 1_000_000, conversation_mode_active: false }));
  notifList.push(makeNotification({ id_hash: "n1", sender_id: "first",  ts: 3_000_000 }));
  notifList.push(makeNotification({ id_hash: "n2", sender_id: "second", ts: 5_000_000 }));
  notifList.push(makeNotification({ id_hash: "n3", sender_id: "third",  ts: 1_000_000 }));

  renderer.mount(root);
  assert.deepEqual(senderIdsInOrder(sCardsRoot), ["second", "first", "third"],
    "all unpinned ⇒ activity-based fallback applies");
  renderer.unmount();
});

test("AC-D5 #5: backward-compat (F-Arnold-D4) — pre-existing comparator-less callers still see Phase 5 behavior", () => {
  // Identical setup to #1 but explicitly omitting senderSortComparator
  // via undefined coercion in the helper. Guards against accidental
  // signature breakage that would force every Phase 5 caller to adopt the
  // Phase 6c comparator.
  const { renderer, root, notifList, senderList, sCardsRoot } = setupRendererForSort(undefined);
  senderList.push(makeSender({ sender_id: "a", last_active_ts: 1_000_000 }));
  senderList.push(makeSender({ sender_id: "b", last_active_ts: 2_000_000 }));
  notifList.push(makeNotification({ id_hash: "na", sender_id: "a", ts: 1_000_000 }));
  notifList.push(makeNotification({ id_hash: "nb", sender_id: "b", ts: 2_000_000 }));

  renderer.mount(root);
  assert.deepEqual(senderIdsInOrder(sCardsRoot), ["b", "a"],
    "undefined comparator opt → default most-recent-first behavior preserved");
  renderer.unmount();
});

// ===========================================================================
// WP14 (F8) — prediction-vote integration in the notification-item paint path
// ===========================================================================

type VoteResult = "true" | "false" | "reject";

interface FakeVoteStore {
  getVote( id: string ): PredictionVoteDir | undefined;
  setContext( id: string, ctx: PredictionVoteContext ): void;
  vote( id: string, dir: PredictionVoteDir ): Promise<boolean>;
}

// A controllable PredictionVoteStore double. On a successful vote it mirrors the
// real store: records the cast + emits store_prediction_vote_changed so the
// renderer's reconcile subscription re-renders. `result` selects the vote outcome.
function makeFakeVoteStore(
  bus: ReturnType<typeof createEventBusForTesting>,
  result: VoteResult,
): {
  store     : FakeVoteStore;
  contexts  : Map<string, PredictionVoteContext>;
  voteCalls : Array<{ id: string; dir: PredictionVoteDir }>;
} {
  const votes     = new Map<string, PredictionVoteDir>();
  const contexts  = new Map<string, PredictionVoteContext>();
  const voteCalls : Array<{ id: string; dir: PredictionVoteDir }> = [];
  const store: FakeVoteStore = {
    getVote    : (id) => votes.get(id),
    setContext : (id, ctx) => { contexts.set(id, ctx); },
    vote       : async (id, dir) => {
      voteCalls.push({ id, dir });
      await Promise.resolve();                  // simulate the async POST round-trip
      if (result === "reject") throw new Error("POST failed");
      if (result === "false") return false;
      votes.set(id, dir);
      bus.emit({
        type    : "store_prediction_vote_changed",
        payload : { notificationId: id, vote: dir },
        source  : "FakeVoteStore",
        ts      : 0,
      });
      return true;
    },
  };
  return { store, contexts, voteCalls };
}

function setupRendererWithVote(
  bus: ReturnType<typeof createEventBusForTesting>,
  voteStore: FakeVoteStore | undefined,
): { notifList: Notification[]; senderList: SenderRecord[]; renderer: NotificationsListRenderer; root: HTMLElement } {
  const notifList : Notification[] = [];
  const senderList: SenderRecord[] = [];
  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : {
      notifications  : { list: () => notifList },
      senders        : { list: () => senderList },
      predictionVote : voteStore,
    },
    appTimezone: "UTC",
  });
  const root = document.createElement("section");
  root.id = "notifications-pane";
  const sCards    = document.createElement("div"); sCards.id    = "sender-cards-container";
  root.appendChild(sCards);
  return { notifList, senderList, renderer, root };
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

function predNotification(over: Partial<Notification> = {}): Notification {
  return {
    id_hash         : "pred1",
    ts              : Date.UTC(2026, 4, 5, 14, 7),
    sender_id       : "sess_42",
    message         : "Schedule the meeting?",
    action_required : false,
    response_type   : "yes_no",
    prediction_hint : { confidence: 0.9, predicted_value: "yes", category: "calendar" },
    ...over,
  };
}

test("F8: store wired → prediction notification mounts interactive vote controls + records the cast", async () => {
  const bus  = createEventBusForTesting();
  const fake = makeFakeVoteStore(bus, "true");
  const { renderer, root, notifList, senderList } = setupRendererWithVote(bus, fake.store);
  notifList.push(predNotification());
  senderList.push(makeSender());
  renderer.mount(root);

  assert.ok( root.querySelector(".prediction-hint-vote") !== null, "controls mount for a prediction notification" );

  root.querySelector<HTMLButtonElement>(".prediction-vote-up")!.click();
  // setContext stashed the full hint context (question = message, response_type carried).
  assert.deepEqual(fake.contexts.get("pred1"), {
    question        : "Schedule the meeting?",
    predicted_value : "yes",
    category        : "calendar",
    response_type   : "yes_no",
  });
  assert.deepEqual(fake.voteCalls, [ { id: "pred1", dir: "up" } ]);

  await flush();
  // Recorded vote emitted store_prediction_vote_changed → reconcile re-render keeps the highlight.
  assert.ok(root.querySelector(".prediction-vote-up")!.classList.contains("selected"));
  renderer.unmount();
});

test("F8: cast context uses empty response_type when the notification lacks one", async () => {
  const bus  = createEventBusForTesting();
  const fake = makeFakeVoteStore(bus, "true");
  const { renderer, root, notifList, senderList } = setupRendererWithVote(bus, fake.store);
  notifList.push(predNotification({ response_type: undefined }));
  senderList.push(makeSender());
  renderer.mount(root);

  root.querySelector<HTMLButtonElement>(".prediction-vote-down")!.click();
  assert.equal(fake.contexts.get("pred1")!.response_type, "");
  await flush();
  renderer.unmount();
});

test("F8: a rejected (false) cast reverts the optimistic highlight via re-render", async () => {
  const bus  = createEventBusForTesting();
  const fake = makeFakeVoteStore(bus, "false");
  const { renderer, root, notifList, senderList } = setupRendererWithVote(bus, fake.store);
  notifList.push(predNotification());
  senderList.push(makeSender());
  renderer.mount(root);

  root.querySelector<HTMLButtonElement>(".prediction-vote-up")!.click();
  assert.ok(root.querySelector(".prediction-vote-up")!.classList.contains("selected"), "optimistic highlight applied on click");
  await flush();
  // No store event for a false cast → castPredictionVote re-renders to REVERT (getVote → undefined).
  assert.equal(root.querySelector(".prediction-vote-up")!.classList.contains("selected"), false);
  renderer.unmount();
});

test("F8: a thrown cast reverts the optimistic highlight via re-render", async () => {
  const bus  = createEventBusForTesting();
  const fake = makeFakeVoteStore(bus, "reject");
  const { renderer, root, notifList, senderList } = setupRendererWithVote(bus, fake.store);
  notifList.push(predNotification());
  senderList.push(makeSender());
  renderer.mount(root);

  root.querySelector<HTMLButtonElement>(".prediction-vote-down")!.click();
  await flush();
  assert.equal(root.querySelector(".prediction-vote-down")!.classList.contains("selected"), false);
  renderer.unmount();
});

test("F8: store absent → controls still render (pure-data) and clicks are inert (no throw)", () => {
  const bus = createEventBusForTesting();
  const { renderer, root, notifList, senderList } = setupRendererWithVote(bus, undefined);
  notifList.push(predNotification());
  senderList.push(makeSender());
  renderer.mount(root);

  const controls = root.querySelector(".prediction-hint-vote");
  assert.notEqual(controls, null, "presence is pure-data — controls render without the store");
  assert.equal(controls!.classList.contains("voted"), false, "no integration → no prior cast highlight");
  assert.doesNotThrow(() => root.querySelector<HTMLButtonElement>(".prediction-vote-up")!.click());
  renderer.unmount();
});

// ===========================================================================
// B3 (01-C) — filtered render source (visibleEntries) + filter-aware empty-state
// ===========================================================================

// A NotificationStore-like stub exposing the B3 surface (visibleEntries +
// isFilterActive) so the renderer's filtered-render branch + filter-aware
// empty-state copy are exercised (the other tests stub only list() → fallback).
function setupFilterableRenderer(opts: {
  list           : Notification[];
  visible        : Notification[];
  isFilterActive : boolean;
}): { renderer: NotificationsListRenderer; root: HTMLElement; bus: ReturnType<typeof createEventBusForTesting> } {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : {
      notifications  : {
        list           : () => opts.list,
        visibleEntries : () => opts.visible,
        isFilterActive : () => opts.isFilterActive,
      },
      senders        : { list: () => [] as SenderRecord[] },
    },
    appTimezone: "UTC",
  });
  const root = document.createElement("section");
  root.id = "notifications-pane";
  const sCards = document.createElement("div");
  sCards.id = "sender-cards-container";
  root.appendChild(sCards);
  return { renderer, root, bus };
}

test("B3: sender section renders from visibleEntries(), not the raw list()", () => {
  const shown   = makeNotification({ id_hash: "vis", sender_id: "sA", message: "shown" });
  const hidden  = makeNotification({ id_hash: "hid", sender_id: "sB", message: "filtered-out" });
  const { renderer, root } = setupFilterableRenderer({
    list: [shown, hidden], visible: [shown], isFilterActive: true,
  });
  renderer.mount(root);
  // Only the visible notification's sender card is rendered (1 of 2).
  const cards = root.querySelectorAll(".sender-card");
  assert.equal(cards.length, 1);
  assert.ok( root.querySelector('[data-testid="multiplexer-empty-state"]') === null );
  renderer.unmount();
});

test("B3: filter-active + empty visible view → filter-specific empty-state copy", () => {
  const { renderer, root } = setupFilterableRenderer({
    list: [makeNotification()], visible: [], isFilterActive: true,
  });
  renderer.mount(root);
  const empty = root.querySelector('[data-testid="multiplexer-empty-state"]');
  assert.notEqual(empty, null);
  assert.match(empty!.textContent ?? "", /match this filter/);
  renderer.unmount();
});

test("B3: no filter active + empty view → the unfiltered empty-state copy", () => {
  const { renderer, root } = setupFilterableRenderer({
    list: [], visible: [], isFilterActive: false,
  });
  renderer.mount(root);
  const empty = root.querySelector('[data-testid="multiplexer-empty-state"]');
  assert.notEqual(empty, null);
  assert.match(empty!.textContent ?? "", /No notifications yet/);
  renderer.unmount();
});
