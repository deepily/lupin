/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — one session id per WebSocket (row d2b1b59a, FINDING 5).
//
// The server keeps ONE socket and ONE subscription list per session id
// (WebSocketManager.active_connections / session_subscriptions). The multiplexer
// used to open /ws/queue and /ws/audio under the SAME id, so whichever socket
// registered last owned both maps. When that was the audio socket, the server
// declined every notification event to this tab as "not subscribed" — measured
// 2026-09-10: the P0 petition asks and every ordinary ask never reached it.
// Legacy notifications.js already opens the two sockets on separate ids
// (getOrCreateSessionId( 'queue' ) / ( 'audio' )).
//
// Write-up: src/rnd/2026.09.10-multiplexer-misses-petition-ask.md

import type { StorageService } from "./StorageService";

export type TransportSessionIdStorage = Pick<
  StorageService,
  "getSessionId" | "setSessionId" | "getAudioSessionId" | "setAudioSessionId"
>;

export interface TransportSessionIds {
  queueSessionId : string;
  audioSessionId : string;
}

// Attempts to draw an audio id that differs from the queue id before failing
// loud. The production generator has 100 combinations, so 32 straight
// collisions is a broken generator, not bad luck.
export const MAX_AUDIO_ID_ATTEMPTS = 32;

/**
 * Resolve the queue and audio WebSocket session ids, generating and persisting
 * whichever is missing.
 *
 * Requires:
 *   - storage exposes the queue + audio session-id accessors
 *   - generate returns a server-valid session id ("adjective noun")
 *
 * Ensures:
 *   - queueSessionId is the stored queue id, or a newly generated + persisted one
 *   - audioSessionId !== queueSessionId, always
 *   - a stored audio id is reused unless it is missing or equals the queue id,
 *     in which case a fresh distinct id is generated and persisted
 *
 * Raises:
 *   - Error if generate returns the queue id MAX_AUDIO_ID_ATTEMPTS times in a row
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as wireTtsPlayback.ts) — it followed the declaration when the helper was inlined, so it is not a real branch.
export function resolveTransportSessionIds(
  storage  : TransportSessionIdStorage,
  generate : () => string,
): TransportSessionIds {
  let queueSessionId = storage.getSessionId();
  if (queueSessionId === null) {
    queueSessionId = generate();
    storage.setSessionId(queueSessionId);
  }

  const storedAudioSessionId = storage.getAudioSessionId();
  if (storedAudioSessionId !== null && storedAudioSessionId !== queueSessionId) {
    return { queueSessionId, audioSessionId: storedAudioSessionId };
  }

  for (let attempt = 0; attempt < MAX_AUDIO_ID_ATTEMPTS; attempt++) {
    const candidate = generate();
    if (candidate !== queueSessionId) {
      storage.setAudioSessionId(candidate);
      return { queueSessionId, audioSessionId: candidate };
    }
  }
  throw new Error(
    `multiplexer: could not draw an audio session id distinct from the queue id "${queueSessionId}" ` +
    `in ${MAX_AUDIO_ID_ATTEMPTS} attempts`,
  );
}
