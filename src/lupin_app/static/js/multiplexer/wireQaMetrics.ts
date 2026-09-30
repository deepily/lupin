/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-1b — the Q&A metrics' audio-side capture point.
//
// §6a ruling 12 split the TTT/TTFA/RTT instrumentation out of B-1 because its
// capture points span the socket and the audio pipeline, which no Phase B section
// owns. Two of the three now live where the events are:
//
//   the SUBMIT clock  QaStore.submit()          — B-1, already landed
//   the TTT stamp     QaStore's tts_job_request — B-1, already landed
//   the REQUEST clock wireTtsPlayback, before the POST   — B-1b, this row
//   the FIRST AUDIO   this wire                          — B-1b, this row
//
// Legacy's counterpart is the `isFirstChunk` branch in its PCM schedule path, which
// stamps `metricsFirstAudioTime` and then calls updateMetricsTTFA + updateMetricsRTT
// together. QaStore.noteFirstAudio() does both from one call, so this wire is the
// thin thing it looks like: translate one bus event into one store call.
//
// 🔴 WHY A SEPARATE WIRE AND NOT A SUBSCRIPTION INSIDE QaStore. QaStore would then
// depend on the audio pipeline to be constructed at all, which makes the Q&A pane
// untestable without an AudioStore and couples two rows that §6a deliberately split.
// The boot seam is where the two meet; that is what a wire is for.

import type { EventBus } from "./shared/EventBus";
import type { StoreAudioChunkDecodedPayload } from "./shared/types";

/** The one thing this wire calls (parity B-1b). */
export interface QaFirstAudioObserver {
  noteFirstAudio(): void;
}

/**
 * Subscribe the first-audio capture point.
 *
 * Requires:
 *   - bus is a live EventBus; observer exposes noteFirstAudio()
 *
 * Ensures:
 *   - the FIRST decoded chunk of each utterance calls noteFirstAudio() exactly once
 *   - every later chunk of that utterance calls nothing — TTFA is time to the first
 *     audio, and stamping on each chunk would overwrite it with the last one
 *   - the NEXT utterance stamps again, because the flag the payload carries is
 *     per-utterance rather than a burst counter (see StoreAudioChunkDecodedPayload)
 *   - returns the bus unsubscriber (page-lifetime in boot; disposed in tests)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as wireTtsPlayback.ts).
export function wireQaMetrics(
  bus      : EventBus,
  observer : QaFirstAudioObserver,
): () => void {
  return bus.on<StoreAudioChunkDecodedPayload>( "store_audio_chunk_decoded", ( e ) => {
    if ( !e.payload.firstInUtterance ) return;
    observer.noteFirstAudio();
  } );
}
