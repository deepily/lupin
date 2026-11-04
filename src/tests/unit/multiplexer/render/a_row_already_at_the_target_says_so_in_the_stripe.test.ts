// Row 71a11ed7 — the controller half: a transition whose `done` says the row was ALREADY at the target
// shows "<Verb>: this row is already <status> — this click changed nothing." in the pressed row's stripe,
// and a plain success shows nothing. Never "refused", never a silent success.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TaskRowController } from "../../../../lupin_app/static/js/multiplexer/render/taskRowController";
import { renderDisclosedRow } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const TASK = { id: "row-1", title: "t", status: "in_progress", priority: "P2", owner_persona: "maya" } as unknown as TaskItem;

async function press( outcome: { alreadyAt?: string } | undefined ): Promise<HTMLElement> {
  const container = document.createElement( "div" );
  const table = document.createElement( "table" );
  table.appendChild( renderDisclosedRow( TASK, "task-list", undefined ) );
  container.replaceChildren( table );
  const rows = new TaskRowController( {
    container, logLabel: "[test]",
    writer: {
      patchTask      : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
      transitionTask : () => ( { restoreState: () => {}, done: Promise.resolve( outcome ) } ),
    },
  } );
  const select = container.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  select.value = "drop";
  rows.handleChange( select );
  ( container.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "why";
  rows.handleClick( container.querySelector( ".task-submit-button" ) );
  await new Promise<void>( ( r ) => setTimeout( r, 0 ) );
  return container.querySelector( ".task-row-error-stripe" ) as HTMLElement;
}

test( "a transition that found the row already there says so, in the stripe, without 'refused'", async () => {
  const stripe = await press( { alreadyAt: "dropped" } );
  assert.equal( stripe.hidden, false, "the operator was told nothing" );
  assert.equal( stripe.textContent, "Drop: this row is already dropped — this click changed nothing." );
} );

test( "a plain success shows no stripe", async () => {
  assert.equal( ( await press( undefined ) ).hidden, true );
} );
