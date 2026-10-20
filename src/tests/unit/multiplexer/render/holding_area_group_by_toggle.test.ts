// Holding area — Creator / Assignee toggle.
//
// The fixture gives every row a different creator and assignee, so a grouping that reads
// the same field in both modes cannot pass. The pane tests drive the real renderer
// into a real element and press the real toggle button.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  HOLDING_GROUP_BY_STORAGE_KEY,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import {
  groupHeldRows,
  groupHeldRowsByFiler,
  taskAssigneeLabel,
} from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const mounted: Array<() => void> = [];
beforeEach( () => { window.localStorage.clear(); } );
afterEach( () => { for ( const unmount of mounted.splice( 0 ) ) unmount(); } );

function held( id: string, createdBy: string, owner: string | null ): TaskItem {
  return {
    id, title: `row ${ id }`, status: "not_approved", priority: "P2",
    created_by: createdBy, owner_persona: owner, correlation_key: null,
  } as unknown as TaskItem;
}

// Creator and assignee differ on each row.
const ROWS = (): TaskItem[] => [
  held( "r1", "sam 0e61abe3",    "maria" ),
  held( "r2", "sam 0e61abe3",    "tiberius" ),
  held( "r3", "rachel 1111aaaa", "maria" ),
  held( "r4", "rachel 1111aaaa", null ),
  held( "r5", "mr radio 2222bbbb", "mr radio" ),
];

const shape = ( groups: ReturnType<typeof groupHeldRows> ): Array<[ string, string[] ]> =>
  groups.map( ( g ) => [ g.filer, g.tasks.map( ( t ) => t.id as string ).sort() ] );

// ───────────────────────────── the model ─────────────────────────────

test( "model: creator mode groups on created_by and equals groupHeldRowsByFiler", () => {
  assert.deepEqual( shape( groupHeldRows( ROWS(), "creator" ) ), [
    [ "Mr Radio", [ "r5" ] ],
    [ "Rachel",   [ "r3", "r4" ] ],
    [ "Sam",      [ "r1", "r2" ] ],
  ] );
  assert.deepEqual( groupHeldRows( ROWS(), "creator" ), groupHeldRowsByFiler( ROWS() ) );
} );

test( "model: assignee mode groups on owner_persona, and a blank owner is 'Unassigned'", () => {
  assert.deepEqual( shape( groupHeldRows( ROWS(), "assignee" ) ), [
    [ "Maria",      [ "r1", "r3" ] ],
    [ "Mr Radio",   [ "r5" ] ],
    [ "Tiberius",   [ "r2" ] ],
    [ "Unassigned", [ "r4" ] ],
  ] );
} );

test( "model: the two modes give different groups for the same rows, and the same total", () => {
  const a = groupHeldRows( ROWS(), "creator" );
  const b = groupHeldRows( ROWS(), "assignee" );
  assert.notDeepEqual( shape( a ), shape( b ) );
  const total = ( gs: typeof a ): number => gs.reduce( ( n, g ) => n + g.tasks.length, 0 );
  assert.equal( total( a ), 5 );
  assert.equal( total( b ), 5 );
} );

test( "model: an unknown mode behaves as creator", () => {
  assert.deepEqual( groupHeldRows( ROWS(), "bogus" as never ), groupHeldRows( ROWS(), "creator" ) );
} );

test( "model: a plan inside an assignee group is made from that assignee's rows only", () => {
  const rows = [
    { ...held( "p1", "sam 0e61abe3", "maria" ),    correlation_key: "epic:x" },
    { ...held( "p2", "rachel 1111aaaa", "maria" ), correlation_key: "epic:x" },
    { ...held( "p3", "sam 0e61abe3", "tiberius" ), correlation_key: "epic:x" },
  ] as TaskItem[];
  const groups = groupHeldRows( rows, "assignee" );
  const maria  = groups.find( ( g ) => g.filer === "Maria" )!;
  assert.deepEqual( maria.plans.map( ( p ) => p.ids ), [ [ "p1", "p2" ] ] );
  assert.deepEqual( groups.find( ( g ) => g.filer === "Tiberius" )!.plans, [], "one row is not a plan" );
} );

test( "model: taskAssigneeLabel display-cases, strips a trailing session id, defaults to Unassigned", () => {
  assert.equal( taskAssigneeLabel( { owner_persona: "maria" } as TaskItem ), "Maria" );
  assert.equal( taskAssigneeLabel( { owner_persona: "mr radio" } as TaskItem ), "Mr Radio" );
  assert.equal( taskAssigneeLabel( { owner_persona: "sam 0e61abe3" } as TaskItem ), "Sam" );
  assert.equal( taskAssigneeLabel( { owner_persona: "" } as TaskItem ), "Unassigned" );
  assert.equal( taskAssigneeLabel( {} as TaskItem ), "Unassigned" );
  assert.equal( taskAssigneeLabel( null ), "Unassigned" );
} );

