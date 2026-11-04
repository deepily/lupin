// Row 4ca5776c — the multiplexer draws a Yes/No card that was filed before the page opened.
//
// ActionRequiredStore took cards only from a live `notification_queue_update`, so a card filed while the
// page was closed was never drawn. hydrateAwaiting feeds the server's list of waiting cards through the
// same path a push takes, and awaitingResponseHydration fetches that list.
//
// Run via:
//   npx tsx --test src/tests/unit/multiplexer/a_card_filed_while_the_page_was_closed_is_drawn.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredStore,
  type ServerNotificationFields,
} from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import {
  AWAITING_RESPONSE_PATH,
  createAwaitingResponseHydration,
} from "../../../lupin_app/static/js/multiplexer/stores/awaitingResponseHydration";
import type { LupinEvent, StoreActionRequiredChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const NOW = 1_700_000_000_000;

function setup() {
  const bus    = createEventBusForTesting();
  const events: LupinEvent<StoreActionRequiredChangedPayload>[] = [];
  bus.on<StoreActionRequiredChangedPayload>("store_action_required_changed", (e) => events.push(e));
  const store = createActionRequiredStore({
    bus,
    api             : { post: async () => ({ ok: true }) },
    setIntervalFn   : () => 1,
    clearIntervalFn : () => {},
    setTimeoutFn    : () => 1,
    clearTimeoutFn  : () => {},
    nowFn           : () => NOW,
  });
  return { bus, store, events };
}

function card(id: string, extra: Partial<ServerNotificationFields> = {}): ServerNotificationFields {
  return {
    id,
    message            : `question ${id}`,
    sender_id          : "claude.code@lupin.deepily.ai#e0e0e0e0",
    response_requested : true,
    response_type      : "yes_no",
    response_default   : "no",
    timeout_seconds    : 90,
    abstract           : `abstract ${id}`,
    ...extra,
  };
}

test("each waiting card is added in list order, with the fields a push would carry", () => {
  const { store } = setup();
  const added = store.hydrateAwaiting([ card("a"), card("b") ]);
  assert.equal(added, 2);
  assert.deepEqual(store.list().map((i) => i.id_hash), [ "a", "b" ]);
  const a = store.getById("a")!;
  assert.equal(a.prompt, "question a");
  assert.equal(a.response_type, "yes_no");
  assert.equal(a.default, "no");
  assert.equal(a.sender_id, "claude.code@lupin.deepily.ai#e0e0e0e0");
  assert.equal(a.abstract, "abstract a");
  assert.equal(a.timeout_seconds, 90);
  assert.equal(a.state, "pending");
});

test("a card carries the sender's persona under the key a push uses, and a null persona stays absent", () => {
  const { store } = setup();
  const persona = { name: "tiffany", voice_id: "v1", icon: "💍", color: "#FFD600", borrowed: false };
  store.hydrateAwaiting([ card("a", { voice_persona: persona }), card("b", { voice_persona: null as unknown as undefined }) ]);
  assert.deepEqual(store.getById("a")!.voice_persona, persona, "the badge reads this");
  assert.equal("voice_persona" in store.getById("b")!, false, "a server null must not become a stored null");
});

test("the first card takes the slot and its countdown starts at the server's remaining time", () => {
  const { store } = setup();
  store.hydrateAwaiting([ card("a", { timeout_seconds: 41 }), card("b") ]);
  assert.equal(store.getById("a")!.expires_at, NOW + 41_000, "the head counts down from what the server says is left");
  assert.equal(store.getById("b")!.expires_at, null, "the second card waits its turn");
});

test("every added card is announced once, so the renderer draws it", () => {
  const { store, events } = setup();
  store.hydrateAwaiting([ card("a"), card("b") ]);
  assert.deepEqual(events.filter((e) => e.payload.changeKind === "added").map((e) => e.payload.id_hash), [ "a", "b" ]);
});

test("a card the store already holds is not added twice, and is not counted", () => {
  const { bus, store } = setup();
  bus.emit({ type: "notification_queue_update", payload: { notification: card("a") }, source: "test", ts: 0 });
  const added = store.hydrateAwaiting([ card("a"), card("b") ]);
  assert.equal(added, 1);
  assert.equal(store.list().length, 2);
});

test("a card that does not ask for a response is ignored", () => {
  const { store } = setup();
  assert.equal(store.hydrateAwaiting([ card("a", { response_requested: false }) ]), 0);
  assert.equal(store.list().length, 0);
});

test("an empty list adds nothing", () => {
  assert.equal(setup().store.hydrateAwaiting([]), 0);
});

// ---------------------------------------------------------------------------
// The runner
// ---------------------------------------------------------------------------

test("the runner asks the awaiting-response route once and returns what the store added", async () => {
  const paths: string[] = [];
  const seen : ServerNotificationFields[][] = [];
  const run = createAwaitingResponseHydration({
    api    : { get: async <T,>(path: string): Promise<T> => { paths.push(path); return { notifications: [ card("a") ] } as T; } },
    stores : { actionRequired: { hydrateAwaiting: (cards) => { seen.push([ ...cards ]); return 7; } } },
  });
  assert.equal(await run.run(), 7);
  assert.deepEqual(paths, [ AWAITING_RESPONSE_PATH ]);
  assert.equal(AWAITING_RESPONSE_PATH, "/api/notifications/awaiting-response");
  assert.deepEqual(seen, [ [ card("a") ] ]);
});

test("a failed request adds nothing, logs the cause, and does not reject", async () => {
  const warned: unknown[][] = [];
  const original = console.warn;
  console.warn = (...args: unknown[]): void => { warned.push(args); };
  try {
    const boom = new Error("network down");
    const run  = createAwaitingResponseHydration({
      api    : { get: async <T,>(): Promise<T> => { throw boom; } },
      stores : { actionRequired: { hydrateAwaiting: () => { throw new Error("must not be reached"); } } },
    });
    assert.equal(await run.run(), 0);
    assert.deepEqual(warned, [ [ "[multiplexer] waiting response cards not loaded:", boom ] ]);
  } finally {
    console.warn = original;
  }
});

test("an answer with no notifications list adds nothing and does not reject", async () => {
  const original = console.warn;
  console.warn = (): void => {};
  try {
    const run = createAwaitingResponseHydration({
      api    : { get: async <T,>(): Promise<T> => ({}) as T },
      stores : setupStoreOnly(),
    });
    assert.equal(await run.run(), 0);
  } finally {
    console.warn = original;
  }
});

function setupStoreOnly() {
  return { actionRequired: setup().store };
}

// ---------------------------------------------------------------------------
// boot.ts wires it (a source pin: boot runs at import and exports nothing)
// ---------------------------------------------------------------------------

const BOOT_PATH = resolve(dirname(fileURLToPath(import.meta.url)), "../../../lupin_app/static/js/multiplexer/boot.ts");
const BOOT_CODE = readFileSync(BOOT_PATH, "utf8").split("\n").filter((l) => !l.trimStart().startsWith("//")).join("\n");

test("boot runs the runner once, on the real api client and the real action-required store", () => {
  const calls = [ ...BOOT_CODE.matchAll(/createAwaitingResponseHydration\(\{([^}]*(?:\{[^}]*\}[^}]*)*)\}\)\.run\(\);/g) ];
  assert.equal(calls.length, 1, "expected exactly one createAwaitingResponseHydration({ … }).run() call in boot");
  const body = (calls[ 0 ] as RegExpMatchArray)[ 1 ] as string;
  assert.ok(/api:\s*apiClient\b/.test(body), "it must use the page's apiClient");
  assert.ok(/stores:\s*\{\s*actionRequired:\s*stores\.actionRequired\s*\}/.test(body), "it must feed stores.actionRequired");
});
