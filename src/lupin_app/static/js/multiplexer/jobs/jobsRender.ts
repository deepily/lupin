/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Builds the jobs list DOM.
//
// Row c80ef763: one list, the Scheduled Jobs pane merged in. One row per service. The collapsed line holds Service, Status, Last run and Last finished, a ⋯ button
// and a 📋. The ⋯ opens a second line (the Scan, Fix and Clears figures and the job's on/off switch)
// and a third (Run now and the job's targets). The long text is the 📋 abstract (abstractText.ts), not
// part of the list. Every text goes in through textContent, never innerHTML. Nothing here reads the
// clock or the network.

import {
  badgeText, clearsText, fixText, lastFinishedText, lastRunText, scanText, sortJobs, nextSort, DEFAULT_SORT,
} from "./jobsFormat";
import type { JobSort } from "./jobsFormat";
import { abstractMarkdown } from "./abstractText";
import { CRON_DRIFT_TEXT, CRON_UNREADABLE_TEXT, cronChangedText, cronInsideText, cronReadsText, cronStateText } from "./cronFormat";
import type { CronJobRow } from "./cronFormat";
import type { JobEntry, JobsSummary } from "./types";
import { renderDiscloseToggle } from "../render/templates/rowDisclosure";
import { abstractIndicator as buildAbstractIndicator } from "../render/templates/actionRequiredChrome";

/** What the page lets a rendered job do: Run now, and the switch's flip. */
export interface JobsActions {
  /** False hides every Run now button: the caller is not the operator. */
  canRun : boolean;
  runNow( job: JobEntry ): Promise<string>;
  /** False disables every Turn on / Turn off button: the caller is not an administrator. */
  canFlip : boolean;
  /** Every switch row, so a job inside another job's tick can say the host is off. */
  cronRows : readonly CronJobRow[];
  /** A click on a flip button; the owner of the list decides what it does. */
  requestFlip( row: CronJobRow, note: HTMLElement, button: HTMLElement ): void;
  /** The ids of the open rows: a toggle writes it and a redraw reads it. */
  open : Set<string>;
}

