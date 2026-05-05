// Multiplexer Phase 4 — pcm-decoder unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/pcm_decoder.test.ts`.
// AC4 floor: ≥ 6 tests per design doc § Verification matrix.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  pcm16ToAudioBuffer,
  pcm16ToAudioBufferFromBlob,
  type AudioContextLike,
  type AudioBufferLike,
} from "../../../fastapi_app/static/js/multiplexer/audio/pcm-decoder";

// ---------------------------------------------------------------------------
// Stub AudioContext / AudioBuffer for Node testing. Captures the createBuffer
// arguments + the Float32Array passed via copyToChannel so tests can assert
// the bit-banging math.
// ---------------------------------------------------------------------------

class StubAudioBuffer implements AudioBufferLike {
  readonly numberOfChannels : number;
  readonly length           : number;
  readonly sampleRate       : number;
  readonly duration         : number;
  // Captured channel data (channelNumber → Float32Array slice).
  readonly channelData      : Map<number, Float32Array> = new Map();

  constructor(numberOfChannels: number, length: number, sampleRate: number) {
    this.numberOfChannels = numberOfChannels;
    this.length           = length;
    this.sampleRate       = sampleRate;
    this.duration         = length / sampleRate;
  }

  copyToChannel(source: Float32Array, channelNumber: number, _bufferOffset?: number): void {
    // Defensive copy so test can assert the values without aliasing risk.
    this.channelData.set(channelNumber, new Float32Array(source));
  }
}

class StubAudioContext implements AudioContextLike {
  createBufferCallCount = 0;
  lastArgs              : [number, number, number] | null = null;

  createBuffer(numberOfChannels: number, length: number, sampleRate: number): AudioBufferLike {
    this.createBufferCallCount++;
    this.lastArgs = [numberOfChannels, length, sampleRate];
    return new StubAudioBuffer(numberOfChannels, length, sampleRate);
  }
}

function makePCM16Buffer(samples: ReadonlyArray<number>): ArrayBuffer {
  const arr = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    arr[i] = samples[i] as number;
  }
  return arr.buffer;
}

// ---------------------------------------------------------------------------
// 1. ArrayBuffer accepted; default 24kHz produces 1-channel buffer
// ---------------------------------------------------------------------------

test("pcm16ToAudioBuffer accepts ArrayBuffer with default 24kHz sample rate", () => {
  const ctx = new StubAudioContext();
  const buf = makePCM16Buffer([0, 16384, -16384, 32767, -32768]);

  const audioBuffer = pcm16ToAudioBuffer(buf, ctx);

  assert.equal(audioBuffer.numberOfChannels, 1, "should produce mono buffer");
  assert.equal(audioBuffer.length, 5, "length should equal sample count");
  assert.equal(audioBuffer.sampleRate, 24000, "default sample rate");
  assert.equal(ctx.createBufferCallCount, 1);
  assert.deepEqual(ctx.lastArgs, [1, 5, 24000]);
});

// ---------------------------------------------------------------------------
// 2. Custom sampleRate flows through to AudioContext.createBuffer
// ---------------------------------------------------------------------------

test("pcm16ToAudioBuffer threads custom sampleRate through to createBuffer", () => {
  const ctx = new StubAudioContext();
  const buf = makePCM16Buffer([0, 0, 0, 0]);

  const audioBuffer = pcm16ToAudioBuffer(buf, ctx, 16000);

  assert.equal(audioBuffer.sampleRate, 16000);
  assert.deepEqual(ctx.lastArgs, [1, 4, 16000]);
});

// ---------------------------------------------------------------------------
// 3. Bit-banging math: Int16 → Float32 normalization
// ---------------------------------------------------------------------------

test("pcm16ToAudioBuffer normalizes Int16 samples to [-1.0, 1.0] floats", () => {
  const ctx    = new StubAudioContext();
  // Test values: 0 → 0.0; 32767 → just under 1.0; -32768 → exactly -1.0;
  // 16384 → exactly 0.5.
  const buf    = makePCM16Buffer([0, 32767, -32768, 16384, -16384]);
  const result = pcm16ToAudioBuffer(buf, ctx) as StubAudioBuffer;

  const ch0 = result.channelData.get(0);
  assert.ok(ch0 instanceof Float32Array);
  assert.equal(ch0!.length, 5);

  // Math expectations: pcm16[i] / 32768.0
  assert.equal(ch0![0], 0);
  assert.ok(Math.abs(ch0![1]! - 32767 / 32768) < 1e-9);
  assert.equal(ch0![2], -1);
  assert.equal(ch0![3], 0.5);
  assert.equal(ch0![4], -0.5);
});

