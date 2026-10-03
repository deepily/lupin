// Holding-area card — PLANS UNDER A FILER (row 451fd70e, replacing the stories strip of row eb235858).
//
// Rows a plan import files share one `correlation_key`. Inside ONE filer's group, the rows that
// share a key sit under a "Plan: <title>" sub-header that opens and closes like the filer group
// and carries its own "Approve all N". Nothing sits above the filer groups. Driven at the layer
// the operator's click enters at: the REAL renderer, mounted into a REAL element, painting
// through the REAL template, clicking the REAL button. The store is the only fake.
//
// ⚠️ NO NEW SERVER DOOR. The control is a loop of ordinary single-row transitions, so
// "operator-only" is the server's per-row rule, unchanged. The refusal test below feeds the loop
// what a non-operator's session earns — a 403 per row — and asserts that nothing is silently
// skipped and that the plan stays for a retry.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import {
  groupHeldRowsByFiler,
  holdingPlanId,
  planTitle,
} from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import { HOLDING_BATCH_ARMED_CLASS, HOLDING_BATCH_NO_ROWS_PLAN } from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch";
import {
  holdingPlanApproveLabel,
  holdingPlanApproveTitle,
  renderHoldingAreaGroups,
  renderHoldingPlanGroup,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/holdingAreaTable";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

// A pane left mounted by a test that failed before its own unmount keeps timers alive, and the
// runner then hangs on the first red instead of reporting it. Every harness is torn down here.
const mounted: Array<() => void> = [];
afterEach( () => { for ( const unmount of mounted.splice( 0 ) ) unmount(); } );

function held( id: string, key: string | null, filer = "rachel" ): TaskItem {
  return {
    id, title: `row ${ id }`, status: "not_approved", priority: "P2",
    created_by: `${ filer } 0e61abe3`, correlation_key: key,
  } as unknown as TaskItem;
}

// The shared fixture, TWO FILERS so a grouping that ignores the filer cannot pass:
//   Rachel: plan-a x3, plan-c x2, plan-s x2, plan-b x1, plan-t x1, and one keyless row x1
//   Sam:    plan-s x2 (the SAME key Rachel holds), plan-t x1 (Rachel holds one too)
const ROWS = (): TaskItem[] => [
  held( "a1", "epic:plan-a" ), held( "a2", "epic:plan-a" ), held( "a3", "epic:plan-a" ),
  held( "b1", "epic:plan-b" ),
  held( "c1", "epic:plan-c" ), held( "c2", "epic:plan-c" ),
  held( "sr1", "epic:plan-s" ), held( "sr2", "epic:plan-s" ),
  held( "tr1", "epic:plan-t" ),
  held( "x1", null ),
  held( "ss1", "epic:plan-s", "sam" ), held( "ss2", "epic:plan-s", "sam" ),
  held( "ts1", "epic:plan-t", "sam" ),
];

const ids = ( rows: ReadonlyArray<TaskItem> ): string[] => rows.map( ( r ) => r.id as string );

// ───────────────────────────── the model ─────────────────────────────

test( "model: plans are made per filer — a key shared by two of ONE filer's rows is a plan, a key held by one is not, a keyless row never is", () => {
  const rachel = groupHeldRowsByFiler( ROWS() ).find( ( g ) => g.filer === "Rachel" )!;
  assert.deepEqual( rachel.plans.map( ( p ) => [ p.key, p.ids ] ), [
    [ "epic:plan-a", [ "a1", "a2", "a3" ] ],
    [ "epic:plan-c", [ "c1", "c2" ] ],
    [ "epic:plan-s", [ "sr1", "sr2" ] ],
  ] );
  assert.deepEqual( ids( rachel.ungrouped ), [ "b1", "tr1", "x1" ] );
  assert.equal( rachel.tasks.length, 10, "the filer's own list must still carry EVERY row, grouped or not" );
} );

test( "model: a key shared across two filers makes one plan under each, never one merged plan", () => {
  const groups = groupHeldRowsByFiler( ROWS() );
  const sam    = groups.find( ( g ) => g.filer === "Sam" )!;
  assert.deepEqual( sam.plans.map( ( p ) => [ p.key, p.ids ] ), [ [ "epic:plan-s", [ "ss1", "ss2" ] ] ] );
  const rachelS = groups.find( ( g ) => g.filer === "Rachel" )!.plans.find( ( p ) => p.key === "epic:plan-s" )!;
  assert.deepEqual( rachelS.ids, [ "sr1", "sr2" ], "Rachel's plan reached a row Sam filed" );
} );

test( "model: one row per filer under a shared key is NOT a plan, even though the key is held twice overall", () => {
  const groups = groupHeldRowsByFiler( ROWS() );
  assert.deepEqual( groups.find( ( g ) => g.filer === "Sam" )!.ungrouped.map( ( t ) => t.id ), [ "ts1" ] );
  assert.ok( ! groups.find( ( g ) => g.filer === "Sam" )!.plans.some( ( p ) => p.key === "epic:plan-t" ), "expected: ! groups.find( ( g ) => g.filer === 'Sam' )!.plans.some( ( p ) => p.key === 'epic:plan-t' )" );
} );

test( "model: epic:unassigned and a blank key are never a plan, beside a real key that is", () => {
  const rows = [ held( "u1", "epic:unassigned" ), held( "u2", "epic:unassigned" ),
                 held( "e1", "" ), held( "e2", "" ),
                 held( "r1", "epic:real" ), held( "r2", "epic:real" ) ];
  const g = groupHeldRowsByFiler( rows )[ 0 ]!;
  assert.deepEqual( g.plans.map( ( p ) => p.key ), [ "epic:real" ] );
  assert.deepEqual( ids( g.ungrouped ), [ "e1", "e2", "u1", "u2" ] );
  const kept = groupHeldRowsByFiler( rows, new Set( [ holdingPlanId( "Rachel", "epic:unassigned" ) ] ) )[ 0 ]!;
  assert.deepEqual( kept.plans.map( ( p ) => p.key ), [ "epic:real" ], "a kept report resurrected a plan over epic:unassigned" );
} );

test( "model: keep names a plan that stays at ONE row — that filer's, and only that plan", () => {
  const keep   = new Set( [ holdingPlanId( "Rachel", "epic:plan-b" ) ] );
  const groups = groupHeldRowsByFiler( ROWS(), keep );
  const rachel = groups.find( ( g ) => g.filer === "Rachel" )!;
  assert.deepEqual( rachel.plans.map( ( p ) => p.key ), [ "epic:plan-a", "epic:plan-b", "epic:plan-c", "epic:plan-s" ] );
  assert.deepEqual( ids( rachel.ungrouped ), [ "tr1", "x1" ] );
  const sam = groups.find( ( g ) => g.filer === "Sam" )!;
  assert.ok( ! sam.plans.some( ( p ) => p.key === "epic:plan-t" ), "Rachel's kept id kept a plan for Sam" );
} );

test( "model: junk in, empty out — and a row with no id cannot join a plan", () => {
  assert.deepEqual( groupHeldRowsByFiler( null ), [] );
  assert.deepEqual( groupHeldRowsByFiler( "nope" ), [] );
  const junk = groupHeldRowsByFiler( [ null, undefined, {} ] );
  assert.deepEqual( junk.map( ( g ) => g.plans ), [ [] ], "junk rows made a plan" );
  const g = groupHeldRowsByFiler( [ { created_by: "rachel 0e61abe3", correlation_key: "k" }, held( "z1", "k" ) ] )[ 0 ]!;
  assert.deepEqual( g.plans, [], "an id-less row counted toward a plan" );
  assert.equal( g.ungrouped.length, 2 );
} );

test( "model: planTitle strips epic:, turns hyphens and underscores to spaces, never blanks a key", () => {
  assert.equal( planTitle( "epic:v022-docs-and-reuse" ), "v022 docs and reuse" );
  assert.equal( planTitle( "plan_x--y" ), "plan x y" );
  assert.equal( planTitle( "epic:" ), "epic:" );
  assert.equal( groupHeldRowsByFiler( ROWS() )[ 0 ]!.plans[ 0 ]!.title, "plan a" );
} );

test( "model: the same key under two filers has two different plan ids", () => {
  assert.notEqual( holdingPlanId( "Rachel", "epic:plan-s" ), holdingPlanId( "Sam", "epic:plan-s" ) );
} );

// ───────────────────────────── the template ─────────────────────────────

test( "template: the label reads 'Plan: <title>', the raw key is only a tooltip, the count is the rows listed", () => {
  const rows = [ held( "m1", "epic:v022-docs-and-reuse" ), held( "m2", "epic:v022-docs-and-reuse" ) ];
  const g    = groupHeldRowsByFiler( rows )[ 0 ]!;
  const el   = renderHoldingPlanGroup( g.filer, g.plans[ 0 ]!, undefined, [], false );
  const label = el.querySelector( ".holding-plan-label" ) as HTMLElement;
  assert.equal( label.textContent, "Plan: v022 docs and reuse" );
  assert.equal( label.title, "epic:v022-docs-and-reuse" );
  assert.ok( ! ( el.querySelector( ".holding-plan-header" )!.textContent ?? "" ).includes( "epic:" ), "the raw key is painted as text" );
  assert.ok( ! /stor(y|ies)|epic/i.test( el.querySelector( ".holding-plan-header" )!.textContent ?? "" ), "the operator reads 'story' or 'epic'" );
  assert.equal( el.querySelector( ".holding-plan-count" )!.textContent, "2" );
  assert.equal( el.querySelectorAll( "table tbody tr[data-task-id], table .task-verb-select[data-task-id]" ).length > 0, true );
  assert.equal( el.dataset.filer, "Rachel" );
  assert.equal( el.dataset.plan, "epic:v022-docs-and-reuse" );
} );

test( "template: collapsed by default, open when asked, with chevron and aria-expanded in agreement", () => {
  const g = groupHeldRowsByFiler( [ held( "m1", "k" ), held( "m2", "k" ) ] )[ 0 ]!;
  const shut = renderHoldingPlanGroup( g.filer, g.plans[ 0 ]!, undefined, [], false );
  assert.ok( shut.classList.contains( "collapsed" ), "expected: shut.classList.contains( 'collapsed' )" );
  assert.equal( shut.querySelector( ".holding-plan-header" )!.getAttribute( "aria-expanded" ), "false" );
  assert.equal( shut.querySelector( ".holding-plan-chevron" )!.textContent, "▶" );
  const open = renderHoldingPlanGroup( g.filer, g.plans[ 0 ]!, undefined, [], true );
  assert.ok( ! open.classList.contains( "collapsed" ), "expected: ! open.classList.contains( 'collapsed' )" );
  assert.equal( open.querySelector( ".holding-plan-header" )!.getAttribute( "aria-expanded" ), "true" );
  assert.equal( open.querySelector( ".holding-plan-chevron" )!.textContent, "▼" );
});

test( "template: the button's label, tooltip and id list all carry the SAME N as the rows in the table", () => {
  const g   = groupHeldRowsByFiler( ROWS() )[ 0 ]!;
  const el  = renderHoldingPlanGroup( g.filer, g.plans[ 0 ]!, undefined, [], true );
  const btn = el.querySelector( ".holding-plan-approve-all" ) as HTMLButtonElement;
  const listed = Array.from( el.querySelectorAll<HTMLElement>( ".task-verb-select[data-task-id]" ) ).map( ( s ) => s.dataset.taskId );
  assert.deepEqual( listed, [ "a1", "a2", "a3" ] );
  assert.equal( btn.dataset.taskIds, listed.join( "," ), "the ids on the button are not the rows listed under it" );
  assert.equal( btn.textContent, holdingPlanApproveLabel( 3 ) );
  assert.equal( holdingPlanApproveLabel( 3 ), "Approve all 3" );
  assert.equal( btn.title, holdingPlanApproveTitle( 3 ) );
  assert.match( holdingPlanApproveTitle( 3 ), /3 rows listed under this plan/ );
} );

test( "template: plans sit INSIDE their filer's group, before its ungrouped rows, which are omitted when there are none", () => {
  const frag   = renderHoldingAreaGroups( groupHeldRowsByFiler( ROWS() ), undefined, [], new Set( [ "Rachel" ] ), new Set( [ holdingPlanId( "Rachel", "epic:plan-c" ) ] ) );
  const groups = Array.from( frag.children ) as HTMLElement[];
  assert.deepEqual( groups.map( ( g ) => g.dataset.filer ), [ "Rachel", "Sam" ] );
  const [ rachel, sam ] = groups as [ HTMLElement, HTMLElement ];
  assert.deepEqual( Array.from( rachel.querySelectorAll<HTMLElement>( ".holding-plan-group" ) ).map( ( p ) => p.dataset.plan ),
    [ "epic:plan-a", "epic:plan-c", "epic:plan-s" ] );
  assert.deepEqual( Array.from( sam.querySelectorAll<HTMLElement>( ".holding-plan-group" ) ).map( ( p ) => p.dataset.plan ), [ "epic:plan-s" ] );
  assert.equal( rachel.querySelector( ".holding-plan-group[data-plan='epic:plan-c']" )!.classList.contains( "collapsed" ), false, "an open plan id did not open its plan" );
  assert.equal( rachel.querySelector( ".holding-plan-group[data-plan='epic:plan-a']" )!.classList.contains( "collapsed" ), true );
  // The filer's own table lists exactly its ungrouped rows.
  const own = Array.from( rachel.children ).filter( ( c ) => c.tagName === "TABLE" );
  assert.equal( own.length, 1 );
  assert.deepEqual( Array.from( own[ 0 ]!.querySelectorAll<HTMLElement>( ".task-verb-select[data-task-id]" ) ).map( ( s ) => s.dataset.taskId ), [ "b1", "tr1", "x1" ] );
  // Sam's ungrouped is one row; a filer whose rows are ALL in plans paints no table of its own.
  const allPlanned = renderHoldingAreaGroups( groupHeldRowsByFiler( [ held( "p1", "k" ), held( "p2", "k" ) ] ), undefined, [] ).firstElementChild as HTMLElement;
  assert.equal( Array.from( allPlanned.children ).filter( ( c ) => c.tagName === "TABLE" ).length, 0 );
  assert.equal( allPlanned.querySelectorAll( ".holding-plan-group" ).length, 1 );
} );

test( "template: nothing sits above the filer groups — no stories strip, no plan header outside a filer", () => {
  const frag = renderHoldingAreaGroups( groupHeldRowsByFiler( ROWS() ), undefined, [] );
  assert.ok( Array.from( frag.children ).every( ( c ) => c.classList.contains( "holding-area-group" ) ), "expected: Array.from( frag.children ).every( ( c ) => c.classList.contains( 'holding-area-group' ) )" );
  assert.ok( frag.querySelector( ".holding-area-stories" ) === null, "a stories strip was painted" );
} );

// ───────────────────────────── the pane ─────────────────────────────

interface Harness {
  container : HTMLElement;
  calls     : Array<{ id: string; toStatus: string; extras: Record<string, string> }>;
  gate      : { release(): void } | null;
  plans     (): string[];
  group     ( filer: string, key: string ): HTMLElement;
  button    ( filer: string, key: string ): HTMLButtonElement;
  status    ( filer: string, key: string ): string;
  listed    ( filer: string, key: string ): string[];
  poll      (): Promise<void>;
  dropRows  ( key: string ): void;
  restoreRows( key: string ): void;
  unmount   (): void;
}

/**
 * `verdict` decides each row's outcome. After every refresh the rows the store holds are the
 * ones the harness has not yet approved — the real store would re-read them — so a refused row
 * stays held and an approved one leaves.
 */
function mount( verdict: ( id: string ) => { ok: boolean; message?: string }, hold = false ): Harness {
  let rows = ROWS();
  const calls: Harness[ "calls" ] = [];
  const bus = createEventBusForTesting();
  const h: { gate: Harness[ "gate" ] } = { gate: null };
  const emit = (): void => {
    bus.emit( { type: "store_holding_area_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } as never );
  };
  const store: HoldingAreaStoreLike = {
    composite: () => ( { status: "", tasks: rows } as TaskListComposite ),
    async refresh() { emit(); },
    async refreshAfterWrite() { emit(); },
    async transitionTask( id, toStatus, extras ) {
      calls.push( { id, toStatus, extras: extras as Record<string, string> } );
      if ( hold && calls.length === 1 ) {
        await new Promise<void>( ( r ) => { h.gate = { release: r }; } );
      }
      const v = verdict( id );
      if ( v.ok ) rows = rows.filter( ( r ) => r.id !== id );
      return v;
    },
  };
  const root = document.createElement( "div" );
  const renderer = createHoldingAreaRenderer( { eventBus: bus, store, nowDateFn: () => new Date( "2026-10-02T15:00:00Z" ) } );
  renderer.mount( root );
  let unmounted = false;
  mounted.push( () => { if ( !unmounted ) renderer.unmount(); } );
  const container = root.querySelector( ".holding-area-container" ) as HTMLElement;
  const group = ( filer: string, key: string ): HTMLElement => {
    const g = Array.from( container.querySelectorAll<HTMLElement>( ".holding-plan-group" ) )
      .find( ( el ) => el.dataset.filer === filer && el.dataset.plan === key );
    assert.ok( g, `no plan group for ${ filer } / ${ key }` );
    return g;
  };
  return {
    container, calls,
    get gate() { return h.gate; },
    plans : () => Array.from( container.querySelectorAll<HTMLElement>( ".holding-plan-group" ) ).map( ( g ) => `${ g.dataset.filer }/${ g.dataset.plan }` ),
    group,
    button: ( filer, key ) => group( filer, key ).querySelector( ".holding-plan-approve-all" ) as HTMLButtonElement,
    status: ( filer, key ) => ( group( filer, key ).querySelector( ".holding-plan-status" ) as HTMLElement ).textContent ?? "",
    listed: ( filer, key ) => Array.from( group( filer, key ).querySelectorAll<HTMLElement>( ".task-verb-select[data-task-id]" ) ).map( ( s ) => s.dataset.taskId as string ),
    poll  : async () => { await store.refresh(); },
    dropRows   : ( key ) => { rows = rows.filter( ( r ) => r.correlation_key !== key ); },
    restoreRows: ( key ) => { rows = [ ...rows, ...ROWS().filter( ( r ) => r.correlation_key === key ) ]; },
    unmount: () => { unmounted = true; renderer.unmount(); },
  } as Harness;
}

const click = ( el: HTMLElement ): void => { el.dispatchEvent( new globalThis.MouseEvent( "click", { bubbles: true } ) ); };
// ARM, THEN CONFIRM (row 376dd4cb): a plan runs on the SECOND press of its button.
const press = ( el: HTMLElement ): void => { click( el ); click( el ); };
const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

const RA = [ "Rachel", "epic:plan-a" ] as const;
const RC = [ "Rachel", "epic:plan-c" ] as const;
const RS = [ "Rachel", "epic:plan-s" ] as const;
const SS = [ "Sam", "epic:plan-s" ] as const;

test( "pane: one plan per filer per key of TWO OR MORE of that filer's rows — a shared key is two plans, a single row none", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.deepEqual( h.plans(), [ "Rachel/epic:plan-a", "Rachel/epic:plan-c", "Rachel/epic:plan-s", "Sam/epic:plan-s" ] );
  assert.equal( h.button( ...RA ).textContent, "Approve all 3" );
  assert.equal( h.button( ...RC ).textContent, "Approve all 2" );
  h.unmount();
} );

test( "pane: the ids on each button equal the rows listed under that plan, and a shared key lists each filer's own rows", () => {
  const h = mount( () => ( { ok: true } ) );
  for ( const [ f, k ] of [ RA, RC, RS, SS ] ) {
    assert.equal( h.button( f, k ).dataset.taskIds, h.listed( f, k ).join( "," ), `${ f }/${ k }` );
  }
  assert.deepEqual( h.listed( ...RS ), [ "sr1", "sr2" ] );
  assert.deepEqual( h.listed( ...SS ), [ "ss1", "ss2" ] );
  h.unmount();
} );

test( "pane: nothing sits above the filer groups, and no operator-visible text says story or epic", () => {
  const h = mount( () => ( { ok: true } ) );
  const first = h.container.firstElementChild as HTMLElement;
  assert.ok( first.classList.contains( "holding-area-group" ), `the pane opens with ${ first.className }` );
  assert.ok( h.container.querySelector( ".holding-area-stories, .holding-story-bar" ) === null, "a stories strip was painted" );
  for ( const g of Array.from( h.container.querySelectorAll( ".holding-plan-header" ) ) ) {
    assert.ok( ! /stor(y|ies)|epic/i.test( g.textContent ?? "" ), `header text: ${ g.textContent }` );
  }
  h.unmount();
} );

test( "toggle: plans start collapsed; a click on the header opens ONLY that plan, and a second click closes it", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "expected: h.group( ...RA ).classList.contains( 'collapsed' )" );
  const header = h.group( ...RA ).querySelector( ".holding-plan-header" ) as HTMLElement;
  click( header );
  assert.equal( h.group( ...RA ).classList.contains( "collapsed" ), false );
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );
  assert.equal( header.querySelector( ".holding-plan-chevron" )!.textContent, "▼" );
  assert.ok( h.group( ...RC ).classList.contains( "collapsed" ), "opening one plan opened a sibling" );
  assert.ok( h.group( ...SS ).classList.contains( "collapsed" ), "opening Rachel's plan opened Sam's plan of the same key" );
  const filerGroup = h.group( ...RA ).closest( ".holding-area-group" ) as HTMLElement;
  assert.ok( filerGroup.classList.contains( "collapsed" ), "opening a plan opened its filer" );
  click( header );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "expected: h.group( ...RA ).classList.contains( 'collapsed' )" );
  assert.equal( header.getAttribute( "aria-expanded" ), "false" );
  assert.equal( header.querySelector( ".holding-plan-chevron" )!.textContent, "▶" );
  h.unmount();
} );

