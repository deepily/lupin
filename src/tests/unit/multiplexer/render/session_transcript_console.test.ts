// The live CC console in the reading pane — row 27760534, plan §4, slice 7.
// ACs B4.3, B4.3b (renderer half), B4.4, B4.13, B4.14, B4.15, and the four exits of design (b).
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THESE TESTS DRIVE THE ASSEMBLED PANE, NOT THE RENDERER ALONE. The real ReadingPaneStore,
// ReadingPaneRenderer and SessionTranscriptStore are wired together here, with only the HTTP
// client and the socket's `send` faked — because the lifecycle claims ("close leaves zero
// watches", "Back is unavailable") are claims about how the three cooperate, and a fake
// reading pane would agree with whatever the renderer assumed about it.
import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import { createSessionTranscriptStore } from "../../../../lupin_app/static/js/multiplexer/stores/SessionTranscriptStore";
import type { TranscriptBlock } from "../../../../lupin_app/static/js/multiplexer/stores/SessionTranscriptStore";
import {
  createSessionTranscriptRenderer,
  describeState,
  REFUSED_FALLBACK,
  renderTranscriptBlock,
  UNRECORDED_THINKING_LABEL,
  THINKING_LABEL,
  TOOL_CHIP_MAX,
} from "../../../../lupin_app/static/js/multiplexer/render/SessionTranscriptRenderer";
import type { SessionTranscriptRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SessionTranscriptRenderer";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { LupinEventType } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import { renderSenderCard } from "../../../../lupin_app/static/js/multiplexer/render/templates/senderCard";
import { createSenderCardConsoleButtons } from "../../../../lupin_app/static/js/multiplexer/render/SenderCardConsoleButtons";
import { parseConsolePageQuery } from "../../../../lupin_app/static/js/multiplexer/console/consolePageUrl";

const SEAT  = "e14bd712-700e-46ce-88ea-8db62604ceb4";
const OTHER = "2b76a19a-1111-4111-8111-111111111111";
const EPOCH = "57238c9d-c227-469e-b707-13b7752a7399";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
  // A deliberately tiny markdown: enough that `# x` becomes a heading and `*x*` emphasis, so
  // a block wrongly routed through markdown CHANGES — which is what B4.13 has to see.
  const w = globalThis as unknown as {
    marked    : { parse( s: string ): string };
    DOMPurify : { sanitize( s: string ): string };
    scrollBy  : () => void;
  };
  w.marked = { parse : ( s: string ): string => s.split( "\n" ).map( ( line ) =>
    line.startsWith( "# " ) ? `<h1>${ line.slice( 2 ) }</h1>` : `<p>${ line.replace( /\*([^*]+)\*/g, "<em>$1</em>" ) }</p>` ).join( "" ) };
  w.DOMPurify = { sanitize : ( s: string ): string => s };
  w.scrollBy  = (): void => {};
});

const live: SessionTranscriptRenderer[] = [];
const panes: Array<{ unmount(): void }> = [];
beforeEach(() => { document.body.replaceChildren(); });
// The pane renderer listens on `document`, so one left mounted would answer the next test's clicks.
afterEach(() => {
  while ( live.length ) live.pop()!.unmount();
  while ( panes.length ) panes.pop()!.unmount();
});

function buildShell(): HTMLElement {
  const shell = document.createElement( "div" );
  shell.className = "content-shell";
  shell.innerHTML = `
    <div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <button id="doc-roots-toggle" type="button">📂</button>
      <main class="container"></main>
    </div>
    <div id="content-pane-splitter"></div>
    <aside class="content-pane" id="content-pane" hidden>
      <button id="content-pane-back" type="button">←</button>
      <span id="content-pane-title"></span>
      <button id="content-pane-bustout" type="button">⤢</button>
      <button id="content-pane-close" type="button">×</button>
      <div id="content-pane-body"></div>
      <div id="session-transcript-mount" hidden></div>
    </aside>`;
  document.body.appendChild( shell );
  return shell;
}

type Body = { file_epoch?: string; offset?: number; next_offset?: number; blocks?: unknown };

