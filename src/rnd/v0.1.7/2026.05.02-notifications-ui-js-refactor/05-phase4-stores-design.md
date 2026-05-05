# Phase 4 Design — Multiplexer Domain Stores

**Date**: 2026-05-04
**Status**: DRAFT — pending plan-review pass + user approval (per Q10 — first per-phase doc post-spine-bundle)
**Phase**: 4 of 9 (per `01-execution-plan.md` §"Phase plan")
**Predecessors**: `00-synthesis-and-roadmap.md`, `01-execution-plan.md`, `01-phase0-decisions.md`, `02-phase1-scaffolding-design.md`, `03-phase2-foundation-design.md`, `04-phase3-transport-design.md` (all approved + implemented)
**Companion**: `90-execution-log.md` Phase 4 section (opens after user approval)

---

## Approval coupling — single-phase gate (per Q10)

Per Q10 amendment in `01-phase0-decisions.md` (2026-05-04): the spine bundle covered Phases 1-3 as a single approval unit; from Phase 4 onward each phase is its own approval gate. This doc is the **first per-phase doc post-spine**, so it carries its own slot table (see §"Plan-review slot table" at end of file) and goes through its own REUSE → Pass 1 (Fitness) → Pass 2 (Adversarial) review pipeline before the user-approval gate fires and the `90-execution-log.md` Phase 4 section opens.

**No code lands until ALL of**: REUSE pre-pass complete + Pass 1 Fitness complete + Pass 2 Adversarial complete + user approves the post-review draft.

## Plan-review pointer — canonical PIP machinery

Per Q11 amendment 2026-05-04: review machinery is the canonical `planning-is-prompting/workflow/plan-review.md`. This phase's TBDs (§"Open Questions" below) feed into `{{TBD_QUESTIONS}}` for the per-phase review.

---

## Context

Phase 4 builds the **domain stores layer** — five modules that consume EventBus events emitted by Phase 3 transports + boot, hold the canonical client-side state derived from those events, and re-emit `store_*` events on EventBus when state changes so renderers (Phase 5+) can subscribe to specific store changes instead of raw transport events.

Why stores live BETWEEN transports and renderer:
- **Idempotency**: transports emit one event per WS frame. Stores deduplicate by ID + apply ordering invariants. Renderers see consistent application state, not raw frames.
- **Multi-consumer fan-out**: a single `notification_received` event might update NotificationStore (append to list) + SenderStore (lookup-or-create the sender + bump unread count) + ActionRequiredStore (if `action_required: true`, register countdown). Each store owns its slice of the derived state.
- **Test isolation**: each store is unit-tested with a fixture event stream; no real WS, no real DOM. Phase 5's renderer tests then mock the *stores*, not the transports.
- **State queries**: Phase 5+ render code asks a store `getById(...)` / `getList()` instead of reaching into a global. The store is the query interface.

The five stores:

| Store | Purpose | XState? |
|---|---|---|
| `NotificationStore` | List of notifications (active + history); unread tracking; expiry sweep | No (plain reducer) |
| `JobStore` | List of jobs across the 5 cj-flow buckets (todo / running / done / dead / history) | No (plain reducer) |
| `AudioStore` | Audio playback queue + current-playback state (idle / decoding / playing / paused / ended); replaces Phase 3's debug-logger binary handler with the real PCM-decoding handler | **Yes** (XState — playback is high-churn per Q6) |
| `ActionRequiredStore` | Action-required notifications: countdown timers, per-notification state (pending / responded / expired / cancelled) | **Yes** (XState — per Q6 explicitly lists action-required as high-churn) |
| `SenderStore` | Map of `sender_id → SenderRecord` (display name, last-active ts, unread count, voice-persona color) | No (plain reducer) |

**Cross-tab note**: All stores are tab-local per **Q12 single-tab application policy** (`01-phase0-decisions.md` Q12, ratified 2026-05-04 PM during Phase 4 plan-review). Phase 2's `BroadcastChannel("lupin")` wrapper is inert — no production consumer wires it. See Q12 for rationale.

This phase ships **no UI**, **no transport changes**, **no renderer**. The output is observable via EventBus `store_*` events emitted by each store on state mutation. Phase 5 (renderer) consumes.

## Strategic posture (recap)

Per `00-synthesis-and-roadmap.md` §1: parallel greenfield rebuild. Stores are written in TypeScript strict mode (per Q4) under `src/fastapi_app/static/js/multiplexer/stores/`. All stores follow the no-globals rule (per Phase 1 ESLint config); inter-module communication is exclusively via EventBus.

XState selection per Q6 ("XState for high-churn modules only — auth, TTS, action-required, connection. Plain reducers everywhere else."):
- ✅ AudioStore — playback is a state-machine flow with multiple transitions (decode → ready → playing → paused → ended), error states, and per-chunk arrival timing. Plain reducer would push the state-machine logic into ad-hoc `if (state === ...)` branches.
- ✅ ActionRequiredStore — explicitly listed in Q6. Per-notification countdown + multi-state (pending / responded / expired / cancelled) + grace-period semantics fit an XState actor cleanly.
- ❌ NotificationStore — append-mostly list with expiry sweep. Plain reducer with explicit dispatch table.
- ❌ JobStore — append/move-between-buckets list operations. Plain reducer.
- ❌ SenderStore — map operations (lookup, insert, update field). Plain reducer.

## Out of scope for Phase 4

- Any UI rendering — Phase 5 consumes Phase 4's `store_*` events to render
- TTS engine + queue (`tts/TTSEngine.ts`, `tts/TTSQueue.ts`) — Phase 6 feature parity (TTS is high-churn per Q6 and gets its own XState actor in Phase 6)
- AudioRecorder (`audio/AudioRecorder.ts`) — Phase 6
- Caches (`audio/caches/TTSAudioCache.ts`, `audio/caches/JobCompletionCache.ts`) — Phase 6
- ClaudeCode store — **explicitly out of scope per D1 A-extended ratification 2026-05-04 PM** (see `90-execution-log.md` "Phase 3 — D1 Ratification Amendment"). **Per Pass 1 F16**: `claude_code_event` is still emitted by Phase 3 QueueTransport (per the QUEUE_SUBSCRIBED_EVENTS constant in `transport/QueueTransport.ts`); Phase 4 ships NO consumer for it. The event flows to EventBus and is dropped on the floor (no listener registered). This is intentional per D1; Phase 5+ may add a consumer when CC functionality re-enters scope.
- **Cross-tab coordination — single-tab application policy per Q12 (`01-phase0-decisions.md`, ratified 2026-05-04 PM during Phase 4 plan-review).** No store broadcasts cross-tab. Phase 2's `BroadcastChannel("lupin")` wrapper is inert in production; cleanup tracked in `TODO.md`.
- Persistence beyond ephemeral runtime state — only NotificationStore reads/writes via StorageService (unread count + last-seen-ts envelopes); other stores are runtime-only and rebuild from event replay on page load
- Cross-store transactional invariants — each store owns its slice; cross-store consistency is achieved by ordered event subscription, not by transactions
- Observability (User Timing marks, OTel) — Phase 7

