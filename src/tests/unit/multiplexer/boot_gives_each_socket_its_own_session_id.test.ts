// Row d2b1b59a, FINDING 5 — boot must start the queue and audio transports on
// DIFFERENT session ids, and route TTS by the audio one.
//
// WHAT BROKE: boot.ts called transports.queue.start(sessionId) and
// transports.audio.start(sessionId, …) with ONE id. The server keeps one socket +
// one subscription list per id, so the audio socket overwrote the queue's, and
// every notification to the tab was declined "not subscribed" (measured
// 2026-09-10; write-up src/rnd/2026.09.10-multiplexer-misses-petition-ask.md).
//
// ⚠️ WHAT THIS TEST IS: a SOURCE PIN. boot.ts runs bootMultiplexer() at import
// and exports nothing, so the wiring cannot be driven from node. This reads the
// file and pins each call to a LITERAL argument name — it does not derive the
// expected side from boot itself. What makes the two names different ids is
// resolveTransportSessionIds, tested behaviourally in transport_session_ids.test.ts.
// The assembled-page proof (an ask renders on /app/multiplexer after the audio
// socket connects) is an E2E on :8000.
//
// Every anchor must match EXACTLY ONCE: zero means boot was restructured and this
// pin needs re-deriving, two means a second call site nobody pinned.
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_gives_each_socket_its_own_session_id.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// 🔴 RESOLVED FROM THIS FILE, NEVER FROM LUPIN_ROOT — measured 2026-09-23 (Krishna 🦚,
// answering María 🌸's B-1 review). LUPIN_ROOT is inherited from the shell and names the
// MAIN CHECKOUT, so from a worktree every pin below was reading — and going green on —
// another tree's boot.ts. It sat green through B-1b's change to wireTtsPlayback's
// signature: the 4-argument pin could not match the 6-argument call, and did not have to,
// because it was looking at a boot.ts that still had four. A pin that reads the wrong
// file is not a weak guard, it is a guard for somebody else's code.
//
// The sibling boot pin (boot_wires_requests_into_both_boards.test.ts) already resolved
// this way and says why. This file did not, and nothing connected the two.
const BOOT_PATH = resolve(
  dirname( fileURLToPath( import.meta.url ) ),
  "../../../lupin_app/static/js/multiplexer/boot.ts",
);
// Comments name the old calls; strip them so only code is pinned.
const BOOT_CODE = readFileSync(BOOT_PATH, "utf8")
  .split("\n")
  .filter((line) => !line.trimStart().startsWith("//"))
  .join("\n");

function onlyMatch(pattern: RegExp): RegExpMatchArray {
  const matches = [...BOOT_CODE.matchAll(new RegExp(pattern.source, "g"))];
  assert.equal(matches.length, 1, `expected exactly one match for ${pattern}, found ${matches.length}`);
  return matches[0] as RegExpMatchArray;
}

test("both ids come from resolveTransportSessionIds", () => {
  onlyMatch(/const \{ queueSessionId, audioSessionId \} = resolveTransportSessionIds\(storage, generateSessionId\);/);
});

test("the queue transport starts on the QUEUE id", () => {
  const m = onlyMatch(/transports\.queue\.start\((\w+)\)/);
  assert.equal(m[1], "queueSessionId");
});

test("the audio transport starts on the AUDIO id, not the queue's", () => {
  const m = onlyMatch(/transports\.audio\.start\((\w+),/);
  assert.equal(m[1], "audioSessionId");
});

test("TTS playback is routed by the AUDIO id — the socket the PCM comes back on", () => {
  const m = onlyMatch(/wireTtsPlayback\(eventBus, stores\.ttsQueue, apiClient, (\w+), stores\.audio, stores\.qa\);/);
  assert.equal(m[1], "audioSessionId");
});

// ---------------------------------------------------------------------------
// Parity B-1b — the two boot wires the metrics ride on. Added 2026-09-23 answering
// María 🌸's B-1 review: both were production-only, and the fix above is what let
// this file see them at all.
//
// ⚠️ THESE PIN ARITY, DELIBERATELY. A 5th/6th argument appended to wireTtsPlayback
// would leave a looser pattern green while the observer it was given changed — which
// is precisely how B-1b's own change went unnoticed here. Zero matches means the call
// was restructured and this pin needs RE-DERIVING against the new shape, not widening.
// ---------------------------------------------------------------------------

test("B-1b: the Q&A store is handed to wireTtsPlayback as the request observer (the TTFA clock)", () => {
  // TTFA is stamped inside that wire, immediately before the POST — legacy stamps it
  // there too ("Start timing BEFORE the fetch for accurate TTFA measurement"). Handed
  // no observer, the wire still plays audio and the metric is silently never taken.
  onlyMatch(/wireTtsPlayback\(eventBus, stores\.ttsQueue, apiClient, audioSessionId, stores\.audio, stores\.qa\);/);
});

test("B-1b: wireQaMetrics is called, once, with the same Q&A store", () => {
  // The other half of the same metric: the first decoded chunk stamps TTFA and RTT
  // together. Unwired, both read null for ever and the pane shows blank timings.
  onlyMatch(/wireQaMetrics\(eventBus, stores\.qa\);/);
});

test("the jobs pane's websocket_id stays the QUEUE id — job events ride the queue socket", () => {
  const m = onlyMatch(/websocketId : (\w+),/);
  assert.equal(m[1], "queueSessionId");
});

test("no bare shared `sessionId` variable survives in boot's code", () => {
  assert.equal(/\bsessionId\b(?!:)/.test(BOOT_CODE), false, "a bare sessionId reference remains");
});
