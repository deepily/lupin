// THE LEGACY CLIENT'S PRIORITY SELECT MUST OFFER EVERY VALUE THE STORE ACCEPTS.
//
// Rick widened the priority space from P0-P3 to P0-P5 by broadcast (row b8205986, P0-A).
// Two clients render that select, and by his no-code-reuse ruling they each carry their
// own copy of the list:
//
//     src/lupin_app/static/js/notifications.js                  const known
//     the multiplexer's task-list model                         EDITABLE_PRIORITIES
//
// The MULTIPLEXER copy is guarded — templates_task_list_table.test.ts deepEquals the
// rendered option values against [ P0 .. P5 ].
//
// 🔴 THE LEGACY COPY WAS NOT, AND THAT WAS MEASURED RATHER THAN ASSUMED. Reverting
// `known` to [ P0, P1, P2, P3 ] in a throwaway worktree left 550 tests GREEN across all
// 14 TypeScript files that name `.task-priority-select` — so a silent undo of a P0 the
// operator ruled by broadcast had nothing standing in its way. This file is that guard.
//
// ⚠️ WHY deepEqual AND NOT A COUNT OR AN includes(). A count of six passes for six WRONG
// values. An `includes( "P5" )` passes for a seven-option select that also offers "P9".
// The LIST and its ORDER are the claim, so the assertion has to be the list and its order.
//
// ⚠️ AND WHY THE SELECT IS ASSERTED PRESENT BEFORE ANYTHING IS READ OFF IT. A querySelector
// that returns null makes every per-option assertion below it vacuous — a loop over zero
// options passes perfectly. The `assert.ok` is what stops this file going green on a row
// that renders no select at all.
//
// The harness mirrors priority_survives_a_repaint.test.ts deliberately: same bootstrap,
// same real `renderTaskList` path, so this guard watches the painted DOM rather than the
// source text of the array.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

/** The store's own value space, per task_store_rules.VALID_PRIORITIES. */
const EVERY_PRIORITY = [ "P0", "P1", "P2", "P3", "P4", "P5" ];

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

function newUI(): any {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui: any = Object.create( Ctor.prototype );
  ui.debug                   = false;
  ui.log                     = (): void => {};
  ui.error                   = (): void => {};
  ui.TASK_TITLE_TRUNCATE_LEN = 60;
  ui.queueSessionId          = "test-session";
  ui._taskListPressInFlight  = false;
  ui._taskListLastGoodTasks  = null;
  ui.loadCollapsedTaskOwners = (): Set<string> => new Set<string>();
  ui._stampTaskListUpdated   = (): void => {};
  return ui;
}

let ui: any;
let container: HTMLElement;

beforeEach( () => {
  ui = newUI();
  document.body.innerHTML = `<div id="task-list-container"></div><span id="task-list-count"></span>`;
  container = document.getElementById( "task-list-container" ) as HTMLElement;
} );

function paint( priority: string ): HTMLSelectElement {
  const tasks = [ {
    id            : "bbbbbbbb-1111-2222-3333-555555555555",
    item_class    : "task",
    title         : "a row whose priority select is under inspection",
    status        : "queued",
    priority,
    owner_persona : "maya",
    project       : "lupin",
  } ];
  ui.renderTaskList( { tasks, count: 1, total: 1, has_more: false }, false );

  const sel = container.querySelector( ".task-priority-select" ) as HTMLSelectElement | null;
  // The positive control for every assertion below: without this, a null select would
  // make the option loop vacuous and this file would pass while measuring nothing.
  assert.ok( sel, "the row must render a priority select at all" );
  return sel as HTMLSelectElement;
}

test( "the legacy client offers every priority the store accepts, in order", () => {
  const sel = paint( "P2" );
  assert.deepEqual(
    Array.from( sel.options ).map( o => o.value ),
    EVERY_PRIORITY,
    "the legacy select's option list must be exactly the store's value space, in order"
  );
} );

// 🔴 AN ARM THAT ASSERTED `sel.value === <stored priority>` WAS WRITTEN HERE, IT FAILED,
// AND IT WAS REMOVED RATHER THAN WORKED AROUND. happy-dom does not re-sync a select's
// `selectedIndex` from the `selected` ATTRIBUTE after an `innerHTML` rewrite, so a row
// painted at P2 reports `.value === "P1"` before anybody touches it. The sibling file
// priority_survives_a_repaint.test.ts measures and documents that same quirk.
//
// ⇒ The arm was reporting on the DOM SHIM, not on the client. Keeping it — with a
// workaround, or with its expectation adjusted to "P1" — would have pinned a happy-dom
// behaviour under a name that claims to be about Lupin's priority space. The two
// surviving arms read `options`, which the shim does report faithfully.

test( "the newly-added values are reachable, named separately from the list check", () => {
  // P4 and P5 are the two Rick's widening added. Named on their own so a failure says
  // WHICH half broke rather than only that the list moved.
  const values = Array.from( paint( "P5" ).options ).map( o => o.value );
  assert.ok( values.includes( "P4" ), "P4 is missing from the legacy select" );
  assert.ok( values.includes( "P5" ), "P5 is missing from the legacy select" );
} );
