// The /app/tasks/view page, batch form: `?rows=a,b`. It only reads and lists.
//
// The page is read from disk and its own script is run under happy-dom with a fetch that answers from a
// table. Each row shows as one line, `<first 8> · <status> · <title>`. A row whose read answers an error,
// or whose read throws, shows `<first 8> · could not be read`, and the other rows still list.
// A bad list (empty, short id, repeated id) shows the error and reads nothing.
//
// Run: npx tsx --test src/tests/unit/lupin_app/task_view_page_batch.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const PAGE = resolve( HERE, "../../../lupin_app/static/html/task-view.html" );
const A    = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const B    = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";

let urls  : string[];
let answer: ( url: string ) => Promise<unknown>;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );
beforeEach( () => {
  urls   = [];
  answer = async ( url ) => ( { ok: true, status: 200, json: async () => ( url.includes( A ) ? { title: "Row A", status: "not_approved" } : { title: "Row B", status: "queued" } ) } );
} );

const settle = async (): Promise<void> => { for ( let i = 0; i < 12; i++ ) await new Promise( ( r ) => setTimeout( r, 0 ) ); };

async function loadPage( search: string ): Promise<void> {
  const html = readFileSync( PAGE, "utf8" );
  document.body.innerHTML = html.slice( html.indexOf( "<main" ), html.indexOf( "</main>" ) + 7 );
  ( globalThis as unknown as { happyDOM: { setURL( u: string ): void } } ).happyDOM.setURL( `http://localhost/app/tasks/view${ search }` );
  ( globalThis as unknown as { fetch: unknown } ).fetch = async ( url: string ): Promise<unknown> => { urls.push( url ); return answer( url ); };
  vm.runInThisContext( html.slice( html.indexOf( "<script>" ) + 8, html.indexOf( "</script>" ) ) );
  await settle();
}

const lines = (): Array<string | null> => Array.from( document.querySelectorAll( "#task-view-batch li" ) ).map( ( li ) => li.textContent );

test( "a batch link lists each row's status and title in order, and reads only the listed rows", async () => {
  await loadPage( `?rows=${ A },${ B }` );
  assert.deepEqual( lines(), [ "a3975cf4 · not_approved · Row A", "0b1c2d3e · queued · Row B" ] );
  assert.deepEqual( urls, [ `/api/tasks/${ A }`, `/api/tasks/${ B }` ] );
  assert.equal( ( document.getElementById( "task-view-batch" ) as HTMLElement ).hidden, false );
  assert.equal( ( document.getElementById( "task-view-row" ) as HTMLElement ).hidden, true );
} );

test( "a row whose read answers an error shows as unreadable and the other row still lists", async () => {
  answer = async ( url ) => ( url.includes( A ) ? { ok: false, status: 404, json: async () => ( {} ) } : { ok: true, status: 200, json: async () => ( { title: "Row B", status: "queued" } ) } );
  await loadPage( `?rows=${ A },${ B }` );
  assert.deepEqual( lines(), [ "a3975cf4 · could not be read", "0b1c2d3e · queued · Row B" ] );
} );

test( "a row whose read throws shows as unreadable and the other row still lists", async () => {
  answer = async ( url ) => {
    if ( url.includes( A ) ) throw new Error( "network down" );
    return { ok: true, status: 200, json: async () => ( { title: "Row B", status: "queued" } ) };
  };
  await loadPage( `?rows=${ A },${ B }` );
  assert.deepEqual( lines(), [ "a3975cf4 · could not be read", "0b1c2d3e · queued · Row B" ] );
  assert.equal( ( document.getElementById( "task-view-batch" ) as HTMLElement ).hidden, false );
} );

for ( const [ name, search ] of [
  [ "a repeated id", `?rows=${ A },${ A }` ],
  [ "a short id", `?rows=a3975cf4` ],
  [ "an empty list", `?rows=` ],
] as const ) {
  test( `${ name } shows the error and reads nothing`, async () => {
    await loadPage( search );
    assert.match( document.getElementById( "task-view-error" )?.textContent ?? "", /clean list/ );
    assert.equal( ( document.getElementById( "task-view-batch" ) as HTMLElement ).hidden, true );
    assert.deepEqual( urls, [] );
  } );
}
