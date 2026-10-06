// Row 8796333b slice 2 — a `task_store_changed` frame delivered by the REAL QueueTransport onto
// the REAL EventBus makes all three task panes read. Every store test elsewhere calls bus.emit
// directly, so none of them notices the transport dropping the event name.
//
// Run: npx tsx --test --test-force-exit src/tests/unit/multiplexer/task_store_changed_through_queue_transport.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createQueueTransport } from "../../../lupin_app/static/js/multiplexer/transport/QueueTransport";
import { createTaskListStore } from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import { createHoldingAreaStore } from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import { createFinishedTasksStore } from "../../../lupin_app/static/js/multiplexer/stores/FinishedTasksStore";
import type { AuthManager } from "../../../lupin_app/static/js/multiplexer/auth/AuthManager";

class MockWebSocket {
  static readonly CONNECTING = 0; static readonly OPEN = 1; static readonly CLOSING = 2; static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];
  readyState = 0;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  sent: string[] = [];
  constructor( public url: string ) { MockWebSocket.instances.push( this ); }
  send( d: string ): void { this.sent.push( d ); }
  close(): void { this.readyState = 3; }
  receive( data: string ): void { this.onmessage?.( new MessageEvent( "message", { data } ) ); }
  /**
   * Deliver a frame the way the SERVER does: only if the type is in the `subscribed_events`
   * the client announced in its auth_request. The transport does no filtering of its own, so
   * the announced list IS its forwarding; a socket that delivered everything would make
   * removing the name from that list invisible.
   */
  deliverIfSubscribed( frame: { type: string } ): void {
    const authRequest = JSON.parse( this.sent[ 0 ]! ) as { subscribed_events: string[] };
    if ( authRequest.subscribed_events.includes( frame.type ) ) this.receive( JSON.stringify( frame ) );
  }
}

const auth = {
  state: "ready", invalidate: () => {},
  getToken: async () => ( { accessToken: "t", refreshToken: "r", expiresAt: Date.now() + 3_600_000 } ),
} as unknown as AuthManager;

const wait = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 10 ) );

async function rig() {
  MockWebSocket.instances = [];
  const bus = createEventBusForTesting();
  const transport = createQueueTransport( {
    authManager: auth, bus, baseUrl: "", WebSocketCtor: MockWebSocket as unknown as typeof WebSocket,
  } );
  const counts = { tasks: 0, holding: 0, finished: 0 };
  const noTimer = { setIntervalFn: () => 1, clearIntervalFn: () => {} };
  const tasks    = createTaskListStore( { bus, api: { get: async <T,>() => { counts.tasks++; return { status: "ok", tasks: [] } as T; }, patch: async <T,>() => null as T, post: async <T,>() => null as T }, ...noTimer } );
  const holding  = createHoldingAreaStore( { bus, api: { get: async <T,>() => { counts.holding++; return { tasks: [] } as T; }, post: async <T,>() => null as T, patch: async <T,>() => null as T }, ...noTimer } );
  const finished = createFinishedTasksStore( { bus, api: { get: async <T,>() => { counts.finished++; return { events: [], count: 0 } as T; } }, ...noTimer } );
  tasks.startPolling(); holding.startPolling(); finished.startPolling();
  await wait();
  const base = { ...counts };
  transport.start( "wise penguin" );
  const ws = MockWebSocket.instances[0]!;
  ws.readyState = 1;
  ws.onopen?.( new Event( "open" ) );
  await wait();
  ws.receive( JSON.stringify( { type: "auth_success", data: {} } ) );
  await wait();
  return { ws, counts, base, stop: () => { tasks.stopPolling(); holding.stopPolling(); finished.stopPolling(); transport.stop(); } };
}

test( "a task_store_changed frame off the socket makes Task List, Holding Area and Finished Tasks each read", async () => {
  const { ws, counts, base, stop } = await rig();
  ws.deliverIfSubscribed( { type: "task_store_changed", event_id: 1, item_id: "i", transition: "amended", to_status: null, ts: "t", count: 1 } as { type: string } );
  await wait();
  assert.equal( counts.tasks - base.tasks, 1, "Task List read" );
  assert.equal( counts.holding - base.holding, 1, "Holding Area read" );
  assert.equal( counts.finished - base.finished, 3, "Finished Tasks read all three statuses" );
  stop();
} );

test( "frames of other names make none of them read — the first test's reads are the push's doing", async () => {
  const { ws, counts, base, stop } = await rig();
  ws.deliverIfSubscribed( { type: "some_other_event" } );
  ws.receive( JSON.stringify( { type: "sys_ping" } ) );
  await wait();
  assert.deepEqual( counts, base );
  stop();
} );
