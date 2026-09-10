// Rick's New Ticket card on the multiplexer (row c9895403) — the button, where it sits,
// the transport adapter, and what the list does once the row exists.
//
// HIS PLACEMENT, verbatim: "within the task list bar right next to the find functionality".
// So the placement is asserted as ADJACENCY to the Find box, not as "somewhere in the header".
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/task_list_renderer_new_ticket.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import {
  apiPostTicket,
  bodyOfApiErrorMessage,
  renderNewTicketButton,
} from "../../../../lupin_app/static/js/multiplexer/render/newTicketCard";
import { ApiError } from "../../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import {
  NEW_TICKET_FIELDS,
  NEW_TICKET_OVERLAY_ID,
  closeNewTicketCard,
  type NewTicketPayload,
  type NewTicketTransportResult,
} from "../../../../lupin_app/static/js/shared/task-create.js";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => {
  localStorage.clear();
  closeNewTicketCard();
  document.body.replaceChildren();
} );

const NEW_ROW: TaskItem = {
  id: "c9895403-fee8-448d-8f4b-ff49c4941bf7", title: "Rick's own ticket",
  status: "queued", owner_persona: "rick", priority: "P0",
};

const tick = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );

interface SetupOptions {
  postTicket?  : ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult>;
  withLookup?  : boolean;
}

function setup( opts: SetupOptions ) {
  const bus = createEventBusForTesting();
  let composite: TaskListComposite | null = null;
  let refreshes = 0;
  const lookups: string[] = [];
  const store = {
    composite : () => composite,
    refresh   : () => { refreshes += 1; return Promise.resolve(); },
    patchTask : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    transitionTask: () => ( { restoreState: () => {}, done: Promise.resolve() } ),
  } as never;

  const r = createTaskListRenderer( {
    eventBus   : bus,
    stores     : { taskList: store },
    nowDateFn  : () => new Date( "2026-09-10T15:00:00Z" ),
    ...( opts.withLookup === false ? {} : {
      lookupFetch: ( path: string ) => { lookups.push( path ); return Promise.resolve( NEW_ROW ); },
    } ),
    ...( opts.postTicket ? { postTicket: opts.postTicket } : {} ),
  } );
  const root = document.createElement( "div" );
  document.body.append( root );
  r.mount( root );

  const publish = ( tasks: TaskItem[] ): void => {
    composite = { tasks, count: tasks.length };
    bus.emit<StoreTaskListChangedPayload>( {
      type: "store_task_list_changed", payload: { stampUpdated: false }, source: "test", ts: 0,
    } );
  };
  const newButton = (): HTMLButtonElement | null =>
    root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-list-new-ticket']" );
  return { root, publish, newButton, lookups, refreshes: () => refreshes };
}

function recordingPost( answer: NewTicketTransportResult ) {
  const sent: NewTicketPayload[] = [];
  const postTicket = ( payload: NewTicketPayload ): Promise<NewTicketTransportResult> => {
    sent.push( payload );
    return Promise.resolve( answer );
  };
  return { sent, postTicket };
}

// ---------------------------------------------------------------------------
// Placement
// ---------------------------------------------------------------------------

test( "the New button sits directly after the Find box — where he asked for it", () => {
  const { root, newButton } = setup( { postTicket: recordingPost( { status: 201, body: NEW_ROW } ).postTicket } );
  const find = root.querySelector( "[data-testid='multiplexer-task-lookup']" );
  assert.ok( find, "the Find box must be mounted for this arm to mean anything" );
  assert.ok( newButton() );
  assert.equal( find.nextElementSibling, newButton() );
  assert.equal( newButton()!.textContent, "＋ New" );
} );

test( "no transport means no button, rather than a card that can only fail", () => {
  const { newButton } = setup( {} );
  assert.equal( newButton(), null );
} );

test( "without a Find box the button still mounts, first in the header actions", () => {
  const { root, newButton } = setup( { withLookup: false, postTicket: recordingPost( { status: 201 } ).postTicket } );
  assert.equal( root.querySelector( "[data-testid='multiplexer-task-lookup']" ), null );
  assert.ok( newButton() );
} );

// ---------------------------------------------------------------------------
// The card, through the multiplexer
// ---------------------------------------------------------------------------

test( "a click opens the shared card, with every shared field and the multiplexer's test ids", () => {
  const { newButton } = setup( { postTicket: recordingPost( { status: 201 } ).postTicket } );
  newButton()!.click();
  const overlay = document.getElementById( NEW_TICKET_OVERLAY_ID );
  assert.ok( overlay );
  assert.equal( overlay.getAttribute( "data-testid" ), "multiplexer-new-ticket" );
  const fields = Array.from( overlay.querySelectorAll( "[data-field]" ) ).map( ( el ) => el.getAttribute( "data-field" ) );
  assert.deepEqual( fields, [ ...NEW_TICKET_FIELDS ], "PARITY: the same fields as the notifications client" );
} );