## Files created / edited

| Path | Change | Owner | Rationale |
|---|---|---|---|
| `src/fastapi_app/static/js/multiplexer/stores/NotificationStore.ts` | NEW | Lupin | Plain reducer; consumes `notification_received` / `notification_responded` / `notification_expired` / `notification_play_sound`; emits `store_notifications_changed`; persists `lupin:notifications:unread-count` envelope via StorageService |
| `src/fastapi_app/static/js/multiplexer/stores/JobStore.ts` | NEW | Lupin | Plain reducer; consumes `job_state_transition` / `job_removed`; emits `store_jobs_changed`; tracks 5-bucket layout matching cj-flow `[todo, running, done, dead, history]`. **Per Q7 ratification 2026-05-04 PM (Option B)**: NO ApiClient dependency at construct; history bucket starts empty + populated by in-session `job_removed` reducer; Phase 5+ renderer calls public `hydrateHistory(api)` when history pane mounts (dedup by id_hash). |
| `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` | NEW | Lupin | XState actor (idle → decoding → playing → paused → ended → error); exposes a public named bound method `audioStoreBinaryHandler(blob)` that boot.ts passes to `transports.audio.start(sessionId, audioStore.binaryHandler)` per D-D ratification; emits `store_audio_state_change` + `store_audio_chunk_decoded` |
| `src/fastapi_app/static/js/multiplexer/stores/ActionRequiredStore.ts` | NEW | Lupin | XState actor per active prompt (pending → responded \| expired \| cancelled). **Per D-F ratification 2026-05-04 PM (Option 2 hybrid)**: per-actor `setInterval(1000)` for smooth 1Hz countdown display + `sys_time_update` subscription as authoritative server-clock reconciler (prevents client-clock drift) + `connection_state_change` subscription for offline-freeze handling (pause interval + emit `offline-frozen` reason; resume on `connection_online`). Emits `store_action_required_changed`. |
| `src/fastapi_app/static/js/multiplexer/stores/SenderStore.ts` | NEW | Lupin | Plain reducer over `Map<sender_id, SenderRecord>`; consumes `voice_persona_assigned` / `voice_persona_released` / `notification_received` (for last-active bump); emits `store_senders_changed` |
| `src/fastapi_app/static/js/multiplexer/stores/index.ts` | NEW | Lupin | Barrel — `createStores(eventBus, storage) → {notifications, jobs, audio, actionRequired, senders}` factory wiring. **Per D-D ratification**: `audioTransport` parameter dropped; AudioStore exposes its `.binaryHandler` for boot.ts to pass through `transports.audio.start(sessionId, audioStore.binaryHandler)`. Stores never call back into transports (transport calls into stores via the handler). **Per Pass 1 F12 — canonical subscription order**: stores constructed in this order: `notifications → senders → actionRequired → audio → jobs`. Order matters because EventBus listener invocation is registration-order: NotificationStore mutates first (canonical record of the notification arrival), SenderStore second (looks up sender + bumps last_active), ActionRequiredStore third (only fires for `action_required: true` and now sees the notification already in NotificationStore if it needs to look it up), AudioStore + JobStore last (no inter-store dependencies). Order is pinned by an inline comment in `index.ts` + asserted by `stores_integration.test.ts` via microtask-boundary assertions. |
| `src/fastapi_app/static/js/multiplexer/audio/pcm-decoder.ts` | NEW | Lupin | Pure synchronous function: `pcm16ToAudioBuffer(buf: ArrayBuffer \| Blob, sampleRate=24000): AudioBuffer`. Manual Int16→Float32 conversion + `AudioContext.createBuffer(1, frameCount, sampleRate)`. Matches legacy `notifications.js:4580-4596` — server emits **raw 24kHz PCM16, NOT an encoded container**, so `AudioContext.decodeAudioData` is the wrong primitive (it expects WAV/MP3/Opus headers and would reject every frame). Stateless. Consumed by AudioStore. **Ratified D-A 2026-05-04 PM.** |
| `src/fastapi_app/static/js/multiplexer/shared/types.ts` | EDITED | Lupin | Append `LupinEventType` union with `store_notifications_changed` / `store_jobs_changed` / `store_audio_state_change` / `store_audio_chunk_decoded` / `store_action_required_changed` / `store_senders_changed` + `boot_complete` (per D-C); add `Notification` / `Job` / `SenderRecord` / `ActionRequiredItem` / `AudioPlaybackState` / `BootCompletePayload` interfaces. `BootCompletePayload` shape: `{handlers: {audioBinary: string, ...}}` — handler names sourced from `Function.name` for runtime verification by AC9. |
| `src/fastapi_app/static/js/multiplexer/boot.ts` | EDITED | Lupin | **Per D-D ratification (2026-05-04 PM, Option B)**: boot sequence is `createTransports(...)` (factory only) → `createStores(eventBus, storage)` → `transports.queue.start(sessionId)` → `transports.audio.start(sessionId, audioStore.binaryHandler)` — the audio handler passes through `start()` per Phase 3's existing contract; **no transport API mutation, no race window**. Stores are subscribed by side-effect of construction (each store's constructor wires its EventBus listeners). At end of boot, emit `boot_complete` on EventBus with `{handlers: {audioBinary: transports.audio.binaryHandler.name}}` payload AND mirror the same payload to `console.log("[multiplexer] boot_complete", JSON.stringify(...))` per D-C ratification — AC9's verification channel. |
| `src/tests/unit/multiplexer/notification_store.test.ts` | NEW | Lupin | Unit tests: append + dedup by id_hash; expiry sweep on `notification_expired`; unread count math; persistence round-trip via mock StorageService |
| `src/tests/unit/multiplexer/job_store.test.ts` | NEW | Lupin | Unit tests: 5-bucket placement; bucket transitions on `job_state_transition`; removal on `job_removed`; ordering preservation |
| `src/tests/unit/multiplexer/audio_store.test.ts` | NEW | Lupin | Unit tests: state-machine transitions (idle → decoding → playing → paused → ended); error path on decoder rejection; binary handler invocation count; AudioContext instantiation only on first chunk (lazy) |
| `src/tests/unit/multiplexer/action_required_store.test.ts` | NEW | Lupin | Unit tests: per-prompt actor lifecycle; **internal setInterval ticking at 1Hz**; **sys_time_update applies clockOffset (positive + negative drift cases)**; **connection_state_change to backoff/offline pauses interval + emits offline-frozen**; **connection_online resumes interval + re-reconciles**; expiry on countdown reaching zero; cancellation propagation; multi-prompt independence; clear interval on terminal state transition. **Per-store minimum: 22 tests (was 18 in original draft; D-F adds 4 new cases for the hybrid timer behavior).** |
| `src/tests/unit/multiplexer/sender_store.test.ts` | NEW | Lupin | Unit tests: lookup-or-create on first event; voice-persona assignment + release; last-active bumps; unread per-sender |
| `src/tests/unit/multiplexer/pcm_decoder.test.ts` | NEW | Lupin | Unit tests: Blob accepted; ArrayBuffer accepted; rejection on malformed payload; stateless property (no shared mutable) |
| `src/tests/unit/multiplexer/stores_integration.test.ts` | NEW | Lupin | Cross-store integration: a single `notification_received` event with `action_required: true` triggers NotificationStore append + SenderStore last-active bump + ActionRequiredStore prompt-creation; ordering deterministic |
| `src/tests/smoke/test_multiplexer_phase4_smoke.py` | NEW | Lupin | Playwright page-load smoke: with stub event stream replayed via `page.evaluate`, all stores reach expected state within 2s; binary chunk arrives via real AudioTransport binary path on :7999 audio WS |

