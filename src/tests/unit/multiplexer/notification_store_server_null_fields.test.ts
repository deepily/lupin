// Multiplexer — NotificationStore fed the server's REAL frame, where an unsupplied field is null, not absent.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_server_null_fields.test.ts`.
//
// Found 2026-09-10 by the slider E2E (ts-720cc046). normalize() copied any field `!== undefined`, so the
// server's nulls reached code that read through them, and EventBus swallowed each throw. Measured on the
// served pre-fix bundle by replaying this frame on the page bus, one misbehaving field per test below:
//
//   voice_persona: null    → the card shows, the notification is NOT spoken (null.voice_id in the intent emit)
//   prediction_hint: null  → the card is NOT shown, and neither is any later card from any sender, because
//                            the whole sender section re-render throws on null.confidence; speech is unaffected
//   timeout_seconds: null  → a response-required notification expires the moment it arrives
//   session_name: null     → a session_topic is forwarded with a null name
//
// The frame is fixtures/notification_queue_update_no_persona.json, built by NotificationItem.to_dict() and
// pinned to it by src/tests/unit/test_multiplexer_null_fields_fixture_matches_to_dict.py.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { createNotificationsListRenderer } from "../../../lupin_app/static/js/multiplexer/render";
import type {
  ListenerErrorPayload,
  SenderRecord,
  SessionTopicPayload,
  StoreNotificationsChangedPayload,
  StoreNotificationTtsIntentPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

interface ServerFrameFixture {
  frame         : { queue_name: string; value: number; notification: Record<string, unknown> };
  voice_persona : Record<string, unknown>;
}

const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/notification_queue_update_no_persona.json", import.meta.url), "utf8"),
) as ServerFrameFixture;

const FRAME_ID     = FIXTURE.frame.notification.id as string;
const FRAME_SENDER = FIXTURE.frame.notification.sender_id as string;

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  // Same marked + DOMPurify shim as notifications_list_renderer.test.ts.
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});

function frameWith(overrides: Record<string, unknown> = {}) {
  const frame = structuredClone(FIXTURE.frame);
  Object.assign(frame.notification, overrides);
  return frame;
}

function setup() {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  const store   = createNotificationStore({
    bus,
    storage,
    setTimeoutFn   : (() => 0) as (cb: () => void, ms: number) => unknown,
    clearTimeoutFn : (() => undefined) as (id: unknown) => void,
    nowFn          : () => 1_757_543_371_000,
  });
  const intents  : StoreNotificationTtsIntentPayload[] = [];
  const changes  : StoreNotificationsChangedPayload[]  = [];
  const thrown   : string[]                            = [];
  bus.on<StoreNotificationTtsIntentPayload>("store_notification_tts_intent", (e) => intents.push(e.payload));
  bus.on<StoreNotificationsChangedPayload>("store_notifications_changed", (e) => changes.push(e.payload));
  bus.on<ListenerErrorPayload>("listener_error", (e) => thrown.push(`${e.payload.originalEvent.type}: ${e.payload.error}`));
  const deliver = (frame: unknown) => bus.emit({ type: "notification_queue_update", payload: frame, source: "test", ts: 0 });
  return { bus, store, intents, changes, thrown, deliver };
}

function senderRecord(sender_id: string): SenderRecord {
  return { sender_id, display_name: sender_id, last_active_ts: 1_757_543_371_000, unread_count: 1, conversation_mode_active: false };
}

// ---------------------------------------------------------------------------
// voice_persona: null — speech
// ---------------------------------------------------------------------------

test("voice_persona null: the server's no-persona frame is carded AND spoken, in the default voice", () => {
  const { store, intents, changes, thrown, deliver } = setup();
  const n = FIXTURE.frame.notification;

  deliver(frameWith());

  assert.deepEqual(thrown, [], "a store listener threw on the server's frame");
  assert.deepEqual(store.list().map((x) => x.id_hash), [ FRAME_ID ], "the notification was not carded");
  assert.ok(changes.some((c) => c.changeKind === "added" && c.id_hash === FRAME_ID), "no store_notifications_changed added event");
  assert.deepEqual(intents, [ { id_hash: FRAME_ID, ttsText: n.message, priority: "high", action_required: false } ],
    "a persona-less high-priority notification must be spoken, with no voice_id");
});

