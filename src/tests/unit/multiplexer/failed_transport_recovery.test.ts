// Bug row 5a8bd0c6: a multiplexer transport in `failed` never restarts, and nothing routes
// close codes 4001/4002/4003.
//
// Each test is written to FAIL while the defect is real. They assert the recovery the state
// machine's own header promises ("failed requires an explicit restart") and the routing the
// connection_state_change payload comment names (4001 token-refresh, 4002 session-displaced,
// 4003 permission-denied). No fix is chosen here; these tests only say the door is shut.

import { test, before, after, mock } from "node:test";
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

test( "a consumer outside the transport layer asks a failed transport to restart", () => {
  const callers = productionSources()
    .filter( ( s ) => !s.rel.startsWith( "transport/" ) )
    .filter( ( s ) => /\.restart\(\s*\)/.test( s.text ) )
    .map( ( s ) => s.rel );
  assert.deepEqual( callers, [ "render/SystemStatusRenderer.ts" ], "the Retry-now button in the System Status pane is the one caller" );
} );

test( "Transport.restart() leaves failed and opens one fresh socket; in any other state it does nothing", async () => {
  const { transport } = await transportInFailed();
  const before = MockWebSocket.instances.length;
  try {
    transport.restart();
    assert.notEqual( transport.state, "failed" );
    assert.equal( MockWebSocket.instances.length, before + 1, "exactly one fresh socket" );
    transport.restart();   // now connecting: a second click must not open another
    assert.equal( MockWebSocket.instances.length, before + 1, "a restart outside failed is a no-op" );
  } finally {
    transport.stop();
  }
} );

test( "Transport.restart() before start() is a no-op", () => {
  const transport = createQueueTransport( {
    authManager : makeAuth(), bus : createEventBusForTesting(), baseUrl : "",
    WebSocketCtor : MockWebSocket as unknown as typeof WebSocket,
  } );
  transport.restart();
  assert.equal( transport.state, "connecting" );
} );

test( "some consumer outside the transport layer routes the permanent-failure close codes", { todo: "row 5a8bd0c6: still open by design, Rick has not ruled on 4001/4002/4003 routing" }, () => {
  const routers = productionSources()
    .filter( ( s ) => !s.rel.startsWith( "transport/" ) && !s.rel.startsWith( "shared/" ) )
    .filter( ( s ) => /\b400[123]\b|auth-permanent/.test( s.text ) )
    .map( ( s ) => s.rel );
  assert.ok( routers.length > 0, "no consumer outside transport/ and shared/ reads 4001/4002/4003 or the auth-permanent reason" );
} );

test( "the restart event the machine accepts brings a failed transport back to a live socket", async () => {
  const { transport, csm } = await transportInFailed();
  const socketsBefore = MockWebSocket.instances.length;
  try {
    csm.send( { type: "restart" } );
    await new Promise( ( r ) => setTimeout( r, 10 ) );
    assert.notEqual( transport.state, "failed", "restart must leave failed" );
    assert.ok( MockWebSocket.instances.length > socketsBefore, "restart moves the machine to `connecting`, but no new socket is opened, so the transport waits on a connection nobody started" );
    assert.equal( MockWebSocket.instances.length, socketsBefore + 1, "exactly one fresh socket" );
    assert.equal( MockWebSocket.instances[ socketsBefore ]!.url, MockWebSocket.instances[ 0 ]!.url, "the fresh socket goes to the same session URL" );
  } finally {
    transport.stop();   // the fresh socket armed a handshake watchdog; a running transport keeps the test process alive
  }
} );

