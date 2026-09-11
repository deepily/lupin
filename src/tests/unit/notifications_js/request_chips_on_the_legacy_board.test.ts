// Promote/demote requests on the LEGACY page — notifications.js, row c9fafb9d (design §6, D4).
//
// 🔴 THE SHARED MODULE IS LOADED THROUGH ITS REAL WINDOW BRIDGE. It is imported dynamically
// AFTER happy-dom registers, so `window.LUPIN_TASK_REQUEST` is published by the module's own
// bridge block — the object the page's classic script reads. A hand-built stand-in would stay
// green against a bridge that forgot to publish a function this client calls.
//
// Harness is the established one (holding_area_panel.test.ts): the class loaded via
// vm.runInThisContext sliced before the DOM-ready init, the prototype Object.create'd, the
// server reached only through a stubbed `authedFetch`.
//
// Run: npx tsx --test src/tests/unit/notifications_js/request_chips_on_the_legacy_board.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { HOLDING_AREA_QUERY, TASK_LIST_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";
import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( async () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  window.LUPIN_TASK_LIST_QUERY    = TASK_LIST_QUERY;
  window.LUPIN_TASK_VERB_SPECS    = TASK_VERB_SPECS;
  window.LUPIN_HOLDING_AREA_QUERY = HOLDING_AREA_QUERY;
  await import( "../../../lupin_app/static/js/shared/task-request.js" );
  assert.ok( window.LUPIN_TASK_REQUEST, "the shared module's bridge did not publish" );

  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type UI = Record<string, unknown> & {
  authedFetch: ( url: string, init?: Record<string, unknown> ) => Promise<unknown>;
  refreshTaskList: () => Promise<void>;
  renderHoldingArea: ( composite: unknown ) => void;
  renderTaskList: ( composite: unknown, stampUpdated?: boolean ) => void;
  _renderRow: ( task: Record<string, unknown>, zone: unknown, opts: { rowClass: string } ) => string;
  _requestChipHtml: ( task: Record<string, unknown> ) => string;
  _handleRequestChipClick: ( target: unknown ) => boolean;
  _handleTaskListClick: ( target: unknown ) => void;
  _hydrateRequestChips: ( container: unknown ) => void;
  _paintRequestStatus: ( chip: unknown, text: string ) => void;
  _paintRequestDetail: ( chip: unknown, detail: unknown ) => void;
  refreshRequestBadges: () => Promise<void>;
};

interface Call { url: string; init?: Record<string, unknown> }

const HELD_ID = "aaaaaaaa-1111-2222-3333-444444444444";
const LIVE_ID = "bbbbbbbb-1111-2222-3333-444444444444";
const FILED   = "2026-09-10T09:00:00Z";

const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

function row( id: string, status: string, move: string | null ): Record<string, unknown> {
  return {
    id, title: `row ${ id.slice( 0, 4 ) }`, status, item_class: "task", created_by: "mr radio 0e61abe3",
    owner_persona: "chloe", priority: "P2", project: "lupin",
    request_state: move === null ? null : "pending", request_move: move, request_ts: move === null ? null : FILED,
  };
}

/**
 * A UI whose server is `respond`. Every call is recorded, and `refreshTaskList` is counted
 * rather than run — the verdict's re-read is the claim, not the board's own fetch.
 */
function newUI( respond: ( url: string, init?: Record<string, unknown> ) => unknown = () => ( { ok: true, status: 200, json: async () => ( {} ) } ) ) {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as UI;
  const calls: Call[] = [];
  const refreshes = { n: 0 };
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.queueSessionId = "test-session";
  ui._holdingAreaControlsWired = false;
  ui._taskListAccordionWired   = false;
  ui._taskListFetchInFlight    = false;
  ui._taskListLastGoodTasks    = null;
  ui.authedFetch = async ( url, init ) => { calls.push( { url, init } ); return respond( url, init ); };
  ui.refreshTaskList = async () => { refreshes.n += 1; };
  return { ui, calls, refreshes };
}

const eventsBody = ( actor: string, reason: string ) => ( {
  ok: true, status: 200,
  json: async () => ( { events: [ { transition: "request_filed", actor, reason: `move: 'admit' (prior request: None) | reason: ${ reason }` } ] } ),
} );

beforeEach( () => {
  document.body.innerHTML = `
    <h3>Task List · <span id="task-list-count">0</span><span id="task-list-request-badge" hidden></span></h3>
    <div id="task-list-container"></div>
    <h3>Holding Area · <span id="holding-area-count">0</span><span id="holding-area-request-badge" hidden></span></h3>
    <div id="holding-area-container"></div>`;
} );

const chipIn = ( id: string ): HTMLElement => document.querySelector<HTMLElement>( `#${ id } .task-request-chip` )!;
const verdictCalls = ( calls: Call[] ) => calls.filter( ( c ) => c.url.endsWith( "/request-verdict" ) );

// ─────────────────────────────── the chip ───────────────────────────────

test( "a pending admit renders the chip the multiplexer renders: text, age, empty detail, Approve, Deny, status", () => {
  const { ui } = newUI();
  const html = ui._requestChipHtml( { ...row( HELD_ID, "not_approved", "admit" ), request_ts: new Date( Date.now() - 3 * 3600e3 ).toISOString() } );
  const holder = document.createElement( "div" );
  holder.innerHTML = html;
  const chip = holder.querySelector<HTMLElement>( ".task-request-chip" )!;
  assert.equal( chip.getAttribute( "data-task-id" ), HELD_ID );
  assert.equal( chip.getAttribute( "data-request-move" ), "admit" );
  assert.equal( chip.querySelector( ".task-request-text" )!.textContent, "⏳ Promote requested · 3h" );
  assert.equal( chip.querySelector( ".task-request-detail" )!.textContent, "" );
  assert.ok( chip.querySelector( ".task-request-approve" ) && chip.querySelector( ".task-request-deny" ) && chip.querySelector( ".task-request-status" ) );
  assert.equal( chip.querySelector( ".task-request-triage" ), null );
} );

test( "a demote chip asks for the triage-by date; a chip with no filing time shows no age", () => {
  const { ui } = newUI();
  const holder = document.createElement( "div" );
  holder.innerHTML = ui._requestChipHtml( { ...row( LIVE_ID, "queued", "demote" ), request_ts: null } );
  assert.equal( holder.querySelector( ".task-request-triage" )!.getAttribute( "aria-label" ), "Triage this by" );
  assert.equal( holder.querySelector( ".task-request-text" )!.textContent, "⏳ Demote requested" );
} );

test( "no chip without a pending request, and none when the shared module did not load", () => {
  const { ui } = newUI();
  assert.equal( ui._requestChipHtml( row( HELD_ID, "not_approved", null ) ), "" );
  const saved = window.LUPIN_TASK_REQUEST;
  window.LUPIN_TASK_REQUEST = undefined;
  try {
    assert.equal( ui._requestChipHtml( row( HELD_ID, "not_approved", "admit" ) ), "" );
  } finally {
    window.LUPIN_TASK_REQUEST = saved;
  }
} );

test( "the shared row carries the chip on the task list and holding area rows, never on the epic board", () => {
  const { ui } = newUI();
  const t = row( LIVE_ID, "queued", "demote" );
  assert.ok( ui._renderRow( t, null, { rowClass: "task-row" } ).includes( "task-request-chip" ) );
  assert.ok( !ui._renderRow( t, null, { rowClass: "epic-row" } ).includes( "task-request-chip" ) );
} );

// ─────────────────────────────── the holding area ───────────────────────────────

test( "a held row's chip sits in its title cell, names who asked and why, and Approve reaches the verdict door", async () => {
  const { ui, calls, refreshes } = newUI( ( url ) =>
    url.endsWith( "/events" ) ? eventsBody( "mr radio 52f3fe21", "ready to start" ) : { ok: true, status: 200 } );
  ui.renderHoldingArea( { status: "ok", tasks: [ row( HELD_ID, "not_approved", "admit" ) ] } );
  const chip = chipIn( "holding-area-container" );
  assert.ok( chip.closest( ".task-col-title" ), "the chip is not on the visible row's title cell" );
  await tick();
  assert.equal( chip.querySelector( ".task-request-detail" )!.textContent, "by mr radio 52f3fe21 — ready to start" );

  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  const sent = verdictCalls( calls );
  assert.equal( sent.length, 1 );
  assert.equal( sent[ 0 ]!.url, `/api/tasks/${ HELD_ID }/request-verdict` );
  assert.equal( sent[ 0 ]!.init!.method, "POST" );
  assert.deepEqual( JSON.parse( String( sent[ 0 ]!.init!.body ) ), { verdict: "approved" } );
  assert.equal( refreshes.n, 1, "a landed verdict re-reads the board — the row moved" );
  assert.ok( !calls.some( ( c ) => c.url.endsWith( "/transition" ) ), "a chip click never runs a row verb" );
} );

test( "a refusal shows the server's words, re-reads nothing, and survives the next paint", async () => {
  const { ui, refreshes } = newUI( ( url ) => url.endsWith( "/events" )
    ? eventsBody( "cheech", "why" )
    : { ok: false, status: 403, json: async () => ( { detail: "only Rick answers a request" } ) } );
  const composite = { status: "ok", tasks: [ row( HELD_ID, "not_approved", "admit" ) ] };
  ui.renderHoldingArea( composite );
  chipIn( "holding-area-container" ).querySelector<HTMLButtonElement>( ".task-request-deny" )!.click();
  await tick();
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-status" )!.textContent, "only Rick answers a request" );
  assert.equal( refreshes.n, 0 );

  ui.renderHoldingArea( composite );
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-status" )!.textContent, "only Rick answers a request",
                "the poll's repaint erased why the click did nothing" );
} );