test("control: the same frame WITH a real persona speaks in that persona's voice", () => {
  const { store, intents, thrown, deliver } = setup();
  const n = FIXTURE.frame.notification;

  deliver(frameWith({ voice_persona: FIXTURE.voice_persona }));

  assert.deepEqual(thrown, []);
  assert.deepEqual(intents, [ { id_hash: FRAME_ID, ttsText: n.message, priority: "high", action_required: false, voice_id: FIXTURE.voice_persona.voice_id } ]);
  assert.deepEqual(store.list()[0].voice_persona, FIXTURE.voice_persona);
});

// ---------------------------------------------------------------------------
// prediction_hint: null — the card, and every card after it
// ---------------------------------------------------------------------------

const FOLLOW_UP_SENDER = "claude.code@lupin.deepily.ai#followup1";

// The real store behind the real list renderer, mounted, with the server frame delivered and then a
// well-formed follow-up from another sender. The follow-up has no null prediction_hint, so it can only go
// missing if the section re-render is still throwing on the frame delivered before it.
function renderFrameThenFollowUp() {
  const { bus, store, deliver } = setup();
  const renderer = createNotificationsListRenderer({
    eventBus    : bus,
    stores      : {
      notifications : { list: () => store.list() },
      senders       : { list: () => [ senderRecord(FRAME_SENDER), senderRecord(FOLLOW_UP_SENDER) ] },
    },
    appTimezone : "UTC",
  });
  const root   = document.createElement("section");
  root.id      = "notifications-pane";
  const sCards = document.createElement("div");
  sCards.id    = "sender-cards-container";
  root.appendChild(sCards);
  renderer.mount(root);

  deliver(frameWith());
  const followUp = frameWith({ id: "follow-up-1", id_hash: "follow-up-1", sender_id: FOLLOW_UP_SENDER, voice_persona: FIXTURE.voice_persona });
  delete followUp.notification.prediction_hint;
  deliver(followUp);
  return { root, renderer };
}

test("prediction_hint null: the server frame's card is in the DOM", () => {
  const { root, renderer } = renderFrameThenFollowUp();
  assert.equal(root.querySelectorAll(`[data-id-hash="${FRAME_ID}"]`).length, 1, "the server frame's card is not in the DOM");
  renderer.unmount();
});

test("prediction_hint null: a LATER well-formed card from another sender is still in the DOM", () => {
  const { root, renderer } = renderFrameThenFollowUp();
  assert.equal(root.querySelectorAll('[data-id-hash="follow-up-1"]').length, 1, "a later, well-formed card is not in the DOM");
  renderer.unmount();
});

// ---------------------------------------------------------------------------
// timeout_seconds: null — expiry
// ---------------------------------------------------------------------------

test("timeout_seconds null: a response-required frame does not expire on arrival", () => {
  const { store, deliver } = setup();
  deliver(frameWith({ response_requested: true, response_type: "yes_no", voice_persona: FIXTURE.voice_persona }));
  assert.equal(store.list()[0].action_required, true);
  assert.equal("expires_at" in store.list()[0], false, "null timeout_seconds made expires_at = arrival time");
});

// ---------------------------------------------------------------------------
// session_name: null — session_topic
// ---------------------------------------------------------------------------

test("session_name null: a session_topic frame emits no session_topic", () => {
  const { bus, store, deliver } = setup();
  const topics: SessionTopicPayload[] = [];
  bus.on<SessionTopicPayload>("session_topic", (e) => topics.push(e.payload));
  deliver(frameWith({ type: "session_topic" }));
  assert.deepEqual(topics, [], "a null session_name was forwarded as a topic");
  assert.equal(store.list().length, 0, "session_topic is control metadata — never carded");
});

// ---------------------------------------------------------------------------
// The rest of the population: no measured misbehaviour, but no null may survive normalize()
// ---------------------------------------------------------------------------

test("normalize() turns every server null into an absent field", () => {
  const { store, deliver } = setup();
  deliver(frameWith());
  const card = store.list()[0] as unknown as Record<string, unknown>;
  assert.deepEqual(Object.keys(card).filter((k) => card[k] === null), [], "normalized notification still carries null fields");
  for (const k of [ "voice_persona", "prediction_hint", "title", "abstract", "progress_group_id", "response_type", "default_value", "expires_at" ]) {
    assert.equal(k in card, false, `${k} should be absent`);
  }
});
