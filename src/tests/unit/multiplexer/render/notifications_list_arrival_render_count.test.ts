// Row 11793820 — one message renders ONLY the arriving sender's card.
//
// The row's done-means, verbatim: "one message causes at most one render, and it
// renders only the arriving sender's card (the others keep their nodes without
// being re-rendered)". Before this row every store event called renderSenderCard
// for EVERY card and compared signatures afterwards — 5 cards 551 ms, 20 cards
// 2,185 ms per arrival in happy-dom, and Rick's window returned 3,233 senders.
//
// Two kinds of test here, and they need each other:
//   - COUNT tests wrap the real template (the `renderCard` seam) and count
//     renders per sender. A renderer that skipped every card would pass them.
//   - The PARITY test drives a long seeded sequence of every kind of change and,
//     after each, holds every card in the DOM equal to a fresh render of its
//     current inputs. A renderer that re-rendered every card would pass THAT.
//
// ⚠️ Assertions compare ids, strings and numbers only — never a DOM node inside an
// assert message (a node in a failure message blows the jstest memory cap).

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsListRenderer } from "../../../../lupin_app/static/js/multiplexer/render";
import { renderSenderCard } from "../../../../lupin_app/static/js/multiplexer/render/templates/senderCard";
import { createConversationModePinRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ConversationModePinRenderer";
import { createSenderCardRecorderRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SenderCardRecorderRenderer";
import { recordingManager } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";
import type {
  Notification,
  PredictionVoteDir,
  SenderRecord,
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

const T0 = Date.UTC(2026, 8, 11, 18, 0);

const idFor = (i: number) => `claude.code@lupin.deepily.ai#cafe${String(i).padStart(4, "0")}`;

interface Harness {
  bus     : ReturnType<typeof createEventBusForTesting>;
  notifs  : Notification[];
  senders : SenderRecord[];
  votes   : Map<string, PredictionVoteDir>;
  cards   : HTMLElement;
  renders : Map<string, number>;
}

function sender(id: string, ts: number): SenderRecord {
  return { sender_id: id, display_name: "lupin", last_active_ts: ts, unread_count: 1, conversation_mode_active: false };
}

function note(idHash: string, senderId: string, ts: number, extra: Partial<Notification> = {}): Notification {
  return { id_hash: idHash, ts, sender_id: senderId, message: `msg ${idHash}`, action_required: false, ...extra };
}

function setup(senderCount: number): Harness {
  const bus     = createEventBusForTesting();
  const notifs  : Notification[]  = [];
  const senders : SenderRecord[]  = [];
  const votes   = new Map<string, PredictionVoteDir>();
  const renders = new Map<string, number>();
  for (let i = 0; i < senderCount; i++) {
    senders.push(sender(idFor(i), T0 + i * 1_000));
    for (let r = 0; r < 3; r++) notifs.push(note(`s${i}r${r}`, idFor(i), T0 + i * 1_000 - r * 60_000));
  }

  const pane = document.createElement("section");
  pane.innerHTML = `<div id="sender-cards-container"></div>`;
  document.body.appendChild(pane);

  const renderer = createNotificationsListRenderer({
    eventBus    : bus,
    stores      : {
      notifications  : { list: () => notifs },
      senders        : { list: () => senders },
      predictionVote : {
        getVote    : (id) => votes.get(id),
        setContext : () => { /* not exercised */ },
        vote       : async () => true,
      },
    },
    appTimezone : "UTC",
    renderCard  : (s, n, o) => {
      renders.set(s.sender_id, (renders.get(s.sender_id) ?? 0) + 1);
      return renderSenderCard(s, n, o);
    },
  });
  renderer.mount(pane);

  return { bus, notifs, senders, votes, cards: pane.querySelector<HTMLElement>("#sender-cards-container")!, renders };
}

function emitNotifications(h: Harness, changeKind: string, idHash?: string): void {
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind, id_hash: idHash }, source: "test", ts: 0 });
}

