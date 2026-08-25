// Multiplexer B4 (01-D, v0.1.9 CC-session parity) — NotificationsListRenderer
// per-message active-TTS controls: the delegated click branches (pause/stop/
// ratify) + the dual-subscription active-TTS class driver.
//
// Companion to notifications_list_renderer.test.ts + notifications_list_accordion_collapse.test.ts;
// run ALL THREE under one c8 process for the 100% gate on NotificationsListRenderer.ts.
//
// THE F0 SEAM (Mr. Radio ruling, Option A refined): identity comes from the
// injected `TtsQueueStoreLike { current(): string | null }` — a READ-ONLY,
// mutator-less interface. COND-2 (B4 makes ZERO TtsQueueStore mutator calls) is
// PROVABLE BY SHAPE: the renderer holds no handle to a queue mutator, so it
// cannot call one. The injected mock below stands in for real F0 (00b) — these
// identity-half assertions are MOCK-VERIFIED ONLY, NOT end-to-end-proven until
// real F0's TtsQueueStore wires boot. The glyph half (store_audio_state_change +
// real AudioStore) IS real-wired today.

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
  AudioPlaybackState,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});

// --- Fakes -----------------------------------------------------------------

interface FakeTts { current(): string | null; set(id: string | null): void; }
function makeFakeTts(): FakeTts {
  let cur: string | null = null;
  return { current: () => cur, set: (id) => { cur = id; } };
}

interface FakeAudio {
  state(): AudioPlaybackState; pause(): void; resume(): void; stop(): void;
  setState(s: AudioPlaybackState): void; calls: string[];
}
function makeFakeAudio(initial: AudioPlaybackState = "playing"): FakeAudio {
  let st = initial;
  const calls: string[] = [];
  return {
    state    : () => st,
    pause    : () => { calls.push("pause"); },
    resume   : () => { calls.push("resume"); },
    stop     : () => { calls.push("stop"); },
    setState : (s) => { st = s; },
    calls,
  };
}

interface FakeRatifier { acknowledgeProxy(): Promise<unknown>; calls: number; }
function makeFakeRatifier(reject = false): FakeRatifier {
  const r: FakeRatifier = {
    calls : 0,
    acknowledgeProxy() {
      r.calls += 1;
      return reject ? Promise.reject(new Error("boom")) : Promise.resolve({ status: "success" });
    },
  };
  return r;
}

interface Setup {
  bus       : ReturnType<typeof createEventBusForTesting>;
  notifList : Notification[];
  senderList: SenderRecord[];
  sCards    : HTMLElement;
  renderer  : NotificationsListRenderer;
  tts       : FakeTts;
  audio     : FakeAudio;
  ratifier  : FakeRatifier;
  openerCalls: string[][];
}

interface SetupOpts {
  withAudio?    : boolean;   // default true
  withTts?      : boolean;   // default true
  withRatifier? : boolean;   // default true
  withOpener?   : boolean;   // default true
  ratifierRejects? : boolean;
}

function setup(notifs: Notification[], senders: SenderRecord[], o: SetupOpts = {}): Setup {
  const bus = createEventBusForTesting();
  const tts = makeFakeTts();
  const audio = makeFakeAudio();
  const ratifier = makeFakeRatifier(o.ratifierRejects ?? false);
  const openerCalls: string[][] = [];

  const renderer = createNotificationsListRenderer({
    eventBus : bus,
    stores   : {
      notifications  : { list: () => notifs },
      senders        : { list: () => senders },
      ...((o.withAudio ?? true) ? { audio } : {}),
      ...((o.withTts ?? true)   ? { ttsQueue: tts } : {}),
    },
    appTimezone : "UTC",
    ...((o.withRatifier ?? true) ? { proxyRatifier: ratifier } : {}),
    ...((o.withOpener ?? true)   ? { proxyRatifyOpener: (...a: string[]) => { openerCalls.push(a); } } : {}),
  });

  const root = document.createElement("section");
  const arSection = document.createElement("div");
  arSection.id = "action-required-section";
  const sCards = document.createElement("div");
  sCards.id = "sender-cards-container";
  root.appendChild(arSection);
  root.appendChild(sCards);
  renderer.mount(root);

  return { bus, notifList: notifs, senderList: senders, sCards, renderer, tts, audio, ratifier, openerCalls };
}

function makeNotification(over: Partial<Notification> = {}): Notification {
  return { id_hash: "n1", ts: Date.UTC(2026, 4, 5, 14, 7), sender_id: "sess_42", message: "hi", action_required: false, ...over };
}
function makeSender(over: Partial<SenderRecord> = {}): SenderRecord {
  return { sender_id: "sess_42", display_name: "S", last_active_ts: 1, unread_count: 1, conversation_mode_active: false, ...over };
}

