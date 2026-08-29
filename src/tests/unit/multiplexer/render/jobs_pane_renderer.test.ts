// Multiplexer Phase 6a — JobsPaneRenderer unit tests.
// AC5 floor: ≥18 tests per design § Verification matrix.
// Includes Pass 1 F3 + F6 + F13 + Pass 2 F23 + F26 + F27 dedicated coverage.
// Phase 6b extension: Tests 21–30 cover AC5c (delete-button click delegation
// + Q-B10 optimistic + rollback + Q-A6 inertness-marker strip).

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createJobStore, type JobHistoryApiClient } from "../../../../lupin_app/static/js/multiplexer/stores/JobStore";
import {
  createJobsPaneRenderer,
  type JobsPaneApiClient,
} from "../../../../lupin_app/static/js/multiplexer/render/JobsPaneRenderer";
import { ApiError } from "../../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type {
  EventBus,
} from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type {
  Job,
  StoreJobsChangedPayload,
  HydrationFailedPayload,
  LupinEvent,
  JobStateTransitionPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id_hash      : "j1",
    job_type     : "DeepResearchJob",
    status       : "running",
    created_at   : Date.UTC(2026, 4, 5, 14, 0),
    completed_at : Date.UTC(2026, 4, 5, 14, 5),
    meta         : { topic: "default" },
    ...overrides,
  };
}

function makeRoot(): HTMLElement {
  const root = document.createElement("section");
  root.id = "jobs-pane";
  root.setAttribute("data-phase6-pending", "true");
  root.setAttribute("hidden", "");
  const container = document.createElement("div");
  container.id = "jobs-buckets-container";
  root.appendChild(container);
  return root;
}

interface SimpleApiStub extends JobsPaneApiClient {
  calls : Array<string>;
}
function makeStubApi(jobs: ReadonlyArray<Job> = []): SimpleApiStub {
  const calls: string[] = [];
  return {
    calls,
    get: async <T>(path: string): Promise<T> => {
      calls.push(path);
      return { jobs } as unknown as T;
    },
    delete: async <T>(path: string): Promise<T> => {
      calls.push(`DELETE ${path}`);
      return null as T;
    },
    post: async <T>(path: string, body: unknown): Promise<T> => {
      calls.push(`POST ${path} ${JSON.stringify(body)}`);
      return null as T;
    },
  };
}

// Server-state names (as JobStore consumes them via mapServerStateToStatus).
// Maps Job.status (UI-side) → wire `to_state` (server-side):
const UI_TO_SERVER_STATE: Record<Job["status"], string> = {
  todo    : "pending",
  running : "running",
  done    : "completed",
  dead    : "failed",
};

function emitJobAdded(bus: EventBus, job: Job): void {
  // The JobStore listens on `job_state_transition` for adds with from_state=null.
  // metadata gets folded into Job.meta by the reducer, so include the test's
  // intended meta + agent_type together.
  bus.emit<JobStateTransitionPayload>({
    type    : "job_state_transition",
    payload : {
      job_id     : job.id_hash,
      id_hash    : job.id_hash,
      from_state : null,
      to_state   : UI_TO_SERVER_STATE[job.status],
      metadata   : { agent_type: job.job_type, ...job.meta },
    },
    source  : "test",
    ts      : Date.now(),
  });
}

function emitJobRemoved(bus: EventBus, idHash: string): void {
  bus.emit({
    type    : "job_removed",
    payload : { id_hash: idHash },
    source  : "test",
    ts      : Date.now(),
  });
}

// ---------------------------------------------------------------------------
// Test 1-2: Constructor + mount idempotency (F4 + F26)
// ---------------------------------------------------------------------------

test("Test 1: constructor throws when stores.jobs is falsy (Pass 2 F4)", () => {
  const bus = createEventBusForTesting();
  const api = makeStubApi();
  assert.throws(
    () => createJobsPaneRenderer({ eventBus: bus, stores: { jobs: undefined as never }, api }),
    /requires stores\.jobs/,
  );
});

