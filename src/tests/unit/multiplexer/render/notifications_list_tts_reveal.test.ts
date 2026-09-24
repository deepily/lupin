// Parity A-2 #4 — TTS playback expands what hides the speaking bubble and scrolls to it.
//
// Legacy: `startTTSPlayingIndicator` calls `expandAccordionsForNotification`
// (notifications.js:5146 → :25478), which expands the sender card, expands the date
// accordion, and then `scrollIntoViewIfNeeded`s the notification. The multiplexer lit the
// bubble and stopped at `if (bubble === null) return` — so on a collapsed card the gold
// pulse played behind a closed accordion: audio with nothing to look at, and no way for the
// operator to tell which notification was speaking.
//
// 🔴 THE GUARD IS WHAT LEGACY GETS FOR FREE AND THIS RENDERER DOES NOT, and it is the
// reason most of this file exists. Legacy reveals from a ONE-SHOT event — the TTS request
// starting, once per utterance. `refreshActiveTts` is not that: it runs on every render and
// every audio state change. An unguarded reveal would re-expand a card the OPERATOR had
// just collapsed and scroll the page back, repeatedly, for as long as the utterance played.
// The page would fight them, and it would look like a rendering bug rather than a policy.
//
// ⇒ The reveal fires on a CHANGE of the active id. The tests below pin both halves: it
// happens on a change, and it does NOT happen on a refresh at the same id.
//
// ⚠️ happy-dom does no layout, so every rect is zeros and reads as "already in view" —
// scrollRevealElement would then resolve without scrolling and every scroll assertion would
// pass vacuously. `placeOffscreen` pins the bubble below the fold so the helper has a reason
// to move, the same device notifications_list_app_timezone uses.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/notifications_list_tts_reveal.test.ts

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

const TS = Date.UTC(2026, 4, 5, 14, 7);

/** The TTS queue seam: only `current()` is read by the driver. */
function makeTts() {
  let id: string | null = null;
  return { current: () => id, set(next: string | null) { id = next; } };
}

/** Records every persisted collapse write, so "did it persist?" is answerable. */
function makeViewState() {
  const collapsed = new Map<string, boolean>();
  const writes: Array<[ string, boolean ]> = [];
  return {
    collapsed, writes,
    isAccordionCollapsed : (id: string) => collapsed.get(id) === true,
    setAccordionCollapsed: (id: string, v: boolean) => { collapsed.set(id, v); writes.push([ id, v ]); },
    isSectionVisible     : () => true,
    setSectionVisible    : () => { /* unused here */ },
    hasSectionPreference : () => false,
    getHiddenSectionIds  : () => [] as string[],
  };
}

interface Setup {
  bus      : ReturnType<typeof createEventBusForTesting>;
  sCards   : HTMLElement;
  renderer : NotificationsListRenderer;
  tts      : ReturnType<typeof makeTts>;
  viewState: ReturnType<typeof makeViewState>;
  scrolls  : () => number;
}

function setup(): Setup {
  const bus       = createEventBusForTesting();
  const tts       = makeTts();
  const viewState = makeViewState();
  const notifs    : Notification[] = [
    { id_hash: "n1", ts: TS, sender_id: "sess_42", message: "hi",    action_required: false },
    { id_hash: "n2", ts: TS, sender_id: "sess_42", message: "there", action_required: false },
  ];
  const senders   : SenderRecord[] = [
    { sender_id: "sess_42", display_name: "S", last_active_ts: TS, unread_count: 1,
      conversation_mode_active: false },
  ];

  const renderer = createNotificationsListRenderer({
    eventBus : bus,
    stores   : { notifications: { list: () => notifs }, senders: { list: () => senders },
                 ttsQueue: tts, viewState },
    appTimezone : "UTC",
  });

  const root      = document.createElement("section");
  const arSection = document.createElement("div");
  arSection.id    = "action-required-section";
  const sCards    = document.createElement("div");
  sCards.id       = "sender-cards-container";
  root.appendChild(arSection);
  root.appendChild(sCards);
  renderer.mount(root);

  let scrolls = 0;
  for (const el of Array.from(sCards.querySelectorAll<HTMLElement>(".sender-message"))) {
    placeOffscreen(el);
    el.scrollIntoView = () => { scrolls += 1; };
  }
  return { bus, sCards, renderer, tts, viewState, scrolls: () => scrolls };
}

/** happy-dom has no layout; pin the element below the fold so the helper must move it. */
function placeOffscreen(el: HTMLElement): void {
  el.getBoundingClientRect = () => ({
    top: window.innerHeight + 100, bottom: window.innerHeight + 400,
    left: 0, right: 0, width: 0, height: 300, x: 0, y: 0, toJSON: () => ({}),
  }) as DOMRect;
}

/**
 * Drive the REAL path the driver listens on — `store_tts_queue_changed`, one of the two
 * bus events wired at NotificationsListRenderer.ts:481. Entering here rather than through
 * a test-only seam is the point: the defect this file guards is reached by an event, and a
 * seam would let the wiring rot while every assertion stayed green.
 */
function ttsChanged(s: Setup): void {
  s.bus.emit({ type: "store_tts_queue_changed", payload: undefined, source: "test", ts: 0 });
}

