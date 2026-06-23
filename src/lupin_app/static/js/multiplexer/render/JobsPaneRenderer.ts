/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6a + 6b — JobsPaneRenderer.
//
// Mirrors the Phase 5 NotificationsListRenderer lifecycle pattern (mount/
// unmount/forceRenderForTesting + unsubscribers array + delegated click
// handler on the mount root). Per design doc 08 (+ Phase 6b extension):
//
//   - Subscribes to `store_jobs_changed` via EventBus
//   - Hybrid render strategy (Q-B adapted for 5 buckets):
//       changeKind: "hydrated"   → full rebuild of history bucket only
//       changeKind: "added"      → re-render the affected bucket
//       changeKind: "transitioned" → re-render `from` and `to` buckets
//       changeKind: "removed"    → re-render `from` bucket (and history if landed)
//   - Eager hydration on mount (Q-A7): floats stores.jobs.hydrateHistory(api).catch(...)
//     so mount() returns immediately; rejection emits `hydration_failed`
//     with `source: "jobs"` (Pass 1 F3)
//   - Per Pass 2 F26: mount() throws on second mount without intervening
//     unmount() so duplicate-listener bugs surface at the call site
//   - Phase 6b: card-header click delegation dispatches `.job-delete-button`
//     clicks to the optimistic-delete flow (Q-B10) BEFORE the card-header
//     toggle path so the delete button never accidentally toggles the card
//     (preserving Pass 2 F23 invariant under the new active-button semantics).
//   - Per Pass 2 F4: narrow `{ jobs: JobStore }` stores option (NOT full
//     StoreSet); throws at construction if `stores.jobs` is falsy
//   - Per Pass 2 F25: optional `appTimezone` threads into bucket templates
//     for TZ-aware bucket-header date display when surfaced
//   - Phase 6b: after each renderAll(), strips Q-A6 inertness markers
//     (`aria-disabled`, `tabindex`, `title`) from all `.job-delete-button`
//     elements so AC2a/AC2b grep guards return zero hits post-mount.

import type { EventBus } from "../shared/EventBus";
import type {
  JobBucket,
  JobStatus,
  StoreJobsChangedPayload,
  HydrationFailedPayload,
  LupinEvent,
} from "../shared/types";
import type { JobStore, JobHistoryApiClient } from "../stores/JobStore";
import { ApiError } from "../api/ApiClient";
import { renderJobBucket } from "./templates/jobBucket";
import { populateJobMetaIfNeeded } from "./templates/jobCard";

// ---------------------------------------------------------------------------
// Public interfaces
// ---------------------------------------------------------------------------

