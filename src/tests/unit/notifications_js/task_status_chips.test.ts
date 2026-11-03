// The status chips on the notifications client's live task list.
//
// The shared module publishes itself: happy-dom is registered before the import, so the
// module's own window arm runs. Nothing here assigns that global by hand, so a broken
// bridge fails this file instead of being hidden by the harness.
//
// Harness mirrors task_lookup_panel.test.ts: slice notifications.js before its DOM-ready
// init, Object.create the prototype to skip the constructor, set only the fields read.
//
// Run: npx tsx --test src/tests/unit/notifications_js/task_status_chips.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Row = { id: string; title: string; status: string; owner_persona: string; priority: string; item_class: string };
type UI  = {
  _taskStatusChips: string[];
  _taskListLastGoodTasks: Row[] | null;
  _taskLookupPinned: Row | null;
  renderTaskList: ( composite: unknown, stamp?: boolean ) => void;
  renderTaskStatusChips: () => void;
  toggleTaskStatusChip: ( key: string ) => void;
  clearTaskStatusChips: () => void;
  filterTasksByStatusChips: ( tasks: Row[] ) => Row[];
  clearTaskLookup: () => void;
};

before( async () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  await import( "../../../lupin_app/static/js/shared/task-status-filter.js" );

  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS },
  );
} );

function row( id: string, status: string ): Row {
  return { id, title: `Title ${ id }`, status, owner_persona: "Rio", priority: "P2", item_class: "task" };
}
const PARKED  = row( "pk", "parked" );
const BLOCKED = row( "bl", "blocked" );
const ACTIVE  = row( "ip", "in_progress" );
const QUEUED  = row( "qu", "queued" );
const CLAIMED = row( "cl", "claimed" );
const REVIEW  = row( "rv", "review" );
const DONE    = row( "dn", "done" );
const BOARD   = [ PARKED, BLOCKED, ACTIVE, QUEUED, CLAIMED, REVIEW, DONE ];

function newUI(): UI {
  const Ctor = ( globalThis as never as { NotificationsUI: { prototype: object } } ).NotificationsUI;
  const ui   = Object.create( Ctor.prototype ) as UI & Record<string, unknown>;
  ui.log                         = () => {};
  ui._taskStatusChips            = [];
  ui._taskListLastGoodTasks      = null;
  ui._taskLookupPinned           = null;
  ui._taskListAccordionWired     = true;
  ui._taskListPressInFlight      = false;
  ui._renderTaskListTruncationBanner = () => "";
  ui._paintTaskListNotices       = () => {};
  ui._captureOperatorState       = () => ( {} );
  ui._restoreOperatorState       = () => {};
  ui._hydrateRequestChips        = () => {};
  ui._stampTaskListUpdated       = () => {};
  ui._wireTaskListAccordion      = () => {};
  ui.loadCollapsedTaskOwners     = () => new Set();
  return ui;
}

function buildDOM( withChips = true ): void {
  document.body.innerHTML = `
    <span id="task-list-count"></span>
    ${ withChips ? `<div id="task-status-chips"></div>` : "" }
    <div id="task-list-container"></div>`;
}

const bodyText = () => document.getElementById( "task-list-container" )!.textContent || "";
const pressed  = () => Array.from( document.querySelectorAll( "#task-status-chips button" ) )
  .filter( ( b ) => b.getAttribute( "aria-pressed" ) === "true" ).map( ( b ) => b.getAttribute( "data-chip" ) );
const chip     = ( key: string ) => document.querySelector( `[data-testid="task-status-chip-${ key }"]` ) as HTMLElement;

beforeEach( () => { buildDOM(); } );

test( "the module published itself (nothing in this file assigns the global)", () => {
  const published = ( window as never as { LUPIN_TASK_STATUS_FILTER?: { TASK_STATUS_CHIPS: unknown[] } } ).LUPIN_TASK_STATUS_FILTER;
  assert.ok( published );
  assert.equal( published.TASK_STATUS_CHIPS.length, 4 );
} );

test( "the default view is All: every open row, All pressed, no chip pressed", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  assert.deepEqual( pressed(), [ "all" ] );
  for ( const t of [ "Title pk", "Title bl", "Title ip", "Title qu", "Title cl", "Title rv" ] ) assert.match( bodyText(), new RegExp( t ) );
  assert.doesNotMatch( bodyText(), /Title dn/, "a terminal row never shows, chips or not" );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 6" );
} );

test( "the bar is drawn once: All plus the four chips, in order", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  const first = Array.from( document.querySelectorAll( "#task-status-chips button" ) );
  assert.deepEqual( first.map( ( b ) => b.textContent ), [ "All", "Parked", "Blocked", "In progress", "Queued" ] );
  ui.renderTaskList( { tasks: BOARD } );
  const second = Array.from( document.querySelectorAll( "#task-status-chips button" ) );
  assert.ok( first.every( ( b, i ) => b === second[ i ] ), "a repaint must reuse the same buttons" );
} );

