// Legacy notifications client — APPROVE A WHOLE STORY (row eb235858).
//
// The twin of multiplexer/render/holding_area_story_approve.test.ts: same fixture shape,
// same assertions, because the two clients share no code and must agree on behaviour.
//
// Harness is the established one (holding_area_panel.test.ts): load the class by slicing
// notifications.js before the DOM-ready init, Object.create the prototype, drive the real
// renderHoldingArea and the real delegated click listener under happy-dom. The only fakes
// are `_transitionTask` (the network) and `refreshHoldingArea`, which re-renders the rows
// the store would still hold.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/holding_area_story_approve.test.ts

import { test, before } from "node:test";
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

type Row = Record<string, unknown>;
type StoryUI = Record<string, unknown> & {
  renderHoldingArea: ( composite: unknown ) => void;
  _groupHeldRowsByStory: ( tasks: unknown, keep?: unknown ) => Array<{ key: string; ids: string[] }>;
  _renderHoldingStories: ( stories: unknown ) => string;
  _transitionTask: ( id: string, to: string, extras?: unknown ) => Promise<{ ok: boolean; message?: string }>;
  refreshHoldingArea: () => Promise<void>;
};

function held( id: string, key: string | null, filer = "rachel" ): Row {
  return { id, title: `row ${ id }`, status: "not_approved", item_class: "task", priority: "P2",
           project: "lupin", created_by: `${ filer } 0e61abe3`, correlation_key: key };
}

// Story A has THREE rows, story C TWO, story B ONE, and one row has no key at all.
const ROWS = (): Row[] => [
  held( "a1", "epic:plan-a" ), held( "a2", "epic:plan-a" ), held( "a3", "epic:plan-a" ),
  held( "b1", "epic:plan-b" ),
  held( "c1", "epic:plan-c" ), held( "c2", "epic:plan-c" ),
  held( "x1", null ),
];

function newUI(): StoryUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as StoryUI;
  ui.debug = false; ui.log = (): void => {}; ui.error = (): void => {};
  ui._taskListFetchInFlight = false; ui._holdingAreaFetchInFlight = false;
  ui._taskListLastGoodTasks = null; ui.queueSessionId = "test-session";
  ui._holdingAreaControlsWired = false; ui._taskListAccordionWired = false;
  // The constructor is skipped, so its constants are absent. Read the real one out of the
  // source rather than retyping it here, or the test would agree with itself.
  const m = readFileSync( NOTIFICATIONS_JS, "utf8" ).match( /this\.EPIC_UNASSIGNED_KEY\s*=\s*'([^']+)'/ );
  assert.ok( m, "the constructor no longer defines EPIC_UNASSIGNED_KEY" );
  ui.EPIC_UNASSIGNED_KEY = m[ 1 ];
  return ui;
}

function realPageDOM(): void {
  document.body.innerHTML = `
    <div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div>
    </div>
    <div class="collapsible-section" id="section-holding-area">
      <div class="section-content" id="holding-area-section"><div id="holding-area-container"></div></div>
    </div>`;
}

interface Harness {
  ui     : StoryUI;
  calls  : Array<{ id: string; to: string; extras: unknown }>;
  bars   : () => string[];
  button : ( key: string ) => HTMLButtonElement;
  status : ( key: string ) => string;
  repaint: () => void;
  dropKey: ( key: string ) => void;
  restoreKey: ( key: string ) => void;
  gate   : () => { release(): void } | null;
}

