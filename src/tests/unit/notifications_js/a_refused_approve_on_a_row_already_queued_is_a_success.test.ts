// Row 71a11ed7 — the legacy page's "Approve refused: no-op transition 'queued'->'queued'" for an approve
// that took effect.
//
// Two fixes, one test each way:
//   1. `_transitionTask`: a 422 on a row whose status is ALREADY the target re-reads the row
//      (GET /api/tasks/{id}) and reports { ok: true }. The test is the row's STATUS, never the message
//      text; a 403, a 422 on a row at another status, and a failed read all stay refusals.
//   2. `_handleTaskSubmitClick`: a second press of the same verb on the same row while the first is out
//      (the button having been replaced by a repaint) sends NOTHING; the key is released when the first
//      settles, and another row is not blocked.
//
// notifications.js is outside the c8 gate (src/tests/run-typescript-tests.sh, ruling f8abf4b6): these
// are behavioural tests, proved by breaking each fix and naming the test that reddens.
//
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  // The page loads shared/task-verbs.js as a module before notifications.js; the
  // harness has to do the same, or every verb lookup returns null.
  ( window as unknown as Record<string, unknown> ).LUPIN_TASK_VERB_SPECS = TASK_VERB_SPECS;
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type RowUI = Record<string, unknown> & {
  _taskActionsCell: ( task: Record<string, unknown> ) => string;
  _handleTaskSubmitClick: ( button: unknown ) => Promise<void>;
  _handleVerbSelectChange: ( select: unknown ) => void;
  _handleRowControlClick: ( target: unknown ) => boolean;
  _wireTaskListAccordion: () => void;
  _wireHoldingAreaControls: () => void;
  _wireEpicBoardAccordion: () => void;
  _transitionTask: ( id: string, to: string, extras?: unknown ) => Promise<{ ok: boolean; message?: string }>;
  _patchTaskFields: ( id: string, patch: Record<string, unknown> ) => Promise<{ ok: boolean; message?: string }>;
  _handlePriorityUpdateClick: ( button: unknown ) => Promise<void>;
  refreshTaskList: () => Promise<void>;
  refreshTaskList: () => Promise<void>;
  refreshHoldingArea: () => Promise<void>;
};

function newUI(): RowUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as RowUI;
  ui.debug                     = false;
  ui.log                       = (): void => {};
  ui.error                     = (): void => {};
  ui._taskListFetchInFlight    = false;
  ui._holdingAreaFetchInFlight = false;
  ui._taskListLastGoodTasks    = null;
  ui.TASK_TITLE_TRUNCATE_LEN   = 60;
  ui.queueSessionId            = "test-session";
  ui._holdingAreaControlsWired = false;
  ui._taskListAccordionWired   = false;
  return ui;
}

const ROW_ID = "aaaaaaaa-1111-2222-3333-444444444444";

function row( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id: ROW_ID, title: "a row", status: "queued", item_class: "task",
    created_by: "rio 87e08fee", priority: "P2", project: "lupin", ...over
  };
}

// The page's real three-pane shape — same fixture the sibling files use, and for the
// same reason: a nested fixture lets one pane's listener catch another pane's clicks.
function realPageDOM(): void {
  document.body.innerHTML = `
    <div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div>
    </div>
    <div class="collapsible-section" id="section-holding-area">
      <div class="section-content" id="holding-area-section">
        <div id="holding-area-container"></div>
      </div>
    </div>
    <div class="collapsible-section" id="section-epic-board">
      <div class="section-content"><div id="epic-board-container"></div></div>
    </div>`;
}

// Put the cell in the live task-list pane and wire the real delegated listeners, so a
// click travels the path a browser would rather than reaching the handler by name.
function paneWithCell( ui: RowUI, task: Record<string, unknown> ): HTMLElement {
  realPageDOM();
  const host = document.getElementById( "task-list-container" ) as HTMLElement;
  host.innerHTML = `
    <table id="task-list-table"><tbody>
      <tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${task.id}" hidden><td></td></tr>
    </tbody></table>`;
  // ⚠️ THE WIRING GUARDS MUST BE RESET, and this is a FIXTURE concern, not a product
  // one. Each pane wires its container once and remembers it, which is correct in the
  // page — the container element outlives every repaint, only its innerHTML is
  // replaced. This helper rebuilds the whole DOM per call, so the remembered "already
  // wired" would leave the listener on a container that has been thrown away, and
  // every click after the first row would reach no handler. That reads exactly like a
  // dead control and is not one.
  ui._taskListAccordionWired   = false;
  ui._holdingAreaControlsWired = false;
  ui._epicBoardAccordionWired  = false;
  ui._wireTaskListAccordion();
  ui._wireHoldingAreaControls();
  ui._wireEpicBoardAccordion();
  return host;
}

// Dispatch a REAL bubbling event and assert a handler was reached, then hand back its
// promise. Copied deliberately from holding_area_panel's `clickThrough`: at the fork,
// 0 of 20 row-control tests reached a real event, which is why three panes of dead
// controls stayed invisible to 484 passing tests.
async function clickThrough( ui: RowUI, method: string, el: Element | null, what: string ): Promise<void> {
  assert.ok( el, `${ what } did not render at all — this test cannot speak to wiring` );
  const target   = ui as unknown as Record<string, ( b: unknown ) => unknown >;
  const original = target[ method ];
  let   ran: unknown = null;
  target[ method ] = ( b: unknown ) => { ran = original.call( ui, b ); return ran; };
  el!.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  target[ method ] = original;
  assert.ok( ran !== null,
    `${ what } reached NO handler — the control is dead on screen however correct the handler is` );
  await ran;
}

function selectVerb( host: HTMLElement, verb: string ): HTMLSelectElement {
  const sel = host.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  assert.ok( sel, "the row renders no verb select at all" );
  sel.value = verb;
  sel.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
  return sel;
}


type Reply = { status: number; body: unknown };

/** Install an `authedFetch` that answers by method+path from a table and records every call. */
function stubFetch( ui: RowUI, answers: Record<string, Reply | "throw"> ): string[] {
  const calls: string[] = [];
  ui.authedFetch = async ( path: string, init?: { method?: string } ) => {
    const key = `${ init?.method ?? "GET" } ${ path }`;
    calls.push( key );
    const a = answers[ key ];
    if ( a === undefined ) throw new Error( `unexpected request ${ key }` );
    if ( a === "throw" ) throw new Error( "network down" );
    return { status: a.status, ok: a.status >= 200 && a.status < 300, json: async () => a.body };
  };
  return calls;
}

const POST  = `POST /api/tasks/${ ROW_ID }/transition`;
const READ  = `GET /api/tasks/${ ROW_ID }`;
const NOOP  = { status: 422, body: { detail: { errors: [ "no-op transition 'queued'->'queued' — NOTHING TO DO" ] } } };

test( "a 422 on a row already at the target is a success, found by re-reading the row", async () => {
  const ui    = newUI();
  const calls = stubFetch( ui, { [ POST ]: NOOP, [ READ ]: { status: 200, body: { id: ROW_ID, status: "queued" } } } );
  assert.deepEqual( await ui._transitionTask( ROW_ID, "queued" ), { ok: true } );
  assert.deepEqual( calls, [ POST, READ ] );
} );

test( "a 422 on a row at ANOTHER status is still a refusal carrying the server's words", async () => {
  const ui = newUI();
  stubFetch( ui, { [ POST ]: NOOP, [ READ ]: { status: 200, body: { id: ROW_ID, status: "not_approved" } } } );
  const r = await ui._transitionTask( ROW_ID, "queued" );
  assert.equal( r.ok, false );
  assert.match( r.message ?? "", /no-op transition/ );
} );