test("Test 2: mount() throws when #jobs-buckets-container is missing", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  // Root without the container child:
  const root = document.createElement("section");
  root.id = "jobs-pane";
  assert.throws(() => renderer.mount(root), /#jobs-buckets-container not found/);
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 3-4: Lifecycle — mount lifts data-phase6-pending but RETAINS `hidden`
// (Lane 0c cold-hidden default); unmount idempotent
// ---------------------------------------------------------------------------

test("Test 3: mount() lifts data-phase6-pending but RETAINS `hidden` on #jobs-pane (Lane 0c cold-hidden default)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  assert.equal(root.hasAttribute("hidden"), true);
  assert.equal(root.getAttribute("data-phase6-pending"), "true");
  renderer.mount(root);
  // Lane 0c (Rachel 🕊️): the `hidden` cold-hidden default is NO LONGER stripped
  // on mount — Job Queues starts hidden (legacy parity, Q3 RULED); the
  // section-toolbar owns visibility, and a persisted user choice overrides the
  // cold `hidden` default (F-Clay-A3). Only data-phase6-pending is lifted.
  assert.equal(root.hasAttribute("hidden"), true);
  assert.equal(root.hasAttribute("data-phase6-pending"), false);
  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 4: unmount() is idempotent (safe to call when not mounted)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  // Calling unmount on a never-mounted renderer should not throw.
  renderer.unmount();
  // Mount + unmount + unmount again
  renderer.mount(makeRoot());
  renderer.unmount();
  renderer.unmount();   // double-unmount = no-op
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 5: Initial paint — all 5 buckets present
// ---------------------------------------------------------------------------

test("Test 5: mount() paints all 5 buckets in render order (todo → history)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  const buckets = root.querySelectorAll(".jobs-bucket");
  assert.equal(buckets.length, 5);
  const order = Array.from(buckets).map(b => b.getAttribute("data-bucket"));
  assert.deepEqual(order, ["todo", "running", "done", "dead", "history"]);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 6-7: Hydrate-on-mount (Q-A7) + hydrateHistory called exactly once
// ---------------------------------------------------------------------------

test("Test 6: mount() invokes hydrateHistory(api) exactly once (Q-A7 eager hydration)", async () => {
  const bus  = createEventBusForTesting();
  // hydrateHistory expects raw rows with server-state values per
  // SERVER_STATE_TO_STATUS (not Job.status UI values); 'completed' → 'done'.
  const api  = makeStubApi([
    { id_hash: "hist-1", job_type: "DeepResearchJob", status: "completed",
      created_at: 1, completed_at: 2, meta: {} } as unknown as Job,
  ]);
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  renderer.mount(makeRoot());

  // Let the floated promise resolve.
  await new Promise(r => setTimeout(r, 10));
  assert.equal(api.calls.length, 1, "hydrateHistory should fire exactly once on mount");
  assert.match(api.calls[0]!, /^\/api\/job-history/);

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 7: mount returns immediately even when hydrate promise is in-flight", () => {
  const bus  = createEventBusForTesting();
  let resolveHydrate!: (v: unknown) => void;
  const api: JobHistoryApiClient = {
    get : <T>(_path: string): Promise<T> => new Promise<T>(r => {
      resolveHydrate = r as unknown as (v: unknown) => void;
    }),
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  // mount() must NOT block on the in-flight hydrate.
  const t0 = Date.now();
  renderer.mount(makeRoot());
  const t1 = Date.now();
  assert.ok(t1 - t0 < 50, `mount should return quickly; took ${t1 - t0}ms`);

  // Cleanup — resolve the dangling promise so the next test isn't polluted.
  resolveHydrate({ jobs: [] });
  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 8: Store-event subscription — added/transitioned/removed re-render
// ---------------------------------------------------------------------------

test("Test 8: job added via job_state_transition triggers a bucket re-render", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Initial: 0 cards.
  assert.equal(root.querySelectorAll(".job-card").length, 0);

  emitJobAdded(bus, makeJob({ id_hash: "j-new", status: "running" }));
  assert.equal(root.querySelectorAll(".job-card").length, 1);
  assert.equal(root.querySelector(".job-card")?.getAttribute("data-id-hash"), "j-new");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 9: removed events route done/dead → history bucket (via JobStore reducer)
// ---------------------------------------------------------------------------

test("Test 9: job_removed for a 'done' job moves it to the history bucket", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Add → transition to done → remove
  emitJobAdded(bus, makeJob({ id_hash: "j-done", status: "running" }));
  bus.emit<JobStateTransitionPayload>({
    type: "job_state_transition",
    payload: { job_id: "j-done", id_hash: "j-done", from_state: "running", to_state: "completed" },
    source: "test", ts: Date.now(),
  });
  emitJobRemoved(bus, "j-done");

  // The job should now be rendered inside the history bucket.
  const historyBucket = root.querySelector('[data-bucket="history"]') as HTMLElement;
  assert.equal(historyBucket.querySelectorAll(".job-card").length, 1);
  assert.equal(historyBucket.querySelector(".job-card")?.getAttribute("data-id-hash"), "j-done");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 10: click on .job-card-header toggles .collapsed + populates lazy meta
// ---------------------------------------------------------------------------

test("Test 10: click on .job-card-header toggles details + lazy-renders meta from JobStore.getById", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "j-click", status: "running", meta: { topic: "click-test" } }));
  const card    = root.querySelector(".job-card") as HTMLElement;
  const header  = card.querySelector(".job-card-header") as HTMLElement;
  const details = card.querySelector(".job-card-details") as HTMLElement;
  const pre     = card.querySelector(".job-meta-json") as HTMLPreElement;

  assert.ok(details.classList.contains("collapsed"));
  assert.equal(pre.hasAttribute("hidden"), true);
  assert.equal(pre.textContent, "");

  header.click();   // first click → expand + lazy-populate
  assert.equal(details.classList.contains("collapsed"), false);
  assert.equal(pre.hasAttribute("hidden"), false);
  assert.match(pre.textContent || "", /click-test/);

  header.click();   // second click → collapse (cache hit; no re-populate)
  assert.equal(details.classList.contains("collapsed"), true);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 11: click delegation — clicks elsewhere don't toggle anything
// ---------------------------------------------------------------------------

test("Test 11: click on non-card area is a no-op (delegated handler early-returns)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "j-1" }));

  // Click on the bucket header — NOT a job-card-header — should not toggle any card details.
  const bucketHeader = root.querySelector(".jobs-bucket-header") as HTMLElement;
  const detailsBefore = root.querySelector(".job-card-details")?.classList.contains("collapsed");
  bucketHeader.click();
  // Card details classlist unchanged.
  const detailsAfter = root.querySelector(".job-card-details")?.classList.contains("collapsed");
  assert.equal(detailsBefore, detailsAfter, "card details classlist should not change on bucket-header click");

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 11b: click on .job-card body (NOT header) is a no-op (only header toggles)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "j-1" }));

  const card    = root.querySelector(".job-card") as HTMLElement;
  const details = card.querySelector(".job-card-details") as HTMLElement;
  assert.ok(details.classList.contains("collapsed"));

  // Click directly on the .job-card-details (body), not the header.
  details.click();
  // Should NOT toggle.
  assert.ok(details.classList.contains("collapsed"));

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 12: forceRenderForTesting + click handler attached after fresh mount
// ---------------------------------------------------------------------------

test("Test 12: forceRenderForTesting() triggers a synchronous full re-render", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  // Mutate the DOM externally (fake out the renderer's mount point):
  const container = root.querySelector("#jobs-buckets-container") as HTMLElement;
  container.innerHTML = "<div class='external-tampering'></div>";
  // forceRenderForTesting wipes + re-renders.
  renderer.forceRenderForTesting();
  assert.ok( container.querySelector(".external-tampering") === null );
  assert.equal(container.querySelectorAll(".jobs-bucket").length, 5);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 13: click on null target (no .target) is safely handled
// ---------------------------------------------------------------------------

test("Test 13: click event with null target is safely handled (defensive)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Synthesize a click event with no target attached.
  const evt = new Event("click", { bubbles: true });
  // Defining target as null on a synthetic event in jsdom is tricky; we rely on
  // the dispatched event's default behavior (target is the dispatchEvent target).
  // Click the root directly — target will be the root, NOT a .job-card.
  root.dispatchEvent(evt);
  // No crash, no card toggled.
  assert.equal(root.querySelectorAll(".job-card-details:not(.collapsed)").length, 0);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 14: click handler isolation (Pass 1 F13)
// ---------------------------------------------------------------------------

test("Test 14: click on a card-header inside #jobs-pane fires JobsPaneRenderer's handler ONLY (F13)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Sibling pane that simulates Phase 5's notifications-pane root, with an
  // independent click listener that we can detect.
  const otherPane = document.createElement("section");
  otherPane.id = "notifications-pane";
  document.body.appendChild(root);
  document.body.appendChild(otherPane);
  let otherFired = false;
  otherPane.addEventListener("click", () => { otherFired = true; });

  emitJobAdded(bus, makeJob({ id_hash: "iso-1" }));
  const header = root.querySelector(".job-card-header") as HTMLElement;
  header.click();

  assert.equal(otherFired, false, "click in #jobs-pane should NOT fire #notifications-pane handler");

  document.body.removeChild(root);
  document.body.removeChild(otherPane);
  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 15: success-path race (Pass 1 F6 + Pass 2 F27 deferred-promise rewrite)
// ---------------------------------------------------------------------------

test("Test 15: hydrate-after-removal preserves in-session removed-job state (success path; deferred-promise pattern per F27)", async () => {
  const bus = createEventBusForTesting();
  let resolveHydrate!: (v: { jobs: ReadonlyArray<Job> }) => void;
  const api: JobHistoryApiClient = {
    get : <T>(_path: string): Promise<T> => new Promise<T>(r => {
      resolveHydrate = r as unknown as (v: { jobs: ReadonlyArray<Job> }) => void;
    }),
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  renderer.mount(makeRoot());

  // Pre-seed: add a 'done' job, then remove it (so it lives in the history bucket
  // via the in-session reducer path).
  emitJobAdded(bus, makeJob({ id_hash: "race-1", status: "running" }));
  bus.emit<JobStateTransitionPayload>({
    type: "job_state_transition",
    payload: { job_id: "race-1", id_hash: "race-1", from_state: "running", to_state: "completed" },
    source: "test", ts: Date.now(),
  });
  emitJobRemoved(bus, "race-1");

  // Hydrate is now in flight (mount fired it). The race-1 in-session entry
  // is in history. Now resolve the hydrate with a stale persisted version
  // of the SAME job — JobStore dedup-by-id_hash should keep state coherent.
  resolveHydrate({ jobs: [
    makeJob({ id_hash: "race-1", status: "done", meta: { stale: true } }),
  ] });

  // Let the hydrate-then queue-microtask settle.
  await new Promise(r => setTimeout(r, 10));

  // Final state: history bucket has exactly one race-1 job.
  const history = jobs.bucket("history");
  const matches = history.filter(j => j.id_hash === "race-1");
  assert.equal(matches.length, 1, `history should contain exactly 1 race-1; got ${matches.length}`);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 16: rejection-path race (Pass 1 F3 + Pass 2 F27)
// ---------------------------------------------------------------------------

test("Test 16: hydrate rejection emits hydration_failed, no unhandled rejection, in-session state preserved (F3)", async () => {
  const bus = createEventBusForTesting();
  let rejectHydrate!: (err: Error) => void;
  const api: JobHistoryApiClient = {
    get : <T>(_path: string): Promise<T> => new Promise<T>((_, r) => {
      rejectHydrate = r;
    }),
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });

  // Subscribe BEFORE mount so we capture the emission.
  const failedPayloads: HydrationFailedPayload[] = [];
  bus.on<HydrationFailedPayload>("hydration_failed", (e: LupinEvent<HydrationFailedPayload>) => {
    failedPayloads.push(e.payload);
  });

  renderer.mount(makeRoot());

  // Pre-seed a removed-job in history.
  emitJobAdded(bus, makeJob({ id_hash: "rej-1", status: "running" }));
  bus.emit<JobStateTransitionPayload>({
    type: "job_state_transition",
    payload: { job_id: "rej-1", id_hash: "rej-1", from_state: "running", to_state: "completed" },
    source: "test", ts: Date.now(),
  });
  emitJobRemoved(bus, "rej-1");

  // Reject the hydrate.
  rejectHydrate(new Error("network down"));

  // Let the catch run.
  await new Promise(r => setTimeout(r, 10));

  // (a) hydration_failed emitted with source: "jobs"
  assert.equal(failedPayloads.length, 1, "exactly 1 hydration_failed emission expected");
  assert.equal(failedPayloads[0]!.source, "jobs");
  assert.match(failedPayloads[0]!.error.message, /network down/);
  // (c) in-session removed job preserved despite hydrate rejection
  const history = jobs.bucket("history");
  assert.equal(history.filter(j => j.id_hash === "rej-1").length, 1);

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 16b: hydrate rejection with non-Error throwable wraps in Error before emitting", async () => {
  const bus = createEventBusForTesting();
  let rejectHydrate!: (err: unknown) => void;
  const api: JobHistoryApiClient = {
    get : <T>(_path: string): Promise<T> => new Promise<T>((_, r) => {
      rejectHydrate = r;
    }),
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });

  const failedPayloads: HydrationFailedPayload[] = [];
  bus.on<HydrationFailedPayload>("hydration_failed", (e: LupinEvent<HydrationFailedPayload>) => {
    failedPayloads.push(e.payload);
  });

  renderer.mount(makeRoot());
  rejectHydrate("network bad");   // non-Error throwable
  await new Promise(r => setTimeout(r, 10));

  assert.equal(failedPayloads.length, 1);
  assert.ok(failedPayloads[0]!.error instanceof Error);
  assert.equal(failedPayloads[0]!.error.message, "network bad");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 17: mount idempotency throw (Pass 2 F26)
// ---------------------------------------------------------------------------

test("Test 17: double-mount throws Error('JobsPaneRenderer already mounted'); post-unmount mount succeeds (F26)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });

  renderer.mount(makeRoot());
  assert.throws(() => renderer.mount(makeRoot()), /JobsPaneRenderer already mounted/);

  // After unmount, a fresh mount succeeds.
  renderer.unmount();
  renderer.mount(makeRoot());   // no throw
  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 18: ENABLED delete-button click triggers delete, intercepted BEFORE the
//   card-header toggle path (W1 — the button is live now; Pass 2 F23 invariant
//   still holds: a delete click never toggles the card open).
// ---------------------------------------------------------------------------

test("Test 18: clicking the ENABLED .job-delete-button triggers delete + never toggles the card (W1 / F23)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-1", status: "running" }));
  const card    = root.querySelector(".job-card") as HTMLElement;
  const button  = card.querySelector(".job-delete-button") as HTMLButtonElement;
  const details = card.querySelector(".job-card-details") as HTMLElement;

  // The delete button is live (no inert markers).
  assert.equal(button.getAttribute("aria-disabled"), null, "button must be enabled");
  assert.ok(details.classList.contains("collapsed"));

  button.click();
  await flushMicrotasks();

  // The delete flow fired (routed to the live queue) + the card is gone. The
  // click was intercepted BEFORE the card-header toggle path (F23), so details
  // (now detached) never expanded. (makeStubApi records the mount-time hydrate
  // GET too, so filter to the DELETE calls.)
  const deleteCalls = api.calls.filter(c => c.startsWith("DELETE "));
  assert.deepEqual(deleteCalls, ["DELETE /api/queue/run/del-1"]);
  assert.equal(jobs.getById("del-1"), undefined, "job removed on success");
  assert.ok(details.classList.contains("collapsed"), "delete never toggled the card open");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 19: hydrated event triggers a render (covers the subscription path)
// ---------------------------------------------------------------------------

test("Test 19: store_jobs_changed { changeKind: 'hydrated' } triggers a re-render", async () => {
  const bus  = createEventBusForTesting();
  // Server-state 'completed' maps to UI-status 'done' via SERVER_STATE_TO_STATUS.
  const api  = makeStubApi([
    { id_hash: "hist-evt", job_type: "DeepResearchJob", status: "completed",
      created_at: 1, completed_at: 2, meta: {} } as unknown as Job,
  ]);
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Wait for hydrate promise to resolve.
  await new Promise(r => setTimeout(r, 10));

  // History bucket should now contain the hydrated job.
  const historyBucket = root.querySelector('[data-bucket="history"]') as HTMLElement;
  const cards = historyBucket.querySelectorAll(".job-card");
  assert.equal(cards.length, 1);
  assert.equal(cards[0]!.getAttribute("data-id-hash"), "hist-evt");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 20: subscriptions detached after unmount (no zombie handlers)
// ---------------------------------------------------------------------------

test("Test 19b: card-header click on a card whose id_hash is unknown to JobStore renders empty meta '{}' via the `?? {}` fallback", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Manually inject a fake card directly into the buckets container with a
  // data-id-hash that JobStore has never seen. This exercises the
  // `job?.meta ?? {}` fallback inside the click handler.
  const container = root.querySelector("#jobs-buckets-container") as HTMLElement;
  container.innerHTML = `
    <section class="jobs-bucket jobs-bucket-running" data-bucket="running">
      <div class="job-card status-running" data-id-hash="ghost-id">
        <div class="job-card-header"><span>x</span></div>
        <div class="job-card-details collapsed">
          <pre class="job-meta-json" hidden></pre>
        </div>
      </div>
    </section>
  `;
  const header = container.querySelector(".job-card-header") as HTMLElement;
  const pre    = container.querySelector(".job-meta-json") as HTMLPreElement;

  header.click();
  // Empty-meta fallback renders "{}" (JSON.stringify({}) → "{}").
  assert.equal(pre.textContent, "{}");
  assert.equal(pre.hasAttribute("hidden"), false);

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 20: store events fired AFTER unmount do NOT trigger renders (subscriptions detached)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Mount + initial render.
  assert.equal(root.querySelectorAll(".jobs-bucket").length, 5);

  // Unmount → buckets-container is cleared.
  renderer.unmount();
  const container = root.querySelector("#jobs-buckets-container") as HTMLElement;
  assert.equal(container.querySelectorAll(".jobs-bucket").length, 0);

  // Fire a store event AFTER unmount — should not crash, should not re-paint.
  emitJobAdded(bus, makeJob({ id_hash: "post-unmount-1" }));
  assert.equal(container.querySelectorAll(".jobs-bucket").length, 0);

  jobs.disposeForTesting();
});

// =============================================================================
// Phase 6b — AC5c: delete-button click delegation + Q-B10 optimistic + rollback
// =============================================================================

interface ControllableDeleteApi extends JobsPaneApiClient {
  calls : Array<string>;
  /** Replace with a resolved Promise (default) or a rejected one for testing. */
  responder : (path: string) => Promise<unknown>;
}

function makeControllableApi(
  hydrateJobs: ReadonlyArray<Job> = [],
  responder: (path: string) => Promise<unknown> = async () => null,
): ControllableDeleteApi {
  const calls: string[] = [];
  const api: ControllableDeleteApi = {
    calls,
    responder,
    get: async <T>(path: string): Promise<T> => {
      return { jobs: hydrateJobs } as unknown as T;
    },
    delete: <T>(path: string): Promise<T> => {
      calls.push(path);
      return api.responder(path) as Promise<T>;
    },
    post: <T>(path: string, _body: unknown): Promise<T> => {
      calls.push(path);
      return api.responder(path) as Promise<T>;
    },
  };
  return api;
}

/** Yield once so any pending then/catch/finally microtasks settle. */
async function flushMicrotasks(): Promise<void> {
  await new Promise(r => setTimeout(r, 0));
}

// ---------------------------------------------------------------------------
// Test 21 (5B-1 + 5B-2): click delegation handles `.job-delete-button` and
//   dispatches to `JobStore.delete(idHash)` + captures the restoreState closure.
// ---------------------------------------------------------------------------

test("Test 21: delete-button click invokes JobStore.delete(idHash) + captures restoreState (5B-1, 5B-2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi();
  const jobs = createJobStore({ bus });

  const deleteCalls: string[] = [];
  const originalDelete = jobs.delete.bind(jobs);
  (jobs as unknown as { delete: (id: string) => { restoreState: () => void } }).delete =
    (id: string) => {
      deleteCalls.push(id);
      return originalDelete(id);
    };

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-21", status: "running" }));
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;
  assert.ok(button, "delete button should be present");

  button.click();
  await flushMicrotasks();

  assert.deepEqual(deleteCalls, ["del-21"], "JobStore.delete should be called exactly once with idHash");
  assert.deepEqual(api.calls,   ["/api/queue/run/del-21"], "api.delete should be called with UI-status → server-queue mapping (running → run)");
  assert.equal(jobs.getById("del-21"), undefined, "job should be removed from store post-success");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 22 (5B-3): 2xx response → restoreState NOT called; no rollback.
// ---------------------------------------------------------------------------

test("Test 22: 2xx response discards restoreState; no rollback (5B-3)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async () => null);
  const jobs = createJobStore({ bus });
  const events: LupinEvent<StoreJobsChangedPayload>[] = [];
  bus.on<StoreJobsChangedPayload>("store_jobs_changed", (e) => events.push(e));

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-22", status: "running" }));
  const before = events.length;
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;
  button.click();
  await flushMicrotasks();

  // Exactly ONE "removed" event; NO "added" event for the restore path.
  const delta = events.slice(before);
  const removeds = delta.filter(e => e.payload.changeKind === "removed");
  const addeds   = delta.filter(e => e.payload.changeKind === "added");
  assert.equal(removeds.length, 1, "exactly one removed event");
  assert.equal(addeds.length,   0, "no added event (no rollback)");
  assert.ok( root.querySelector('[data-id-hash="del-22"]') === null, "card stays gone" );

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 23 (5B-4): 404 response → treated as success per Q-B10; no rollback.
// ---------------------------------------------------------------------------

test("Test 23: 404 response is treated as success per Q-B10 (5B-4)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async () => {
    throw new ApiError(404, "/api/queue/run/del-23", "not found");
  });
  const jobs = createJobStore({ bus });
  const events: LupinEvent<StoreJobsChangedPayload>[] = [];
  bus.on<StoreJobsChangedPayload>("store_jobs_changed", (e) => events.push(e));

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-23", status: "running" }));
  const before = events.length;
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;
  button.click();
  await flushMicrotasks();

  const delta = events.slice(before);
  assert.equal(delta.filter(e => e.payload.changeKind === "removed").length, 1);
  assert.equal(delta.filter(e => e.payload.changeKind === "added").length,   0, "404 is success — no rollback");
  assert.ok( root.querySelector('[data-id-hash="del-23"]') === null );
  // No error stripe rendered on success-path 404.
  assert.ok( root.querySelector(".job-card-error-stripe") === null );

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 24 (5B-5): 5xx response → restoreState invoked + inline error stripe rendered.
// ---------------------------------------------------------------------------

test("Test 24: 5xx response invokes restoreState + renders inline error stripe (5B-5)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async () => {
    throw new ApiError(500, "/api/queue/run/del-24", "server error");
  });
  const jobs = createJobStore({ bus });
  const events: LupinEvent<StoreJobsChangedPayload>[] = [];
  bus.on<StoreJobsChangedPayload>("store_jobs_changed", (e) => events.push(e));

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-24", status: "running" }));
  const before = events.length;
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;
  button.click();
  await flushMicrotasks();

  const delta = events.slice(before);
  assert.equal(delta.filter(e => e.payload.changeKind === "removed").length, 1, "optimistic removal fired");
  assert.equal(delta.filter(e => e.payload.changeKind === "added").length,   1, "restoreState fired added event");

  // Card is back in DOM after rollback.
  const restoredCard = root.querySelector('[data-id-hash="del-24"]') as HTMLElement | null;
  assert.ok(restoredCard, "card should be back in DOM after rollback");
  const stripe = restoredCard!.querySelector(".job-card-error-stripe") as HTMLElement | null;
  assert.ok(stripe, "inline error stripe should be present");
  assert.equal(stripe!.getAttribute("role"),      "alert");
  assert.equal(stripe!.getAttribute("aria-live"), "polite");
  assert.match(stripe!.textContent ?? "", /HTTP 500/);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 25 (5B-6): Network error → same rollback behavior as 5xx.
// ---------------------------------------------------------------------------

test("Test 25: network error invokes restoreState + renders inline error stripe (5B-6)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async () => {
    throw new TypeError("Failed to fetch");
  });
  const jobs = createJobStore({ bus });
  const events: LupinEvent<StoreJobsChangedPayload>[] = [];
  bus.on<StoreJobsChangedPayload>("store_jobs_changed", (e) => events.push(e));

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-25", status: "running" }));
  const before = events.length;
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;
  button.click();
  await flushMicrotasks();

  const delta = events.slice(before);
  assert.equal(delta.filter(e => e.payload.changeKind === "removed").length, 1);
  assert.equal(delta.filter(e => e.payload.changeKind === "added").length,   1);

  const restoredCard = root.querySelector('[data-id-hash="del-25"]') as HTMLElement | null;
  assert.ok(restoredCard);
  const stripe = restoredCard!.querySelector(".job-card-error-stripe");
  assert.ok(stripe);
  assert.match(stripe!.textContent ?? "", /Failed to fetch/);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 26 (5B-7): rapid double-click — only the first click dispatches `delete`.
// ---------------------------------------------------------------------------

test("Test 26: rapid double-click — only first click emits delete (5B-7)", async () => {
  const bus  = createEventBusForTesting();
  // Pending-forever promise so the in-flight set stays populated.
  const pending: Promise<unknown> = new Promise(() => {});
  const api = makeControllableApi([], () => pending);
  const jobs = createJobStore({ bus });

  // Spy on JobStore.delete (replace with no-op stub so the card stays in DOM
  // and a second click can dispatch).
  const deleteCalls: string[] = [];
  (jobs as unknown as { delete: (id: string) => { restoreState: () => void } }).delete =
    (id: string) => {
      deleteCalls.push(id);
      // No-op delete — card stays in DOM so the second click is dispatchable.
      return { restoreState: () => {} };
    };

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-26", status: "running" }));
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;

  button.click();
  button.click();
  button.click();
  await flushMicrotasks();

  assert.deepEqual(deleteCalls, ["del-26"], "JobStore.delete called exactly once across 3 rapid clicks");
  assert.equal(api.calls.length, 1, "api.delete also called exactly once");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 27 (5B-8): non-delete-button clicks within a row are NO-OP for delete.
// ---------------------------------------------------------------------------

test("Test 27: non-delete-button clicks within row do NOT trigger delete (5B-8)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi();
  const jobs = createJobStore({ bus });

  const deleteCalls: string[] = [];
  const originalDelete = jobs.delete.bind(jobs);
  (jobs as unknown as { delete: (id: string) => { restoreState: () => void } }).delete =
    (id: string) => { deleteCalls.push(id); return originalDelete(id); };

  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-27", status: "running" }));
  // Click the status icon (a span inside the card-header, NOT the delete button).
  const header = root.querySelector(".job-card-header") as HTMLElement;
  const icon   = header.querySelector(".job-status-icon") as HTMLElement;
  icon.click();
  await flushMicrotasks();

  assert.deepEqual(deleteCalls, [],          "delete handler should not fire on non-delete clicks");
  assert.equal(api.calls.length, 0,          "api.delete should not be called");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 28 (W1): `.job-delete-button` renders ENABLED post-render — no Q-A6 inert
//   markers present (the former post-render strip is gone; the template renders
//   the button live). Same post-render invariant, now guaranteed at the source.
// ---------------------------------------------------------------------------

test("Test 28: .job-delete-button renders with NO inert markers post-render (W1)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-28a", status: "running" }));
  emitJobAdded(bus, makeJob({ id_hash: "del-28b", status: "done" }));

  // No `aria-disabled="true"` should remain on any delete button after render.
  assert.ok( root.querySelector('.job-delete-button[aria-disabled="true"]') === null,
    "aria-disabled='true' should be stripped", );
  // No "Delete coming in Phase 6b" title should remain.
  assert.ok( root.querySelector('.job-delete-button[title="Delete coming in Phase 6b"]') === null,
    "Phase 6b placeholder title should be stripped", );
  // tabindex=-1 is also stripped (was part of the disabled state).
  assert.ok( root.querySelector('.job-delete-button[tabindex="-1"]') === null,
    "tabindex='-1' should be stripped", );

  // Sanity: buttons themselves still exist.
  assert.equal(root.querySelectorAll(".job-delete-button").length, 2);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 29: deriveErrorMessage covers non-ApiError Error branch + verifies the
//   `todo` UI-status → `todo` server-queue mapping (the non-collapsing path).
// ---------------------------------------------------------------------------

test("Test 29: non-ApiError Error still produces stripe; verifies todo → todo queue mapping", async () => {
  const bus  = createEventBusForTesting();
  // Reject with a plain Error (non-ApiError) — exercises the `err instanceof Error` branch.
  const api  = makeControllableApi([], async () => {
    throw new Error("connection reset by peer");
  });
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-30", status: "todo" }));
  // Verify the todo-status mapping too.
  const button = root.querySelector(".job-delete-button") as HTMLButtonElement;
  button.click();
  await flushMicrotasks();

  assert.equal(api.calls[0], "/api/queue/todo/del-30", "todo status maps directly to 'todo' queue");
  const stripe = root.querySelector(".job-card-error-stripe") as HTMLElement | null;
  assert.ok(stripe);
  assert.match(stripe!.textContent ?? "", /connection reset/);

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Test 30 (W1 regression): deleting a HISTORY-bucket card routes to
//   /api/job-history/{id}, NOT the live-queue endpoint. A history row's status
//   is done/dead but it is no longer in a live queue, so the legacy
//   /api/queue/{queue}/{id} 404s → the 404-as-success branch silently swallows
//   it → the persisted history row survives a reload (the latent bug W1 fixes).
// ---------------------------------------------------------------------------

test("Test 30 (W1 regression): history-bucket delete routes to /api/job-history/{id}, not /api/queue/...", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi();   // records the raw path in api.calls
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Land a job in the HISTORY bucket: a done job removed → archived to history.
  emitJobAdded(bus, makeJob({ id_hash: "hist-del", status: "done" }));
  emitJobRemoved(bus, "hist-del");
  const historyBucket = root.querySelector('[data-bucket="history"]') as HTMLElement;
  const button = historyBucket.querySelector(".job-delete-button") as HTMLButtonElement;
  assert.ok(button, "history card carries a live delete button");

  button.click();
  await flushMicrotasks();

  assert.deepEqual(api.calls, ["/api/job-history/hist-del"]);
  assert.ok(!api.calls[0]!.startsWith("/api/queue/"), "history row must NOT hit the live-queue endpoint");
  assert.equal(jobs.getById("hist-del"), undefined, "history row removed from store on success");

  renderer.unmount();
  jobs.disposeForTesting();
});

// =============================================================================
// WS3 cross-cutting — hydration_failed CONSUMER (visible fail-loud affordance
// + Retry). Before this consumer the event had ZERO subscribers, so a hydrate
// failure was invisible. Fault-injection: api.get rejects (== /api/job-history
// 500) → assert the affordance is VISIBLE in the DOM.
// =============================================================================

/** An api whose first `get` (hydrate) call rejects, subsequent ones resolve. */
function makeFlakyHydrateApi(
  failTimes: number,
  rejectWith: unknown = new ApiError("HTTP 500", 500),
): SimpleApiStub {
  const calls: string[] = [];
  let getCount = 0;
  return {
    calls,
    get: async <T>(path: string): Promise<T> => {
      calls.push(path);
      getCount += 1;
      if (getCount <= failTimes) {
        return Promise.reject(rejectWith) as Promise<T>;
      }
      return { jobs: [] } as unknown as T;
    },
    delete: async <T>(path: string): Promise<T> => {
      calls.push(`DELETE ${path}`);
      return null as T;
    },
  };
}

test("Test 31: fault-injection — hydrate 500 paints a VISIBLE hydration-error banner with Retry (consumer)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeFlakyHydrateApi(1);
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  // Let the floated hydrateHistory().catch → emit → consumer microtasks settle.
  await flushMicrotasks();

  const banner = root.querySelector(".jobs-hydration-error") as HTMLElement | null;
  assert.ok(banner, "hydration-error banner should be VISIBLE in the DOM after a 500");
  assert.equal(banner!.getAttribute("role"), "alert", "banner is an assertive alert");
  assert.match(banner!.textContent ?? "", /Could not load job history/);
  assert.match(banner!.textContent ?? "", /HTTP 500/, "the underlying error surfaces to the user");
  const retry = banner!.querySelector(".jobs-hydration-retry") as HTMLButtonElement | null;
  assert.ok(retry, "Retry affordance should be present");

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 32: hydration_failed from a NON-jobs source is ignored (no banner)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await flushMicrotasks();

  // A different renderer's hydrate failure must not paint the jobs banner.
  bus.emit<HydrationFailedPayload>({
    type    : "hydration_failed",
    payload : { source: "commons", error: new Error("not ours") },
    source  : "CommonsPanelRenderer",
    ts      : Date.now(),
  });

  assert.ok( root.querySelector(".jobs-hydration-error") === null, "non-jobs source must be ignored" );

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 33: Retry success removes the banner + hydrates the buckets (consumer)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeFlakyHydrateApi(1);   // first get fails, second succeeds
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await flushMicrotasks();

  const banner = root.querySelector(".jobs-hydration-error") as HTMLElement | null;
  assert.ok(banner, "banner present after initial failure");

  (banner!.querySelector(".jobs-hydration-retry") as HTMLButtonElement).click();
  await flushMicrotasks();

  assert.ok( root.querySelector(".jobs-hydration-error") === null, "Retry success removes the banner" );
  // Two get calls: the failed hydrate + the successful retry.
  assert.equal(api.calls.filter(p => p.startsWith("/api/job-history")).length, 2);

  renderer.unmount();
  jobs.disposeForTesting();
});

test("Test 34: Retry that fails again repaints the banner (replace, not stack)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeFlakyHydrateApi(2);   // both hydrate + retry fail
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await flushMicrotasks();

  assert.ok(root.querySelector(".jobs-hydration-error"), "banner after first failure");

  (root.querySelector(".jobs-hydration-retry") as HTMLButtonElement).click();
  await flushMicrotasks();

  // Exactly ONE banner — the second failure replaced the first, did not stack.
  const banners = root.querySelectorAll(".jobs-hydration-error");
  assert.equal(banners.length, 1, "repeated failure replaces the banner, never stacks");

  renderer.unmount();
  jobs.disposeForTesting();
});

// ---------------------------------------------------------------------------
// Lane 0a — uniform section-header bar (📝 Jobs + 4-live-bucket count + collapse)
// ---------------------------------------------------------------------------

test("Lane 0a: Jobs renders the 📝 section-header; count = 4 live buckets (history excluded); collapse toggles", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  const header = root.querySelector(".section-header") as HTMLElement;
  assert.ok(header, "section-header bar present");
  assert.ok(header.querySelector("h3")!.textContent!.includes("📝 Jobs"), "📝 Jobs title in h3");
  assert.ok( root.querySelector(".jobs-pane-header") === null, "inert static header is gone" );

  const count = root.querySelector(".section-header-count") as HTMLElement;
  assert.equal(count.textContent, "0", "count 0 initially");

  emitJobAdded(bus, makeJob({ id_hash: "j1", status: "running" }));
  assert.equal(count.textContent, "1", "1 live job");
  emitJobAdded(bus, makeJob({ id_hash: "j2", status: "todo" }));
  assert.equal(count.textContent, "2", "2 live jobs across buckets");

  // Move j1 to the HISTORY bucket (transition done → remove). It leaves the live
  // buckets, so the count drops — history is excluded from the header count.
  bus.emit<JobStateTransitionPayload>({
    type: "job_state_transition",
    payload: { job_id: "j1", id_hash: "j1", from_state: "running", to_state: "completed" },
    source: "test", ts: Date.now(),
  });
  emitJobRemoved(bus, "j1");
  assert.equal(count.textContent, "1", "history bucket excluded from the live count");

  // The buckets container is the collapsible body.
  assert.ok((root.querySelector("#jobs-buckets-container") as HTMLElement).classList.contains("section-content"));

  // Session-only collapse on the pane root.
  const chevron = header.querySelector(".toggle-button") as HTMLElement;
  (header.querySelector("h3") as HTMLElement).dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(root.getAttribute("data-collapsed"), "true");
  assert.equal(chevron.textContent, "▶");

  renderer.unmount();
  jobs.disposeForTesting();
});

// =============================================================================
// W2 — per-bucket delete-all 🗑 (confirm-gated bulk delete, refetch-after-2xx)
// =============================================================================

function stubConfirm(result: boolean): () => void {
  const orig = globalThis.confirm;
  globalThis.confirm = () => result;
  return () => { globalThis.confirm = orig; };
}

test("Test 31: delete-all confirm-CANCEL aborts with NO fetch + bucket intact (W2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "d1", status: "todo" }));

  const restore = stubConfirm(false);
  (root.querySelector(".jobs-bucket-todo .queue-delete-all-btn") as HTMLButtonElement).click();
  await flushMicrotasks();
  restore();

  assert.deepEqual(api.calls.filter(c => c.startsWith("DELETE ")), [], "no DELETE on cancel");
  assert.equal(jobs.bucket("todo").length, 1, "job still present after cancel");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 32: delete-all on RUNNING bucket → DELETE /api/queue/run/all + cleared; confirm carries interrupt warning (W2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "r1", status: "running" }));
  emitJobAdded(bus, makeJob({ id_hash: "r2", status: "running" }));

  let seen = "";
  const orig = globalThis.confirm;
  globalThis.confirm = (m?: string) => { seen = m ?? ""; return true; };
  (root.querySelector(".jobs-bucket-running .queue-delete-all-btn") as HTMLButtonElement).click();
  await flushMicrotasks();
  globalThis.confirm = orig;

  assert.match(seen, /running jobs \(2\)/, "count in confirm message");
  assert.match(seen, /interrupt active jobs/, "running carries the interrupt warning");
  assert.deepEqual(api.calls.filter(c => c.startsWith("DELETE ")), ["DELETE /api/queue/run/all"]);
  assert.equal(jobs.bucket("running").length, 0, "bucket cleared after 2xx");
  const bucketEl = root.querySelector('[data-bucket="running"]') as HTMLElement;
  assert.ok( bucketEl.querySelector(".jobs-bucket-empty") !== null, "re-rendered empty" );
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 33: delete-all on TODO bucket → DELETE /api/queue/todo/all; NO interrupt warning for non-running (W2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "t1", status: "todo" }));

  let seen = "";
  const orig = globalThis.confirm;
  globalThis.confirm = (m?: string) => { seen = m ?? ""; return true; };
  (root.querySelector(".jobs-bucket-todo .queue-delete-all-btn") as HTMLButtonElement).click();
  await flushMicrotasks();
  globalThis.confirm = orig;

  assert.doesNotMatch(seen, /interrupt/, "no interrupt warning for a non-running bucket");
  assert.deepEqual(api.calls.filter(c => c.startsWith("DELETE ")), ["DELETE /api/queue/todo/all"]);
  assert.equal(jobs.bucket("todo").length, 0, "bucket cleared after 2xx");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 34: delete-all on HISTORY bucket → DELETE /api/job-history/all?days=30 + refetch empties it (W2)", async () => {
  const bus   = createEventBusForTesting();
  const calls: string[] = [];
  let historyRows: Job[] = [
    { id_hash: "h1", job_type: "X", status: "completed", created_at: 1, completed_at: 2, meta: {} } as unknown as Job,
  ];
  const api: JobsPaneApiClient = {
    get: async <T>(path: string): Promise<T> => {
      calls.push(path);
      return { jobs: historyRows, total: historyRows.length } as unknown as T;
    },
    delete: async <T>(path: string): Promise<T> => {
      calls.push(`DELETE ${path}`);
      historyRows = [];          // server cleared → the refetch returns empty
      return null as T;
    },
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));   // initial hydrate
  assert.equal(jobs.bucket("history").length, 1, "history hydrated with 1");

  const restore = stubConfirm(true);
  (root.querySelector(".jobs-bucket-history .queue-delete-all-btn") as HTMLButtonElement).click();
  await new Promise(r => setTimeout(r, 30));   // delete + refetch
  restore();

  assert.ok(calls.includes("DELETE /api/job-history/all?days=30"), "windowed history delete-all endpoint");
  assert.ok(calls.some(c => c.startsWith("/api/job-history?days=30")), "refetched the same window");
  assert.equal(jobs.bucket("history").length, 0, "history empty after delete-all + refetch");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 35: delete-all 404 is treated as success — bucket cleared (W2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async (path) => { throw new ApiError(404, path, "not found"); });
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "x1", status: "done" }));
  assert.equal(jobs.bucket("done").length, 1);

  const restore = stubConfirm(true);
  (root.querySelector(".jobs-bucket-done .queue-delete-all-btn") as HTMLButtonElement).click();
  await flushMicrotasks();
  restore();

  assert.deepEqual(api.calls, ["/api/queue/done/all"]);
  assert.equal(jobs.bucket("done").length, 0, "404 cleared the bucket (treated as success)");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 36: delete-all 5xx leaves the bucket INTACT + logs (W2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async (path) => { throw new ApiError(500, path, "boom"); });
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "x1", status: "done" }));

  const origWarn = console.warn; let warned = false; console.warn = () => { warned = true; };
  const restore = stubConfirm(true);
  (root.querySelector(".jobs-bucket-done .queue-delete-all-btn") as HTMLButtonElement).click();
  await flushMicrotasks();
  restore(); console.warn = origWarn;

  assert.equal(warned, true, "5xx logged a warning");
  assert.equal(jobs.bucket("done").length, 1, "bucket intact on a non-404 error");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 37: delete-all non-ApiError (network) rejection leaves the bucket INTACT + logs (W2)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async () => { throw new Error("network down"); });
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "x1", status: "dead" }));

  const origWarn = console.warn; let warned = false; console.warn = () => { warned = true; };
  const restore = stubConfirm(true);
  (root.querySelector(".jobs-bucket-dead .queue-delete-all-btn") as HTMLButtonElement).click();
  await flushMicrotasks();
  restore(); console.warn = origWarn;

  assert.equal(warned, true, "network error logged a warning");
  assert.equal(jobs.bucket("dead").length, 1, "bucket intact on a non-ApiError rejection");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 38: delete-all on HISTORY with an ALL-TIME window → DELETE /api/job-history/all?days=all (W2)", async () => {
  const bus   = createEventBusForTesting();
  const calls: string[] = [];
  let historyRows: Job[] = [
    { id_hash: "h1", job_type: "X", status: "completed", created_at: 1, completed_at: 2, meta: {} } as unknown as Job,
  ];
  const api: JobsPaneApiClient = {
    get: async <T>(path: string): Promise<T> => {
      calls.push(path);
      return { jobs: historyRows, total: historyRows.length } as unknown as T;
    },
    delete: async <T>(path: string): Promise<T> => {
      calls.push(`DELETE ${path}`);
      historyRows = [];
      return null as T;
    },
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));            // mount hydrate → window = 30

  // Simulate the W3 time-window select switching to all-time (days omitted →
  // historyWindowDays() === undefined) so delete-all takes the all-time branch.
  await jobs.hydrateHistory(api, { days: undefined, append: false });
  assert.equal(jobs.historyWindowDays(), undefined, "window is now all-time");

  const restore = stubConfirm(true);
  (root.querySelector(".jobs-bucket-history .queue-delete-all-btn") as HTMLButtonElement).click();
  await new Promise(r => setTimeout(r, 30));            // delete + refetch
  restore();

  assert.ok(calls.includes("DELETE /api/job-history/all?days=all"), "all-time delete-all endpoint uses days=all");
  assert.equal(jobs.bucket("history").length, 0, "history empty after all-time delete-all");
  renderer.unmount(); jobs.disposeForTesting();
});

