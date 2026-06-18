/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
/**
 * Composition root for the WebSocket diagnostic standalone bundle.
 *
 * Splits genuinely-untestable browser-global binding (`createBrowserDeps`, the
 * module-level kickoff) from the testable wiring logic (`wireDiagnostic` — the
 * DOMContentLoaded bootstrap + the global onclick delegators), so the wiring is
 * unit-tested to 100% with injected seams while only the thin browser glue is
 * c8-ignored (its bound behaviour is covered via the injected-deps unit tests).
 */
import { WebSocketDiagnosticTool } from "./websocketDiagnostic";
import type { DiagnosticDeps, WebSocketLike, ResponseLike } from "./websocketDiagnostic";

/* c8 ignore start */ // browser-binding seams: wrap real WebSocket/fetch/URL/Date/
// setTimeout globals; not meaningfully unit-testable. The bound behaviour is covered
// via the injected-deps unit tests in websocket_diagnostic_port.test.ts.
export function createBrowserDeps(): DiagnosticDeps {
    return {
        doc            : document,
        host           : window.location.host,
        now            : () => Date.now(),
        createWebSocket: ( url ) => new WebSocket( url ) as unknown as WebSocketLike,
        fetchFn        : ( url, init ) => fetch( url, init as RequestInit ) as unknown as Promise<ResponseLike>,
        createObjectURL: ( blob ) => URL.createObjectURL( blob ),
        revokeObjectURL: ( url ) => URL.revokeObjectURL( url ),
        createAudio    : () => document.createElement( "audio" ),
        setTimeoutFn   : ( cb, ms ) => setTimeout( cb, ms ),
        consoleLog     : ( msg ) => console.log( msg ),
    };
}
/* c8 ignore stop */

/** Window surface the diagnostic page's inline onclick handlers call. */
export interface DiagnosticWindow {
    startDiagnosticTest: () => Promise<void>;
    stopDiagnosticTest : () => void;
    clearDiagnosticLogs: () => void;
}

/**
 * Wire the DOMContentLoaded bootstrap + the global onclick handlers onto the
 * given doc/target using the provided tool factory. Pure (injected seams) so it
 * is unit-tested directly.
 */
export function wireDiagnostic(
    doc     : Document,
    target  : Partial<DiagnosticWindow>,
    makeTool: () => WebSocketDiagnosticTool,
): { getTool: () => WebSocketDiagnosticTool | null } {
    let tool: WebSocketDiagnosticTool | null = null;

    doc.addEventListener( "DOMContentLoaded", () => {
        tool = makeTool();
        void tool.initialize();
    } );

    target.startDiagnosticTest = async () => {
        if ( tool ) await tool.startDiagnosticTest();
    };
    target.stopDiagnosticTest = () => {
        if ( tool ) tool.stopDiagnosticTest();
    };
    target.clearDiagnosticLogs = () => {
        if ( tool ) tool.clearLogs();
    };

    return { getTool: () => tool };
}

/* c8 ignore start */ // module-level kickoff: binds real globals; behaviour covered via wireDiagnostic unit tests. The typeof-document guard lets this module be imported in a non-DOM (test) context without firing the side effect.
if ( typeof document !== "undefined" ) {
    wireDiagnostic(
        document,
        window as unknown as Partial<DiagnosticWindow>,
        () => new WebSocketDiagnosticTool( createBrowserDeps() ),
    );
}
/* c8 ignore stop */