test( "Assigned to offers the owners on the board, read when the card opens", () => {
  const { newButton, publish } = setup( { postTicket: recordingPost( { status: 201 } ).postTicket } );

  newButton()!.click();   // before any poll: nobody to offer
  assert.equal( document.querySelectorAll( `#${ NEW_TICKET_OVERLAY_ID } datalist option` ).length, 0 );
  closeNewTicketCard();

  publish( [
    { id: "a", title: "one",   status: "queued", owner_persona: "maria" },
    { id: "b", title: "two",   status: "queued", owner_persona: "mr radio" },
    { id: "c", title: "three", status: "queued", owner_persona: "maria" },
  ] );
  newButton()!.click();
  const names = Array.from( document.querySelectorAll( `#${ NEW_TICKET_OVERLAY_ID } datalist option` ) )
    .map( ( o ) => ( o as HTMLOptionElement ).value );
  assert.deepEqual( names, [ "maria", "mr radio" ] );
} );

test( "a created ticket refreshes the board and pins the new row through the Find box", async () => {
  const { sent, postTicket } = recordingPost( { status: 201, body: NEW_ROW } );
  const s = setup( { postTicket } );
  s.newButton()!.click();
  const title = document.querySelector<HTMLInputElement>( "[data-testid='multiplexer-new-ticket-title']" )!;
  title.value = "Rick's own ticket";
  document.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-new-ticket-create']" )!.click();
  await tick(); await tick();

  assert.equal( sent.length, 1 );
  assert.equal( s.refreshes(), 1 );
  assert.deepEqual( s.lookups, [ `/api/tasks/${ NEW_ROW.id }` ] );
  const input = s.root.querySelector<HTMLInputElement>( "[data-testid='multiplexer-task-lookup-input']" )!;
  assert.equal( input.value, NEW_ROW.id );
  const titles = Array.from( s.root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() );
  assert.deepEqual( titles, [ "Rick's own ticket" ] );
} );

test( "a created ticket with no Find box still refreshes the board", async () => {
  const s = setup( { withLookup: false, postTicket: recordingPost( { status: 201, body: NEW_ROW } ).postTicket } );
  s.newButton()!.click();
  document.querySelector<HTMLInputElement>( "[data-testid='multiplexer-new-ticket-title']" )!.value = "T";
  document.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-new-ticket-create']" )!.click();
  await tick();
  assert.equal( s.refreshes(), 1 );
} );

test( "a created row with no id refreshes but looks nothing up", async () => {
  const s = setup( { postTicket: recordingPost( { status: 201, body: { status: "queued" } } ).postTicket } );
  s.newButton()!.click();
  document.querySelector<HTMLInputElement>( "[data-testid='multiplexer-new-ticket-title']" )!.value = "T";
  document.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-new-ticket-create']" )!.click();
  await tick();
  assert.equal( s.refreshes(), 1 );
  assert.deepEqual( s.lookups, [] );
} );

// ---------------------------------------------------------------------------
// The transport adapter
// ---------------------------------------------------------------------------

test( "apiPostTicket posts to /api/tasks and reports success as 201 with the body", async () => {
  const calls: Array<[ string, unknown ]> = [];
  const send = apiPostTicket( ( path, body ) => { calls.push( [ path, body ] ); return Promise.resolve( NEW_ROW ); } );
  const payload = { title: "T" };
  assert.deepEqual( await send( payload ), { status: 201, body: NEW_ROW } );
  assert.deepEqual( calls, [ [ "/api/tasks", payload ] ] );
} );

test( "a real ApiError comes back as its status and the server's body text", async () => {
  const body = '{"detail":"Creating a ticket at P0 is reserved to the operator\'s own account"}';
  const send = apiPostTicket( () => Promise.reject( new ApiError( 403, "http://localhost:7999/api/tasks", body ) ) );
  assert.deepEqual( await send( { title: "T" } ), { status: 403, text: body } );
} );

test( "a failure with no status — a timeout, a dropped connection, a null — is status 0", async () => {
  assert.deepEqual( await apiPostTicket( () => Promise.reject( new Error( "timeout" ) ) )( {} ), { status: 0 } );
  assert.deepEqual( await apiPostTicket( () => Promise.reject( null ) )( {} ), { status: 0 } );
} );

test( "bodyOfApiErrorMessage takes the text after the first ': ' and nothing else", () => {
  assert.equal( bodyOfApiErrorMessage( "HTTP 422 http://h:1/api/tasks: {\"detail\":\"a: b\"}" ), "{\"detail\":\"a: b\"}" );
  assert.equal( bodyOfApiErrorMessage( "no separator" ), "no separator" );
  assert.equal( bodyOfApiErrorMessage( 42 ), "" );
} );

test( "renderNewTicketButton reads the roster at click time, not at render time", () => {
  let roster = [ "early" ];
  const button = renderNewTicketButton( {
    postTicket : recordingPost( { status: 201 } ).postTicket,
    assignees  : () => roster,
    onCreated  : () => {},
  } );
  roster = [ "late" ];
  button.click();
  const names = Array.from( document.querySelectorAll( `#${ NEW_TICKET_OVERLAY_ID } datalist option` ) )
    .map( ( o ) => ( o as HTMLOptionElement ).value );
  assert.deepEqual( names, [ "late" ] );
} );
