// Row 4bf48f78, step 2 — PLAY HERE AND DOWNLOAD ON THE MULTIPLEXER'S FINISHED PODCAST CARD.
//
// Measured 2026-10-08 on the real ReadingPaneRenderer, before this module existed: a click on an
// `/app/audio?path=…&embed=1` anchor was not claimed (no overlay, no fetch, no pane), and a click on
// `/api/io/file?path=…` was not claimed either, so the browser navigated without an Authorization header and
// the server answered 401. Cases 1 and 2 re-run that measurement against the wired renderer in both layouts;
// the rest pin the module itself.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/podcast_links.test.ts

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type { WindowLike, WindowDocLike } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";

let activeRenderer: any = null;
afterEach( () => { if ( activeRenderer ) { activeRenderer.unmount(); activeRenderer = null; } document.body.replaceChildren(); } );
function makeWindowStub(): { win: WindowLike; opens: Array<unknown> } {
  const opens: Array<unknown> = [];
  const win: WindowLike = { open( url?: string ): WindowDocLike | null { opens.push( url ); return { document: { open() {}, write() {}, close() {} } }; } };
  return { win, opens };
}
before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const w = globalThis as any; w.marked = { parse: ( s: string ) => s }; w.DOMPurify = { sanitize: ( s: string ) => s }; w.scrollBy = () => {};
} );
// The master-detail shell, matching multiplexer.html. `#action-required-section`
// and `#action-required-content` are both here because both are pane-resident
// surfaces, and the tooltip is planted on <body> per case.
function buildShell(): HTMLElement {
  const shell = document.createElement( "div" );
  shell.className = "content-shell";
  shell.innerHTML = `
    <div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <button id="doc-roots-toggle" type="button">📂</button>
      <main class="container">
        <section id="notifications-pane">
          <div id="action-required-section">
            <div id="action-required-content"><button class="ar-respond">Respond</button></div>
          </div>
          <div id="sender-cards-container">
            <div class="sender-card" data-sender-id="alice">
              <span class="message-text">A history entry that carries a doc link</span>
            </div>
          </div>
        </section>
      </main>
    </div>
    <div id="content-pane-splitter" role="separator"></div>
    <aside class="content-pane" id="content-pane" hidden>
      <div class="content-pane-header">
        <button id="content-pane-back" type="button" disabled>←</button>
        <span id="content-pane-title"></span>
        <button id="content-pane-bustout" type="button">⤢</button>
        <button id="content-pane-close" type="button">×</button>
      </div>
      <div id="content-pane-body"></div>
    </aside>`;
  document.body.appendChild( shell );
  return shell;
}

type Mode = "vertical" | "horizontal";

function setup( mode: Mode ) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  // Seeded through the store's own persistence key, the way a returning user
  // arrives. "vertical" is the store's DEFAULT (ReadingPaneStore.ts:108) — the mode
  // the regression lived in, and the mode no pre-existing case covered.
  storage.setJSON( "reading_pane_layout_mode", { mode }, 1 );
  const store    = createReadingPaneStore( { bus, storage } );
  const win      = makeWindowStub();
  const shell    = buildShell();
  const renderer = createReadingPaneRenderer( {
    eventBus  : bus,
    stores    : { readingPane: store, actionRequired: { list: () => [] } },
    windowRef : win.win,
  } );
  renderer.mount( shell );
  activeRenderer = renderer;
  assert.equal( store.getLayoutMode(), mode, "the fixture must actually be in the mode it claims" );
  return { store, win, shell };
}


import {
  isEmbeddedAudioHref, isIoFileHref, filenameForIoDownload, showPodcastOverlay, dismissPodcastOverlay,
  downloadIoFileWithAuth, handlePodcastLinkClick, bindPodcastLinks, PODCAST_OVERLAY_ID,
} from "../../../../lupin_app/static/js/multiplexer/render/podcastLinks";
import type { DownloadDeps } from "../../../../lupin_app/static/js/multiplexer/render/podcastLinks";

