// Row 83c3ff74 — the jobs pane follows the SAME Mine / Not Mine / All Users switch as the
// notifications pane. Run via
// `npx tsx --test src/tests/unit/multiplexer/the_jobs_pane_follows_the_shared_mine_switch.test.ts`.
//
// Rick's ruling (2026-09-10 ~17:40 EDT): for an admin the jobs pane defaults to OWN jobs, like
// legacy, with legacy's indicator and switch — ONE shared mode, like legacy's single control.
//
// Everything here is real: the NotificationStore that owns the mode, the JobStore, the jobs pane
// renderer and the notifications header renderer, wired with the same expressions boot.ts passes.
// Only the network and the auth token are stubs. A test that built the jobs pane alone could not
// see the one property that matters most: that flipping EITHER header moves BOTH panes.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting, type EventBus } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore, FILTER_MODE_KEY } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { createJobStore } from "../../../lupin_app/static/js/multiplexer/stores/JobStore";
import { createJobsPaneRenderer } from "../../../lupin_app/static/js/multiplexer/render/JobsPaneRenderer";
import { createNotificationsHeaderRenderer } from "../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type { JobStateTransitionPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
afterEach(() => {
  document.body.replaceChildren();
});

const settle = (): Promise<void> => new Promise(r => setTimeout(r, 20));

const RICK_EMAIL = "rick@example.com";
const RICK_UID   = "rick_6bdc";

interface Harness {
  bus         : EventBus;
  store       : ReturnType<typeof createNotificationStore>;
  jobsRoot    : HTMLElement;
  notifRoot   : HTMLElement;
  map         : Map<string, string>;
  historyGets : string[];
  userFilter  : (i: number) => string | null;
}

function bootLike(opts: { storedMode?: string; admin: boolean; uid?: string | null }): Harness {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  const map     = new Map<string, string>();
  if (opts.storedMode !== undefined) map.set(FILTER_MODE_KEY, opts.storedMode);
  const store = createNotificationStore({
    bus, storage,
    sharedStorage : { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => { map.set(k, v); } },
  });
  const jobs = createJobStore({ bus });

  const historyGets: string[] = [];
  const api = {
    get    : <T>(path: string): Promise<T> => { historyGets.push(path); return Promise.resolve({ jobs: [], total: 0 } as T); },
    delete : <T>(): Promise<T> => Promise.resolve(undefined as T),
    post   : <T>(): Promise<T> => Promise.resolve(undefined as T),
  };
  const uid = opts.uid === undefined ? RICK_UID : opts.uid;

  // The notifications header, as boot mounts it.
  const notifRoot = document.createElement("div");
  document.body.appendChild(notifRoot);
  createNotificationsHeaderRenderer({
    eventBus  : bus,
    store,
    api       : { delete: <T>(): Promise<T> => Promise.resolve(undefined as T), bounceDevServer: () => Promise.resolve({ status: "accepted", timestamp: "" }) },
    confirmFn : () => true,
    isAdmin   : () => opts.admin,
  }).mount(notifRoot);

  // The jobs pane, with the four filter options boot passes.
  const jobsRoot  = document.createElement("section");
  const container = document.createElement("div");
  container.id = "jobs-buckets-container";
  jobsRoot.appendChild(container);
  document.body.appendChild(jobsRoot);
  createJobsPaneRenderer({
    eventBus            : bus,
    stores              : { jobs },
    api,
    filterStore         : store,
    isAdmin             : () => opts.admin,
    getCurrentUserId    : () => uid,
    getCurrentUserEmail : () => RICK_EMAIL,
  }).mount(jobsRoot);

  const userFilter = (i: number): string | null => new URL(historyGets[ i ]!, "http://x").searchParams.get("user_filter");
  return { bus, store, jobsRoot, notifRoot, map, historyGets, userFilter };
}

const q = (root: HTMLElement, testid: string): HTMLElement =>
  root.querySelector(`[data-testid='${testid}']`) as HTMLElement;

function transition(bus: EventBus, id: string, metadata: Record<string, unknown>): void {
  bus.emit<JobStateTransitionPayload>({
    type    : "job_state_transition",
    payload : { job_id: id, from_state: "queued", to_state: "running", metadata },
    source  : "test",
    ts      : Date.now(),
  });
}

