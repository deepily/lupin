// Row 27760534 — the standalone console page, /app/console (Rick's ruling 2026-09-28).
// 100% lines/branches/functions for console/consolePage.ts and console/consolePageUrl.ts.
//
// 🔴 THE PAGE IS DRIVEN THROUGH ITS REAL PAGE MARKUP AND ITS REAL PIECES. The DOM is parsed out
// of html/console.html itself, and the store and renderer are the production ones — only the
// HTTP client and the socket are faked. A page that boots fine into a hand-built <div> and not
// into its own markup would pass every other test here.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { EventBus } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { LupinEventType } from "../../../lupin_app/static/js/multiplexer/shared/types";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { REFRESH_REJECTED_ERROR } from "../../../lupin_app/static/js/multiplexer/auth/AuthManager";
import {
  bootConsolePage,
  createStandaloneConsolePane,
  generateConsoleSessionId,
  redirectTargetKeepingQuery,
  CONSOLE_PAGE_ERROR_ID,
  CONSOLE_PAGE_MOUNT_ID,
  CONSOLE_PAGE_TITLE_ID,
} from "../../../lupin_app/static/js/multiplexer/console/consolePage";
import type { ConsoleLocation, ConsolePageDeps } from "../../../lupin_app/static/js/multiplexer/console/consolePage";
import {
  buildConsolePageHref,
  parseConsolePageQuery,
  CONSOLE_DEFAULT_TITLE,
  CONSOLE_PAGE_PATH,
} from "../../../lupin_app/static/js/multiplexer/console/consolePageUrl";

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const HTML_PATH = resolve( HERE, "../../../lupin_app/static/html/console.html" );

const SEAT  = "e14bd712-700e-46ce-88ea-8db62604ceb4";
const EPOCH = "57238c9d-c227-469e-b707-13b7752a7399";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const w = globalThis as unknown as { marked: { parse( s: string ): string }; DOMPurify: { sanitize( s: string ): string } };
  w.marked    = { parse : ( s: string ): string => `<p>${ s }</p>` };
  w.DOMPurify = { sanitize : ( s: string ): string => s };
} );

// The page's own <body>, parsed out of console.html — scripts dropped, markup kept.
beforeEach( () => {
  const html = readFileSync( HTML_PATH, "utf8" );
  const body = ( html.match( /<body[^>]*>([\s\S]*)<\/body>/ ) as RegExpMatchArray )[ 1 ] as string;
  document.body.innerHTML = body.replace( /<script[\s\S]*?<\/script>/g, "" );
  document.title = "";
} );

const flush = () => new Promise( ( r ) => setImmediate( r ) );
const byId  = ( id: string ) => document.getElementById( id ) as HTMLElement;
const emit  = ( bus: EventBus, type: string, payload: unknown ) =>
  bus.emit( { type : type as LupinEventType, payload, source : "test", ts : 0 } );

interface Harness {
  deps      : ConsolePageDeps;
  bus       : EventBus;
  location  : ConsoleLocation;
  sent      : Array<Record<string, unknown>>;
  gets      : string[];
  starts    : string[];
  connects  : number;
  winEvents : Map<string, () => void>;
  events    : string[];
}

function harness( search: string, opts: { token?: boolean } = {} ): Harness {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  if ( opts.token ?? true ) storage.setTokens( "access", "refresh" );
  const h: Harness = {
    deps : undefined as unknown as ConsolePageDeps,
    bus,
    location  : { pathname : CONSOLE_PAGE_PATH, search, href : `${ CONSOLE_PAGE_PATH }${ search }` },
    sent      : [],
    gets      : [],
    starts    : [],
    connects  : 0,
    winEvents : new Map(),
    events    : [],
  };
  for ( const type of [ "page_hidden", "page_visible", "network_online", "network_offline" ] as const ) {
    bus.on( type, () => { h.events.push( type ); } );
  }
  h.deps = {
    doc          : document,
    win          : { addEventListener : ( type, listener ) => { h.winEvents.set( type, listener ); } },
    location     : h.location,
    storage,
    bus,
    newSessionId : () => "console-abc123def456",
    connect      : () => {
      h.connects += 1;
      return {
        api   : { get : async <T>( p: string ): Promise<T> => {
          h.gets.push( p );
          return { file_epoch : EPOCH, offset : 0, next_offset : 40, blocks : [ { kind : "text", text : "hello from the seat" } ] } as unknown as T;
        } },
        queue : {
          start : ( id: string ) => { h.starts.push( id ); },
          send  : ( env: unknown ) => { h.sent.push( env as Record<string, unknown> ); },
        },
      };
    },
  };
  return h;
}

// ── the URL contract ───────────────────────────────────────────────────────

test( "buildConsolePageHref and parseConsolePageQuery round-trip a title carrying &, # and an emoji", () => {
  const title = "🦉 a & b #1";
  const href  = buildConsolePageHref( SEAT, title );
  assert.equal( href, `/app/console?seat=${ SEAT }&title=%F0%9F%A6%89%20a%20%26%20b%20%231` );
  assert.deepEqual( parseConsolePageQuery( href.slice( href.indexOf( "?" ) ) ), { seat : SEAT, title, error : null } );
} );