function setup( opts: { arCount?: number; popOut?: boolean; windowOpens?: boolean } = {} ) {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting( bus );
  const pane     = createReadingPaneStore( { bus, storage } );
  const shell    = buildShell();
  const sent     : Array<Record<string, unknown>> = [];
  const gets     : string[] = [];
  let respond    = ( _p: string ): Body | Promise<Body> =>
    ( { file_epoch : EPOCH, offset : 1000, next_offset : 1100, blocks : [ { kind : "text", text : "hello" } ] } );
  const opens    : string[] = [];
  const targets  : string[] = [];
  // The pane reads the seat through the transcript renderer, exactly as boot.ts wires it; the
  // renderer is built below, so the reader closes over a binding assigned after it.
  let seatReader : ( () => string | null ) | null = null;
  const paneRenderer = createReadingPaneRenderer( {
    eventBus  : bus,
    stores    : { readingPane : pane, actionRequired : { list : () => Array.from( { length : opts.arCount ?? 0 }, () => ( { state : "pending" } ) ) } },
    windowRef : { open : ( url?: string, target?: string ) => {
      opens.push( String( url ) );
      targets.push( String( target ) );
      return opts.windowOpens ? { document : { open () {}, write () {}, close () {} } } : null;
    } },
    ...( opts.popOut ? { consoleSeat : () => ( seatReader as () => string | null )() } : {} ),
  } );
  paneRenderer.mount( shell );
  panes.push( paneRenderer );
  const transcript = createSessionTranscriptStore( {
    bus,
    api  : { get : async <T>( p: string ): Promise<T> => { gets.push( p ); return await respond( p ) as unknown as T; } },
    send : ( env ) => { sent.push( env as Record<string, unknown> ); },
  } );
  const renderer = createSessionTranscriptRenderer( {
    eventBus : bus,
    stores   : { transcript, readingPane : pane },
  } );
  seatReader = () => renderer.showingSeat();
  const mountEl = document.getElementById( "session-transcript-mount" ) as HTMLElement;
  renderer.mount( mountEl );
  live.push( renderer );
  bus.emit( { type : "auth_success", payload : {}, source : "test", ts : 0 } );
  return {
    bus, pane, paneRenderer, transcript, renderer, sent, gets, opens, targets, mountEl,
    setRespond : ( f: typeof respond ) => { respond = f; },
  };
}

const flush   = () => new Promise( ( r ) => setImmediate( r ) );
const $       = ( sel: string ) => document.querySelector( sel ) as HTMLElement;
const click   = ( el: Element ) => el.dispatchEvent( new MouseEvent( "click", { bubbles : true } ) );
const verbs   = ( sent: Array<Record<string, unknown>> ) => sent.map( e => `${ e.type }:${ e.cc_session_id }` );
const emit    = ( bus: EventBus, type: string, payload: unknown ) =>
  bus.emit( { type : type as LupinEventType, payload, source : "test", ts : 0 } );
const liveWatches = ( sent: Array<Record<string, unknown>> ): Set<string> => {
  const set = new Set<string>();
  for ( const e of sent ) {
    if ( e.type === "cc_transcript_watch" )   set.add( e.cc_session_id as string );
    if ( e.type === "cc_transcript_unwatch" ) set.delete( e.cc_session_id as string );
  }
  return set;
};

/** Give the list real scroll geometry — happy-dom lays nothing out. */
function geometry( list: HTMLElement, g: { scrollHeight: number; clientHeight: number; scrollTop?: number } ) {
  let top = g.scrollTop ?? 0;
  Object.defineProperty( list, "scrollHeight", { configurable : true, get : () => g.scrollHeight } );
  Object.defineProperty( list, "clientHeight", { configurable : true, get : () => g.clientHeight } );
  Object.defineProperty( list, "scrollTop",    { configurable : true, get : () => top, set : ( v: number ) => { top = v; } } );
  return g;
}

// ── opening, and the four exits ────────────────────────────────────────────

test( "openSeat shows the console instead of the body and watches the FULL id", async () => {
  const h = setup();
  assert.equal( h.renderer.openSeat( SEAT, "🦉 mr radio — console" ), true );
  await flush();
  assert.equal( h.pane.getPaneContent(), "console" );
  assert.equal( $( "#content-pane" ).hidden, false );
  assert.equal( $( "#content-pane-body" ).hidden, true );
  assert.equal( h.mountEl.hidden, false );
  assert.equal( $( "#content-pane-title" ).textContent, "🦉 mr radio — console" );
  assert.deepEqual( verbs( h.sent ), [ `cc_transcript_watch:${ SEAT }` ] );
  assert.equal( $( ".session-transcript-list" ).textContent, "hello" );
} );

