// Multiplexer boot entry — Phase 3 wiring.
//
// Responsibilities:
//   1. Resolve session ID via StorageService (DC2 — generate on miss using
//      "adjective_animal" form mirroring `notifications.js:2134`).
//   2. Construct AuthManager + ApiClient + transports via the Phase 2/3
//      factories (no globals beyond the shared singletons EventBus + storage).
//   3. Start QueueTransport + AudioTransport, each on its OWN session ID
//      (transportSessionIds.ts — a shared id made the tab deaf to notifications).
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
import { redirectToLoginIfUnauthenticated, logout } from "./auth/authGuard";
import { createApiClient } from "./api/ApiClient";
import { createTransports } from "./transport";
import { createStores } from "./stores";
import type { SchedulableAudioContext } from "./stores";
import { createStripReconnectRehydrator } from "./stores/StripReconnectRehydrator";
import { createColdHistoryHydration } from "./stores/coldHistoryHydration";
import { effectiveHoursForQuery } from "./stores/historyWindow";
import { wireNotificationTtsIntent } from "./wireTtsIntent";
import { wireTtsPlayback } from "./wireTtsPlayback";
import { resolveTransportSessionIds } from "./shared/transportSessionIds";
import {
  createNotificationsListRenderer,
  createNotificationsHeaderRenderer,
  createJobsPaneRenderer,
  createActionRequiredRenderer,
  createTtsChromeRenderer,
  createConversationModePinRenderer,
  createPersonaModalRenderer,
  createSenderCardRecorderRenderer,
  createSessionStripRenderer,
  createReadingPaneRenderer,
  createCommonsActivityRenderer,
  createBroadcastCardRenderer,
  configureMetaDisplayCap,
  // Lane E full-parity quartet renderers.
  createTtsPreviewSliderRenderer,
  createMissedBadgeRenderer,
  createFleetStatusRenderer,
  createTaskListRenderer,
  createFinishedTasksRenderer,
  createHoldingAreaRenderer,
  createEpicBoardRenderer,
  createSectionToolbarRenderer,
  createNavBarRenderer,
  type TtsPreviewSliderRenderer,
} from "./render";
import {
  DEFAULT_TTS_FRACTION,
  TTS_FRACTION_STORAGE_KEY,
  TTS_FRACTION_STORAGE_SCHEMA,
  resolveLiveFraction,
  type SharedFractionStorage,
} from "./render/TtsPreviewSliderRenderer";
import { apiPostTicket } from "./render/newTicketCard";
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

  // Session IDs: read or generate via StorageService (DC2), ONE PER SOCKET. The
  // server keeps one socket + one subscription list per id, so a shared id let
  // the audio socket overwrite the queue's subscriptions (row d2b1b59a).
  const { queueSessionId, audioSessionId } = resolveTransportSessionIds(storage, generateSessionId);

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
  // Lane E WP13 — forward-declared so the config `.then` (resolving AFTER the
  // synchronous mount block) can seed the slider's INI default. A stored
  // localStorage override always wins; seedIniDefault no-ops then.
  let ttsPreviewSliderRenderer: TtsPreviewSliderRenderer | null = null;

  fetch(`${apiBaseUrl}/api/multiplexer/config`)
    .then(r => r.ok ? r.json() : null)
    .catch(() => null)
    .then((serverConfig: { multiplexer_max_meta_display_bytes?: number; tts_preview_fraction?: number } | null) => {
      if (serverConfig !== null) {
        configureMetaDisplayCap(serverConfig);
        // Lane E WP13 — seed the TTS preview slider's INI default (F6).
        if (serverConfig.tts_preview_fraction !== undefined && ttsPreviewSliderRenderer !== null) {
          ttsPreviewSliderRenderer.seedIniDefault(serverConfig.tts_preview_fraction);
        }
      }
    });

  // ---------------------------------------------------------------------
  // Per D-D ratification 2026-05-04 PM (Option B):
  //   1. createTransports(...) — factory only; transports NOT started yet
  //   2. createStores(eventBus, storage, api) — stores subscribe via constructors
  //   3. transports.queue.start(queueSessionId) — queue connects + handshakes
  //   4. transports.audio.start(audioSessionId, audioStore.binaryHandler) — audio
  //      connects with the production handler bound at start-time (never
  //      reaches the Phase 3 default debug logger; zero race window)
  // ---------------------------------------------------------------------

  const baseUrl    = buildWebSocketBaseUrl();
  const transports = createTransports(authManager, eventBus, baseUrl);

  const stores = createStores({
    eventBus,
    storage,
    api                 : apiClient,
    // Phase 2 — the TaskList edit audit `actor` derives from the authenticated
    // user's identity (Q1). AuthManager is constructed above; its email claim is
    // stable across refresh, so reading it lazily per-edit is correct.
    actorProvider       : () => authManager.getCurrentUserEmail(),
    audioContextFactory : (): SchedulableAudioContext => {
      // Production AudioContext factory. Browser autoplay policy may throw
      // if no user gesture preceded — AudioStore catches and emits
      // store_audio_state_change { state: "error", reason: "audiocontext-blocked" }.
      // Chrome-only mux (Rick 2026-06-27) — no `webkitAudioContext` vendor
      // prefix (Krishna-C2: the vestigial fallback was dead under Chrome-only).
      const Ctor = (window as unknown as {
        AudioContext ?: { new (opts?: { sampleRate?: number }): SchedulableAudioContext };
      }).AudioContext;
      if (!Ctor) throw new Error("AudioContext is not available");
      return new Ctor({ sampleRate: 24000 });
    },
  });

  // F0-d — wire the TTS producer seam. NotificationStore emits
  // store_notification_tts_intent for every SPOKEN new-arrival (high/urgent);
  // this glue enqueues each onto TtsQueueStore (stores-emit / boot-wires idiom —
  // the two stores never couple directly). Registered here, BEFORE transports
  // start, so a high/urgent frame arriving immediately after transport.start()
  // is captured (F13 ordering invariant). Page-lifetime subscription (like the
  // stores themselves); the returned unsubscriber is unused in boot.
  //
  // P0 (Rick's broadcast a090b845, 2026-09-10): the TTS preview slider governs what
  // is SPOKEN. Until this wiring nothing on the speech path read it, so every
  // notification played in full even with the slider at 0%. The settings are read
  // at each arrival: the fraction from the legacy page's shared key first (so a
  // change there applies without a reload), then this page's slider. The feature
  // flag and minimum length come from /api/config/client, the endpoint legacy uses,
  // with legacy's defaults (disabled, 100 chars) until it answers. A slider at 0
  // skips speech regardless of the flag, as in legacy.
  const ttsPreviewConfig = { enabled: false, minChars: 100 };
  apiClient.get<{ tts_preview_enabled?: boolean; tts_preview_min_chars?: number }>("/api/config/client")
    .then((c) => {
      ttsPreviewConfig.enabled  = !!c.tts_preview_enabled;
      ttsPreviewConfig.minChars = c.tts_preview_min_chars || 100;
    })
    .catch(() => { /* keep legacy's defaults: disabled, 100 chars */ });
  let sharedTtsStorage: SharedFractionStorage | null = null;
  try { sharedTtsStorage = window.localStorage; } catch { sharedTtsStorage = null; }
  wireNotificationTtsIntent(eventBus, stores.ttsQueue, () => Date.now(), () => ({
    fraction : resolveLiveFraction(
      sharedTtsStorage,
      ttsPreviewSliderRenderer === null ? null : ttsPreviewSliderRenderer.getFraction(),
      storage.getJSON<{ fraction: number }>(TTS_FRACTION_STORAGE_KEY, TTS_FRACTION_STORAGE_SCHEMA)?.fraction,
      DEFAULT_TTS_FRACTION,
    ),
    enabled  : ttsPreviewConfig.enabled,
    minChars : ttsPreviewConfig.minChars,
  }));

  // 4f14d38f — TTS playback request-initiation. When TtsQueueStore's active item
  // rolls to a NEW notification, POST its text to /api/get-speech-elevenlabs with
  // the mux's OWN audio sessionId (the PCM routing key); the server streams PCM
  // back over this session's /ws/audio → AudioStore plays → store_audio_ended →
  // TtsQueueStore.advance(). Registered before transports start so an item queued
  // immediately after connect still triggers a request. Page-lifetime subscription.
  wireTtsPlayback(eventBus, stores.ttsQueue, apiClient, audioSessionId);

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

  // Lane B WP2 — CC-session strip renderer. CONSTRUCTED here (mounted later, in
  // its original slot below) because the notifications-list renderer asks it,
  // for every card it inserts, whether that card is focus-hidden (P0 8cb5c22e).
  // Construction subscribes to nothing and touches no DOM.
  // Row d04ff119: the notification store lets the strip count unread arrivals
  // from sessions hidden by focus. Storage is left to its localStorage default.
  const sessionStripRenderer = createSessionStripRenderer({
    eventBus,
    stores : { strip: stores.sessionStrip, notifications: stores.notifications },
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
      // WP14 (F8) — wire the prediction-vote store so prediction-hint
      // notifications mount interactive thumbs-vote controls in the
      // notification-item render path (createStores already builds the store).
      predictionVote : stores.predictionVote,
      // Section-toolbar / accordion-collapse parity (2026-06-23) — the renderer
      // reads persisted accordion collapse on render + persists header-click
      // toggles, and applies toolbar-driven collapse-all/expand-all.
      viewState      : stores.viewState,
    },
    // Phase 6c Node D Step D5 — inject the conversation-mode-aware sort
    // BEFORE first render so the initial paint already respects pin priority.
    senderSortComparator : phase6cSenderSort,
    // S2a–d / S3 (2026-09-10) — sender-card header controls (📋 · ✨ · rename ·
    // × delete-all) and the per-date × delete. The email is read at click time.
    api                  : apiClient,
    getUserEmail         : () => authManager.getCurrentUserEmail(),
    // P0 8cb5c22e — a card goes in already focus-hidden (legacy flags at creation,
    // notifications.js:19004), so a message from another persona never flashes
    // every card visible. The strip decides; this renderer only asks.
    isCardFocusHidden    : (senderId) => sessionStripRenderer.isCardFocusHidden(senderId),
  });
  const mountEl = document.getElementById("notifications-pane");
  if (mountEl === null) throw new Error("multiplexer: #notifications-pane not found");
  renderer.mount(mountEl);

  // B3 (01-C) — notifications section-header (count · history-dropdown · clear-all).
  // Mounts ABOVE the notifications-list pane. Owns the clear-all orchestration
  // (confirm → per-id DELETE /api/notifications/{id_hash} over visibleEntries()
  // → store.removeByIdHashes(successes)); reuses the generic ApiClient.delete<T>.
  const notificationsHeaderRenderer = createNotificationsHeaderRenderer({
    eventBus,
    store   : stores.notifications,
    api     : apiClient,
    // Row 98305d96 — legacy shows its filter badge and switch to admins only.
    isAdmin : () => authManager.isCurrentUserAdmin(),
  });
  const notificationsHeaderMountEl = document.getElementById("notifications-header-mount");
  if (notificationsHeaderMountEl === null) throw new Error("multiplexer: #notifications-header-mount not found");
  notificationsHeaderRenderer.mount(notificationsHeaderMountEl);

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
    stores      : { jobs: stores.jobs },
    api         : apiClient,
    // W5 — the WS/session id sent as `websocket_id` in the per-job retry POST so
    // the server routes the re-queued job's events back to this client.
    websocketId : queueSessionId,
    // Row 83c3ff74 — legacy's single Mine / Not Mine / All Users control: the jobs pane reads and
    // sets the SAME mode as the notifications header, and an admin's "Mine" names their uid.
    filterStore         : stores.notifications,
    isAdmin             : () => authManager.isCurrentUserAdmin(),
    getCurrentUserId    : () => authManager.getCurrentUserId(),
    getCurrentUserEmail : () => authManager.getCurrentUserEmail(),
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
    stores : { audio: stores.audio, ttsQueue: stores.ttsQueue },   // WP4 — item queue
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

  // WP2 retire (2026-06-10): FocusTrayRenderer is RETIRED — the CC-session
  // strip's icon-click focus supersedes the interim conversation-mode tray
  // (Tiberius ruling, one-mechanism rule). The strip is the sole writer of
  // data-focus-hidden now (see SessionStripRenderer). We still resolve
  // <main.container> here for PersonaModalRenderer (#persona-modal-portal
  // lives at main level).
  const mainContainerEl = document.querySelector<HTMLElement>("main.container");
  if (mainContainerEl === null) throw new Error("multiplexer: <main.container> not found");

  // Phase 6c Node A Step A5 — persona-modal renderer. Uses the <main.container>
  // root because #persona-modal-portal lives at main level.
  const personaModalRenderer = createPersonaModalRenderer({
    eventBus,
    stores : { senders: stores.senders },
  });
  personaModalRenderer.mount(mainContainerEl);

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

  // Lane L4 (v0.1.9) — top nav / logout bar (PORT of lupin-nav.js → mux-TS).
  // Mounts into #lupin-nav-mount (first child of <body>). auth adapter:
  //   isAuthenticated ← persisted access token (legacy presence-semantics);
  //   email           ← AuthManager.getCurrentUserEmail() (null-guarded, F-K-D2);
  //   logout          ← authGuard.logout(storage, window.location) — clears the
  //                     PERSISTED tokens (F-K-D1) then redirects to LOGIN_PATH.
  // Re-renders on auth_state_change (SPA has no full reload — F-K-D4).
  const navBarRenderer = createNavBarRenderer({
    eventBus,
    auth : {
      isAuthenticated     : (): boolean       => storage.getAccessToken() !== null,
      getCurrentUserEmail : (): string | null => authManager.getCurrentUserEmail(),
      logout              : (): void          => logout( storage, window.location ),
    },
    getActivePath : (): string => window.location.pathname,
  });
  const navBarMountEl = document.getElementById("lupin-nav-mount");
  if (navBarMountEl === null) throw new Error("multiplexer: #lupin-nav-mount not found");
  navBarRenderer.mount(navBarMountEl);

  // Lane B WP2 — CC-session strip renderer. Mounts on <main.container> (like
  // FocusTrayRenderer) because the renderer queries #cc-session-strip AND its
  // child controls as descendants of root — it cannot mount on
  // #cc-session-strip itself (querySelector can't match the root element).
  // Store-action + addEventListener delegation only (no inline onclick).
  // Constructed earlier, above the notifications-list renderer (P0 8cb5c22e).
  const sessionStripMountEl = document.querySelector<HTMLElement>("main.container");
  if (sessionStripMountEl === null) throw new Error("multiplexer: <main.container> not found");
  sessionStripRenderer.mount(sessionStripMountEl);

  // Lane B WP9 — cold-reload lineage hydration. The server resolves
  // voice_persona + manager_persona per sender (notifications.py
  // get_visible_senders), so on a fresh page load we hydrate the strip store
  // from that snapshot — existing sessions' icons + manager-lineage badges
  // paint on first load instead of waiting for the next live
  // voice_persona_assigned. Floated non-blocking (mirrors the config fetch);
  // boundary .catch avoids an unhandled rejection — hydration is best-effort,
  // live events still populate the strip. Skipped when no email resolves yet.
  // Cold-load notification hydration (2026-06-11) — the SAME senders-visible
  // snapshot now fans out to THREE consumers: the strip (WP9, unchanged), the
  // sender records (persona/unread/activity), and the notification history
  // (the card-gap fix: cold load previously rendered ZERO sender cards because
  // nothing ever fetched history). One fetch; per-sender conversation-by-date
  // calls ride inside hydrateHistory. Window = the history-window picker's
  // choice, shared with legacy under its raw localStorage key; 48h when nothing
  // is stored. The 2026-06-11 ruling ran 48h silently with no selector; Rick's
  // 2026-09-10 ruling 1 (P0 5ebd2aff) restored the legacy selector — historyWindow.ts.
  // Design: src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md
  //
  // P0 5ebd2aff (2026-09-10) — the fetch → three-consumer fan-out moved into
  // coldHistoryHydration.ts so it (a) waits for the real endpoint instead of the
  // 10 s ApiClient default (senders-visible measured 52.8 s for Rick, 5,179
  // senders) and (b) tells the list pane loading / failed instead of swallowing
  // the abort into "No notifications yet." The pane's Retry re-runs it.
  const coldHistoryHydration = createColdHistoryHydration({
    bus               : eventBus,
    api               : apiClient,
    stores            : { sessionStrip: stores.sessionStrip, senders: stores.senders, notifications: stores.notifications },
    getEmail          : () => authManager.getCurrentUserEmail(),
    getEffectiveHours : () => effectiveHoursForQuery(stores.notifications.historyWindow(), new Date()),
    // Row 98305d96 — legacy's admin "Not Mine": only an admin in mode "others" asks the
    // server to drop notifications from their own jobs. Everyone else sends nothing extra.
    getExcludeOwnJobs : () => authManager.isCurrentUserAdmin() && stores.notifications.filterMode() === "others",
  });
  void coldHistoryHydration.run();
  // v0.1.9 focus-bar eager re-hydrate (option 2) — the cold hydrate above runs
  // ONCE at boot; after a long silent window the host prune reaps stale sessions
  // and the strip only lazily refills (~15-20min) as sessions re-announce a
  // persona. This subscriber re-runs the SAME idempotent hydrate on the queue
  // socket's genuine reconnect edge (reconnecting->connected), refilling the
  // strip immediately. Self-contained (no store/renderer surgery); mirrors
  // ActionRequiredStore's connected-edge pattern.
  // Design: src/rnd/v0.1.9/2026.07.07-focus-bar-repopulation-ux-design.md
  createStripReconnectRehydrator({
    bus      : eventBus,
    api      : apiClient,
    stores   : { sessionStrip: stores.sessionStrip, senders: stores.senders },
    getEmail : () => authManager.getCurrentUserEmail(),
  });
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
  // Lane C (v0.1.9) — broadcast-to-all-CC compose card. Recipient auto-refresh
  // rides the existing store_session_strip_changed event (no new EventBus event).
  // B1 (01-A): mounted FIRST so its rendered subtree hosts the re-nested commons
  // "Recent Activity" chrome (broadcastCard.ts) BEFORE CommonsActivityRenderer
  // mounts onto it.
  const broadcastCardRenderer = createBroadcastCardRenderer({
    eventBus,
    store        : stores.broadcast,
    api          : apiClient,
    getAuthToken : () => cachedAccessToken,
  });
  const broadcastCardMountEl = document.getElementById("broadcast-card-mount");
  if (broadcastCardMountEl === null) throw new Error("multiplexer: #broadcast-card-mount not found");
  broadcastCardRenderer.mount(broadcastCardMountEl);
  // Lane D WP3 — commons "Recent Activity" panel. Carries `api` (third field,
  // Tiberius-approved — JobsPaneRenderer precedent) for REST hydrate
  // (/api/commons/broadcast-history) + the persona-pool filter dropdown. The
  // renderer also subscribes to store_session_strip_changed (WP7) to refresh
  // its persona filter when Lane B's strip changes.
  // B1 (01-A): the commons chrome is now renderer-PRODUCED inside the broadcast
  // card, so its mount root is acquired by a DYNAMIC post-mount querySelector on
  // the LIVE rendered broadcast subtree (a page-load getElementById would resolve
  // null → throw). broadcastCardRenderer.mount() above has already rendered it.
  const commonsActivityRenderer = createCommonsActivityRenderer({
    eventBus,
    stores : { commons: stores.commons },
    api    : apiClient,
  });
  const commonsActivityMountEl = broadcastCardMountEl.querySelector<HTMLElement>("#commons-activity-pane");
  if (commonsActivityMountEl === null) throw new Error("multiplexer: #commons-activity-pane not found inside rendered broadcast card");
  commonsActivityRenderer.mount(commonsActivityMountEl);
  // Lane E WP13 — TTS preview-fraction slider. Storage-backed (no store): the
  // StorageService override is layered on the INI default seeded late via the
  // /api/multiplexer/config `.then` above (seedIniDefault).
  ttsPreviewSliderRenderer = createTtsPreviewSliderRenderer({
    storage,
    iniDefaultFraction : DEFAULT_TTS_FRACTION,   // refined by the config-fetch seed when it resolves
  });
  // Rick's 2026-09-10 ruling 3 (P0 5ebd2aff): the slider's slot is PRODUCED by
  // NotificationsHeaderRenderer inside the header bar (legacy placement), so it is
  // found by a post-mount querySelector on the header mount — the commons-activity
  // precedent above — not by a page-load getElementById.
  const ttsPreviewSliderMountEl = notificationsHeaderMountEl.querySelector<HTMLElement>("#tts-preview-slider-mount");
  if (ttsPreviewSliderMountEl === null) throw new Error("multiplexer: #tts-preview-slider-mount not found inside the rendered notifications header");
  ttsPreviewSliderRenderer.mount(ttsPreviewSliderMountEl);

  // Lane E WP15 — missed-while-away badge + Reset.
  const missedBadgeRenderer = createMissedBadgeRenderer({
    eventBus,
    stores : { missed: stores.missed },
  });
  const missedBadgeMountEl = document.getElementById("missed-badge-mount");
  if (missedBadgeMountEl === null) throw new Error("multiplexer: #missed-badge-mount not found");
  missedBadgeRenderer.mount(missedBadgeMountEl);

  // Lane E WP12 — read-only Fleet-Status table. startPolling() AFTER mount and
  // OFF the WS transports (Cheech's rule): it polls /api/arbiter/fleet-state on
  // its own 60s timer.
  const fleetStatusRenderer = createFleetStatusRenderer({
    eventBus,
    stores : { fleet: stores.fleetStatus },
  });
  const fleetStatusMountEl = document.getElementById("fleet-status-pane");
  if (fleetStatusMountEl === null) throw new Error("multiplexer: #fleet-status-pane not found");
  fleetStatusRenderer.mount(fleetStatusMountEl);
  stores.fleetStatus.startPolling();

  // Row 470b7509 — Finished Tasks. A THIRD autonomous poller, and its own door:
  // /api/tasks/events, not /api/tasks (ruling R5 — no terminal-timestamp column
  // exists, so /api/tasks cannot answer "what finished in the last 24 hours").
  // Mounted BEFORE the task list purely to match the DOM order the user sees;
  // the two are independent.
  const finishedTasksRenderer = createFinishedTasksRenderer({
    eventBus,
    store : stores.finishedTasks,
  });
  const finishedTasksMountEl = document.getElementById("finished-tasks-pane");
  if (finishedTasksMountEl === null) throw new Error("multiplexer: #finished-tasks-pane not found");
  finishedTasksRenderer.mount(finishedTasksMountEl);
  stores.finishedTasks.startPolling();

  // Step 4 (store-canonical task mgmt) — read-only Task-List card. Same
  // autonomous-timer pattern as fleet-status: startPolling() AFTER mount, OFF
  // the WS transports; it polls /api/tasks on its own 60s timer.
  const taskListRenderer = createTaskListRenderer({
    eventBus,
    // Phase 2 — the fleet store supplies the owner-reassignment roster (active
    // personas, Sam included — Q5) from the SAME source the fleet-status card uses.
    stores : { taskList: stores.taskList, fleet: stores.fleetStatus },
    // Rick's findability P0 (row 732151f2) — the "find ticket by id" box.
    // 🔴 apiClient.get on /api/tasks/<ref>, which applies NO board-visibility
    // filter and therefore finds HOLDING-AREA rows. Do NOT "simplify" this onto
    // the board query (/api/tasks?id_prefix=): measured 2026-09-09, that path
    // could see 1 of the 23 held rows, because it chains _apply_owed_filter
    // after the prefix match.
    lookupFetch : (path) => apiClient.get<import("./render/taskListModel").TaskItem>(path),
    // Rick's New Ticket card (row c9895403) — the "＋ New" button beside Find. The POST
    // carries his login token, which is what lets the server honour P0 and skip the
    // ratio gate for him; a seat's API key gets neither.
    postTicket  : apiPostTicket((path, body) => apiClient.post<unknown>(path, body)),
    // Row c9fafb9d — the demote-request badge and each row's Approve/Deny.
    requestStore : stores.taskRequests,
  });
  const taskListMountEl = document.getElementById("task-list-pane");
  if (taskListMountEl === null) throw new Error("multiplexer: #task-list-pane not found");
  taskListRenderer.mount(taskListMountEl);
  stores.taskList.startPolling();

  // Row 87812328 — Holding Area. Its OWN 60s poll, because not_approved rows
  // are invisible to the task list's query; it is a second FETCH, not a second
  // view of one composite. Same autonomous-timer pattern: startPolling() AFTER
  // mount, off the WS transports.
  const holdingAreaRenderer = createHoldingAreaRenderer({
    eventBus,
    store : stores.holdingArea,
    // No lookupFetch: the holding area carries no search box (Rick, row 700f0e1d,
    // 2026-09-11). The task list's box reaches held rows already.
    // Row c9fafb9d — the promote-request badge and each row's Approve/Deny.
    requestStore : stores.taskRequests,
  });
  const holdingAreaMountEl = document.getElementById("holding-area-pane");
  if (holdingAreaMountEl === null) throw new Error("multiplexer: #holding-area-pane not found");
  holdingAreaRenderer.mount(holdingAreaMountEl);
  stores.holdingArea.startPolling();
  // Row c9fafb9d — AFTER both panes mount, so the first badge poll has badges to paint.
  stores.taskRequests.startPolling();

  // Row 87812328 — Epic Board. 🔴 NO startPolling() AND NO STORE OF ITS OWN:
  // it reads the TASK LIST's composite and repaints off store_task_list_changed.
  // That is deliberate and is the mechanism by which the two panes cannot show
  // different clocks — the legacy client's own words, "no second fetch, no
  // second timer". Adding a timer here would reintroduce exactly the drift the
  // shared composite exists to prevent.
  // The titles/stories are a memoized ONE-SHOT, not a poll — a hand-edited file
  // is not live state. It is fired-and-forgotten rather than awaited: the board
  // renders correctly without it (de-slugged names, no story rows), so blocking
  // boot on it would trade a complete pane for a slower one. The titles appear
  // on the task list's next tick, which is the only clock this pane has.
  // 🔴 CAPTURED, NOT DISCARDED — see the repaint below. Still not awaited, so
  // boot is not blocked; the difference is that its arrival now REACHES the pane.
  const epicStoriesLoaded = stores.epicStories.load();

  const epicBoardRenderer = createEpicBoardRenderer({
    eventBus,
    store     : stores.taskList,
    storiesFn : () => stores.epicStories.stories(),
  });
  const epicBoardMountEl = document.getElementById("epic-board-pane");
  if (epicBoardMountEl === null) throw new Error("multiplexer: #epic-board-pane not found");
  epicBoardRenderer.mount(epicBoardMountEl);

  // 🔴 REPAINT WHEN THE ONE-SHOT LANDS. The comment above used to say the titles
  // "appear on the task list's next tick, which is the only clock this pane has",
  // and that was true — but the tick is a POLL INTERVAL away, and until it comes
  // the pane shows de-slugged epic names and NO story rows while the data has
  // already arrived. Measured 2026-09-06 on the live page: /api/epic-stories was
  // served at 0.09s, the task list did not tick again for the next 15s, and the
  // board still read `alpha` (de-slugged) with zero story rows the whole time —
  // where legacy showed the story immediately. Boot is still not blocked; the
  // load simply now has a consumer.
  void epicStoriesLoaded.then( () => epicBoardRenderer.repaint() );

  // Section-toolbar + accordion-collapse parity (2026-06-23, Rachel 🕊️) —
  // carbon-copy of the legacy floating #section-toolbar: per-section visibility
  // toggles + collapse-all/expand-all. Drives the ViewStateStore (persisted);
  // collapse-all/expand-all fan out to NotificationsListRenderer's accordions
  // via store_view_state_changed. Per-accordion header-click toggle is wired in
  // NotificationsListRenderer (above). The layout-mode ⇆ stays in
  // #reading-pane-toolbar (mux-N/A here — see design doc 06).
  const sectionToolbarRenderer = createSectionToolbarRenderer({
    stores : { viewState: stores.viewState },
  });
  const sectionToolbarMountEl = document.getElementById("section-toolbar-mount");
  if (sectionToolbarMountEl === null) throw new Error("multiplexer: #section-toolbar-mount not found");
  sectionToolbarRenderer.mount(sectionToolbarMountEl);

  // Lane E WP14 / F8 — prediction-hint vote: the PredictionVoteStore is wired
  // into createStores() AND injected into the NotificationsListRenderer above
  // (stores.predictionVote). The vote CONTROLS template (predictionVoteControls)
  // is now mounted by the notification-item render path for any prediction-hint
  // notification clearing the confidence gate — no standalone mount here.

  attachLifecycleListeners();

  // Per Pass 2 A8: transports start AFTER every renderer mount so the audio
  // chunk_decoded subscription in TtsChromeRenderer is wired before the first
  // audio frame arrives. AC9b smoke test asserts this invariant.
  transports.queue.start(queueSessionId);
  transports.audio.start(audioSessionId, stores.audio.binaryHandler);

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
      personaModalRenderer        : "mounted",
      senderCardRecorderRenderer  : "mounted",
      sessionStripRenderer        : "mounted",
      readingPaneRenderer         : "mounted",
      commonsActivityRenderer     : "mounted",
      // Lane E full-parity quartet (WP13/WP15/WP12 renderers; WP14 has no
      // standalone renderer — its store rides createStores()).
      ttsPreviewSliderRenderer    : "mounted",
      missedBadgeRenderer         : "mounted",
      fleetStatusRenderer         : "mounted",
      taskListRenderer            : "mounted",
      // The two accordion panes (2026-09-06, Clayton 😎's F3). Both were mounted
      // ~30 lines above and named nowhere here, so unmounting either left AC9's
      // wiring assertion green — a renderer complete, correct and absent from
      // the contract that claims it is installed.
      finishedTasksRenderer       : "mounted",
      holdingAreaRenderer         : "mounted",
      epicBoardRenderer           : "mounted",
      // Section-toolbar + accordion-collapse parity (2026-06-23).
      sectionToolbarRenderer      : "mounted",
      // Lane L4 (v0.1.9) — top nav / logout bar.
      navBarRenderer              : "mounted",
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
  console.log("[multiplexer] personaModalRenderer:mounted");
  console.log("[multiplexer] senderCardRecorderRenderer:mounted");
  console.log("[multiplexer] sessionStripRenderer:mounted");
  console.log("[multiplexer] readingPaneRenderer:mounted");
  console.log("[multiplexer] commonsActivityRenderer:mounted");
  console.log("[multiplexer] ttsPreviewSliderRenderer:mounted");
  console.log("[multiplexer] missedBadgeRenderer:mounted");
  console.log("[multiplexer] fleetStatusRenderer:mounted");
  console.log("[multiplexer] taskListRenderer:mounted");
  console.log("[multiplexer] sectionToolbarRenderer:mounted");
  console.log("[multiplexer] navBarRenderer:mounted");
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
  console.log("hello multiplexer", { sessionId: queueSessionId, audioSessionId });
}

bootMultiplexer();
