// Multiplexer parity P0 (2026-09-10) — the sender-card header controls, the
// per-date delete, and active-sender marking, in NotificationsListRenderer.
//
// Legacy behaviours ported (notifications.js): copySenderSessionId (S2a),
// generateSessionGist (S2b), editSessionName → showSessionNameEditModal (S2c),
// deleteSenderConversation (S2d), softDeleteByDate (S3), group.isActive (S4).
// Companion to notifications_list_renderer.test.ts and
// notifications_list_accordion_collapse.test.ts.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/sender_card_header_controls.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createNotificationsListRenderer,
  type NotificationsListRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render";
import { openSessionNameEditModal } from "../../../../lupin_app/static/js/multiplexer/render/sessionNameEditModal";
import type { Notification, SenderRecord } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});
afterEach(() => {
  document.body.replaceChildren();
});

const CC_ID    = "claude.code@lupin.deepily.ai#abe7d752";
const OTHER_ID = "claude.code@cosa.deepily.ai#0badf00d";
const EMAIL    = "rick@example.com";
const DAY1     = Date.UTC(2026, 8, 9, 14, 7);    // 2026-09-09
const DAY2     = Date.UTC(2026, 8, 10, 9, 30);   // 2026-09-10

function note(over: Partial<Notification> = {}): Notification {
  return { id_hash: "n1", ts: DAY2, sender_id: CC_ID, message: "hello", action_required: false, ...over };
}
function senderRec(over: Partial<SenderRecord> = {}): SenderRecord {
  return { sender_id: CC_ID, display_name: "Lupin", last_active_ts: DAY2, unread_count: 1, conversation_mode_active: false, ...over };
}

interface Deferred<T> { promise: Promise<T>; resolve: (v: T) => void; }
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

interface ApiCall { method: "POST" | "DELETE"; path: string; body?: unknown; }

interface HarnessOptions {
  withApi?        : boolean;                                   // default true
  email?          : string | null;                             // default EMAIL; null → getUserEmail omitted
  confirm?        : boolean;                                   // default true
  postReply?      : (path: string, body: unknown) => Promise<unknown>;
  deleteReply?    : (path: string) => Promise<unknown>;
  clipboardWrite? : (text: string) => Promise<void>;
}

interface Harness {
  bus      : ReturnType<typeof createEventBusForTesting>;
  notifs   : Notification[];
  senders  : SenderRecord[];
  renderer : NotificationsListRenderer;
  root     : HTMLElement;
  cards    : HTMLElement;
  calls    : ApiCall[];
  removed  : string[][];
  named    : Array<[string, string]>;
  confirms : string[];
  failures : string[];
  copied   : string[];
}

function setup(o: HarnessOptions = {}): Harness {
  const bus      = createEventBusForTesting();
  const notifs   : Notification[] = [];
  const senders  : SenderRecord[] = [];
  const calls    : ApiCall[] = [];
  const removed  : string[][] = [];
  const named    : Array<[string, string]> = [];
  const confirms : string[] = [];
  const failures : string[] = [];
  const copied   : string[] = [];
  const changed  = (type: string): void => bus.emit({ type, payload: { changeKind: "updated" }, source: "test", ts: 0 });

  const renderer = createNotificationsListRenderer({
    eventBus : bus,
    stores   : {
      // Fakes that behave like the real stores: mutate, then emit the change.
      notifications : {
        list             : () => notifs,
        removeByIdHashes : (ids) => {
          removed.push([ ...ids ]);
          const drop = new Set(ids);
          for (let i = notifs.length - 1; i >= 0; i--) {
            if (drop.has(notifs[i]!.id_hash)) notifs.splice(i, 1);
          }
          changed("store_notifications_changed");
        },
      },
      senders : {
        list           : () => senders,
        setSessionName : (id, name) => {
          named.push([ id, name ]);
          const rec = senders.find(s => s.sender_id === id);
          if (rec !== undefined) rec.session_name = name;
          changed("store_senders_changed");
        },
      },
    },
    appTimezone    : "UTC",
    api            : o.withApi === false ? undefined : {
      post<T>(path: string, body: unknown): Promise<T> {
        calls.push({ method: "POST", path, body });
        return (o.postReply ? o.postReply(path, body) : Promise.resolve({ gist: "Parity sweep" })) as Promise<T>;
      },
      delete<T>(path: string): Promise<T> {
        calls.push({ method: "DELETE", path });
        return (o.deleteReply ? o.deleteReply(path) : Promise.resolve({ ok: true })) as Promise<T>;
      },
    },
    getUserEmail   : o.email === null ? undefined : () => o.email ?? EMAIL,
    confirmFn      : (m) => { confirms.push(m); return o.confirm ?? true; },
    clipboardWrite : o.clipboardWrite ?? ((t) => { copied.push(t); return Promise.resolve(); }),
    reportFailure  : (m) => { failures.push(m); },
  });

  const root  = document.createElement("section");
  root.id     = "notifications-pane";
  const cards = document.createElement("div");
  cards.id    = "sender-cards-container";
  root.appendChild(cards);
  return { bus, notifs, senders, renderer, root, cards, calls, removed, named, confirms, failures, copied };
}

