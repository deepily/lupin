/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Builds the jobs accordion DOM.
//
// One accordion, one line per job. Every text goes in through textContent, never innerHTML, and a
// link is drawn only for a path on this server (isSafeHref), because the reader passes through
// strings that job writers produced. Nothing here reads the clock or the network.

import {
  NOT_REPORTED, badgeText, clearsText, fixText, formatCount, formatWhen, graceText, isSafeHref,
  lastFinishedText, lastRunText, notReportedNames, notifyIntervalText, scanText, sortJobs,
} from "./jobsFormat";
import type { JobEntry, JobPoint, JobsSummary } from "./types";

const SVG_NS = "http://www.w3.org/2000/svg";

/** What the page lets a rendered job do. Only Run now exists. */
export interface JobsActions {
  /** False hides every Run now button: the caller is not the operator. */
  canRun : boolean;
  runNow( job: JobEntry ): Promise<string>;
}

function el( doc: Document, tag: string, className: string | null, text: string | null, testid: string | null ): HTMLElement {
  const node = doc.createElement( tag );
  if ( className !== null ) node.className = className;
  if ( text !== null ) node.textContent = text;
  if ( testid !== null ) node.setAttribute( "data-testid", testid );
  return node;
}

function link( doc: Document, href: string, text: string, testid: string ): HTMLAnchorElement {
  const a = doc.createElement( "a" );
  a.href = href;
  a.textContent = text;
  a.setAttribute( "data-testid", testid );
  return a;
}

/**
 * A tiny inline trend line from a debt's points.
 *
 * Ensures:
 *   - fewer than two points draws nothing (returns null)
 *   - a flat series draws a level line, not a divide-by-zero
 */
export function sparkline( doc: Document, points: readonly JobPoint[], label: string ): SVGElement | null {
  if ( points.length < 2 ) return null;
  const values = points.map( ( p ) => p.value );
  const lo     = Math.min( ...values );
  const span   = Math.max( ...values ) - lo;
  const coords = values.map( ( v, i ) => {
    const x = ( i / ( values.length - 1 ) ) * 118 + 1;
    const y = span === 0 ? 12 : 23 - ( ( v - lo ) / span ) * 22;
    return `${ x.toFixed( 1 ) },${ y.toFixed( 1 ) }`;
  } );
  const svg = doc.createElementNS( SVG_NS, "svg" );
  svg.setAttribute( "viewBox", "0 0 120 24" );
  svg.setAttribute( "width", "120" );
  svg.setAttribute( "height", "24" );
  svg.setAttribute( "role", "img" );
  svg.setAttribute( "aria-label", `${ label }: ${ values.join( ", " ) }` );
  svg.setAttribute( "data-testid", "jobs-sparkline" );
  const line = doc.createElementNS( SVG_NS, "polyline" );
  line.setAttribute( "points", coords.join( " " ) );
  line.setAttribute( "fill", "none" );
  line.setAttribute( "stroke", "currentColor" );
  line.setAttribute( "stroke-width", "1.5" );
  svg.appendChild( line );
  return svg;
}

function addRow( doc: Document, list: HTMLElement, name: string, value: string, testid: string ): HTMLElement {
  const dt = el( doc, "dt", null, name, null );
  const dd = el( doc, "dd", null, value, testid );
  list.appendChild( dt );
  list.appendChild( dd );
  return dd;
}

function block( doc: Document, title: string, testid: string ): HTMLElement {
  const section = el( doc, "section", "jobs-block", null, testid );
  section.appendChild( el( doc, "h3", null, title, null ) );
  return section;
}

function reasonsBlock( doc: Document, job: JobEntry ): HTMLElement {
  const section = block( doc, "Reasons", "jobs-reasons" );
  if ( job.reasons.length === 0 && job.unknown_reason === null ) {
    section.appendChild( el( doc, "p", null, "No rule is true: nothing to report.", null ) );
    return section;
  }
  const ul = doc.createElement( "ul" );
  for ( const reason of job.reasons ) ul.appendChild( el( doc, "li", null, reason.text, "jobs-reason" ) );
  if ( job.unknown_reason !== null ) ul.appendChild( el( doc, "li", null, job.unknown_reason, "jobs-reason" ) );
  if ( job.machine_was_off ) ul.appendChild( el( doc, "li", null, "Missed while the machine was off.", "jobs-reason" ) );
  section.appendChild( ul );
  return section;
}

