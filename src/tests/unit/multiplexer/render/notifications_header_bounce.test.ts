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

function apiError(status: number): Error {
  const e = new Error(`HTTP ${status}`) as Error & { status: number };
  e.status = status;
  return e;
}

function mount(api: NotificationDeleteApiLike, opts: {
  confirmFn?: (m: string) => boolean;
  fetchFn?  : typeof fetch;
} = {}) {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsHeaderRenderer({
    eventBus     : bus,
    store        : makeStore(),
    api,
    confirmFn    : opts.confirmFn ?? (() => true),
    fetchFn      : opts.fetchFn,
    bouncePollMs : 1,
    bounceWaitMs : 300,
    bounceGraceMs: 100,
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