test( "B4.4 close: unwatches, and returns the reading stack EXACTLY as it was", async () => {
  const h = setup();
  h.pane.open( "abstract", "the *doc* I was reading", "My doc" );
  const bodyNode = $( "#content-pane-body" ).firstChild;
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  click( $( "#content-pane-close" ) );
  assert.equal( h.pane.getPaneContent(), "reading" );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
  assert.equal( $( "#content-pane-title" ).textContent, "My doc" );
  assert.equal( $( "#content-pane-body" ).hidden, false );
  assert.equal( h.mountEl.hidden, true );
  // `ok( a === b )`, not `equal( a, b )`: a failing equal on two DOM nodes inspects both,
  // and a happy-dom node graph is large enough to exhaust the test's memory cap.
  assert.ok( $( "#content-pane-body" ).firstChild === bodyNode, "the body was not repainted — no iframe reload" );
} );

test( "B4.4 close with no document underneath closes the pane entirely", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  click( $( "#content-pane-close" ) );
  assert.equal( $( "#content-pane" ).hidden, true );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "B4.4 switch seat: UNWATCH the old seat BEFORE watching the new — never two watches", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "one" );
  await flush();
  h.renderer.openSeat( OTHER, "two" );
  await flush();
  assert.deepEqual( verbs( h.sent ), [
    `cc_transcript_watch:${ SEAT }`, `cc_transcript_unwatch:${ SEAT }`, `cc_transcript_watch:${ OTHER }` ] );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [ OTHER ] );
  assert.equal( $( "#content-pane-title" ).textContent, "two" );
} );

// A pane built WITHOUT the seat reader cannot name a seat, so its bust-out stays disabled for
// the console. (boot.ts always passes the reader; this is the pane's own guard.)
test( "B4.4 Back is unavailable while the console shows; bust-out too when the pane cannot name the seat", async () => {
  const h = setup();
  h.pane.open( "abstract", "a", "A" );
  h.pane.open( "abstract", "b", "B" );
  assert.equal( ( $( "#content-pane-back" ) as HTMLButtonElement ).disabled, false );
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  assert.equal( ( $( "#content-pane-back" ) as HTMLButtonElement ).disabled, true );
  assert.equal( ( $( "#content-pane-bustout" ) as HTMLButtonElement ).disabled, true );
  click( $( "#content-pane-bustout" ) );   // a disabled button dispatches nothing
  assert.deepEqual( h.opens, [] );
  assert.equal( h.pane.getPaneContent(), "console" );
  assert.equal( h.pane.back(), false );
  click( $( "#content-pane-close" ) );
  assert.equal( $( "#content-pane-title" ).textContent, "B", "Back's stack was never touched" );
  assert.equal( ( $( "#content-pane-bustout" ) as HTMLButtonElement ).disabled, false );
} );

test( "opening a document from the console leaves it — and unwatches", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  h.pane.open( "doc", "/app/docs?path=lupin/README.md", "README" );
  assert.equal( h.pane.getPaneContent(), "reading" );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "a switch to vertical layout, or a full close, also unwatches", async () => {
  const h = setup();
  h.pane.toggleLayoutMode();   // → horizontal
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  h.pane.toggleLayoutMode();   // → vertical clears the pane
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );

  h.renderer.openSeat( SEAT, "console" );
  await flush();
  h.pane.close();
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "the action-required card outranks the console: openSeat refuses and watches nothing", async () => {
  const h = setup( { arCount : 1 } );
  click( $( "#layout-mode-toggle" ) );   // the renderer's toggle lifts a live AR into the pane
  assert.equal( h.pane.isActionRequiredInPane(), true );
  assert.equal( h.renderer.openSeat( SEAT, "console" ), false );
  await flush();
  assert.deepEqual( h.sent, [] );
  assert.equal( h.pane.showReading(), false, "the console never opened" );
} );

test( "AR arriving while the console shows hides it without unwatching; AR leaving shows it again", async () => {
  const h = setup();
  h.pane.toggleLayoutMode();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  h.pane.enterActionRequiredPane();
  assert.equal( h.mountEl.hidden, true );
  assert.equal( $( "#content-pane-title" ).textContent, "Action Required" );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [ SEAT ] );
  click( $( "#content-pane-close" ) );   // inert while AR owns the pane
  assert.equal( h.pane.getPaneContent(), "console" );
  h.pane.exitActionRequiredPane();
  assert.equal( h.mountEl.hidden, false );
} );

