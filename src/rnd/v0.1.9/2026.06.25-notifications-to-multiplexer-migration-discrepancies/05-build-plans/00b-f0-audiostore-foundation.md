# F0 — Shared AudioStore / TTS-Queue Foundation — Build Plan

**Date**: 2026-06-27
**Status**: 🟡 **REVISED per cascade-review (APPROVE-WITH-CHANGES — Cheech 🌿 + María 🌸)** — 8 conditions folded in by Krishna 🦚 (reviser), 2026-06-27; pending condition-verification re-review. Keystone shared dependency; reviewed FIRST, before Plan 01.
**Author**: Mr. Radio 🦉 (for Rick)
**Foundation for**: Plans **01** (B4 active-TTS gate), **02** (Action-Required live countdown), **03** (TTS-Queue multi-item restore), **05** (Q&A submit→answer→playing correlation). See `00-plans-index.md` §F0.
**Source audit refs**: `00-plans-index.md` §"F0 — Shared AudioStore foundation"; Plan `01-cc-session-B1-B5.md` §8 OQ-1 (load-bearing).
**Decision-of-record refs**: this plan EXISTS to surface the F0 seam decision for Rick's ratification — it is the artifact OQ-1 asked reviewers to scope. Cross-cutting mandates 1–7 of `00-plans-index.md` inherited, not restated.

---

## 0. Ratified decisions & switchover-critical finding (2026-06-27, Rick walkthrough)

**Q1 — F0 seam (OQ-F0.1): RATIFIED → Dedicated `TtsQueueStore`.** The notification-level item-queue lives in its own store; `AudioStore` stays a pure PCM/XState machine and is **id-blind**. The active notification id is **client-side**, owned and sourced by `TtsQueueStore` at speak-initiation — **NOT** emitted by `AudioStore` (this corrects the earlier "AudioStore emits the active id" framing, now disproven by the **OQ-F0.3 ROOT FINDING** below). Boot correlates PCM playback state (`AudioStore`) with item identity (`TtsQueueStore`). (§8 OQ-F0.1 recommendation accepted; the dedicated-store ruling is unchanged — only the active-id *source* is corrected.)

**🔴 SWITCHOVER-CRITICAL FINDING — audible playback is a HARD blocker.** Rick confirmed (2026-06-27): *"TTS rendering of notifications sent via the MCP server arrive at the browser client and are rendered via TTS as spoken audio."* The cosa-voice/MCP voice Rick hears is rendered **by the browser notifications client's in-browser PCM player** (`notifications.js` `initPCMAudioContext`/`pcmNextStartTime`, `/ws/audio/{sessionId}`). The multiplexer wires the same `/ws/audio` transport (`boot.ts:547`) but `AudioStore` is **decode-only** — playback scheduling is deferred to the unbuilt "Phase-6 TTSEngine" (`AudioStore.ts:21-25`). **Therefore switching to the multiplexer in its current state would SILENCE Rick's spoken notifications.** Audible playback is now a **mandatory member of the minimum-viable switchover subset**, not a deferred nicety.