function bubble(s: Setup, idHash: string): HTMLElement | null {
  return s.sCards.querySelector(`.sender-message[data-id-hash="${idHash}"]`);
}
function litCount(s: Setup): number {
  return s.sCards.querySelectorAll(".sender-message.tts-playing").length;
}

// ===========================================================================
// Active-TTS class driver — identity (F0 seam) + glyph (store_audio_state_change)
// ===========================================================================

test("driver: current()=id (playing) lights exactly that bubble — tts-playing + is-playing-current, glyph ⏸", () => {
  const s = setup([makeNotification()], [makeSender()]);
  s.tts.set("n1");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  const b = bubble(s, "n1")!;
  assert.ok(b.classList.contains("tts-playing"));
  assert.ok(b.classList.contains("is-playing-current"));
  assert.equal(b.classList.contains("is-paused-current"), false);
  assert.equal(b.querySelector(".notification-corner-pause-btn")!.textContent, "⏸");
  s.renderer.unmount();
});

test("driver: paused state adds is-paused-current + flips glyph to ▶ (glyph half = real-wired)", () => {
  const s = setup([makeNotification()], [makeSender()]);
  s.audio.setState("paused");
  s.tts.set("n1");
  s.bus.emit({ type: "store_audio_state_change", payload: { state: "paused", prev: "playing" } });
  const b = bubble(s, "n1")!;
  assert.ok(b.classList.contains("is-paused-current"));
  const btn = b.querySelector(".notification-corner-pause-btn") as HTMLButtonElement;
  assert.equal(btn.textContent, "▶");
  assert.equal(btn.dataset.paused, "true");
  assert.equal(btn.getAttribute("aria-label"), "Resume notification audio");
  s.renderer.unmount();
});

test("driver: current()===null clears ALL — nothing lit (clear-prior, no set)", () => {
  const s = setup([makeNotification()], [makeSender()]);
  s.tts.set("n1");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.equal(litCount(s), 1);
  s.tts.set(null);
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.equal(litCount(s), 0);
  s.renderer.unmount();
});

test("driver: current()=id NOT in the DOM → nothing lit, no throw", () => {
  const s = setup([makeNotification()], [makeSender()]);
  s.tts.set("ghost-id");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.equal(litCount(s), 0);
  s.renderer.unmount();
});

test("driver: ONE-BUBBLE across a TRANSITION (A lit → B set → A cleared, only B lit) — clear-prior negative test", () => {
  const n1 = makeNotification({ id_hash: "n1", sender_id: "s1" });
  const n2 = makeNotification({ id_hash: "n2", sender_id: "s2", message: "second" });
  const s = setup([n1, n2], [makeSender({ sender_id: "s1" }), makeSender({ sender_id: "s2" })]);

  s.tts.set("n1");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.ok(bubble(s, "n1")!.classList.contains("tts-playing"));
  assert.equal(litCount(s), 1);

  // TRANSITION — a missing clear-prior would leave BOTH lit (this is what fails it).
  s.tts.set("n2");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.equal(bubble(s, "n1")!.classList.contains("tts-playing"), false);
  assert.ok(bubble(s, "n2")!.classList.contains("tts-playing"));
  assert.equal(litCount(s), 1);   // EXACTLY one bubble lit, ever
  s.renderer.unmount();
});

test("driver: clear-prior resets the prior bubble's pause glyph back to ⏸/false", () => {
  const n1 = makeNotification({ id_hash: "n1", sender_id: "s1" });
  const n2 = makeNotification({ id_hash: "n2", sender_id: "s2" });
  const s = setup([n1, n2], [makeSender({ sender_id: "s1" }), makeSender({ sender_id: "s2" })]);
  // n1 paused (glyph ▶)
  s.audio.setState("paused");
  s.tts.set("n1");
  s.bus.emit({ type: "store_audio_state_change", payload: { state: "paused", prev: "playing" } });
  assert.equal((bubble(s, "n1")!.querySelector(".notification-corner-pause-btn") as HTMLButtonElement).textContent, "▶");
  // transition to n2 (playing) → n1's glyph reset
  s.audio.setState("playing");
  s.tts.set("n2");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  const n1btn = bubble(s, "n1")!.querySelector(".notification-corner-pause-btn") as HTMLButtonElement;
  assert.equal(n1btn.textContent, "⏸");
  assert.equal(n1btn.dataset.paused, "false");
  s.renderer.unmount();
});

test("driver: no ttsQueue injected → current() resolves null → clears, no throw", () => {
  const s = setup([makeNotification()], [makeSender()], { withTts: false });
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.equal(litCount(s), 0);
  s.renderer.unmount();
});

