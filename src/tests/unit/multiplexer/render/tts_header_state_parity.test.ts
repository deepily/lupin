// Parity A-2 #3d (row 0db76ed7, 2026-09-18, Chloé 🗼) — the TTS headers.
// Mirrors legacy `updateTTSQueueSection` (notifications.js:22656-22716): one
// `<h3>` in three states. A manual pause WITH an active item reads
// "Paused: <queue + active>" and puts `.paused` on the section (:22688-22694).
// Focus mode reads "Paused: <queue> waiting" and puts `.focus-mode` on it
// (:22696-22703). Otherwise it reads "🔊 Playing: <queue + active>"
// (:22704-22710). The count is set at :22713-22715.
// The multiplexer has two headers, the section bar and the body's
// `.tts-playing-header`. Both follow that machine, and the pane root carries
// the state class the way legacy's `#tts-queue-section` did.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTtsQueueStore, type TtsQueueStore } from "../../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import {
  createTtsChromeRenderer,
  type AudioStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TtsChromeRenderer";
import type {
  AudioPlaybackState,
  StoreAudioStateChangePayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => { document.body.replaceChildren(); });

type Bus = ReturnType<typeof createEventBusForTesting>;

interface Pane {
  bus   : Bus;
  root  : HTMLElement;
  queue : TtsQueueStore;
  unmount(): void;
  setAudio(state: AudioPlaybackState): void;
}

// The real queue store and the real renderer on one bus, with a synchronous
// RAF. The audio store is a fake whose state the test moves, emitting the same
// store_audio_state_change the real AudioStore emits.
function mountPane(): Pane {
  const bus  = createEventBusForTesting();
  const root = document.createElement("section");
  root.id = "tts-pane";
  document.body.appendChild(root);
  let state: AudioPlaybackState = "idle";
  const audio: AudioStoreLike = {
    state : () => state,
    burstLength : () => 0,
    pause : () => {}, resume : () => {}, stop : () => {}, skip : () => {},
  };
  const queue = createTtsQueueStore({ bus, nowFn: () => 0 });
  const renderer = createTtsChromeRenderer({
    eventBus                : bus,
    stores                  : { audio, ttsQueue: queue },
    requestAnimationFrameFn : (cb) => { cb(0); return 1; },
    cancelAnimationFrameFn  : () => {},
  });
  renderer.mount(root);
  return {
    bus, root, queue,
    unmount: () => renderer.unmount(),
    setAudio(next) {
      const prev = state;
      state = next;
      bus.emit<StoreAudioStateChangePayload>({
        type: "store_audio_state_change", payload: { state: next, prev }, source: "test", ts: 0,
      });
    },
  };
}

function bodyHeader(root: HTMLElement): HTMLElement {
  const el = root.querySelector<HTMLElement>(".tts-playing-header");
  assert.ok(el !== null, "the body header renders");
  return el;
}

function barText(root: HTMLElement): string {
  return (root.querySelector('[data-testid="multiplexer-tts-header"] h3')?.textContent ?? "").trim();
}

function enqueueThree(queue: TtsQueueStore): void {
  queue.enqueue({ id_hash: "a", ttsText: "one" });
  queue.enqueue({ id_hash: "b", ttsText: "two" });
  queue.enqueue({ id_hash: "c", ttsText: "three" });
}

test("#3d playing: both headers count active + pending, and neither state class is set", () => {
  const { root, queue, setAudio } = mountPane();
  enqueueThree(queue);
  setAudio("playing");

  assert.equal(bodyHeader(root).textContent, "🔊 Playing: 3", "1 active + 2 pending");
  assert.equal(barText(root), "🔊 Playing 3");
  assert.equal(root.classList.contains("paused"), false);
  assert.equal(root.classList.contains("focus-mode"), false);
});

test("#3d manual pause: both headers read Paused with active + pending, and the pane carries .paused", () => {
  const { root, queue, setAudio } = mountPane();
  enqueueThree(queue);
  setAudio("playing");
  setAudio("paused");

  assert.equal(bodyHeader(root).textContent, "Paused: 3");
  assert.equal(bodyHeader(root).classList.contains("paused"), true);
  assert.equal(barText(root), "Paused 3", "the bar title follows the pause");
  assert.equal(root.classList.contains("paused"), true);
  assert.equal(root.classList.contains("focus-mode"), false);
});

test("#3d focus mode: both headers read Paused … waiting with the pending count, and the pane carries .focus-mode", () => {
  const { bus, root, queue, setAudio } = mountPane();
  queue.enqueue({ id_hash: "ar", ttsText: "approve?", action_required: true });
  queue.enqueue({ id_hash: "b", ttsText: "two" });
  queue.enqueue({ id_hash: "c", ttsText: "three" });
  setAudio("playing");
  setAudio("ended");
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
  assert.equal(queue.focusMode(), true, "precondition: the finished action-required item entered focus");

  assert.equal(bodyHeader(root).textContent, "Paused: 2 waiting");
  assert.equal(bodyHeader(root).classList.contains("focus-mode"), true);
  assert.equal(barText(root), "Paused 2 waiting");
  assert.equal(root.classList.contains("focus-mode"), true);
  assert.equal(root.classList.contains("paused"), false);

  queue.resumeFocus();
  assert.equal(root.classList.contains("focus-mode"), false, "leaving focus clears the class");
  assert.equal(barText(root), "🔊 Playing 2");
});

test("#3d play after a pause: the title and class revert", () => {
  const { root, queue, setAudio } = mountPane();
  enqueueThree(queue);
  setAudio("playing");
  setAudio("paused");
  setAudio("playing");

  assert.equal(barText(root), "🔊 Playing 3");
  assert.equal(bodyHeader(root).textContent, "🔊 Playing: 3");
  assert.equal(root.classList.contains("paused"), false);
});

test("#3d a pause with NO active item is not the Paused state (legacy's `&& this.activeTTSItem`, :22688)", () => {
  const { root, queue, setAudio } = mountPane();
  queue.enqueue({ id_hash: "a", ttsText: "one" });
  setAudio("playing");
  setAudio("paused");
  queue.removeById("a");   // the operator deletes the paused item's card

  assert.equal(queue.activeItem(), null, "precondition: audio still paused, nothing active");
  assert.equal(barText(root), "🔊 Playing 0");
  assert.equal(root.classList.contains("paused"), false);
});

test("#3d empty queue: the bar reads 🔊 Playing 0 with no state class", () => {
  const { root } = mountPane();
  assert.equal(barText(root), "🔊 Playing 0");
  assert.equal(root.classList.contains("paused"), false);
  assert.equal(root.classList.contains("focus-mode"), false);
});

test("#3d unmount leaves no state class on the pane root", () => {
  const { root, queue, setAudio, unmount } = mountPane();
  enqueueThree(queue);
  setAudio("playing");
  setAudio("paused");
  assert.equal(root.classList.contains("paused"), true, "precondition");

  unmount();
  assert.equal(root.classList.contains("paused"), false);
  assert.equal(root.classList.contains("focus-mode"), false);
});
