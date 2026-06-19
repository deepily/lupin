// WebSocket diagnostic tool TS port — unit tests.
//
// TS port of `src/lupin_app/static/js/websocket-diagnostic.js`. Drives the full
// class (session fetch, connect lifecycle incl. the APPROVED composed-handler
// bug-fix, duplicate detection, message handling, audio playback + overlap
// detection, stop/reset, analysis) and the boot wiring — all deterministically
// via injected seams (doc / clock / WebSocket factory / fetch / object-URL /
// audio factory / connect-timeout). Target: c8 --100 changed-surface.
//
// Run via: npx tsx --test src/tests/unit/diagnostic/websocket_diagnostic_port.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
    WebSocketDiagnosticTool,
    WS_OPEN,
    type DiagnosticDeps,
    type WebSocketLike,
    type ResponseLike,
} from "../../../lupin_app/static/js/diagnostic/websocketDiagnostic";
import { wireDiagnostic, type DiagnosticWindow } from "../../../lupin_app/static/js/diagnostic/boot";

before(() => {
    if ( typeof globalThis.document === "undefined" ) {
        GlobalRegistrator.register();
    }
});

// ---------------------------------------------------------------------------
// Test doubles
// ---------------------------------------------------------------------------

class MockWS implements WebSocketLike {
    onopen   : ( ( ev?: unknown ) => void ) | null = null;
    onclose  : ( ( ev: { code: number; reason: string } ) => void ) | null = null;
    onerror  : ( ( ev: unknown ) => void ) | null = null;
    onmessage: ( ( ev: { data: unknown } ) => void ) | null = null;
    readyState = 0;
    closeCount = 0;
    close(): void { this.closeCount++; this.readyState = 3; }
    fireOpen(): void { this.readyState = WS_OPEN; this.onopen?.(); }
    fireClose( code: number, reason: string ): void { this.onclose?.( { code, reason } ); }
    fireError( e: unknown ): void { this.onerror?.( e ); }
    fireMessage( data: unknown ): void { this.onmessage?.( { data } ); }
}

interface Ctrl {
    deps              : DiagnosticDeps;
    clock             : { t: number };
    createdSockets    : MockWS[];
    audios            : HTMLAudioElement[];
    objectUrlsCreated : string[];
    objectUrlsRevoked : string[];
    consoleMsgs       : string[];
    pausedSpy         : HTMLAudioElement[];
    lastTimeoutCb     : ( () => void ) | null;
    fetchImpl         : ( url: string, init?: unknown ) => Promise<ResponseLike>;
    playImpl          : () => Promise<void> | undefined;
}

function makeResponse( ok: boolean, status: number, statusText: string, body: unknown ): ResponseLike {
    return { ok, status, statusText, json: async () => body };
}

function makeCtrl(): Ctrl {
    const ctrl: Ctrl = {
        deps              : null as unknown as DiagnosticDeps,
        clock             : { t: 1000 },
        createdSockets    : [],
        audios            : [],
        objectUrlsCreated : [],
        objectUrlsRevoked : [],
        consoleMsgs       : [],
        pausedSpy         : [],
        lastTimeoutCb     : null,
        fetchImpl         : async () => makeResponse( true, 200, "OK", { session_id: "sess-default" } ),
        playImpl          : () => Promise.resolve(),
    };

    ctrl.deps = {
        doc            : document,
        host           : "localhost:7999",
        now            : () => ctrl.clock.t,
        createWebSocket: () => { const ws = new MockWS(); ctrl.createdSockets.push( ws ); return ws; },
        fetchFn        : ( url, init ) => ctrl.fetchImpl( url, init ),
        createObjectURL: () => { const u = `blob:fake-${ctrl.objectUrlsCreated.length}`; ctrl.objectUrlsCreated.push( u ); return u; },
        revokeObjectURL: ( u ) => { ctrl.objectUrlsRevoked.push( u ); },
        createAudio    : () => {
            const a = document.createElement( "audio" );
            Object.defineProperty( a, "paused", { value: true, writable: true, configurable: true } );
            a.play  = ( () => ctrl.playImpl() ) as HTMLAudioElement[ "play" ];
            a.pause = () => { ( a as unknown as { paused: boolean } ).paused = true; ctrl.pausedSpy.push( a ); };
            ctrl.audios.push( a );
            return a;
        },
        setTimeoutFn   : ( cb ) => { ctrl.lastTimeoutCb = cb; return 0; },
        consoleLog     : ( m ) => { ctrl.consoleMsgs.push( m ); },
    };
    return ctrl;
}

