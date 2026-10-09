/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line (same as docLink.ts:1).
// Doc viewer — the "Make a podcast" button on a file view (row e23b9ed6, Rick's own P0).
//
// The doc viewer page (`/app/docs?path=…`) is the ONE page both clients show a document through: the
// legacy notifications client opens it in a pane iframe and the multiplexer embeds it in its reading pane.
// So this module is loaded by that page, once, and both clients get the button.
//
// WHAT A CLICK DOES. The button asks the server whether the file can be podcast (`GET …/from-viewer/check`),
// and shows itself only when it can. A click opens an in-page confirmation naming the file and its size,
// never a browser dialog. Yes posts `{ path }` to `POST …/from-viewer`, which judges the file again, claims
// one job per person, file and bytes, and queues it. The page never holds a list of allowed file kinds:
// the server's answer is the list.
//
// All logic is here and takes its browser pieces as arguments, so a test can drive every branch.

/** The two server doors the page calls. */
export const CHECK_URL = "/api/podcast-proxy/from-viewer/check";
export const START_URL = "/api/podcast-proxy/from-viewer";

/** The event the page fires, with `detail.path`, once it knows it is showing a FILE (not a listing). */
export const FILE_EVENT = "doc-viewer-file";

/** Where the page leaves the path when it fired the event before this module had loaded. */
export const FILE_PATH_GLOBAL = "__docViewerFilePath";

/** The ids the page's HTML gives the pieces. */
export const IDS = {
  toolbar : "doc-viewer-toolbar",
  button  : "doc-podcast-btn",
  panel   : "doc-podcast-confirm",
  text    : "doc-podcast-text",
  yes     : "doc-podcast-yes",
  cancel  : "doc-podcast-cancel",
  status  : "doc-download-status",
} as const;

export type PodcastState = "hidden" | "ready" | "confirming" | "posting" | "done";

/** What the module needs from the browser, so a test can hand it stand-ins. */
export interface DocPodcastDeps {
  doc         : Document;
  authedFetch : ( url: string, init: RequestInit ) => Promise<Response>;
  path        : string;
}

export interface DocPodcast {
  start : () => Promise<void>;
  state : () => PodcastState;
}

/** The browser window's two members this module reads. */
export interface DocWindowLike {
  __docViewerAuthedFetch? : ( url: string, init: RequestInit ) => Promise<Response>;
  __docViewerFilePath?    : string;
}

/**
 * A byte count a person can read.
 *
 * Ensures: "812 B", "4.2 KB", "1.3 MB"; never a fraction of a byte.
 */
export function humanSize( bytes: number ): string {
  if ( bytes < 1024 ) return `${bytes} B`;
  if ( bytes < 1024 * 1024 ) return `${( bytes / 1024 ).toFixed( 1 )} KB`;
  return `${( bytes / ( 1024 * 1024 ) ).toFixed( 1 )} MB`;
}

/** The question the confirmation asks. Names the file and its size. */
export function confirmCopy( name: string, size: number ): string {
  return `Make a podcast of ${name} (${humanSize( size )})? The whole file is read out to a voice model.`;
}

/**
 * The sentence for a refusal or a failure, from the server's `{ detail: { code, message } }` when it sent one.
 *
 * Ensures: the server's own message when present; else "Podcast failed (HTTP <status>)".
 */
export function refusalText( status: number, body: unknown ): string {
  const detail = ( body as { detail?: { message?: unknown } } | null )?.detail;
  if ( detail !== undefined && detail !== null && typeof detail.message === "string" && detail.message !== "" ) return detail.message;
  return `Podcast failed (HTTP ${status})`;
}

async function readJson( response: Response ): Promise<unknown> {
  try { return await response.json(); } catch { return null; }
}

/**
 * Build the button's behaviour over the page's elements.
 *
 * Requires: the page's HTML carries the ids in IDS; deps.path is the page's `?path=` value.
 * Ensures:
 *   - `start()` shows the button only when the check answers ok; any other answer leaves the page untouched
 *   - a click opens the confirmation; Cancel closes it and posts nothing
 *   - Yes posts once: a second Yes while posting, or after done, does nothing
 *   - success and "already started" both say the job id beside the button; a refusal says its sentence and
 *     leaves the button usable
 *   - `start()` wires the elements once, however many times it is called
 */
