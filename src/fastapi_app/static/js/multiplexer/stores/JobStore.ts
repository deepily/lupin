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

    // /api/queue/job-history is mounted under the `/api/queue` router prefix.
    // Phase 4 scope: fetch the first page (default limit=20). Phase 5+
    // renderer can request more via paged calls.
    const resp = await api.get<JobHistoryResponse>("/api/queue/job-history?limit=100");

    const inSessionIds = new Set(this.buckets.history.map(j => j.id_hash));
    for (const raw of resp.jobs) {
      const job = this.normalizeRaw(raw);
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
    if (idx < 0) return;              // index/list out of sync — defensive no-op
    const job = fromList[idx]!;
    fromList.splice(idx, 1);
    job.status = toStatus;
    if (toStatus === "running" && job.started_at === undefined) {
      job.started_at = this.nowFn();
    }
    if ((toStatus === "done" || toStatus === "dead") && job.completed_at === undefined) {
      job.completed_at = e.payload.timestamp ? Date.parse(e.payload.timestamp) : this.nowFn();
    }
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
    const id = e.payload.job_id ?? e.payload.id_hash;
    if (!id) return;
    const bucketName = this.indexById.get(id);
    if (!bucketName) return;          // unknown — no-op
    const list = this.buckets[bucketName];
    const idx  = list.findIndex(j => j.id_hash === id);
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

  // Normalize a job-history row from /api/queue/job-history into a Job.
  // Server response shape is loose; we extract the canonical fields and keep
  // the rest in `meta` for renderer access.
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
    /* c8 ignore start */ // Server response shape variation — exercised in prod when started_at present.
    if (started !== undefined) {
      job.started_at = typeof started === "number" ? started : Date.parse(started);
    }
    /* c8 ignore stop */
    if (completed !== undefined) {
      job.completed_at = typeof completed === "number" ? completed : Date.parse(completed);
    }
    return job;
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createJobStore(opts: JobStoreOptions): JobStore {
  return new JobStoreImpl(opts);
}