**No CoSA edits**: All files under `src/fastapi_app/static/js/multiplexer/`, `src/fastapi_app/static/js/multiplexer/audio/`, and `src/tests/` (Lupin parent). Per `feedback_lupin_only_never_cosa`.

## Store contracts (the inputs to Phase 5+)

These public APIs are what Phase 5 (renderer) and Phase 6 (feature parity) consume. They MUST stay stable across the review pipeline + Phase 4 implementation; if review surfaces a contract change, it ripples into Phase 5 design.

### NotificationStore

```ts
export interface Notification {
  id_hash         : string;
  ts              : number;        // ms epoch
  sender_id       : string;
  message         : string;
  title?          : string;
  action_required : boolean;
  expires_at?     : number;        // ms epoch
  responded?      : boolean;
}

export interface NotificationStore {
  list(): ReadonlyArray<Notification>;          // active (not expired, not history)
  history(): ReadonlyArray<Notification>;        // expired or older than retention window
  unreadCount(): number;
  markRead(idHash: string): void;
  // Listeners: subscribe via EventBus to "store_notifications_changed"
}
```

**Reducer contract**:
- `notification_received` → append to active list (dedup by `id_hash`); bump unread on EVERY arrival (per Pass 1 Finding F3 — design previously implied "addressed-to-self" conditional, but no addressee field exists on the payload + no canonical client-side predicate; simplest correct rule is "every arrival bumps unread"); emit `store_notifications_changed { changeKind: "added", id_hash }`
- `notification_responded` → mark `responded=true` on matching `id_hash`; emit `store_notifications_changed { changeKind: "updated", id_hash }`. **Per Pass 1 Finding F11**: NotificationStore reduces ONLY its own slice — does NOT call into ActionRequiredStore. ActionRequiredStore subscribes to the same `notification_responded` event independently via EventBus per the inter-module rule (Phase 2 §architectural posture). No store-to-store calls anywhere in Phase 4.
- `notification_expired` → move from active to history; emit `store_notifications_changed { changeKind: "expired", id_hash }`
- **Periodic expiry sweep on `sys_time_update`** (per Pass 1 Finding F4): any active item with `expires_at < now` mutates state directly (no synthesized event re-emit) and emits `store_notifications_changed { changeKind: "expired", id_hash, source: "local-sweep" }`. The `source: "local-sweep"` payload field distinguishes from server-driven expiry. If a real server `notification_expired` arrives subsequently for the same `id_hash`, the reducer is idempotent (no-op — item already in history). Unit test required: double-expire race (local sweep fires + server frame arrives within same microtask) results in single history entry.

**Persistence (per Q2 ratification 2026-05-04 PM, Option A — unread count only)**:
- **Persisted envelope**: `StorageService.getJSON<{count: number, lastSeenTs: number}>("notifications:unread-count")` — single key, ~80 bytes per write. Phase 2 StorageService prepends `lupin:` prefix automatically.
- **Schema versioning**: envelope MUST include `schemaVersion: 1` per Phase 2 contract (Pass 1 Finding F5). Schema mismatch on read → `getJSON` returns `null` + emits `storage_corrupt` event (Phase 2 plumbing); store treats `null` as "fresh user, count=0".
- **Write debouncing** (Pass 1 Finding F5): every `unread_count` mutation calls `setJSON` debounced via 250ms tail debounce or `requestIdleCallback` — burst notifications must not thrash localStorage. In-memory `unread_count` is primary; persisted copy is a snapshot for next-load.
- **Hydration on construct**: emits `store_notifications_changed { changeKind: "hydrated" }` so renderers can do initial paint of the unread badge without waiting for the first WS frame.
- **Active list does NOT persist**: rebuilds from server event replay on `auth_success` (server buffers recent events per `routers/websocket.py` — Phase 4 implementation MUST verify this contract before close, escalate as blocker if missing). Trade-off accepted per Q2: list pane shows brief "no notifications" for 100-500ms post-load until first event-replay frame arrives. Avoids schema-migration headache + storage-volume cost of persisting full list.

### JobStore

```ts
export interface Job {
  id_hash      : string;
  job_type     : string;            // "DeepResearchJob", "PodcastGeneratorJob", etc.
  // Server-side authoritative status enum per cj-flow JobState (running_fifo_queue.py:1024, :147)
  status       : "todo" | "running" | "done" | "dead";
  created_at   : number;
  started_at?  : number;
  completed_at?: number;
  meta         : Record<string, unknown>;   // job-type-specific payload
}

export interface JobStore {
  bucket(name: "todo" | "running" | "done" | "dead" | "history"): ReadonlyArray<Job>;
  getById(idHash: string): Job | undefined;
  // Per Q7 ratification 2026-05-04 PM: history bucket starts empty; in-session
  // job_removed events accumulate live, but cross-session history requires the
  // explicit hydrate call below from Phase 5+ renderer (e.g., on history pane mount).
  hydrateHistory(api: ApiClient): Promise<void>;
  isHistoryHydrated(): boolean;
}
```