const flush = (): Promise<void> => new Promise<void>(r => setTimeout(r, 0));

function click(el: Element | null): void {
  assert.ok(el !== null, "click target exists");
  el.dispatchEvent(new Event("click", { bubbles: true }));
}
function key(el: Element, k: string): void {
  el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
}
function cardFor(h: Harness, senderId: string): HTMLElement | null {
  return h.cards.querySelector<HTMLElement>(`.sender-card[data-sender-id="${senderId}"]`);
}
function inCard(h: Harness, senderId: string, sel: string): HTMLElement | null {
  return cardFor(h, senderId)?.querySelector<HTMLElement>(sel) ?? null;
}
function renameModal(): HTMLElement | null {
  return document.getElementById("session-name-edit-modal");
}

// ===========================================================================
// S4 — exactly one active card: the most recently active sender
// ===========================================================================

test("S4: only the most recently active sender's card is active, and the mark moves when another sender becomes newer", () => {
  const h = setup();
  h.notifs.push(note({ id_hash: "a1" }), note({ id_hash: "b1", sender_id: OTHER_ID }));
  h.senders.push(senderRec({ last_active_ts: DAY1 }), senderRec({ sender_id: OTHER_ID, last_active_ts: DAY2 }));
  h.renderer.mount(h.root);

  const activeIds = (): Array<string | undefined> =>
    Array.from(h.cards.querySelectorAll<HTMLElement>(".sender-card-active")).map(c => c.dataset["senderId"]);
  assert.deepEqual(activeIds(), [ OTHER_ID ]);
  assert.equal(inCard(h, OTHER_ID, ".sender-active-indicator")!.textContent, "●");
  assert.equal(inCard(h, CC_ID, ".sender-active-indicator")!.textContent, "○");

  h.senders[0]!.last_active_ts = DAY2 + 60_000;
  h.bus.emit({ type: "store_senders_changed", payload: { changeKind: "updated" }, source: "test", ts: 0 });
  assert.deepEqual(activeIds(), [ CC_ID ]);
  assert.equal(inCard(h, OTHER_ID, ".sender-active-indicator")!.textContent, "○");
  h.renderer.unmount();
});

test("S2 header: a click on the persona badge fires no card control and does not collapse the card", async () => {
  const h = setup();
  h.notifs.push(note());
  h.senders.push(senderRec({ voice_persona: { name: "María", voice_id: "v1", icon: "🦋", color: "#aa3366", borrowed: false } }));
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-persona-badge .persona-badge-name"));
  await flush();

  assert.notEqual(cardFor(h, CC_ID)!.getAttribute("data-collapsed"), "true", "the badge click did not collapse the card");
  assert.deepEqual(h.confirms, []);
  assert.deepEqual(h.calls, []);
  assert.ok(renameModal() === null);
  h.renderer.unmount();
});

// ===========================================================================
// S3 — per-date × soft delete
// ===========================================================================

