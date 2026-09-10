// Rick's New Ticket card — the shared module BOTH clients render through (row c9895403).
//
// WHAT THIS FILE IS REALLY GUARDING:
//   1. HIS RULINGS ARE THE DEFAULTS — P2, approved (live board), by keypress 2026-09-10.
//   2. A 2xx IS NOT ALWAYS "CREATED". A petitioned row exists and was granted nothing;
//      calling it created is the 202-reads-as-approval trap one status code over.
//   3. THE CARD REFUSES NOTHING SILENTLY AND LOSES NOTHING TYPED. Every failure keeps
//      the card open with his text intact and says which failure it was.
//
// Run: npx tsx --test src/tests/unit/shared/task_create.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  NEW_TICKET_FIELDS,
  NEW_TICKET_DEFAULTS,
  NEW_TICKET_CREATED_BY,
  NEW_TICKET_TITLE_REQUIRED_MESSAGE,
  NEW_TICKET_OVERLAY_ID,
  NEW_TICKET_NO_ANSWER_MESSAGE,
  NEW_TICKET_PRIORITIES,
  NEW_TICKET_TYPES,
  buildNewTicketPayload,
  detailFrom,
  describeNewTicketResult,
  assigneeOptions,
  openNewTicketCard,
  closeNewTicketCard,
  type NewTicketPayload,
  type NewTicketTransportResult,
} from "../../../lupin_app/static/js/shared/task-create.js";
import {
  TASK_LOOKUP_AUTH_REQUIRED_MESSAGE,
} from "../../../lupin_app/static/js/shared/task-lookup.js";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => {
  closeNewTicketCard();
  document.body.replaceChildren();
} );

const QUEUED_ROW = { id: "c9895403-fee8-448d-8f4b-ff49c4941bf7", status: "queued", title: "A ticket" };

/** Records every payload sent, and answers with whatever the arm needs. */
function recordingPost( answer: NewTicketTransportResult | Error ) {
  const sent: NewTicketPayload[] = [];
  const postTicket = ( payload: NewTicketPayload ): Promise<NewTicketTransportResult> => {
    sent.push( payload );
    return answer instanceof Error ? Promise.reject( answer ) : Promise.resolve( answer );
  };
  return { sent, postTicket };
}

const tick = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );

function key( init: KeyboardEventInit ): void {
  document.dispatchEvent( new KeyboardEvent( "keydown", { bubbles: true, ...init } ) );
}

// ---------------------------------------------------------------------------
// 1. His rulings
// ---------------------------------------------------------------------------

test( "the defaults are Rick's rulings — P2, approved — plus the epic key the store requires", () => {
  assert.deepEqual( { ...NEW_TICKET_DEFAULTS }, {
    priority: "P2", approved: true, item_class: "task", project: "lupin", correlation_key: "epic:unassigned",
  } );
} );

test( "created_by is exactly 'rick', so an unassigned row is owned by rick and not by a door name", () => {
  assert.equal( NEW_TICKET_CREATED_BY, "rick" );
} );

test( "the card offers Title and Details first, and every other editor field he named", () => {
  assert.deepEqual( [ ...NEW_TICKET_FIELDS ], [
    "title", "details", "owner_persona", "accountable_manager",
    "priority", "approved", "item_class", "correlation_key", "project",
  ] );
} );

// ---------------------------------------------------------------------------
// The payload
// ---------------------------------------------------------------------------

test( "a blank title is refused and produces no payload at all", () => {
  for ( const title of [ "", "   ", undefined, 5 ] ) {
    const built = buildNewTicketPayload( { title } );
    assert.deepEqual( built, { ok: false, error: NEW_TICKET_TITLE_REQUIRED_MESSAGE } );
  }
} );

test( "an approved minimal ticket goes straight onto the board", () => {
  assert.deepEqual( buildNewTicketPayload( { title: "  Fix the thing  " } ), {
    ok      : true,
    payload : {
      item_class : "task", title: "Fix the thing", project: "lupin",
      created_by : "rick", priority: "P2", status: "queued", correlation_key: "epic:unassigned",
    },
  } );
} );