function stripBlock( doc: Document, job: JobEntry, todayIso: string ): HTMLElement {
  const section = block( doc, "Last attempts", "jobs-strip" );
  if ( job.strip.length === 0 ) {
    section.appendChild( el( doc, "p", null, NOT_REPORTED, null ) );
    return section;
  }
  const ol = doc.createElement( "ol" );
  ol.className = "jobs-strip-list";
  for ( const entry of job.strip ) {
    const text = entry.outcome === "missed"
      ? `${ formatWhen( entry.at, todayIso ) } MISSED (due, no run)`
      : `${ formatWhen( entry.at, todayIso ) } ${ entry.outcome }`;
    const li = el( doc, "li", `jobs-strip-${ entry.outcome }`, text, "jobs-strip-entry" );
    li.setAttribute( "data-outcome", entry.outcome );
    ol.appendChild( li );
  }
  section.appendChild( ol );
  return section;
}

function scanBlock( doc: Document, job: JobEntry, todayIso: string ): HTMLElement | null {
  if ( !job.applies.scan_debt || job.liveness !== null ) return null;
  const section = block( doc, "Scan debt", "jobs-scan" );
  const debt    = job.scan_debt;
  if ( debt === null ) {
    section.appendChild( el( doc, "p", null, NOT_REPORTED, null ) );
    return section;
  }
  const dl = doc.createElement( "dl" );
  addRow( doc, dl, "Count", debt.count === null ? NOT_REPORTED : `${ formatCount( debt.count ) } ${ debt.unit ?? "" }`.trim(), "jobs-scan-count" );
  addRow( doc, dl, "As of", formatWhen( debt.as_of, todayIso ), "jobs-scan-as-of" );
  addRow( doc, dl, "Drained last run", formatCount( debt.drained_last_run ), "jobs-scan-drained" );
  addRow( doc, dl, "Arrived last interval", formatCount( debt.arrived_last_interval ), "jobs-scan-arrived" );
  addRow( doc, dl, "Never checked", formatCount( debt.never_checked ), "jobs-scan-never" );
  addRow( doc, dl, "Clears in", clearsText( job ).replace( /^clears: /, "" ) || NOT_REPORTED, "jobs-scan-clears" );
  section.appendChild( dl );
  const spark = sparkline( doc, debt.points, "scan debt" );
  if ( spark !== null ) section.appendChild( spark );
  return section;
}

function fixBlock( doc: Document, job: JobEntry ): HTMLElement | null {
  if ( !job.applies.fix_debt ) return null;
  const section = block( doc, "Fix debt", "jobs-fix" );
  const debt    = job.fix_debt;
  if ( debt === null ) {
    section.appendChild( el( doc, "p", null, NOT_REPORTED, null ) );
    return section;
  }
  const dl = doc.createElement( "dl" );
  if ( debt.kind === "reported" ) {
    addRow( doc, dl, "Named, not acted on", formatCount( debt.open_reported ), "jobs-fix-reported" );
  } else {
    addRow( doc, dl, "Unfiled", formatCount( debt.unfiled ), "jobs-fix-unfiled" );
    addRow( doc, dl, "Filed in total", formatCount( debt.filed_total ), "jobs-fix-filed" );
    addRow( doc, dl, "Open now", formatCount( debt.open_now ), "jobs-fix-open" );
    addRow( doc, dl, "Closed in window", formatCount( debt.closed_in_window ), "jobs-fix-closed" );
    addRow( doc, dl, "Own mark", debt.own_mark ?? NOT_REPORTED, "jobs-fix-mark" );
  }
  section.appendChild( dl );
  const spark = sparkline( doc, debt.points, "rows opened" );
  if ( spark !== null ) section.appendChild( spark );
  if ( isSafeHref( debt.store_href ) ) section.appendChild( link( doc, debt.store_href, "Rows in the task store", "jobs-fix-store-link" ) );
  return section;
}

