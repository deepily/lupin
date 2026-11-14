// The jobs pane's view of GET /api/jobs/summary. Type-only: no runtime statements.
//
// The shape follows the background-job reporting design (planning-is-prompting,
// src/rnd/2026.11.07-background-job-reporting-format.md): summary, registry, health, page and
// the seven additions. The reader computes health and the page only formats what it is given,
// so there is one definition of silent.
//
// Null always means not reported. A debt that does not apply to a job is declared false in
// `applies` and is then not shown at all, so the two cases look different.

/** The five health states, worst first. */
export type JobState = "unknown" | "silent" | "failing" | "behind" | "healthy";

/** The four outcomes of one attempt. */
export type JobOutcome = "clean" | "carried" | "failed" | "skipped" | "disabled";

/** A reference to a task-store row, shown as a titled link and never as a bare id. */
export interface JobRowRef {
  id    : string;
  title : string;
  href  : string | null;
}

/** One file or ledger line backing a figure. `href` is a doc-viewer link when in scope. */
export interface JobEvidence {
  label : string;
  path  : string;
  href  : string | null;
}

/** One true rule from , in plain words. `state` is the state that rule would give on its own. */
export interface JobReason {
  state : JobState;
  rule  : string;
  text  : string;
}

/** The last attempt the job recorded (`last_attempt`). */
export interface JobAttempt {
  started_at  : string;
  finished_at : string | null;
  trigger     : string | null;
  outcome     : JobOutcome;
  stage       : string | null;
  failure     : string | null;
  evidence    : string | null;
}

/** The last attempt that finished with `clean` or `carried`. */
export interface JobFinished {
  started_at : string;
  outcome    : JobOutcome;
  evidence   : string | null;
}

/** One strip entry: an attempt, or a hole where a run was due and absent. */
export interface JobStripEntry {
  at      : string;
  outcome : JobOutcome | "missed";
}

/** One point of a sparkline. `value` is a count (scan) or a running total (fix). */
export interface JobPoint {
  at    : string;
  value : number;
}

/** How soon the debt clears (design "Clears in"), decided by the reader. */
export interface JobClearsIn {
  kind : "days" | "never_at_this_rate" | "not_enough_runs";
  days : number | null;
}

/** Staleness debt for a refresh job. The reader computes the age at read time. */
export interface JobFreshness {
  built_at          : string | null;
  stale_after_hours : number | null;
  age_hours         : number | null;
}

/** The scan debt: things the job still has to look at. */
export interface JobScanDebt {
  unit                  : string | null;
  count                 : number | null;
  never_checked         : number | null;
  drained_last_run      : number | null;
  arrived_last_interval : number | null;
  as_of                 : string | null;
  freshness             : JobFreshness | null;
  points                : JobPoint[];
  clears_in             : JobClearsIn | null;
}

/** The fix debt: rows (or, for kind "reported", named piles) the job leaves for people. */
export interface JobFixDebt {
  kind              : "rows" | "reported";
  own_mark          : string | null;
  unfiled           : number | null;
  filed_total       : number | null;
  open_now          : number | null;
  closed_in_window  : number | null;
  open_reported     : number | null;
  points            : JobPoint[];
  store_href        : string | null;
}

/** When the job should run, from the registry. */
export interface JobSchedule {
  entries        : string[];
  last_due       : string | null;
  next_due       : string | null;
  grace_minutes  : number | null;
  grace_seconds  : number | null;
}

/** Liveness for a job that only says up or down. `up` null means the unit is not loaded. */
export interface JobLiveness {
  kind : string;
  unit : string;
  up   : boolean | null;
}

/** The 200 body of POST /api/jobs/{job}/run, the one management action. */
export interface JobRunStarted {
  job        : string;
  target     : string | null;
  status     : "started";
  trigger    : "hand";
  pid        : number;
  started_at : string;
}

/** One job, or one target of a job, as the reader returns it. */
export interface JobEntry {
  job                       : string;
  target                    : string | null;
  title                     : string;
  owner                     : string;
  audience                  : string[];
  notify_interval_seconds   : number | null;
  state                     : JobState;
  running                   : boolean;
  unscheduled               : boolean;
  /** True when the job's installed schedule could not be read. */
  schedule_unverified       : boolean;
  machine_was_off           : boolean;
  reasons                   : JobReason[];
  applies                   : { scan_debt: boolean; fix_debt: boolean };
  last_attempt              : JobAttempt | null;
  last_finished             : JobFinished | null;
  consecutive_failures      : number | null;
  work_found_last_run       : number | null;
  strip                     : JobStripEntry[];
  scan_debt                 : JobScanDebt | null;
  fix_debt                  : JobFixDebt | null;
  schedule                  : JobSchedule | null;
  liveness                  : JobLiveness | null;
  evidence                  : JobEvidence[];
  rows                      : JobRowRef[];
  detail_link               : string | null;
  runnable                  : boolean;
  unknown_reason            : string | null;
  targets                   : JobEntry[];
}

/** The whole response of GET /api/jobs/summary. */
export interface JobsSummary {
  schema       : "jobs-summary/1";
  generated_at : string;
  /** True only when the caller may run jobs by hand: the operator's login. */
  caller_is_operator : boolean;
  jobs         : JobEntry[];
  /** How many registered jobs have reporting switched off; they are not in `jobs`. */
  reporting_off? : number;
  /** One sentence for that count, or null. */
  reporting_off_line? : string | null;
}
