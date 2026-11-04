// Row 5a8bd0c6, Rick's ruling 2026-10-07: the Retry-now button in the System Status pane restarts a
// transport that gave up. The real renderer and the real QueueTransport, joined by the real bus; only the
// WebSocket constructor is a fake. A click on the button must end in a fresh socket on the same URL.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/retry_now_restarts_a_failed_transport.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createQueueTransport } from "../../../../lupin_app/static/js/multiplexer/transport/QueueTransport";
import { createAudioTransport } from "../../../../lupin_app/static/js/multiplexer/transport/AudioTransport";
import { createSystemStatusRenderer, HEALTH_CIRCUIT } from "../../../../lupin_app/static/js/multiplexer/render/SystemStatusRenderer";
import type { AuthManager } from "../../../../lupin_app/static/js/multiplexer/auth/AuthManager";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url        : string;
  readyState : number = 0;
  onopen     : ( ( e: Event ) => void ) | null = null;
  onmessage  : ( ( e: MessageEvent ) => void ) | null = null;
  onclose    : ( ( e: CloseEvent ) => void ) | null = null;
  onerror    : ( ( e: Event ) => void ) | null = null;
  constructor( url: string ) { this.url = url; MockWebSocket.instances.push( this ); }
  send( _data: string ): void { /* nothing listens */ }
  close(): void { this.readyState = 3; }
  fireOpen(): void { this.readyState = 1; if ( this.onopen ) this.onopen( new Event( "open" ) ); }
  fireClose( code: number, reason: string ): void {
    this.readyState = 3;
    if ( this.onclose ) this.onclose( { type: "close", code, reason } as unknown as CloseEvent );
  }
  receive( data: string ): void { if ( this.onmessage ) this.onmessage( new MessageEvent( "message", { data } ) ); }
}

const auth = {
  state: "ready", invalidate: () => {}, getToken: async () => ( { accessToken: "t", refreshToken: "r", expiresAt: Date.now() + 3_600_000 } ),
} as unknown as AuthManager;

test( "clicking Retry-now on a failed queue transport opens a fresh socket and hides the button", async () => {
  MockWebSocket.instances = [];
  const bus       = createEventBusForTesting();
  const transport = createQueueTransport( { authManager: auth, bus, baseUrl: "", WebSocketCtor: MockWebSocket as unknown as typeof WebSocket } );
  const root      = document.createElement( "div" );
  const renderer  = createSystemStatusRenderer( {
    eventBus     : bus,
    auth         : { getToken: async () => ( {} as never ), getCurrentUserEmail: () => null, isCurrentUserAdmin: () => false },
    transports   : { queue: transport },
    sessionIds   : { queue: "wise_penguin", audio: null },
    reinitConfig : async () => ( {} ),
    logFn        : () => {},
    setIntervalFn: () => 1,
  } );
  renderer.mount( root );
  try {
    transport.start( "wise_penguin" );
    MockWebSocket.instances[ 0 ]!.fireOpen();
    await new Promise( ( r ) => setTimeout( r, 10 ) );
    MockWebSocket.instances[ 0 ]!.receive( JSON.stringify( { type: "auth_success", data: {} } ) );
    MockWebSocket.instances[ 0 ]!.fireClose( 4001, "token expired" );
    assert.equal( transport.state, "failed", "precondition: a 4001 close ends in failed" );

    const btn    = root.querySelector( '[data-testid="multiplexer-ws-retry-now-btn"]' ) as HTMLButtonElement;
    const health = root.querySelector( '[data-testid="multiplexer-ws-health-status"]' ) as HTMLElement;
    assert.equal( health.textContent, HEALTH_CIRCUIT );
    assert.equal( btn.hidden, false, "the button is offered with the circuit line" );

    const before = MockWebSocket.instances.length;
    btn.click();
    assert.equal( MockWebSocket.instances.length, before + 1, "the click opened exactly one fresh socket" );
    assert.equal( MockWebSocket.instances[ before ]!.url, MockWebSocket.instances[ 0 ]!.url, "on the same session URL" );
    assert.equal( btn.hidden, true, "the transport left failed, so the button goes away" );
  } finally {
    renderer.unmount();
    transport.stop();
  }
} );

test( "an audio-only failure shows Retry-now, and a click restarts the audio transport and leaves the queue alone", async () => {
  MockWebSocket.instances = [];
  const bus       = createEventBusForTesting();
  const ctor      = MockWebSocket as unknown as typeof WebSocket;
  const queue     = createQueueTransport( { authManager: auth, bus, baseUrl: "", WebSocketCtor: ctor } );
  const audio     = createAudioTransport( { authManager: auth, bus, baseUrl: "", WebSocketCtor: ctor } );
  const root      = document.createElement( "div" );
  const renderer  = createSystemStatusRenderer( {
    eventBus     : bus,
    auth         : { getToken: async () => ( {} as never ), getCurrentUserEmail: () => null, isCurrentUserAdmin: () => false },
    transports   : { queue, audio },
    sessionIds   : { queue: "wise_penguin", audio: "wise_penguin" },
    reinitConfig : async () => ( {} ),
    logFn        : () => {},
    setIntervalFn: () => 1,
  } );
  renderer.mount( root );
  const socketsFor = ( path: string ) => MockWebSocket.instances.filter( ( w ) => w.url.includes( path ) );
  try {
    queue.start( "wise_penguin" );
    audio.start( "wise_penguin" );
    for ( const ws of MockWebSocket.instances ) ws.fireOpen();
    await new Promise( ( r ) => setTimeout( r, 10 ) );
    for ( const ws of MockWebSocket.instances ) ws.receive( JSON.stringify( { type: "auth_success", data: {} } ) );
    const audioSocket = socketsFor( "/ws/audio" )[ 0 ]!;
    audioSocket.fireClose( 4001, "token expired" );
    assert.equal( audio.state, "failed", "precondition: a 4001 close fails the audio transport" );
    assert.notEqual( queue.state, "failed", "precondition: the queue transport did not fail" );

    const btn = root.querySelector( '[data-testid="multiplexer-ws-retry-now-btn"]' ) as HTMLButtonElement;
    assert.equal( btn.hidden, false, "an audio failure alone offers the button" );

    const queueBefore = socketsFor( "/ws/queue" ).length;
    const audioBefore = socketsFor( "/ws/audio" ).length;
    btn.click();
    assert.equal( socketsFor( "/ws/audio" ).length, audioBefore + 1, "the click opened one fresh audio socket" );
    assert.equal( socketsFor( "/ws/queue" ).length, queueBefore, "and left the queue transport alone" );
    assert.notEqual( audio.state, "failed", "the audio transport left failed" );
    assert.equal( btn.hidden, true, "the button goes away once nothing is failed" );
  } finally {
    renderer.unmount();
    queue.stop();
    audio.stop();
  }
} );