const STATUS_IDS = [
    "session-id", "active-connections", "total-connections", "duplicate-connections",
    "chunks-received", "audio-elements", "simultaneous-play", "first-audio-latency",
];

function buildDom(): void {
    document.body.replaceChildren();
    const make = ( id: string, tag = "div" ) => { const el = document.createElement( tag ); el.id = id; document.body.appendChild( el ); return el; };
    make( "diagnostic-console" );
    STATUS_IDS.forEach( ( id ) => make( id, "span" ) );
    make( "diagnostic-test-btn", "button" );
    make( "connection-list" );
    make( "chunk-timeline" );
    // Use inputs (not selects) so an arbitrary .value sticks under happy-dom; the
    // port reads `.value` generically, so this faithfully exercises getCurrentSettings.
    ( make( "test-text", "input" ) as HTMLInputElement ).value = "hello world";
    ( make( "voice-select", "input" ) as HTMLInputElement ).value = "voiceX";
    ( make( "model-select", "input" ) as HTMLInputElement ).value = "modelX";
    ( make( "profile-select", "input" ) as HTMLInputElement ).value = "premium";
}

beforeEach(() => { buildDom(); });

function newTool(): { tool: WebSocketDiagnosticTool; ctrl: Ctrl } {
    const ctrl = makeCtrl();
    return { tool: new WebSocketDiagnosticTool( ctrl.deps ), ctrl };
}

/** Build a tool that has been initialize()d with a successful session fetch. */
async function initedTool(): Promise<{ tool: WebSocketDiagnosticTool; ctrl: Ctrl }> {
    const { tool, ctrl } = newTool();
    ctrl.fetchImpl = async () => makeResponse( true, 200, "OK", { session_id: "sess-1" } );
    await tool.initialize();
    return { tool, ctrl };
}

// ===========================================================================
// initialize / getSessionId
// ===========================================================================

test( "initialize wires UI, fetches session id, populates status", async () => {
    const { tool } = await initedTool();
    assert.equal( tool.sessionId, "sess-1" );
    assert.equal( document.getElementById( "session-id" )!.textContent, "sess-1" );
    assert.ok( tool.logElement );
} );

test( "getSessionId rejects + logs on fetch failure", async () => {
    const { tool, ctrl } = newTool();
    ctrl.fetchImpl = async () => { throw new Error( "network down" ); };
    await assert.rejects( () => tool.initialize(), /network down/ );
} );

test( "initialize tolerates a null session id (?? fallback)", async () => {
    const { tool, ctrl } = newTool();
    ctrl.fetchImpl = async () => makeResponse( true, 200, "OK", { session_id: null } );
    await tool.initialize();
    assert.equal( tool.sessionId, null );
    assert.equal( document.getElementById( "session-id" )!.textContent, "" );  // ?? "" branch
} );

// ===========================================================================
// startDiagnosticTest
// ===========================================================================

test( "startDiagnosticTest no-ops when already running", async () => {
    const { tool } = await initedTool();
    tool.isRunning = true;
    await tool.startDiagnosticTest();
    assert.equal( tool.connectionCounter, 0 );  // never reached createMonitoredWebSocket
} );

test( "startDiagnosticTest warns when no text entered", async () => {
    const { tool } = await initedTool();
    ( document.getElementById( "test-text" ) as HTMLInputElement ).value = "";
    await tool.startDiagnosticTest();
    assert.equal( tool.isRunning, false );
    assert.equal( tool.connectionCounter, 0 );
} );