**Q2 — substrate (OQ-F0.2): "leave untouched" OVERTAKEN; substrate REVISED to the Web-Audio PCM scheduler (NOT SequentialAudioManager).** Audible playback is now switchover-mandatory → a **separate, mandatory sibling lane** (the Phase-6 TTS-playback plan), NOT folded into this F0 queue-store plan. **Substrate finding (2026-06-27, Rick asked "what's recyclable?"):**
- ✅ **THE template = `notifications.js:playPCMChunk` (4580-4674) + `initPCMAudioContext` (4570)** — the proven Web Audio API gapless 24kHz scheduler Rick actually hears: PCM16→Float32→`createBuffer(1,n,24000)` → `createBufferSource` → `connect(destination)` → `source.start(Math.max(pcmNextStartTime, currentTime))`, advancing `pcmNextStartTime += buffer.duration`; pause/resume = `pcmAudioContext.suspend()/resume()` (17206/17244); `source.onended` → completion.
- ✅ **DECODE HALF ALREADY DONE in the mux** — `audio/pcm-decoder.ts:pcm16ToAudioBuffer` already performs the identical Int16→Float32→createBuffer conversion (legacy 4614-4625). Phase-6 = port the **scheduling/output stage only** (~40 lines: createBufferSource + gapless scheduling + onended + source tracking) onto AudioStore's existing decoded-AudioBuffer path.
- ⚠️ **`SequentialAudioManager.ts` is the SUPERSEDED approach, NOT the substrate.** It is the TS port of `sequential-audio-manager.js` — the HTMLAudioElement-per-chunk player the legacy comment (`notifications.js:4567`) explicitly says the Web-Audio PCM path *"replaces (choppy sequential playback)."* **Disposition (P2-1): PREFER DELETE the file outright** (superseded + off the boot path — cleanest, moots all Firefox residue); if stripping instead, remove the FULL detection machinery — `:69`/`:123`/`:29` as well as `:99`/`:124`/`:197` (María executor note; see §3 Targets row + §8). The Chrome-only mandate permits ZERO Firefox detection, with **no "keep as reference" exception**. The Phase-6 engine follows the `playPCMChunk` Web-Audio path, which aligns with AudioStore's existing decode + gapless quality. (Resolves the earlier "adopt SequentialAudioManager" framing — the cascade review confirms substrate choice.)

Net: the Phase-6 lane is **port-the-scheduler**, not build-a-core — meaningfully smaller than feared. Coordinate with the `312ba8ab` (JS→TS mux migration) owner on AudioStore-area edits.

**Q3 — `queueLength()` naming (OQ-F0.4): ✅ DECIDED (Rick, 2026-06-27) → `burstLength()`.** The PCM counter `AudioStore.queueLength()` (returns chunks-in-current-burst) is renamed `burstLength()`; `queueLength()`/`itemQueueLength()` is reserved for the new `TtsQueueStore`. Applied in this revision (see §3, §5 F0-b, §8 OQ-F0.4).

**🔵 OQ-F0.3 ROOT FINDING — the active id is inherently CLIENT-SIDE (sourced + verified, cascade-review 2026-06-27).** The notification `id_hash` is **provably absent from the server `/ws/audio` path**: the TTS request carries only `{session_id, text}` (`speech.py:424-425`); PCM frames are raw bytes (`speech.py:814`, `:1065`); the status/complete/error envelopes carry **no id**. There is no server seam to thread it through — the id can only be known client-side. The mux today has **no client-side TTS-initiation seam**: `AudioStore` is a passive server-push consumer (`boot.ts:547`), and `render/TtsChromeRenderer.ts:25-27` self-documents that `AudioStore` does **NOT** expose `currentNotificationIdHash()`. Legacy sources the id at **`playNotificationAudio` (`notifications.js:15007`)** — reading it off the `/ws/queue` notification object *before* calling `playTTS`. **The exact client-side field is `Notification.id_hash`** (REQUIRED, non-optional string — `shared/types.ts:334`), populated from the server WS frame `routers/notifications.py:859` (`"id_hash": db_notification_id`; the `:939` comment pins the invariant "WS frame `id_hash` == persisted row UUID"); the mux already keys on it (`NotificationStore.ts:420` `byId.set(n.id_hash, …)`). **Consequences:** (a) F0-a's active-id is re-homed to `TtsQueueStore.current()` (NOT `AudioStore`), published on the `store_tts_queue_changed` event; (b) F0-d is **net-new build** — it ports the `playNotificationAudio` speak-initiation seam (reading `Notification.id_hash`), not merely threading an existing field. (Resolves §8 OQ-F0.3.)

**🔗 CROSS-PLAN OWNERSHIP (00b ↔ 00c) — single owner of the "speak this notification" flow.** To prevent a 00b↔00c collision: **00b's `TtsQueueStore` is the SOLE owner** of selection + id-capture (reading `Notification.id_hash`) + invoking the `/api` TTS request. **00c's Phase-6 playback engine CONSUMES `TtsQueueStore.current()`** for renderer correlation — it is **id-blind-but-correlated** and never sources or captures the id itself. One flow, one owner; 00c subscribes, 00b drives.