function mount( verdict: ( id: string ) => { ok: boolean; message?: string }, hold = false ): Harness {
  const ui = newUI();
  let rows = ROWS();
  const calls: Harness[ "calls" ] = [];
  let gate: { release(): void } | null = null;
  realPageDOM();
  const repaint = (): void => ui.renderHoldingArea( { status: "", tasks: rows, count: rows.length, total: rows.length, has_more: false } );
  ui.refreshHoldingArea = async () => { repaint(); };
  ui._transitionTask = async ( id, to, extras ) => {
    calls.push( { id, to, extras } );
    if ( hold && calls.length === 1 ) await new Promise<void>( ( r ) => { gate = { release: r }; } );
    const v = verdict( id );
    if ( v.ok ) rows = rows.filter( ( r ) => r.id !== id );
    return v;
  };
  repaint();
  const bar = ( key: string ): HTMLElement => {
    const b = Array.from( document.querySelectorAll<HTMLElement>( ".holding-story-bar" ) ).find( ( el ) => el.dataset.story === key );
    assert.ok( b, `no story bar for ${ key }` );
    return b;
  };
  return {
    ui, calls, repaint, gate: () => gate,
    bars  : () => Array.from( document.querySelectorAll<HTMLElement>( ".holding-story-bar" ) ).map( ( b ) => b.dataset.story as string ),
    button: ( key ) => bar( key ).querySelector( ".holding-story-approve-all" ) as HTMLButtonElement,
    status: ( key ) => ( bar( key ).querySelector( ".holding-story-status" ) as HTMLElement ).textContent ?? "",
    dropKey: ( key ) => { rows = rows.filter( ( r ) => r.correlation_key !== key ); },
    restoreKey: ( key ) => { rows = [ ...rows, ...ROWS().filter( ( r ) => r.correlation_key === key ) ]; },
  };
}

const click  = ( el: Element ): void => { el.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) ); };
// ARM, THEN CONFIRM (row 376dd4cb): a story runs on the SECOND press of its button.
const press  = ( el: Element ): void => { click( el ); click( el ); };
const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

// ───────────────────────────── grouping ─────────────────────────────

test( "grouping: two rows make a story, ONE row does not, a keyless row never does", () => {
  const ui = newUI();
  assert.deepEqual( ui._groupHeldRowsByStory( ROWS() ), [
    { key: "epic:plan-a", ids: [ "a1", "a2", "a3" ] },
    { key: "epic:plan-c", ids: [ "c1", "c2" ] },
  ] );
} );

test( "grouping: epic:unassigned is never a story, beside a real key that is", () => {
  const ui = newUI();
  const rows = [ held( "u1", "epic:unassigned" ), held( "u2", "epic:unassigned" ),
                 held( "r1", "epic:real" ), held( "r2", "epic:real" ) ];
  assert.deepEqual( ui._groupHeldRowsByStory( rows ), [ { key: "epic:real", ids: [ "r1", "r2" ] } ] );
  assert.deepEqual( ui._groupHeldRowsByStory( rows, new Set( [ "epic:unassigned" ] ) ).map( ( s ) => s.key ),
    [ "epic:real" ], "a kept report resurrected a bar over epic:unassigned" );
  // and in the pane: two unassigned rows paint no bar
  realPageDOM();
  ui.renderHoldingArea( { status: "", tasks: rows, count: 4, total: 4, has_more: false } );
  const bars = Array.from( document.querySelectorAll<HTMLElement>( ".holding-story-bar" ) ).map( ( b ) => b.dataset.story );
  assert.deepEqual( bars, [ "epic:real" ] );
} );

test( "grouping: keep names a key that stays at ONE row, and only that key", () => {
  const ui = newUI();
  const stories = ui._groupHeldRowsByStory( ROWS(), new Set( [ "epic:plan-b" ] ) );
  assert.deepEqual( stories.map( ( s ) => s.key ), [ "epic:plan-a", "epic:plan-b", "epic:plan-c" ] );
  assert.deepEqual( stories[ 1 ], { key: "epic:plan-b", ids: [ "b1" ] } );
} );

test( "grouping: junk in, empty out — and an id-less row cannot join a story", () => {
  const ui = newUI();
  assert.deepEqual( ui._groupHeldRowsByStory( null ), [] );
  assert.deepEqual( ui._groupHeldRowsByStory( "nope" ), [] );
  assert.deepEqual( ui._groupHeldRowsByStory( [ null, undefined, {} ] ), [] );
  assert.deepEqual( ui._groupHeldRowsByStory( [ { correlation_key: "k" }, { id: "z1", correlation_key: "k" } ] ), [] );
  assert.equal( ui._renderHoldingStories( [] ), "" );
  assert.equal( ui._renderHoldingStories( null ), "" );
} );