test( "startDiagnosticTest happy path: connect, send TTS, disable button", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.fetchImpl = async ( url ) =>
        url === "/api/get-speech-elevenlabs" ? makeResponse( true, 200, "OK", { ok: true } ) : makeResponse( true, 200, "OK", { session_id: "sess-1" } );

    const p = tool.startDiagnosticTest();
    ctrl.createdSockets.at( -1 )!.fireOpen();   // resolve the connect promise
    await p;

    assert.equal( tool.isRunning, true );
    assert.equal( tool.activeConnections, 1 );  // revived metrics (composed-handler fix)
    const btn = document.getElementById( "diagnostic-test-btn" ) as HTMLButtonElement;
    assert.equal( btn.disabled, true );
    assert.equal( btn.textContent, "🔄 Running Diagnostic..." );
} );

test( "startDiagnosticTest happy path tolerates a missing test button", async () => {
    const { tool, ctrl } = await initedTool();
    document.getElementById( "diagnostic-test-btn" )!.remove();
    ctrl.fetchImpl = async () => makeResponse( true, 200, "OK", { ok: true } );

    const p = tool.startDiagnosticTest();
    ctrl.createdSockets.at( -1 )!.fireOpen();
    await p;
    assert.equal( tool.isRunning, true );
} );

test( "startDiagnosticTest catch path: connect error resets running state", async () => {
    const { tool, ctrl } = await initedTool();
    const p = tool.startDiagnosticTest();
    ctrl.createdSockets.at( -1 )!.fireError( "boom" );  // reject the connect promise
    await p;
    assert.equal( tool.isRunning, false );
    const btn = document.getElementById( "diagnostic-test-btn" ) as HTMLButtonElement;
    assert.equal( btn.disabled, false );
} );

// ===========================================================================
// createMonitoredWebSocket — connect lifecycle + composed handlers
// ===========================================================================

test( "createMonitoredWebSocket resolves on open + revives connected metrics", async () => {
    const { tool, ctrl } = await initedTool();
    const p = tool.createMonitoredWebSocket();
    const ws = ctrl.createdSockets.at( -1 )!;
    ws.fireOpen();
    await p;
    assert.equal( tool.activeConnections, 1 );
    assert.equal( tool.connectionCounter, 1 );
} );

test( "createMonitoredWebSocket tolerates a null session id in the URL (?? fallback)", async () => {
    const { tool, ctrl } = await initedTool();
    tool.sessionId = null;
    const p = tool.createMonitoredWebSocket();
    ctrl.createdSockets.at( -1 )!.fireOpen();
    await p;
    assert.equal( tool.activeConnections, 1 );
} );

test( "createMonitoredWebSocket flags a duplicate when one is already active", async () => {
    const { tool, ctrl } = await initedTool();
    const p1 = tool.createMonitoredWebSocket();
    ctrl.createdSockets.at( -1 )!.fireOpen();
    await p1;

    const p2 = tool.createMonitoredWebSocket();  // existingActive > 0
    ctrl.createdSockets.at( -1 )!.fireOpen();
    await p2;
    assert.equal( tool.duplicateConnections, 1 );
    assert.ok( document.getElementById( "duplicate-connections" )!.textContent === "1" );
} );

test( "createMonitoredWebSocket rejects on error and on timeout, ignoring post-settle events", async () => {
    const { tool, ctrl } = await initedTool();

    // error rejects
    const pErr = tool.createMonitoredWebSocket();
    ctrl.createdSockets.at( -1 )!.fireError( "x" );
    await assert.rejects( () => pErr, /WebSocket error/ );

    // timeout rejects
    const pTo = tool.createMonitoredWebSocket();
    ctrl.lastTimeoutCb!();
    await assert.rejects( () => pTo, /timeout/ );

    // post-settle: open then a late timeout + late open + late error are all no-ops
    const pOk = tool.createMonitoredWebSocket();
    const ws = ctrl.createdSockets.at( -1 )!;
    ws.fireOpen();
    await pOk;
    ctrl.lastTimeoutCb!();   // settled → timeout no-op
    ws.fireOpen();           // settled → onopen metrics run again, resolve skipped
    ws.fireError( "late" );  // settled → onerror logs, reject skipped
    assert.ok( tool.activeConnections >= 1 );
} );