function emitSenders(h: Harness, senderId?: string): void {
  h.bus.emit({ type: "store_senders_changed", payload: { changeKind: "updated", sender_id: senderId }, source: "test", ts: 0 });
}

// A message arrives the way production delivers it: both stores update, and each
// emits its own change event (NotificationStore, then SenderStore). The sender
// record is mutated IN PLACE, as SenderStore does.
// Row 11793820 — NotificationsListRenderer renders once per turn, in a microtask
// queued by the store events. A microtask queued after them runs after that render.
const renderTurn = (): Promise<void> => new Promise<void>(resolve => queueMicrotask(resolve));

async function arrive(h: Harness, idHash: string, senderId: string, ts: number): Promise<void> {
  h.notifs.push(note(idHash, senderId, ts));
  const rec = h.senders.find(s => s.sender_id === senderId)!;
  rec.last_active_ts = ts;
  rec.unread_count++;
  emitNotifications(h, "added", idHash);
  emitSenders(h, senderId);
  await renderTurn();
}

function cardNodes(h: Harness): Map<string, Element> {
  return new Map(Array.from(h.cards.querySelectorAll(".sender-card")).map(c => [ c.getAttribute("data-sender-id") ?? "", c ]));
}

// ===========================================================================
// Count
// ===========================================================================

test("a message from one sender renders no other sender's card", async () => {
  const h = setup(8);
  h.renders.clear();

  await arrive(h, "new-3", idFor(3), T0 + 60_000);

  const others = Array.from(h.renders.entries()).filter(([ id ]) => id !== idFor(3));
  assert.deepEqual(others, [], "cards of senders that sent nothing were rendered");
  assert.ok((h.renders.get(idFor(3)) ?? 0) >= 1, "the arriving sender's card was not rendered at all");
});

test("the other cards keep their DOM nodes through a foreign arrival", async () => {
  const h      = setup(8);
  const before = cardNodes(h);

  await arrive(h, "new-5", idFor(5), T0 + 60_000);

  const after = cardNodes(h);
  for (const [ id, node ] of before) {
    if (id === idFor(5)) continue;
    assert.equal(after.get(id) === node, true, `${id}: its node was replaced`);
  }
});

test("a kept card still moves its active dot when another sender becomes the newest", async () => {
  const h = setup(4);
  const card = (i: number) => h.cards.querySelector(`.sender-card[data-sender-id="${idFor(i)}"]`)!;
  assert.equal(card(3).classList.contains("sender-card-active"), true, "precondition: the newest sender is active");

  await arrive(h, "new-0", idFor(0), T0 + 60_000);

  assert.equal(card(3).classList.contains("sender-card-active"), false);
  assert.equal(card(3).querySelector(".sender-active-indicator")!.textContent, "○");
  assert.equal(card(0).classList.contains("sender-card-active"), true);
  assert.equal(card(0).querySelector(".sender-active-indicator")!.textContent, "●");
});

// ===========================================================================
// Parity — a skipped card is never a stale card
// ===========================================================================

function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Every card in the DOM must equal a fresh render of its CURRENT inputs. Cards sit
// in the default sort (newest sender first), and the first card is the active one.
function assertParity(h: Harness, step: string): void {
  const integration = { getVote: (id: string) => h.votes.get(id), onVote: () => { /* inert */ } };
  const cards = Array.from(h.cards.querySelectorAll<HTMLElement>(".sender-card"));
  cards.forEach((card, index) => {
    const id     = card.getAttribute("data-sender-id")!;
    const rec    = h.senders.find(s => s.sender_id === id)!;
    const rows   = h.notifs.filter(n => n.sender_id === id && !n.action_required);
    const fresh  = renderSenderCard(rec, rows, { appTimezone: "UTC", predictionVote: integration, isActive: index === 0 });
    if (card.outerHTML !== fresh.outerHTML) {
      assert.fail(`${step}: card ${id} (position ${index}) differs from a fresh render of its current inputs`);
    }
  });
}

