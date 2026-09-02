// Holding Area + per-row state controls — frontend unit tests that RUN THE CODE.
//
// Rick's P0, store row 8af64f5a. Design:
//   planning-is-prompting → src/rnd/2026.09.02-ticket-approval-gate-and-wont-fix.md
//
// 🔴 WHY THIS FILE EXISTS, and it is the whole point.
//
// `src/tests/unit/test_task_row_state_controls.py` covers this feature with 39 assertions and every
// one of them reads `notifications.js` AS TEXT. That tier is genuinely useful — it is where the
// client's rules get pinned against the server's own constants, so the two cannot drift — but it is
// structurally incapable of telling a working control from a string that looks like one. Measured
// during that slice, three separate times:
//
//   · `assert "isTerminal" in src`             held against `const isTerminal = false;`
//   · `assert "Overtaken by events" in page`   held against the HTML COMMENT describing the option
//   · `assert "A triage-by date is required"`  held against the message sitting in a dead branch
//
// And once at the level above: a stray brace inserted into `_taskActionsCell` left every one of the
// 34 assertions green while the browser could not parse the file at all.
//
// ⇒ So this file INSTANTIATES the class and calls the methods. Everything here is a claim about what
//   the code DOES. If a control stops rendering, stops being disabled, or stops sending what the
//   server requires, these go red — and none of them can be satisfied by a comment.
//
// Harness is the established one (fleet_status_panel / task_list_panel): load the class via
// vm.runInThisContext sliced before the DOM-ready init, Object.create the prototype to skip the
// constructor, hand-set the few fields the methods read, drive the methods under happy-dom.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/holding_area_panel.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TASK_LIST_QUERY, HOLDING_AREA_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  // Both globals stand in for the page's module script. Omit either and the matching
  // fetcher short-circuits to its `query_unavailable` deploy-defect branch — correct
  // production behaviour, and a confusing way for a render test to fail.
  window.LUPIN_TASK_LIST_QUERY    = TASK_LIST_QUERY;
  window.LUPIN_HOLDING_AREA_QUERY = HOLDING_AREA_QUERY;

  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type HoldingUI = Record<string, unknown> & {
  _taskActionsCell: ( task: Record<string, unknown> ) => string;
  _groupHeldRowsByFiler: ( tasks: unknown ) => Array<{ filer: string; tasks: Record<string, unknown>[] }>;
  renderHoldingArea: ( composite: unknown ) => void;
  _heldRowIdsForFiler: ( filer: string ) => string[];
  _applyHoldingBatch: ( filer: string, toStatus: string, extras: unknown, verb: string )
    => Promise<{ ok: number; failed: number; firstError: string | null }>;
  _handleTaskWontFixClick: ( button: unknown ) => Promise<void>;
  _handleTaskDropClick: ( button: unknown ) => Promise<void>;
  _wireHoldingAreaControls: () => void;
  _handleRowControlClick: ( target: unknown ) => boolean;
  _renderTaskRow: ( task: Record<string, unknown>, ianaZone?: unknown ) => string;
  _holdingAreaControlsWired: boolean;
  _handleTaskParkClick: ( button: unknown ) => Promise<void>;
  _controlScope: ( button: unknown ) => ParentNode;
  _rowInputValue: ( taskId: string, cls: string, scope: unknown ) => string;
  _handleTaskDemoteClick: ( button: unknown ) => Promise<void>;
  _handleTaskApproveClick: ( button: unknown ) => Promise<void>;
  _handleHoldingWontFixAllClick: ( button: unknown ) => Promise<void>;
  _transitionTask: ( id: string, to: string, extras?: unknown ) => Promise<{ ok: boolean; message?: string }>;
  refreshTaskList: () => Promise<void>;
  refreshHoldingArea: () => Promise<void>;
};

function newUI(): HoldingUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as HoldingUI;
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

function row( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id: "aaaaaaaa-1111-2222-3333-444444444444",
    title: "a row",
    status: "queued",
    item_class: "task",
    created_by: "mr radio 0e61abe3",
    priority: "P2",
    project: "lupin",
    ...over
  };
}

function buildHoldingDOM(): void {
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.innerHTML = `
    <h3>Holding Area: <span id="holding-area-count">0</span></h3>
    <div id="holding-area-container"></div>`;
  document.body.appendChild( section );
}

beforeEach( () => buildHoldingDOM() );


// ═══════════════════════════ the actions cell, RENDERED ═══════════════════════════

test( "a terminal row renders every control disabled — not merely described as disabled", () => {
  const ui = newUI();
  for ( const status of [ "done", "dropped", "wont_fix" ] ) {
    const host = document.createElement( "div" );
    host.innerHTML = ui._taskActionsCell( row( { status } ) );

    const buttons = Array.from( host.querySelectorAll( "button" ) );
    assert.ok( buttons.length > 0, `${status}: no controls rendered at all` );
    for ( const b of buttons ) {
      assert.equal( ( b as HTMLButtonElement ).disabled, true,
        `${status}: "${b.textContent}" is clickable on a terminal row the server refuses outright` );
      assert.equal( b.getAttribute( "aria-disabled" ), "true", `${status}: "${b.textContent}" has no aria-disabled` );
    }
    // ...and no inputs, because there is nothing to fill in for a move that cannot happen.
    assert.equal( host.querySelectorAll( "input" ).length, 0,
      `${status}: renders inputs for an impossible transition` );
  }
} );

test( "park is enabled ONLY from queued / in_progress, and says why when it is not", () => {
  const ui = newUI();
  const parkOf = ( status: string ) => {
    const host = document.createElement( "div" );
    host.innerHTML = ui._taskActionsCell( row( { status } ) );
    return host.querySelector( ".task-park-button" ) as HTMLButtonElement;
  };
  for ( const status of [ "queued", "in_progress" ] ) {
    assert.equal( parkOf( status ).disabled, false, `park should be live from ${status}` );
  }
  for ( const status of [ "blocked", "review", "claimed", "parked", "not_approved" ] ) {
    const b = parkOf( status );
    assert.equal( b.disabled, true, `park is offered from ${status}, which the server refuses with a 422` );
    assert.match( b.getAttribute( "title" ) ?? "", /queued or in progress/,
      `${status}: the disabled park button does not teach the rule` );
  }
} );

test( "approve and demote are never both live on the same row", () => {
  const ui = newUI();
  for ( const status of [ "queued", "in_progress", "blocked", "review", "parked", "not_approved" ] ) {
    const host = document.createElement( "div" );
    host.innerHTML = ui._taskActionsCell( row( { status } ) );
    const approve = host.querySelector( ".task-approve-button" ) as HTMLButtonElement;
    const demote  = host.querySelector( ".task-demote-button" )  as HTMLButtonElement;

    assert.equal( !approve.disabled && !demote.disabled, false,
      `${status}: approve and demote both live — one of them is a no-op edge the store rejects` );

    if ( status === "not_approved" ) {
      assert.equal( approve.disabled, false, "approve must be live on a held row — it is the holding area's only exit" );
      assert.equal( demote.disabled,  true,  "demote is offered on a row already in the holding area" );
    } else {
      assert.equal( approve.disabled, true,  `${status}: approve is offered on a row that is not held` );
      assert.equal( demote.disabled,  false, `${status}: demote is unavailable on a live row` );
    }
  }
} );