test( "parseConsolePageQuery: a missing or blank seat is an error; a missing or blank title is the default", () => {
  for ( const search of [ "", "?title=x", "?seat=%20%20" ] ) {
    const q = parseConsolePageQuery( search );
    assert.equal( q.seat, null, search );
    assert.match( q.error as string, /No seat was named/ );
  }
  assert.equal( parseConsolePageQuery( "" ).title, CONSOLE_DEFAULT_TITLE );
  assert.equal( parseConsolePageQuery( `?seat=${ SEAT }&title=%20` ).title, CONSOLE_DEFAULT_TITLE );
  assert.equal( parseConsolePageQuery( `seat=${ SEAT }&title=T` ).title, "T", "a leading ? is optional" );
} );

test( "parseConsolePageQuery refuses the 8-hex chip prefix, and any other malformed id, by name", () => {
  for ( const bad of [ "e14bd712", "not-a-uuid", `${ SEAT }x`, "e14bd712-700e-46ce-88ea-8db62604ceb" ] ) {
    const q = parseConsolePageQuery( `?seat=${ encodeURIComponent( bad ) }` );
    assert.equal( q.seat, null, bad );
    assert.ok( ( q.error as string ).includes( bad ) && /not a full seat id/.test( q.error as string ), q.error as string );
  }
  assert.equal( parseConsolePageQuery( `?seat=${ SEAT.toUpperCase() }` ).seat, SEAT.toUpperCase(), "hex case is not a defect" );
  assert.equal( parseConsolePageQuery( `?seat=%20${ SEAT }%20` ).seat, SEAT, "trimmed" );
} );

// ── the small pieces ───────────────────────────────────────────────────────

test( "the standalone pane always shows the console and has no reading stack to return to", () => {
  const pane = createStandaloneConsolePane();
  assert.equal( pane.getPaneContent(), "console" );
  assert.equal( pane.showConsole( "anything" ), true );
  assert.equal( pane.showReading(), false );
} );

test( "redirectTargetKeepingQuery: the guard's pathname carries the query; href writes through", () => {
  const loc    = { pathname : "/app/console", search : `?seat=${ SEAT }`, href : "/start" };
  const target = redirectTargetKeepingQuery( loc );
  assert.equal( target.pathname, `/app/console?seat=${ SEAT }` );
  assert.equal( target.href, "/start" );
  target.href = "/elsewhere";
  assert.equal( loc.href, "/elsewhere" );
} );

test( "generateConsoleSessionId is server-valid (programmatic form) and differs per draw", () => {
  const SERVER_PROGRAMMATIC = /^[a-z][a-z0-9]*-[a-z0-9-]{1,47}$/;
  const a = generateConsoleSessionId( Math.random );
  const b = generateConsoleSessionId( Math.random );
  assert.match( a, SERVER_PROGRAMMATIC );
  assert.match( a, /^console-[0-9a-z]{12}$/ );
  assert.notEqual( a, b );
  assert.equal( generateConsoleSessionId( () => 0 ), "console-000000000000" );
  assert.equal( generateConsoleSessionId( () => 0.999 ), "console-zzzzzzzzzzzz" );
} );

// ── boot ───────────────────────────────────────────────────────────────────

test( "a valid seat: renders, watches THAT seat after auth, starts only the queue socket, and titles the tab", async () => {
  const h = harness( `?seat=${ SEAT }&title=${ encodeURIComponent( "🦉 mr radio — console" ) }` );
  const result = bootConsolePage( h.deps );

  assert.equal( result.status, "watching" );
  assert.equal( document.title, "🦉 mr radio — console" );
  assert.equal( byId( CONSOLE_PAGE_TITLE_ID ).textContent, "🦉 mr radio — console" );
  assert.equal( byId( CONSOLE_PAGE_ERROR_ID ).hidden, true );
  assert.equal( byId( CONSOLE_PAGE_MOUNT_ID ).hidden, false );
  assert.deepEqual( h.starts, [ "console-abc123def456" ], "the queue transport, on the page's own fresh id" );
  assert.equal( h.connects, 1 );

  await flush();
  assert.deepEqual( h.gets, [ `/api/cc-transcript/${ SEAT }` ], "the backlog of the FULL seat id" );
  assert.equal( byId( CONSOLE_PAGE_MOUNT_ID ).querySelector( ".session-transcript-list" )!.textContent, "hello from the seat" );
  assert.deepEqual( h.sent, [], "nothing is sent before auth_success" );

  emit( h.bus, "auth_success", {} );
  assert.deepEqual( h.sent, [ { type : "cc_transcript_watch", cc_session_id : SEAT, from_offset : 40, file_epoch : EPOCH } ] );

  const watching = result as Extract<typeof result, { status: "watching" }>;
  assert.equal( watching.seat, SEAT );
  assert.equal( watching.sessionId, "console-abc123def456" );
  assert.equal( watching.store.snapshot().watchedCcSessionId, SEAT );
  assert.equal( watching.renderer.showingSeat(), SEAT, "the standalone pane always reports the console" );
} );