function el( doc: Document, tag: string, className: string | null, text: string | null, testid: string | null ): HTMLElement {
  const node = doc.createElement( tag );
  if ( className !== null ) node.className = className;
  if ( text !== null ) node.textContent = text;
  if ( testid !== null ) node.setAttribute( "data-testid", testid );
  return node;
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

/** The 📋 of a job: the delegated click handler opens its abstract. */
function abstractIndicator( doc: Document, job: JobEntry, todayIso: string, testid: string, cronRows: readonly CronJobRow[] ): HTMLElement {
  // raw: the multiplexer reads the markdown raw. abstractMarkdown always opens with a title line, so it is never blank.
  return buildAbstractIndicator( abstractMarkdown( job, todayIso, cronRows ), { doc, className: "jobs-abstract", title: "View details", testid } )!;
}

/** One job's switch: state, flip button, when it changed, whether it is read, and the notes. */
function switchCells( doc: Document, row: CronJobRow, actions: JobsActions ): HTMLElement {
  const unreadable = row.honoured && row.enabled === null;
  const wrap = el( doc, "span", unreadable ? "cron-item cron-unreadable" : "cron-item", null, "cron-item" );
  wrap.setAttribute( "data-job", row.job );
  wrap.append(
    el( doc, "span", "cron-schedule", row.schedule, "cron-schedule" ),
    el( doc, "span", `cron-state cron-state-${ cronStateText( row.enabled ).toLowerCase() }`, cronStateText( row.enabled ), "cron-state" ),
    el( doc, "span", "cron-changed", cronChangedText( row ), "cron-changed" ),
    el( doc, "span", "cron-honoured", cronReadsText( row ), "cron-honoured" ),
  );
  if ( row.drift ) wrap.appendChild( el( doc, "span", "cron-drift", CRON_DRIFT_TEXT, "cron-drift" ) );
  if ( unreadable ) wrap.appendChild( el( doc, "span", "cron-unreadable-note", CRON_UNREADABLE_TEXT, "cron-unreadable" ) );
  const inside = cronInsideText( row, actions.cronRows as CronJobRow[] );
  if ( inside !== null ) wrap.appendChild( el( doc, "span", "cron-inside", inside, "cron-inside" ) );
  const button = el( doc, "button", "cron-flip", row.enabled === true ? "Turn off" : "Turn on", "cron-flip" ) as HTMLButtonElement;
  button.type = "button";
  button.disabled = !actions.canFlip || row.enabled === null || !row.honoured;     // no key to flip yet, or nothing reads it
  const note = el( doc, "span", "cron-error", null, "cron-error" );
  note.setAttribute( "role", "alert" );
  note.hidden = true;
  button.addEventListener( "click", () => actions.requestFlip( row, note, button ) );
  wrap.append( button, note );
  return wrap;
}

/** Line 2: the figures that apply to the job, then its switch. */
function lineTwo( doc: Document, job: JobEntry, actions: JobsActions ): HTMLElement {
  const line = el( doc, "div", "jobs-line2", null, "jobs-line2" );
  const figures: Array<[ string, string, string ]> = [
    [ "Scan", scanText( job ), "jobs-fig-scan" ], [ "Fix", fixText( job ), "jobs-fig-fix" ], [ "Clears", clearsText( job ), "jobs-fig-clears" ],
  ];
  for ( const [ label, text, testid ] of figures ) if ( text !== "" ) line.appendChild( el( doc, "span", "jobs-fig", `${ label }: ${ text }`, testid ) );
  if ( job.cron !== undefined && job.cron !== null ) line.appendChild( switchCells( doc, job.cron, actions ) );
  return line;
}

/** One target of a job, as a compact line inside the parent's third line. */
function targetLine( doc: Document, target: JobEntry, todayIso: string ): HTMLElement {
  const line = el( doc, "div", "jobs-target", null, "jobs-target" );
  line.setAttribute( "data-job", target.job );
  line.setAttribute( "data-target", target.target ?? "" );
  line.setAttribute( "data-state", target.state );
  line.append(
    el( doc, "span", `jobs-dot jobs-state-${ target.state }`, "●", null ),
    el( doc, "span", "jobs-title", target.target === null ? target.title : `${ target.title } (${ target.target })`, "jobs-target-title" ),
    el( doc, "span", "jobs-badge", badgeText( target ), "jobs-target-badge" ),
    el( doc, "span", "jobs-last-run", lastRunText( target, todayIso ), "jobs-target-last-run" ),
    abstractIndicator( doc, target, todayIso, "jobs-target-abstract", [] ),      // a target has no switch of its own
  );
  return line;
}

/** Line 3: Run now, then the job's targets. */
function lineThree( doc: Document, job: JobEntry, todayIso: string, actions: JobsActions, sort: JobSort ): HTMLElement {
  const line = el( doc, "div", "jobs-line3", null, "jobs-line3" );
  const run  = runNowBlock( doc, job, actions );
  if ( run !== null ) line.appendChild( run );
  for ( const target of sortJobs( job.targets, sort ) ) line.appendChild( targetLine( doc, target, todayIso ) );
  if ( line.childElementCount === 0 ) line.textContent = "Nothing to run by hand, and no targets.";
  return line;
}

/**
 * One job: the collapsed line and its hidden second and third lines.
 *
 * Ensures:
 *   - the line holds the ⋯ button, the status dot, Service, Status, Last run, Last finished and the 📋, and no Scan, Fix or Clears
 *   - the lines start hidden unless `actions.open` holds the job's id, and the ⋯ button's aria-expanded tracks them
 *   - targets of a job are drawn as compact lines inside the third line
 */
export function renderJob( doc: Document, job: JobEntry, todayIso: string, actions: JobsActions, sort: JobSort = DEFAULT_SORT ): HTMLElement {
  const id      = itemId( job );
  const item    = el( doc, "section", "jobs-item", null, "jobs-item" );
  item.setAttribute( "data-job", job.job );
  item.setAttribute( "data-target", job.target ?? "" );
  item.setAttribute( "data-state", job.state );

  const heading = doc.createElement( "h2" );
  heading.className = "jobs-heading";
  const line = el( doc, "div", "jobs-line", null, "jobs-line" );
  line.id = `${ id }-line`;

  const toggle = renderDiscloseToggle( id );
  toggle.classList.add( "jobs-disclose" );
  toggle.setAttribute( "data-testid", "jobs-disclose" );
  toggle.setAttribute( "aria-controls", `${ id }-panel` );
  const cells: Array<[ string, string ]> = [
    [ `jobs-dot jobs-state-${ job.state }`, "●" ],
    [ "jobs-title", job.target === null ? job.title : `${ job.title } (${ job.target })` ],
    [ "jobs-badge", badgeText( job ) ],
    [ "jobs-last-run", lastRunText( job, todayIso ) ],
    [ "jobs-last-finished", job.liveness === null && job.cron_only !== true ? lastFinishedText( job, todayIso ) : "" ],
  ];
  const last = el( doc, "span", "jobs-disclose-cell", null, null );
  last.appendChild( toggle );
  for ( const [ cls, text ] of cells ) {
    const span = el( doc, "span", cls, text, cls.split( " " )[ 0 ] as string );
    if ( cls.startsWith( "jobs-dot" ) ) span.setAttribute( "aria-hidden", "true" );
    line.appendChild( span );
  }
  line.appendChild( abstractIndicator( doc, job, todayIso, "jobs-abstract", actions.cronRows ) );
  line.appendChild( last );                                    // Rick, 15 Nov: the ⋯ sits at the right-hand end of the row
  heading.appendChild( line );
  item.appendChild( heading );

  const panel = el( doc, "div", "jobs-panel", null, "jobs-panel" );
  panel.id = `${ id }-panel`;
  panel.setAttribute( "role", "region" );
  panel.setAttribute( "aria-labelledby", line.id );
  panel.append( lineTwo( doc, job, actions ), lineThree( doc, job, todayIso, actions, sort ) );
  const opened = actions.open.has( id );
  panel.hidden = !opened;
  toggle.setAttribute( "aria-expanded", opened ? "true" : "false" );
  item.appendChild( panel );

  toggle.addEventListener( "click", () => {
    const open = toggle.getAttribute( "aria-expanded" ) === "true";
    toggle.setAttribute( "aria-expanded", open ? "false" : "true" );
    panel.hidden = open;
    if ( open ) actions.open.delete( id ); else actions.open.add( id );
  } );
  return item;
}

/** The columns of one line, in grid order; `sortId` names the entry a click picks. */
const COLUMNS: ReadonlyArray<{ cls: string; label: string; sortId: string | null }> = [
  { cls: "jobs-dot",           label: "",              sortId: null },
  { cls: "jobs-title",         label: "Service",       sortId: "name" },
  { cls: "jobs-badge",         label: "Status",        sortId: "health" },
  { cls: "jobs-last-run",      label: "Last run",      sortId: "last-run" },
  { cls: "jobs-last-finished", label: "Last finished", sortId: null },
  { cls: "jobs-abstract",      label: "",              sortId: null },
  { cls: "jobs-disclose-cell", label: "",              sortId: null },
];

function arrow( sort: JobSort ): string { return sort.direction === "asc" ? " ▲" : " ▼"; }

function headerRow( doc: Document, sort: JobSort, onSort: ( next: JobSort ) => void ): HTMLElement {
  const row = el( doc, "div", "jobs-header jobs-line-grid", null, "jobs-header" );
  row.setAttribute( "role", "row" );
  for ( const col of COLUMNS ) {
    const cell = el( doc, "span", `jobs-head-cell ${ col.cls }`, null, null );
    cell.setAttribute( "role", "columnheader" );
    if ( col.sortId === null ) cell.textContent = col.label;
    else {
      const sortId = col.sortId, active = sort.id === sortId;
      const button = el( doc, "button", "jobs-sort-button", col.label + ( active ? arrow( sort ) : "" ), `jobs-sort-${ sortId }` ) as HTMLButtonElement;
      button.type = "button";
      button.addEventListener( "click", () => onSort( nextSort( sort, sortId ) ) );
      cell.setAttribute( "aria-sort", active ? ( sort.direction === "asc" ? "ascending" : "descending" ) : "none" );
      cell.appendChild( button );
    }
    row.appendChild( cell );
  }
  return row;
}

/** The pick each mount carries, so a refresh redraws in the order the reader chose. */
const picked = new WeakMap<HTMLElement, JobSort>();

/**
 * Replace the list's children with a note, a header row and one item per job.
 *
 * Ensures:
 *   - `summary.jobs` is already merged (mergeJobs): every item is one job, with its switch when it has one
 *   - with no `sort` given, the mount's last pick is used, or the active-first order when it has none
 *   - a click on the Service or Status heading redraws the accordion in the next order
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function renderAccordion( doc: Document, mount: HTMLElement, summary: JobsSummary, actions: JobsActions, sort?: JobSort ): void {
  const use = sort ?? picked.get( mount ) ?? DEFAULT_SORT;
  picked.set( mount, use );
  mount.replaceChildren();
  if ( actions.cronRows.length > 0 ) {
    mount.appendChild( el( doc, "p", "cron-note", actions.canFlip
      ? "Flipping a switch takes effect at the job's next start, or next tick for a loop. A run already going is not stopped."
      : "Read-only: only an administrator can flip a switch.", "cron-note" ) );
  }
  mount.appendChild( headerRow( doc, use, ( next ) => renderAccordion( doc, mount, summary, actions, next ) ) );
  for ( const job of sortJobs( summary.jobs, use ) ) mount.appendChild( renderJob( doc, job, summary.generated_at, actions, use ) );
  if ( summary.reporting_off_line ) {                        // row 4aa0ba1b: the server drops a switched-off job and says how many
    const line = doc.createElement( "p" );
    line.className = "jobs-off-line";
    line.setAttribute( "data-testid", "background-jobs-off-line" );
    line.textContent = summary.reporting_off_line;
    mount.appendChild( line );
  }
}
