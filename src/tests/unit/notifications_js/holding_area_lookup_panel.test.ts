// THE HOLDING AREA'S TICKET SEARCH — notifications client, and it RUNS THE CODE.
//
// Rick, 2026-09-09, after accepting the task list's filter: *"Now that you've
// proven how it works I want that extended and added to the holding area on both
// the multiplexer and the notifications client."*
//
// 🔴 THE ASSERTIONS THAT MATTER MOST HERE ARE THE REFUSALS. The lookup endpoint
// is visibility-free on purpose, so it returns queued, done and parked rows just
// as readily as held ones. The task list can show anything it is handed; this
// pane cannot. Every row under a heading that reads "Holding Area" is claimed to
// be waiting on triage, so pinning a queued row here would be a false statement
// made by the LAYOUT — one no wording in the result line could take back.
//
// ⚠️ AND NOTHING HERE READS THE FILE AS TEXT. The Python tier over this client
// has gone green three separate times against a string that merely looked like a
// working control (see holding_area_panel.test.ts's header for the three). These
// instantiate the class and drive the methods.
//
// Run: npx tsx --test src/tests/unit/notifications_js/holding_area_lookup_panel.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TASK_LIST_QUERY, HOLDING_AREA_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";
import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  window.LUPIN_TASK_LIST_QUERY    = TASK_LIST_QUERY;
  window.LUPIN_TASK_VERB_SPECS    = TASK_VERB_SPECS;
  window.LUPIN_HOLDING_AREA_QUERY = HOLDING_AREA_QUERY;

  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type LookupUI = Record<string, unknown> & {
  renderHoldingArea       : ( composite: unknown ) => void;
  runHoldingAreaLookup    : () => Promise<void>;
  clearHoldingAreaLookup  : () => void;
  lookupTaskByRef         : ( typed: string ) => Promise<unknown>;
  _holdingAreaPinned      : unknown;
  _holdingAreaLastGoodComposite : unknown;
};

/** The lookup outcome the class's own `lookupTaskByRef` would have returned. */
function foundOutcome( task: Record<string, unknown> ): Record<string, unknown> {
  return { state: "found", task };
}

function newUI( lookupOutcome: unknown ): LookupUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as LookupUI;
  ui.debug                     = false;
  ui.log                       = (): void => {};
  ui.error                     = (): void => {};
  ui._holdingAreaControlsWired = false;
  ui._holdingAreaPinned        = null;
  ui._holdingAreaLastGoodComposite = null;
  ui.queueSessionId            = "test-session";
  // 🔴 STUBBED AT THE NETWORK SEAM ONLY. Everything downstream — the status
  // check, the pin, the re-render, the result wording — is the real code.
  ui.lookupTaskByRef = (): Promise<unknown> => Promise.resolve( lookupOutcome );
  return ui;
}

function held( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id: "aaaaaaaa-1111-2222-3333-444444444444",
    title: "First held row", status: "not_approved", item_class: "task",
    created_by: "maria 536c8ff7", owner_persona: "maria", priority: "P1", project: "lupin",
    ...over
  };
}

const PANE: Record<string, unknown>[] = [
  held(),
  held( { id: "bbbbbbbb-1111-2222-3333-444444444444", title: "Second held row", created_by: "mr radio 81381447" } ),
  held( { id: "cccccccc-1111-2222-3333-444444444444", title: "Third held row",  created_by: "sam 684c7fdd" } ),
];

function buildDOM(): void {
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.innerHTML = `
    <h3>Holding Area: <span id="holding-area-count">0</span></h3>
    <div class="task-lookup">
      <input type="search" id="holding-area-lookup-input">
      <button type="button" id="holding-area-lookup-go"></button>
      <button type="button" id="holding-area-lookup-clear" hidden></button>
      <div id="holding-area-lookup-result" role="status"></div>
    </div>
    <div id="holding-area-container"></div>`;
  document.body.appendChild( section );
}

beforeEach( () => buildDOM() );

const input  = (): HTMLInputElement => document.getElementById( "holding-area-lookup-input" ) as HTMLInputElement;
const result = (): HTMLElement      => document.getElementById( "holding-area-lookup-result" ) as HTMLElement;
const clearB = (): HTMLButtonElement => document.getElementById( "holding-area-lookup-clear" ) as HTMLButtonElement;
const titles = (): string[] =>
  Array.from( document.querySelectorAll( "#holding-area-container .task-title" ) )
    .map( ( el ) => ( el.textContent ?? "" ).trim() );
const count  = (): string => document.getElementById( "holding-area-count" )?.textContent ?? "";

// ---------------------------------------------------------------------------
// Positive controls
// ---------------------------------------------------------------------------

test( "positive control: the pane really does render three held rows first", () => {
  const ui = newUI( foundOutcome( PANE[ 0 ]! ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );
  assert.equal( titles().length, 3, "without this, 'only one row shows' proves nothing" );
} );

// ---------------------------------------------------------------------------
// The behaviour Rick asked for
// ---------------------------------------------------------------------------

test( "🔴 A FOUND HELD ROW HIDES EVERY OTHER HELD TICKET", async () => {
  const ui = newUI( foundOutcome( PANE[ 1 ]! ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "bbbbbbbb";
  await ui.runHoldingAreaLookup();

  assert.deepEqual( titles(), [ "Second held row" ],
    "the other held tickets are still on screen — this is not a filter" );
  assert.equal( count(), "1", "a count that disagrees with the visible rows reads as data loss" );
  assert.equal( result().getAttribute( "data-state" ), "filtered" );
  assert.equal( clearB().hidden, false, "the clear control must appear once a filter is live" );
} );

test( "🔴 A HELD ROW THE CURRENT POLL DID NOT RETURN IS STILL SHOWN", async () => {
  // The pinned row is the FETCHED row, not an id-filter over the pane's payload.
  // Filtering the payload would render an empty pane here, and empty reads as
  // "does not exist" — worse than no search.
  const offPane = held( { id: "3fdf4fb4-2370-4117-9a02-c271fcecc331", title: "A held row the poll did not return" } );
  const ui = newUI( foundOutcome( offPane ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "3fdf4fb4";
  await ui.runHoldingAreaLookup();

  assert.deepEqual( titles(), [ "A held row the poll did not return" ] );
} );

// ---------------------------------------------------------------------------
// The refusals
// ---------------------------------------------------------------------------

test( "🔴 A QUEUED ROW IS FOUND AND REFUSED — the pane is a claim, not a container", async () => {
  const queued = held( { id: "dddddddd-1111-2222-3333-444444444444", title: "A live queued ticket", status: "queued" } );
  const ui = newUI( foundOutcome( queued ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "dddddddd";
  await ui.runHoldingAreaLookup();

  assert.equal( result().getAttribute( "data-state" ), "out-of-scope",
    "reported as filtered — the pane would be claiming a queued row is awaiting triage" );
  assert.match( result().textContent ?? "", /not in the holding area/ );
  assert.match( result().textContent ?? "", /queued/,
    "the real status must be named, or the operator cannot tell where the row went" );
  assert.equal( titles().length, 3, "a refusal must leave the pane exactly as it was" );
  assert.equal( clearB().hidden, true,
    "a clear control offered when nothing was hidden implies the row IS in this pane" );
} );

test( "a row with no status at all is refused, not silently pinned", async () => {
  const ui = newUI( foundOutcome( { id: "eeeeeeee", title: "Shapeless" } ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "eeeeeeee";
  await ui.runHoldingAreaLookup();

  assert.equal( result().getAttribute( "data-state" ), "out-of-scope" );
  assert.match( result().textContent ?? "", /unknown status/ );
  assert.equal( titles().length, 3 );
} );

test( "a FAILED lookup leaves the pane alone", async () => {
  const ui = newUI( { state: "missing" } );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "99999999";
  await ui.runHoldingAreaLookup();

  assert.notEqual( result().getAttribute( "data-state" ), "filtered" );
  assert.equal( titles().length, 3, "a failed search must not be destructive" );
} );

// ---------------------------------------------------------------------------
// Survival, clearing, and the states that outrank a filter
// ---------------------------------------------------------------------------

test( "🔴 THE FILTER SURVIVES A POLL", async () => {
  const ui = newUI( foundOutcome( PANE[ 2 ]! ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "cccccccc";
  await ui.runHoldingAreaLookup();
  assert.deepEqual( titles(), [ "Third held row" ] );

  ui.renderHoldingArea( { status: "ok", tasks: PANE } ); // the poll lands
  assert.deepEqual( titles(), [ "Third held row" ],
    "the poll dropped the filter — it would evaporate under the operator and read as a bug in the box" );
} );

test( "clearing restores CURRENT rows, not the snapshot from when the filter was applied", async () => {
  const ui = newUI( foundOutcome( PANE[ 0 ]! ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "aaaaaaaa";
  await ui.runHoldingAreaLookup();
  assert.deepEqual( titles(), [ "First held row" ] );

  // A row drains away while the filter is live.
  ui.renderHoldingArea( { status: "ok", tasks: [ PANE[ 1 ]!, PANE[ 2 ]! ] } );
  ui.clearHoldingAreaLookup();

  assert.equal( titles().length, 2, "restored a stale snapshot instead of the current payload" );
  assert.equal( titles().includes( "First held row" ), false, "the drained row came back" );
  assert.equal( count(), "2" );
  assert.equal( result().textContent, "" );
  assert.equal( clearB().hidden, true );
} );

test( "🔴 AN UNREACHABLE STORE IS NEWS AND OUTRANKS A LIVE FILTER", async () => {
  const ui = newUI( foundOutcome( PANE[ 0 ]! ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );

  input().value = "aaaaaaaa";
  await ui.runHoldingAreaLookup();

  ui.renderHoldingArea( { status: "unreachable" } );
  assert.match( document.getElementById( "holding-area-container" )?.textContent ?? "", /unreachable/i,
    "the pinned row was re-asserted over a sentinel — the operator would never learn the pane stopped answering" );
} );

test( "an unreachable poll does not overwrite the last good composite", async () => {
  const ui = newUI( foundOutcome( PANE[ 0 ]! ) );
  ui.renderHoldingArea( { status: "ok", tasks: PANE } );
  ui.renderHoldingArea( { status: "unreachable" } );

  ui.clearHoldingAreaLookup();
  assert.equal( titles().length, 3,
    "clearing after an outage replayed the outage instead of the last rows anyone could read" );
} );

test( "a missing box is a no-op, not a throw — it is wired from an inline handler", async () => {
  const ui = newUI( foundOutcome( PANE[ 0 ]! ) );
  document.body.replaceChildren();
  await ui.runHoldingAreaLookup();   // must not throw
  ui.clearHoldingAreaLookup();       // must not throw
} );