test("S3: the date × confirms, DELETEs that day for this sender and user, and drops only that day's rows", async () => {
  const h = setup();
  h.notifs.push(
    note({ id_hash: "d1a", ts: DAY1 }),
    note({ id_hash: "d1b", ts: DAY1 + 1000 }),
    note({ id_hash: "d2a", ts: DAY2 }),
    note({ id_hash: "x1",  ts: DAY1, sender_id: OTHER_ID }),
  );
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(inCard(h, CC_ID, '.date-accordion[data-date-key="2026-09-09"] .date-delete-btn'));
  await flush();

  assert.deepEqual(h.confirms, [ "Hide all notifications from 2026-09-09?" ]);
  assert.deepEqual(h.calls, [ {
    method : "DELETE",
    path   : `/api/notifications/date/${encodeURIComponent(CC_ID)}/${encodeURIComponent(EMAIL)}/2026-09-09`,
  } ]);
  assert.deepEqual(h.removed, [ [ "d1a", "d1b" ] ]);
  assert.ok(inCard(h, CC_ID, '.date-accordion[data-date-key="2026-09-09"]') === null, "that day's accordion is gone");
  assert.ok(inCard(h, CC_ID, '.date-accordion[data-date-key="2026-09-10"]') !== null, "the other day stays");
  assert.ok(inCard(h, OTHER_ID, '.date-accordion[data-date-key="2026-09-09"]') !== null, "another sender's same day stays");
  assert.deepEqual(h.failures, []);
  h.renderer.unmount();
});

test("S3: clicking the date × never toggles the date accordion's collapse", async () => {
  const h = setup({ confirm: false });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  const accordion = h.cards.querySelector(".date-accordion") as HTMLElement;
  click(accordion.querySelector(".date-delete-btn"));
  await flush();

  assert.equal(h.confirms.length, 1, "the click reached the delete handler");
  assert.equal(accordion.getAttribute("data-collapsed"), "false");
  assert.equal(accordion.querySelector(".date-toggle")!.textContent, "▼");
  h.renderer.unmount();
});

test("S3: declining the day-delete confirm sends nothing and removes nothing", async () => {
  const h = setup({ confirm: false });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".date-delete-btn"));
  await flush();

  assert.equal(h.confirms.length, 1);
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.removed, []);
  h.renderer.unmount();
});

test("S3: a failed day delete keeps the rows and reports the failure", async () => {
  const h = setup({ deleteReply: () => Promise.reject(new Error("HTTP 500")) });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".date-delete-btn"));
  await flush();

  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.removed, []);
  assert.ok(h.cards.querySelector(".date-accordion") !== null);
  assert.equal(h.failures.length, 1);
  assert.match(h.failures[0]!, /2026-09-10.*HTTP 500/);
  h.renderer.unmount();
});

test("S3: with no signed-in email the day delete sends nothing and reports why", async () => {
  const h = setup({ email: null });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".date-delete-btn"));
  await flush();

  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.removed, []);
  assert.equal(h.failures.length, 1);
  assert.match(h.failures[0]!, /no signed-in user email/);
  h.renderer.unmount();
});

test("S2b/S2d/S3: without an api client the ✨, × and date × controls ask nothing and send nothing", async () => {
  const h = setup({ withApi: false });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-gist-btn"));
  click(h.cards.querySelector(".sender-delete-btn"));
  click(h.cards.querySelector(".date-delete-btn"));
  await flush();

  assert.deepEqual(h.confirms, []);
  assert.deepEqual(h.removed, []);
  assert.deepEqual(h.named, []);
  assert.deepEqual(h.failures, []);
  assert.equal(h.cards.querySelector(".sender-gist-btn")!.textContent, "✨");
  h.renderer.unmount();
});

// ===========================================================================
// S2a — 📋 copy
// ===========================================================================

test("S2a: 📋 copies the session hex without '#', flashes ✅ for 1200 ms, and does not collapse the card", async (t) => {
  const h = setup();
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);
  t.mock.timers.enable({ apis: [ "setTimeout" ] });

  const btn = h.cards.querySelector(".sender-session-copy") as HTMLElement;
  click(btn);
  for (let i = 0; i < 5; i++) await Promise.resolve();

  assert.deepEqual(h.copied, [ "abe7d752" ]);
  assert.equal(btn.textContent, "✅");
  t.mock.timers.tick(1199);
  assert.equal(btn.textContent, "✅");
  t.mock.timers.tick(1);
  assert.equal(btn.textContent, "📋");
  assert.notEqual(cardFor(h, CC_ID)!.getAttribute("data-collapsed"), "true", "the copy click did not collapse the card");
  h.renderer.unmount();
});