test( "toggle: the keyboard opens a plan, and a click on its Approve button never toggles it", () => {
  const h = mount( () => ( { ok: true } ) );
  const header = h.group( ...RA ).querySelector( ".holding-plan-header" ) as HTMLElement;
  const key = ( k: string ): boolean => header.dispatchEvent( new globalThis.KeyboardEvent( "keydown", { key: k, bubbles: true, cancelable: true } ) );
  assert.equal( key( "a" ), true );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "a stray key toggled the plan" );
  assert.equal( key( "Enter" ), false, "Enter on a plan header must be consumed" );
  assert.equal( h.group( ...RA ).classList.contains( "collapsed" ), false );
  click( h.button( ...RA ) );
  assert.equal( h.group( ...RA ).classList.contains( "collapsed" ), false, "pressing Approve folded the plan" );
  h.unmount();
} );

test( "toggle: an open plan survives the 60s repaint, and its open state is forgotten when the plan is gone", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.group( ...RC ).querySelector( ".holding-plan-header" ) as HTMLElement );
  await h.poll();
  assert.equal( h.group( ...RC ).classList.contains( "collapsed" ), false, "the repaint snapped an open plan shut" );
  assert.ok( h.group( ...RA ).classList.contains( "collapsed" ), "expected: h.group( ...RA ).classList.contains( 'collapsed' )" );

  h.dropRows( "epic:plan-c" );
  await h.poll();
  h.restoreRows( "epic:plan-c" );
  await h.poll();
  assert.ok( h.group( ...RC ).classList.contains( "collapsed" ), "a plan that came back kept its old open state" );
  h.unmount();
} );

