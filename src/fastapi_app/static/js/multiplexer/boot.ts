// Multiplexer boot entry — Phase 3 wiring.
//
// Responsibilities:
//   1. Resolve session ID via StorageService (DC2 — generate on miss using
//      "adjective_animal" form mirroring `notifications.js:2134`).
//   2. Construct AuthManager + ApiClient + transports via the Phase 2/3
//      factories (no globals beyond the shared singletons EventBus + storage).
//   3. Start QueueTransport + AudioTransport with the resolved session ID.
//   4. Attach DOM lifecycle listeners and emit the 5-event Lifecycle Emission
//      Contract per design § "boot.ts Lifecycle Event Emission Contract".
//
// Lifecycle event mapping:
//   - document.visibilitychange → hidden  → page_hidden
//   - document.visibilitychange → visible → page_visible
//   - window.online                       → network_online
//   - window.offline                      → network_offline
//   - window.pageshow (event.persisted=true)  → page_visible {bfcache: true}
//
// Implementation deviation from design: design's table specifies
// `window.pagehide (event.persisted=true)` for bfcache restore; that's
// MDN-incorrect (`pagehide` fires on bfcache STORE, `pageshow` fires on
// RESTORE — see https://developer.mozilla.org/en-US/docs/Web/API/Window/pageshow_event).
// Implemented per the correct semantics; recorded in 90-execution-log.md
// Phase 3 Notes.

import { eventBus } from "./shared/EventBus";
import { storage } from "./shared/StorageService";
import { createAuthManager } from "./auth/AuthManager";
import { createTransports } from "./transport";
import type { LifecyclePayload } from "./shared/types";

// Session-ID generator mirroring `notifications.js:2134`. 10 × 10 = 100
// distinct combinations; the fallback if the server hasn't issued a session
// ID yet.
//
// Separator: SPACE, not underscore. The server's `is_valid_session_id`
// validator (src/cosa/rest/routers/websocket.py:102) accepts either the
// "adjective noun" (literal space) or "prefix-hash" (hyphens) form;
// underscore-separated IDs are rejected with a 403 at the WS upgrade.
// The transport URL builder URL-encodes the space to "%20" automatically.
const SESSION_ID_ADJECTIVES = [
  "wise", "clever", "swift", "bright", "keen",
  "bold", "calm",   "cool",  "fair",   "fine",
];
const SESSION_ID_ANIMALS = [
  "penguin", "dolphin", "eagle", "tiger", "wolf",
  "bear",    "lion",    "hawk",  "fox",   "owl",
];

function pickRandom<T>(arr: ReadonlyArray<T>): T {
  // arr is non-empty by construction (ADJECTIVES / ANIMALS literal arrays).
  // The non-null assertion is justified: noUncheckedIndexedAccess returns
  // T | undefined for indexed access, but arr.length > 0 + Math.random < 1
  // means the index is always valid.
  return arr[Math.floor(Math.random() * arr.length)] as T;
}

function generateSessionId(): string {
  return `${pickRandom(SESSION_ID_ADJECTIVES)} ${pickRandom(SESSION_ID_ANIMALS)}`;
}

function buildWebSocketBaseUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

function emitLifecycle(type: "page_hidden" | "page_visible" | "network_online" | "network_offline", extra?: { bfcache?: true }): void {
  const ts = Date.now();
  const payload: LifecyclePayload = { ts };
  if (extra?.bfcache) payload.bfcache = true;
  eventBus.emit<LifecyclePayload>({
    type,
    payload,
    source : "boot",
    ts,
  });
}

function attachLifecycleListeners(): void {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      emitLifecycle("page_hidden");
    } else {
      emitLifecycle("page_visible");
    }
  });

  window.addEventListener("online", () => emitLifecycle("network_online"));
  window.addEventListener("offline", () => emitLifecycle("network_offline"));

  // bfcache restore — see implementation deviation note in this file's
  // header comment.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) emitLifecycle("page_visible", { bfcache: true });
  });
}

function bootMultiplexer(): void {
  document.title = "Multiplexer";

  // Session ID: read or generate via StorageService (DC2).
  let sessionId = storage.getSessionId();
  if (sessionId === null) {
    sessionId = generateSessionId();
    storage.setSessionId(sessionId);
  }

  // AuthManager: production singleton wired to shared storage + bus.
  const authManager = createAuthManager({
    refreshUrl       : "/auth/refresh",
    defaultTimeoutMs : 10_000,
    storage,
    bus              : eventBus,
  });

  // Transports — Queue + Audio.
  const baseUrl    = buildWebSocketBaseUrl();
  const transports = createTransports(authManager, eventBus, baseUrl);

  attachLifecycleListeners();

  transports.queue.start(sessionId);
  transports.audio.start(sessionId);

  // Phase 3 boot signal — preserves the Phase 1 console-line invariant for
  // Playwright smoke test continuity, and tags the resolved session.
  console.log("hello multiplexer", { sessionId });
}

bootMultiplexer();