test("S2a: a clipboard failure is reported and the button keeps its 📋", async () => {
  const h = setup({ clipboardWrite: () => Promise.reject(new Error("denied")) });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-session-copy"));
  await flush();

  assert.equal(h.failures.length, 1);
  assert.match(h.failures[0]!, /copy the session ID/);
  assert.equal(h.cards.querySelector(".sender-session-copy")!.textContent, "📋");
  h.renderer.unmount();
});

// ===========================================================================
// S2b — ✨ gist
// ===========================================================================

test("S2b: ✨ POSTs this sender's messages and abstracts, shows ⏳ while pending, then names the session", async () => {
  const reply = deferred<unknown>();
  const h = setup({ postReply: () => reply.promise });
  h.notifs.push(
    note({ id_hash: "g1", message: "first", abstract: "detail one" }),
    note({ id_hash: "g2", message: "second" }),
    note({ id_hash: "g3", message: "", abstract: "detail three" }),
    note({ id_hash: "o1", message: "not mine", abstract: "nope", sender_id: OTHER_ID }),
  );
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(inCard(h, CC_ID, ".sender-gist-btn"));
  const pending = inCard(h, CC_ID, ".sender-gist-btn") as HTMLButtonElement;
  assert.equal(pending.disabled, true);
  assert.ok(pending.classList.contains("working"));
  assert.equal(pending.textContent, "⏳");
  assert.deepEqual(h.calls, [ {
    method : "POST",
    path   : "/api/notifications/generate-gist",
    body   : { messages: [ "first", "second" ], abstracts: [ "detail one", "detail three" ] },
  } ]);

  reply.resolve({ gist: "Parity sweep" });
  await flush();

  assert.deepEqual(h.named, [ [ CC_ID, "Parity sweep" ] ]);
  const done = inCard(h, CC_ID, ".sender-gist-btn") as HTMLButtonElement;
  assert.equal(done.disabled, false);
  assert.ok(!done.classList.contains("working"));
  assert.equal(done.textContent, "✨");
  assert.equal(inCard(h, CC_ID, ".sender-session-name")!.textContent, "Parity sweep");
  assert.deepEqual(h.failures, []);
  h.renderer.unmount();
});

test("S2b: a pending ✨ keeps its ⏳ across a re-render, and a second click sends nothing", async () => {
  const reply = deferred<unknown>();
  const h = setup({ postReply: () => reply.promise });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  const original = h.cards.querySelector(".sender-gist-btn") as HTMLButtonElement;
  click(original);
  // P0 8cb5c22e — an UNCHANGED card now keeps its node, so the re-render must
  // carry a real change (a new message) for the card to be rebuilt at all.
  h.notifs.push(note({ id_hash: "n2", message: "a new message" }));
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "updated" }, source: "test", ts: 0 });

  const fresh = h.cards.querySelector(".sender-gist-btn") as HTMLButtonElement;
  assert.ok(fresh !== original, "the re-render replaced the card");
  assert.equal(fresh.textContent, "⏳");
  assert.equal(fresh.disabled, true);
  click(fresh);
  assert.equal(h.calls.length, 1, "no second request while one is out");

  reply.resolve({ gist: "Done" });
  await flush();
  assert.equal(h.cards.querySelector(".sender-gist-btn")!.textContent, "✨");
  h.renderer.unmount();
});

test("S2b: a failed or empty gist restores ✨, reports the failure, and leaves the name alone", async () => {
  const replies: Array<() => Promise<unknown>> = [
    () => Promise.reject(new Error("HTTP 502")),
    () => Promise.resolve(null),
    () => Promise.resolve({}),
    () => Promise.resolve({ gist: "   " }),
  ];
  for (const reply of replies) {
    const h = setup({ postReply: reply });
    h.notifs.push(note());
    h.senders.push(senderRec());
    h.renderer.mount(h.root);

    click(h.cards.querySelector(".sender-gist-btn"));
    await flush();

    assert.deepEqual(h.named, []);
    assert.equal(h.failures.length, 1);
    assert.match(h.failures[0]!, /Could not generate a session gist/);
    const btn = h.cards.querySelector(".sender-gist-btn") as HTMLButtonElement;
    assert.equal(btn.textContent, "✨");
    assert.equal(btn.disabled, false);
    assert.ok(!btn.classList.contains("working"));
    h.renderer.unmount();
  }
});

