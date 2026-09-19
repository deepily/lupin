// TaskRowController.groupScope — the fallbacks behind "act on the copy that was pressed".
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// The Epic Board paints a row waiting on Rick twice, so the controller confines every
// by-id lookup to the pressed control's own group <tbody> (the two-copy cases live in
// epic_board_renderer.test.ts, "SHOWN TWICE"). These pin what happens when that group
// is not there to confine to:
//   1. no <tbody> at all              -> the pane, as before
//   2. a repaint detached a KEYLESS   -> the pane (the Holding Area's tbody has no key,
//      group                             and it paints each task once)
//   3. a repaint left no group with   -> the pane, never the detached node, which would
//      the old key                       swallow the refusal

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TaskRowController } from "../../../../lupin_app/static/js/multiplexer/render/taskRowController";
import { renderDisclosedRow } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const ID = "row-1";
const TASK = { id: ID, title: "t", status: "in_progress", priority: "P2", owner_persona: "maya" } as unknown as TaskItem;

/** A table holding the row, optionally inside a <tbody> carrying `key`. */
function paint( container: HTMLElement, group: "none" | "keyless" | Record<string, string> ): void {
  const table = document.createElement( "table" );
  const rows  = renderDisclosedRow( TASK, "task-list", undefined );
  if ( group === "none" ) {
    table.appendChild( rows );
  } else {
    const tbody = document.createElement( "tbody" );
    if ( group !== "keyless" ) Object.assign( tbody.dataset, group );
    tbody.appendChild( rows );
    table.appendChild( tbody );
  }
  container.replaceChildren( table );
}

/** A controller whose one write rejects on a later microtask, after the test has repainted. */
function controllerOver( container: HTMLElement ) {
  return new TaskRowController( {
    container, logLabel: "[test]",
    writer: {
      patchTask      : () => ( { restoreState: () => {}, done: Promise.reject( new Error( "refused" ) ) } ),
      transitionTask : () => ( { restoreState: () => {}, done: Promise.reject( new Error( "refused" ) ) } ),
    },
  } );
}

function stripe( container: HTMLElement ): HTMLElement {
  return container.querySelector( ".task-row-error-stripe" ) as HTMLElement;
}

async function refuseAcrossRepaint( before: "keyless" | Record<string, string>, after: "keyless" | Record<string, string> ) {
  const container = document.createElement( "div" );
  paint( container, before );
  const rows = controllerOver( container );
  const select = container.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  select.value = "drop";
  rows.handleChange( select );
  ( container.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "why";
  const submit = container.querySelector( ".task-submit-button" ) as HTMLElement;
  rows.handleClick( submit );
  paint( container, after );   // lands before the rejection settles
  assert.ok( !container.contains( submit ), "the repaint did not detach the pressed control" );
  await new Promise<void>( ( r ) => setTimeout( r, 0 ) );
  return container;
}

test( "no <tbody>: the ⋯ still opens its row, scoped to the pane", () => {
  const container = document.createElement( "div" );
  paint( container, "none" );
  assert.equal( container.querySelectorAll( "tbody" ).length, 0, "the fixture grew a tbody — the no-group arm is unexercised" );
  const rows = controllerOver( container );
  rows.handleClick( container.querySelector( ".task-disclose-button" ) );
  assert.equal( ( container.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, false );
} );

test( "a KEYLESS group detached by a repaint: the refusal lands in the pane's fresh stripe", async () => {
  const container = await refuseAcrossRepaint( "keyless", "keyless" );
  assert.equal( stripe( container ).hidden, false, "the refusal was painted into the detached group" );
  assert.match( stripe( container ).textContent ?? "", /refused/ );
} );

test( "a KEYED group detached and not repainted: the refusal falls back to the pane", async () => {
  const container = await refuseAcrossRepaint( { epic: "epic:alpha" }, { epic: "epic:beta" } );
  assert.equal( stripe( container ).hidden, false, "the refusal was painted into the detached group" );
  assert.match( stripe( container ).textContent ?? "", /refused/ );
} );

test( "a KEYED group detached and repainted: the refusal lands in the fresh group with that key", async () => {
  const container = await refuseAcrossRepaint( { epic: "epic:alpha" }, { epic: "epic:alpha" } );
  assert.match( stripe( container ).textContent ?? "", /refused/ );
} );
