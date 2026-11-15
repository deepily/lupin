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
import type { JobEntry } from "./types";

/** Backslash-escape the characters markdown would act on, so job text reads as written. */
export function mdText( text: string ): string {
  return text.replace( /[\\`*_{}[\]<>#|~]/g, ( c ) => `\\${ c }` );
}

/** A markdown link for a safe on-server path; plain escaped text for anything else. */
export function mdLink( href: string | null, label: string ): string {
  if ( !isSafeHref( href ) ) return mdText( label );
  return `[${ mdText( label ) }](${ ( href as string ).replace( /[() ]/g, ( c ) => `%${ c.charCodeAt( 0 ).toString( 16 ).toUpperCase() }` ) })`;
}

function section( title: string, lines: string[] ): string {
  return `## ${ title }\n\n${ lines.join( "\n" ) }\n`;
}

function titleLine( job: JobEntry ): string {
  return `# ${ mdText( job.title ) }${ job.target === null ? "" : ` (${ mdText( job.target ) })` }\n`;
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
  ];
}

function fixLines( job: JobEntry ): string[] {
  const debt = job.fix_debt;
  if ( debt === null ) return [ NOT_REPORTED ];
  if ( debt.kind === "reported" ) return [ `- Named, not acted on: ${ formatCount( debt.open_reported ) }` ];
  const trend = trendArrow( debt.points );
  const lines = [
    `- Unfiled: ${ formatCount( debt.unfiled ) }${ trend === "" ? "" : ` ${ trend }` }`,
    `- Filed in total: ${ formatCount( debt.filed_total ) }`,
    `- Open now: ${ formatCount( debt.open_now ) }`,
    `- Closed in window: ${ formatCount( debt.closed_in_window ) }`,
    `- Own mark: ${ mdText( debt.own_mark ?? NOT_REPORTED ) }`,
  ];
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

function peopleLines( job: JobEntry ): string[] {
  const lines = [
    `- Owner: ${ mdText( job.owner ) }`,
    `- Told: ${ job.audience.length === 0 ? "the owner" : mdText( job.audience.join( ", " ) ) }`,
  ];
  for ( const row of job.rows ) lines.push( `- ${ mdLink( row.href, row.title ) }` );
  if ( isSafeHref( job.detail_link ) ) lines.push( `- ${ mdLink( job.detail_link, "Open the detail page" ) }` );
  return lines;
}

/**
 * The markdown abstract for one job.
 *
 * Requires:
 *   - `todayIso` starts with YYYY-MM-DDTHH:MM
 *
 * Ensures:
 *   - the headings are Reasons, Last attempts (not for a liveness job), Scan debt, Fix debt (each only when it applies),
 *     Schedule, Evidence, People and Not reported, in that order
 *   - job-writer text is escaped, and only an on-server path becomes a link
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function abstractMarkdown( job: JobEntry, todayIso: string ): string {
  const parts = [ titleLine( job ), section( "Reasons", reasonLines( job ) ) ];
  if ( job.liveness === null ) parts.push( section( "Last attempts", stripLines( job, todayIso ) ) );
  if ( job.applies.scan_debt && job.liveness === null ) parts.push( section( "Scan debt", scanLines( job, todayIso ) ) );
  if ( job.applies.fix_debt ) parts.push( section( "Fix debt", fixLines( job ) ) );
  parts.push( section( "Schedule", scheduleLines( job, todayIso ) ) );
  parts.push( section( "Evidence", job.evidence.length === 0
    ? [ NOT_REPORTED ]
    : job.evidence.map( ( e ) => `- ${ mdLink( e.href, `${ e.label }: ${ e.path }` ) }` ) ) );
  parts.push( section( "People", peopleLines( job ) ) );
  const names = notReportedNames( job );
  parts.push( section( "Not reported", [ names.length === 0 ? "Every figure was reported." : mdText( names.join( ", " ) ) ] ) );
  return parts.join( "\n" );
}