test( "an error body that is not JSON reads as its status; a transport failure reads as unreachable", async () => {
  let mode = "html";
  const { ui } = newUI( ( url ) => {
    if ( url.endsWith( "/events" ) ) return eventsBody( "x", "y" );
    if ( mode === "html" ) return { ok: false, status: 502, json: async () => { throw new Error( "not json" ); } };
    if ( mode === "detail-object" ) return { ok: false, status: 422, json: async () => ( { detail: { errors: [ "bad" ] } } ) };
    throw new Error( "socket hang up" );
  } );
  const composite = { status: "ok", tasks: [ row( HELD_ID, "not_approved", "admit" ) ] };
  const statusAfterDeny = async (): Promise<string> => {
    ui.renderHoldingArea( composite );
    chipIn( "holding-area-container" ).querySelector<HTMLButtonElement>( ".task-request-deny" )!.click();
    await tick();
    return chipIn( "holding-area-container" ).querySelector( ".task-request-status" )!.textContent ?? "";
  };
  assert.equal( await statusAfterDeny(), "502" );
  mode = "detail-object";
  assert.equal( await statusAfterDeny(), JSON.stringify( { errors: [ "bad" ] } ) );
  mode = "throw";
  assert.equal( await statusAfterDeny(), "unreachable: socket hang up" );
} );

