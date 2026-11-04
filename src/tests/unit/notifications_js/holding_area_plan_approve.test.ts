// Legacy notifications client — PLANS UNDER A FILER (row 451fd70e, replacing the stories strip of row eb235858).
//
// The twin of multiplexer/render/holding_area_plan_approve.test.ts: same fixture shape,
// same assertions, because the two clients share no code and must agree on behaviour.
//
// Harness is the established one (holding_area_panel.test.ts): load the class by slicing
// notifications.js before the DOM-ready init, Object.create the prototype, drive the real
// renderHoldingArea and the real delegated click listener under happy-dom. The only fakes
// are `_transitionTask` (the network) and `refreshHoldingArea`, which re-renders the rows
// the store would still hold.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/holding_area_plan_approve.test.ts

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
type Group = { filer: string; tasks: Row[]; plans: Array<{ key: string; title: string; tasks: Row[]; ids: string[] }>; ungrouped: Row[] };
type PlanUI = Record<string, unknown> & {
  renderHoldingArea: ( composite: unknown ) => void;
  _groupHeldRowsByFiler: ( tasks: unknown, keep?: unknown ) => Group[];
  _holdingPlanId: ( filer: string, key: string ) => string;
  _planTitle: ( key: string ) => string;
  _renderHoldingAreaGroup: ( filer: string, tasks: Row[], plans?: unknown, ungrouped?: unknown ) => string;
  _transitionTask: ( id: string, to: string, extras?: unknown ) => Promise<{ ok: boolean; message?: string }>;
  refreshHoldingArea: () => Promise<void>;
};

function held( id: string, key: string | null, filer = "rachel" ): Row {
  return { id, title: `row ${ id }`, status: "not_approved", item_class: "task", priority: "P2",
           project: "lupin", created_by: `${ filer } 0e61abe3`, correlation_key: key };
}

// The shared fixture, TWO FILERS so a grouping that ignores the filer cannot pass:
//   Rachel: plan-a x3, plan-c x2, plan-s x2, plan-b x1, plan-t x1, and one keyless row x1
//   Sam:    plan-s x2 (the SAME key Rachel holds), plan-t x1 (Rachel holds one too)
const ROWS = (): Row[] => [
  held( "a1", "epic:plan-a" ), held( "a2", "epic:plan-a" ), held( "a3", "epic:plan-a" ),
  held( "b1", "epic:plan-b" ),
  held( "c1", "epic:plan-c" ), held( "c2", "epic:plan-c" ),
  held( "sr1", "epic:plan-s" ), held( "sr2", "epic:plan-s" ),
  held( "tr1", "epic:plan-t" ),
  held( "x1", null ),
  held( "ss1", "epic:plan-s", "sam" ), held( "ss2", "epic:plan-s", "sam" ),
  held( "ts1", "epic:plan-t", "sam" ),
];

const ids = ( rows: Row[] ): unknown[] => rows.map( ( r ) => r.id );

function newUI(): PlanUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as PlanUI;
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
  ui     : PlanUI;
  calls  : Array<{ id: string; to: string; extras: unknown }>;
  plans  : () => string[];
  group  : ( filer: string, key: string ) => HTMLElement;
  button : ( filer: string, key: string ) => HTMLButtonElement;
  status : ( filer: string, key: string ) => string;
  listed : ( filer: string, key: string ) => string[];
  repaint: () => void;
  dropRows: ( key: string ) => void;
  dropRow: ( id: string ) => void;
  restoreRows: ( key: string ) => void;
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
  const group = ( filer: string, key: string ): HTMLElement => {
    const g = Array.from( document.querySelectorAll<HTMLElement>( ".holding-plan-group" ) )
      .find( ( el ) => el.dataset.filer === filer && el.dataset.plan === key );
    assert.ok( g, `no plan group for ${ filer } / ${ key }` );
    return g;
  };
  return {
    ui, calls, repaint, group, gate: () => gate,
    plans : () => Array.from( document.querySelectorAll<HTMLElement>( ".holding-plan-group" ) ).map( ( g ) => `${ g.dataset.filer }/${ g.dataset.plan }` ),
    button: ( f, k ) => group( f, k ).querySelector( ".holding-plan-approve-all" ) as HTMLButtonElement,
    status: ( f, k ) => ( group( f, k ).querySelector( ".holding-plan-status" ) as HTMLElement ).textContent ?? "",
    listed: ( f, k ) => Array.from( group( f, k ).querySelectorAll<HTMLElement>( ".task-verb-select[data-task-id]" ) ).map( ( s ) => s.dataset.taskId as string ),
    dropRows   : ( key ) => { rows = rows.filter( ( r ) => r.correlation_key !== key ); },
    dropRow    : ( id ) => { rows = rows.filter( ( r ) => r.id !== id ); },
    restoreRows: ( key ) => { rows = [ ...rows, ...ROWS().filter( ( r ) => r.correlation_key === key ) ]; },
  };
}

