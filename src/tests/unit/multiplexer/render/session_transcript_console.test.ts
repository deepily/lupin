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
  renderTranscriptBlock,
  UNRECORDED_THINKING_LABEL,
  TOOL_CHIP_MAX,
} from "../../../../lupin_app/static/js/multiplexer/render/SessionTranscriptRenderer";
import type { SessionTranscriptRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SessionTranscriptRenderer";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { LupinEventType } from "../../../../lupin_app/static/js/multiplexer/shared/types";

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

function setup( opts: { arCount?: number } = {} ) {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting( bus );
  const pane     = createReadingPaneStore( { bus, storage } );
  const shell    = buildShell();
  const sent     : Array<Record<string, unknown>> = [];
  const gets     : string[] = [];
  let respond    = ( _p: string ): Body | Promise<Body> =>
    ( { file_epoch : EPOCH, offset : 1000, next_offset : 1100, blocks : [ { kind : "text", text : "hello" } ] } );
  const opens    : string[] = [];
  const paneRenderer = createReadingPaneRenderer( {
    eventBus  : bus,
    stores    : { readingPane : pane, actionRequired : { list : () => Array.from( { length : opts.arCount ?? 0 }, () => ( { state : "pending" } ) ) } },
    windowRef : { open : ( url?: string ) => { opens.push( String( url ) ); return null; } },
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
  const mountEl = document.getElementById( "session-transcript-mount" ) as HTMLElement;
  renderer.mount( mountEl );
  live.push( renderer );
  bus.emit( { type : "auth_success", payload : {}, source : "test", ts : 0 } );
  return {
    bus, pane, paneRenderer, transcript, renderer, sent, gets, opens, mountEl,
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

test( "B4.4 back and bust-out are unavailable while the console shows", async () => {
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

// ── block rendering (B4.13, B4.14, Q2, OSQ-7) ──────────────────────────────

const DUMP = "# not a heading\n*not emphasis*\n    indented line";

test( "B4.13: a tool result renders BYTE-IDENTICAL to its source; the same prose renders as markup", () => {
  const tool = renderTranscriptBlock( { kind : "tool_result", text : DUMP } );
  assert.equal( tool.querySelector( "pre" )!.textContent, DUMP );
  assert.equal( tool.querySelector( "h1, em" ), null );

  const prose = renderTranscriptBlock( { kind : "text", text : DUMP, role : "assistant" } );
  assert.ok( prose.querySelector( "h1" ), "prose goes through markdown" );
  assert.ok( prose.querySelector( "em" ) );
  assert.equal( prose.getAttribute( "data-role" ), "assistant" );
} );

test( "B4.14: an UNRECOGNISED kind renders its text as plain text — visible, not dropped", () => {
  const el = renderTranscriptBlock( { kind : "kind_invented_for_this_test", text : DUMP } );
  assert.equal( el.getAttribute( "data-kind" ), "kind_invented_for_this_test" );
  assert.equal( el.querySelector( "pre" )!.textContent, DUMP );
  assert.equal( el.querySelector( "details" ), null, "shown outright, not folded away" );
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

test( "Q2 + OSQ-7: tool results and thinking are FOLDED and expandable", () => {
  for ( const [ kind, label ] of [ [ "tool_result", "tool result" ], [ "thinking", "thinking" ] ] as const ) {
    const d = renderTranscriptBlock( { kind, text : "body" } ).querySelector( "details" )!;
    assert.equal( d.open, false );
    assert.equal( d.querySelector( "summary" )!.textContent, label );
  }
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
    assert.equal( el.querySelector( "details" ), null, `no fold for ${ JSON.stringify( block ) }` );
    assert.equal( el.querySelector( ".session-transcript-unrecorded" )!.textContent, UNRECORDED_THINKING_LABEL );
    assert.equal( el.getAttribute( "data-kind" ), "thinking" );
  }
  assert.equal( UNRECORDED_THINKING_LABEL, "💭 thinking (not recorded)" );
  const recorded = renderTranscriptBlock( { kind : "thinking", text : "weighing two options" } );
  assert.equal( recorded.querySelector( ".session-transcript-unrecorded" ), null );
  assert.equal( recorded.querySelector( "details pre" )!.textContent, "weighing two options" );
} );
