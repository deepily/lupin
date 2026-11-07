// Tests for the one-click priority link in the legacy client (row 54d62c0e).
//
// A card lists held rows as `[approve ☐](/app/tasks/approve?row=<uuid>) [📋](/app/tasks/view?row=<uuid>)`. The click handler must
// claim the link, send the approve move once, and draw the answer where the link was.
//
// The links are planted inside `#action-required-content`, where the card lives.
// The pane-resident branch of the doc-link listener sends any click there to a new tab.
// A link planted in the history list would pass without exercising that trap.
// `_transitionTask` is replaced by a recorder, so a sent request is read from its calls.
//
// Run: npx tsx --test src/tests/unit/notifications_js/promote_p0_link.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const ROW_A    = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const ROW_B    = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";
const APPROVE  = ( id: string ): string => `/app/tasks/approve?row=${ id }`;
const P0LINK   = ( id: string ): string => `/app/tasks/approve?row=${ id }&priority=P0`;
const DOC_HREF = "/app/docs?path=lupin/src/rnd/a-real-doc.md";

type Result = { ok: boolean; message?: string };
interface Call { id: string; status: string; extras: unknown }

let calls    : Call[];
let tabOpens : unknown[];
let paneOpens: string[];
let release  : Array<( r: Result ) => void>;
let ui       : Record<string, unknown>;
type Row = { title?: string; priority?: string | null; owner_persona?: string | null; status?: string; body?: string | null };
let table    : Record<string, Row | null>;
let asked    : string[];

function buildDOM(): void {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.innerHTML = `
    <div class="content-shell"><div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <button id="doc-roots-toggle" type="button">📂</button>
      <div id="action-required-content"></div>
      <div id="notification-list"></div>
    </div></div>`;
  document.body.appendChild( host );
}

/** Plant a bulleted card with one link per entry in `hrefs`; return the anchors. */
function plantCard( hrefs: string[], hostId = "action-required-content" ): HTMLAnchorElement[] {
  const host = document.getElementById( hostId ) as Element;
  host.replaceChildren();
  return hrefs.map( ( href ) => {
    const li = document.createElement( "li" );
    const a  = document.createElement( "a" );
    a.setAttribute( "href", href );
    a.textContent = "approve ☐";
    li.appendChild( a );
    host.appendChild( li );
    return a;
  } );
}

/** Click and report whether the app claimed it. */
function click( a: Element ): boolean {
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  a.dispatchEvent( ev );
  return ev.defaultPrevented;
}

/** Let pending promise callbacks run. */
const settle = async (): Promise<void> => { for ( let i = 0; i < 5; i++ ) await Promise.resolve(); };

/** Register the listeners one time; each mount adds document listeners that stay. */
function mountOnce(): void {
  buildDOM();
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug = false;
  ui._contentPaneHistory = [];
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui._openContentPane = ( _k: string, payload: string ): void => { paneOpens.push( payload ); };
  ui._initPaneSplitter              = (): void => {};
  ui._updateLayoutModeButtonTooltip = (): void => {};
  ui._handleEmbeddedAudioClick      = (): void => {};
  ui._handleIoFileDownloadClick     = (): void => {};
  ui._toggleLayoutMode              = (): void => {};
  // The recorder: each call parks until the test releases it with a chosen answer.
  ui._transitionTask = ( id: string, status: string, extras: unknown ): Promise<Result> => {
    calls.push( { id, status, extras } );
    return new Promise<Result>( ( res ) => { release.push( res ); } );
  };
  // The reader: answers from `table` and records every id asked for.
  ui._readTask = async ( id: string ): Promise<Row | null> => { asked.push( id ); return table[ id ] ?? null; };
  ( globalThis as unknown as { open: unknown } ).open = ( ...args: unknown[] ): null => { tabOpens.push( args ); return null; };
  ( ui as unknown as { _initMasterDetailLayout(): void } )._initMasterDetailLayout();
}

// Row 009d2d53: the link parsing lives in shared/approve-link.js; notifications.js reads it off window.
const LIB = (): Record<string, ( ...a: any[] ) => any> => ( window as unknown as { LUPIN_APPROVE_LINK: Record<string, ( ...a: any[] ) => any> } ).LUPIN_APPROVE_LINK;

beforeEach( () => {
  calls = []; tabOpens = []; paneOpens = []; release = []; table = {}; asked = [];
  buildDOM();
  document.getElementById( "task-body-overlay" )?.remove();
  document.getElementById( "abstract-tooltip" )?.remove();
} );

before( async () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  await import( "../../../lupin_app/static/js/shared/approve-link.js" );   // row 009d2d53: notifications.js reads the shared module off window
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
  mountOnce();
} );