test( "filer group: its Approve all still covers EVERY row of that filer, grouped or not, and none of another filer's", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.container.querySelector( ".holding-approve-all[data-filer='Rachel']" ) as HTMLButtonElement;
  press( btn );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ).sort(),
    [ "a1", "a2", "a3", "b1", "c1", "c2", "sr1", "sr2", "tr1", "x1" ].sort() );
  h.unmount();
} );

test( "click: ONE confirmed press sends one queued transition per row of THAT plan — not its filer's other rows, not the same key under another filer", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( h.button( ...RS ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "sr1", "sr2" ] );
  assert.deepEqual( [ ...new Set( h.calls.map( ( c ) => c.toStatus ) ) ], [ "queued" ] );
  assert.deepEqual( h.calls[ 0 ]?.extras, {}, "approve posted a reason it was never asked for" );
  assert.deepEqual( h.plans(), [ "Rachel/epic:plan-a", "Rachel/epic:plan-c", "Sam/epic:plan-s" ] );
  assert.deepEqual( h.listed( ...SS ), [ "ss1", "ss2" ], "Sam's rows moved with Rachel's plan" );
  h.unmount();
} );

test( "click: approving a plan leaves the filer's ungrouped rows and the other plans held", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( h.button( ...RA ) );
  await settle();
  const remaining = Array.from( h.container.querySelectorAll<HTMLElement>( ".holding-area-group[data-filer='Rachel'] .task-verb-select[data-task-id]" ) ).map( ( s ) => s.dataset.taskId );
  assert.deepEqual( remaining.sort(), [ "b1", "c1", "c2", "sr1", "sr2", "tr1", "x1" ].sort() );
  h.unmount();
} );

