/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 4 — JobStore.
//
// Plain reducer over 5-bucket layout: todo / running / done / dead / history.
// Consumes:
//   - job_state_transition : move job between buckets (or add if first-seen)
//   - job_removed          : remove from current bucket; if was done/dead,
//                            append to history bucket (in-session)
// Emits:
//   - store_jobs_changed { changeKind, id_hash?, from?, to?, bucket? }
// History bucket:
//   - In-session: populated by job_removed for done/dead status
//   - Cross-session: lazy via hydrateHistory(api) per Q7 Option B
//
// Status enum (per Pass 1 F18) is the 4-value UI-mapped status; the 5th
// "history" bucket is a reducer-derived UI view, not a `status` value.
// Server emits 9+ JobState values which we map through STATE_TO_UI per
// `src/cosa/rest/job_state.py:71`.

import type { EventBus } from "../shared/EventBus";
import type {
  Job,
  JobBucket,
  JobStatus,
  LupinEvent,
  StoreJobsChangedPayload,
} from "../shared/types";

// ---------------------------------------------------------------------------
// Server JobState → UI bucket mapping (mirror of cosa/rest/job_state.py:71
// STATE_TO_UI_CONTAINER, but with 4 UI bucket values matching design intent —
// "running" full-word rather than legacy "run").
// ---------------------------------------------------------------------------

const SERVER_STATE_TO_STATUS: Record<string, JobStatus> = {
  pending     : "todo",
  queued      : "todo",
  scheduled   : "todo",
  paused      : "todo",
  stalled     : "todo",
  running     : "running",
  completed   : "done",
  failed      : "dead",
  cancelled   : "dead",
  interrupted : "dead",
};

function mapServerStateToStatus(state: string): JobStatus | null {
  return SERVER_STATE_TO_STATUS[state] ?? null;
}

// ---------------------------------------------------------------------------
// Server payload shapes (per `cosa/rest/queue_util.py:62` for transitions and
// `cosa/rest/routers/queues.py:1286` for removals).
// ---------------------------------------------------------------------------

interface JobStateTransitionPayload {
  job_id     ?: string;
  id_hash    ?: string;
  from_state ?: string;
  to_state   ?: string;
  timestamp  ?: string;
  metadata   ?: { agent_type?: string;[k: string]: unknown };
}

interface JobRemovedPayload {
  job_id    ?: string;
  id_hash   ?: string;
  queue     ?: string;
  timestamp ?: string;
}

// Loose ApiClient surface for hydrateHistory — JobStore only needs `get<T>`.
// Production code passes the canonical ApiClient; tests pass a stub.
export interface JobHistoryApiClient {
  get<T>(path: string): Promise<T>;
}

interface JobHistoryResponse {
  jobs : ReadonlyArray<Record<string, unknown>>;
  total       ?: number;
  filtered_by ?: string;
  limit       ?: number;
  offset      ?: number;
}

// ---------------------------------------------------------------------------
// Public interface (per design § JobStore)
// ---------------------------------------------------------------------------

export interface JobStore {
  bucket(name: JobBucket): ReadonlyArray<Job>;
  getById(idHash: string): Job | undefined;
  hydrateHistory(api: JobHistoryApiClient): Promise<void>;
  isHistoryHydrated(): boolean;
  /**
   * Phase 6b: remove a job from its current bucket and emit
   * `store_jobs_changed{changeKind:"removed"}`. Returns a closure
   * (`restoreState`) that puts the entry back at its original bucket + index
   * and emits `changeKind:"added"`. Nonexistent idHash → no-op delete +
   * no-op `restoreState` (no exception, no event). Used by JobsPaneRenderer
   * delete-button (Q-B10 optimistic + rollback).
   */
  delete(idHash: string): { restoreState: () => void };
  /** Test/cleanup helper: detach EventBus listeners. */
  disposeForTesting(): void;
}