**Revised switchover-critical set** (the minimum to retire the legacy client):
1. **F0** — `TtsQueueStore` + active-id (this plan; visual-control data).
2. **Phase-6 TTS-playback engine** — NEW mandatory sibling plan `00c` (port the Web-Audio `playPCMChunk` scheduler so the mux audibly speaks — **NOT** `SequentialAudioManager`, per §0 Q2; consumes `TtsQueueStore.current()` per the cross-plan ownership note above). *Without this, switchover is impossible.*
3. **Plan 01** — CC Notifications accordion #5.
4. **Fleet Status #6 + Task List #7** — live-render verification.

---

## 1. Goal & parity target

Extend the multiplexer audio layer so it exposes the two facts four downstream plans independently need but no current store provides: **(a)** the **notification `id_hash` currently being spoken** (active-item identity), and **(b)** a **multi-item, notification-level TTS queue** model (`enqueue / advance / removeById / clear / current / pending`). "Done" = a single foundational lane lands an audio-layer extension with 100% L/B/F unit coverage, emitting an active-id signal on the EventBus and exposing an item-queue API, with zero DOM/visual surface of its own — its parity is proven indirectly when plans 01/02/03/05 consume it. This plan is **logic-level**; it has no Oracle tier of its own (consumers carry the visual tiers).

## 2. Scope

**IN**:
- **F0-a — active-item identity.** A signal carrying the `id_hash` (and minimally the bucket/group context) of the notification whose TTS is currently being spoken, **owned by `TtsQueueStore` and exposed via `current()`** (NOT by `AudioStore`, which stays id-blind per the §0 OQ-F0.3 root finding), **published on the `store_tts_queue_changed` event**. The active id updates as items are selected/advanced/cleared, so a renderer can gate exactly one bubble (Plan 01 B4) and one countdown (Plan 02).
- **F0-b — notification-level item queue.** A queue model over *notification items* (not PCM chunks): `enqueue(item)`, `advance()`, `removeById(id_hash)`, `clear()`, `current()`, `pending()` — **ported from the legacy client-side TTS item-queue (`notifications.js`: `ttsQueue` decl `:308`, enqueue `:16519`, `activateNextTTS()` `:16549`, `.shift()` advance `:16564`; id-keyed, strict FIFO, focus-mode auto-play — see §3 for the full anchor set)**, built via the established `createXStore` factory + `StoreSet` barrel (REUSE — see §3). This is the substrate Plan 03 (TTS-Queue) renders and mutates.
- **F0-c — types + EventBus contract.** A dedicated `store_tts_queue_changed` event payload in `multiplexer/shared/types.ts` (`{ activeNotificationId, pending[] }`), wired so consumers subscribe rather than poll. The active id rides **this** event — **NOT** `StoreAudioStateChangePayload` (AudioStore is id-blind, OQ-F0.3).
- **F0-d — speak-initiation seam (NET-NEW BUILD) + boot wiring.** **Build** the client-side speak-initiation seam by porting legacy `playNotificationAudio` (`notifications.js:15007`): on a "speak notification X" gesture/auto-play, read `X.id_hash` (the REQUIRED `Notification.id_hash` field, `shared/types.ts:334`) off the `/ws/queue` notification object and set `TtsQueueStore.current()` **before** the `/ws/audio` TTS request fires. This is **net-new code**, not a re-home of an existing thread (OQ-F0.3 proves nothing to thread server-side) — sized into the work breakdown (§5 F0-d) + estimate (§9). Boot mounts `TtsQueueStore` and correlates it with `AudioStore` PCM state. (Unit coverage is its own bucket, F0-e.)

**OUT**:
- Actual audible-playback scheduling — **owned by the mandatory sibling Phase-6 TTS-playback plan (`00c`)**, NOT this plan. (§0 makes audible playback switchover-mandatory; `SequentialAudioManager` is the superseded approach, not the substrate — see §0 Q2. 00c consumes `TtsQueueStore.current()` per the §0 cross-plan ownership note.)
- Drag-reorder of the pending queue — gated by Rick's design Q **e′** (legacy is strict FIFO, no drag); F0-b ships FIFO `advance()` semantics, leaving reorder as a Plan-03 fast-follow only if (e′) rules for it.
- Any per-bubble DOM, CSS, or corner-control render — that is Plan 01 B4 / Plan 03, consuming this foundation.

