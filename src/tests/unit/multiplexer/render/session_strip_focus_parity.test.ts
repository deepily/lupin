// Row d04ff119 — multiplexer focus mode matches legacy: the unread badge on hidden
// sessions, and focus + hide-inactive persisted under legacy's keys.
// (The third item, a click on the focused icon doing nothing, is in
// session_strip_renderer.test.ts beside the other click tests.)
//
// Legacy references, notifications.js at 36a9cad8:
//   _markStripIconActivity :16310 · skip rules :18866-18881 · _enterFocusMode :16444
//   _exitFocusMode :16519 · _maybeReapplyPersistedFocus :16719 · keys :214-215
//
// The browser-to-browser round trip (legacy's real save → this client's restore,
// and back) is session_strip_focus_cross_client.test.ts.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSessionStripRenderer,
  FOCUS_STATE_KEY,
  HIDE_INACTIVE_KEY,
} from "../../../../lupin_app/static/js/multiplexer/render/SessionStripRenderer";
import type {
  Notification,
  StripSession,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  document.body.replaceChildren();
});

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

class FakeStorage {
  readonly map = new Map<string, string>();
  writes = 0;
  getItem(key: string): string | null { return this.map.get(key) ?? null; }
  setItem(key: string, value: string): void { this.writes++; this.map.set(key, value); }
}

function session(id: string, assignedAt: number, over: Partial<StripSession> = {}): StripSession {
  return {
    sender_id     : id,
    voice_persona : { name: id, voice_id: "v", icon: "🙂", color: "#81D4FA", borrowed: false },
    assigned_at   : assignedAt,
    active        : true,
    ...over,
  };
}

interface Harness {
  bus      : ReturnType<typeof createEventBusForTesting>;
  sessions : StripSession[];
  notifs   : Notification[];
  storage  : FakeStorage;
  icon     : (id: string) => HTMLElement | null;
  toggle   : HTMLElement;
  hide     : HTMLElement;
  unmount  : () => void;
  click    : (id: string) => void;
  arrive   : (id: string, over?: Partial<Notification>) => void;
  strip    : (change: "added" | "removed" | "updated", id?: string) => void;
}

let serial = 0;

function setup(opts: { sessions?: StripSession[]; storage?: FakeStorage; notifications?: boolean } = {}): Harness {
  const bus      = createEventBusForTesting();
  const sessions = opts.sessions ?? [ session("a", 1000), session("b", 2000), session("c", 3000) ];
  const notifs   : Notification[] = [];
  const storage  = opts.storage ?? new FakeStorage();

  const root = document.createElement("main");
  root.innerHTML = `
    <div id="cc-session-strip"><div id="cc-strip-icons"></div>
      <button id="cc-strip-toggle"></button><button id="cc-hide-inactive-toggle"></button></div>`;
  document.body.appendChild(root);

  const renderer = createSessionStripRenderer({
    eventBus : bus,
    stores   : opts.notifications === false
      ? { strip: { list: () => sessions } }
      : { strip: { list: () => sessions }, notifications: { list: () => notifs } },
    storage  : storage,
  });
  renderer.mount(root);

  const icon = (id: string) => root.querySelector<HTMLElement>(`.cc-strip-icon[data-sender-id="${id}"]`);
  return {
    bus, sessions, notifs, storage, icon,
    toggle  : root.querySelector<HTMLElement>("#cc-strip-toggle")!,
    hide    : root.querySelector<HTMLElement>("#cc-hide-inactive-toggle")!,
    unmount : () => renderer.unmount(),
    click   : (id) => { icon(id)!.dispatchEvent(new Event("click", { bubbles: true })); },
    arrive  : (id, over = {}) => {
      const idHash = `n${serial++}`;
      notifs.push({ id_hash: idHash, ts: 0, sender_id: id, message: "m", action_required: false, ...over });
      bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: idHash }, source: "test", ts: 0 });
    },
    strip   : (changeKind, id) => {
      bus.emit({ type: "store_session_strip_changed", payload: { changeKind, sender_id: id }, source: "test", ts: 0 });
    },
  };
}

const badge = (h: Harness, id: string): [ string | null, string | null ] =>
  [ h.icon(id)!.getAttribute("data-unread"), h.icon(id)!.getAttribute("data-unread-count") ];

// ===========================================================================
// 1. Unread badge
// ===========================================================================

