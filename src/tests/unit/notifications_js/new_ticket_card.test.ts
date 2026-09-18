// Rick's New Ticket card on the notifications client (row c9895403) — the other half.
//
// WHAT THIS FILE IS REALLY GUARDING:
//   1. THE BUTTON IS WHERE HE ASKED — in the Find row, directly after 🔎. Read from the
//      shipped HTML, because a method nothing calls is the failure this repo keeps paying for.
//   2. THE CARD IS THE SHARED ONE — same fields as the multiplexer, by construction.
//   3. A MISSING MODULE IS SAID OUT LOUD, not thrown from an inline onclick nobody sees.
//
// Harness mirrors task_lookup_panel.test.ts: slice notifications.js before its DOM-ready
// init, run it in this context, Object.create the prototype to skip the constructor.
//
// Run: npx tsx --test src/tests/unit/notifications_js/new_ticket_card.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  NEW_TICKET_FIELDS,
  NEW_TICKET_OVERLAY_ID,
  assigneeOptions,
  closeNewTicketCard,
  openNewTicketCard,
} from "../../../lupin_app/static/js/shared/task-create.js";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const NOTIFICATIONS_HTML = resolve( HERE, "../../../lupin_app/static/html/notifications.html" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS },
  );
} );

beforeEach( () => {
  window.LUPIN_OPEN_NEW_TICKET_CARD = openNewTicketCard;
  window.LUPIN_NEW_TICKET_ASSIGNEES = assigneeOptions;
  closeNewTicketCard();
  document.body.replaceChildren();
} );

/** A Response-alike. `ok` is derived so a caller cannot set an incoherent pair. */
function response( status: number, body: unknown ) {
  return {
    status,
    ok   : status >= 200 && status < 300,
    json : () => Promise.resolve( body ),
    text : () => Promise.resolve( typeof body === "string" ? body : JSON.stringify( body ) ),
  };
}

interface UI {
  _taskListLastGoodTasks : Array<Record<string, unknown>> | null;
  openNewTicketCard      : () => { controls: { title: HTMLInputElement }; createButton: HTMLButtonElement; submit: () => Promise<void> } | null;
  postNewTicket          : ( payload: Record<string, string> ) => Promise<Record<string, unknown>>;
  showCreatedTicket      : ( row: unknown ) => void;
}

function makeUI( fetchImpl: ( url: string, options?: Record<string, unknown> ) => Promise<unknown> ) {
  const calls = { fetch: [] as Array<[ string, Record<string, unknown> | undefined ]>, lookups: 0, refreshes: 0 };
  const ui = Object.create( ( globalThis as never as { NotificationsUI: { prototype: object } } ).NotificationsUI.prototype );
  ui.log = () => {};
  ui.authedFetch = ( url: string, options?: Record<string, unknown> ) => { calls.fetch.push( [ url, options ] ); return fetchImpl( url, options ); };
  ui.runTaskLookup   = () => { calls.lookups   += 1; return Promise.resolve(); };
  ui.refreshTaskList = () => { calls.refreshes += 1; return Promise.resolve(); };
  ui._taskListLastGoodTasks = null;
  return { ui: ui as UI, calls };
}

function findRow(): { input: HTMLInputElement; result: HTMLElement } {
  const input = document.createElement( "input" );
  input.id = "task-lookup-input";
  const result = document.createElement( "div" );
  result.id = "task-lookup-result";
  document.body.append( input, result );
  return { input, result };
}

const tick = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );
const NEW_ROW = { id: "c9895403-fee8-448d-8f4b-ff49c4941bf7", status: "queued", title: "T" };

// ---------------------------------------------------------------------------
// 1. Wiring — read from what ships
// ---------------------------------------------------------------------------