test("S2b: a sender with no message or abstract text sends no gist request", async () => {
  const h = setup();
  h.notifs.push(note({ message: "" }));
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-gist-btn"));
  await flush();

  assert.deepEqual(h.calls, []);
  assert.equal(h.cards.querySelector(".sender-gist-btn")!.textContent, "✨");
  h.renderer.unmount();
});

test("S2b: a gist that settles after unmount, or after its card is gone, finishes without error", async () => {
  const rejections: unknown[] = [];
  const onRejection = (e: unknown): void => { rejections.push(e); };
  process.on("unhandledRejection", onRejection);
  try {
    // (a) the renderer is unmounted while the request is out.
    const r1 = deferred<unknown>();
    const a  = setup({ postReply: () => r1.promise });
    a.notifs.push(note());
    a.senders.push(senderRec());
    a.renderer.mount(a.root);
    click(a.cards.querySelector(".sender-gist-btn"));
    a.renderer.unmount();
    r1.resolve({ gist: "late" });
    await flush();

    // (b) the card is deleted while the request is out.
    const r2 = deferred<unknown>();
    const b  = setup({ postReply: () => r2.promise });
    b.notifs.push(note());
    b.senders.push(senderRec());
    b.renderer.mount(b.root);
    click(b.cards.querySelector(".sender-gist-btn"));
    click(b.cards.querySelector(".sender-delete-btn"));
    await flush();
    assert.ok(cardFor(b, CC_ID) === null, "the card is gone before the gist settles");
    r2.resolve({ gist: "late" });
    await flush();
    assert.deepEqual(b.failures, []);
    b.renderer.unmount();
  } finally {
    process.off("unhandledRejection", onRejection);
  }
  assert.deepEqual(rejections, []);
});

// ===========================================================================
// S2c — click-to-rename modal
// ===========================================================================

test("S2c: clicking the session name opens the Rename Session modal prefilled with the current name, with no mic", () => {
  const h = setup();
  h.notifs.push(note());
  h.senders.push(senderRec({ session_name: "Old name" }));
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-session-name"));

  assert.equal(document.querySelectorAll("#session-name-edit-modal.session-name-edit-modal").length, 1);
  const modal = renameModal()!;
  assert.equal(modal.querySelector(".session-name-edit-header span")!.textContent, "Rename Session");
  assert.equal(modal.querySelector(".session-name-edit-close")!.textContent, "×");
  const input = modal.querySelector<HTMLInputElement>("#session-name-input.session-name-input")!;
  assert.equal(input.value, "Old name");
  assert.ok(document.activeElement === input, "the input has focus");
  assert.ok(modal.querySelector(".session-name-edit-hint") !== null);
  assert.equal(modal.querySelector(".session-name-cancel-btn")!.textContent, "Cancel");
  assert.equal(modal.querySelector(".session-name-save-btn")!.textContent, "Save");
  assert.ok(modal.querySelector("#session-name-mic-btn, .stt-button") === null, "no mic button");
  assert.notEqual(cardFor(h, CC_ID)!.getAttribute("data-collapsed"), "true", "the name click did not collapse the card");
  h.renderer.unmount();
});

test("S2c: Enter saves the trimmed name through SenderStore, closes the modal, and the card shows it", () => {
  const h = setup();
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-session-name"));
  const input = document.querySelector<HTMLInputElement>("#session-name-input")!;
  assert.equal(input.value, "", "no name yet → empty prefill");
  input.value = "  Parity sweep  ";
  key(input, "Enter");

  assert.deepEqual(h.named, [ [ CC_ID, "Parity sweep" ] ]);
  assert.ok(renameModal() === null);
  assert.equal(h.cards.querySelector(".sender-session-name")!.textContent, "Parity sweep");
  h.renderer.unmount();
});

test("S2c: Escape, Cancel and × close without saving, and Save with a blank name changes nothing", () => {
  const h = setup();
  h.notifs.push(note());   // no SenderRecord: the card renders from a stub sender
  h.renderer.mount(h.root);

  const open = (): HTMLInputElement => {
    click(h.cards.querySelector(".sender-session-name"));
    return document.querySelector<HTMLInputElement>("#session-name-input")!;
  };

  let input = open();
  input.value = "typed";
  key(input, "Escape");
  assert.ok(renameModal() === null, "Escape closes");

  input = open();
  input.value = "typed";
  click(document.querySelector(".session-name-cancel-btn"));
  assert.ok(renameModal() === null, "Cancel closes");

  input = open();
  input.value = "typed";
  click(document.querySelector(".session-name-edit-close"));
  assert.ok(renameModal() === null, "× closes");

  input = open();
  input.value = "   ";
  click(document.querySelector(".session-name-save-btn"));
  assert.ok(renameModal() === null, "Save closes");

  assert.deepEqual(h.named, []);
  h.renderer.unmount();
});