const click  = ( el: Element ): void => { el.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) ); };
// ARM, THEN CONFIRM (row 376dd4cb): a plan runs on the SECOND press of its button.
const press  = ( el: Element ): void => { click( el ); click( el ); };
const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

const RA = [ "Rachel", "epic:plan-a" ] as const;
const RC = [ "Rachel", "epic:plan-c" ] as const;
const RS = [ "Rachel", "epic:plan-s" ] as const;
const SS = [ "Sam", "epic:plan-s" ] as const;

// ───────────────────────────── grouping ─────────────────────────────

test( "grouping: plans are made per filer — two of ONE filer's rows make a plan, one does not, a keyless row never", () => {
  const rachel = newUI()._groupHeldRowsByFiler( ROWS() ).find( ( g ) => g.filer === "Rachel" )!;
  assert.deepEqual( rachel.plans.map( ( p ) => [ p.key, p.ids ] ), [
    [ "epic:plan-a", [ "a1", "a2", "a3" ] ],
    [ "epic:plan-c", [ "c1", "c2" ] ],
    [ "epic:plan-s", [ "sr1", "sr2" ] ],
  ] );
  assert.deepEqual( ids( rachel.ungrouped ), [ "b1", "tr1", "x1" ] );
  assert.equal( rachel.tasks.length, 10, "the filer's own list must still carry EVERY row, grouped or not" );
} );

test( "grouping: a key shared across two filers makes one plan under each, never one merged plan", () => {
  const groups = newUI()._groupHeldRowsByFiler( ROWS() );
  const sam = groups.find( ( g ) => g.filer === "Sam" )!;
  assert.deepEqual( sam.plans.map( ( p ) => [ p.key, p.ids ] ), [ [ "epic:plan-s", [ "ss1", "ss2" ] ] ] );
  assert.deepEqual( groups.find( ( g ) => g.filer === "Rachel" )!.plans.find( ( p ) => p.key === "epic:plan-s" )!.ids, [ "sr1", "sr2" ],
    "Rachel's plan reached a row Sam filed" );
} );

test( "grouping: one row per filer under a shared key is NOT a plan, even though the key is held twice overall", () => {
  const sam = newUI()._groupHeldRowsByFiler( ROWS() ).find( ( g ) => g.filer === "Sam" )!;
  assert.deepEqual( ids( sam.ungrouped ), [ "ts1" ] );
  assert.ok( ! sam.plans.some( ( p ) => p.key === "epic:plan-t" ), "expected: ! sam.plans.some( ( p ) => p.key === 'epic:plan-t' )" );
} );

test( "grouping: epic:unassigned and a blank key are never a plan, beside a real key that is", () => {
  const ui   = newUI();
  const rows = [ held( "u1", "epic:unassigned" ), held( "u2", "epic:unassigned" ),
                 held( "e1", "" ), held( "e2", "" ),
                 held( "r1", "epic:real" ), held( "r2", "epic:real" ) ];
  const g = ui._groupHeldRowsByFiler( rows )[ 0 ]!;
  assert.deepEqual( g.plans.map( ( p ) => p.key ), [ "epic:real" ] );
  assert.deepEqual( ids( g.ungrouped ), [ "e1", "e2", "u1", "u2" ] );
  const kept = ui._groupHeldRowsByFiler( rows, new Set( [ ui._holdingPlanId( "Rachel", "epic:unassigned" ) ] ) )[ 0 ]!;
  assert.deepEqual( kept.plans.map( ( p ) => p.key ), [ "epic:real" ], "a kept report resurrected a plan over epic:unassigned" );
  // and in the pane: two unassigned rows paint no plan
  realPageDOM();
  ui.renderHoldingArea( { status: "", tasks: rows, count: 6, total: 6, has_more: false } );
  assert.deepEqual( Array.from( document.querySelectorAll<HTMLElement>( ".holding-plan-group" ) ).map( ( p ) => p.dataset.plan ), [ "epic:real" ] );
} );

test( "grouping: keep names a plan that stays at ONE row — that filer's, and only that plan", () => {
  const ui     = newUI();
  const groups = ui._groupHeldRowsByFiler( ROWS(), new Set( [ ui._holdingPlanId( "Rachel", "epic:plan-b" ) ] ) );
  const rachel = groups.find( ( g ) => g.filer === "Rachel" )!;
  assert.deepEqual( rachel.plans.map( ( p ) => p.key ), [ "epic:plan-a", "epic:plan-b", "epic:plan-c", "epic:plan-s" ] );
  assert.deepEqual( ids( rachel.ungrouped ), [ "tr1", "x1" ] );
  assert.ok( ! groups.find( ( g ) => g.filer === "Sam" )!.plans.some( ( p ) => p.key === "epic:plan-t" ), "Rachel's kept id kept a plan for Sam" );
} );

test( "grouping: junk in, empty out — and an id-less row cannot join a plan", () => {
  const ui = newUI();
  assert.deepEqual( ui._groupHeldRowsByFiler( null ), [] );
  assert.deepEqual( ui._groupHeldRowsByFiler( "nope" ), [] );
  assert.deepEqual( ui._groupHeldRowsByFiler( [ null, undefined, {} ] ).map( ( g ) => g.plans ), [ [] ] );
  const g = ui._groupHeldRowsByFiler( [ { created_by: "rachel 0e61abe3", correlation_key: "k" }, held( "z1", "k" ) ] )[ 0 ]!;
  assert.deepEqual( g.plans, [], "an id-less row counted toward a plan" );
  assert.equal( g.ungrouped.length, 2 );
} );

test( "title: strips epic:, turns hyphens and underscores to spaces, never blanks a key; two filers' plan ids differ", () => {
  const ui = newUI();
  assert.equal( ui._planTitle( "epic:v022-docs-and-reuse" ), "v022 docs and reuse" );
  assert.equal( ui._planTitle( "epic:" ), "epic:", "a prefix-only key was blanked" );
  assert.equal( ui._planTitle( "a_b--c" ), "a b c" );
  assert.notEqual( ui._holdingPlanId( "Rachel", "epic:plan-s" ), ui._holdingPlanId( "Sam", "epic:plan-s" ) );
} );

// ───────────────────────────── the markup ─────────────────────────────

test( "label: 'Plan: <title>', the raw key only as a tooltip, the count is the rows listed, no 'story' or 'epic' text", () => {
  const ui = newUI();
  const rows = [ held( "m1", "epic:v022-docs-and-reuse" ), held( "m2", "epic:v022-docs-and-reuse" ) ];
  realPageDOM();
  ui.renderHoldingArea( { status: "", tasks: rows, count: 2, total: 2, has_more: false } );
  const g = document.querySelector( ".holding-plan-group" ) as HTMLElement;
  const label = g.querySelector( ".holding-plan-label" ) as HTMLElement;
  assert.equal( label.textContent, "Plan: v022 docs and reuse" );
  assert.equal( label.title, "epic:v022-docs-and-reuse" );
  const headerText = g.querySelector( ".holding-plan-header" )!.textContent ?? "";
  assert.ok( ! /stor(y|ies)|epic/i.test( headerText ), `header text: ${ headerText }` );
  assert.equal( g.querySelector( ".holding-plan-count" )!.textContent, "2" );
} );

test( "markup: collapsed by default, open when asked, chevron and aria-expanded in agreement", () => {
  const ui = newUI();
  const shut = document.createElement( "div" );
  shut.innerHTML = ui._renderHoldingAreaGroup( "Rachel", ROWS(), ui._groupHeldRowsByFiler( ROWS() )[ 0 ]!.plans, [] );
  assert.ok( shut.querySelector( ".holding-plan-group" )!.classList.contains( "collapsed" ), "expected: shut.querySelector( '.holding-plan-group' )!.classList.contains( 'collapsed' )" );
  assert.equal( shut.querySelector( ".holding-plan-header" )!.getAttribute( "aria-expanded" ), "false" );
  assert.equal( shut.querySelector( ".holding-plan-chevron" )!.textContent, "▶" );
  ui._holdingAreaExpandedPlans = new Set( [ ui._holdingPlanId( "Rachel", "epic:plan-a" ) ] );
  const open = document.createElement( "div" );
  open.innerHTML = ui._renderHoldingAreaGroup( "Rachel", ROWS(), ui._groupHeldRowsByFiler( ROWS() )[ 0 ]!.plans, [] );
  const a = open.querySelector( ".holding-plan-group[data-plan='epic:plan-a']" ) as HTMLElement;
  assert.ok( ! a.classList.contains( "collapsed" ), "expected: ! a.classList.contains( 'collapsed' )" );
  assert.equal( a.querySelector( ".holding-plan-header" )!.getAttribute( "aria-expanded" ), "true" );
  assert.equal( a.querySelector( ".holding-plan-chevron" )!.textContent, "▼" );
  assert.ok( open.querySelector( ".holding-plan-group[data-plan='epic:plan-c']" )!.classList.contains( "collapsed" ), "expected: open.querySelector( '.holding-plan-group[data-plan='epic:plan-c']' )!.classList.contains( 'collapsed" );
} );

test( "markup: a group with no plan arguments paints every row in its own table; one with all rows planned paints none", () => {
  const ui = newUI();
  const box = document.createElement( "div" );
  box.innerHTML = ui._renderHoldingAreaGroup( "Rachel", [ held( "p1", "k" ), held( "p2", "k" ) ] );
  assert.equal( box.querySelectorAll( ".holding-plan-group" ).length, 0 );
  assert.equal( box.querySelectorAll( ":scope > .holding-area-group > table" ).length, 1 );
  const g = ui._groupHeldRowsByFiler( [ held( "p1", "k" ), held( "p2", "k" ) ] )[ 0 ]!;
  box.innerHTML = ui._renderHoldingAreaGroup( g.filer, g.tasks, g.plans, g.ungrouped );
  assert.equal( box.querySelectorAll( ":scope > .holding-area-group > table" ).length, 0, "an empty ungrouped table was painted" );
  assert.equal( box.querySelectorAll( ".holding-plan-group" ).length, 1 );
} );

// ───────────────────────────── the pane ─────────────────────────────

test( "pane: one plan per filer per key of two or more of that filer's rows — a shared key is two plans, a single row none", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.deepEqual( h.plans(), [ "Rachel/epic:plan-a", "Rachel/epic:plan-c", "Rachel/epic:plan-s", "Sam/epic:plan-s" ] );
  assert.equal( h.button( ...RA ).textContent, "Approve all 3" );
  assert.equal( h.button( ...RC ).textContent, "Approve all 2" );
} );

test( "pane: the ids on each button equal the rows listed under that plan; a shared key lists each filer's own rows", () => {
  const h = mount( () => ( { ok: true } ) );
  for ( const [ f, k ] of [ RA, RC, RS, SS ] ) assert.equal( h.button( f, k ).dataset.taskIds, h.listed( f, k ).join( "," ), `${ f }/${ k }` );
  assert.deepEqual( h.listed( ...RS ), [ "sr1", "sr2" ] );
  assert.deepEqual( h.listed( ...SS ), [ "ss1", "ss2" ] );
} );

test( "pane: nothing sits above the filer groups", () => {
  mount( () => ( { ok: true } ) );
  const first = ( document.getElementById( "holding-area-container" ) as HTMLElement ).firstElementChild as HTMLElement;
  assert.ok( first.classList.contains( "holding-area-group" ), `the pane opens with ${ first.className }` );
  assert.ok( document.querySelector( ".holding-area-stories, .holding-story-bar" ) === null, "a stories strip was painted" );
} );

test( "toggle: plans start collapsed; a click on the header opens ONLY that plan, a second closes it", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "expected: h.group( ...RA ).classList.contains( 'collapsed' )" );
  const header = h.group( ...RA ).querySelector( ".holding-plan-header" ) as HTMLElement;
  click( header );
  assert.equal( h.group( ...RA ).classList.contains( "collapsed" ), false );
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );
  assert.equal( header.querySelector( ".holding-plan-chevron" )!.textContent, "▼" );
  assert.ok( h.group( ...RC ).classList.contains( "collapsed" ), "opening one plan opened a sibling" );
  assert.ok( h.group( ...SS ).classList.contains( "collapsed" ), "opening Rachel's plan opened Sam's plan of the same key" );
  assert.ok( ( h.group( ...RA ).closest( ".holding-area-group" ) as HTMLElement ).classList.contains( "collapsed" ), "opening a plan opened its filer" );
  click( header );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "expected: h.group( ...RA ).classList.contains( 'collapsed' )" );
  assert.equal( header.getAttribute( "aria-expanded" ), "false" );
  assert.equal( header.querySelector( ".holding-plan-chevron" )!.textContent, "▶" );
} );