test( "the shipped page reads 🔎 Find → ✕ clear → ＋ New, and loads the shared module", () => {
  // Rick, row 700f0e1d: the ✕ "should appear between the search icon and the new
  // button… It affects the search area, not the new button."
  const html  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const find  = html.indexOf( 'id="task-lookup-go"' );
  const newer = html.indexOf( 'id="task-new-ticket"' );
  const clear = html.indexOf( 'id="task-lookup-clear"' );
  assert.ok( find > 0 && clear > find && newer > clear, "button order must be Find → clear → New" );
  assert.match( html, /id="task-new-ticket"[\s\S]*?onclick="window\.notificationsUI\.openNewTicketCard\(\)"/ );
  assert.match( html, /<script type="module" src="\/static\/js\/shared\/task-create\.js\?v=\d{8}[a-z]"><\/script>/ );
} );

// ---------------------------------------------------------------------------
// 2. The card
// ---------------------------------------------------------------------------

test( "the card is the shared one: every shared field, and the board's owners as assignees", () => {
  const { ui } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  ui._taskListLastGoodTasks = [ { owner_persona: "maria" }, { owner_persona: "cheech" }, { owner_persona: "maria" } ];
  assert.ok( ui.openNewTicketCard() );
  const overlay = document.getElementById( NEW_TICKET_OVERLAY_ID )!;
  assert.equal( overlay.getAttribute( "data-testid" ), "new-ticket" );
  const fields = Array.from( overlay.querySelectorAll( "[data-field]" ) ).map( ( el ) => el.getAttribute( "data-field" ) );
  assert.deepEqual( fields, [ ...NEW_TICKET_FIELDS ], "PARITY: the same fields as the multiplexer" );
  const names = Array.from( overlay.querySelectorAll( "datalist option" ) ).map( ( o ) => ( o as HTMLOptionElement ).value );
  assert.deepEqual( names, [ "cheech", "maria" ] );
} );

test( "before the first poll there is simply nobody to offer", () => {
  const { ui } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  assert.ok( ui.openNewTicketCard() );
  assert.equal( document.querySelectorAll( `#${ NEW_TICKET_OVERLAY_ID } datalist option` ).length, 0 );
} );

// ---------------------------------------------------------------------------
// 3. A missing module
// ---------------------------------------------------------------------------

test( "a missing shared module is reported as a deploy defect in the Find result line", () => {
  const { result } = findRow();
  delete window.LUPIN_OPEN_NEW_TICKET_CARD;
  const { ui } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  assert.equal( ui.openNewTicketCard(), null );
  assert.equal( result.getAttribute( "data-state" ), "module_missing" );
  assert.match( result.textContent ?? "", /page asset failed to load/ );
} );

test( "a missing roster helper counts as a missing module, and no result line is not a throw", () => {
  delete window.LUPIN_NEW_TICKET_ASSIGNEES;
  const { ui } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  assert.equal( ui.openNewTicketCard(), null );
} );

// ---------------------------------------------------------------------------
// The transport
// ---------------------------------------------------------------------------

test( "postNewTicket POSTs JSON to /api/tasks through the authenticated fetch", async () => {
  const { ui, calls } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  const answer = await ui.postNewTicket( { title: "T", priority: "P0" } );
  assert.deepEqual( answer, { status: 201, body: NEW_ROW } );
  const [ url, options ] = calls.fetch[ 0 ];
  assert.equal( url, "/api/tasks" );
  assert.equal( options?.method, "POST" );
  assert.deepEqual( options?.headers, { "Content-Type": "application/json" } );
  assert.deepEqual( JSON.parse( String( options?.body ) ), { title: "T", priority: "P0" } );
} );

test( "a refusal comes back as its status and raw body; a throw comes back as status 0", async () => {
  const refused = makeUI( () => Promise.resolve( response( 422, '{"detail":"no"}' ) ) );
  assert.deepEqual( await refused.ui.postNewTicket( { title: "T" } ), { status: 422, text: '{"detail":"no"}' } );

  const dead = makeUI( () => Promise.reject( new Error( "offline" ) ) );
  assert.deepEqual( await dead.ui.postNewTicket( { title: "T" } ), { status: 0 } );
} );

