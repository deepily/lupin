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
  makeNewTicketDictationHook,
  renderNewTicketButton,
} from "../../../../lupin_app/static/js/multiplexer/render/newTicketCard";
import type { RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";
import type { TaskRowRecorderLike } from "../../../../lupin_app/static/js/multiplexer/render/taskRowController";
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
  recorder?    : TaskRowRecorderLike;
  getAuthToken?: () => string | null;
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
    ...( opts.recorder ? { recorder: opts.recorder } : {} ),
    ...( opts.getAuthToken ? { getAuthToken: opts.getAuthToken } : {} ),
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
  assert.ok( find.nextElementSibling === newButton(), "the New button must sit directly after the Find box" );
  assert.equal( newButton()!.textContent, "＋ New" );
} );

test( "no transport means no button, rather than a card that can only fail", () => {
  const { newButton } = setup( {} );
  assert.equal( newButton(), null );
} );

test( "without a Find box the button still mounts, first in the header actions", () => {
  const { root, newButton } = setup( { withLookup: false, postTicket: recordingPost( { status: 201 } ).postTicket } );
  assert.equal( root.querySelectorAll( "[data-testid='multiplexer-task-lookup']" ).length, 0 );
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

// ---------------------------------------------------------------------------
// The Title and Details mics (row f9a449c3)
//
// Rick: *"the new ticket widget lacks voice to text buttons for the title and the
// details"*, filed P0 because the alternative he was living with was OSX dictation.
//
// 🔴 THE MULTIPLEXER'S RECORDER AND THE CLASSIC PAGE'S SHARE NO INTERFACE — one writes
// into the element, this one hands the transcription back through `onComplete`. That is
// why the shared card takes a HOOK and not a recorder, and why this file tests the hook
// this client builds rather than re-testing the card.
// ---------------------------------------------------------------------------

interface MuxStart { contextId: string; opts: RecordingManagerStartOptions }

/** A `TaskRowRecorderLike` that records what it was asked and lets the arm drive it. */
function fakeRecorder( active: string | null = null ) {
  const starts: MuxStart[] = [];
  const stops: string[] = [];
  return {
    starts,
    stops,
    last : () => starts[ starts.length - 1 ].opts,
    recorder : {
      getActiveContextId : () => active,
      stopRecording : ( contextId: string ) => { stops.push( contextId ); return Promise.resolve(); },
      startRecording : ( opts: RecordingManagerStartOptions ) => {
        starts.push( { contextId: opts.contextId, opts } );
        return Promise.resolve();
      },
    },
  };
}

function micsOf() {
  const overlay = document.getElementById( NEW_TICKET_OVERLAY_ID )!;
  return {
    overlay,
    title        : overlay.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-new-ticket-title-mic']" ),
    details      : overlay.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-new-ticket-details-mic']" ),
    titleInput   : overlay.querySelector<HTMLInputElement>( "[data-field='title']" )!,
    detailsInput : overlay.querySelector<HTMLTextAreaElement>( "[data-field='details']" )!,
  };
}

test( "no recorder, no mics — the card is exactly what it was", () => {
  renderNewTicketButton( {
    postTicket : recordingPost( { status: 201 } ).postTicket,
    assignees  : () => [],
    onCreated  : () => {},
  } ).click();
  assert.equal( document.querySelectorAll( ".new-ticket-mic" ).length, 0 );
} );

test( "a recorder puts a mic on Title and on Details, and on nothing else", () => {
  const fake = fakeRecorder();
  renderNewTicketButton( {
    postTicket : recordingPost( { status: 201 } ).postTicket,
    assignees  : () => [],
    onCreated  : () => {},
    recorder   : fake.recorder,
  } ).click();
  const mics = micsOf();
  assert.ok( mics.title );
  assert.ok( mics.details );
  assert.equal( mics.overlay.querySelectorAll( ".new-ticket-mic" ).length, 2 );
} );

test( "the Title mic records under its own context and splices into the TITLE input", () => {
  const fake = fakeRecorder();
  const hook = makeNewTicketDictationHook( fake.recorder, () => "tok-123" );
  const input = document.createElement( "input" );
  input.value = "Fix  now";
  input.setSelectionRange( 4, 4 );
  const button = document.createElement( "button" );

  hook( { field: "title", button, input } );
  assert.equal( fake.starts.length, 1 );
  assert.equal( fake.starts[ 0 ].contextId, "new-ticket-title" );
  assert.equal( fake.last().authToken, "tok-123", "the upload carries the page's own token" );
  assert.ok( button.classList.contains( "recording" ) );

  fake.last().onComplete!( "the widget", new Blob() );
  assert.equal( input.value, "Fix the widget now", "spliced at the caret it had when recording began" );
  assert.equal( button.classList.contains( "recording" ), false, "and the button goes back to idle" );
} );

test( "the Details mic is a SEPARATE context, and writes into the textarea it was handed", () => {
  const fake = fakeRecorder();
  const hook = makeNewTicketDictationHook( fake.recorder, () => null );
  const details = document.createElement( "textarea" );
  const title   = document.createElement( "input" );
  title.value = "untouched";

  hook( { field: "details", button: document.createElement( "button" ), input: details } );
  assert.equal( fake.starts[ 0 ].contextId, "new-ticket-details" );
  assert.notEqual( fake.starts[ 0 ].contextId, "new-ticket-title", "two fields, two contexts" );

  fake.last().onComplete!( "background material", new Blob() );
  assert.equal( details.value, "background material" );
  assert.equal( title.value, "untouched", "the other field is not touched" );
} );

test( "a click while THIS field is recording stops it; a click while it is processing is ignored", () => {
  const fake = fakeRecorder( "new-ticket-title" );
  const hook = makeNewTicketDictationHook( fake.recorder, () => null );
  const button = document.createElement( "button" );
  const input  = document.createElement( "input" );

  hook( { field: "title", button, input } );
  assert.deepEqual( fake.stops, [ "new-ticket-title" ] );
  assert.equal( fake.starts.length, 0 );
  assert.ok( button.classList.contains( "processing" ) );
  assert.equal( button.classList.contains( "recording" ), false );

  // Still awaiting the transcription — a third click must not start a new recording.
  hook( { field: "title", button, input } );
  assert.equal( fake.starts.length, 0 );
  assert.deepEqual( fake.stops, [ "new-ticket-title" ], "and must not ask it to stop twice" );
} );

test( "a failed dictation and a cancelled one both put the mic back to idle", () => {
  const fake = fakeRecorder();
  const hook = makeNewTicketDictationHook( fake.recorder, () => null );

  const failed = document.createElement( "button" );
  hook( { field: "title", button: failed, input: document.createElement( "input" ) } );
  fake.last().onError!( { type: "mic", message: "no device", originalError: null } );
  assert.equal( failed.className.includes( "recording" ), false );
  assert.equal( failed.className.includes( "processing" ), false );

  const cancelled = document.createElement( "button" );
  hook( { field: "details", button: cancelled, input: document.createElement( "textarea" ) } );
  fake.last().onCancel!();
  assert.equal( cancelled.className.includes( "recording" ), false );
} );

test( "after a completed dictation the same mic can record again", () => {
  const fake = fakeRecorder();
  const hook = makeNewTicketDictationHook( fake.recorder, () => null );
  const button = document.createElement( "button" );
  const input  = document.createElement( "input" );

  hook( { field: "title", button, input } );
  fake.last().onComplete!( "one", new Blob() );
  hook( { field: "title", button, input } );
  assert.equal( fake.starts.length, 2, "a finished recording must not wedge its own context" );
} );

test( "with no auth token the dictation still starts — the upload simply carries none", () => {
  const fake = fakeRecorder();
  makeNewTicketDictationHook( fake.recorder, undefined )(
    { field: "title", button: document.createElement( "button" ), input: document.createElement( "input" ) } );
  assert.equal( fake.starts.length, 1 );
  assert.equal( fake.last().authToken, null );
} );

test( "TaskListRenderer hands its own recorder down to the card, so the pane's mics are live", () => {
  const fake = fakeRecorder();
  const { newButton } = setup( {
    withLookup : true,
    recorder   : fake.recorder,
    postTicket : recordingPost( { status: 201, body: NEW_ROW } ).postTicket,
  } );
  newButton()!.click();
  const mics = micsOf();
  assert.ok( mics.title, "a pane wired for the row mic must wire the card's mics too" );

  mics.title!.click();
  assert.equal( fake.starts.length, 1 );
  assert.equal( fake.starts[ 0 ].contextId, "new-ticket-title" );
  assert.ok( fake.last().onComplete, "and the splice is wired, not just the start" );
} );

// Bug f309e6ec — the renderer's two conditional spreads into renderNewTicketButton. Each
// arm is asserted by what the card DOES with it, not by the line having run: an absent
// recorder means no mics at all, and the token a mic uploads with is the pane's own getter
// when one is wired and null when it is not.

test( "a Task List with no recorder hands the card none — the card carries no mics", () => {
  const { newButton } = setup( { postTicket: recordingPost( { status: 201, body: NEW_ROW } ).postTicket } );
  newButton()!.click();
  assert.ok( document.getElementById( NEW_TICKET_OVERLAY_ID ), "the card must be open for this arm to mean anything" );
  assert.equal( document.querySelectorAll( ".new-ticket-mic" ).length, 0 );
} );

test( "a Task List with an auth-token getter hands it to the card, so a mic uploads with the pane's token", () => {
  const fake = fakeRecorder();
  const { newButton } = setup( {
    recorder     : fake.recorder,
    getAuthToken : () => "tok-from-the-pane",
    postTicket   : recordingPost( { status: 201, body: NEW_ROW } ).postTicket,
  } );
  newButton()!.click();
  micsOf().details!.click();
  assert.equal( fake.starts.length, 1 );
  assert.equal( fake.last().authToken, "tok-from-the-pane" );
} );

test( "a Task List with a recorder but no auth-token getter still dictates — the upload carries no token", () => {
  const fake = fakeRecorder();
  const { newButton } = setup( {
    recorder   : fake.recorder,
    postTicket : recordingPost( { status: 201, body: NEW_ROW } ).postTicket,
  } );
  newButton()!.click();
  micsOf().details!.click();
  assert.equal( fake.starts.length, 1 );
  assert.equal( fake.last().authToken, null );
} );
