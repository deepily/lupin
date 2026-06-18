/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
/**
 * WebSocket Audio Diagnostic Tool — TypeScript port of the legacy
 * `websocket-diagnostic.js`.
 *
 * Pure diagnostic tool: analyses WebSocket connections + audio flow to surface
 * duplicate connections, simultaneous playback, chunk timing. Dev-only page.
 *
 * Design (mirrors the nav/multiplexer port convention): every non-deterministic
 * or external seam — the document, the clock, the WebSocket factory, fetch, the
 * object-URL helpers, the audio-element factory, and the connect-timeout timer —
 * is injected via {@link DiagnosticDeps}, so the whole class is deterministically
 * testable to c8 --100. The thin composition root in `boot.ts` binds these seams
 * to the real browser globals.
 *
 * APPROVED port-time bug-fix (Mr. Radio 2026-06-18, see createMonitoredWebSocket):
 * the legacy reassigned `websocket.onopen`/`onerror` to the connect-promise
 * resolve/reject AFTER installing the metrics handlers, leaving the metrics
 * `onopen`/`onerror` DEAD (activeConnections never incremented, "connected" never
 * logged). This port COMPOSES them — one handler updates metrics AND settles the
 * promise — preserving the observable promise contract EXACTLY (resolve-on-open /
 * reject-on-error) while reviving the previously-dead diagnostic metrics. This is
 * an APPROVED intentional deviation, not a parity regression.
 *
 * Ported: 2026-06-18 (Tiffany 💍). Additive — the legacy `.js` stays live until wired.
 */

// ===========================================================================
// Injected seams
// ===========================================================================

/** Minimal structural view of a WebSocket the tool drives. */
export interface WebSocketLike {
    onopen    : ( ( ev?: unknown ) => void ) | null;
    onclose   : ( ( ev: { code: number; reason: string } ) => void ) | null;
    onerror   : ( ( ev: unknown ) => void ) | null;
    onmessage : ( ( ev: { data: unknown } ) => void ) | null;
    readyState: number;
    close(): void;
}

/** Minimal structural view of the fetch Response the tool reads. */
export interface ResponseLike {
    ok        : boolean;
    status    : number;
    statusText: string;
    json(): Promise<unknown>;
}

/** `WebSocket.OPEN` — the readyState the stop-path checks before closing. */
export const WS_OPEN = 1;

/** All external/non-deterministic dependencies, injected for testability. */
export interface DiagnosticDeps {
    doc             : Document;
    host            : string;                                              // window.location.host
    now             : () => number;                                        // Date.now seam
    createWebSocket : ( url: string ) => WebSocketLike;                     // new WebSocket(url)
    fetchFn         : ( url: string, init?: unknown ) => Promise<ResponseLike>;
    createObjectURL : ( blob: Blob ) => string;
    revokeObjectURL : ( url: string ) => void;
    createAudio     : () => HTMLAudioElement;                              // doc.createElement("audio")
    setTimeoutFn    : ( cb: () => void, ms: number ) => unknown;           // connect-timeout timer
    consoleLog      : ( message: string ) => void;                         // console.log mirror
}

/** Settings read from the diagnostic page form. */
export interface DiagnosticSettings {
    text           : string;
    voice_id       : string;
    model_id       : string;
    quality_profile: string;
}

type LogType = "info" | "success" | "warning" | "error" | "diagnostic";

interface ConnectionInfo {
    id          : string;
    websocket   : WebSocketLike;
    state       : "connecting" | "active" | "closed";
    created     : number;
    url         : string;
    messages    : number;
    chunks      : number;
    connected?  : number;
    closed?     : number;
    closeCode?  : number;
    closeReason?: string;
}

interface ElementInfo {
    id          : string;
    element     : HTMLAudioElement;
    created     : number;
    sequence    : number;
    connectionId: string;
    size        : number;
    state       : "created" | "playing" | "ended" | "error" | "failed";
    playStarted?: number;
    playEnded?  : number;
    duration?   : number;
}

interface ChunkInfo {
    type        : "chunk";
    connectionId: string;
    size        : number;
    timestamp   : number;
    sequence    : number;
}

// ===========================================================================
// The tool
// ===========================================================================

export class WebSocketDiagnosticTool {
    private readonly deps: DiagnosticDeps;

    // Connection tracking
    sessionId            : string | null = null;
    readonly connections : Map<string, ConnectionInfo> = new Map();
    connectionCounter    = 0;
    activeConnections    = 0;
    duplicateConnections = 0;

    // Audio tracking
    chunksReceived       = 0;
    readonly audioElements: Map<string, ElementInfo> = new Map();
    audioElementCounter  = 0;
    simultaneousPlayCount = 0;
    chunkTimeline        : ChunkInfo[] = [];

    // Timing
    startTime            : number | null = null;
    firstAudioTime       : number | null = null;

    // State
    isRunning            = false;

    // UI elements
    logElement           : HTMLElement | null = null;
    statusElements       : Record<string, HTMLElement | null> = {};

    // Current connection handles
    currentWebSocket     : WebSocketLike | null = null;
    currentConnectionId  : string | null = null;

    constructor( deps: DiagnosticDeps ) {
        this.deps = deps;
    }

    async initialize(): Promise<void> {
        this.log( "🔧 Initializing WebSocket Diagnostic Tool", "diagnostic" );

        // Get UI elements
        this.logElement = this.deps.doc.getElementById( "diagnostic-console" );
        this.setupStatusElements();

        // Get session ID
        await this.getSessionId();

        this.log( "✅ WebSocket Diagnostic Tool initialized successfully", "success" );
        this.updateStatus( "session-id", this.sessionId ?? "" );
    }

    setupStatusElements(): void {
        const doc = this.deps.doc;
        this.statusElements = {
            "session-id"           : doc.getElementById( "session-id" ),
            "active-connections"   : doc.getElementById( "active-connections" ),
            "total-connections"    : doc.getElementById( "total-connections" ),
            "duplicate-connections": doc.getElementById( "duplicate-connections" ),
            "chunks-received"      : doc.getElementById( "chunks-received" ),
            "audio-elements"       : doc.getElementById( "audio-elements" ),
            "simultaneous-play"    : doc.getElementById( "simultaneous-play" ),
            "first-audio-latency"  : doc.getElementById( "first-audio-latency" ),
        };
    }

    async getSessionId(): Promise<void> {
        try {
            const response = await this.deps.fetchFn( "/api/get-session-id" );
            const data = ( await response.json() ) as { session_id: string };
            this.sessionId = data.session_id;
            this.log( `✅ Session ID obtained: ${this.sessionId}`, "success" );
        } catch ( error ) {
            this.log( `❌ Failed to get session ID: ${this.errMsg( error )}`, "error" );
            throw error;
        }
    }

    async startDiagnosticTest(): Promise<void> {
        if ( this.isRunning ) {
            this.log( "⚠️ Diagnostic test already running", "warning" );
            return;
        }

        const settings = this.getCurrentSettings();
        if ( !settings.text ) {
            this.log( "⚠️ Please enter text to test", "warning" );
            return;
        }

        try {
            this.log( "🔍 Starting diagnostic test...", "diagnostic" );
            this.log( `📝 Test text: "${settings.text}"`, "diagnostic" );
            this.log( `🎵 Voice: ${settings.voice_id}, Model: ${settings.model_id}, Profile: ${settings.quality_profile}`, "diagnostic" );

            // Reset metrics
            this.resetMetrics();
            this.isRunning = true;
            this.startTime = this.deps.now();

            // Create WebSocket connection with monitoring
            await this.createMonitoredWebSocket();

            // Send TTS request
            await this.sendTTSRequest( settings );

            // Enable stop button
            const testBtn = this.deps.doc.getElementById( "diagnostic-test-btn" ) as HTMLButtonElement | null;
            if ( testBtn ) {
                testBtn.disabled    = true;
                testBtn.textContent = "🔄 Running Diagnostic...";
            }
        } catch ( error ) {
            this.log( `❌ Diagnostic test failed: ${this.errMsg( error )}`, "error" );
            this.isRunning = false;
            this.enableTestButton();
        }
    }

