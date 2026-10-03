// Holding-area card — APPROVE A WHOLE STORY (row eb235858).
//
// A plan import files its rows as a batch of held rows sharing one `correlation_key`
// (the story). The pane shows one bar per story with ONE control, "Approve all N in this
// story". Driven at the layer the operator's click enters at: the REAL renderer, mounted
// into a REAL element, painting through the REAL template, clicking the REAL button.
// The store is the only fake.
//
// ⚠️ NO NEW SERVER DOOR. The control is a loop of ordinary single-row transitions, so
// "operator-only" is the server's per-row rule, unchanged. The refusal test below feeds
// the loop what a non-operator's session earns — a 403 per row — and asserts that nothing
// is silently skipped and that the bar stays for a retry.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { groupHeldRowsByStory, storyTitle } from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import { HOLDING_BATCH_ARMED_CLASS, HOLDING_BATCH_NO_ROWS_STORY } from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch";
import {
  holdingStoryApproveLabel,
  holdingStoryApproveTitle,
  renderHoldingStories,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/holdingAreaTable";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function held( id: string, key: string | null, filer = "rachel" ): TaskItem {
  return {
    id, title: `row ${ id }`, status: "not_approved", priority: "P2",
    created_by: `${ filer } 0e61abe3`, correlation_key: key,
  } as unknown as TaskItem;
}

// Rows for the shared fixture: story A has THREE rows, story C has TWO, story B has ONE,
// and "loose" has no key at all.
const ROWS = (): TaskItem[] => [
  held( "a1", "epic:plan-a" ), held( "a2", "epic:plan-a" ), held( "a3", "epic:plan-a" ),
  held( "b1", "epic:plan-b" ),
  held( "c1", "epic:plan-c" ), held( "c2", "epic:plan-c" ),
  held( "x1", null ),
];

interface Harness {
  container : HTMLElement;
  calls     : Array<{ id: string; toStatus: string; extras: Record<string, string> }>;
  gate      : { release(): void } | null;
  bars      (): string[];
  button    ( key: string ): HTMLButtonElement;
  status    ( key: string ): string;
  poll      (): Promise<void>;
  dropKey   ( key: string ): void;
  restoreKey( key: string ): void;
  unmount   (): void;
}