function scheduleBlock( doc: Document, job: JobEntry, todayIso: string ): HTMLElement {
  const section = block( doc, "Schedule", "jobs-schedule" );
  const dl      = doc.createElement( "dl" );
  const s       = job.schedule;
  if ( job.liveness !== null ) {
    addRow( doc, dl, "Liveness", `${ job.liveness.kind } unit ${ job.liveness.unit }`, "jobs-liveness" );
  }
  if ( job.schedule_unverified ) addRow( doc, dl, "Check", "schedule unverified: the installed schedule could not be read", "jobs-schedule-unverified" );
  addRow( doc, dl, "Runs", s === null || s.entries.length === 0 ? "unscheduled" : s.entries.join( "; " ), "jobs-schedule-entries" );
  addRow( doc, dl, "Last due", s === null ? NOT_REPORTED : formatWhen( s.last_due, todayIso ), "jobs-schedule-last-due" );
  addRow( doc, dl, "Next due", s === null ? NOT_REPORTED : formatWhen( s.next_due, todayIso ), "jobs-schedule-next-due" );
  addRow( doc, dl, "Grace", graceText( job ), "jobs-schedule-grace" );
  addRow( doc, dl, "Tells Rick", notifyIntervalText( job ), "jobs-notify-interval" );
  section.appendChild( dl );
  return section;
}

function evidenceBlock( doc: Document, job: JobEntry ): HTMLElement {
  const section = block( doc, "Evidence", "jobs-evidence" );
  if ( job.evidence.length === 0 ) {
    section.appendChild( el( doc, "p", null, NOT_REPORTED, null ) );
    return section;
  }
  const ul = doc.createElement( "ul" );
  for ( const item of job.evidence ) {
    const li = doc.createElement( "li" );
    if ( isSafeHref( item.href ) ) li.appendChild( link( doc, item.href, `${ item.label }: ${ item.path }`, "jobs-evidence-link" ) );
    else li.appendChild( el( doc, "span", null, `${ item.label }: ${ item.path }`, "jobs-evidence-path" ) );
    ul.appendChild( li );
  }
  section.appendChild( ul );
  return section;
}

function peopleBlock( doc: Document, job: JobEntry ): HTMLElement {
  const section = block( doc, "People", "jobs-people" );
  const dl      = doc.createElement( "dl" );
  addRow( doc, dl, "Owner", job.owner, "jobs-owner" );
  addRow( doc, dl, "Told", job.audience.length === 0 ? "the owner" : job.audience.join( ", " ), "jobs-audience" );
  section.appendChild( dl );
  if ( job.rows.length > 0 ) {
    const ul = doc.createElement( "ul" );
    for ( const row of job.rows ) {
      const li = doc.createElement( "li" );
      if ( isSafeHref( row.href ) ) li.appendChild( link( doc, row.href, row.title, "jobs-row-link" ) );
      else li.appendChild( el( doc, "span", null, row.title, "jobs-row-title" ) );
      ul.appendChild( li );
    }
    section.appendChild( ul );
  }
  if ( isSafeHref( job.detail_link ) ) section.appendChild( link( doc, job.detail_link, "Open the detail page", "jobs-detail-link" ) );
  return section;
}

function notReportedBlock( doc: Document, job: JobEntry ): HTMLElement {
  const section = block( doc, "Not reported", "jobs-not-reported" );
  const names   = notReportedNames( job );
  section.appendChild( el( doc, "p", null, names.length === 0 ? "Every figure was reported." : names.join( ", " ), "jobs-not-reported-names" ) );
  return section;
}

function runNowBlock( doc: Document, job: JobEntry, actions: JobsActions ): HTMLElement | null {
  if ( !actions.canRun || !job.runnable ) return null;
  const wrap   = el( doc, "div", "jobs-actions", null, null );
  const button = doc.createElement( "button" );
  button.type = "button";
  button.textContent = "Run now";
  button.setAttribute( "data-testid", "jobs-run-now" );
  const status = el( doc, "span", "jobs-run-status", null, "jobs-run-status" );
  status.setAttribute( "role", "status" );
  button.addEventListener( "click", () => {
    button.disabled = true;
    status.textContent = "Starting…";
    actions.runNow( job ).then(
      ( message ) => { status.textContent = message; button.disabled = false; },
      ( err: unknown ) => { status.textContent = `Run now failed: ${ String( err ) }`; button.disabled = false; },
    );
  } );
  wrap.appendChild( button );
  wrap.appendChild( status );
  return wrap;
}