## 3. Source anchors

All paths relative to repo root.

### Current state (what exists today)
| Element | Anchor | What it does / lacks |
|---|---|---|
| AudioStore (coarse state) | `static/js/multiplexer/stores/AudioStore.ts:114-130` (interface), `:151-350` (impl) | XState v5 actor; `state()` ∈ {idle,decoding,playing,paused,ended,error}; `pause/resume/skip/stop`. **No notification identity.** |
| Burst counter (NOT items) | `AudioStore.ts:163-165,216-218` `chunksInBurst` / `queueLength()` | Counts PCM chunk *arrivals* in one burst — **not** notification items. ✅ **OQ-F0.4 DECIDED (Rick, 2026-06-27): rename `queueLength()`→`burstLength()`** (it returns chunks-in-current-burst); `queueLength()`/`itemQueueLength()` reserved for `TtsQueueStore`. |
| State-change emit path | `AudioStore.ts:187-198` `actor.subscribe(...)` → `store_audio_state_change {state, prev}` | Stays **id-blind** — F0-a does NOT extend this with an active id (the id lives on `TtsQueueStore`/`store_tts_queue_changed`, OQ-F0.3). |
| State payload type | `multiplexer/shared/types.ts` → `StoreAudioStateChangePayload` (`{state, prev, reason?}`) | **NOT extended** with `activeNotificationId` — F0-c adds a *separate* `store_tts_queue_changed` payload for the active id + item queue (OQ-F0.3). |
| Binary handler wiring | `AudioStore.ts:170,207-209` `binaryHandler` (`audioStoreBinaryHandler`); `boot.ts` `transports.audio.start(sessionId, audioStore.binaryHandler)` | The chunk-ingress seam carries raw bytes with **no notification id and never will** — the id is absent from `/ws/audio` server-side (OQ-F0.3). The active id is set client-side at speak-initiation (F0-d), not derived here. |
| Server `/ws/audio` TTS request (id-absent) | `src/cosa/rest/routers/speech.py:424-425` (request = `{session_id, text}`); raw PCM `:814`, `:1065` | **Proves the id is NOT on the audio path** — no field to thread; the id must be captured client-side (OQ-F0.3). |
| **Client-side id source — "/ws/queue id-source gate"** | `multiplexer/shared/types.ts:333-334` `Notification.id_hash` (REQUIRED, non-optional); server emits at `src/cosa/rest/routers/notifications.py:859` (`"id_hash": db_notification_id`; invariant pinned `:939` "WS frame `id_hash` == persisted row UUID"); mux keys on it `stores/NotificationStore.ts:420` (`byId.set(n.id_hash, …)`) | **The exact field F0-d reads** off the `/ws/queue` notification object at speak-initiation to set `TtsQueueStore.current()`. Cited, not asserted. |
| SequentialAudioManager (superseded, Firefox-tainted) | `static/js/multiplexer/audio/SequentialAudioManager.ts:86-335` | TS port of the HTMLAudioElement-per-chunk player (umbrella `312ba8ab`); **Blob-chunk-level + id-blind** → **NOT a candidate** for F0-b's notification-item queue (REUSE-1 rejection — the legacy `ttsQueue` is the real source). Also carries a ported `isFirefox` branch (`:99`/`:124`/`:197`, plus `:69`/`:123`/`:29` machinery) — violates the Chrome-only mandate. **Action (P2-1): PREFER DELETE the file; if stripping, remove the FULL machinery** (see Targets row) — no "keep as reference" exception. |
| Legacy active-item driver + speak-initiation seam (F0-d port source) | `static/js/notifications.js:15007` `playNotificationAudio` (sets `currentNotificationId` from the `/ws/queue` notification object, then `playTTS`); `:14903-14971` (active-TTS driver), `:14696`/`:13869` (per-msg render) | **F0-d ports this** — where legacy learns the active id client-side and keys `is-playing-current`. The net-new speak-initiation seam. |
| **Legacy client-side TTS item-queue (REUSE-1 port source for F0-a + F0-b)** | `static/js/notifications.js`: `this.ttsQueue` decl `:308` (item shape `{id, type, notification, ttsText, addedAt}`); enqueue push `:16519`; `activateNextTTS()` def `:16549`; `.shift()` advance `:16564`; `this.activeTTSItem` decl `:309` (set-on-advance `:16565`, guard `:16526`) | **The real notification-level item-queue F0-b ports** — id-keyed, strict-FIFO `enqueue/advance`. **`this.activeTTSItem` is the legacy active-item field that maps 1:1 to `TtsQueueStore.current()` — the exact port source for F0-a's active-id.** **This** (not `SequentialAudioManager`) is F0-a/b's source of truth. |