test( "a plan that ends PARTLY refused says so, and keeps its header even down to one row", async () => {
  const refusal = "403: actor 'maria' is not in approvers ['rick']";
  const h = mount( ( id ) => id === "a2" ? { ok: false, message: refusal } : { ok: true } );
  press( h.button( ...RA ) );
  await settle();

  assert.deepEqual( h.plans(), [ "Rachel/epic:plan-a", "Rachel/epic:plan-c", "Rachel/epic:plan-s", "Sam/epic:plan-s" ], "the half-approved plan lost its header" );
  assert.equal( h.status( ...RA ), `2 of 3 approved — 1 refused. First refusal: ${ refusal }` );
  assert.equal( h.button( ...RA ).dataset.taskIds, "a2", "the header now offers more than the rows still held" );
  assert.deepEqual( h.listed( ...RA ), [ "a2" ] );
  assert.equal( h.button( ...RA ).textContent, "Approve all 1" );

  await h.poll();
  assert.match( h.status( ...RA ), /1 refused/, "the 60s poll erased the partial-failure report" );
  assert.equal( h.status( ...RC ), "", "a report leaked onto a plan that never ran" );
  h.unmount();
} );

test( "a report on Rachel's plan does not keep Sam's one-row remainder of the same key alive", async () => {
  const h = mount( ( id ) => id === "sr1" ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( ...RS ) );
  await settle();
  assert.match( h.status( ...RS ), /1 refused/ );
  press( h.button( ...SS ) );
  await settle();
  assert.deepEqual( h.plans().filter( ( p ) => p.startsWith( "Sam/" ) ), [], "Sam's fully approved plan stayed on Rachel's report" );
  h.unmount();
} );