test( "won't-fix and demote each render the input their transition REQUIRES", () => {
  const ui = newUI();
  const host = document.createElement( "div" );
  host.innerHTML = ui._taskActionsCell( row( { status: "queued" } ) );

  assert.ok( host.querySelector( ".task-wont-fix-reason" ), "won't-fix has no reason input" );
  assert.ok( host.querySelector( ".task-demote-reason" ),   "demote has no reason input" );
  // Rick's ruling 2026-09-02: a held row comes back on a chase, like a parked one.
  const chase = host.querySelector( ".task-demote-chase" ) as HTMLInputElement;
  assert.ok( chase, "demote collects no triage-by date" );
  assert.equal( chase.type, "date", "the triage-by input is not a date picker" );
} );

test( "every live control carries the row id, so its handler can find its inputs", () => {
  const ui = newUI();
  const host = document.createElement( "div" );
  const id = "bc77cd79-7acc-4a99-8a27-8fc77d2cc1b3";
  host.innerHTML = ui._taskActionsCell( row( { status: "parked", id } ) );

  const live = Array.from( host.querySelectorAll( "button:not([disabled]), input" ) );
  assert.ok( live.length > 0, "a parked row rendered no live controls at all" );
  for ( const el of live ) {
    assert.equal( ( el as HTMLElement ).dataset.taskId, id,
      "a live control carries no data-task-id — its handler would return silently" );
  }
} );


// ═══════════════════════════ the transitions, DRIVEN ═══════════════════════════