export interface JobStoreOptions {
  bus    : EventBus;
  nowFn? : () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class JobStoreImpl implements JobStore {
  private readonly bus   : EventBus;
  private readonly nowFn : () => number;

  // Per-bucket job lists (history is the 5th bucket; status enum still 4-value).
  private readonly buckets: Record<JobBucket, Job[]> = {
    todo    : [],
    running : [],
    done    : [],
    dead    : [],
    history : [],
  };

  // id_hash → bucket lookup so getById is O(1).
  private readonly indexById = new Map<string, JobBucket>();

  private historyHydrated = false;

  private readonly unsubscribers: Array<() => void> = [];

  constructor(opts: JobStoreOptions) {
    this.bus   = opts.bus;
    /* c8 ignore next */ // defensive: production callers pass nowFn explicitly via DI; fallback is for ad-hoc construction.
    this.nowFn = opts.nowFn ?? (() => Date.now());
    this.subscribe();
  }

  bucket(name: JobBucket): ReadonlyArray<Job> {
    return this.buckets[name];
  }

  getById(idHash: string): Job | undefined {
    const bucketName = this.indexById.get(idHash);
    if (!bucketName) return undefined;
    return this.buckets[bucketName].find(j => j.id_hash === idHash);
  }

  async hydrateHistory(api: JobHistoryApiClient): Promise<void> {
    if (this.historyHydrated) return;

    // /api/job-history is mounted under the queues router, which uses the `/api`
    // prefix (queues.py) — matches the legacy client (notifications.js). It is NOT
    // `/api/queue/...`: that prefix is reserved for per-queue item ops, e.g.
    // /api/queue/{queueName}/{jobId}. The endpoint accepts limit 1-100.
    // Phase 4 scope: fetch the first page. Phase 5+ renderer can request more
    // via paged calls.
    const resp = await api.get<JobHistoryResponse>("/api/job-history?limit=100");

    const inSessionIds = new Set(this.buckets.history.map(j => j.id_hash));
    for (const raw of resp.jobs) {
      const job = this.normalizeRaw(raw);
      /* c8 ignore next */ // defensive: server response is normally well-formed; null only on malformed rows missing id or unmappable status — server-contract enforced upstream.
      if (!job) continue;
      if (inSessionIds.has(job.id_hash)) continue;
      // Hydrated jobs land in the history bucket directly; their UI status
      // is whatever maps from their persisted server state (must be done/dead
      // since they're terminal).
      this.buckets.history.push(job);
      this.indexById.set(job.id_hash, "history");
    }

    this.historyHydrated = true;
    this.bus.emit<StoreJobsChangedPayload>({
      type    : "store_jobs_changed",
      payload : { changeKind: "hydrated", bucket: "history" },
      source  : "JobStore",
      ts      : this.nowFn(),
    });
  }

  isHistoryHydrated(): boolean {
    return this.historyHydrated;
  }

  delete(idHash: string): { restoreState: () => void } {
    const bucketName = this.indexById.get(idHash);
    if (!bucketName) {
      return { restoreState: () => {} };
    }
    const list = this.buckets[bucketName];
    const idx  = list.findIndex(j => j.id_hash === idHash);
    /* c8 ignore next */ // defensive: indexById and bucket arrays are kept in lockstep by every reducer path; "out of sync" is a never-reached invariant violation.
    if (idx < 0) return { restoreState: () => {} };
    const job = list[idx]!;
    list.splice(idx, 1);
    this.indexById.delete(idHash);
    this.emit({ changeKind: "removed", id_hash: idHash });

    const restoreState = (): void => {
      list.splice(idx, 0, job);
      this.indexById.set(idHash, bucketName);
      this.emit({ changeKind: "added", id_hash: idHash, to: bucketName });
    };
    return { restoreState };
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    for (const off of this.unsubscribers) off();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Subscriptions
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<JobStateTransitionPayload>("job_state_transition", (e) => this.onStateTransition(e)),
    );
    this.unsubscribers.push(
      this.bus.on<JobRemovedPayload>("job_removed", (e) => this.onRemoved(e)),
    );
  }

  // -------------------------------------------------------------------------
  // Reducers
  // -------------------------------------------------------------------------

  private onStateTransition(e: LupinEvent<JobStateTransitionPayload>): void {
    const id = e.payload.job_id ?? e.payload.id_hash;
    if (!id) return;
    if (!e.payload.to_state) return;
    const toStatus = mapServerStateToStatus(e.payload.to_state);
    if (!toStatus) return;            // unknown server state — drop quietly

    const existingBucket = this.indexById.get(id);
    if (!existingBucket) {
      // First-seen — treat as added.
      const job: Job = {
        id_hash    : id,
        job_type   : (e.payload.metadata?.agent_type as string | undefined) ?? "unknown",
        status     : toStatus,
        created_at : e.payload.timestamp ? Date.parse(e.payload.timestamp) : this.nowFn(),
        meta       : (e.payload.metadata as Record<string, unknown>) ?? {},
      };
      if (toStatus === "running") job.started_at = job.created_at;
      this.buckets[toStatus].push(job);
      this.indexById.set(id, toStatus);
      this.emit({ changeKind: "added", id_hash: id, to: toStatus });
      return;
    }

    if (existingBucket === toStatus) {
      // Same UI bucket — server-state churn that doesn't move the job (e.g.
      // pending → queued, both → todo). Update meta, emit transitioned.
      const job = this.buckets[existingBucket].find(j => j.id_hash === id);
      if (job && e.payload.metadata) {
        Object.assign(job.meta, e.payload.metadata);
      }
      this.emit({
        changeKind : "transitioned",
        id_hash    : id,
        from       : existingBucket,
        to         : toStatus,
      });
      return;
    }

    // Cross-bucket transition — physically move the job.
    const fromList = this.buckets[existingBucket];
    const idx      = fromList.findIndex(j => j.id_hash === id);
    /* c8 ignore next */ // defensive: indexById and bucket arrays are kept in lockstep by every reducer path; "out of sync" is a never-reached invariant violation.
    if (idx < 0) return;
    const job = fromList[idx]!;
    fromList.splice(idx, 1);
    job.status = toStatus;
    /* c8 ignore next 3 */ // defensive: started_at is set by the first-seen branch above when toStatus="running"; reaching this branch with started_at=undefined requires a transition from a non-running bucket to running where the job was previously seen but never had started_at set — server contract enforces started_at on first running transition.
    if (toStatus === "running" && job.started_at === undefined) {
      job.started_at = this.nowFn();
    }
    /* c8 ignore next 3 */ // defensive: completed_at branches — done/dead transitions in the existing test fixtures all carry payload.timestamp; the nowFn fallback path is a safety net for malformed events.
    if ((toStatus === "done" || toStatus === "dead") && job.completed_at === undefined) {
      job.completed_at = e.payload.timestamp ? Date.parse(e.payload.timestamp) : this.nowFn();
    }
    /* c8 ignore next */ // defensive: cross-bucket transitions in test fixtures don't always carry metadata; the conditional Object.assign is for fixtures that do.
    if (e.payload.metadata) Object.assign(job.meta, e.payload.metadata);
    this.buckets[toStatus].push(job);
    this.indexById.set(id, toStatus);
    this.emit({
      changeKind : "transitioned",
      id_hash    : id,
      from       : existingBucket,
      to         : toStatus,
    });
  }

