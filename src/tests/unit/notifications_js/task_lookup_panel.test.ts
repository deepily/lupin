// Ticket lookup by hash on the notifications client — the other half of Rick's
// findability P0 (row 732151f2).
//
// WHAT THIS FILE IS REALLY GUARDING. Two things, and neither is "the box
// renders":
//   1. THE ENDPOINT. The lookup must call /api/tasks/<ref>, which applies no
//      board-visibility filter and therefore finds HOLDING-AREA rows. The board
//      query (/api/tasks?id_prefix=) chains _apply_owed_filter after the prefix
//      match — measured 2026-09-09, it could see 1 of the 23 held rows. A future
//      "simplification" onto that path must redden here, not ship quietly.
//   2. THE OUTCOMES STAY DISTINCT. Not-found, ambiguous, signed-out, store-down
//      and asset-missing call for five different next moves. Collapsing them is
//      the api-key-staircase defect in another costume.
//
// Harness mirrors task_list_panel.test.ts: slice notifications.js before its
// DOM-ready init, run it in this context, Object.create the prototype to skip
// the constructor, hand-set only the fields these methods read.
//
// Run: npx tsx --test src/tests/unit/notifications_js/task_lookup_panel.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

// The REAL shared module, not a copy — the same discipline task_list_panel.test.ts
// uses for the query constant. notifications.js is a classic script and reads
// these off `window`, so the harness stands in for the page's <script type=module>.
import {
  taskLookupPath,
  taskRefRefusalMessage,
  TASK_LOOKUP_AUTH_REQUIRED_MESSAGE,
  TASK_LOOKUP_UNREACHABLE_MESSAGE,
} from "../../../lupin_app/static/js/shared/task-lookup.js";
import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  window.LUPIN_TASK_LOOKUP_PATH                  = taskLookupPath;
  window.LUPIN_TASK_REF_REFUSAL_MESSAGE          = taskRefRefusalMessage;
  window.LUPIN_TASK_LOOKUP_AUTH_REQUIRED_MESSAGE = TASK_LOOKUP_AUTH_REQUIRED_MESSAGE;
  window.LUPIN_TASK_LOOKUP_UNREACHABLE_MESSAGE   = TASK_LOOKUP_UNREACHABLE_MESSAGE;

  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS },
  );
} );

/** A UI instance with only what these methods touch. */
function makeUI( fetchImpl: ( url: string ) => Promise<unknown> ) {
  const ui = Object.create( ( globalThis as never as { NotificationsUI: { prototype: object } } ).NotificationsUI.prototype );
  ui.log = () => {};
  ui.authedFetch = fetchImpl;
  return ui as {
    lookupTaskByRef  : ( typed: string ) => Promise<Record<string, unknown>>;
    describeTaskLookup : ( typed: string, outcome: Record<string, unknown> ) => { text: string; state: string };
    runTaskLookup    : () => Promise<void>;
  };
}

/** A Response-alike. `ok` is derived so a caller cannot set an incoherent pair. */
function response( status: number, body: unknown = {} ) {
  return {
    status,
    ok   : status >= 200 && status < 300,
    json : () => Promise.resolve( body ),
  };
}

beforeEach( () => {
  window.LUPIN_TASK_LOOKUP_PATH                  = taskLookupPath;
  window.LUPIN_TASK_REF_REFUSAL_MESSAGE          = taskRefRefusalMessage;
  window.LUPIN_TASK_LOOKUP_AUTH_REQUIRED_MESSAGE = TASK_LOOKUP_AUTH_REQUIRED_MESSAGE;
  window.LUPIN_TASK_LOOKUP_UNREACHABLE_MESSAGE   = TASK_LOOKUP_UNREACHABLE_MESSAGE;
  document.body.innerHTML = "";
} );

// ---------------------------------------------------------------------------
// 🔴 THE ENDPOINT
// ---------------------------------------------------------------------------

