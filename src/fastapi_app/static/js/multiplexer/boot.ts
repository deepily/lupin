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
import { createApiClient } from "./api/ApiClient";
import { createTransports } from "./transport";
import { createStores } from "./stores";
import {
  createNotificationsListRenderer,
  createJobsPaneRenderer,
  configureMetaDisplayCap,
} from "./render";
import type { BootCompletePayload, LifecyclePayload } from "./shared/types";

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

  // ApiClient: production singleton for ActionRequiredStore.respond + Phase 5+
  // renderers (e.g. JobStore.hydrateHistory).
  const apiBaseUrl = window.location.origin;
  const apiClient  = createApiClient({
    baseUrl          : apiBaseUrl,
    defaultTimeoutMs : 10_000,
    authManager,
  });

  // Phase 6a Pass 2 F20 — fetch the multiplexer client-config endpoint and
  // thread the meta-display cap into jobCard.ts. Floated as a non-blocking
  // promise: the cap is read lazily on first card-header click (NOT on mount),
  // so a small race window is acceptable — jobCard.ts ships with a 256000
  // default that covers the gap if the user clicks before the fetch resolves
  // (or if the endpoint is briefly unreachable). Boundary `.catch(() => null)`
  // avoids unhandled rejection while preserving the default cap.
  fetch(`${apiBaseUrl}/api/multiplexer/config`)
    .then(r => r.ok ? r.json() : null)
    .catch(() => null)
    .then((serverConfig: { multiplexer_max_meta_display_bytes?: number } | null) => {
      if (serverConfig !== null) configureMetaDisplayCap(serverConfig);
    });

  // ---------------------------------------------------------------------
  // Per D-D ratification 2026-05-04 PM (Option B):
  //   1. createTransports(...) — factory only; transports NOT started yet
  //   2. createStores(eventBus, storage, api) — stores subscribe via constructors
  //   3. transports.queue.start(sessionId) — queue connects + handshakes
  //   4. transports.audio.start(sessionId, audioStore.binaryHandler) — audio
  //      connects with the production handler bound at start-time (never
  //      reaches the Phase 3 default debug logger; zero race window)
  // ---------------------------------------------------------------------

  const baseUrl    = buildWebSocketBaseUrl();
  const transports = createTransports(authManager, eventBus, baseUrl);

  const stores = createStores({
    eventBus,
    storage,
    api                 : apiClient,
    audioContextFactory : () => {
      // Production AudioContext factory. Browser autoplay policy may throw
      // if no user gesture preceded — AudioStore catches and emits
      // store_audio_state_change { state: "error", reason: "audiocontext-blocked" }.
      const Ctor = (window as unknown as {
        AudioContext       ?: { new (opts?: { sampleRate?: number }): AudioContext };
        webkitAudioContext ?: { new (opts?: { sampleRate?: number }): AudioContext };
      }).AudioContext ?? (window as unknown as {
        webkitAudioContext ?: { new (opts?: { sampleRate?: number }): AudioContext };
      }).webkitAudioContext;
      if (!Ctor) throw new Error("AudioContext is not available");
      return new Ctor({ sampleRate: 24000 });
    },
  });

  // Phase 5 — notifications-list renderer mounts BEFORE transports start
  // (per F13 ordering invariant): subscribe to store_*_changed events first
  // so any frame arriving immediately after transport.start() is captured by
  // the live renderer rather than missing the initial paint window.
  const renderer = createNotificationsListRenderer({
    eventBus,
    stores : {
      notifications  : stores.notifications,
      senders        : stores.senders,
      actionRequired : stores.actionRequired,
    },
  });
  const mountEl = document.getElementById("notifications-pane");
  if (mountEl === null) throw new Error("multiplexer: #notifications-pane not found");
  renderer.mount(mountEl);

  // Phase 6a — jobs-pane renderer mounts AFTER the Phase 5 renderer mount,
  // BEFORE transports.queue.start (per F13 ordering invariant). Same factory
  // shape; narrow stores option per Pass 2 F4.
  const jobsRenderer = createJobsPaneRenderer({
    eventBus,
    stores : { jobs: stores.jobs },
    api    : apiClient,
  });
  const jobsMountEl = document.getElementById("jobs-pane");
  if (jobsMountEl === null) throw new Error("multiplexer: #jobs-pane not found");
  jobsRenderer.mount(jobsMountEl);

  attachLifecycleListeners();

  transports.queue.start(sessionId);
  transports.audio.start(sessionId, stores.audio.binaryHandler);

  // Per D-C ratification 2026-05-04 PM (Option B): emit boot_complete on
  // EventBus + mirror to console.log so AC9's Playwright check can verify the
  // wiring without the no-globals violation `window.audioTransport.binaryHandler`
  // access path. The handler name comes from `Function.name` on the bound
  // method — for production code this MUST equal "audioStoreBinaryHandler".
  //
  // Phase 5 RE-16 + F22 extension: literal "mounted" string for
  // `notificationsRenderer` (NOT function-name introspection — fixed contract
  // surface for AC9 Playwright equality check).
  const bootCompletePayload: BootCompletePayload = {
    handlers : {
      audioBinary           : stores.audio.binaryHandler.name,
      notificationsRenderer : "mounted",
      jobsRenderer          : "mounted",
    },
  };
  eventBus.emit<BootCompletePayload>({
    type    : "boot_complete",
    payload : bootCompletePayload,
    source  : "boot",
    ts      : Date.now(),
  });
  // Phase 6a Pass 2 F22 — emit two stable, non-JSON console lines BEFORE the
  // JSON-form line so AC9's grep target is robust against future serialization
  // refactors. AC9 asserts on the literal stable strings, NOT on the JSON
  // form. Mirror-emit notificationsRenderer:mounted for Phase 5 surface
  // consistency (same line-shape contract).
  console.log("[multiplexer] notificationsRenderer:mounted");
  console.log("[multiplexer] jobsRenderer:mounted");
  console.log("[multiplexer] boot_complete", JSON.stringify(bootCompletePayload));

  // Phase 5 D-E test hook (per `92-phase5-review-findings.md` D-E): expose
  // the eventBus + stores for `page.evaluate` fixture injection from
  // Playwright smoke tests. NOT covered by the no-globals ESLint rule (only
  // `notificationsUI` + `multiplexerUI` are restricted; `__multiplexerTestHook`
  // is a fresh test surface). Production code MUST NOT consume this global —
  // it's strictly for `test_multiplexer_phase5_smoke.py` and similar.
  ( window as unknown as { __multiplexerTestHook?: unknown } ).__multiplexerTestHook = {
    eventBus,
    stores,
    bootCompleteTs : Date.now(),
  };

  // Phase 3 boot signal — preserves the Phase 1 console-line invariant for
  // Playwright smoke test continuity, and tags the resolved session.
  console.log("hello multiplexer", { sessionId });
}

bootMultiplexer();
