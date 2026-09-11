// Promote/demote requests — the chip, the badge and the verdict controller (row c9fafb9d).
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE CONTROLLER'S TESTS CLICK REAL BUTTONS INSIDE A REAL CHIP. The chip's data attributes
// are the only thing the click reads, so a test that called `send` with an id would pass
// against a chip that carried none.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  renderRequestChip,
  renderRequestBadge,
  paintRequestBadge,
  triageDayToIso,
  createRequestChipController,
  wireRequestPane,
  REQUEST_DETAIL_LOADING,
  REQUEST_DETAIL_UNKNOWN,
  REQUEST_VERDICT_SENDING,
  type RequestBoardStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/requestChips";
import type { RequestFiledDetail, RequestVerdictResult } from "../../../../lupin_app/static/js/multiplexer/stores/TaskRequestStore";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import { DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE } from "../../../../lupin_app/static/js/shared/task-request.js";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const NOW  = Date.parse( "2026-09-10T12:00:00Z" );
const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

function pending( move: string, id = "row-1", ts: string | null = "2026-09-10T09:00:00Z" ): TaskItem {
  return { id, title: "t", status: "queued", request_state: "pending", request_move: move, request_ts: ts };
}

interface FakeStore extends RequestBoardStoreLike {
  verdicts : Array<{ id: string; body: Record<string, unknown> }>;
  loads    : string[];
  details  : Map<string, RequestFiledDetail>;
  answer   : RequestVerdictResult;
  release  : ( () => void ) | null;
  holdVerdict : boolean;
  countsValue : Record<string, unknown> | null;
}

function fakeStore(): FakeStore {
  const s: FakeStore = {
    verdicts: [], loads: [], details: new Map(), answer: { ok: true }, release: null, holdVerdict: false,
    countsValue: null,
    counts: () => s.countsValue,
    async submitVerdict( id, body ) {
      s.verdicts.push( { id, body } );
      if ( s.holdVerdict ) await new Promise<void>( ( r ) => { s.release = r; } );
      return s.answer;
    },
    cachedDetail: ( id, ts ) => s.details.get( `${ id }@${ ts }` ),
    async loadDetail( id, ts ) { s.loads.push( `${ id }@${ ts }` ); },
  };
  return s;
}

function mountChip( task: TaskItem ): { container: HTMLElement; chip: HTMLElement } {
  const container = document.createElement( "div" );
  const chip = renderRequestChip( task, NOW )!;
  container.appendChild( chip );
  return { container, chip };
}

const statusOf = ( chip: HTMLElement ): string => chip.querySelector( ".task-request-status" )!.textContent ?? "";
const detailOf = ( chip: HTMLElement ): string => chip.querySelector( ".task-request-detail" )!.textContent ?? "";

// ---------------------------------------------------------------------------
// The chip template
// ---------------------------------------------------------------------------

test( "a pending admit chip carries the row's id, move and filing time, its age, and both buttons", () => {
  const chip = renderRequestChip( pending( "admit" ), NOW )!;
  assert.equal( chip.className, "task-request-chip" );
  assert.equal( chip.dataset.taskId, "row-1" );
  assert.equal( chip.dataset.requestMove, "admit" );
  assert.equal( chip.dataset.requestTs, "2026-09-10T09:00:00Z" );
  assert.equal( chip.querySelector( ".task-request-text" )!.textContent, "⏳ Promote requested · 3h" );
  assert.equal( chip.querySelector( ".task-request-approve" )!.textContent, "Approve" );
  assert.equal( chip.querySelector( ".task-request-deny" )!.textContent, "Deny" );
  assert.equal( chip.querySelector( ".task-request-triage" ), null, "an admit needs no triage date" );
} );

test( "a demote chip asks for the triage-by date the demote verb asks for", () => {
  const date = renderRequestChip( pending( "demote" ), NOW )!.querySelector<HTMLInputElement>( ".task-request-triage" )!;
  assert.equal( date.type, "date" );
  assert.equal( date.getAttribute( "aria-label" ), "Triage this by" );
} );