// ─────────────────────────────── the task list ───────────────────────────────

test( "on the task list a demote Approve with no date is refused in the page and sends nothing", async () => {
  const { ui, calls } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "x", "y" ) : { ok: true, status: 200 } );
  ui.renderTaskList( { tasks: [ row( LIVE_ID, "queued", "demote" ) ], count: 1 }, false );
  const chip = chipIn( "task-list-container" );
  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  assert.deepEqual( verdictCalls( calls ), [] );
  assert.match( chip.querySelector( ".task-request-status" )!.textContent ?? "", /triage-by date/ );
} );

test( "on the task list a demote Approve WITH a date sends next_chase_ts at 09:00 local, and is not an accordion toggle", async () => {
  const { ui, calls } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "x", "y" ) : { ok: true, status: 200 } );
  ui.renderTaskList( { tasks: [ row( LIVE_ID, "queued", "demote" ) ], count: 1 }, false );
  const chip = chipIn( "task-list-container" );
  const group = chip.closest( "tbody" )!;
  const collapsedBefore = group.className;
  chip.querySelector<HTMLInputElement>( ".task-request-triage" )!.value = "2026-09-17";
  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  assert.deepEqual( JSON.parse( String( verdictCalls( calls )[ 0 ]!.init!.body ) ),
                    { verdict: "approved", next_chase_ts: new Date( "2026-09-17T09:00:00" ).toISOString() } );
  assert.equal( group.className, collapsedBefore, "the chip click toggled the owner accordion" );
} );

