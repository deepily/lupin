// Parity A-2 #2h (row 2ebf322f) — the document-level Y / N / C / P / Esc shortcuts.
//
// Legacy: `attachKeyboardListener` (notifications.js:25892). Two listeners, because
// Escape does not raise `keypress` in many browsers:
//   - keypress: P toggles pause for ANY response type (:25905); then, on the OLDEST
//     card only (:25912) and only when it is yes_no (:25917), C toggles the comment
//     row (:25920) and Y / N answer (:25926-25930)
//   - keydown: Escape cancels the active card (:25936)
//   - both suppressed while the operator types, tested on activeElement.tagName
//     against INPUT / TEXTAREA (:25902, :25937)
//
// Guard: `attachKeyboardListener` measured 0 across the whole multiplexer at HEAD
// bf9b78c0 and 0 on Maya 🌻's branch, while legacy carried 3 — so every case below
// reads a behaviour that did not exist in either tree.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_keyboard.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredRenderer,
  type ActionRequiredRenderer,
  type ActionRequiredStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

interface Harness {
  renderer : ActionRequiredRenderer;
  root     : HTMLElement;
  sent     : Array<{ idHash: string; response: ActionRequiredResponse }>;
  paused   : string[];
  items    : ActionRequiredItem[];
}

function item( over: Partial<ActionRequiredItem> = {} ): ActionRequiredItem {
  return {
    id_hash: "ar1", prompt: "Proceed?", response_type: "yes_no", questions: [],
    expires_at: Date.now() + 30_000, timeout_seconds: 30, state: "pending", ...over,
  };
}

let live: Harness | null = null;

function mount( items: ActionRequiredItem[] ): Harness {
  const sent   : Array<{ idHash: string; response: ActionRequiredResponse }> = [];
  const paused : string[] = [];
  const store: ActionRequiredStoreLike = {
    list            : () => items,
    getById         : ( id ) => items.find( ( i ) => i.id_hash === id ),
    respondAndAwait : async ( idHash, response ) => { sent.push( { idHash, response } ); },
    togglePause     : ( id ) => { paused.push( id ); return true; },
    recordStep      : () => {},
  };
  const renderer = createActionRequiredRenderer( {
    eventBus : createEventBusForTesting(),
    stores   : { actionRequired: store },
  } );
  const root = document.createElement( "div" );
  root.id = "action-required-pane";
  document.body.appendChild( root );
  renderer.mount( root );
  const h: Harness = { renderer, root, sent, paused, items };
  live = h;
  return h;
}

beforeEach( () => { live = null; } );

afterEach( () => {
  // The listeners are on `document`, so a renderer left mounted would answer the
  // NEXT test's keystrokes. Tearing down here is what keeps each case independent.
  if ( live !== null ) {
    live.renderer.unmount();
    live.root.remove();
    live = null;
  }
} );

function press( key: string ): void {
  document.dispatchEvent( new KeyboardEvent( "keypress", { key, bubbles: true, cancelable: true } ) );
}

function keydown( key: string ): void {
  document.dispatchEvent( new KeyboardEvent( "keydown", { key, bubbles: true, cancelable: true } ) );
}

// --- Y and N ------------------------------------------------------------------

test( "Y answers yes on the oldest card", () => {
  const h = mount( [ item() ] );
  press( "y" );
  assert.equal( h.sent.length, 1 );
  assert.equal( h.sent[ 0 ]!.idHash, "ar1" );
  assert.equal( h.sent[ 0 ]!.response, "yes" );
} );

test( "N answers no", () => {
  const h = mount( [ item() ] );
  press( "n" );
  assert.deepEqual( h.sent, [ { idHash: "ar1", response: "no" } ] );
} );

test( "the shortcut is case-insensitive, as legacy's toLowerCase makes it", () => {
  const h = mount( [ item() ] );
  press( "Y" );
  assert.equal( h.sent.length, 1 );
} );

test( "Y answers the OLDEST card, not the last one added", () => {
  const h = mount( [ item( { id_hash: "old" } ), item( { id_hash: "new" } ) ] );
  press( "y" );
  assert.equal( h.sent[ 0 ]!.idHash, "old" );
} );

