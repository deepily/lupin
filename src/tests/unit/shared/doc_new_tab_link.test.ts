// The ↗ open-in-a-new-tab link beside a file in the doc viewer's folder listing.
//
// Run: npx tsx --test src/tests/unit/shared/doc_new_tab_link.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import * as link from "../../../lupin_app/static/js/shared/doc-new-tab-link.js";
import { normalizeDocLinkHref } from "../../../lupin_app/static/js/multiplexer/render/docLink";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const FILE = { kind: "file", name: "plan.md", view_url: "/app/docs?path=lupin%2Fsrc%2Fplan.md" };

test( "a viewable file gets the same href the pane's bust-out button opens", () => {
  assert.equal( link.newTabHrefFor( FILE ), normalizeDocLinkHref( FILE.view_url ) );
  assert.equal( link.newTabHrefFor( FILE ), "/app/docs?path=lupin%2Fsrc%2Fplan.md" );
} );

test( "an absolute loopback view_url is normalized exactly as the pane normalizes it", () => {
  const e = { ...FILE, view_url: "http://localhost:7999/app/docs?path=lupin%2Fa.md" };
  assert.equal( link.newTabHrefFor( e ), "/app/docs?path=lupin%2Fa.md" );
} );

test( "io audio, pdf and image files are viewable and keep their own routes", () => {
  for ( const url of [ "/app/audio?path=a.mp3", "/api/io/file?path=a.pdf", "/api/io/file?path=a.png" ] ) {
    assert.equal( link.newTabHrefFor( { kind: "file", name: "x", view_url: url } ), url );
  }
} );

test( "no glyph for a directory, a download-only type, or a missing view_url", () => {
  assert.equal( link.newTabHrefFor( { kind: "directory", name: "d", view_url: "/app/docs?path=lupin%2Fd" } ), null );
  assert.equal( link.newTabHrefFor( { kind: "file", name: "a.pptx", view_url: "/api/io/file?path=a.pptx&download=true" } ), null );
  assert.equal( link.newTabHrefFor( { kind: "file", name: "a.md" } ), null );
  assert.equal( link.newTabHrefFor( { kind: "file", name: "a.md", view_url: "" } ), null );
  assert.equal( link.newTabLinkHtml( { kind: "directory", name: "d", view_url: "/app/docs?path=lupin%2Fd" } ), "" );
} );

test( "the anchor opens a tab, is labelled, and is marked for the interceptors", () => {
  const host = document.createElement( "div" );
  host.innerHTML = link.newTabLinkHtml( FILE );
  const a = host.querySelector( "a" ) as HTMLAnchorElement;
  assert.equal( a.getAttribute( "target" ), "_blank" );
  assert.equal( a.getAttribute( "rel" ), "noopener" );
  assert.equal( a.getAttribute( "title" ), "Open plan.md in a new tab" );
  assert.equal( a.getAttribute( "aria-label" ), "Open plan.md in a new tab" );
  assert.equal( a.getAttribute( "href" ), link.newTabHrefFor( FILE ) );
  assert.equal( a.textContent, "↗" );
  assert.equal( link.isNewTabAnchor( a ), true );
} );

test( "a file name with quotes and markup cannot break out of the attributes", () => {
  const host = document.createElement( "div" );
  host.innerHTML = link.newTabLinkHtml( { kind: "file", name: "a\"><b>.md", view_url: "/api/io/file?path=a&b=1" } );
  assert.equal( host.querySelectorAll( "a" ).length, 1 );
  assert.equal( host.querySelectorAll( "b" ).length, 0 );
  assert.equal( ( host.querySelector( "a" ) as Element ).getAttribute( "aria-label" ), "Open a\"><b>.md in a new tab" );
  assert.equal( ( host.querySelector( "a" ) as Element ).getAttribute( "href" ), "/api/io/file?path=a&b=1" );
} );

test( "isNewTabAnchor: unmarked anchors and null are not claimed", () => {
  const plain = document.createElement( "a" );
  assert.equal( link.isNewTabAnchor( plain ), false );
  assert.equal( link.isNewTabAnchor( null ), false );
} );

test( "notifications.js skips the same attribute the shared module stamps", () => {
  const src = readFileSync( "src/lupin_app/static/js/notifications.js", "utf8" );
  assert.ok( src.includes( `a.hasAttribute( "${link.NEW_TAB_ATTR}" )` ), "notifications.js must skip the NEW_TAB_ATTR marker" );
} );
