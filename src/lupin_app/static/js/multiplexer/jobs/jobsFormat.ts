/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Text rules for the jobs page.
//
// Nothing here touches the DOM or the clock. Times are read straight off the ISO text the reader
// sent ("2026-11-07T19:31:02-05:00" prints as 19:31), so a page opened in another time zone shows
// the same wall time as the log it points at, and a test needs no fake clock.

import type { JobEntry, JobPoint, JobScanDebt, JobState } from "./types";

/** The states, worst first. The accordion sorts by this order. */
export const STATE_ORDER: readonly JobState[] = [ "unknown", "silent", "failing", "behind", "healthy" ];

const STATE_LABEL: Record<JobState, string> = {
  unknown : "UNKNOWN",
  silent  : "SILENT",
  failing : "FAILING",
  behind  : "BEHIND",
  healthy : "healthy",
};

/** Printed wherever a figure is null, so a missing figure never reads as zero. */
export const NOT_REPORTED = "not reported";

/**
 * The time part of an ISO text as HH:MM, or MM-DD HH:MM when it is not on `todayIso`'s day.
 *
 * Requires:
 *   - iso and todayIso start with YYYY-MM-DDTHH:MM
 *
 * Ensures:
 *   - null in gives "not reported"; text that is not an ISO time comes back unchanged
 */
export function formatWhen( iso: string | null, todayIso: string ): string {
  if ( iso === null ) return NOT_REPORTED;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec( iso );
  if ( match === null ) return iso;
  const day = `${ match[ 1 ] }-${ match[ 2 ] }-${ match[ 3 ] }`;
  return todayIso.startsWith( day ) ? ( match[ 4 ] as string ) : `${ match[ 2 ] }-${ match[ 3 ] } ${ match[ 4 ] }`;
}

/** A count with thousands separators, or "not reported". */
export function formatCount( n: number | null ): string {
  return n === null ? NOT_REPORTED : n.toLocaleString( "en-US" );
}

/**
 * ▲ when the series grew, ▼ when it shrank, = when it held.
 *
 * It returns an empty string with fewer than two points.
 *
 * It compares the first and last point, the same two ends the sparkline draws.
 */
export function trendArrow( points: readonly JobPoint[] ): string {
  if ( points.length < 2 ) return "";
  const first = ( points[ 0 ] as JobPoint ).value;
  const last  = ( points[ points.length - 1 ] as JobPoint ).value;
  if ( last > first ) return "▲";
  return last < first ? "▼" : "=";
}

/** Sort worst state first, then title, then target. Never mutates its input. */
export function sortJobs( jobs: readonly JobEntry[] ): JobEntry[] {
  const rank = ( j: JobEntry ): number => STATE_ORDER.indexOf( j.state );
  return [ ...jobs ].sort( ( a, b ) =>
    rank( a ) - rank( b ) || a.title.localeCompare( b.title ) || ( a.target ?? "" ).localeCompare( b.target ?? "" ) );
}

/** The header line, such as "5 jobs: 3 failing, 1 healthy". Empty states are left out. */
export function headerLine( jobs: readonly JobEntry[] ): string {
  const parts: string[] = [];
  for ( const state of STATE_ORDER ) {
    const n = jobs.filter( ( j ) => j.state === state ).length;
    if ( n > 0 ) parts.push( `${ n } ${ state }` );
  }
  const noun = jobs.length === 1 ? "job" : "jobs";
  return parts.length === 0 ? `${ jobs.length } ${ noun }` : `${ jobs.length } ${ noun }: ${ parts.join( ", " ) }`;
}

/**
 * The badge text: the first true state, then any other state a reason names.
 *
 * An example is "FAILING · BEHIND".
 *
 * An unscheduled job also carries an unscheduled label. It is a badge and not a state.
 */
export function badgeText( job: JobEntry ): string {
  const states = [ job.state ];
  for ( const reason of job.reasons ) {
    if ( !states.includes( reason.state ) && reason.state !== "healthy" ) states.push( reason.state );
  }
  const labels = states.map( ( s ) => STATE_LABEL[ s ] );
  if ( job.unscheduled ) labels.push( "UNSCHEDULED" );
  if ( job.schedule_unverified ) labels.push( "schedule unverified" );
  return labels.join( " · " );
}

/** What a skipped, clean or failed attempt reads as on the collapsed line. */
export function lastRunText( job: JobEntry, todayIso: string ): string {
  if ( job.liveness !== null ) {
    if ( job.liveness.up === null ) return `unit ${ job.liveness.unit } is not loaded`;
    return job.liveness.up ? `up (${ job.liveness.unit })` : `down (${ job.liveness.unit })`;
  }
  if ( job.state === "silent" ) {
    const due = job.schedule === null ? null : job.schedule.last_due;
    return `SILENT, due ${ formatWhen( due, todayIso ) }, nothing since`;
  }
  const attempt = job.last_attempt;
  if ( attempt === null ) return job.state === "unknown" ? "never reported" : "no run recorded";
  const at = formatWhen( attempt.started_at, todayIso );
  if ( attempt.outcome === "failed" ) {
    return attempt.failure === null ? `last run ${ at } failed` : `last run ${ at } failed (${ attempt.failure })`;
  }
  if ( attempt.outcome === "skipped" ) return `last run ${ at } skipped`;
  if ( attempt.outcome === "clean" && job.work_found_last_run === 0 ) return `ran ${ at }, found nothing`;
  return `last run ${ at } ${ attempt.outcome }`;
}