// =============================================================================
// W3 — history time-window <select> change → REPLACE-fetch the new window
// =============================================================================

test("Test 39: changing the history time-window select refetches that window (W3)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));   // mount hydrate (window 30)

  const select = root.querySelector(".jobs-bucket-history .history-time-select") as HTMLSelectElement;
  select.value = "7";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await new Promise(r => setTimeout(r, 20));

  assert.ok(api.calls.some(c => c === "/api/job-history?days=7&limit=20&offset=0"), "refetched the days=7 window");
  assert.equal(jobs.historyWindowDays(), 7, "store window updated to 7");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 40: selecting 'all time' refetches with NO days param (all-time) (W3)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));

  const select = root.querySelector(".jobs-bucket-history .history-time-select") as HTMLSelectElement;
  select.value = "all";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await new Promise(r => setTimeout(r, 20));

  assert.ok(api.calls.some(c => c === "/api/job-history?limit=20&offset=0"), "all-time omits the days param");
  assert.equal(jobs.historyWindowDays(), undefined);
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 41: a change event on a non-select element is a no-op (W3 guard)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));
  const before = api.calls.length;

  (root.querySelector("#jobs-buckets-container") as HTMLElement).dispatchEvent(new Event("change", { bubbles: true }));
  await flushMicrotasks();

  assert.equal(api.calls.length, before, "a change outside the time-window select triggers no fetch");
  renderer.unmount(); jobs.disposeForTesting();
});