test( "the lookup calls the visibility-free single-row endpoint", async () => {
  const calls: string[] = [];
  const ui = makeUI( ( url ) => { calls.push( url ); return Promise.resolve( response( 200, { id: "x" } ) ); } );

  await ui.lookupTaskByRef( "3fdf4fb4" );

  assert.deepEqual( calls, [ "/api/tasks/3fdf4fb4" ] );
  assert.ok( !calls[ 0 ].includes( "id_prefix" ),
    "the board query hides held rows — the lookup must not be moved onto it" );
} );

test( "a holding-area row comes back as found, WITH its status", async () => {
  const held = { id: "3fdf4fb4-2370-4117-9a02-c271fcecc331", title: "Main is RED", status: "not_approved", owner_persona: "maria", priority: "P2" };
  const ui = makeUI( () => Promise.resolve( response( 200, held ) ) );

  const outcome = await ui.lookupTaskByRef( "3fdf4fb4" );
  assert.equal( outcome.state, "found" );

  const { text } = ui.describeTaskLookup( "3fdf4fb4", outcome );
  assert.match( text, /^Main is RED/, "the title leads — that is what a human recognises" );
  assert.match( text, /not_approved/, "which pile it is in is usually the actual question" );
} );

// ---------------------------------------------------------------------------
// LOCAL REFUSAL — no round trip for something we can already judge
// ---------------------------------------------------------------------------

test( "junk is refused locally, with no request", async () => {
  const calls: string[] = [];
  const ui = makeUI( ( url ) => { calls.push( url ); return Promise.resolve( response( 200 ) ); } );

  const outcome = await ui.lookupTaskByRef( "hello" );

  assert.equal( outcome.state, "refused" );
  assert.deepEqual( calls, [], "no request may be spent on a ref we can refuse locally" );
} );

test( "a missing shared module is its OWN state, not an outage", async () => {
  // A 404'd static asset and a down store need different remedies. Reporting
  // one as the other sends the reader to triage an outage that is not happening
  // — the exact separation fetchTaskList already makes for its query module.
  delete window.LUPIN_TASK_LOOKUP_PATH;
  const ui = makeUI( () => Promise.resolve( response( 200 ) ) );

  const outcome = await ui.lookupTaskByRef( "3fdf4fb4" );
  assert.equal( outcome.state, "module_missing" );

  const { text } = ui.describeTaskLookup( "3fdf4fb4", outcome );
  assert.match( text, /asset/i );
  assert.ok( !/store did not answer/i.test( text ),
    "a deploy defect must not be reported as the store being down" );
} );

// ---------------------------------------------------------------------------
// THE OUTCOMES MUST NOT COLLAPSE
// ---------------------------------------------------------------------------

test( "404, 422, 401 and 500 map to four different states", async () => {
  const cases: Array<[ number, string ]> = [
    [ 404, "missing" ],
    [ 422, "ambiguous" ],
    [ 401, "auth_required" ],
    [ 500, "unreachable" ],
  ];
  for ( const [ status, expected ] of cases ) {
    const ui = makeUI( () => Promise.resolve( response( status, { detail: "d" } ) ) );
    const outcome = await ui.lookupTaskByRef( "3fdf4fb4" );
    assert.equal( outcome.state, expected, `HTTP ${status} must map to ${expected}` );
  }
} );

test( "the five failure sentences are all different from each other", () => {
  const ui = makeUI( () => Promise.resolve( response( 200 ) ) );
  const texts = [
    ui.describeTaskLookup( "abcd1234", { state: "missing" } ).text,
    ui.describeTaskLookup( "abcd", { state: "ambiguous", detail: null } ).text,
    ui.describeTaskLookup( "abcd1234", { state: "auth_required" } ).text,
    ui.describeTaskLookup( "abcd1234", { state: "unreachable" } ).text,
    ui.describeTaskLookup( "abcd1234", { state: "module_missing" } ).text,
  ];
  assert.equal( new Set( texts ).size, 5,
    "five outcomes calling for five different next moves must read differently" );
} );

