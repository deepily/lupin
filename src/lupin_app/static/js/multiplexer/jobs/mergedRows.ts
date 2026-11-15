/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// One list from two doors (row c80ef763).
//
// GET /api/jobs/summary says how each job is doing; GET /api/cron-jobs says whether its switch is on.
// Both are keyed by the registry job id. This joins them: a job with a switch carries it as `cron`,
// and a switch whose job the summary leaves out (a job with reporting switched off) gets an entry of
// its own, marked `cron_only`, so no switch is ever missing from the list.
// Nothing here touches the DOM or the clock.

import type { CronJobRow } from "./cronFormat";
import type { JobEntry } from "./types";

/**
 * The entry for a switch the summary does not report on.
 *
 * Ensures:
 *   - state "unknown", no figures, nothing runnable, `cron_only` true, and the switch attached
 */
export function cronOnlyEntry( row: CronJobRow ): JobEntry {
  return {
    job : row.job, target : null, title : row.title, owner : "", audience : [], notify_interval_seconds : null,
    state : "unknown", running : false, unscheduled : false, schedule_unverified : false, machine_was_off : false,
    reasons : [], applies : { scan_debt : false, fix_debt : false }, last_attempt : null, last_finished : null,
    consecutive_failures : null, work_found_last_run : null, strip : [], scan_debt : null, fix_debt : null,
    schedule : null, liveness : null, evidence : [], rows : [], detail_link : null, runnable : false,
    unknown_reason : null, targets : [], cron : row, cron_only : true,
  };
}

/**
 * Join the summary's jobs with the switch rows.
 *
 * Requires:
 *   - `jobs` are the top-level entries of the summary; `cronRows` are the rows of the switch list
 *
 * Ensures:
 *   - one entry per summary job, in the summary's order, each a copy carrying its switch row or null
 *   - one `cronOnlyEntry` after them for every switch row no summary job names
 *   - the inputs are not changed, and targets stay nested under their job, switchless
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function mergeJobs( jobs: readonly JobEntry[], cronRows: readonly CronJobRow[] ): JobEntry[] {
  const byJob  = new Map<string, CronJobRow>( cronRows.map( ( r ) => [ r.job, r ] ) );
  const merged = jobs.map( ( j ) => ( { ...j, cron : byJob.get( j.job ) ?? null } ) );
  const named  = new Set<string>( jobs.map( ( j ) => j.job ) );
  return [ ...merged, ...cronRows.filter( ( r ) => !named.has( r.job ) ).map( cronOnlyEntry ) ];
}
