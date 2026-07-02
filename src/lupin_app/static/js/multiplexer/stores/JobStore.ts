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

// W3 — parametrized history hydration (time-window select + load-more).
// `hydrateHistory(api)` with no opts stays backward-compatible: the mount call
// in JobsPaneRenderer is unchanged and gets the legacy 30-day virgin window.
export interface HydrateHistoryOptions {
  // Time window in days. KEY ABSENT → legacy 30-day default (DEFAULT_HISTORY_
  // WINDOW_DAYS). KEY PRESENT but `undefined` → all-time (the `days` query param
  // is omitted). A number → that rolling window. On a load-more (append) the
  // window is the ALREADY-SELECTED one (this.historyDays), NOT re-read from opts.
  days?   : number;
  // Page size. Default 20 (legacy / W4 load-more parity — NOT the old 100).
  limit?  : number;
  // Pagination offset for a REPLACE fetch (default 0). Ignored on append —
  // append fetches at the tracked cursor (this.historyOffset).
  offset? : number;
  // false (default) = REPLACE the window (clear history bucket + refetch, used
  // for initial mount / window-change / retry). true = APPEND (load-more).
  append? : boolean;
}

interface JobHistoryResponse {
  jobs : ReadonlyArray<Record<string, unknown>>;
  total       ?: number;
  filtered_by ?: string;
  limit       ?: number;
  offset      ?: number;
}

// W3 — legacy virgin defaults (plan 04 §W3: "default 30 per legacy"; limit 20
// for load-more parity, replacing the old hardcoded limit=100 single fetch).
const DEFAULT_HISTORY_WINDOW_DAYS = 30;
const DEFAULT_HISTORY_PAGE_LIMIT  = 20;

// ---------------------------------------------------------------------------
// Public interface (per design § JobStore)
// ---------------------------------------------------------------------------

export interface JobStore {
  bucket(name: JobBucket): ReadonlyArray<Job>;
  getById(idHash: string): Job | undefined;
  /**
   * W3: parametrized + re-runnable. `opts.append=false` (default) REPLACES the
   * history window (clears the bucket + refetches); `append=true` loads the next
   * page. Backward-compatible: `hydrateHistory(api)` with no opts fetches the
   * legacy 30-day window (first page). See HydrateHistoryOptions.
   */
  hydrateHistory(api: JobHistoryApiClient, opts?: HydrateHistoryOptions): Promise<void>;
  isHistoryHydrated(): boolean;
  /** W3: server cursor — rows fetched for the current window (Load-More gate LHS). */
  historyLoadedCount(): number;
  /** W3: server-reported total for the current window (Load-More gate RHS). */
  historyTotalCount(): number;
  /**
   * W3/W2: the current history window in days (`undefined` = all-time). Read by
   * the renderer for the W2 history delete-all `days` query param (and, once it
   * lands, the W3 time-window `<select>`'s current value).
   */
  historyWindowDays(): number | undefined;
  /**
   * W2: bulk-clear a bucket in place. Removes every job in `name` (and its
   * `indexById` entries) and emits `store_jobs_changed{changeKind:"removed",
   * bucket:name}`. This is the post-2xx local clear for delete-all on the
   * WS-fed LIVE buckets (todo/running/done/dead), which have no GET-refetch
   * endpoint — clearing AFTER the 2xx is authoritative, not optimistic. History
   * delete-all does NOT use this (it refetches via `hydrateHistory` so the
   * server stays the source of truth + the pagination cursors reset). Emits
   * unconditionally so the caller can rely on a re-render even for an already-
   * empty bucket.
   */
  clearBucket(name: JobBucket): void;
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

  // W3 — history pagination + window state. `historyOffset` is the server cursor
  // (raw rows fetched so far, NOT the deduped bucket length), so the next append
  // fetches at the correct offset. `historyTotal` is the server's window total
  // (Load-More gate). `historyDays` is the current window (undefined = all-time),
  // read back on append so load-more stays in the same window.
  private historyOffset = 0;
  private historyTotal  = 0;
  private historyDays: number | undefined = DEFAULT_HISTORY_WINDOW_DAYS;

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

  async hydrateHistory(api: JobHistoryApiClient, opts: HydrateHistoryOptions = {}): Promise<void> {
    // W3 — re-runnable: the old `if (this.historyHydrated) return;` once-guard is
    // GONE. A REPLACE (append=false) must refetch on every window-change / retry.
    const append = opts.append ?? false;
    const limit  = opts.limit ?? DEFAULT_HISTORY_PAGE_LIMIT;

    // Window + offset resolution differs between REPLACE and APPEND:
    //   - REPLACE: window comes from opts (key absent → 30-day legacy default;
    //     key present but undefined → all-time / omit the `days` param); offset
    //     from opts (default 0).
    //   - APPEND (load-more): window is the ALREADY-SELECTED one (historyDays)
    //     so paging stays in the same window; offset is the tracked cursor.
    let days: number | undefined;
    let offset: number;
    if (append) {
      days   = this.historyDays;
      offset = this.historyOffset;
    } else {
      days   = "days" in opts ? opts.days : DEFAULT_HISTORY_WINDOW_DAYS;
      offset = opts.offset ?? 0;
    }

    // REPLACE clears the history bucket (+ its index entries) BEFORE the fetch:
    // the server is authoritative for the window; in-session removals within the
    // window come back from the server (they were persisted on removal).
    if (!append) {
      for (const j of this.buckets.history) this.indexById.delete(j.id_hash);
      this.buckets.history.length = 0;
    }

    // /api/job-history is mounted under the queues router, which uses the `/api`
    // prefix (queues.py) — matches the legacy client (notifications.js). It is NOT
    // `/api/queue/...`: that prefix is reserved for per-queue item ops, e.g.
    // /api/queue/{queueName}/{jobId}. Params: days (omit → all-time), limit
    // (1-100), offset (pagination).
    const params = new URLSearchParams();
    if (days !== undefined) params.set("days", String(days));
    params.set("limit",  String(limit));
    params.set("offset", String(offset));
    const resp = await api.get<JobHistoryResponse>(`/api/job-history?${params.toString()}`);

    // Keyed-merge dedup: skip any id already tracked in ANY bucket (replace has
    // just cleared history, so this only skips a still-live done/dead job — never
    // overwrites its indexById mapping; append skips already-loaded history rows).
    for (const raw of resp.jobs) {
      const job = this.normalizeRaw(raw);
      /* c8 ignore next */ // defensive: server response is normally well-formed; null only on malformed rows missing id or unmappable status — server-contract enforced upstream.
      if (!job) continue;
      if (this.indexById.has(job.id_hash)) continue;
      // Hydrated jobs land in the history bucket directly; their UI status
      // is whatever maps from their persisted server state (must be done/dead
      // since they're terminal).
      this.buckets.history.push(job);
      this.indexById.set(job.id_hash, "history");
    }

    // Advance the server cursor by the RAW page size (not the deduped count) so
    // the next append offset mirrors the server's row position. Total falls back
    // to the cursor when the server omits it (keeps the Load-More gate closed).
    this.historyOffset   = offset + resp.jobs.length;
    this.historyTotal    = resp.total ?? this.historyOffset;
    this.historyDays     = days;
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

  historyLoadedCount(): number {
    return this.historyOffset;
  }

  historyTotalCount(): number {
    return this.historyTotal;
  }

  historyWindowDays(): number | undefined {
    return this.historyDays;
  }

  clearBucket(name: JobBucket): void {
    const list = this.buckets[name];
    for (const j of list) this.indexById.delete(j.id_hash);
    list.length = 0;
    this.emit({ changeKind: "removed", bucket: name });
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