test( "toggle: the keyboard opens a plan, and a click on its Approve button never toggles it", () => {
  const h = mount( () => ( { ok: true } ) );
  const header = h.group( ...RA ).querySelector( ".holding-plan-header" ) as HTMLElement;
  const key = ( k: string ): boolean => header.dispatchEvent( new window.KeyboardEvent( "keydown", { key: k, bubbles: true, cancelable: true } ) );
  assert.equal( key( "a" ), true );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "a stray key toggled the plan" );
  assert.equal( key( "Enter" ), false, "Enter on a plan header must be consumed" );
  assert.equal( h.group( ...RA ).classList.contains( "collapsed" ), false );
  click( h.button( ...RA ) );
  assert.equal( h.group( ...RA ).classList.contains( "collapsed" ), false, "pressing Approve folded the plan" );
} );

test( "toggle: a plan opened before the controls were wired still toggles — the open set is created on demand", () => {
  const h = mount( () => ( { ok: true } ) );
  delete h.ui._holdingAreaExpandedPlans;
  click( h.group( ...RC ).querySelector( ".holding-plan-header" ) as HTMLElement );
  assert.equal( h.group( ...RC ).classList.contains( "collapsed" ), false );
  assert.ok( ( h.ui._holdingAreaExpandedPlans as Set<string> ).has( h.ui._holdingPlanId( ...RC ) ), "expected: ( h.ui._holdingAreaExpandedPlans as Set<string> ).has( h.ui._holdingPlanId( ...RC ) )" );
} );

test( "toggle: an open plan survives the repaint, and its open state is forgotten when the plan is gone", () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.group( ...RC ).querySelector( ".holding-plan-header" ) as HTMLElement );
  h.repaint();
  assert.equal( h.group( ...RC ).classList.contains( "collapsed" ), false, "the repaint snapped an open plan shut" );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "expected: h.group( ...RA ).classList.contains( 'collapsed' )" );
  h.dropRows( "epic:plan-c" );
  h.repaint();
  h.restoreRows( "epic:plan-c" );
  h.repaint();
  assert.ok( h.group( ...RC ).classList.contains( "collapsed" ), "a plan that came back kept its old open state" );
} );

test( "filer group: its Approve all still covers EVERY row of that filer, grouped or not, and none of another filer's", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( document.querySelector( ".holding-approve-all[data-filer='Rachel']" ) as HTMLElement );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ).sort(), [ "a1", "a2", "a3", "b1", "c1", "c2", "sr1", "sr2", "tr1", "x1" ].sort() );
} );

test( "click: ONE confirmed press sends one queued transition per row of THAT plan — not its filer's other rows, not the same key under another filer", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( h.button( ...RS ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "sr1", "sr2" ] );
  assert.deepEqual( [ ...new Set( h.calls.map( ( c ) => c.to ) ) ], [ "queued" ] );
  assert.deepEqual( h.calls[ 0 ]?.extras, {}, "approve posted a reason it was never asked for" );
  assert.deepEqual( h.plans(), [ "Rachel/epic:plan-a", "Rachel/epic:plan-c", "Sam/epic:plan-s" ] );
  assert.deepEqual( h.listed( ...SS ), [ "ss1", "ss2" ], "Sam's rows moved with Rachel's plan" );
} );

test( "click: approving a plan leaves the filer's ungrouped rows and the other plans held", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( h.button( ...RA ) );
  await settle();
  const remaining = Array.from( document.querySelectorAll<HTMLElement>( ".holding-area-group[data-filer='Rachel'] .task-verb-select[data-task-id]" ) ).map( ( s ) => s.dataset.taskId );
  assert.deepEqual( remaining.sort(), [ "b1", "c1", "c2", "sr1", "sr2", "tr1", "x1" ].sort() );
} );