test( "a chip with no filing time or id shows no age and carries empty anchors, never undefined", () => {
  const chip = renderRequestChip( { request_state: "pending", request_move: "admit", request_ts: null }, NOW )!;
  assert.equal( chip.querySelector( ".task-request-text" )!.textContent, "⏳ Promote requested" );
  assert.equal( chip.dataset.taskId, "" );
  assert.equal( chip.dataset.requestTs, "" );
} );

test( "no chip for a row with nothing pending", () => {
  assert.equal( renderRequestChip( { id: "x", request_state: "denied", request_move: "admit" }, NOW ), null );
} );

// ---------------------------------------------------------------------------
// The badge
// ---------------------------------------------------------------------------

test( "a badge is hidden until its own count is positive, and reads only its own key", () => {
  const badge = renderRequestBadge( "b" );
  assert.equal( badge.getAttribute( "data-testid" ), "b" );
  assert.equal( badge.hidden, true );
  paintRequestBadge( badge, { holding_area: 2, task_area: 0 }, "holding_area" );
  assert.deepEqual( [ badge.textContent, badge.hidden ], [ "2 requests", false ] );
  paintRequestBadge( badge, { holding_area: 2, task_area: 0 }, "task_area" );
  assert.deepEqual( [ badge.textContent, badge.hidden ], [ "", true ] );
} );

test( "wireRequestPane places the badge after the count chip and repaints it on every badge poll until disposed", () => {
  const bus   = createEventBusForTesting();
  const store = fakeStore();
  store.countsValue = { task_area: 1, holding_area: 0 };
  const h3 = document.createElement( "h3" );
  const countEl = document.createElement( "span" );
  h3.appendChild( countEl );
  const wiring = wireRequestPane( { bus, store, countEl, badgeKey: "task_area", testid: "tl-badge" } );
  const badge = countEl.nextElementSibling as HTMLElement;
  assert.equal( badge.getAttribute( "data-testid" ), "tl-badge" );
  assert.equal( badge.textContent, "1 request" );

  store.countsValue = { task_area: 4, holding_area: 9 };
  bus.emit( { type: "store_request_badges_changed", payload: { known: true }, source: "t", ts: 0 } );
  assert.equal( badge.textContent, "4 requests" );

  wiring.dispose();
  store.countsValue = { task_area: 0, holding_area: 0 };
  bus.emit( { type: "store_request_badges_changed", payload: { known: true }, source: "t", ts: 0 } );
  assert.equal( badge.textContent, "4 requests", "a disposed pane no longer listens" );

  // The wiring's click and hydrate are the controller's own.
  const { container, chip } = mountChip( pending( "admit" ) );
  wiring.hydrate( container );
  assert.equal( detailOf( chip ), REQUEST_DETAIL_LOADING );
  assert.equal( wiring.handleClick( chip.querySelector( ".task-request-deny" ) ), true );
} );

// ---------------------------------------------------------------------------
// The triage-date conversion
// ---------------------------------------------------------------------------

test( "a triage day becomes 09:00 LOCAL as an instant; a blank or garbage day becomes null", () => {
  assert.equal( triageDayToIso( "2026-09-17" ), new Date( "2026-09-17T09:00:00" ).toISOString() );
  assert.equal( triageDayToIso( "" ), null );
  assert.equal( triageDayToIso( "not-a-day" ), null );
} );

// ---------------------------------------------------------------------------
// The controller — clicks
// ---------------------------------------------------------------------------

test( "a click that is not on a chip button is not the controller's", () => {
  const c = createRequestChipController( fakeStore() );
  assert.equal( c.handleClick( null ), false );
  assert.equal( c.handleClick( {} as EventTarget ), false, "a target that is not an element" );
  assert.equal( c.handleClick( document.createElement( "button" ) ), false );
} );

