// The shared draft-at-reveal rules: what a client hands buildDraft, and what comes back.
//
// Run: npx tsx --test src/tests/unit/shared/draft_at_reveal.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import * as shared from "../../../lupin_app/static/js/shared/draft-at-reveal.js";
import * as mux from "../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredDraft";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const NONE = { text: "", batch: [], saved: {}, shown: null } as const;

test( "importing the module puts its three names on window.LUPIN_DRAFT_AT_REVEAL, and publishOnWindow writes to what it is handed", () => {
  const published = ( window as never as { LUPIN_DRAFT_AT_REVEAL?: Record<string, unknown> } ).LUPIN_DRAFT_AT_REVEAL!;
  assert.deepEqual( Object.keys( published ).sort(), [ "DRAFT_MAX_CHARS", "buildDraft", "routeLength" ] );
  assert.equal( published.buildDraft, shared.buildDraft );
  const stand_in: Record<string, unknown> = {};
  shared.publishOnWindow( stand_in );
  assert.equal( stand_in.LUPIN_DRAFT_AT_REVEAL !== undefined, true );
} );

test( "the multiplexer module hands back the very same limit and counter", () => {
  assert.equal( mux.DRAFT_MAX_CHARS, shared.DRAFT_MAX_CHARS );
  assert.equal( mux.routeLength, shared.routeLength );
} );

test( "an open-ended card gives its trimmed text, and nothing for a blank box", () => {
  assert.deepEqual( shared.buildDraft( "open_ended", { ...NONE, text: "  hello  " } ), { value: "hello" } );
  assert.equal( shared.buildDraft( "open_ended", { ...NONE, text: "   " } ), null );
} );

test( "a batch card gives its non-empty trimmed fields as JSON, and nothing when every field is blank", () => {
  const parts = { ...NONE, batch: [ [ "A", " one " ], [ "B", "  " ], [ "C", "three" ] ] as const };
  assert.deepEqual( shared.buildDraft( "open_ended_batch", parts ), { value: JSON.stringify( { answers: { A: "one", C: "three" } } ) } );
  assert.equal( shared.buildDraft( "open_ended_batch", { ...NONE, batch: [ [ "A", "" ] ] } ), null );
} );

test( "a multiple-choice card gives the saved answers plus the question on screen, with the screen winning on one header", () => {
  const saved = { Env: "staging", Tags: [ "a" ] };
  assert.deepEqual( shared.buildDraft( "multiple_choice", { ...NONE, saved, shown: { header: "Env", value: "prod" } } ),
                    { value: JSON.stringify( { answers: { Env: "prod", Tags: [ "a" ] } } ) } );
  assert.deepEqual( shared.buildDraft( "multiple_choice", { ...NONE, saved } ), { value: JSON.stringify( { answers: saved } ) } );
  assert.deepEqual( shared.buildDraft( "multiple_choice", { ...NONE, shown: { header: "H", value: [ "x", "y" ] } } ),
                    { value: JSON.stringify( { answers: { H: [ "x", "y" ] } } ) } );
  assert.equal( shared.buildDraft( "multiple_choice", { ...NONE, shown: undefined } ), null );
} );

test( "a yes/no card, an unknown type and a missing type give no draft", () => {
  for ( const type of [ "yes_no", "something_else", undefined ] ) assert.equal( shared.buildDraft( type, { ...NONE, text: "typed" } ), null );
} );

test( "a draft over the limit as the route counts it is dropped, and one at the limit is kept", () => {
  assert.equal( shared.routeLength( { value: "x".repeat( 4083 ) } ), 4096 );
  assert.deepEqual( shared.buildDraft( "open_ended", { ...NONE, text: "x".repeat( 4083 ) } ), { value: "x".repeat( 4083 ) } );
  assert.equal( shared.buildDraft( "open_ended", { ...NONE, text: "x".repeat( 4084 ) } ), null );
} );

test( "a character beyond Basic Latin counts six, an emoji twelve, and the tilde stays one", () => {
  assert.equal( shared.routeLength( { value: "é".repeat( 500 ) } ), 3013 );
  assert.equal( shared.routeLength( { value: "\u{1F600}".repeat( 500 ) } ), 6013 );
  assert.equal( shared.routeLength( { value: "~" } ), 14 );
} );