    async createMonitoredWebSocket(): Promise<void> {
        const connectionId = `conn_${this.connectionCounter++}`;
        const wsUrl = `ws://${this.deps.host}/ws/audio/${encodeURIComponent( this.sessionId ?? "" )}`;

        this.log( `🔌 Creating WebSocket connection: ${connectionId}`, "diagnostic" );
        this.log( `📡 WebSocket URL: ${wsUrl}`, "diagnostic" );

        // Check for duplicate connections
        const existingActive = Array.from( this.connections.values() ).filter( ( conn ) => conn.state === "active" ).length;
        if ( existingActive > 0 ) {
            this.duplicateConnections++;
            this.log( `⚠️ DUPLICATE CONNECTION DETECTED! Already have ${existingActive} active connections`, "warning" );
            this.updateStatus( "duplicate-connections", this.duplicateConnections );
            this.addConnectionToList( connectionId, "DUPLICATE", "duplicate" );
        }

        const websocket = this.deps.createWebSocket( wsUrl );
        const connectionInfo: ConnectionInfo = {
            id        : connectionId,
            websocket,
            state     : "connecting",
            created   : this.deps.now(),
            url       : wsUrl,
            messages  : 0,
            chunks    : 0,
        };

        this.connections.set( connectionId, connectionInfo );
        this.updateConnectionMetrics();
        this.addConnectionToList( connectionId, "Connecting...", "active" );

        // Store reference
        this.currentWebSocket    = websocket;
        this.currentConnectionId = connectionId;

        // APPROVED port-time bug-fix (Mr. Radio 2026-06-18): the legacy installed
        // metrics handlers on onopen/onerror, then REASSIGNED onopen=resolve /
        // onerror=reject for this connect-promise — silently killing the metrics
        // handlers (activeConnections never incremented). Here we COMPOSE them:
        // each handler does its metrics work AND settles the promise via a one-shot
        // `settled` latch, preserving the EXACT promise contract (resolve-on-open /
        // reject-on-error / reject-on-timeout) while reviving the dead metrics.
        return new Promise<void>( ( resolve, reject ) => {
            let settled = false;

            this.deps.setTimeoutFn( () => {
                if ( !settled ) {
                    settled = true;
                    reject( new Error( "WebSocket connection timeout" ) );
                }
            }, 5000 );

            websocket.onopen = () => {
                connectionInfo.state     = "active";
                connectionInfo.connected = this.deps.now();
                this.activeConnections++;

                this.log( `✅ WebSocket connected: ${connectionId}`, "success" );
                this.updateConnectionMetrics();
                this.updateConnectionInList( connectionId, "Active", "active" );

                if ( !settled ) {
                    settled = true;
                    resolve();
                }
            };

            websocket.onclose = ( event ) => {
                connectionInfo.state       = "closed";
                connectionInfo.closed      = this.deps.now();
                connectionInfo.closeCode   = event.code;
                connectionInfo.closeReason = event.reason;
                this.activeConnections = Math.max( 0, this.activeConnections - 1 );

                this.log( `📡 WebSocket closed: ${connectionId} (code: ${event.code}, reason: ${event.reason})`, "info" );
                this.updateConnectionMetrics();
                this.updateConnectionInList( connectionId, `Closed (${event.code})`, "closed" );
            };

            websocket.onerror = ( error ) => {
                this.log( `❌ WebSocket error: ${connectionId} - ${String( error )}`, "error" );
                if ( !settled ) {
                    settled = true;
                    reject( new Error( `WebSocket error: ${connectionId}` ) );
                }
            };

            websocket.onmessage = ( event ) => {
                connectionInfo.messages++;
                this.handleDiagnosticMessage( event, connectionId );
            };
        } );
    }

    handleDiagnosticMessage( event: { data: unknown }, connectionId: string ): void {
        const connectionInfo = this.connections.get( connectionId )!;

        if ( event.data instanceof Blob ) {
            // Binary audio chunk
            connectionInfo.chunks++;
            this.chunksReceived++;

            const chunkInfo: ChunkInfo = {
                type        : "chunk",
                connectionId,
                size        : event.data.size,
                timestamp   : this.deps.now(),
                sequence    : this.chunksReceived,
            };

            this.log( `📦 Audio chunk received: ${connectionId} (size: ${event.data.size} bytes, seq: ${this.chunksReceived})`, "diagnostic" );

            // Record first audio timing
            if ( this.chunksReceived === 1 && this.startTime ) {
                this.firstAudioTime = this.deps.now();
                const latency = this.firstAudioTime - this.startTime;
                this.updateStatus( "first-audio-latency", `${latency}ms` );
                this.log( `🚀 First audio chunk in ${latency}ms`, latency < 500 ? "success" : "warning" );
            }

            this.chunkTimeline.push( chunkInfo );
            this.addToChunkTimeline( "received", `Chunk ${this.chunksReceived} (${event.data.size}b) from ${connectionId}` );
            this.updateStatus( "chunks-received", this.chunksReceived );

            // Simulate audio playback for monitoring (no actual sequencing)
            void this.simulateAudioPlayback( event.data, this.chunksReceived, connectionId );
        } else {
            // Text message (status update)
            try {
                const message = JSON.parse( String( event.data ) ) as { type?: string; text?: string };
                this.log( `📨 Status message from ${connectionId}: ${message.type} - ${message.text ?? "no text"}`, "info" );

                if ( message.type === "audio_streaming_complete" ) {
                    this.log( `🏁 Streaming complete from ${connectionId}`, "success" );
                    this.onTestComplete();
                }
            } catch {
                this.log( `📨 Non-JSON message from ${connectionId}: ${String( event.data )}`, "info" );
            }
        }
    }

    async simulateAudioPlayback( audioBlob: Blob, sequence: number, connectionId: string ): Promise<void> {
        // Create audio element for monitoring (mirrors original behaviour)
        const elementId = `audio_${this.audioElementCounter++}`;
        const audio = this.deps.createAudio();

        const elementInfo: ElementInfo = {
            id          : elementId,
            element     : audio,
            created     : this.deps.now(),
            sequence,
            connectionId,
            size        : audioBlob.size,
            state       : "created",
        };

        this.audioElements.set( elementId, elementInfo );
        this.updateStatus( "audio-elements", this.audioElements.size );

        // Monitor for simultaneous playback
        const currentlyPlaying = Array.from( this.audioElements.values() ).filter( ( el ) => el.state === "playing" ).length;
        if ( currentlyPlaying > 0 ) {
            this.simultaneousPlayCount++;
            this.log( `⚠️ SIMULTANEOUS PLAYBACK DETECTED! ${currentlyPlaying + 1} audio elements playing`, "warning" );
            this.updateStatus( "simultaneous-play", this.simultaneousPlayCount );
            this.addToChunkTimeline( "duplicate", `OVERLAP: ${elementId} while ${currentlyPlaying} others playing` );
        }

        // Set up audio element
        const audioUrl = this.deps.createObjectURL( audioBlob );
        audio.src           = audioUrl;
        audio.style.display = "none";
        this.deps.doc.body.appendChild( audio );

        // Monitor playback events
        audio.addEventListener( "play", () => {
            elementInfo.state       = "playing";
            elementInfo.playStarted = this.deps.now();
            this.log( `▶️ Audio playback started: ${elementId} (seq: ${sequence})`, "diagnostic" );
            this.addToChunkTimeline( "played", `Playing ${elementId} (seq: ${sequence}) from ${connectionId}` );

            // Check for overlaps
            const nowPlaying = Array.from( this.audioElements.values() ).filter( ( el ) => el.state === "playing" ).length;
            if ( nowPlaying > 1 ) {
                this.log( `🔄 OVERLAP: ${nowPlaying} audio elements now playing simultaneously`, "warning" );
            }
        } );

        audio.addEventListener( "ended", () => {
            elementInfo.state    = "ended";
            elementInfo.playEnded = this.deps.now();
            elementInfo.duration = elementInfo.playEnded - ( elementInfo.playStarted ?? elementInfo.playEnded );
            this.log( `⏹️ Audio playback ended: ${elementId} (duration: ${elementInfo.duration}ms)`, "diagnostic" );

            // Cleanup
            this.deps.revokeObjectURL( audioUrl );
            this.deps.doc.body.removeChild( audio );
        } );

        audio.addEventListener( "error", () => {
            elementInfo.state = "error";
            this.log( `❌ Audio playback error: ${elementId}`, "error" );
        } );

        // Attempt to play (mirrors original behaviour)
        try {
            const playPromise = audio.play();
            if ( playPromise !== undefined ) {
                await playPromise;
            }
        } catch ( error ) {
            elementInfo.state = "failed";
            if ( this.errName( error ) === "NotAllowedError" ) {
                this.log( `🔒 Autoplay prevented: ${elementId}`, "warning" );
            } else {
                this.log( `❌ Audio play failed: ${elementId} - ${this.errMsg( error )}`, "error" );
            }
        }
    }