test( "B4.4 + B4.15 unmount leaves zero watches, and a RELOAD returns to the reading view", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  live.pop()!.unmount();
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
  assert.equal( h.mountEl.childElementCount, 0 );

  // The reload: fresh stores and renderers over the same storage. Nothing restores the axis.
  const fresh = setup();
  await flush();
  assert.equal( fresh.pane.getPaneContent(), "reading" );
  assert.equal( fresh.mountEl.hidden, true );
  assert.deepEqual( fresh.sent, [] );
  assert.equal( fresh.transcript.snapshot().watchedCcSessionId, null );
} );

test( "unmount with nothing watched sends nothing; mounting twice throws", () => {
  const h = setup();
  const r = live.pop()!;
  r.unmount();
  assert.deepEqual( h.sent, [] );
  r.mount( h.mountEl );
  r.forceRenderForTesting();
  assert.equal( ( $( ".session-transcript-earlier" ) as HTMLButtonElement ).hidden, true, "nothing watched: nothing to page" );
  assert.throws( () => r.mount( h.mountEl ), /already mounted/ );
  live.push( r );
} );

test( "a pane change that stays in the reading view does not touch the transcript", async () => {
  const h = setup();
  h.pane.open( "abstract", "x", "X" );
  assert.deepEqual( h.sent, [] );
} );

test( "a page without the console mount still renders the reading pane", () => {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const pane  = createReadingPaneStore( { bus, storage : createStorageServiceForTesting( bus ) } );
  const shell = buildShell();
  document.getElementById( "session-transcript-mount" )!.remove();
  const r = createReadingPaneRenderer( { eventBus : bus, stores : { readingPane : pane, actionRequired : { list : () => [] } }, windowRef : { open : () => null } } );
  r.mount( shell );
  panes.push( r );
  pane.showConsole( "c" );
  assert.equal( $( "#content-pane-body" ).hidden, true );
} );

// ── pop-out: the console's own tab (Rick's ruling 2026-09-28) ─────────────