test("driver: no audio injected → lit bubble defaults to playing glyph (audio-undefined branch)", () => {
  const s = setup([makeNotification()], [makeSender()], { withAudio: false });
  s.tts.set("n1");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  const b = bubble(s, "n1")!;
  assert.ok(b.classList.contains("tts-playing"));
  assert.equal(b.classList.contains("is-paused-current"), false);
  s.renderer.unmount();
});

test("driver: re-render re-applies the active-TTS state (lit bubble survives a forceRender)", () => {
  const s = setup([makeNotification()], [makeSender()]);
  s.tts.set("n1");
  s.bus.emit({ type: "store_tts_queue_changed", payload: {} });
  assert.equal(litCount(s), 1);
  s.renderer.forceRenderForTesting();   // rebuilds bubbles → driver must re-light
  assert.equal(litCount(s), 1);
  assert.ok(bubble(s, "n1")!.classList.contains("tts-playing"));
  s.renderer.unmount();
});

test("driver: active bubble is OUTGOING (no pause btn) → setPauseGlyph null-guard, classes still apply, no throw", () => {
  const s = setup([makeNotification({ direction: "outgoing" })], [makeSender()]);
  s.audio.setState("paused");
  s.tts.set("n1");
  s.bus.emit({ type: "store_audio_state_change", payload: { state: "paused", prev: "playing" } });
  const b = bubble(s, "n1")!;
  assert.ok(b.classList.contains("tts-playing"));
  assert.ok( b.querySelector(".notification-corner-pause-btn") === null );   // outgoing has no pause btn
  s.renderer.unmount();
});

// ===========================================================================
// Delegated click branches — pause / stop / ratify (ride the existing handler)
// ===========================================================================

test("click pause (playing) → AudioStore.pause()", () => {
  const s = setup([makeNotification()], [makeSender()]);
  (bubble(s, "n1")!.querySelector(".notification-corner-pause-btn") as HTMLElement).click();
  assert.deepEqual(s.audio.calls, ["pause"]);
  s.renderer.unmount();
});

test("click pause (paused) → AudioStore.resume()", () => {
  const s = setup([makeNotification()], [makeSender()]);
  s.audio.setState("paused");
  (bubble(s, "n1")!.querySelector(".notification-corner-pause-btn") as HTMLElement).click();
  assert.deepEqual(s.audio.calls, ["resume"]);
  s.renderer.unmount();
});

test("click stop → AudioStore.stop() (halt only — COND-2: no advance, no queue mutator)", () => {
  const s = setup([makeNotification()], [makeSender()]);
  (bubble(s, "n1")!.querySelector(".notification-corner-stop-btn") as HTMLElement).click();
  assert.deepEqual(s.audio.calls, ["stop"]);
  s.renderer.unmount();
});

test("click pause/stop with NO audio injected → no throw (optional)", () => {
  const s = setup([makeNotification()], [makeSender()], { withAudio: false });
  (bubble(s, "n1")!.querySelector(".notification-corner-pause-btn") as HTMLElement).click();
  (bubble(s, "n1")!.querySelector(".notification-corner-stop-btn") as HTMLElement).click();
  assert.equal(litCount(s), 0);   // smoke — no exception
  s.renderer.unmount();
});

test("click ratify-link → acknowledgeProxy() + opener(page) + default prevented", () => {
  const s = setup([makeNotification({ progress_group_id: "pr-1a2b3c4d-7" })], [makeSender()]);
  const link = bubble(s, "n1")!.querySelector(".proxy-ratify-link") as HTMLAnchorElement;
  const ev = new Event("click", { bubbles: true, cancelable: true });
  link.dispatchEvent(ev);
  assert.equal(s.ratifier.calls, 1);
  assert.equal(s.openerCalls.length, 1);
  assert.equal(ev.defaultPrevented, true);
  s.renderer.unmount();
});

test("click ratify-link with NO ratifier/opener injected → no throw", () => {
  const s = setup([makeNotification({ progress_group_id: "pr-9" })], [makeSender()], { withRatifier: false, withOpener: false });
  (bubble(s, "n1")!.querySelector(".proxy-ratify-link") as HTMLElement).click();
  assert.equal(s.ratifier.calls, 0);
  s.renderer.unmount();
});

test("click ratify-link whose acknowledgeProxy REJECTS → swallowed (fire-and-forget), no unhandled", async () => {
  const s = setup([makeNotification({ progress_group_id: "pr-x" })], [makeSender()], { ratifierRejects: true });
  (bubble(s, "n1")!.querySelector(".proxy-ratify-link") as HTMLElement).click();
  await Promise.resolve();   // let the rejected microtask settle through .catch
  assert.equal(s.ratifier.calls, 1);
  s.renderer.unmount();
});