/**
 * `verdict` decides each row's outcome. After every refresh the rows the store holds are
 * the ones the harness has not yet approved — the real store would re-read them — so a
 * refused row stays held and an approved one leaves.
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
  const container = root.querySelector( ".holding-area-container" ) as HTMLElement;
  const bar = ( key: string ): HTMLElement => {
    const b = Array.from( container.querySelectorAll<HTMLElement>( ".holding-story-bar" ) ).find( ( el ) => el.dataset.story === key );
    assert.ok( b, `no story bar for ${ key }` );
    return b;
  };
  return {
    container, calls,
    get gate() { return h.gate; },
    bars  : () => Array.from( container.querySelectorAll<HTMLElement>( ".holding-story-bar" ) ).map( ( b ) => b.dataset.story as string ),
    button: ( key ) => bar( key ).querySelector( ".holding-story-approve-all" ) as HTMLButtonElement,
    status: ( key ) => ( bar( key ).querySelector( ".holding-story-status" ) as HTMLElement ).textContent ?? "",
    poll  : async () => { await store.refresh(); },
    dropKey   : ( key ) => { rows = rows.filter( ( r ) => r.correlation_key !== key ); },
    restoreKey: ( key ) => { rows = [ ...rows, ...ROWS().filter( ( r ) => r.correlation_key === key ) ]; },
    unmount: () => renderer.unmount(),
  } as Harness;
}

const click = ( el: HTMLElement ): void => { el.dispatchEvent( new globalThis.MouseEvent( "click", { bubbles: true } ) ); };
// ARM, THEN CONFIRM (row 376dd4cb): a story runs on the SECOND press of its button.
const press = ( el: HTMLElement ): void => { click( el ); click( el ); };
const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

// ───────────────────────────── the model ─────────────────────────────

test( "model: a key held by two rows is a story, a key held by ONE is not, a keyless row never is", () => {
  const stories = groupHeldRowsByStory( ROWS() );
  assert.deepEqual( stories, [
    { key: "epic:plan-a", ids: [ "a1", "a2", "a3" ], title: "plan a", filers: [ "Rachel" ] },
    { key: "epic:plan-c", ids: [ "c1", "c2" ], title: "plan c", filers: [ "Rachel" ] },
  ] );
} );

test( "model: epic:unassigned is never a story, beside a real key that is", () => {
  const rows = [ held( "u1", "epic:unassigned" ), held( "u2", "epic:unassigned" ),
                 held( "r1", "epic:real" ), held( "r2", "epic:real" ) ];
  assert.deepEqual( groupHeldRowsByStory( rows ), [ { key: "epic:real", ids: [ "r1", "r2" ], title: "real", filers: [ "Rachel" ] } ] );
  assert.deepEqual( groupHeldRowsByStory( rows, new Set( [ "epic:unassigned" ] ) ).map( ( s ) => s.key ),
    [ "epic:real" ], "a kept report resurrected a bar over epic:unassigned" );
} );

test( "model: keep names a key that stays at ONE row, and only that key", () => {
  const stories = groupHeldRowsByStory( ROWS(), new Set( [ "epic:plan-b" ] ) );
  assert.deepEqual( stories.map( ( s ) => s.key ), [ "epic:plan-a", "epic:plan-b", "epic:plan-c" ] );
  assert.deepEqual( stories[ 1 ], { key: "epic:plan-b", ids: [ "b1" ], title: "plan b", filers: [ "Rachel" ] } );
} );

test( "model: junk in, empty out — and a row with no id cannot join a story", () => {
  assert.deepEqual( groupHeldRowsByStory( null ), [] );
  assert.deepEqual( groupHeldRowsByStory( "nope" ), [] );
  assert.deepEqual( groupHeldRowsByStory( [ null, undefined, {} ] ), [] );
  const rows = [ { correlation_key: "k" }, { id: "z1", correlation_key: "k" } ];
  assert.deepEqual( groupHeldRowsByStory( rows ), [], "an id-less row counted toward a story" );
} );

test( "model: storyTitle strips epic:, turns hyphens and underscores to spaces, never blanks a key", () => {
  assert.equal( storyTitle( "epic:v022-docs-and-reuse" ), "v022 docs and reuse" );
  assert.equal( storyTitle( "plan_x--y" ), "plan x y" );
  assert.equal( storyTitle( "epic:" ), "epic:" );
} );

test( "model: filers are the distinct, sorted persona labels of the story's rows", () => {
  const rows = [ held( "m1", "epic:mix", "zed" ), held( "m2", "epic:mix", "amy" ), held( "m3", "epic:mix", "zed" ) ];
  assert.deepEqual( groupHeldRowsByStory( rows )[ 0 ]?.filers, [ "Amy", "Zed" ] );
} );

test( "template: the bar's persona slot names the filer and the story reads as a titled story, never the raw key", () => {
  const rows  = [ held( "m1", "epic:v022-docs-and-reuse", "rachel" ), held( "m2", "epic:v022-docs-and-reuse", "sam" ) ];
  const strip = renderHoldingStories( groupHeldRowsByStory( rows ) ) as HTMLElement;
  assert.equal( strip.querySelector( ".holding-story-filer" )?.textContent, "Rachel, Sam" );
  assert.equal( strip.querySelector( ".holding-story-key" )?.textContent, "Story: v022 docs and reuse" );
  assert.ok( ! ( strip.querySelector( ".holding-story-filer" )?.textContent ?? "" ).includes( "epic:" ), "raw key in the persona slot" );
  assert.ok( ! ( strip.querySelector( ".holding-story-key" )?.textContent ?? "" ).includes( "epic:" ), "raw key in the story label" );
  assert.equal( ( strip.querySelector( ".holding-story-bar" ) as HTMLElement ).dataset.story, "epic:v022-docs-and-reuse" );
} );

test( "template: no stories renders nothing at all; the label and tooltip name N and the key", () => {
  assert.equal( renderHoldingStories( [] ), null );
  assert.equal( holdingStoryApproveLabel( 3 ), "Approve all 3 in this story" );
  assert.match( holdingStoryApproveTitle( "epic:plan-a" ), /epic:plan-a/ );
} );

// ───────────────────────────── the pane ─────────────────────────────

test( "pane: one bar per story of TWO OR MORE rows — none for the single-row key or the keyless row", () => {
  const h = mount( () => ( { ok: true } ) );
  assert.deepEqual( h.bars(), [ "epic:plan-a", "epic:plan-c" ] );
  assert.equal( h.button( "epic:plan-a" ).textContent, "Approve all 3 in this story" );
  assert.equal( h.button( "epic:plan-c" ).textContent, "Approve all 2 in this story" );
  assert.equal( h.button( "epic:plan-a" ).dataset.taskIds, "a1,a2,a3" );
  h.unmount();
} );

test( "click: ONE press sends one queued transition per row of THAT story and no other row", async () => {
  const h = mount( () => ( { ok: true } ) );
  press( h.button( "epic:plan-a" ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  assert.deepEqual( [ ...new Set( h.calls.map( ( c ) => c.toStatus ) ) ], [ "queued" ] );
  assert.deepEqual( h.calls[ 0 ]?.extras, {}, "approve posted a reason it was never asked for" );
  assert.deepEqual( h.bars(), [ "epic:plan-c" ], "the approved story's bar is still there, or another vanished" );
  h.unmount();
} );

test( "a story that ends PARTLY refused says so, and keeps its bar even down to one row", async () => {
  const refusal = "403: actor 'maria' is not in approvers ['rick']";
  const h = mount( ( id ) => id === "a2" ? { ok: false, message: refusal } : { ok: true } );
  press( h.button( "epic:plan-a" ) );
  await settle();

  // a2 is the only row of the story left — below the two-row floor — yet the bar stays.
  assert.deepEqual( h.bars(), [ "epic:plan-a", "epic:plan-c" ], "the half-approved story lost its bar" );
  assert.equal( h.status( "epic:plan-a" ), `2 of 3 approved — 1 refused. First refusal: ${ refusal }` );
  assert.equal( h.button( "epic:plan-a" ).dataset.taskIds, "a2", "the bar now offers more than the rows still held" );
  assert.equal( h.button( "epic:plan-a" ).textContent, "Approve all 1 in this story" );

  // An ordinary poll repaints; the report survives it.
  await h.poll();
  assert.match( h.status( "epic:plan-a" ), /1 refused/, "the 60s poll erased the partial-failure report" );
  assert.equal( h.status( "epic:plan-c" ), "", "a report leaked onto a story that never ran" );
  h.unmount();
} );

test( "a non-operator is refused on every row: nothing skipped, nothing approved, the bar stays", async () => {
  const h = mount( () => ( { ok: false, message: "403: 'maria' is not an approver" } ) );
  press( h.button( "epic:plan-c" ) );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "c1", "c2" ], "the loop stopped at the first refusal" );
  assert.equal( h.status( "epic:plan-c" ), "0 of 2 approved — 2 refused. First refusal: 403: 'maria' is not an approver" );
  assert.deepEqual( h.bars(), [ "epic:plan-a", "epic:plan-c" ] );
  assert.equal( h.button( "epic:plan-c" ).disabled, false, "the bar stayed dead after a refused run" );
  h.unmount();
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
  assert.deepEqual( h.bars(), [ "epic:plan-c" ], "a fully approved story kept its bar, or its report" );
  await h.poll();
  assert.deepEqual( h.bars(), [ "epic:plan-c" ], "a stale report resurrected the bar on the next poll" );
  h.unmount();
} );

test( "a second press while the story runs is ignored, and the button is dead meanwhile", async () => {
  const h = mount( () => ( { ok: true } ), true );
  const btn = h.button( "epic:plan-a" );
  press( btn );
  await settle();
  assert.equal( h.calls.length, 1, "the confirming press did not reach the store" );
  assert.equal( btn.disabled, true, "the button stayed live mid-run" );
  assert.match( h.status( "epic:plan-a" ), /^Approved 0 of 3…$/ );

  click( btn );
  await settle();
  assert.equal( h.calls.length, 1, "a second press started the story over" );

  // 🔴 THE GUARD IS THE SET, NOT THE DISABLED ATTRIBUTE: a poll tick mid-run rebuilds the
  // bar and hands the operator a FRESH, ENABLED button. A press on it must still be ignored.
  await h.poll();
  const fresh = h.button( "epic:plan-a" );
  assert.notEqual( fresh, btn, "the poll did not rebuild the bar, so this arm tests nothing" );
  assert.equal( fresh.disabled, false, "precondition: the rebuilt button is live" );
  press( fresh );
  await settle();
  assert.equal( h.calls.length, 1, "a press on the rebuilt button started the story a second time" );

  h.gate!.release();
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  h.unmount();
} );

test( "defensive presses: a bar with no ids reports it and posts nothing; one with no story key does nothing", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( "epic:plan-c" );
  btn.dataset.taskIds = "";
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0 );
  assert.equal( h.status( "epic:plan-c" ), HOLDING_BATCH_NO_ROWS_STORY );

  const other = h.button( "epic:plan-a" );
  delete other.dataset.story;
  click( other );
  await settle();
  assert.equal( h.calls.length, 0, "a key-less button posted transitions" );

  const idless = h.button( "epic:plan-c" );
  delete idless.dataset.taskIds;       // an attribute that is absent, not merely empty
  click( idless );
  await settle();
  assert.equal( h.calls.length, 0, "a button with no id list posted transitions" );
  assert.equal( h.status( "epic:plan-c" ), HOLDING_BATCH_NO_ROWS_STORY );
  h.unmount();
} );

test( "a report is dropped when its story leaves the board entirely", async () => {
  const h = mount( ( id ) => id.startsWith( "c" ) ? { ok: false, message: "no" } : { ok: true } );
  press( h.button( "epic:plan-c" ) );
  await settle();
  assert.match( h.status( "epic:plan-c" ), /2 refused/ );

  h.dropKey( "epic:plan-c" );          // someone else closed both refused rows
  await h.poll();
  assert.deepEqual( h.bars(), [ "epic:plan-a" ], "a story with no rows kept a bar on the strength of its report" );

  h.restoreKey( "epic:plan-c" );       // the same key comes back later, as a NEW story
  await h.poll();
  assert.equal( h.status( "epic:plan-c" ), "", "a dead story's report came back with its key" );
  h.unmount();
} );

test( "a refusal that carries no message still counts, and a pane unmounted mid-run does not throw", async () => {
  const h = mount( () => ( { ok: false } ), true );
  press( h.button( "epic:plan-c" ) );
  await settle();
  h.unmount();                         // the operator navigates away while row one is in flight
  h.gate!.release();
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "c1", "c2" ], "the run abandoned its rows when the pane went away" );
} );

test( "a refusal with no message reports an empty first refusal rather than 'undefined'", async () => {
  const h = mount( () => ( { ok: false } ) );
  press( h.button( "epic:plan-c" ) );
  await settle();
  assert.equal( h.status( "epic:plan-c" ), "0 of 2 approved — 2 refused. First refusal: " );
  h.unmount();
} );

// ───────────────────────── arm, then confirm (row 376dd4cb) ─────────────────────────

test( "arm: the FIRST press posts nothing, names the count on the button and says what the next press does", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( "epic:plan-a" );
  assert.equal( btn.textContent, "Approve all 3 in this story" );
  click( btn );
  await settle();
  assert.equal( h.calls.length, 0, "the first press posted a transition" );
  assert.equal( btn.textContent, "Confirm approve all 3 in this story" );
  assert.equal( btn.dataset.armed, "1" );
  assert.ok( btn.classList.contains( HOLDING_BATCH_ARMED_CLASS ), "an armed button carries the armed class" );
  assert.equal( h.status( "epic:plan-a" ), "Click again to approve 3 rows in this story." );
  h.unmount();
} );

test( "confirm: the SECOND press runs the story and the button is back to rest", async () => {
  const h = mount( () => ( { ok: true } ) );
  const btn = h.button( "epic:plan-a" );
  click( btn );
  click( btn );
  await settle();
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a1", "a2", "a3" ] );
  assert.equal( btn.dataset.armed, undefined, "the button stayed armed after it ran" );
  assert.equal( btn.classList.contains( HOLDING_BATCH_ARMED_CLASS ), false );
  h.unmount();
} );

test( "arming one story disarms the other, and clears the status line of the one it disarmed", async () => {
  const h = mount( () => ( { ok: true } ) );
  const a = h.button( "epic:plan-a" );
  const c = h.button( "epic:plan-c" );
  click( a );
  assert.equal( a.dataset.armed, "1" );
  click( c );
  assert.equal( c.dataset.armed, "1" );
  assert.equal( a.dataset.armed, undefined, "two story buttons were armed at once" );
  assert.equal( a.textContent, "Approve all 3 in this story" );
  assert.equal( h.status( "epic:plan-a" ), "", "a disarmed story kept its 'Click again' line" );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );

test( "a repaint rebuilds the bar unarmed, and the armed status line does not outlive the arming", async () => {
  const h = mount( () => ( { ok: true } ) );
  click( h.button( "epic:plan-a" ) );
  await h.poll();
  const fresh = h.button( "epic:plan-a" );
  assert.equal( fresh.dataset.armed, undefined );
  assert.equal( fresh.textContent, "Approve all 3 in this story" );
  assert.equal( h.status( "epic:plan-a" ), "" );
  click( fresh );
  await settle();
  assert.equal( h.calls.length, 0, "a press after a repaint ran the story instead of arming it" );
  h.unmount();
} );

test( "disarming tolerates an armed bar whose attributes were stripped", async () => {
  const h = mount( () => ( { ok: true } ) );
  const stray = h.button( "epic:plan-a" );
  stray.dataset.armed = "1";
  delete stray.dataset.story;               // an armed button with no story key: the status paint finds no span
  delete stray.dataset.taskIds;             // and no id list: its resting label counts 0 rows
  const c = h.button( "epic:plan-c" );
  click( c );
  assert.equal( c.dataset.armed, "1", "the real press did not arm" );
  assert.equal( stray.dataset.armed, undefined );
  assert.equal( stray.textContent, "Approve all 0 in this story" );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );
