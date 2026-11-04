// Row e45c7c7b: a relative link in a rendered markdown file opens the file it names.
//
// WHATS-NEW.md links `src/rnd/v0.2.2/...-rewrite-plan.md`, right for GitHub. The viewer left it alone, the
// browser resolved it against /app/ and landed on /app/src/rnd/..., a 404. These cases drive the real resolver
// and the real page binder over a real DOM (happy-dom) and assert the href the reader would follow.
//
// Run: npx tsx --test src/tests/unit/multiplexer/docPodcast/doc_relative_links.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { resolveRelativeDocHref, rewriteRelativeDocLinks } from "../../../../lupin_app/static/js/multiplexer/render/docLink";
import { bindDocRelativeLinks, TARGET_ID } from "../../../../lupin_app/static/js/multiplexer/docPodcast/docLinks";
import { FILE_EVENT } from "../../../../lupin_app/static/js/multiplexer/docPodcast/docPodcast";

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

const WHATS_NEW = "src/rnd/v0.2.2/2026.09.30-lupin-af-documentation-rewrite-plan/2026.09.30-lupin-af-documentation-rewrite-plan.md";

test( "the exact WHATS-NEW.md link resolves to the plan, in its scope", () => {
  assert.equal(
    resolveRelativeDocHref( WHATS_NEW, "lupin/WHATS-NEW.md" ),
    `/app/docs?path=lupin/${WHATS_NEW}`,
  );
});

test( "a link resolves against the document's own directory, not the scope root", () => {
  assert.equal( resolveRelativeDocHref( "b.md", "lupin/src/docs/a.md" ), "/app/docs?path=lupin/src/docs/b.md" );
  assert.equal( resolveRelativeDocHref( "./b.md", "lupin/src/docs/a.md" ), "/app/docs?path=lupin/src/docs/b.md" );
  assert.equal( resolveRelativeDocHref( "../x/b.md", "lupin/src/docs/a.md" ), "/app/docs?path=lupin/src/x/b.md" );
  assert.equal( resolveRelativeDocHref( "a//b.md", "lupin/a.md" ), "/app/docs?path=lupin/a/b.md" );
});

test( "a fragment survives, a query is dropped, escapes are decoded then re-encoded", () => {
  assert.equal( resolveRelativeDocHref( "b.md#sec", "lupin/a.md" ), "/app/docs?path=lupin/b.md#sec" );
  assert.equal( resolveRelativeDocHref( "b.md?raw=1", "lupin/a.md" ), "/app/docs?path=lupin/b.md" );
  assert.equal( resolveRelativeDocHref( "my%20doc.md", "lupin/a.md" ), "/app/docs?path=lupin/my%20doc.md" );
  assert.equal( resolveRelativeDocHref( "x.md?q#f", "lupin/a.md" ), "/app/docs?path=lupin/x.md#f" );
});

test( "a bare directory link opens the directory in its scope", () => {
  assert.equal( resolveRelativeDocHref( "docs/", "lupin/a.md" ), "/app/docs?path=lupin/docs" );
  assert.equal( resolveRelativeDocHref( ".", "lupin/a.md" ), "/app/docs?path=lupin" );
});

test( "anchors, absolute URLs, root paths and existing viewer links are left alone", () => {
  for ( const href of [ null, "", "#top", "https://example.com/x.md", "mailto:a@b.c", "//cdn.example.com/x", "/app/docs?path=lupin/x.md", "/static/x.png" ] ) {
    assert.equal( resolveRelativeDocHref( href, "lupin/WHATS-NEW.md" ), null, String( href ) );
  }
});

test( "a ../ that would leave the scope does not resolve", () => {
  assert.equal( resolveRelativeDocHref( "../secret.md", "lupin/a.md" ), null );
  assert.equal( resolveRelativeDocHref( "../../etc/passwd", "lupin/src/a.md" ), null );
  assert.equal( resolveRelativeDocHref( "x/../../y.md", "lupin/a.md" ), null );
  // climbing to the scope root is still inside it
  assert.equal( resolveRelativeDocHref( "../y.md", "lupin/src/a.md" ), "/app/docs?path=lupin/y.md" );
});

test( "a malformed escape and an empty document path both leave the link alone", () => {
  assert.equal( resolveRelativeDocHref( "%E0%A4%A.md", "lupin/a.md" ), null );
  assert.equal( resolveRelativeDocHref( "b.md", "" ), null );
  assert.equal( resolveRelativeDocHref( "b.md", "a.md" ), null );
});

test( "rewriteRelativeDocLinks changes only the links that resolve, and counts them", () => {
  const root = document.createElement( "div" );
  root.innerHTML = `<a id="r" href="b.md">r</a><a id="h" href="#x">h</a><a id="e" href="https://e.com/">e</a><a id="n">n</a>`;
  assert.equal( rewriteRelativeDocLinks( root, "lupin/a.md" ), 1 );
  assert.equal( root.querySelector( "#r" )!.getAttribute( "href" ), "/app/docs?path=lupin/b.md" );
  assert.equal( root.querySelector( "#h" )!.getAttribute( "href" ), "#x" );
  assert.equal( root.querySelector( "#e" )!.getAttribute( "href" ), "https://e.com/" );
});

function page(): HTMLElement {
  document.body.innerHTML = `<div id="${TARGET_ID}"></div>`;
  return document.getElementById( TARGET_ID )!;
}
const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

beforeEach( () => { document.body.innerHTML = ""; } );

test( "when the page announces a file, links rendered AFTER that are rewritten", async () => {
  const target = page();
  bindDocRelativeLinks( {}, document );
  document.dispatchEvent( new CustomEvent( FILE_EVENT, { detail: { path: "lupin/WHATS-NEW.md" } } ) );
  target.innerHTML = `<a id="p" href="${WHATS_NEW}">plan</a>`;
  await tick();
  assert.equal( target.querySelector( "#p" )!.getAttribute( "href" ), `/app/docs?path=lupin/${WHATS_NEW}` );
});

test( "when the module loaded after the page rendered, the global path rewrites what is already there", () => {
  const target = page();
  target.innerHTML = `<a id="p" href="b.md">b</a>`;
  bindDocRelativeLinks( { __docViewerFilePath: "lupin/src/a.md" }, document );
  assert.equal( target.querySelector( "#p" )!.getAttribute( "href" ), "/app/docs?path=lupin/src/b.md" );
});

test( "with no announced file and no global, nothing is touched", async () => {
  const target = page();
  bindDocRelativeLinks( {}, document );
  target.innerHTML = `<a id="p" href="b.md">b</a>`;
  await tick();
  assert.equal( target.querySelector( "#p" )!.getAttribute( "href" ), "b.md" );
});