test( "each chip alone shows only its own rows", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  const expected: Record<string, string[]> = {
    parked      : [ "Title pk" ],
    blocked     : [ "Title bl" ],
    queued      : [ "Title qu" ],
    in_progress : [ "Title ip", "Title cl", "Title rv" ],   // claimed + review: provisional until Rick rules
  };
  for ( const key of Object.keys( expected ) ) {
    ui.clearTaskStatusChips();
    chip( key ).click();
    assert.deepEqual( pressed(), [ key ] );
    for ( const title of [ "pk", "bl", "ip", "qu", "cl", "rv" ].map( ( s ) => `Title ${ s }` ) ) {
      const should = expected[ key ].includes( title );
      assert.equal( new RegExp( title ).test( bodyText() ), should, `${ key }: ${ title } should ${ should ? "" : "not " }show` );
    }
  }
} );

test( "a union shows both chips' rows and the count follows the shown rows (a parked row with no chase time counts live)", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  chip( "blocked" ).click();
  chip( "queued" ).click();
  assert.deepEqual( pressed(), [ "blocked", "queued" ] );
  assert.match( bodyText(), /Title bl/ );
  assert.match( bodyText(), /Title qu/ );
  assert.doesNotMatch( bodyText(), /Title pk|Title ip/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 2" );
} );

test( "all four selected is the All view, and the bar says All", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  const allView = bodyText();
  for ( const key of [ "parked", "blocked", "in_progress", "queued" ] ) chip( key ).click();
  assert.deepEqual( pressed(), [ "all" ] );
  assert.deepEqual( ui._taskStatusChips, [] );
  assert.equal( bodyText(), allView );
} );

test( "clearing the last chip returns to All, never an empty list", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  chip( "parked" ).click();
  assert.doesNotMatch( bodyText(), /Title bl/ );
  chip( "parked" ).click();
  assert.deepEqual( pressed(), [ "all" ] );
  assert.match( bodyText(), /Title bl/ );
  assert.match( bodyText(), /Title qu/ );
} );

test( "the All button drops every chip", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  chip( "blocked" ).click();
  chip( "queued" ).click();
  chip( "all" ).click();
  assert.deepEqual( pressed(), [ "all" ] );
  assert.deepEqual( ui._taskStatusChips, [] );
  assert.match( bodyText(), /Title pk/ );
} );

test( "a chip with no matching rows says so and offers All, not a blank list", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: [ QUEUED ] } );
  chip( "parked" ).click();
  const msg = document.querySelector( "[data-testid=\"task-status-filter-empty\"]" );
  assert.ok( msg );
  assert.match( msg.textContent || "", /press All/ );
  chip( "all" ).click();
  assert.match( bodyText(), /Title qu/ );
} );

test( "a chip never removes rows from the replay held for an outage or the lookup's ✕", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  chip( "parked" ).click();
  assert.equal( ui._taskListLastGoodTasks!.length, 6, "the held list stays whole" );
} );

test( "the chips compose with the find-by-id lookup: a pinned row shows whatever the chips say, and ✕ returns to the chip view", () => {
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  chip( "blocked" ).click();
  ui._taskLookupPinned = QUEUED;
  document.body.insertAdjacentHTML( "beforeend",
    `<input id="task-lookup-input" value="qu"><div id="task-lookup-result"></div><button id="task-lookup-clear"></button>` );
  ui.renderTaskList( { tasks: ui._taskListLastGoodTasks }, false );
  assert.match( bodyText(), /Title qu/, "the pinned row shows although Queued is not selected" );
  assert.doesNotMatch( bodyText(), /Title bl/ );
  assert.deepEqual( pressed(), [ "blocked" ], "the chips keep their selection while a row is pinned" );
  ui.clearTaskLookup();
  assert.match( bodyText(), /Title bl/, "after ✕ the chip view returns" );
  assert.doesNotMatch( bodyText(), /Title qu/ );
  assert.deepEqual( pressed(), [ "blocked" ] );
} );

test( "a missing shared module shows All and draws no bar (never an empty list)", () => {
  const w     = window as never as { LUPIN_TASK_STATUS_FILTER?: unknown };
  const saved = w.LUPIN_TASK_STATUS_FILTER;
  delete w.LUPIN_TASK_STATUS_FILTER;
  try {
    const ui = newUI();
    ui.renderTaskList( { tasks: BOARD } );
    assert.equal( document.querySelectorAll( "#task-status-chips button" ).length, 0 );
    assert.match( bodyText(), /Title qu/ );
    ui.toggleTaskStatusChip( "queued" );   // a no-op, not a throw
    assert.deepEqual( ui._taskStatusChips, [] );
    assert.deepEqual( ui.filterTasksByStatusChips( BOARD ), BOARD );
  } finally {
    w.LUPIN_TASK_STATUS_FILTER = saved;
  }
} );

test( "a page without the chip host still renders the list", () => {
  buildDOM( false );
  const ui = newUI();
  ui.renderTaskList( { tasks: BOARD } );
  assert.match( bodyText(), /Title qu/ );
} );

test( "a repaint before any fetch has rows paints from an empty held list", () => {
  const ui = newUI();
  ui.toggleTaskStatusChip( "queued" );
  assert.match( bodyText(), /No open tasks/ );
  ui.clearTaskStatusChips();
  assert.match( bodyText(), /No open tasks/ );
} );

