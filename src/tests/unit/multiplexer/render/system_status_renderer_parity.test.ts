// Parity B-5 / B-5L — System Status, and the Config reload button.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1). All in src/lupin_app/static/js/notifications.js
// unless noted:
//   - `refreshAllStatus`        :1460  ↻ disables, runs four readouts IN ORDER, re-enables in a finally
//   - `refreshWebSocketStatus`  :1504  the two socket pills, and the six-state map at :1512
//   - `refreshAuthStatus`       :1537  "Not authenticated" / "Token expired" / "Authenticated (admin)"
//   - `refreshSessionDisplay`   :1576  both ids, or `-`
//   - `copyToClipboard`         :1585  📋 — and its NO-OP on empty or `-`
//   - `checkWebSocketHealth`    :1125  the health line's four texts
//   - `reinitializeConfig`      :1399  the Config row: dim, clear, ✓ or ✗, re-enable in a finally
//   - the markup                 notifications.html:1309-1373
//
// 🔴 THE CONFIG BUTTON IS NOT ADMIN-GATED, AND THAT REVERSES AN EARLIER RULING.
// The build plan's §3 R8 says admin-only in both clients and an earlier attempt
// (eadcf5ba) built it that way. Rick ruled on 2026-09-23 that the gate is a
// DIVERGENCE: `admin` matches zero lines in notifications.js:1399-1458. The later
// ruling governs, and the test below asserts the ABSENCE of a gate so that
// re-adding one from the plan document goes red instead of quiet.
//
// ⚠️ UPDATED 2026-09-23 (row 977eaaf2): `/api/init` IS secured now — it carries
// `Depends(require_admin)`, so a direct request without an admin token answers 401
// or 403. The sentence here used to say the opposite, and a reassurance that has
// gone stale is worse than a wrong instruction: it disarms the reader who would
// otherwise have checked.
//
// What has NOT changed is this file's subject. The CLIENT button is still ungated,
// per Rick's later ruling, and the tests below still assert the ABSENCE of a client
// gate so that re-adding one from the plan document goes red instead of quiet. The
// server gate is a separate axis and no assertion here claims anything about it.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/system_status_renderer_parity.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSystemStatusRenderer,
  CONNECTION_PILLS,
  NOT_INITIALIZED_PILL,
  SEEDED,
  HEALTH_MONITORING,
  HEALTH_STOPPED,
  HEALTH_CIRCUIT,
  HEALTH_INTERVAL_MS,
  type TransportStateLike,
} from "../../../../lupin_app/static/js/multiplexer/render/SystemStatusRenderer";
import type { ConnectionState, ConnectionStateChangePayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const FIXED_DATE = (): Date => new Date( "2026-09-23T20:30:07Z" );

/** A transport whose state can be moved between assertions. */
function fakeTransport( state: ConnectionState ): TransportStateLike & { set( s: ConnectionState ): void } {
  const holder = { state, set( s: ConnectionState ) { holder.state = s; } };
  return holder;
}

/**
 * An auth fake that HOLDS a situation.
 *
 * 🔴 `getToken` REJECTING AND `getCurrentUserEmail` ANSWERING ARE INDEPENDENT,
 * because that pair is exactly what separates "never logged in" from "token
 * expired" — a fake that coupled them could not tell the two apart, and neither
 * could any assertion written over it.
 */
function fakeAuth( init: { tokenOk?: boolean; email?: string | null; admin?: boolean } = {} ) {
  const state = {
    tokenOk : init.tokenOk !== false,
    email   : init.email === undefined ? "rick@example.com" : init.email,
    admin   : init.admin === true,
  };
  return {
    state,
    auth: {
      getToken             : async () => {
        if ( !state.tokenOk ) throw new Error( "refresh failed" );
        return { accessToken: "t", expiresAt: 0 } as never;
      },
      getCurrentUserEmail  : () => state.email,
      isCurrentUserAdmin   : () => state.admin,
    },
  };
}

interface MountOpts {
  queue?       : TransportStateLike;
  audio?       : TransportStateLike;
  auth?        : ReturnType<typeof fakeAuth>[ "auth" ];
  sessionIds?  : { queue: string | null; audio: string | null };
  reinit?      : () => Promise<{ status?: string; message?: string }>;
  clipboardFn? : ( text: string ) => Promise<void>;
  logFn?       : ( message: string ) => void;
}

function mountPane( opts: MountOpts = {} ) {
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  const timeouts  : Array<() => void> = [];
  const intervals : Array<{ cb: () => void; ms: number }> = [];
  const cleared   : number[] = [];
  const copied    : string[] = [];

  const r = createSystemStatusRenderer( {
    eventBus   : bus,
    auth       : opts.auth ?? fakeAuth().auth,
    transports : { queue: opts.queue, audio: opts.audio },
    sessionIds : opts.sessionIds ?? { queue: "wise penguin", audio: "clever dolphin" },
    reinitConfig : opts.reinit ?? ( async () => ( { status: "success", message: "ok" } ) ),
    logFn       : opts.logFn ?? ( () => {} ),
    nowDateFn   : FIXED_DATE,
    clipboardFn : opts.clipboardFn ?? ( async ( t ) => { copied.push( t ); } ),
    setTimeoutFn   : ( cb ) => { timeouts.push( cb ); return timeouts.length; },
    clearTimeoutFn : () => {},
    setIntervalFn  : ( cb, ms ) => { intervals.push( { cb, ms } ); return intervals.length; },
    clearIntervalFn: ( h ) => { cleared.push( h ); },
  } );
  r.mount( root );

  const q  = ( testid: string ): HTMLElement =>
    root.querySelector( `[data-testid="${ testid }"]` ) as HTMLElement;
  const text = ( testid: string ): string => q( testid )?.textContent ?? "";
  const cls  = ( testid: string ): string => q( testid )?.className ?? "";
  const emitState = ( transport: string, state: ConnectionState ): void => {
    bus.emit<ConnectionStateChangePayload>( {
      type: "connection_state_change",
      payload: { state, prev: "connecting", attempts: 0, transport },
      source: "test", ts: 0,
    } );
  };
  return { root, renderer: r, bus, q, text, cls, emitState, timeouts, intervals, cleared, copied };
}

const settle = async (): Promise<void> => { for ( let i = 0; i < 6; i++ ) await Promise.resolve(); };

// ---------------------------------------------------------------------------
// B10 — the seeded values ARE the spec
// ---------------------------------------------------------------------------

test( "B10: every row seeds with legacy's own words before anything is measured", () => {
  // ⚠️ NOT awaited — this is the paint between mount and the first resolution.
  // "Disconnected" before a socket has tried is a CLAIM, and it is legacy's
  // claim; "Unknown" would be more honest and would also be a divergence.
  const { text } = mountPane();
  assert.equal( text( "multiplexer-ws-queue-status" ), NOT_INITIALIZED_PILL.text,
    "no transport wired → legacy's else-leg, not the seeded string" );
  assert.equal( text( "multiplexer-auth-status" ),     SEEDED.auth );
  assert.equal( text( "multiplexer-user-display" ),    SEEDED.user );
  assert.equal( text( "multiplexer-ws-health-status" ), HEALTH_MONITORING );
} );

test( "B10: a pane with transports seeds both pills from their current state, not from a constant", () => {
  const { text } = mountPane( { queue: fakeTransport( "offline" ), audio: fakeTransport( "connected" ) } );
  assert.equal( text( "multiplexer-ws-queue-status" ), SEEDED.socket, "offline reads as legacy's 'Disconnected'" );
  assert.equal( text( "multiplexer-ws-audio-status" ), "Connected" );
} );

// ---------------------------------------------------------------------------
// S1 / S2 — the pills
// ---------------------------------------------------------------------------

test( "S1/S2: every one of the six connection states maps to a pill, and the map is total", () => {
  // A missing key would make `CONNECTION_PILLS[state]` undefined and throw at
  // paint time — on the ONE state nobody exercised. So the map is checked
  // against the type's own members rather than against the states a test happens
  // to drive.
  const ALL: ConnectionState[] = [ "connecting", "connected", "reconnecting", "backoff", "offline", "failed" ];
  for ( const state of ALL ) {
    const pill = CONNECTION_PILLS[ state ];
    assert.ok( pill !== undefined && pill.text !== "" && pill.cls !== "", `no pill for ${ state }` );
  }
  assert.equal( Object.keys( CONNECTION_PILLS ).length, ALL.length, "the map has no extra keys either" );
} );

test( "S1/S2: the two states this client splits and legacy does not both read 'Reconnecting...'", () => {
  // The mux has `reconnecting` AND `backoff` where legacy has one `BACKOFF`.
  // Telling the user two different things about one situation would be the
  // divergence, so both take legacy's single word.
  assert.equal( CONNECTION_PILLS.reconnecting.text, CONNECTION_PILLS.backoff.text );
  assert.equal( CONNECTION_PILLS.reconnecting.text, "Reconnecting..." );
} );

test( "🔴 S1: the pills follow socket EVENTS, not only the ↻", () => {
  // A pane repainting only on demand would show a stale "Connected" straight
  // through an outage — the reading most likely to stop someone investigating.
  const queue = fakeTransport( "connected" );
  const { text, cls, emitState } = mountPane( { queue, audio: fakeTransport( "connected" ) } );
  assert.equal( text( "multiplexer-ws-queue-status" ), "Connected", "positive control" );

  queue.set( "failed" );
  emitState( "QueueTransport", "failed" );

  assert.equal( text( "multiplexer-ws-queue-status" ), "Circuit open" );
  assert.equal( cls( "multiplexer-ws-queue-status" ), "status-error" );
} );

test( "a socket event also re-derives the health line", () => {
  const queue = fakeTransport( "connected" );
  const { text, emitState } = mountPane( { queue, audio: fakeTransport( "connected" ) } );
  queue.set( "failed" );
  emitState( "QueueTransport", "failed" );
  assert.equal( text( "multiplexer-ws-health-status" ), HEALTH_CIRCUIT );
} );

// ---------------------------------------------------------------------------
// S3 — auth
// ---------------------------------------------------------------------------

test( "S3: a valid token reads 'Authenticated' and shows the email", async () => {
  const { text, cls } = mountPane( { auth: fakeAuth().auth } );
  await settle();
  assert.equal( text( "multiplexer-auth-status" ),  "Authenticated" );
  assert.equal( cls( "multiplexer-auth-status" ),   "status-good" );
  assert.equal( text( "multiplexer-user-display" ), "rick@example.com" );
} );

test( "S3: an admin's row carries ' (admin)'", async () => {
  const { text } = mountPane( { auth: fakeAuth( { admin: true } ).auth } );
  await settle();
  assert.equal( text( "multiplexer-auth-status" ), "Authenticated (admin)" );
} );

test( "🔴 S3: 'Token expired' and 'Not authenticated' are DIFFERENT states, told apart by the email claim", async () => {
  // A stored-but-dead token still carries an email; never having logged in does
  // not. Collapsing the two would tell someone whose session lapsed that they
  // were never signed in, and they would go looking in the wrong place.
  const expired = mountPane( { auth: fakeAuth( { tokenOk: false, email: "rick@example.com" } ).auth } );
  await settle();
  assert.equal( expired.text( "multiplexer-auth-status" ), "Token expired" );
  assert.equal( expired.cls( "multiplexer-auth-status" ),  "status-error" );
  assert.equal( expired.text( "multiplexer-user-display" ), SEEDED.user,
    "legacy returns early here and does NOT touch the user row" );

  const never = mountPane( { auth: fakeAuth( { tokenOk: false, email: null } ).auth } );
  await settle();
  assert.equal( never.text( "multiplexer-auth-status" ),  SEEDED.auth );
  assert.equal( never.text( "multiplexer-user-display" ), "Not logged in" );
} );

test( "S3: a valid token with no email claim falls back to 'Unknown', as legacy does", async () => {
  const { text } = mountPane( { auth: fakeAuth( { email: null } ).auth } );
  await settle();
  assert.equal( text( "multiplexer-user-display" ), "Unknown" );
} );

// ---------------------------------------------------------------------------
// S6 — sessions and 📋
// ---------------------------------------------------------------------------

test( "S6: both session ids render as <code>", () => {
  const { text, q } = mountPane();
  assert.equal( text( "multiplexer-queue-session" ), "wise penguin" );
  assert.equal( text( "multiplexer-audio-session" ), "clever dolphin" );
  assert.equal( q( "multiplexer-queue-session" ).tagName, "CODE" );
} );

test( "S6: an absent session id reads legacy's '-'", () => {
  const { text } = mountPane( { sessionIds: { queue: null, audio: null } } );
  assert.equal( text( "multiplexer-queue-session" ), SEEDED.session );
} );

test( "S6: 📋 copies the id and shows a brief checkmark", async () => {
  const { q, copied, timeouts } = mountPane();
  const btn = q( "multiplexer-queue-session-copy" );
  btn.click();
  await settle();

  assert.deepEqual( copied, [ "wise penguin" ] );
  assert.equal( btn.textContent, "✅" );
  assert.equal( timeouts.length, 1, "one revert is scheduled" );
  timeouts[ 0 ]!();
  assert.equal( btn.textContent, "📋", "and it reverts" );
} );

test( "🔴 S6: 📋 on a '-' placeholder copies NOTHING and gives NO feedback", async () => {
  // A checkmark over a copied dash is a lie about what happened, and the
  // operator only finds out when they paste.
  const { q, copied } = mountPane( { sessionIds: { queue: null, audio: null } } );
  const btn = q( "multiplexer-queue-session-copy" );
  btn.click();
  await settle();
  assert.deepEqual( copied, [], "nothing reached the clipboard" );
  assert.equal( btn.textContent, "📋", "and the button never claimed otherwise" );
} );

// ---------------------------------------------------------------------------
// S7 — the health line
// ---------------------------------------------------------------------------

// ⚠️ EACH OF THESE TICKS THE INTERVAL FIRST. At mount the line reads
// "Monitoring (90s interval)" — legacy writes that when the monitor STARTS
// (notifications.js:1103) and only derives a verdict on a tick. Asserting the
// derived text straight after mount would be asserting a state neither client
// is in, and it is how these four cases were wrong on their first run.
test( "S7: both connected → '✓ Healthy (checked …)'", () => {
  const { text, intervals } = mountPane( { queue: fakeTransport( "connected" ), audio: fakeTransport( "connected" ) } );
  assert.equal( text( "multiplexer-ws-health-status" ), HEALTH_MONITORING, "before the first tick" );
  intervals[ 0 ]!.cb();
  assert.match( text( "multiplexer-ws-health-status" ), /^✓ Healthy \(checked .+\)$/ );
} );

test( "S7: either socket failed → the circuit message, which wins over a half-connected pair", () => {
  const { text, intervals } = mountPane( { queue: fakeTransport( "connected" ), audio: fakeTransport( "failed" ) } );
  intervals[ 0 ]!.cb();
  assert.equal( text( "multiplexer-ws-health-status" ), HEALTH_CIRCUIT );
} );

test( "S7: anything else names BOTH states, so the line says which half is unwell", () => {
  const { text, intervals } = mountPane( { queue: fakeTransport( "connected" ), audio: fakeTransport( "backoff" ) } );
  intervals[ 0 ]!.cb();
  assert.equal( text( "multiplexer-ws-health-status" ), "Watchdog: queue=connected audio=backoff" );
} );

test( "S7: an unwired transport reads 'none' rather than being silently skipped", () => {
  const { text, intervals } = mountPane( { queue: fakeTransport( "connected" ) } );
  intervals[ 0 ]!.cb();
  assert.equal( text( "multiplexer-ws-health-status" ), "Watchdog: queue=connected audio=none" );
} );

test( "🔴 S7: the readout runs on a 90s interval, and NOTHING pokes a socket", () => {
  // Legacy's watchdog nudges each channel here. This client's
  // ConnectionStateMachine owns reconnection, so a second nudge would be a
  // second thing deciding when to reconnect. The interval is a READOUT only.
  const queue = fakeTransport( "connected" );
  const { intervals, text } = mountPane( { queue, audio: fakeTransport( "connected" ) } );
  assert.equal( intervals.length, 1 );
  assert.equal( intervals[ 0 ]!.ms, HEALTH_INTERVAL_MS, "the words say 90s, so the cadence must be 90s" );

  queue.set( "offline" );
  intervals[ 0 ]!.cb();
  assert.equal( text( "multiplexer-ws-health-status" ), "Watchdog: queue=offline audio=connected",
    "the tick re-derives the line from state it READ, having changed nothing" );
} );

test( "unmount stops the interval and says so on the line", () => {
  const { renderer, root, cleared } = mountPane( { queue: fakeTransport( "connected" ) } );
  const health = root.querySelector( '[data-testid="multiplexer-ws-health-status"]' ) as HTMLElement;
  renderer.unmount();
  assert.equal( cleared.length, 1, "the interval is cleared" );
  assert.equal( health.textContent, HEALTH_STOPPED,
    "a stale '✓ Healthy' outliving the monitor is what this string prevents" );
} );

// ---------------------------------------------------------------------------
// B8 — the ↻
// ---------------------------------------------------------------------------

test( "B8: ↻ disables and spins for the duration, and re-enables afterwards", async () => {
  let release: ( () => void ) | null = null;
  const auth = {
    getToken            : () => new Promise( ( res ) => { release = () => res( { accessToken: "t" } as never ); } ),
    getCurrentUserEmail : () => "rick@example.com",
    isCurrentUserAdmin  : () => false,
  };
  const { q, renderer } = mountPane( { auth: auth as never } );
  const btn = q( "multiplexer-status-refresh-btn" ) as HTMLButtonElement;

  const pending = renderer.refreshForTesting();
  assert.equal( btn.disabled, true, "disabled while in flight" );
  assert.ok( btn.classList.contains( "spinning" ) );

  release!();
  await pending;
  assert.equal( btn.disabled, false );
  assert.equal( btn.classList.contains( "spinning" ), false );
} );

test( "🔴 B8: a throw anywhere in the pass is CAUGHT and logged, and the control re-enables", async () => {
  // Two things at once, because they failed together on the first run. A
  // refresh that threw and left the button disabled looks like a hung pane and
  // the operator's only remedy is the page reload they were avoiding — AND an
  // uncaught throw out of a click handler becomes an unhandled rejection, which
  // surfaces nowhere the operator can see. Legacy catches (notifications.js:1493);
  // this file's first cut had only a `finally`, and node's test runner caught it.
  const auth = {
    getToken            : async () => { throw new Error( "boom" ); },
    getCurrentUserEmail : () => { throw new Error( "boom too" ); },
    isCurrentUserAdmin  : () => false,
  };
  const logs: string[] = [];
  const { q, renderer } = mountPane( { auth: auth as never, logFn: ( m ) => logs.push( m ) } );
  const btn = q( "multiplexer-status-refresh-btn" ) as HTMLButtonElement;

  await renderer.refreshForTesting();   // must NOT reject
  assert.equal( btn.disabled, false, "re-enabled anyway" );
  assert.equal( btn.classList.contains( "spinning" ), false );
  // The auth readout catches its own throw, so the line names THAT rather than
  // the outer pass — asserted specifically, because "some log happened" would
  // pass on a build that reported the wrong thing and send the reader to the
  // wrong half of the pane.
  assert.ok( logs.some( ( m ) => /auth readout failed/.test( m ) ), "and it is reported, not swallowed" );
  assert.ok( logs.every( ( m ) => !/status refresh failed/.test( m ) ),
    "the outer catch stays a backstop — if it fires, something ELSE threw and that is worth knowing" );
} );

test( "🔴 B8: the OUTER backstop catches a throw the auth readout cannot — and names it differently", () => {
  // ⚠️ THIS EXISTS BECAUSE THE BACKSTOP WAS OTHERWISE UNREACHED. `refreshAuth`
  // now swallows its own throws, so the outer catch in `refreshAll` was live
  // code no test entered — which is indistinguishable from dead code until the
  // day something else throws. A transport whose `state` getter throws puts a
  // failure in `paintSockets()`, which only the outer catch can hold.
  // It starts healthy and goes bad AFTER mount, which is not a contrivance — it
  // is a transport torn down under a live pane. A getter that threw from the
  // first read would blow up `mount()` instead, which is a different failure and
  // not the one this backstop is for.
  const logs: string[] = [];
  let healthy = true;
  const hostile: TransportStateLike = {
    get state(): ConnectionState {
      if ( !healthy ) throw new Error( "transport exploded" );
      return "connected";
    },
  };
  const { renderer, q } = mountPane( { queue: hostile, logFn: ( m ) => logs.push( m ) } );
  healthy = false;
  const btn = q( "multiplexer-status-refresh-btn" ) as HTMLButtonElement;

  return renderer.refreshForTesting().then( () => {
    assert.ok( logs.some( ( m ) => /status refresh failed/.test( m ) ),
      "the outer catch fires, and says 'status refresh' rather than 'auth readout' — " +
      "the two messages are what tell a reader WHICH half broke" );
    assert.equal( btn.disabled, false, "and the finally still re-enabled the control" );
  } );
} );

test( "B2: pressing ↻ does not collapse the section", () => {
  const { root, q } = mountPane();
  q( "multiplexer-status-refresh-btn" ).dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.notEqual( root.getAttribute( "data-collapsed" ), "true" );
} );

test( "B3: collapse works and is NOT persisted", () => {
  const first = mountPane();
  ( first.root.querySelector( ".section-header h3" ) as HTMLElement )
    .dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( first.root.getAttribute( "data-collapsed" ), "true" );

  const second = mountPane();
  assert.notEqual( second.root.getAttribute( "data-collapsed" ), "true",
    "persistence is available since A-2 #6, so its absence here is a decision — legacy does not persist this section" );
} );

// ---------------------------------------------------------------------------
// S8 / B-5L — the Config reload
// ---------------------------------------------------------------------------

test( "🔴 S8: the reload button is PLAIN — no admin gate, no hidden state", () => {
  // Rick's 2026-09-23 ruling, reversing the build plan's §3 R8. `admin` matches
  // ZERO lines in legacy's reinitializeConfig (notifications.js:1399-1458), so a
  // gate here would be the multiplexer inventing a behaviour. This assertion
  // exists so that re-adding one from the plan document goes RED, not quiet.
  const nonAdmin = mountPane( { auth: fakeAuth( { admin: false } ).auth } );
  const btn = nonAdmin.q( "multiplexer-config-reload-btn" ) as HTMLButtonElement;
  assert.notEqual( btn, null, "a non-admin sees the button" );
  assert.equal( btn.hidden, false, "it is not hidden" );
  assert.equal( btn.disabled, false, "and it is not disabled" );
  assert.equal( btn.textContent, "↻ Reload" );
} );

test( "S8: a success writes a green ✓", async () => {
  const { q, text, cls } = mountPane( { reinit: async () => ( { status: "success", message: "reloaded" } ) } );
  q( "multiplexer-config-reload-btn" ).click();
  await settle();
  assert.equal( text( "multiplexer-config-status" ), "✓" );
  assert.match( cls( "multiplexer-config-status" ), /config-status-ok/ );
} );

test( "S8: a non-success writes a red ✗ carrying the SERVER's own message", async () => {
  const { q, text, cls } = mountPane( { reinit: async () => ( { status: "error", message: "bad ini" } ) } );
  q( "multiplexer-config-reload-btn" ).click();
  await settle();
  assert.equal( text( "multiplexer-config-status" ), "✗ bad ini",
    "the server's reason is what makes this actionable; '✗' alone sends the reader nowhere" );
  assert.match( cls( "multiplexer-config-status" ), /config-status-error/ );
} );

test( "S8: a non-success with NO message still writes a ✗, not a blank status", async () => {
  // The server is allowed to omit `message`. A `✗ undefined` would be worse than
  // useless and an empty string would read as success, so the glyph carries it
  // alone — checked because this is the one leg with no words to assert on.
  const { q, text, cls } = mountPane( { reinit: async () => ( { status: "error" } ) } );
  q( "multiplexer-config-reload-btn" ).click();
  await settle();
  assert.equal( text( "multiplexer-config-status" ), "✗ " );
  assert.match( cls( "multiplexer-config-status" ), /config-status-error/ );
} );

test( "S8: a throw writes a red ✗ with the error's message, and a message-less throw says 'Network error'", async () => {
  const withMsg = mountPane( { reinit: async () => { throw new Error( "connection refused" ); } } );
  withMsg.q( "multiplexer-config-reload-btn" ).click();
  await settle();
  assert.equal( withMsg.text( "multiplexer-config-status" ), "✗ connection refused" );

  const bare = mountPane( { reinit: async () => { throw new Error( "" ); } } );
  bare.q( "multiplexer-config-reload-btn" ).click();
  await settle();
  assert.equal( bare.text( "multiplexer-config-status" ), "✗ Network error" );
} );

test( "S8: a non-Error throw also lands on 'Network error' rather than printing '[object Object]'", async () => {
  const { q, text } = mountPane( { reinit: async () => { throw { weird: true }; } } );
  q( "multiplexer-config-reload-btn" ).click();
  await settle();
  assert.equal( text( "multiplexer-config-status" ), "✗ Network error" );
} );

test( "🔴 S8: the previous message is cleared BEFORE the call, so a stale ✗ is never read as this press's result", async () => {
  let outcome: { status?: string; message?: string } = { status: "error", message: "bad ini" };
  let release: ( () => void ) | null = null;
  const { q, text } = mountPane( {
    reinit: () => new Promise( ( res ) => { release = () => res( outcome ); } ),
  } );
  const btn = q( "multiplexer-config-reload-btn" ) as HTMLButtonElement;

  btn.click();
  release!();
  await settle();
  assert.equal( text( "multiplexer-config-status" ), "✗ bad ini", "positive control: there is a message to clear" );

  outcome = { status: "success" };
  btn.click();
  assert.equal( text( "multiplexer-config-status" ), "", "cleared the moment the press starts" );
  assert.equal( btn.disabled, true, "and dimmed while in flight" );
  release!();
  await settle();
  assert.equal( text( "multiplexer-config-status" ), "✓" );
} );

test( "S8: the button re-enables in a `finally`, on the failing path too", async () => {
  const { q } = mountPane( { reinit: async () => { throw new Error( "boom" ); } } );
  const btn = q( "multiplexer-config-reload-btn" ) as HTMLButtonElement;
  btn.click();
  await settle();
  assert.equal( btn.disabled, false );
  assert.equal( btn.style.opacity, "1" );
} );

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test( "mounting twice throws; unmount empties the root and detaches the socket subscription", () => {
  const queue = fakeTransport( "connected" );
  const { root, renderer, emitState } = mountPane( { queue } );
  assert.throws( () => renderer.mount( document.createElement( "div" ) ), /already mounted/ );

  renderer.unmount();
  assert.equal( root.children.length, 0 );
  queue.set( "failed" );
  emitState( "QueueTransport", "failed" );   // must not throw into a torn-down pane
} );