test( "an ambiguous 422 passes the server's candidate list through", async () => {
  const detail = "task id prefix '49e5' is ambiguous — it matches 2 items: a, b.";
  const ui = makeUI( () => Promise.resolve( response( 422, { detail } ) ) );

  const outcome = await ui.lookupTaskByRef( "49e5" );
  assert.equal( ui.describeTaskLookup( "49e5", outcome ).text, detail,
    "the server names the candidates; that beats anything composed here" );
} );

test( "a 422 whose body will not parse still yields a usable sentence", async () => {
  const ui = makeUI( () => Promise.resolve( {
    status : 422,
    ok     : false,
    json   : () => Promise.reject( new Error( "not json" ) ),
  } ) );

  const outcome = await ui.lookupTaskByRef( "49e5" );
  assert.equal( outcome.state, "ambiguous" );
  assert.match( ui.describeTaskLookup( "49e5", outcome ).text, /more than one ticket/ );
} );

test( "a network throw is caught, never propagated", async () => {
  const ui = makeUI( () => Promise.reject( new Error( "network down" ) ) );
  const outcome = await ui.lookupTaskByRef( "3fdf4fb4" );
  assert.equal( outcome.state, "unreachable" );
} );

// ---------------------------------------------------------------------------
// THE SUMMARY DEGRADES
// ---------------------------------------------------------------------------

test( "missing fields render as dashes, never the word undefined", () => {
  const ui = makeUI( () => Promise.resolve( response( 200 ) ) );
  const { text } = ui.describeTaskLookup( "x", { state: "found", task: {} } );
  assert.match( text, /\(untitled\)/ );
  assert.match( text, /unassigned/ );
  assert.ok( !text.includes( "undefined" ),
    "a card reading 'undefined' is how a missing field becomes a support question" );
} );

test( "an outcome with no state at all degrades to unreachable rather than throwing", () => {
  const ui = makeUI( () => Promise.resolve( response( 200 ) ) );
  assert.equal( ui.describeTaskLookup( "x", {} ).state, "unreachable" );
} );

// ---------------------------------------------------------------------------
// THE DOM HALF
// ---------------------------------------------------------------------------

test( "runTaskLookup FILTERS THE LIST to the found row", async () => {
  // 🔨 THIS TEST USED TO ASSERT THE OPPOSITE, and that is the point. It checked
  // that the result line said "Found it" — the describe-only build Rick rejected:
  // "it doesn't display it it only puts the title up in green text… you would
  // hide all of the other tickets in the task list and only display the 1 that
  // was found."
  document.body.innerHTML = `
    <input id="task-lookup-input" value="3fdf4fb4">
    <button id="task-lookup-clear" hidden></button>
    <div id="task-lookup-result"></div>
    <div id="task-list-container"></div>
    <span id="task-list-count"></span>`;
  const ui = makeUI( () => Promise.resolve( response( 200, {
    id: "3fdf4fb4-2370-4117-9a02-c271fcecc331", title: "Found it",
    status: "not_approved", owner_persona: "maria", priority: "P0",
  } ) ) );
  // Two rows already on the board, so "only the match is showing" can fail.
  ui._taskListLastGoodTasks = [
    { id: "aaaaaaaa-1", title: "Another row",  status: "queued", owner_persona: "sam",   priority: "P1" },
    { id: "bbbbbbbb-2", title: "And another",  status: "queued", owner_persona: "maria", priority: "P2" },
  ];

  await ui.runTaskLookup();

  const container = document.getElementById( "task-list-container" )!;
  const html      = container.innerHTML;
  assert.match( html, /Found it/, "the row the operator asked for is not on screen" );
  assert.ok( !html.includes( "Another row" ), "the other tickets are still showing — the build that was rejected" );
  assert.ok( !html.includes( "And another" ) );
  assert.match( html, /not_approved/, "a held row shown without its status reads as an ordinary live ticket" );

  const result = document.getElementById( "task-lookup-result" )!;
  assert.equal( result.getAttribute( "data-state" ), "filtered" );
  assert.equal( document.getElementById( "task-lookup-clear" )!.hidden, false, "no way back out of the filter" );
} );