test( "a non-operator is refused on every row: nothing skipped, nothing approved, the plan stays", async () => {
  const h = mount( () => ( { ok: false, message: "403: 'maria' is not an approver" } ) );
  press( h.button( ...RC ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "c1", "c2" ], "the loop stopped at the first refusal" );
  assert.equal( h.status( ...RC ), "0 of 2 approved — 2 refused. First refusal: 403: 'maria' is not an approver" );
  assert.equal( h.plans().length, 4 );
  assert.equal( h.button( ...RC ).disabled, false, "the button stayed dead after a refused run" );
  h.unmount();
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
  assert.ok( ! h.plans().includes( "Rachel/epic:plan-a" ), "a fully approved plan kept its header, or its report" );
  await h.poll();
  assert.ok( ! h.plans().includes( "Rachel/epic:plan-a" ), "a stale report resurrected the plan on the next poll" );
  h.unmount();
} );

test( "a second press while the plan runs is ignored, and the button is dead meanwhile", async () => {
  const h = mount( () => ( { ok: true } ), true );
  const btn = h.button( ...RA );
  press( btn );
  await settle();
  assert.equal( h.calls.length, 1, "the confirming press did not reach the store" );
  assert.equal( btn.disabled, true, "the button stayed live mid-run" );
  assert.match( h.status( ...RA ), /^Approved 0 of 3…$/ );

  click( btn );
  await settle();
  assert.equal( h.calls.length, 1, "a second press started the plan over" );

  // 🔴 THE GUARD IS THE SET, NOT THE DISABLED ATTRIBUTE: a poll tick mid-run rebuilds the
  // header and hands the operator a FRESH, ENABLED button. A press on it must still be ignored.
  await h.poll();
  const fresh = h.button( ...RA );
  assert.ok( fresh !== btn, "the poll did not rebuild the header, so this arm tests nothing" );
  assert.equal( fresh.disabled, false, "precondition: the rebuilt button is live" );
  press( fresh );
  await settle();
  assert.equal( h.calls.length, 1, "a press on the rebuilt button started the plan a second time" );

  h.gate!.release();
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  h.unmount();
} );

