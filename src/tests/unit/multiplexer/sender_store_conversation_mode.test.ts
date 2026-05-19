// Multiplexer Phase 6c Node D — SenderStore conversation-mode reducer tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/sender_store_conversation_mode.test.ts`.
//
// AC-D3 target: ≥12 cases per Tiberius Path III ratification (2026-05-19).
// The Path III bridge means the reducer listens for BOTH `conversation_mode_changed`
// (post-rename target) and `speakerphone_changed` (current server-emitted),
// reading `payload.active ?? payload.on` for the mode flag. These tests cover
// both type strings × both field names + the single-pin dual-emission
// invariant + defensive paths.
//
// Path δ scope (Rick 2026-05-19): mic_monopoly extraction tests (originally
// AC-D3 items #5/#6 conditional on Recon-D2) are NOT in this file. See
// TODO.md "Phase 6c follow-on: mic-monopoly indicator" — when the deferred
// design lands, this file gains cases #13/#14 for mic_monopoly extraction.
//
// File location note: placed alongside the existing `sender_store.test.ts`
// (NOT in a `stores/` subdir as the execution plan literal suggested) to
// match the actual existing test layout. If a Phase 6c+ follow-on creates
// `stores/` subdirectory, both files should migrate together.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import { createSenderStore } from "../../../fastapi_app/static/js/multiplexer/stores/SenderStore";
import type {
  LupinEvent,
  StoreSendersChangedPayload,
} from "../../../fastapi_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setup() {
  const bus    = createEventBusForTesting();
  const events : LupinEvent<StoreSendersChangedPayload>[] = [];
  bus.on<StoreSendersChangedPayload>("store_senders_changed", (e) => events.push(e));
  const store  = createSenderStore({ bus, nowFn: () => 1_000_000 });
  return { bus, store, events };
}

function emitRegular(
  bus       : ReturnType<typeof createEventBusForTesting>,
  sender_id : string,
  timestamp = "2026-05-04T10:00:00Z",
): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { type: "task", sender_id, timestamp } },
    source  : "test",
    ts      : 0,
  });
}

function emitConvMode(
  bus       : ReturnType<typeof createEventBusForTesting>,
  type      : "conversation_mode_changed" | "speakerphone_changed",
  sender_id : string,
  payload   : { active?: boolean; on?: boolean; session_id?: string; displaced?: boolean; displaced_by?: string },
  timestamp = "2026-05-04T10:05:00Z",
): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { type, sender_id, timestamp, payload } },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// 1-2 : Type-name bridge — both strings activate the conversation-mode reducer
// ===========================================================================

test("conversation_mode_changed with payload.active=true sets conversation_mode_active on existing sender", () => {
  const { bus, store } = setup();
  emitRegular(bus, "alice@x");
  const before = store.get("alice@x")!;
  assert.equal(before.conversation_mode_active, false, "field starts at false on regular-notification record creation");

  emitConvMode(bus, "conversation_mode_changed", "alice@x", { active: true });
  assert.equal(store.get("alice@x")!.conversation_mode_active, true);
});

test("speakerphone_changed with payload.on=true sets conversation_mode_active (current-wire path)", () => {
  const { bus, store } = setup();
  emitRegular(bus, "bob@x");

  emitConvMode(bus, "speakerphone_changed", "bob@x", { on: true });
  assert.equal(store.get("bob@x")!.conversation_mode_active, true);
});

// ===========================================================================
// 3-4 : Field-name bridge — payload.active and payload.on are both honored
// regardless of the wrapping notification.type string
// ===========================================================================

test("conversation_mode_changed with cross-name payload.on=true still activates (bridge accepts either field)", () => {
  const { bus, store } = setup();
  emitRegular(bus, "carol@x");
  emitConvMode(bus, "conversation_mode_changed", "carol@x", { on: true });
  assert.equal(store.get("carol@x")!.conversation_mode_active, true);
});

test("speakerphone_changed with cross-name payload.active=true still activates (bridge accepts either field)", () => {
  const { bus, store } = setup();
  emitRegular(bus, "dave@x");
  emitConvMode(bus, "speakerphone_changed", "dave@x", { active: true });
  assert.equal(store.get("dave@x")!.conversation_mode_active, true);
});

// ===========================================================================
// 5-6 : Deactivation under both field names
// ===========================================================================

test("conversation_mode_changed with payload.active=false clears conversation_mode_active", () => {
  const { bus, store } = setup();
  emitRegular(bus, "eve@x");
  emitConvMode(bus, "conversation_mode_changed", "eve@x", { active: true });
  emitConvMode(bus, "conversation_mode_changed", "eve@x", { active: false });
  assert.equal(store.get("eve@x")!.conversation_mode_active, false);
});

test("speakerphone_changed with payload.on=false clears conversation_mode_active", () => {
  const { bus, store } = setup();
  emitRegular(bus, "frank@x");
  emitConvMode(bus, "speakerphone_changed", "frank@x", { on: true });
  emitConvMode(bus, "speakerphone_changed", "frank@x", { on: false });
  assert.equal(store.get("frank@x")!.conversation_mode_active, false);
});

// ===========================================================================
// 7 : Single-pin invariant via dual-emission
//   When B activates while A is already pinned:
//     - A's record is cleared FIRST (emits one "updated" for A)
//     - B's record is set SECOND  (emits one "updated" for B)
//   The order matters because downstream consumers (e.g. the renderer) see
//   the intermediate "no sender is pinned" state during the swap.
// ===========================================================================

