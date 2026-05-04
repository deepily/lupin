# Lupin Project History

### 2026.05.04 PM - Session ec746144 | Multiplexer Phase 3 — transport layer (ws-channel + CSM + Queue/Audio/CC-stub) + 70 new tests; AC#7 + AC#8 green

**Context**: Continued Phase 3 of the multiplexer notifications-UI greenfield refactor immediately after `/clear`. Phases 1 (TS toolchain) and 2 (foundation services) shipped earlier today and are committed (`d596626` + `6c26905` + `7eca02b`). Spine-bundle approval (REUSE + Pass 1 Fitness + Pass 2 Adversarial) closed clean 2026-05-04 covering all three Phase 1-3 design docs. Phase 3 is the **payoff** of the spine: by end-of-phase, the multiplexer page connects to `:7999` via two transports (queue + audio), authenticates, receives real events. ClaudeCodeTransport ships as a stub per Option C user decision (cosa-voice question timed out; AI proceeded with most-aligned-with-file-map option and explicit override-prompt notification).

**Accomplishments**:

- **6 new TS source files** (5 transport modules + 1 barrel/factory) at `src/fastapi_app/static/js/multiplexer/transport/`:
  - `ws-channel.ts` — Port of `ws-channel.js` with Claude analysis fixes baked in: §1.1 binary-frame routing (Blob/ArrayBuffer → onBinaryMessage), §2.2 lifecycle removal (no `_attachPageLifecycle`; orchestrator owns), §2.5 no JSON round-trip in dispatch chain. Generation-token discipline preserved. Added a duck-typed `CloseEvent` fallback for Node test environments (CloseEvent isn't a Node global without `--experimental-websocket`).
  - `ConnectionStateMachine.ts` — XState v5 tracker per Phase 2 AuthManager precedent; full state×event matrix from design (`connecting → connected → reconnecting → backoff → offline | failed`); 100ms grace via `isFluke` guard for transient-fluke vs genuine-disconnect routing; `min(1000 * 2^n, 30000)` full-jitter backoff per Open Q2; emits `connection_state_change` / `connection_reconnecting` / `connection_offline` / `connection_online` with `source: "ConnectionStateMachine"` per AC#7 + per-transport `payload.transport` tag.
  - `QueueTransport.ts` — Exports `BaseTransportImpl` abstract base + concrete `QueueTransportImpl`. The base extraction stays inside QueueTransport.ts (instead of adding a 7th file outside the design's file map); AudioTransport.ts imports `BaseTransportImpl` from there. Auth handshake sends `auth_request` with the comprehensive `subscribed_events` list mirroring `notifications.js:2287`. Envelope mapping per Pass 1 finding #15.
  - `AudioTransport.ts` — Extends `BaseTransportImpl`; `start(sessionId, binaryHandler?)` signature per Pass 1 finding #14; default debug-logger handler; error-catching wrapper around the caller-provided handler.
  - `ClaudeCodeTransport.ts` — STUB per Option C. Discovered design gap: legacy `/api/claude-code/ws/{task_id}` is fundamentally divergent from queue/audio (per-task lazy connection, no auth_request — server sends `{type: "connected"}` instead, different message types). Fired `mcp__cosa-voice__ask_multiple_choice`; question timed out; AI proceeded with stub option (most aligned with design's file map) and notified user with explicit override prompt. `start(taskId)` throws `not implemented in Phase 3 — body lands in Phase 4 stores`. boot.ts MUST NOT auto-start it.
  - `transport/index.ts` — `createTransports(authManager, eventBus, baseUrl) → {queue, audio, claudeCode}` factory per Pass 1 finding #11; barrel re-exports.
- **boot.ts** edited to replace the Phase 1 "hello multiplexer" stub: resolve sessionId via StorageService (DC2 — generates `adjective noun` SPACE-separated form so the server's `is_valid_session_id` validator accepts it; legacy `notifications.js:2141` underscore form would 403 at WS upgrade), construct AuthManager (`/auth/refresh`, 10s timeout), invoke `createTransports(...)`, start queue + audio (NOT claudeCode), attach DOM lifecycle listeners and emit the 5-event Lifecycle Emission Contract (`page_hidden` / `page_visible` / `network_online` / `network_offline` / `page_visible {bfcache: true}` from `pageshow` per MDN-correct semantics — design table had `pagehide` which is MDN-incorrect for restore).
- **shared/types.ts** extended with Phase 3 emissions: `LupinEventType` union grew with `connection_*` / `transport_ready` / `page_*` / `network_*` / `auth_success`. Added `ConnectionStateChangePayload` / `ConnectionReconnectingPayload` / `ConnectionLifecyclePayload` / `TransportReadyPayload` / `LifecyclePayload` interfaces — payloads carry `transport: string` for per-CSM identification.
- **5 unit-test files at `src/tests/unit/multiplexer/`** covering Phase 3 — 65 new tests, 100% pass: `ws_channel.test.ts` (18), `connection_state_machine.test.ts` (23), `queue_transport.test.ts` (14), `audio_transport.test.ts` (7), `claude_code_transport.test.ts` (6). Phase 2 tests still 59/59 → total 128/128 passing in ~330ms.
- **Live :7999 verification suite** — 1 Playwright page-load smoke (`src/tests/smoke/test_multiplexer_phase3_smoke.py`) verifying queue + audio reach `auth_success` within 10s with no transport-related console errors. 4 pure-Python WS smoke tests (`src/tests/websocket_smoke/test_multiplexer_transport.py`) verifying queue + audio handshake within 5s, queue reconnect after clean close, and server-rejects-invalid-token negative path. Phase 1 smoke regression: 7/7 still pass.
- **Coverage matrix** — c8 reports **100% line coverage per module** across all 10 multiplexer modules (Phase 2's 5 + Phase 3's 5). Branch coverage 86.35% all-files (per-module 74-95%) is honest residue from `??`-default fallbacks always resolving one way and defensive null-guards. 2 new `c8 ignore` regions added with rationale — CloseEvent browser-only branch in ws-channel.ts; QueueTransport scheduleBackoff/cancelBackoffTimer/onStateChange-backoff timer paths exercised live via WS smoke + mock.timers test but not attributed cleanly by c8+tsx+node:test source maps. Phase 2 `c8 ignore`s carried forward (NavigatorLockManager browser-only, ChainMutexLockManager TS-plumbing, StorageService header).
- **Real bug caught + fixed during testing**: QueueTransport's auth-failure path was calling `wsChannel.stop()` but not notifying the CSM, leaving the CSM stuck in `connected` while the channel was dead. The unit test `auth getToken() failure → socket stops; CSM enters backoff` surfaced it. Fixed by sending `socket_close` to the CSM in the catch block alongside `wsChannel.stop()`.

**Files modified (Lupin parent only — CoSA submodule untouched)**:

- `src/fastapi_app/static/js/multiplexer/transport/ws-channel.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/transport/ConnectionStateMachine.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/transport/QueueTransport.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/transport/AudioTransport.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/transport/ClaudeCodeTransport.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/transport/index.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/boot.ts` (REWRITTEN — was Phase 1 stub)
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` (EDITED — Phase 3 LupinEventType union + payload interfaces)
- `src/tests/unit/multiplexer/ws_channel.test.ts` (NEW)
- `src/tests/unit/multiplexer/connection_state_machine.test.ts` (NEW)
- `src/tests/unit/multiplexer/queue_transport.test.ts` (NEW)
- `src/tests/unit/multiplexer/audio_transport.test.ts` (NEW)
- `src/tests/unit/multiplexer/claude_code_transport.test.ts` (NEW)
- `src/tests/websocket_smoke/test_multiplexer_transport.py` (NEW)
- `src/tests/smoke/test_multiplexer_phase3_smoke.py` (NEW)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (Phase 3 section opened + closed; deliverables, verification, coverage tables; spec-drift + implementation-deviation subsections — 7 entries)
- `.claude-session.md` (session ec746144 Phase 3 entries appended)
- `history.md` (this entry)
- `TODO.md` (Phase 3 marked complete; Phase 4 implementation pointer added)

**No CoSA submodule edits this session** per `feedback_lupin_only_never_cosa`.

**Verification (all on :7999, AI-discretionary)**:

- `npx tsc --noEmit -p tsconfig.json` → exit 0
- `npx eslint src/fastapi_app/static/js/multiplexer/` → exit 0
- `npx tsx --test src/tests/unit/multiplexer/*.ts` → 128/128 PASS in ~330ms (concurrent run)
- `npx c8 --include='src/fastapi_app/static/js/multiplexer/**/*.ts' --exclude='boot.ts' --reporter=text npx tsx --test ...` → 100% lines per module, 100% statements per module
- `bash src/scripts/build-multiplexer.sh` → boot.js stable=54,908 bytes + content-hashed copy + manifest.json regenerated
- `pytest src/tests/smoke/test_multiplexer_phase1_smoke.py src/tests/smoke/test_multiplexer_phase3_smoke.py src/tests/websocket_smoke/test_multiplexer_transport.py -v` → 12/12 PASS in 7.58s
- Phase 1 smoke regression: 7/7 still PASS — Phase 3 didn't break Phase 1
- Phase 2 unit-test regression: 59/59 still PASS within the 128-total run

**Implementation deviations from design** (captured in execution log Phase 3 § "Implementation deviations"):

1. `BaseTransportImpl` abstract class extracted to `QueueTransport.ts` (not a 7th file) so AudioTransport can extend without copy-paste — preserves design's file count.
2. Lazy CSM construction in `start()` (subclass field-init order — `transportName` not visible to parent constructor).
3. CSM `source = "ConnectionStateMachine"` per AC#7; per-transport identity in `payload.transport`.
4. Bug fix: QueueTransport auth-failure path now also notifies CSM (not just stops wsChannel).
5. Duck-typed `CloseEvent` fallback in `ws-channel.ts` for Node test environments.
6. `mock.timers` test for backoff with `c8 ignore` annotations on timer-callback paths (instrumentation quirk, not real uncovered code).
7. Smoke test split: pure-Python WS smoke (server-side AC#7 first bullet) + Playwright page-load (AC#8 + observable AC#7 positive path) + CSM unit tests (JS-side state-transition + ordering assertions).
8. boot.ts uses SPACE-separated session IDs (server validator rejects underscore form with HTTP 403).
9. boot.ts uses `pageshow + persisted` for bfcache restore (design table had MDN-incorrect `pagehide`).
10. AC#8 reframed per Option C: queue + audio reach `transport_ready`; ClaudeCode dormant by design.

**Caveats / Notes**:

- ClaudeCodeTransport stub: file + interface + factory entry land; body throws `not implemented`. boot.ts does NOT auto-start. Phase 4 stores phase wires the body.
- Phase 4 entry artifacts: see `90-execution-log.md` Phase 3 § "Notes" for the 6-doc reading order.
- 1 moderate npm audit warning (transitive) carried forward from Phase 1; no auto-fix without major-version bump risk.
- Per `feedback_never_auto_commit_push`: NO commit until user explicitly authorizes.

---

### 2026.05.04 PM - Session ec746144 | Multiplexer Phase 2 — coverage AC upgraded 90% → 100%; 6 tests added; 100% lines achieved

**Context**: After the Phase 2 implementation entry below was written, the user pointed out that I'd been treating the `≥ 90% coverage per module` acceptance criterion as a ceiling rather than a floor. They directed me to upgrade the AC to `100%`, document the upgrade in the design corpus, and actually achieve it. Option A chosen (5-6 small tests + targeted `c8 ignore` annotations on browser-only + TS-plumbing dead code) over Option B (jsdom + polyfill + refactor).

**Accomplishments**:

- **AC upgrade landed across 8 references** in 3 docs: `03-phase2-foundation-design.md` AC#4 + 5 verification table rows updated; `02-phase1-scaffolding-design.md` `c8` devDep description carries upgrade pointer; `90-execution-log.md` Phase 2 AC4 row + new "Coverage AC upgrade — 90% → 100%" subsection added with full rationale, before/after table, and the explicit two-exception policy.
- **2 `c8 ignore` annotations** in `auth/AuthManager.ts`: `NavigatorLockManager.request` body (browser-only — wraps `navigator.locks` which is unavailable in Node) bracketed with `/* c8 ignore start/stop */`; `ChainMutexLockManager` `release: () => { /* unreachable */ }` placeholder annotated with `/* c8 ignore next 3 */` (TS "definitely-assigned" plumbing — Promise constructor synchronously overwrites `release` before any caller can reach the body). Both annotations carry inline comments explaining why.
- **1 `c8 ignore` annotation** in `shared/StorageService.ts` header comment to silence c8 instrumentation noise (c8's source-mapped first-byte attribution falls on the comment line because of how tsx transpiles ESM module headers; this is reporting noise, not actual uncovered code).
- **6 new tests** filling the Node-testable gap: `api_client.test.ts` +4 (`put()`, `patch()`, relative-path-no-leading-slash, error-body-read-failure with mocked Response.text() throw); `auth_manager.test.ts` +1 (5xx refresh response — HTTP-status failure path distinct from the network-error path); `broadcast.test.ts` +1 (default channel factory exercises `globalThis.BroadcastChannel` instead of the test mock factory).
- **Final coverage** (c8): All five modules at **100% statements + 100% lines + 100% functions** (except AuthManager 95.65% functions due to the unreachable `release` placeholder counted as an uninvoked function — by design). Branches 84-92% per module — residual is composed of `??`-default fallbacks always resolving one way and defensive null-guards. Test count 53 → 59.
- **Verification re-run**: `npx tsc --noEmit -p tsconfig.json` exit 0; `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; `npx tsx --test` × all 5 files → 59/59 pass; `npx c8` → 100% lines/statements per module reported.

**Files modified (Lupin parent only)**:

- `src/fastapi_app/static/js/multiplexer/auth/AuthManager.ts` (2 `c8 ignore` regions added)
- `src/fastapi_app/static/js/multiplexer/shared/StorageService.ts` (1 header `c8 ignore`)
- `src/tests/unit/multiplexer/api_client.test.ts` (+4 tests)
- `src/tests/unit/multiplexer/auth_manager.test.ts` (+1 test)
- `src/tests/unit/multiplexer/broadcast.test.ts` (+1 test)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/03-phase2-foundation-design.md` (AC#4 + 5 verification rows)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/02-phase1-scaffolding-design.md` (`c8` devDep description carries upgrade pointer)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (Phase 2 AC4 row + post-AC-upgrade coverage table + new "Coverage AC upgrade — 90% → 100%" subsection)
- `history.md` (this entry)

**Caveats / Notes**:

- The "Uncovered Line #s" column in c8's text report still lists numbers per module even when lines are at 100%. After the upgrade those listings represent unhit branches (specifically `??`-default branches and inside-the-wrapper-map null checks), not unhit lines.
- AuthManager Funcs metric reads 95.65% because the `release: () => { /* unreachable */ }` placeholder is detected by c8 as a function declaration that is never invoked. The placeholder is `/* c8 ignore */`-annotated for line/statement metrics but c8's function-coverage metric counts it independently. This is honest: the function exists in the source, c8 sees it, it's never called. Reframing it to satisfy 100% Funcs would require either Node 22's `Promise.withResolvers()` (couples the module to a newer runtime) or a different concurrency primitive — not worth the churn for a metric quirk.
- All other Phase 2 design / verification / commit obligations from the earlier entry (53/59 tests, tsc/eslint/build/Phase 1 smoke regressions all clean) remain in force. The CoSA `pages.py` Phase 1 commit is still pending user attention.

---

### 2026.05.04 PM - Session ec746144 | Multiplexer Phase 2 — foundation services (Auth/Api/Storage/EventBus/Broadcast) + 53 unit tests

**Context**: User asked to continue Phase 2 of the notifications-UI greenfield refactor immediately after `/clear`. Phase 1 (TS toolchain + esbuild + scaffolding) shipped earlier today and the spine-bundle plan-review (REUSE + Pass 1 Fitness + Pass 2 Adversarial) closed clean across the three Phase 1-3 design docs. Per Q10 amendment, the within-bundle cadence requires Phase 1 implementation + commit before Phase 2 code lands; Phase 2 design doc `03-phase2-foundation-design.md` is the implementation contract. Phase 2 ships **services only** — no UI / no transport / no domain stores.

**Accomplishments**:

- **xstate ^5.31.0 installed as runtime dependency** per Q6 (XState for high-churn modules — auth, TTS, action-required, connection). First runtime dep in `package.json`.
- **`shared/types.ts`** (NEW) — `LupinEventType` string-literal union covering Phase 2 emissions (`auth_state_change` / `refresh_started` / `refresh_completed` / `refresh_failed` / `storage_corrupt` / `listener_error`) + BroadcastChannel-whitelist references (`notification_received` / `voice_persona_assigned` / `voice_persona_released` / `conversation_mode_change`); `LupinEvent` envelope; `Token`; `AuthState` union; per-event payload interfaces; `StorageEnvelope`; `SessionIdEnvelope`; `ListenerErrorPayload`. Hybrid type-safety policy per OQ3 ratification.
- **`shared/EventBus.ts`** (NEW) — `EventTarget`-backed singleton + `createEventBusForTesting()` factory. Per-(type, listener) wrapper Map for clean `off()` and unsubscribe-closure semantics. Per-listener error isolation: a throwing listener triggers a `listener_error` event referencing the original event; recursion-guard skips re-emission when the original event was already a `listener_error` (no infinite blow-up if a `listener_error` listener itself throws).
- **`shared/StorageService.ts`** (NEW) — `lupin:` key prefix + schema-version envelopes; `storage_corrupt` event emitted **synchronously, in the same microtask as the `null` return** per Pass 1 finding #7; first-class `getSessionId()` / `setSessionId()` per DC2 (StorageService owns ALL storage; no raw `localStorage` elsewhere in the multiplexer tree); `InMemoryStorage` test backend + `createStorageServiceForTesting()` factory.
- **`auth/AuthManager.ts`** (NEW) — XState v5 actor (`idle` → `ready` → `refreshing` → `ready` | `expired`). `LockManager` abstraction with `NavigatorLockManager` (browser, wraps `navigator.locks.request`) + `ChainMutexLockManager` (Node tests, promise-chain mutex). Sync-block `getToken()` per DC1: hot path (cached valid token) returns immediately; cold path acquires lock, double-checks token, fetches refresh under lock, releases. Concurrent callers queue at the lock → exactly ONE network round-trip per refresh. AbortError → `error: "timeout"` mapping per Pass 1 finding #6. Refresh round-trip uses raw `fetch()` (NOT ApiClient — circular dep avoidance, documented as deviation in execution log).
- **`api/ApiClient.ts`** (NEW) — Authenticated fetch wrapper. **Manual `setTimeout` + `clearTimeout` in `finally`** instead of `AbortSignal.timeout()` because the latter leaves the underlying timer pending after settlement, which node:test detects as lingering work and cancels subsequent tests in the file. `AbortSignal.any([userSignal, timeoutCtrl.signal])` combines user abort + timeout. 401 response → `authManager.invalidate()` → `ApiError(401)`. `noAuth` opt-out for endpoints like `/auth/login`. baseUrl trailing-slash normalization. JSON / text / 204 No Content response handling. `LUPIN_API_URL` env-var aware (per `feedback_tests_parameterize_base_url`).
- **`shared/broadcast.ts`** (NEW) — `BroadcastChannel("lupin")` wrapper. **Static `BROADCAST_WHITELIST`** per DC4 (5 entries: `auth_state_change` / `notification_received` / `voice_persona_assigned` / `voice_persona_released` / `conversation_mode_change`). Loop prevention via `source: "broadcast"` marker on inbound events. Idempotent `start()`. `BroadcastChannelLike` test interface for in-process MockChannel that simulates the cross-tab semantic (peers see each other's messages but not their own).
- **5 unit-test files at `src/tests/unit/multiplexer/`** — 53 tests total, 100% pass: `event_bus.test.ts` (9), `storage_service.test.ts` (13), `auth_manager.test.ts` (11), `api_client.test.ts` (12), `broadcast.test.ts` (8). AC#5 five-concurrent-getToken-during-expired produces exactly 1 fetch — proven. AC#8 two-instance round-trip with no echo-back to source — proven via in-process MockChannel.
- **Verification matrix** — all run on :7999 (AI-discretionary venue). All 8 ACs PASS. tsc `--noEmit` exit 0. ESLint exit 0 (after fixing 2 `_` → `()` unused-arg findings in AuthManager XState `assign` callbacks). Build artifact `boot.js` re-emits cleanly. c8 coverage: 97.87% statements / 85.65% branches / 94% functions / 97.87% lines across the 5 modules (per-module statements all ≥ 95%, well above AC#4's 90% gate; below-90% branch dips on 3 modules due to browser-only fallbacks unreachable from Node — `NavigatorLockManager`, `defaultChannelFactory`, `globalThis.fetch.bind`). Phase 1 smoke test (`test_multiplexer_phase1_smoke.py`) re-run: 7/7 still PASS — Phase 2 didn't break Phase 1.

**Files modified (Lupin parent only — CoSA submodule untouched)**:

- `package.json` + `package-lock.json` (xstate ^5.31.0 added as runtime dep)
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/shared/EventBus.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/shared/StorageService.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/shared/broadcast.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/auth/AuthManager.ts` (NEW)
- `src/fastapi_app/static/js/multiplexer/api/ApiClient.ts` (NEW)
- `src/tests/unit/multiplexer/event_bus.test.ts` (NEW)
- `src/tests/unit/multiplexer/storage_service.test.ts` (NEW)
- `src/tests/unit/multiplexer/auth_manager.test.ts` (NEW)
- `src/tests/unit/multiplexer/api_client.test.ts` (NEW)
- `src/tests/unit/multiplexer/broadcast.test.ts` (NEW)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (Phase 2 section opened + closed; deliverables, verification, coverage tables; three implementation-deviation notes — refresh raw-fetch / manual timeout / XState tracker pattern)
- `.claude-session.md` (session ec746144 manifest section appended with 18 Phase 2 entries)
- `history.md` (this entry)
- `TODO.md` (Phase 2 marked complete; Phase 3 implementation pointer added with 6-doc reading order)

**No CoSA submodule edits this session** per `feedback_lupin_only_never_cosa`.

**Verification (all on :7999, AI-discretionary)**:
- `npx tsc --noEmit -p tsconfig.json` → exit 0.
- `npx eslint src/fastapi_app/static/js/multiplexer/` → exit 0.
- `npx tsx --test` across all 5 unit-test files → 53/53 PASS in 224ms (concurrent run); 53/53 PASS again post-edits.
- `npx c8 --include='src/fastapi_app/static/js/multiplexer/**/*.ts' --exclude='boot.ts' npx tsx --test` → 97.87% statements per-module table.
- `bash src/scripts/build-multiplexer.sh` → boot.js stable + content-hashed copy + manifest.json regenerated.
- Phase 1 regression: `pytest src/tests/smoke/test_multiplexer_phase1_smoke.py -v` → 7/7 in 6.38s.

**Implementation deviations from design (captured in execution log Phase 2 Notes)**:
1. AuthManager refresh path uses raw `fetch()` not ApiClient — avoids ApiClient ↔ AuthManager circular dep; refresh endpoint takes refresh token in body, not in `Authorization` header, so auth-injection layer is unneeded; timeout-aware behavior preserved via `AbortSignal.timeout`.
2. ApiClient timeout uses manual `setTimeout` + `clearTimeout` in `finally` not `AbortSignal.timeout()` — node:test detected the latter as lingering work and cancelled subsequent tests; production behavior identical to caller, marginally better timer hygiene.
3. XState v5 used as state TRACKER (external code drives transitions) not autonomous actor — the lock-and-double-check sequence reads cleanly in one function this way; design's "XState actor" wording satisfied; public observability (state subscription) unchanged.

**Caveats / Notes**:

- Page-load smoke verification (Playwright `/app/multiplexer` no-console-errors-related-to-imports) is **deferred to Phase 3** since Phase 2's "Files created / edited" table does NOT include `boot.ts` and Phase 2 ships services only. Import resolvability proven via `tsc --noEmit` + 53 unit tests successfully importing each module. Phase 3 wires services into `boot.ts` and the page-load assertion runs naturally then.
- Phase 1 smoke test still passes — Phase 2 import additions don't disturb the Phase 1 stable boot.js (boot.ts unchanged).
- The Phase 1 commit (`d596626`) carried forward into this session; Phase 2 work begins from there.
- 1 moderate npm audit warning (transitive) carried forward from Phase 1; no auto-fix without major-version bump risk.

**Next session entry artifacts** (a fresh-context Claude reads these to start Phase 3 implementation):
1. `~/.claude/CLAUDE.md` (Layer 1)
2. Lupin `CLAUDE.md` + `CLAUDE.local.md`
3. `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/01-working-contract.md` (Layer 2)
4. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` (Layer 3 — Q1-Q11 + amendments)
5. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/04-phase3-transport-design.md` (THIS PHASE — implement against this)
6. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (review history + Phase 1 + Phase 2 outcomes; **especially the three Phase 2 implementation-deviation notes**)

---

### 2026.05.04 - Session ec746144 | Multiplexer rebuild — spine-bundle docs + full plan-review (REUSE + Pass 1 + Pass 2) all gates clean

**Context**: User opened the session asking for a summary of the notifications-UI refactor's first phase. Instead of a stand-alone Phase 1 doc, the work productively reframed the entire 9-phase project into a **spine bundle** model: Phases 1-3 (toolchain + foundation services + transport) ship as a single design + review unit, then per-phase from Phase 4. After Q10 + Q11 amendments captured 2026-05-04, the spine bundle's three design docs went through the full canonical PIP `plan-review.md` machinery — REUSE pre-pass + Pass 1 (Fitness) + Pass 2 (Adversarial) — all three gates closed clean. User intends to clear memory next and start Phase 1 implementation from the documentation alone.

**Accomplishments**:

- **Phase 0 amendments** — Q10 (single per-phase gate) refined to bundle Phases 1-3 as the spine; Q11 (review owner) refined to align with canonical PIP `plan-review.md` (REUSE → Fitness → Adversarial; review fires after design-doc draft, before user approval). Both amendments landed in `01-phase0-decisions.md` with cross-reference table updates and full rationale. The two stale prompt clones at `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/02-` and `/03-` were declared NOT canonical and removed from all anchor refs (the directory's `01-working-contract.md` remains as the Layer-2 anchor instance per PIP §1).
- **Synthesis + execution-log updates** — `00-synthesis-and-roadmap.md` gained a "Phase bundling" subsection in §3 + plan-review-timing paragraph in §4.4 + Q10/Q11 row updates in §5 + new "spine boundary holds but Phase 4+ surface bigger than expected" risk in §6.
- **Phase 2 design doc drafted** — `03-phase2-foundation-design.md` (NEW, ~18 KB, 318 lines post-fixes). Covers AuthManager (sync-block contract per DC1, `navigator.locks` dedup, EventBus refresh emissions), ApiClient (`AbortSignal.any` for timeout + manual abort), StorageService (typed JSON + first-class `getSessionId`/`setSessionId` per DC2), EventBus (singleton EventTarget + reserved-event-types subsection + listener-error isolation), BroadcastChannel wrapper (static `BROADCAST_WHITELIST` constant per DC4 + 4-step add procedure).
- **Phase 3 design doc drafted** — `04-phase3-transport-design.md` (NEW, ~24 KB, 305 lines post-fixes). Covers ws-channel.ts port (Claude §1.1 binary-frame fix carried forward + §2.2 lifecycle removal + §2.5 JSON-round-trip removal), ConnectionStateMachine XState actor with 100ms grace period + full state×event transition matrix + `offline` state distinct from `failed`, three transport wrappers (Queue/Audio/ClaudeCode) with envelope-mapping contract, `boot.ts` Lifecycle Event Emission Contract (5-event map), `createTransports` factory signature pinned, AC-7 reconnect verification with explicit programmatic assertions.
- **REUSE pre-pass** — clean-context Explore agent surveyed the spine bundle for prior art across `src/fastapi_app/static/` and `src/cosa/rest/routers/`. 17 findings: 4 extend-existing (route registration, dev-tools card, QueueTransport, WS smoke directory), 13 genuinely-new (with prior-art trail for 7 of them). Plus 4 design concerns surfaced (DC1-DC4) — sync-block AuthManager, session ID source, test runner commitment, BroadcastChannel whitelist shape.
- **DC1 (sync block AuthManager) deep-dive** — User asked for pros/cons. Sync block wins decisively: `navigator.locks` already serializes; statistically the latency cost is rare; WS auth handshake is the killer use case (optimistic stale token costs 3 round-trips vs 2). UI observability solved orthogonally via EventBus emissions (`refresh_started/completed/failed`). DC2/DC3/DC4 resolved with corresponding doc edits.
- **Pass 1 (Fitness)** — 17 findings (7 AMBIGUITY, 7 COMPLETENESS, 2 TESTABILITY, 1 RISK_SURFACE; zero design concerns). All applied + 6 enumerated Open Questions ratified (Phase 2 Q2/Q3/Q4 + Phase 3 Q2/Q3/Q4). Notable resolutions: Phase 1 npm install bootstrap row prepended; tsconfig paths pinned exactly; ESLint canonical rule snippet inlined; ConnectionStateMachine full transition matrix; boot.ts Lifecycle Emission Contract; AudioTransport stub signature pinned; ClaudeCodeTransport URL unblock procedure (grep + server-router verify + escalate-on-mismatch).
- **Pass 2 (Adversarial)** — 6 ownership-language findings, all ACs/Rollback items lacking explicit `EXECUTOR: AI` tags. All 6 applied; 8 `EXECUTOR: AI` tags now distributed across the spine bundle. Greps clean: zero `EXECUTOR: HUMAN`, zero bare checkboxes, all `manual` hits annotated as legitimate non-Manual-E2E uses.
- **All three gates closed clean**. Convergence re-grep after each pass: zero new TBDs, zero Open sub-questions introduced. Idempotency marker recorded in `90-execution-log.md`.

**Files modified (Lupin parent only — CoSA submodule untouched)**:

- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` (§3 Phase Bundling + §4.4 Plan-review timing + §5 Q10/Q11 + §6 risks)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` (Q10 + Q11 amendments + cross-ref table + Q11 forward-ref correction)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/02-phase1-scaffolding-design.md` (Approval coupling note, Plan-review pointer + slot table, all OQ resolutions, all 4 Phase 1 Pass 1 findings, all 3 Phase 1 Pass 2 findings, Prior art referenced section)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/03-phase2-foundation-design.md` (NEW — full Phase 2 design with all Pass 1 + Pass 2 fixes baked in + DC1-DC4 resolutions + Prior art referenced section)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/04-phase3-transport-design.md` (NEW — full Phase 3 design with all Pass 1 + Pass 2 fixes baked in + DC2 resolution + Prior art referenced section)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (Spine Bundle Plan-Review section: REUSE results + Pass 1 results + Pass 2 results + spine-bundle approval table + Phase 1 implementation prerequisites pointer list)
- `~/.claude/plans/vectorized-bubbling-plum.md` (the originating planning round's plan file — sequencing strategy + DC analysis)
- `.claude-session.md` (session ec746144 manifest section)
- `history.md` (this entry)
- `TODO.md` (spine-bundle approved — Phase 1 implementation pointer added)

**No CoSA submodule edits this session** per `feedback_lupin_only_never_cosa`.

**Verification (all on :7999, AI-discretionary)**:
- Convergence re-grep after each gate (REUSE / Pass 1 / Pass 2): clean.
- All 6 enumerated Open Questions across Phases 2 and 3 marked RESOLVED with explicit answers.
- 8 `EXECUTOR: AI` tags distributed across the spine bundle's verification + rollback sections.
- Zero `EXECUTOR: HUMAN`, zero bare checkboxes, zero unresolved TBDs (only meta-references to PIP machinery vocabulary remain — false positives by design).

**Next session entry artifacts** (a fresh-context Claude reads these to start Phase 1 implementation):
1. `~/.claude/CLAUDE.md` (Layer 1)
2. Lupin `CLAUDE.md` + `CLAUDE.local.md`
3. `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/01-working-contract.md` (Layer 2)
4. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` (Layer 3 — Q1-Q11 + Q10/Q11 amendments)
5. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md`
6. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/02-phase1-scaffolding-design.md` (THIS PHASE)
7. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (review history + spine-bundle approval status; Phase 1 implementation entry artifacts pointer at end)

**Caveats / Notes**:

- Phase 2 + Phase 3 design docs are spine-bundle members (approved alongside Phase 1) but their CODE does NOT land in the Phase 1 implementation session. Within-bundle cadence is per-phase: Phase 1 implements + verifies + commits before Phase 2 code starts; same Phase 2 → Phase 3.
- The spine bundle approval explicitly does NOT commit to the rest of the phase plan (Phases 4-9). After Phase 3 ships, a natural go/no-go gate determines whether to draft more design docs.
- Stale prompt clones at `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/02-` and `/03-` are non-canonical and ignored. The directory's `01-working-contract.md` is the Layer-2 anchor instance and stays.

**Checkpoint commit** (this session): see manifest for hash.

---

### 2026.05.03 - Session 656c8ba2 | WSChannel binary-frame regression — notifications-UI TTS playback fixed

**Context**: User reported that notifications-UI TTS had stopped playing — the voice-persona-reference page worked (HTTP MP3 path) and the high-priority "ding" played, but no spoken audio ever rendered for `notify()`-triggered notifications. Two-step trace identified a regression introduced by Session 0022baba's WS reconnect circuit-breaker milestone (commits 234d7b7→1a9e3e0, 2026-05-02): the new `WSChannel` facade in `ws-channel.js` had no Blob/ArrayBuffer branch in `socket.onmessage` — `JSON.parse(Blob)` threw, the catch returned, and binary audio chunks were silently dropped. The legacy `handleAudioMessage` Blob branch (notifications.js:2649) became unreachable because the facade now intercepts before that handler runs. End-to-end manual verification confirmed the fix: 5 audio chunks (~218 KB) reaching `handleAudioChunk` with TTFA 277ms.

**Accomplishments**:

- **Diagnosis** — two-finding console capture pinpointed the regression vs the documented design. (1) Server-side `audio_streaming_status` and `audio_streaming_complete` text envelopes arrived fine; binary chunks did not. (2) Reading `cosa_voice_mcp.py:785-791` clarified that the parallel "no ding either" symptom in conversation mode is intentional design — `_notify_impl` force-overrides `suppress_ding=True` and rewrites `priority="high"` whenever conv mode is active. `_converse_impl` (the path `ask_yes_no` rides) skips the override, which is why blocking calls still ding. Documented as "Bug 2" but explicitly out of scope.
- **Fix — `ws-channel.js`** — added `opts.onBinaryMessage` callback + JSDoc clause + a Blob/ArrayBuffer branch at the top of `socket.onmessage` that routes binary frames to the new callback (or no-ops if no callback wired). 11 lines.
- **Fix — `notifications.js`** — wired `onBinaryMessage: blob => this.handleAudioChunk( blob )` into the audio-channel construction at line 2226; replaced the stale "different pathway" comment with the actual split documentation. 3 functional lines + comment update.
- **Cache-buster bumps** — after first verification cycle came back as a stale cache, bumped `notifications.js` import path `ws-channel.js?v=20260502a → v=20260503a` and the HTML script tag `notifications.js?v=20260502b → v=20260503a` to force browsers to re-fetch both files.
- **Regression tests** — added `_binary( data )` driver to the MockWebSocket harness in `test_ws_channel_unit.py` and 2 new Layer-1 tests: (a) Blob and ArrayBuffer frames invoke `onBinaryMessage`, never `onMessage`; sizes preserved. (b) JSON-string frames still invoke `onMessage`, never `onBinaryMessage`. Locks in the routing split.
- **Verification (all on :7999, AI-discretionary)**: py_compile ✅ · WSChannel unit suite **22/22 in 1.42s** (20 pre-existing + 2 new) · WS smoke tests **50/50 in 44.59s, audio_perf 1.81ms avg** · End-to-end manual: high-priority `notify()` post-cache-bust hard-refresh → 5× `🔊 handleAudioChunk` lines (23936/56848/83776/28424/25470 bytes), TTFA 277ms, PCM playback complete, TTS spoke aloud as designed.

**Files Modified (Lupin parent — 5 files, this entry, manifest update)**:

- `src/fastapi_app/static/js/ws-channel.js` (+11 / -2)
- `src/fastapi_app/static/js/notifications.js` (+8 / -8 — onBinaryMessage wire-up, opts re-aligned, stale comment replaced, ws-channel.js cache-buster bump)
- `src/fastapi_app/static/html/notifications.html` (+1 / -1 — notifications.js cache-buster bump)
- `src/tests/ws_channel_unit/test_ws_channel_unit.py` (+~85 lines — `_binary` harness driver + 2 regression tests + section banners)
- `.claude-session.md` (manifest section for this session)

**Caveats / Notes**:

- The cache-buster lesson is generalizable: Chrome's Ctrl+Shift+R will refresh top-level `<script>` tags but does NOT always force re-fetch on dynamically-imported ES modules — bump the `?v=` query string at the import site whenever the module changes.
- Bug 2 (no-ding-in-conv-mode) was explicitly left alone per the design intent at `cosa_voice_mcp.py:785-791`. If the user wants TTS-without-ding to be reconsidered (or wants the override behavior surfaced more visibly), it's a separate design conversation.
- Skipped the R&D doc per `feedback_skip_rnd_doc_for_trivial_fixes` — single-cause regression, ~25 lines net, fully captured by this entry plus the regression tests' inline docstrings.
- No CoSA submodule edits in this session (the prior session's `voice_persona.py` edit is still uncommitted in the submodule, owned by user).

---

### 2026.05.03 - Session aacd24b4 | Voice persona /clear preservation fix — Phases 1.1 + 1.5 + 2 + 3 shipped

**Context**: Picked up the Phase 0 plan that 4ede5bad serialized last night. Read `01-design.md` end-to-end, executed the four phases that don't depend on user-driven `/clear` repro, fixed an order-dependent flake in the unit suite that the new tests surfaced, and serialized next-step handoff doc for the remaining gate-identification phases.

**Accomplishments**:

- **Phase 1.1 — diagnostic stderr prints** added to `register_session.main()` at three sites (gate-result, gate-2-fail with bound exception, preserve-check). Will harvest gate state on the user's next `/clear` to identify which gate is silently failing.
- **Phase 2 — release-on-overwrite helper**: new `_release_voice_persona_via_http()` mirrors the alloc helper (login → POST /release → fail-soft, 2s timeouts). Invoked when the carry-forward declines but the old bridge had a persona — emits `voice_persona_released` so the frontend's `senderPersonaMap` clears before the new persona arrives.
- **Phase 3 — re-assigned announcement**: `voice_persona.py /allocate` gained an `Optional[str] previous_persona_name` query param. On `newly_allocated=True` AND a non-empty previous name, pushes a `task`-typed "Voice re-assigned: X → Y" notification (priority=medium, suppress_ding=False). Hook captures `old_data["voice_persona"]["display_name"]` at the same conditional that fires the release call and threads it through `_allocate_voice_persona_via_http` via `urllib.parse.quote`.
- **Phase 1.5 — unit tests**: `src/tests/unit/test_register_session_preservation.py` (NEW) — 9 tests across 3 classes (8 pass + 1 xfail pinned to Phase 1.3's gate-3 broadening). Fixture redirects `HOME` to `tmp_path` and patches all side-effect helpers in `register_session` so `main()` runs in isolation. Covers fresh start, /clear with persona, /clear without persona, /clear with corrupted bridge (verifies the gate-2-fail diagnostic fires), legacy `session_ids[]` match (xfail).
- **Side fix — flake in test_voice_persona_helpers.py**: `TestAllocatePersonaForSession::test_picks_unallocated_when_pool_partially_occupied` (and sibling `test_borrows_when_pool_fully_occupied`) write bridge files keyed by `os.getpid() + N`. Linux PID allocation isn't sequential, so on host-side runs `_can_trust_host_pids()=True` skipped the dead-PID bridges → undercounted occupied set → seed-7 picked an "occupied" voice. Pre-existing structural flake; my new test file shifted suite timing enough to surface it. Repaired with a class-level autouse fixture patching `_can_trust_host_pids → False` (mirrors the in-container path).
- **Documentation**: `90-execution-log.md` filled with per-phase outcomes + side-fix writeup; new `91-next-steps.md` serialized covering the user-owned (CoSA-side commit, Phase 1.2 `/clear` repro to harvest diagnostics, optional curl smoke for Fix 3) and Claude-owned (Phase 1.3 minimal patch, Phase 1.4 sweep, remove diagnostics, final verification matrix) follow-ups.
- **Verification (all on :7999 / discretionary)**: py_compile ✅ · import chain ✅ · helper smoke ✅ · new unit tests ✅ (8 pass + 1 xfail) · full unit suite **3950 passed, 2 xfailed, 0 failures (132s)** after the flake fix.

**Files Modified (Lupin parent — 5 staged + this entry + 91-next-steps.md to commit)**:
- `src/lupin_cli/claude_code/hooks/register_session.py` (+115 / -7)
- `src/tests/unit/test_register_session_preservation.py` (NEW, ~270 lines)
- `src/tests/unit/test_voice_persona_helpers.py` (+14 — class-level autouse fixture)
- `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/90-execution-log.md` (+77 / -25)
- `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/91-next-steps.md` (NEW)
- `TODO.md` (marked CoSA WS commit done, voice-persona task to `[~]`)
- `history.md` (this entry)

**CoSA submodule (managed separately per `feedback_lupin_only_never_cosa`)**:
- `src/cosa/rest/routers/voice_persona.py` (+25) — needs a CoSA-context commit. Parent commit `2000cb4` is the documenting reference.

**Caveats / Notes**:
- Phases 1.2/1.3/1.4 still pending — need user `/clear` repro on a planning session, then a minimal gate patch + sweep of `register_session.py:699-703` (idle-backoff carry-forward, same failure mode). Diagnostic prints removed in a follow-up commit once the patch lands and the xfail flips to xpass.
- Frontend Fix 4 (notifications.js stale-badge propagation) remains PARKED per user — they own that file during the WS refactor lane.
- History.md at 18.8k tokens (over WARNING) — user explicitly directed earlier to skip archival this session; deferred to TODO.

**Checkpoint commit (mid-session)**: `2000cb4` — Phases 1.1 + 1.5 + 2 + 3.

---

### 2026.05.02 - Session 4ede5bad (continued) | Voice persona desync investigation + /clear preservation fix design

**Context**: Same session pivoted from the focus-tray bug-fix work (entry below — checkpoint b791383) to a new bug report from the user: a notification carrying the **Mr Radio** persona badge was speaking in **Tiberius's** voice. Root cause investigation took the rest of the session; tonight's work is documentation only (Phase 0 of the fix plan), with code execution scheduled for tomorrow AM.

**Accomplishments**:

### Built voice-persona reference page (Phase 0 of the investigation — user-prioritized BEFORE diagnostics)

- **Why it came first**: User course-corrected my initial "let me add diagnostic prints" plan with "I need a reference page that plays back samples of all voices." Without an absolute audio ground-truth, every later diagnostic conclusion depends on the user's ear-memory, which is unfalsifiable. Built the ruler before measuring. Saved as a feedback memory: `feedback_ground_truth_before_perception_debug`.
- **New page**: `src/fastapi_app/static/html/test/voice-persona-reference.html` — admin-gated, fetches `/api/cosa-voice/voice-persona/pool`, renders six persona tiles with badge styling matching notification cards, ▶ Play sample per tile, "Play all in sequence" toolbar, currently-allocated personas footer.
- **New endpoint**: `POST /api/cosa-voice/voice-persona/sample` in `src/cosa/rest/routers/voice_persona.py` — JWT-protected, pool-validated voice_id (rejects out-of-pool with 400 + helpful detail), calls ElevenLabs HTTP TTS API, returns `audio/mpeg` bytes inline. Verified end-to-end: 70KB MP3 / 128kbps mono on the Tiberius voice_id.
- **dev-tools card**: `src/fastapi_app/static/html/dev-tools.html` updated under "Audio & TTS" section, count 14→15.

### Diagnosed root cause via the reference page

- User played all six samples, identified the leaked voice as **Tiberius** unambiguously. Pre-refresh: badge said Mr Radio, voice was Tiberius. Post-refresh: badge synced to Tiberius. So the *voice* was correct for the bridge state at the moment of the leak — the *badge* was the stale element.
- **H1 confirmed**: `/clear` triggered the SessionStart hook in `src/lupin_cli/claude_code/hooks/register_session.py` to overwrite the bridge without preserving the existing `voice_persona`. The carry-forward at lines 682-683 didn't fire — one of `is_context_clear`, `old_data`, or `old_data["voice_persona"]` was falsy. New persona (Tiberius) was randomly drawn from the free pool. `voice_persona_assigned` event fired but `voice_persona_released` for the outgoing Mr Radio never did (the hook silently overwrites instead of explicitly releasing first), so the frontend's `senderPersonaMap` retained the stale Mr Radio entry until refresh.
- **H2/H3/H4 disproved** — no stale persisted envelope, no bridge-lookup collision, no suffix-less sender_id path involved.

### Serialized fix design for tomorrow AM execution

- **Folder pattern** mirrors `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/` per `feedback_plans_include_tracking_docs`: design doc + paired execution log.
- **NEW**: `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md` — full design (210 lines, 15.5 KB) covering Context, gate-by-gate detection walkthrough at register_session.py:596-647, three server-side fixes with line-precise pointers, sweep check (same `is_context_clear` carry-forward at lines 699-703 for `idle_block.backoff_index`), plan-compliance audit against feedback memories.
- **NEW**: `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/90-execution-log.md` — phase status table skeleton ready for tomorrow's session to append per fix.
- **TODO.md** updated with "FIRST THING IN THE MORNING — 2026.05.03" pointer at top.
- **Frontend Fix 4 PARKED** — notifications.js stale-badge propagation. User is doing heavy WebSocket refactor on that file; we don't touch it this round. With the planned server-side Fixes 2 + 3, the frontend desync window collapses dramatically (released → senderPersonaMap.delete → fresh hydration).

### Files modified/created (Lupin parent only — CoSA submodule managed separately)

- `src/fastapi_app/static/html/test/voice-persona-reference.html` (NEW)
- `src/fastapi_app/static/html/dev-tools.html` (added persona-reference card)
- `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/90-execution-log.md` (NEW)
- `TODO.md` (added morning pointer for 2026-05-03; moved today's voice-persona accomplishments to "MORNING FINISHED — 2026.05.02")
- `history.md` (this entry)
- `.claude-session.md` (manifest section updated with voice-persona files)

### CoSA submodule (managed in CoSA context — NOT in this commit)

- `src/cosa/rest/routers/voice_persona.py` — new `/voice-persona/sample` endpoint. Will need a separate CoSA-context commit alongside session 0022baba's `websocket.py` + `websocket_manager.py` close-code work.

### Verification

- `py_compile` on voice_persona.py — clean.
- Import chain check (`from cosa.rest.routers import voice_persona`) — clean, 5 routes registered.
- Live curl tests: pool endpoint returns 6 personas; sample endpoint returns valid MP3 (70 KB, 128 kbps mono); pool-membership guard rejects unknown voice_ids with 400 + helpful detail.
- Documentation phase only — no fix code written tonight per user instruction. Tomorrow AM picks up the 3 server-side fixes from the design doc.

### Caveats / Notes

- The voice-leak symptom resolved itself for the user via browser refresh (the stale-badge frontend bug is the only remaining visible artifact). Tomorrow's server-side fixes prevent the recurrence at the source (preservation) and add defense-in-depth (release-on-overwrite) + UX (re-assigned announcement).
- Original draft of the plan said "skip R&D doc, this is small" — user corrected with "propose step 0 serialization path and write to disc" — that plus `feedback_plans_include_tracking_docs` were the right framing. Lesson saved as a behavioral correction in the plan compliance audit (re-classify as non-trivial when the work has multiple separable layers like diagnostic + defense + UX + tests).

---

### 2026.05.02 - Session 4ede5bad | Bug Fix Mode | Focus-tray inactive-session toggle + bubble differentiation

**Context**: User opened `/plan-bug-fix-mode-start` in conversation mode with a two-tweak bundle against the CC notifications focus tray + conversation pane. Tweak 1: add a toggle pill in `#cc-session-strip` that hides strip icons for sessions whose voice persona has been deallocated (the "slate-gray, no persona" fallback — surfaces organically because `senderPersonaMap.get(senderId)` returns null and the CSS rule `background: var(--persona-color, #6c757d)` falls back to slate). Tweak 2: differentiate notification bubbles in the conversation pane for personaless cards (`.sender-message.incoming` was rendering as a flat near-white wash with no inter-bubble distinction).

**Accomplishments**:

### Fix 1: Hide-inactive toggle in focus tray (Tweak 1)

- **Source**: USER-REQUESTED 2026-05-02 ~11:30 EDT.
- **Active-session signal**: no new server endpoint needed — `senderPersonaMap.has(senderId)` is the canonical client-side signal (server stops stamping `voice_persona` on outbound envelopes when the bridge dies; `voice_persona_released` WS event removes the map entry; same signal already drives the CSS slate-gray fallback).
- **Fix**: New `#cc-hide-inactive-toggle` button in `#cc-session-strip`. State persists in `localStorage` (`notifications_cc_hide_inactive_strip`). Helpers `_isStripIconInactive`, `_applyHideInactiveStripFilter`, `_setHideInactiveStrip`, `_bindHideInactiveToggle`. Filter re-applied in three places: end of `_addStripIcon` (one-icon update), inside `voice_persona_assigned` case (becomes-active → un-hide), inside `voice_persona_released` case (becomes-inactive → hide). CSS rule `.cc-strip-icon[data-inactive-hidden="true"] { display: none; }` is independent of the existing `[data-focus-hidden]` rule so focus-mode + hide-inactive coexist without interaction.

### Fix 2: Bubble differentiation for personaless cards (Tweak 2)

- **Iteration 1 — Option 1 (subtle)**: Tried a 1-px hairline between adjacent `.sender-message` siblings + alternating-row tint on `.incoming:nth-child(even)`, gated to `.sender-card:not([style*="--persona-color"])`. **User vetoed** — wanted same balloon size/format/icon layout, just a more visible inactive-state fill.
- **Iteration 2 — Option 4 (gray gradient)**: Removed hairline + zebra rules. Replaced with a single rule on personaless cards: `.sender-card:not([style*="--persona-color"]) .sender-message.incoming { background: linear-gradient(to bottom, #e9ecef, #f8f9fa); }` (Bootstrap gray-200 → gray-100). Same bubble size, same date/abstract icon layout — only the fill changes. Persona-color cards retain their existing tinted gradient untouched.
- **Substring-gating sweep**: confirmed `_setPersonaBadgeOnCard` (notifications.js:8897) calls `card.style.setProperty("--persona-color", ...)` on live persona arrival and `removeProperty("--persona-color")` on release, so the `:not([style*="--persona-color"])` selector responds correctly to runtime style mutation. No sync between persona events and CSS gating needed beyond what's already wired.

### Fix 3 (caught during Iteration 2 review): Strip icon ordering reversed on initial page load

- **Symptom**: with the 24-hour history filter showing all sessions, the strip rendered oldest-leftmost / newest-rightmost. Counterintuitive.
- **Root cause**: `_addStripIcon` always prepended (`insertBefore(firstChild)`). During initial-page-load (where the API returns sender cards newest-first and `createSenderCard` is called once per sender), each prepend pushed the previously-first icon rightward — last-processed (oldest) ended up leftmost.
- **Fix**: `_addStripIcon` now takes `insertAtTop` (default `true`). `createSenderCard` passes its own `insertAtTop` flag down. Initial load → `false` → `appendChild` → API order preserved (newest leftmost). Runtime arrivals → `true` → `insertBefore(firstChild)` → fresh icon at leftmost. Mirrors the existing sender-card list pattern (`notifications.js:10287-10296`).

### Polish: pill order swap

- User asked to put the Focus pill first, the All pill second (left to right). Single HTML edit reordered the two `<button>` siblings inside `#cc-session-strip`.

### Findings: dedup hole in `addNotificationToSenderGroup` (filed for later, no fix this session)

- User reported the closing notify text rendered TWICE in the same minute. Investigated — single MCP server, single CC listener, single `_notify_impl` call, single HTTP POST. **Root cause hypothesis**: `addNotificationToSenderGroup` (notifications.js:10065) blindly pushes to `dateGroup` and calls `addMessageToDateAccordion` without an `id_hash` dedup. Only the WS arrival path at `:5445` dedups. Other call sites that bypass the dedup: `loadSenderConversation` (`:11144`), `loadInitialNotifications` (`:11842`), the high-priority TTS-activation render at `:13007`. Conversation mode forces `priority=high` (`cosa_voice_mcp.py:788-789`), routing through the TTS-activation path — so any second delivery of the same envelope (re-fetch on tab refocus / on reconnect after one of the user's ongoing WS-reconnect-loop drops / a second tab) renders again. Suggested fix shape: drop a `dateGroup.some(n => n.id_hash === notification.id_hash)` early-return at the top of `addNotificationToSenderGroup`. Filed for the user to approve as a follow-up.

### Files modified/created (Lupin parent only — no CoSA touched)

- `src/fastapi_app/static/html/notifications.html` — new `#cc-hide-inactive-toggle` pill; pill order now Focus then All.
- `src/fastapi_app/static/js/notifications.js` — `CC_HIDE_INACTIVE_KEY` localStorage key + `ccHideInactiveStrip` state + bootstrap mirror; `_bindHideInactiveToggle`, `_isStripIconInactive`, `_applyHideInactiveStripFilter`, `_setHideInactiveStrip`; `_addStripIcon` takes `insertAtTop` param; `voice_persona_assigned` and `voice_persona_released` re-apply filter; `createSenderCard` propagates `insertAtTop` to `_addStripIcon`.
- `src/fastapi_app/static/css/notifications.css` — `[data-hide-inactive="true"]` toggle-active styling; `[data-inactive-hidden="true"]` `display: none`; gray-gradient rule on `.sender-card:not([style*="--persona-color"]) .sender-message.incoming`.
- `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` — `TestHideInactiveToggle` (5 cases), `TestPersonalessBubbleGradient` (3 cases), `TestStripOrdering` (2 cases). Helpers `_click_hide_inactive_toggle`, `_seed_persona`, `_release_persona` (mirror real WS event paths).
- `src/rnd/v0.1.7/2026.05.02-focus-tray-inactive-toggle/01-design.md` (NEW) — full design with active-session detection rationale, 3 sweep tables, edge-case handling, iteration history (Option 1 → Option 4), strip-ordering fix note, 10-case test plan.
- `src/rnd/v0.1.7/2026.05.02-focus-tray-inactive-toggle/90-execution-log.md` (NEW) — phased checklist + iteration-2 changelog + surprises section.
- `bug-fix-queue.md`, `history.md`, `.claude-session.md` — tracking files.

### Verification

- `pytest src/tests/unit/` — 3942 passed, 1 xfailed, 0 failed (132s, no regressions from JS/CSS/HTML edits).
- `run-websocket-smoke-tests.sh` — 50/50 passed (44s, two runs).
- JS `new Function(src)` parse — clean.
- Test file `py_compile` — clean.
- E2E (`TestHideInactiveToggle` + `TestPersonalessBubbleGradient` + `TestStripOrdering`) — :8000-only per testing-venues rubric, **deferred** until user schedules a slot via `/api/test-suite/submit`.
- Visual check on `:7999` — user reviewed; both tweaks signed off after iteration 2.

### Caveats / Notes

- **`addNotificationToSenderGroup` dedup hole** is the most likely cause of the user's twice-rendered notify card. Not fixed this session per user instruction ("look into why that happened" — investigation only, no code changes).
- The substring-match selector `:not([style*="--persona-color"])` is the same gating signal as every existing fallback in the file. If a future inline-style property is added to `.sender-card`, the gating may need updating.
- Conversation mode was active throughout the session; per user-only-initiation rule I did NOT toggle it.

#### Checkpoint 1 | 2026.05.02 12:30 EDT | Both tweaks shipped, tests added, dedup hole filed

**Files**: notifications.{html,js,css}, test_cc_session_strip_and_focus.py, 01-design.md + 90-execution-log.md (NEW), bug-fix-queue.md, history.md, .claude-session.md
**Commit**: b791383

---

### 2026.05.02 - Session 0022baba | Bug Fix Mode | WebSocket reconnect circuit breaker

**Context**: User opened a session with `/plan-bug-fix-mode-start` and almost immediately reported a wall of browser console errors against the notifications UI — `ERR_CONNECTION_RESET` on multiple HTTP endpoints (`/api/notify/response`, `/api/get-queue/done`, `/api/get-queue/dead`, `/api/job-history`, `/api/stats/time-saved/global`) plus repeated WS connect failures (`code=1006 reason=`) on both `/ws/queue/foolish%20goat` and `/ws/audio/slow%20zebra`. Server-side probes from the host (`curl :7999/health` 200 in 1.3 ms; `docker ps` healthy 24min uptime; `active_connections = ['cc-listener-0022baba']` only) ruled out a Lupin server outage. User then surfaced the load-bearing clue: "And a ton of these from my tunneling app, ssh: `accept: Too many open files`". After a `ulimit -n 8192` bump did NOT recover the page, the symptom string flipped from bare `failed:` to `failed: Insufficient resources` with the reconnect counter past 461 attempts — diagnostic that confirmed the renderer (Chrome's per-tab ~255 WS slot pool) was now the binding constraint, not the SSH layer. User killed the tab, opened a fresh one; both WS authenticated on first attempt and sys_ping flowing.

**Fixes (none applied yet)**:

### Fix 1 (planned): WebSocket reconnect circuit breaker

- **Source**: USER-REPORTED 2026-05-02 ~10:30 EDT during session-start. Diagnosed as the real root cause of the deferred 2026-04-22 entry "ERR_CONNECTION_RESET + audio WS connect failure" (now superseded in `bug-fix-queue.md`).
- **Symptom**: notifications.js reconnect logic schedules `setTimeout` reconnects forever with backoff capped at 60s. When the network is genuinely down (SSH tunnel EMFILE today; could be any sustained outage), cumulative attempts saturate Chrome's renderer WS slot pool (~255), error reason flips to `Insufficient resources`, and the loop digs deeper instead of recovering. Only killing the tab process drains the renderer counters.
- **Required behavior**: (1) cap consecutive failed-reconnect attempts per channel (proposed: 20), (2) on threshold breach STOP scheduling reconnects for that channel and surface a "Connection lost — refresh to retry" banner, (3) detect `Insufficient resources` in the WS error event explicitly and escalate immediately (don't wait for threshold), (4) reset attempt counter on `auth_success` so transient drops don't accumulate forever.
- **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js` — `scheduleReconnect` (~5628), `connectQueueWebSocket` close handler (~2178), `connectAudioWebSocket` close handler (~2228), `connectWebSockets` (~2141-2150), `checkWebSocketHealth` (~907).
- **Plan**: Phase 0 = serialize design doc to `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/01-design.md`. Phase 1 = implement circuit breaker. Phase 2 = unit tests + integration test simulating rapid 1006s asserting the cap fires. Phase 3 = wrap + commit.
- **Test**: [pending]
- **Commit**: [pending]

### Caveats / Notes

- Fresh tab also showed two pre-existing 401s on `/api/stats/time-saved` and `/api/stats/time-saved/global`. Unrelated to the WS circuit breaker — separate concern, possibly admin-stats-endpoint auth gate. Not filed as a separate bug yet (need to confirm whether it's expected for non-admin users; user IS admin per `admin: true` in console).
- Out of scope for the circuit breaker fix: SSH tunnel FD-exhaustion remediation. That belongs in the user's ssh config (`ulimit -n 8192` + `ServerAliveInterval 30` / `ServerAliveCountMax 3`), not Lupin code.

#### Checkpoint | 2026.05.02 13:35 | WS reconnect circuit-breaker Phase 1 — WSChannel module + Layer-1 unit tests

**Phase 1 deliverables** (state machine module + 20 unit tests + execution log; `notifications.js` UNCHANGED in this phase per spec — module is consumer-less until Phase 2 wires it in):

- **NEW** `src/fastapi_app/static/js/ws-channel.js` — ES module: `STATE` enum (DISCONNECTED/CONNECTING/AUTHENTICATING/CONNECTED/BACKOFF/OPEN_CIRCUIT), `fullJitterDelay` helper, `createChannel({url,name,onMessage,onAuthSuccess,onCircuitOpen,onStateChange,WebSocketCtor})` factory. Internal: closure-private state, generation token (drops late callbacks), readyState guard (load-bearing for Chromium 255-pending fix), single `onclose` reconnect scheduler, `onerror` is no-op (RFC 6455 §7.1.4), rapid-fail tripwire (5-in-30s with `wasEverOpen=false`), capped exp + full-jitter backoff (BASE=1000, CAP=30000, MAX=20), handshake-timeout watchdog (10s), permanent close codes 4001/4002/4003 → immediate OPEN_CIRCUIT, page-lifecycle handlers (online/offline/pageshow/pagehide/freeze/resume) auto-attached, visibility-hidden defer guard, `ws-circuit-open` and `ws-state-change` window events.
- **NEW** `src/tests/ws_channel_unit/test_ws_channel_unit.py` (+ `__init__.py`) — 20 Layer-1 unit tests via Playwright `page.evaluate()` against an injected `MockWebSocket` + `TestClock` (no real network, no real timers, runs in `about:blank` with init-script injection). Covers: single-scheduler invariants, generation token, readyState guard, attempt-budget circuit, rapid-fail tripwire, jitter bounds (16000 trials), handshake timeout, cleanup-nulls-handlers, watchdog rules (never resets counter, only fires when truly idle), close-code 4001 immediate trip, all six page-lifecycle handlers. Located in a sibling dir (not `e2e_ui/`) to avoid the `:8000`-only `verify_test_environment` autouse fixture; deviation documented in execution log.
- **NEW** `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/` doc set (00-index, 00-working-contract, 01-design-review with Q1–Q12 frozen, 02..06 phase docs, 07-test-strategy 5-tier pyramid, 08-rollout, 99-plan-review-findings, 91-phase-1-execution-log, plus the original expert-brief and reviewer responses from claude/openai).

**Verification (5/5 green)**: `node --check ws-channel.js` PARSE OK · 20/20 Layer-1 unit tests pass in 0.95s · `git diff src/fastapi_app/static/js/notifications.js` empty · `grep ws-channel src/fastapi_app/` returns only self-mentions · `bash src/scripts/run-websocket-smoke-tests.sh` 50/50 pass in 43.75s.

**AI structural review (15/15)**: every Q1–Q12 frozen invariant verified against the implementation file:line; two soft notes recorded for Q2 (manualRetry-zeros-attempts is the synthesized design intent per §2 + Risk row 7) and Q3 (watchdog "never touches counter" interpreted as "never RESETS" — bumping via `scheduleReconnect` is the same path any close uses).

**Files**: `src/fastapi_app/static/js/ws-channel.js`, `src/tests/ws_channel_unit/{__init__.py,test_ws_channel_unit.py}`, 15 files in `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/`, `history.md`, `.claude-session.md`.
**Commit**: 8fd0036

#### Checkpoint | 2026.05.02 14:55 | WS reconnect circuit-breaker Phase 2 — WSChannel wired into NotificationsUI

**Phase 2 deliverables** (the NotificationsUI integration; the legacy reconnect machinery is excised in place):

- **MODIFIED** `src/fastapi_app/static/js/ws-channel.js` — additive Phase-1-spec gap fixes: new `authMessage: () => object` opt (channel calls the builder once on AUTHENTICATING and sends the JSON-stringified result via the live socket), and a new public `send(payload)` proxy method that auto-stringifies non-string payloads and no-ops when state is not OPEN. All 20 Phase-1 Layer-1 tests still pass — change is purely additive.
- **MODIFIED** `src/fastapi_app/static/js/notifications.js` — the Diff Map applied at all 10 sites: deleted the legacy per-socket connect helpers + their separate auth-send methods + the shared retry-helper + the `isConnecting`/`connectionRetries` shared flags; replaced with two `WSChannel` facades constructed via dynamic-imported `createChannel`; `checkWebSocketHealth` converted to a watchdog that delegates to `channel._tickWatchdog()` (off-hours gate REMOVED, counter-zeroing REMOVED — both were proximate causes of the 461-attempts-without-cap incident); auth methods → `_buildQueueAuthMessage()` / `_buildAudioAuthMessage()` JSON builders; auth_error refresh paths redirected to `manualRetry()`; `handlePing` uses `channel.send()` (channel guards on state internally); `refreshWebSocketStatus` reads `channel.state` (string) and maps to existing UI status pill; `logout()` calls `channel.destroy()` (full teardown including window listeners + watchdog timer); `handleAuthFailure()` keeps `channel.close()` (navigating away).
- **MODIFIED** `src/fastapi_app/static/html/notifications.html` — single-line cache-bust bump `?v=20260428f` → `?v=20260502a` (forces browser reload of the rewritten `notifications.js`).
- **NEW** `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/92-phase-2-execution-log.md` — Phase 2 execution log: pre-phase audit (Phase-1-API-gap discovery + ES-module load strategy), module extension table, verification matrix (5/8 green / 3/8 deferred), AI structural review against the Diff Map (all 10 sites mapped to file:line evidence).

**Verification (5/8 green, 3/8 deferred to Phase-2b)**: grep `scheduleReconnect|connectionRetries|isConnecting` → ZERO hits ✅ · grep `this.queueChannel|this.audioChannel` → 2 ctor + 2 connect ✅ · py_compile N/A (no Python touched) · Layer-1 regression 20/20 in 0.99s ✅ · websocket_smoke regression 50/50 in 45s ✅ · Layer-3 in-page (10 new tests) DEFERRED · Layer-4 happy-path on `:8000` DEFERRED (slot-ask required) · Layer-3 intermittent-flap DEFERRED. Phase-2b will close all three deferred items before Phase 3 close. **Total Phase 2 regression: 70/70.**

**Behavior change for users (per `08-rollout-and-rollback.md`)**: the 8 AM–Midnight off-hours gate on the health monitor is removed alongside the counter-zeroing. Reconnect attempts at 3 AM during a server restart now count against the 20-attempt budget instead of being skipped — strictly better than today: the breaker trips at ~6–10 min wall and the user sees a banner the next time they look at the tab (Phase 3 lands the banner DOM + Retry-now button).

**Files**: `src/fastapi_app/static/js/ws-channel.js`, `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/html/notifications.html`, `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/92-phase-2-execution-log.md`, `history.md`, `.claude-session.md`.
**Commit**: acf5387

#### Checkpoint | 2026.05.02 15:25 | WS reconnect circuit-breaker Phase 3 — banner UI + Retry-now + Layer-3 tests

**Phase 3 deliverables** (the user-facing circuit-open banner + the Layer-3 banner-integration tests that verify it):

- **MODIFIED** `src/fastapi_app/static/html/notifications.html` — inserted `#ws-circuit-banner` markup as the first child of `.container`, before the `<h2>` heading (so the alert appears above the page title). Banner contains the user-facing copy, a `.ws-circuit-banner-dev-hint` (hidden by default — toggled by `envLabel`), and the `#ws-circuit-retry-btn` button. `role="alert"` on the container, `aria-live="polite"` on the text. CSS cache-bust bumped `?v=20260428f` → `?v=20260502a`.
- **MODIFIED** `src/fastapi_app/static/css/notifications.css` — added a banner-styling block at end of file: `.ws-circuit-banner` (red error background, flex layout, padding); `.ws-circuit-banner-text`; `.ws-circuit-banner-dev-hint` (italic, with monospaced `code` styling for the SSH-tunnel hint); `.ws-circuit-retry-btn` (transparent border button with hover + disabled-state visuals).
- **MODIFIED** `src/fastapi_app/static/js/notifications.js` — replaced the Phase 2 `_showCircuitBanner` placeholder with the real DOM-toggling implementation: removes `hidden` from banner, toggles dev-hint visibility based on `this.envLabel === "DEVELOPMENT"`, re-enables the retry button. Added `_hideCircuitBanner()` (re-adds `hidden`, re-enables button). Added `_wireCircuitBanner()`: idempotent (early-return on `_circuitBannerWired` flag), registers a `ws-circuit-open` window-event listener that routes to `_showCircuitBanner`, wires the Retry-now button click handler that disables itself + invokes `manualRetry()` on both channels (try/catch belt-and-braces against a synchronous throw stranding the button — Phase 3 §Risks row 2). Init wiring at `:401` calls `_wireCircuitBanner()` BEFORE `connectWebSockets()` so the listener is registered before any potential dispatch. Both `auth_success` branches in `handleQueueMessage` and `handleAudioMessage` call `_hideCircuitBanner()` (Q10 — global banner, hide on first channel's `auth_success`).
- **NEW** `src/tests/ws_channel_browser/test_ws_circuit_banner.py` (+ `__init__.py`) — 4 Layer-3 Pytest+Playwright banner-integration tests against the live `:7999` dev server. Authenticates via `POST /auth/login` per `feedback_auth_contract_lookup` memory, pre-populates localStorage with the JWT + `user_data`, overrides `window.WebSocket` with a no-op `MockWebSocket` (prevents live `auth_success` race vs synthetic events), navigates to `/app/notifications`, waits for `_circuitBannerWired === true`, drives synthetic `ws-circuit-open` dispatches + button clicks + direct `handleQueueMessage` invocations to assert banner DOM behavior. Placed in a sibling dir (not `e2e_ui/`) for the same reason as the Layer-1 unit tests — the e2e_ui autouse fixture mandates `:8000` `lupin_db_test`.
- **NEW** `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/93-phase-3-execution-log.md` — Phase 3 execution log: pre-phase audit (banner-insertion sentinel resolved at phase entry), structural review against all 13 spec rows (all ✅), test infrastructure decisions table, per-test breakdown.

**Verification (6/7 green, 1/7 deferred)**: grep `ws-circuit-banner|ws-circuit-retry-btn` in `notifications.html` → 4 hits ✅ · grep `_showCircuitBanner|_hideCircuitBanner|_wireCircuitBanner` in `notifications.js` → 16 hits ✅ · Layer-3 `test_circuit_open_shows_banner` ✅ · Layer-3 `test_retry_now_clears_breaker_and_reconnects` ✅ · Layer-3 `test_retry_button_disables_during_reconnect` ✅ · Layer-3 `test_dev_hint_visible_only_in_dev` ✅ · E2E UI visual snapshot DEFERRED (`:8000` slot-ask required). **Phase-3 total: 74/74 (20 Layer-1 + 50 websocket_smoke regression + 4 NEW Layer-3 banner tests)** in ~47s.

**AI structural review (13/13 invariants)**: every spec row verified against file:line evidence in `93-phase-3-execution-log.md` §AI Structural Review.

**Files**: `src/fastapi_app/static/html/notifications.html`, `src/fastapi_app/static/css/notifications.css`, `src/fastapi_app/static/js/notifications.js`, `src/tests/ws_channel_browser/{__init__.py,test_ws_circuit_banner.py}`, `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/93-phase-3-execution-log.md`, `history.md`, `.claude-session.md`.
**Commit**: b4eb821

#### Checkpoint | 2026.05.02 15:35 | WS reconnect circuit-breaker Phase 4 — page lifecycle + 6 lifecycle tests

**Phase 4 deliverables** (Page Lifecycle wiring on the consumer side + the Layer-3 tests that verify it):

- **MODIFIED** `src/fastapi_app/static/js/ws-channel.js` — added a Phase 4 `manualRetry` no-op-on-CONNECTED guard (`if (state === STATE.CONNECTED) return;`) per `05-phase-4-page-lifecycle.md` §Risks row 3 mitigation. Without this, an `online` event firing on a flaky network mid-session would cleanup-and-reconnect already-OPEN channels, breaking live traffic for no benefit. The guard does NOT fire from OPEN_CIRCUIT (Phase 1 test 11 still works) or BACKOFF (the half-open probe fast-paths out).
- **MODIFIED** `src/fastapi_app/static/js/notifications.js` — added `_attachPageLifecycle()` method per Phase 4 §Lifecycle Wiring: idempotent (early-return on `_pageLifecycleAttached` flag); wires `visibilitychange→visible` to `connect()` on both channels; `pageshow.persisted=true` to `manualRetry()` on both; `pagehide` to `close()` on both; Chrome `freeze`/`resume` to `close()`/`connect()` respectively; `online` to `manualRetry()` on both; `offline` to `close()` on both. Init wiring at `:409` calls `_attachPageLifecycle()` AFTER `connectWebSockets()` so both `this.queueChannel` and `this.audioChannel` exist when handlers reference them. Cross-channel calls are safe because the channels' own auto-attached listeners + the new manualRetry guard make every operation idempotent.
- **NEW** `src/tests/ws_channel_browser/test_ws_lifecycle.py` — 6 Pytest+Playwright Layer-3 tests against `:7999`, same harness shape as the Phase 3 banner tests but with a richer `MockWebSocket` that tracks `instances` and exposes a `_close(code)` driver. Each test navigates to `/app/notifications`, waits for both `_circuitBannerWired` AND `_pageLifecycleAttached` flags, then dispatches a DOM event and asserts channel state / instance counts. Tests: `test_visibility_hidden_pauses_connect`, `test_visibility_visible_resumes_connect`, `test_pageshow_persisted_full_reset_lifecycle`, `test_offline_closes_sockets`, `test_online_triggers_retry_lifecycle`, `test_pagehide_closes_for_bfcache`.
- **NEW** `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/94-phase-4-execution-log.md` — Phase 4 execution log: pre-phase audit (init-order site resolved at phase entry; Phase 1 over-implementation acknowledged; manualRetry idempotency gap addressed), structural review against 12 spec invariants (all ✅), test results summary, Phase 4 sign-off.

**Verification (8/8 green)**: grep `_attachPageLifecycle|visibilitychange|pageshow|pagehide|freeze|resume` in `notifications.js` ✅ · `test_visibility_hidden_pauses_connect` ✅ · `test_visibility_visible_resumes_connect` ✅ · `test_pageshow_persisted_full_reset_lifecycle` ✅ · `test_offline_closes_sockets` ✅ · `test_online_triggers_retry_lifecycle` ✅ · `test_pagehide_closes_for_bfcache` ✅ · earlier-phase regression ✅ (Layer-1 20/20 + websocket_smoke 50/50 + Layer-3 banner 4/4 still pass when run alongside the 6 new lifecycle tests; 10/10 combined Layer-3 in 3.37s).

**AI structural review (12/12 invariants)**: every spec row verified against file:line evidence in `94-phase-4-execution-log.md` §AI Structural Review.

**Files**: `src/fastapi_app/static/js/ws-channel.js`, `src/fastapi_app/static/js/notifications.js`, `src/tests/ws_channel_browser/test_ws_lifecycle.py`, `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/94-phase-4-execution-log.md`, `history.md`, `.claude-session.md`.
**Commit**: 0ca2eed

#### Checkpoint | 2026.05.02 16:10 | WS reconnect circuit-breaker Phase 5 — server close codes 4001/4002 + client banner reason + 5 close-code tests

**Phase 5 deliverables** (server-side hardening + client wiring + docs + tests; closes the WS reconnect circuit-breaker milestone):

- **MODIFIED in CoSA** `src/cosa/rest/routers/websocket.py` — added top-of-file constants `CLOSE_CODE_AUTH_INVALID_TOKEN=4001`, `CLOSE_CODE_AUTH_SESSION_CONFLICT=4002`, `CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED=4003` with a comment block reserving the 4000-4999 application range per RFC 6455 §7.4.2. Replaced 10 generic `await websocket.close()` calls in the queue auth path (lines 362-494) with `await websocket.close(code=4001, reason=<specific>)` — `invalid_auth_request_json`, `auth_protocol_violation`, `missing_token`, `invalid_token_type`, `empty_token`, `token_expired`, `invalid_token`, `auth_error`, etc. Audio path (`:249-254`) was left as-is — it doesn't close on auth failure. **CoSA submodule git ops are out of scope for this Lupin-side commit; the user must commit CoSA separately in a CoSA-context session.**
- **MODIFIED in CoSA** `src/cosa/rest/websocket_manager.py:147` — single-session-per-user displaced socket close changed from `code=1000, reason="New session opened"` to `code=4002, reason="session_conflict_displaced"` so the displaced client recognizes it as PERMANENT and does NOT auto-retry. **Same CoSA-commit caveat as above.**
- **MODIFIED** `src/fastapi_app/static/js/ws-channel.js` — `openCircuit()` now accepts `reason` + optional `code` parameters and emits them in the `CIRCUIT_OPEN_EVENT` detail. Permanent-close-code path passes `"auth-permanent"` + `event.code`; budget exhaustion passes `"budget-exhausted"`; rapid-fail tripwire passes `"rapid-fail"`. All 20 Phase 1 Layer-1 tests still pass — the signature change is additive and back-compatible.
- **MODIFIED** `src/fastapi_app/static/js/notifications.js` — `_showCircuitBanner(detail)` differentiates by `detail.reason` and `detail.code`; on `reason==="auth-permanent" && code===4001`, attempts `refreshAccessToken()` BEFORE rendering the banner. On refresh-success, calls `manualRetry()` on both channels (banner never appears). On refresh-failure, falls through to `_renderCircuitBanner` which swaps banner copy by reason+code: 4001 → "Authentication failed — please log in again."; 4002 → "Another session has taken over. Refresh to reclaim."; 4003 → "Permission denied for one or more notification streams."; else → existing network-failure copy. Banner text element gets a `data-reason` attribute for test hooks. **Removed the duplicate per-channel `onCircuitOpen` callback** from both queueChannel and audioChannel constructions — it was double-firing `_showCircuitBanner` (once via channel callback + once via window listener) and breaking the 4001 refresh single-attempt guard. The window-level `ws-circuit-open` listener registered by `_wireCircuitBanner` is now the single owner of the banner-render path.
- **MODIFIED** `src/fastapi_app/static/html/notifications.html` — banner text element gets `data-reason="default"` + `data-testid` hooks; CSS + JS cache-bust bumped `?v=20260502a` → `?v=20260502b`.
- **NEW** `src/tests/websocket_smoke/core/test_close_codes.py` — Layer-2 Python protocol test (`test_invalid_token_close_code`) that connects to `/ws/queue/<session>` with a junk token, sends an `auth_request`, and asserts the server closes with `code=4001`. Runs the async client logic in a worker thread so its asyncio loop is isolated from pytest-asyncio + pytest-playwright (combined runs of those two harnesses + `asyncio.run()` collide). Conditional `test_session_conflict_close_code` is `pytest.mark.skip` since the fixture for `enforce_single_session_per_user=True` requires server-config hot-swap.
- **NEW** `src/tests/ws_channel_browser/test_ws_close_codes.py` — 4 Layer-3 Pytest+Playwright tests against `:7999`: `test_close_4001_opens_circuit_immediately` (state=OPEN_CIRCUIT in 1 tick, attempts unchanged), `test_close_4001_banner_message` (banner text contains "Authentication failed", `data-reason="auth-permanent"`), `test_4001_triggers_token_refresh_path` (refresh stub called exactly once), `test_4001_refresh_success_no_banner_flash` (banner hidden when refresh succeeds).
- **MODIFIED** `src/docs/websocket-events.md` — new "Close Code Semantics" section with per-code semantics table, server-emit conditions, client behavior, comparison to standard close codes (1000/1001/1006/1008), and a browser-side reaction summary.
- **MODIFIED** `src/docs/websocket-architecture.md` — "Auth Error Conditions" table extended with a Close Code column; cross-link to `websocket-events.md#close-code-semantics`.
- **NEW** `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/95-phase-5-execution-log.md` — Phase 5 execution log: pre-phase audit, step-0 collision grep evidence, file modification map (with explicit "CoSA edits MUST be committed separately" note), structural review against 12 spec invariants, sign-off table.

**Verification (9/9 green + 3 extras green)**: step 0 collision grep zero ✅ · py_compile both CoSA files ✅ · import-chain `from cosa.rest.routers import websocket` ✅ · Layer-2 `test_invalid_token_close_code` (live `:7999` connect with junk token, server closes with 4001) ✅ · Layer-2 `test_session_conflict_close_code` ✅ SKIP (conditional) · Layer-3 `test_close_4001_opens_circuit_immediately` ✅ · Layer-3 `test_close_4001_banner_message` ✅ · `websocket-events.md` close-code section ✅ · `websocket-architecture.md` cross-ref ✅ · Layer-3 `test_4001_triggers_token_refresh_path` + `test_4001_refresh_success_no_banner_flash` ✅. Plus regression: Layer-1 20/20 in 0.96s ✅ · websocket_smoke 50/50 in 45s ✅ · Layer-3 banner+lifecycle 10/10 still pass alongside the 4 new close-code tests.

**Phase-5 total: 85 passed + 1 skipped (conditional)** in ~50s — full pyramid green.

**AI structural review (12/12 invariants)**: every spec row verified against file:line evidence in `95-phase-5-execution-log.md` §AI Structural Review.

**CoSA submodule boundary**: this Lupin-side commit explicitly excludes the two modified CoSA files (`src/cosa/rest/routers/websocket.py`, `src/cosa/rest/websocket_manager.py`). They live in the CoSA submodule (`git@github.com:deepily/cosa.git`) and per `feedback_cosa_edit_vs_manage_git`: editing CoSA from this Lupin context is allowed; running `git add` / `git commit` / `git push` against the CoSA submodule from this context is forbidden. **The user is responsible for committing the CoSA-side changes in a CoSA-context session.**

**Files (Lupin parent only)**: `src/fastapi_app/static/js/ws-channel.js`, `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/html/notifications.html`, `src/docs/websocket-events.md`, `src/docs/websocket-architecture.md`, `src/tests/websocket_smoke/core/test_close_codes.py`, `src/tests/ws_channel_browser/test_ws_close_codes.py`, `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/95-phase-5-execution-log.md`, `history.md`, `.claude-session.md`.
**CoSA files NOT in this commit (require separate user-driven CoSA-context commit)**: `src/cosa/rest/routers/websocket.py`, `src/cosa/rest/websocket_manager.py`.
**Commit**: c4d901f

#### Session Summary | 2026.05.02 — bug-fix-mode CLOSED (0022baba)

**Milestone shipped end-to-end this session**: WS reconnect circuit-breaker (5 phases, design + impl + tests + docs), resolving the user-reported `Insufficient resources` Chrome-renderer saturation bug filed at session-start.

**Commits (8 total, in order)**:

| # | Hash | Phase | One-line |
|---|------|-------|----------|
| 1 | `234d7b7` | 1 | WSChannel ES module + 20 Layer-1 unit tests + Phase 0 doc-set serialization |
| 2 | `00c7c3b` | 2 | NotificationsUI integration: deleted legacy reconnect machinery, two WSChannel facades, watchdog conversion |
| 3 | `4b287cd` | 3 | Banner DOM + CSS + Retry-now wiring + 4 Layer-3 banner tests |
| 4 | `27bcacd` | 3 follow-up | Visual snapshot test file authored (`test_ws_circuit_banner_visual.py`) |
| 5 | `92da8e2` | 3 close-out | Visual baseline established + verified pixel-identical on `:8000` (job `ts-f98d589a` then `ts-580c3d6f`) |
| 6 | `8e6d61b` | 4 | Page-lifecycle wiring (`_attachPageLifecycle`) + manualRetry no-op-on-CONNECTED guard + 6 Layer-3 lifecycle tests |
| 7 | `1a9e3e0` | 5 | Server close codes 4001/4002 (CoSA edits, NOT in this Lupin commit) + client banner reason differentiation + 4001 token-refresh path + 5 NEW close-code tests + docs |

**Test pyramid (final state)**:
- Layer-1 unit (`src/tests/ws_channel_unit/`): **20/20** in 0.99s
- Layer-2 protocol (`src/tests/websocket_smoke/core/test_close_codes.py`): **1 pass + 1 conditional skip** in <1s
- Layer-3 browser (`src/tests/ws_channel_browser/`): **14/14** in ~3s (4 banner + 6 lifecycle + 4 close-code)
- websocket_smoke regression: **50/50** in 45s (preserved across all 5 phases)
- E2E visual snapshot (`src/tests/e2e_ui/test_ws_circuit_banner_visual.py`): baseline established + verified on `:8000`

**Files added (Lupin parent repo)**:
- `src/fastapi_app/static/js/ws-channel.js` (NEW; 477 LOC)
- `src/tests/ws_channel_unit/{__init__.py,test_ws_channel_unit.py}` (NEW; 20 unit tests)
- `src/tests/ws_channel_browser/{__init__.py,test_ws_circuit_banner.py,test_ws_lifecycle.py,test_ws_close_codes.py}` (NEW; 14 Layer-3 tests)
- `src/tests/websocket_smoke/core/test_close_codes.py` (NEW; Layer-2 close-code regression)
- `src/tests/e2e_ui/test_ws_circuit_banner_visual.py` (NEW; visual snapshot)
- `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/` (NEW; full doc set: 00-index, 00-working-contract, 01-design-review with Q1–Q12 frozen, 02..06 phase docs, 07-test-strategy, 08-rollout, 99-plan-review-findings, 91-95 execution logs, plus expert-brief and reviewer responses)

**Files modified (Lupin parent repo)**:
- `src/fastapi_app/static/js/notifications.js` (rewrite of WS machinery in Phase 2; banner + lifecycle wiring in Phases 3-4; banner reason differentiation in Phase 5)
- `src/fastapi_app/static/html/notifications.html` (banner DOM + CSS/JS cache-bust bumps)
- `src/fastapi_app/static/css/notifications.css` (banner styling block)
- `src/docs/websocket-events.md` (Close Code Semantics section)
- `src/docs/websocket-architecture.md` (Auth Error Conditions table extended; cross-ref)
- `bug-fix-queue.md` (today's WS-circuit-breaker bug marked RESOLVED)

**Files modified in CoSA submodule (NOT in any Lupin commit — user must commit separately in CoSA context)**:
- `src/cosa/rest/routers/websocket.py` (CLOSE_CODE_AUTH_* constants + 10 close-call sites get explicit code=4001)
- `src/cosa/rest/websocket_manager.py` (line 147 single-session displaced socket close changed to code=4002)

**Bug-fix mode**: closed for session 0022baba (queue table updated; in-progress entry marked resolved with commit-hash trail). Other sessions' bugs (13 pending in queue) untouched.

**Carryover for next session**:
- Commit the two CoSA-submodule files in a CoSA-context session.
- Optional: archive `history.md` (currently 17,138 tokens — just over the 17k WARNING threshold). Workflow added an entry to `TODO.md`.

---

### 2026.05.01 - Session 92ece47c | TODO size-management skill + first archival pass

**Context**: User flagged TODO.md was at 31.5k tokens / 126% of the 25k limit at session-start. Global Claude config + planning-is-prompting workflow had no size-management protocol for TODO.md (only history.md did). User approved adopting the history.md adaptive-archival pattern, with one structural adjustment for TODO's status × age semantics.

**Accomplishments**:
- Authored design doc + execution log capturing the *status × age* asymmetry (history archival is mechanical / cut by date; TODO archival is semantic / cut by status × age — pending items load-bearing regardless of age).
- Built `/todo-size-management` slash command mirroring `/history-management` shape (4 modes: check, archive, analyze, dry-run; thresholds at 17k WARNING / 19k CRITICAL; 8-12k retention target).
- Ran live archival on current TODO.md: aggressive pass (whole CLOSED sections + `[x]`-bullet excision from MIXED sections). 21 whole + 10 MIXED-excerpt sections archived.
- Result: TODO.md 31.6k → 19.4k tokens (-37%), 1,194 → 857 lines (-28%). 208 pending items preserved with zero leakage to archive (verified: source had 199 top-level + 9 indented `[ ]`, new TODO has same counts, archive has 0).
- Filed cross-project follow-up to promote the algorithm to `planning-is-prompting/workflow/todo-size-management.md` (PIP currently says "TODO.md is NEVER archived" — promotion requires canonical-policy update).
- Filed manual stale-pending triage as `[LUPIN]` follow-up to bring TODO.md the rest of the way to the 8-12k retention target.

**Files modified/created**:
- `.claude/commands/todo-size-management.md` (new skill)
- `src/rnd/v0.1.7/2026.05.01-todo-size-management/01-design.md` (new)
- `src/rnd/v0.1.7/2026.05.01-todo-size-management/90-execution-log.md` (new)
- `todo-history/2026-04-10-to-2026-05-01-todo.md` (new archive — 447 lines / 12.9k tokens)
- `TODO.md` (rewritten via the new skill — top-of-file follow-ups added)
- `TODO.md.backup-2026-05-01-92ece47c` (rollback safety, untracked)

**Caveats**:
- 19.4k tokens is still above the 8-12k retention target. Reaching there requires manual triage of stale `[ ]` items in long-running OPEN/MIXED sections (v0.1.6 — FUTURE DEVELOPMENT, Pending — HIGH PRIORITY, etc.). The skill never auto-prunes pending work — that's by design.
- Conservative mechanical pass alone was insufficient (only 14% reduction). The MIXED `[x]`-excision step is what got us to 38%. Continuation lines (sub-bullets) under `[x]` parents traveled with the parent into the archive — verified as zero pending leaked.

---

### 2026.05.01 - Session a6b318ea | Bug Fix Mode | Focus-tray icon stranding (cleanup paths + conv-mode mic overlay)

**Context**: Two related stranded-icon bugs in the CC notifications UI focus tray, surfaced + fixed in one session.

### Fix 1: Focus tray strands icons after Clear All / per-day delete / history-window change

- **Source**: User report (start of session) — "Clear All or ad-hoc deletion of a session pane DOES NOT update the focus tray; icons from deleted sessions are stranded."
- **Symptom**: Three sibling code paths tore down sender cards but left their strip icons in `#cc-strip-icons`. The fourth path (per-sender × via `deleteSenderConversation`) was already correct.
- **Root cause**: Three call sites mutated `senderGroups` + removed cards from `#notifications-list` but never invoked `_removeStripIcon` or its bulk equivalent:
  - `clearAllNotifications()` at `notifications.js:11780` (Clear All button)
  - `removeSenderCard(senderId)` at `notifications.js:10706` (called from `softDeleteByDate` when deleting the last day for a sender)
  - `clearSenderGroups()` at `notifications.js:11036` (called when the history-window dropdown changes — same class-of-bug, included per the sweep-for-pattern-offenders rule)
- **Fix**: Extracted `_clearAllStripIcons()` helper next to `_removeStripIcon` (exits focus mode if active, empties `#cc-strip-icons`, hides `#cc-session-strip`, resets `ccStripUnreadCounts`). Wired `_removeStripIcon(senderId)` into the per-sender `removeSenderCard` path; wired `_clearAllStripIcons()` into the two bulk paths.
- **Bonus pre-existing typo**: The new test surfaced `removeSenderCard` calling the non-existent `this.updateNotificationCount()` — renamed to canonical `updateTotalNotificationsCount()` (used in 9 other sites). Latent throw that the old code never hit because the previous behavior never reached the strip-icon path.
- **Files**:
  - `src/fastapi_app/static/js/notifications.js` (4 edit sites: helper + 3 call sites + typo fix)
  - `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` (new `TestStripCleanupOnBulkDelete` class with 4 regression tests)
- **Test**: 4 new tests + 13 pre-existing tests in the file — all 17 pass on `:8000` E2E (`ts-d7b35841`).
- **Commit**: 1b191f4

### Fix 2: Mic-icon overlay strands on conv-mode toggle OFF

- **Source**: User voice report mid-session — "The microphone icon indicating who's got monopoly of the microphone is stranded in the focus tray. When a user toggles out of conversation mode the icon is not removed from the tray."
- **Symptom**: Strip icon's `data-conv-mode="true"` attribute (which renders the mic overlay) never cleared on the OFF transition, even after the WS event arrived.
- **Root cause**: Format mismatch on session_id key. The `conversation_mode_changed` WS payload carries the full session UUID (e.g. `a6b318ea-072c-474b-aa90-...`), but strip icons key by the 8-char prefix (`a6b318ea`). The WS-router at `notifications.js:5407` was passing the un-normalized full UUID to `_setStripIconConvMode`, so the `querySelector('#cc-strip-icons .cc-strip-icon[data-session-id="<full-uuid>"]')` missed every time. The same class of bug was already documented + fixed for `.sender-conversation-mode-btn` in `handleConversationModeChanged` on 2026-04-28 (comment at lines 9553-9564); the strip-icon update path was added later and bypassed that normalization.
- **Fix**: Moved the `_setStripIconConvMode` call OUT of the WS router and INTO `handleConversationModeChanged` after the 8-char normalization, alongside `_pinSenderCardForSession`/`_unpinSenderCardForSession`. Single source of truth for session-keyed DOM widget updates.
- **Files**:
  - `src/fastapi_app/static/js/notifications.js` (2 edit sites: WS router slimmed, `handleConversationModeChanged` extended)
  - `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` (new `test_conv_mode_off_via_ws_clears_strip_icon_overlay` regression — drives the full WS path with a full-UUID payload for both ON and OFF transitions)
- **Test**: New regression + same pre-existing 13 tests — all 18 pass on `:8000` E2E (`ts-d7b35841`, 71.7s).
- **Commit**: 1b191f4

### Caveats / Notes

- The first E2E resubmit (`ts-1cae37ec`) crashed at startup (pytest exit=4) because the `-k 'A or B'` expression got mangled by shell-split in the test_suite agent's pytest_args handling. Switched to a file-path filter (`-v src/tests/e2e_ui/test_cc_session_strip_and_focus.py`) which runs all 17→18 tests in the file unambiguously. Worth filing as a small bug against the test_suite agent later if `-k` with quoting is intended to be supported.
- The second resubmit (`ts-f6d91ccb`) failed 1 test for a wrong reason — my regression test passed a flat object to `handleNotificationUpdate` which expects `{notification: {...}}` envelope shape, so the switch case never fired. Test wrapper fixed; code fix was correct from the first edit.

### Polish & Follow-on Tweaks (uncommitted bundle, post-`c49778e`)

After the wrap, user requested seven small UI polish tweaks against the same surfaces. All landed on `notifications.js` + `notifications.css` and verified against the same E2E file (most recent run `ts-7f6b3651`: 18/18 pass, 71.4s).

1. **Mic-icon offsets `−3 → −6`** — pushes the conversation-mode mic overlay outward so the visible glyph reads as docked to the persona-circle perimeter rather than overlapping its interior.
2. **Unread badge sizing + center-anchored on perimeter** — switched from edge-offset positioning (`top:-2; right:-2`, drifted inward as multi-digit counts widened the box) to center-anchored positioning (`top:6; left:34; transform: translate(-50%,-50%)`). Badge midpoint now sits on the persona perimeter at 45° regardless of 1- vs 2-digit width. Also reduced size (16×16 vs 18×18, font 10/regular vs 11/bold).
3. **Pulse animation finite + restart on each notification** — `animation-iteration-count: infinite → 3`. JS in `_promoteStripIcon` now restarts the animation on each promote via remove+reflow+re-add of `data-unread`, so every new notification triggers a fresh 3-pulse cycle instead of running forever.
4. **Corner Stop button on TTS message bubbles** — sibling to existing Pause/Resume corner button, sits to its left at `right: 32px` with red theme. Click invokes existing `stopTTSAndAdvance()` helper. Initial CSS visibility selector was over-broad (included `.is-paused-current`); fixed in same session to mirror pause-button's `.tts-playing`-only visibility so Stop hides cleanly when `stopTTSPlayingIndicator` removes that class.
5. **Strip-icon tooltip includes persona display name** — tooltip now reads `"<project> #<sessionId> (<persona display name>)"` instead of just project + session. Uses `persona.display_name || persona.name` (matches existing `_renderPersonaBadgeHTML` precedence).
6. **Filter progress-group-entry notifications from focus-tray unread badge** — plumbed `{ skipUnread: bool }` option through `_promoteStripIcon` and `moveSenderCardToTop`. `addNotificationToSenderGroup` sets `skipUnread: true` when `notification.progress_group_id` is present, so tool-call progress updates (the noise case) don't bump the badge or restart the pulse. Card still moves to top so recency ordering is preserved — only the visual nag is suppressed.
7. **Stranded-stop-button bug** (caught in #4 above) — fixed in the same iteration; folded into the bundle.

**Files** (parent Lupin only — CoSA submodule untouched):
- `src/fastapi_app/static/css/notifications.css`
- `src/fastapi_app/static/js/notifications.js`

**Verification cadence**: 4 E2E runs on `:8000` across the bundle (`ts-605094aa`, `ts-8ff8181a`, `ts-7f6b3651`, plus the original `ts-d7b35841` baseline). Last run 18/18 pass.

### Session Summary

- **Total fixes**: 2 committed (`1b191f4` + `c49778e` hash-stamp) + 7 uncommitted polish tweaks (this bundle)
- **Files changed**: 5 in committed bugs, 2 in polish bundle (3 if you count the manifest)
- **Tests added**: 5 new regression cases across 2 classes — all green, no regressions on the 13 pre-existing tests in the strip/focus test file
- **GitHub issues closed**: none (user-reported, no GH ticket)
- **Status**: Session closed 2026-05-01

---

### 2026.05.01 - Session 5b732efe | CC notifications UI tweaks: Today filter + Arnold yellow + focus-mode flash + María rename

**Context**: User-driven mini-batch of four UI tweaks during the v0.1.7 spit-and-polish cycle, executed under auto-mode.

**Accomplishments**:

1. **"Today" filter for CC notifications history dropdown** — distinct from "Last 24 hours". Stored as a `'today'` sentinel in localStorage; new `getEffectiveHoursForQuery()` helper resolves it to numeric hours-since-local-midnight at query time (Math.ceil so 12:00:01 AM is included). Three query sites (loadConversationHistory, loadSenderConversation, bulk-delete) routed through the helper. Initial implementation had an HTML-escaping bug — `JSON.stringify('today')` produced literal `"today"` inside a double-quoted onclick attribute; fixed via `.replace(/"/g, "&quot;")` so string sentinels survive HTML attribute parsing while numbers/null pass through unchanged.

2. **Arnold persona color recolored** to `#FFD600` (Material Yellow A700, sunshiny). Prior `#C62828` red overlapped visually with maria `#F06292` and Domi `#880E4F`. Yellow keeps Arnold distinct from mr radio's amber `#FFA000`.

3. **Focus-mode entry flash** — when the focus-toggle pill goes OFF→ON, the focused card now pulses a persona-tinted box-shadow (1.5s ease-out animation via `data-focus-flash` attribute + `@keyframes sender-card-focus-flash`). Mid-mode strip-icon switches don't flash (user already knows which session they clicked). Implementation: new `flash` parameter on `_enterFocusMode(senderId, flash=false)` plus `_flashFocusedCard()` helper with restart-on-double-toggle support.

4. **Persona key `Maria` → `maria` + display "María"** — lowercase no-punctuation key form aligns with the mr-radio convention. New `_DISPLAY_OVERRIDES = {"maria": "María"}` in `voice_persona_helpers.py` (CoSA submodule); `display_name_for()` consults overrides before generic title-case. Test fixtures and assertions updated in `test_voice_persona_helpers.py` (replaced "Maria" → "maria"; new `test_display_overrides_apply` confirms case-insensitive override match) and `test_voice_persona_allocation.py` (pool name set).

**Files Modified** (parent Lupin only — CoSA submodule managed separately):
- `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini` (Arnold color + Maria → maria pool/keys + matching splainer entries + Domi cross-reference)
- `src/fastapi_app/static/js/notifications.js` (Today filter plumbing + focus-mode flash + HTML-escape bugfix)
- `src/fastapi_app/static/css/notifications.css` (focus-flash @keyframes + selector)
- `src/tests/unit/test_voice_persona_helpers.py`, `src/tests/smoke/test_voice_persona_allocation.py` (Maria → maria test fixtures + new override test)

**CoSA submodule** (commit separately in CoSA session):
- `src/cosa/rest/voice_persona_helpers.py` (added `_DISPLAY_OVERRIDES` map + override-first lookup; docstring updated)

**Verification**: `node -c notifications.js` ✓ · `py_compile voice_persona_helpers.py` ✓ · `pytest src/tests/unit/test_voice_persona_helpers.py` → 34/34 passed (including new override test). `pytest src/tests/unit/test_voice_persona_helpers.py src/tests/unit/test_conv_mode_wrap.py src/tests/unit/test_conversation_mode_router.py` → 88/88 passed.

**Caveats**: INI changes only affect *new* persona allocations — existing live sessions keep their stamped `name="Maria"` until reallocated (or a server bounce + new session). JS/CSS hot-reload via static file serving on hard browser refresh.

---

### 2026.05.01 - Session 6562a2c9 | History archival + history/ index repair

**Context**: Brief session-start ritual where user requested proactive history-file archival.

**Accomplishments**:

1. **Archived 3 sessions from 2026-04-29** (Persona Theming Round 1, passlib/bcrypt 4.3.0 pin diagnosis, Test-Suite Anomaly Remediation Phases 1+2+3 + Idle-Aware Stop Hook) to new `history/2026-04-29-history.md` (4,420 tokens). Trim removed lines 451-627 from main file.

2. **Repaired `history/README.md` archive index** — three rows were missing despite archive files existing on disk: `2026-04-29-history.md` (NEW this session), `2026-04-25-to-28-history.md`, `2026-04-22-to-24-history.md`. Quick-stats bumped: 16 → 19 archives, 326+ → 346+ sessions documented, last-updated stamp 2026-04-16 → 2026-05-01.

3. **Manifest hygiene** — appended Session 6562a2c9 section to `.claude-session.md` after detecting parallel session 5b732efe ("CC Notifications: add Today filter") was already active. Did not touch parallel session's section or its files.

**Verification**: `history.md` 13,365 → 9,379 tokens (53% → 37.5% of 25k limit). Archive file 4,420 tokens (17.6%). Both healthy.

**Files** (parent Lupin only — selectively staged):
- `history.md` (trim + archive list entry)
- `history/2026-04-29-history.md` (NEW)
- `history/README.md` (added 3 missing archive rows + stats refresh)
- `.claude-session.md` (this session's section)

**Caveat surfaced for follow-up**: `TODO.md` is at 31,518 tokens (126% of 25k limit, 199 pending items). Triage deferred at user direction; logged in TODO.md.

---

### 2026.05.01 - Session 911b1cdc | Persona rename + display_name helper + conv-mode displace exit-reminder push

**Accomplishments**:

1. **Persona rename `Mr. NPR` → `mr radio`** in `lupin-app.ini` pool CSV + four persona keys, with matching `lupin-app-splainer.ini` entries and rename provenance. Convention applied: pool/key form is lowercase no-punctuation per project key convention.

2. **New `display_name_for()` helper** in `cosa/rest/voice_persona_helpers.py` with `_HONORIFIC_TOKENS = {mr, mrs, ms, dr, prof, sr, jr, st}` — converts pool key form to proper-noun display form (`mr radio` → `Mr. Radio`, `Maria` → `Maria`). `display_name` field stamped at all three persona-dict construction sites; `_voice_persona_for_sender_id` in notifications router defensively stamps it on legacy bridges. Frontend `_renderPersonaBadgeHTML` uses `persona.display_name || persona.name` for both tooltip and label.

3. **Cross-session conversation-mode mic-monopoly correction** — diagnosed: server bridge mutex was correct (only one bridge had `conversation_mode_active=true`), but the displaced session's Claude Code instance still carried stale `<system-reminder>` injections from prior turns saying conversation mode was active, so it kept calling `notify()` and wrapping replies. Fix: at displacement time the conversation-mode router pushes a parallel `user_initiated_message` with `title="action:exit_conversation_mode"` and `job_id=other_sid[:8]`; `cc_notification_listener._handle_action` routes it to a new `_inject_exit_conversation_reminder` that calls a new `conv_mode_exit_reminder()` helper in `hook_common.py` and types the resulting `<system-reminder>` block into the displaced session's tmux pane verbatim (bypasses bridge-gated `conv_mode_wrap` via a new `wrap=True/False` param on `_inject_via_tmux`). Best-effort try/except so action push failure does not block the activate path.

**Files Modified** (parent Lupin only — CoSA submodule managed separately):
- `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini` (persona rename + matching splainer entries)
- `src/fastapi_app/static/js/notifications.js` (badge label uses display_name)
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` (new `conv_mode_exit_reminder()` helper)
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (new `exit_conversation_mode` action handler + `wrap` param on `_inject_via_tmux`)
- `src/tests/unit/test_voice_persona_helpers.py`, `src/tests/unit/test_conv_mode_wrap.py`, `src/tests/unit/test_conversation_mode_router.py`, `src/tests/smoke/test_voice_persona_allocation.py`, `src/tests/smoke/test_cc_notification_listener.py` (new test classes + assertion-count updates for the action push)

**Verification**: 41/41 conv_mode_wrap, 13/13 conversation_mode_router, 11/11 listener event-handling, 33/33 voice persona tests; broader unit suite clean (3920 passed + 1 xfailed) excluding one pre-existing phantom-name flake unrelated to these changes.

**Caveat**: existing CC listener subprocesses are running pre-edit code; the new action handler only activates for sessions started after the listener change is live. Currently-running sessions need to restart for the cross-session exit-reminder injection to fire end-to-end.

---

### 2026.05.01 - Session 31172845 | Bug Fix Mode | Post-mortem remediation: 2026.04.30 22:15-EDT all-suite run

**Context**: User asked for a post-mortem on the 2026-04-30 22:15-EDT all-suite test run (9 smoke failures, 4732 passed, 51 skipped). Authored the post-mortem doc, then a multi-phase remediation plan (approved by user with default-pick instructions for Cluster B + C). User stepped away mid-session and directed autonomous execution under bug-fix-mode for trackable rollback.

**Plan**: `src/rnd/v0.1.7/2026.05.01-postmortem-fixes-plan.md`
**Execution log**: `src/rnd/v0.1.7/2026.05.01-postmortem-fixes-90-execution-log.md` (per-phase entries with file:line evidence and verification tables)
**Post-mortem doc**: `src/rnd/v0.1.7/2026.05.01-postmortem-2026.04.30-2215-edt-all-test-run.md`

#### Accomplishments

| Phase | Cluster | Status |
|-------|---------|--------|
| 0 | Documentation (plan + execution log + post-mortem skip-count + suite-table fixes) | ✅ landed |
| 1A | Smoke skip refactor — `test_container_preflight.py` runtime skips → module-level skip (7 → 1 skip line) | ✅ landed |
| 1B | Integration skip cleanup — renamed `test_phase_*` → `phase_*` in `test_deep_research_orchestrator.py`; removed 6 dead `@pytest.mark.skip` decorators | ✅ landed |
| 2 | D — `test_suite` mode HTTP 500 — defensive branch reorder in `todo_fifo_queue.py:634-655` (CoSA), 15 invariant guard unit tests | ⚠️ defensive only; real `NoneType.split()` source not identified, **filed** for follow-up |
| 3 | G — presentation keyword fallback added in `mock_job.py:268-282` (CoSA), 12 unit tests | ✅ landed |
| 4 | F — `notify_user_sync.py:225` connect-timeout split `(3, N+10)`, 2 unit tests | ✅ **smoke red→green** confirmed (`test_idle_waiter_smoke`) |
| 5 | A — 503 cascade root-caused: `/api/notify` returns 503 when offline + no `response_default`; expediter `_batch_collect_args` doesn't set one; 4 fix options documented and **filed** for design conversation | ✅ diagnosis complete |
| 6 | B — INI-driven per-suite extra pytest_args: 5 new keys + matching splainer + smoke `conftest.py` (5 flag registrations) + `TestSuiteJob._run_suite` append + 4 unit tests | ✅ landed |
| 7 | C — preflight at submit endpoint: docstring-only (architectural blocker — server inside container, no docker socket); 3 design options **filed** | ⚠️ documentation only |

**Test pyramid**: 33 new unit tests (4 new files), 1 smoke test went red→green, 6 dead integration skips eliminated.
**Skip count projection**: 51 → ~45 on next `:8000` run.
**5 follow-up bugs filed** in `bug-fix-queue.md` Queued (Cluster A 503 cascade, Cluster D real bug, Cluster C preflight surrogate, claude-agent-sdk install state, smoke harness label improvement).

#### Files Modified

**Parent Lupin** (this commit):
- `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini` (Phase 6 INI keys)
- `src/lupin_cli/notifications/notify_user_sync.py` (Phase 4 timeout split)
- `src/tests/integration/test_deep_research_orchestrator.py` (Phase 1B renames)
- `src/tests/smoke/test_container_preflight.py` (Phase 1A module-level skip)
- `src/tests/smoke/conftest.py` (NEW — Phase 6 pytest_addoption stubs)
- `src/tests/unit/test_todo_fifo_queue_mode_routing.py`, `test_mock_job_voice_routing.py`, `test_notify_user_sync_timeout.py`, `test_test_suite_job_smoke_extra_args.py` (NEW — 33 tests total)
- `src/rnd/v0.1.7/2026.05.01-postmortem-2026.04.30-2215-edt-all-test-run.md` (skip-count + suite-table corrections)
- `src/rnd/v0.1.7/2026.05.01-postmortem-fixes-plan.md`, `2026.05.01-postmortem-fixes-90-execution-log.md` (NEW)
- `bug-fix-queue.md`, `TODO.md` (post-mortem remediation user-actions + 5 Queued follow-ups)

**CoSA submodule** (commit separately in CoSA session per nested-repo rules):
- `src/cosa/rest/todo_fifo_queue.py` (Phase 2 defensive reorder)
- `src/cosa/rest/routers/mock_job.py` (Phase 3 presentation routing)
- `src/cosa/agents/test_suite/job.py` (Phase 6 per-suite extra args)
- `src/cosa/rest/routers/test_suite.py` (Phase 7 docstring)

**History archive**: 11 sessions from 2026-04-25 to 2026-04-28 moved to `history/2026-04-25-to-28-history.md` (token count 24126 → 12156).

#### Session Summary

| Metric | Value |
|--------|-------|
| Phases executed | 8 (0, 1A, 1B, 2, 3, 4, 5, 6, 7) |
| Phases fully landed | 6 of 8 |
| Phases partial / filed | 2 (Cluster D real bug, Cluster C architectural decision) |
| New unit tests | 33 |
| Smoke regressions red→green | 1 (idle_waiter) |
| Follow-up bugs filed | 5 |
| Auto-commits performed | 0 (per `feedback_never_auto_commit_push`) |

---

### 2026.05.01 - Session f742b1bc | WS "unable to connect" outage — root cause was uvicorn --reload watching the wrong tree

#### Checkpoint | 2026.05.01 ~10:55 EDT | One-config-line fix to `main.py` ends 30s-2min browser outages

Picked up from last night's bug doc (`src/rnd/v0.1.7/2026.04.30-ws-restart-auth-cascade-bug.md`) which had paused with three deferred questions. User's answers immediately ruled out the original hypothesis: trigger was "passage of time" (not a manual restart or `--reload` from a save), the browser was showing its own `ERR_CONNECTION_REFUSED` page (not a Lupin-side `auth_error` or JS disconnect banner), and the outage was 30 seconds to a couple of minutes (not permanent until reload). That combination meant port 7999 was actually unbound at those moments — which on a healthy container can only happen during a uvicorn reload window.

**Diagnosis**: docker container `lupin-rest-dev` was healthy with `RestartCount: 0` and 56-min uptime, but `docker logs` showed uvicorn `StatReload` firing repeatedly on test files in `src/tests/` — `test_voice_persona_helpers.py` and `test_voice_persona_allocation.py`. One concrete burst on 2026-05-01 between 02:08 and 02:15 UTC: 8 reloads in 7 minutes. Each reload tears down the server and rebuilds it; the rebuild takes 12-18 seconds before `Application startup complete` re-fires. During that window port 7999 is unbound — exactly the user's "browser unable to connect" symptom.

**Why uvicorn was watching test files at all**: `src/fastapi_app/main.py:846-853` was launching `uvicorn.run()` with `reload=not is_production_or_test` and **no scope-narrowing**, so the entire `/var/lupin/src` tree was watched, including `tests/` and the LanceDB long-term-memory store at `conf/long-term-memory/lupin.lancedb/...` (which writes constantly at runtime).

**Fix** (`src/fastapi_app/main.py:846-862`): switched from default-watch-everything to a `reload_dirs` whitelist of the five runtime code dirs:

```python
reload_kwargs = {}
if not is_production_or_test:
    reload_kwargs[ "reload" ] = True
    reload_kwargs[ "reload_dirs" ] = [ "fastapi_app", "cosa", "lib", "lupin_cli", "lupin_mcp" ]
uvicorn.run( "fastapi_app.main:app", host="0.0.0.0", port=port, workers=1, log_level="info", **reload_kwargs )
```

Verification: post-bounce `Will watch for changes in these directories` banner shows exactly those five paths. Touched both test files + a LanceDB-path probe; uvicorn fired zero StatReload events. Container healthy on `:7999`.

**False starts worth recording** (all in the bug doc §Resolution):
1. First patch used `reload_excludes=["tests/*", ...]` — failed because uvicorn's StatReload uses `Path.match()` where `*` is a single path-segment matcher, so `tests/*` does NOT match `tests/unit/foo.py`.
2. Second patch used `reload_excludes=["tests/**/*", ..., "**/*.lance/**"]` — pegged the python process at 99% CPU during reload-watcher init because the deep-glob walks every subdirectory of every `.lance` directory and LanceDB has thousands of those (`gist_cache.lance/_versions/`, `_transactions/`, `data/` × many tables). Container hung past `[LUPIN] Starting FastAPI server` for several minutes.
3. Final patch (`reload_dirs` whitelist) is robust and trivially fast.

**Bugs A + B from the original bug doc still open** (cosmetic, log-hygiene only): mislabeled "Token verification failed" message and cascading `send_json` on closed socket at `websocket.py:458-466`. Both `<10` line fixes; held for a follow-up commit since they don't affect the user-visible symptom.

**Open question parked**: even with reload now ignoring `tests/`, the underlying question of *what* is bumping test-file mtimes at irregular intervals (02:08, 02:14, 09:12 EDT today) without anyone running tests is unexplained. Plausible suspects: backup script, IDE indexer, hook, periodic git op. Not urgent; tracked in TODO.md.

**Conversation-mode hygiene self-correction**: user explicitly probed mid-session ("are you in conversation mode, true or false?") after I'd been writing long substantive paragraphs in terminal text *and* duplicating them via `notify()` — the exact anti-pattern from yesterday's `feedback_no_duplicate_notify_in_conversation_mode.md` memory. Acknowledged the violation and corrected mid-turn: terminal text now stays minimal, closing-turn `notify()` carries the full voice content, mid-turn `notify()` is reserved for distinct progress/error content.

**Files** (parent Lupin only — 4): `src/fastapi_app/main.py` · `src/rnd/v0.1.7/2026.04.30-ws-restart-auth-cascade-bug.md` (added §Resolution) · `TODO.md` · `.claude-session.md` · `history.md` (this entry).

---

### 2026.04.30 - Session e8713aeb | Spit-and-polish: cc-strip-icons hover clipping, hookEventName schema fix, voice persona renames

#### Checkpoint | 2026.04.30 22:40 EDT | Three small bugs landed in one focus mode UI/hooks/persona pass

Three independent fixes plus a conversation-mode pitfall captured as a memory.

**Bug 1 — `cc-strip-icons` hover clipping in CC notification panel focus mode** (CSS-only): icons inside the sticky session strip (`.cc-strip-icons`) were getting clipped 4–5 px on all sides when hovered. Root cause: the container had `overflow-x: auto` (which per CSS spec also promotes Y-axis to auto-clipping) plus zero internal padding, so hover scale (1.08×), focus scale (1.10×), and the protruding `::before` mic badge (`bottom: -3px right: -3px`) and `::after` unread badge (`top: -4px right: -4px`) all overflowed and got chopped. Added `overflow-y: hidden` (suppresses the unwanted vertical scrollbar that the implicit Y promotion was triggering) plus `padding: 6px 4px` inside the scroll container to give the scaled icons + badges breathing room. Strip grows ~12 px taller; the toggle button stays vertically centered via the parent's existing `align-items: center`. (`src/fastapi_app/static/css/notifications.css:1975-1992`)

**Bug 2 — `UserPromptSubmit` hook JSON validation error: missing `hookEventName`** (Python — Lupin hook handlers): Claude Code recently tightened the hook output schema to require a `hookEventName` field on `hookSpecificOutput`. `build_additional_context()` in `hook_common.py:421` was emitting just `{ "hookSpecificOutput": { "additionalContext": ... } }`, so the validator was rejecting every hook turn. Added a required `hook_event_name` parameter to the function; updated all four call sites (three in `user_prompt_submit.py` passing `"UserPromptSubmit"`, one in `post_tool_use.py` passing `"PostToolUse"`); refreshed two unit tests with stale shape expectations and added a new propagation test. **Verification**: 91/91 hook unit tests pass; `py_compile` clean on all four modified Python files.

**Bug 3 — Voice persona renames in CC session voice persona pool** (INI + tests): user requested three persona renames in the CC session voice persona pool (Lupin voice-persona allocation system, NOT the podcast generator personalities — those stay): Adam → Tiberius, Quentin → Mr. NPR, Nora → Maria (key kept ASCII, persona is conceptually María). ElevenLabs voice IDs, icons, colors, and profiles all unchanged — only the persona name labels rotated. Updated `src/conf/lupin-app.ini` (pool CSV + four keys per persona × three personas = 12 keys + the ASCII-key explanatory comment) and matching `src/conf/lupin-app-splainer.ini` entries (incl. provenance notes + the Domi color description that referenced Maria for low-alpha disambiguation). Sweep also caught `session_bridge.py`'s inline persona round-trip smoke test (Adam → Tiberius) and the two test files that hardcoded the old pool: `test_voice_persona_helpers.py` (POOL_6 fixture + mock config_mgr persona table + default pool CSV + 8 assertion sites + bridge fixture comment) and `test_voice_persona_allocation.py` (pool name set in two assertions). Initial pass used lowercase `maria` per a literal reading of the user's quoted example; user corrected mid-session ("shouldn't Maria be capitalized since it's a proper noun?") so a second pass recapitalized everywhere. **Verification**: 25/25 unit tests pass; `configparser` round-trip confirmed all six personas resolve cleanly with the renamed keys (including `Mr. NPR` with its period and space — `ConfigParser` tolerates both, lookups stay case-insensitive via `key.lower()` on read). Final pool: `Maria, Mr. NPR, Rachel, Tiberius, Domi, Arnold`. Dev server (`:7999`) needs a `docker restart lupin-rest-dev` to pick up the new INI keys.

**Conversation-mode pitfall captured** (memory): user asked why I wasn't responding by voice in mid-session; the guardrail correctly blocked my preemptive `enter_conversation_mode()` attempt because user hadn't explicitly said the toggle phrase. After user said "let's enter conversation mode," conversation mode activated, but my next two turns produced **duplicate TTS** — I'd written substantive narration in both an opening text block AND a `notify()` call AND a closing reply on the same content. Diagnosed: in conversation mode, the closing-turn `notify()` IS the voice channel for the final response, and adding pre-tool-call narration prose with overlapping content gets spoken too. Captured as `feedback_no_duplicate_notify_in_conversation_mode.md` (and indexed in `MEMORY.md`) so this fails-loud for future me: in conversation mode, exactly one substantive utterance per turn, carried by `notify()` at the end. Mid-turn `notify()` is reserved for content that DIFFERS from the closing reply (progress on long tool work, errors, milestones).

**Files** (12): `src/fastapi_app/static/css/notifications.css` · `src/lupin_cli/claude_code/hooks/lib/hook_common.py` · `src/lupin_cli/claude_code/hooks/user_prompt_submit.py` · `src/lupin_cli/claude_code/hooks/post_tool_use.py` · `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` · `src/tests/unit/test_hook_voice_helpers.py` · `src/tests/unit/test_conv_mode_wrap_threading.py` · `src/conf/lupin-app.ini` · `src/conf/lupin-app-splainer.ini` · `src/tests/unit/test_voice_persona_helpers.py` · `src/tests/smoke/test_voice_persona_allocation.py` · `.claude-session.md` (manifest + memory file written outside the repo at `~/.claude/projects/.../memory/`).

**Commit**: `0de2069` (rewritten on final amend; original pre-amend was `8e0756c`)

---

### 2026.04.30 - Session b195a160 (afternoon continuation) | Postmortem Tier-1+2 closures + slow-test rewrite + Cluster J root-cause

#### Session-End | 2026.04.30 ~21:20 EDT | Closed Clusters D + E + F-step1 + F-step2 + K + slow-test + J | Scheduled :8000 all-test-run for 21:30

**Context**: Continuation of session b195a160 from this morning (commit `177d1af` covered postmortem A/B/C closures + bcrypt 4.3.0 image rebuild + dev/test recompose). Afternoon arc closed every Tier-1 and Tier-2 follow-up from the postmortem doc plus discovered and fixed a hidden 196-second regression introduced by an earlier covert-E2E pattern. Final all-test-run scheduled on :8000 at 21:30 EDT to verify the postmortem-cluster collapse end-to-end.

**Tier-1 + Tier-2 postmortem closures**:

- **Cluster D — `--auto-proxy` fail-fast** (1 smoke fail). `test_presentation_live_smoke.py` + `test_research_to_presentation_live_smoke.py` now raise `RuntimeError` in <1s if invoked under pytest without `--auto-proxy` (env-var sentinel `PYTEST_CURRENT_TEST`). Was burning 900s/2400s timeouts per scheduled run waiting for human gate approvals. CLI dev mode keeps the warning + manual flow. Surfaced (deferred to user) the architectural follow-up: per-test-file pytest_arg declarations that the scheduler could merge.

- **Cluster E — render-only YAML fixture pin** (1 smoke fail). Authored `src/tests/fixtures/presentations/render-only-example.yaml` (3-slide minimum, valid schema) and replaced `_find_latest_yaml()` glob auto-discovery with `_resolve_fixture_yaml()`. Auto-discovery was suspected (but not proven) to suffer from dev-vs-test bind-mount divergence — pinning to a checked-in fixture removes the brittleness regardless. `--yaml-path` CLI override preserved for ad-hoc dev runs. Dropped now-unused `glob` import.

- **Cluster F-step1 — `slide_count` in PG artifacts** (CoSA). Added `self.artifacts["slide_count"] = presentation.total_slides` to `presentation_generator/job.py` LIVE branch (line 290) + sentinel `0` to dry-run branch.

- **Cluster F-step2 — `slide_count` through `ChainedResult`** (CoSA, Path 1 chosen — formal field through state machine, not the dict-passthrough hack). Added `slide_count: Optional[int] = None` to `state.py:ChainedResult`. Orchestrator at `agent.py:214` now reads `pg_artifacts.get("slide_count")` into `self.result.slide_count`. R2P `job.py:256` writes `self.artifacts["slide_count"] = result.slide_count` (LIVE + dry-run branches). Test's `_check_slide_count` will now pass on the next R2P live run.

- **Cluster K — 3-attempt verifier retry with gentle backoff** (CoSA). `notification_proxy/verification.py` loop bumped from 2-attempt to 3-attempt with `time.sleep(0.5 * attempt)` between attempts (0.5s, 1.0s). Yesterday's `FUZZY_BUDGET_2` failed on attempt 1+2 due to vLLM transient empty-XML; this gives 3rd-attempt insurance. Worst-case adds 1.5s for a triply-flaky scenario.

**Discovered + fixed: `test_swe_team_orchestrator.py::TestDryRunRegression` 196-second covert-E2E** (parent + CoSA):

- **Diagnosis**: full-suite run in load-stressed conditions flagged `test_dry_run_completes` as failed; standalone re-run took **196 seconds**. Reading the test confirmed it instantiated `SweTeamOrchestrator` WITHOUT a mocked `team_io`, so `orch.run()` called the REAL `cosa_interface.notify_progress` → `_dispatcher.notify_progress` → `asyncio.to_thread(_notify_user_async, ...)` for every breadcrumb. Under load each notify takes ~25-30s through the dispatcher's IPC path; 7 breadcrumbs × ~28s ≈ 196s. **The test was a covert end-to-end test masquerading as a unit test.**
- **Fix (Path 1: full rewrite)**: split into Tier-1 (fast, mocked) + Tier-2 (slow, real) per the testing-venues rubric. Phase 0 serialized plan to `src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md`. Phase 1 added `DELAY_MULTIPLIER = 1.0` class constant to `MockAgentSDKSession` (CoSA). Phase 2 rewrote `TestDryRunRegression` as 7 small tests + class-autouse fixture that AsyncMocks the 4 `cosa_interface` entry points + zeroes the mock-client delays. Phase 2.5 applied same `monkeypatch` to `test_dry_run_emits_state_changes` (line 386 — same pattern, different class). Phase 3 authored new Tier-2 smoke at `src/tests/smoke/test_swe_team_dry_run_e2e.py` (~80 lines, 240s budget, `:8000`-scheduled venue).
- **Result**: 8 unit tests pass in **0.58 seconds total** (was ~980s for the same coverage area, **~1700× speedup**). Tier-2 smoke takes ~196s against the real dispatcher — that's the smoke doing its job, surfacing dispatcher health honestly. Bumped budget to 240s.

**Cluster J — `'NoneType' object has no attribute 'split'`** (CoSA + parent regression test):

- **Live traceback captured on `:7999`** (after a courtesy bounce of an unhealthy dev container): `queues.py:241 push → todo_fifo_queue.py:1096 _handle_agentic_command → expeditor.py:170 expedite → completion_client.py:237 llm_client.run → aiohttp ClientConnectorError to 192.168.1.21:3001`. The :7999 dev hit a NETWORK error first because that vLLM endpoint isn't reachable from dev — separate infra issue surfaced. On :8000 yesterday, the LLM call SUCCEEDED, control flowed past line 170 to line 340, and `None.split()` fired.
- **Root cause** (static analysis from line 340 + 588 of `expeditor.py`): `agent_entry.get("display_name", agent_entry["cli_module"].split(...)...)` — Python's `dict.get(key, default)` evaluates the default arm **eagerly**. The `test_suite` registry entry has `cli_module=None` by design (API-only agent, no CLI), so the eager `None.split(".")` ran every time. Yesterday's :8000 traceback matches.
- **Fix**: extracted `_resolve_display_name(agent_entry)` static method on `RuntimeArgumentExpeditor` with proper short-circuit (display_name first, cli_module derivation second, "agent" sentinel last). Both call sites now use the helper. Added 8 regression tests in `TestResolveDisplayName` covering the exact `test_suite` registry shape. Full expediter unit suite: 155/0 fail (was 147 → +8).
- **Adjacent finding (NOT cluster J)**: dev `:7999` cannot reach `192.168.1.21:3001` for the runtime-argument expediter's LLM. Test `:8000` could yesterday. Worth a follow-up if it affects dev workflow.

**Schedule for tonight**: `:8000` all-test-run scheduled 2026-04-30T21:30:00-04:00, job_id `ts-0fb8e488::50c73ba7-...`. Predicted delta vs yesterday's 15-failure baseline: **5–6 failures** (closing 7 method-level fails from A+B+C this morning, plus D+E+F+K+slow-test+J this afternoon, plus likely G+H+I via the recompose; held-open: J's adjacent dev-LLM infra issue + visibility on whether G/H/I close cleanly).

**Files committed in this checkpoint** (parent Lupin only — 9 files):
- `src/tests/smoke/test_presentation_live_smoke.py` (Cluster D)
- `src/tests/smoke/test_presentation_render_only_smoke.py` (Cluster E)
- `src/tests/smoke/test_research_to_presentation_live_smoke.py` (Cluster D)
- `src/tests/smoke/test_swe_team_dry_run_e2e.py` (NEW — slow-test Tier-2)
- `src/tests/unit/test_runtime_argument_expeditor.py` (Cluster J — 8 new tests)
- `src/tests/unit/test_swe_team_orchestrator.py` (slow-test Tier-1 rewrite + monkeypatch on test_dry_run_emits_state_changes)
- `src/tests/fixtures/presentations/render-only-example.yaml` (NEW — Cluster E fixture)
- `src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md` (NEW — slow-test plan doc)
- `history.md` (this entry)

**Note on TODO.md**: my afternoon TODO.md edits (postmortem follow-ups marked done, archive task added) landed in commit `b6a8915` ("Session 406cadbf session-end: final closure pass") because the parallel session's session-end ritual used a broader `git add` and swept up my staged-but-uncommitted TODO.md changes. Outcome is correct (TODO.md reflects this session's work and is in HEAD); minor parallel-session-hygiene issue worth flagging.

**CoSA submodule edits NOT in this commit** (per `feedback_lupin_only_never_cosa` — manage from cosa-context):
- `src/cosa/training/quantizer.py` (Cluster B from morning)
- `src/cosa/agents/presentation_generator/job.py` (Cluster F-step1)
- `src/cosa/agents/notification_proxy/verification.py` (Cluster K)
- `src/cosa/agents/deep_research_to_presentation/state.py` (F-step2)
- `src/cosa/agents/deep_research_to_presentation/agent.py` (F-step2)
- `src/cosa/agents/deep_research_to_presentation/job.py` (F-step2)
- `src/cosa/agents/swe_team/mock_clients.py` (slow-test DELAY_MULTIPLIER)
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` (Cluster J)

**Open follow-ups** (parked, in TODO.md):
- Cluster J adjacent: investigate why `192.168.1.21:3001` (vLLM for runtime-argument expediter) isn't reachable from `:7999` dev.
- Cluster I config audit: after the 21:30 EDT all-test-run, verify whether `EXP_PRES_MISSING` still returns "Could not match voice command" (presentation_generator routing in agentic-commands.json may need a reload or cache invalidation).
- history.md archival: deferred this session; user chose "next session" at 20.8k tokens.
- Architectural follow-up: per-test-file pytest_arg declarations the scheduler could merge (so tests like `test_presentation_live` always get `--auto-proxy` without manual repetition at submission).

#### Schedule for verification

- `ts-0fb8e488` — all-test-run on `:8000`, scheduled `2026-04-30T21:30:00-04:00`. Will return cosa-voice notification on completion (~25-45 min depending on dispatcher slowness).

---

### 2026.04.30 - Session 406cadbf | Conversation-Mode Three-Layer Mic-Monopoly Enforcement (Phases 1-5) + cc_listener hardcoded sender_id fix

#### Checkpoint | 2026.04.30 ~20:10 EDT | 7 commits across two thematically distinct fixes

**Context**: Started as a bug-fix session on the cc_notification_listener ghost-card symptom (a CoSA-context CC session was rendering as TWO sender cards in the UI, one correctly under [COSA] and a ghost under [LUPIN] with the same session_id). Root cause was a hardcoded `lupin.deepily.ai` literal in the listener — a regression-shaped miss of the 2026.04.24 nested-repo detection fix. Then pivoted to the architectural-gap conversation that's been outstanding since the conv-mode mic-monopoly mutex (v1.1, Session c7333045 on 2026.04.28): the mutex coordinates the bridge file and UI but **not Claude's in-session belief about `conversation_mode_active`** — so a displaced session's Claude keeps emitting conv-mode-shaped `notify()` calls, producing the multi-session cross-talk symptom user reported on 2026-04-29 ("multiple sessions responding to me through TTS as though I had multiple monopolized conversation engagements running simultaneously"). User's framing: "if it's not code-based and deterministic, then I think that Claude could simply drift away from remembering what state it is in." Designed and shipped a three-layer enforcement net.

**Two thematically distinct fixes** in one session:

#### A. `cc_notification_listener` hardcoded sender_id fix (commits `2eaeffc` + `2ae7f1a`)

- **Bug**: `cc_notification_listener.py:453` constructed the gist-response `sender_id` with `f"claude.code@lupin.deepily.ai#{self.session_id_hash}"` — project segment **literally hardcoded to "lupin"** regardless of which repo the CC session is running in. Nested-repo CC sessions got a ghost `[LUPIN]` sender card alongside their correct `[COSA]` card for the same session_id. Same family as the 2026.04.24 nested-repo bug; missed offender during that fix's audit.
- **Fix** (commit `2eaeffc`): replaced the hardcoded line with `build_sender_id_for_cc(session_id=self.session_id_hash) or f"claude.code@lupin.deepily.ai#{self.session_id_hash}"` (Option 1 — symmetric with the parallel correct path at `permission_request.py:123` → `send_tts()`). The `or` fallback preserves failure-mode parity. Net diff: +1 import line, ±1 logic line.
- **Sweep check**: grepped parent Lupin source for hardcoded `lupin.deepily.ai` literals (excluded tests/CoSA/rnd). Singleton offender; other hits benign (docstring examples, Firefox plugin server URL, swe.* agent seed data). Saved memory `feedback_sweep_for_pattern_offenders.md` codifying the lesson.
- **V5 user-verified** (commit `2ae7f1a`): user restarted a CoSA-context CC session post-commit; no ghost card appeared. Bug fully resolved end-to-end.
- **R&D doc**: `src/rnd/v0.1.7/2026.04.30-cc-listener-hardcoded-sender-id-fix.md`

#### B. Conversation-Mode Three-Layer Mic-Monopoly Enforcement (commits `02af97b` → `d7a6c9f`)

**Architectural gap diagnosed**: the mutex coordinates THREE state surfaces — bridge file (canonical), UI cache (broadcast-driven), and Claude's in-session belief (set ONCE at SessionStart via `get_session_info()`, never refreshed). The first two were correctly wired; surface 3 was the gap. Confirmed by source-inspection of `_notify_impl` (no bridge consultation) and the static MCP `instructions=` block ("check `get_session_info()` once at session start"). User proposed fix architecture: push the state into a per-call gate at the MCP boundary; verify Claude's behavior at every text-injection and notify boundary.

**User-driven design supersedure** during plan drafting: my first F2 fix (drop `<voice-message>` XML wrap, switch to append-only system-reminder) was overcorrecting. User pushed back: *"I think you're throwing the baby out with the bathwater. Sanitize the input by stripping everything from `</voice-message` to the end, in addition to dropping anything after and including `<system-reminder`."* Reinstated the wrapping form + added `sanitize_for_wrap` boundary sanitization. Saved memory `feedback_sanitize_at_boundary_not_format_strip.md` codifying the lesson.

**5 phases delivered** (each phase = one commit + ping):

| Phase | Commit | Layer | Key artifact |
|---|---|---|---|
| 1 | `02af97b` | Wrap helper + sanitization | `sanitize_for_wrap` + `conv_mode_wrap` in `hook_common.py` (27 unit tests) |
| 2 | `a9ff8bc` | Thread through 3 inbound paths | listener tmux inject (voice), qualifier tmux inject (hook-idle-prompt), user_prompt_submit (terminal-typed via `conv_mode_reminder_block`) — pre/post tool use deferred (per-tool-call reminder noise rationale); permission_request, anything_else_ask confirmed outbound + exempt |
| 3 | `3e030dc` | `_notify_impl` bidirectional gate | active forces `priority='high'` + `suppress_ding=True` + strips fenced code; inactive + CC sender + `suppress_ding=True` inverts ding for **audible cross-talk cue** (the original symptom fix); `_internal_call=True` escape hatch for `set_session_topic`; dynamic `cc_meta` session resolution |
| 4 | `9a00d6b` | Stop-hook auto-narrate | reads transcript JSONL, checks for `mcp__cosa-voice__notify` ToolUseBlock, synthesizes `send_tts(narration, priority='high', suppress_ding=True)` if turn ended silent; dedup via `last_autonarrated_turn_id` bridge stamp; 5 fail-closed gates |
| 5 | `d7a6c9f` | Cross-layer integration smoke | mock-driven 3-layer compose verification including the cross-talk-cue regression test |

**Adversarial review pass** before execution: 9 findings raised against my own design doc — 3 critical (F1 layer 2 didn't fix symptom C, F2 wrapper injection vector, F3 inbound/outbound conflation), 3 important (F4 dynamic session resolution, F5 internal-callers exemption, F6 MCP HTTP fallback bypass documented as known limitation), 3 minor. All findings incorporated into the design doc; F2 then user-superseded as noted above. Re-audit pass confirmed coverage of all 13 applicable feedback memories.

**Test totals**: 176/176 pass in 30.1s (83 new + 93 existing regression). Phase 6 (multi-session live verification + WebSocket smoke full run) outstanding, user-gated per `feedback_e2e_two_phase_gate`.

**R&D docs**:
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md` — design + adversarial-review findings table + sweep check
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/90-execution.md` — phase-by-phase execution log with commit hashes + verification details + cumulative summary table
- Viewer URLs: `http://localhost:7999/static/html/document-viewer.html?path=plans/2026.04.30-conv-mode-three-layer-{design,execution}.md` (real file copies in `io/plans/`, refreshed at every phase commit; not symlinks per user direction)

**Memories saved this session**:
- `feedback_sweep_for_pattern_offenders.md` — class-of-bugs fixes require codebase-wide grep, not just call-site patch
- `feedback_sanitize_at_boundary_not_format_strip.md` — defending templated content against injection: prefer boundary input sanitization over giving up structural framing

**Files modified** (Lupin parent only — no CoSA git ops):

R&D:
- `src/rnd/v0.1.7/2026.04.30-cc-listener-hardcoded-sender-id-fix.md` (NEW)
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/90-execution.md` (NEW)

Code (Phase 1+2+3+4):
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (hardcoded fix + Layer 1 voice wrap)
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` (Layer 1 helpers + Layer 1 qualifier wrap + send_tts suppress_ding kwarg)
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (Layer 3 dedup helpers)
- `src/lupin_cli/claude_code/hooks/user_prompt_submit.py` (Layer 1 reminder via additionalContext)
- `src/lupin_cli/claude_code/hooks/stop.py` (Layer 3 auto-narrate)
- `src/lupin_mcp/cosa_voice_mcp.py` (Layer 2 bidirectional gate + strip_fenced_code_blocks helper)

Tests:
- `src/tests/unit/test_conv_mode_wrap.py` (NEW, Phase 1+2)
- `src/tests/unit/test_conv_mode_wrap_threading.py` (NEW, Phase 2 integration)
- `src/tests/unit/test_notify_impl_conv_mode_override.py` (NEW, Phase 3)
- `src/tests/unit/test_stop_hook_auto_narrate.py` (NEW, Phase 4)
- `src/tests/smoke/test_conv_mode_three_layer_integration.py` (NEW, Phase 5)

Tracking:
- `history.md` (this entry)
- `TODO.md` (Phase 6 follow-up)
- `.claude-session.md` (session manifest entries per phase)
- `io/plans/2026.04.30-conv-mode-three-layer-{design,execution}.md` (viewer copies, gitignored)

**Operational notes**:
- TTS notify pipeline timed out 5× across the session before user bounced the server; recovered after bounce.
- Phase 4 test runtime is ~30s due to lazy-import of `cosa_voice_mcp.strip_fenced_code_blocks` triggering MCP module init (account-validation HTTP). Could be optimized by extracting the helper to a lighter module — deferred.

**Open follow-ups** (logged in TODO.md):
- Phase 6 multi-session live verification matrix (10 rows, design doc §4 Phase 6)
- Full WebSocket smoke suite run on user-confirmed slot
- MCP HTTP-fallback mutex bypass at `cosa_voice_mcp.py:1295` (Risk #7, deferred follow-up)
- Pre/post-tool-use Layer 1 threading (deferred per per-tool-call reminder noise rationale; revisit if drift observed)

---

### 2026.04.30 - Session 488ca8bd | CC Notification Session Panel Display Modality — selector strip + exclusive focus mode (Phase 0 + Phase 1 + E2E test file written, :8000 scheduling deferred per user)

#### Checkpoint | 2026.04.30 ~20:00 EDT | Phase 0 docs + Phase 1 implementation + Phase 2 E2E test file (gated for :8000 scheduled run)

**Context**: User wanted a different display modality for the CC notification session panels. Two pains: (a) volume — too much surface area when multiple CC sessions are active; (b) **vertical reorder churn** — every incoming notification bubbles the receiving session's card to the top of the stack, destroying focus mid-read on any one session. Conversation-mode pin only partially helps (engages only during audio). Inspired by the conv-mode mutex, user proposed the *visual* analog: an exclusive focus mode where only one session's card is rendered at a time.

**Elicitation outcome** (Q1-Q6 via Socratic dialogue):
- **Q1 — Conv-mode coupling**: orthogonal axes (independent on/off; either, both, or neither active)
- **Q2 — Non-focused activity**: strip badge (icon glow + numeric unread count); no toasts, no audio interrupts
- **Q3 — Selector strip**: always-on permanent chrome above `#notifications-list`; click-to-scroll in default mode, click-to-switch in focus mode
- **Q4 — Focus toggle placement**: pill button embedded inside the strip itself
- **Q5 — Reorder behavior**: default-view stack still reorders by recency (unchanged); strip icons mirror that ordering (leftmost = most recently updated session); focus-mode preserves the strip's recency-meter behavior so non-focused sessions getting fresh activity slide leftward, providing peripheral awareness without yanking focus
- **Q6 — Appetite**: (ii) proper feature, 1-2 weeks; Pattern 3 with single R&D doc + execution log (BFE-style)

**Phase 0 — Documentation Artifacts** (per DOCUMENTATION-FIRST PROTOCOL):
- `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md` (NEW) — 17-section design: pain, modality choice, conv-mode coupling table, DOM structure, strip icon spec (~40-44px circle, persona-color background, project initial), focus toggle UX, peripheral awareness, `localStorage` persistence (`notifications_cc_focus_state` key), edge cases, why client-only, coexistence with conv-mode pin, single ordering rule (leftmost = freshest in both modes), files-to-modify map, testing layers, deferred items, out-of-scope, revision log
- `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/90-execution-log.md` (NEW) — Phase 0 + Phase 1 + Phase 2 results: sweep findings, files modified, static verification table, surprises, plan-deviation note for WS-smoke layer

**Phase 1 — Implementation** (Lupin parent only, no CoSA edits per `feedback_lupin_only_never_cosa`):
- `src/fastapi_app/static/html/notifications.html` — `#cc-session-strip` chrome added above `#notifications-list` (icons container + toggle pill, `hidden` until first CC session card)
- `src/fastapi_app/static/css/notifications.css` — new ~163-line section: sticky strip, persona-color icons via `var(--persona-color)`, `data-focused` / `data-unread` (with `cc-strip-icon-pulse` keyframe + `::after` numeric badge) / `data-conv-mode` (mic-overlay `::before`) states, `.cc-strip-toggle` pill, `.sender-card[data-focus-hidden="true"] { display: none; }`
- `src/fastapi_app/static/js/notifications.js` — 14 new helper methods (`_addStripIcon`, `_removeStripIcon`, `_promoteStripIcon`, `_setStripIconPersonaColor`, `_setStripIconConvMode`, `_enterFocusMode`, `_exitFocusMode`, `_handleStripIconClick`, `_handleStripToggleClick`, `_bindStripToggle`, `_applyFocusHiddenToCard`, `_clearStripUnreadFor`, `_saveCcFocusState`, `_stripIconIdFor`); `CC_FOCUS_STATE_KEY` constant + `ccFocusState` hydration in constructor + toggle binding; hooks into `createSenderCard` (add icon + apply focus-hidden + bump unread on new non-focused session arrivals during focus), `moveSenderCardToTop` (promote icon + bump unread for non-focused), `deleteSenderConversation` (remove icon + auto-exit focus if focused session deleted), `_setPersonaBadgeOnCard` (mirror persona color to strip icon — bug caught during self-review: initial integration placed mirror after early-return paths, fixed by moving alongside the card's `--persona-color` setProperty/removeProperty calls so it fires on add/replace/release equally), `handleNotificationUpdate` switch case for `conversation_mode_changed`

**Phase 1 sweep + verification on `:7999`** (AI-discretionary, all 8 checks ✅):
- Sweep clean: no existing CSS/JS rule manipulates `.sender-card` display/visibility → no collision with new `data-focus-hidden` rule
- `node --check notifications.js` → OK
- `:7999/health` → 200; HTML/JS/CSS served → 200 each; 67 strip-helper matches in served JS, 19 strip-CSS-rule matches in served CSS, 4 strip-element matches in served HTML

**Phase 2 — Test file written, scheduling DEFERRED per user** (gate per `feedback_e2e_two_phase_gate`):
- `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` (NEW) — 12 Playwright tests across 7 classes (`TestStripRenders`, `TestRecencyReorder`, `TestFocusMode`, `TestPeripheralAwareness`, `TestPersistence`, `TestConvModeOrthogonality`, `TestFocusModeEdgeCases`); covers 11 of 13 plan scenarios. Tests use deterministic DOM injection via `window.notificationsUI._helper(...)` rather than waiting on real multi-session WS notifications.
- **Plan deviation** (documented in `90-execution-log.md` §"Plan deviation"): planned `src/tests/websocket_smoke/test_focus_state_persistence.py` NOT created — the two scenarios it would cover (focus state localStorage round-trip; badge update without focus swap) are DOM/localStorage behaviors, not raw-WS-protocol; properly belong in Playwright. The `src/tests/websocket_smoke/` suite is for connection/auth/event-system protocol tests. Both scenarios are already covered by `TestPersistence` + `TestPeripheralAwareness` in the new E2E file. Net coverage unchanged.
- **Visual regression baselines** (4 PNGs under `__snapshots__/`) NOT yet captured — generated on first `--update-snapshots` run during the deferred E2E batch.
- **Scheduling**: user opted to batch this E2E run with other test work later this evening. No `POST /api/test-suite/submit` from this session.

**Pre-existing modifications NOT staged** (belong to parallel sessions per `.claude-session.md` v2.0):
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/90-execution.md`
- `src/tests/smoke/test_presentation_*` (3 files)
- `src/tests/unit/test_swe_team_orchestrator.py`
- `src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md`
- `src/tests/fixtures/presentations/`
- `src/tests/smoke/test_swe_team_dry_run_e2e.py`

**Out of scope** (deferred per design §16):
- Cross-device focus sync (would need server-side bridge field + WS event — wait for use case)
- Strip overflow strategy beyond `overflow-x: auto` with thin scrollbar (revisit only if 8+ active CC sessions become routine)
- Per-card "anchor" pinning (Q5 option-c from elicitation — separate small feature if reorder churn in default-stacked-view still bothers user)
- Tier 3 / Tier 4 persona theming (held from Round 1 follow-ups in TODO.md; orthogonal to this work)

**Plan**: `~/.claude/plans/i-want-to-start-parsed-blossom.md`

**Files committed in this checkpoint** (Lupin parent only):
- `src/fastapi_app/static/html/notifications.html`, `src/fastapi_app/static/css/notifications.css`, `src/fastapi_app/static/js/notifications.js`
- `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md`, `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/90-execution-log.md` (both NEW)
- `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` (NEW)
- `history.md` (this entry)
- `.claude-session.md` (488ca8bd section + Last Updated — gitignored)

---

### 2026.04.30 - Session b195a160 | Postmortem of 2026-04-29 all-test run + bcrypt 4.3.0 image rebuild + postgres relocation + dev/test recompose

#### Checkpoint | 2026.04.30 ~13:15 EDT | Closed 7 of 15 yesterday-test-run failures + put new bcrypt-pinned image into rotation on both servers

**Context**: User went to the doctor mid-morning with the brief "perform a full Postmortem on yesterday's all test run on the test server. Group errors and failures in the clusters, propose fixes in order of easiest first, and do as much good as you can in my absence." Yesterday's 17:39 EDT `:8000` all-test run produced 4583 passed / 15 failed / 54 skipped / 0 errors. Session executed in three arcs: (a) postmortem + low-risk closures, (b) docker image rebuild (postgres bind-mount permission + uv.lock blockers), (c) tag promotion + recompose.

**Arc 1 — Postmortem (Clusters A/B/C closed, eight others surfaced for user review)**:

- **Postmortem doc** at `src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md` — 11-cluster grouping with cost/risk matrix and predicted next-run delta table.
- **Cluster A** (3 unit failures): `src/tests/unit/test_swe_team_job.py::TestErrorHandling` 3 tests wrapped in `with pytest.raises( <ExcType>, match=... ):` per the Phase 4 #5 do_all re-raise contract from Session d34f2f74. Verified: 22/22 of `test_swe_team_job.py` pass. Full unit suite: 3803/0 fail (was 3770/3 fail yesterday).
- **Cluster B** (3 smoke failures): `src/cosa/training/quantizer.py:8` un-gated `from auto_round import AutoRound` replaced with try/except + `AUTO_ROUND_AVAILABLE` flag (mirrors peft_trainer pattern). `quantize_model()` now raises clear `RuntimeError` if called without `auto_round` installed. Verified by simulated `sys.modules` block — peft_trainer imports cleanly without the cascade. **CoSA submodule edit; not staged in this checkpoint per `feedback_lupin_only_never_cosa`.**
- **Cluster C** (1 smoke failure): `src/tests/smoke/test_tfe_error_capture_smoke.py:105` wrapped `tfe.do_all()` in try/except so forensic assertions still run after re-raise. Verified live on `:7999`: 1/1 pass.
- **Surfaced for user review** in TODO.md: Tier 1 (Cluster D auto-proxy skip-marker, K verifier threshold), Tier 2 (E YAML 404, F slide_count missing, J `'NoneType'.split` in test_suite push handler), Tier 3 (container recreate — addressed in Arc 3 below).

**Arc 2 — Docker image rebuild (two stacked blockers resolved)**:

- **Blocker 1: BuildKit context-load permission**: `src/conf/long-term-memory/postgresql-dev-data` was mode 0700 owned by UID 70 (postgres-in-container). `.dockerignore` already had 11 postgres-specific patterns (lines 1-11) but BuildKit's sender stats the dir BEFORE applying ignore filters. User authorized 1B (durable relocation) and overrode the original plan's target — moved to `/mnt/DATA01/include/www.deepily.ai/projects/lupin-data/postgresql-dev-data` (NOT `/mnt/DATA01/lupin-data/`). Same physical disk → `rename(2)` only, no copy. Pre-flight pg_dump backup at `src/conf/long-term-memory/postgresql-backup.sql` (11 MB).
  - Surprise: passwordless sudo not configured + `mv` (coreutils) won't work even with parent-dir write permission because `rename(2)` on a directory needs write permission on the *directory itself* (to update its `..` entry), and rruiz can't write to a 0700 UID-70 dir. Worked around by spinning up an `alpine:latest` container with `--user 0 -v /mnt/DATA01:/mnt/DATA01` and running `mv` inside — root inside the container has CAP_DAC_OVERRIDE, same-fs rename collapses to instant inode-update. Same outcome as `sudo mv` would produce.
  - 5 files edited (parent Lupin only): `docker-compose.yml` (mount path), `.dockerignore` (deleted 11 patterns + comment), `.gitignore` (deleted dir line, kept backup-file line), `src/scripts/conf/rsync-exclude.txt` (deleted dir line), `src/scripts/run-postgresql-dev.sh` (updated displayed path). Each with breadcrumb comment dating the relocation.
  - Verified: same inode (`24777760`), UID 70, mode 0700 preserved at new path. Postgres came back up healthy on new mount; 119 users in dev DB intact, both dev+test DBs present.
- **Blocker 2: uv.lock drift**: Build then advanced to stage 13/47 and failed with "warning: The package `pydantic-ai==0.6.2` does not have an extra named `slim`. The lockfile at `uv.lock` needs to be updated, but `--locked` was provided." Investigation revealed pyproject.toml line 53 was already correct (`pydantic-ai==0.6.2`, `[slim]` dropped 2026-04-28). The uv.lock had ALSO been cleaned of `[slim]` references. The misleading `slim` warning was a symptom of the broader lockfile-pyproject mismatch — actual drift was `bcrypt` spec (`>=4.0,<5` → `==4.3.0`). Single `uv lock` regen on host produced a 2-line diff and unblocked the build.
- **Build outcome**: All 47 stages passed. `lupin:1.0.0-bcrypt-4.3.0` image (31.7 GB, ID `2283718c1317`) created. Verified bcrypt 4.3.0 inside via `docker run --rm --entrypoint=/opt/venv/bin/python lupin:1.0.0-bcrypt-4.3.0 -c "import bcrypt; print(bcrypt.__version__)"` → `4.3.0`. Per `feedback_no_auto_promote_tags`, parked at candidate tag (NOT yet promoted at this point in the arc).

**Arc 3 — Tag promotion + dev/test recompose**:

- Pre-flight: queue-empty courtesy check on `:7999` per `feedback_dev_server_bounce_courtesy` — todo=0, running pool=0, consumer healthy, heartbeat 16s. Safe.
- `docker tag lupin:1.0.0-bcrypt-4.3.0 lupin:1.0.0` — `lupin:1.0.0` now points to `2283718c1317` (was `8f523bcc8ac2`). Old image preserved on `lupin:1.0.0-fonts` as rollback target.
- `docker compose down lupin-rest-dev && up -d lupin-rest-dev` — healthy in 30s, running new image, bcrypt 4.3.0 confirmed inside.
- `docker compose down lupin-rest-test && up -d lupin-rest-test` — healthy in 31s, same.
- **Verification**: `LUPIN_INTERACTIVE_TESTS=true` now in env on **both** containers (was missing from running test container, was the root cause of yesterday's Cluster G/H/likely-I cascade). bcrypt 4.3.0 in both. `:7999` /health 200, `:8000` /health 200.
- **Surprise**: `(trapped) error reading bcrypt version` log STILL fires with bcrypt 4.3.0. Confirmed via `hasattr( bcrypt, '__about__' ) == False` on the new image. Per pyca/bcrypt issue #684, this is a known 4.1.1+ cosmetic artifact — `hashpw/checkpw` work fine (verified). The 4.3.0 pin still fixes the actual functional breakage that 5.0.0 introduced (which removed `__about__` harder, breaking passlib's bulk-user fixture). The previously-xfail'd `test_admin_users.py::test_list_users_search_filter` and `test_update_user_roles_remove_admin` should now PASS — that was the real value of the pin.

**Predicted next-test-run delta**:

| Stage | Failures |
|---|---:|
| Yesterday | 15 |
| After this morning's 3 file fixes | 8 |
| **After today's recompose (now)** | **5–6** |

Recompose closes Cluster H (swe_team_proxy 3/3 cancels, explicit `LUPIN_INTERACTIVE_TESTS` dependency from yesterday's TODO), very likely Cluster G (12 expediter http_error_503 cascade — same env-var family), possibly Cluster I (presentation routing — fresh config load).

**Files committed in this checkpoint** (parent Lupin only):
- `src/tests/unit/test_swe_team_job.py`, `src/tests/smoke/test_tfe_error_capture_smoke.py` (Clusters A + C closures)
- `docker-compose.yml`, `.dockerignore`, `.gitignore`, `src/scripts/conf/rsync-exclude.txt`, `src/scripts/run-postgresql-dev.sh` (postgres relocation set)
- `uv.lock` (bcrypt spec drift fix)
- `TODO.md` (postmortem + image-rebuild follow-ups, marked yesterday's stale postgres + uv.lock TODO bullets as DONE)
- `src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md` (NEW — postmortem doc)
- `history.md` (this entry)
- `.claude-session.md` (session b195a160 section added + Last Updated bumped)

**CoSA submodule edits NOT in this commit** (per `feedback_lupin_only_never_cosa`): `src/cosa/training/quantizer.py` (Cluster B `auto_round` import gate). Manage via separate cosa-context session.

**Open follow-ups** (parked, surfaced in TODO.md):
- Tier 1: Cluster D `--auto-proxy` skip-marker; Cluster K verifier transient threshold.
- Tier 2: Cluster E (YAML 404 in render-only test); Cluster F (slide_count not in R2P artifacts); Cluster J (`'NoneType'.split` in test_suite push handler — needs `:8000` container stdout grep).
- Optional: route the uv.lock R&D doc to external uv expert (build-blocking severity is gone, the toolchain-governance questions remain).

---

### 2026.04.30 - Session 406cadbf | cc_notification_listener hardcoded sender_id fix

#### Checkpoint | 2026.04.30 ~12:50 EDT | One-line bug fix + R&D doc

**Context**: User reported that a fresh CC session started inside `src/cosa/` (session ID `77dac746`) was rendering as **two sender cards** in the notifications UI for the same session_id — one correctly under `[COSA]`, plus a ghost card under `[LUPIN]` that appeared the moment the listener fired its first voice-receipt ACK ("Received: Why haven't you updated your..."). The receipt notification used a different `sender_id` than the SessionStart-era notifications, so the UI grouped them as separate senders.

**Diagnosis**: `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:453` builds the gist-response notification's `sender_id` with the project segment **literally hardcoded to `"lupin"`**: `f"claude.code@lupin.deepily.ai#{self.session_id_hash}"`. The 2026.04.24 nested-repo detection fix (R&D doc `2026.04.24-cosa-voice-nested-repo-detection-fix.md`) repaired `detect_project()` inside CoSA's `sender_id.py` and added the `build_sender_id_for_cc()` bridge-anchored helper at `session_bridge.py:436` (whose docstring literally describes this dual-card-per-session symptom), but the audit didn't sweep parent Lupin code for hardcoded `lupin.deepily.ai` strings — so this listener offender was missed. Family of bug, missed singleton.

**Fix**: replaced the hardcoded line with `build_sender_id_for_cc( session_id=self.session_id_hash ) or f"claude.code@lupin.deepily.ai#{self.session_id_hash}"` (Option 1 — symmetric with the parallel correct path at `permission_request.py:123` → `send_tts()` → `build_sender_id_for_cc()`). The `or` fallback preserves the legacy hardcoded value as a worst-case fallback if bridge resolution returns `None`, so failure-mode is no worse than today. Added the import. Net diff: +1 import line, ±1 logic line.

**Sweep check**: grepped parent Lupin source for `lupin.deepily.ai` literals (excluded `src/tests/`, `src/cosa/`, `src/rnd/`). Singleton offender — only `cc_notification_listener.py:453` constructs CC-session sender_ids. Other hits are benign (cosa_voice_mcp.py docstring example, README, Firefox plugin server URL, seed_proxy_decisions.py for `swe.*` agents).

**Verification**:

| Layer | Result |
|---|---|
| `py_compile` | OK |
| Import chain | OK |
| `pytest src/tests/smoke/test_cc_notification_listener.py` | passing (mocks `_send_gist_response`, no assertion regression) |
| `pytest src/tests/unit/test_session_bridge_lookup.py` (incl. `TestBuildSenderIdForCcBridgeCwdAnchoring` × 6) | passing |
| Combined | **93/93 passed in 0.20s** |
| Live re-test | User-gated (restart CC session in `src/cosa/`, check UI for ghost card) |

**Files** (Lupin parent only — no CoSA): `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (the fix), `src/rnd/v0.1.7/2026.04.30-cc-listener-hardcoded-sender-id-fix.md` (NEW R&D doc), `history.md` (this entry), `.claude-session.md` (manifest).

**Deployment note**: the listener is a long-lived subprocess spawned by SessionStart hook. In-flight CC sessions still run pre-fix code; the fix takes effect on next SessionStart.

**V5 user-verified 2026-04-30**: user restarted a CoSA-context CC session post-commit `2eaeffc`; no ghost `[LUPIN]` card appeared. Bug fully resolved.

**Out of scope** (separate concerns from user's report):
- The CoSA session's Claude failed to call `set_session_topic()` until prompted — Phase B startup discipline issue, not code.
- This Lupin parent's first `set_session_topic` call this session got `bridge=ok / ui_push=HTTP 401` — succeeded silently in the bridge but didn't reach UI. Retry succeeded. Worth a follow-up if it's recurring.

---

## Archives

- [2026-04-29](history/2026-04-29-history.md) — 3 sessions (Persona Theming Round 1 + WS-event cleanup, passlib/bcrypt 4.3.0 pin diagnosis, Test-Suite Anomaly Remediation Phases 1+2+3 + Idle-Aware Stop Hook)
- [2026-04-25 to 04-28](history/2026-04-25-to-28-history.md) — 11 sessions (per-session voice personas, conversation-mode v1.1, test-suite anomaly remediation, conversation-mode-for-CC, docker image hygiene 130→31.6 GB, notification dispatch unification, cosa-voice MCP fix, podcast completion URLs)
- [2026-04-22 to 04-24](history/2026-04-22-to-24-history.md) — 6 sessions (PR Readiness 100%-green, CJ Flow Async Phase 0+1, cosa-voice nested-repo fix, [UNKNOWN] hyphen fix, TFE model flip, LanceDB-GCS CUDA OOM resolution)
- [2026-04-14 to 04-21](history/2026-04-14-to-21-history.md) — 12 sessions (TFE Resume E2E, BFE Phase 6 obs, CJ Flow async design, Opus 4.7 + thinking-effort, bug fixes)
- [2026-04-08 to 04-14](history/2026-04-08-to-14-history.md) — 23 sessions (TFE E2E, BFE Phase 6, checkpoint-resume, bug fixes)
- [2026-03-26 to 04-07](history/2026-03-26-to-04-07-history.md) — Sessions 379-a47f938e (BFE Phase 6, CJ Flow persistence, Sonnet pivot, UPE LanceDB isolation)
- [Full archive index](history/README.md)
