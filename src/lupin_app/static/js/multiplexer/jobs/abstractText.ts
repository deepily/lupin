/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The 📋 abstract of a job.
//
// Row c80ef763: it is what the expanded accordion panel used to show: reasons, last attempts, scan debt, fix debt,
// schedule, evidence, people and what was not reported. The text leaves the list and goes behind the
// 📋, the way a notification's abstract does. Every writer-supplied string is escaped, and a link is
// drawn only for a path on this server (isSafeHref), because the reader passes through strings that
// job writers produced. Nothing here touches the DOM or the clock.

import {
  NOT_REPORTED, clearsText, formatCount, formatWhen, graceText, isSafeHref, notReportedNames, notifyIntervalText, trendArrow,
} from "./jobsFormat";
import { cronChangedText, cronInsideText, cronReadsText, cronStateText, CRON_DRIFT_TEXT, CRON_UNREADABLE_TEXT } from "./cronFormat";
import type { CronJobRow } from "./cronFormat";
import type { JobEntry, JobPoint } from "./types";

/** Backslash-escape the characters markdown would act on, so job text reads as written. */
export function mdText( text: string ): string {
  return text.replace( /[\\`*_{}[\]<>#|~]/g, ( c ) => `\\${ c }` );
}

/** A markdown link for a safe on-server path; plain escaped text for anything else. */
export function mdLink( href: string | null, label: string ): string {
  if ( !isSafeHref( href ) ) return mdText( label );
  return `[${ mdText( label ) }](${ ( href as string ).replace( /[() ]/g, ( c ) => `%${ c.charCodeAt( 0 ).toString( 16 ).toUpperCase() }` ) })`;
}

function section( title: string, lines: string[], level = 2 ): string {
  return `${ "#".repeat( level ) } ${ title }\n\n${ lines.join( "\n" ) }\n`;
}

/** The old sparkline's series as text, like its aria-label did; nothing under two points. */
function trendLine( label: string, points: readonly JobPoint[] ): string[] {
  return points.length < 2 ? [] : [ `- Trend (${ label }): ${ points.map( ( p ) => p.value ).join( ", " ) }` ];
}

function nameOf( job: JobEntry ): string {
  return `${ mdText( job.title ) }${ job.target === null ? "" : ` (${ mdText( job.target ) })` }`;
}

function titleLine( job: JobEntry ): string {
  return `# ${ nameOf( job ) }\n`;
}

/**
 * The job's description as a paragraph, drawn right after the title.
 *
 * Ensures:
 *   - the entry's own text is used, and the switch row's text when the entry has none
 *   - no text at all gives no paragraph
 */
function descriptionBlock( job: JobEntry ): string[] {
  const text = job.description || ( job.cron?.description ?? "" );
  return text === "" ? [] : [ `${ mdText( text ) }\n` ];
}

function reasonLines( job: JobEntry ): string[] {
  if ( job.reasons.length === 0 && job.unknown_reason === null ) return [ "No rule is true: nothing to report." ];
  const lines = job.reasons.map( ( r ) => `- ${ mdText( r.text ) }` );
  if ( job.unknown_reason !== null ) lines.push( `- ${ mdText( job.unknown_reason ) }` );
  if ( job.machine_was_off ) lines.push( "- Missed while the machine was off." );
  return lines;
}

function stripLines( job: JobEntry, todayIso: string ): string[] {
  if ( job.strip.length === 0 ) return [ NOT_REPORTED ];
  return job.strip.map( ( e, i ) => `${ i + 1 }. ${ formatWhen( e.at, todayIso ) } ${ e.outcome === "missed" ? "MISSED (due, no run)" : mdText( e.outcome ) }` );
}

function scanLines( job: JobEntry, todayIso: string ): string[] {
  const debt = job.scan_debt;
  if ( debt === null ) return [ NOT_REPORTED ];
  const count = debt.count === null ? NOT_REPORTED : `${ formatCount( debt.count ) } ${ debt.unit ?? "" }`.trim();
  const trend = trendArrow( debt.points );
  return [
    `- Count: ${ mdText( count ) }${ trend === "" ? "" : ` ${ trend }` }`,
    `- As of: ${ formatWhen( debt.as_of, todayIso ) }`,
    `- Drained last run: ${ formatCount( debt.drained_last_run ) }`,
    `- Arrived last interval: ${ formatCount( debt.arrived_last_interval ) }`,
    `- Never checked: ${ formatCount( debt.never_checked ) }`,
    `- Clears in: ${ clearsText( job ) || NOT_REPORTED }`,
    ...trendLine( "scan debt", debt.points ),
  ];
}

function fixLines( job: JobEntry ): string[] {
  const debt = job.fix_debt;
  if ( debt === null ) return [ NOT_REPORTED ];
  if ( debt.kind === "reported" ) return [ `- Named, not acted on: ${ formatCount( debt.open_reported ) }`, ...trendLine( "rows opened", debt.points ) ];
  const trend = trendArrow( debt.points );
  const lines = [
    `- Unfiled: ${ formatCount( debt.unfiled ) }${ trend === "" ? "" : ` ${ trend }` }`,
    `- Filed in total: ${ formatCount( debt.filed_total ) }`,
    `- Open now: ${ formatCount( debt.open_now ) }`,
    `- Closed in window: ${ formatCount( debt.closed_in_window ) }`,
    `- Own mark: ${ mdText( debt.own_mark ?? NOT_REPORTED ) }`,
  ];
  lines.push( ...trendLine( "rows opened", debt.points ) );
  if ( isSafeHref( debt.store_href ) ) lines.push( `- ${ mdLink( debt.store_href, "Rows in the task store" ) }` );
  return lines;
}

function scheduleLines( job: JobEntry, todayIso: string ): string[] {
  const s     = job.schedule;
  const lines: string[] = [];
  if ( job.liveness !== null ) lines.push( `- Liveness: ${ mdText( job.liveness.kind ) } unit ${ mdText( job.liveness.unit ) }` );
  if ( job.schedule_unverified ) lines.push( "- Check: schedule unverified: the installed schedule could not be read" );
  lines.push( `- Runs: ${ s === null || s.entries.length === 0 ? "unscheduled" : mdText( s.entries.join( "; " ) ) }` );
  lines.push( `- Last due: ${ s === null ? NOT_REPORTED : formatWhen( s.last_due, todayIso ) }` );
  lines.push( `- Next due: ${ s === null ? NOT_REPORTED : formatWhen( s.next_due, todayIso ) }` );
  lines.push( `- Grace: ${ graceText( job ) }` );
  lines.push( `- Tells Rick: ${ notifyIntervalText( job ) }` );
  return lines;
}

/** What the old Scheduled Jobs row showed: state, schedule, last flip, reads, warnings. */
function switchLines( row: CronJobRow, cronRows: readonly CronJobRow[] ): string[] {
  const lines = [
    `- State: ${ cronStateText( row.enabled ) }`,
    `- Cron schedule: ${ mdText( row.schedule ) }`,
    `- Last changed: ${ mdText( cronChangedText( row ) ) }`,
    `- Reads: ${ cronReadsText( row ) }`,
  ];
  if ( row.drift ) lines.push( `- Check: ${ CRON_DRIFT_TEXT }` );
  if ( row.honoured && row.enabled === null ) lines.push( `- Check: ${ CRON_UNREADABLE_TEXT }` );
  const inside = cronInsideText( row, cronRows as CronJobRow[] );
  if ( inside !== null ) lines.push( `- Check: ${ mdText( inside ) }` );
  return lines;
}

function peopleLines( job: JobEntry ): string[] {
  const lines = [
    `- Owner: ${ mdText( job.owner ) }`,
    `- Told: ${ job.audience.length === 0 ? "the owner" : mdText( job.audience.join( ", " ) ) }`,
  ];
  for ( const row of job.rows ) lines.push( `- ${ mdLink( row.href, row.title ) }` );
  if ( isSafeHref( job.detail_link ) ) lines.push( `- ${ mdLink( job.detail_link, "Open the detail page" ) }` );
  return lines;
}

/** The sections every job has, at a heading level; `switchPart` goes after Schedule. */
function jobSections( job: JobEntry, todayIso: string, level: number, switchPart: string | null ): string[] {
  const parts: string[] = [ section( "Reasons", reasonLines( job ), level ) ];
  if ( job.liveness === null ) parts.push( section( "Last attempts", stripLines( job, todayIso ), level ) );
  if ( job.applies.scan_debt && job.liveness === null ) parts.push( section( "Scan debt", scanLines( job, todayIso ), level ) );
  if ( job.applies.fix_debt ) parts.push( section( "Fix debt", fixLines( job ), level ) );
  parts.push( section( "Schedule", scheduleLines( job, todayIso ), level ) );
  if ( switchPart !== null ) parts.push( switchPart );
  parts.push( section( "Evidence", job.evidence.length === 0
    ? [ NOT_REPORTED ]
    : job.evidence.map( ( e ) => `- ${ mdLink( e.href, `${ e.label }: ${ e.path }` ) }` ), level ) );
  parts.push( section( "People", peopleLines( job ), level ) );
  const names = notReportedNames( job );
  parts.push( section( "Not reported", [ names.length === 0 ? "Every figure was reported." : mdText( names.join( ", " ) ) ], level ) );
  return parts;
}

/**
 * The markdown abstract for one job.
 *
 * Requires:
 *   - `todayIso` starts with YYYY-MM-DDTHH:MM
 *   - `cronRows` are the rows of the switch list, so a job inside another's tick can say so
 *
 * Ensures:
 *   - the headings are Reasons, Last attempts (not for a liveness job), Scan debt, Fix debt (each only when it applies),
 *     Schedule, Switch (only for a job with one), Evidence, People and Not reported, in that order
 *   - a debt of two or more points carries its trend as text, named "scan debt" or "rows opened"
 *   - each target of the job follows as its own "Target:" block with the same sections
 *   - a switch-only job (`cron_only`) carries its title, its Switch and one line saying why nothing else is reported
 *   - job-writer text is escaped, and only an on-server path becomes a link
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function abstractMarkdown( job: JobEntry, todayIso: string, cronRows: readonly CronJobRow[] = [] ): string {
  const row = job.cron ?? null;
  const own = row === null ? null : section( "Switch", switchLines( row, cronRows ) );
  if ( job.cron_only === true && own !== null ) return [ titleLine( job ), ...descriptionBlock( job ), own, "No run reports for this job: reporting is switched off.\n" ].join( "\n" );
  const parts = [ titleLine( job ), ...descriptionBlock( job ), ...jobSections( job, todayIso, 2, own ) ];
  for ( const target of job.targets ) {
    parts.push( section( `Target: ${ nameOf( target ) }`, [] ).trimEnd() + "\n" );
    parts.push( ...jobSections( target, todayIso, 3, null ) );
  }
  return parts.join( "\n" );
}