// =============================================================================
// W4 — history Load-More pagination (append at the tracked cursor)
// =============================================================================

test("Test 42: Load-More appends the next page at the tracked cursor (W4)", async () => {
  const bus   = createEventBusForTesting();
  const calls: string[] = [];
  let page = 0;
  const api: JobsPaneApiClient = {
    get: async <T>(path: string): Promise<T> => {
      calls.push(path);
      const id = `h-${page++}`;                     // distinct row per page
      return { jobs: [ { id_hash: id, job_type: "X", status: "completed", created_at: 1, completed_at: 2, meta: {} } ], total: 5 } as unknown as T;
    },
    delete: async <T>(): Promise<T> => null as T,
  };
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));   // mount hydrate → loaded 1 < total 5

  const loadMore = root.querySelector(".jobs-bucket-history .history-load-more") as HTMLButtonElement;
  assert.notEqual(loadMore, null, "Load-More present when loaded < total");
  loadMore.click();
  await new Promise(r => setTimeout(r, 20));

  assert.ok(calls.some(c => c === "/api/job-history?days=30&limit=20&offset=1"), "appended at offset=1");
  assert.equal(jobs.bucket("history").length, 2, "second page appended (dedup by id)");
  renderer.unmount(); jobs.disposeForTesting();
});