function visibleJobIds(root: HTMLElement): string[] {
  return [ ...root.querySelectorAll(".job-card") ].map(c => c.getAttribute("data-id-hash") as string).sort();
}

// ---------------------------------------------------------------------------
// The default and the request per mode
// ---------------------------------------------------------------------------

test("an admin with nothing stored gets OWN jobs: one history request, naming the admin's uid", async () => {
  const h = bootLike({ admin: true });
  await settle();
  assert.equal(h.historyGets.length, 1);
  assert.equal(h.userFilter(0), RICK_UID);
  const badge = q(h.jobsRoot, "queues-filter-badge");
  assert.equal(badge.hidden, false);
  assert.equal(badge.textContent, "👤 Mine");
  assert.equal(badge.getAttribute("data-mode"), "own");
});

test("a stored Not Mine asks for !self, and a stored All Users asks for *", async () => {
  const others = bootLike({ admin: true, storedMode: "others" });
  const all    = bootLike({ admin: true, storedMode: "all" });
  await settle();
  assert.equal(others.userFilter(0), "!self");
  assert.equal(q(others.jobsRoot, "queues-filter-badge").textContent, "🚫 Not Mine");
  assert.equal(all.userFilter(0), "*");
  assert.equal(q(all.jobsRoot, "queues-filter-badge").textContent, "👥 All Users");
});

test("a non-admin sends no filter even with legacy's Not Mine stored, and sees neither badge nor switch", async () => {
  const h = bootLike({ admin: false, storedMode: "others", uid: null });
  await settle();
  assert.equal(h.historyGets.length, 1);
  assert.equal(h.userFilter(0), null);
  assert.equal(q(h.jobsRoot, "queues-filter-badge").hidden, true);
  assert.equal(q(h.jobsRoot, "multiplexer-jobs-filter-switch").hidden, true);
});

test("an admin in Mine whose uid cannot be read sends NOTHING and says why, instead of showing every user", async () => {
  const h = bootLike({ admin: true, uid: null });
  await settle();
  assert.equal(h.historyGets.length, 0);
  const banner = h.jobsRoot.querySelector(".jobs-hydration-error-message") as HTMLElement;
  assert.notEqual(banner, null);
  assert.match(banner.textContent as string, /user id/);
});

// ---------------------------------------------------------------------------
// One shared mode — either header moves both panes, with one reload per change
// ---------------------------------------------------------------------------

test("Not Mine clicked in the NOTIFICATIONS header reloads job history once, with !self", async () => {
  const h = bootLike({ admin: true });
  await settle();
  q(h.notifRoot, "multiplexer-notifications-filter-others-btn").click();
  await settle();
  assert.equal(h.historyGets.length, 2, `job history fetched ${h.historyGets.length} times`);
  assert.equal(h.userFilter(1), "!self");
  assert.equal(q(h.jobsRoot, "queues-filter-badge").textContent, "🚫 Not Mine");
  assert.equal(q(h.jobsRoot, "multiplexer-jobs-filter-others-btn").getAttribute("aria-pressed"), "true");
});

test("All Users clicked in the JOBS header moves the shared mode: legacy's key, the notifications badge, one reload", async () => {
  const h = bootLike({ admin: true });
  await settle();
  q(h.jobsRoot, "multiplexer-jobs-filter-all-btn").click();
  await settle();
  assert.equal(h.store.filterMode(), "all");
  assert.equal(h.map.get(FILTER_MODE_KEY), "all");
  assert.equal(q(h.notifRoot, "multiplexer-notifications-filter-badge").textContent, "👥 All Users");
  assert.equal(h.historyGets.length, 2);
  assert.equal(h.userFilter(1), "*");
});

test("clicking the mode already showing reloads nothing", async () => {
  const h = bootLike({ admin: true, storedMode: "others" });
  await settle();
  q(h.jobsRoot, "multiplexer-jobs-filter-others-btn").click();
  await settle();
  assert.equal(h.historyGets.length, 1);
});

