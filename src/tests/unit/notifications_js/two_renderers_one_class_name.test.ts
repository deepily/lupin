// 🔴 `.task-priority-select` NAMES TWO DIFFERENT CONTROLS — ONE BEHAVIOUR, TWO WIRINGS.
//
// ⚠️ REVISED 2026-09-16 (parity A-2 #0). Until then the two had OPPOSITE semantics: the
// multiplexer committed on change with no Update button. A-2 #0 ported the classic staged
// edit, so both now pair the select with a disabled Update and carry `data-original`. What
// still separates them is the WRAPPER, and each handler finds its button through its own:
// classic `select.closest( ".task-actions" )`, multiplexer the select's parent element.
// A guard that finds the class — or now the button — is still satisfied by either renderer.
//
// Measured 2026-09-03, while chasing a report that the priority Update button was dead.
// A search for the class name found matches in both the classic notifications page and
// the multiplexer bundle, and the two matches are not the same control:
//
//   CLASSIC  (notifications.js, `_priorityCell`)          multiplexer (taskRowControls.ts,
//     select + `.task-priority-update` button              `renderPriorityControl`)
//     inside `.task-actions`                                 select + Update, inside
//     button disabled until the value differs                `.task-col-actions`, NO
//     PATCHes on the CLICK                                   `.task-actions` (pre-A-2 #0:
//                                                            no button, PATCHed on change)
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
//   · either loses the Update button
//   · the two converge on one wrapper, so `closest( ".task-actions" )` crosses renderers
//
// Run: npx tsx --test src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderDisclosedRow } from "../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed";
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

/**
 * The MULTIPLEXER's actions cell, built by the real exported `renderDisclosedRow`.
 *
 * ⚠️ RE-POINTED 2026-09-05, from `renderTaskRow` in `taskListTable.ts`, which
 * `0fd99f96` deleted when it moved the controls out of the row. Re-pointed rather
 * than restored: `renderTaskRow` painted the controls INSIDE `.task-row`, which is
 * the shape that reshape removed, so re-adding it to satisfy this file would have
 * left the test guarding a renderer the product no longer reaches. Every fact this
 * file asserts is still true of the shipping renderer — that is what made
 * re-pointing available rather than a weakening.
 *
 * ⚠️ RETURNS A FRAGMENT OF THREE ROWS, not one `<tr>`: the visible row, the hidden
 * controls row that carries the nine controls, and the hidden error stripe. The
 * selectors below reach the controls row through the fragment, which is the whole
 * reason this reads the fragment rather than picking a row out of it.
 */
function multiplexerRow(): DocumentFragment {
  const task: TaskItem = {
    title: "row", item_class: "task", status: "queued", priority: "P0", project: "lupin",
  };
  return renderDisclosedRow( task, "task-list", "America/New_York" );
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

test( "🔴 THE MULTIPLEXER stages the edit the same way, OUTSIDE any .task-actions", () => {
  const row    = multiplexerRow();
  const select = row.querySelector( SELECTOR ) as HTMLElement;
  const button = row.querySelector( ".task-priority-update" ) as HTMLButtonElement | null;

  // ⚠️ COMPARED AS BOOLEANS, NOT AS NODES. `assert.equal( element, null )` hands
  // node:assert a happy-dom element to render into the diff on FAILURE — it walks the
  // circular parent chain and the whole file dies with SIGKILL, reporting `0 passed`
  // instead of a named failure (measured 2026-09-03).
  assert.equal( button !== null, true,
    "the multiplexer's Update button is gone — the staged edit parity A-2 #0 ported is broken" );
  assert.equal( ( button as HTMLButtonElement ).disabled, true,
    "the multiplexer button must start inert, as the classic one does" );
  assert.equal( select.getAttribute( "data-original" ), "P0",
    "the multiplexer select must carry the painted priority to compare against" );
  assert.equal( ( button as HTMLButtonElement ).parentElement === select.parentElement, true,
    "the Update button must share the select's parent — the multiplexer's handler finds it there" );
  assert.equal( select.closest( ".task-actions" ) !== null, false,
    "the multiplexer select is now inside .task-actions — the two cells have converged on " +
    "one wrapper and a `closest( '.task-actions' )` lookup can now cross renderers" );
  assert.ok( select.closest( ".task-col-actions" ),
    "the multiplexer select must sit in .task-col-actions — its delegated handlers are written against that wrapper" );
} );

test( "THE DISCRIMINATOR, stated as one assertion a wrong-renderer guard would fail", () => {
  // A guard that merely finds SELECTOR — or the Update button — is satisfied by either
  // renderer. The wrapper is the fact that still separates them.
  const classicWrapped     = ( classicCell().querySelector( SELECTOR ) as HTMLElement ).closest( ".task-actions" ) !== null;
  const multiplexerWrapped = ( multiplexerRow().querySelector( SELECTOR ) as HTMLElement ).closest( ".task-actions" ) !== null;

  assert.notEqual( classicWrapped, multiplexerWrapped,
    "both renderers now agree about the .task-actions wrapper. Either they were unified — in " +
    "which case delete this file and say so in the commit — or one of them changed by " +
    "accident, and a guard aimed at the wrong one will now pass silently either way" );
  assert.equal( classicWrapped, true, "and it is the CLASSIC page that owns the wrapper" );
} );