test( "clearTaskLookup puts the whole list back and resets the box", async () => {
  document.body.innerHTML = `
    <input id="task-lookup-input" value="3fdf4fb4">
    <button id="task-lookup-clear" hidden></button>
    <div id="task-lookup-result"></div>
    <div id="task-list-container"></div>
    <span id="task-list-count"></span>`;
  const ui = makeUI( () => Promise.resolve( response( 200, {
    id: "3fdf4fb4-x", title: "Found it", status: "queued", owner_persona: "maria", priority: "P0" } ) ) );
  ui._taskListLastGoodTasks = [
    { id: "aaaaaaaa-1", title: "Another row", status: "queued", owner_persona: "sam", priority: "P1" },
  ];

  await ui.runTaskLookup();
  ui.clearTaskLookup();

  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /Another row/ );
  assert.equal( ( document.getElementById( "task-lookup-input" ) as HTMLInputElement ).value, "",
    "a stale ref left in the box invites a second Enter on old input" );
  assert.equal( document.getElementById( "task-lookup-clear" )!.hidden, true );
} );

test( "a MISS leaves the board alone — a typo must not be destructive", async () => {
  document.body.innerHTML = `
    <input id="task-lookup-input" value="deadbeef">
    <button id="task-lookup-clear" hidden></button>
    <div id="task-lookup-result"></div>
    <div id="task-list-container">EXISTING BOARD</div>`;
  const ui = makeUI( () => Promise.resolve( response( 404 ) ) );

  await ui.runTaskLookup();

  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /EXISTING BOARD/,
    "a miss wiped the list the operator was reading" );
  assert.equal( document.getElementById( "task-lookup-result" )!.getAttribute( "data-state" ), "missing" );
} );

test( "runTaskLookup is a no-op when its elements are absent, not a throw", async () => {
  // It is wired from an INLINE handler, where an exception is swallowed by the
  // browser and invisible to everyone — so the guard has to be here.
  document.body.innerHTML = "";
  const ui = makeUI( () => Promise.resolve( response( 200 ) ) );
  await ui.runTaskLookup();   // must not reject
} );

test( "an empty box refuses without a request rather than searching for everything", async () => {
  document.body.innerHTML = `
    <input id="task-lookup-input" value="   ">
    <div id="task-lookup-result"></div>`;
  const calls: string[] = [];
  const ui = makeUI( ( url ) => { calls.push( url ); return Promise.resolve( response( 200 ) ); } );

  await ui.runTaskLookup();

  assert.deepEqual( calls, [] );
  assert.equal( document.getElementById( "task-lookup-result" )!.getAttribute( "data-state" ), "refused" );
} );

// ---------------------------------------------------------------------------
// AFTER A VERB ON THE FILTERED ROW — Rick, row 700f0e1d, 2026-09-11:
// "whenever delete from a row filtered by the search box takes place, the search
// card results should be cleared so that the whole task list is displayed again."
//
// Driven through the REAL Submit handler, with only the network and the refresh
// stubbed. Kept in step with the multiplexer's settlePinnedAfterVerb tests.
// ---------------------------------------------------------------------------

const PINNED = { id: "3fdf4fb4-2370-4117-9a02-c271fcecc331", title: "Pinned row", status: "queued", owner_persona: "maria", priority: "P1" };
const BOARD_ROWS = [
  { id: "aaaaaaaa-1", title: "Another row", status: "queued", owner_persona: "sam",   priority: "P1" },
  { id: "bbbbbbbb-2", title: "And another", status: "queued", owner_persona: "maria", priority: "P2" },
];