test( "pop-out: bust-out is ENABLED on the console and opens /app/console with the seat and title encoded", async () => {
  const h = setup( { popOut : true, windowOpens : true } );
  h.pane.open( "abstract", "the doc underneath", "Underneath" );
  const title = "🦉 mr radio & co — console #1";
  h.renderer.openSeat( SEAT, title );
  await flush();
  const bust = $( "#content-pane-bustout" ) as HTMLButtonElement;
  assert.equal( bust.disabled, false );

  click( bust );
  assert.equal( h.opens.length, 1 );
  const href = h.opens[ 0 ]!;
  assert.equal( href, `/app/console?seat=${ SEAT }&title=%F0%9F%A6%89%20mr%20radio%20%26%20co%20%E2%80%94%20console%20%231` );
  assert.deepEqual( h.targets, [ "_blank" ] );
  // The page reads back exactly what the pane wrote — the one contract, both directions.
  const parsed = parseConsolePageQuery( href.slice( href.indexOf( "?" ) ) );
  assert.deepEqual( parsed, { seat : SEAT, title, error : null } );

  // ...and the pane leaves the console the way close does: back to the reading stack, unwatched,
  // so the seat is watched by the new tab alone.
  assert.equal( h.pane.getPaneContent(), "reading" );
  assert.equal( $( "#content-pane-title" ).textContent, "Underneath" );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "pop-out with no document underneath closes the pane, as close would", async () => {
  const h = setup( { popOut : true, windowOpens : true } );
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  click( $( "#content-pane-bustout" ) );
  assert.equal( $( "#content-pane" ).hidden, true );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "pop-out blocked by the browser (window.open → null) keeps the console where it is", async () => {
  const h = setup( { popOut : true } );
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  click( $( "#content-pane-bustout" ) );
  assert.equal( h.opens.length, 1, "the tab was asked for" );
  assert.equal( h.pane.getPaneContent(), "console", "nothing opened, so nothing is torn down" );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [ SEAT ] );
} );

test( "pop-out clicked before the seat is watched opens nothing", () => {
  const h = setup( { popOut : true, windowOpens : true } );
  h.pane.showConsole( "no seat yet" );   // the axis without a watch: the reader answers null
  assert.equal( ( $( "#content-pane-bustout" ) as HTMLButtonElement ).disabled, false );
  click( $( "#content-pane-bustout" ) );
  assert.deepEqual( h.opens, [] );
  assert.equal( h.pane.getPaneContent(), "console" );
} );

test( "doc bust-out is unchanged by the console pop-out: a document still opens its own href", () => {
  const h = setup( { popOut : true, windowOpens : true } );
  h.pane.open( "doc", "/app/docs?path=lupin/README.md", "README" );
  click( $( "#content-pane-bustout" ) );
  assert.equal( h.opens.length, 1 );
  assert.ok( h.opens[ 0 ]!.startsWith( "/app/docs?path=lupin/README.md" ), h.opens[ 0 ] );
  assert.equal( h.opens[ 0 ]!.includes( "/app/console" ), false );
  assert.equal( $( "#content-pane" ).hidden, true, "a doc bust-out closes the pane, as before" );
} );

// ── the console button toggles (Rick, 2026-09-28) ──────────────────────────

test( "toggleSeat: no console → opens; same seat → closes back to where the pane was; other seat → switches", async () => {
  const h = setup();
  h.pane.open( "abstract", "reading this", "Doc" );
  assert.equal( h.renderer.showingSeat(), null );

  assert.equal( h.renderer.toggleSeat( SEAT, "one" ), true );
  await flush();
  assert.equal( h.renderer.showingSeat(), SEAT );
  assert.equal( $( "#content-pane-title" ).textContent, "one" );

  assert.equal( h.renderer.toggleSeat( OTHER, "two" ), true, "a different seat switches, never closes" );
  await flush();
  assert.equal( h.renderer.showingSeat(), OTHER );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [ OTHER ] );

  assert.equal( h.renderer.toggleSeat( OTHER, "two" ), false, "the same seat again closes it" );
  assert.equal( h.renderer.showingSeat(), null );
  assert.equal( h.pane.getPaneContent(), "reading" );
  assert.equal( $( "#content-pane-title" ).textContent, "Doc", "back exactly where the pane was" );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "toggleSeat on the only thing in the pane closes the pane, as a document's toggle does", async () => {
  const h = setup();
  h.renderer.toggleSeat( SEAT, "one" );
  await flush();
  h.renderer.toggleSeat( SEAT, "one" );
  assert.equal( $( "#content-pane" ).hidden, true );
} );

test( "showingSeat is null while the pane shows the reading stack", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "one" );
  await flush();
  h.pane.showReading();
  assert.equal( h.renderer.showingSeat(), null );
} );

// The assembled button: the REAL card template, the REAL pane and transcript, and the
// affordance wired exactly as boot.ts wires it.
function withButtons( h: ReturnType<typeof setup> ) {
  const container = document.createElement( "div" );
  container.appendChild( renderSenderCard( {
    sender_id : "claude.code@lupin.deepily.ai#e14bd712", display_name : "x", last_active_ts : 0,
    unread_count : 0, conversation_mode_active : false,
    voice_persona : { name : "Mr. Radio", voice_id : "v1", icon : "🦉", color : "#ab1234", borrowed : false },
  }, [], { appTimezone : "UTC" } ) );
  container.appendChild( renderSenderCard( {
    sender_id : "claude.code@lupin.deepily.ai#2b76a19a", display_name : "y", last_active_ts : 0,
    unread_count : 0, conversation_mode_active : false,
    voice_persona : { name : "Rio", voice_id : "v2", icon : "🎸", color : "#123456", borrowed : false },
  }, [], { appTimezone : "UTC" } ) );
  document.body.appendChild( container );
  const seats = new Map<string, string>( [ [ "Mr. Radio", SEAT ], [ "Rio", OTHER ] ] );
  const buttons = createSenderCardConsoleButtons( {
    eventBus   : h.bus,
    affordance : {
      resolve : ( _senderId, personaName ) => seats.get( personaName as string ) ?? null,
      open    : ( seat, title ) => { h.renderer.toggleSeat( seat, title ); },
      showing : () => h.renderer.showingSeat(),
    },
  } );
  buttons.mount( container );
  panes.push( buttons );
  const btn     = ( seat: string ) => container.querySelector( `[data-seat="${ seat }"]` ) as HTMLButtonElement;
  const pressed = () => [ SEAT, OTHER ].map( s => btn( s ).getAttribute( "aria-pressed" ) );
  return { btn, pressed };
}