test( "onclose handler updates state + decrements active count", async () => {
    const { tool, ctrl } = await initedTool();
    const p = tool.createMonitoredWebSocket();
    const ws = ctrl.createdSockets.at( -1 )!;
    ws.fireOpen();
    await p;
    assert.equal( tool.activeConnections, 1 );
    ws.fireClose( 1000, "bye" );
    assert.equal( tool.activeConnections, 0 );
} );

// ===========================================================================
// handleDiagnosticMessage
// ===========================================================================

async function toolWithConnection(): Promise<{ tool: WebSocketDiagnosticTool; ctrl: Ctrl; ws: MockWS }> {
    const { tool, ctrl } = await initedTool();
    const p = tool.createMonitoredWebSocket();
    const ws = ctrl.createdSockets.at( -1 )!;
    ws.fireOpen();
    await p;
    return { tool, ctrl, ws };
}

test( "handleDiagnosticMessage: first blob chunk records latency (fast = success)", async () => {
    const { tool, ws, ctrl } = await toolWithConnection();
    tool.startTime = 1000;
    ctrl.clock.t = 1200;                       // latency 200ms (<500 → success)
    ws.fireMessage( new Blob( [ "abc" ] ) );
    assert.equal( tool.chunksReceived, 1 );
    assert.equal( document.getElementById( "first-audio-latency" )!.textContent, "200ms" );
} );

test( "handleDiagnosticMessage: first blob chunk slow latency = warning branch", async () => {
    const { tool, ws, ctrl } = await toolWithConnection();
    tool.startTime = 1000;
    ctrl.clock.t = 1800;                       // latency 800ms (>=500 → warning)
    ws.fireMessage( new Blob( [ "abcd" ] ) );
    assert.equal( document.getElementById( "first-audio-latency" )!.textContent, "800ms" );
} );

test( "handleDiagnosticMessage: chunk with no startTime skips the latency block", async () => {
    const { tool, ws } = await toolWithConnection();
    tool.startTime = null;
    ws.fireMessage( new Blob( [ "z" ] ) );     // chunksReceived === 1 but startTime falsy
    assert.equal( tool.chunksReceived, 1 );
    assert.equal( document.getElementById( "first-audio-latency" )!.textContent, "" );
} );

test( "handleDiagnosticMessage: second chunk skips the first-audio block", async () => {
    const { tool, ws } = await toolWithConnection();
    tool.startTime = 1000;
    ws.fireMessage( new Blob( [ "a" ] ) );     // seq 1
    ws.fireMessage( new Blob( [ "b" ] ) );     // seq 2 → chunksReceived !== 1
    assert.equal( tool.chunksReceived, 2 );
} );

test( "handleDiagnosticMessage: streaming-complete JSON triggers onTestComplete", async () => {
    const { tool, ws } = await toolWithConnection();
    tool.startTime = 1000;
    ws.fireMessage( JSON.stringify( { type: "audio_streaming_complete" } ) );
    assert.equal( tool.isRunning, false );
} );

test( "handleDiagnosticMessage: other JSON message logs but does not complete", async () => {
    const { tool, ws } = await toolWithConnection();
    tool.isRunning = true;
    ws.fireMessage( JSON.stringify( { type: "status", text: "working" } ) );
    assert.equal( tool.isRunning, true );      // not completed
} );

test( "handleDiagnosticMessage: non-JSON text message hits the catch branch", async () => {
    const { tool, ws } = await toolWithConnection();
    assert.doesNotThrow( () => ws.fireMessage( "not json {{{" ) );
} );