test( "a typed comment rides with a keyboard Y — the key drives the card's own button", () => {
  // The guard against re-implementing the answer in the key handler: a handler that
  // built its own response would drop this comment, which is the defect b51dc7ea
  // fixed for the click path.
  const h = mount( [ item() ] );
  const input = h.root.querySelector<HTMLInputElement>( ".yes-no-comment-input" )!;
  input.value = "with reservations";
  input.dispatchEvent( new Event( "input", { bubbles: true } ) );
  input.blur();
  press( "y" );
  assert.equal( h.sent.length, 1, "the answer was sent" );
  assert.match( JSON.stringify( h.sent[ 0 ]!.response ), /with reservations/,
    "the comment rode along — if this fails the key path built its own response" );
} );

// --- P ------------------------------------------------------------------------

test( "P toggles pause", () => {
  const h = mount( [ item() ] );
  press( "p" );
  assert.deepEqual( h.paused, [ "ar1" ] );
} );

test( "P works for a non-yes_no card, which Y and N do not", () => {
  const h = mount( [ item( { response_type: "open_ended" } ) ] );
  press( "p" );
  assert.deepEqual( h.paused, [ "ar1" ], "P runs before legacy's yes_no narrowing" );
  press( "y" );
  assert.equal( h.sent.length, 0, "Y is inert on an open_ended card" );
} );

// --- C ------------------------------------------------------------------------

test( "C opens the comment row and focuses its input", () => {
  const h = mount( [ item() ] );
  const container = h.root.querySelector<HTMLElement>( ".yes-no-comment-container" )!;
  assert.equal( container.classList.contains( "expanded" ), false, "starts closed" );
  press( "c" );
  assert.ok( container.classList.contains( "expanded" ), "C opened it" );
} );

test( "C toggles — a second press closes the row again", () => {
  const h = mount( [ item() ] );
  const container = h.root.querySelector<HTMLElement>( ".yes-no-comment-container" )!;
  press( "c" );
  assert.ok( container.classList.contains( "expanded" ) );
  // The focus C gives the input would suppress the next keystroke, so drop focus
  // the way an operator clicking away does.
  ( document.activeElement as HTMLElement | null )?.blur();
  press( "c" );
  assert.equal( container.classList.contains( "expanded" ), false );
} );

// --- Escape -------------------------------------------------------------------

test( "Escape cancels the active card through the ✕'s own path", () => {
  const h = mount( [ item( { default: "no" } ) ] );
  keydown( "Escape" );
  assert.equal( h.sent.length, 1 );
  assert.equal( h.sent[ 0 ]!.idHash, "ar1" );
} );

test( "Escape is a keydown, not a keypress — legacy splits them for exactly this", () => {
  const h = mount( [ item() ] );
  press( "Escape" );
  assert.equal( h.sent.length, 0, "keypress must not cancel" );
  keydown( "Escape" );
  assert.equal( h.sent.length, 1, "keydown must" );
} );

// --- suppression while typing --------------------------------------------------

test( "every shortcut is inert while the operator types in an input", () => {
  const h = mount( [ item() ] );
  const input = h.root.querySelector<HTMLInputElement>( ".yes-no-comment-input" )!;
  input.focus();
  assert.equal( document.activeElement, input, "the input really holds focus — without this the rest asserts nothing" );
  press( "y" );
  press( "n" );
  press( "p" );
  press( "c" );
  keydown( "Escape" );
  assert.deepEqual( h.sent, [], "no answer was sent while typing" );
  assert.deepEqual( h.paused, [], "no pause was toggled while typing" );
} );

test( "a TEXTAREA suppresses them too, not only an INPUT", () => {
  const h = mount( [ item() ] );
  const ta = document.createElement( "textarea" );
  document.body.appendChild( ta );
  ta.focus();
  press( "y" );
  assert.deepEqual( h.sent, [] );
  ta.remove();
} );

// --- no cards, and teardown ----------------------------------------------------

test( "with no cards every shortcut is inert", () => {
  const h = mount( [] );
  press( "y" );
  press( "p" );
  keydown( "Escape" );
  assert.deepEqual( h.sent, [] );
  assert.deepEqual( h.paused, [] );
} );

test( "unmount detaches the listeners — a key after teardown answers nothing", () => {
  const h = mount( [ item() ] );
  h.renderer.unmount();
  h.root.remove();
  live = null;                       // already torn down; afterEach must not repeat it
  press( "y" );
  keydown( "Escape" );
  assert.deepEqual( h.sent, [], "a detached renderer must not answer for a card that is gone" );
} );