const AUDIO = "podcast/x.mp3";
const ENC   = encodeURIComponent( AUDIO );
const PLAY  = `/app/audio?path=${ENC}&embed=1`;
const LISTEN = `/app/audio?path=${ENC}`;
const DOWNLOAD = `/api/io/file?path=${ENC}&download=true`;

function plant( host: Element, href: string, text: string ): HTMLAnchorElement {
  const a = document.createElement( "a" );
  a.setAttribute( "href", href ); a.setAttribute( "target", "_blank" ); a.textContent = text;
  host.appendChild( a );
  return a;
}
function click( el: Element ): MouseEvent {
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  el.dispatchEvent( ev );
  return ev;
}
/** A DownloadDeps that records everything and runs timers on demand. */
function makeDeps( over: Partial<DownloadDeps> = {} ) {
  const log = { fetches: [] as Array<{ url: string; headers: Record<string, string> }>, alerts: [] as string[], timers: [] as Array<{ fn: () => void; ms: number }> };
  const deps: DownloadDeps = {
    getToken : () => "tok123",
    fetchFn  : async ( url, init ) => { log.fetches.push( { url, headers: init.headers } ); return new Response( "audio-bytes", { status: 200, headers: { "Content-Disposition": 'attachment; filename="show.mp3"' } } ); },
    alertFn  : ( m ) => { log.alerts.push( m ); },
    setTimer : ( fn, ms ) => { log.timers.push( { fn, ms } ); },
    ...over,
  };
  return { deps, log };
}

// ===== 1/2: the measurement, re-run through the wired renderer in both layouts =====
for ( const mode of [ "vertical", "horizontal" ] as Mode[] ) {
  test( `${mode}: Play Here on a history card is claimed and opens the floating player, not a tab`, () => {
    const { win, shell } = setup( mode );
    const a  = plant( shell.querySelector( "#sender-cards-container" ) as Element, PLAY, "▶️ Play Here" );
    const ev = click( a );
    assert.equal( ev.defaultPrevented, true, "the click must be claimed; unclaimed is the measured defect" );
    assert.deepEqual( win.opens, [], "no tab" );
    const frame = document.querySelector( `#${PODCAST_OVERLAY_ID} iframe` ) as HTMLIFrameElement;
    assert.ok( frame, "the overlay iframe must exist" );
    assert.equal( frame.getAttribute( "src" ), PLAY + "&autoplay=1" );
    assert.equal( document.querySelector( ".podcast-overlay-title" )?.textContent, "▶️ Play Here" );
  } );

  test( `${mode}: Download on a history card is fetched with the Bearer token, not navigated`, async () => {
    const { shell } = setup( mode );
    const { log } = installGlobalFetch();
    const a  = plant( shell.querySelector( "#sender-cards-container" ) as Element, DOWNLOAD, "⬇️ Download" );
    const ev = click( a );
    assert.equal( ev.defaultPrevented, true );
    await settle();
    assert.equal( log.fetches.length, 1, "exactly one authenticated fetch" );
    assert.equal( log.fetches[ 0 ].url, DOWNLOAD );
    assert.equal( log.fetches[ 0 ].headers.Authorization, "Bearer tok-from-storage" );
  } );

  test( `${mode}: Listen (no embed flag) is left alone and still opens its tab`, () => {
    const { win, shell } = setup( mode );
    const { log } = installGlobalFetch();
    const ev = click( plant( shell.querySelector( "#sender-cards-container" ) as Element, LISTEN, "🎧 Listen" ) );
    assert.equal( ev.defaultPrevented, false );
    assert.deepEqual( win.opens, [] );
    assert.equal( document.getElementById( PODCAST_OVERLAY_ID ), null );
    assert.equal( log.fetches.length, 0 );
  } );
}

test( "unmounting the renderer stops it claiming podcast links", () => {
  const { shell } = setup( "vertical" );
  activeRenderer.unmount(); activeRenderer = null;
  const ev = click( plant( shell, PLAY, "Play" ) );
  assert.equal( ev.defaultPrevented, false );
  assert.equal( document.getElementById( PODCAST_OVERLAY_ID ), null );
} );