test( "Approve on an admit sends approved, and a landed verdict leaves no status line", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { chip } = mountChip( pending( "admit" ) );
  assert.equal( c.handleClick( chip.querySelector( ".task-request-approve" ) ), true );
  await tick();
  assert.deepEqual( store.verdicts, [ { id: "row-1", body: { verdict: "approved" } } ] );
  assert.equal( statusOf( chip ), "" );
} );

test( "Deny on a demote sends denied and needs no date", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { chip } = mountChip( pending( "demote" ) );
  c.handleClick( chip.querySelector( ".task-request-deny" ) );
  await tick();
  assert.deepEqual( store.verdicts, [ { id: "row-1", body: { verdict: "denied" } } ] );
} );

test( "Approve on a demote WITHOUT a date is refused in the page and sends nothing", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { chip } = mountChip( pending( "demote" ) );
  c.handleClick( chip.querySelector( ".task-request-approve" ) );
  await tick();
  assert.deepEqual( store.verdicts, [] );
  assert.equal( statusOf( chip ), DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE );
} );

test( "Approve on a demote WITH a date sends it as next_chase_ts at 09:00 local", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { chip } = mountChip( pending( "demote" ) );
  chip.querySelector<HTMLInputElement>( ".task-request-triage" )!.value = "2026-09-17";
  c.handleClick( chip.querySelector( ".task-request-approve" ) );
  await tick();
  assert.deepEqual( store.verdicts, [ { id: "row-1", body: {
    verdict: "approved", next_chase_ts: new Date( "2026-09-17T09:00:00" ).toISOString() } } ] );
} );

test( "a verdict in flight disables both buttons, shows Sending…, and a second press is ignored", async () => {
  const store = fakeStore();
  store.holdVerdict = true;
  const c = createRequestChipController( store );
  const { chip } = mountChip( pending( "admit" ) );
  const approve = chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!;
  const deny    = chip.querySelector<HTMLButtonElement>( ".task-request-deny" )!;
  c.handleClick( approve );
  await tick();
  assert.equal( statusOf( chip ), REQUEST_VERDICT_SENDING );
  assert.deepEqual( [ approve.disabled, deny.disabled ], [ true, true ] );
  c.handleClick( deny );
  await tick();
  assert.equal( store.verdicts.length, 1 );
  store.release!();
  await tick();
  assert.deepEqual( [ approve.disabled, deny.disabled ], [ false, false ] );
} );

test( "an idless chip sends nothing", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { chip } = mountChip( { request_state: "pending", request_move: "admit" } );
  c.handleClick( chip.querySelector( ".task-request-deny" ) );
  await tick();
  assert.deepEqual( store.verdicts, [] );
} );

test( "a hand-built chip with no data attributes sends nothing, whichever button is pressed", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const chip = document.createElement( "div" );
  chip.className = "task-request-chip";
  const approve = document.createElement( "button" );
  approve.className = "task-request-approve";
  chip.appendChild( approve );
  assert.equal( c.handleClick( approve ), true );
  await tick();
  assert.deepEqual( store.verdicts, [] );
} );

test( "a demote chip whose date box is gone reads as no date, and refuses", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { chip } = mountChip( pending( "demote" ) );
  chip.querySelector( ".task-request-triage" )!.remove();
  c.handleClick( chip.querySelector( ".task-request-approve" ) );
  await tick();
  assert.deepEqual( store.verdicts, [] );
  assert.equal( statusOf( chip ), DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE );
} );