// ───────────────────────────── the pane ─────────────────────────────

test( "pane: one bar per story of two or more rows, labelled with N, none for the single-row key", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.deepEqual( h.bars(), [ "epic:plan-a", "epic:plan-c" ] );
  assert.equal( h.button( "epic:plan-a" ).textContent, "Approve all 3 in this story" );
  assert.equal( h.button( "epic:plan-c" ).textContent, "Approve all 2 in this story" );
  assert.equal( h.button( "epic:plan-a" ).dataset.taskIds, "a1,a2,a3" );
} );

test( "click: ONE press sends one queued transition per row of THAT story and no other row", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( h.button( "epic:plan-a" ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  assert.deepEqual( [ ...new Set( h.calls.map( ( c ) => c.to ) ) ], [ "queued" ] );
  assert.deepEqual( h.calls[ 0 ]?.extras, {} );
  assert.deepEqual( h.bars(), [ "epic:plan-c" ] );
} );

test( "a story that ends PARTLY refused says so, and keeps its bar even down to one row", async () => {
  const refusal = "403: actor 'maria' is not in approvers ['rick']";
  const h = mount( ( id ) => id === "a2" ? { ok: false, message: refusal } : { ok: true } );
  press( h.button( "epic:plan-a" ) );
  await settle();

  assert.deepEqual( h.bars(), [ "epic:plan-a", "epic:plan-c" ], "the half-approved story lost its bar" );
  assert.equal( h.status( "epic:plan-a" ), `2 of 3 approved — 1 refused. First refusal: ${ refusal }` );
  assert.equal( h.button( "epic:plan-a" ).dataset.taskIds, "a2" );
  assert.equal( h.button( "epic:plan-a" ).textContent, "Approve all 1 in this story" );

  h.repaint();                               // the 60s poll
  assert.match( h.status( "epic:plan-a" ), /1 refused/, "the poll erased the partial-failure report" );
  assert.equal( h.status( "epic:plan-c" ), "", "a report leaked onto a story that never ran" );
} );

test( "a non-operator is refused on every row: nothing skipped, nothing approved, the bar stays", async () => {
  const h = mount( () => ( { ok: false, message: "403: 'maria' is not an approver" } ) );
  press( h.button( "epic:plan-c" ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "c1", "c2" ], "the loop stopped at the first refusal" );
  assert.equal( h.status( "epic:plan-c" ), "0 of 2 approved — 2 refused. First refusal: 403: 'maria' is not an approver" );
  assert.deepEqual( h.bars(), [ "epic:plan-a", "epic:plan-c" ] );
  assert.equal( h.button( "epic:plan-c" ).disabled, false );
} );

test( "a retry of the refused row clears the report once it succeeds", async () => {
  let refuse = true;
  const h = mount( ( id ) => id === "a2" && refuse ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( "epic:plan-a" ) );
  await settle();
  assert.match( h.status( "epic:plan-a" ), /1 refused/ );

  refuse = false;
  press( h.button( "epic:plan-a" ) );
  await settle();
  assert.deepEqual( h.bars(), [ "epic:plan-c" ] );
  h.repaint();
  assert.deepEqual( h.bars(), [ "epic:plan-c" ], "a stale report resurrected the bar on the next poll" );
} );

test( "the button is dead while the story runs", async () => {
  const h = mount( () => ( { ok: true } ), true );
  const btn = h.button( "epic:plan-a" );
  press( btn );
  await settle();
  assert.equal( h.calls.length, 1 );
  assert.equal( btn.disabled, true, "the button stayed live mid-run" );
  assert.equal( h.status( "epic:plan-a" ), "Approved 0 of 3…" );

  // 🔴 THE GUARD IS A SET, NOT THE DISABLED ATTRIBUTE: a poll tick mid-run rebuilds the bar
  // and hands the operator a fresh, enabled button, and a press on it must be ignored.
  h.repaint();
  const fresh = h.button( "epic:plan-a" );
  assert.notEqual( fresh, btn, "the repaint did not rebuild the bar, so this arm tests nothing" );
  assert.equal( fresh.disabled, false, "precondition: the rebuilt button is live" );
  press( fresh );
  await settle();
  assert.equal( h.calls.length, 1, "a press on the rebuilt button started the story a second time" );

  h.gate()!.release();
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
} );

test( "defensive presses: no ids reports it and posts nothing; no story key does nothing", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( "epic:plan-c" );
  btn.dataset.taskIds = "";
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0 );
  assert.equal( h.status( "epic:plan-c" ), "No rows in this story." );

  const other = h.button( "epic:plan-a" );
  delete other.dataset.story;
  click( other );
  await settle();
  assert.equal( h.calls.length, 0, "a key-less button posted transitions" );
} );