// ---------------------------------------------------------------------------
// 4. Empty buffer rejection
// ---------------------------------------------------------------------------

test("pcm16ToAudioBuffer rejects empty buffer with explicit error", () => {
  const ctx = new StubAudioContext();
  const buf = new ArrayBuffer(0);

  assert.throws(
    () => pcm16ToAudioBuffer(buf, ctx),
    /pcm16: empty buffer/,
  );
  assert.equal(ctx.createBufferCallCount, 0, "context.createBuffer must not be called on rejection");
});

// ---------------------------------------------------------------------------
// 5. Malformed payload (odd byteLength) rejection
// ---------------------------------------------------------------------------

test("pcm16ToAudioBuffer rejects buffer with odd byteLength", () => {
  const ctx = new StubAudioContext();
  // 3 bytes — not divisible by 2; cannot be Int16-aligned.
  const buf = new ArrayBuffer(3);

  assert.throws(
    () => pcm16ToAudioBuffer(buf, ctx),
    /pcm16: buffer length 3 not a multiple of 2/,
  );
  assert.equal(ctx.createBufferCallCount, 0);
});

// ---------------------------------------------------------------------------
// 6. Statelessness: two consecutive calls produce independent buffers
// ---------------------------------------------------------------------------

test("pcm16ToAudioBuffer is stateless — consecutive calls produce independent buffers", () => {
  const ctx = new StubAudioContext();
  const a   = pcm16ToAudioBuffer(makePCM16Buffer([100, 200]), ctx) as StubAudioBuffer;
  const b   = pcm16ToAudioBuffer(makePCM16Buffer([-100, -200]), ctx) as StubAudioBuffer;

  // Distinct AudioBuffer instances.
  assert.notEqual(a, b);
  // Distinct Float32 backing arrays.
  const aCh = a.channelData.get(0)!;
  const bCh = b.channelData.get(0)!;
  assert.notEqual(aCh, bCh);
  // Math is independent.
  assert.ok(aCh[0]! > 0 && bCh[0]! < 0, "first samples should have opposite signs");
  assert.equal(ctx.createBufferCallCount, 2);
});

// ---------------------------------------------------------------------------
// 7. Blob accepted (async wrapper)
// ---------------------------------------------------------------------------

test("pcm16ToAudioBufferFromBlob accepts Blob input and delegates to sync core", async () => {
  const ctx = new StubAudioContext();
  const buf = makePCM16Buffer([1000, -1000, 0]);
  const blob = new Blob([buf]);

  const result = await pcm16ToAudioBufferFromBlob(blob, ctx);

  assert.equal(result.length, 3);
  assert.equal(result.sampleRate, 24000);
  assert.equal(ctx.createBufferCallCount, 1);
});

// ---------------------------------------------------------------------------
// 8. Empty Blob rejection
// ---------------------------------------------------------------------------

test("pcm16ToAudioBufferFromBlob rejects empty Blob without invoking sync core", async () => {
  const ctx = new StubAudioContext();
  const blob = new Blob([]);

  await assert.rejects(
    () => pcm16ToAudioBufferFromBlob(blob, ctx),
    /pcm16: empty blob/,
  );
  assert.equal(ctx.createBufferCallCount, 0);
});

// ---------------------------------------------------------------------------
// 9. Async wrapper threads custom sampleRate through
// ---------------------------------------------------------------------------

test("pcm16ToAudioBufferFromBlob threads custom sampleRate through async path", async () => {
  const ctx = new StubAudioContext();
  const blob = new Blob([makePCM16Buffer([0, 0])]);

  const result = await pcm16ToAudioBufferFromBlob(blob, ctx, 48000);

  assert.equal(result.sampleRate, 48000);
  assert.deepEqual(ctx.lastArgs, [1, 2, 48000]);
});
