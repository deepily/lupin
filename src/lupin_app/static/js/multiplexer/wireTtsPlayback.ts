/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (same as wireTtsIntent.ts:1).
// Multiplexer 4f14d38f — TTS playback request-initiation wire.
//
// THE MISSING MIDDLE of the TTS chain. F0-d (producer) enqueues onto
// TtsQueueStore; AudioStore/AudioTransport decode + SCHEDULE incoming PCM and
// self-advance on completion — but NOTHING asked the server to GENERATE the
// audio, so enqueued items never played (audio stayed idle forever). This wire
// closes the gap: when TtsQueueStore's active item rolls to a NEW notification it
// POSTs the text to the server, which streams PCM back over the session's
// /ws/audio socket → AudioStore plays → store_audio_ended → TtsQueueStore.advance().
//
// ENVELOPE (Tiberius-ratified, verified against BOTH server + legacy):
//   • The request is an HTTP POST to /api/get-speech-elevenlabs — NOT a /ws/audio
//     WebSocket send. /ws/audio is the RETURN CHANNEL ONLY (PCM chunks flow back
//     over it). Legacy sender: notifications.js playInstantTTS :4262-4293.
//   • Body { text, session_id }. `session_id` is THE routing key: the server
//     (speech.py get_tts_audio_elevenlabs :488 → register_session_user →
//     is_connected → stream_tts_hybrid) streams the PCM back to EXACTLY that
//     session's /ws/audio socket. So we send the MUX's OWN AUDIO session id (the
//     id AudioTransport bound /ws/audio with, boot.ts — NOT the queue socket's id,
//     row d2b1b59a) — a stale id would route PCM to the wrong socket (or 400). The server IGNORES the X-Session-ID header
//     (speech.py:488 only debug-prints headers) — it is DELIBERATELY OMITTED here,
//     NOT forgotten; the body session_id is authoritative.
//   • voice_id (766bb609): threaded from the item's per-session persona voice_id
//     when present → the sender's own voice; OMITTED when absent → server default
//     voice (Sam), legacy's null-voice_id case (notifications.js:4262-4293). The
//     omitted-branch body is byte-identical to the pre-766bb609 request. The
//     live-voice E2E (each session actually speaks in its own voice) is deferred
//     to post-switchover — the mux must be the live client to verify it.
//
// RE-REQUEST GUARD: fire the POST EXACTLY ONCE per new active notification. Track
// the last-requested id and request only when the active id rolls to a NEW
// non-null value. Same-id re-emits (pending-list churn while the same item plays)
// do NOT re-request; a null active (queue drained / cleared / stop-de-light)
// resets the guard WITHOUT requesting — so a later re-enqueue of the same id
// re-requests, and the advance→null final roll cannot loop into a request.

import type { EventBus } from "./shared/EventBus";
import type { TtsRequestFailedPayload, TtsRequestStartedPayload } from "./shared/types";
import type { TtsQueueStore } from "./stores/TtsQueueStore";
import type { AudioStore, TtsMode } from "./stores/AudioStore";
import type { ApiClient } from "./api/ApiClient";

// Narrow consume-surfaces (Pass-2 minimal-interface discipline).
export type TtsPlaybackActiveReader = Pick<TtsQueueStore, "activeItem">;
export type TtsPlaybackPoster       = Pick<ApiClient, "post">;
/** The one thing this wire asks AudioStore: which door to knock on (parity B-1). */
export type TtsPlaybackModeReader   = Pick<AudioStore, "ttsMode">;
/**
 * Parity B-1b — the TTFA clock's START. Legacy stamps `metricsTTSStartTime`
 * immediately before the fetch in BOTH playInstantTTS and playReliableTTS, with the
 * comment "Start timing BEFORE the fetch for accurate TTFA measurement". Stamping
 * after would hide the request's own latency inside the metric.
 */
export interface TtsPlaybackRequestObserver {
  noteTtsRequested(): void;
}

// PARITY B-1 — THE TWO DOORS, and they are not interchangeable.
//
// Legacy picks between them on every playback by reading `#tts-mode`
// (notifications.js:4287-4315): instant -> playInstantTTS, which POSTs
// /api/get-speech-elevenlabs (:4376) and streams PCM back over /ws/audio;
// reliable -> playReliableTTS, which POSTs /api/get-speech (:4436) and batches it
// through OpenAI. The BODY is the same on both ({ text, session_id, voice_id? })
// and the return channel is the same socket, so the branch is the URL alone.
//
// The multiplexer shipped the instant door only, so its `reliable` option would
// have been a painted-but-dead control. §6a ruling 3 puts the mode on AudioStore
// and makes this branch B-1's to build; B-7's direct-play path reuses it.
const TTS_ENDPOINTS: Readonly<Record<TtsMode, string>> = {
  instant  : "/api/get-speech-elevenlabs",
  reliable : "/api/get-speech",
};

