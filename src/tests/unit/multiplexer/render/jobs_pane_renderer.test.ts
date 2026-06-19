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
// Test 3-4: Lifecycle — mount lifts hidden + data-phase6-pending; unmount idempotent
// ---------------------------------------------------------------------------

test("Test 3: mount() lifts hidden + data-phase6-pending from #jobs-pane", () => {
  const bus  = createEventBusForTesting();
  const api  = makeStubApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  assert.equal(root.hasAttribute("hidden"), true);
  assert.equal(root.getAttribute("data-phase6-pending"), "true");
  renderer.mount(root);
  assert.equal(root.hasAttribute("hidden"), false);
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
  assert.equal(container.querySelector(".external-tampering"), null);
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
// Test 18: disabled-delete-button click no-op (Pass 2 F23 — programmatic enforcement)
// ---------------------------------------------------------------------------

test("Test 18: click on disabled .job-delete-button does NOT toggle the card (Pass 2 F23)", () => {
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
  const pre     = card.querySelector(".job-meta-json") as HTMLPreElement;

  // Initial state: collapsed, hidden pre.
  assert.ok(details.classList.contains("collapsed"));
  assert.equal(pre.hasAttribute("hidden"), true);

  // Click the disabled × button 3 times.
  button.click();
  button.click();
  button.click();

  // No state change.
  assert.ok(details.classList.contains("collapsed"), "details should remain collapsed");
  assert.equal(pre.hasAttribute("hidden"), true,    "pre should remain hidden");
  assert.equal(pre.textContent, "",                 "pre should remain empty");

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
  assert.equal(root.querySelector('[data-id-hash="del-22"]'), null, "card stays gone");

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
  assert.equal(root.querySelector('[data-id-hash="del-23"]'), null);
  // No error stripe rendered on success-path 404.
  assert.equal(root.querySelector(".job-card-error-stripe"), null);

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
// Test 28 (5B-9): Q-A6 inertness markers stripped from `.job-delete-button`.
// ---------------------------------------------------------------------------

test("Test 28: inertness markers stripped from .job-delete-button post-render (5B-9)", () => {
  const bus  = createEventBusForTesting();
  const api  = makeControllableApi();
  const jobs = createJobStore({ bus });
  const renderer = createJobsPaneRenderer({ eventBus: bus, stores: { jobs }, api });
  const root = makeRoot();
  renderer.mount(root);

  emitJobAdded(bus, makeJob({ id_hash: "del-28a", status: "running" }));
  emitJobAdded(bus, makeJob({ id_hash: "del-28b", status: "done" }));

  // No `aria-disabled="true"` should remain on any delete button after render.
  assert.equal(
    root.querySelector('.job-delete-button[aria-disabled="true"]'),
    null,
    "aria-disabled='true' should be stripped",
  );
  // No "Delete coming in Phase 6b" title should remain.
  assert.equal(
    root.querySelector('.job-delete-button[title="Delete coming in Phase 6b"]'),
    null,
    "Phase 6b placeholder title should be stripped",
  );
  // tabindex=-1 is also stripped (was part of the disabled state).
  assert.equal(
    root.querySelector('.job-delete-button[tabindex="-1"]'),
    null,
    "tabindex='-1' should be stripped",
  );

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
