/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Background-jobs pane.
//
// A collapsible multiplexer section that holds the jobs accordion (row d540113f).
// Rick ruled that the accordion belongs to both notification clients, not to a page of its own.
// It sits right after the Epic Board.
//
// The pane computes no health. It asks GET /api/jobs/summary and formats the answer through
// ../jobs/jobsRender. Its one action is Run now: POST /api/jobs/{job}/run.
//
// The legacy client carries its own independent copy (static/js/background-jobs.js); the two share
// no runtime code, by Rick's no-shared-code ruling (row 87812328).

import { ApiError } from "../api/ApiClient";
import { headerLine } from "../jobs/jobsFormat";
import { renderAccordion } from "../jobs/jobsRender";
import type { JobsActions } from "../jobs/jobsRender";
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

/** Options for `createBackgroundJobsRenderer`. Only `api` is required. */
export interface BackgroundJobsRendererOptions {
  api              : BackgroundJobsApi;
  doc?             : Document;
  setIntervalFn?   : ( fn: () => void, ms: number ) => number;
  clearIntervalFn? : ( id: number ) => void;
}

/** The path of the Run now door for one job or one target of a job. */
export function runNowPath( job: JobEntry ): string {
  const base = `/api/jobs/${ encodeURIComponent( job.job ) }/run`;
  return job.target === null ? base : `${ base }?target=${ encodeURIComponent( job.target ) }`;
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
  private readonly doc            : Document;
  private readonly setIntervalFn  : ( fn: () => void, ms: number ) => number;
  private readonly clearIntervalFn: ( id: number ) => void;

  private root        : HTMLElement | null = null;
  private header      : SectionHeaderHandle | null = null;
  private errorEl     : HTMLElement | null = null;
  private mountEl     : HTMLElement | null = null;
  private collapseOff : ( () => void ) | null = null;
  private pollId      : number | null = null;

  constructor( opts: BackgroundJobsRendererOptions ) {
    this.api             = opts.api;
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
    this.pollId = this.setIntervalFn( () => { void this.refresh(); }, JOBS_POLL_MS );
    void this.refresh();
  }

  unmount(): void {
    if ( this.pollId !== null ) this.clearIntervalFn( this.pollId );
    teardownScaffold( [], this.collapseOff, this.root );
    this.pollId = null; this.collapseOff = null; this.root = null;
    this.header = null; this.errorEl = null; this.mountEl = null;
  }

  async refresh(): Promise<void> {
    const mountEl = this.mountEl, errorEl = this.errorEl, header = this.header;
    if ( mountEl === null || errorEl === null || header === null ) return;
    try {
      const summary = await this.api.get<JobsSummary>( JOBS_SUMMARY_PATH );
      if ( this.mountEl === null ) return;                       // unmounted while the request was out
      renderAccordion( this.doc, mountEl, summary, this.actions( summary.caller_is_operator ) );
      header.countEl.textContent = String( summary.jobs.length );
      errorEl.hidden = true;
      this.updateHeadline( headerLine( summary.jobs ) );
    } catch ( err ) {
      errorEl.textContent = `Could not load the jobs: ${ err instanceof ApiError ? `HTTP ${ err.status }` : String( err ) }`;
      errorEl.hidden = false;
    }
  }

  private updateHeadline( line: string ): void {
    ( this.header as SectionHeaderHandle ).header.setAttribute( "title", line );
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
    };
  }
}

/** Build the renderer. It paints nothing until `mount()` is called. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function createBackgroundJobsRenderer( opts: BackgroundJobsRendererOptions ): BackgroundJobsRenderer {
  return new BackgroundJobsRendererImpl( opts );
}