// ===== the predicates =====
test( "isEmbeddedAudioHref: only the embed form, relative or absolute loopback, any query order", () => {
  assert.equal( isEmbeddedAudioHref( PLAY ), true );
  assert.equal( isEmbeddedAudioHref( `http://localhost:7999${PLAY}` ), true );
  assert.equal( isEmbeddedAudioHref( `/app/audio?path=${ENC}&embed=1&x=2` ), true );
  assert.equal( isEmbeddedAudioHref( `/app/audio?path=${ENC}&embed=10` ), false );
  assert.equal( isEmbeddedAudioHref( LISTEN ), false );
  assert.equal( isEmbeddedAudioHref( "/app/audio?embed=1&path=a" ), false, "the prefix is the path form, not any audio query" );
  assert.equal( isEmbeddedAudioHref( "/app/docs?path=a&embed=1" ), false );
  assert.equal( isEmbeddedAudioHref( null ), false );
} );

test( "isIoFileHref: the file endpoint with or without download=true, nothing else", () => {
  assert.equal( isIoFileHref( DOWNLOAD ), true );
  assert.equal( isIoFileHref( `/api/io/file?path=${ENC}` ), true );
  assert.equal( isIoFileHref( `http://127.0.0.1:7999${DOWNLOAD}` ), true );
  assert.equal( isIoFileHref( "/api/io/other?path=a" ), false );
  assert.equal( isIoFileHref( null ), false );
} );

test( "filenameForIoDownload: header first, then the path basename, then a fallback", () => {
  assert.equal( filenameForIoDownload( DOWNLOAD, 'attachment; filename="show.mp3"' ), "show.mp3" );
  assert.equal( filenameForIoDownload( DOWNLOAD, "attachment; filename*=UTF-8''sh%C3%B3w.mp3" ), "shów.mp3" );
  assert.equal( filenameForIoDownload( DOWNLOAD, "attachment" ), "x.mp3" );
  assert.equal( filenameForIoDownload( "/api/io/file?path=a/b/c.mp3", null ), "c.mp3" );
  assert.equal( filenameForIoDownload( "/api/io/file", null ), "download" );
  assert.equal( filenameForIoDownload( "/api/io/file?path=", null ), "download" );
} );

// ===== the overlay =====
test( "showPodcastOverlay: single instance, autoplay added once, only the X closes it", () => {
  showPodcastOverlay( PLAY, "First" );
  showPodcastOverlay( PLAY + "&autoplay=1", "Second" );
  assert.equal( document.querySelectorAll( `#${PODCAST_OVERLAY_ID}` ).length, 1, "a second player replaces the first" );
  assert.equal( document.querySelector( ".podcast-overlay-title" )?.textContent, "Second" );
  const frame = document.querySelector( "iframe" ) as HTMLIFrameElement;
  assert.equal( frame.getAttribute( "src" ), PLAY + "&autoplay=1", "the flag is not doubled" );
  assert.equal( frame.getAttribute( "allow" ), "autoplay" );
  ( document.querySelector( "[data-testid=podcast-overlay-dismiss]" ) as HTMLElement ).click();
  assert.equal( document.getElementById( PODCAST_OVERLAY_ID ), null );
  dismissPodcastOverlay();   // a second dismiss is a no-op
} );

// ===== the download =====
test( "downloadIoFileWithAuth: success saves the blob under the server's filename and defers cleanup", async () => {
  const created: Blob[] = [];
  const revoked: string[] = [];
  const realCreate = URL.createObjectURL, realRevoke = URL.revokeObjectURL;
  URL.createObjectURL = ( b: Blob ) => { created.push( b ); return "blob:fake"; };
  URL.revokeObjectURL = ( u: string ) => { revoked.push( u ); };
  let saved: { download: string; href: string } | null = null;
  const realClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () { saved = { download: this.download, href: this.href }; };
  try {
    const { deps, log } = makeDeps();
    await downloadIoFileWithAuth( DOWNLOAD, deps );
    assert.equal( log.fetches[ 0 ].headers.Authorization, "Bearer tok123" );
    assert.equal( created.length, 1 );
    assert.deepEqual( saved, { download: "show.mp3", href: "blob:fake" } );
    assert.equal( document.querySelectorAll( "a[download]" ).length, 1, "anchor stays until the timer fires" );
    assert.deepEqual( log.timers.map( t => t.ms ), [ 5000, 60000 ] );
    log.timers.forEach( t => t.fn() );
    assert.equal( document.querySelectorAll( "a[download]" ).length, 0 );
    assert.deepEqual( revoked, [ "blob:fake" ] );
    assert.deepEqual( log.alerts, [] );
  } finally {
    URL.createObjectURL = realCreate; URL.revokeObjectURL = realRevoke; HTMLAnchorElement.prototype.click = realClick;
  }
} );