test("dual-emission single-pin: activating B when A is pinned clears A FIRST then sets B SECOND", () => {
  const { bus, store, events } = setup();
  emitRegular(bus, "a@x");
  emitRegular(bus, "b@x");
  emitConvMode(bus, "conversation_mode_changed", "a@x", { active: true });
  const before = events.length;

  emitConvMode(bus, "conversation_mode_changed", "b@x", { active: true });

  // Two "updated" emissions in order: A cleared, then B set.
  const swap = events.slice(before).filter(e => e.payload.changeKind === "updated");
  assert.equal(swap.length, 2, "expected exactly two emissions for the pin swap");
  assert.equal(swap[0]!.payload.sender_id, "a@x", "A's clear must emit FIRST");
  assert.equal(swap[1]!.payload.sender_id, "b@x", "B's set must emit SECOND");

  // Final store state: only B is pinned.
  assert.equal(store.get("a@x")!.conversation_mode_active, false);
  assert.equal(store.get("b@x")!.conversation_mode_active, true);
});

// ===========================================================================
// 8 : Re-activation of the same sender does NOT re-emit
//   The reducer guards against redundant state churn so consumers don't
//   re-paint on no-op events.
// ===========================================================================

test("activating an already-active sender does NOT emit a second store_senders_changed", () => {
  const { bus, events } = setup();
  emitRegular(bus, "g@x");
  emitConvMode(bus, "conversation_mode_changed", "g@x", { active: true });
  const after_first = events.length;

  emitConvMode(bus, "conversation_mode_changed", "g@x", { active: true });
  assert.equal(events.length, after_first, "second activate should be a no-op (state unchanged)");
});

// ===========================================================================
// 9 : Deactivating an already-inactive sender is a no-op (no emission)
// ===========================================================================

test("deactivating an already-inactive sender emits no event", () => {
  const { bus, events } = setup();
  emitRegular(bus, "h@x");
  const before = events.length;

  emitConvMode(bus, "conversation_mode_changed", "h@x", { active: false });
  assert.equal(events.length, before, "deactivate-on-inactive is a no-op");
});

// ===========================================================================
// 10-11 : Conversation-mode events do NOT bump unread or last_active
//   (state-update notifications, not user-facing arrivals — same contract as
//   voice_persona_assigned / voice_persona_released)
// ===========================================================================

test("conversation-mode event does NOT bump unread_count", () => {
  const { bus, store } = setup();
  emitRegular(bus, "i@x");
  const before_unread = store.get("i@x")!.unread_count;
  emitConvMode(bus, "conversation_mode_changed", "i@x", { active: true });
  assert.equal(store.get("i@x")!.unread_count, before_unread, "state-update events must not bump unread");
});

test("conversation-mode event does NOT bump last_active_ts", () => {
  const { bus, store } = setup();
  emitRegular(bus, "j@x", "2026-05-04T10:00:00Z");
  const before_ts = store.get("j@x")!.last_active_ts;
  emitConvMode(bus, "conversation_mode_changed", "j@x", { active: true }, "2026-05-04T11:00:00Z");
  assert.equal(store.get("j@x")!.last_active_ts, before_ts, "state-update events must not bump last_active_ts");
});

// ===========================================================================
// 12 : Conversation-mode event creates a new SenderRecord if none exists
//   (parallels the voice_persona_assigned auto-create pattern; unread_count
//   stays at 0 because conv-mode events are state-update, not arrivals)
// ===========================================================================

test("conv-mode event on unknown sender creates a record with unread_count=0 and conversation_mode_active=true", () => {
  const { bus, store } = setup();
  assert.equal(store.get("k@x"), undefined, "precondition: sender unknown");

  emitConvMode(bus, "conversation_mode_changed", "k@x", { active: true });
  const rec = store.get("k@x");
  assert.ok(rec, "record must be created");
  assert.equal(rec!.unread_count, 0, "conv-mode events do not bump unread");
  assert.equal(rec!.conversation_mode_active, true);
});

// ===========================================================================
// 13 : Defensive — missing payload is a no-op
// ===========================================================================

test("conversation_mode_changed with missing payload does not crash or emit", () => {
  const { bus, store, events } = setup();
  emitRegular(bus, "l@x");
  const before = events.length;

  // Emit with explicit absent payload (payload property omitted entirely).
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { type: "conversation_mode_changed", sender_id: "l@x", timestamp: "2026-05-04T10:05:00Z" } },
    source  : "test",
    ts      : 0,
  });

  // The reducer treats missing payload as active=false (`undefined ?? undefined === true` is false).
  // Record's conversation_mode_active is already false from setup, so no state change → no emission.
  assert.equal(events.length, before, "no emission when payload missing and state already false");
  assert.equal(store.get("l@x")!.conversation_mode_active, false);
});

// ===========================================================================
// 14 : Nullish-coalesce precedence — payload.active wins when both fields set
//   This guards against future server confusion where both fields are populated
//   (e.g. during a partial rename rollout); active is the post-rename canonical.
// ===========================================================================

test("when both payload.active and payload.on are set, payload.active takes precedence", () => {
  const { bus, store } = setup();
  emitRegular(bus, "m@x");
  emitConvMode(bus, "conversation_mode_changed", "m@x", { active: true, on: false });
  assert.equal(store.get("m@x")!.conversation_mode_active, true, "active=true wins over on=false");

  // Inverse: active=false beats on=true.
  emitConvMode(bus, "conversation_mode_changed", "m@x", { active: false, on: true });
  assert.equal(store.get("m@x")!.conversation_mode_active, false, "active=false wins over on=true");
});