// ===========================================================================
// simulateAudioPlayback
// ===========================================================================

test( "simulateAudioPlayback: play→ended lifecycle creates+cleans an audio element", async () => {
    const { tool, ctrl } = await initedTool();
    await tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" );
    const audio = ctrl.audios.at( -1 )!;
    assert.equal( ctrl.objectUrlsCreated.length, 1 );
    assert.ok( document.body.contains( audio ) );

    audio.dispatchEvent( new Event( "play" ) );
    audio.dispatchEvent( new Event( "ended" ) );
    assert.equal( ctrl.objectUrlsRevoked.length, 1 );
    assert.equal( document.body.contains( audio ), false );  // removed on ended
} );

test( "simulateAudioPlayback: ended without a prior play uses playEnded fallback duration", async () => {
    const { tool, ctrl } = await initedTool();
    await tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" );
    const audio = ctrl.audios.at( -1 )!;
    assert.doesNotThrow( () => audio.dispatchEvent( new Event( "ended" ) ) );  // playStarted undefined → ?? fallback
} );

test( "simulateAudioPlayback: error event marks the element errored", async () => {
    const { tool, ctrl } = await initedTool();
    await tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" );
    const audio = ctrl.audios.at( -1 )!;
    assert.doesNotThrow( () => audio.dispatchEvent( new Event( "error" ) ) );
} );

test( "simulateAudioPlayback: simultaneous playback + overlap-on-play are detected", async () => {
    const { tool } = await initedTool();
    // First element, force it into 'playing' so the next creation sees currentlyPlaying > 0.
    await tool.simulateAudioPlayback( new Blob( [ "a" ] ), 1, "conn_0" );
    const first = Array.from( tool.audioElements.values() )[ 0 ]!;
    first.state = "playing";

    await tool.simulateAudioPlayback( new Blob( [ "b" ] ), 2, "conn_0" );  // currentlyPlaying === 1 > 0
    assert.equal( tool.simultaneousPlayCount, 1 );

    // Firing play on the 2nd while the 1st is already 'playing' → nowPlaying > 1 overlap log.
    const second = Array.from( tool.audioElements.values() )[ 1 ]!;
    assert.doesNotThrow( () => second.element.dispatchEvent( new Event( "play" ) ) );
} );

test( "simulateAudioPlayback: undefined play() return skips the await", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.playImpl = () => undefined;
    await assert.doesNotReject( () => tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" ) );
} );

test( "simulateAudioPlayback: autoplay-prevented (NotAllowedError) is caught", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.playImpl = () => Promise.reject( Object.assign( new Error( "blocked" ), { name: "NotAllowedError" } ) );
    await tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" );
    const info = Array.from( tool.audioElements.values() ).at( -1 )!;
    assert.equal( info.state, "failed" );
} );

test( "simulateAudioPlayback: generic play failure is caught", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.playImpl = () => Promise.reject( new Error( "decode error" ) );
    await tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" );
    const info = Array.from( tool.audioElements.values() ).at( -1 )!;
    assert.equal( info.state, "failed" );
} );

test( "simulateAudioPlayback: a non-Error play rejection is stringified", async () => {
    const { tool, ctrl } = await initedTool();
    // Non-Error rejection → errName() returns "" (not NotAllowedError) and errMsg()
    // falls to String(error) — covers both error-helper ternaries' else branches.
    ctrl.playImpl = () => Promise.reject( "stringy failure" );
    await tool.simulateAudioPlayback( new Blob( [ "x" ] ), 1, "conn_0" );
    const info = Array.from( tool.audioElements.values() ).at( -1 )!;
    assert.equal( info.state, "failed" );
} );

// ===========================================================================
// sendTTSRequest
// ===========================================================================