test( "downloadIoFileWithAuth: no token means a login prompt and no fetch (null and empty)", async () => {
  for ( const token of [ null, "" ] ) {
    const { deps, log } = makeDeps( { getToken: () => token } );
    await downloadIoFileWithAuth( DOWNLOAD, deps );
    assert.deepEqual( log.alerts, [ "Please log in to download files" ] );
    assert.equal( log.fetches.length, 0 );
  }
} );

test( "downloadIoFileWithAuth: a refusal is reported with the server's status and saves nothing", async () => {
  const { deps, log } = makeDeps( { fetchFn: async () => new Response( "no", { status: 401, statusText: "Unauthorized" } ) } );
  await downloadIoFileWithAuth( DOWNLOAD, deps );
  assert.deepEqual( log.alerts, [ "Download failed: 401 Unauthorized" ] );
  assert.deepEqual( log.timers, [] );
} );

test( "downloadIoFileWithAuth: a thrown fetch is reported and nothing is revoked", async () => {
  const { deps, log } = makeDeps( { fetchFn: async () => { throw new Error( "offline" ); } } );
  await downloadIoFileWithAuth( DOWNLOAD, deps );
  assert.deepEqual( log.alerts, [ "Download failed: offline" ] );
  assert.deepEqual( log.timers, [] );
} );

// ===== the click decision =====
test( "handlePodcastLinkClick: unrelated clicks are not claimed", () => {
  const host = document.createElement( "div" ); document.body.appendChild( host );
  const { deps } = makeDeps();
  const nonAnchor = document.createElement( "span" ); host.appendChild( nonAnchor );
  assert.equal( handlePodcastLinkClick( click( nonAnchor ), deps ), false );
  assert.equal( handlePodcastLinkClick( click( plant( host, "/app/docs?path=a", "doc" ) ), deps ), false );
  assert.equal( handlePodcastLinkClick( { target: null, preventDefault() {} } as unknown as Event, deps ), false );
  assert.equal( handlePodcastLinkClick( { target: {}, preventDefault() {} } as unknown as Event, deps ), false );
  const pane = document.createElement( "div" ); pane.id = "content-pane-body"; host.appendChild( pane );
  const frameHost = document.createElement( "iframe" ); pane.appendChild( frameHost );
  const inner = { closest: ( sel: string ) => sel === "a[href]" ? plant( host, PLAY, "p" ) : frameHost, preventDefault() {} };
  assert.equal( handlePodcastLinkClick( { target: inner, preventDefault() { throw new Error( "must not claim" ); } } as unknown as Event, deps ), false );
  assert.equal( document.getElementById( PODCAST_OVERLAY_ID ), null );
} );

test( "a Play Here link with no text still opens the player, titled Podcast", () => {
  const host = document.createElement( "div" ); document.body.appendChild( host );
  const { deps } = makeDeps();
  assert.equal( handlePodcastLinkClick( click( plant( host, PLAY, "" ) ), deps ), true );
  assert.equal( document.querySelector( ".podcast-overlay-title" )?.textContent, "Podcast" );
  dismissPodcastOverlay();
} );