// ⚠️ SIZE. happy-dom holds on to what these fresh renders build: measured 557 MB
// peak at 40 steps and 1,039 MB at 90 against the lane's 2,048 MB ceiling. So the
// sequence is 4 shuffled ROUNDS of every kind (48 steps) rather than a long random
// draw — every kind runs exactly 4 times, in a different order each round, and no
// kind can be missed by an unlucky seed.
test("parity: after every step of a seeded sequence of every change kind, every card equals a fresh render", async () => {
  const h      = setup(6);
  const rand   = mulberry32(11793820);
  const pick   = <T>(xs: ReadonlyArray<T>): T => xs[Math.floor(rand() * xs.length)]!;
  let   clock  = T0 + 100_000;
  let   serial = 0;

  const kinds = [
    "arrive", "replace-row", "remove-row", "rename", "conv-mode", "persona", "worker",
    "unread", "new-sender", "hint-row", "vote", "display-name",
  ] as const;
  const ROUNDS   = 4;
  const sequence : Array<typeof kinds[number]> = [];
  for (let r = 0; r < ROUNDS; r++) {
    const round = [ ...kinds ];
    for (let i = round.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [ round[i], round[j] ] = [ round[j]!, round[i]! ];
    }
    sequence.push(...round);
  }

  const ran = new Map<string, number>();
  for (let i = 0; i < sequence.length; i++) {
    const kind = sequence[i]!;
    const rec  = pick(h.senders);
    clock += 1_000;
    switch (kind) {
      case "arrive":
        await arrive(h, `a${serial++}`, rec.sender_id, clock);
        break;
      case "replace-row": {
        const mine = h.notifs.filter(n => n.sender_id === rec.sender_id);
        assert.ok(mine.length > 0, `step ${i}: sender ${rec.sender_id} has no row to replace`);
        const old = pick(mine);
        h.notifs[h.notifs.indexOf(old)] = { ...old, message: `edited ${serial++}` };
        emitNotifications(h, "updated", old.id_hash);
        break;
      }
      case "remove-row": {
        // From a sender with rows to spare, so no card disappears (that path is
        // the orphan removal, covered in dom.test.ts).
        const rich = h.senders.filter(s => h.notifs.filter(n => n.sender_id === s.sender_id).length > 1);
        assert.ok(rich.length > 0, `step ${i}: no sender has a row to spare`);
        const owner = pick(rich).sender_id;
        h.notifs.splice(h.notifs.indexOf(pick(h.notifs.filter(n => n.sender_id === owner))), 1);
        emitNotifications(h, "removed");
        break;
      }
      case "rename":
        rec.session_name = `topic ${serial++}`;
        emitSenders(h, rec.sender_id);
        break;
      case "conv-mode":
        rec.conversation_mode_active = !rec.conversation_mode_active;
        emitSenders(h, rec.sender_id);
        break;
      case "persona":
        rec.voice_persona = { name: `P${serial++}`, voice_id: "v", icon: "🙂", color: pick([ "#81D4FA", "#F06292" ]), borrowed: rand() < 0.5 };
        emitSenders(h, rec.sender_id);
        break;
      case "worker":
        rec.is_worker = !rec.is_worker;
        emitSenders(h, rec.sender_id);
        break;
      case "unread":
        rec.unread_count = Math.floor(rand() * 4);
        emitSenders(h, rec.sender_id);
        break;
      case "display-name":
        rec.display_name = pick([ "lupin", "plan", "cosa" ]);
        emitSenders(h, rec.sender_id);
        break;
      case "new-sender": {
        const id = idFor(100 + serial++);
        h.senders.push(sender(id, clock));
        h.notifs.push(note(`n${serial++}`, id, clock));
        emitNotifications(h, "added");
        emitSenders(h, id);
        break;
      }
      case "hint-row": {
        const idHash = `h${serial++}`;
        h.notifs.push(note(idHash, rec.sender_id, clock, { prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } }));
        emitNotifications(h, "added", idHash);
        break;
      }
      case "vote": {
        if (!h.notifs.some(n => n.prediction_hint !== undefined)) {
          h.notifs.push(note(`h${serial++}`, rec.sender_id, clock, { prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } }));
          emitNotifications(h, "added");
        }
        const target = pick(h.notifs.filter(n => n.prediction_hint !== undefined));
        h.votes.set(target.id_hash, h.votes.get(target.id_hash) === "up" ? "down" : "up");
        h.bus.emit({ type: "store_prediction_vote_changed", payload: { notificationId: target.id_hash, vote: h.votes.get(target.id_hash)! }, source: "test", ts: 0 });
        break;
      }
    }
    await renderTurn();
    assertParity(h, `step ${i} (${kind})`);
    ran.set(kind, (ran.get(kind) ?? 0) + 1);
  }
  assert.deepEqual([ ...ran.entries() ].filter(([ , n ]) => n !== ROUNDS), [], "a change kind did not run every round");
  assert.equal(ran.size, kinds.length);
});