test( "behaviour: 20 failed reconnects end in failed, and nothing the page can produce reopens it", async () => {
  MockWebSocket.instances = [];
  const bus       = createEventBusForTesting();
  const states: string[] = [];
  bus.on<{ state: string }>( "connection_state_change", ( e ) => states.push( e.payload.state ) );
  const transport = createQueueTransport( {
    authManager   : makeAuth(), bus, baseUrl : "",
    WebSocketCtor : MockWebSocket as unknown as typeof WebSocket,
  } );
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    transport.start( "wise_penguin" );
    // Every socket dies at once with an ordinary code (1006), never reaching auth_success.
    for ( let i = 0; i < 60 && transport.state !== "failed"; i++ ) {
      MockWebSocket.instances[ MockWebSocket.instances.length - 1 ]!.fireClose( 1006, "" );
      mock.timers.tick( 31_000 );
    }
    assert.equal( transport.state, "failed", "precondition: repeated ordinary closes end in failed" );
    const socketsAtFailure = MockWebSocket.instances.length;
    assert.equal( socketsAtFailure, 20, "measured: the 20th failed attempt trips the limit, so 20 sockets were opened" );

    // Everything a page can offer: tab hidden and shown, network lost and regained, and ten minutes of clock.
    for ( const type of [ "page_hidden", "page_visible", "network_offline", "network_online", "page_visible" ] ) {
      bus.emit( { type, payload: {}, source: "test", ts: Date.now() } as never );
    }
    mock.timers.tick( 600_000 );

    assert.equal( transport.state, "failed", "nothing reopened the transport" );
    assert.equal( MockWebSocket.instances.length, socketsAtFailure, "no new socket was opened" );
    assert.equal( states[ states.length - 1 ], "failed", "no state change followed failed" );
  } finally {
    mock.timers.reset();
  }
} );

test( "a restart after the retry budget ran out gets a fresh budget: one ordinary close lands in backoff, not failed", () => {
  MockWebSocket.instances = [];
  const transport = createQueueTransport( {
    authManager   : makeAuth(), bus : createEventBusForTesting(), baseUrl : "",
    WebSocketCtor : MockWebSocket as unknown as typeof WebSocket,
  } );
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    transport.start( "wise_penguin" );
    for ( let i = 0; i < 60 && transport.state !== "failed"; i++ ) {
      MockWebSocket.instances[ MockWebSocket.instances.length - 1 ]!.fireClose( 1006, "" );
      mock.timers.tick( 31_000 );
    }
    assert.equal( transport.state, "failed", "precondition: the budget ran out" );
    ( transport as unknown as { csm: { send( e: unknown ): void } } ).csm.send( { type: "restart" } );
    MockWebSocket.instances[ MockWebSocket.instances.length - 1 ]!.fireClose( 1006, "" );
    assert.equal( transport.state, "backoff", "one failed attempt after a restart must back off, not return to failed" );
  } finally {
    transport.stop();
    mock.timers.reset();
  }
} );

test( "after a restart the state changes no longer carry the old failure's reason and code", async () => {
  MockWebSocket.instances = [];
  const bus    = createEventBusForTesting();
  const events: { state: string; reason?: string; code?: number }[] = [];
  bus.on<{ state: string; reason?: string; code?: number }>( "connection_state_change", ( e ) => events.push( e.payload ) );
  const transport = createQueueTransport( {
    authManager   : makeAuth(), bus, baseUrl : "",
    WebSocketCtor : MockWebSocket as unknown as typeof WebSocket,
  } );
  try {
    transport.start( "wise_penguin" );
    MockWebSocket.instances[0]!.fireOpen();
    await new Promise( ( r ) => setTimeout( r, 10 ) );
    MockWebSocket.instances[0]!.receive( JSON.stringify( { type: "auth_success", data: {} } ) );
    MockWebSocket.instances[0]!.fireClose( 4001, "token expired" );
    const failed = events.find( ( e ) => e.state === "failed" );
    assert.equal( failed?.code, 4001, "precondition: the failed event carries the 4001" );

    ( transport as unknown as { csm: { send( e: unknown ): void } } ).csm.send( { type: "restart" } );
    MockWebSocket.instances[ MockWebSocket.instances.length - 1 ]!.fireClose( 1006, "" );   // an ordinary close after the restart
    const afterFailed = events.slice( events.indexOf( failed! ) + 1 );
    assert.ok( afterFailed.length >= 2, "precondition: the restart and the ordinary close each changed state" );
    for ( const e of afterFailed ) {
      assert.equal( e.reason, undefined, `the ${ e.state } event after the restart must not carry the old reason` );
      assert.equal( e.code,   undefined, `the ${ e.state } event after the restart must not carry the old code` );
    }
  } finally {
    transport.stop();
  }
} );
