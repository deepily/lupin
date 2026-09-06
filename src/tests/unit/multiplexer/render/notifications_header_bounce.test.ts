// Row 1b4211ac R2 — NotificationsHeaderRenderer "Bounce server" button.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/notifications_header_bounce.test.ts`.
//
// The button must never lie about the ~20s outage:
//   - confirm declined      → no request, button stays enabled
//   - 202 accepted          → disabled, then re-enabled ONLY after /health is ok
//     again (having gone down), status "Server back up ✓"
//   - 409 already bouncing   → plain reason, button re-enabled, no false success
//   - 503 watcher not running→ plain reason, button re-enabled

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsHeaderRenderer } from "../../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type {
  NotificationsHeaderStoreLike,
  NotificationDeleteApiLike,
} from "../../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type { Notification } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
afterEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

function note(id: string): Notification {
  return { id_hash: id, ts: 1_700_000_000_000, sender_id: "s", message: "m-" + id, action_required: false };
}

function makeStore(): NotificationsHeaderStoreLike {
  const active = [ note("a") ];
  return {
    list           : () => active,
    history        : () => [],
    visibleEntries : () => active,
    removeByIdHashes: () => { /* not exercised here */ },
  };
}

// api fake — delete is inert; bounceDevServer runs the injected behavior.
function makeApi(bounce: () => Promise<{ status: string; timestamp: string }>): {
  api: NotificationDeleteApiLike; calls: number;
} {
  const box = { n: 0 };
  const api: NotificationDeleteApiLike = {
    delete<T>(): Promise<T> { return Promise.resolve(undefined as T); },
    bounceDevServer() { box.n++; return bounce(); },
  };
  return { api, get calls() { return box.n; } };
}

function apiError(status: number, message?: string): Error {
  const e = new Error(message ?? `HTTP ${status}`) as Error & { status: number };
  e.status = status;
  return e;
}

function mount(api: NotificationDeleteApiLike, opts: {
  confirmFn?    : (m: string) => boolean;
  fetchFn?      : typeof fetch;
  bounceWaitMs? : number;
  bounceGraceMs?: number;
} = {}) {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsHeaderRenderer({
    eventBus     : bus,
    store        : makeStore(),
    api,
    confirmFn    : opts.confirmFn ?? (() => true),
    fetchFn      : opts.fetchFn,
    bouncePollMs : 1,
    bounceWaitMs : opts.bounceWaitMs  ?? 300,
    bounceGraceMs: opts.bounceGraceMs ?? 100,
  });
  const root = document.createElement("div");
  document.body.appendChild(root);
  renderer.mount(root);
  return { renderer, root };
}

const $btn    = (root: HTMLElement) => root.querySelector('[data-testid="multiplexer-bounce-dev-server"]') as HTMLButtonElement;
const $status = (root: HTMLElement) => root.querySelector('[data-testid="multiplexer-notifications-header-status"]') as HTMLElement;

async function until(pred: () => boolean, timeoutMs = 2000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (pred()) return true;
    await new Promise(r => setTimeout(r, 2));
  }
  return pred();
}

// ---------------------------------------------------------------------------

test("button renders in the header actions", () => {
  const { api } = makeApi(() => Promise.resolve({ status: "triggered", timestamp: "t" }));
  const { root } = mount(api);
  const btn = $btn(root);
  assert.ok(btn, "bounce button should be present");
  assert.match(btn.textContent ?? "", /Bounce server/);
  assert.equal(btn.disabled, false);
});

test("declining the confirm makes no request and leaves the button enabled", async () => {
  const wrap = makeApi(() => Promise.resolve({ status: "triggered", timestamp: "t" }));
  const { root } = mount(wrap.api, { confirmFn: () => false });
  $btn(root).click();
  await new Promise(r => setTimeout(r, 5));
  assert.equal(wrap.calls, 0, "no bounce request on decline");
  assert.equal($btn(root).disabled, false);
});

test("202 accepted → waits for /health, then re-enables with a back-up status", async () => {
  const wrap = makeApi(() => Promise.resolve({ status: "triggered", timestamp: "t" }));
  // First probe: server is down (throws). Second probe: back up.
  let probe = 0;
  const fetchFn = (() => {
    probe++;
    if (probe === 1) return Promise.reject(new Error("connection refused"));
    return Promise.resolve(new Response("{}", { status: 200 }));
  }) as unknown as typeof fetch;

  const { root } = mount(wrap.api, { fetchFn });
  $btn(root).click();

  // Disabled while bouncing.
  assert.ok(await until(() => $btn(root).disabled === true));
  // Re-enabled once health confirms it is back.
  assert.ok(await until(() => $btn(root).disabled === false && /back up/i.test($status(root).textContent ?? "")));
  assert.equal(wrap.calls, 1);
  assert.ok(probe >= 2, "health was polled across the down→up transition");
});

test("409 already-bouncing surfaces a plain reason and re-enables", async () => {
  const wrap = makeApi(() => Promise.reject(apiError(409)));
  const { root } = mount(wrap.api);
  $btn(root).click();
  assert.ok(await until(() => /already running/i.test($status(root).textContent ?? "")));
  assert.equal($btn(root).disabled, false);
});

test("503 watcher-down surfaces a plain reason and re-enables", async () => {
  const wrap = makeApi(() => Promise.reject(apiError(503)));
  const { root } = mount(wrap.api);
  $btn(root).click();
  assert.ok(await until(() => /watcher is not running/i.test($status(root).textContent ?? "")));
  assert.equal($btn(root).disabled, false);
});

