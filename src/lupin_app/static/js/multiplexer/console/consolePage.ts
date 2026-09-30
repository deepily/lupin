/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Console tee — the standalone console page, `/app/console` (row 27760534, Rick's ruling
// 2026-09-28).
//
// One seat's live CC console, full-page, in its own tab. It stands alone: it does not need the
// multiplexer open, it survives a reload, and it can be bookmarked — the seat and the title
// come from the query string (consolePageUrl.ts), never from an opener.
//
// It REUSES the multiplexer's pieces rather than forking them — SessionTranscriptStore for the
// stream rules, SessionTranscriptRenderer for the render rules (plan §3–§4) — so the pane
// console and this page cannot drift into two behaviours. The renderer asks a reading-pane
// collaborator whether the console is showing; here it always is, so that collaborator is the
// one-line standalone pane below.
//
// 🔴 THIS TAB GETS ITS OWN QUEUE SOCKET ID, AND IT IS NEVER STORED. The server keeps one socket
// per session id, and the multiplexer keeps its id in localStorage — so a console tab that
// reused it would take the multiplexer's socket away from it (row d2b1b59a's defect, a tab
// over). A fresh id per page load also keeps two console tabs, or a duplicated one, apart.
//
// Split from ./boot.ts so the wiring is unit-tested with injected seams; boot.ts only binds
// the real browser globals.

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type { PaneContent } from "../shared/types";
import type { RedirectTarget } from "../auth/authGuard";
import { redirectToLoginIfUnauthenticated, bounceToLoginOnDeadSession } from "../auth/authGuard";
import { createSessionTranscriptStore } from "../stores/SessionTranscriptStore";
import type { SessionTranscriptApiClient, SessionTranscriptStore } from "../stores/SessionTranscriptStore";
import { createSessionTranscriptRenderer } from "../render/SessionTranscriptRenderer";
import type { ReadingPaneConsoleLike, SessionTranscriptRenderer } from "../render/SessionTranscriptRenderer";
import { parseConsolePageQuery } from "./consolePageUrl";

/** The queue transport surface this page drives. */
export interface ConsoleQueueTransport {
  start( sessionId: string ): void;
  send( envelope: unknown ): void;
}

/** What the page connects with, built only once the login guard has passed. */
export interface ConsoleConnection {
  api   : SessionTranscriptApiClient;
  queue : ConsoleQueueTransport;
}

/** The `window.location` surface the page reads and redirects through. */
export interface ConsoleLocation {
  readonly pathname : string;
  readonly search   : string;
  href              : string;
}

/** The window surface for the socket's lifecycle events. */
export interface ConsoleWindowEvents {
  addEventListener( type: "online" | "offline", listener: () => void ): void;
}

export interface ConsolePageDeps {
  doc          : Document;
  win          : ConsoleWindowEvents;
  location     : ConsoleLocation;
  storage      : StorageService;
  bus          : EventBus;
  connect      : () => ConsoleConnection;
  newSessionId : () => string;
}

export type ConsolePageResult =
  | { status : "error";      error : string }
  | { status : "redirected" }
  | { status : "watching";   seat : string; sessionId : string; store : SessionTranscriptStore; renderer : SessionTranscriptRenderer };

export const CONSOLE_PAGE_MOUNT_ID = "session-transcript-mount";
export const CONSOLE_PAGE_TITLE_ID = "console-page-title";
export const CONSOLE_PAGE_ERROR_ID = "console-page-error";

/**
 * The reading-pane collaborator for a page that IS the console.
 *
 * Ensures:
 *   - the pane content is always "console" — there is no reading stack to return to
 *   - showConsole always accepts (nothing outranks it here: no action-required card)
 *   - showReading always refuses, since there is nothing to show instead
 */
export function createStandaloneConsolePane(): ReadingPaneConsoleLike {
  return {
    getPaneContent : (): PaneContent => "console",
    showConsole    : (): boolean => true,
    showReading    : (): boolean => false,
  };
}

/**
 * A redirect target whose "where I was" keeps the query string.
 *
 * 🔴 THE LOGIN GUARD SENDS BACK TO `pathname`, AND FOR THIS PAGE THE PATH IS NOT THE PLACE.
 * `/app/console` without `?seat=` is the error page, so a bookmarked console that bounced
 * through login would come back to nothing. This adapter makes the guard's pathname carry the
 * query, and writes `href` straight through.
 *
 * Ensures:
 *   - pathname reads as location.pathname + location.search
 *   - assigning href assigns location.href
 */
export function redirectTargetKeepingQuery( location: ConsoleLocation ): RedirectTarget {
  return {
    get pathname(): string { return `${ location.pathname }${ location.search }`; },
    get href(): string     { return location.href; },
    set href( value: string ) { location.href = value; },
  };
}

/**
 * A server-valid, per-load queue session id.
 *
 * Requires:
 *   - random returns a float in [0, 1)
 *
 * Ensures:
 *   - matches the server's programmatic form `^[a-z][a-z0-9]*-[a-z0-9-]{1,47}$`
 *     ("console-" then 12 base-36 characters)
 */
export function generateConsoleSessionId( random: () => number ): string {
  let tail = "";
  while ( tail.length < 12 ) tail += Math.floor( random() * 36 ).toString( 36 );
  return `console-${ tail }`;
}

/**
 * Boot the console page.
 *
 * Requires:
 *   - doc carries #session-transcript-mount, #console-page-title and #console-page-error
 *
 * Ensures:
 *   - document.title is the query's title in every outcome, so even an error tab is named
 *   - a missing or malformed seat shows its error visibly and connects nothing
 *   - no access token: redirects to login with a redirect-back that keeps the query
 *   - otherwise mounts the renderer, watches the seat, and starts ONLY the queue socket on a
 *     fresh session id; the transcript store exists before the socket starts, so the first
 *     `auth_success` is heard
 *
 * Raises:
 *   - Error if the page's mount, title or error element is missing
 */
export function bootConsolePage( deps: ConsolePageDeps ): ConsolePageResult {
  const mountEl = requireElement( deps.doc, CONSOLE_PAGE_MOUNT_ID );
  const titleEl = requireElement( deps.doc, CONSOLE_PAGE_TITLE_ID );
  const errorEl = requireElement( deps.doc, CONSOLE_PAGE_ERROR_ID );

  const query = parseConsolePageQuery( deps.location.search );
  deps.doc.title      = query.title;
  titleEl.textContent = query.title;

  // Checked before the login guard: a malformed link needs no server to be told so.
  if ( query.seat === null ) {
    const error = query.error as string;
    errorEl.textContent = error;
    errorEl.hidden      = false;
    mountEl.hidden      = true;
    return { status : "error", error };
  }

  const target = redirectTargetKeepingQuery( deps.location );
  if ( redirectToLoginIfUnauthenticated( deps.storage, target ) ) return { status : "redirected" };
  bounceToLoginOnDeadSession( deps.bus, deps.storage, target );

  const { api, queue } = deps.connect();
  const store = createSessionTranscriptStore( {
    bus  : deps.bus,
    api,
    send : ( envelope ) => queue.send( envelope ),
  } );
  const renderer = createSessionTranscriptRenderer( {
    eventBus : deps.bus,
    stores   : { transcript : store, readingPane : createStandaloneConsolePane() },
  } );
  errorEl.hidden = true;
  mountEl.hidden = false;
  renderer.mount( mountEl );
  renderer.openSeat( query.seat, query.title );

  attachLifecycle( deps );
  const sessionId = deps.newSessionId();
  queue.start( sessionId );
  return { status : "watching", seat : query.seat, sessionId, store, renderer };
}

// The queue transport's reconnect machine listens for these, as it does in the multiplexer:
// a tab coming back into view or a network coming back reconnects now rather than on backoff.
function attachLifecycle( deps: ConsolePageDeps ): void {
  const emit = ( type: "page_hidden" | "page_visible" | "network_online" | "network_offline" ): void => {
    const ts = Date.now();
    deps.bus.emit( { type, payload : { ts }, source : "consolePage", ts } );
  };
  deps.doc.addEventListener( "visibilitychange", () => {
    emit( deps.doc.visibilityState === "hidden" ? "page_hidden" : "page_visible" );
  } );
  deps.win.addEventListener( "online",  () => emit( "network_online" ) );
  deps.win.addEventListener( "offline", () => emit( "network_offline" ) );
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
function requireElement( doc: Document, id: string ): HTMLElement {
  const el = doc.getElementById( id );
  if ( el === null ) throw new Error( `console page: #${ id } not found` );
  return el;
}
