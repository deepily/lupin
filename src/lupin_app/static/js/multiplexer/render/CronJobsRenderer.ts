/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Scheduled-jobs pane.
//
// A collapsible multiplexer section that shows each cron job's on/off switch, read from lupin-app.ini by
// GET /api/cron-jobs. An administrator flips one with PUT /api/cron-jobs/{job}/enabled; everyone else sees
// the switches read-only. The server's `caller_is_admin` decides that, never this file. A flip edits the INI
// key the job reads at its next start; it does not stop a run already going.
//
// Every text goes in through textContent, never innerHTML. The legacy client carries its own independent
// copy (static/js/cron-jobs.js); the two share no runtime code, by Rick's no-shared-code ruling (row 87812328).
//
// The `cron_job_switch_changed` frame (queue socket) arrives on the event bus with the row as its payload,
// so a flip made in another client repaints this pane without a reload.

import { ApiError } from "../api/ApiClient";
import type { EventBus } from "../shared/EventBus";
import { teardownScaffold } from "./dom";
import { renderSectionHeader, wireSectionCollapse } from "./templates/sectionHeader";
import type { SectionHeaderHandle } from "./templates/sectionHeader";

/** The list door, and the root of each job's flip door. */
export const CRON_JOBS_PATH   = "/api/cron-jobs";
/** How often the pane asks again, in milliseconds. */
export const CRON_JOBS_POLL_MS = 60_000;
/** What a row says when no flip has ever been recorded for it. */
export const CRON_NOT_REPORTED = "not reported";
/** What a row says when the file disagrees with the last recorded flip. */
export const CRON_DRIFT_TEXT   = "changed outside the endpoint";

/** One job's row, as GET /api/cron-jobs and the socket frame carry it. */
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
}

/** The list door's answer. */
export interface CronJobsSummary {
  jobs            : CronJobRow[];
  caller_is_admin : boolean;
}

/** The JSON client surface this pane calls. */
export interface CronJobsApi {
  get<T>( path: string ): Promise<T>;
  put<T>( path: string, body: unknown ): Promise<T>;
}

/** The pane's public surface. */
export interface CronJobsRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Stop polling, drop listeners and clear the root. Idempotent. */
  unmount(): void;
  /** Ask the list door again and redraw. Never rejects. */
  refresh(): Promise<void>;
}