// ===========================================================================
// One render per arrival — with every renderer that decorates a card mounted
// ===========================================================================
//
// These run the list renderer, ConversationModePinRenderer and
// SenderCardRecorderRenderer on one bus in boot order (boot.ts:360, :444, :487).
// With the pin and recorder mounted, a `notifications_list_rendered` listener that
// raised a store event would show up here as a second render (Mr. Radio's review).

interface Fleet extends Harness {
  rendered : { count: number };
  errors   : string[];
  throwFor : { senderId: string | undefined };   // the next render of this sender's card throws, once
  unmount  : () => void;
}

function setupFleet(senderCount: number): Fleet {
  const bus     = createEventBusForTesting();
  const notifs  : Notification[] = [];
  const senders : SenderRecord[] = [];
  const votes   = new Map<string, PredictionVoteDir>();
  const renders = new Map<string, number>();
  for (let i = 0; i < senderCount; i++) {
    senders.push(sender(idFor(i), T0 + i * 1_000));
    notifs.push(note(`s${i}r0`, idFor(i), T0 + i * 1_000));
  }
  const throwFor = { senderId: undefined as string | undefined };

  const pane = document.createElement("section");
  pane.innerHTML = `<div id="sender-cards-container"></div>`;
  document.body.appendChild(pane);
  const cards = pane.querySelector<HTMLElement>("#sender-cards-container")!;

  const list = createNotificationsListRenderer({
    eventBus    : bus,
    stores      : { notifications: { list: () => notifs }, senders: { list: () => senders } },
    appTimezone : "UTC",
    renderCard  : (s, n, o) => {
      renders.set(s.sender_id, (renders.get(s.sender_id) ?? 0) + 1);
      if (throwFor.senderId === s.sender_id) {
        throwFor.senderId = undefined;
        throw new Error("template exploded once");
      }
      return renderSenderCard(s, n, o);
    },
  });
  const pin      = createConversationModePinRenderer({ eventBus: bus, stores: { senders: { list: () => senders } } });
  const recorder = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  list.mount(pane);
  pin.mount(pane);
  recorder.mount(cards);

  const rendered = { count: 0 };
  const errors   : string[] = [];
  bus.on("notifications_list_rendered", () => { rendered.count++; });
  bus.on<{ error: string }>("listener_error", (e) => { errors.push(e.payload.error); });

  return {
    bus, notifs, senders, votes, cards, renders, rendered, errors, throwFor,
    unmount : () => { recorder.unmount(); pin.unmount(); list.unmount(); },
  };
}

