// THE PRIORITY SELECT MUST SURVIVE THE POLL REPAINT — Rick's "permanently disabled".
//
// RICK, 2026-09-03, in his own words: "it is permanently disabled. No change in value
// re-enables the update button."
//
// 🔴 THAT IS NOT WHAT THE CONTROL DOES WHEN YOU CALL IT BY NAME. `_handlePrioritySelectChange`
// enables the button correctly, and seven arms in row_control_redesign.test.ts prove it,
// as do Pocholo's twelve per-pane arms with a real bubbling `change`. What none of those
// can see is A POLL LANDING BETWEEN THE CHOICE AND THE CLICK. `renderTaskList` repaints by
// replacing `container.innerHTML` every 60 seconds; `_captureOperatorState` carries the
// verb selects, the typed boxes, the error stripes and the disclosed rows across that
// assignment — and, at the sha this file was written against, NOT the priority select.
// So the repaint recreates the select at the row's stored priority and the button at its
// rendered `disabled`, silently undoing both.
//
// From the operator's side that is indistinguishable from a button that never works:
// choose, wait, click, nothing — and no evidence afterwards, because the fresh markup
// looks exactly like a control nobody has touched.
//
// ⚠️ THIS IS THE SAME DEFECT THE CODEBASE ALREADY FIXED FOR THE REASON BOX. The capture
// helper's own docstring is about Rick's dead Won't-fix button. A control was added to
// the cell without being joined to that repair — which is why these arms drive
// `renderTaskList`, the layer the incident enters at. A test calling the capture helpers
// directly would be describing the fix rather than the failure.
//
// ⚠️ WHAT THIS FILE DOES NOT CLAIM. It does not claim to be the whole of Rick's report.
// Capture-omission predicts "my choice reverts on the next tick"; whether that is also
// what he means by "no change re-enables it" is a separate measurement (Pocholo's point,
// and he is right to insist on the split).
//
// ─────────────────────────────────────────────────────────────────────────────────────
// 🔴 WHY THE ROW IS PAINTED P0 AND THE OPERATOR CHOOSES P2. THIS IS NOT ARBITRARY, AND
// CHANGING IT SILENTLY BREAKS THE FILE.
//
// happy-dom does not re-sync a select's `selectedIndex` from the `selected` ATTRIBUTE
// after an `innerHTML` rewrite. Measured on this exact markup, on a FRESH paint that
// nobody has touched:
//
//     stored P0 -> .value "P0"  ok         stored P2 -> .value "P1"  WRONG (markup says P2)
//     stored P1 -> .value "P1"  ok         stored P3 -> .value "P1"  WRONG (markup says P3)
//
// So a row painted at P3 reports `.value === "P1"` before anybody selects anything. An
// arm that painted P3 and chose P1 would read "P1" both before AND after the repaint and
// pass while measuring nothing — that arm was written first, it passed, and it was WRONG.
// Setting `.value` programmatically is reliable; only the read after a paint is not.
//
// P0/P2 is the pair where every read is correct, so the assertion can actually fail.
// `FIXTURE GUARD` below is the check on that, and it is the first thing to look at if
// this file ever starts behaving strangely.
// ─────────────────────────────────────────────────────────────────────────────────────
//
// Run: npx tsx --test src/tests/unit/notifications_js/priority_survives_a_repaint.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

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

const ROW_ID  = "bbbbbbbb-1111-2222-3333-555555555555";
const PAINTED = "P0";   // see the block above — not interchangeable
const CHOSEN  = "P2";   // see the block above — not interchangeable

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
  // localStorage-backed collapse state is irrelevant here and its absence would throw.
  ui.loadCollapsedTaskOwners = (): Set<string> => new Set<string>();
  ui._stampTaskListUpdated   = (): void => {};
  return ui;
}

function taskRow( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id            : ROW_ID,
    item_class    : "task",
    title         : "a row whose priority the operator is changing",
    status        : "queued",
    priority      : PAINTED,
    owner_persona : "maya",
    project       : "lupin",
    ...over,
  };
}

let ui: any;
let container: HTMLElement;