test( "the button toggles the console and aria-pressed follows it: open, switch, same-seat close", async () => {
  const h = setup();
  const b = withButtons( h );
  assert.deepEqual( b.pressed(), [ "false", "false" ] );

  b.btn( SEAT ).click();
  await flush();
  assert.equal( h.renderer.showingSeat(), SEAT );
  assert.deepEqual( b.pressed(), [ "true", "false" ] );

  b.btn( OTHER ).click();
  await flush();
  assert.equal( h.renderer.showingSeat(), OTHER );
  assert.deepEqual( b.pressed(), [ "false", "true" ] );

  b.btn( OTHER ).click();
  assert.equal( h.renderer.showingSeat(), null );
  assert.deepEqual( b.pressed(), [ "false", "false" ] );
  assert.deepEqual( [ ...liveWatches( h.sent ) ], [] );
} );

test( "aria-pressed clears when the console closes from the PANE's close button", async () => {
  const h = setup();
  const b = withButtons( h );
  b.btn( SEAT ).click();
  await flush();
  assert.deepEqual( b.pressed(), [ "true", "false" ] );
  click( $( "#content-pane-close" ) );
  assert.deepEqual( b.pressed(), [ "false", "false" ] );
} );

test( "aria-pressed clears when the console is POPPED OUT to its own tab", async () => {
  const h = setup( { popOut : true, windowOpens : true } );
  const b = withButtons( h );
  b.btn( SEAT ).click();
  await flush();
  assert.deepEqual( b.pressed(), [ "true", "false" ] );
  click( $( "#content-pane-bustout" ) );
  assert.equal( h.opens.length, 1 );
  assert.deepEqual( b.pressed(), [ "false", "false" ] );
} );

// ── auto-follow, Jump to live, load earlier (B4.3, B4.3b) ──────────────────

test( "B4.3: pinned to the live end it follows; scrolled up it stops; Jump to live returns", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  const list = $( ".session-transcript-list" );
  const g    = geometry( list, { scrollHeight : 1000, clientHeight : 200, scrollTop : 800 } );

  emit( h.bus, "cc_transcript_append", { cc_session_id : SEAT, file_epoch : EPOCH, offset : 1100, next_offset : 1200, blocks : [ { kind : "text", text : "one" } ] } );
  assert.equal( list.scrollTop, 1000, "following pins the bottom edge (newest at the BOTTOM, OSQ-9)" );
  assert.equal( ( $( ".session-transcript-jump" ) as HTMLButtonElement ).hidden, true );

  list.scrollTop = 100;
  list.dispatchEvent( new Event( "scroll" ) );
  assert.equal( h.renderer.isFollowing(), false );
  assert.equal( ( $( ".session-transcript-jump" ) as HTMLButtonElement ).hidden, false );
  g.scrollHeight = 1300;
  emit( h.bus, "cc_transcript_append", { cc_session_id : SEAT, file_epoch : EPOCH, offset : 1200, next_offset : 1300, blocks : [ { kind : "text", text : "two" } ] } );
  assert.equal( list.scrollTop, 100, "scrolled up, new output does not yank the reader" );

  click( $( ".session-transcript-jump" ) );
  assert.equal( h.renderer.isFollowing(), true );
  assert.equal( list.scrollTop, 1300 );
  assert.equal( ( $( ".session-transcript-jump" ) as HTMLButtonElement ).hidden, true );

  list.scrollTop = 1300 - 200 - 3;   // within the slack counts as the live end
  list.dispatchEvent( new Event( "scroll" ) );
  assert.equal( h.renderer.isFollowing(), true );
} );