test("focus on: each message from a hidden session counts on its icon, and the pulse restarts every time", () => {
  const h = setup();
  h.click("a");
  const icon = h.icon("b")!;
  const removals: number[] = [];
  const realRemove = icon.removeAttribute.bind(icon);
  icon.removeAttribute = (name: string) => { if (name === "data-unread") removals.push(1); realRemove(name); };

  h.arrive("b");
  assert.deepEqual(badge(h, "b"), [ "true", "1" ]);
  h.arrive("b");
  assert.deepEqual(badge(h, "b"), [ "true", "2" ]);
  assert.equal(removals.length, 2, "the pulse was not restarted on each message");
  assert.deepEqual(badge(h, "c"), [ null, null ], "a session that sent nothing got a badge");
});

test("no badge: from the focused session, with focus off, or with no notification store wired", () => {
  const h = setup();
  h.arrive("b");
  assert.deepEqual(badge(h, "b"), [ null, null ], "focus off counted");
  h.click("a");
  h.arrive("a");
  assert.deepEqual(badge(h, "a"), [ null, null ], "the focused session counted its own message");

  const bare = setup({ notifications: false });
  bare.click("a");
  bare.arrive("b");
  assert.deepEqual(badge(bare, "b"), [ null, null ]);
});

test("the legacy skip rules: progress-group rows, outgoing replies and action-required rows do not count", () => {
  const h = setup();
  h.click("a");
  h.arrive("b", { progress_group_id: "pg-1" });
  h.arrive("b", { direction: "outgoing" });
  h.arrive("b", { action_required: true });
  assert.deepEqual(badge(h, "b"), [ null, null ]);
  h.arrive("b", { progress_group_id: "" });   // an empty group id is no group
  assert.deepEqual(badge(h, "b"), [ "true", "1" ]);
});

test("only 'added' with an id counts, and a row the store does not hold or a sender with no icon counts nothing", () => {
  const h = setup();
  h.click("a");
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "updated", id_hash: "x" }, source: "test", ts: 0 });
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added" }, source: "test", ts: 0 });
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: "not-in-store" }, source: "test", ts: 0 });
  h.arrive("stranger");
  for (const id of [ "b", "c" ]) assert.deepEqual(badge(h, id), [ null, null ]);
});

test("a managed worker pulses without a number", () => {
  const h = setup({ sessions: [ session("a", 1000), session("w", 2000, { manager_persona: { name: "María", icon: "🌸", color: "#F06292" } as StripSession["manager_persona"] }) ] });
  h.click("a");
  h.arrive("w");
  h.arrive("w");
  assert.deepEqual(badge(h, "w"), [ "true", null ]);
});

test("focusing a session clears its badge only; exiting focus clears them all", () => {
  const h = setup();
  h.click("a");
  h.arrive("b");
  h.arrive("c");
  h.click("b");
  assert.deepEqual(badge(h, "b"), [ null, null ]);
  assert.deepEqual(badge(h, "c"), [ "true", "1" ]);
  h.arrive("a");
  h.toggle.dispatchEvent(new Event("click", { bubbles: true }));
  for (const id of [ "a", "b", "c" ]) assert.deepEqual(badge(h, id), [ null, null ], `${id} kept a badge after exit`);
});

test("a count survives an icon being rebuilt, and a removed session drops its count", () => {
  const h = setup();
  h.click("a");
  h.arrive("b");
  h.arrive("b");
  h.icon("b")!.remove();         // the icon node goes; a reconcile builds a fresh one
  h.strip("updated", "b");
  assert.deepEqual(badge(h, "b"), [ "true", "2" ]);

  h.sessions.splice(1, 1);
  h.strip("removed", "b");
  h.sessions.push(session("b", 2000));
  h.strip("added", "b");
  assert.deepEqual(badge(h, "b"), [ null, null ], "a session that left and came back kept its old count");
});

// ===========================================================================
// 3. Persistence under legacy's keys
// ===========================================================================

test("focus and hide-inactive are written in legacy's shape on every change", () => {
  const h = setup();
  h.click("b");
  assert.equal(h.storage.getItem(FOCUS_STATE_KEY), '{"enabled":true,"focused_sender_id":"b"}');
  h.click("c");
  assert.equal(h.storage.getItem(FOCUS_STATE_KEY), '{"enabled":true,"focused_sender_id":"c"}');
  h.toggle.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(h.storage.getItem(FOCUS_STATE_KEY), '{"enabled":false,"focused_sender_id":null}');
  h.hide.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(h.storage.getItem(HIDE_INACTIVE_KEY), "true");
  h.hide.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(h.storage.getItem(HIDE_INACTIVE_KEY), "false");
});

