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
function defaultBinaryHandler(data: Blob | ArrayBuffer): void {
  const size = data instanceof Blob ? data.size : data.byteLength;
  console.debug("Audio chunk received", size);
}

export interface AudioTransport extends Transport {
  start(sessionId: string, binaryHandler?: (data: Blob | ArrayBuffer) => void): void;
}

export type AudioTransportOptions = BaseTransportOptions;

export class AudioTransportImpl extends BaseTransportImpl implements AudioTransport {
  protected readonly transportName    : string                = TRANSPORT_NAME;
  protected readonly endpointPath     : string                = "/ws/audio";
  protected readonly subscribedEvents : ReadonlyArray<string> = AUDIO_SUBSCRIBED_EVENTS;

  private boundBinaryHandler: (data: Blob | ArrayBuffer) => void = defaultBinaryHandler;

  // Re-typed `start` to accept the optional binary handler. The base class's
  // `start(sessionId)` is called; we set the bound handler first so
  // `openSocket()` (invoked from base.start) sees it.
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
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`${TRANSPORT_NAME}: binary handler threw — ${msg}`);
    }
  };
}

export function createAudioTransport(opts: AudioTransportOptions): AudioTransport {
  return new AudioTransportImpl(opts);
}