test( "Not approved mints into the holding area — a real choice, not the default", () => {
  const built = buildNewTicketPayload( { title: "Park this", approved: false } );
  assert.ok( built.ok );
  assert.equal( built.payload.status, "not_approved" );
} );

test( "Details travels as body; blank Details and blank optionals are omitted", () => {
  const full = buildNewTicketPayload( {
    title : "T", details: "  background  ", owner_persona: " maria ",
    accountable_manager: "mr radio", correlation_key: "epic:x", project: " cosa ",
    priority: "P0", item_class: "bug",
  } );
  assert.ok( full.ok );
  assert.deepEqual( full.payload, {
    item_class : "bug", title: "T", project: "cosa", created_by: "rick", priority: "P0",
    status     : "queued", body: "background", owner_persona: "maria",
    accountable_manager: "mr radio", correlation_key: "epic:x",
  } );

  const bare = buildNewTicketPayload( { title: "T", details: "  ", owner_persona: "", project: "   ", correlation_key: " " } );
  assert.ok( bare.ok );
  for ( const absent of [ "body", "owner_persona", "accountable_manager" ] ) {
    assert.ok( !( absent in bare.payload ), `${ absent } should be omitted when blank` );
  }
  assert.equal( bare.payload.project, "lupin" );
  // 🔴 NEVER OMITTED: the store's epic-key guard answers 422 to a create without one.
  assert.equal( bare.payload.correlation_key, "epic:unassigned" );
} );

test( "an unknown priority or type is refused, naming the value", () => {
  assert.deepEqual( buildNewTicketPayload( { title: "T", priority: "P9" } ), { ok: false, error: 'Unknown priority "P9".' } );
  assert.deepEqual( buildNewTicketPayload( { title: "T", item_class: "epic" } ), { ok: false, error: 'Unknown ticket type "epic".' } );
} );

// ---------------------------------------------------------------------------
// 2. The outcome
// ---------------------------------------------------------------------------

test( "detailFrom reads the server's refusal in every shape it arrives in", () => {
  assert.equal( detailFrom( JSON.stringify( { detail: "Creating a ticket at P0 is reserved" } ) ), "Creating a ticket at P0 is reserved" );
  assert.equal( detailFrom( { detail: "object detail" } ), "object detail" );
  assert.equal(
    detailFrom( JSON.stringify( { detail: [ { msg: "field required" }, { loc: [ "title" ] } ] } ) ),
    'field required; {"loc":["title"]}',
  );
  assert.equal( detailFrom( "  Internal Server Error  " ), "Internal Server Error" );
  assert.equal( detailFrom( JSON.stringify( { nope: 1 } ) ), "" );
  assert.equal( detailFrom( "42" ), "" );
  assert.equal( detailFrom( null ), "" );
  assert.equal( detailFrom( undefined ), "" );
} );

test( "a 2xx row on the board is 'created', names the short id, and hands the row back", () => {
  const outcome = describeNewTicketResult( 201, QUEUED_ROW );
  assert.equal( outcome.state, "created" );
  assert.equal( outcome.text, "Created c9895403 — on the board." );
  assert.equal( outcome.row, QUEUED_ROW );
} );

test( "a created row in the holding area says so", () => {
  assert.equal( describeNewTicketResult( 201, { id: "abcdef12-x", status: "not_approved" } ).text,
    "Created abcdef12 — in the holding area." );
} );

test( "🔴 a 201 carrying a petition is NOT created — nothing was granted", () => {
  const outcome = describeNewTicketResult( 201, { ...QUEUED_ROW, status: "not_approved", petition: { ticket_id: "t" } } );
  assert.equal( outcome.state, "petition" );
  assert.match( outcome.text, /not on the board yet/ );
} );

test( "a 2xx with a body that is not a row still reports created, with no id to name", () => {
  const outcome = describeNewTicketResult( 200, null );
  assert.equal( outcome.state, "created" );
  assert.equal( outcome.text, "Created  — in the holding area." );
  assert.deepEqual( outcome.row, {} );
} );

