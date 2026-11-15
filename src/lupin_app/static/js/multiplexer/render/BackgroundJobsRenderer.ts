/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Background-jobs pane.
//
// Rows d540113f and c80ef763: the one jobs list. A collapsible multiplexer section that holds the jobs list. Rick ruled that the list belongs to both
// notification clients, not to a page of its own, and (row c80ef763) that the Scheduled Jobs pane is
// part of it: each job's on/off switch sits on its second line. It sits right after the Epic Board.
//
// The pane computes no health. It asks GET /api/jobs/summary and GET /api/cron-jobs together, joins
// them by job id (../jobs/mergedRows) and formats the answer through ../jobs/jobsRender. Its two
// actions are Run now (POST /api/jobs/{job}/run) and the switch (PUT /api/cron-jobs/{job}/enabled).
// A `cron_job_switch_changed` frame (queue socket) repaints a switch flipped in another client.
//
// The legacy client carries its own independent copy (static/js/background-jobs.js and cron-jobs.js);
// the two share no runtime code, by Rick's no-shared-code ruling (row 87812328).

import { ApiError } from "../api/ApiClient";
import type { EventBus } from "../shared/EventBus";
import { CRON_CONFIRM_TEXT, CRON_JOBS_PATH, cronFlipFailureText, cronFlipPath, refusalDetail } from "../jobs/cronFormat";
import type { CronJobRow, CronJobsSummary } from "../jobs/cronFormat";
import { headerLine } from "../jobs/jobsFormat";
import { renderAccordion } from "../jobs/jobsRender";
import type { JobsActions } from "../jobs/jobsRender";
import { mergeJobs } from "../jobs/mergedRows";
import type { JobEntry, JobRunStarted, JobsSummary } from "../jobs/types";
import { teardownScaffold } from "./dom";
import { renderSectionHeader, wireSectionCollapse } from "./templates/sectionHeader";
import type { SectionHeaderHandle } from "./templates/sectionHeader";

/** The summary door. */
export const JOBS_SUMMARY_PATH = "/api/jobs/summary";
/** How often the pane asks again, in milliseconds. */
export const JOBS_POLL_MS      = 60_000;

/** The JSON client surface this pane calls. */
export interface BackgroundJobsApi {
  get<T>( path: string ): Promise<T>;
  post<T>( path: string, body: unknown ): Promise<T>;
  put<T>( path: string, body: unknown ): Promise<T>;
}

/** The pane's public surface. */
export interface BackgroundJobsRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Stop polling, drop listeners and clear the root. Idempotent. */
  unmount(): void;
  /** Ask the summary door again and redraw. Never rejects. */
  refresh(): Promise<void>;
}

/** Options for `createBackgroundJobsRenderer`. Only `api` and `eventBus` are required. */
export interface BackgroundJobsRendererOptions {
  api              : BackgroundJobsApi;
  eventBus         : EventBus;
  doc?             : Document;
  setIntervalFn?   : ( fn: () => void, ms: number ) => number;
  clearIntervalFn? : ( id: number ) => void;
}

/** The path of the Run now door for one job or one target of a job. */
export function runNowPath( job: JobEntry ): string {
  const base = `/api/jobs/${ encodeURIComponent( job.job ) }/run`;
  return job.target === null ? base : `${ base }?target=${ encodeURIComponent( job.target ) }`;
}

/**
 * Turn the answer to a Run now request into one sentence for the panel.
 *
 * Ensures:
 *   - 403, 404, 409 and 422 each get their own plain-words line; anything else shows its status
 *   - a 422 whose body carries a `detail` (a launch that failed, naming the path) shows that detail instead of the generic line
 */
export function runNowFailureText( err: unknown ): string {
  if ( !( err instanceof ApiError ) ) return `Run now failed: ${ String( err ) }`;
  if ( err.status === 403 ) return "Only Rick's login can run a job by hand.";
  if ( err.status === 404 ) return "The reader does not know this job.";
  if ( err.status === 409 ) return "Not started: the job's run lock is held, so a run is already going.";
  if ( err.status === 422 ) return refusalDetail( err ) ?? "This job cannot be run by hand.";
  return `Run now failed (HTTP ${ err.status }).`;
}

class BackgroundJobsRendererImpl implements BackgroundJobsRenderer {
  private readonly api            : BackgroundJobsApi;
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
  private summary     : JobsSummary | null = null;                       // the last good answer of each door
  private cron        : CronJobsSummary = { jobs : [], caller_is_admin : false };
  private readonly open = new Set<string>();                              // the rows whose ⋯ is open, kept across a repaint
  private pendingConfirm : string | null = null;                          // the job whose turn-off waits for its confirming click