test( "a garbage date is treated as no date", async () => {
  const { ui, calls } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "x", "y" ) : { ok: true, status: 200 } );
  ui.renderTaskList( { tasks: [ row( LIVE_ID, "queued", "demote" ) ], count: 1 }, false );
  const chip = chipIn( "task-list-container" );
  const date = chip.querySelector<HTMLInputElement>( ".task-request-triage" )!;
  Object.defineProperty( date, "value", { value: "not-a-day" } );
  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  assert.deepEqual( verdictCalls( calls ), [] );
} );

test( "a second press while a verdict is on the wire is ignored, and the buttons come back after", async () => {
  let release!: () => void;
  const gate = new Promise<void>( ( r ) => { release = r; } );
  const { ui, calls } = newUI( async ( url ) => {
    if ( url.endsWith( "/events" ) ) return eventsBody( "x", "y" );
    await gate;
    return { ok: true, status: 200 };
  } );
  ui.renderTaskList( { tasks: [ row( LIVE_ID, "queued", "admit" ) ], count: 1 }, false );
  const chip    = chipIn( "task-list-container" );
  const approve = chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!;
  approve.click();
  await tick();
  assert.equal( approve.disabled, true );
  assert.equal( chip.querySelector( ".task-request-status" )!.textContent, "Sending…" );
  ui._handleRequestChipClick( chip.querySelector( ".task-request-deny" ) );
  await tick();
  assert.equal( verdictCalls( calls ).length, 1 );
  release();
  await tick();
  assert.equal( approve.disabled, false );
} );

test( "clicks that are not chip buttons are not the chip handler's; an idless chip sends nothing", async () => {
  const { ui, calls } = newUI();
  assert.equal( ui._handleRequestChipClick( null ), false );
  assert.equal( ui._handleRequestChipClick( document.createElement( "button" ) ), false );
  const orphan = document.createElement( "button" );
  orphan.className = "task-request-approve";
  assert.equal( ui._handleRequestChipClick( orphan ), false, "a chip button outside a chip" );

  const chip = document.createElement( "div" );
  chip.className = "task-request-chip";
  const deny = document.createElement( "button" );
  deny.className = "task-request-deny";
  chip.appendChild( deny );
  assert.equal( ui._handleRequestChipClick( deny ), true );
  await tick();
  assert.deepEqual( calls, [] );
} );

// ─────────────────────────────── hydrate ───────────────────────────────

test( "the filer and reason are read once per filing and cached; a failed read is not cached", async () => {
  let fail = true;
  const { ui, calls } = newUI( ( url ) => {
    if ( !url.endsWith( "/events" ) ) return { ok: true, status: 200 };
    return fail ? { ok: false, status: 500, json: async () => ( {} ) } : eventsBody( "maría", "done upstream" );
  } );
  const composite = { status: "ok", tasks: [ row( HELD_ID, "not_approved", "admit" ) ] };
  ui.renderHoldingArea( composite );
  await tick();
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-detail" )!.textContent, "loading who asked…" );

  fail = false;
  ui.renderHoldingArea( composite );
  await tick();
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-detail" )!.textContent, "by maría — done upstream" );

  ui.renderHoldingArea( composite );
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-detail" )!.textContent, "by maría — done upstream" );
  assert.equal( calls.filter( ( c ) => c.url.endsWith( "/events" ) ).length, 2, "the cached filing was read again" );
} );

test( "a thrown trail read leaves the chip loading; hydrate without a container or module does nothing", async () => {
  const { ui } = newUI( () => { throw new Error( "down" ); } );
  ui.debug = true;
  const origLog = console.log;
  console.log = (): void => {};
  try {
    ui.renderHoldingArea( { status: "ok", tasks: [ row( HELD_ID, "not_approved", "admit" ) ] } );
    await tick();
  } finally {
    console.log = origLog;
  }
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-detail" )!.textContent, "loading who asked…" );
  ui._hydrateRequestChips( null );
  const saved = window.LUPIN_TASK_REQUEST;
  window.LUPIN_TASK_REQUEST = undefined;
  try {
    ui._hydrateRequestChips( document.body );
  } finally {
    window.LUPIN_TASK_REQUEST = saved;
  }
} );

