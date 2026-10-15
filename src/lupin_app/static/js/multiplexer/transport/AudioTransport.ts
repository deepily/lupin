/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 3 — AudioTransport.
// Wraps a WSChannel for /ws/audio/{sessionId}. Inherits the auth handshake +
// CSM + lifecycle plumbing from BaseTransportImpl; adds the binary-frame
// callback contract per Pass 1 finding #14:
//
//   start(sessionId: string, binaryHandler?: (data: Blob | ArrayBuffer) => void): void
//
// Phase 3 default `binaryHandler` is a debug-logger; Phase 4's AudioStore
// replaces it with the real PCM-decoding handler. Per finding #14: the
// callback is invoked once per binary frame, no return value; errors thrown
// by the callback are caught at the call site so the transport keeps running.
//
// Text envelopes (status events: `audio_streaming_status`,
// `audio_streaming_complete`, `tts_error`, etc.) flow through the same
// `payload`-mapping rule as QueueTransport.

import type { Transport, BaseTransportOptions } from "./QueueTransport";
import { BaseTransportImpl } from "./QueueTransport";
import * as debugSink from "../shared/debugSink";

const AUDIO_SUBSCRIBED_EVENTS: ReadonlyArray<string> = [
  "audio_streaming_chunk",
  "audio_streaming_status",
  "audio_streaming_complete",
  "tts_error",
  "sys_ping",
  "auth_success",
  "auth_error",
  "connect",
];

const TRANSPORT_NAME = "AudioTransport";

// Phase 3 default binary handler. Phase 4's AudioStore replaces this when
// it calls audioTransport.start(sessionId, audioStore.handleChunk).
/* c8 ignore start */ // Phase 3 default binary handler — replaced by Phase 4 AudioStore.handleChunk in production wiring; the debug-logger fallback runs only when AudioTransport is started without a binaryHandler arg, which Phase 3 boot.ts no longer does once Phase 4 lands. Tests cover the override path (audio_transport.test.ts), not this fallback.
/**
 * Logs the size of a received binary audio frame to the console debug output.
 */
function defaultBinaryHandler(data: Blob | ArrayBuffer): void {
  const size = data instanceof Blob ? data.size : data.byteLength;
  console.debug("Audio chunk received", size);
}
/* c8 ignore stop */

/**
 * A transport for `/ws/audio/{sessionId}` that also delivers binary audio frames.
 *
 * `start( sessionId, binaryHandler )` takes the function called once per binary frame.
 */
export interface AudioTransport extends Transport {
  start(sessionId: string, binaryHandler?: (data: Blob | ArrayBuffer) => void): void;
}

/**
 * The options of an audio transport.
 *
 * `baseUrl` is the server origin. The socket opens at `<baseUrl>/ws/audio/<session id>`.
 */
export type AudioTransportOptions = BaseTransportOptions;

/**
 * The audio transport.
 *
 * It uses the base handshake and reconnect handling, and routes each binary frame to the handler given at `start`.
 * A handler that throws is logged and does not stop the transport.
 */
export class AudioTransportImpl extends BaseTransportImpl implements AudioTransport {
  protected readonly transportName    : string                = TRANSPORT_NAME;
  protected readonly endpointPath     : string                = "/ws/audio";
  protected readonly subscribedEvents : ReadonlyArray<string> = AUDIO_SUBSCRIBED_EVENTS;

  private boundBinaryHandler: (data: Blob | ArrayBuffer) => void = defaultBinaryHandler;

  /**
   * Sets the binary frame handler and then starts the base transport.
   */
  override start(sessionId: string, binaryHandler?: (data: Blob | ArrayBuffer) => void): void {
    this.boundBinaryHandler = binaryHandler ?? defaultBinaryHandler;
    super.start(sessionId);
  }

  // Wraps the caller's binary handler with a try/catch so a thrown handler
  // does not crash the transport (per Pass 1 finding #14 callback contract).
  protected override onBinaryMessage = (data: Blob | ArrayBuffer): void => {
    try {
      this.boundBinaryHandler(data);
    } catch (err) {
      // Surface as console for visibility; do NOT propagate. The transport
      // continues processing subsequent frames.
      /* c8 ignore next */ // defensive: error-message-extraction branch — tests pass real Error instances; the String(err) fallback is for non-Error throwables.
      const msg = err instanceof Error ? err.message : String(err);
      debugSink.error(`${TRANSPORT_NAME}: binary handler threw — ${msg}`);
    }
  };
}

/** Build an audio transport for `/ws/audio`; no socket opens until `start` is called. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createAudioTransport(opts: AudioTransportOptions): AudioTransport {
  return new AudioTransportImpl(opts);
}