/** Options for `createCronJobsRenderer`. Only `api` and `eventBus` are required. */
export interface CronJobsRendererOptions {
  api              : CronJobsApi;
  eventBus         : EventBus;
  doc?             : Document;
  setIntervalFn?   : ( fn: () => void, ms: number ) => number;
  clearIntervalFn? : ( id: number ) => void;
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

/** "who, YYYY-MM-DD HH:MM" for a row with a recorded flip, else the not-reported text. */
export function cronChangedText( row: CronJobRow ): string {
  if ( row.last_changed_by === null || row.last_changed_at === null ) return CRON_NOT_REPORTED;
  return `${ row.last_changed_by }, ${ row.last_changed_at.slice( 0, 16 ).replace( "T", " " ) }`;
}

/** The `detail` sentence of a refusal body, or null. */
function refusalDetail( err: ApiError ): string | null {
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
export function cronFlipFailureText( err: unknown ): string {
  if ( !( err instanceof ApiError ) ) return `Flip failed: ${ String( err ) }`;
  if ( err.status === 403 ) return "Only an administrator can flip a job's switch.";
  if ( err.status === 404 ) return "The server does not know this job.";
  if ( err.status === 409 ) return refusalDetail( err ) ?? "The configuration file does not carry this job's switch yet.";
  if ( err.status === 422 ) return refusalDetail( err ) ?? "The server refused this flip.";
  return `Flip failed (HTTP ${ err.status }).`;
}

class CronJobsRendererImpl implements CronJobsRenderer {
  private readonly api            : CronJobsApi;
  private readonly bus            : EventBus;
  private readonly doc            : Document;
  private readonly setIntervalFn  : ( fn: () => void, ms: number ) => number;
  private readonly clearIntervalFn: ( id: number ) => void;

  private root        : HTMLElement | null = null;
  private header      : SectionHeaderHandle | null = null;
  private errorEl     : HTMLElement | null = null;
  private mountEl     : HTMLElement | null = null;
  private collapseOff : ( () => void ) | null = null;
  private busOff      : ( () => void ) | null = null;
  private pollId      : number | null = null;
  private current     : CronJobsSummary = { jobs: [], caller_is_admin: false };

  constructor( opts: CronJobsRendererOptions ) {
    this.api             = opts.api;
    this.bus             = opts.eventBus;
    this.doc             = opts.doc ?? document;
    this.setIntervalFn   = opts.setIntervalFn ?? ( ( fn, ms ) => window.setInterval( fn, ms ) );
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( id ) => window.clearInterval( id ) );
  }

  mount( root: HTMLElement ): void {
    if ( this.root !== null ) throw new Error( "CronJobsRenderer already mounted" );
    this.root = root;

    const refreshBtn = this.doc.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "refresh-btn";
    refreshBtn.setAttribute( "data-testid", "multiplexer-cron-jobs-refresh" );
    refreshBtn.setAttribute( "title", "Refresh now" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => { void this.refresh(); } );

    this.header = renderSectionHeader( {
      icon    : "⏰",
      title   : "Scheduled Jobs",
      testid  : "multiplexer-cron-jobs-header",
      actions : [ refreshBtn ],
    } );
    this.header.countEl.setAttribute( "data-testid", "multiplexer-cron-jobs-count" );
    this.header.countEl.textContent = "…";

    const content = this.doc.createElement( "div" );
    content.className = "section-content cron-jobs-content";
    content.setAttribute( "data-testid", "multiplexer-cron-jobs-content" );
    this.errorEl = this.doc.createElement( "p" );
    this.errorEl.className = "cron-error-banner";
    this.errorEl.setAttribute( "role", "alert" );
    this.errorEl.setAttribute( "data-testid", "cron-jobs-error" );
    this.errorEl.hidden = true;
    this.mountEl = this.doc.createElement( "div" );
    this.mountEl.className = "cron-accordion";
    this.mountEl.setAttribute( "data-testid", "cron-jobs-container" );
    content.append( this.errorEl, this.mountEl );

    root.replaceChildren( this.header.header, content );
    this.collapseOff = wireSectionCollapse( root, this.header );
    this.busOff      = this.bus.on<CronJobRow>( "cron_job_switch_changed", ( e ) => this.applyRow( e.payload ) );
    this.pollId      = this.setIntervalFn( () => { void this.refresh(); }, CRON_JOBS_POLL_MS );
    void this.refresh();
  }

  unmount(): void {
    if ( this.pollId !== null ) this.clearIntervalFn( this.pollId );
    if ( this.busOff !== null ) this.busOff();
    teardownScaffold( [], this.collapseOff, this.root );
    this.pollId = null; this.collapseOff = null; this.busOff = null; this.root = null;
    this.header = null; this.errorEl = null; this.mountEl = null;
  }

  async refresh(): Promise<void> {
    const errorEl = this.errorEl;
    if ( this.mountEl === null || errorEl === null ) return;
    try {
      const summary = await this.api.get<CronJobsSummary>( CRON_JOBS_PATH );
      if ( this.mountEl === null ) return;                       // unmounted while the request was out
      this.paint( summary );
      errorEl.hidden = true;
    } catch ( err ) {
      errorEl.textContent = `Could not load the scheduled jobs: ${ err instanceof ApiError ? `HTTP ${ err.status }` : String( err ) }`;
      errorEl.hidden = false;
    }
  }

  // One row came back from the server (a flip's answer, or another client's frame): swap it in place.
  private applyRow( row: CronJobRow ): void {
    if ( this.mountEl === null || row === null || typeof row !== "object" || typeof row.job !== "string" ) return;
    const index = this.current.jobs.findIndex( ( j ) => j.job === row.job );
    if ( index === -1 ) return;
    this.current.jobs[ index ] = row;
    this.paint( this.current );
  }

  private paint( summary: CronJobsSummary ): void {
    const mountEl = this.mountEl as HTMLElement;
    const header  = this.header as SectionHeaderHandle;
    this.current  = summary;
    mountEl.replaceChildren();
    const note = this.el( "p", "cron-note", summary.caller_is_admin
      ? "Flipping a switch takes effect at the job's next start. A run already going is not stopped."
      : "Read-only: only an administrator can flip a switch.", "cron-note" );
    mountEl.appendChild( note );
    for ( const row of summary.jobs ) mountEl.appendChild( this.renderRow( row, summary.caller_is_admin ) );
    const off = summary.jobs.filter( ( j ) => j.enabled === false ).length;
    header.countEl.textContent = `${ summary.jobs.length }${ off > 0 ? ` (${ off } off)` : "" }`;
  }

  private el( tag: string, cls: string, text: string | null, testid: string ): HTMLElement {
    const node = this.doc.createElement( tag );
    node.className = cls;
    if ( text !== null ) node.textContent = text;
    node.setAttribute( "data-testid", testid );
    return node;
  }

  private renderRow( row: CronJobRow, canFlip: boolean ): HTMLElement {
    const item  = this.el( "div", "cron-item", null, "cron-item" );
    item.setAttribute( "data-job", row.job );
    item.append(
      this.el( "span", "cron-title", row.title, "cron-title" ),
      this.el( "span", "cron-schedule", row.schedule, "cron-schedule" ),
      this.el( "span", `cron-state cron-state-${ cronStateText( row.enabled ).toLowerCase() }`, cronStateText( row.enabled ), "cron-state" ),
      this.el( "span", "cron-changed", cronChangedText( row ), "cron-changed" ),
      this.el( "span", "cron-honoured", row.honoured ? "reads its switch" : "does not read its switch yet", "cron-honoured" ),
    );
    if ( row.drift ) item.appendChild( this.el( "span", "cron-drift", CRON_DRIFT_TEXT, "cron-drift" ) );
    const button = this.el( "button", "cron-flip", row.enabled === true ? "Turn off" : "Turn on", "cron-flip" ) as HTMLButtonElement;
    button.type = "button";
    button.disabled = !canFlip || row.enabled === null || !row.honoured;     // no key to flip yet, or nothing reads it
    const note = this.el( "span", "cron-error", null, "cron-error" );
    note.setAttribute( "role", "alert" );
    note.hidden = true;
    button.addEventListener( "click", () => { void this.flip( row, note ); } );
    item.append( button, note );
    return item;
  }

  private async flip( row: CronJobRow, note: HTMLElement ): Promise<void> {
    try {
      const answer = await this.api.put<CronJobRow>( cronFlipPath( row.job ), { on: row.enabled !== true } );
      this.applyRow( answer );
    } catch ( err ) {
      note.textContent = cronFlipFailureText( err );
      note.hidden = false;
    }
  }
}

/** Build the renderer. It paints nothing until `mount()` is called. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function createCronJobsRenderer( opts: CronJobsRendererOptions ): CronJobsRenderer {
  return new CronJobsRendererImpl( opts );
}