    async sendTTSRequest( settings: DiagnosticSettings ): Promise<void> {
        try {
            this.log( "📡 Sending TTS request to ElevenLabs endpoint...", "diagnostic" );

            const requestBody = {
                session_id     : this.sessionId,
                text           : settings.text,
                voice_id       : settings.voice_id,
                model_id       : settings.model_id,
                quality_profile: settings.quality_profile,
            };

            this.log( `📤 Request body: ${JSON.stringify( requestBody, null, 2 )}`, "diagnostic" );

            const response = await this.deps.fetchFn( "/api/get-speech-elevenlabs", {
                method : "POST",
                headers: {
                    "Content-Type" : "application/json",
                    // Pre-existing dev-only token, preserved verbatim from the legacy tool.
                    "Authorization": "Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com",
                },
                body   : JSON.stringify( requestBody ),
            } );

            if ( !response.ok ) {
                throw new Error( `HTTP ${response.status}: ${response.statusText}` );
            }

            const responseData = await response.json();
            this.log( `📥 TTS request successful: ${JSON.stringify( responseData )}`, "success" );
            this.log( "⏳ Waiting for audio chunks via WebSocket...", "diagnostic" );
        } catch ( error ) {
            throw new Error( `TTS request failed: ${this.errMsg( error )}` );
        }
    }

    onTestComplete(): void {
        this.isRunning = false;
        const totalTime = this.deps.now() - ( this.startTime ?? this.deps.now() );

        this.log( `🏁 Diagnostic test complete - Total time: ${( totalTime / 1000 ).toFixed( 1 )}s`, "success" );
        this.log( "📊 Final Analysis:", "diagnostic" );
        this.log( `   - Total connections created: ${this.connectionCounter}`, "diagnostic" );
        this.log( `   - Active connections: ${this.activeConnections}`, "diagnostic" );
        this.log( `   - Duplicate connections: ${this.duplicateConnections}`, "diagnostic" );
        this.log( `   - Chunks received: ${this.chunksReceived}`, "diagnostic" );
        this.log( `   - Audio elements created: ${this.audioElements.size}`, "diagnostic" );
        this.log( `   - Simultaneous playback events: ${this.simultaneousPlayCount}`, "diagnostic" );

        // Analysis
        if ( this.duplicateConnections > 0 ) {
            this.log( "🔴 ROOT CAUSE DETECTED: Multiple WebSocket connections to same session", "error" );
        }

        if ( this.simultaneousPlayCount > 0 ) {
            this.log( "🟠 ISSUE DETECTED: Simultaneous audio playback (likely cause of duplication)", "warning" );
        }

        if ( this.duplicateConnections === 0 && this.simultaneousPlayCount === 0 ) {
            this.log( "🟢 No obvious connection or timing issues detected", "success" );
        }

        this.enableTestButton();
    }

    stopDiagnosticTest(): void {
        this.log( "⏹️ Stopping diagnostic test...", "diagnostic" );
        this.isRunning = false;

        // Close WebSocket connections
        this.connections.forEach( ( connectionInfo, connectionId ) => {
            if ( connectionInfo.websocket.readyState === WS_OPEN ) {
                this.log( `🔌 Closing WebSocket: ${connectionId}`, "diagnostic" );
                connectionInfo.websocket.close();
            }
        } );

        // Stop audio elements
        this.audioElements.forEach( ( elementInfo, elementId ) => {
            if ( !elementInfo.element.paused ) {
                this.log( `⏸️ Stopping audio element: ${elementId}`, "diagnostic" );
                elementInfo.element.pause();
            }
        } );

        this.enableTestButton();
    }

    resetMetrics(): void {
        this.connections.clear();
        this.audioElements.clear();
        this.chunkTimeline = [];
        this.connectionCounter = 0;
        this.audioElementCounter = 0;
        this.activeConnections = 0;
        this.duplicateConnections = 0;
        this.chunksReceived = 0;
        this.simultaneousPlayCount = 0;
        this.startTime = null;
        this.firstAudioTime = null;

        // Reset UI
        this.updateConnectionMetrics();
        this.updateStatus( "chunks-received", 0 );
        this.updateStatus( "audio-elements", 0 );
        this.updateStatus( "simultaneous-play", 0 );
        this.updateStatus( "first-audio-latency", "-" );

        // Clear lists
        const connList = this.deps.doc.getElementById( "connection-list" )!;
        connList.innerHTML = '<div style="color: #888; font-style: italic;">No connections yet...</div>';
        const timeline = this.deps.doc.getElementById( "chunk-timeline" )!;
        timeline.innerHTML = '<div style="color: #888; font-style: italic;">No audio activity yet...</div>';
    }