// Several turns, not one: a render that re-triggers itself through a listener
// would schedule its next flush as a new microtask, and a timer runs after all of them.
const settle = (): Promise<void> => new Promise<void>(resolve => setTimeout(resolve, 0));

test("one arrival: exactly ONE card render and ONE rendered announcement, with pin + recorder mounted", async () => {
  const h = setupFleet(6);
  h.renders.clear();
  h.rendered.count = 0;

  await arrive(h, "one", idFor(2), T0 + 60_000);
  await settle();

  assert.deepEqual([ ...h.renders.entries() ], [ [ idFor(2), 1 ] ]);
  assert.equal(h.rendered.count, 1, "the list rendered more than once for one arrival");
  h.unmount();
});

test("a pinned sender's card keeps its pin when a message replaces the card", async () => {
  const h = setupFleet(3);
  h.senders[1]!.conversation_mode_active = true;
  h.bus.emit({ type: "store_senders_changed", payload: { changeKind: "updated", sender_id: idFor(1) }, source: "test", ts: 0 });
  await settle();
  const before = h.cards.querySelector(`.sender-card[data-sender-id="${idFor(1)}"]`)!;
  assert.equal(before.getAttribute("data-pinned-conv-mode"), "true", "precondition: the card is pinned");

  await arrive(h, "for-pinned", idFor(1), T0 + 60_000);
  await settle();

  const after = h.cards.querySelector(`.sender-card[data-sender-id="${idFor(1)}"]`)!;
  assert.equal(after !== before, true, "precondition: the message replaced the card");
  assert.equal(after.getAttribute("data-pinned-conv-mode"), "true", "the replacement card lost its pin");
  h.unmount();
});

test("a recording in progress survives a message that replaces the recording sender's card", async () => {
  const h = setupFleet(3);
  const row = (): Element => h.cards.querySelector(`.sender-card[data-sender-id="${idFor(0)}"] .cc-voice-input`)!;
  const original = recordingManager.startRecording.bind(recordingManager);
  ( recordingManager as unknown as { startRecording: () => Promise<void> } ).startRecording = async () => { /* never completes */ };
  try {
    ( row().querySelector(".cc-session-stt") as HTMLButtonElement ).click();
  } finally {
    ( recordingManager as unknown as { startRecording: typeof original } ).startRecording = original;
  }
  const before = row();
  assert.equal(before.getAttribute("data-recorder-state"), "recording", "precondition: recording");

  await arrive(h, "while-recording", idFor(0), T0 + 60_000);
  await settle();

  assert.equal(row() !== before, true, "precondition: the message replaced the row");
  assert.equal(row().getAttribute("data-recorder-state"), "recording", "the replacement row shows idle mid-recording");
  h.unmount();
});

test("a render that throws is reported, and the next arrival still renders", async () => {
  const h = setupFleet(3);
  h.throwFor.senderId = idFor(1);   // armed after mount, so the initial paint is unaffected

  await arrive(h, "boom", idFor(1), T0 + 60_000);
  await settle();
  assert.equal(h.errors.length, 1, "the throwing render was not reported as listener_error");
  assert.match(h.errors[0]!, /template exploded once/);

  await arrive(h, "after-boom", idFor(1), T0 + 70_000);
  await settle();
  const card = h.cards.querySelector(`.sender-card[data-sender-id="${idFor(1)}"]`)!;
  assert.equal(card.querySelector('[data-id-hash="after-boom"]') !== null, true, "a render after the throw did not happen");
  h.unmount();
});

test("unmount with a render pending: no render runs, nothing throws", async () => {
  const h = setupFleet(3);
  h.renders.clear();
  h.rendered.count = 0;

  h.notifs.push(note("late", idFor(0), T0 + 60_000));
  h.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: "late" }, source: "test", ts: 0 });
  h.unmount();
  await settle();

  assert.equal(h.renders.size, 0);
  assert.equal(h.rendered.count, 0);
  assert.deepEqual(h.errors, []);
});
