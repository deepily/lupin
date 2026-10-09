/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line (same as docLink.ts:1).
// Multiplexer — the two podcast links a finished podcast card carries: Play Here and Download.
//
// Row 4bf48f78, step 2. Measured 2026-10-08 on the multiplexer's real ReadingPaneRenderer: a click on
// `/app/audio?path=…&embed=1` was not claimed (no overlay, no fetch; the anchor's `target="_blank"` opened a plain
// tab), and a click on `/api/io/file?path=…` was not claimed either, so the browser navigated without an
// Authorization header and the server answered 401. This module ports the legacy page's two interceptions
// (`notifications.js`: `_handleEmbeddedAudioClick`, `_handleIoFileDownloadClick`) so both clients behave the same.
//
// A plain `/app/audio?path=` link (Listen) is deliberately left alone: it still opens a tab.

import { normalizeDocLinkHref } from "./docLink";

/** The floating player's element id: single instance, replaced by a second Play Here. */
export const PODCAST_OVERLAY_ID = "podcast-overlay";

const AUDIO_PREFIX    = "/app/audio?path=";
const IO_FILE_PREFIX  = "/api/io/file?";
const EMBED_FLAG_RE   = /[?&]embed=1(?:&|$)/;
const AUTOPLAY_FLAG_RE = /[?&]autoplay=1(?:&|$)/;
const TOKEN_KEY       = "lupin_access_token";

/** The browser pieces the download needs, injectable so a test can watch every one of them. */
export interface DownloadDeps {
  getToken  : () => string | null;
  fetchFn   : ( url: string, init: { headers: Record<string, string> } ) => Promise<Response>;
  alertFn   : ( message: string ) => void;
  setTimer  : ( fn: () => void, ms: number ) => void;
}

/**
 * True only for an audio link that carries the embed flag, in either the relative or the absolute-loopback form.
 *
 * Requires: href is the anchor's raw href or null.
 * Ensures: false for null, for any non-audio href, and for `/app/audio?path=` without `embed=1`.
 */
export function isEmbeddedAudioHref( href: string | null ): boolean {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null || !normalized.startsWith( AUDIO_PREFIX ) ) return false;
  return EMBED_FLAG_RE.test( normalized );
}

/** True for a same-origin `/api/io/file?` request, with or without `download=true`. */
export function isIoFileHref( href: string | null ): boolean {
  const normalized = normalizeDocLinkHref( href );
  return normalized !== null && normalized.startsWith( IO_FILE_PREFIX );
}

/**
 * The name to save a download under.
 *
 * Ensures: the server's Content-Disposition filename when it supplies one; else the basename of the `path`
 * query parameter; else "download".
 */
export function filenameForIoDownload( url: string, contentDisposition: string | null ): string {
  if ( contentDisposition !== null ) {
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec( contentDisposition );
    if ( match !== null ) return decodeURIComponent( match[ 1 ] as string );
  }
  const path = new URLSearchParams( url.split( "?" )[ 1 ] ?? "" ).get( "path" );
  if ( path !== null && path !== "" ) return path.split( "/" ).pop() as string;
  return "download";
}

/** Remove the floating player if it is open. Removing the iframe stops the audio. */
export function dismissPodcastOverlay(): void {
  document.getElementById( PODCAST_OVERLAY_ID )?.remove();
}

/**
 * Show the floating in-tab player for an embed URL, replacing any player already open.
 *
 * Requires: embedUrl is an `/app/audio?path=…&embed=1` href; title is the link text.
 * Ensures: returns the overlay; the iframe starts playing (`autoplay=1`, added once); only the user closes it.
 */
export function showPodcastOverlay( embedUrl: string, title: string ): HTMLElement {
  dismissPodcastOverlay();

  const overlay = document.createElement( "div" );
  overlay.id        = PODCAST_OVERLAY_ID;
  overlay.className = "podcast-overlay";
  overlay.setAttribute( "data-testid", "podcast-overlay" );

  const header  = document.createElement( "div" );
  header.className = "podcast-overlay-header";
  const titleEl = document.createElement( "div" );
  titleEl.className   = "podcast-overlay-title";
  titleEl.textContent = title;
  const dismiss = document.createElement( "button" );
  dismiss.type      = "button";
  dismiss.className = "podcast-overlay-dismiss";
  dismiss.setAttribute( "data-testid", "podcast-overlay-dismiss" );
  dismiss.setAttribute( "aria-label", "Dismiss podcast player" );
  dismiss.textContent = "✕";
  dismiss.addEventListener( "click", dismissPodcastOverlay );
  header.appendChild( titleEl );
  header.appendChild( dismiss );

  const frame = document.createElement( "iframe" );
  frame.className = "podcast-overlay-frame";
  frame.setAttribute( "data-testid", "podcast-overlay-frame" );
  frame.src = AUTOPLAY_FLAG_RE.test( embedUrl ) ? embedUrl : embedUrl + "&autoplay=1";
  frame.setAttribute( "title", title );
  frame.setAttribute( "allow", "autoplay" );

  overlay.appendChild( header );
  overlay.appendChild( frame );
  document.body.appendChild( overlay );
  return overlay;
}