test( "the detail names what is missing, and painting a chip without its spans does not throw", () => {
  const { ui } = newUI();
  const holder = document.createElement( "div" );
  holder.innerHTML = ui._requestChipHtml( row( HELD_ID, "not_approved", "admit" ) );
  const chip = holder.querySelector( ".task-request-chip" )!;
  const detail = (): string => chip.querySelector( ".task-request-detail" )!.textContent ?? "";
  ui._paintRequestDetail( chip, null );
  assert.equal( detail(), "filer and reason not on the trail" );
  ui._paintRequestDetail( chip, { filer: "", reason: "why" } );
  assert.equal( detail(), "why" );
  ui._paintRequestDetail( chip, { filer: "cheech", reason: "" } );
  assert.equal( detail(), "by cheech" );
  ui._paintRequestDetail( chip, { filer: "", reason: "" } );
  assert.equal( detail(), "filer and reason not on the trail" );

  const bare = document.createElement( "div" );
  ui._paintRequestDetail( bare, null );
  ui._paintRequestStatus( bare, "x" );
} );

test( "the task list's pinned row and unreachable replay both fill their chips", async () => {
  const { ui } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "cheech", "blocked" ) : { ok: true, status: 200 } );
  const t = row( LIVE_ID, "queued", "demote" );
  ui.renderTaskList( { tasks: [ t ], count: 1 }, false );
  await tick();
  ui.renderTaskList( { status: "unreachable", tasks: null }, false );
  assert.ok( document.querySelector( ".task-list-unreachable" ) );
  assert.equal( chipIn( "task-list-container" ).querySelector( ".task-request-detail" )!.textContent, "by cheech — blocked" );

  ui._taskLookupPinned = t;
  ui.renderTaskList( { tasks: [], count: 0 }, false );
  assert.equal( chipIn( "task-list-container" ).querySelector( ".task-request-detail" )!.textContent, "by cheech — blocked" );
} );

test( "the holding area's pinned row fills its chip", async () => {
  const { ui } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "mr radio", "go" ) : { ok: true, status: 200 } );
  ui._holdingAreaPinned = row( HELD_ID, "not_approved", "admit" );
  ui.renderHoldingArea( { status: "ok", tasks: [] } );
  await tick();
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-detail" )!.textContent, "by mr radio — go" );
} );

// ─────────────────────────────── badges ───────────────────────────────

test( "the two badges paint their OWN counts, hide at zero, and a failed read hides both", async () => {
  let answer: unknown = { ok: true, status: 200, json: async () => ( { task_area: 2, holding_area: 0 } ) };
  const { ui, calls } = newUI( () => answer );
  await ui.refreshRequestBadges();
  assert.equal( calls[ 0 ]!.url, "/api/tasks/request-badges" );
  const tl = document.getElementById( "task-list-request-badge" )!;
  const ha = document.getElementById( "holding-area-request-badge" )!;
  assert.deepEqual( [ tl.textContent, tl.hidden, ha.textContent, ha.hidden ], [ "2 requests", false, "", true ] );

  answer = { ok: false, status: 500, json: async () => ( {} ) };
  await ui.refreshRequestBadges();
  assert.deepEqual( [ tl.hidden, ha.hidden ], [ true, true ] );

  answer = { ok: true, status: 200, json: async () => ( { task_area: 0, holding_area: 1 } ) };
  await ui.refreshRequestBadges();
  assert.deepEqual( [ ha.textContent, ha.hidden ], [ "1 request", false ] );
  ui.authedFetch = async () => { throw new Error( "down" ); };
  await ui.refreshRequestBadges();
  assert.equal( ha.hidden, true, "a thrown read must not leave the last count standing" );
} );