test( "a plan that ends PARTLY refused says so, and keeps its header even down to one row", async () => {
  const refusal = "403: actor 'maria' is not in approvers ['rick']";
  const h = mount( ( id ) => id === "a2" ? { ok: false, message: refusal } : { ok: true } );
  press( h.button( ...RA ) );
  await settle();
  assert.deepEqual( h.plans(), [ "Rachel/epic:plan-a", "Rachel/epic:plan-c", "Rachel/epic:plan-s", "Sam/epic:plan-s" ], "the half-approved plan lost its header" );
  assert.equal( h.status( ...RA ), `2 of 3 approved — 1 refused. First refusal: ${ refusal }` );
  assert.equal( h.button( ...RA ).dataset.taskIds, "a2" );
  assert.deepEqual( h.listed( ...RA ), [ "a2" ] );
  assert.equal( h.button( ...RA ).textContent, "Approve all 1" );
  h.repaint();
  assert.match( h.status( ...RA ), /1 refused/, "a repaint erased the partial-failure report" );
  assert.equal( h.status( ...RC ), "", "a report leaked onto a plan that never ran" );
} );

test( "a report on Rachel's plan does not keep Sam's one-row remainder of the same key alive", async () => {
  const h = mount( ( id ) => id === "sr1" ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( ...RS ) );
  await settle();
  assert.match( h.status( ...RS ), /1 refused/ );
  press( h.button( ...SS ) );
  await settle();
  assert.deepEqual( h.plans().filter( ( p ) => p.startsWith( "Sam/" ) ), [], "Sam's fully approved plan stayed on Rachel's report" );
} );

test( "a non-operator is refused on every row: nothing skipped, nothing approved, the plan stays", async () => {
  const h = mount( () => ( { ok: false, message: "403: 'maria' is not an approver" } ) );
  press( h.button( ...RC ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "c1", "c2" ], "the loop stopped at the first refusal" );
  assert.equal( h.status( ...RC ), "0 of 2 approved — 2 refused. First refusal: 403: 'maria' is not an approver" );
  assert.equal( h.plans().length, 4 );
  assert.equal( h.button( ...RC ).disabled, false );
} );

test( "a retry of the refused row clears the report once it succeeds", async () => {
  let refuse = true;
  const h = mount( ( id ) => id === "a2" && refuse ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( ...RA ) );
  await settle();
  assert.match( h.status( ...RA ), /1 refused/ );
  refuse = false;
  press( h.button( ...RA ) );
  await settle();
  assert.ok( ! h.plans().includes( "Rachel/epic:plan-a" ), "expected: ! h.plans().includes( 'Rachel/epic:plan-a' )" );
  h.repaint();
  assert.ok( ! h.plans().includes( "Rachel/epic:plan-a" ), "a stale report resurrected the plan on the next repaint" );
} );

test( "the button is dead while the plan runs, and a press on the rebuilt button is ignored", async () => {
  const h = mount( () => ( { ok: true } ), true );
  const btn = h.button( ...RA );
  press( btn );
  await settle();
  assert.equal( h.calls.length, 1 );
  assert.equal( btn.disabled, true, "the button stayed live mid-run" );
  assert.equal( h.status( ...RA ), "Approved 0 of 3…" );
  // 🔴 THE GUARD IS A SET, NOT THE DISABLED ATTRIBUTE: a poll tick mid-run rebuilds the header
  // and hands the operator a fresh, enabled button, and a press on it must be ignored.
  h.repaint();
  const fresh = h.button( ...RA );
  assert.ok( fresh !== btn, "the repaint did not rebuild the header, so this arm tests nothing" );
  assert.equal( fresh.disabled, false, "precondition: the rebuilt button is live" );
  press( fresh );
  await settle();
  assert.equal( h.calls.length, 1, "a press on the rebuilt button started the plan a second time" );
  h.gate()!.release();
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
} );

test( "the same key under another filer is a different run: its press is NOT blocked by Rachel's run in flight", async () => {
  const h = mount( () => ( { ok: true } ), true );
  press( h.button( ...RS ) );
  await settle();
  assert.equal( h.calls.length, 1 );
  press( h.button( ...SS ) );
  await settle();
  assert.ok( h.calls.some( ( c ) => c.id === "ss1" ), "Sam's plan was treated as the same run as Rachel's" );
  h.gate()!.release();
  await settle();
} );

test( "defensive presses: no ids reports it and posts nothing; no plan key does nothing", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( ...RC );
  btn.dataset.taskIds = "";
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0 );
  assert.equal( h.status( ...RC ), "No rows in this plan." );

  const other = h.button( ...RA );
  delete other.dataset.plan;
  click( other );
  await settle();
  assert.equal( h.calls.length, 0, "a key-less button posted transitions" );

  const idless = h.button( ...RC );
  delete idless.dataset.taskIds;
  click( idless );
  await settle();
  assert.equal( h.calls.length, 0 );
  assert.equal( h.status( ...RC ), "No rows in this plan." );
} );