test( "won't-fix will not call the server on a blank reason, and sends it verbatim when present", async () => {
  const ui = newUI();
  const calls: Array<[ string, string, unknown ]> = [];
  ui._transitionTask = async ( id, to, extras ) => { calls.push( [ id, to, extras ] ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  const id = "aaaaaaaa-1111-2222-3333-444444444444";
  document.body.innerHTML = `
    <input class="task-action-input task-wont-fix-reason" data-task-id="${id}" value="">
    <table><tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr></table>`;
  const button = { dataset: { taskId: id } };

  await ui._handleTaskWontFixClick( button );
  assert.equal( calls.length, 0, "a blank won't-fix reason reached the server" );

  ( document.querySelector( ".task-wont-fix-reason" ) as HTMLInputElement ).value = "fuck no, I will not fix this";
  await ui._handleTaskWontFixClick( button );
  assert.equal( calls.length, 1 );
  assert.equal( calls[ 0 ][ 1 ], "wont_fix" );
  assert.equal( ( calls[ 0 ][ 2 ] as { reason: string } ).reason, "fuck no, I will not fix this" );
} );

test( "demote requires BOTH a reason and a triage-by date, and stamps a real instant", async () => {
  const ui = newUI();
  const calls: Array<[ string, string, unknown ]> = [];
  ui._transitionTask = async ( id, to, extras ) => { calls.push( [ id, to, extras ] ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  const id = "aaaaaaaa-1111-2222-3333-444444444444";
  document.body.innerHTML = `
    <input class="task-action-input task-demote-reason" data-task-id="${id}" value="">
    <input class="task-action-input task-demote-chase"  data-task-id="${id}" value="">
    <table><tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr></table>`;
  const button = { dataset: { taskId: id } };
  const reason = document.querySelector( ".task-demote-reason" ) as HTMLInputElement;
  const chase  = document.querySelector( ".task-demote-chase" )  as HTMLInputElement;

  await ui._handleTaskDemoteClick( button );
  assert.equal( calls.length, 0, "a blank demote reason reached the server" );

  reason.value = "overtaken by the holding-area work";
  await ui._handleTaskDemoteClick( button );
  assert.equal( calls.length, 0,
    "a demotion with NO triage-by date reached the server — that row would never come back" );

  chase.value = "2026-09-10";
  await ui._handleTaskDemoteClick( button );
  assert.equal( calls.length, 1 );
  const extras = calls[ 0 ][ 2 ] as { reason: string; next_chase_ts: string };
  assert.equal( calls[ 0 ][ 1 ], "not_approved" );
  assert.ok( extras.next_chase_ts, "no chase timestamp was sent" );

  // 🔴 THE ZONE TRAP, EXECUTED RATHER THAN DESCRIBED. A bare "2026-09-10" parses as
  // midnight UTC, which is the PREVIOUS EVENING for every zone west of Greenwich — the
  // chase would fire a day early every time and nothing would look wrong. The handler
  // stamps 09:00 local first, so the instant it sends must be strictly later.
  const sent  = new Date( extras.next_chase_ts );
  const naive = new Date( "2026-09-10" );
  assert.ok( sent.getTime() > naive.getTime(),
    `chase ${extras.next_chase_ts} is not later than bare-midnight-UTC — the local-time stamp is gone` );
  assert.equal( sent.getDate(), 10, "the chase landed on the wrong calendar day in the local zone" );
} );

test( "approve sends the promotion and never invents an allowlist check of its own", async () => {
  const ui = newUI();
  const calls: Array<[ string, string, unknown ]> = [];
  ui._transitionTask = async ( id, to, extras ) => { calls.push( [ id, to, extras ] ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  const id = "aaaaaaaa-1111-2222-3333-444444444444";
  document.body.innerHTML = `<table><tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr></table>`;
  await ui._handleTaskApproveClick( { dataset: { taskId: id } } );

  assert.equal( calls.length, 1, "approve did not fire — the client is gating on a rule of its own" );
  assert.equal( calls[ 0 ][ 1 ], "queued" );
} );

test( "a refused transition shows the SERVER'S words, not a client paraphrase", async () => {
  const ui = newUI();
  const serverWords = "403: actor 'maria' is not in approvers ['rick','mr radio']; edit lupin-app.ini or ask an approver";
  ui._transitionTask = async () => ( { ok: false, message: serverWords } );
  ui.refreshTaskList = async () => {};

  const id = "aaaaaaaa-1111-2222-3333-444444444444";
  document.body.innerHTML = `
    <input class="task-action-input task-wont-fix-reason" data-task-id="${id}" value="because">
    <table><tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr></table>`;

  await ui._handleTaskWontFixClick( { dataset: { taskId: id } } );
  const stripe = document.querySelector( `.task-row-error-stripe[data-error-for="${id}"]` ) as HTMLElement;
  assert.equal( stripe.hidden, false, "the refusal is invisible — the row looks like nothing happened" );
  assert.ok( ( stripe.textContent ?? "" ).includes( serverWords ),
    "the server's message was replaced by our own wording, losing the actor and the allowlist" );
} );


// ═══════════════════════════ the holding-area pane, PAINTED ═══════════════════════════

test( "held rows group by FILER, not by owner, and filers sort alphabetically", () => {
  const ui = newUI();
  const groups = ui._groupHeldRowsByFiler( [
    row( { id: "1", created_by: "mr radio 0e61abe3", owner_persona: "maria" } ),
    row( { id: "2", created_by: "krishna 420f5ec9", owner_persona: "maria" } ),
    row( { id: "3", created_by: "mr radio 0e61abe3", owner_persona: "tiberius" } )
  ] );
  // All three share ONE owner and split across TWO filers, so a grouper keyed on the
  // owner returns a single group here and looks perfectly reasonable doing it.
  assert.deepEqual( groups.map( g => g.filer ), [ "Krishna", "Mr Radio" ] );
  assert.equal( groups[ 1 ].tasks.length, 2 );
} );

test( "an empty holding area says so in words rather than rendering blank", () => {
  const ui = newUI();
  ui.renderHoldingArea( { tasks: [], count: 0, total: 0, has_more: false } );
  const container = document.getElementById( "holding-area-container" ) as HTMLElement;
  assert.match( container.textContent ?? "", /Nothing waiting on triage/ );
  assert.equal( ( document.getElementById( "holding-area-count" ) as HTMLElement ).textContent, "0" );
} );

test( "each sentinel state renders its own message and never a silent blank", () => {
  const ui = newUI();
  const container = document.getElementById( "holding-area-container" ) as HTMLElement;
  for ( const [ status, needle ] of [
    [ "auth_required",     /Sign-in required/ ],
    [ "query_unavailable", /deploy defect/ ],
    [ "unreachable",       /unreachable/ ]
  ] as Array<[ string, RegExp ]> ) {
    ui.renderHoldingArea( { status, tasks: null } );
    assert.match( container.textContent ?? "", needle, `${status} rendered nothing a reader can act on` );
    assert.equal( ( document.getElementById( "holding-area-count" ) as HTMLElement ).textContent, "—",
      `${status} left a stale count on screen` );
  }
} );

test( "a populated pane paints groups, batch controls and a LABELLED table header", () => {
  const ui = newUI();
  ui.renderHoldingArea( {
    tasks: [ row( { id: "1", status: "not_approved", created_by: "krishna 420f5ec9" } ),
             row( { id: "2", status: "not_approved", created_by: "krishna 420f5ec9" } ) ],
    count: 2, total: 2, has_more: false
  } );
  const container = document.getElementById( "holding-area-container" ) as HTMLElement;

  assert.equal( container.querySelectorAll( ".holding-area-group" ).length, 1 );
  assert.ok( container.querySelector( ".holding-approve-all" ),         "no batch approve control" );
  assert.ok( container.querySelector( ".holding-wont-fix-all" ),        "no batch won't-fix control" );
  assert.ok( container.querySelector( ".holding-wont-fix-all-reason" ), "batch won't-fix has no reason box" );
  // Twelve LABELLED columns, not twelve anonymous ones.
  assert.equal( container.querySelectorAll( "thead th" ).length, 12 );
  assert.equal( ( document.getElementById( "holding-area-count" ) as HTMLElement ).textContent, "2" );
} );

test( "the batch reads ids off the LIVE DOM, so it can never act on a stale list", () => {
  const ui = newUI();
  ui.renderHoldingArea( {
    tasks: [ row( { id: "id-one", status: "not_approved", created_by: "krishna 420f5ec9" } ),
             row( { id: "id-two", status: "not_approved", created_by: "krishna 420f5ec9" } ) ],
    count: 2, total: 2, has_more: false
  } );
  assert.deepEqual( ui._heldRowIdsForFiler( "Krishna" ).sort(), [ "id-one", "id-two" ] );
  assert.deepEqual( ui._heldRowIdsForFiler( "Nobody" ), [], "an unknown filer must yield nothing, not throw" );
} );

test( "🔴 a PARTIALLY refused batch reports the failure instead of looking successful", async () => {
  const ui = newUI();
  ui.renderHoldingArea( {
    tasks: [ row( { id: "ok-1", status: "not_approved", created_by: "krishna 420f5ec9" } ),
             row( { id: "no-2", status: "not_approved", created_by: "krishna 420f5ec9" } ),
             row( { id: "ok-3", status: "not_approved", created_by: "krishna 420f5ec9" } ) ],
    count: 3, total: 3, has_more: false
  } );
  ui.refreshHoldingArea = async () => {};
  ui._transitionTask = async ( id ) => id.startsWith( "no" )
    ? { ok: false, message: "403: actor 'maria' is not in approvers ['rick']" }
    : { ok: true };

  const result = await ui._applyHoldingBatch( "Krishna", "queued", {}, "Approved" );
  assert.equal( result.ok, 2 );
  assert.equal( result.failed, 1 );

  // THE PROPERTY. Without it the pane simply repaints shorter, which reads as success,
  // while the refused row sits there with nothing saying why.
  const line = document.querySelector( '.holding-area-group-status[data-filer="Krishna"]' ) as HTMLElement;
  assert.match( line.textContent ?? "", /1 refused/, "a partial batch failure rendered as success" );
  assert.match( line.textContent ?? "", /not in approvers/, "the server's first refusal was swallowed" );
} );

test( "batch won't-fix will not fire without its one reason", async () => {
  const ui = newUI();
  ui.renderHoldingArea( {
    tasks: [ row( { id: "x", status: "not_approved", created_by: "krishna 420f5ec9" } ) ],
    count: 1, total: 1, has_more: false
  } );
  let called = 0;
  ui._transitionTask = async () => { called++; return { ok: true }; };
  ui.refreshHoldingArea = async () => {};

  await ui._handleHoldingWontFixAllClick( { dataset: { filer: "Krishna" } } );
  assert.equal( called, 0, "a blank batch reason reached the server, N times over" );
  const line = document.querySelector( '.holding-area-group-status[data-filer="Krishna"]' ) as HTMLElement;
  assert.match( line.textContent ?? "", /reason is required/i );

  ( document.querySelector( '.holding-wont-fix-all-reason[data-filer="Krishna"]' ) as HTMLInputElement ).value = "overtaken";
  await ui._handleHoldingWontFixAllClick( { dataset: { filer: "Krishna" } } );
  assert.equal( called, 1 );
} );


// ═══════════════════════ _transitionTask ITSELF, which nothing was watching ═══════════════════════
//
// 🔴 FOUND BY MR RADIO'S BLAST-RADIUS CRITERION, applied to my own suite rather than agreed with.
// The question is not "was the mutation caught" but "how MANY tests saw it" — one red where you
// expected several means most of the suite was never looking. Measured across both tiers:
//
//     the actions cell renders nothing        → 8 red   (JS)
//     the holding pane paints nothing         → 4 red   (JS) + 1 (Python)
//     _transitionTask always returns { ok }   → 0 red   ← EVERYTHING
//
// Zero. Every test above stubs `_transitionTask`, which is correct for testing the handlers but left
// the one function that actually talks to the server completely unwatched. Had it swallowed a 403 and
// returned success, every test in this file and all 39 in the Python tier would have stayed green
// while every refusal on screen rendered as a silent success — the row would simply not change and
// nothing anywhere would say why.
//
// So these stub `authedFetch` instead and drive the real thing.

function uiWithFetch( impl: ( url: string, init: Record<string, unknown> ) => unknown ): HoldingUI {
  const ui = newUI();
  ui.authedFetch = async ( url: string, init: Record<string, unknown> ) => impl( url, init );
  return ui;
}

test( "_transitionTask: a 2xx is success, and the request carries what the server requires", async () => {
  let seenUrl = "", seenBody: Record<string, unknown> = {};
  const ui = uiWithFetch( ( url, init ) => {
    seenUrl  = url;
    seenBody = JSON.parse( String( ( init as { body: string } ).body ) );
    return { ok: true, status: 200 };
  } );

  const out = await ui._transitionTask( "abc-123", "wont_fix", { reason: "no" } );
  assert.deepEqual( out, { ok: true } );
  assert.equal( seenUrl, "/api/tasks/abc-123/transition" );
  assert.equal( seenBody.to_status, "wont_fix" );
  assert.equal( seenBody.reason, "no" );
  assert.equal( seenBody.authority, "user_direct" );
  assert.ok( String( seenBody.actor ).startsWith( "operator " ), "the transition is not attributed to an operator" );
} );

test( "_transitionTask: a row id is URL-ENCODED, so an odd id cannot reshape the path", async () => {
  let seenUrl = "";
  const ui = uiWithFetch( ( url ) => { seenUrl = url; return { ok: true, status: 200 }; } );
  await ui._transitionTask( "a/b?c=d", "queued" );
  assert.equal( seenUrl, "/api/tasks/a%2Fb%3Fc%3Dd/transition" );
} );

test( "🔴 _transitionTask: a REFUSAL is a failure and carries the server's own detail", async () => {
  const detail = "403: actor 'maria' is not in approvers ['rick']; edit lupin-app.ini or ask an approver";
  const ui = uiWithFetch( () => ( {
    ok: false, status: 403, json: async () => ( { detail } )
  } ) );

  const out = await ui._transitionTask( "abc", "wont_fix", { reason: "x" } );
  assert.equal( out.ok, false, "a 403 was reported as success — every refusal would render as a silent no-op" );
  assert.equal( out.message, detail, "the server's detail was dropped, losing the actor and the allowlist" );
} );

test( "_transitionTask: a structured (non-string) detail survives instead of becoming [object Object]", async () => {
  // FastAPI validation errors arrive as a LIST of objects. Interpolated naively they
  // render as "[object Object]", which tells the operator nothing at all.
  const ui = uiWithFetch( () => ( {
    ok: false, status: 422,
    json: async () => ( { detail: [ { loc: [ "body", "reason" ], msg: "field required" } ] } )
  } ) );
  const out = await ui._transitionTask( "abc", "wont_fix" );
  assert.equal( out.ok, false );
  assert.ok( !out.message?.includes( "[object Object]" ), "a structured 422 renders as [object Object]" );
  assert.match( out.message ?? "", /field required/ );
} );

test( "_transitionTask: a non-JSON error body still fails, with the status as the message", async () => {
  const ui = uiWithFetch( () => ( {
    ok: false, status: 502, json: async () => { throw new Error( "not json" ); }
  } ) );
  const out = await ui._transitionTask( "abc", "queued" );
  assert.equal( out.ok, false, "an HTML gateway error page was read as success" );
  assert.equal( out.message, "502" );
} );

test( "_transitionTask: a network throw is a failure and NEVER propagates", async () => {
  const ui = uiWithFetch( () => { throw new Error( "connection refused" ); } );
  const out = await ui._transitionTask( "abc", "queued" );
  assert.equal( out.ok, false, "an unreachable store was reported as success" );
  assert.match( out.message ?? "", /unreachable: connection refused/ );
} );


// ═══════════════ THE DEFECT RICK HIT: two panes, one row, a global querySelector ═══════════════
//
// 🔴 REPRODUCTION OF A LIVE BUG, 2026-09-02. Rick clicked Won't-fix on bc77cd79 and nothing happened.
// Mr Radio measured it from the other end: the row was untouched, there were ZERO wont_fix events in
// the whole store, and thirty minutes of server log carried no PATCH to any task row. The request
// never left the browser.
//
// THE CAUSE IS MINE, introduced at fe8642c7 when I gave the epic board the same actions cell. From
// that commit on, a row that carries an epic key renders TWICE — once in the task list, once on the
// epic board — and `_rowInputValue` / `_renderTaskRowError` both use a bare `document.querySelector`,
// which returns the FIRST match in the document.
//
// So: he types the reason into the pane he is looking at, the handler reads the OTHER pane's empty
// box, refuses for a blank reason, and writes the complaint into the OTHER pane's error stripe.
// Nothing happens where he is looking. He reported it as a dead button, which is exactly what it is
// from where he sat.
//
// ⇒ AND THE SILENT-REFUSAL SHAPE IS THE SAME ONE I HAD JUST WRITTEN ABOUT one layer down: he cannot
//   distinguish "you forgot the reason" from "the control is broken". A guard that refuses without
//   showing the refusal in the place the operator is looking has not refused, it has vanished.

function twoPanesShowingTheSameRow( ui: HoldingUI, id: string ): void {
  const task = row( { id, status: "parked" } );
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  // Task list FIRST in document order, epic board second — the real page's order.
  host.innerHTML = `
    <table id="task-list-table"><tbody>
      <tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr>
    </tbody></table>
    <table id="epic-board-table"><tbody>
      <tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr>
    </tbody></table>`;
  document.body.appendChild( host );
}

test( "🔴 a reason typed on the EPIC BOARD is the one that gets sent", async () => {
  const ui = newUI();
  const id = "bc77cd79-7acc-4a99-8a27-8fc77d2cc1b3";
  twoPanesShowingTheSameRow( ui, id );

  const calls: Array<[ string, string, unknown ]> = [];
  ui._transitionTask = async ( i, to, extras ) => { calls.push( [ i, to, extras ] ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  // Rick types into the SECOND pane — the one he is looking at — and clicks ITS button.
  const epic = document.getElementById( "epic-board-table" ) as HTMLElement;
  ( epic.querySelector( ".task-wont-fix-reason" ) as HTMLInputElement ).value = "fuck no, I will not fix this";
  await ui._handleTaskWontFixClick( epic.querySelector( ".task-wont-fix-button" ) as HTMLElement );

  assert.equal( calls.length, 1,
    "the click was swallowed — the handler read the OTHER pane's empty box and refused silently" );
  assert.equal( ( calls[ 0 ][ 2 ] as { reason: string } ).reason, "fuck no, I will not fix this" );
} );

test( "🔴 a refusal appears in the pane the operator actually clicked in", async () => {
  const ui = newUI();
  const id = "bc77cd79-7acc-4a99-8a27-8fc77d2cc1b3";
  twoPanesShowingTheSameRow( ui, id );
  ui._transitionTask = async () => ( { ok: true } );
  ui.refreshTaskList = async () => {};

  // Both boxes blank: the refusal is legitimate. The question is WHERE it is shown.
  const epic = document.getElementById( "epic-board-table" ) as HTMLElement;
  await ui._handleTaskWontFixClick( epic.querySelector( ".task-wont-fix-button" ) as HTMLElement );

  const epicStripe = epic.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( epicStripe.hidden, false,
    "the refusal was written into the other pane's stripe — from here the button looks dead" );
  assert.match( epicStripe.textContent ?? "", /reason is required/i );
} );


// ═══════════════════════ progressive disclosure — Rick's layout ═══════════════════════

function rowWithDisclosure( ui: HoldingUI, id: string, paneId: string ): string {
  const task = row( { id, status: "queued" } );
  return `
    <table id="${paneId}"><tbody>
      <tr><td>${ui._disclosureToggle( task )}</td></tr>
      <tr class="task-controls-row" data-controls-for="${id}" hidden><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr>
    </tbody></table>`;
}

test( "the controls row is HIDDEN by default and the toggle says so", () => {
  const ui = newUI();
  const id = "row-1";
  document.body.innerHTML = rowWithDisclosure( ui, id, "task-list-table" );

  const controls = document.querySelector( ".task-controls-row" ) as HTMLElement;
  const toggle   = document.querySelector( ".task-disclose-button" ) as HTMLElement;
  assert.equal( controls.hidden, true, "the controls row is visible before anyone asked for it" );
  assert.equal( toggle.getAttribute( "aria-expanded" ), "false" );
  // 🔴 aria-expanded, not a CSS class. A disclosure that exists only in styling is
  // invisible to a keyboard user, who then cannot reach any of these verbs at all.
  assert.equal( toggle.tagName, "BUTTON", "the disclosure affordance is not focusable" );
} );

test( "clicking the ellipsis discloses the controls, and clicking again hides them", () => {
  const ui = newUI();
  const id = "row-1";
  document.body.innerHTML = rowWithDisclosure( ui, id, "task-list-table" );
  const controls = document.querySelector( ".task-controls-row" ) as HTMLElement;
  const toggle   = document.querySelector( ".task-disclose-button" ) as HTMLElement;

  ui._handleDisclosureToggle( toggle );
  assert.equal( controls.hidden, false, "the controls did not appear" );
  assert.equal( toggle.getAttribute( "aria-expanded" ), "true" );
  assert.match( toggle.getAttribute( "title" ) ?? "", /Hide/ );

  ui._handleDisclosureToggle( toggle );
  assert.equal( controls.hidden, true, "the controls did not collapse again" );
  assert.equal( toggle.getAttribute( "aria-expanded" ), "false" );
} );

test( "collapsing clears the error stripe, so a stale refusal cannot outlive its form", () => {
  const ui = newUI();
  const id = "row-1";
  document.body.innerHTML = rowWithDisclosure( ui, id, "task-list-table" );
  const toggle = document.querySelector( ".task-disclose-button" ) as HTMLElement;
  const pane   = document.getElementById( "task-list-table" ) as HTMLElement;

  ui._handleDisclosureToggle( toggle );
  ui._renderTaskRowError( id, "A won't-fix reason is required.", pane );
  const stripe = document.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( stripe.hidden, false );

  ui._handleDisclosureToggle( toggle );   // collapse
  assert.equal( stripe.hidden, true,
    "a refusal is still on screen complaining about a form nobody can see any more" );
} );

test( "🔴 the ellipsis opens ITS OWN pane's controls, not the other pane's copy", () => {
  const ui = newUI();
  const id = "bc77cd79-7acc-4a99-8a27-8fc77d2cc1b3";
  // The exact shape that made Won't-fix look dead: one row, two panes, one id.
  document.body.innerHTML =
    rowWithDisclosure( ui, id, "task-list-table" ) + rowWithDisclosure( ui, id, "epic-board-table" );

  const epic = document.getElementById( "epic-board-table" ) as HTMLElement;
  const list = document.getElementById( "task-list-table" ) as HTMLElement;
  ui._handleDisclosureToggle( epic.querySelector( ".task-disclose-button" ) as HTMLElement );

  assert.equal( ( epic.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, false,
    "pressing the epic board's ellipsis opened nothing there" );
  assert.equal( ( list.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, true,
    "it opened the OTHER pane's controls — the same defect that made Won't-fix look dead" );
} );


test( "🔴 the REAL row renderers emit the controls row already hidden", () => {
  // ⚠️ THIS ASSERTS ON _renderTaskRow / _renderEpicRow, NOT ON A HAND-BUILT FIXTURE.
  // The disclosure tests above construct their own markup with `hidden` written in, so
  // they cannot see the renderer forgetting it — measured: deleting `hidden` from
  // _renderTaskRow left all four of them green while every row on the page shipped its
  // controls expanded, which is the exact layout Rick rejected.
  //
  // Same family as the other blind spots today: what the file HOLDS CONSTANT is what it
  // cannot see. Those tests hold the markup constant; this one varies it by taking the
  // real thing.
  const ui = newUI();
  for ( const render of [ "_renderTaskRow", "_renderEpicRow" ] as const ) {
    const host = document.createElement( "table" );
    host.innerHTML = `<tbody>${( ui[ render ] as ( t: unknown ) => string )( row( { id: "r1" } ) )}</tbody>`;
    const controls = host.querySelector( ".task-controls-row" ) as HTMLElement;
    assert.ok( controls, `${render} emits no controls row at all` );
    assert.equal( controls.hidden, true,
      `${render} ships its controls EXPANDED — the vertical stack of widgets Rick rejected` );
    assert.ok( host.querySelector( ".task-disclose-button" ), `${render} emits no disclosure affordance` );
    // The two rows must agree on the id, or the toggle opens nothing.
    assert.equal( ( host.querySelector( ".task-disclose-button" ) as HTMLElement ).dataset.taskId,
                  controls.dataset.controlsFor,
                  `${render}: the toggle and its controls row carry different ids` );
  }
} );

// ═══════════ Drop · Park · Demote — the three controls NOBODY HAS CLICKED YET ═══════════
//
// 🔴 THE COVERAGE HERE TRACKED WHICH BUTTONS A HUMAN HAPPENED TO PRESS, NOT WHICH ONES
// CAN BREAK. Won't-fix and Approve have guards because Rick hit them; Drop and Park had
// no test anywhere that drove their handler at all, and Demote had one whose first
// assertion could not see the guard it was named for.
//
// Measured across the whole 484-test notifications_js tier, one deliberate break each:
//
//   Drop sends the wrong verb (dropped -> done)      0 red
//   Drop's blank-reason guard deleted                0 red
//   Park sends the wrong verb (parked -> dropped)    0 red
//   Park's blank-reason guard deleted                0 red
//   Demote's blank-reason guard deleted              0 red
//   _controlScope drops its tight `.task-actions` leg 0 red
//
// ⚠️ "MISSING OR MERELY UNWATCHED" IS A FALSE PAIR — THERE IS A THIRD STATE, AND IT IS
// THE ONE THESE CONTROLS WERE IN: PRESENT, CORRECT, AND UNTESTABLE-IF-WRONG. Read in the
// source before writing a line of this: Drop checks its reason, Park checks reason +
// chase + date-parse, Demote checks reason + chase + date-parse. Every one of them was
// right. What was absent was any test that could have noticed if it weren't.
//
// ⇒ So these are GREEN on today's client and redden only under mutation, and that is the
// expected result rather than a weak one. A test that went red on arrival would have been
// evidence of a live defect — a different finding with a different owner. Which state you
// are in is settled by deleting the guard and watching a NAMED test that was passing at
// baseline go red; each of the seven below does exactly that, one test per break.
//
// 🔴 AND WHY DEMOTE'S EXISTING TEST COULD NOT SEE ITS OWN GUARD: it leaves BOTH the
// reason and the chase blank, then asserts the server was not called. Either guard alone
// satisfies that, so deleting the reason check changes nothing observable — the chase
// check catches the same case and the assertion passes. The fixture cannot discriminate
// between the two, whatever the test's name says. Every blank-reason case below fills
// the OTHER field, so exactly one guard can be responsible for the refusal.

function dropRowDOM( id: string, reason = "" ): void {
  document.body.innerHTML = `
    <table><tbody>
      <tr><td class="task-actions">
        <input class="task-action-input task-drop-reason" data-task-id="${id}" value="${reason}">
        <button class="task-action-btn task-drop-button" data-task-id="${id}">Drop</button>
      </td></tr>
      <tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr>
    </tbody></table>`;
}

function parkRowDOM( id: string, reason = "", chase = "" ): void {
  document.body.innerHTML = `
    <table><tbody>
      <tr><td class="task-actions">
        <input class="task-action-input task-park-reason" data-task-id="${id}" value="${reason}">
        <input class="task-action-input task-park-chase"  data-task-id="${id}" value="${chase}">
        <button class="task-action-btn task-park-button" data-task-id="${id}">Park</button>
      </td></tr>
      <tr class="task-row-error-stripe" data-error-for="${id}" hidden><td></td></tr>
    </tbody></table>`;
}

function recordingUI(): { ui: HoldingUI; calls: Array<[ string, string, unknown ]> } {
  const ui = newUI();
  const calls: Array<[ string, string, unknown ]> = [];
  ui._transitionTask = async ( id, to, extras ) => { calls.push( [ id, to, extras ] ); return { ok: true }; };
  ui.refreshTaskList = async () => {};
  return { ui, calls };
}

const CTRL_ID = "aaaaaaaa-1111-2222-3333-444444444444";

test( "🔴 Drop sends `dropped` — the verb is asserted, so a wrong terminal state cannot ship", async () => {
  // ⚠️ THIS IS UI CORRECTNESS, NOT DATA INTEGRITY, and the first cut of this comment had
  // it wrong. It claimed `dropped` -> `done` would write the wrong terminal state to the
  // store. It would not: the server refuses it twice over — `validate_transition` gives
  // done/dropped/wont_fix no out-edges at all, and a live row reaching `->done` must
  // carry a CHECKABLE receipt (a real commit/qid/test_run), which a button does not have.
  // The button would simply fail in a way the operator could not explain. Left visible
  // rather than quietly deleted, because "wrong verb" reads like a store problem and the
  // instinct to file it as one is what has to be corrected.
  const { ui, calls } = recordingUI();
  dropRowDOM( CTRL_ID, "superseded by the epic board" );

  await ui._handleTaskDropClick( document.querySelector( ".task-drop-button" ) );
  assert.equal( calls.length, 1, "Drop never reached the server" );
  assert.equal( calls[ 0 ][ 1 ], "dropped", "Drop sent the wrong transition verb" );
  assert.equal( ( calls[ 0 ][ 2 ] as { reason: string } ).reason, "superseded by the epic board",
    "the typed reason is not what got sent" );
} );

test( "🔴 Drop refuses a blank reason, tells the operator why, and calls nobody", async () => {
  const { ui, calls } = recordingUI();
  dropRowDOM( CTRL_ID, "" );

  await ui._handleTaskDropClick( document.querySelector( ".task-drop-button" ) );
  assert.equal( calls.length, 0, "a blank drop reason reached the server" );
  const stripe = document.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( stripe.hidden, false, "the refusal is invisible — the row looks like nothing happened" );
  assert.match( stripe.textContent ?? "", /reason is required/i );
} );

test( "🔴 Park sends `parked` with the reason AND a real chase instant", async () => {
  const { ui, calls } = recordingUI();
  parkRowDOM( CTRL_ID, "waiting on Rick's ruling", "2026-09-10" );

  await ui._handleTaskParkClick( document.querySelector( ".task-park-button" ) );
  assert.equal( calls.length, 1, "Park never reached the server" );
  assert.equal( calls[ 0 ][ 1 ], "parked", "Park sent the wrong transition verb" );
  // NOTE the field name: Park sends `park_reason`, where Drop and Won't-fix send
  // `reason`. Asserting `reason` here passes `undefined === undefined` against a handler
  // that sends nothing at all, so the specific name is the assertion.
  const extras = calls[ 0 ][ 2 ] as { park_reason: string; next_chase_ts: string };
  assert.equal( extras.park_reason, "waiting on Rick's ruling" );
  // Same local-day trap the demote test already guards: a bare "YYYY-MM-DD" read as
  // midnight UTC lands the chase on the previous evening for everyone west of Greenwich.
  const sent = new Date( extras.next_chase_ts );
  assert.ok( sent.getTime() > new Date( "2026-09-10" ).getTime(),
    `chase ${extras.next_chase_ts} is not later than bare-midnight-UTC — the local stamp is gone` );
  assert.equal( sent.getDate(), 10, "the chase landed on the wrong calendar day locally" );
} );

test( "🔴 Park refuses a blank REASON specifically — the chase date is filled in", async () => {
  // The discriminating fixture. With both fields blank either guard explains the
  // refusal, so deleting one is invisible; filling the chase leaves exactly one.
  const { ui, calls } = recordingUI();
  parkRowDOM( CTRL_ID, "", "2026-09-10" );

  await ui._handleTaskParkClick( document.querySelector( ".task-park-button" ) );
  assert.equal( calls.length, 0, "a blank park reason reached the server" );
  assert.match( ( document.querySelector( ".task-row-error-stripe" ) as HTMLElement ).textContent ?? "",
    /park reason is required/i );
} );

test( "🔴 Park refuses a blank CHASE DATE specifically — the reason is filled in", async () => {
  const { ui, calls } = recordingUI();
  parkRowDOM( CTRL_ID, "waiting on Rick's ruling", "" );

  await ui._handleTaskParkClick( document.querySelector( ".task-park-button" ) );
  assert.equal( calls.length, 0, "an unbounded park reached the server" );
  assert.match( ( document.querySelector( ".task-row-error-stripe" ) as HTMLElement ).textContent ?? "",
    /chase date is required/i );
} );

test( "🔴 Demote refuses a blank REASON specifically — the triage-by date is filled in", async () => {
  // The gap in the existing demote test, named and closed. That one leaves both fields
  // blank, so its "a blank demote reason reached the server" assertion is satisfied by
  // the CHASE guard and stays green with the reason guard deleted.
  const { ui, calls } = recordingUI();
  document.body.innerHTML = `
    <table><tbody>
      <tr><td class="task-actions">
        <input class="task-action-input task-demote-reason" data-task-id="${CTRL_ID}" value="">
        <input class="task-action-input task-demote-chase"  data-task-id="${CTRL_ID}" value="2026-09-10">
        <button class="task-action-btn task-demote-button" data-task-id="${CTRL_ID}">Demote</button>
      </td></tr>
      <tr class="task-row-error-stripe" data-error-for="${CTRL_ID}" hidden><td></td></tr>
    </tbody></table>`;

  await ui._handleTaskDemoteClick( document.querySelector( ".task-demote-button" ) );
  assert.equal( calls.length, 0, "a blank demote reason reached the server" );
  assert.match( ( document.querySelector( ".task-row-error-stripe" ) as HTMLElement ).textContent ?? "",
    /demote reason is required/i );
} );

test( "🔴 _controlScope reads the input in the CLICKED row's own cell, not the first match", async () => {
  // This is the cd2ea523 defect one level tighter: not two panes, two ROWS IN ONE TABLE
  // carrying the same task id. `.task-actions` is the leg that separates them — drop it
  // and the fallback to the enclosing table matches both rows, so the handler sends the
  // OTHER row's text. Both scopes are inside the same table, so `_paneScope` cannot see
  // this and the existing two-pane test does not cover it.
  const { ui, calls } = recordingUI();
  document.body.innerHTML = `
    <table><tbody>
      <tr><td class="task-actions">
        <input class="task-action-input task-drop-reason" data-task-id="${CTRL_ID}" value="THE FIRST ROW'S TEXT">
        <button class="task-action-btn task-drop-button" data-task-id="${CTRL_ID}" id="first">Drop</button>
      </td></tr>
      <tr><td class="task-actions">
        <input class="task-action-input task-drop-reason" data-task-id="${CTRL_ID}" value="THE SECOND ROW'S TEXT">
        <button class="task-action-btn task-drop-button" data-task-id="${CTRL_ID}" id="second">Drop</button>
      </td></tr>
      <tr class="task-row-error-stripe" data-error-for="${CTRL_ID}" hidden><td></td></tr>
    </tbody></table>`;

  await ui._handleTaskDropClick( document.getElementById( "second" ) );
  assert.equal( calls.length, 1, "Drop never reached the server" );
  assert.equal( ( calls[ 0 ][ 2 ] as { reason: string } ).reason, "THE SECOND ROW'S TEXT",
    "the handler sent a different row's reason — the scope fell back past `.task-actions`" );
} );

// ══════ THE PANE ITSELF HAD NO CLICK LISTENER — every control in it was dead ══════
//
// 🔴 THE ASYMMETRY IS THE FINDING, not the added listener. `renderTaskList` wires one
// (`_wireTaskListAccordion`) and `renderEpicBoard` wires one (`_wireEpicBoardAccordion`);
// `renderHoldingArea` wired NOTHING. All three panes render the same controls, two were
// wired by hand and the third was simply forgotten — so batch approve, batch won't-fix
// and all five per-row controls painted correctly and their clicks landed on no handler.
// This pane exists for exactly those controls.
//
// It hid because every control test in the tree calls the handler DIRECTLY. A handler
// called by name always runs; what these ask instead is whether a real click gets to it.
//
// ⚠️ THIS FIX REPAIRS A DEFECT AND ATTRIBUTES NOTHING. It is tempting to read it as the
// explanation for a dead Won't-fix button reported earlier, and that inference is not
// available: the server-side measurement behind that report — zero `wont_fix` events
// store-wide — has MORE THAN ONE SUFFICIENT CAUSE. A lookup collision swallowing the
// click produces it, and so does a pane with no listener. An observation satisfiable by
// two mechanisms cannot tell you which one ran, which is the same rule the tests in this
// file apply to fixtures, arriving on a diagnosis instead. Settling it needs a store fact
// about which pane the row was in, and that is not a client question.

function realPageDOM(): void {
  // The page's actual shape: notifications.html has #task-list-container at :774 and
  // #holding-area-container at :812 as SIBLING sections. A nested fixture would let the
  // task list's listener catch these clicks and hide the defect entirely.
  document.body.innerHTML = `
    <div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div>
    </div>
    <div class="collapsible-section" id="section-holding-area">
      <div class="section-content" id="holding-area-section">
        <div id="holding-area-container"></div>
      </div>
    </div>`;
}

const HELD_ROWS = [
  row( { id: "h1", status: "not_approved" } ),
  row( { id: "h2", status: "not_approved" } )
];

function paintedHoldingPane( ui: HoldingUI ): void {
  realPageDOM();
  ui._wireTaskListAccordion();                     // the sibling pane wires itself as usual
  ui.renderHoldingArea( { status: "ok", tasks: HELD_ROWS } );
}

function clickIt( el: Element | null, what: string ): void {
  assert.ok( el, `${what} did not render at all — this test cannot speak to wiring` );
  el!.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
}

test( "🔴 THROUGH THE CLICK PATH: batch APPROVE-ALL reaches its handler", () => {
  const ui = newUI();
  let got: string | null = null;
  ui._handleHoldingApproveAllClick = async ( b ) => { got = ( b as HTMLElement ).dataset.filer ?? ""; };
  paintedHoldingPane( ui );

  clickIt( document.querySelector( ".holding-approve-all" ), "batch approve" );
  assert.ok( got !== null, "batch approve reached no handler — the pane has no click listener" );
} );

test( "🔴 THROUGH THE CLICK PATH: batch WON'T-FIX-ALL reaches its handler", () => {
  const ui = newUI();
  let got: string | null = null;
  ui._handleHoldingWontFixAllClick = async ( b ) => { got = ( b as HTMLElement ).dataset.filer ?? ""; };
  paintedHoldingPane( ui );

  clickIt( document.querySelector( ".holding-wont-fix-all" ), "batch won't-fix" );
  assert.ok( got !== null, "batch won't-fix reached no handler — the pane has no click listener" );
} );

test( "🔴 THROUGH THE CLICK PATH: a PER-ROW control in this pane reaches its handler", () => {
  const ui = newUI();
  let got: string | null = null;
  ui._handleTaskWontFixClick = async ( b ) => { got = ( b as HTMLElement ).dataset.taskId ?? ""; };
  paintedHoldingPane( ui );

  clickIt( document.querySelector( "#holding-area-container .task-wont-fix-button" ),
           "a per-row won't-fix in the holding pane" );
  assert.equal( got, "h1", "a per-row control in the holding pane reached no handler" );
} );

test( "the sibling task-list pane still routes its own clicks — the panes do not steal from each other", () => {
  // Positive control for the three above. Both containers now carry a listener; a click
  // must reach exactly one handler, from the pane it was made in.
  const ui = newUI();
  const reached: string[] = [];
  ui._handleTaskWontFixClick = async ( b ) => { reached.push( ( b as HTMLElement ).dataset.taskId ?? "" ); };
  paintedHoldingPane( ui );
  document.getElementById( "task-list-container" )!.innerHTML =
    `<table>${ui._renderTaskRow( row( { id: "tl1", status: "not_approved" } ), undefined )}</table>`;

  clickIt( document.querySelector( "#task-list-container .task-wont-fix-button" ), "task-list won't-fix" );
  assert.deepEqual( reached, [ "tl1" ], "the task-list pane's own click no longer reaches its handler" );
} );

test( "the pane's listener is installed ONCE, however many times it repaints", () => {
  // The pane repaints on every poll. An un-guarded wire would stack a listener per paint
  // and fire the handler N times for one click — N transitions from one press.
  const ui = newUI();
  let calls = 0;
  ui._handleHoldingApproveAllClick = async () => { calls += 1; };
  paintedHoldingPane( ui );
  ui.renderHoldingArea( { status: "ok", tasks: HELD_ROWS } );
  ui.renderHoldingArea( { status: "ok", tasks: HELD_ROWS } );

  clickIt( document.querySelector( ".holding-approve-all" ), "batch approve" );
  assert.equal( calls, 1, "one press fired the batch handler more than once" );
} );

test( "🔴 _heldRowIdsForFiler collects ONLY its own group — a batch cannot reach across groups", () => {
  // The third member of the two-pane-lookup family, and the widest: `_controlScope` and
  // `_paneScope` each govern ONE row, this governs EVERY row a batch touches. It resolves
  // via `document.querySelector` on the group, so the group filter is the only thing
  // keeping one filer's batch off another filer's rows — and dropping it reddened nothing.
  const ui = newUI();
  document.body.innerHTML = `
    <div id="holding-area-container">
      <div class="holding-area-group" data-filer="alice">
        <button class="task-action-btn task-approve-button" data-task-id="a1"></button>
        <button class="task-action-btn task-approve-button" data-task-id="a2"></button>
      </div>
      <div class="holding-area-group" data-filer="bob">
        <button class="task-action-btn task-approve-button" data-task-id="b1"></button>
      </div>
    </div>`;

  assert.deepEqual( ui._heldRowIdsForFiler( "alice" ), [ "a1", "a2" ] );
  assert.deepEqual( ui._heldRowIdsForFiler( "bob" ), [ "b1" ],
    "bob's batch collected alice's rows — the group scope is gone" );
  assert.deepEqual( ui._heldRowIdsForFiler( "carol" ), [],
    "an unknown filer collected rows that are not in its group" );
} );

test( "🔴 batch APPROVE sends `queued` and batch WON'T-FIX sends `wont_fix`", async () => {
  // Both verbs were unasserted: a batch acts on every row in a group, so a wrong one is
  // the whole pane rather than one row.
  const ui = newUI();
  const sent: Array<[ string, string ]> = [];
  ui._transitionTask = async ( id, to ) => { sent.push( [ id, to ] ); return { ok: true }; };
  ui.refreshHoldingArea = async () => {};
  document.body.innerHTML = `
    <div id="holding-area-container">
      <div class="holding-area-group" data-filer="alice">
        <button class="task-action-btn task-approve-button" data-task-id="a1"></button>
        <input class="task-action-input holding-wont-fix-all-reason" data-filer="alice" value="closing the lot">
      </div>
    </div>`;

  await ui._handleHoldingApproveAllClick( { dataset: { filer: "alice" } } );
  assert.deepEqual( sent, [ [ "a1", "queued" ] ], "batch approve sent the wrong transition verb" );

  sent.length = 0;
  await ui._handleHoldingWontFixAllClick( { dataset: { filer: "alice" } } );
  assert.deepEqual( sent, [ [ "a1", "wont_fix" ] ], "batch won't-fix sent the wrong transition verb" );
} );

// ═════════ three more the batch was doing correctly and unwatched ═════════
//
// Found by continuing to pose breaks after the obvious ones were covered, rather than
// stopping when the list I started with was green. Each scored ZERO reds across the whole
// tier before these; each is behaviour the code already gets right.

function batchDOM( ids: string[], reason = "closing the lot" ): void {
  document.body.innerHTML = `
    <div id="holding-area-container">
      <div class="holding-area-group" data-filer="alice">
        <span class="holding-area-group-status" data-filer="alice"></span>
        ${ids.map( i => `<button class="task-action-btn task-approve-button" data-task-id="${i}"></button>` ).join( "" )}
        <input class="task-action-input holding-wont-fix-all-reason" data-filer="alice" value="${reason}">
      </div>
    </div>`;
}

function statusText(): string {
  return ( document.querySelector( ".holding-area-group-status" ) as HTMLElement ).textContent ?? "";
}

test( "🔴 a partial refusal reports the FIRST server message, not the last", async () => {
  // The docstring is explicit that the first is the one worth keeping — on a 403 it names
  // the actor and the allowlist, and later rows produce the same refusal with less in it.
  // Nothing was checking WHICH one survived, so keeping the last read identically.
  const ui = newUI();
  let n = 0;
  ui._transitionTask = async () => {
    n += 1;
    if ( n === 1 ) return { ok: false, message: "403: rio is not on the approve allowlist" };
    if ( n === 2 ) return { ok: false, message: "403: forbidden" };
    return { ok: true };
  };
  ui.refreshHoldingArea = async () => {};
  batchDOM( [ "a1", "a2", "a3" ] );

  const out = await ui._applyHoldingBatch( "alice", "queued", {}, "Approved" );
  assert.equal( out.failed, 2 );
  assert.match( out.firstError ?? "", /not on the approve allowlist/,
    "the batch kept a later, less informative refusal instead of the first" );
  assert.match( statusText(), /not on the approve allowlist/ );
} );

test( "🔴 the batch REFRESHES the pane when it is done", async () => {
  // Without the refresh the rows it just transitioned stay on screen, so a batch that
  // fully succeeded looks like a batch that did nothing at all.
  const ui = newUI();
  let refreshed = 0;
  ui._transitionTask = async () => ( { ok: true } );
  ui.refreshHoldingArea = async () => { refreshed += 1; };
  batchDOM( [ "a1", "a2" ] );

  await ui._applyHoldingBatch( "alice", "queued", {}, "Approved" );
  assert.equal( refreshed, 1, "the pane was never repainted — the rows it moved are still on screen" );
} );

test( "🔴 an EMPTY group says so and calls nobody", async () => {
  const ui = newUI();
  let calls = 0;
  ui._transitionTask = async () => { calls += 1; return { ok: true }; };
  ui.refreshHoldingArea = async () => {};
  batchDOM( [] );

  const out = await ui._applyHoldingBatch( "alice", "queued", {}, "Approved" );
  assert.equal( calls, 0, "an empty group still fired requests" );
  assert.deepEqual( out, { ok: 0, failed: 0, firstError: null } );
  assert.match( statusText(), /No rows in this group/,
    "an empty group reported nothing, which reads as a batch that silently did nothing" );
} );
