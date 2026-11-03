// The /app/tasks/approve page, batch form: `?rows=a,b&move=queued|dropped[&reason=...]`.
//
// The page is read from disk and its own script is run under happy-dom with a fetch that answers from a
// table and records every request. Opening the page lists the rows and sends nothing but reads.
// The one button sends one transition per listed row with the move and, for a drop, the reason;
// the result names each row, and a refusal or a 202 on one row does not hide the others.
// A bad list (empty, short, repeated id, odd move, drop without a reason) shows the error and no button.
//
// Run: npx tsx --test src/tests/unit/lupin_app/task_approve_page_batch.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const PAGE = resolve( HERE, "../../../lupin_app/static/html/task-approve.html" );
const A    = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const B    = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";

type Req = { url: string; method: string; body: Record<string, unknown> | null };
let reqs  : Req[];
let status: Record<string, number>;
let rows  : Record<string, { title: string; status: string } | null>;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );
beforeEach( () => { reqs = []; status = {}; rows = { [ A ]: { title: "Row A", status: "not_approved" }, [ B ]: { title: "Row B", status: "not_approved" } }; } );

const settle = async (): Promise<void> => { for ( let i = 0; i < 12; i++ ) await new Promise( ( r ) => setTimeout( r, 0 ) ); };

/** Load the page at `search` and run its script against a recording fetch. */
async function loadPage( search: string ): Promise<void> {
  const html = readFileSync( PAGE, "utf8" );
  document.body.innerHTML = html.slice( html.indexOf( "<main" ), html.indexOf( "</main>" ) + 7 );
  ( globalThis as unknown as { happyDOM: { setURL( u: string ): void } } ).happyDOM.setURL( `http://localhost/app/tasks/approve${ search }` );
  ( globalThis as unknown as { fetch: unknown } ).fetch = async ( url: string, init: { method: string; body?: string } ): Promise<unknown> => {
    reqs.push( { url, method: init.method, body: init.body ? JSON.parse( init.body ) : null } );
    const id   = url.match( /[0-9a-f-]{36}/ )?.[ 0 ] as string;
    const code = init.method === "GET" ? ( rows[ id ] === null ? 404 : 200 ) : ( status[ id ] ?? 200 );
    return { ok: code >= 200 && code < 300, status: code, json: async () => ( init.method === "GET" ? rows[ id ] : { detail: "not yours to approve" } ) };
  };
  vm.runInThisContext( html.slice( html.indexOf( "<script>" ) + 8, html.indexOf( "</script>" ) ) );
  await settle();
}

const text = ( id: string ): string => document.getElementById( id )?.textContent ?? "";
const hidden = ( id: string ): boolean => ( document.getElementById( id ) as HTMLElement ).hidden;

test( "opening a batch link lists each row's status and title, names the move, and sends only reads", async () => {
  await loadPage( `?rows=${ A },${ B }&move=queued` );
  const items = Array.from( document.querySelectorAll( "#task-approve-batch-list li" ) ).map( ( li ) => li.textContent );
  assert.deepEqual( items, [ "a3975cf4 · not_approved · Row A", "0b1c2d3e · not_approved · Row B" ] );
  assert.equal( text( "task-approve-heading" ), "Approve 2 tickets" );
  assert.equal( text( "task-approve-batch-button" ), "Approve all 2" );
  assert.equal( hidden( "task-approve-batch" ), false );
  assert.deepEqual( reqs.map( ( r ) => r.method ), [ "GET", "GET" ] );
  assert.equal( hidden( "task-approve-row" ), true, "the single-row section stays hidden" );
} );

test( "an unreadable row is listed as such", async () => {
  rows[ B ] = null;
  await loadPage( `?rows=${ A },${ B }&move=queued` );
  const items = Array.from( document.querySelectorAll( "#task-approve-batch-list li" ) ).map( ( li ) => li.textContent );
  assert.equal( items[ 1 ], "0b1c2d3e · could not be read" );
} );

test( "one press sends one queued transition per row, user_direct, with no reason, and reports both", async () => {
  await loadPage( `?rows=${ A },${ B }&move=queued` );
  ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).click();
  await settle();
  const posts = reqs.filter( ( r ) => r.method === "POST" );
  assert.deepEqual( posts.map( ( r ) => r.url ), [ `/api/tasks/${ A }/transition`, `/api/tasks/${ B }/transition` ] );
  for ( const p of posts ) {
    assert.equal( p.body?.to_status, "queued" );
    assert.equal( p.body?.authority, "user_direct" );
    assert.equal( "reason" in ( p.body as object ), false );
  }
  assert.equal( text( "task-approve-batch-result" ), "2 of 2 applied\na3975cf4 applied ✅\n0b1c2d3e applied ✅" );
  assert.equal( ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).disabled, true );
} );

