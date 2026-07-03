/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (same as TtsQueueStore.ts:1).
// Multiplexer F0-d — TTS producer→consumer wire.
//
// NotificationStore emits `store_notification_tts_intent` for every SPOKEN
// new-arrival (the gate + ttsText derivation live at the emit site — see
// NotificationStore.onQueueUpdate). Per the codebase idiom (stores EMIT, boot
// WIRES consumers — two stores must never couple directly), this boot-level glue
// subscribes to that intent and appends the item onto TtsQueueStore. Extracted
// from bootMultiplexer() as its own unit so it is 100% c8-gated (boot.ts is the
// esbuild entry point, Playwright-tested, not unit-covered).
//
// Ported from legacy `notifications.js:5934-5942` (the setTimeout(addToTTSQueue))
// — MINUS the 300ms ding-settle delay, which is deferred (watch-out #5): the mux
// enqueues synchronously on intent. TtsQueueStore auto-promotes the head when
// nothing is speaking, so ordering is preserved without the delay.

import type { EventBus } from "./shared/EventBus";
import type { StoreNotificationTtsIntentPayload, TtsQueueItem } from "./shared/types";
import type { TtsQueueStore } from "./stores/TtsQueueStore";

// The narrow consume-surface: the wire touches ONLY enqueue() (never advance /
// current / clear) — Pass-2 minimal-interface discipline.
export type TtsQueueEnqueuer = Pick<TtsQueueStore, "enqueue">;

/**
 * Subscribe the TTS-intent producer seam to the TtsQueueStore consumer.
 *
 * Requires:
 *   - bus is a live EventBus
 *   - ttsQueue exposes enqueue()
 *   - nowFn returns the ms-epoch stamp for the item's addedAt (injected for
 *     deterministic tests; boot passes () => Date.now())
 *
 * Ensures:
 *   - every store_notification_tts_intent event enqueues exactly one TtsQueueItem
 *     carrying { id_hash, ttsText, addedAt, action_required } + voice_id when the
 *     intent payload carries one (omitted otherwise)
 *   - returns the bus unsubscriber (page-lifetime in boot; disposed in tests)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as TtsQueueStore.ts:221).
export function wireNotificationTtsIntent(
  bus      : EventBus,
  ttsQueue : TtsQueueEnqueuer,
  nowFn    : () => number,
): () => void {
  return bus.on<StoreNotificationTtsIntentPayload>(
    "store_notification_tts_intent",
    // 70cbff3e (A1 producer-seam): stamp action_required onto the item so
    // TtsQueueStore can decide focus-mode ENTER at store_audio_ended.
    ( e ) => {
      const queued: TtsQueueItem = {
        id_hash         : e.payload.id_hash,
        ttsText         : e.payload.ttsText,
        addedAt         : nowFn(),
        action_required : e.payload.action_required,
      };
      // 766bb609: stamp voice_id ONLY when present, so a persona-less notification
      // enqueues a byte-identical (pre-766bb609) item → server default voice.
      if ( e.payload.voice_id !== undefined ) queued.voice_id = e.payload.voice_id;
      ttsQueue.enqueue( queued );
    },
  );
}