export interface JobsPaneRenderer {
  /**
   * Attach to a root DOM node. Per Pass 2 F26: throws Error
   * "JobsPaneRenderer already mounted" on second call without intervening
   * unmount(). Throws if `#jobs-buckets-container` is missing inside `root`.
   */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe all listeners + clear mount points. Idempotent. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

export interface JobsPaneRendererStores {
  jobs : JobStore;
}

/**
 * Phase 6b: superset of `JobHistoryApiClient` adding the `delete<T>` method
 * required by the Q-B10 optimistic-delete flow. Production code passes the
 * canonical `ApiClient` (from `api/ApiClient.ts`) which satisfies both
 * interfaces structurally. Tests pass a stub with `get` + `delete`.
 */
export interface JobsPaneApiClient extends JobHistoryApiClient {
  delete<T>(path: string): Promise<T>;
}

export interface JobsPaneRendererOptions {
  eventBus     : EventBus;
  stores       : JobsPaneRendererStores;
  api          : JobsPaneApiClient;
  /**
   * Per Pass 2 F25: TZ-aware bucket-header date display. Threaded into
   * `formatHM` / `formatDateKey` call sites in jobBucket.ts. Falls back to
   * browser-local TZ when undefined (matches the existing time.ts contract).
   */
  appTimezone? : string;
}

// ---------------------------------------------------------------------------
// All 5 buckets in render order
// ---------------------------------------------------------------------------

const ALL_BUCKETS: ReadonlyArray<JobBucket> = ["todo", "running", "done", "dead", "history"];

// Phase 6b — UI status → server queue-name mapping for the DELETE endpoint
// at `cosa/rest/routers/queues.py:1188`. Note the `running` → `run` collapse:
// the server queue is named `run` (legacy) but the UI bucket is `running`.
const UI_STATUS_TO_SERVER_QUEUE: Record<JobStatus, string> = {
  todo    : "todo",
  running : "run",
  done    : "done",
  dead    : "dead",
};

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class JobsPaneRendererImpl implements JobsPaneRenderer {
  private readonly bus           : EventBus;
  private readonly stores        : JobsPaneRendererStores;
  private readonly api           : JobsPaneApiClient;
  private readonly appTimezone   : string | undefined;
  private readonly unsubscribers : Array<() => void> = [];

  private mounted        : boolean = false;
  private root           : HTMLElement | null = null;
  private bucketsMount   : HTMLElement | null = null;
  private clickHandler   : ((e: Event) => void) | null = null;

  // The visible hydration-failure banner (null when no failure is showing).
  // Tracked so repeated failures replace rather than stack, and so unmount
  // tears it down with the rest of the pane.
  private hydrationErrorEl : HTMLElement | null = null;

  // Phase 6b — idHashes of jobs whose DELETE is in flight. Rapid double-click
  // on the same `.job-delete-button` is gated by this set (5B-7); the entry
  // is removed in the .finally() of the apiClient.delete promise chain.
  private readonly deleteInFlight: Set<string> = new Set();

  constructor(opts: JobsPaneRendererOptions) {
    // Pass 2 F4: fail fast at construction if stores.jobs is missing.
    if (!opts.stores || !opts.stores.jobs) {
      throw new Error("JobsPaneRenderer requires stores.jobs to be initialized");
    }
    this.bus         = opts.eventBus;
    this.stores      = opts.stores;
    this.api         = opts.api;
    this.appTimezone = opts.appTimezone;
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  mount(root: HTMLElement): void {
    // Pass 2 F26: idempotency guard — second mount without intervening unmount
    // throws so duplicate-listener bugs surface at the call site that caused
    // them (typical sources: Vite/HMR re-running boot.ts, tests forgetting
    // unmount() between fixtures).
    if (this.mounted) {
      throw new Error("JobsPaneRenderer already mounted");
    }
    const bucketsMount = root.querySelector("#jobs-buckets-container") as HTMLElement | null;
    if (bucketsMount === null) {
      throw new Error("JobsPaneRenderer.mount: #jobs-buckets-container not found inside root");
    }
    this.root         = root;
    this.bucketsMount = bucketsMount;
    this.mounted      = true;

    // Lift the data-phase6-pending sentinel + hidden attribute from #jobs-pane
    // (the design contract for Phase 6a — `data-phase6-pending` stays on
    // #tts-pane until 6b lands).
    root.removeAttribute("hidden");
    root.removeAttribute("data-phase6-pending");

    this.attachClickDelegation();
    this.subscribe();
    this.renderAll();

    // Q-A7 — eager hydration. Float the promise; mount returns immediately.
    this.hydrateWithFailureSignal();
  }

  // Eager hydration with a fail-loud UI signal. Floats the hydrate promise so
  // mount() (and the Retry affordance) return immediately; a rejection is
  // (a) caught so no unhandled-rejection event ever fires (Pass 1 F3) and
  // (b) re-published as `hydration_failed { source: "jobs" }` so
  // onHydrationFailed paints the visible Retry banner. Extracted so mount()
  // and the Retry button share ONE hydrate path.
  private hydrateWithFailureSignal(): void {
    this.stores.jobs.hydrateHistory(this.api).catch((err: unknown) => {
      const error = err instanceof Error ? err : new Error(String(err));
      console.warn("JobsPaneRenderer: hydrateHistory rejected:", error);
      this.bus.emit<HydrationFailedPayload>({
        type    : "hydration_failed",
        payload : { source: "jobs", error },
        source  : "JobsPaneRenderer",
        ts      : Date.now(),
      });
    });
  }

  unmount(): void {
    if (!this.mounted) return;   // idempotent

    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    this.clearHydrationError();

    if (this.clickHandler !== null && this.root !== null) {
      this.root.removeEventListener("click", this.clickHandler);
    }
    this.clickHandler = null;

    if (this.bucketsMount !== null) this.bucketsMount.replaceChildren();
    this.bucketsMount = null;
    this.root         = null;
    this.mounted      = false;
  }

  forceRenderForTesting(): void {
    this.renderAll();
  }

  // -------------------------------------------------------------------------
  // Subscriptions
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<StoreJobsChangedPayload>(
        "store_jobs_changed",
        (e) => this.onJobsChanged(e),
      ),
    );
    // hydration_failed CONSUMER. Before this, the event had ZERO subscribers,
    // so a hydrate failure was invisible to the user (only a console.warn).
    // JobsPaneRenderer is both the emitter (its floated hydrateHistory
    // rejection) AND the natural consumer: it owns the jobs-pane DOM, so it is
    // where a "Could not load job history" + Retry affordance belongs (the
    // 6b retry affordance the emit site always anticipated).
    this.unsubscribers.push(
      this.bus.on<HydrationFailedPayload>(
        "hydration_failed",
        (e) => this.onHydrationFailed(e),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // hydration_failed consumer — visible fail-loud affordance + Retry
  // -------------------------------------------------------------------------

  private onHydrationFailed(e: LupinEvent<HydrationFailedPayload>): void {
    // Only OUR source. Other renderers' hydrate failures (future) carry a
    // different `source` and are surfaced by their own consumers.
    if (e.payload.source !== "jobs") return;
    this.renderHydrationError(e.payload.error);
  }

  private renderHydrationError(error: Error): void {
    /* c8 ignore next */ // defensive: the hydration_failed listener is detached in unmount() BEFORE root is nulled, so onHydrationFailed cannot fire with a null root via the bus; this guards only a synthetic direct call.
    if (this.root === null || this.bucketsMount === null) return;
    // Replace any prior banner so repeated failures don't stack.
    this.clearHydrationError();

    const banner = document.createElement("div");
    banner.className = "jobs-hydration-error";
    banner.setAttribute("role", "alert");
    banner.setAttribute("aria-live", "polite");

    const message = document.createElement("span");
    message.className = "jobs-hydration-error-message";
    message.textContent = `Could not load job history: ${error.message}`;
    banner.appendChild(message);

    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "jobs-hydration-retry";
    retry.textContent = "Retry";
    banner.appendChild(retry);

    // Banner sits at the top of the pane, above the buckets.
    this.root.insertBefore(banner, this.bucketsMount);
    this.hydrationErrorEl = banner;
  }

  private clearHydrationError(): void {
    if (this.hydrationErrorEl !== null) {
      this.hydrationErrorEl.remove();
      this.hydrationErrorEl = null;
    }
  }

  private handleRetryClick(): void {
    // Clear the banner immediately; a fresh failure re-emits hydration_failed
    // (→ onHydrationFailed repaints it), a success leaves it cleared.
    this.clearHydrationError();
    this.hydrateWithFailureSignal();
  }

  private onJobsChanged(_e: LupinEvent<StoreJobsChangedPayload>): void {
    // Phase 6a render strategy (Q-B adapted): for any changeKind, full
    // re-render is correct + cheap (5 buckets × small N each). Future
    // optimization may target only the affected bucket(s) per changeKind,
    // but Phase 4 stores already dedup + the templates are pure, so a full
    // re-render is structurally identical to per-bucket diffing.
    this.renderAll();
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  private renderAll(): void {
    /* c8 ignore next */ // defensive: bucketsMount post-mount is always set; subscriptions are detached in unmount BEFORE this null happens.
    if (this.bucketsMount === null) return;

    // Build all 5 buckets in render order. Each bucket is rendered fresh from
    // the JobStore — Phase 4 reducers keep the bucket arrays canonical, so
    // we just snapshot them.
    const buckets = ALL_BUCKETS.map(name => ({
      name,
      jobs : this.stores.jobs.bucket(name),
    }));

    // Replace the buckets container's children atomically. Single
    // replaceChildren call → single layout flush.
    const fragments = buckets.map(b =>
      renderJobBucket(b.name, b.jobs, { appTimezone: this.appTimezone })
    );
    this.bucketsMount.replaceChildren(...fragments);

    // Phase 6b — strip Q-A6 inertness markers from every `.job-delete-button`
    // so AC2a/AC2b grep guards return zero hits post-mount (5B-9).
    this.stripInertnessMarkers();
  }

  private stripInertnessMarkers(): void {
    /* c8 ignore next */ // defensive: bucketsMount is null only between unmount and re-mount; renderAll's null-guard above prevents this branch.
    if (this.bucketsMount === null) return;
    const buttons = this.bucketsMount.querySelectorAll(".job-delete-button");
    for (const btn of Array.from(buttons)) {
      btn.removeAttribute("aria-disabled");
      btn.removeAttribute("tabindex");
      btn.removeAttribute("title");
    }
  }

  // -------------------------------------------------------------------------
  // Click delegation — delete-button (Phase 6b) + card-header toggle (Phase 6a)
  // -------------------------------------------------------------------------

  private attachClickDelegation(): void {
    /* c8 ignore next */ // defensive: root post-mount is always set; this method runs from mount() after root is wired.
    if (this.root === null) return;
    this.clickHandler = (e: Event) => {
      const target = e.target as Element | null;
      /* c8 ignore next */ // defensive: browser-dispatched click events always carry a target; null-target is unreachable from real user input but guards against synthetic events constructed without a target.
      if (target === null) return;
      // hydration_failure Retry dispatch BEFORE the job paths — the banner
      // lives above the buckets and carries no .job-card, but ordering it
      // first keeps the intent explicit.
      const retryButton = target.closest(".jobs-hydration-retry") as HTMLElement | null;
      if (retryButton !== null) {
        this.handleRetryClick();
        return;
      }
      // Phase 6b — delete-button dispatch BEFORE the card-header toggle path
      // so the Q-B10 optimistic-delete flow fires and the toggle never does
      // (preserves the Pass 2 F23 invariant under active-button semantics).
      const deleteButton = target.closest(".job-delete-button") as HTMLElement | null;
      if (deleteButton !== null) {
        this.handleDeleteClick(deleteButton);
        return;
      }
      // Pass 2 F23 — query by class, NOT by attribute, so the
      // delete-button-vs-card data-id-hash collision can never resurface.
      const card = target.closest(".job-card") as HTMLElement | null;
      if (card === null) return;
      // Only the card HEADER toggles; clicks on the details body are passive.
      if (target.closest(".job-card-header") === null) return;

      const details = card.querySelector(".job-card-details") as HTMLElement | null;
      /* c8 ignore next */ // defensive: details child is guaranteed by the renderJobCard template invariant.
      if (details === null) return;

      // Lazy-render meta on first expand (the WeakSet inside jobCard.ts
      // dedups subsequent calls, so this is safe to invoke on every click).
      const idHash = card.getAttribute("data-id-hash");
      if (idHash !== null) {
        const job = this.stores.jobs.getById(idHash);
        populateJobMetaIfNeeded(card, job?.meta ?? {});
      }

      details.classList.toggle("collapsed");
    };
    this.root.addEventListener("click", this.clickHandler);
  }

  // -------------------------------------------------------------------------
  // Delete-button click flow (Q-B10 — optimistic + rollback)
  // -------------------------------------------------------------------------

  private handleDeleteClick(deleteButton: HTMLElement): void {
    const card = deleteButton.closest(".job-card") as HTMLElement | null;
    /* c8 ignore next */ // defensive: delete-button only ever lives inside .job-card per the template invariant.
    if (card === null) return;
    const idHash = card.getAttribute("data-id-hash");
    /* c8 ignore next */ // defensive: every .job-card carries data-id-hash per Pass 1 F12 + renderJobCard contract.
    if (idHash === null) return;
    // 5B-7: rapid double-click is a no-op for the second invocation.
    if (this.deleteInFlight.has(idHash)) return;

    const job = this.stores.jobs.getById(idHash);
    /* c8 ignore next */ // defensive: store-DOM consistency invariant — every rendered .job-card has a corresponding JobStore entry; reaching this branch would indicate a renderAll race that the synchronous bus contract precludes.
    if (job === undefined) return;
    const queueName = UI_STATUS_TO_SERVER_QUEUE[job.status];

    this.deleteInFlight.add(idHash);
    const { restoreState } = this.stores.jobs.delete(idHash);

    this.api.delete<unknown>(`/api/queue/${queueName}/${idHash}`)
      .then(() => {
        // 2xx → success path; restoreState discarded (5B-3).
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          // 404 → treated as success per Q-B10 (5B-4).
          return;
        }
        // 5xx or network error → rollback + inline error stripe (5B-5 / 5B-6).
        restoreState();
        this.renderErrorStripe(idHash, deriveErrorMessage(err));
      })
      .finally(() => {
        this.deleteInFlight.delete(idHash);
      });
  }

  private renderErrorStripe(idHash: string, message: string): void {
    /* c8 ignore next */ // defensive: bucketsMount is null only between unmount/re-mount; renderErrorStripe is invoked from the .catch microtask which would have to outlive an unmount — a race the test environment doesn't exercise but worth guarding.
    if (this.bucketsMount === null) return;
    // Lookup by dataset rather than CSS selector to sidestep idHash-escape
    // concerns. After restoreState() the renderAll has already painted the
    // restored card, so this query returns the new node.
    let target: HTMLElement | null = null;
    for (const card of Array.from(this.bucketsMount.querySelectorAll<HTMLElement>(".job-card"))) {
      if (card.dataset["idHash"] === idHash) {
        target = card;
        break;
      }
    }
    /* c8 ignore next */ // defensive: restoreState fires the "added" event synchronously which triggers renderAll, so the restored card is always in DOM by the time this microtask runs.
    if (target === null) return;
    // No pre-existing stripe to clear: the .catch's restoreState() call above
    // synchronously emits "added" → renderAll rebuilds this card fresh before
    // we reach this point. Any prior stripe lives only on the now-detached node.
    const stripe = document.createElement("div");
    stripe.className = "job-card-error-stripe";
    stripe.setAttribute("role", "alert");
    stripe.setAttribute("aria-live", "polite");
    stripe.textContent = message;
    target.appendChild(stripe);
  }
}

// ---------------------------------------------------------------------------
// Helpers (module-private)
// ---------------------------------------------------------------------------

function deriveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return `Delete failed (HTTP ${err.status})`;
  if (err instanceof Error)    return `Delete failed: ${err.message}`;
  /* c8 ignore next */ // defensive: fetch / apiClient always reject with Error subclasses; this branch is a safety net for non-Error throws.
  return "Delete failed";
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Factory — production code constructs via `createJobsPaneRenderer`.
 * Matches Phase 5 `createNotificationsListRenderer` shape (RE-12).
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createJobsPaneRenderer(opts: JobsPaneRendererOptions): JobsPaneRenderer {
  return new JobsPaneRendererImpl(opts);
}
