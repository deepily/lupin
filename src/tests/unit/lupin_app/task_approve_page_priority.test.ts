// The /app/tasks/approve page, priority form: `?row=<id>&priority=P0` (row 526bfd86).
//
// The page's own script runs under happy-dom with a recording fetch. The one button sends the approve move plus
// `promote_priority` when the link names a level in P0..P5, and nothing extra otherwise. A link whose ampersand
// arrived escaped as "&amp;" still carries its level.
//
// Run: npx tsx --test src/tests/unit/lupin_app/task_approve_page_priority.test.ts

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

async function pressApprove( search: string ): Promise<Req | undefined> {
  await loadPage( search );
  ( document.getElementById( "task-approve-button" ) as HTMLButtonElement ).click();
  await settle();
  return reqs.find( ( r ) => r.method === "POST" );
}

test( "a priority link sends the approve move plus promote_priority, and the button names the level", async () => {
  const post = await pressApprove( `?row=${ A }&priority=P0` );
  assert.equal( text( "task-approve-button" ), "Approve at P0" );
  assert.deepEqual( post?.body, { to_status: "queued", actor: "operator approve-landing-page", authority: "user_direct", promote_priority: "P0" } );
  assert.equal( text( "task-approve-result" ), "approved at P0 ✅" );
} );

test( "the link's own level is sent, not a fixed P0", async () => {
  const post = await pressApprove( `?row=${ A }&priority=P3` );
  assert.equal( post?.body?.promote_priority, "P3" );
} );

test( "a plain link and a level outside P0..P5 send no promote_priority", async () => {
  for ( const search of [ `?row=${ A }`, `?row=${ A }&priority=P9`, `?row=${ A }&priority=p0` ] ) {
    reqs = [];
    const post = await pressApprove( search );
    assert.equal( post?.body !== null && post !== undefined && "promote_priority" in post.body!, false, search );
  }
} );

// An href whose ampersand arrives as the literal text "&amp;" parses as a parameter named "amp;priority".
// Dropping it would admit the row at its old priority although the link asked for a raise.
test( "a link whose ampersand arrives escaped as &amp; still carries its level", async () => {
  const post = await pressApprove( `?row=${ A }&amp;priority=P0` );
  assert.equal( post?.body?.promote_priority, "P0" );
} );
