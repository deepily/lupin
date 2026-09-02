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
