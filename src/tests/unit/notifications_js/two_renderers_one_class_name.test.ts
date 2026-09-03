// 🔴 `.task-priority-select` NAMES TWO DIFFERENT CONTROLS, WITH OPPOSITE SEMANTICS.
//
// Measured 2026-09-03, while chasing a report that the priority Update button was dead.
// A search for the class name found matches in both the classic notifications page and
// the multiplexer bundle, and the two matches are not the same control:
//
//   CLASSIC  (notifications.js, `_priorityCell`)          multiplexer (taskListTable.ts,
//     select + `.task-priority-update` button              `renderActionsCell`)
//     inside `.task-actions`                                 select alone, inside
//     button disabled until the value differs                `td.task-col-actions`
//     PATCHes on the CLICK                                   NO button at all
//                                                            PATCHes ON CHANGE
//
// ⚠️ WHY THIS IS WORTH A FILE. A guard written against one renderer says nothing about
// the other AND DOES NOT LOOK WRONG WHILE FAILING TO: the selector matches in both, the
// test goes green, and the renderer you meant was never exercised. That is this repo's
// "a hit is not a use", except the hits are in two different products wearing one name —
// so even reading the match does not save you unless you notice which file it came from.
//
// The concrete trap, and the reason this was nearly reported as a live defect: the built
// multiplexer bundle contains `task-priority-select` and contains NEITHER
// `task-priority-update` NOR `.task-actions`. Grep the class name across the tree and you
// get hits in both; grep the button and you get one. Nothing in either result tells you
// there are two controls.
//
// 🔴 THIS FILE DRIVES BOTH RENDERERS FOR REAL — it does not grep either one. A source-text
// guard would be the same defect one level up: it would match strings in files without
// establishing what those files BUILD. Both renderers are importable, so there is no
// excuse for asserting on their text.
//
// WHAT WOULD MAKE THIS FILE FAIL, and each is a decision somebody should make on purpose:
//   · the two renderers are unified (then delete this file and say so)
//   · either grows or loses the Update button
//   · the multiplexer stops committing on change, or the classic page starts
//
// Run: npx tsx --test src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderTaskRow } from "../../../lupin_app/static/js/multiplexer/render/templates/taskListTable";
import type { TaskItem } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const SELECTOR = ".task-priority-select";

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

/** The CLASSIC page's actions cell, built by the real `_taskActionsCell`. */
function classicCell(): HTMLElement {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui: any = Object.create( Ctor.prototype );
  ui.debug = false; ui.log = (): void => {}; ui.error = (): void => {};
  ui.TASK_TITLE_TRUNCATE_LEN = 60; ui.queueSessionId = "test-session";

  const host = document.createElement( "div" );
  host.innerHTML = ui._taskActionsCell( {
    id: "aaaa1111-2222-3333-4444-555566667777", item_class: "task",
    title: "row", status: "queued", priority: "P0", project: "lupin",
  } );
  return host;
}

/** The MULTIPLEXER's actions cell, built by the real exported `renderTaskRow`. */
function multiplexerRow(): HTMLTableRowElement {
  const task: TaskItem = {
    title: "row", item_class: "task", status: "queued", priority: "P0", project: "lupin",
  };
  return renderTaskRow( task, "America/New_York" );
}

test( "POSITIVE CONTROL: the collision is real — BOTH renderers paint the same class", () => {
  assert.ok( classicCell().querySelector( SELECTOR ),
    `the classic renderer no longer paints ${SELECTOR} — if the control moved or was ` +
    `renamed, this whole file is describing a collision that no longer exists` );
  assert.ok( multiplexerRow().querySelector( SELECTOR ),
    `the multiplexer no longer paints ${SELECTOR} — same conclusion, other side` );
} );

test( "THE CLASSIC renderer pairs the select with an Update button, inside .task-actions", () => {
  const host   = classicCell();
  const select = host.querySelector( SELECTOR ) as HTMLElement;
  const button = host.querySelector( ".task-priority-update" ) as HTMLButtonElement | null;

  assert.ok( button, "the classic Update button is gone — the click-to-commit contract is broken" );
  assert.equal( ( button as HTMLButtonElement ).disabled, true,
    "the classic button must start inert; enabling only on a real change is its whole point" );
  assert.ok( select.closest( ".task-actions" ),
    "the classic select must sit inside .task-actions — `_handlePrioritySelectChange` finds " +
    "its button with select.closest( '.task-actions' ), so outside it the button never enables" );
  assert.equal( select.getAttribute( "data-original" ), "P0",
    "the classic select carries the painted priority; without it 'differs from original' " +
    "has nothing to compare against" );
} );

test( "🔴 THE MULTIPLEXER paints the SAME class with NO Update button and NO .task-actions", () => {
  const row    = multiplexerRow();
  const select = row.querySelector( SELECTOR ) as HTMLElement;

  // ⚠️ COMPARED AS A BOOLEAN, NOT AS A NODE. `assert.equal( element, null )` passes
  // fine and, on FAILURE, hands node:assert a happy-dom element to render into the
  // diff — it walks the circular parent chain and the whole file dies with SIGKILL,
  // reporting `0 passed` instead of a named failure. Measured here on 2026-09-03: the
  // first cut of this arm killed its own run and looked like a broken harness rather
  // than the caught mutation it actually was. An assertion whose FAILURE path is
  // lethal is a test that cannot tell you the one thing it exists to say.
  assert.equal( row.querySelector( ".task-priority-update" ) !== null, false,
    "the multiplexer has grown a .task-priority-update button. That is a real change and " +
    "may be right — but it means a guard can no longer tell the two renderers apart by " +
    "the button, and this file's premise needs revisiting rather than this line deleting" );
  assert.equal( select.closest( ".task-actions" ) !== null, false,
    "the multiplexer select is now inside .task-actions — the two cells have converged on " +
    "one wrapper and a `closest( '.task-actions' )` lookup can now cross renderers" );
  assert.ok( select.closest( ".task-col-actions" ),
    "the multiplexer select must sit in td.task-col-actions — its own delegated change " +
    "handler is written against that wrapper" );
  assert.equal( select.getAttribute( "data-original" ), null,   // a string|null, safe to diff
    "the multiplexer select carries no data-original, because it has nothing to compare " +
    "against: it commits the moment the value moves" );
} );

test( "THE DISCRIMINATOR, stated as one assertion a wrong-renderer guard would fail", () => {
  // A guard that merely finds SELECTOR is satisfied by either renderer. This is the pair
  // of facts that separates them, asserted together so the difference is the subject
  // rather than an incidental detail of two unrelated tests.
  const classicHasButton     = classicCell().querySelector( ".task-priority-update" )     !== null;
  const multiplexerHasButton = multiplexerRow().querySelector( ".task-priority-update" ) !== null;

  assert.notEqual( classicHasButton, multiplexerHasButton,
    "both renderers now agree about the Update button. Either they were unified — in " +
    "which case delete this file and say so in the commit — or one of them changed by " +
    "accident, and a guard aimed at the wrong one will now pass silently either way" );
  assert.equal( classicHasButton, true, "and it is the CLASSIC page that owns the button" );
} );