### Targets (add/edit)
| File | Action |
|---|---|
| **NEW** `multiplexer/stores/TtsQueueStore.ts` | **F0-a + F0-b** — owns the item queue (`enqueue/advance/removeById/clear/current/pending`) AND the active id (`current()`); emits `store_tts_queue_changed`. Built via the established `createXStore` factory (REUSE-2). Ratified (OQ-F0.1) — **no longer conditional**. |
| `multiplexer/stores/index.ts` | Register `TtsQueueStore` in the `StoreSet` barrel + `createStores()` factory (`:64-135`), following the established pattern (REUSE-2). |
| `multiplexer/stores/AudioStore.ts` | **Unchanged for identity** — stays id-blind (OQ-F0.3). Apply the ✅-decided `queueLength()`→`burstLength()` rename (OQ-F0.4); otherwise touched only if F0-d's boot correlation needs a read-only state hook. |
| `multiplexer/shared/types.ts` | F0-c `store_tts_queue_changed` payload type (convergence file — manager-serial-merge). |
| `multiplexer/boot.ts` | F0-d: mount `TtsQueueStore`; wire the ported speak-initiation seam (set `current()` from the `/ws/queue` `Notification.id_hash`); correlate with `AudioStore` PCM state (convergence file). |
| `multiplexer/audio/SequentialAudioManager.ts` | **P2-1 — PREFER DELETE the file** (superseded + off the boot path; cleanest, moots all Firefox residue). **If stripping instead**, the impl must remove the FULL Firefox-detection machinery — not only the branch `:99`/`:124`/`:197`, but ALSO `:69` (the `userAgent` option), `:123` (the `ua` derivation), and `:29` (the comment) — else dead detection code lingers (María steward executor guidance). Chrome-only mandate, no "keep as reference" exception (§0 Q2). Confirm parked/live status with the `312ba8ab` owner before deleting. |

## 4. Dependencies & prerequisites

- **No upstream plan prereqs** — F0 is the root of the dependency DAG; it is built/reviewed FIRST.
- **Downstream consumers** (must NOT start their dependent buckets until F0 lands): Plan 01 B4, Plan 02 countdown, Plan 03 queue, Plan 05 correlation.
- **Convergence files** (manager-serial-merge — mandate 5): `shared/types.ts`, `boot.ts`, store barrel/index. No parallel edits.
- **Coordination**: confirm with Tiberius's crew whether any in-flight audio/TTS work touches `AudioStore.ts` / `SequentialAudioManager.ts` before opening the F0 lane (mandate 6). The umbrella `312ba8ab` (JS→TS mux migration) owns SequentialAudioManager — confirm its status (live frontier vs parked) before stripping its Firefox branch or deleting it (P2-1).
- **Cross-plan ownership ("00b↔00c speak-flow ownership")**: 00b's `TtsQueueStore` is the SOLE owner of the "speak this notification" flow — selection + id-capture (`Notification.id_hash`) + invoking the TTS request. The sibling Phase-6 plan (`00c`) **consumes** `TtsQueueStore.current()` (id-blind-but-correlated) and never sources/captures the id. Prevents a 00b↔00c collision over the speak flow.
- **No new endpoints / INI keys anticipated** — but note (correcting an earlier draft assumption): the active id is **NOT** already on the audio path. It is **absent server-side** (`/ws/audio` carries no id, OQ-F0.3) and must be **sourced client-side** at speak-initiation from `Notification.id_hash` (the "/ws/queue id-source gate"). F0-d **builds** that capture — it does not merely "carry" an existing field.

## 5. Work breakdown

Each bucket: **what · files · ACs · gate**.