function itemId( job: JobEntry ): string {
  return `jobs-${ job.job }${ job.target === null ? "" : `-${ job.target }` }`.replace( /[^A-Za-z0-9_-]/g, "-" );
}

/**
 * One job: the collapsed line (a button) and its expanded panel.
 *
 * Ensures:
 *   - the panel starts hidden and the button's aria-expanded tracks it
 *   - targets of a job are drawn as nested items inside the panel
 */
export function renderJob( doc: Document, job: JobEntry, todayIso: string, actions: JobsActions ): HTMLElement {
  const id      = itemId( job );
  const item    = el( doc, "section", "jobs-item", null, "jobs-item" );
  item.setAttribute( "data-job", job.job );
  item.setAttribute( "data-target", job.target ?? "" );
  item.setAttribute( "data-state", job.state );

  const heading = doc.createElement( "h2" );
  heading.className = "jobs-heading";
  const button = doc.createElement( "button" );
  button.type = "button";
  button.className = "jobs-line";
  button.id = `${ id }-line`;
  button.setAttribute( "aria-expanded", "false" );
  button.setAttribute( "aria-controls", `${ id }-panel` );
  button.setAttribute( "data-testid", "jobs-line" );
  const cells: Array<[ string, string ]> = [
    [ "jobs-caret", "▶" ],
    [ `jobs-dot jobs-state-${ job.state }`, "●" ],
    [ "jobs-title", job.target === null ? job.title : `${ job.title } (${ job.target })` ],
    [ "jobs-badge", badgeText( job ) ],
    [ "jobs-last-run", lastRunText( job, todayIso ) ],
    [ "jobs-last-finished", job.liveness === null ? lastFinishedText( job, todayIso ) : "" ],
    [ "jobs-scan-cell", scanText( job ) ],
    [ "jobs-fix-cell", fixText( job ) ],
    [ "jobs-clears-cell", clearsText( job ) ],
  ];
  for ( const [ cls, text ] of cells ) {
    const span = el( doc, "span", cls, text, cls.split( " " )[ 0 ] as string );
    if ( cls.startsWith( "jobs-dot" ) ) span.setAttribute( "aria-hidden", "true" );
    button.appendChild( span );
  }
  heading.appendChild( button );
  item.appendChild( heading );

  const panel = el( doc, "div", "jobs-panel", null, "jobs-panel" );
  panel.id = `${ id }-panel`;
  panel.setAttribute( "role", "region" );
  panel.setAttribute( "aria-labelledby", button.id );
  panel.hidden = true;
  panel.appendChild( reasonsBlock( doc, job ) );
  if ( job.liveness === null ) panel.appendChild( stripBlock( doc, job, todayIso ) );
  for ( const part of [ scanBlock( doc, job, todayIso ), fixBlock( doc, job ) ] ) if ( part !== null ) panel.appendChild( part );
  panel.appendChild( scheduleBlock( doc, job, todayIso ) );
  panel.appendChild( evidenceBlock( doc, job ) );
  panel.appendChild( peopleBlock( doc, job ) );
  panel.appendChild( notReportedBlock( doc, job ) );
  const run = runNowBlock( doc, job, actions );
  if ( run !== null ) panel.appendChild( run );
  for ( const target of sortJobs( job.targets ) ) panel.appendChild( renderJob( doc, target, todayIso, actions ) );
  item.appendChild( panel );

  button.addEventListener( "click", () => {
    const open = button.getAttribute( "aria-expanded" ) === "true";
    button.setAttribute( "aria-expanded", open ? "false" : "true" );
    panel.hidden = open;
    ( button.querySelector( ".jobs-caret" ) as HTMLElement ).textContent = open ? "▶" : "▼";
  } );
  return item;
}

/**
 * Replace the accordion's children with one item per job, worst state first.
 *
 * Ensures:
 *   - the same job id with two targets stays two items; nothing is merged or dropped
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function renderAccordion( doc: Document, mount: HTMLElement, summary: JobsSummary, actions: JobsActions ): void {
  mount.replaceChildren();
  for ( const job of sortJobs( summary.jobs ) ) mount.appendChild( renderJob( doc, job, summary.generated_at, actions ) );
}