beforeEach( () => {
  ui = newUI();
  document.body.innerHTML = `<div id="task-list-container"></div><span id="task-list-count"></span>`;
  container = document.getElementById( "task-list-container" ) as HTMLElement;
} );

/** One poll tick, through the REAL repaint path the 60-second timer uses. */
function poll( tasks: Record<string, unknown>[] ): void {
  ui.renderTaskList( { tasks, count: tasks.length, total: tasks.length, has_more: false }, false );
}

function controls() {
  const select = container.querySelector( ".task-priority-select" ) as HTMLSelectElement | null;
  const button = container.querySelector( ".task-priority-update" ) as HTMLButtonElement | null;
  return { select, button };
}

/** Choose a priority the way an operator does — set the value, then fire the handler. */
function choose( value: string ): void {
  const { select } = controls();
  select!.value = value;
  ui._handlePrioritySelectChange( select );
}

test( "FIXTURE GUARD: the harness reports the painted priority honestly", () => {
  poll( [ taskRow() ] );
  const { select } = controls();
  const marked = select!.querySelector( "option[selected]" );
  assert.equal( marked?.getAttribute( "value" ), PAINTED, "the markup must mark the row's priority" );
  assert.equal( select!.value, PAINTED,
    `the DOM implementation reports .value='${select!.value}' for a select whose markup ` +
    `marks '${PAINTED}' — every value assertion in this file is unreadable until that is ` +
    `true. See the header block: this is why the row is painted P0 and not P3.` );
  assert.equal( select!.dataset.original, PAINTED );
} );

test( "POSITIVE CONTROL: the repaint path paints a priority select and an inert Update button", () => {
  poll( [ taskRow() ] );
  const { select, button } = controls();
  assert.ok( select, "renderTaskList painted no .task-priority-select — every assertion below would pass vacuously" );
  assert.ok( button, "renderTaskList painted no .task-priority-update" );
  assert.equal( button!.disabled, true, "a freshly painted Update must start inert" );
} );

test( "POSITIVE CONTROL: choosing a different priority enables Update (no repaint in between)", () => {
  poll( [ taskRow() ] );
  choose( CHOSEN );
  assert.equal( controls().button!.disabled, false,
    "the control does not enable at all — that would be a defect in the CHANGE handler, " +
    "not the repaint, and the two repaint arms below cannot be read until this passes" );
} );

test( "THE CHOSEN PRIORITY SURVIVES A POLL REPAINT", () => {
  poll( [ taskRow() ] );
  choose( CHOSEN );

  poll( [ taskRow() ] );   // the 60-second tick lands between the choice and the click

  assert.equal( controls().select!.value, CHOSEN,
    `the poll repaint threw away the operator's chosen priority and put the row's stored ` +
    `'${PAINTED}' back — choose, wait one tick, click, and nothing happens` );
} );

test( "UPDATE IS STILL ENABLED AFTER A POLL REPAINT", () => {
  poll( [ taskRow() ] );
  choose( CHOSEN );

  poll( [ taskRow() ] );

  assert.equal( controls().button!.disabled, false,
    "the value may have been restored, but the button was left at the fresh markup's " +
    "`disabled` — restoring the value without recomputing the button is half a repair, " +
    "and the operator still cannot click" );
} );

test( "AND THE CONTROL STILL GOES INERT when the board catches up to the chosen value", () => {
  poll( [ taskRow() ] );
  choose( CHOSEN );

  // The row itself moves to the chosen value — this operator's PATCH landed, or somebody
  // else applied it. There is now nothing left to submit.
  poll( [ taskRow( { priority: CHOSEN } ) ] );

  assert.equal( controls().button!.disabled, true,
    "after the board caught up there is no pending edit, so Update must go inert — a " +
    "restore that force-enables would leave a live button over a no-op" );
} );

test( "a row that LEAVES the board takes its unsaved priority with it, without throwing", () => {
  poll( [ taskRow() ] );
  choose( CHOSEN );

  poll( [] );   // somebody closed it

  // Boolean, not the node: a failing `assert.equal( element, null )` makes node:assert
  // stringify a happy-dom element and walk its circular parent chain, killing the run
  // with SIGKILL and `0 passed` instead of naming this test.
  assert.equal( controls().select !== null, false, "the row is gone, so its select is gone" );
} );