/**
 * Subscribe the TTS playback request-initiation seam.
 *
 * Requires:
 *   - bus is a live EventBus; ttsQueue exposes activeItem(); apiClient exposes post()
 *   - sessionId is the mux's OWN /ws/audio session id (boot's audioSessionId,
 *     which AudioTransport bound the audio socket with) — the PCM routing key
 *   - modeReader exposes ttsMode() — the page-wide select's current value
 *   - observer, when given, exposes noteTtsRequested() — the TTFA clock's start
 *
 * Ensures:
 *   - each time the active item rolls to a NEW non-null id, POSTs
 *     { text, session_id } EXACTLY once — to /api/get-speech-elevenlabs in
 *     `instant` mode and /api/get-speech in `reliable`, the mode read at request
 *     time (parity B-1)
 *   - same-id re-emits do not re-request; a null active resets the guard
 *   - a failed POST degrades to silence, never a throw, and emits
 *     tts_request_failed{idHash} so the queue moves on (row 0b384107)
 *   - returns the bus unsubscriber (page-lifetime in boot; disposed in tests)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as wireTtsIntent.ts).
export function wireTtsPlayback(
  bus        : EventBus,
  ttsQueue   : TtsPlaybackActiveReader,
  apiClient  : TtsPlaybackPoster,
  sessionId  : string,
  modeReader : TtsPlaybackModeReader,
  /** Optional: omitted wherever the Q&A metrics are not in play (tests, and any
   *  future caller that does not own a metrics strip). */
  observer?  : TtsPlaybackRequestObserver,
): () => void {
  let lastRequestedId: string | null = null;
  return bus.on( "store_tts_queue_changed", () => {
    const active = ttsQueue.activeItem();
    if ( active === null ) {
      // Drained / cleared / stopped → reset so a later re-enqueue of the same id
      // re-requests, and the advance→null final roll makes no request.
      lastRequestedId = null;
      return;
    }
    if ( active.id_hash === lastRequestedId ) return;   // same item still active — no re-request
    lastRequestedId = active.id_hash;
    // 766bb609: base body { text, session_id }. Thread the sender's persona
    // voice_id when the item carries one (→ that session speaks in its own voice);
    // OMIT the key entirely when absent → server default voice (Sam), legacy's
    // null-voice_id case (notifications.js:4262-4293) — byte-identical to the
    // pre-766bb609 body, so a persona-less notification is unaffected.
    const body: { text: string; session_id: string; voice_id?: string } = {
      text       : active.ttsText ?? "",
      session_id : sessionId,
    };
    if ( active.voice_id !== undefined ) body.voice_id = active.voice_id;
    // Row 0b384107 — a failed request is the end of that item, as legacy's playTTS
    // catch treats it (notifications.js:22394-22396): announce it so TtsQueueStore
    // releases the slot. Silence, never a crash.
    const idHash = active.id_hash;
    // B-1b — the TTFA clock starts HERE, before the POST, exactly as legacy's
    // "Start timing BEFORE the fetch" comment requires.
    if ( observer !== undefined ) observer.noteTtsRequested();
    // Row 26bfde78 — the stall watchdog arms HERE, on the request, not on the
    // first chunk. A request whose stream never yields a single chunk reaches the
    // audio layer not at all, so a watchdog armed on arriving audio cannot see it;
    // this item would hold the TTS slot, and every Action Required card behind it
    // (A-2 #2d), with nothing on screen and nothing in the console to say why.
    bus.emit<TtsRequestStartedPayload>( {
      type    : "tts_request_started",
      payload : { idHash },
      source  : "wireTtsPlayback",
      ts      : Date.now(),
    } );
    // Read the mode at REQUEST time, never at wire time: the select can change
    // between two items, and legacy re-reads it per playback for the same reason.
    //
    // 🔴 THE ITEM'S OWN MODE WINS WHEN IT CARRIES ONE (parity B-7, María 🌸's
    // review of cfe8a348). Legacy's `playTTS( text, mode )` branches on its
    // ARGUMENT and never consults `#tts-mode`, so `testTTS( 'reliable' )` really
    // does exercise the reliable door. This wire read only the page-wide value,
    // which made "Test Reliable TTS" post to the INSTANT door on any default
    // page — and report success, because the POST was fine. Absent → the
    // page-wide mode, which is every other caller.
    const mode = active.tts_mode ?? modeReader.ttsMode();
    void apiClient.post( TTS_ENDPOINTS[ mode ], body )
      .catch( () => {
        bus.emit<TtsRequestFailedPayload>( {
          type    : "tts_request_failed",
          payload : { idHash },
          source  : "wireTtsPlayback",
          ts      : Date.now(),
        } );
      } );
  } );
}
