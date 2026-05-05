// Multiplexer Phase 4 — pcm-decoder.
//
// Pure(ish) PCM16 → AudioBuffer conversion.
//
// Per D-A ratification 2026-05-04 PM: server emits raw 24kHz PCM16, NOT an
// encoded container. AudioContext.decodeAudioData expects WAV/MP3/Opus
// headers and would reject every frame, so we do the bit-banging math
// directly. Ports legacy `notifications.js:4580-4596`.
//
// Signature deviation from design (recorded in execution log Phase 4 § "Spec
// drifts re-audited at execute time"):
//   Design says `pcm16ToAudioBuffer(buf, sampleRate=24000): AudioBuffer`.
//   Actual impl takes an `AudioContext` as a required argument because
//   `AudioBuffer` cannot be constructed without one in browser-portable code
//   (`new AudioBuffer(...)` is supported in modern browsers but doesn't add a
//   way to wire `copyToChannel` results into a context's playback graph;
//   `audioContext.createBuffer(1, frameCount, sampleRate)` is the canonical
//   path the legacy code uses, and it requires the context anyway). The
//   audioContext arg is invariant — AudioStore manages a single lazy
//   AudioContext per Q6 ratification and threads it through to the decoder.
//
// Stateless: every call does fresh allocation; no module-level mutable state.

// Minimal AudioContext shape we depend on. Tests inject a stub satisfying
// this contract — full Web Audio API surface is not needed.
export interface AudioContextLike {
  createBuffer(numberOfChannels: number, length: number, sampleRate: number): AudioBufferLike;
}

export interface AudioBufferLike {
  copyToChannel(source: Float32Array, channelNumber: number, bufferOffset?: number): void;
  readonly sampleRate: number;
  readonly length: number;
  readonly numberOfChannels: number;
  readonly duration: number;
}

const SIGNED_16BIT_MAX_PLUS_ONE = 32768.0;

/**
 * Convert a raw 24kHz PCM16 ArrayBuffer to a mono AudioBuffer.
 *
 * Requires:
 *   - buf is an ArrayBuffer with byteLength divisible by 2 (Int16 alignment)
 *   - audioContext is a live AudioContext (or AudioContextLike test stub)
 *   - sampleRate is a positive integer (default 24000 — server contract)
 *
 * Ensures:
 *   - Returns an AudioBuffer with 1 channel, length = buf.byteLength / 2,
 *     and the requested sampleRate
 *   - Does not retain or mutate the input ArrayBuffer
 *
 * Raises:
 *   - Error("pcm16: buffer length N not a multiple of 2") if alignment fails
 *   - Whatever the audioContext throws (e.g. OOM, sampleRate out of range)
 */
export function pcm16ToAudioBuffer(
  buf          : ArrayBuffer,
  audioContext : AudioContextLike,
  sampleRate   : number = 24000,
): AudioBufferLike {
  if (buf.byteLength === 0) {
    throw new Error("pcm16: empty buffer");
  }
  if (buf.byteLength % 2 !== 0) {
    throw new Error(`pcm16: buffer length ${buf.byteLength} not a multiple of 2`);
  }

  const pcm16   = new Int16Array(buf);
  const float32 = new Float32Array(pcm16.length);
  for (let i = 0; i < pcm16.length; i++) {
    // Convert from signed 16-bit [-32768, 32767] to float [-1.0, 1.0].
    // noUncheckedIndexedAccess: pcm16[i] is `number | undefined`; the loop
    // bound guarantees defined access, so the non-null assertion is safe.
    float32[i] = (pcm16[i] as number) / SIGNED_16BIT_MAX_PLUS_ONE;
  }

  const audioBuffer = audioContext.createBuffer(1, float32.length, sampleRate);
  audioBuffer.copyToChannel(float32, 0, 0);
  return audioBuffer;
}

/**
 * Async wrapper for Blob inputs. AudioStore's binary handler may receive
 * either a Blob (browser binary frame) or an ArrayBuffer (test fixture); this
 * helper unwraps the Blob to ArrayBuffer and delegates to the sync core.
 *
 * Requires:
 *   - blob is a non-empty Blob
 *   - audioContext is a live AudioContext (or AudioContextLike test stub)
 *
 * Ensures:
 *   - Returns Promise<AudioBuffer> resolved with the decoded buffer
 *
 * Raises:
 *   - Error("pcm16: empty blob") if blob.size === 0
 *   - Whatever pcm16ToAudioBuffer throws downstream
 */
export async function pcm16ToAudioBufferFromBlob(
  blob         : Blob,
  audioContext : AudioContextLike,
  sampleRate   : number = 24000,
): Promise<AudioBufferLike> {
  if (blob.size === 0) {
    throw new Error("pcm16: empty blob");
  }
  const buf = await blob.arrayBuffer();
  return pcm16ToAudioBuffer(buf, audioContext, sampleRate);
}
