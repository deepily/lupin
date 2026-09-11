// A manager's request looks the same on both boards — row c9fafb9d, Mr. Radio's D4.
//
// 🔴 THE TWO CHIPS ARE BUILT BY TWO RENDERERS, and the shared module only decides their
// WORDS. The markup — which classes, which data attributes, in what order — is written
// twice, once as createElement calls (multiplexer) and once as an HTML string
// (notifications.js). This test builds both for the same rows and compares their structure
// element by element, so a class renamed in one client reddens here rather than silently
// breaking that client's click handler or stylesheet rule.
//
// Run: npx tsx --test src/tests/unit/shared/both_clients_render_one_request_chip.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Chip = ( task: Record<string, unknown>, nowMs: number ) => HTMLElement | null;
let renderRequestChip: Chip;

before( async () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  await import( "../../../lupin_app/static/js/shared/task-request.js" );
  ( { renderRequestChip } = await import( "../../../lupin_app/static/js/multiplexer/render/requestChips" ) as { renderRequestChip: Chip } );
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  vm.runInThisContext( src.slice( 0, src.indexOf( "// Initialize when DOM is ready" ) ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
                       { filename: NOTIFICATIONS_JS } );
} );

/** Every element in the chip, as tag + class + data-* + type + aria-label + text of a leaf. */
function shape( root: Element ): string[] {
  const out: string[] = [];
  for ( const el of [ root, ...Array.from( root.querySelectorAll( "*" ) ) ] ) {
    const data = Array.from( el.attributes ).filter( ( a ) => a.name.startsWith( "data-" ) )
      .map( ( a ) => `${ a.name }=${ a.value }` ).sort().join( "," );
    const leafText = el.children.length === 0 ? ( el.textContent ?? "" ) : "";
    out.push( [ el.tagName, el.className, data, el.getAttribute( "type" ) ?? "", el.getAttribute( "aria-label" ) ?? "", leafText ].join( "|" ) );
  }
  return out;
}

test( "for an admit, a demote and a timeless request, both clients build the same chip", () => {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const legacy = Object.create( Ctor.prototype ) as { _requestChipHtml( t: Record<string, unknown> ): string };
  const now = Date.now();
  const rows = [
    { id: "aaaaaaaa-1", request_state: "pending", request_move: "admit",  request_ts: new Date( now - 12 * 60e3 ).toISOString() },
    { id: "bbbbbbbb-2", request_state: "pending", request_move: "demote", request_ts: new Date( now - 2 * 86400e3 ).toISOString() },
    { id: "cccccccc-3", request_state: "pending", request_move: "admit",  request_ts: null },
  ];
  for ( const row of rows ) {
    const holder = document.createElement( "div" );
    holder.innerHTML = legacy._requestChipHtml( row );
    const fromLegacy = holder.firstElementChild;
    const fromMux    = renderRequestChip( row, now );
    assert.ok( fromLegacy && fromMux, `no chip for ${ row.request_move }` );
    assert.deepEqual( shape( fromLegacy ), shape( fromMux ), `the two clients drew different ${ row.request_move } chips` );
  }
} );