// ---------------------------------------------------------------------------
// After the row exists
// ---------------------------------------------------------------------------

test( "end to end: a created ticket closes the card, pins the row through Find, and refreshes", async () => {
  const { input } = findRow();
  const { ui, calls } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  const card = ui.openNewTicketCard()!;
  card.controls.title.value = "Rick's ticket";
  card.createButton.click();
  await tick(); await tick();
  assert.ok( document.getElementById( NEW_TICKET_OVERLAY_ID ) === null, "creating a ticket must close the card" );
  assert.equal( input.value, NEW_ROW.id );
  assert.equal( calls.lookups, 1 );
  assert.equal( calls.refreshes, 1 );
} );

test( "a row with no id, or a page with no Find box, still refreshes and looks nothing up", () => {
  const { ui, calls } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  ui.showCreatedTicket( NEW_ROW );            // no Find input on the page
  findRow();
  ui.showCreatedTicket( { status: "queued" } );
  ui.showCreatedTicket( null );
  assert.equal( calls.lookups, 0 );
  assert.equal( calls.refreshes, 3 );
} );

// ---------------------------------------------------------------------------
// The Title and Details mics on THIS client (row f9a449c3)
//
// Rick filed it as a P0 because he had been dictating his own tickets through OSX's
// ASR — *"profoundly inferior to the one that I have built in to Lupin."*
//
// 🔴 WHAT IS GUARDED IS THE ELEMENT THE RECORDER RECEIVES. `_handleReasonSttClick`
// carries a docstring about exactly this: an id-keyed lookup once handed the recorder
// the invisible copy of a row and Rick's click did nothing (bc77cd79). The card hands
// the element over directly, and these arms assert the identity rather than a count.
// ---------------------------------------------------------------------------

interface StartCall { contextId: string; button: HTMLElement; input: HTMLElement; options: unknown }

/** A recordingManager stand-in that records what it was asked to do. */
function fakeRecorder( state: { recording?: boolean; processing?: boolean } = {} ) {
  const starts: StartCall[] = [];
  let stops = 0;
  return {
    starts,
    stopsOf : () => stops,
    manager : {
      isRecording  : () => state.recording === true,
      isProcessing : () => state.processing === true,
      stopRecording: () => { stops += 1; return Promise.resolve(); },
      startRecording: ( contextId: string, button: HTMLElement, input: HTMLElement, options: unknown ) => {
        starts.push( { contextId, button, input, options } );
        return Promise.resolve();
      },
    },
  };
}

function uiWithRecorder( recorder: ReturnType<typeof fakeRecorder> ) {
  const made = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  ( made.ui as unknown as { recordingManager: unknown } ).recordingManager = recorder.manager;
  return made;
}

/** The open card's two mics, read off the live DOM the way a browser would. */
function micsOf() {
  const overlay = document.getElementById( NEW_TICKET_OVERLAY_ID )!;
  return {
    overlay,
    title   : overlay.querySelector<HTMLButtonElement>( "[data-testid='new-ticket-title-mic']" ),
    details : overlay.querySelector<HTMLButtonElement>( "[data-testid='new-ticket-details-mic']" ),
    titleInput   : overlay.querySelector<HTMLInputElement>( "[data-field='title']" )!,
    detailsInput : overlay.querySelector<HTMLTextAreaElement>( "[data-field='details']" )!,
  };
}

test( "this client's card carries a mic on Title and on Details", () => {
  const recorder = fakeRecorder();
  const { ui } = uiWithRecorder( recorder );
  assert.ok( ui.openNewTicketCard() );
  const mics = micsOf();
  assert.ok( mics.title, "Title must have a mic — the half of the ask he named first" );
  assert.ok( mics.details, "Details must have one too" );
  assert.equal( mics.overlay.querySelectorAll( ".new-ticket-mic" ).length, 2, "and no others" );
} );