function defaultDeps(): DownloadDeps {
  return {
    getToken : () => { try { return localStorage.getItem( TOKEN_KEY ); } catch { return null; } },
    fetchFn  : ( url, init ) => fetch( url, init ),
    alertFn  : ( message ) => { globalThis.alert( message ); },
    setTimer : ( fn, ms ) => { setTimeout( fn, ms ); },
  };
}

/**
 * Fetch a token-guarded `/api/io/file` URL and hand the bytes to the browser as a download.
 *
 * Requires: url is a same-origin `/api/io/file?` path.
 * Ensures: with no token, asks the user to log in and fetches nothing; on a non-OK answer or a thrown error,
 * reports the server's status or the error and saves nothing; on success saves the blob under
 * `filenameForIoDownload` and revokes the object URL after a delay.
 */
export async function downloadIoFileWithAuth( url: string, deps: DownloadDeps = defaultDeps() ): Promise<void> {
  const token = deps.getToken();
  if ( token === null || token === "" ) { deps.alertFn( "Please log in to download files" ); return; }

  let blobUrl: string | null = null;
  try {
    const response = await deps.fetchFn( url, { headers: { Authorization: `Bearer ${token}` } } );
    if ( !response.ok ) { deps.alertFn( `Download failed: ${response.status} ${response.statusText}` ); return; }

    const blob   = await response.blob();
    blobUrl      = URL.createObjectURL( blob );
    const anchor = document.createElement( "a" );
    anchor.href          = blobUrl;
    anchor.download      = filenameForIoDownload( url, response.headers.get( "Content-Disposition" ) );
    anchor.rel           = "noopener";
    anchor.style.display = "none";
    document.body.appendChild( anchor );
    anchor.click();
    // Removing the anchor in the same tick as the click can cancel the save before the browser services it.
    deps.setTimer( () => anchor.remove(), 5000 );
  } catch ( error ) {
    deps.alertFn( `Download failed: ${( error as Error ).message}` );
  } finally {
    const revoke = blobUrl;
    if ( revoke !== null ) deps.setTimer( () => URL.revokeObjectURL( revoke ), 60000 );
  }
}

/**
 * Decide one click. Claims a Play Here or a Download link and leaves every other click untouched.
 *
 * Requires: ev is a click event.
 * Ensures: returns true when the click was claimed (and `preventDefault` was called); a click inside the
 * reading pane's own iframe, on a non-anchor, on Listen, or on any other link returns false.
 */
export function handlePodcastLinkClick( ev: Event, deps?: DownloadDeps ): boolean {
  const target = ev.target as Element | null;
  if ( target === null || typeof target.closest !== "function" ) return false;
  const anchor = target.closest( "a[href]" );
  if ( anchor === null || target.closest( "#content-pane-body iframe" ) !== null ) return false;

  const href = anchor.getAttribute( "href" );
  if ( isEmbeddedAudioHref( href ) ) {
    ev.preventDefault();
    showPodcastOverlay( normalizeDocLinkHref( href ) as string, anchor.textContent || "Podcast" );
    return true;
  }
  if ( isIoFileHref( href ) ) {
    ev.preventDefault();
    void downloadIoFileWithAuth( normalizeDocLinkHref( href ) as string, deps );
    return true;
  }
  return false;
}

/**
 * Listen for clicks on the whole document.
 *
 * Ensures: returns a function that removes the listener, for the owner's `unmount`.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as docLink.ts isPaneResidentAnchor); the body below is fully covered.
export function bindPodcastLinks( deps?: DownloadDeps ): () => void {
  const onClick = ( ev: Event ): void => { handlePodcastLinkClick( ev, deps ); };
  document.addEventListener( "click", onClick );
  return (): void => { document.removeEventListener( "click", onClick ); };
}