### F0-a — Active-notification-id signal
**What**: Track and expose the `id_hash` of the notification currently being spoken as **`TtsQueueStore.current()`** (`string | null`), published on the **`store_tts_queue_changed`** event. Set at speak-initiation (F0-d seam), advanced/cleared on `advance`/`clear`. **Port source**: legacy `this.activeTTSItem` (`notifications.js:309`, set-on-advance `:16565`) — the active-item field that maps 1:1 to `current()`. **`AudioStore` is NOT touched for identity** — it stays id-blind (OQ-F0.3).
**Files**: `TtsQueueStore.ts` (NEW — owns `current()` + emits `store_tts_queue_changed`), `shared/types.ts` (payload). **Not** `AudioStore.ts`.
**ACs**:
- Functional: when notification X is selected for TTS, `TtsQueueStore.current() === X.id_hash` and a `store_tts_queue_changed` event fires; on `advance`/`clear`, `current()` becomes the next item's id or `null`. Exactly one active id at a time.
- Structural: the active id is owned by `TtsQueueStore` (single source of truth), emitted on `store_tts_queue_changed`; `AudioStore`'s `StoreAudioStateChangePayload` is untouched (no `activeNotificationId` added).
- Negative: with no active item, `current()` is `null` and the event carries `activeNotificationId: null`, never a stale id.

### F0-b — Notification-level item queue
**What**: A FIFO queue over notification items with `enqueue/advance/removeById/clear/current/pending`, **ported from the legacy client-side TTS item-queue (`notifications.js`: `ttsQueue` decl `:308` (shape `{id,type,notification,ttsText,addedAt}`), enqueue `:16519`, `activateNextTTS()` `:16549`, `.shift()` advance `:16564`, active-item `this.activeTTSItem` `:309`→`current()` — id-keyed, strict FIFO, focus-mode auto-play)** — **NOT** from `SequentialAudioManager` (Blob-chunk-level, id-blind; REUSE-1 rejection). Distinct from `chunksInBurst` (PCM-level). Built via the established `createXStore` factory + registered in the `StoreSet` barrel (`stores/index.ts:64-135`; REUSE-2).
**Files**: `TtsQueueStore.ts` (NEW, per ratified OQ-F0.1); `stores/index.ts` (barrel + `createStores` registration); `shared/types.ts` (`store_tts_queue_changed`).
**ACs**:
- Functional: `enqueue` appends; `advance` pops the head and makes the next head `current()`; `removeById` excises any pending item by `id_hash` (and resyncs if it was current); `clear` empties; `pending()` returns the tail in FIFO order; `current()` === F0-a active id.
- Structural: queue is notification-item-typed, not `Blob`/chunk-typed; built via `createXStore` + barrel registration (REUSE-2). ✅ **OQ-F0.4 DECIDED**: the PCM counter is renamed `AudioStore.queueLength()`→`burstLength()`; `TtsQueueStore` exposes its own `itemQueueLength()` — no naming collision.
- Negative: `advance`/`removeById`/`clear` on an empty queue are safe no-ops; `removeById` of an absent id is a no-op.

### F0-c — Types + EventBus contract
**What**: Land the `store_tts_queue_changed` event payload consumers subscribe to: `{ activeNotificationId: string | null, pending: NotificationItem[] }`. The active id rides **this** event — `StoreAudioStateChangePayload` is **NOT** extended (AudioStore is id-blind, OQ-F0.3). The single-bubble gate (Plan 01 B4) and the multi-item queue render (Plan 03) both subscribe to `store_tts_queue_changed`.
**Files**: `shared/types.ts` (convergence).
**ACs**: types compile; EventBus generic-typed; no consumer reads store internals directly (subscribe-only).

