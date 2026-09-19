// Parity A-2 #3a (row 0c9f5d21, 2026-09-18, Chloé 🗼) — the TTS pane is visible
// iff its toolbar button is active, whatever the queue holds. Mirrors legacy
// `updateTTSQueueSection` (notifications.js:22646-22671, predicate at :22662)
// as it actually renders: `.collapsible-section.section-hidden` carries
// `display: none !important` (notifications.css:111-113), which beats the
// inline `display: block` the predicate writes, and the toolbar flips `active`
// and `section-hidden` together — so "an item exists OR the button is active"
// reduces to "the button is active". Mr. Radio ruled 2026-09-18 that legacy's
// fresh-browser cold-hidden state (#tts-queue-section, notifications.html:434) is a legacy defect,
// not ported; this file PINS the behaviour so a literal port of the predicate,
// which would let an arrival reveal a toolbar-hidden pane, reddens here.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTtsQueueStore, type TtsQueueStore } from "../../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import {
  createTtsChromeRenderer,
  type AudioStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TtsChromeRenderer";
import {
  createSectionToolbarRenderer,
  type ViewStateStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/SectionToolbarRenderer";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => { document.body.replaceChildren(); });

function makeViewState(): ViewStateStoreLike {
  const prefs = new Map<string, boolean>();
  return {
    isSectionVisible     : (id) => prefs.get(id) !== false,
    setSectionVisible    : (id, v) => { prefs.set(id, v); },
    getHiddenSectionIds  : () => [ ...prefs.entries() ].filter(([ , v ]) => !v).map(([ k ]) => k),
    hasSectionPreference : (id) => prefs.has(id),
  };
}

const idleAudio: AudioStoreLike = {
  state       : () => "idle",
  burstLength : () => 0,
  pause       : () => {},
  resume      : () => {},
  stop        : () => {},
  skip        : () => {},
};

// The assembled pane: the real toolbar renderer, the real queue store and the
// real chrome renderer, wired through one bus with a synchronous RAF.
function mountPane(): { pane: HTMLElement; button: HTMLElement; queue: TtsQueueStore } {
  const bus  = createEventBusForTesting();
  const pane = document.createElement("section");
  pane.id = "tts-pane";
  const toolbarRoot = document.createElement("div");
  document.body.append(toolbarRoot, pane);

  const queue = createTtsQueueStore({ bus, nowFn: () => 0 });
  createSectionToolbarRenderer({ stores: { viewState: makeViewState() } }).mount(toolbarRoot);
  createTtsChromeRenderer({
    eventBus                : bus,
    stores                  : { audio: idleAudio, ttsQueue: queue },
    requestAnimationFrameFn : (cb) => { cb(0); return 1; },
    cancelAnimationFrameFn  : () => {},
  }).mount(pane);

  const button = toolbarRoot.querySelector<HTMLElement>('.toolbar-btn[data-section="tts-pane"]');
  assert.ok(button !== null, "the toolbar must carry a tts-pane button");
  return { pane, button, queue };
}

function isShown(pane: HTMLElement): boolean {
  return !pane.hidden && !pane.classList.contains("section-hidden");
}

function emptyPanel(pane: HTMLElement): Element | null {
  return pane.querySelector(".tts-queue-empty-state");
}

test("#3a cold load: the button is active, so the EMPTY pane is shown with its empty panel", () => {
  const { pane, button } = mountPane();
  assert.equal(button.classList.contains("active"), true);
  assert.equal(isShown(pane), true);
  assert.ok(emptyPanel(pane) !== null, "an empty queue under an active button shows 🔇 Nothing in the queue");
});

test("#3a toolbar off: an arriving item does NOT reveal the pane (section-hidden wins, notifications.css:111)", () => {
  const { pane, button, queue } = mountPane();
  button.click();
  assert.equal(isShown(pane), false);

  queue.enqueue({ id_hash: "a", ttsText: "hello" });
  queue.enqueue({ id_hash: "b", ttsText: "world" });

  assert.equal(queue.current(), "a", "the item really is in the queue");
  assert.equal(pane.hidden, true);
  assert.equal(pane.classList.contains("section-hidden"), true);
  assert.equal(button.classList.contains("active"), false);
});

test("#3a toolbar on again with an EMPTY queue: the pane shows its empty panel", () => {
  const { pane, button } = mountPane();
  button.click();
  button.click();
  assert.equal(button.classList.contains("active"), true);
  assert.equal(isShown(pane), true);
  assert.ok(emptyPanel(pane) !== null);
});

test("#3a toolbar on: queue mutations never hide the pane, emptying it included", () => {
  const { pane, queue } = mountPane();
  queue.enqueue({ id_hash: "a", ttsText: "hello" });
  assert.equal(isShown(pane), true);
  assert.ok(emptyPanel(pane) === null, "an item replaces the empty panel");

  queue.clear();
  assert.equal(isShown(pane), true);
  assert.ok(emptyPanel(pane) !== null);
});