test( "a refusal is painted verbatim AND survives a repaint; a later success clears it", async () => {
  const store = fakeStore();
  store.answer = { ok: false, message: "only Rick answers a request" };
  const c = createRequestChipController( store );
  const first = mountChip( pending( "admit" ) );
  c.handleClick( first.chip.querySelector( ".task-request-approve" ) );
  await tick();
  assert.equal( statusOf( first.chip ), "only Rick answers a request" );

  // The 60s poll rebuilds the chip from scratch; hydrate puts the sentence back.
  const repainted = mountChip( pending( "admit" ) );
  c.hydrate( repainted.container );
  assert.equal( statusOf( repainted.chip ), "only Rick answers a request" );

  store.answer = { ok: true };
  c.handleClick( repainted.chip.querySelector( ".task-request-approve" ) );
  await tick();
  const again = mountChip( pending( "admit" ) );
  c.hydrate( again.container );
  assert.equal( statusOf( again.chip ), "" );
} );

test( "a chip whose status or detail span is missing is painted without a throw", async () => {
  const store = fakeStore();
  store.answer = { ok: false, message: "no" };
  const c = createRequestChipController( store );
  const { container, chip } = mountChip( pending( "admit" ) );
  chip.querySelector( ".task-request-status" )!.remove();
  chip.querySelector( ".task-request-detail" )!.remove();
  c.handleClick( chip.querySelector( ".task-request-approve" ) );
  await tick();
  c.hydrate( container );
  await tick();
  assert.equal( store.verdicts.length, 1 );
} );

// ---------------------------------------------------------------------------
// The controller — hydrate
// ---------------------------------------------------------------------------

test( "hydrate paints a cached filer and reason without reading the trail again", () => {
  const store = fakeStore();
  store.details.set( "row-1@2026-09-10T09:00:00Z", { filer: "mr radio 52f3fe21", reason: "stale for a week" } );
  const c = createRequestChipController( store );
  const { container, chip } = mountChip( pending( "admit" ) );
  c.hydrate( container );
  assert.equal( detailOf( chip ), "by mr radio 52f3fe21 — stale for a week" );
  assert.deepEqual( store.loads, [] );
} );

test( "hydrate names what is missing: no filing, a blank filer, a blank reason, or both blank", () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const cases: Array<[ RequestFiledDetail, string ]> = [
    [ null,                                  REQUEST_DETAIL_UNKNOWN ],
    [ { filer: "",      reason: "why" },     "why" ],
    [ { filer: "cheech", reason: "" },       "by cheech" ],
    [ { filer: "",      reason: "" },        REQUEST_DETAIL_UNKNOWN ],
  ];
  for ( const [ detail, expected ] of cases ) {
    store.details.set( "row-1@2026-09-10T09:00:00Z", detail );
    const { container, chip } = mountChip( pending( "admit" ) );
    c.hydrate( container );
    assert.equal( detailOf( chip ), expected, JSON.stringify( detail ) );
  }
} );

test( "an uncached chip reads loading, asks the trail once, then paints what arrived onto the same chip", async () => {
  const store = fakeStore();
  store.loadDetail = async ( id, ts ) => {
    store.loads.push( `${ id }@${ ts }` );
    store.details.set( `${ id }@${ ts }`, { filer: "maría", reason: "done upstream" } );
  };
  const c = createRequestChipController( store );
  const { container, chip } = mountChip( pending( "demote" ) );
  c.hydrate( container );
  assert.equal( detailOf( chip ), REQUEST_DETAIL_LOADING );
  await tick();
  assert.deepEqual( store.loads, [ "row-1@2026-09-10T09:00:00Z" ] );
  assert.equal( detailOf( chip ), "by maría — done upstream" );
} );

test( "a failed trail read leaves the chip reading loading, for the next paint to retry", async () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const { container, chip } = mountChip( pending( "admit" ) );
  c.hydrate( container );
  await tick();
  assert.equal( detailOf( chip ), REQUEST_DETAIL_LOADING );
} );

test( "hydrate reads an idless, timeless chip under empty keys rather than 'undefined'", () => {
  const store = fakeStore();
  const c = createRequestChipController( store );
  const container = document.createElement( "div" );
  const chip = document.createElement( "div" );
  chip.className = "task-request-chip";
  container.appendChild( chip );
  c.hydrate( container );
  assert.deepEqual( store.loads, [ "@" ] );
} );
