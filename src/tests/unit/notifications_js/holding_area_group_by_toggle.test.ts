// Holding area — Creator / Assignee toggle in the classic client.
//
// Creator and assignee differ on each row, so a grouping that reads one field in both modes
// cannot pass. The toggle markup is lifted from the real notifications.html, so a button that
// exists only in the test cannot make it green.

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
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  // Both globals stand in for the page's module script. Omit either and the matching
  // fetcher short-circuits to its `query_unavailable` deploy-defect branch — correct
  // production behaviour, and a confusing way for a render test to fail.
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


const NOTIFICATIONS_HTML = resolve( HERE, "../../../lupin_app/static/html/notifications.html" );

type GroupUI = Record<string, unknown> & {
  _groupHeldRows: ( tasks: unknown, by: string, keep?: Set<string> ) => Array<{ filer: string; tasks: Array<Record<string, unknown>> }>;
  _groupHeldRowsByFiler: ( tasks: unknown ) => unknown;
  _taskAssigneeLabel: ( task: unknown ) => string;
  _heldRowIdsForFiler: ( filer: string ) => string[];
  renderHoldingArea: ( composite: unknown ) => void;
  _setHoldingGroupBy: ( by: string ) => void;
  _holdingAreaGroupBy: string;
};

function newUI(): GroupUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as GroupUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.HOLDING_GROUP_BY_KEY      = "lupin.holdingArea.groupBy";
  ui._holdingAreaGroupBy       = "creator";
  ui._holdingAreaLastComposite = null;
  ui._holdingAreaControlsWired = false;
  ui._taskListAccordionWired   = false;
  return ui;
}

function held( id: string, createdBy: string, owner: string | null ): Record<string, unknown> {
  return { id, title: `row ${ id }`, status: "not_approved", priority: "P2", item_class: "task",
           created_by: createdBy, owner_persona: owner, correlation_key: null, project: "lupin" };
}

// Creator and assignee differ on each row.
const ROWS = (): Array<Record<string, unknown>> => [
  held( "11111111-0000-0000-0000-000000000001", "sam 0e61abe3",      "maria" ),
  held( "11111111-0000-0000-0000-000000000002", "sam 0e61abe3",      "tiberius" ),
  held( "11111111-0000-0000-0000-000000000003", "rachel 1111aaaa",   "maria" ),
  held( "11111111-0000-0000-0000-000000000004", "rachel 1111aaaa",   null ),
  held( "11111111-0000-0000-0000-000000000005", "mr radio 2222bbbb", "mr radio" ),
];

const labels = ( gs: Array<{ filer: string }> ): string[] => gs.map( ( g ) => g.filer );

function togglePageDOM(): void {
  // The real page's toggle block, up to its closing tag.
  const html  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const start = html.indexOf( '<div id="holding-group-toggle"' );
  const end   = html.indexOf( "</div>", start ) + "</div>".length;
  assert.ok( start > 0 && end > start, "notifications.html must carry the toggle above the container" );
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.innerHTML = `<span id="holding-area-count">0</span>` + html.slice( start, end ) + `<div id="holding-area-container"></div>`;
  document.body.appendChild( section );
}

const pressedBy = (): string[] =>
  Array.from( document.querySelectorAll<HTMLElement>( "#holding-group-toggle [data-group-by]" ) )
    .filter( ( b ) => b.getAttribute( "aria-pressed" ) === "true" ).map( ( b ) => b.dataset.groupBy as string );

const shownGroups = (): string[] =>
  Array.from( document.querySelectorAll<HTMLElement>( ".holding-area-group" ) ).map( ( g ) => g.dataset.filer as string );

beforeEach( () => { togglePageDOM(); window.localStorage.clear(); } );

test( "model: creator mode groups on created_by and is what _groupHeldRowsByFiler returns", () => {
  const ui = newUI();
  assert.deepEqual( labels( ui._groupHeldRows( ROWS(), "creator" ) ), [ "Mr Radio", "Rachel", "Sam" ] );
  assert.deepEqual( ui._groupHeldRowsByFiler( ROWS() ), ui._groupHeldRows( ROWS(), "creator" ) );
} );

test( "model: assignee mode groups on owner_persona, a blank owner is Unassigned, totals match", () => {
  const ui = newUI();
  const gs = ui._groupHeldRows( ROWS(), "assignee" );
  assert.deepEqual( labels( gs ), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  assert.deepEqual( gs.map( ( g ) => g.tasks.length ), [ 2, 1, 1, 1 ] );
  assert.deepEqual( labels( ui._groupHeldRows( ROWS(), "bogus" ) ), [ "Mr Radio", "Rachel", "Sam" ] );
} );

test( "model: _taskAssigneeLabel display-cases, strips a session id, defaults to Unassigned", () => {
  const ui = newUI();
  assert.equal( ui._taskAssigneeLabel( { owner_persona: "maria" } ), "Maria" );
  assert.equal( ui._taskAssigneeLabel( { owner_persona: "mr radio" } ), "Mr Radio" );
  assert.equal( ui._taskAssigneeLabel( { owner_persona: "sam 0e61abe3" } ), "Sam" );
  assert.equal( ui._taskAssigneeLabel( { owner_persona: "" } ), "Unassigned" );
  assert.equal( ui._taskAssigneeLabel( null ), "Unassigned" );
} );

test( "pane: first paint is grouped by creator with Creator pressed", () => {
  const ui = newUI();
  ui.renderHoldingArea( { status: "", tasks: ROWS() } );
  assert.deepEqual( shownGroups(), [ "Mr Radio", "Rachel", "Sam" ] );
  assert.deepEqual( pressedBy(), [ "creator" ] );
} );

test( "pane: pressing the REAL Assignee button regroups; Creator returns; the choice is saved", () => {
  const ui = newUI();
  ui.renderHoldingArea( { status: "", tasks: ROWS() } );
  ( document.querySelector( '[data-testid="holding-group-by-assignee"]' ) as HTMLButtonElement ).click();
  assert.deepEqual( shownGroups(), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  assert.deepEqual( pressedBy(), [ "assignee" ] );
  assert.equal( window.localStorage.getItem( "lupin.holdingArea.groupBy" ), "assignee" );
  ( document.querySelector( '[data-testid="holding-group-by-creator"]' ) as HTMLButtonElement ).click();
  assert.deepEqual( shownGroups(), [ "Mr Radio", "Rachel", "Sam" ] );
  assert.deepEqual( pressedBy(), [ "creator" ] );
} );

test( "pane: a saved assignee choice is restored on the next page's first paint", () => {
  window.localStorage.setItem( "lupin.holdingArea.groupBy", "assignee" );
  const ui = newUI();
  ui.renderHoldingArea( { status: "", tasks: ROWS() } );
  assert.deepEqual( shownGroups(), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  assert.deepEqual( pressedBy(), [ "assignee" ] );
} );

test( "pane: an unknown mode or the mode already chosen is ignored", () => {
  const ui = newUI();
  ui.renderHoldingArea( { status: "", tasks: ROWS() } );
  ui._setHoldingGroupBy( "bogus" );
  ui._setHoldingGroupBy( "creator" );
  assert.equal( ui._holdingAreaGroupBy, "creator" );
  assert.equal( window.localStorage.getItem( "lupin.holdingArea.groupBy" ), null );
} );

test( "pane: with storage blocked the toggle still works for this page view", () => {
  const real = Object.getOwnPropertyDescriptor( window, "localStorage" )!;
  const ui   = newUI();
  ui.renderHoldingArea( { status: "", tasks: ROWS() } );
  Object.defineProperty( window, "localStorage", { configurable: true, get() { throw new Error( "blocked" ); } } );
  try {
    ui._setHoldingGroupBy( "assignee" );
    assert.deepEqual( shownGroups(), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  } finally {
    Object.defineProperty( window, "localStorage", real );
  }
} );

test( "pane: Approve all ids in an assignee group are that assignee's rows", () => {
  const ui = newUI();
  ui.renderHoldingArea( { status: "", tasks: ROWS() } );
  ui._setHoldingGroupBy( "assignee" );
  assert.deepEqual( ui._heldRowIdsForFiler( "Maria" ).sort(),
    [ "11111111-0000-0000-0000-000000000001", "11111111-0000-0000-0000-000000000003" ] );
} );