test( "B4.3b: Load earlier pages backwards and PREPENDS without moving the reader's view", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  const list    = $( ".session-transcript-list" );
  const earlier = $( ".session-transcript-earlier" ) as HTMLButtonElement;
  assert.equal( earlier.hidden, false, "offset 1000 > 0, so there is file before us" );

  const g = geometry( list, { scrollHeight : 1000, clientHeight : 200, scrollTop : 300 } );
  list.dispatchEvent( new Event( "scroll" ) );   // the reader is up in the history

  let release!: ( b: Body ) => void;
  h.setRespond( () => new Promise<Body>( ( r ) => { release = r; } ) );
  click( earlier );
  await flush();
  assert.equal( earlier.disabled, true, "in flight: no double page" );
  g.scrollHeight = 1500;   // the prepended page adds 500px above
  release( { file_epoch : EPOCH, offset : 0, next_offset : 1000, blocks : [ { kind : "text", text : "older" } ] } );
  await flush();

  assert.ok( h.gets.at( -1 )!.includes( "before_offset=1000" ) );
  assert.deepEqual( Array.from( list.children ).map( c => c.textContent ), [ "older", "hello" ] );
  assert.equal( list.scrollTop, 800, "same distance from the bottom as before: the view did not jump" );
  assert.equal( earlier.hidden, true, "offset 0 — the start of the epoch" );
  assert.equal( earlier.disabled, false );
} );

test( "the status line says when the stream is catching up or has ended, and hides otherwise", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  const bar = $( ".session-transcript-bottom" );
  assert.equal( bar.hidden, true );
  emit( h.bus, "cc_transcript_state", { cc_session_id : SEAT, file_epoch : EPOCH, state : "ended" } );
  assert.equal( $( ".session-transcript-state" ).textContent, "Session ended" );
  assert.equal( bar.hidden, false );
  assert.equal( describeState( { ...h.transcript.snapshot(), repairing : true } ), "Catching up…" );
} );

// Row a68b10a3: a refused watch must say something, or the pane goes blank.
test( "a refused watch says why: not_found reads \"Session not found\", anything else a fallback", async () => {
  const snap = ( streamState: string | null, streamReason: string | null ) =>
    ( { ...setup().transcript.snapshot(), streamState, streamReason } );
  assert.equal( describeState( snap( "refused", "not_found" ) ), "Session not found" );
  for ( const reason of [ null, "something_new", "constructor", "toString" ] ) {
    assert.equal( describeState( snap( "refused", reason ) ), REFUSED_FALLBACK, `reason ${ reason }` );
  }
  assert.equal( REFUSED_FALLBACK, "Watch refused" );
  assert.equal( describeState( snap( "live", "not_found" ) ), "", "a reason on a non-refused state says nothing" );
  assert.equal( describeState( snap( null, null ) ), "" );
} );

test( "a refused frame reaches the pane as a visible status line", async () => {
  const h = setup();
  h.renderer.openSeat( SEAT, "console" );
  await flush();
  emit( h.bus, "cc_transcript_state", { cc_session_id : SEAT, file_epoch : null, state : "refused", reason : "not_found" } );
  assert.equal( $( ".session-transcript-state" ).textContent, "Session not found" );
  assert.equal( $( ".session-transcript-bottom" ).hidden, false );
} );

// ── block rendering (B4.13, B4.14, Q2, OSQ-7) ──────────────────────────────

const DUMP = "# not a heading\n*not emphasis*\n    indented line";

test( "B4.13: a tool result renders BYTE-IDENTICAL to its source; the same prose renders as markup", () => {
  const tool = renderTranscriptBlock( { kind : "tool_result", text : DUMP } );
  assert.equal( tool.querySelector( "pre" )!.textContent, DUMP );
  assert.equal( tool.querySelectorAll( "h1, em" ).length, 0 );

  const prose = renderTranscriptBlock( { kind : "text", text : DUMP, role : "assistant" } );
  assert.ok( prose.querySelector( "h1" ), "prose goes through markdown" );
  assert.ok( prose.querySelector( "em" ) );
  assert.equal( prose.getAttribute( "data-role" ), "assistant" );
} );

test( "B4.14: an UNRECOGNISED kind renders its text as plain text — visible, not dropped", () => {
  const el = renderTranscriptBlock( { kind : "kind_invented_for_this_test", text : DUMP } );
  assert.equal( el.getAttribute( "data-kind" ), "kind_invented_for_this_test" );
  assert.equal( el.querySelector( "pre" )!.textContent, DUMP );
  assert.equal( el.querySelectorAll( "details" ).length, 0, "shown outright, not folded away" );
} );

