/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6a — JobsPaneRenderer.
//
// Mirrors the Phase 5 NotificationsListRenderer lifecycle pattern (mount/
// unmount/forceRenderForTesting + unsubscribers array + delegated click
// handler on the mount root). Per design doc 08:
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
//   - Per Pass 2 F23: card-header click delegation early-returns when
//     target.closest(".job-delete-button") matches so the disabled `×`
//     never accidentally toggles the card
//   - Per Pass 2 F4: narrow `{ jobs: JobStore }` stores option (NOT full
//     StoreSet); throws at construction if `stores.jobs` is falsy
//   - Per Pass 2 F25: optional `appTimezone` threads into bucket templates
//     for TZ-aware bucket-header date display when surfaced

import type { EventBus } from "../shared/EventBus";
import type {
  JobBucket,
  StoreJobsChangedPayload,
  HydrationFailedPayload,
  LupinEvent,
} from "../shared/types";
import type { JobStore, JobHistoryApiClient } from "../stores/JobStore";
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

export interface JobsPaneRendererOptions {
  eventBus     : EventBus;
  stores       : JobsPaneRendererStores;
  api          : JobHistoryApiClient;
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

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class JobsPaneRendererImpl implements JobsPaneRenderer {
  private readonly bus           : EventBus;
  private readonly stores        : JobsPaneRendererStores;
  private readonly api           : JobHistoryApiClient;
  private readonly appTimezone   : string | undefined;
  private readonly unsubscribers : Array<() => void> = [];

  private mounted        : boolean = false;
  private root           : HTMLElement | null = null;
  private bucketsMount   : HTMLElement | null = null;
  private clickHandler   : ((e: Event) => void) | null = null;

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
    // Pass 1 F3 — wrap the rejection in a `.catch(...)` so unhandled-rejection
    // events never fire, and emit `hydration_failed` so a future 6b retry
    // affordance can subscribe.
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
  }

  // -------------------------------------------------------------------------
  // Click delegation — `.job-card-header` click toggles details + lazy-render
  // -------------------------------------------------------------------------

  private attachClickDelegation(): void {
    /* c8 ignore next */ // defensive: root post-mount is always set; this method runs from mount() after root is wired.
    if (this.root === null) return;
    this.clickHandler = (e: Event) => {
      const target = e.target as Element | null;
      /* c8 ignore next */ // defensive: browser-dispatched click events always carry a target; null-target is unreachable from real user input but guards against synthetic events constructed without a target.
      if (target === null) return;
      // Pass 2 F23 (programmatic enforcement of disabled-delete-button no-op):
      // bail BEFORE the card-header detection so a click on the disabled `×`
      // never propagates into the toggle path.
      if (target.closest(".job-delete-button") !== null) return;
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