test( "every failure is its own state, in the words the lookup box already uses", () => {
  assert.deepEqual( describeNewTicketResult( 401, "" ), { state: "auth_required", text: TASK_LOOKUP_AUTH_REQUIRED_MESSAGE, row: null } );
  assert.deepEqual( describeNewTicketResult( 403, '{"detail":"no"}' ), { state: "refused", text: "no", row: null } );
  assert.deepEqual( describeNewTicketResult( 403, "" ), { state: "refused", text: "The store refused this ticket.", row: null } );
  assert.deepEqual( describeNewTicketResult( 422, '{"detail":"bad"}' ), { state: "invalid", text: "bad", row: null } );
  assert.deepEqual( describeNewTicketResult( 422, undefined ), { state: "invalid", text: "The store could not accept this ticket.", row: null } );
} );

test( "a status the card has no name for still shows the server's own words and the code", () => {
  // María's review, follow-up 1: a 500 carrying a real cause used to read "try again".
  assert.deepEqual( describeNewTicketResult( 500, '{"detail":"database is locked"}' ),
    { state: "failed", text: "The store answered 500: database is locked", row: null } );
  assert.deepEqual( describeNewTicketResult( 409, "conflict on title" ),
    { state: "failed", text: "The store answered 409: conflict on title", row: null } );
  assert.deepEqual( describeNewTicketResult( 429, "" ),
    { state: "failed", text: "The store answered 429 and gave no reason.", row: null } );
} );

test( "no answer at all warns the ticket may already be saved, so a retry is not a blind duplicate", () => {
  // María's review, follow-up 2: a POST can time out after the store saved the row.
  assert.deepEqual( describeNewTicketResult( 0, undefined ), {
    state : "unreachable",
    text  : "The store did not answer, so this ticket may already be saved. Search Find for its title before you try again.",
    row   : null,
  } );
} );

test( "the priority and type menus, and the no-answer sentence, are pinned to literals", () => {
  assert.deepEqual( [ ...NEW_TICKET_PRIORITIES ], [ "P0", "P1", "P2", "P3", "P4", "P5" ] );
  assert.deepEqual( [ ...NEW_TICKET_TYPES ], [ "task", "bug", "decision" ] );
  assert.ok( Object.isFrozen( NEW_TICKET_PRIORITIES ), "a caller cannot add a priority the store refuses" );
  assert.ok( Object.isFrozen( NEW_TICKET_TYPES ), "a caller cannot add a type the store refuses" );
  assert.equal( NEW_TICKET_NO_ANSWER_MESSAGE,
    "The store did not answer, so this ticket may already be saved. Search Find for its title before you try again." );
} );

test( "assigneeOptions merges lists once each, trimmed and sorted, dropping blanks and non-strings", () => {
  assert.deepEqual( assigneeOptions( [ "maria", " mr radio ", null ], [ "maria", "", 7, "cheech" ] ), [ "cheech", "maria", "mr radio" ] );
  assert.deepEqual( assigneeOptions(), [] );
} );

// ---------------------------------------------------------------------------
// The card
// ---------------------------------------------------------------------------

test( "the card renders every field exactly once, in order, with Rick's defaults", () => {
  const card = openNewTicketCard( { postTicket: recordingPost( { status: 201, body: QUEUED_ROW } ).postTicket } );
  const fields = Array.from( card.overlay.querySelectorAll( "[data-field]" ) ).map( ( el ) => el.getAttribute( "data-field" ) );
  assert.deepEqual( fields, [ ...NEW_TICKET_FIELDS ] );
  assert.equal( card.controls.priority.value, "P2" );
  assert.equal( card.controls.approved.value, "yes" );
  assert.equal( card.controls.item_class.value, "task" );
  assert.equal( card.controls.project.value, "lupin" );
  assert.equal( card.controls.correlation_key.value, "epic:unassigned", "pre-filled and visible, not added silently" );
  assert.equal( document.activeElement, card.controls.title, "the title takes focus so he can start typing" );
  assert.equal( card.overlay.getAttribute( "data-testid" ), "new-ticket" );
  assert.equal( card.controls.details.tagName, "TEXTAREA" );
  assert.equal( document.querySelector( "label[for='new-ticket-details']" )?.textContent, "Details" );
} );

