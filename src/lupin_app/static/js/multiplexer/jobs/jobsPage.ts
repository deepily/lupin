/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The jobs page: one accordion.
//
// Split from ./boot.ts so the wiring is unit-tested with injected seams; boot.ts only binds the real
// browser globals. The page computes no health: it asks GET /api/jobs/summary and formats the answer.
// The one action it offers is Run now: POST /api/jobs/{job}/run.

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import { bounceToLoginOnDeadSession, redirectToLoginIfUnauthenticated } from "../auth/authGuard";
import type { RedirectTarget } from "../auth/authGuard";
import { ApiError } from "../api/ApiClient";
import { headerLine } from "./jobsFormat";
import { renderAccordion } from "./jobsRender";
import type { JobsActions } from "./jobsRender";
import type { JobEntry, JobRunStarted, JobsSummary } from "./types";

/** The summary door. */
export const JOBS_SUMMARY_PATH = "/api/jobs/summary";
/** The id of the header line element. */
export const JOBS_HEADER_ID    = "jobs-header";
/** The id of the error element. */
export const JOBS_ERROR_ID     = "jobs-error";
/** The id of the accordion mount. */
export const JOBS_MOUNT_ID     = "jobs-accordion";
/** The id of the Refresh button. */
export const JOBS_REFRESH_ID   = "jobs-refresh";

/** The JSON client surface this page calls. */
export interface JobsApi {
  get<T>( path: string ): Promise<T>;
  post<T>( path: string, body: unknown ): Promise<T>;
}

/** The `window.location` surface the page reads and redirects through. */
export interface JobsLocation {
  readonly pathname : string;
  readonly search   : string;
  href              : string;
}

/** What `bootJobsPage` needs from the browser. */
export interface JobsPageDeps {
  doc      : Document;
  location : JobsLocation;
  storage  : StorageService;
  bus      : EventBus;
  /** Built only after the login guard passes. */
  connect  : () => JobsApi;
}

/** How the boot ended. `loaded` resolves once the first summary or its failure is shown. */
export type JobsPageResult =
  | { status: "redirected" }
  | { status: "started"; loaded: Promise<void>; refresh: () => Promise<void> };

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
 */
export function runNowFailureText( err: unknown ): string {
  if ( !( err instanceof ApiError ) ) return `Run now failed: ${ String( err ) }`;
  if ( err.status === 403 ) return "Only Rick's login can run a job by hand.";
  if ( err.status === 404 ) return "The reader does not know this job.";
  if ( err.status === 409 ) return "Not started: the job's run lock is held, so a run is already going.";
  if ( err.status === 422 ) return "This job cannot be run by hand.";
  return `Run now failed (HTTP ${ err.status }).`;
}

/** The `RedirectTarget` view of the page's location. The pathname keeps the query. */
export function redirectTarget( location: JobsLocation ): RedirectTarget {
  return {
    get pathname(): string { return `${ location.pathname }${ location.search }`; },
    get href(): string     { return location.href; },
    set href( value: string ) { location.href = value; },
  };
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
function requireElement( doc: Document, id: string ): HTMLElement {
  const el = doc.getElementById( id );
  if ( el === null ) throw new Error( `jobs page: #${ id } not found` );
  return el;
}

/**
 * Boot the jobs page.
 *
 * Requires:
 *   - doc carries #jobs-header, #jobs-error, #jobs-accordion and #jobs-refresh
 *
 * Ensures:
 *   - no access token: redirects to login and connects nothing
 *   - otherwise fetches the summary once, draws the accordion, and redraws on Refresh
 *   - a failed fetch shows its reason in #jobs-error and leaves the last good accordion on screen
 *   - Run now posts to the job's own door and prints the outcome beside the button
 *
 * Raises:
 *   - Error if a required element is missing
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function bootJobsPage( deps: JobsPageDeps ): JobsPageResult {
  const headerEl  = requireElement( deps.doc, JOBS_HEADER_ID );
  const errorEl   = requireElement( deps.doc, JOBS_ERROR_ID );
  const mountEl   = requireElement( deps.doc, JOBS_MOUNT_ID );
  const refreshEl = requireElement( deps.doc, JOBS_REFRESH_ID );

  const target = redirectTarget( deps.location );
  if ( redirectToLoginIfUnauthenticated( deps.storage, target ) ) return { status : "redirected" };
  bounceToLoginOnDeadSession( deps.bus, deps.storage, target );

  const api = deps.connect();
  const makeActions = ( canRun: boolean ): JobsActions => ( {
    canRun,
    async runNow( job ) {
      try {
        const started = await api.post<JobRunStarted>( runNowPath( job ), undefined );
        return `Started at ${ started.started_at } (pid ${ started.pid }).`;
      } catch ( err ) {
        return runNowFailureText( err );
      }
    },
  } );

  const refresh = async (): Promise<void> => {
    try {
      const summary = await api.get<JobsSummary>( JOBS_SUMMARY_PATH );
      renderAccordion( deps.doc, mountEl, summary, makeActions( summary.caller_is_operator ) );
      headerEl.textContent = headerLine( summary.jobs );
      errorEl.hidden = true;
    } catch ( err ) {
      errorEl.textContent = `Could not load the jobs: ${ err instanceof ApiError ? `HTTP ${ err.status }` : String( err ) }`;
      errorEl.hidden = false;
    }
  };
  refreshEl.addEventListener( "click", () => { void refresh(); } );
  return { status : "started", loaded : refresh(), refresh };
}
