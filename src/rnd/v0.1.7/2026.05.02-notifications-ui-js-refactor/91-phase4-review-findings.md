# Phase 4 — Plan Review Pipeline Findings (Pre-Approval Consolidation)

**Date**: 2026-05-04 PM
**Status**: 🔴 **Awaiting user ratification per PIP `plan-review.md` §6 (Gate 1) + §9 (Gate 2)** — no fixes applied to `05-phase4-stores-design.md` until user approves which findings to act on.
**Pipeline run**: REUSE pre-pass + Pass 1 Fitness + Pass 2 Adversarial (all three Agents in parallel; fresh-context per canonical PIP spec)
**Plan doc under review**: `05-phase4-stores-design.md` (320 lines, drafted 2026-05-04 PM session ec746144)

This document is the user-facing **batched review summary** — three Agent passes consolidated into one ratification surface. Once user picks per-finding `Apply` / `Reject` / `Defer`, AI applies approved fixes per PIP §7 Resolution Loop, runs convergence re-greps, and updates the design doc's idempotency marker. After all three passes converge cleanly, user gives final go-ahead and `90-execution-log.md` Phase 4 section opens for implementation.

**No code is written until the entire pipeline closes with user approval.**

---

## TL;DR — User decisions required (in priority order)

| # | Decision | Why it's blocking | Recommendation |
|---|----------|-------------------|----------------|
| **D-A** ✅ | **PCM decoder contract** — `decodeAudioData` (design says) vs raw PCM16 conversion (legacy actually uses) | Server sends raw 24kHz PCM16; `decodeAudioData` will reject every frame. Without resolution, AC7 fails by design. | **RATIFIED 2026-05-04 PM — Option 1**: Adopted legacy `pcm16ToAudioBuffer(buf, sampleRate=24000)` shape. Rewrites applied to: pcm-decoder.ts file row (synchronous PCM16 contract); §AudioStore XState section (decoder-is-synchronous note + chunk_decoded event rename + decode_failed paths enumerated); Q1 marked RATIFIED. |
| **D-B** ❌ MOOT | **Response endpoint URL** — `/api/notify/response` (design) vs `/notify/response` (server canonical at `notifications.py:923`) | ~~Live `respond()` calls will 404 in Phase 6.~~ | **AGENTS MISREAD THE ROUTER PREFIX.** `notifications.py:70` registers `router = APIRouter(prefix="/api", ...)`. The `@router.post("/notify/response", ...)` at line 923 mounts under that prefix as `/api/notify/response` — exactly what the design says. URL is correct as-written; no edit. Both REUSE Design Concern #4 + Pass 1 Finding #2 + Pass 1 Finding #2 are FALSE POSITIVES (agent missed the router prefix wiring). User-confirmed via independent grep 2026-05-04 PM. |
| **D-C** ✅ | **AC9 verification mechanism** — `page.evaluate(audioTransport.binaryHandler)` requires `window` global, contradicting no-globals rule | AC9 is unexecutable as written. | **RATIFIED 2026-05-04 PM — Option B**: boot.ts emits one-shot `boot_complete` EventBus event + mirrored `console.log("[multiplexer] boot_complete", JSON)` line; AC9 reads via Playwright's `page.on("console", ...)` and asserts `payload.handlers.audioBinary === "audioStoreBinaryHandler"`. Edits applied to: AC9 row, boot.ts edit row (boot_complete emission), shared/types.ts edit row (`boot_complete` in union + `BootCompletePayload` interface). Phase 1 no-globals invariant preserved; verification is the production code path. |
| **D-D** ✅ | **Transport binary-handler API** — Phase 3 takes handler at `start()` time as constructor arg; Phase 4 design implies mutable property assignment | API mismatch; Phase 4 won't compile against Phase 3 contract as written. | **RATIFIED 2026-05-04 PM — Option B**: boot.ts reordered (createTransports factory → createStores → transport.start(sessionId, audioStore.binaryHandler)). Zero new transport API; no race window; Phase 3 contract literally unchanged. Edits applied to: AudioStore file row (named bound method), stores/index.ts file row (createStores signature drops audioTransport parameter), boot.ts file row (sequence rewrite), AudioStore §"Replaces Phase 3's debug-logger" (full code snippet showing audioStoreBinaryHandler shape). |
| **D-E** ✅ | **SenderRecord field set** — design's `voice_persona?: {name, color}` is a strict subset of legacy `senderPersonaMap` shape `{name, voice_id, icon, color, borrowed}` | `voice_id` is consumed by `getVoiceIdForSender` for TTS routing in Phase 6. Dropping fields forces re-add cycle. | **RATIFIED 2026-05-04 PM — yes**: Extended `SenderRecord.voice_persona` to `{name, voice_id, icon, color, borrowed}` matching legacy `notifications.js:128` shape. Per-field rationale documented in design doc §SenderStore. Phase 6 TTS routing can consume `voice_id` without SenderStore mid-rebuild interface change. |
| **D-F** ✅ | **`sys_time_update` as countdown tick source** — server-broadcast cadence not 1Hz-guaranteed; UX risk | Action-required prompts may have jagged countdowns. | **RATIFIED 2026-05-04 PM — Option 2 (hybrid)**: per-actor `setInterval(1000)` for smooth 1Hz UX + `sys_time_update` as authoritative clockOffset reconciler + `connection_state_change` freeze/resume handling. Edits applied to: ActionRequiredStore §XState section (full hybrid behavior spec), ActionRequiredStore file row, action_required_store.test.ts file row (per-store minimum bumped 18 → 22 tests), Q3 marked RATIFIED. Auto-expiry stays local-only (no POST default). |
| **D-G** | **Q1-Q7 ratification** — Pass 1 provided explicit answers; user confirms/overrides | Open Questions block move to implementation per PIP §6. | All 7 are reasonable; defaults proposed below. Confirm batch-ratify or call out specific overrides. |