// ---------------------------------------------------------------------------
// Row 87812328 — the two arms c8 reported uncovered at 209541db (394, 424-425).
//
// 🔴 INHERITED, NOT AUTHORED HERE. Both regions were written by 1fa05b16
// (2026-08-03), which IS an ancestor of this branch's merge-base 8bf71a64;
// `git log 8bf71a64..HEAD -- .../NotificationsHeaderRenderer.ts` returns ZERO
// commits. This branch did not create the shortfall and these tests do not
// make it ours — they close a gap that was already there when we arrived.
// ---------------------------------------------------------------------------

test("an error that is neither 409 nor 503 surfaces the error's OWN message", async () => {
  // Line 394 — the fall-through arm of the reason ternary. The message is
  // deliberately distinctive: no other arm in the chain can produce it, so this
  // assertion is satisfied by exactly one path.
  const wrap = makeApi(() => Promise.reject(apiError(500, "upstream exploded")));
  const { root } = mount(wrap.api);
  $btn(root).click();
  assert.ok(await until(() => /upstream exploded/.test($status(root).textContent ?? "")),
    "a 500 must report its own message, not a canned 409/503 reason");
  assert.equal($btn(root).disabled, false, "button re-enables after a plain failure");
});

test("an error carrying NO status at all also falls through to its own message", async () => {
  // Same arm, different input: `status` is undefined, so BOTH comparisons in the
  // chain take their false side. A future `status ?? 0` refactor would break this
  // without breaking the 500 case above, which is why both inputs are driven.
  const wrap = makeApi(() => Promise.reject(new Error("no status field here")));
  const { root } = mount(wrap.api);
  $btn(root).click();
  assert.ok(await until(() => /no status field here/.test($status(root).textContent ?? "")),
    "a statusless error must report its own message");
  assert.equal($btn(root).disabled, false);
});

test("a /health that answers NOT-OK counts as the down-edge and re-enables", async () => {
  // Lines 424-425 — the `else { sawDown = true }` arm: the server ANSWERS during
  // the restart but with a non-ok status, which is a down-edge just as much as a
  // refused connection is.
  //
  // 🔴 THE GRACE IS SET BEYOND THE WAIT ON PURPOSE. Line 422 returns true on
  // EITHER `sawDown` OR an elapsed grace, so with the default 100ms grace this
  // assertion would have two sufficient causes and could not tell you which one
  // fired. A 10s grace against a 2s wait makes the grace arm UNREACHABLE inside
  // this test, leaving `sawDown` as the only path to a "back up" status.
  let probe = 0;
  const fetchFn = (() => {
    probe++;
    if (probe === 1) return Promise.resolve(new Response("nope", { status: 503 }));
    return Promise.resolve(new Response("{}", { status: 200 }));
  }) as unknown as typeof fetch;

  const wrap = makeApi(() => Promise.resolve({ status: "triggered", timestamp: "t" }));
  const { root } = mount(wrap.api, { fetchFn, bounceWaitMs: 2000, bounceGraceMs: 10_000 });
  $btn(root).click();

  assert.ok(await until(() => $btn(root).disabled === false && /back up/i.test($status(root).textContent ?? "")),
    "a not-ok /health followed by an ok one must resolve as back-up");
  assert.ok(probe >= 2, "health was polled across the not-ok → ok transition");
});

test("NEGATIVE CONTROL — an always-ok /health inside the grace never reports back-up", async () => {
  // The discriminating half of the test above. Same grace-beyond-wait geometry,
  // but /health is ok from the first probe, so `sawDown` never becomes true and
  // the grace never elapses. If this reported "back up", the previous test would
  // be passing for a reason other than the arm it names.
  const fetchFn = (() => Promise.resolve(new Response("{}", { status: 200 }))) as unknown as typeof fetch;

  const wrap = makeApi(() => Promise.resolve({ status: "triggered", timestamp: "t" }));
  const { root } = mount(wrap.api, { fetchFn, bounceWaitMs: 300, bounceGraceMs: 10_000 });
  $btn(root).click();

  assert.ok(await until(() => $btn(root).disabled === false && /not yet confirmed healthy/i.test($status(root).textContent ?? "")),
    "with no down-edge and no elapsed grace the wait must time out, not claim success");
});

test("a click on the detached button after unmount is a no-op, not a crash", async () => {
  // Line 381 — the `bounceBtn === null` guard. NOT a defensive-unreachable arm:
  // unmount() nulls the field (:250) while the click listener stays bound to the
  // element itself (:170), so a click already in flight during teardown lands
  // here for real. Driven rather than pragma'd, per the 19154376 precedent.
  //
  // ⚠️ This arm was uncovered BEFORE this branch too — `BRDA:381,66,0,0` on the
  // pre-existing test file. c8's text column listed only 394,424-425 while those
  // larger gaps were open; closing them is what surfaced this one.
  const wrap = makeApi(() => Promise.resolve({ status: "triggered", timestamp: "t" }));
  const { renderer, root } = mount(wrap.api);
  const btn = $btn(root);                 // hold the element across teardown
  renderer.unmount();

  btn.click();                            // the listener is still bound to it
  await new Promise(r => setTimeout(r, 5));
  assert.equal(wrap.calls, 0, "a post-unmount click must not reach the bounce API");
});
