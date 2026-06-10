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
import { redirectToLoginIfUnauthenticated } from "./auth/authGuard";
import { createApiClient } from "./api/ApiClient";
import { createTransports } from "./transport";
import { createStores } from "./stores";
import {
  createNotificationsListRenderer,
  createJobsPaneRenderer,
  createActionRequiredRenderer,
  createTtsChromeRenderer,
  createConversationModePinRenderer,
  createFocusTrayRenderer,
  createPersonaModalRenderer,
  createSenderCardRecorderRenderer,
  createReadingPaneRenderer,
  configureMetaDisplayCap,
} from "./render";
import type { BootCompletePayload, LifecyclePayload, SenderSortComparator } from "./shared/types";

// Phase 6c Node D Step D5 — boot-injected sender sort comparator. Hoists any
// sender whose `conversation_mode_active === true` above the default
// most-recent-activity-first ordering; ties within the same conversation-mode
// state fall back to activity-based sort. Per F-Arnold-D3: sender-level
// signature (NOT entry-level). The default sort (no opts override) preserves
// Phase 5 behavior; this override only activates when wired here at boot.
const phase6cSenderSort: SenderSortComparator = (a, b) =>
  (Number(b.conversation_mode_active) - Number(a.conversation_mode_active))
  || (b.last_active_ts - a.last_active_ts);

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

  // WP0 login bounce — if no access token is present, redirect to the login
  // page (with a redirect-back) and HALT boot. Mirrors notifications.js +
  // auth.js `isAuthenticated()` (presence-only; an expired token still proceeds
  // and AuthManager refreshes it). `window.location` satisfies RedirectTarget.
  if (redirectToLoginIfUnauthenticated(storage, window.location)) return;

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

  // =====================================================================
  // boot.ts MOUNT-SLOT CONVENTION (Lane A deliverable — multiplexer parity)
  // ---------------------------------------------------------------------
  // Every renderer is wired into boot via the SAME 8-line handshake (the
  // Phase 6c mount template). New parity lanes (strip / reading-pane /
  // commons / fleet / quartet) append their slot in the NEW-LANE MOUNT SLOT
  // marked below — never interleaved among the existing Phase 5/6 mounts —
  // so worktree merges stay conflict-free and the canonical mount ORDER is
  // preserved.
  //
  // The 8-line handshake (copy verbatim, fill <Name>/<#mount-id>):
  //   // Lane <X> WP<NN> — <feature> renderer.
  //   const <name>Renderer = create<Name>Renderer({
  //     eventBus,
  //     stores : { <store>: stores.<store> },   // narrow stores per Pass 2 F4
  //   });
  //   const <name>MountEl = document.getElementById("<#mount-id>");
  //   if (<name>MountEl === null) throw new Error("multiplexer: #<#mount-id> not found");
  //   <name>Renderer.mount(<name>MountEl);
  //
  // Then ALSO, in lockstep (both required, same canonical order):
  //   (a) add `<name>Renderer : "mounted"` to bootCompletePayload.handlers;
  //   (b) add `console.log("[multiplexer] <name>Renderer:mounted")` in the
  //       AC9 console-line block (after the existing lines, before the JSON).
  // A renderer needing a poll timer (e.g. Fleet) starts it AFTER mount and
  // stops it on unmount — it does NOT ride the WS transports below.
  //
  // INVARIANT: renderers mount FIRST, transports start LAST (Pass 2 A8) — a
  // new slot goes ABOVE `attachLifecycleListeners()` / `transports.*.start`.
  // =====================================================================

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
    // Phase 6c Node D Step D5 — inject the conversation-mode-aware sort
    // BEFORE first render so the initial paint already respects pin priority.
    senderSortComparator : phase6cSenderSort,
  });
  const mountEl = document.getElementById("notifications-pane");
  if (mountEl === null) throw new Error("multiplexer: #notifications-pane not found");
  renderer.mount(mountEl);

  // Phase 6a — jobs-pane renderer mounts AFTER the Phase 5 renderer mount,
  // BEFORE transports.queue.start (per F13 ordering invariant). Same factory
  // shape; narrow stores option per Pass 2 F4.
  //
  // Order INVARIANT (per Pass 2 A7 + A8 — Phase 6b ordering): renderers FIRST,
  // transports LAST. Canonical mount order is
  //   notificationsRenderer → jobsRenderer → actionRequiredRenderer → ttsChromeRenderer
  // AC9 asserts the four `:mounted` console lines in this order; AC9b asserts
  // all four lines appear BEFORE the first `store_audio_chunk_decoded` event
  // (transports.audio.start(...) MUST land after every renderer mount).
  const jobsRenderer = createJobsPaneRenderer({
    eventBus,
    stores : { jobs: stores.jobs },
    api    : apiClient,
  });
  const jobsMountEl = document.getElementById("jobs-pane");
  if (jobsMountEl === null) throw new Error("multiplexer: #jobs-pane not found");
  jobsRenderer.mount(jobsMountEl);

  // Phase 6b — action-required renderer mounts AFTER jobs renderer per A7
  // ordering. Claims `dataset.phase6bOwner="true"` on the mount surface so
  // Phase 5's NotificationsListRenderer short-circuits its read-only path
  // (Pass 2 A3).
  const actionRequiredRenderer = createActionRequiredRenderer({
    eventBus,
    stores : { actionRequired: stores.actionRequired },
  });
  const actionRequiredMountEl = document.getElementById("action-required-section");
  if (actionRequiredMountEl === null) throw new Error("multiplexer: #action-required-section not found");
  actionRequiredRenderer.mount(actionRequiredMountEl);

  // Phase 6b — TTS chrome renderer mounts AFTER action-required renderer
  // (canonical AC9 order: notifications → jobs → actionRequired → ttsChrome).
  const ttsChromeRenderer = createTtsChromeRenderer({
    eventBus,
    stores : { audio: stores.audio },
  });
  const ttsMountEl = document.getElementById("tts-pane");
  if (ttsMountEl === null) throw new Error("multiplexer: #tts-pane not found");
  ttsChromeRenderer.mount(ttsMountEl);
  // Lift the hidden + data-phase6-pending markers from #tts-pane now that the
  // renderer owns the surface (mirrors JobsPaneRenderer's in-mount lift for
  // #jobs-pane; TtsChromeRenderer keeps the lift here in boot.ts to preserve
  // its narrow scope to AudioStore-driven rendering only).
  ttsMountEl.removeAttribute("hidden");
  ttsMountEl.removeAttribute("data-phase6-pending");

  // Phase 6c Node D Step D5 — conversation-mode pin renderer mounts AFTER
  // ttsChromeRenderer per canonical boot order (notifications → jobs →
  // actionRequired → ttsChrome → conversationModePin). Subscribes to
  // store_senders_changed and writes data-pinned-conv-mode / data-focus-flash
  // attributes on sender cards. Reuses #notifications-pane as the mount root
  // because sender cards are descendants of that subtree (rendered by
  // NotificationsListRenderer into #sender-cards-container).
  const conversationModePinRenderer = createConversationModePinRenderer({
    eventBus,
    stores : { senders: stores.senders },
  });
  conversationModePinRenderer.mount(mountEl);

  // Phase 6c Node B Step B5 — focus-tray renderer mounts AFTER
  // conversationModePinRenderer per canonical boot order. Mount root must
  // contain BOTH `#focus-mode-toggle` (inside `#notifications-pane`) and
  // `#focus-tray` (sibling of `#notifications-pane`); `<main.container>`
  // is the natural parent of both. Subscribes to store_senders_changed
  // and writes data-focus-hidden on non-pinned sender cards when focus
  // mode is ON.
  const focusTrayRenderer = createFocusTrayRenderer({
    eventBus,
    stores : { senders: stores.senders },
  });
  const focusTrayMountEl = document.querySelector<HTMLElement>("main.container");
  if (focusTrayMountEl === null) throw new Error("multiplexer: <main.container> not found");
  focusTrayRenderer.mount(focusTrayMountEl);

  // Phase 6c Node A Step A5 — persona-modal renderer mounts AFTER
  // focusTrayRenderer per canonical boot order. Uses the same
  // <main.container> root because #persona-modal-portal lives at main level.
  const personaModalRenderer = createPersonaModalRenderer({
    eventBus,
    stores : { senders: stores.senders },
  });
  personaModalRenderer.mount(focusTrayMountEl);

  // Phase 6c Node C Step C5 — sender-card recorder renderer mounts LAST.
  // Per F-Arnold-C4 + Recon-C7: AuthManager must resolve before this renderer
  // instantiates. AuthManager exposes getToken() (async) + getCurrentUserEmail()
  // (sync, decodes the access-token email claim).
  //
  // WP1 — the recorder's outbound user_initiated_message POST stamps
  // `sender_id` with the current user's email. The WP0 login bounce above
  // guarantees a token is present by this point, so getCurrentUserEmail()
  // resolves the address from the stored token (email claim is stable across
  // refresh). `?? ""` is a defensive floor for a malformed-token edge.
  console.log("[multiplexer] authManager:ready");
  // Read cached access token via getToken() — wrap into a sync getter that
  // returns the most-recently-resolved token string. Initial value is null
  // until first call resolves. Production usage: send POST waits for token
  // via async path; the sync getter here returns the cached value at click time.
  let cachedAccessToken: string | null = null;
  void authManager.getToken().then(t => { cachedAccessToken = t.accessToken; }).catch(() => { /* refresh path handles */ });
  const senderCardRecorderRenderer = createSenderCardRecorderRenderer({
    eventBus,
    currentUserEmail : authManager.getCurrentUserEmail() ?? "",
    getAuthToken     : () => cachedAccessToken,
  });
  const recorderMountEl = document.getElementById("sender-cards-container");
  if (recorderMountEl === null) throw new Error("multiplexer: #sender-cards-container not found");
  senderCardRecorderRenderer.mount(recorderMountEl);

  // ===================== NEW-LANE MOUNT SLOT =====================
  // Parity lanes append their 8-line mount handshake HERE (see the MOUNT-SLOT
  // CONVENTION block above). Order between independent lanes does not matter;
  // each lane also updates bootCompletePayload.handlers + the AC9 console line.
  // ===============================================================

  // Lane C WP4+WP5 — master-detail Reading Pane renderer. Mounts on the
  // `.content-shell` root (contains .left-column + #content-pane* + splitter +
  // #layout-mode-toggle). Reads the readingPane store (gesture/AR-driven) and
  // the actionRequired store (count only, for the WP5 lift/drain).
  const readingPaneRenderer = createReadingPaneRenderer({
    eventBus,
    stores : { readingPane: stores.readingPane, actionRequired: stores.actionRequired },
  });
  const readingPaneMountEl = document.querySelector<HTMLElement>(".content-shell");
  if (readingPaneMountEl === null) throw new Error("multiplexer: .content-shell not found");
  readingPaneRenderer.mount(readingPaneMountEl);

  attachLifecycleListeners();

  // Per Pass 2 A8: transports start AFTER every renderer mount so the audio
  // chunk_decoded subscription in TtsChromeRenderer is wired before the first
  // audio frame arrives. AC9b smoke test asserts this invariant.
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
      audioBinary                 : stores.audio.binaryHandler.name,
      notificationsRenderer       : "mounted",
      jobsRenderer                : "mounted",
      actionRequiredRenderer      : "mounted",
      ttsChromeRenderer           : "mounted",
      conversationModePinRenderer : "mounted",
      focusTrayRenderer           : "mounted",
      personaModalRenderer        : "mounted",
      senderCardRecorderRenderer  : "mounted",
      readingPaneRenderer         : "mounted",
    },
  };
  eventBus.emit<BootCompletePayload>({
    type    : "boot_complete",
    payload : bootCompletePayload,
    source  : "boot",
    ts      : Date.now(),
  });
  // Phase 6a Pass 2 F22 + Phase 6b Pass 2 a3 — emit four stable, non-JSON
  // console lines BEFORE the JSON-form line so AC9's grep target is robust
  // against future serialization refactors. AC9 asserts the literal canonical
  // order: notifications → jobs → actionRequired → ttsChrome.
  console.log("[multiplexer] notificationsRenderer:mounted");
  console.log("[multiplexer] jobsRenderer:mounted");
  console.log("[multiplexer] actionRequiredRenderer:mounted");
  console.log("[multiplexer] ttsChromeRenderer:mounted");
  console.log("[multiplexer] conversationModePinRenderer:mounted");
  console.log("[multiplexer] focusTrayRenderer:mounted");
  console.log("[multiplexer] personaModalRenderer:mounted");
  console.log("[multiplexer] senderCardRecorderRenderer:mounted");
  console.log("[multiplexer] readingPaneRenderer:mounted");
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