test( "a 403 is a refusal and the row is NEVER re-read", async () => {
  const ui    = newUI();
  const calls = stubFetch( ui, { [ POST ]: { status: 403, body: { detail: "not an approver" } } } );
  const r = await ui._transitionTask( ROW_ID, "queued" );
  assert.deepEqual( r, { ok: false, message: "not an approver" } );
  assert.deepEqual( calls, [ POST ] );
} );

test( "a 422 whose re-read fails (non-2xx, network, or no row) leaves the refusal standing", async () => {
  for ( const reread of [ { status: 500, body: {} }, "throw" as const, { status: 200, body: null } ] ) {
    const ui = newUI();
    stubFetch( ui, { [ POST ]: NOOP, [ READ ]: reread } );
    const r = await ui._transitionTask( ROW_ID, "queued" );
    assert.equal( r.ok, false, `a failed re-read (${ JSON.stringify( reread ) }) was read as success` );
  }
} );

test( "the assembled click: Approve on a row the server says is already queued shows NO refusal stripe", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "not_approved" } ) );
  stubFetch( ui, { [ POST ]: NOOP, [ READ ]: { status: 200, body: { id: ROW_ID, status: "queued" } } } );
  let refreshed = 0;
  ui.refreshTaskList = async () => { refreshed++; };

  selectVerb( host, "approve" );
  await clickThrough( ui, "_handleTaskSubmitClick", host.querySelector( ".task-submit-button" ), "Submit for approve" );

  const stripe = host.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( stripe.hidden, true, `the operator was told: ${ stripe.textContent }` );
  assert.equal( refreshed, 1, "the list was not refreshed, so the row would not move" );
} );

test( "a second press while the first is in flight sends nothing, and the key is released after", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "not_approved" } ) );
  ui.refreshTaskList = async () => {};
  let sent = 0;
  let release: () => void = () => {};
  ui._transitionTask = () => { sent++; return new Promise( ( res ) => { release = () => res( { ok: true } ); } ); };

  selectVerb( host, "approve" );
  const button = host.querySelector( ".task-submit-button" ) as HTMLElement;
  const first  = ui._handleTaskSubmitClick( button );
  // A repaint replaces the button with a fresh, live one while the first request is still out.
  const second = ui._handleTaskSubmitClick( button.cloneNode( true ) );
  await second;
  assert.equal( sent, 1, "the second press fired a second transition" );

  release();
  await first;
  const third = ui._handleTaskSubmitClick( button );
  assert.equal( sent, 2, "the key was never released, so the row can never be approved again" );
  release();
  await third;
} );

test( "the guard is per row: another row's Approve is not blocked by the first", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "not_approved" } ) );
  ui.refreshTaskList = async () => {};
  const ids: string[] = [];
  const releases: Array<() => void> = [];
  ui._transitionTask = ( id: string ) => { ids.push( id ); return new Promise( ( res ) => { releases.push( () => res( { ok: true } ) ); } ); };

  selectVerb( host, "approve" );
  const button = host.querySelector( ".task-submit-button" ) as HTMLElement;
  const first  = ui._handleTaskSubmitClick( button );

  const other = button.cloneNode( true ) as HTMLElement;
  const OTHER_ID = "bbbbbbbb-1111-2222-3333-444444444444";
  other.dataset.taskId = OTHER_ID;
  host.querySelector( ".task-row-error-stripe" )!.insertAdjacentHTML( "afterend",
    `<tr class="task-row-error-stripe" data-error-for="${ OTHER_ID }" hidden><td></td></tr>` );
  const select = host.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  const otherSelect = select.cloneNode( true ) as HTMLSelectElement;
  otherSelect.dataset.taskId = OTHER_ID;
  otherSelect.value = "approve";
  select.after( otherSelect );
  const second = ui._handleTaskSubmitClick( other );

  assert.deepEqual( ids, [ ROW_ID, OTHER_ID ], "the second row's Approve was swallowed by the first row's key" );
  releases.forEach( ( r ) => r() );
  await Promise.all( [ first, second ] );
} );