export function createDocPodcast( deps: DocPodcastDeps ): DocPodcast {
  let state  : PodcastState = "hidden";
  let wired                 = false;
  let name                  = "";
  let size                  = 0;
  const el = ( id: string ): HTMLElement => deps.doc.getElementById( id ) as HTMLElement;
  const say = ( text: string, good = false ): void => {
    el( IDS.status ).textContent = text;
    el( IDS.status ).classList.toggle( "is-ok", good );
  };

  async function post(): Promise<void> {
    state = "posting";
    ( el( IDS.yes ) as HTMLButtonElement ).disabled = true;
    say( "Starting the podcast…" );
    let outcome: { ok: boolean; status: number; body: any };
    try {
      const response = await deps.authedFetch( START_URL, {
        method  : "POST",
        headers : { "Content-Type": "application/json" },
        body    : JSON.stringify( { path: deps.path } ),
      } );
      outcome = { ok: response.ok, status: response.status, body: await readJson( response ) };
    } catch {
      outcome = { ok: false, status: 0, body: null };
    }
    el( IDS.panel ).hidden = true;
    ( el( IDS.yes ) as HTMLButtonElement ).disabled = false;
    if ( outcome.ok ) {
      state = "done";
      ( el( IDS.button ) as HTMLButtonElement ).disabled = true;
      say( `Podcast queued: job ${outcome.body.job_id}`, true );
    } else if ( outcome.status === 409 && outcome.body?.detail?.job_id ) {
      state = "done";
      ( el( IDS.button ) as HTMLButtonElement ).disabled = true;
      say( `Already started: job ${outcome.body.detail.job_id}`, true );
    } else {
      state = "ready";
      say( outcome.status === 0 ? "Could not reach the server." : refusalText( outcome.status, outcome.body ) );
    }
  }

  function wire(): void {
    wired = true;
    el( IDS.button ).addEventListener( "click", () => {
      if ( state !== "ready" ) return;
      state = "confirming";
      el( IDS.text ).textContent = confirmCopy( name, size );
      el( IDS.panel ).hidden = false;
      say( "" );
    } );
    el( IDS.cancel ).addEventListener( "click", () => {
      if ( state !== "confirming" ) return;
      state = "ready";
      el( IDS.panel ).hidden = true;
    } );
    el( IDS.yes ).addEventListener( "click", () => {
      if ( state !== "confirming" ) return;
      void post();
    } );
  }

  async function start(): Promise<void> {
    if ( wired ) return;
    let facts: { name: string; size: number } | null = null;
    try {
      const response = await deps.authedFetch( `${CHECK_URL}?path=${encodeURIComponent( deps.path )}`, {} );
      if ( response.ok ) facts = ( await readJson( response ) ) as { name: string; size: number } | null;
    } catch {
      facts = null;
    }
    if ( facts === null || typeof facts.name !== "string" ) return;
    name  = facts.name;
    size  = facts.size;
    wire();
    state = "ready";
    el( IDS.toolbar ).hidden = false;
    el( IDS.button ).hidden  = false;
  }

  return { start, state: () => state };
}

/**
 * Attach the button to the page.
 *
 * Requires: win carries `__docViewerAuthedFetch` by the time a file is shown (the page sets it first).
 * Ensures: starts exactly once per file announcement, whether the page fired FILE_EVENT before or after this ran.
 */
/* c8 ignore next */ // tsx phantom branch: the CJS export annotation maps onto this last export's line.
export function bindDocPodcast( win: DocWindowLike, doc: Document ): void {
  const startFor = ( path: string ): void => {
    const authedFetch = ( url: string, init: RequestInit ): Promise<Response> => win.__docViewerAuthedFetch!( url, init );
    void createDocPodcast( { doc, authedFetch, path } ).start();
  };
  doc.addEventListener( FILE_EVENT, ( ev: Event ) => startFor( ( ev as CustomEvent<{ path: string }> ).detail.path ) );
  if ( typeof win.__docViewerFilePath === "string" ) startFor( win.__docViewerFilePath );
}