function bubble(s: Setup, idHash: string): HTMLElement {
  const el = s.sCards.querySelector<HTMLElement>(`.sender-message[data-id-hash="${idHash}"]`);
  assert.notEqual(el, null, `no bubble for ${idHash}`);
  return el as HTMLElement;
}
function card(s: Setup): HTMLElement {
  return s.sCards.querySelector<HTMLElement>(".sender-card") as HTMLElement;
}
function accordion(s: Setup): HTMLElement {
  return s.sCards.querySelector<HTMLElement>(".date-accordion") as HTMLElement;
}
/** Collapse both ancestors the way a click would, without going through the renderer. */
function collapseBoth(s: Setup): void {
  card(s).setAttribute("data-collapsed", "true");
  accordion(s).setAttribute("data-collapsed", "true");
}

// ===========================================================================

test("instrument check: the fixture renders two bubbles inside a card and a date accordion", () => {
  // Without this, a reveal test could pass by finding nothing to expand.
  const s = setup();
  assert.notEqual(bubble(s, "n1"), null);
  assert.notEqual(card(s), null, "no sender card rendered");
  assert.notEqual(accordion(s), null, "no date accordion rendered");
  s.renderer.unmount();
});

test("🔴 a speaking bubble inside a COLLAPSED card and accordion expands both and scrolls", () => {
  const s = setup();
  collapseBoth(s);
  assert.equal(card(s).getAttribute("data-collapsed"), "true", "precondition: card collapsed");

  s.tts.set("n1");
  ttsChanged(s);

  assert.equal(accordion(s).getAttribute("data-collapsed"), "false", "the date accordion stayed shut");
  assert.equal(card(s).getAttribute("data-collapsed"), "false", "the sender card stayed shut");
  assert.equal(s.scrolls(), 1, "the speaking bubble was never scrolled to");
  s.renderer.unmount();
});

test("the expansions PERSIST, as legacy's do — a reveal is not a temporary peek", () => {
  // Legacy's expandSenderCard routes through toggleSenderCard, which writes the same
  // collapse state a click does. A reveal that only touched the DOM would be undone by
  // the next render's reapplyAccordionCollapse.
  const s = setup();
  collapseBoth(s);
  s.tts.set("n1");
  ttsChanged(s);

  assert.deepEqual(
    s.viewState.writes.filter(([ , v ]) => v === false).map(([ id ]) => id).sort(),
    [ "date::sess_42::2026-05-05", "sender::sess_42" ].sort(),
    "the expansion was not persisted, so the next render would re-collapse it",
  );
  s.renderer.unmount();
});

test("🔴 a REFRESH at the same id does NOT re-expand — the page must not fight the operator", () => {
  // THE TEST THIS FILE EXISTS FOR. refreshActiveTts runs on every render and every audio
  // state change; legacy's reveal is a one-shot per utterance. Without the change-guard,
  // collapsing a card mid-playback would snap it back open on the very next refresh.
  const s = setup();
  s.tts.set("n1");
  ttsChanged(s);      // the real reveal
  const after = s.scrolls();

  collapseBoth(s);                               // the operator deliberately collapses it
  ttsChanged(s);      // a repaint at the SAME utterance

  assert.equal(card(s).getAttribute("data-collapsed"), "true",
    "a refresh re-expanded a card the operator had just collapsed");
  assert.equal(s.scrolls(), after, "a refresh scrolled again at the same utterance");
  s.renderer.unmount();
});

test("a NEW utterance reveals again — the guard is per-id, not once-per-page", () => {
  const s = setup();
  s.tts.set("n1");
  ttsChanged(s);
  const after = s.scrolls();

  collapseBoth(s);
  s.tts.set("n2");                               // a different utterance
  ttsChanged(s);

  assert.equal(card(s).getAttribute("data-collapsed"), "false", "the second utterance did not reveal");
  assert.equal(s.scrolls(), after + 1, "the second utterance did not scroll");
  s.renderer.unmount();
});

test("the SAME utterance revealed again after playback stops — a replay is not 'already seen'", () => {
  // current() → null between the two plays. Treating the repeat as already-revealed would
  // leave a replay silent-on-screen, which is exactly when an operator looks for the source.
  const s = setup();
  s.tts.set("n1");
  ttsChanged(s);
  const after = s.scrolls();

  s.tts.set(null);
  ttsChanged(s);      // playback stops
  collapseBoth(s);
  s.tts.set("n1");                               // the same utterance plays again
  ttsChanged(s);

  assert.equal(card(s).getAttribute("data-collapsed"), "false", "the replay did not reveal");
  assert.equal(s.scrolls(), after + 1, "the replay did not scroll");
  s.renderer.unmount();
});

test("an ALREADY-EXPANDED card is not written to the store — a reveal only undoes collapse", () => {
  // Writing `false` over an already-false entry is harmless but noisy, and it would make
  // the persistence assertion above unable to tell a real expansion from a no-op.
  const s = setup();                             // nothing collapsed
  s.tts.set("n1");
  ttsChanged(s);

  assert.deepEqual(s.viewState.writes, [], "a reveal wrote collapse state for an open card");
  s.renderer.unmount();
});