/** "last finished 11-06 19:06", or "last finished: not reported". */
export function lastFinishedText( job: JobEntry, todayIso: string ): string {
  if ( job.last_finished === null ) return `last finished: ${ NOT_REPORTED }`;
  return `last finished ${ formatWhen( job.last_finished.started_at, todayIso ) }`;
}

/** The scan column text, or an empty string when scan debt does not apply. */
export function scanText( job: JobEntry ): string {
  if ( !job.applies.scan_debt ) return "";
  const debt = job.scan_debt;
  if ( debt === null ) return `scan: ${ NOT_REPORTED }`;
  if ( debt.freshness !== null ) return freshnessText( debt );
  if ( debt.count === null ) return `scan: ${ NOT_REPORTED }`;
  return `scan ${ formatCount( debt.count ) } ${ trendArrow( debt.points ) }`.trimEnd();
}

/** "age 2 h of 36" for a refresh job, or "age: not reported". */
export function freshnessText( debt: JobScanDebt ): string {
  const f = debt.freshness;
  if ( f === null || f.age_hours === null ) return `age: ${ NOT_REPORTED }`;
  const age = Math.round( f.age_hours );
  return f.stale_after_hours === null ? `age ${ age } h` : `age ${ age } h of ${ f.stale_after_hours }`;
}

/** The fix column text, or an empty string when fix debt does not apply. */
export function fixText( job: JobEntry ): string {
  if ( !job.applies.fix_debt ) return "";
  const debt = job.fix_debt;
  if ( debt === null ) return `rows: ${ NOT_REPORTED }`;
  if ( debt.kind === "reported" ) {
    return debt.open_reported === null ? `named: ${ NOT_REPORTED }` : `named ${ formatCount( debt.open_reported ) }, not acted on`;
  }
  if ( debt.unfiled === null ) return `rows: ${ NOT_REPORTED }`;
  return `unfiled ${ formatCount( debt.unfiled ) } ${ trendArrow( debt.points ) }`.trimEnd();
}

/** The clears-in column text, or an empty string with no scan debt. */
export function clearsText( job: JobEntry ): string {
  const clears = job.scan_debt === null ? null : job.scan_debt.clears_in;
  if ( !job.applies.scan_debt || clears === null ) return "";
  if ( clears.kind === "never_at_this_rate" ) return "clears: never at this rate";
  if ( clears.kind === "not_enough_runs" ) return "clears: not enough runs";
  if ( clears.days === null ) return `clears: ${ NOT_REPORTED }`;
  return `clears: ${ clears.days === 1 ? "1 day" : `${ clears.days } days` }`;
}

/**
 * Every null the panel must name, so a missing figure is never read as zero.
 *
 * A debt that does not apply is skipped altogether: it is absent, not unreported.
 */
export function notReportedNames( job: JobEntry ): string[] {
  const names: string[] = [];
  if ( job.last_finished === null ) names.push( "last finished run" );
  if ( job.liveness === null && job.applies.scan_debt ) {
    const debt = job.scan_debt;
    if ( debt === null ) names.push( "scan debt" );
    else {
      if ( debt.count === null && debt.freshness === null ) names.push( "scan debt count" );
      if ( debt.never_checked === null && debt.freshness === null ) names.push( "never checked" );
      if ( debt.drained_last_run === null && debt.freshness === null ) names.push( "drained last run" );
      if ( debt.arrived_last_interval === null && debt.freshness === null ) names.push( "arrived last interval" );
    }
  }
  if ( job.applies.fix_debt ) {
    const debt = job.fix_debt;
    if ( debt === null ) names.push( "fix debt" );
    else if ( debt.kind === "rows" ) {
      if ( debt.unfiled === null ) names.push( "unfiled rows" );
      if ( debt.open_now === null ) names.push( "open rows" );
      if ( debt.closed_in_window === null ) names.push( "rows closed in window" );
    } else if ( debt.open_reported === null ) names.push( "named pile" );
  }
  return names;
}

/** Grace in words, such as "30 minutes". Seconds win when both are set. */
export function graceText( job: JobEntry ): string {
  const s = job.schedule;
  if ( s === null ) return NOT_REPORTED;
  if ( s.grace_seconds !== null ) return `${ s.grace_seconds } seconds`;
  return s.grace_minutes === null ? NOT_REPORTED : `${ s.grace_minutes } minutes`;
}

/** How often Rick hears about this job, such as "every 1 h" or "every 10 min". */
export function notifyIntervalText( job: JobEntry ): string {
  const secs = job.notify_interval_seconds;
  if ( secs === null ) return NOT_REPORTED;
  if ( secs % 3600 === 0 ) return `every ${ secs / 3600 } h`;
  if ( secs % 60 === 0 ) return `every ${ secs / 60 } min`;
  return `every ${ secs } s`;
}

/** True for an href the page may link to: a path on this server and never a URL scheme. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function isSafeHref( href: string | null ): href is string {
  return href !== null && href.startsWith( "/" ) && !href.startsWith( "//" ) && !href.includes( "\\" );
}