// =============================================================================
// W5 — per-job retry ↻ (confirm-gated POST; WS repopulates live buckets)
// =============================================================================

test("Test 43: retry ↻ renders on dead + history cards, NOT on live todo/running/done cards (W5)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi([
    { id_hash: "hist-1", job_type: "X", status: "completed", created_at: 1, completed_at: 2, meta: {} } as unknown as Job,
  ]);
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);
  await new Promise(r => setTimeout(r, 20));   // history hydrate → hist-1 in history
  emitJobAdded(bus, makeJob({ id_hash: "dead-1", status: "dead" }));
  emitJobAdded(bus, makeJob({ id_hash: "run-1",  status: "running" }));

  const deadCard = root.querySelector('[data-bucket="dead"] .job-card') as HTMLElement;
  const runCard  = root.querySelector('[data-bucket="running"] .job-card') as HTMLElement;
  const histCard = root.querySelector('[data-bucket="history"] .job-card') as HTMLElement;
  assert.ok( deadCard.querySelector(".job-retry-button") !== null, "dead card has retry" );
  assert.ok( histCard.querySelector(".job-retry-button") !== null, "history card has retry" );
  assert.ok( runCard.querySelector(".job-retry-button") === null, "running (live) card has no retry" );
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 44: retry click confirm → POST /api/v2/ask re-asking the stored question with the wired websocket_id (W5)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api, websocketId: "wise-penguin" });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "dead-1", status: "dead", meta: { question_text: "what is 2 + 2?" } }));

  const restore = stubConfirm(true);
  (root.querySelector('[data-bucket="dead"] .job-retry-button') as HTMLButtonElement).click();
  await flushMicrotasks();
  restore();

  // The door moved AND the body changed shape: the retired /api/job-history/{id}/retry
  // sent only a websocket_id because the SERVER held the question. /api/v2/ask is a
  // question door, so the client now sends the question it holds.
  assert.ok(
    api.calls.some(c => c === 'POST /api/v2/ask {"question":"what is 2 + 2?","websocket_id":"wise-penguin"}'),
    "retry re-asks the stored question and carries the wired websocket_id",
  );
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 45: retry without a wired websocketId sends websocket_id:'' (W5 fallback)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });   // no websocketId
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "dead-1", status: "dead", meta: { question_text: "what is 2 + 2?" } }));

  const restore = stubConfirm(true);
  (root.querySelector('[data-bucket="dead"] .job-retry-button') as HTMLButtonElement).click();
  await flushMicrotasks();
  restore();

  assert.ok(
    api.calls.some(c => c === 'POST /api/v2/ask {"question":"what is 2 + 2?","websocket_id":""}'),
    "retry falls back to an empty websocket_id",
  );
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 45b: a card with no stored question does not POST and does not prompt (2026-08-21 cutover)", async () => {
  // The retry door used to work from the id alone — the server looked the question up.
  // Now the client re-asks, so a card whose row carries no question text has nothing to
  // send. Posting an empty question would be rejected at the door with nothing useful to
  // show; warn and stop instead. Reachable for a card built from a WebSocket event rather
  // than a hydrated history row.
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api, websocketId: "wise-penguin" });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "dead-1", status: "dead", meta: {} }));

  let prompted = false;
  const restore = stubConfirm(true);
  const realConfirm = globalThis.confirm;
  globalThis.confirm = ((msg?: string) => { prompted = true; return realConfirm(msg as string); }) as typeof globalThis.confirm;
  (root.querySelector('[data-bucket="dead"] .job-retry-button') as HTMLButtonElement).click();
  await flushMicrotasks();
  globalThis.confirm = realConfirm;
  restore();

  assert.deepEqual(api.calls.filter(c => c.startsWith("POST ")), [], "no POST without a question");
  assert.equal(prompted, false, "no confirm dialog either — there is nothing to confirm");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 46: retry confirm-CANCEL aborts with no POST (W5)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api, websocketId: "wise-penguin" });
  const root = makeRoot();
  renderer.mount(root);
  emitJobAdded(bus, makeJob({ id_hash: "dead-1", status: "dead", meta: { question_text: "what is 2 + 2?" } }));

  const restore = stubConfirm(false);
  (root.querySelector('[data-bucket="dead"] .job-retry-button') as HTMLButtonElement).click();
  await flushMicrotasks();
  restore();

  assert.deepEqual(api.calls.filter(c => c.startsWith("POST ")), [], "no POST on cancel");
  renderer.unmount(); jobs.disposeForTesting();
});