test( "badges are a no-op without the module, and skip a page that lacks a badge element", async () => {
  const { ui, calls } = newUI( () => ( { ok: true, status: 200, json: async () => ( { task_area: 1, holding_area: 1 } ) } ) );
  const saved = window.LUPIN_TASK_REQUEST;
  window.LUPIN_TASK_REQUEST = undefined;
  try {
    await ui.refreshRequestBadges();
  } finally {
    window.LUPIN_TASK_REQUEST = saved;
  }
  assert.deepEqual( calls, [] );
  document.getElementById( "task-list-request-badge" )!.remove();
  await ui.refreshRequestBadges();
  assert.equal( document.getElementById( "holding-area-request-badge" )!.textContent, "1 request" );
} );

test( "the page links the shared module before notifications.js and carries both badge spans", () => {
  const page = readFileSync( resolve( HERE, "../../../lupin_app/static/html/notifications.html" ), "utf8" );
  const shared = page.indexOf( 'src="/static/js/shared/task-request.js?v=' );
  const client = page.indexOf( 'src="/static/js/notifications.js?v=' );
  assert.ok( shared > 0 && client > shared, "task-request.js must load, and before notifications.js" );
  assert.ok( page.includes( 'id="task-list-request-badge"' ) && page.includes( 'id="holding-area-request-badge"' ) );
} );

test( "the board's 60s tick paints the badges", () => {
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const start = src.indexOf( "    async refreshTaskList() {" );
  const end   = src.indexOf( "\n    }\n", start );
  assert.ok( start > 0 && src.slice( start, end ).includes( "await this.refreshRequestBadges();" ) );
} );

// ─────────────────────────────── Tiffany's review, on this client ───────────────────────────────

test( "F2: a triage date typed on the task list survives the poll's repaint, and is what Approve sends", async () => {
  const { ui, calls } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "x", "y" ) : { ok: true, status: 200 } );
  const composite = { tasks: [ row( LIVE_ID, "queued", "demote" ) ], count: 1 };
  ui.renderTaskList( composite, false );
  chipIn( "task-list-container" ).querySelector<HTMLInputElement>( ".task-request-triage" )!.value = "2026-09-17";

  ui.renderTaskList( composite, true );
  const chip = chipIn( "task-list-container" );
  assert.equal( chip.querySelector<HTMLInputElement>( ".task-request-triage" )!.value, "2026-09-17", "the repaint wiped the typed date" );
  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  assert.equal( JSON.parse( String( verdictCalls( calls )[ 0 ]!.init!.body ) ).next_chase_ts,
                new Date( "2026-09-17T09:00:00" ).toISOString() );
} );

test( "F2: a triage date typed in the holding area survives its repaint too", () => {
  const { ui } = newUI( ( url ) => url.endsWith( "/events" ) ? eventsBody( "x", "y" ) : { ok: true, status: 200 } );
  // A demote request on a held row cannot be filed, but the pane's paint path is the claim.
  const composite = { status: "ok", tasks: [ row( HELD_ID, "not_approved", "demote" ) ] };
  ui.renderHoldingArea( composite );
  chipIn( "holding-area-container" ).querySelector<HTMLInputElement>( ".task-request-triage" )!.value = "2026-09-18";
  ui.renderHoldingArea( composite );
  assert.equal( chipIn( "holding-area-container" ).querySelector<HTMLInputElement>( ".task-request-triage" )!.value, "2026-09-18" );
} );

test( "F3: a refusal belongs to the request it answered — a re-filed request on the same row opens clean", async () => {
  const { ui } = newUI( ( url ) => url.endsWith( "/events" )
    ? eventsBody( "x", "y" )
    : { ok: false, status: 403, json: async () => ( { detail: "only Rick answers a request" } ) } );
  const first = row( HELD_ID, "not_approved", "admit" );
  ui.renderHoldingArea( { status: "ok", tasks: [ first ] } );
  chipIn( "holding-area-container" ).querySelector<HTMLButtonElement>( ".task-request-deny" )!.click();
  await tick();
  ui.renderHoldingArea( { status: "ok", tasks: [ first ] } );
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-status" )!.textContent, "only Rick answers a request",
                "positive control: the same request keeps its refusal" );
  ui.renderHoldingArea( { status: "ok", tasks: [ { ...first, request_ts: "2026-09-10T11:00:00Z" } ] } );
  assert.equal( chipIn( "holding-area-container" ).querySelector( ".task-request-status" )!.textContent, "",
                "the new request inherited the old one's refusal" );
} );
