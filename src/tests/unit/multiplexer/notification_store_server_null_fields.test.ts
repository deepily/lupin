// Multiplexer — NotificationStore fed the server's REAL frame, where an unsupplied field is null, not absent.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_server_null_fields.test.ts`.
//
// Found 2026-09-10 by the slider E2E (ts-720cc046): the multiplexer spoke nothing for a high-priority
// notification from a sender with no voice persona. The server sends `voice_persona: null`; normalize()
// copied any field `!== undefined`, so the TTS-intent emit read `null.voice_id` and threw. The same frame
// carries `prediction_hint: null`, and the card template threw on `null.confidence`. EventBus swallows
// listener throws into `listener_error`, so both were silent — hence every test here also asserts that
// no listener threw.
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
import { renderNotificationItem } from "../../../lupin_app/static/js/multiplexer/render/templates/notificationItem";
import type {
  ListenerErrorPayload,
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

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  // Same marked + DOMPurify shim as templates_notification_item.test.ts.
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

test("the server's no-persona frame is carded AND emits a TTS intent, and no listener throws", () => {
  const { store, intents, changes, thrown, deliver } = setup();
  const n = FIXTURE.frame.notification;

  deliver(frameWith());

  assert.deepEqual(thrown, [], "a listener threw on the server's frame");
  assert.deepEqual(store.list().map((x) => x.id_hash), [ n.id ], "the notification was not carded");
  assert.ok(changes.some((c) => c.changeKind === "added" && c.id_hash === n.id), "no store_notifications_changed added event");
  assert.deepEqual(intents, [ { id_hash: n.id, ttsText: n.message, priority: "high", action_required: false } ],
    "a persona-less high-priority notification must be spoken, in the server's default voice (no voice_id)");
});

test("normalize() turns every server null into an absent field", () => {
  const { store, deliver } = setup();
  deliver(frameWith());
  const card = store.list()[0] as unknown as Record<string, unknown>;
  const nullKeys = Object.keys(card).filter((k) => card[k] === null);
  assert.deepEqual(nullKeys, [], "normalized notification still carries null fields");
  for (const k of [ "voice_persona", "prediction_hint", "title", "abstract", "progress_group_id", "response_type", "default_value", "expires_at" ]) {
    assert.equal(k in card, false, `${k} should be absent`);
  }
});

test("control: the same frame WITH a real persona speaks in that persona's voice", () => {
  const { store, intents, thrown, deliver } = setup();
  const n = FIXTURE.frame.notification;

  deliver(frameWith({ voice_persona: FIXTURE.voice_persona }));

  assert.deepEqual(thrown, []);
  assert.deepEqual(intents, [ { id_hash: n.id, ttsText: n.message, priority: "high", action_required: false, voice_id: FIXTURE.voice_persona.voice_id } ]);
  assert.deepEqual(store.list()[0].voice_persona, FIXTURE.voice_persona);
});

test("the card for the server's frame renders (prediction_hint: null no longer reaches the template)", () => {
  const { store, deliver } = setup();
  deliver(frameWith());
  const el = renderNotificationItem(store.list()[0]);
  assert.equal(el.getAttribute("data-id-hash"), FIXTURE.frame.notification.id);
});

test("a response-required frame with timeout_seconds: null does not expire on arrival", () => {
  const { store, thrown, deliver } = setup();
  // A real persona, so the voice_persona throw cannot fail this test first: the assertion
  // that must fire without the fix is the expires_at one.
  deliver(frameWith({ response_requested: true, response_type: "yes_no", voice_persona: FIXTURE.voice_persona }));
  assert.deepEqual(thrown, []);
  assert.equal(store.list()[0].action_required, true);
  assert.equal("expires_at" in store.list()[0], false, "null timeout_seconds made expires_at = arrival time");
});

test("a session_topic frame with session_name: null emits no session_topic", () => {
  const { bus, store, thrown, deliver } = setup();
  const topics: SessionTopicPayload[] = [];
  bus.on<SessionTopicPayload>("session_topic", (e) => topics.push(e.payload));
  deliver(frameWith({ type: "session_topic" }));
  assert.deepEqual(thrown, []);
  assert.deepEqual(topics, [], "a null session_name was forwarded as a topic");
  assert.equal(store.list().length, 0, "session_topic is control metadata — never carded");
});