test( "Assigned to and Accountable manager offer the roster; no roster means an empty list", () => {
  const card = openNewTicketCard( { postTicket: recordingPost( { status: 201 } ).postTicket, assignees: [ "cheech", "maria" ], testidPrefix: "x" } );
  const listId = card.controls.owner_persona.getAttribute( "list" );
  assert.equal( listId, "x-assignees" );
  assert.equal( card.controls.accountable_manager.getAttribute( "list" ), listId );
  const names = Array.from( document.querySelectorAll( `#${ listId } option` ) ).map( ( o ) => ( o as HTMLOptionElement ).value );
  assert.deepEqual( names, [ "cheech", "maria" ] );

  const empty = openNewTicketCard( { postTicket: recordingPost( { status: 201 } ).postTicket } );
  assert.equal( empty.overlay.querySelectorAll( "datalist option" ).length, 0 );
} );

test( "a second open replaces the first — exactly one card", () => {
  openNewTicketCard( { postTicket: recordingPost( { status: 201 } ).postTicket } );
  openNewTicketCard( { postTicket: recordingPost( { status: 201 } ).postTicket } );
  assert.equal( document.querySelectorAll( `#${ NEW_TICKET_OVERLAY_ID }` ).length, 1 );
} );

test( "a blank title is refused WITHOUT a request", async () => {
  const { sent, postTicket } = recordingPost( { status: 201, body: QUEUED_ROW } );
  const card = openNewTicketCard( { postTicket } );
  await card.submit();
  assert.equal( sent.length, 0 );
  assert.equal( card.result.getAttribute( "data-state" ), "invalid-form" );
  assert.equal( card.result.textContent, NEW_TICKET_TITLE_REQUIRED_MESSAGE );
} );

test( "a created ticket closes the card and hands the row to onCreated", async () => {
  const { sent, postTicket } = recordingPost( { status: 201, body: QUEUED_ROW } );
  const created: Record<string, unknown>[] = [];
  const card = openNewTicketCard( { postTicket, onCreated: ( row ) => created.push( row ) } );
  card.controls.title.value    = "Rick's ticket";
  card.controls.details.value  = "Here is the background.";
  card.controls.priority.value = "P0";
  await card.submit();
  assert.equal( sent.length, 1 );
  assert.equal( sent[ 0 ].priority, "P0" );
  assert.equal( sent[ 0 ].body, "Here is the background." );
  assert.equal( sent[ 0 ].status, "queued" );
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );
  assert.deepEqual( created, [ QUEUED_ROW ] );
} );

test( "Not approved in the card sends not_approved", async () => {
  const { sent, postTicket } = recordingPost( { status: 201, body: { ...QUEUED_ROW, status: "not_approved" } } );
  const card = openNewTicketCard( { postTicket } );
  card.controls.title.value = "Hold this";
  card.controls.approved.value = "no";
  await card.submit();
  assert.equal( sent[ 0 ].status, "not_approved" );
} );

test( "a created ticket with no onCreated still closes without throwing", async () => {
  const card = openNewTicketCard( { postTicket: recordingPost( { status: 201, body: QUEUED_ROW } ).postTicket } );
  card.controls.title.value = "T";
  await card.submit();
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );
} );

test( "a petition keeps the card open and does not call onCreated", async () => {
  let called = false;
  const card = openNewTicketCard( {
    postTicket: recordingPost( { status: 201, body: { ...QUEUED_ROW, petition: {} } } ).postTicket,
    onCreated : () => { called = true; },
  } );
  card.controls.title.value = "T";
  await card.submit();
  assert.ok( document.getElementById( NEW_TICKET_OVERLAY_ID ) );
  assert.equal( card.result.getAttribute( "data-state" ), "petition" );
  assert.equal( called, false );
} );

