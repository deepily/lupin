// A missing shared/approve-link.js leaves approve links as plain links.
//
// Every handler declines the click, nothing throws, and one console error names the module.
//
// Run: npx tsx --test src/tests/unit/notifications_js/a_missing_approve_link_module_degrades_to_plain_links.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Handlers = Record<string, ( ev: unknown ) => unknown>;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
} );

test( "with no window.LUPIN_APPROVE_LINK every handler declines, nothing throws, and the error is reported once", () => {
  const w = window as never as { LUPIN_APPROVE_LINK?: unknown };
  assert.equal( w.LUPIN_APPROVE_LINK, undefined, "this file must run without the shared module" );
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as Handlers & { _observeApproveLinks( root: Element ): void; _approveLinkStop?: unknown };
  const errors: unknown[][] = [];
  const saved = console.error;
  console.error = ( ...a: unknown[] ): void => { errors.push( a ); };
  try {
    const ev = { target: document.body };
    for ( const name of [ "_handleApproveLinkClick", "_handleApprovePriorityLinkClick", "_handleViewLinkClick", "_handleBatchApproveLinkClick", "_handleBatchViewLinkClick" ] ) {
      assert.equal( ui[ name ]!( ev ), false, name );
    }
    ui._observeApproveLinks( document.body );
    assert.equal( ui._approveLinkStop, undefined );
  } finally { console.error = saved; }
  assert.equal( errors.length, 1, "one console error, not one per click" );
  assert.match( String( errors[ 0 ]![ 0 ] ), /shared\/approve-link\.js did not load/ );
} );