test( "a report is dropped when its plan leaves the board entirely", async () => {
  const h = mount( ( id ) => id.startsWith( "c" ) ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( ...RC ) );
  await settle();
  assert.match( h.status( ...RC ), /2 refused/ );
  h.dropRows( "epic:plan-c" );
  h.repaint();
  assert.ok( ! h.plans().includes( "Rachel/epic:plan-c" ), "a plan with no rows kept a header on the strength of its report" );
  h.restoreRows( "epic:plan-c" );
  h.repaint();
  assert.equal( h.status( ...RC ), "", "a dead plan's report came back with its key" );
} );

// ───────────────────────── arm, then confirm (row 376dd4cb) ─────────────────────────

test( "arm: the FIRST press posts nothing, names the count on the button and says what the next press does", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( ...RA );
  assert.equal( btn.textContent, "Approve all 3" );
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0, "the first press posted a transition" );
  assert.equal( btn.textContent, "Confirm approve all 3" );
  assert.equal( btn.dataset.armed, "1" );
  assert.ok( btn.classList.contains( "task-submit-armed" ), "expected: btn.classList.contains( 'task-submit-armed' )" );
  assert.equal( h.status( ...RA ), "Click again to approve 3 rows in this plan." );
} );

test( "confirm: the SECOND press runs the plan and the button is back to rest", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( ...RA );
  click( btn );
  click( btn );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  assert.equal( btn.dataset.armed, undefined );
  assert.equal( btn.classList.contains( "task-submit-armed" ), false );
} );

test( "arming one plan disarms the other, and clears the status line of the one it disarmed", () => {
  const h = mount( () => ( { ok: true } ) );
  const a = h.button( ...RA );
  const c = h.button( ...RC );
  click( a );
  click( c );
  assert.equal( c.dataset.armed, "1" );
  assert.equal( a.dataset.armed, undefined, "two plan buttons were armed at once" );
  assert.equal( a.textContent, "Approve all 3" );
  assert.equal( h.status( ...RA ), "" );
  assert.equal( h.calls.length, 0 );
} );

test( "a repaint keeps an armed plan armed while it stays open with the same rows, and the next press confirms it", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( ...RA ) );
  h.repaint();
  const fresh = h.button( ...RA );
  assert.equal( fresh.dataset.armed, "1", "a repaint disarmed a plan that is still open" );
  assert.ok( fresh.classList.contains( "task-submit-armed" ) );
  assert.equal( fresh.textContent, "Confirm approve all 3" );
  assert.equal( h.status( ...RA ), "Click again to approve 3 rows in this plan." );
  assert.ok( ! h.group( ...RA ).classList.contains( "collapsed" ), "the repaint shut the armed plan" );
  assert.equal( h.calls.length, 0, "a repaint posted" );
  click( fresh );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ], "the press after a repaint did not confirm the armed plan" );
} );

test( "a repaint does not re-arm a plan whose rows changed, or one that left the board and came back", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( ...RA ) );
  h.dropRow( "a3" );
  h.repaint();
  assert.equal( h.button( ...RA ).dataset.armed, undefined, "an arm survived a change of the rows it was armed for" );
  assert.equal( h.button( ...RA ).textContent, "Approve all 2" );
  assert.equal( h.status( ...RA ), "" );
  click( h.button( ...RC ) );
  h.dropRows( "epic:plan-c" );
  h.repaint();
  h.restoreRows( "epic:plan-c" );
  h.repaint();
  assert.equal( h.button( ...RC ).dataset.armed, undefined, "an arm survived its plan leaving the board" );
  assert.equal( h.button( ...RC ).textContent, "Approve all 2" );
  click( h.button( ...RC ) );
  await settle();
  assert.equal( h.calls.length, 0, "a press after the plan came back approved it instead of arming it" );
} );

test( "after a repaint only the plan armed last is armed, and closing it disarms it for good", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( ...RA ) );
  click( h.button( ...RC ) );
  h.repaint();
  assert.equal( h.button( ...RA ).dataset.armed, undefined, "two plans were armed after a repaint" );
  assert.equal( h.button( ...RC ).dataset.armed, "1" );
  click( h.group( ...RC ).querySelector( ".holding-plan-header" ) as HTMLElement );
  h.repaint();
  assert.equal( h.button( ...RC ).dataset.armed, undefined, "a repaint re-armed a plan the operator had closed" );
  assert.equal( h.button( ...RC ).textContent, "Approve all 2" );
} );