test( "the same key under another filer is a different run: its press is NOT blocked by Rachel's run in flight", async () => {
  const h = mount( () => ( { ok: true } ), true );
  press( h.button( ...RS ) );
  await settle();
  assert.equal( h.calls.length, 1 );
  press( h.button( ...SS ) );
  await settle();
  assert.ok( h.calls.some( ( c ) => c.id === "ss1" ), "Sam's plan was treated as the same run as Rachel's" );
  h.gate!.release();
  await settle();
  h.unmount();
} );

test( "defensive presses: a plan with no ids reports it and posts nothing; one with no plan key does nothing", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( ...RC );
  btn.dataset.taskIds = "";
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0 );
  assert.equal( h.status( ...RC ), HOLDING_BATCH_NO_ROWS_PLAN );

  const other = h.button( ...RA );
  delete other.dataset.plan;
  click( other );
  await settle();
  assert.equal( h.calls.length, 0, "a key-less button posted transitions" );

  const idless = h.button( ...RC );
  delete idless.dataset.taskIds;       // an attribute that is absent, not merely empty
  click( idless );
  await settle();
  assert.equal( h.calls.length, 0, "a button with no id list posted transitions" );
  assert.equal( h.status( ...RC ), HOLDING_BATCH_NO_ROWS_PLAN );
  h.unmount();
} );

