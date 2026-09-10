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

test( "the shipped page puts ＋ New directly after the 🔎 Find button, and loads the shared module", () => {
  const html  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const find  = html.indexOf( 'id="task-lookup-go"' );
  const newer = html.indexOf( 'id="task-new-ticket"' );
  const clear = html.indexOf( 'id="task-lookup-clear"' );
  assert.ok( find > 0 && newer > find && clear > newer, "button order must be Find → New → clear" );
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
  assert.equal( document.getElementById( NEW_TICKET_OVERLAY_ID ), null );
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
