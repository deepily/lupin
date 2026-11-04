// The /app/tasks/view page shows a ticket's title and body as text, never as markup.
//
// The page is read from disk and its own script is run under happy-dom, with a fetch that answers
// from a table. A body carrying an <img onerror> tag must come out as visible characters and
// must not create an element. The same check runs on the title.
//
// Run: npx tsx --test src/tests/unit/lupin_app/task_view_page_escapes_the_body.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const PAGE = resolve( HERE, "../../../lupin_app/static/html/task-view.html" );
const ROW  = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const EVIL = '<img src=x onerror="window.__pwned=1">';

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

/** Load the page for one row and run its script against a fetch that answers with `row`. */
async function loadPage( row: Record<string, unknown> ): Promise<void> {
  const html = readFileSync( PAGE, "utf8" );
  document.body.innerHTML = html.slice( html.indexOf( "<main" ), html.indexOf( "</main>" ) + 7 );
  ( globalThis as unknown as { happyDOM: { setURL( u: string ): void } } ).happyDOM.setURL( `http://localhost/app/tasks/view?row=${ ROW }` );
  ( globalThis as unknown as { fetch: unknown } ).fetch = async (): Promise<unknown> => ( { ok: true, status: 200, json: async () => row } );
  const script = html.slice( html.indexOf( "<script>" ) + 8, html.indexOf( "</script>" ) );
  vm.runInThisContext( script );
  for ( let i = 0; i < 10; i++ ) await new Promise( ( r ) => setTimeout( r, 0 ) );
}

test( "a body carrying an img tag is shown as text and creates no element", async () => {
  await loadPage( { title: "T", priority: "P2", owner_persona: "krishna", status: "queued", body: `before ${ EVIL } after` } );
  const body = document.getElementById( "task-view-body" ) as Element;
  assert.equal( body.textContent, `before ${ EVIL } after`, "the tag is visible as characters" );
  assert.ok( document.querySelector( "#task-view-row img" ) === null, "no img element exists" );
  assert.equal( ( globalThis as unknown as { __pwned?: number } ).__pwned, undefined );
} );

test( "a title and an owner carrying an img tag are shown as text too", async () => {
  await loadPage( { title: EVIL, priority: "P2", owner_persona: EVIL, status: "queued", body: "b" } );
  assert.equal( document.getElementById( "task-view-title" )?.textContent, EVIL );
  assert.equal( document.getElementById( "task-view-owner" )?.textContent, EVIL );
  assert.ok( document.querySelector( "#task-view-row img" ) === null );
} );