test( "a queued link that carries a reason sends no reason", async () => {
  await loadPage( `?rows=${ A }&move=queued&reason=x` );
  ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).click();
  await settle();
  const post = reqs.find( ( r ) => r.method === "POST" ) as Req;
  assert.equal( "reason" in ( post.body as object ), false );
} );

test( "a drop sends dropped and the reason with every row, and the page says Drop", async () => {
  await loadPage( `?rows=${ A },${ B }&move=dropped&reason=duplicate%20refile` );
  assert.equal( text( "task-approve-heading" ), "Drop 2 tickets" );
  assert.equal( text( "task-approve-batch-button" ), "Drop all 2" );
  ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).click();
  await settle();
  const posts = reqs.filter( ( r ) => r.method === "POST" );
  assert.equal( posts.length, 2 );
  for ( const p of posts ) { assert.equal( p.body?.to_status, "dropped" ); assert.equal( p.body?.reason, "duplicate refile" ); }
} );

test( "a refusal and a 202 are named per row and never counted as applied", async () => {
  status[ A ] = 403;
  status[ B ] = 202;
  await loadPage( `?rows=${ A },${ B }&move=queued` );
  ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).click();
  await settle();
  assert.equal(
    text( "task-approve-batch-result" ),
    "0 of 2 applied\na3975cf4 refused: not yours to approve\n0b1c2d3e refused: waiting on Rick — he has not been asked yet",
  );
} );

test( "one refused row leaves the other applied", async () => {
  status[ A ] = 403;
  await loadPage( `?rows=${ A },${ B }&move=queued` );
  ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).click();
  await settle();
  assert.equal( text( "task-approve-batch-result" ), "1 of 2 applied\na3975cf4 refused: not yours to approve\n0b1c2d3e applied ✅" );
} );

for ( const [ name, search ] of [
  [ "a repeated id", `?rows=${ A },${ A }&move=queued` ],
  [ "a short id", `?rows=a3975cf4&move=queued` ],
  [ "an empty list", `?rows=&move=queued` ],
  [ "an odd move", `?rows=${ A }&move=done` ],
  [ "no move", `?rows=${ A }` ],
  [ "a drop with no reason", `?rows=${ A }&move=dropped` ],
  [ "a drop with a blank reason", `?rows=${ A }&move=dropped&reason=%20%20` ],
] as const ) {
  test( `${ name } shows the error and no button, and sends nothing`, async () => {
    await loadPage( search );
    assert.match( text( "task-approve-error" ), /clean list/ );
    assert.equal( hidden( "task-approve-error" ), false );
    assert.equal( hidden( "task-approve-batch" ), true );
    assert.deepEqual( reqs, [] );
  } );
}

test( "the single-row form still works beside the batch code", async () => {
  await loadPage( `?row=${ A }` );
  assert.equal( text( "task-approve-title" ), "Row A" );
  assert.equal( hidden( "task-approve-row" ), false );
  assert.equal( hidden( "task-approve-batch" ), true );
} );

test( "a network error on one row is that row's line and the other row still reports", async () => {
  await loadPage( `?rows=${ A },${ B }&move=queued` );
  const real = ( globalThis as unknown as { fetch: ( u: string, i: unknown ) => Promise<unknown> } ).fetch;
  ( globalThis as unknown as { fetch: unknown } ).fetch = async ( url: string, init: unknown ): Promise<unknown> => {
    if ( url.includes( A ) ) throw new Error( "network down" );
    return real( url, init );
  };
  ( document.getElementById( "task-approve-batch-button" ) as HTMLButtonElement ).click();
  await settle();
  assert.equal( text( "task-approve-batch-result" ), "1 of 2 applied\na3975cf4 refused: unreachable: network down\n0b1c2d3e applied ✅" );
} );

test( "a row that cannot be read while listing shows as unreadable and the page still opens", async () => {
  const html = readFileSync( PAGE, "utf8" );
  document.body.innerHTML = html.slice( html.indexOf( "<main" ), html.indexOf( "</main>" ) + 7 );
  ( globalThis as unknown as { happyDOM: { setURL( u: string ): void } } ).happyDOM.setURL( `http://localhost/app/tasks/approve?rows=${ A },${ B }&move=queued` );
  ( globalThis as unknown as { fetch: unknown } ).fetch = async ( url: string ): Promise<unknown> => {
    if ( url.includes( A ) ) throw new Error( "network down" );
    return { ok: true, status: 200, json: async () => rows[ B ] };
  };
  vm.runInThisContext( html.slice( html.indexOf( "<script>" ) + 8, html.indexOf( "</script>" ) ) );
  await settle();
  const items = Array.from( document.querySelectorAll( "#task-approve-batch-list li" ) ).map( ( li ) => li.textContent );
  assert.deepEqual( items, [ "a3975cf4 · could not be read", "0b1c2d3e · not_approved · Row B" ] );
  assert.equal( hidden( "task-approve-batch" ), false );
} );
