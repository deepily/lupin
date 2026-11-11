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

test( "handleApprovePriorityLinkClick is handleApproveLinkClick answering the priority link: each link has one handler, and the move differs only by the level", async () => {
  const ROW   = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
  const calls: Array<{ id: string; status: string; extras: unknown }> = [];
  const sender = { transitionTask: async ( id: string, status: string, extras: unknown ) => { calls.push( { id, status, extras } ); return { ok: true as const }; } };
  const plant  = ( href: string ): Element => {
    document.body.innerHTML = `<a href="${ href }">go</a>`;
    return document.querySelector( "a" ) as Element;
  };
  const ev = (): Event => new Event( "click", { cancelable: true } );

  const plain = plant( `/app/tasks/approve?row=${ ROW }` );
  assert.equal( shared.handleApprovePriorityLinkClick( ev(), plain, sender as never ), false, "a plain link is not a priority click" );
  assert.equal( calls.length, 0 );
  const e1 = ev();
  assert.equal( shared.handleApproveLinkClick( e1, plain, sender as never ), true );
  assert.equal( e1.defaultPrevented, true );
  await Promise.resolve();
  assert.deepEqual( calls, [ { id: ROW, status: "queued", extras: {} } ] );

  calls.length = 0;
  const prio = plant( `/app/tasks/approve?row=${ ROW }&priority=P0` );
  assert.equal( shared.handleApproveLinkClick( ev(), prio, sender as never ), false, "a priority link is not a plain click" );
  assert.equal( calls.length, 0 );
  assert.equal( shared.handleApprovePriorityLinkClick( ev(), prio, sender as never ), true );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( calls, [ { id: ROW, status: "queued", extras: { promote_priority: "P0" } } ] );
  assert.equal( document.body.textContent, "approved at P0 ✅" );
} );