After D-A through D-G are decided, the remaining ~24 findings are wording/coverage/test-spec tightening — straightforward Resolution Loop iteration without further user input needed.

---

## Q1-Q7 ratification (Pass 1's proposed answers)

| Q | Question | Pass 1's proposed answer | Confirm? |
|---|----------|--------------------------|----------|
| Q1 | PCM decoder location | ✅ Separate module (`audio/pcm-decoder.ts`) — but contract changes per D-A above | TBD |
| Q2 | NotificationStore persistence | ✅ Unread count only (with debounce + schemaVersion per Pass 1 finding #5) | ✅ RATIFIED 2026-05-04 PM |
| Q3 | ActionRequired local expiry | ✅ Local-only transition, do NOT POST default | TBD |
| Q4 | Cross-tab BroadcastChannel set | **SIDESTEPPED via Q12** (single-tab application policy ratified 2026-05-04 PM in `01-phase0-decisions.md`). No store broadcasts cross-tab in Phase 4. Phase 2 broadcast.ts is inert; cleanup tracked in TODO.md. | ✅ RATIFIED via Q12 |
| Q5 | XState v5 actor pattern | ✅ Tracker pattern (matches Phase 2 AuthManager + Phase 3 CSM precedent) | ✅ RATIFIED 2026-05-04 PM |
| Q6 | AudioContext lifecycle | ✅ Lazy on first chunk (browser autoplay policy) — failure emits `store_audio_state_change { state: "error", reason: "audiocontext-blocked" }` | ✅ RATIFIED 2026-05-04 PM |
| Q7 | JobStore history hydration | ✅ Lazy via Phase 5+ renderer (keeps Phase 4 dependency-surface minimal) | ✅ RATIFIED 2026-05-04 PM |

---

## REUSE Pre-Pass Findings

**Verdicts**: 6 reuse-as-is (patterns) + 5 extend-existing + 7 genuinely-new + 2 design-conflict. 4 Layer 3 design concerns (folded into TL;DR above as D-A, D-B, D-E, D-F).

| ID | New thing the plan proposes | Existing prior art (file:line) | Verdict | Recommended action |
|---|---|---|---|---|
| RE-1 | NotificationStore — list, dedup, unread, expiry sweep | `notifications.js:236, 5654, 2607, 2616` | genuinely-new | Accept as new (greenfield isolation per Q5) |
| RE-2 | JobStore — 5-bucket layout | `notifications.js:5910, 6238` (hydration only); server emits at `running_fifo_queue.py:533` | genuinely-new | Accept as new |
| RE-3 | AudioStore XState actor | `notifications.js:4546, 4536, 84-88` (PCM playback patterns) | extend-existing | **D-A** — must use raw PCM16 path, NOT `decodeAudioData` |
| RE-4 | ActionRequiredStore XState actor | `notifications.js:236-237, 14968-15020, 12625, 12895` | extend-existing | Port lifecycle states; replace `setInterval` per **D-F** |
| RE-5 | SenderStore Map<sender_id, SenderRecord> | `notifications.js:128-132, 283-292, 5614-5628, 9000` | extend-existing | **D-E** — extend `SenderRecord` with `voice_id`/`icon`/`borrowed` |
| RE-6 | `createStores(eventBus, storage, audioTransport)` factory | `multiplexer/transport/index.ts:31` (`createTransports` pattern) | reuse-as-is (pattern) | Apply: copy factory shape exactly |
| RE-7 | `audio/pcm-decoder.ts` — `Blob → AudioBuffer` via `decodeAudioData` | `notifications.js:4580-4596` (manual Int16→Float32 conversion at 24kHz) | extend-existing / **DESIGN-CONFLICT** | **D-A** — rewrite contract |
| RE-8 | LupinEventType union additions (6 store events) | `multiplexer/shared/types.ts:11-43` | extend-existing | Apply: append following Phase 3 precedent |
| RE-9 | `Notification` interface | No TS prior art; legacy untyped at `notifications.js:5615, 5654`; canonical schema in `cosa/rest/routers/notifications.py` | genuinely-new | Source fields from server contract; design currently misses `job_id`, `voice_persona`, `priority`, `notification_type`, `created_at`/`updated_at` |
| RE-10 | `Job` interface | No TS prior art; server `JobState` enum at `running_fifo_queue.py:1024, 147` | genuinely-new | Status enum in design (`todo\|running\|done\|dead`) misses `JobState.QUEUED`/`STALLED` — match server enum exactly |
| RE-11 | `SenderRecord` interface | `notifications.js:128` defines `{name, voice_id, icon, color, borrowed}` | extend-existing | **D-E** |
| RE-12 | `ActionRequiredItem` interface | `notifications.js:236` (state Map values) — carries `default_value`, `response_type`, `options` | extend-existing | Add `response_type` field (`yes_no\|multiple_choice\|open_ended\|open_ended_batch`) — needed by Phase 5 renderer for widget selection |
| RE-13 | `AudioPlaybackState` type | `notifications.js:84-88` (raw state vars, no enum) | genuinely-new | First enumeration; verify against legacy reachable states (e.g., `priming` for AudioContext.suspend resume) |
| RE-14 | `stores_integration.test.ts` cross-store fan-out | `multiplexer/tests/event_bus.test.ts`, `auth_manager.test.ts`, etc. | reuse-as-is (pattern) | Apply: `tsx --test` + `c8` idiom established |
| RE-15 | `test_multiplexer_phase4_smoke.py` Playwright pattern | `src/tests/smoke/test_multiplexer_phase{1,3}_smoke.py` | reuse-as-is (pattern) | Apply: copy Playwright scaffolding shape |
| RE-16 | AudioStore as `binaryHandler` for AudioTransport | `multiplexer/transport/AudioTransport.ts:35-38, 56-59` (override hook already exists) | reuse-as-is | Apply — pure boot.ts wiring change; zero new transport code (but see **D-D** for ordering) |
| RE-17 | `sys_time_update` as countdown tick source | `notifications.js:2625-2635` (clock display only — never as countdown driver) | genuinely-new | **D-F** |
| RE-18 | `/api/notify/response` URL | Server canonical: `POST /notify/response` (`notifications.py:923` — NO `/api` prefix) | **DESIGN-CONFLICT** | **D-B** — citation fix |
| RE-19 | `notification_play_sound` event consumer | Whitelisted at `lupin-app.ini:623`; no emitter found in `cosa/rest/routers/`; legacy `notifications.js:2620-2622` is no-op | genuinely-new but check emitter | Verify event is actually emitted; if not, NotificationStore subscribes to dead silence — drop from contract |
| RE-20 | NotificationStore persistence key `lupin:notifications:unread-count` | `multiplexer/shared/StorageService.ts:16` (KEY_PREFIX = `lupin:`) | reuse-as-is (pattern) | Apply — design key is just `notifications:unread-count`; StorageService prepends prefix |

**Layer 3 Design Concerns from REUSE**: 4 (D-A, D-B, D-E, D-F — all in TL;DR).

---

## Pass 1 Fitness Findings

**18 findings clustered around RISK SURFACE (4), AMBIGUITY (5), TESTABILITY (3), EXTERNAL DEPENDENCIES (4), DECISION TRACEABILITY (2), SCOPE (1).**
**0 Layer 3 design concerns** — all findings resolvable inside the design doc.

| ID | Section / line | Type | What's missing | Proposed fix | Severity |
|---|---|---|---|---|---|
| F1 | §Files line 79 + §AudioStore lines 167-173 | RISK SURFACE | Transport API mismatch — Phase 3 takes handler at `start(sessionId, binaryHandler?)` time, not as mutable property. Order-of-construction with `createStores` is unspecified. | **D-D** in TL;DR | Block |
| F2 | §ActionRequiredStore line 201 | EXTERNAL DEPS | `respond()` posts to `/api/notify/response` — wrong URL (server canonical is `/notify/response`); body schema unspecified | **D-B** in TL;DR | Block |
| F3 | §SenderStore line 222 | AMBIGUITY | "addressed-to-self" is undefined client-side — no addressee field on `notification_received`, no comparison rule | Drop the conditional and bump on every `notification_received` (simplest); OR define predicate + add unit tests | Major |
| F4 | §NotificationStore line 122 + reducer bullet 4 | RISK SURFACE | Synthesized expiry: re-entrancy risk if store also subscribes to its own emit; cross-tab broadcast unspecified; double-expire race not handled | Spec: synthesized expiry mutates state directly + emits `store_notifications_changed { source: "local-sweep" }`; subsequent server `notification_expired` for same `id_hash` is idempotent no-op; add unit test for double-expire race | Major |
| F5 | §NotificationStore line 124 (Persistence) | RISK SURFACE | `setJSON` "on every unread-count change" — no debounce; schema-version field unspecified | Spec: 250ms tail debounce or `requestIdleCallback`; envelope must include `schemaVersion: 1` per Phase 2 contract; unit test asserting envelope shape | Major |
| F6 | §AudioStore line 169 + AC5 line 235 | TESTABILITY | XState event vocabulary listed in prose but no transition table; AC5 is unverifiable without one | Add explicit state×event transition table; use it as test-oracle for AC5 | Major |
| F7 | §ActionRequiredStore line 199 | RISK SURFACE | `sys_time_update` cadence unspecified (5s vs 60s per `app_debug` toggle); no offline-freeze behavior | **D-F** in TL;DR | Major |
| F8 | §ActionRequiredStore line 202 | EXTERNAL DEPS | `cancelled` via server-side `notification_responded` fanout — server contract not cited | Verify in `routers/notifications.py` + `websocket_manager.py`; if no fanout, rely on Phase 2 BroadcastChannel for cross-tab `responded` | Major |
| F9 | §SenderStore line 225 (BroadcastChannel) | DECISION TRACE | Double-broadcast risk: Phase 2 already broadcasts `voice_persona_*` at EventBus layer; Phase 4 Q4 re-broadcasts `store_senders_changed` derived from same | Pin layer: cross-tab owned at EventBus (Phase 2 whitelist); SenderStore is pure local consumer; drop `store_senders_changed` from Q4 broadcast set | Major |
| F10 | §AC7 line 237 | TESTABILITY | "test fixture" mechanism for TTS chunk emission unspecified; no existing endpoint | Spec: either build `/api/audio/test-chunk` debug endpoint OR send fixture via `page.evaluate` direct into AudioStore (bypasses transport) | Major |
| F11 | §NotificationStore line 121 + reducer bullet 2 | AMBIGUITY | "if `action_required`, also forward to ActionRequiredStore" — violates EventBus-only inter-module rule (Phase 2 line 47) | Restate: NotificationStore reduces own slice; ActionRequiredStore subscribes to same `notification_responded` independently; no store-to-store calls | Major |
| F12 | §Files line 88 (`stores_integration.test.ts`) | TESTABILITY | "ordering deterministic" — EventBus listener invocation is registration-order; depends on `createStores` order | Spec canonical subscription order in `index.ts`: `notifications → senders → actionRequired → audio → jobs`; assert via microtask boundary in test | Minor |
| F13 | §AudioStore line 162 (pause/resume/skip) | SCOPE | Listed as "driven by user actions in Phase 6" but part of Phase 4 public API — risk of dead API drift | Either (a) defer to Phase 6, OR (b) keep + require unit tests through direct method invocation. State which | Minor |
| F14 | §Verification matrix line 250 | TESTABILITY | "~70-90 new = ~190-210 pass" is fuzzy; no per-store minimum | Per-store floor: NotificationStore ≥18, JobStore ≥12, AudioStore ≥18, ActionRequiredStore ≥18, SenderStore ≥10, pcm-decoder ≥6, integration ≥6 = 88 minimum | Minor |
| F15 | §AC10 line 240 | COMPLETENESS | "still green" too soft for automated AC; no enumerated commands | Enumerate: TS compile, ESLint, Phase 1 smoke 7/7, Phase 2 unit suite, Phase 3 smoke 1/1, Phase 3 WS smoke 4/4 | Minor |
| F16 | §Out of scope line 62 | DECISION TRACE | ClaudeCode out of scope per D1 — but `claude_code_event` still emitted by QueueTransport (Phase 3) and unconsumed in Phase 4 | Add note: event flows to EventBus and is dropped on the floor (no listener); intentional per D1; Phase 5+ may add consumer | Minor |
| F17 | §ActionRequiredStore line 180 (`options`, `default`) | EXTERNAL DEPS | Which notification subtypes carry these fields? `converse` is open-ended with no options; `ask_yes_no` has fixed `["yes","no"]` | Spec: list `response_type ∈ {"yes_no", "multiple_choice", "open_ended"}` + per-type options array shape; cite `notifications.py` ranges | Minor |
| F18 | §JobStore line 130 (`status` enum) | RISK SURFACE | `status` enum is 4-value but `bucket()` accepts 5 values including `"history"` — divergence | Either (a) add `"history"` to status enum, OR (b) document bucket as reducer-derived view (status = server-side authoritative; bucket = UI-side derived) | Minor |

---

## Pass 2 Adversarial Findings

**11 findings — all ownership-language / executability gaps in verification matrix, AC table, rollback section.**
**1 Layer 3 design concern**: AC9 `page.evaluate` mechanism contradicts no-globals rule (folded into TL;DR as D-C).

| ID | Section / line | Problem | Proposed fix | Severity |
|---|---|---|---|---|
| A1 | §AC6 line 236 | "100% lines per module with `c8 ignore` regions allowed only with explicit inline rationale" — no EXECUTOR tag on rationale-acceptance step; reads as soft user-checkpoint | Add: "EXECUTOR: AI — any `c8 ignore` region MUST include same-line comment naming unreachable branch + reason; AI rejects PRs lacking this. No human gate." | Major |
| A2 | §AC7 line 237 | "server is requested to send a TTS chunk via test fixture" — passive voice; fixture mechanism undefined; AC7 unexecutable as written | Either name existing fixture endpoint OR add sub-AC7a building one; reframe AC7 with explicit POST + assertion (also F10) | Block |
| A3 | §AC9 line 239 | `page.evaluate(audioTransport.binaryHandler !== console.debug)` requires `window` global; contradicts no-globals rule | **D-C** in TL;DR | Block |
| A4 | §AC4 line 233 | "122 + ~70-90 = ~190-210" — fuzzy range; AI cannot assert "approximately N tests pass" | Hard floor: "exit 0; total ≥ 192; zero failures; final count in execution log" (also F14) | Major |
| A5 | §Build verification line 252 | "size growth proportional to store code addition" — judgment call, no numeric threshold | "boot.js size delta vs Phase 3 baseline ≤ 30 KB gzipped; AI flags if delta exceeds bound" | Minor |
| A6 | §Verification matrix lines 253-256 | Phase 1 / Phase 3 / WS smoke rows lack EXECUTOR tags entirely | Add Executor column to matrix OR add `EXECUTOR: AI` to every row's pass criterion (match AC table format) | Major |
| A7 | §Rollback steps 1-3 lines 263-265 | Implicit precondition "regression detected" has no defined trigger; AI auto-revert vs ask is undefined | Add step 0: "EXECUTOR: AI — IF Phase 1+2+3 verification non-zero AND `git blame` points at Phase 4 code, AI MUST notify via cosa-voice `ask_yes_no` 'Auto-revert?' before step 1. AI does not silently revert." | Major |
| A8 | §Q6 resolution line 277 | AC7 requires `decoding → playing` within 2s but Q6 says "audiocontext-blocked" is a valid failure mode in headless without gesture | Add to AC7: "Playwright launches with `--autoplay-policy=no-user-gesture-required`; if absent, AI flags as blocker" | Major |
| A9 | §Idempotency marker line 320 | "Last reviewed: TBD (...)" — implies user approval is close criterion but never states EXECUTOR for marker update | Add: "EXECUTOR: AI — at Pass 2 convergence + post user-approval, AI overwrites with `last-reviewed-at: YYYY-MM-DD (commit-hash)` per PIP §12" | Minor |
| A10 | §Q2 resolution line 273 | Server-side replay claim ("server keeps recent events on `auth_success`") cited without file:line | Cite or flip Q2 to require pre-req | Major |
| A11 | §Q5 resolution line 276 | "matches Phase 2 + Phase 3 ConnectionStateMachine precedent" without file:line | Add file:line cites | Minor |

---

## Convergence re-grep results (per PIP §7)

Run on the design doc as it stands BEFORE any fixes:

```
$ grep -rn "TBD\|confirm during impl\|decide at impl time\|tbd" 05-phase4-stores-design.md
19, 272, 273, 274, 275, 276, 277, 278, 312, 313, 320  (11 hits — all expected: §"Open Questions" Q1-Q7 + slot table + last-reviewed marker)

$ grep -rn "Open sub-question" 05-phase4-stores-design.md
(no matches — Convention 4 unused)

$ grep -rn "Manual\|manual" 05-phase4-stores-design.md
(no matches)

$ grep -rn "EXECUTOR: HUMAN" 05-phase4-stores-design.md
(no matches)

$ grep -rnE "^\- \[ \] [^E]" 05-phase4-stores-design.md
(no matches — no checkbox lists)
```

Baseline is clean on Pass 2's three structural greps and Pass 1's two unresolved-question greps (the 11 TBD hits are expected — those are the Q1-Q7 ratification surface PLUS slot-table placeholders that resolve at user-approval time).

---

## What happens after user ratification

1. User picks `Apply` / `Reject` / `Defer` for each finding above (D-A through D-G + REUSE/F1-F18/A1-A11)
2. AI applies approved fixes as edits to `05-phase4-stores-design.md` (per PIP §7 Resolution Loop)
3. AI re-runs the five greps above; expects all "fixed" hits gone + zero new hits
4. AI reports diff baseline → post-fix; if convergence clean, advance termination check
5. Termination check per PIP §10: 0 new structural findings OR 2 rounds done
6. AI updates idempotency marker per PIP §12
7. AI appends "Prior art referenced" subsection to design doc (REUSE outcomes for `reuse-as-is` + `extend-existing` rows)
8. User gives final go-ahead → `90-execution-log.md` Phase 4 section opens (status: in-progress)
9. AI implements per spec, runs verification matrix, files commit hash

**At this point**: pipeline is on hold at step 1. AI is not applying anything until user returns and ratifies.

---

## Appendix — full agent transcripts

The three Agent transcripts are stored at:
- REUSE pre-pass: `/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin/ec746144-dd8a-4336-a3c3-311d8906e24a/tasks/a79607306f58d8c02.output`
- Pass 1 Fitness: `/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin/ec746144-dd8a-4336-a3c3-311d8906e24a/tasks/a019b226c00f2ae51.output`
- Pass 2 Adversarial: `/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin/ec746144-dd8a-4336-a3c3-311d8906e24a/tasks/a2a51c8cc05210337.output`

These are full JSONL transcripts; this consolidation document is the user-facing summary of their conclusions.

---

**Status**: ✅ **Plan-review pipeline closed 2026-05-04 PM.** All gates passed. See "Resolution Loop closure" below.

---

## ✅ Resolution Loop closure (2026-05-04 PM)

User ratified all decision blockers + delegated minor-findings application to AI per PIP §7 Resolution Loop.

### Blockers ratified (D-A through D-G + Q12)

| Tag | Decision | Where applied in design doc |
|---|---|---|
| **D-A** | Option 1 — `pcm16ToAudioBuffer` raw PCM16 path | pcm-decoder.ts file row + AudioStore XState section + Q1 RATIFIED |
| **D-B** | MOOT — agents misread server router prefix; URL was correct | 91-phase4-review-findings.md TL;DR row |
| **D-C** | Option B — boot_complete EventBus event + console.log | AC9 + boot.ts edit row + shared/types.ts edit row |
| **D-D** | Option B — reorder boot.ts (createStores before transport.start) | AudioStore file row + stores/index.ts file row + boot.ts edit row + AudioStore §"Replaces Phase 3's debug-logger" |
| **D-E** | Yes — extend SenderRecord.voice_persona to full 5-field shape | SenderStore interface + rationale section |
| **D-F** | Option 2 — hybrid setInterval + sys_time_update reconcile + connection freeze | ActionRequiredStore XState section + file row + test file row + Q3 RATIFIED |
| **D-G/Q2** | Option A — unread count only with debounce + schemaVersion | NotificationStore Persistence section + Q2 RATIFIED |
| **D-G/Q4** | SIDESTEPPED via Q12 (single-tab application) | Q12 added to 01-phase0-decisions.md + 00-synthesis-and-roadmap.md + broadcast.ts header + TODO.md cleanup follow-up + Q4 RATIFIED |
| **D-G/Q5** | Tracker pattern | Q5 RATIFIED + AudioStore + ActionRequiredStore notes |
| **D-G/Q6** | Lazy on first chunk | Q6 RATIFIED + AudioStore lazy AudioContext bullet |
| **D-G/Q7** | Lazy via Phase 5+ renderer | JobStore interface + JobStore section + file row + Q7 RATIFIED |

### Pass 1 Fitness — 18 findings (all closed)

| ID | Status | Where applied |
|---|---|---|
| F1 | RATIFIED via D-D | AudioStore + stores/index.ts + boot.ts file rows |
| F2 | MOOT (false positive) | D-B notes — agents misread router prefix |
| F3 | APPLIED | NotificationStore reducer (drop addressed-to-self) + SenderStore reducer (same alignment) |
| F4 | APPLIED | NotificationStore reducer "Periodic expiry sweep" — local mutation + idempotent + double-expire test required |
| F5 | RATIFIED via D-G/Q2 | NotificationStore Persistence section (debounce + schemaVersion + storage_corrupt) |
| F6 | APPLIED | AC5 explicit state×event transition table requirements |
| F7 | RATIFIED via D-F | ActionRequiredStore XState section (hybrid timer) |
| F8 | APPLIED | ActionRequiredStore `cancelled` reachability — Phase 4 implementation MUST verify server-side fanout |
| F9 | OBSOLETE via Q12 | No cross-tab broadcast at all in Phase 4 |
| F10 | APPLIED | AC7 fixture mechanism specified (build sub-AC7a if endpoint missing) |
| F11 | APPLIED | NotificationStore reducer — no store-to-store calls; ActionRequiredStore subscribes via EventBus |
| F12 | APPLIED | stores/index.ts file row — canonical subscription order pinned: notifications → senders → actionRequired → audio → jobs |
| F13 | APPLIED | AudioStore interface — pause/resume/skip stay Phase 4 with direct unit test invocation |
| F14 | APPLIED | AC4 per-store test floors (NotificationStore ≥18, JobStore ≥12, AudioStore ≥18, ActionRequiredStore ≥22, SenderStore ≥10, pcm-decoder ≥6, integration ≥6 = 88 minimum) |
| F15 | APPLIED | AC10 enumerated commands (7 commands explicit) |
| F16 | APPLIED | Out of scope — `claude_code_event` flows to floor (no consumer); intentional per D1 |
| F17 | APPLIED | ActionRequiredItem interface — `response_type` field added |
| F18 | APPLIED | JobStore Status vs bucket clarification subsection + Job interface comment |

### Pass 2 Adversarial — 11 findings (all closed)

| ID | Status | Where applied |
|---|---|---|
| A1 | APPLIED | AC6 — c8 ignore inline-comment EXECUTOR contract |
| A2 | APPLIED | AC7 fixture mechanism (overlap with F10) |
| A3 | RATIFIED via D-C | boot_complete event + console.log mechanism |
| A4 | APPLIED | AC4 hard floor (overlap with F14) |
| A5 | APPLIED | Verification matrix Build row — boot.js delta ≤ 30 KB gzipped |
| A6 | APPLIED | Verification matrix — Executor column added per row |
| A7 | APPLIED | Rollback step 0 — cosa-voice ask_yes_no before auto-revert |
| A8 | APPLIED | AC7 + Verification matrix Phase 4 smoke row — Playwright `--autoplay-policy=no-user-gesture-required` flag required |
| A9 | APPLIED | Idempotency marker EXECUTOR: AI subsection in slot table |
| A10 | APPLIED | Q2 — server-replay verification + escalation procedure spelled out |
| A11 | APPLIED | Q5 — file:line cites for Phase 2 AuthManager + Phase 3 ConnectionStateMachine |

### REUSE pre-pass — 20 rows + 4 design concerns (all closed)

20 verdicts captured + persisted as a "Prior art referenced" subsection at end of design doc per PIP §4. 4 Design Concerns folded into D-A / D-B / D-E / D-F decisions above.

### Convergence re-grep results (post-fix, per PIP §7)

| Grep target | Pre-fix hits | Post-fix hits | Status |
|---|---|---|---|
| `TBD\|confirm during impl\|decide at impl time\|tbd` | 11 | 3 (all benign — PIP slot meta-refs + Phase-5-deferred URL with verification gate) | ✅ no new structural hits |
| `Open sub-question` | 0 | 0 | ✅ clean |
| `Manual\|manual` | 0 | 2 (both describe legacy "Manual Int16→Float32 conversion" math, not "manual test") | ✅ no test-ownership violations |
| `EXECUTOR: HUMAN` | 0 | 0 | ✅ clean |
| `^- \[ \] [^E]` | 0 | 0 | ✅ clean |

### Termination per PIP §10

✅ Quality criterion met: zero new structural findings introduced by the Resolution Loop fixes. Termination cleanly.

### Idempotency marker per PIP §12

Last-reviewed line at end of design doc reads: `**Last reviewed**: 2026-05-04 (REUSE pre-pass + Pass 1 Fitness + Pass 2 Adversarial all closed; user ratified D-A through D-G + Q1-Q7 + Q12 + 21 minor wording/coverage fixes via Resolution Loop)`. Commit hash will be appended per Pass 2 A9 + PIP §12 immediately after user final-go-ahead + Phase 4 implementation commit lands.

### Awaiting user final-go-ahead

Per Q11 amendment step 11 (canonical PIP `plan-review.md` per-phase sequence): user approves the post-review design doc → AI opens `90-execution-log.md` Phase 4 section (status: in-progress) → AI implements per spec → AI runs verification matrix → AI files commit hash → AI closes Phase 4 section.

**Phase 4 implementation does not begin until user types final go-ahead in next turn.**
