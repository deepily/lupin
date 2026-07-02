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
//     session's /ws/audio socket. So we send the MUX's OWN boot sessionId (the id
//     AudioTransport bound /ws/audio with, boot.ts) — a stale id would route PCM
//     to the wrong socket (or 400). The server IGNORES the X-Session-ID header
//     (speech.py:488 only debug-prints headers) — it is DELIBERATELY OMITTED here,
//     NOT forgotten; the body session_id is authoritative.
//   • voice_id is OMITTED → the server falls back to its configured default voice
//     (Sam), matching legacy's null-voice_id case (notifications.js:4262-4293).
//     Per-session persona voice is a NAMED follow-on (P3 store item) — NOT MVP;
//     do not "fix" this omission.
//
// RE-REQUEST GUARD: fire the POST EXACTLY ONCE per new active notification. Track
// the last-requested id and request only when the active id rolls to a NEW
// non-null value. Same-id re-emits (pending-list churn while the same item plays)
// do NOT re-request; a null active (queue drained / cleared / stop-de-light)
// resets the guard WITHOUT requesting — so a later re-enqueue of the same id
// re-requests, and the advance→null final roll cannot loop into a request.

import type { EventBus } from "./shared/EventBus";
import type { TtsQueueStore } from "./stores/TtsQueueStore";
import type { ApiClient } from "./api/ApiClient";

// Narrow consume-surfaces (Pass-2 minimal-interface discipline).
export type TtsPlaybackActiveReader = Pick<TtsQueueStore, "activeItem">;
export type TtsPlaybackPoster       = Pick<ApiClient, "post">;

/**
 * Subscribe the TTS playback request-initiation seam.
 *
 * Requires:
 *   - bus is a live EventBus; ttsQueue exposes activeItem(); apiClient exposes post()
 *   - sessionId is the mux's OWN /ws/audio session id (the boot sessionId
 *     AudioTransport bound the audio socket with) — the PCM routing key
 *
 * Ensures:
 *   - each time the active item rolls to a NEW non-null id, POSTs
 *     { text, session_id } to /api/get-speech-elevenlabs EXACTLY once
 *   - same-id re-emits do not re-request; a null active resets the guard
 *   - a failed POST degrades to silence (fire-and-forget), never a throw
 *   - returns the bus unsubscriber (page-lifetime in boot; disposed in tests)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as wireTtsIntent.ts).
export function wireTtsPlayback(
  bus       : EventBus,
  ttsQueue  : TtsPlaybackActiveReader,
  apiClient : TtsPlaybackPoster,
  sessionId : string,
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
    void apiClient.post( "/api/get-speech-elevenlabs", {
      text       : active.ttsText ?? "",
      session_id : sessionId,
    } ).catch( () => { /* fire-and-forget: a failed TTS request degrades to silence, not a crash */ } );
  } );
}