test( "model: a non-array input yields no groups in either mode", () => {
  assert.deepEqual( groupHeldRows( null, "assignee" ), [] );
  assert.deepEqual( groupHeldRows( "x", "creator" ), [] );
} );

// ───────────────────────────── the pane ─────────────────────────────

function mount(): { root: HTMLElement; groups: () => string[]; press: ( by: string ) => void; calls: string[] } {
  const rows  = ROWS();
  const calls: string[] = [];
  const bus   = createEventBusForTesting();
  const store: HoldingAreaStoreLike = {
    composite: () => ( { status: "", tasks: rows } as TaskListComposite ),
    async refresh() { calls.push( "refresh" ); },
    async refreshAfterWrite() { /* unused */ },
    async transitionTask( id, toStatus ) { calls.push( `${ id }->${ toStatus }` ); return { ok: true }; },
  } as HoldingAreaStoreLike;
  const root     = document.createElement( "div" );
  const renderer = createHoldingAreaRenderer( { eventBus: bus, store, nowDateFn: () => new Date( "2026-10-20T15:00:00Z" ) } );
  renderer.mount( root );
  mounted.push( () => renderer.unmount() );
  return {
    root, calls,
    groups: () => Array.from( root.querySelectorAll<HTMLElement>( ".holding-area-group" ) ).map( ( g ) => g.dataset.filer as string ),
    press : ( by ) => ( root.querySelector( `[data-testid="multiplexer-holding-group-by-${ by }"]` ) as HTMLButtonElement ).click(),
  };
}

const pressed = ( root: HTMLElement ): string[] =>
  Array.from( root.querySelectorAll<HTMLElement>( ".holding-group-toggle-btn" ) )
    .filter( ( b ) => b.getAttribute( "aria-pressed" ) === "true" ).map( ( b ) => b.dataset.groupBy as string );

test( "pane: starts grouped by creator with Creator pressed", () => {
  const h = mount();
  assert.deepEqual( h.groups(), [ "Mr Radio", "Rachel", "Sam" ] );
  assert.deepEqual( pressed( h.root ), [ "creator" ] );
} );

test( "pane: pressing Assignee regroups on owner_persona without a new fetch, and Creator returns", () => {
  const h = mount();
  h.press( "assignee" );
  assert.deepEqual( h.groups(), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  assert.deepEqual( pressed( h.root ), [ "assignee" ] );
  assert.deepEqual( h.calls, [], "the switch repaints from the store, it asks for nothing" );
  h.press( "creator" );
  assert.deepEqual( h.groups(), [ "Mr Radio", "Rachel", "Sam" ] );
  assert.deepEqual( pressed( h.root ), [ "creator" ] );
} );

test( "pane: the choice is saved and a fresh mount restores it", () => {
  const first = mount();
  first.press( "assignee" );
  assert.equal( window.localStorage.getItem( HOLDING_GROUP_BY_STORAGE_KEY ), "assignee" );
  const second = mount();
  assert.deepEqual( second.groups(), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  assert.deepEqual( pressed( second.root ), [ "assignee" ] );
} );

test( "pane: pressing the button already pressed changes nothing", () => {
  const h = mount();
  h.press( "creator" );
  assert.deepEqual( h.groups(), [ "Mr Radio", "Rachel", "Sam" ] );
  assert.equal( window.localStorage.getItem( HOLDING_GROUP_BY_STORAGE_KEY ), null );
} );

test( "pane: with storage blocked the toggle still works for this page view", () => {
  const real = Object.getOwnPropertyDescriptor( window, "localStorage" )!;
  Object.defineProperty( window, "localStorage", { configurable: true, get() { throw new Error( "blocked" ); } } );
  try {
    const h = mount();
    h.press( "assignee" );
    assert.deepEqual( h.groups(), [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ] );
  } finally {
    Object.defineProperty( window, "localStorage", real );
  }
} );

test( "pane: Approve all in an assignee group reaches that assignee's rows, not the creator's", async () => {
  const h = mount();
  h.press( "assignee" );
  const group = h.root.querySelector<HTMLElement>( '.holding-area-group[data-filer="Maria"]' )!;
  const btn   = group.querySelector<HTMLButtonElement>( ".holding-approve-all" )!;
  btn.click();                       // arms
  btn.click();                       // confirms
  await new Promise( ( r ) => setTimeout( r, 50 ) );
  assert.deepEqual( h.calls.filter( ( c ) => c.includes( "->" ) ).sort(), [ "r1->queued", "r3->queued" ] );
} );
