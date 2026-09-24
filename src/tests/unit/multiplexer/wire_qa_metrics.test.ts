// Parity B-1b — wireQaMetrics + the first-chunk flag it keys on.
//
// LEGACY UNDER TEST, by symbol:
//   notifications.js  playInstantTTS / playReliableTTS — `metricsTTSStartTime`
//                     stamped immediately BEFORE the fetch
//   notifications.js  the PCM schedule path's `isFirstChunk` branch — stamps
//                     `metricsFirstAudioTime`, then updateMetricsTTFA + updateMetricsRTT
//
// 🔴 THE CENTRAL CLAIM, AND WHY IT IS TESTED ACROSS TWO UTTERANCES RATHER THAN ONE.
// The obvious discriminator for "first chunk" is `burstLength() === 1`, and it is
// WRONG: `chunksInBurst` is reset by skip() and stop() only, never by the natural
// completion path, so it accumulates across utterances. A single-utterance test
// cannot tell the two implementations apart — both pass. The second utterance is
// what separates them, and that is the test that would have caught it.
//
// Run: npx tsx --test src/tests/unit/multiplexer/wire_qa_metrics.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { wireQaMetrics } from "../../../lupin_app/static/js/multiplexer/wireQaMetrics";
import type { StoreAudioChunkDecodedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

function makeObserver(): { calls: number; noteFirstAudio: () => void } {
  const o = { calls: 0, noteFirstAudio: (): void => { o.calls += 1; } };
  return o;
}

function chunk(
  bus              : ReturnType<typeof createEventBusForTesting>,
  firstInUtterance : boolean,
): void {
  bus.emit<StoreAudioChunkDecodedPayload>( {
    type    : "store_audio_chunk_decoded",
    payload : { durationMs: 20, sampleRate: 24000, frameCount: 480, firstInUtterance },
    source  : "test",
    ts      : 0,
  } );
}

test( "the first chunk of an utterance stamps exactly once", () => {
  const bus = createEventBusForTesting();
  const o   = makeObserver();
  wireQaMetrics( bus, o );

  chunk( bus, true );
  assert.equal( o.calls, 1 );
} );

test( "every later chunk of the same utterance stamps NOTHING", () => {
  // TTFA is time to the FIRST audio. Stamping per chunk would overwrite it with the
  // last one, and the metric would silently become time-to-last-audio.
  const bus = createEventBusForTesting();
  const o   = makeObserver();
  wireQaMetrics( bus, o );

  chunk( bus, true );
  chunk( bus, false );
  chunk( bus, false );
  assert.equal( o.calls, 1 );
} );

test( "a SECOND utterance stamps again — the discriminator is per-utterance, not a burst counter", () => {
  const bus = createEventBusForTesting();
  const o   = makeObserver();
  wireQaMetrics( bus, o );

  chunk( bus, true );  chunk( bus, false );   // utterance 1
  chunk( bus, true );  chunk( bus, false );   // utterance 2
  assert.equal( o.calls, 2 );
} );

test( "the unsubscriber stops the wire", () => {
  const bus = createEventBusForTesting();
  const o   = makeObserver();
  const off = wireQaMetrics( bus, o );

  off();
  chunk( bus, true );
  assert.equal( o.calls, 0 );
} );