  constructor( opts: BackgroundJobsRendererOptions ) {
    this.api             = opts.api;
    this.bus             = opts.eventBus;
    this.doc             = opts.doc ?? document;
    this.setIntervalFn   = opts.setIntervalFn ?? ( ( fn, ms ) => window.setInterval( fn, ms ) );
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( id ) => window.clearInterval( id ) );
  }

  mount( root: HTMLElement ): void {
    if ( this.root !== null ) throw new Error( "BackgroundJobsRenderer already mounted" );
    this.root = root;

    const refreshBtn = this.doc.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "refresh-btn";
    refreshBtn.setAttribute( "data-testid", "multiplexer-background-jobs-refresh" );
    refreshBtn.setAttribute( "title", "Refresh now" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => { void this.refresh(); } );

    this.header = renderSectionHeader( {
      icon    : "🔁",
      title   : "Background Jobs",
      testid  : "multiplexer-background-jobs-header",
      actions : [ refreshBtn ],
    } );
    this.header.countEl.setAttribute( "data-testid", "multiplexer-background-jobs-count" );
    this.header.countEl.textContent = "…";

    const content = this.doc.createElement( "div" );
    content.className = "section-content background-jobs-content";
    content.setAttribute( "data-testid", "multiplexer-background-jobs-content" );
    this.errorEl = this.doc.createElement( "p" );
    this.errorEl.className = "jobs-error";
    this.errorEl.setAttribute( "role", "alert" );
    this.errorEl.setAttribute( "data-testid", "jobs-error" );
    this.errorEl.hidden = true;
    this.mountEl = this.doc.createElement( "div" );
    this.mountEl.className = "jobs-accordion";
    this.mountEl.setAttribute( "data-testid", "jobs-accordion" );
    content.append( this.errorEl, this.mountEl );

    root.replaceChildren( this.header.header, content );
    this.collapseOff = wireSectionCollapse( root, this.header );
    this.busOff      = this.bus.on<CronJobRow>( "cron_job_switch_changed", ( e ) => this.applyRow( e.payload ) );
    this.pollId = this.setIntervalFn( () => { void this.refresh(); }, JOBS_POLL_MS );
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
    const [ jobs, cron ] = await Promise.allSettled( [ this.api.get<JobsSummary>( JOBS_SUMMARY_PATH ), this.api.get<CronJobsSummary>( CRON_JOBS_PATH ) ] );
    if ( this.mountEl === null ) return;                       // unmounted while the requests were out
    const problems: string[] = [];
    if ( jobs.status === "fulfilled" ) this.summary = jobs.value;
    else problems.push( `Could not load the jobs: ${ failureText( jobs.reason ) }` );
    if ( cron.status === "fulfilled" ) this.cron = cron.value;
    else problems.push( `Could not load the scheduled jobs: ${ failureText( cron.reason ) }` );
    this.paint();
    errorEl.textContent = problems.join( " " );
    errorEl.hidden = problems.length === 0;
  }

  // One switch row came back from the server (a flip's answer, or another client's frame): swap it in place.
  private applyRow( row: CronJobRow ): void {
    if ( this.mountEl === null || row === null || typeof row !== "object" || typeof row.job !== "string" ) return;
    const index = this.cron.jobs.findIndex( ( j ) => j.job === row.job );
    if ( index === -1 ) return;
    this.cron.jobs[ index ] = row;
    this.paint();
  }

  // Draw the list from the last good answers. Nothing is drawn until the summary has arrived once.
  private paint(): void {
    const mountEl = this.mountEl as HTMLElement;
    const header  = this.header as SectionHeaderHandle;
    if ( this.summary === null ) return;
    this.pendingConfirm = null;        // a redraw drops a half-finished confirmation, so one stale click never turns a job off
    const merged = mergeJobs( this.summary.jobs, this.cron.jobs );
    renderAccordion( this.doc, mountEl, { ...this.summary, jobs : merged }, this.actions( this.summary.caller_is_operator ) );
    const off = this.cron.jobs.filter( ( j ) => j.enabled === false ).length;
    header.countEl.textContent = `${ merged.length }${ off > 0 ? ` (${ off } off)` : "" }`;
    header.header.setAttribute( "title", headerLine( this.summary.jobs ) );
  }

  private actions( canRun: boolean ): JobsActions {
    return {
      canRun,
      runNow: async ( job ) => {
        try {
          const started = await this.api.post<JobRunStarted>( runNowPath( job ), undefined );
          return `Started at ${ started.started_at } (pid ${ started.pid }).`;
        } catch ( err ) {
          return runNowFailureText( err );
        }
      },
      canFlip     : this.cron.caller_is_admin,
      cronRows    : this.cron.jobs,
      requestFlip : ( row, note, button ) => { void this.requestFlip( row, note, button ); },
      open        : this.open,
    };
  }

  // An alarm job's turn-off waits for a second, confirming click.
  private async requestFlip( row: CronJobRow, note: HTMLElement, button: HTMLElement ): Promise<void> {
    if ( row.alarm === true && row.enabled === true && this.pendingConfirm !== row.job ) {
      this.pendingConfirm = row.job;
      button.textContent  = "Confirm: turn off";
      note.textContent    = CRON_CONFIRM_TEXT;
      note.hidden         = false;
      return;
    }
    this.pendingConfirm = null;
    try {
      this.applyRow( await this.api.put<CronJobRow>( cronFlipPath( row.job ), { on : row.enabled !== true } ) );
    } catch ( err ) {
      note.textContent = cronFlipFailureText( err );
      note.hidden = false;
    }
  }
}

/** The reason a door failed, in a few words. */
function failureText( reason: unknown ): string {
  return reason instanceof ApiError ? `HTTP ${ reason.status }` : String( reason );
}

/** Build the renderer. It paints nothing until `mount()` is called. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function createBackgroundJobsRenderer( opts: BackgroundJobsRendererOptions ): BackgroundJobsRenderer {
  return new BackgroundJobsRendererImpl( opts );
}
