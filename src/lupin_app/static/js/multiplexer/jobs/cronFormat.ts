/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Text rules for a job's switch.
//
// Row c80ef763 merged the Scheduled Jobs pane into the jobs list. Nothing here touches the DOM, the network or the clock. They were the text rules of the Scheduled
// Jobs pane (rows 063fc1a8, c38a49bd); the jobs list now draws a job's switch on its second line.
// The legacy client carries its own independent copy (static/js/cron-jobs.js); the two share no
// runtime code, by Rick's no-shared-code ruling (row 87812328).

import { ApiError } from "../api/ApiClient";

/** The list door, and the root of each job's flip door. */
export const CRON_JOBS_PATH   = "/api/cron-jobs";
/** What a row says when no flip has ever been recorded for it. */
export const CRON_NOT_REPORTED = "not reported";
/** What a row says when the file disagrees with the last recorded flip. */
export const CRON_DRIFT_TEXT   = "changed outside the endpoint";
/** What an unreadable switch says: the job skips its ticks until the key is fixed. */
export const CRON_UNREADABLE_TEXT = "switch unreadable: the key is missing from the configuration file or holds neither true nor false";
/** What an alarm job's first turn-off click says; a second click confirms. */
export const CRON_CONFIRM_TEXT = "Turning this off also silences what would report it. Click again to confirm.";
/** How a row says when its job reads the switch, by the server's `reads` field. */
export const CRON_READS_TEXT: Readonly<Record<string, string>> = { run : "reads its switch at each run", tick : "reads its switch every tick" };

/** One job's switch row, as GET /api/cron-jobs and the socket frame carry it. */
export interface CronJobRow {
  job             : string;
  title           : string;
  schedule        : string;
  key             : string;
  enabled         : boolean | null;
  honoured        : boolean;
  drift           : boolean;
  last_changed_by : string | null;
  last_changed_at : string | null;
  /** "run" for a wrapper-started job, "tick" for a loop that checks every tick, else none. */
  reads?          : string | null;
  /** True for one of the alarm jobs: turning it off silences what would report it. */
  alarm?          : boolean;
  /** The job whose tick this one runs inside, or null. */
  inside?         : string | null;
}

/** The list door's answer. */
export interface CronJobsSummary {
  jobs            : CronJobRow[];
  caller_is_admin : boolean;
}

/** The path of the flip door for one job. */
export function cronFlipPath( job: string ): string {
  return `${ CRON_JOBS_PATH }/${ encodeURIComponent( job ) }/enabled`;
}

/** The capitalised word a row shows for its switch: on, off or unknown. */
export function cronStateText( enabled: boolean | null ): string {
  if ( enabled === null ) return "UNKNOWN";
  return enabled ? "ON" : "OFF";
}

/** How a row says its job reads the switch, from `reads` when sent, else from honoured. */
export function cronReadsText( row: CronJobRow ): string {
  const said = typeof row.reads === "string" ? CRON_READS_TEXT[ row.reads ] : undefined;
  if ( said !== undefined ) return said;
  return row.honoured ? "reads its switch" : "does not read its switch yet";
}

/** A line for a job inside another job's tick, when that host job is off; else null. */
export function cronInsideText( row: CronJobRow, jobs: CronJobRow[] ): string | null {
  if ( typeof row.inside !== "string" ) return null;
  const host = jobs.find( ( j ) => j.job === row.inside );
  return host !== undefined && host.enabled === false ? `off while ${ row.inside } is off` : null;
}

/** "who, YYYY-MM-DD HH:MM" for a row with a recorded flip, else the not-reported text. */
export function cronChangedText( row: CronJobRow ): string {
  if ( row.last_changed_by === null || row.last_changed_at === null ) return CRON_NOT_REPORTED;
  return `${ row.last_changed_by }, ${ row.last_changed_at.slice( 0, 16 ).replace( "T", " " ) }`;
}

/** The `detail` sentence of a refusal body, or null. */
export function refusalDetail( err: ApiError ): string | null {
  const start = err.message.indexOf( "{" );
  if ( start < 0 ) return null;
  try {
    const body = JSON.parse( err.message.slice( start ) ) as { detail?: unknown };
    return typeof body.detail === "string" && body.detail !== "" ? body.detail : null;
  } catch { return null; }
}

/**
 * Turn the answer to a refused flip into one sentence for the row.
 *
 * Ensures:
 *   - 403, 404, 409 and 422 each get their own plain-words line; anything else shows its status
 *   - a 409 or 422 whose body carries a `detail` shows that detail instead of the generic line
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function cronFlipFailureText( err: unknown ): string {
  if ( !( err instanceof ApiError ) ) return `Flip failed: ${ String( err ) }`;
  if ( err.status === 403 ) return "Only an administrator can flip a job's switch.";
  if ( err.status === 404 ) return "The server does not know this job.";
  if ( err.status === 409 ) return refusalDetail( err ) ?? "The configuration file does not carry this job's switch yet.";
  if ( err.status === 422 ) return refusalDetail( err ) ?? "The server refused this flip.";
  return `Flip failed (HTTP ${ err.status }).`;
}