test( "sendTTSRequest succeeds on ok response", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.fetchImpl = async () => makeResponse( true, 200, "OK", { queued: true } );
    await assert.doesNotReject( () => tool.sendTTSRequest( { text: "t", voice_id: "v", model_id: "m", quality_profile: "q" } ) );
} );

test( "sendTTSRequest throws on non-ok response", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.fetchImpl = async () => makeResponse( false, 503, "Unavailable", {} );
    await assert.rejects(
        () => tool.sendTTSRequest( { text: "t", voice_id: "v", model_id: "m", quality_profile: "q" } ),
        /HTTP 503/,
    );
} );

test( "sendTTSRequest wraps a fetch rejection", async () => {
    const { tool, ctrl } = await initedTool();
    ctrl.fetchImpl = async () => { throw new Error( "offline" ); };
    await assert.rejects(
        () => tool.sendTTSRequest( { text: "t", voice_id: "v", model_id: "m", quality_profile: "q" } ),
        /TTS request failed: offline/,
    );
} );

// ===========================================================================
// onTestComplete analysis branches
// ===========================================================================

test( "onTestComplete: duplicate + simultaneous issues are reported", async () => {
    const { tool } = await initedTool();
    tool.startTime = 500;
    tool.duplicateConnections = 2;
    tool.simultaneousPlayCount = 3;
    tool.onTestComplete();
    assert.equal( tool.isRunning, false );
} );

test( "onTestComplete: clean run + null startTime fallback", async () => {
    const { tool } = await initedTool();
    tool.startTime = null;                 // → ?? now() fallback
    tool.duplicateConnections = 0;
    tool.simultaneousPlayCount = 0;
    assert.doesNotThrow( () => tool.onTestComplete() );
} );

// ===========================================================================
// stopDiagnosticTest
// ===========================================================================

test( "stopDiagnosticTest closes open sockets + pauses playing audio, skips the rest", async () => {
    const { tool, ctrl } = await toolWithConnection();
    // Add a second, already-closed connection (readyState != OPEN → skip).
    const p2 = tool.createMonitoredWebSocket();
    const ws2 = ctrl.createdSockets.at( -1 )!;
    ws2.fireOpen();
    await p2;
    ws2.readyState = 3;  // closed → stop should NOT call close() on it

    // Two audio elements: one playing (gets paused), one already paused (skipped).
    await tool.simulateAudioPlayback( new Blob( [ "a" ] ), 1, "conn_0" );
    await tool.simulateAudioPlayback( new Blob( [ "b" ] ), 2, "conn_0" );
    const infos = Array.from( tool.audioElements.values() );
    ( infos[ 0 ]!.element as unknown as { paused: boolean } ).paused = false;  // playing

    tool.stopDiagnosticTest();

    const openWs = ctrl.createdSockets[ 0 ]!;
    assert.equal( openWs.closeCount, 1 );      // open one closed
    assert.equal( ws2.closeCount, 0 );          // closed one skipped
    assert.equal( ctrl.pausedSpy.length, 1 );   // only the playing one paused
    assert.equal( tool.isRunning, false );
} );

// ===========================================================================
// resetMetrics / list + status helpers / settings / log / clearLogs
// ===========================================================================

test( "resetMetrics clears state and re-seeds the lists", async () => {
    const { tool } = await toolWithConnection();
    tool.resetMetrics();
    assert.equal( tool.connections.size, 0 );
    assert.equal( tool.connectionCounter, 0 );
    assert.match( document.getElementById( "connection-list" )!.innerHTML, /No connections yet/ );
    assert.match( document.getElementById( "chunk-timeline" )!.innerHTML, /No audio activity yet/ );
} );

test( "updateConnectionInList updates an existing row and ignores a missing one", async () => {
    const { tool } = await initedTool();
    tool.addConnectionToList( "c1", "Connecting...", "active" );
    tool.updateConnectionInList( "c1", "Active", "active" );
    assert.match( document.getElementById( "conn-c1" )!.className, /active/ );
    assert.doesNotThrow( () => tool.updateConnectionInList( "nope", "x", "y" ) );  // missing → if(item) false
} );