test("a history reload after a mode change keeps the window the pane was showing", async () => {
  const h = bootLike({ admin: true });
  await settle();
  const select = h.jobsRoot.querySelector(".history-time-select") as HTMLSelectElement;
  select.value = "7";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await settle();
  q(h.jobsRoot, "multiplexer-jobs-filter-others-btn").click();
  await settle();
  const last = new URL(h.historyGets[ h.historyGets.length - 1 ]!, "http://x").searchParams;
  assert.equal(last.get("days"), "7");
  assert.equal(last.get("user_filter"), "!self");
});

// ---------------------------------------------------------------------------
// The live buckets — filtered in the browser by the job's user_email, like legacy
// ---------------------------------------------------------------------------

test("live jobs: Mine shows own + unowned, Not Mine shows others + unowned, All Users shows all — no stale cards", async () => {
  const h = bootLike({ admin: true });
  await settle();
  transition(h.bus, "mine",    { user_email: RICK_EMAIL });
  transition(h.bus, "theirs",  { user_email: "someone@example.com" });
  transition(h.bus, "noemail", { agent_type: "claude_code" });

  assert.deepEqual(visibleJobIds(h.jobsRoot), [ "mine", "noemail" ]);
  const count = h.jobsRoot.querySelector(".section-header-count") as HTMLElement;
  assert.equal(count.textContent, "2", "the header count counts what is shown");

  q(h.jobsRoot, "multiplexer-jobs-filter-others-btn").click();
  assert.deepEqual(visibleJobIds(h.jobsRoot), [ "noemail", "theirs" ]);

  q(h.notifRoot, "multiplexer-notifications-filter-all-btn").click();
  assert.deepEqual(visibleJobIds(h.jobsRoot), [ "mine", "noemail", "theirs" ]);
  assert.equal(count.textContent, "3");
});

test("the delete-all confirm counts the jobs the mode shows, not the ones it hides", async () => {
  const h = bootLike({ admin: true });
  await settle();
  transition(h.bus, "mine",   { user_email: RICK_EMAIL });
  transition(h.bus, "theirs", { user_email: "someone@example.com" });
  const asked: string[] = [];
  const realConfirm = globalThis.confirm;
  globalThis.confirm = (m?: string): boolean => { asked.push(String(m)); return false; };
  try {
    (h.jobsRoot.querySelector(".queue-delete-all-btn[data-bucket='running']") as HTMLElement).click();
  } finally {
    globalThis.confirm = realConfirm;
  }
  assert.equal(asked.length, 1);
  assert.match(asked[ 0 ]!, /Delete all running jobs \(1\)\?/);
});

test("a pane given the filter store but no identity treats the viewer as a non-admin: no filter, no switch", async () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  const map     = new Map<string, string>([ [ FILTER_MODE_KEY, "all" ] ]);
  const store   = createNotificationStore({
    bus, storage, sharedStorage: { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => { map.set(k, v); } },
  });
  const gets: string[] = [];
  const root = document.createElement("section");
  const container = document.createElement("div");
  container.id = "jobs-buckets-container";
  root.appendChild(container);
  createJobsPaneRenderer({
    eventBus    : bus,
    stores      : { jobs: createJobStore({ bus }) },
    api         : { get: <T>(p: string): Promise<T> => { gets.push(p); return Promise.resolve({ jobs: [], total: 0 } as T); }, delete: <T>(): Promise<T> => Promise.resolve(undefined as T), post: <T>(): Promise<T> => Promise.resolve(undefined as T) },
    filterStore : store,
  }).mount(root);
  await settle();
  assert.equal(gets.length, 1);
  assert.equal(new URL(gets[ 0 ]!, "http://x").searchParams.get("user_filter"), null);
  assert.equal(q(root, "multiplexer-jobs-filter-switch").hidden, true);
  // Mine for a viewer with no email: a job naming an owner is hidden, as legacy's own-mode comparison hides it.
  transition(bus, "owned", { user_email: RICK_EMAIL });
  transition(bus, "unowned", { agent_type: "claude_code" });
  assert.deepEqual(visibleJobIds(root), [ "unowned" ]);
});

test("a non-admin's live buckets are not narrowed by a Not Mine that legacy left stored", async () => {
  const h = bootLike({ admin: false, storedMode: "others", uid: null });
  await settle();
  transition(h.bus, "mine", { user_email: RICK_EMAIL });
  assert.deepEqual(visibleJobIds(h.jobsRoot), [ "mine" ]);
});