test( "a report is dropped when its plan leaves the board entirely", async () => {
  const h = mount( ( id ) => id.startsWith( "c" ) ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( ...RC ) );
  await settle();
  assert.match( h.status( ...RC ), /2 refused/ );

  h.dropRows( "epic:plan-c" );          // someone else closed both refused rows
  await h.poll();
  assert.ok( ! h.plans().includes( "Rachel/epic:plan-c" ), "a plan with no rows kept a header on the strength of its report" );

  h.restoreRows( "epic:plan-c" );       // the same key comes back later, as a NEW plan
  await h.poll();
  assert.equal( h.status( ...RC ), "", "a dead plan's report came back with its key" );
  h.unmount();
} );

test( "a refusal that carries no message still counts, and a pane unmounted mid-run does not throw", async () => {
  const h = mount( () => ( { ok: false } ), true );
  press( h.button( ...RC ) );
  await settle();
  h.unmount();                         // the operator navigates away while row one is in flight
  h.gate!.release();
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "c1", "c2" ], "the run abandoned its rows when the pane went away" );
} );

test( "a refusal with no message reports an empty first refusal rather than 'undefined'", async () => {
  const h = mount( () => ( { ok: false } ) );
  press( h.button( ...RC ) );
  await settle();
  assert.equal( h.status( ...RC ), "0 of 2 approved — 2 refused. First refusal: " );
  h.unmount();
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
  assert.ok( btn.classList.contains( HOLDING_BATCH_ARMED_CLASS ), "an armed button carries the armed class" );
  assert.equal( h.status( ...RA ), "Click again to approve 3 rows in this plan." );
  h.unmount();
} );