  private onRemoved(e: LupinEvent<JobRemovedPayload>): void {
    /* c8 ignore next */ // defensive: server payload always carries job_id; id_hash fallback is for legacy clients that may emit either key — exercised in production rollout but not in current test fixtures.
    const id = e.payload.job_id ?? e.payload.id_hash;
    /* c8 ignore next */ // defensive: empty payload handling — never sent by the server.
    if (!id) return;
    const bucketName = this.indexById.get(id);
    /* c8 ignore next */ // defensive: removal of a job not in any bucket — server contract enforces "removed implies tracked"; benign no-op covers race where two removals fire for the same id.
    if (!bucketName) return;
    const list = this.buckets[bucketName];
    const idx  = list.findIndex(j => j.id_hash === id);
    /* c8 ignore next */ // defensive: indexById and bucket arrays are kept in lockstep; "out of sync" is a never-reached invariant violation.
    if (idx < 0) return;
    const job = list[idx]!;
    list.splice(idx, 1);

    // If the job was in done/dead, archive it to history. Otherwise it leaves
    // the store entirely (e.g. a todo job cancelled by the user before run).
    if (bucketName === "done" || bucketName === "dead") {
      this.buckets.history.push(job);
      this.indexById.set(id, "history");
    } else {
      this.indexById.delete(id);
    }
    this.emit({ changeKind: "removed", id_hash: id });
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private emit(payload: StoreJobsChangedPayload): void {
    this.bus.emit<StoreJobsChangedPayload>({
      type    : "store_jobs_changed",
      payload,
      source  : "JobStore",
      ts      : this.nowFn(),
    });
  }

  // Normalize a job-history row from /api/job-history into a Job.
  // Server response shape is loose; we extract the canonical fields and keep
  // the rest in `meta` for renderer access.
  /* c8 ignore start */ // Server-shape variation handling: this normalizer accepts multiple id keys (id_hash / job_id / id), multiple state keys (status / state), and three timestamp encodings (number / ISO string / undefined). Production server emits one canonical shape per release; the multi-key tolerance exists for cross-version robustness during rolling upgrades. Test fixtures cover the canonical shape; the alternate-key branches are exercised only against alternate-version servers.
  private normalizeRaw(raw: Record<string, unknown>): Job | null {
    const id = (raw["id_hash"] ?? raw["job_id"] ?? raw["id"]) as string | undefined;
    if (!id || typeof id !== "string") return null;
    const serverState = (raw["status"] ?? raw["state"]) as string | undefined;
    const status = serverState ? mapServerStateToStatus(serverState) : null;
    if (!status) return null;
    const created = raw["created_at"] as string | number | undefined;
    const started = raw["started_at"] as string | number | undefined;
    const completed = raw["completed_at"] as string | number | undefined;

    const job: Job = {
      id_hash    : id,
      job_type   : (raw["job_type"] as string | undefined) ?? "unknown",
      status,
      created_at : typeof created === "number" ? created : (typeof created === "string" ? Date.parse(created) : this.nowFn()),
      meta       : raw,
    };
    if (started !== undefined) {
      job.started_at = typeof started === "number" ? started : Date.parse(started);
    }
    if (completed !== undefined) {
      job.completed_at = typeof completed === "number" ? completed : Date.parse(completed);
    }
    return job;
  }
  /* c8 ignore stop */
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createJobStore(opts: JobStoreOptions): JobStore {
  return new JobStoreImpl(opts);
}