### F0-d — Speak-initiation seam (NET-NEW BUILD) + boot wiring
**What**: **NET-NEW BUILD — port the client-side speak-initiation seam.** OQ-F0.3 proves the id is absent from `/ws/audio` server-side, so there is nothing to "thread" — the seam must be **built** client-side. Port legacy `playNotificationAudio` (`notifications.js:15007`): on a "speak notification X" gesture/auto-play, read **`X.id_hash`** — the REQUIRED `Notification.id_hash` field (`shared/types.ts:334`; the "/ws/queue id-source gate", cited not asserted) — off the `/ws/queue` notification object and call `TtsQueueStore.enqueue/advance` to set `current()` **before** the `/ws/audio` TTS request fires. **Cross-plan ownership ("00b↔00c speak-flow ownership"):** 00b's `TtsQueueStore` is the SOLE owner of selection + id-capture + invoking the TTS request; 00c's Phase-6 engine only *consumes* `current()` (id-blind-but-correlated). Boot mounts `TtsQueueStore` and correlates `current()` with `AudioStore`'s PCM playback state for renderer gating.
**Files**: `boot.ts` (mount + seam wiring, convergence); the speak-initiation call site (gesture/auto-play handlers). **Sizing: net-new build, NOT a field re-home** — the dominant code-volume bucket of F0 (see §9).
**ACs**: the active id observed at `TtsQueueStore.current()` matches the notification the user/system chose to speak, set *before* TTS audio begins; the `/ws/audio` binary path stays id-blind; AC9 `binaryHandler` Function.name invariant (`AudioStore.ts:126-127,207`) preserved (the handler is unchanged).

### F0-e — Tests (100% L/B/F)
**What**: Unit suite for F0-a..d, including the new `TtsQueueStore` and the ported speak-initiation seam.
**Files**: `multiplexer/stores/__tests__/TtsQueueStore.test.ts` (+ boot-seam coverage), mirroring the existing store test layout.
**ACs**: `c8 --100` **lines/branches/functions** on every F0-touched file (`TtsQueueStore.ts`, the boot seam, `shared/types.ts` additions, the `burstLength()` rename); injected stubs (`audioContextFactory`, `nowFn`, decoder fns already injectable) drive all transitions; queue edge cases (empty, absent-id, current-removed) + the speak-initiation id-capture covered. `# c8 ignore` only for genuinely-unreachable defensive arms with a same-line reason (mandate 1).

## 6. Test strategy & venue routing

- **:7999 (AI-discretionary)** — all of F0 is TS unit + `c8 --100`; no server state, no DOM. Inline import-chain check after edits. This entire plan executes on :7999.
- **:8000** — none for F0 itself; the *consumers* (01/02/03/05) carry E2E/visual on :8000. F0's correctness is fully unit-provable.
- **New fixtures**: a queue-state fixture (≥2 notification items, one active) + an active-id transition fixture.

## 7. Oracle & visual parity

**None for F0** — it has no DOM/CSS surface. The Layout-Parity Oracle tiers are exercised by the consuming plans (01 T1/T2, 02/03 their own). F0's "parity" is behavioral, proven by unit tests + downstream consumption. (Stated explicitly so reviewers don't expect golden captures here.)

## 8. Risks & open questions (for reviewers — these are the point of F0)

> **Reconcile note (2026-06-27, revised post-cascade-review):** **OQ-F0.1 (seam), OQ-F0.2 (substrate), OQ-F0.3 (active-id origin), and OQ-F0.4 (naming) are ALL RESOLVED** — F0.1 → dedicated `TtsQueueStore` (ratified §0); F0.2 → Web-Audio PCM scheduler in sibling Phase-6 plan `00c`, `SequentialAudioManager` superseded (P2-1: strip Firefox/delete); **F0.3 → the active id is inherently CLIENT-SIDE, sourced at the ported `playNotificationAudio` speak-initiation seam from `Notification.id_hash` (see §0 ROOT FINDING)**; **F0.4 → Rick confirmed `queueLength()`→`burstLength()` (2026-06-27)**. The pre-ratification conditional phrasing ("iff OQ-F0.1 lands…") has been **scrubbed** from §2/§3/§5. **No open items remain.** Do NOT re-litigate. (Bullets retained below for reviewer context, marked with their resolutions.)