test( "a report is dropped when its story leaves the board entirely", async () => {
  const h = mount( ( id ) => id.startsWith( "c" ) ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( "epic:plan-c" ) );
  await settle();
  assert.match( h.status( "epic:plan-c" ), /2 refused/ );

  h.dropKey( "epic:plan-c" );
  h.repaint();
  assert.deepEqual( h.bars(), [ "epic:plan-a" ], "a story with no rows kept a bar on the strength of its report" );

  h.restoreKey( "epic:plan-c" );             // the same key returns later as a NEW story
  h.repaint();
  assert.equal( h.status( "epic:plan-c" ), "", "a dead story's report came back with its key" );
} );

// ───────────────────────── arm, then confirm (row 376dd4cb) ─────────────────────────

test( "arm: the FIRST press posts nothing, names the count on the button and says what the next press does", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( "epic:plan-a" );
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0, "the first press posted a transition" );
  assert.equal( btn.textContent, "Confirm approve all 3 in this story" );
  assert.equal( btn.dataset.armed, "1" );
  assert.ok( btn.classList.contains( "task-submit-armed" ), "an armed button carries the armed class" );
  assert.equal( h.status( "epic:plan-a" ), "Click again to approve 3 rows in this story." );
} );

test( "confirm: the SECOND press runs the story and the button is back to rest", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( "epic:plan-a" );
  click( btn );
  click( btn );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  assert.equal( btn.dataset.armed, undefined, "the button stayed armed after it ran" );
  assert.equal( btn.classList.contains( "task-submit-armed" ), false );
} );

test( "arming one story disarms the other, and clears the status line of the one it disarmed", () => {
  const h = mount( () => ( { ok: true } ) );
  const a = h.button( "epic:plan-a" );
  const c = h.button( "epic:plan-c" );
  click( a );
  click( c );
  assert.equal( c.dataset.armed, "1" );
  assert.equal( a.dataset.armed, undefined, "two story buttons were armed at once" );
  assert.equal( a.textContent, "Approve all 3 in this story" );
  assert.equal( h.status( "epic:plan-a" ), "", "a disarmed story kept its 'Click again' line" );
  assert.equal( h.calls.length, 0 );
} );

test( "a repaint rebuilds the bar unarmed, and the armed status line does not outlive the arming", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( "epic:plan-a" ) );
  h.repaint();
  const fresh = h.button( "epic:plan-a" );
  assert.equal( fresh.dataset.armed, undefined );
  assert.equal( fresh.textContent, "Approve all 3 in this story" );
  assert.equal( h.status( "epic:plan-a" ), "" );
  click( fresh );
  await settle();
  assert.equal( h.calls.length, 0, "a press after a repaint ran the story instead of arming it" );
} );

test( "disarming tolerates an armed bar whose attributes were stripped", () => {
  const h = mount( () => ( { ok: true } ) );
  const stray = h.button( "epic:plan-a" );
  stray.dataset.armed = "1";
  delete stray.dataset.story;
  delete stray.dataset.taskIds;
  const c = h.button( "epic:plan-c" );
  click( c );
  assert.equal( c.dataset.armed, "1", "the real press did not arm" );
  assert.equal( stray.dataset.armed, undefined );
  assert.equal( stray.textContent, "Approve all 0 in this story" );
  assert.equal( h.calls.length, 0 );
} );