test( "Q2: a tool call is a collapsed ONE-LINE chip; its full text is inside, as plain text", () => {
  const long = `Bash(${ "x".repeat( 200 ) })\nsecond line`;
  const el   = renderTranscriptBlock( { kind : "tool_call", text : long } );
  const d    = el.querySelector( "details" )!;
  assert.equal( d.open, false );
  assert.equal( d.querySelector( "summary" )!.textContent, `${ long.split( "\n" )[ 0 ]!.slice( 0, TOOL_CHIP_MAX ) }…` );
  assert.equal( d.querySelector( "pre" )!.textContent, long );
  const short = renderTranscriptBlock( { kind : "tool_call", text : "Read(file.py)" } );
  assert.equal( short.querySelector( "summary" )!.textContent, "Read(file.py)" );
} );

test( "Q2: tool results are FOLDED and expandable", () => {
  const d = renderTranscriptBlock( { kind : "tool_result", text : "body" } ).querySelector( "details" )!;
  assert.equal( d.open, false );
  assert.equal( d.querySelector( "summary" )!.textContent, "tool result" );
} );

// Row 2742f945 (Rick, 2026-09-29): the ~6% of thinking blocks that carry text show inline.
test( "row 2742f945: thinking WITH text is INLINE under a label, never folded, as plain text", () => {
  const el = renderTranscriptBlock( { kind : "thinking", text : "M1 and M3 are built, committed" } );
  assert.equal( el.querySelectorAll( "details" ).length, 0, "no fold" );
  const wrap = el.querySelector( ".session-transcript-thinking" )!;
  assert.equal( wrap.querySelector( ".session-transcript-thinking-label" )!.textContent, THINKING_LABEL );
  assert.equal( THINKING_LABEL, "💭 thinking" );
  assert.equal( wrap.querySelector( "pre" )!.textContent, "M1 and M3 are built, committed" );
  assert.equal( el.getAttribute( "data-kind" ), "thinking" );
  assert.equal( el.querySelectorAll( ".session-transcript-unrecorded" ).length, 0 );
} );

test( "row 2742f945: inline thinking is plain text — markup and markdown are not interpreted", () => {
  const el = renderTranscriptBlock( { kind : "thinking", text : "# not a heading <b>x</b>\n* not a list" } );
  assert.equal( el.querySelectorAll( "b, h1, ul, li" ).length, 0 );
  assert.equal( el.querySelector( "pre" )!.textContent, "# not a heading <b>x</b>\n* not a list" );
} );

test( "row 2742f945: inline thinking still says when the server cut it to budget", () => {
  const el = renderTranscriptBlock( { kind : "thinking", text : "abc", truncated : true } );
  assert.equal( el.querySelector( ".session-transcript-truncated" )!.textContent, "… truncated" );
} );

test( "a block cut to budget says so; a block with no text renders empty, not broken", () => {
  const cut = renderTranscriptBlock( { kind : "tool_result", text : "abc", truncated : true } );
  assert.equal( cut.querySelector( ".session-transcript-truncated" )!.textContent, "… truncated" );
  const empty = renderTranscriptBlock( { kind : "tool_result" } as TranscriptBlock );
  assert.equal( empty.querySelector( "pre" )!.textContent, "" );
  assert.equal( empty.hasAttribute( "data-role" ), false );
} );

// Claude Code records most thinking as a signature with EMPTY text (measured on a live
// transcript, 2026-09-28: 4 of the last 5 thinking blocks). A fold that opens onto nothing
// looks broken, so an empty one is a plain label that cannot be expanded.
test( "OSQ-7: thinking with no recorded text is a dim label, not an empty fold", () => {
  for ( const block of [ { kind : "thinking" }, { kind : "thinking", text : "" }, { kind : "thinking", text : "  \n " } ] ) {
    const el = renderTranscriptBlock( block as TranscriptBlock );
    assert.equal( el.querySelectorAll( "details" ).length, 0, `no fold for ${ JSON.stringify( block ) }` );
    assert.equal( el.querySelector( ".session-transcript-unrecorded" )!.textContent, UNRECORDED_THINKING_LABEL );
    assert.equal( el.getAttribute( "data-kind" ), "thinking" );
  }
  assert.equal( UNRECORDED_THINKING_LABEL, "💭 thinking (not recorded)" );
  const recorded = renderTranscriptBlock( { kind : "thinking", text : "weighing two options" } );
  assert.equal( recorded.querySelectorAll( ".session-transcript-unrecorded" ).length, 0 );
  assert.equal( recorded.querySelector( ".session-transcript-thinking pre" )!.textContent, "weighing two options" );
} );