    updateConnectionMetrics(): void {
        this.updateStatus( "active-connections", this.activeConnections );
        this.updateStatus( "total-connections", this.connectionCounter );
        this.updateStatus( "duplicate-connections", this.duplicateConnections );
    }

    addConnectionToList( connectionId: string, status: string, cssClass: string ): void {
        const list = this.deps.doc.getElementById( "connection-list" )!;
        const item = this.deps.doc.createElement( "div" );
        item.className = `connection-item ${cssClass}`;
        item.id = `conn-${connectionId}`;
        item.innerHTML = `
            <span>${connectionId}</span>
            <span>${status}</span>
        `;
        list.appendChild( item );
        list.scrollTop = list.scrollHeight;
    }

    updateConnectionInList( connectionId: string, status: string, cssClass: string ): void {
        const item = this.deps.doc.getElementById( `conn-${connectionId}` );
        if ( item ) {
            item.className = `connection-item ${cssClass}`;
            const lastSpan = item.querySelector( "span:last-child" );
            if ( lastSpan ) lastSpan.textContent = status;
        }
    }

    addToChunkTimeline( type: string, message: string ): void {
        const timeline = this.deps.doc.getElementById( "chunk-timeline" )!;
        const entry = this.deps.doc.createElement( "div" );
        entry.className = `chunk-entry ${type}`;
        entry.innerHTML = `
            <span>${this.timeLabel()}</span>
            <span>${message}</span>
        `;
        timeline.appendChild( entry );
        timeline.scrollTop = timeline.scrollHeight;
    }

    enableTestButton(): void {
        const testBtn = this.deps.doc.getElementById( "diagnostic-test-btn" ) as HTMLButtonElement | null;
        if ( testBtn ) {
            testBtn.disabled    = false;
            testBtn.textContent = "🔍 Start Diagnostic Test";
        }
    }

    getCurrentSettings(): DiagnosticSettings {
        const doc = this.deps.doc;
        const textEl    = doc.getElementById( "test-text" ) as HTMLInputElement | null;
        const voiceEl   = doc.getElementById( "voice-select" ) as HTMLSelectElement | null;
        const modelEl   = doc.getElementById( "model-select" ) as HTMLSelectElement | null;
        const profileEl = doc.getElementById( "profile-select" ) as HTMLSelectElement | null;
        return {
            text           : textEl?.value.trim() ?? "",
            voice_id       : voiceEl?.value ?? "21m00Tcm4TlvDq8ikWAM",
            model_id       : modelEl?.value ?? "eleven_flash_v2_5",
            quality_profile: profileEl?.value ?? "balanced",
        };
    }

    updateStatus( elementId: string, value: string | number ): void {
        const element = this.statusElements[ elementId ];
        if ( element ) {
            element.textContent = String( value );
        }
    }

    log( message: string, type: LogType = "info" ): void {
        if ( !this.logElement ) return;

        const logEntry = this.deps.doc.createElement( "div" );
        logEntry.innerHTML = `<span class="timestamp">[${this.timeLabel()}]</span> <span class="${type}">${message}</span>`;

        this.logElement.appendChild( logEntry );
        this.logElement.scrollTop = this.logElement.scrollHeight;

        // Also mirror to the browser console
        this.deps.consoleLog( `[WebSocketDiagnostic] ${message}` );
    }

    clearLogs(): void {
        if ( this.logElement ) {
            this.logElement.innerHTML = "";
            this.log( "📝 Diagnostic console cleared", "diagnostic" );
            this.log( "🔍 Ready for new diagnostic tests", "info" );
        }
    }

    // ---------------------------------------------------------------------
    // Small internal helpers (typed-error extraction + timestamp label)
    // ---------------------------------------------------------------------

    private errMsg( error: unknown ): string {
        return error instanceof Error ? error.message : String( error );
    }

    private errName( error: unknown ): string {
        return error instanceof Error ? error.name : "";
    }

    private timeLabel(): string {
        return new Date( this.deps.now() ).toLocaleTimeString();
    }
    /* c8 ignore next */ // tsx phantom-branch artifact on the trailing class-close line.
}
