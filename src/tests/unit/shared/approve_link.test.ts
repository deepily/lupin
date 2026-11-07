// The shared approve-link module publishes itself on window.
//
// The classic-script notifications page reads it there, and the multiplexer imports the same file.
//
// Run: npx tsx --test src/tests/unit/shared/approve_link.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import * as shared from "../../../lupin_app/static/js/shared/approve-link.js";
import * as facade from "../../../lupin_app/static/js/multiplexer/render/approveLink";
import { normalizeDocLinkHref } from "../../../lupin_app/static/js/multiplexer/render/docLink";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

test( "importing the module puts every export except publishOnWindow on window.LUPIN_APPROVE_LINK", () => {
  const published = ( window as never as { LUPIN_APPROVE_LINK?: Record<string, unknown> } ).LUPIN_APPROVE_LINK;
  assert.ok( published, "window.LUPIN_APPROVE_LINK was not published" );
  const exported = Object.keys( shared ).filter( ( k ) => k !== "publishOnWindow" ).sort();
  // The constants are internal to the module's callers; every function is on the surface.
  const functions = exported.filter( ( k ) => typeof ( shared as Record<string, unknown> )[ k ] === "function" );
  assert.deepEqual( Object.keys( published ).sort(), functions );
  for ( const k of functions ) assert.equal( published[ k ], ( shared as Record<string, unknown> )[ k ], k );
} );

test( "publishOnWindow writes to whatever object it is handed", () => {
  const stand_in: Record<string, unknown> = {};
  shared.publishOnWindow( stand_in );
  assert.equal( typeof ( stand_in.LUPIN_APPROVE_LINK as Record<string, unknown> ).handleBatchApproveLinkClick, "function" );
} );

test( "the multiplexer's approveLink and docLink modules are the shared functions, not copies", () => {
  for ( const name of [ "approveRowId", "approvePriorityLink", "viewRowId", "parseBatchIds", "batchLinkOf", "batchViewIds", "markApproveLinks", "handleBatchViewLinkClick" ] ) {
    assert.equal( ( facade as Record<string, unknown> )[ name ], ( shared as Record<string, unknown> )[ name ], name );
  }
  assert.equal( normalizeDocLinkHref, shared.normalizeDocLinkHref );
} );

test( "normalizeDocLinkHref strips a loopback origin and reads null and empty as null", () => {
  assert.equal( shared.normalizeDocLinkHref( "http://localhost:7999/app/docs?path=a" ), "/app/docs?path=a" );
  assert.equal( shared.normalizeDocLinkHref( "https://127.0.0.1/x" ), "/x" );
  assert.equal( shared.normalizeDocLinkHref( "https://example.com/x" ), "https://example.com/x" );
  assert.equal( shared.normalizeDocLinkHref( "" ), null );
  assert.equal( shared.normalizeDocLinkHref( null ), null );
} );