test( "a P0 link is claimed and sends queued with promote_priority P0 once, opening no tab", () => {
  const [ a ] = plantCard( [ P0LINK( ROW_A ) ] );
  assert.equal( click( a! ), true );
  assert.equal( click( a! ), true, "still claimed on a second click" );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: { promote_priority: "P0" } } ] );
  assert.deepEqual( tabOpens, [] );
} );

test( "the plain approve link sends no P0 flag and the two hrefs are not confused", () => {
  const [ plain ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( plain! );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} } ] );
  const ui2 = { _approveLinkRowId: ( h: string ): unknown => LIB().approveRowId!( h ), _approvePriorityLink: ( h: string | null ): unknown => LIB().approvePriorityLink!( h ) };
  assert.equal( ui2._approveLinkRowId( P0LINK( ROW_A ) ), null );
  assert.equal( ui2._approvePriorityLink( APPROVE( ROW_A ) ), null );
  assert.equal( ui2._approvePriorityLink( null ), null );
  assert.deepEqual( ui2._approvePriorityLink( `/app/tasks/approve?row=${ ROW_A }&priority=P3` ), { rowId: ROW_A, priority: "P3" } );
  assert.equal( ui2._approvePriorityLink( `/app/tasks/approve?row=${ ROW_A }&priority=P6` ), null, "a level outside P0..P5" );
} );

test( "success draws approved at <level> ✅, disabled; a refusal shows the server's words", async () => {
  const [ a, b ] = plantCard( [ `/app/tasks/approve?row=${ ROW_A }&priority=P2`, P0LINK( ROW_B ) ] );
  click( a! ); click( b! );
  assert.deepEqual( calls.map( ( c ) => [ c.id, c.extras ] ), [ [ ROW_A, { promote_priority: "P2" } ], [ ROW_B, { promote_priority: "P0" } ] ], "each request carries its own link's level" );
  release[ 0 ]!( { ok: true } );
  release[ 1 ]!( { ok: false, message: "Promote-to-P0 is honoured only for Rick's login." } );
  await settle();
  const host = document.getElementById( "action-required-content" ) as Element;
  const done = host.querySelector( ".approve-link-approved" ) as Element;
  assert.equal( done.textContent, "approved at P2 ✅" );
  assert.equal( done.getAttribute( "aria-disabled" ), "true" );
  assert.equal( host.querySelector( ".approve-link-refused" )?.textContent, "Promote-to-P0 is honoured only for Rick's login." );
} );

test( "a malformed P0 href and a click off any link are not claimed", () => {
  const [ a ] = plantCard( [ "/app/tasks/approve?row=a3975cf4&priority=P0" ] );
  assert.equal( click( a! ), false );
  assert.equal( click( document.getElementById( "action-required-content" ) as Element ), false );
  assert.deepEqual( calls, [] );
} );

test( "a drawn P0 link for a row that already left the holding area reads approved ✅", async () => {
  const [ a ] = plantCard( [ P0LINK( ROW_A ) ] );
  table[ ROW_A ] = { status: "queued" };
  await LIB().markApproveLinks!( [ a!.parentElement as Element ], ( id: string ) => ui._readTask( id ) );
  const host = document.getElementById( "action-required-content" ) as Element;
  assert.equal( host.querySelector( ".approve-link-approved" )?.textContent, "approved ✅" );
} );

// Row 526bfd86: the P0 link, drawn by the real renderers, in the message and in the abstract.
const REAL_LINE = ( id: string ): string =>
  `- Decision proxy explainer [approve ☐](${ APPROVE( id ) }) [⏫ P0](${ P0LINK( id ) }) [📋](/app/tasks/view?row=${ id })`;

for ( const [ surface, render ] of [ [ "MESSAGE (inline)", "renderMarkdownInline" ], [ "ABSTRACT (block)", "renderMarkdown" ] ] as const ) {
  test( `526bfd86: legacy P0 link in a notification ${ surface } sends promote_priority`, async () => {
    const vendor = resolve( HERE, "../../../lupin_app/static/js/vendor" );
    if ( typeof ( globalThis as Record<string, unknown> ).marked === "undefined" ) {
      vm.runInThisContext( readFileSync( resolve( vendor, "marked.min.js" ), "utf8" ) );
      vm.runInThisContext( readFileSync( resolve( vendor, "purify.min.js" ), "utf8" ) );
    }
    const host = document.getElementById( "action-required-content" ) as Element;
    host.innerHTML = ( ui as Record<string, ( t: string ) => string> )[ render ]!( REAL_LINE( ROW_A ) );
    const anchors = Array.from( host.querySelectorAll( "a" ) );
    assert.equal( anchors.length, 3, "three links drawn" );
    assert.equal( click( anchors[ 1 ]! ), true, "the P0 link is claimed" );
    assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: { promote_priority: "P0" } } ] );
  } );
}
