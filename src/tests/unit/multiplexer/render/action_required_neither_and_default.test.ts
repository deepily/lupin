// Parity A-2 #2i (row 2ebf322f) — the yes_no card's ⊘ Neither and the default highlight.
//
// Legacy: renderActionRequiredNotification, the yes_no block (notifications.js:23236-23253).
//   - three buttons: "✓ Yes (Y)", "✗ No (N)", "⊘ Neither" titled "Neither — the question
//     itself needs re-framing"; each answers its data-response ("yes" / "no" / "neither")
//     through submitYesNoWithComment (:23366-23371)
//   - the server's response_default puts `.default-value` on Yes or No ("Phase 2.2",
//     :23237-23240); Neither is never marked
// Guard: each test below reads a behaviour legacy has and the multiplexer lacked at 59731c05.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_neither_and_default.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderActionRequiredInteractive } from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import type { ActionRequiredItem, ActionRequiredResponse } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function yesNo( over: Partial<ActionRequiredItem> = {} ): ActionRequiredItem {
  return {
    id_hash : "yn1", prompt: "Deploy now?", response_type: "yes_no", questions: [],
    expires_at: 1, timeout_seconds: 30, state: "pending", ...over,
  };
}

function render( item: ActionRequiredItem ) {
  const sent: ActionRequiredResponse[] = [];
  const el   = renderActionRequiredInteractive( item, { onSubmit: ( r ) => sent.push( r ) } );
  const btn  = ( answer: string ) => el.querySelector<HTMLButtonElement>( `button[data-value="${ answer }"]` )!;
  return { el, sent, btn };
}

test( "three buttons in legacy's order and labels: ✓ Yes (Y), ✗ No (N), ⊘ Neither", () => {
  const { el } = render( yesNo() );
  const labels = Array.from( el.querySelectorAll<HTMLButtonElement>( ".action-required-controls button" ), ( b ) => b.textContent!.replace( /\s+/g, " " ).trim() );
  assert.deepEqual( labels, [ "✓ Yes (Y)", "✗ No (N)", "⊘ Neither" ] );
} );

test( "Neither answers \"neither\" and carries legacy's re-framing title", () => {
  const { sent, btn } = render( yesNo() );
  assert.equal( btn( "neither" ).title, "Neither — the question itself needs re-framing" );
  btn( "neither" ).click();
  assert.deepEqual( sent, [ "neither" ] );
} );

test( "Yes and No still answer \"yes\" and \"no\"", () => {
  const { sent, btn } = render( yesNo() );
  btn( "yes" ).click();
  btn( "no" ).click();
  assert.deepEqual( sent, [ "yes", "no" ] );
} );

test( "a default of \"yes\" marks Yes only; a default of \"no\" marks No only", () => {
  for ( const def of [ "yes", "no" ] as const ) {
    const { el } = render( yesNo( { default: def } ) );
    const marked = Array.from( el.querySelectorAll<HTMLButtonElement>( ".default-value" ), ( b ) => b.dataset.value );
    assert.deepEqual( marked, [ def ] );
  }
} );

test( "no default, or a default Neither would match, marks nothing — legacy never marks Neither", () => {
  for ( const def of [ undefined, "neither", "maybe" ] ) {
    const { el } = render( yesNo( def === undefined ? {} : { default: def } ) );
    assert.equal( el.querySelectorAll( ".default-value" ).length, 0, `default ${ String( def ) }` );
  }
} );