test( "updateConnectionInList tolerates a row with no spans", async () => {
    const { tool } = await initedTool();
    const orphan = document.createElement( "div" );
    orphan.id = "conn-bare";
    document.getElementById( "connection-list" )!.appendChild( orphan );
    assert.doesNotThrow( () => tool.updateConnectionInList( "bare", "x", "y" ) );  // lastSpan null
} );

test( "getCurrentSettings reads values, and falls back to defaults when inputs are absent", async () => {
    const { tool } = await initedTool();
    const got = tool.getCurrentSettings();
    assert.equal( got.text, "hello world" );
    assert.equal( got.voice_id, "voiceX" );

    // Remove the inputs → default fallbacks.
    [ "test-text", "voice-select", "model-select", "profile-select" ].forEach( ( id ) => document.getElementById( id )!.remove() );
    const dflt = tool.getCurrentSettings();
    assert.equal( dflt.text, "" );
    assert.equal( dflt.voice_id, "21m00Tcm4TlvDq8ikWAM" );
    assert.equal( dflt.model_id, "eleven_flash_v2_5" );
    assert.equal( dflt.quality_profile, "balanced" );
} );

test( "updateStatus is a no-op for an unmapped element id", () => {
    const { tool } = newTool();   // statusElements not populated (no initialize)
    assert.doesNotThrow( () => tool.updateStatus( "session-id", "x" ) );
} );

test( "log no-ops without a console element, and writes + mirrors when present", async () => {
    const { tool, ctrl } = newTool();
    tool.log( "ignored" );                                  // logElement null → early return
    assert.equal( ctrl.consoleMsgs.length, 0 );

    const { tool: t2, ctrl: c2 } = await initedTool();
    const before = c2.consoleMsgs.length;
    t2.log( "hello", "success" );
    assert.equal( c2.consoleMsgs.length, before + 1 );
    assert.match( t2.logElement!.innerHTML, /hello/ );
} );

test( "clearLogs clears + reseeds when present, and is a no-op when absent", async () => {
    const { tool } = await initedTool();
    tool.clearLogs();
    assert.match( tool.logElement!.innerHTML, /Ready for new diagnostic tests/ );

    const { tool: t2 } = newTool();   // logElement null
    assert.doesNotThrow( () => t2.clearLogs() );
} );

// ===========================================================================
// boot.ts — wireDiagnostic
// ===========================================================================

function fakeTool(): { tool: WebSocketDiagnosticTool; calls: string[] } {
    const calls: string[] = [];
    const tool = {
        initialize         : async () => { calls.push( "init" ); },
        startDiagnosticTest : async () => { calls.push( "start" ); },
        stopDiagnosticTest  : () => { calls.push( "stop" ); },
        clearLogs           : () => { calls.push( "clear" ); },
    } as unknown as WebSocketDiagnosticTool;
    return { tool, calls };
}

test( "wireDiagnostic: globals no-op before DOMContentLoaded, delegate after", async () => {
    document.body.replaceChildren();
    const { tool, calls } = fakeTool();
    const target: Partial<DiagnosticWindow> = {};
    let made = 0;
    const { getTool } = wireDiagnostic( document, target, () => { made++; return tool; } );

    // Before the event: tool is null → guards short-circuit.
    assert.equal( getTool(), null );
    await target.startDiagnosticTest!();
    target.stopDiagnosticTest!();
    target.clearDiagnosticLogs!();
    assert.deepEqual( calls, [] );

    // Fire DOMContentLoaded → tool created + initialized.
    document.dispatchEvent( new Event( "DOMContentLoaded" ) );
    assert.equal( made, 1 );
    assert.equal( getTool(), tool );

    // After: delegators call through.
    await target.startDiagnosticTest!();
    target.stopDiagnosticTest!();
    target.clearDiagnosticLogs!();
    assert.deepEqual( calls, [ "init", "start", "stop", "clear" ] );
} );