test( "bindPodcastLinks: claims while bound, stops after the returned unbinder runs", () => {
  const host = document.createElement( "div" ); document.body.appendChild( host );
  const { deps } = makeDeps();
  const unbind = bindPodcastLinks( deps );
  assert.equal( click( plant( host, PLAY, "p" ) ).defaultPrevented, true );
  dismissPodcastOverlay();
  unbind();
  assert.equal( click( plant( host, PLAY, "p" ) ).defaultPrevented, false );
} );

test( "the default deps read the stored token and answer without a real network", async () => {
  const realFetch = globalThis.fetch;
  const seen: Array<{ url: string; auth: string }> = [];
  globalThis.fetch = ( async ( url: string, init: { headers: Record<string, string> } ) => { seen.push( { url, auth: init.headers.Authorization } ); return new Response( "no", { status: 500, statusText: "Boom" } ); } ) as unknown as typeof fetch;
  const realAlert = globalThis.alert; const alerts: string[] = [];
  globalThis.alert = ( m: string ) => { alerts.push( m ); };
  try {
    localStorage.setItem( "lupin_access_token", "stored" );
    await downloadIoFileWithAuth( DOWNLOAD );
    assert.deepEqual( seen, [ { url: DOWNLOAD, auth: "Bearer stored" } ] );
    assert.deepEqual( alerts, [ "Download failed: 500 Boom" ] );
    localStorage.removeItem( "lupin_access_token" );
    await downloadIoFileWithAuth( DOWNLOAD );
    assert.deepEqual( alerts[ 1 ], "Please log in to download files" );
    const realStorage = Object.getOwnPropertyDescriptor( globalThis, "localStorage" ) as PropertyDescriptor;
    Object.defineProperty( globalThis, "localStorage", { configurable: true, get() { throw new Error( "blocked" ); } } );
    try { await downloadIoFileWithAuth( DOWNLOAD ); } finally { Object.defineProperty( globalThis, "localStorage", realStorage ); }
    assert.deepEqual( alerts[ 2 ], "Please log in to download files", "unreadable storage reads as no token" );
    const t = setTimeout; let ran = 0;
    // the default timer wrapper is exercised by the success path below
    const realCreate = URL.createObjectURL; URL.createObjectURL = () => "blob:d";
    const realRevoke = URL.revokeObjectURL; URL.revokeObjectURL = () => { ran++; };
    const realClick = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = () => {};
    const realSet = globalThis.setTimeout; ( globalThis as any ).setTimeout = ( fn: () => void ) => { fn(); return 0; };
    localStorage.setItem( "lupin_access_token", "stored" );
    globalThis.fetch = ( async () => new Response( "ok", { status: 200 } ) ) as unknown as typeof fetch;
    try { await downloadIoFileWithAuth( DOWNLOAD ); } finally { ( globalThis as any ).setTimeout = realSet; URL.createObjectURL = realCreate; URL.revokeObjectURL = realRevoke; HTMLAnchorElement.prototype.click = realClick; }
    assert.equal( ran, 1, "the default timer ran the revoke" );
    void t;
  } finally {
    globalThis.fetch = realFetch; globalThis.alert = realAlert; localStorage.removeItem( "lupin_access_token" );
  }
} );

/** Replace global fetch for the renderer-wired cases; the default deps read this and the stored token. */
function installGlobalFetch() {
  const log = { fetches: [] as Array<{ url: string; headers: Record<string, string> }> };
  localStorage.setItem( "lupin_access_token", "tok-from-storage" );
  const realCreate = URL.createObjectURL; URL.createObjectURL = () => "blob:t";
  const realClick  = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = () => {};
  ( globalThis as any ).fetch = async ( url: string, init: { headers: Record<string, string> } ) => { log.fetches.push( { url, headers: init.headers } ); return new Response( "x", { status: 200 } ); };
  restorers.push( () => { URL.createObjectURL = realCreate; HTMLAnchorElement.prototype.click = realClick; localStorage.removeItem( "lupin_access_token" ); } );
  return { log };
}
const restorers: Array<() => void> = [];
afterEach( () => { while ( restorers.length ) ( restorers.pop() as () => void )(); } );
const settle = () => new Promise<void>( r => setImmediate( r ) );