- **OQ-F0.1 (seam — load-bearing): one store or two?** Does the item-queue (F0-b) live as an **extension of `AudioStore`** (single store, simplest wiring, but conflates PCM-stream state with notification-item state) or as a **dedicated `TtsQueueStore`** (clean separation, but a second store + boot mount + an AudioStore↔TtsQueueStore correlation for `current()`)? **✅ RATIFIED → dedicated `TtsQueueStore`** for the item queue. *(Note: the original recommendation had active-id emitted from `AudioStore`; OQ-F0.3 subsequently proved the id is client-side, so active-id is owned by `TtsQueueStore.current()` and `AudioStore` stays id-blind — see §0.)* The XState PCM machine stays pure; boot correlates the two.
- **OQ-F0.2 (substrate): ✅ RESOLVED — retire/strip `SequentialAudioManager`.** It is blob-chunk-level, id-blind, and not on the live boot path — **not** F0-b's substrate (REUSE-1 rejects it; the legacy `ttsQueue` is the real port source). The Phase-6 audible-playback substrate is the Web-Audio `playPCMChunk` scheduler in sibling plan `00c` (§0 Q2). **P2-1 disposition:** PREFER DELETE the file (superseded + off boot path); if stripping instead, remove the FULL Firefox machinery — `:99`/`:124`/`:197` AND `:69`/`:123`/`:29` (María executor note, §3 Targets row) — Chrome-only mandate, no "keep as reference" exception. (Confirm parked/live status with the `312ba8ab` owner before deleting.)
- **OQ-F0.3 (id source): ✅ RESOLVED — the active `id_hash` is inherently CLIENT-SIDE.** Proven absent from `/ws/audio` server-side (`speech.py:424-425` TTS request = `{session_id, text}`; raw PCM `:814`/`:1065`; no id in status/complete/error). The mux has no client-side TTS-initiation seam today (`boot.ts:547`; `TtsChromeRenderer.ts:25-27` self-documents the gap). F0-d **builds** the seam by porting legacy `playNotificationAudio` (`notifications.js:15007`), reading **`Notification.id_hash`** (the "/ws/queue id-source gate": REQUIRED field `shared/types.ts:334` ← server `routers/notifications.py:859`, invariant `:939`; mux keys on it `NotificationStore.ts:420`) before `playTTS`. The id sets `TtsQueueStore.current()`; `AudioStore` stays id-blind. See §0 ROOT FINDING.
- **OQ-F0.4 (`queueLength()` naming): ✅ DECIDED (Rick, 2026-06-27) → `burstLength()`.** The PCM counter `AudioStore.queueLength()` (returns chunks-in-current-burst) is renamed `burstLength()`; `queueLength()`/`itemQueueLength()` is reserved for `TtsQueueStore`. Applied in this revision — no pending marker.
- **Risk**: `shared/types.ts` + `boot.ts` are convergence files touched by nearly every plan — F0 edits them FIRST, so sequence F0's merge ahead of the consumers to avoid rebase churn.

## 9. Lane decomposition & estimate

| Lane | Buckets | Files (lane-owned vs convergence) | Rough size |
|---|---|---|---|
| **F0 (single foundational lane)** | F0-a..e | **`TtsQueueStore.ts` (NEW)**, `stores/index.ts`; `shared/types.ts`*, `boot.ts`*; `AudioStore.ts` (`burstLength()` rename); `SequentialAudioManager.ts` (strip Firefox/delete) | **M** — bumped from S–M: **F0-d is net-new build** (porting the client-side `playNotificationAudio` speak-initiation seam + `Notification.id_hash` capture — NOT a field re-home, OQ-F0.3), plus the new `TtsQueueStore` (factory + barrel) and its 100% L/B/F suite. Code volume — not just the seam decision — now drives the size. |

**Sequencing**: F0 lands **before** any of 01-B4 / 02-countdown / 03-queue / 05-correlation begins. It is the first artifact into cascaded review and the first lane to merge.

**Doc touchpoints** (mandate 7): on completion update `00-plans-index.md` §F0 (mark resolved + record the OQ-F0.1/F0.2/F0.3 rulings + the OQ-F0.4 `burstLength()` rename), Plan `01` §8 OQ-1 (resolved → point at the F0 seam + the `store_tts_queue_changed` event), and `src/docs/websocket-events.md` only if F0-c adds a new EventBus event that maps to a WS payload. Register `TtsQueueStore` in the `stores/index.ts` barrel. No `lupin-app.ini` keys anticipated.
