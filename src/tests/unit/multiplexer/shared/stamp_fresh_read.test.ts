// stampFreshRead — the "updated" stamp the three boards share (row 9cc37a94 item 37).
//
// Run: npx tsx --test src/tests/unit/multiplexer/shared/stamp_fresh_read.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { READ_BACK_FAILED_CLASS, stampFreshRead, stampReadBackFailed } from "../../../../lupin_app/static/js/multiplexer/shared/afterWriteRead";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

test( "a fresh read writes the text and ends a read-back failure", () => {
  const el = document.createElement( "span" );
  stampReadBackFailed( el );
  assert.ok( el.classList.contains( READ_BACK_FAILED_CLASS ) );
  stampFreshRead( el, "updated 10:42" );
  assert.equal( el.textContent, "updated 10:42" );
  assert.ok( !el.classList.contains( READ_BACK_FAILED_CLASS ) );
} );

test( "a null stamp is a no-op", () => {
  assert.doesNotThrow( () => stampFreshRead( null, "updated 10:42" ) );
} );
