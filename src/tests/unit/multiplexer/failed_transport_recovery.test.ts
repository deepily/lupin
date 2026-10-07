// Bug row 5a8bd0c6: a multiplexer transport in `failed` never restarts, and nothing routes
// close codes 4001/4002/4003.
//
// Each test is written to FAIL while the defect is real. They assert the recovery the state
// machine's own header promises ("failed requires an explicit restart") and the routing the
// connection_state_change payload comment names (4001 token-refresh, 4002 session-displaced,
// 4003 permission-denied). No fix is chosen here; these tests only say the door is shut.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createQueueTransport } from "../../../lupin_app/static/js/multiplexer/transport/QueueTransport";
import type { AuthManager } from "../../../lupin_app/static/js/multiplexer/auth/AuthManager";

// Same pinned draw as queue_transport.test.ts: it keeps the backoff delay long.
const realRandom = Math.random;
before( () => { Math.random = () => 0.9; } );
after(  () => { Math.random = realRandom; } );

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url        : string;
  readyState : number = 0;
  onopen     : ( ( e: Event ) => void ) | null = null;
  onmessage  : ( ( e: MessageEvent ) => void ) | null = null;
  onclose    : ( ( e: CloseEvent ) => void ) | null = null;
  onerror    : ( ( e: Event ) => void ) | null = null;
  sent       : string[] = [];
  constructor( url: string ) { this.url = url; MockWebSocket.instances.push( this ); }
  send( data: string ): void { this.sent.push( data ); }
  close(): void { this.readyState = 3; }
  fireOpen(): void { this.readyState = 1; if ( this.onopen ) this.onopen( new Event( "open" ) ); }
  fireClose( code: number, reason: string ): void {
    this.readyState = 3;
    if ( this.onclose ) this.onclose( { type: "close", code, reason } as unknown as CloseEvent );
  }
  receive( data: string ): void { if ( this.onmessage ) this.onmessage( new MessageEvent( "message", { data } ) ); }
}

function makeAuth(): AuthManager {
  return {
    state      : "ready",
    invalidate : () => { /* no-op */ },
    getToken   : async () => ( { accessToken: "t", refreshToken: "r", expiresAt: Date.now() + 3_600_000 } ),
  };
}

const MULTIPLEXER_DIR = fileURLToPath( new URL( "../../../lupin_app/static/js/multiplexer", import.meta.url ) );

/** Every non-test .ts source under multiplexer/, as { path relative to multiplexer/, text }. */
function productionSources(): { rel: string; text: string }[] {
  const out: { rel: string; text: string }[] = [];
  const walk = ( dir: string ): void => {
    for ( const name of readdirSync( dir ) ) {
      const full = join( dir, name );
      if ( statSync( full ).isDirectory() ) { walk( full ); continue; }
      if ( name.endsWith( ".ts" ) && !name.endsWith( ".test.ts" ) && !name.endsWith( ".d.ts" ) ) {
        out.push( { rel: full.slice( MULTIPLEXER_DIR.length + 1 ), text: readFileSync( full, "utf8" ) } );
      }
    }
  };
  walk( MULTIPLEXER_DIR );
  return out;
}

async function transportInFailed(): Promise<{ transport: ReturnType<typeof createQueueTransport>; csm: { send( e: unknown ): void } }> {
  MockWebSocket.instances = [];
  const transport = createQueueTransport( {
    authManager   : makeAuth(),
    bus           : createEventBusForTesting(),
    baseUrl       : "",
    WebSocketCtor : MockWebSocket as unknown as typeof WebSocket,
  } );
  transport.start( "wise_penguin" );
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise( ( r ) => setTimeout( r, 10 ) );
  MockWebSocket.instances[0]!.receive( JSON.stringify( { type: "auth_success", data: {} } ) );
  MockWebSocket.instances[0]!.fireClose( 4001, "token expired" );
  assert.equal( transport.state, "failed", "precondition: a 4001 close ends in failed" );
  const csm = ( transport as unknown as { csm: { send( e: unknown ): void } } ).csm;
  assert.ok( csm, "precondition: the started transport holds its state machine" );
  return { transport, csm };
}

test( "the surface is non-empty: the source walk finds the files this file reasons about", () => {
  const rels = productionSources().map( ( s ) => s.rel );
  assert.ok( rels.includes( "transport/ConnectionStateMachine.ts" ), "walk must find the state machine" );
  assert.ok( rels.includes( "transport/QueueTransport.ts" ), "walk must find the queue transport" );
} );

test( "some production code sends the `restart` event", () => {
  const senders = productionSources()
    .filter( ( s ) => s.rel !== "transport/ConnectionStateMachine.ts" )
    .filter( ( s ) => /type\s*:\s*["']restart["']/.test( s.text ) )
    .map( ( s ) => s.rel );
  assert.ok( senders.length > 0, "no production file outside the state machine sends { type: \"restart\" }, so a transport in failed stays failed" );
} );

test( "some consumer outside the transport layer routes the permanent-failure close codes", () => {
  const routers = productionSources()
    .filter( ( s ) => !s.rel.startsWith( "transport/" ) && !s.rel.startsWith( "shared/" ) )
    .filter( ( s ) => /\b400[123]\b|auth-permanent/.test( s.text ) )
    .map( ( s ) => s.rel );
  assert.ok( routers.length > 0, "no consumer outside transport/ and shared/ reads 4001/4002/4003 or the auth-permanent reason" );
} );

test( "the restart event the machine accepts brings a failed transport back to a live socket", async () => {
  const { transport, csm } = await transportInFailed();
  const socketsBefore = MockWebSocket.instances.length;
  csm.send( { type: "restart" } );
  await new Promise( ( r ) => setTimeout( r, 10 ) );
  assert.notEqual( transport.state, "failed", "restart must leave failed" );
  assert.ok( MockWebSocket.instances.length > socketsBefore, "restart moves the machine to `connecting`, but no new socket is opened, so the transport waits on a connection nobody started" );
} );