/** The Find box, a filtered list, and one action cell for `rowId` with `verb` chosen. */
function verbHarness( verb: string, rowId: string, transitionOk: boolean, lookupRow: Record<string, unknown> = PINNED ) {
  window.LUPIN_TASK_VERB_SPECS = TASK_VERB_SPECS;
  document.body.innerHTML = `
    <input id="task-lookup-input" value="3fdf4fb4">
    <button id="task-lookup-clear"></button>
    <div id="task-lookup-result" data-state="filtered"></div>
    <span id="task-list-count"></span>
    <div id="task-list-container"></div>
    <table><tbody><tr><td class="task-actions">
      <select class="task-verb-select" data-task-id="${ rowId }"><option value="${ verb }" selected>${ verb }</option></select>
      <input class="task-reason-input" data-task-id="${ rowId }" value="no longer needed">
      <button class="task-submit-button" data-task-id="${ rowId }">Submit</button>
    </td></tr></tbody></table>`;
  const fetched: string[] = [];
  const ui = makeUI( ( url ) => { fetched.push( url ); return Promise.resolve( response( 200, lookupRow ) ); } ) as never as Record<string, unknown> & {
    _handleTaskSubmitClick : ( b: HTMLButtonElement ) => Promise<void>;
    _settlePinnedRowAfterVerb : ( id: string, status: string ) => void;
  };
  let refreshed = 0;
  ui._transitionTask   = async () => ( transitionOk ? { ok: true } : { ok: false, message: "refused by the store" } );
  ui.refreshTaskList   = async () => { refreshed += 1; };
  ui._taskListLastGoodTasks = BOARD_ROWS;
  ui._taskLookupPinned = PINNED;
  const button = document.querySelector<HTMLButtonElement>( ".task-submit-button" )!;
  const listHtml = (): string => document.getElementById( "task-list-container" )!.innerHTML;
  const tick = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );
  return { ui, button, listHtml, fetched, refreshed: () => refreshed, tick };
}

test( "🔴 a DROP on the filtered row clears the search and shows the whole list", async () => {
  const h = verbHarness( "drop", PINNED.id, true );
  await h.ui._handleTaskSubmitClick( h.button );

  assert.equal( h.ui._taskLookupPinned, null, "the filter survived the drop — Rick's complaint" );
  assert.equal( ( document.getElementById( "task-lookup-input" ) as HTMLInputElement ).value, "",
    "the box still holds the dropped row's id" );
  assert.equal( document.getElementById( "task-lookup-clear" )!.hidden, true );
  assert.match( h.listHtml(), /Another row/, "the whole list did not come back" );
  assert.match( h.listHtml(), /And another/ );
  assert.equal( h.refreshed(), 1, "the board must still refresh after the verb" );
} );

test( "a REFUSED drop keeps the filter — nothing left the list", async () => {
  const h = verbHarness( "drop", PINNED.id, false );
  await h.ui._handleTaskSubmitClick( h.button );
  assert.equal( ( h.ui._taskLookupPinned as { id: string } | null )?.id, PINNED.id, "a refusal cleared the operator's filter" );
  assert.equal( ( document.getElementById( "task-lookup-input" ) as HTMLInputElement ).value, "3fdf4fb4" );
} );

test( "🔴 an APPROVE (→ queued) on the filtered row RE-FETCHES the pin and keeps the filter", async () => {
  const approved = { ...PINNED, status: "queued", title: "Pinned row, now approved" };
  const h = verbHarness( "approve", PINNED.id, true, approved );
  await h.ui._handleTaskSubmitClick( h.button );
  await h.tick();

  assert.equal( h.fetched.length, 1, "the pin was not re-fetched, so it would still show the old status" );
  assert.equal( ( h.ui._taskLookupPinned as { title: string } ).title, "Pinned row, now approved" );
  assert.ok( !h.listHtml().includes( "Another row" ), "approve cleared the filter, but the row is still on the list" );
} );

test( "a verb on a DIFFERENT row, or with nothing pinned, leaves the Find box alone", () => {
  const h = verbHarness( "drop", "aaaaaaaa-1", true );
  h.ui._settlePinnedRowAfterVerb( "aaaaaaaa-1", "dropped" );
  assert.equal( ( h.ui._taskLookupPinned as { id: string } ).id, PINNED.id, "another row's drop cleared this filter" );

  h.ui._taskLookupPinned = null;
  h.ui._settlePinnedRowAfterVerb( PINNED.id, "dropped" );   // must not throw
  assert.equal( ( document.getElementById( "task-lookup-input" ) as HTMLInputElement ).value, "3fdf4fb4",
    "an unfiltered list's verb touched the Find box" );
} );