test("a remount restores focus and hide-inactive from storage", () => {
  const storage = new FakeStorage();
  storage.map.set(FOCUS_STATE_KEY, '{"enabled":true,"focused_sender_id":"b"}');
  storage.map.set(HIDE_INACTIVE_KEY, "true");
  const h = setup({ storage });

  assert.equal(h.toggle.getAttribute("data-focus-active"), "true");
  assert.equal(h.icon("b")!.getAttribute("data-focused"), "true");
  assert.equal(h.hide.getAttribute("data-hide-inactive"), "true");
  assert.equal(storage.writes, 0, "restoring wrote to storage");
});

test("a saved focus whose session is not in the strip yet is applied when that session arrives", () => {
  const storage = new FakeStorage();
  storage.map.set(FOCUS_STATE_KEY, '{"enabled":true,"focused_sender_id":"late"}');
  const h = setup({ storage });
  assert.equal(h.toggle.getAttribute("data-focus-active"), "false", "focus applied before its session existed");

  h.sessions.push(session("late", 9000));
  h.strip("added", "late");

  assert.equal(h.toggle.getAttribute("data-focus-active"), "true");
  assert.equal(h.icon("late")!.getAttribute("data-focused"), "true");
});

test("a focus choice made before the saved session arrives wins over the saved one", () => {
  const storage = new FakeStorage();
  storage.map.set(FOCUS_STATE_KEY, '{"enabled":true,"focused_sender_id":"late"}');
  const h = setup({ storage });
  h.click("a");
  h.toggle.dispatchEvent(new Event("click", { bubbles: true }));   // and out again

  h.sessions.push(session("late", 9000));
  h.strip("added", "late");
  assert.equal(h.toggle.getAttribute("data-focus-active"), "false", "the stale saved focus overrode the user's choice");
});

test("the focused session being reaped exits focus without writing, and its return restores focus", () => {
  const h = setup();
  h.click("b");
  const writes = h.storage.writes;

  h.sessions.splice(1, 1);
  h.strip("removed", "b");
  assert.equal(h.toggle.getAttribute("data-focus-active"), "false");
  assert.equal(h.storage.writes, writes, "an automatic exit overwrote the saved focus");
  assert.equal(h.storage.getItem(FOCUS_STATE_KEY), '{"enabled":true,"focused_sender_id":"b"}');

  h.sessions.push(session("b", 2000));
  h.strip("added", "b");
  assert.equal(h.icon("b")!.getAttribute("data-focused"), "true");
});

test("unreadable storage leaves the default state and never throws", () => {
  for (const raw of [ "{not json", "null", '"b"', '{"enabled":true}', '{"enabled":"yes","focused_sender_id":"b"}', '{"enabled":true,"focused_sender_id":""}' ]) {
    const storage = new FakeStorage();
    storage.map.set(FOCUS_STATE_KEY, raw);
    const h = setup({ storage });
    assert.equal(h.toggle.getAttribute("data-focus-active"), "false", `restored focus from ${raw}`);
    h.unmount();
  }
});

test("storage that throws on read and on write: the page still focuses, nothing throws", () => {
  const throwing = {
    getItem : (): string | null => { throw new Error("SecurityError"); },
    setItem : (): void => { throw new Error("QuotaExceededError"); },
  };
  const h = setup({ storage: throwing as unknown as FakeStorage });
  h.click("b");
  h.hide.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(h.icon("b")!.getAttribute("data-focused"), "true");
  assert.equal(h.hide.getAttribute("data-hide-inactive"), "true");
});

test("storage: null persists nothing and restores nothing", () => {
  const bus  = createEventBusForTesting();
  const root = document.createElement("main");
  root.innerHTML = `<div id="cc-session-strip"><div id="cc-strip-icons"></div><button id="cc-strip-toggle"></button><button id="cc-hide-inactive-toggle"></button></div>`;
  document.body.appendChild(root);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: { list: () => [ session("a", 1) ] } }, storage: null });
  r.mount(root);
  root.querySelector<HTMLElement>(".cc-strip-icon")!.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(root.querySelector("#cc-strip-toggle")!.getAttribute("data-focus-active"), "true");
  r.unmount();
});