test( "the Title mic hands the recorder the TITLE input and its own button", async () => {
  const recorder = fakeRecorder();
  const { ui } = uiWithRecorder( recorder );
  ui.openNewTicketCard();
  const mics = micsOf();

  mics.title!.click();
  await tick();
  assert.equal( recorder.starts.length, 1 );
  assert.equal( recorder.starts[ 0 ].contextId, "new-ticket-title" );
  assert.ok( recorder.starts[ 0 ].input === mics.titleInput,
    "the recorder must be given the box he is looking at, never one a lookup chose" );
  assert.ok( recorder.starts[ 0 ].button === mics.title );
} );

test( "the Details mic hands the recorder the DETAILS textarea, under its own context id", async () => {
  const recorder = fakeRecorder();
  const { ui } = uiWithRecorder( recorder );
  ui.openNewTicketCard();
  const mics = micsOf();

  mics.details!.click();
  await tick();
  assert.equal( recorder.starts.length, 1 );
  assert.equal( recorder.starts[ 0 ].contextId, "new-ticket-details" );
  assert.ok( recorder.starts[ 0 ].input === mics.detailsInput );
  assert.equal( recorder.starts[ 0 ].input.tagName, "TEXTAREA" );
} );

test( "the two mics never cross: each click starts its own field, with its own element", async () => {
  const recorder = fakeRecorder();
  const { ui } = uiWithRecorder( recorder );
  ui.openNewTicketCard();
  const mics = micsOf();

  mics.details!.click();
  await tick();
  mics.title!.click();
  await tick();
  assert.deepEqual( recorder.starts.map( ( s ) => s.contextId ), [ "new-ticket-details", "new-ticket-title" ] );
  assert.ok( recorder.starts[ 0 ].input === mics.detailsInput );
  assert.ok( recorder.starts[ 1 ].input === mics.titleInput );
} );

test( "a click while recording STOPS, and a click while processing does nothing — the page's own toggle", async () => {
  const recording = fakeRecorder( { recording: true } );
  const rec = uiWithRecorder( recording );
  rec.ui.openNewTicketCard();
  micsOf().title!.click();
  await tick();
  assert.equal( recording.stopsOf(), 1, "a second click stops the recording" );
  assert.equal( recording.starts.length, 0, "and starts nothing new" );

  const processing = fakeRecorder( { processing: true } );
  const proc = uiWithRecorder( processing );
  proc.ui.openNewTicketCard();
  micsOf().title!.click();
  await tick();
  assert.equal( processing.starts.length, 0, "a transcription in flight is left alone" );
  assert.equal( processing.stopsOf(), 0 );
} );

test( "a page whose recorder never initialised gets a mic that does nothing, not a thrown card", async () => {
  const { ui } = makeUI( () => Promise.resolve( response( 201, NEW_ROW ) ) );
  ( ui as unknown as { recordingManager: unknown } ).recordingManager = null;
  ui.openNewTicketCard();
  const mics = micsOf();
  assert.doesNotThrow( () => mics.title!.click() );
  await tick();
  assert.ok( document.getElementById( NEW_TICKET_OVERLAY_ID ), "and the card he is filling in stays open" );
} );

test( "dictating does not file the ticket: the mic click sends no POST", async () => {
  const recorder = fakeRecorder();
  const { ui, calls } = uiWithRecorder( recorder );
  ui.openNewTicketCard();
  micsOf().title!.click();
  await tick(); await tick();
  assert.equal( calls.fetch.length, 0 );
  assert.ok( document.getElementById( NEW_TICKET_OVERLAY_ID ) );
} );

test( "the shipped page's cache-bust on the shared module moved with this change", () => {
  // A mic that exists only in the repo is a mic Rick does not have. The module is
  // served with a `?v=` and the browser caches it hard, so the version is part of the fix.
  const html  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const match = html.match( /shared\/task-create\.js\?v=(\d{8})([a-z])/ );
  assert.ok( match, "the module must still be loaded with a cache-bust" );
  assert.ok( Number( match![ 1 ] ) >= 20260917, `the bust must name this change's day or later, read ${ match![ 1 ] }` );
} );