test( "confirm: the SECOND press runs the plan and the button is back to rest", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( ...RA );
  click( btn );
  click( btn );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  assert.equal( btn.dataset.armed, undefined, "the button stayed armed after it ran" );
  assert.equal( btn.classList.contains( HOLDING_BATCH_ARMED_CLASS ), false );
  h.unmount();
} );

test( "arming one plan disarms the other, and clears the status line of the one it disarmed", async () => {
  const h = mount( () => ( { ok: true } ) );
  const a = h.button( ...RA );
  const c = h.button( ...RC );
  click( a );
  assert.equal( a.dataset.armed, "1" );
  click( c );
  assert.equal( c.dataset.armed, "1" );
  assert.equal( a.dataset.armed, undefined, "two plan buttons were armed at once" );
  assert.equal( a.textContent, "Approve all 3" );
  assert.equal( h.status( ...RA ), "", "a disarmed plan kept its 'Click again' line" );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );

test( "a repaint rebuilds the header unarmed, and the armed status line does not outlive the arming", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( ...RA ) );
  await h.poll();
  const fresh = h.button( ...RA );
  assert.equal( fresh.dataset.armed, undefined );
  assert.equal( fresh.textContent, "Approve all 3" );
  assert.equal( h.status( ...RA ), "" );
  click( fresh );
  await settle();
  assert.equal( h.calls.length, 0, "a press after a repaint ran the plan instead of arming it" );
  h.unmount();
} );

test( "disarming tolerates an armed header whose attributes were stripped", async () => {
  const h = mount( () => ( { ok: true } ) );
  const stray = h.button( ...RA );
  stray.dataset.armed = "1";
  delete stray.dataset.plan;                // an armed button with no plan key: the status paint finds no span
  delete stray.dataset.taskIds;             // and no id list: its resting label counts 0 rows
  const c = h.button( ...RC );
  click( c );
  assert.equal( c.dataset.armed, "1", "the real press did not arm" );
  assert.equal( stray.dataset.armed, undefined );
  assert.equal( stray.textContent, "Approve all 0" );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );

test( "a plan's identity is read from its filer AND its plan attributes: an armed button missing either is still disarmed, a status span missing either is skipped", async () => {
  const h = mount( () => ( { ok: true } ) );
  // An armed button with no filer, and another with no plan: disarming asks each for its id.
  const noFiler = h.button( ...RS );
  noFiler.dataset.armed = "1";
  delete noFiler.dataset.filer;
  // Status spans that lost one half of their identity are passed over, never matched by accident.
  delete ( h.group( ...RA ).querySelector( ".holding-plan-status" ) as HTMLElement ).dataset.filer;
  delete ( h.group( ...RC ).querySelector( ".holding-plan-status" ) as HTMLElement ).dataset.plan;
  click( h.button( ...SS ) );
  assert.equal( h.button( ...SS ).dataset.armed, "1" );
  assert.equal( h.status( ...SS ), "Click again to approve 2 rows in this plan.", "the status paint found the wrong span" );
  assert.equal( noFiler.dataset.armed, undefined );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );

test( "arm: the FIRST press OPENS the closed plan, so its rows are on screen before the confirming press; only that plan opens", async () => {
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
  await h.poll();
  assert.ok( ! h.group( ...RA ).classList.contains( "collapsed" ), "the repaint shut the plan the operator is about to approve" );
  h.unmount();
} );