test("S2c: unmounting the renderer closes an open rename modal", () => {
  const h = setup();
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-session-name"));
  assert.ok(renameModal() !== null);
  h.renderer.unmount();
  assert.ok(renameModal() === null);
});

test("S2c modal: opening a second modal replaces the first, and keys other than Enter and Escape do nothing", () => {
  const saved: string[] = [];
  openSessionNameEditModal({ doc: document, currentName: "one", onSave: (n) => saved.push(n) });
  const close = openSessionNameEditModal({ doc: document, currentName: "two", onSave: (n) => saved.push(n) });

  assert.equal(document.querySelectorAll("#session-name-edit-modal").length, 1);
  const input = document.querySelector<HTMLInputElement>("#session-name-input")!;
  assert.equal(input.value, "two");
  key(input, "a");
  assert.ok(renameModal() !== null);

  close();
  close();   // idempotent
  assert.ok(renameModal() === null);
  assert.deepEqual(saved, []);
});

// ===========================================================================
// S2d — × delete the whole conversation
// ===========================================================================

test("S2d: × confirms with the count and project, DELETEs the conversation for this user, and removes the sender's rows", async () => {
  const h = setup();
  h.notifs.push(note({ id_hash: "m1", ts: DAY1 }), note({ id_hash: "m2" }), note({ id_hash: "o1", sender_id: OTHER_ID }));
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(inCard(h, CC_ID, ".sender-delete-btn"));
  await flush();

  assert.deepEqual(h.confirms, [ "Delete all 2 messages from LUPIN? This cannot be undone." ]);
  assert.deepEqual(h.calls, [ {
    method : "DELETE",
    path   : `/api/notifications/conversation/${encodeURIComponent(CC_ID)}/${encodeURIComponent(EMAIL)}`,
  } ]);
  assert.deepEqual(h.removed, [ [ "m1", "m2" ] ]);
  assert.ok(cardFor(h, CC_ID) === null, "the card is gone");
  assert.ok(cardFor(h, OTHER_ID) !== null, "the other sender's card stays");
  assert.deepEqual(h.failures, []);
  h.renderer.unmount();
});

test("S2d: when the server delete fails the rows are still removed here AND the failure is reported", async () => {
  const h = setup({ deleteReply: () => Promise.reject(new Error("HTTP 500")) });
  h.notifs.push(note({ id_hash: "m1" }));
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-delete-btn"));
  await flush();

  assert.deepEqual(h.confirms, [ "Delete all 1 message from LUPIN? This cannot be undone." ]);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.removed, [ [ "m1" ] ], "legacy parity: removed locally even though the server failed");
  assert.equal(h.failures.length, 1);
  assert.match(h.failures[0]!, /server delete failed \(HTTP 500\)/);
  h.renderer.unmount();
});

test("S2d: declining the delete-all confirm sends nothing and removes nothing", async () => {
  const h = setup({ confirm: false });
  h.notifs.push(note());
  h.senders.push(senderRec());
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-delete-btn"));
  await flush();

  assert.equal(h.confirms.length, 1);
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.removed, []);
  assert.ok(cardFor(h, CC_ID) !== null);
  h.renderer.unmount();
});

test("S2d: with no signed-in email nothing is sent, the rows are removed here, and the failure is reported", async () => {
  const h = setup({ email: null });
  h.notifs.push(note({ id_hash: "a1", sender_id: "lupin-arbiter-app-8001" }));
  h.renderer.mount(h.root);

  click(h.cards.querySelector(".sender-delete-btn"));
  await flush();

  assert.deepEqual(h.confirms, [ "Delete all 1 message from UNKNOWN? This cannot be undone." ]);
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.removed, [ [ "a1" ] ]);
  assert.equal(h.failures.length, 1);
  assert.match(h.failures[0]!, /no signed-in user email/);
  h.renderer.unmount();
});