**Per Q7 ratification (2026-05-04 PM, Option B — lazy via Phase 5+ renderer)**: JobStore ships in Phase 4 with NO ApiClient dependency at construct time. The history bucket starts empty; live `job_removed` events for done/dead jobs append in-session. Phase 5+ renderer calls `hydrateHistory(api)` when the history pane mounts; the call:
- Fetches the canonical history endpoint (server URL TBD at Phase 5 — Phase 4 implementation MUST verify the endpoint exists during impl)
- Dedups response entries by `id_hash` against any in-session entries already in the bucket (so a job that completed during the session AND appears in server history doesn't double-count)
- Sets `_historyHydrated = true`; subsequent calls are no-ops
- Emits `store_jobs_changed { changeKind: "hydrated", bucket: "history" }`

Renderers can check `isHistoryHydrated()` to decide whether to show "Load history" CTA, spinner, or pre-populated list.

**Status vs bucket clarification (per Pass 1 Finding F18)**: `Job.status` is the server-side authoritative cj-flow state (4 values). `JobStore.bucket()` accepts a 5th view name `"history"` which is a **reducer-derived UI view**, not a `status` value. A job in the `history` bucket has `status ∈ {"done", "dead"}`. The reducer moves done/dead jobs to `history` on `job_removed`. Tests assert this invariant: every Job in `bucket("history")` has `status === "done" || status === "dead"`.

**Reducer contract**:
- `job_state_transition` → move job between buckets per `from` / `to` fields; emit `store_jobs_changed { changeKind: "transitioned", id_hash, from, to }`
- `job_removed` → remove from current bucket; if status was `done` or `dead`, append to `history`; emit `store_jobs_changed { changeKind: "removed", id_hash }`
- No persistence — jobs hydrate from `/api/get-queue/{name}` on first load via Phase 5+ renderer; Phase 4 only handles the live event stream

### AudioStore (XState)

```ts
export type AudioPlaybackState = "idle" | "decoding" | "playing" | "paused" | "ended" | "error";

export interface AudioStore {
  state(): AudioPlaybackState;
  queueLength(): number;
  // binary handler bound to AudioTransport; AudioStore is the AudioTransport's binaryHandler.
  // Public mutators (per Pass 1 F13: kept in Phase 4 public API; Phase 6 wires UI;
  // Phase 4 unit tests exercise the state-machine transitions through DIRECT method
  // invocation — no UI required, no dead API in Phase 4):
  pause(): void;
  resume(): void;
  skip(): void;
  // Listeners: "store_audio_state_change" + "store_audio_chunk_decoded" via EventBus
  // (chunk_decoded payload = AudioBuffer produced by pcm16ToAudioBuffer per D-A)
}
```

**XState actor (tracker pattern per Q5 ratification 2026-05-04 PM)**:
- Machine tracks state graph only; side effects (PCM decode, `AudioContext.createBufferSource`, EventBus emissions, playback scheduling) live in the wrapping `AudioStoreImpl` class. Reader sees behavior in one place; emissions stay explicit and grep-able. Matches Phase 2 AuthManager + Phase 3 ConnectionStateMachine precedent.
- States: `idle` → `decoding` → `playing` → (`paused` / `ended` / `error`)
- Events: `chunk_arrived(blob)`, `chunk_decoded(audioBuffer)`, `decode_failed(err)`, `playback_ended`, `pause_requested`, `resume_requested`, `skip_requested`
- **Decoder is synchronous (per D-A ratification 2026-05-04 PM)** — `pcm16ToAudioBuffer(blob, 24000)` is pure bit-banging math (Int16Array view → Float32Array → `AudioContext.createBuffer`), runs in microseconds. The `decoding` state is therefore transient (entered + exited within one microtask); kept as an explicit state for state-machine clarity + so `decode_failed` has a definite source state.
- **Lazy `AudioContext` construction (per Q6 ratification 2026-05-04 PM)**: instantiated on first `chunk_arrived` inside the wrapping module's binary handler (NOT at AudioStore construct time). Browser autoplay policy blocks non-gestured AudioContext; lazy aligns failure with action. On `new AudioContext({sampleRate: 24000})` throw or `state === "suspended"`, emit `store_audio_state_change { state: "error", reason: "audiocontext-blocked" }` and transition machine to `error` for renderer fallback UI. Subsequent chunks reuse the cached AudioContext. Reentrancy-safe (binary handler just calls `actor.send()` after construct).
- `decode_failed` paths: (a) AudioContext blocked by autoplay policy, (b) malformed PCM16 buffer (length not a multiple of 2), (c) AudioContext OOM. All three transition to `error` state.
- No autoplay policy management at Phase 4 level — Phase 6's TTS engine handles user-gesture priming

**Replaces Phase 3's debug-logger binary handler (per D-D ratification 2026-05-04 PM, Option B)**: `boot.ts` Phase 4 wiring binds AudioStore's binary handler at transport-start time, NOT via post-start mutation. AudioStore exposes a public named bound method:

```ts
class AudioStoreImpl implements AudioStore {
  // Named so Function.name === "audioStoreBinaryHandler" for AC9 verification
  readonly binaryHandler = function audioStoreBinaryHandler(this: AudioStoreImpl, blob: Blob | ArrayBuffer): void {
    this._actor.send({ type: "chunk_arrived", blob });
  }.bind(this);
}
```

boot.ts then calls `transports.audio.start(sessionId, audioStore.binaryHandler)` per Phase 3's `start(sessionId, binaryHandler?)` contract — handler is bound at WS open time and never changes. Phase 3's default `console.debug("Audio chunk received", ...)` is therefore never reached in production wiring; AudioStore IS the consumer from the first chunk onward, with zero race window.

### ActionRequiredStore (XState)

```ts
export interface ActionRequiredItem {
  id_hash       : string;
  prompt        : string;
  // Per Pass 1 Finding F17: response_type is canonical to ask_*() notifications;
  // Phase 5 renderer needs this to pick the input widget shape.
  response_type : "yes_no" | "multiple_choice" | "open_ended" | "open_ended_batch";
  // Options: ["yes","no"] for yes_no; user-supplied list for multiple_choice;
  // [] for open_ended/open_ended_batch (prompt is freeform-text)
  options       : ReadonlyArray<string>;
  default?      : string;                          // returned on expiry
  expires_at    : number;                          // ms epoch
  state         : "pending" | "responded" | "expired" | "cancelled";
  response?     : string;                          // populated on respond
}

export interface ActionRequiredStore {
  list(): ReadonlyArray<ActionRequiredItem>;
  getById(idHash: string): ActionRequiredItem | undefined;
  respond(idHash: string, response: string): void;        // user-initiated; sends via ApiClient
  // Listeners: "store_action_required_changed"
}
```

**XState — one actor per active prompt (tracker pattern per Q5 ratification 2026-05-04 PM)**:
- Per-actor machine tracks state graph (`pending → responded | expired | cancelled`); side effects (setInterval scheduling, ApiClient POST, EventBus emissions, sys_time_update + connection_state_change subscriptions) live in the wrapping `ActionRequiredStoreImpl` class. Spawning + lifecycle management uses XState's `spawn` primitive but the spawned actors are also tracker-pattern (no `invoke` services).
- Spawned on `notification_received` with `action_required: true`
- States: `pending` → `responded` | `expired` | `cancelled`
- **Countdown tick source (per D-F ratification 2026-05-04 PM, Option 2 — hybrid)**:
  - Each actor maintains an internal `setInterval(1000)` for smooth 1Hz UX
  - Each tick: compute `Math.max(0, expires_at - (Date.now() + clockOffset))`, emit `store_action_required_changed { countdownMs: remaining }`
  - Subscribes to `sys_time_update`: treats `event.payload.serverTime` as authoritative; updates `clockOffset = serverTime - Date.now()`. Reconciliation runs every 5-60s (per `app_debug` server cadence) and prevents unbounded client-clock drift (mobile NTP drift, sleep/wake clock skew).
  - Subscribes to `connection_state_change`: on transition to `backoff`/`offline`/`failed`, **pause internal interval** + emit `store_action_required_changed { state: "pending", reason: "offline-frozen", countdownMs: lastValue }` for UI to display "⚠ offline — countdown paused". On `connection_online`, resume interval; next `sys_time_update` re-reconciles offset.
  - On state transition to `responded`/`expired`/`cancelled`: clear interval; actor stops ticking.
- Auto-transition to `expired` when countdown reaches zero (sets `response = default` if provided). Per Q3 ratification: local-only transition, do NOT POST `default` back to server (server has its own expiry timer; local POST risks double-respond).
- `respond(idHash, response)` POSTs to `/api/notify/response` via ApiClient + transitions to `responded`
- `cancelled` reachable via incoming `notification_responded` event from server (e.g., another browser window of the same user responded first via the SAME tab — single-tab policy per Q12 means peer-tab fanout is N/A; "another tab responded first" rationale becomes server-side bookkeeping only). **Phase 4 implementation MUST verify** at `src/cosa/rest/routers/notifications.py` + `src/cosa/rest/websocket_manager.py` that responding to a notification fans out a `notification_responded` event back to the responding session's WS (Pass 1 Finding F8); if the server does not echo the response back, ActionRequiredStore needs an alternate reachability path to `cancelled` (e.g., the local `respond()` method transitions immediately).
- `clockOffset` lives in actor context (not on `ActionRequiredItem`); per-actor isolation (each prompt has its own offset, though they should converge to the same value within a microsecond after the first `sys_time_update`)

### SenderStore

```ts
export interface SenderRecord {
  sender_id        : string;
  display_name     : string;
  last_active_ts   : number;
  unread_count     : number;
  voice_persona?   : {
    name     : string;   // human-readable persona name (e.g., "Tiberius")
    voice_id : string;   // ElevenLabs voice_id — consumed by Phase 6 TTS routing per legacy `getVoiceIdForSender` (notifications.js:9000)
    icon     : string;   // emoji or icon ID for sender card display
    color    : string;   // hex color for sender card badge / mic-monopoly pin
    borrowed : boolean;  // true if persona is borrowed from another sender (visual cue per legacy)
  };
}

export interface SenderStore {
  get(senderId: string): SenderRecord | undefined;
  list(): ReadonlyArray<SenderRecord>;
}
```

**`voice_persona` field set rationale (per D-E ratification 2026-05-04 PM)**: Matches legacy `senderPersonaMap` shape at `notifications.js:128` exactly. Phase 4 ships the full field set so Phase 6 TTS routing can consume `voice_id` without forcing SenderStore to re-extend its interface mid-rebuild. Field-by-field: `voice_id` → ElevenLabs API parameter (`getVoiceIdForSender:9000`); `icon` → sender card display; `color` → badge styling + mic-monopoly pin (per `feedback_no_green_in_persona_pool`); `borrowed` → "this persona belongs to another sender" visual cue.

**Reducer contract**:
- `notification_received` → lookup-or-create sender record; bump `last_active_ts` to event ts; bump `unread_count` on every arrival (per Pass 1 Finding F3 + alignment with NotificationStore's reducer); emit `store_senders_changed { changeKind: "updated", sender_id }`
- `voice_persona_assigned` → set `voice_persona = { name, voice_id, icon, color, borrowed }` on the matching sender record (full field set per D-E ratification)
- `voice_persona_released` → clear `voice_persona`
- Cross-tab propagation: N/A per Q12 single-tab policy (see `01-phase0-decisions.md` Q12). SenderStore is tab-local; voice persona state derives from per-tab consumption of `voice_persona_assigned` / `voice_persona_released` events.

## Acceptance criteria

| AC | Verification step | Owner |
|---|---|---|
| **AC1** | All 7 source files exist at expected paths under `multiplexer/stores/` (5 stores + index.ts) + `audio/pcm-decoder.ts` + `multiplexer/shared/types.ts` updated. EXECUTOR: AI ls + cat | AI |
| **AC2** | `npx tsc --noEmit -p tsconfig.json` exit 0. EXECUTOR: AI bash | AI |
| **AC3** | `npx eslint src/fastapi_app/static/js/multiplexer/stores/ src/fastapi_app/static/js/multiplexer/audio/` exit 0. EXECUTOR: AI bash | AI |
| **AC4** | **EXECUTOR: AI bash** — `npx tsx --test src/tests/unit/multiplexer/notification_store.test.ts src/tests/unit/multiplexer/job_store.test.ts src/tests/unit/multiplexer/audio_store.test.ts src/tests/unit/multiplexer/action_required_store.test.ts src/tests/unit/multiplexer/sender_store.test.ts src/tests/unit/multiplexer/pcm_decoder.test.ts src/tests/unit/multiplexer/stores_integration.test.ts` exit 0; **per-store test floor (per Pass 1 F14 + Pass 2 A4)**: NotificationStore ≥18, JobStore ≥12, AudioStore ≥18, ActionRequiredStore ≥22 (D-F bumped from 18 +4 timer cases), SenderStore ≥10, pcm-decoder ≥6, integration ≥6 → **total Phase 4 new tests ≥ 92**; cumulative suite ≥ 214 (122 prior + 92 floor); zero failures. Final exact count recorded in execution log. | AI |
| **AC5** | **EXECUTOR: AI bash** — XState model tests for AudioStore + ActionRequiredStore pass: all reachable states reached, no unreachable transitions, all final states reachable. **Plus per Pass 1 F6 + D-F**: explicit state×event transition table tests for AudioStore (idle/decoding/playing/paused/ended/error × chunk_arrived/chunk_decoded/decode_failed/playback_ended/pause_requested/resume_requested/skip_requested) and ActionRequiredStore (pending/responded/expired/cancelled × notification_received/sys_time_update/connection_state_change/respond/notification_responded). | AI |
| **AC6** | **EXECUTOR: AI bash** — `npx c8 --include='src/fastapi_app/static/js/multiplexer/stores/**/*.ts' --include='src/fastapi_app/static/js/multiplexer/audio/pcm-decoder.ts' --reporter=text npx tsx --test ...` reports **100% lines per module** (carried-forward AC from Phase 2 upgrade). **Per Pass 2 A1**: any `c8 ignore` region MUST be accompanied by a same-line comment naming the unreachable branch + reason; AI rejects coverage runs that include un-annotated `c8 ignore` regions. No human gate on rationale acceptance — the inline-comment format is the contract. | AI |
| **AC7** | **EXECUTOR: AI Playwright** — AudioStore binary handler integration smoke against :7999 audio WS. Playwright launches with `--autoplay-policy=no-user-gesture-required` (per Pass 2 A8 — required because AC7 needs lazy-AudioContext to succeed without user gesture in headless; if flag absent, AC7 fails by design and AI escalates). Fixture mechanism (per Pass 1 F10 + Pass 2 A2): page navigation triggers a server-side test endpoint to enqueue a known PCM16 chunk on the audio WS. **Phase 4 implementation MUST verify** `/api/audio/test-chunk` (or equivalent debug endpoint) exists; if missing, AI builds the endpoint as a sub-AC (AC7a) before AC7 can run. AC7 then asserts: (a) audio WS opens within 2s; (b) AudioStore receives chunk within 1s of fixture trigger; (c) machine transitions `idle → decoding → playing` (verified via `store_audio_state_change` events on EventBus subscription); (d) zero `decode_failed` emissions on the success path. | AI |
| **AC8** | Cross-store integration: single replayed `notification_received { action_required: true }` event triggers (a) NotificationStore append, (b) SenderStore last-active bump, (c) ActionRequiredStore prompt-creation — all three `store_*_changed` events fire in deterministic order within one microtask. EXECUTOR: AI tsx --test | AI |
| **AC9** | Page-load smoke (`test_multiplexer_phase4_smoke.py`) on :7999 — `/app/multiplexer` loads; stores register; AudioStore binding verified via `boot_complete` EventBus event + paired `console.log("[multiplexer] boot_complete", JSON)` line: AI Playwright subscribes via `page.on("console", ...)` and asserts `payload.handlers.audioBinary === "audioStoreBinaryHandler"` (NOT the Phase 3 default-debug-logger name). No transport-related or store-related console errors. **EXECUTOR: AI** Playwright. **Ratified D-C 2026-05-04 PM (Option B)**: Phase 1 no-globals invariant preserved; verification mechanism is the production code path, not a debug-only handle. |
| **AC10** | **EXECUTOR: AI bash** — Phase 1 + Phase 2 + Phase 3 verification suites still green; no regressions. Enumerated commands (per Pass 1 F15): (1) `npx tsc --noEmit -p tsconfig.json` exit 0; (2) `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; (3) `pytest src/tests/smoke/test_multiplexer_phase1_smoke.py -v` 7/7 PASS; (4) Phase 2 unit tests (subset of AC4 command, but explicitly carried forward): `npx tsx --test src/tests/unit/multiplexer/{api_client,auth_manager,broadcast,event_bus,storage_service}.test.ts` ≥ 59/59 PASS (Phase 2 baseline); (5) `pytest src/tests/smoke/test_multiplexer_phase3_smoke.py -v` 1/1 PASS; (6) `pytest src/tests/websocket_smoke/test_multiplexer_transport.py -v` 4/4 PASS; (7) Phase 3 unit tests subset: `npx tsx --test src/tests/unit/multiplexer/{ws_channel,connection_state_machine,queue_transport,audio_transport}.test.ts` ≥ 62/62 PASS (Phase 3 baseline post-D1, was 65 before CC stub deletion). | AI |

## Verification matrix

All run on :7999 (AI-discretionary) per `01-working-contract.md`. User is never the tester per CLAUDE.local.md. **EXECUTOR: AI for every row** (per Pass 2 A6 — explicit per-row tag rather than a single section-level disclaimer).

| Layer | Executor | Command | Pass criterion |
|---|---|---|---|
| TS compile | AI bash | `npx tsc --noEmit -p tsconfig.json` | exit 0 |
| ESLint | AI bash | `npx eslint src/fastapi_app/static/js/multiplexer/` | exit 0 |
| Unit tests | AI bash | `npx tsx --test src/tests/unit/multiplexer/*.ts` | exit 0; total ≥ 214 (122 prior + 92 floor per AC4); zero failures; final exact count recorded in execution log |
| Coverage | AI bash | `npx c8 --include='src/fastapi_app/static/js/multiplexer/**/*.ts' --exclude='src/fastapi_app/static/js/multiplexer/boot.ts' --reporter=text npx tsx --test src/tests/unit/multiplexer/*.ts` | 100% lines per module across all modules; `c8 ignore` regions only with same-line inline comment naming branch + reason |
| Build | AI bash | `bash src/scripts/build-multiplexer.sh` | boot.js produced; **boot.js size delta vs Phase 3 baseline ≤ 30 KB gzipped** (per Pass 2 A5 — concrete bound replacing "proportional"); AI flags as concern + records final delta in execution log if exceeded |
| Phase 1 smoke | AI bash | `pytest src/tests/smoke/test_multiplexer_phase1_smoke.py -v` | 7/7 PASS |
| Phase 3 smoke | AI bash | `pytest src/tests/smoke/test_multiplexer_phase3_smoke.py -v` | 1/1 PASS |
| Phase 3 WS smoke | AI bash | `pytest src/tests/websocket_smoke/test_multiplexer_transport.py -v` | 4/4 PASS |
| Phase 4 smoke | AI Playwright | `pytest src/tests/smoke/test_multiplexer_phase4_smoke.py -v` (Playwright must launch with `--autoplay-policy=no-user-gesture-required` per AC7 + Pass 2 A8) | NEW — see AC9 + AC7 |
| AudioStore live audio WS | AI Playwright | included in Phase 4 smoke | see AC7 |

## Rollback procedure

If Phase 4 implementation introduces a regression that breaks Phase 1-3 surface:

0. **EXECUTOR: AI** — Trigger detection (per Pass 2 A7): IF any Phase 1+2+3 verification command from the verification matrix returns non-zero AND `git blame` of the failing source line points at a Phase 4 commit (or the failing test file is a Phase 4-new file), AI MUST notify the user via `cosa-voice` `ask_yes_no` "Phase 4 broke X — auto-revert Phase 4 commit? [Y/n]" with full failure trace in the abstract field BEFORE executing step 1. AI does not silently revert. If the user declines, AI investigates instead and surfaces options.
1. **EXECUTOR: AI bash** — `git revert <phase4-commit>` (the Phase 4 implementation commit lands as a single commit; revert is one-shot). Only after user approves step 0.
2. **EXECUTOR: AI bash** — re-run full Phase 1+2+3 verification suite to confirm restored to spine state
3. **EXECUTOR: AI bash** — `bash src/scripts/build-multiplexer.sh` to regenerate boot.js without store code; restore previous content-hashed manifest
4. Phase 4 design doc gets a "rollback rationale" appendix; root cause + fix proposal feed into Phase 4-redo design draft

## Open Questions

| # | Question | Suggested resolution | Status |
|---|---|---|---|
| **Q1** | AudioStore — should the PCM decoder be a separate module (`audio/pcm-decoder.ts`) or live inside AudioStore? | **RATIFIED D-A 2026-05-04 PM**: Separate module — `pcm16ToAudioBuffer(buf, sampleRate=24000): AudioBuffer` (synchronous; matches legacy `notifications.js:4580-4596`). Original draft proposed `decodeAudioData` which would reject every frame (server sends raw PCM16, not an encoded container). AudioStore imports as: `import { pcm16ToAudioBuffer } from "../audio/pcm-decoder"`. | ✅ RATIFIED |
| **Q2** | NotificationStore persistence — only unread count, or also active list (so reload doesn't lose in-flight notifications)? | **RATIFIED 2026-05-04 PM (Option A): unread count only.** Persisted envelope `{schemaVersion: 1, count, lastSeenTs}` ~80 bytes. Write debounced (250ms tail or `requestIdleCallback`). Schema mismatch returns null + emits `storage_corrupt` per Phase 2. Active list rebuilds from server event replay on `auth_success`. **Per Pass 2 A10 + Pass 1 F4 — server-side replay claim verification**: Phase 4 implementation MUST verify the buffer-and-send mechanism at `src/cosa/rest/routers/websocket.py` (look for `auth_success` handler enqueuing recent events from queue) AND `src/cosa/rest/websocket_manager.py`. If the server does not actually replay buffered events on `auth_success`, this is a Phase 4 BLOCKER — escalate via `cosa-voice` `ask_yes_no` "server replay missing; build it server-side OR pivot Q2 to full-list persistence?" before declaring Phase 4 done. Cite file:line in execution log on close. Trade accepted: list pane shows brief "no notifications" 100-500ms post-load; avoids schema-migration headache + storage-volume cost. | ✅ RATIFIED |
| **Q3** | ActionRequiredStore — when a prompt expires locally (countdown hits zero), do we POST `default` back to server, or just transition to `expired` and rely on server-side expiry to do the same? | **Just transition locally; do NOT POST.** Server has its own expiry timer (per `routers/notifications.py` `timeout_seconds`); local POST risks double-respond if the server has already expired the prompt. Local `expired` state is for UI hiding only. **Plus: countdown tick source is hybrid per D-F (setInterval + sys_time_update reconcile + connection_state_change freeze).** | ✅ RATIFIED via D-F 2026-05-04 PM |
| **Q4** | Cross-tab via BroadcastChannel — which store events propagate? | **SIDESTEPPED via Q12 (2026-05-04 PM)**: multiplexer is single-tab; no Phase 4 store broadcasts cross-tab. Phase 2's `broadcast.ts` is inert. See `01-phase0-decisions.md` Q12 for the policy + `TODO.md` for the Phase 2 cleanup follow-up. | ✅ RATIFIED via Q12 |
| **Q5** | XState v5 actor pattern — re-use Phase 2 AuthManager's "tracker pattern" (state-tracking only, external code drives transitions) or use full autonomous-actor pattern (services invoke side effects)? | **RATIFIED 2026-05-04 PM: Tracker pattern.** Matches Phase 2 AuthManager (`auth/AuthManager.ts:55-115` — XState v5 tracker with idle/refreshing/ready/expired states, side effects in class methods) + Phase 3 ConnectionStateMachine (`transport/ConnectionStateMachine.ts:1-50` — XState v5 tracker with connecting/connected/reconnecting/backoff/offline/failed states, transport class drives transitions) — single XState pattern across spine + stores. Side effects (PCM decode, AudioContext calls, timer scheduling, EventBus emissions) live in the wrapping module; XState machine tracks state graph only. Reasons: precedent consistency, EventBus emissions stay grep-able and explicit, debug surface is smaller (no async actor-service layer). Phase 6 may revisit autonomous-actor for TTS engine if declarative service composition becomes a clear win there. (File:line cites added per Pass 2 A11.) | ✅ RATIFIED |
| **Q6** | AudioStore + AudioContext lifecycle — do we instantiate `AudioContext` lazily on first chunk (browser autoplay policy may require gesture), or eagerly on store construct? | **RATIFIED 2026-05-04 PM (Option A): Lazy on first chunk.** Browser autoplay policy is the dispositive constraint — eager would produce boot-time errors for users who never play audio. Lazy aligns failure with action: first chunk arrives → instantiate AudioContext → if blocked, emit `store_audio_state_change { state: "error", reason: "audiocontext-blocked" }`. Pairs cleanly with Phase 6 user-gesture priming. First-chunk latency tax (~5-50ms) is small relative to TTS chunk cadence. Playwright AC7 must launch with `--autoplay-policy=no-user-gesture-required` per Pass 2 Finding A8. | ✅ RATIFIED |
| **Q7** | JobStore bucket history — server has `/api/get-queue/history`; do we hydrate that on construct or lazy-load when renderer first asks? | **RATIFIED 2026-05-04 PM (Option B): Lazy via Phase 5+ renderer.** JobStore ships with no ApiClient dependency at construct; exposes public `hydrateHistory(api): Promise<void>` + `isHistoryHydrated(): boolean`. History bucket starts empty + populated by in-session `job_removed` reducer; full server history loaded on-demand by Phase 5+ renderer with dedup by `id_hash`. Composes cleanly with Phase 6's planned `JobCompletionCache`. | ✅ RATIFIED |

## Self-audit against feedback memory

| Memory | Compliance |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ Phase 4 design doc lands BEFORE Phase 4 code |
| `feedback_documentation_first_protocol` | ✅ This doc is the documentation gate before code |
| `feedback_plans_include_tracking_docs` | ✅ Phase 4 section in `90-execution-log.md` opens after user approval |
| `feedback_comprehensive_automated_testing` | ✅ Verification matrix routes through TS compile + ESLint + unit + coverage + build + Phase 1/3 smoke regressions + Phase 4 smoke + audio integration |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/` and `src/tests/` (Lupin parent) |
| `feedback_never_auto_commit_push` | ✅ Phase 4 commit only after user explicit authorization post-implementation |
| `feedback_audit_plans_at_execute_time` | ✅ Implementation phase will re-audit this design doc at execute time |
| `feedback_tests_parameterize_base_url` | ✅ Phase 4 smoke test parameterizes via `LUPIN_API_URL` (default :7999) |
| `feedback_sweep_for_pattern_offenders` | ✅ Implementation will grep for residual ClaudeCode references before close per the sweep precedent set by D1 ratification |
| `feedback_no_defensive_programming` | ✅ Stores will use explicit `x !== undefined` checks, not `getattr`-style defensive fallbacks |
| `feedback_e2e_two_phase_gate` | n/a — Phase 4 is unit + smoke only; no E2E in this phase |
| `feedback_test_server_monopolize_mode` | n/a — all Phase 4 venue is :7999 (AI-discretionary) |
| `feedback_no_green_in_persona_pool` | n/a — Phase 4 doesn't allocate persona colors |
| `feedback_skip_rnd_doc_for_trivial_fixes` | n/a — Phase 4 is non-trivial; full doc applies |

No violations detected at draft time.

---

## Plan-review slot table (per Q11 amendment)

For the canonical `planning-is-prompting/workflow/plan-review.md` review pipeline. Filled in for the per-phase review pass:

| Slot | Value |
|---|---|
| `{{PLAN_DOC_PATHS}}` | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/05-phase4-stores-design.md` |
| `{{ANCHOR_DOCS}}` | `~/.claude/CLAUDE.md`, Lupin `CLAUDE.md` + `CLAUDE.local.md`, `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/01-working-contract.md`, `01-phase0-decisions.md` |
| `{{PRIOR_DESIGN_DOCS}}` | `02-phase1-scaffolding-design.md`, `03-phase2-foundation-design.md`, `04-phase3-transport-design.md` (with D1 amendment banner) |
| `{{TBD_QUESTIONS}}` | Q1-Q7 in §"Open Questions" above |
| `{{IDEMPOTENCY_MARKER}}` | `last-reviewed-at: 2026-05-04 (post-review commit hash will land at user final-go-ahead per Pass 2 A9 — EXECUTOR: AI overwrites the "Last reviewed" line at end-of-doc with `last-reviewed-at: YYYY-MM-DD (commit-hash)` per PIP §12 immediately after final go-ahead + Resolution Loop closure)` |
| `{{PHASE_NUM}}` | 4 |
| `{{PHASE_NAME}}` | Domain stores |
| `{{IMPLEMENTATION_VENUE}}` | :7999 (AI-discretionary) per `01-working-contract.md` |

---

## Prior art referenced (per PIP §4 — REUSE pre-pass outcomes 2026-05-04 PM)

The REUSE pre-pass surfaced existing prior art for several Phase 4 components. This section persists those pointers past review for use at code-write time:

### Reuse-as-is (patterns)

| Phase 4 element | Existing pattern (file:line) | Notes |
|---|---|---|
| `createStores(eventBus, storage)` factory shape | `multiplexer/transport/index.ts:31` (`createTransports(authManager, eventBus, baseUrl)`) | Copy factory shape exactly; same idiom, same return-shape convention |
| `tsx --test` + `c8` test idiom | `multiplexer/tests/event_bus.test.ts`, `auth_manager.test.ts`, `connection_state_machine.test.ts`, etc. (existing 9 unit-test files) | Established Phase 2/3 idiom; just compose multiple stores under one EventBus for integration tests |
| Playwright page-load smoke | `src/tests/smoke/test_multiplexer_phase1_smoke.py`, `test_multiplexer_phase3_smoke.py` | Existing Playwright scaffolding; new file follows established shape |
| AudioStore as `binaryHandler` for AudioTransport | `multiplexer/transport/AudioTransport.ts:35-38` (`defaultBinaryHandler` documented as Phase-4-replaceable) + `:56-59` (`start(sessionId, binaryHandler?)` already accepts override) | Pure boot.ts wiring change per D-D Option B; zero new transport code |
| `lupin:` storage key prefix | `multiplexer/shared/StorageService.ts:16` (`KEY_PREFIX = "lupin:"` already prepends) | Phase 4 keys are just `notifications:unread-count`; StorageService prepends prefix automatically |

### Extend-existing

| Phase 4 element | Legacy prior art (file:line) | What's reused |
|---|---|---|
| `pcm-decoder.ts` (`pcm16ToAudioBuffer`) | `notifications.js:4580-4596` | Manual Int16→Float32 conversion + `AudioContext.createBuffer(1, frameCount, 24000)` — port the working bit-banging exactly. Per D-A. |
| AudioStore PCM playback path | `notifications.js:4546` (`playPCMChunk`), `:4536` (`initPCMAudioContext`), `:84-88` (state vars) | Lazy AudioContext init + suspended-resume pattern. Translate to XState states + tracker pattern per Q5 + Q6. |
| ActionRequiredStore lifecycle | `notifications.js:236-237` (`actionRequiredNotifications` + `countdownTimers` Maps), `:14968-15020` (`startCountdownTimer` interval-based countdown), `:12625` (active-iter), `:12895` (`actionRequiredNotifications.set`), `:15020` (interval handle storage) | Lifecycle states + countdown + expiry semantics. Replace `setInterval` per-prompt with hybrid (per-actor `setInterval(1000)` + `sys_time_update` reconcile + `connection_state_change` freeze) per D-F. |
| SenderStore `senderPersonaMap` | `notifications.js:128-132` (`senderPersonaMap` Map shape), `:283-292` (`senderGroups` rich record), `:5614-5628` (`voice_persona_assigned`/`released` handlers + map mutations), `:9000` (`getVoiceIdForSender`) | Full field set `{name, voice_id, icon, color, borrowed}` per D-E (matches legacy). Per-tab consumer per Q12. |
| `ActionRequiredItem` interface | `notifications.js:236` (state Map values include UI state: `default_value`, `response_type`, `options`) | Schema visible in `actionRequiredNotifications.set()` calls. Phase 4 adds `response_type` field per Pass 1 F17 — Phase 5 needs it for input widget selection. |
| `LupinEventType` union additions (8 store events + boot_complete) | `multiplexer/shared/types.ts:11-43` (existing union) | Append following Phase 3's append style. Phase 4 adds: `store_notifications_changed`, `store_jobs_changed`, `store_audio_state_change`, `store_audio_chunk_decoded`, `store_action_required_changed`, `store_senders_changed`, `boot_complete`. |

### Genuinely new

| Phase 4 element | Why no prior art is acceptable |
|---|---|
| `NotificationStore` reducer shape | Legacy uses class-method jungle in `notifications.js:236, 5654, 2607, 2616`. Greenfield isolation per Q5 — no reusable module. Translate logic patterns (dedup, expiry) without reusing code. |
| `JobStore` 5-bucket layout | Legacy hydration helpers exist (`notifications.js:5910, 6238`) but no client-side bucket data structure. cj-flow server-side bucket model is the input. |
| `Notification` / `Job` / `AudioPlaybackState` TS interfaces | First TS shape — legacy is untyped objects. Source fields from server contract at implementation time; do NOT invent additional fields. |
| `sys_time_update` as countdown tick source (with hybrid `setInterval` per D-F) | Legacy uses `sys_time_update` for clock display only (`notifications.js:2625-2635`). Novel use as countdown driver — D-F's hybrid approach mitigates the cadence issue. |

### Reuse pre-pass verifications still pending at implementation time

- `notification_play_sound` event: Phase 4 NotificationStore design proposed consuming this; REUSE found `lupin-app.ini:623` whitelists it but no server-side emitter located. Phase 4 implementation MUST grep `cosa/rest/routers/` for the emitter; if absent, drop the consumer (NotificationStore subscribes to dead silence otherwise).
- Server-side event replay on `auth_success` (Q2 dependency): Phase 4 implementation MUST verify per `routers/websocket.py` + `websocket_manager.py`; escalate if missing.
- Server-side `notification_responded` fanout for ActionRequiredStore `cancelled` reachability (F8): same verification; escalate if missing.

---

**Last reviewed**: 2026-05-04 (REUSE pre-pass + Pass 1 Fitness + Pass 2 Adversarial all closed; user ratified D-A through D-G + Q1-Q7 + Q12 single-tab policy + 21 minor wording/coverage fixes via Resolution Loop). Idempotency marker `last-reviewed-at` will receive the post-final-go-ahead commit hash per PIP §12 + Pass 2 A9 once user authorizes the Phase 4 commit.