test( "a refusal keeps the card open, shows the server's detail, and keeps what he typed", async () => {
  const card = openNewTicketCard( { postTicket: recordingPost( { status: 422, text: '{"detail":"ratio gate says no"}' } ).postTicket } );
  card.controls.title.value   = "Keep me";
  card.controls.details.value = "and me";
  await card.submit();
  assert.equal( card.result.getAttribute( "data-state" ), "invalid" );
  assert.equal( card.result.textContent, "ratio gate says no" );
  assert.equal( card.controls.title.value, "Keep me" );
  assert.equal( card.controls.details.value, "and me" );
  assert.equal( card.createButton.disabled, false, "he can try again" );
} );

test( "a transport that rejects reads as the store not answering, and the card recovers", async () => {
  const card = openNewTicketCard( { postTicket: recordingPost( new Error( "network" ) ).postTicket } );
  card.controls.title.value = "T";
  await card.submit();
  assert.equal( card.result.getAttribute( "data-state" ), "unreachable" );
  assert.equal( card.result.textContent,
    "The store did not answer, so this ticket may already be saved. Search Find for its title before you try again." );
  assert.equal( card.createButton.disabled, false );
} );

test( "a second submit while the first is in flight sends nothing", async () => {
  const sent: NewTicketPayload[] = [];
  let release: ( r: NewTicketTransportResult ) => void = () => {};
  const postTicket = ( payload: NewTicketPayload ): Promise<NewTicketTransportResult> => {
    sent.push( payload );
    return new Promise( ( res ) => { release = res; } );
  };
  const card = openNewTicketCard( { postTicket } );
  card.controls.title.value = "T";
  const first = card.submit();
  assert.equal( card.result.getAttribute( "data-state" ), "pending" );
  assert.equal( card.createButton.disabled, true );
  await card.submit();
  assert.equal( sent.length, 1 );
  release( { status: 201, body: QUEUED_ROW } );
  await first;
} );

test( "Escape, Cancel and the backdrop close without sending; a click inside the card does not close it", () => {
  const { sent, postTicket } = recordingPost( { status: 201, body: QUEUED_ROW } );

  let card = openNewTicketCard( { postTicket } );
  card.overlay.querySelector<HTMLElement>( ".new-ticket-card" )!.click();
  assert.ok( document.getElementById( NEW_TICKET_OVERLAY_ID ), "a click inside the card must not close it" );
  key( { key: "Escape" } );
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );

  card = openNewTicketCard( { postTicket } );
  card.overlay.querySelector<HTMLButtonElement>( "[data-testid='new-ticket-cancel']" )!.click();
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );

  card = openNewTicketCard( { postTicket } );
  card.overlay.click();
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );

  card = openNewTicketCard( { postTicket } );
  card.close();
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );
  assert.equal( sent.length, 0 );
} );

test( "Ctrl+Enter, Cmd+Enter and Create submit; a plain Enter and other keys do not", async () => {
  const { sent, postTicket } = recordingPost( { status: 422, text: "" } );
  const card = openNewTicketCard( { postTicket } );
  card.controls.title.value = "T";

  key( { key: "Enter" } );
  key( { key: "a", ctrlKey: true } );
  await tick();
  assert.equal( sent.length, 0 );

  key( { key: "Enter", ctrlKey: true } );
  await tick();
  key( { key: "Enter", metaKey: true } );
  await tick();
  card.createButton.click();
  await tick();
  assert.equal( sent.length, 3 );
} );

test( "closing detaches the key listener, and closing with no card open is harmless", async () => {
  const { sent, postTicket } = recordingPost( { status: 201, body: QUEUED_ROW } );
  const card = openNewTicketCard( { postTicket } );
  card.controls.title.value = "T";
  card.close();
  key( { key: "Enter", ctrlKey: true } );
  await tick();
  assert.equal( sent.length, 0 );
  assert.doesNotThrow( () => closeNewTicketCard() );
} );

// The `window` bridge is tested in task_create_window_bridge.test.ts, NOT here: this file
// imports the module statically, which evaluates it before happy-dom registers, so the
// bridge never runs in this process. Measured — the arm failed twice here, once because of
// that and once because a `?query` re-import returned the same cached instance.