test( "disarming tolerates an armed header whose attributes were stripped", () => {
  const h = mount( () => ( { ok: true } ) );
  const stray = h.button( ...RA );
  stray.dataset.armed = "1";
  delete stray.dataset.plan;
  delete stray.dataset.taskIds;
  click( h.button( ...RC ) );
  assert.equal( h.button( ...RC ).dataset.armed, "1" );
  assert.equal( stray.dataset.armed, undefined );
  assert.equal( stray.textContent, "Approve all 0" );
  assert.equal( h.calls.length, 0 );
} );

test( "arm: the FIRST press OPENS the closed plan, so its rows are on screen before the confirming press; only that plan opens", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "precondition: the plan starts closed" );
  click( h.button( ...RA ) );
  assert.ok( ! h.group( ...RA ).classList.contains( "collapsed" ), "arming did not open the plan" );
  const header = h.group( ...RA ).querySelector( ".holding-plan-header" ) as HTMLElement;
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );
  assert.equal( header.querySelector( ".holding-plan-chevron" )!.textContent, "▼" );
  assert.ok( h.group( ...RC ).classList.contains( "collapsed" ), "arming one plan opened a sibling" );
  assert.ok( h.group( ...SS ).classList.contains( "collapsed" ), "arming opened another filer's plan of the same key" );
  assert.equal( h.calls.length, 0, "arming posted" );
  h.repaint();
  assert.ok( ! h.group( ...RA ).classList.contains( "collapsed" ), "the repaint shut the plan the operator is about to approve" );
} );


// ───────────── closing a plan disarms its Approve all (bug e848467a) ─────────────

const planHeader = ( h: Harness, f: string, k: string ): HTMLElement => h.group( f, k ).querySelector( ".holding-plan-header" ) as HTMLElement;

test( "close: closing an armed plan disarms it and clears its line, and the next press arms again instead of approving", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( ...RA );
  click( btn );
  assert.equal( btn.dataset.armed, "1", "precondition: the first press armed the plan" );
  click( planHeader( h, ...RA ) );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "precondition: the header click closed the plan" );
  assert.equal( btn.dataset.armed, undefined, "closing the plan left its Approve all armed" );
  assert.equal( btn.classList.contains( "task-submit-armed" ), false );
  assert.equal( btn.textContent, "Approve all 3" );
  assert.equal( h.status( ...RA ), "" );
  click( planHeader( h, ...RA ) );
  assert.equal( h.button( ...RA ).dataset.armed, undefined, "reopening showed an armed button" );
  click( h.button( ...RA ) );
  await settle();
  assert.equal( h.calls.length, 0, "one press after a close and a reopen approved the plan" );
  assert.equal( h.button( ...RA ).dataset.armed, "1" );
} );

test( "close: the keyboard closes an armed plan the same way", () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( ...RA ) );
  planHeader( h, ...RA ).dispatchEvent( new window.KeyboardEvent( "keydown", { key: "Enter", bubbles: true, cancelable: true } ) );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "precondition: Enter closed the plan" );
  assert.equal( h.button( ...RA ).dataset.armed, undefined );
  assert.equal( h.status( ...RA ), "" );
} );

test( "close: opening or closing any OTHER plan leaves an armed plan armed, and so does opening it", () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( ...RA ) );
  click( planHeader( h, ...RC ) );
  click( planHeader( h, ...SS ) );
  click( planHeader( h, ...RC ) );
  click( planHeader( h, ...SS ) );
  assert.equal( h.button( ...RA ).dataset.armed, "1", "toggling a sibling disarmed the armed plan" );
  assert.equal( h.button( ...RA ).textContent, "Confirm approve all 3" );
  assert.equal( h.status( ...RA ), "Click again to approve 3 rows in this plan." );
  assert.ok( ! h.group( ...RA ).classList.contains( "collapsed" ), "the armed plan was shut" );
} );

test( "close: closing an unarmed plan changes nothing about it", () => {
  const h = mount( () => ( { ok: true } ) );
  click( planHeader( h, ...RA ) );
  click( planHeader( h, ...RA ) );
  assert.equal( h.button( ...RA ).textContent, "Approve all 3" );
  assert.equal( h.button( ...RA ).dataset.armed, undefined );
  assert.equal( h.status( ...RA ), "" );
} );