test("Test 47: retry POST failure logs + changes nothing (W5)", async () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi([], async (path) => { throw new ApiError(500, path, "boom"); });
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api, websocketId: "wise-penguin" });
  const root = makeRoot();
  renderer.mount(root);
  // The question is REQUIRED for this test to test what it says. After the 2026-08-21
  // cutover the click returns early — warning, and changing nothing — when the row has
  // no question text, which would satisfy both assertions below without a POST ever
  // being attempted. Caught by running it: the test stayed green while covering the
  // wrong branch.
  emitJobAdded(bus, makeJob({ id_hash: "dead-1", status: "dead", meta: { question_text: "what is 2 + 2?" } }));

  const origWarn = console.warn; let warned = false; console.warn = () => { warned = true; };
  const restore = stubConfirm(true);
  (root.querySelector('[data-bucket="dead"] .job-retry-button') as HTMLButtonElement).click();
  await flushMicrotasks();
  restore(); console.warn = origWarn;

  // makeControllableApi records the bare path (makeStubApi records "POST <path> <body>").
  assert.ok(
    api.calls.includes("/api/v2/ask"),
    "the retry must actually have been attempted — otherwise this test passes on the no-question early return",
  );
  assert.equal(warned, true, "retry failure logged");
  assert.equal(jobs.bucket("dead").length, 1, "dead card still present after a failed retry");
  renderer.unmount(); jobs.disposeForTesting();
});

// =============================================================================
// W6 — queues filter-badge (static hidden plan-08 seam)
// =============================================================================

test("Test 48: jobs-pane header renders a hidden static queues-filter-badge (W6 plan-08 seam)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  const badge = root.querySelector('[data-testid="queues-filter-badge"]') as HTMLElement;
  assert.notEqual(badge, null, "filter badge present in the jobs-pane header");
  assert.ok(badge.classList.contains("queues-filter-badge"));
  assert.equal(badge.hidden, true, "badge ships hidden (static seam, inert under D1)");
  assert.equal(badge.textContent, "👤 Mine", "default-Mine label");
  renderer.unmount(); jobs.disposeForTesting();
});