test( "a live chunk for the seat lands on the page", async () => {
  const h = harness( `?seat=${ SEAT }` );
  bootConsolePage( h.deps );
  await flush();
  emit( h.bus, "auth_success", {} );
  emit( h.bus, "cc_transcript_append", { cc_session_id : SEAT, file_epoch : EPOCH, offset : 40, next_offset : 80, blocks : [ { kind : "tool_call", text : "Read(x.py)" } ] } );
  const blocks = byId( CONSOLE_PAGE_MOUNT_ID ).querySelectorAll( ".session-transcript-block" );
  assert.equal( blocks.length, 2 );
  assert.equal( blocks[ 1 ]!.getAttribute( "data-kind" ), "tool_call" );
} );

test( "a missing seat shows a VISIBLE error, connects nothing, and still names the tab", () => {
  const h = harness( "?title=Orphan" );
  const result = bootConsolePage( h.deps );
  assert.equal( result.status, "error" );
  const err = byId( CONSOLE_PAGE_ERROR_ID );
  assert.equal( err.hidden, false );
  assert.match( err.textContent as string, /No seat was named/ );
  assert.equal( ( result as { error: string } ).error, err.textContent );
  assert.equal( byId( CONSOLE_PAGE_MOUNT_ID ).hidden, true );
  assert.equal( document.title, "Orphan" );
  assert.equal( h.connects, 0 );
  assert.deepEqual( h.starts, [] );
} );

test( "a chip prefix for a seat is refused on the page, before any login bounce", () => {
  const h = harness( "?seat=e14bd712", { token : false } );
  const result = bootConsolePage( h.deps );
  assert.equal( result.status, "error" );
  assert.match( byId( CONSOLE_PAGE_ERROR_ID ).textContent as string, /not a full seat id/ );
  assert.equal( h.location.href, "/app/console?seat=e14bd712", "no redirect" );
  assert.equal( document.title, CONSOLE_DEFAULT_TITLE );
} );

test( "no token: redirects to login with a redirect-back that KEEPS the seat and title", () => {
  const search = `?seat=${ SEAT }&title=T`;
  const h = harness( search, { token : false } );
  assert.deepEqual( bootConsolePage( h.deps ), { status : "redirected" } );
  assert.equal( h.location.href, `/app/auth/login?redirect=${ encodeURIComponent( `/app/console${ search }` ) }` );
  assert.equal( h.connects, 0 );
} );

test( "a dead session mid-page bounces to login, keeping the query", () => {
  const search = `?seat=${ SEAT }`;
  const h = harness( search );
  bootConsolePage( h.deps );
  emit( h.bus, "refresh_failed", { error : REFRESH_REJECTED_ERROR, sentRefresh : "refresh" } );
  assert.equal( h.location.href, `/app/auth/login?redirect=${ encodeURIComponent( `/app/console${ search }` ) }` );
} );

test( "visibility and network changes reach the bus, for the transport's reconnect machine", () => {
  const h = harness( `?seat=${ SEAT }` );
  bootConsolePage( h.deps );
  const vis = Object.getOwnPropertyDescriptor( Document.prototype, "visibilityState" );
  let state = "hidden";
  Object.defineProperty( document, "visibilityState", { configurable : true, get : () => state } );
  try {
    document.dispatchEvent( new Event( "visibilitychange" ) );
    state = "visible";
    document.dispatchEvent( new Event( "visibilitychange" ) );
  } finally {
    delete ( document as unknown as Record<string, unknown> )[ "visibilityState" ];
    if ( vis ) Object.defineProperty( Document.prototype, "visibilityState", vis );
  }
  h.winEvents.get( "offline" )!();
  h.winEvents.get( "online" )!();
  assert.deepEqual( h.events, [ "page_hidden", "page_visible", "network_offline", "network_online" ] );
} );

test( "a page missing its mount, title or error element fails loudly, naming it", () => {
  for ( const id of [ CONSOLE_PAGE_MOUNT_ID, CONSOLE_PAGE_TITLE_ID, CONSOLE_PAGE_ERROR_ID ] ) {
    beforeEachReset();
    byId( id ).remove();
    assert.throws( () => bootConsolePage( harness( `?seat=${ SEAT }` ).deps ), new RegExp( `#${ id } not found` ) );
  }
} );

function beforeEachReset(): void {
  const html = readFileSync( HTML_PATH, "utf8" );
  const body = ( html.match( /<body[^>]*>([\s\S]*)<\/body>/ ) as RegExpMatchArray )[ 1 ] as string;
  document.body.innerHTML = body.replace( /<script[\s\S]*?<\/script>/g, "" );
}
