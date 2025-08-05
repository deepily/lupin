/**
 * Fresh Queue UI - Unified JavaScript Module
 * Single-file implementation to replace complex multi-file architecture
 * Handles WebSocket connections, authentication, Q&A, and TTS functionality
 */

class FreshQueueUI {
    constructor() {
        // Configuration
        this.debug = true;
        this.verbose = true;
        
        // WebSocket connections
        this.queueWS = null;
        this.audioWS = null;
        
        // Session management
        this.queueSessionId = null;
        this.audioSessionId = null;
        
        // Authentication
        this.currentUser = null;
        this.authToken = null;
        
        // Audio management
        this.audioContext = null;
        this.currentAudio = null;
        this.isPlaying = false;
        
        // HTML audio element for reliable mode (like original HybridTTS)
        this.audioElement = this.createAudioElement();
        
        // Sequential playback for instant mode (Chrome fix)
        this.sequentialQueue = [];
        this.isSequentialPlaying = false;
        this.currentSequentialAudio = null;
        this.sequentialChunksPlayed = 0;
        
        // First chunk timing for instant mode
        this.firstChunkStartTime = null;
        this.firstChunkPlayed = false;
        
        // State management
        this.isConnecting = false;
        this.connectionRetries = 0;
        this.maxRetries = 5;
        
        // Job completion debugging
        this.lastQASubmissionTime = null;
        this.lastQASubmissionText = null;
        
        // Notification state management
        this.notificationState = {
            apiKey: "claude_code_simple_key",
            userId: null, // Will be set from WebSocket auth
            notifications: [], // Local cache of notifications
            lastSync: null
        };
        
        // Event deduplication
        this.processedEvents = new Set();
        this.maxProcessedEvents = 100; // Prevent memory leaks
        
        // Storage keys
        this.QUEUE_SESSION_KEY = 'fresh_queue_session_id';
        this.AUDIO_SESSION_KEY = 'fresh_audio_session_id';
        this.USER_EMAIL_KEY = 'fresh_user_email';
        this.VERSION_KEY = 'fresh_queue_version';
        this.CURRENT_VERSION = '1.1.1'; // Increment to invalidate old cache
        
        // Initialize
        this.init();
    }
    
    // ========================================
    // INITIALIZATION
    // ========================================
    
    async init() {
        this.log( "FreshQueueUI initializing..." );
        
        try {
            // Check and clear old cache if needed
            this.validateCache();
            
            // Setup user and authentication
            await this.setupAuthentication();
            
            // Create audio context
            await this.createAudioContext();
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Connect WebSockets
            await this.connectWebSockets();
            
            this.log( "FreshQueueUI initialization complete" );
            
        } catch ( error ) {
            this.error( "Initialization failed:", error );
            this.updateStatus( "auth-status", "Initialization failed", "error" );
        }
    }
    
    validateCache() {
        const storedVersion = localStorage.getItem( this.VERSION_KEY );
        
        // Always check for malformed session IDs first
        const queueSession = localStorage.getItem( this.QUEUE_SESSION_KEY );
        const audioSession = localStorage.getItem( this.AUDIO_SESSION_KEY );
        
        let foundMalformed = false;
        
        if ( queueSession && ( queueSession.startsWith('{') || queueSession.includes('timestamp') ) ) {
            this.log( "Detected malformed queue session ID - clearing" );
            localStorage.removeItem( this.QUEUE_SESSION_KEY );
            foundMalformed = true;
        }
        
        if ( audioSession && ( audioSession.startsWith('{') || audioSession.includes('timestamp') ) ) {
            this.log( "Detected malformed audio session ID - clearing" );
            localStorage.removeItem( this.AUDIO_SESSION_KEY );
            foundMalformed = true;
        }
        
        if ( storedVersion !== this.CURRENT_VERSION ) {
            this.log( `Cache version mismatch (stored: ${storedVersion}, current: ${this.CURRENT_VERSION}) - clearing cache` );
            
            // Clear all cached data
            localStorage.removeItem( this.QUEUE_SESSION_KEY );
            localStorage.removeItem( this.AUDIO_SESSION_KEY );
            localStorage.removeItem( this.USER_EMAIL_KEY );
            
            // Update version
            localStorage.setItem( this.VERSION_KEY, this.CURRENT_VERSION );
            
            this.log( "Cache cleared and version updated" );
        } else if ( foundMalformed ) {
            this.log( "Malformed session IDs cleared, version still valid" );
        } else {
            this.log( `Cache version valid: ${this.CURRENT_VERSION}` );
        }
    }
    
    async setupAuthentication() {
        // Get or create user email (mock system)
        let userEmail = localStorage.getItem( this.USER_EMAIL_KEY );
        
        if ( !userEmail || userEmail === 'null' || userEmail === 'undefined' ) {
            // Use actual user email instead of generating random ones
            userEmail = "ricardo.felipe.ruiz@gmail.com";
            
            localStorage.setItem( this.USER_EMAIL_KEY, userEmail );
            this.log( `Set user email: ${userEmail}` );
        }
        
        this.currentUser = userEmail;
        this.authToken = `Bearer mock_token_email_${userEmail}`;
        
        // Update UI
        this.updateElement( "user-display", userEmail );
        this.log( `Authentication setup complete for user: ${userEmail}` );
    }
    
    createAudioElement() {
        const audio = document.createElement( 'audio' );
        audio.controls = false; // Hidden for UI cleanliness
        audio.style.display = 'none';
        document.body.appendChild( audio );
        
        // Add error handler (adapted from original HybridTTS)
        audio.addEventListener( 'error', ( e ) => {
            this.error( "HTML audio element error:", e );
            this.isPlaying = false;
        });
        
        return audio;
    }
    
    async createAudioContext() {
        try {
            if ( window.AudioContext || window.webkitAudioContext ) {
                this.audioContext = new ( window.AudioContext || window.webkitAudioContext )();
                this.log( "AudioContext created successfully" );
            } else {
                this.error( "AudioContext not supported in this browser" );
            }
        } catch ( error ) {
            this.error( "Failed to create AudioContext:", error );
        }
    }
    
    setupEventListeners() {
        // Direct TTS test (bypass Q&A)
        document.getElementById( 'direct-tts-button' ).addEventListener( 'click', () => {
            this.directTTSTest();
        });
        
        // Q&A submission
        document.getElementById( 'submit-qa' ).addEventListener( 'click', () => {
            this.submitQA();
        });
        
        // Test buttons
        document.getElementById( 'test-instant-tts' ).addEventListener( 'click', () => {
            this.testTTS( 'instant' );
        });
        
        document.getElementById( 'test-reliable-tts' ).addEventListener( 'click', () => {
            this.testTTS( 'reliable' );
        });
        
        document.getElementById( 'stop-audio' ).addEventListener( 'click', () => {
            this.stopAudio();
        });
        
        // Enter key in textarea
        document.getElementById( 'qa-input' ).addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' && ( e.ctrlKey || e.metaKey ) ) {
                this.submitQA();
            }
        });
        
        this.log( "Event listeners setup complete" );
    }
    
    // ========================================
    // SESSION MANAGEMENT
    // ========================================
    
    async getOrCreateSessionId( sessionType ) {
        const storageKey = sessionType === 'audio' ? this.AUDIO_SESSION_KEY : this.QUEUE_SESSION_KEY;
        
        // Check localStorage first
        let storedSessionId = localStorage.getItem( storageKey );
        
        if ( storedSessionId && storedSessionId !== 'undefined' && storedSessionId !== 'null' ) {
            this.log( `[SESSION] Reusing ${sessionType} session: ${storedSessionId}` );
            return storedSessionId;
        }
        
        // Generate new session ID
        try {
            const response = await fetch( '/api/get-session-id', {
                method: 'GET',
                headers: {
                    'Authorization': this.authToken
                }
            });
            
            if ( response.ok ) {
                const data = await response.json();
                const sessionId = data.session_id;
                
                if ( !sessionId ) {
                    throw new Error( 'Session ID not found in response' );
                }
                
                localStorage.setItem( storageKey, sessionId );
                this.log( `[SESSION] Generated new ${sessionType} session: ${sessionId}` );
                return sessionId;
            } else {
                throw new Error( `HTTP ${response.status}: ${response.statusText}` );
            }
            
        } catch ( error ) {
            this.error( `Failed to get session ID for ${sessionType}:`, error );
            
            // Generate fallback session ID
            const fallbackId = this.generateFallbackSessionId();
            localStorage.setItem( storageKey, fallbackId );
            this.log( `[SESSION] Using fallback ${sessionType} session: ${fallbackId}` );
            return fallbackId;
        }
    }
    
    generateFallbackSessionId() {
        const adjectives = [ 'wise', 'clever', 'swift', 'bright', 'keen', 'bold', 'calm', 'cool', 'fair', 'fine' ];
        const animals = [ 'penguin', 'dolphin', 'eagle', 'tiger', 'wolf', 'bear', 'lion', 'hawk', 'fox', 'owl' ];
        
        const adj = adjectives[ Math.floor( Math.random() * adjectives.length ) ];
        const animal = animals[ Math.floor( Math.random() * animals.length ) ];
        
        return `${adj}_${animal}`;
    }
    
    // ========================================
    // WEBSOCKET CONNECTIONS
    // ========================================
    
    async connectWebSockets() {
        this.log( "Connecting WebSockets..." );
        
        try {
            // Get session IDs
            this.queueSessionId = await this.getOrCreateSessionId( 'queue' );
            this.audioSessionId = await this.getOrCreateSessionId( 'audio' );
            
            // Update UI with session IDs
            this.updateElement( "queue-session", this.queueSessionId );
            this.updateElement( "audio-session", this.audioSessionId );
            
            // Connect both WebSockets
            await Promise.all([
                this.connectQueueWebSocket(),
                this.connectAudioWebSocket()
            ]);
            
            this.log( "Both WebSockets connected successfully" );
            
        } catch ( error ) {
            this.error( "WebSocket connection failed:", error );
            this.scheduleReconnect();
        }
    }
    
    async connectQueueWebSocket() {
        return new Promise( ( resolve, reject ) => {
            try {
                const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
                const wsUrl = `${protocol}//${window.location.host}/ws/queue/${this.queueSessionId}`;
                
                this.log( `Connecting to queue WebSocket: ${wsUrl}` );
                this.queueWS = new WebSocket( wsUrl );
                
                this.queueWS.onopen = () => {
                    this.log( "Queue WebSocket connected" );
                    this.updateStatus( "queue-ws-status", "Connected", "good" );
                    this.authenticateQueueWebSocket();
                };
                
                this.queueWS.onmessage = ( event ) => {
                    this.handleQueueMessage( event );
                };
                
                this.queueWS.onclose = ( event ) => {
                    this.log( `Queue WebSocket closed: ${event.code} ${event.reason}` );
                    this.updateStatus( "queue-ws-status", "Disconnected", "error" );
                    this.scheduleReconnect();
                };
                
                this.queueWS.onerror = ( error ) => {
                    this.error( "Queue WebSocket error:", error );
                    this.updateStatus( "queue-ws-status", "Error", "error" );
                    reject( error );
                };
                
                // Resolve when connection is established
                this.queueWS.addEventListener( 'open', resolve, { once: true } );
                
                // Set timeout for connection
                setTimeout( () => {
                    if ( this.queueWS.readyState !== WebSocket.OPEN ) {
                        reject( new Error( "Queue WebSocket connection timeout" ) );
                    }
                }, 10000 );
                
            } catch ( error ) {
                reject( error );
            }
        });
    }
    
    async connectAudioWebSocket() {
        return new Promise( ( resolve, reject ) => {
            try {
                const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
                const wsUrl = `${protocol}//${window.location.host}/ws/audio/${this.audioSessionId}`;
                
                this.log( `Connecting to audio WebSocket: ${wsUrl}` );
                this.audioWS = new WebSocket( wsUrl );
                
                this.audioWS.onopen = () => {
                    this.log( "Audio WebSocket connected" );
                    this.updateStatus( "audio-ws-status", "Connected", "good" );
                    this.authenticateAudioWebSocket();
                };
                
                this.audioWS.onmessage = ( event ) => {
                    this.handleAudioMessage( event );
                };
                
                this.audioWS.onclose = ( event ) => {
                    this.log( `Audio WebSocket closed: ${event.code} ${event.reason}` );
                    this.updateStatus( "audio-ws-status", "Disconnected", "error" );
                    this.scheduleReconnect();
                };
                
                this.audioWS.onerror = ( error ) => {
                    this.error( "Audio WebSocket error:", error );
                    this.updateStatus( "audio-ws-status", "Error", "error" );
                    reject( error );
                };
                
                // Resolve when connection is established
                this.audioWS.addEventListener( 'open', resolve, { once: true } );
                
                // Set timeout for connection
                setTimeout( () => {
                    if ( this.audioWS.readyState !== WebSocket.OPEN ) {
                        reject( new Error( "Audio WebSocket connection timeout" ) );
                    }
                }, 10000 );
                
            } catch ( error ) {
                reject( error );
            }
        });
    }
    
    authenticateQueueWebSocket() {
        const authMessage = {
            type: "auth_request",
            token: this.authToken.replace( "Bearer ", "" ), // Strip Bearer prefix for WebSocket auth
            session_id: this.queueSessionId,
            subscribed_events: [
                "queue_todo_update",
                "queue_running_update", 
                "queue_done_update",
                "queue_dead_update",
                "tts_job_request",
                "sys_time_update",
                "notification_play_sound",
                "notification_message_user",
                "notification_queue_update",
                "auth_success",
                "auth_error", 
                "connect",
                "sys_ping"
            ]
        };
        
        this.queueWS.send( JSON.stringify( authMessage ) );
        this.log( "Queue WebSocket authentication sent" );
    }
    
    authenticateAudioWebSocket() {
        const authMessage = {
            type: "auth_request",
            token: this.authToken.replace( "Bearer ", "" ), // Strip Bearer prefix for WebSocket auth
            session_id: this.audioSessionId,
            subscribed_events: [
                "audio_streaming_chunk",
                "audio_streaming_status", 
                "audio_streaming_complete",
                "sys_ping",
                "auth_success",
                "auth_error",
                "connect"
            ]
        };
        
        this.audioWS.send( JSON.stringify( authMessage ) );
        this.log( "Audio WebSocket authentication sent" );
    }
    
    // ========================================
    // MESSAGE HANDLERS
    // ========================================
    
    handleQueueMessage( event ) {
        try {
            // Server uses event envelope pattern: envelope.data contains actual payload
            const envelope = JSON.parse( event.data );
            this.log( `[QUEUE WS] Received: ${envelope.type}`, envelope );
            
            switch ( envelope.type ) {
                case "auth_success":
                    this.log( `Queue WebSocket authenticated for user: ${envelope.user_id}` );
                    this.updateStatus( "auth-status", `Authenticated as ${envelope.user_id}`, "good" );
                    
                    // Store the server-provided user ID for notifications
                    this.notificationState.userId = envelope.user_id;
                    this.log( `Notification state updated with server user ID: ${envelope.user_id}` );
                    
                    // Load initial data now that we have the correct user ID
                    this.loadInitialData();
                    break;
                    
                case "auth_error":
                    this.error( `Queue WebSocket auth failed: ${envelope.message}` );
                    this.updateStatus( "auth-status", `Auth failed: ${envelope.message}`, "error" );
                    break;
                    
                case "connect":
                    this.log( `Queue WebSocket connected: ${envelope.message}` );
                    break;
                    
                case "tts_job_request":
                    // 🔍 DEBUGGING: Log raw WebSocket event before processing
                    this.log( "🔍 [WEBSOCKET-DEBUG] Raw tts_job_request received:", JSON.stringify( envelope, null, 2 ) );
                    this.handleJobCompletion( envelope );
                    break;
                    
                case "queue_todo_update":
                    this.log( `Queue TODO update: ${envelope.value}` );
                    this.updateQueueLists( "todo" );
                    break;
                    
                case "queue_running_update":
                    this.log( `Queue RUNNING update: ${envelope.value}` );
                    this.updateQueueLists( "run" );
                    break;
                    
                case "queue_done_update":
                    this.log( `Queue DONE update: ${envelope.value}` );
                    this.updateQueueLists( "done" );
                    break;
                    
                case "queue_dead_update":
                    this.log( `Queue DEAD update: ${envelope.value}` );
                    this.updateQueueLists( "dead" );
                    break;
                    
                case "notification_message_user":
                    this.handleUserNotification( envelope );
                    break;
                    
                case "notification_queue_update":
                    this.handleNotificationUpdate( envelope );
                    break;
                    
                case "sys_time_update":
                    // Update clock display with server time
                    if ( envelope.date ) {
                        this.updateElement( "clock", envelope.date );
                        this.log( `Clock updated: ${envelope.date}` );
                    }
                    break;
                    
                case "sys_ping":
                    this.handlePing( "queue" );
                    break;
                    
                default:
                    this.log( `[QUEUE WS] Unhandled message type: ${envelope.type}` );
            }
            
        } catch ( error ) {
            this.error( "Failed to parse queue WebSocket message:", error );
        }
    }
    
    handleAudioMessage( event ) {
        // Handle both text and binary messages
        if ( event.data instanceof Blob ) {
            this.handleAudioChunk( event.data );
            return;
        }
        
        try {
            // Server uses event envelope pattern: envelope.data contains actual payload
            const envelope = JSON.parse( event.data );
            this.log( `[AUDIO WS] Received: ${envelope.type}`, envelope );
            
            switch ( envelope.type ) {
                case "auth_success":
                    this.log( `Audio WebSocket authenticated for user: ${envelope.user_id}` );
                    break;
                    
                case "auth_error":
                    this.error( `Audio WebSocket auth failed: ${envelope.message}` );
                    break;
                    
                case "connect":
                    this.log( `Audio WebSocket connected: ${envelope.message}` );
                    break;
                    
                case "audio_streaming_status":
                    this.handleAudioStatus( envelope );
                    break;
                    
                case "audio_streaming_complete":
                    this.handleAudioComplete( envelope );
                    break;
                    
                case "sys_ping":
                    this.handlePing( "audio" );
                    break;
                    
                default:
                    this.log( `[AUDIO WS] Unhandled message type: ${envelope.type}` );
            }
            
        } catch ( error ) {
            this.error( "Failed to parse audio WebSocket message:", error );
        }
    }
    
    handlePing( connectionType ) {
        const ws = connectionType === "queue" ? this.queueWS : this.audioWS;
        
        if ( ws && ws.readyState === WebSocket.OPEN ) {
            const pongMessage = {
                type: "sys_pong",
                timestamp: new Date().toISOString()
            };
            ws.send( JSON.stringify( pongMessage ) );
        }
    }
    
    // ========================================
    // Q&A FUNCTIONALITY
    // ========================================
    
    async submitQA() {
        const inputElement = document.getElementById( 'qa-input' );
        const submitButton = document.getElementById( 'submit-qa' );
        const loadingSpinner = document.getElementById( 'submit-loading' );
        
        const text = inputElement.value.trim();
        
        if ( !text ) {
            this.error( "Please enter some text to submit" );
            return;
        }
        
        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            this.updateElement( "response-text", "Submitting Q&A..." );
            
            this.log( `Submitting Q&A: ${text}` );
            
            // Track for job completion debugging
            this.lastQASubmissionTime = Date.now();
            this.lastQASubmissionText = text;
            
            // Submit to /api/push endpoint (GET request with query parameters)
            const url = `/api/push?question=${encodeURIComponent(text)}&websocket_id=${this.queueSessionId}`;
            const response = await fetch( url, {
                method: 'GET',
                headers: {
                    'Authorization': this.authToken,
                    'X-Session-ID': this.queueSessionId
                }
            });
            
            if ( !response.ok ) {
                throw new Error( `HTTP ${response.status}: ${response.statusText}` );
            }
            
            const responseData = await response.json();
            this.log( "Q&A submitted successfully:", responseData );
            
            // Update response area
            this.updateElement( "response-text", JSON.stringify( responseData, null, 2 ) );
            
            // Clear input
            inputElement.value = '';
            
        } catch ( error ) {
            this.error( "Q&A submission failed:", error );
            this.updateElement( "response-text", `Error: ${error.message}` );
            
        } finally {
            // Reset UI
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }
    
    handleJobCompletion( envelope ) {
        // Add event deduplication to prevent duplicate processing
        const eventId = `${envelope.type}_${envelope.timestamp}`;
        
        if ( this.processedEvents.has( eventId ) ) {
            this.log( `Skipping duplicate event: ${eventId}` );
            return;
        }
        
        // Add to processed events with cleanup
        this.processedEvents.add( eventId );
        
        // Clean up old events if set gets too large
        if ( this.processedEvents.size > this.maxProcessedEvents ) {
            const eventsArray = Array.from( this.processedEvents );
            const keepEvents = eventsArray.slice( -this.maxProcessedEvents + 10 ); // Keep most recent
            this.processedEvents = new Set( keepEvents );
            this.log( `Cleaned up processed events cache, kept ${keepEvents.length} recent events` );
        }
        
        // 🔍 ENHANCED DEBUGGING: Comprehensive envelope object analysis
        this.log( "🔍 [JOB-COMPLETION-DEBUG] === JOB COMPLETION RECEIVED ===" );
        this.log( "🔍 [JOB-COMPLETION-DEBUG] Full envelope object:", JSON.stringify( envelope, null, 2 ) );
        this.log( "🔍 [JOB-COMPLETION-DEBUG] envelope.text type:", typeof envelope.text );
        this.log( "🔍 [JOB-COMPLETION-DEBUG] envelope.text value:", envelope.text );
        this.log( "🔍 [JOB-COMPLETION-DEBUG] envelope.text length:", envelope.text?.length || 'N/A' );
        this.log( "🔍 [JOB-COMPLETION-DEBUG] Available fields:", Object.keys( envelope ) );
        
        // 🔍 DEBUGGING: Calculate timing from Q&A submission
        const timeSinceSubmission = this.lastQASubmissionTime ? ( Date.now() - this.lastQASubmissionTime ) / 1000 : 'N/A';
        this.log( "🔍 [JOB-COMPLETION-DEBUG] Time since Q&A submission:", timeSinceSubmission + 's' );
        this.log( "🔍 [JOB-COMPLETION-DEBUG] Original Q&A text:", this.lastQASubmissionText );
        
        // 🔍 DEBUGGING: Current TTS mode context
        const mode = document.getElementById( 'tts-mode' ).value;
        this.log( "🔍 [JOB-COMPLETION-DEBUG] Current TTS mode:", mode );
        
        // 🚨 CRITICAL: Detect when fallback will be triggered (check both locations)
        const hasDirectText = envelope.text && envelope.text.trim() !== '';
        const hasNestedText = envelope.data?.text && envelope.data.text.trim() !== '';
        const willUseFallback = !hasDirectText && !hasNestedText;
        
        if ( willUseFallback ) {
            this.error( "🚨 [FALLBACK-TRIGGERED] Job completed with no/empty text!" );
            this.error( "🚨 [FALLBACK-TRIGGERED] This will play 'Job completed' instead of actual response" );
            this.error( "🚨 [FALLBACK-TRIGGERED] envelope.text:", envelope.text );
            this.error( "🚨 [FALLBACK-TRIGGERED] envelope.data.text:", envelope.data?.text );
            this.error( "🚨 [FALLBACK-TRIGGERED] Full envelope object:", envelope );
            this.error( "🚨 [FALLBACK-TRIGGERED] Expected Q&A response for:", this.lastQASubmissionText );
        } else {
            const textLocation = hasDirectText ? 'envelope.text' : 'envelope.data.text';
            this.log( `✅ [JOB-COMPLETION-DEBUG] Text found at ${textLocation}, will use actual response` );
        }
        
        this.log( "Job completion received:", envelope );
        
        // 🔧 Server uses event envelope pattern: envelope.data contains actual payload
        // The nested structure (envelope.data.text) is intentional server architecture  
        // Event envelope pattern: {type, timestamp, data: {actual_payload}}
        const actualText = envelope.data?.text || envelope.text; // Try nested first, fallback to direct
        
        // 🔍 DEBUGGING: Confirm we're extracting the right text
        if ( envelope.data?.text && !envelope.text ) {
            this.log( "✅ [ENVELOPE-PATTERN] Found text in nested location: envelope.data.text" );
        } else if ( envelope.text && !envelope.data?.text ) {
            this.log( "⚠️ [ENVELOPE-PATTERN] Found text in direct location: envelope.text (unusual)" );
        } else if ( !actualText ) {
            this.error( "❌ [ENVELOPE-PATTERN] No text found in either envelope.text or envelope.data.text" );
        }
        
        // Update response area with job completion
        this.updateElement( "response-text", `Job completed: ${actualText || 'No text provided'}` );
        
        // Play TTS audio based on current mode
        this.playTTS( actualText || "Job completed", mode );
    }
    
    // ========================================
    // TTS FUNCTIONALITY
    // ========================================
    
    async directTTSTest() {
        const inputElement = document.getElementById( 'direct-tts-input' );
        const text = inputElement.value.trim();
        
        if ( !text ) {
            this.error( "Please enter text to speak" );
            return;
        }
        
        // Get current TTS mode
        const mode = document.getElementById( 'tts-mode' ).value;
        
        this.log( `🔊 Direct TTS Test: "${text}" in ${mode} mode (bypassing Q&A)` );
        
        // 🔍 DEBUGGING: Mark this as direct TTS (not Q&A submission)
        this.log( "🔍 [DIRECT-TTS-DEBUG] This is a direct TTS test, NOT a Q&A submission" );
        this.log( "🔍 [DIRECT-TTS-DEBUG] Should NOT trigger handleJobCompletion" );
        
        // Call TTS directly - no Q&A, no job completion, no WebSocket events
        await this.playTTS( text, mode );
        
        // Clear input after successful test
        inputElement.value = '';
    }
    
    async testTTS( mode ) {
        const testText = "This is a test of the text-to-speech system in " + mode + " mode.";
        this.log( `Testing TTS in ${mode} mode: ${testText}` );
        
        await this.playTTS( testText, mode );
    }
    
    async playTTS( text, mode ) {
        this.log( `Playing TTS: "${text}" in ${mode} mode` );
        
        try {
            if ( mode === 'instant' ) {
                await this.playInstantTTS( text );
            } else {
                await this.playReliableTTS( text );
            }
        } catch ( error ) {
            this.error( `TTS playback failed in ${mode} mode:`, error );
        }
    }
    
    async playInstantTTS( text ) {
        this.log( "Starting instant TTS (11labs streaming)..." );
        
        try {
            // Request TTS via 11labs streaming endpoint
            const response = await fetch( '/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.authToken,
                    'X-Session-ID': this.audioSessionId
                },
                body: JSON.stringify({
                    text: text,
                    voice: 'default',
                    session_id: this.audioSessionId  // Ensure session_id is included
                })
            });
            
            if ( !response.ok ) {
                throw new Error( `HTTP ${response.status}: ${response.statusText}` );
            }
            
            const result = await response.json();
            this.log( "Instant TTS request successful:", result );
            
            // Audio chunks will be received via WebSocket
            this.currentTTSMode = 'instant';
            this.audioChunks = [];
            this.audioSources = [];
            this.startTime = Date.now(); // Track timing for both modes
            
        } catch ( error ) {
            this.error( "Instant TTS request failed:", error );
            throw error;
        }
    }
    
    async playReliableTTS( text ) {
        this.log( "Starting reliable TTS (OpenAI batch)..." );
        
        try {
            // Request TTS via OpenAI batch endpoint
            const response = await fetch( '/api/get-speech', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.authToken
                },
                body: JSON.stringify({
                    text: text,
                    voice: 'default',
                    session_id: this.audioSessionId  // Add missing session_id
                })
            });
            
            if ( !response.ok ) {
                throw new Error( `HTTP ${response.status}: ${response.statusText}` );
            }
            
            // Parse JSON response (should confirm TTS generation started)
            const result = await response.json();
            this.log( "Reliable TTS request successful:", result );
            
            if ( result.status !== 'success' ) {
                throw new Error( `TTS generation failed: ${result.message || 'Unknown error'}` );
            }
            
            // Audio chunks will be received via WebSocket (same as instant mode)
            this.currentTTSMode = 'reliable';
            this.audioChunks = [];
            this.audioSources = [];
            this.startTime = Date.now(); // Track timing for reliable mode
            
        } catch ( error ) {
            this.error( "Reliable TTS request failed:", error );
            throw error;
        }
    }
    
    handleAudioStatus( envelope ) {
        this.log( `Audio status: ${envelope.status || envelope.text}` );
        // Future: update UI with loading status
    }
    
    handleAudioChunk( blobData ) {
        if ( this.debug ) this.log( `Received audio chunk: ${blobData.size} bytes` );
        
        if ( this.currentTTSMode === 'instant' ) {
            // Use sequential queue for Chrome compatibility
            this.playChunkSequential( blobData );
        } else {
            // Collect chunks for later playback
            this.audioChunks = this.audioChunks || [];
            this.audioChunks.push( blobData );
        }
    }
    
    handleAudioComplete( data ) {
        const collectedChunks = this.audioChunks ? this.audioChunks.length : 0;
        const processedChunks = this.processedChunks || 0;
        const sequentialPlayed = this.sequentialChunksPlayed || 0;
        
        if ( this.currentTTSMode === 'instant' ) {
            // For instant mode, show sequential chunks played
            this.log( `Audio streaming complete: ${data.chunks || 0} server chunks, ${sequentialPlayed} sequential chunks played, ${data.duration || 0}s` );
        } else {
            this.log( `Audio streaming complete: ${data.chunks || 0} server chunks, ${collectedChunks} collected chunks, ${data.duration || 0}s` );
        }
        
        if ( this.currentTTSMode === 'reliable' && this.audioChunks && this.audioChunks.length > 0 ) {
            // Use proven reliable mode playback (adapted from original HybridTTS)
            this.playCollectedAudio();
        }
        
        // Clean up
        this.currentTTSMode = null;
        this.processedChunks = 0;
        this.sequentialChunksPlayed = 0;
        
        // Reset first chunk timing for next request
        this.firstChunkStartTime = null;
        this.firstChunkPlayed = false;
    }
    
    // ========================================
    // SEQUENTIAL PLAYBACK FOR INSTANT MODE (Chrome fix)
    // ========================================
    
    playChunkSequential( blobData ) {
        // Skip chunks that are too small (likely metadata/headers)
        if ( blobData.size < 100 ) {
            if ( this.debug ) this.log( `Skipping small sequential chunk: ${blobData.size} bytes` );
            return;
        }
        
        // Track first chunk arrival time
        if ( !this.firstChunkPlayed && !this.firstChunkStartTime ) {
            this.firstChunkStartTime = Date.now();
        }
        
        // Add to queue
        this.sequentialQueue.push( blobData );
        
        if ( this.debug ) this.log( `Added chunk to sequential queue (${this.sequentialQueue.length} total)` );
        
        // Start playing if not already playing
        if ( !this.isSequentialPlaying ) {
            this.playNextSequentialChunk();
        }
    }
    
    playNextSequentialChunk() {
        // Check if queue is empty
        if ( this.sequentialQueue.length === 0 ) {
            this.isSequentialPlaying = false;
            this.currentSequentialAudio = null;
            
            if ( this.debug ) this.log( `Sequential queue empty, ${this.sequentialChunksPlayed} chunks played total` );
            
            // Update processed chunks counter for stats
            this.processedChunks = this.sequentialChunksPlayed;
            return;
        }
        
        // Get next chunk from queue
        const nextChunk = this.sequentialQueue.shift();
        this.sequentialChunksPlayed++;
        
        if ( this.debug ) this.log( `Playing sequential chunk ${this.sequentialChunksPlayed} (${this.sequentialQueue.length} remaining)` );
        
        // Create blob URL
        const blobUrl = URL.createObjectURL( nextChunk );
        
        // Create audio element for this chunk
        this.currentSequentialAudio = new Audio( blobUrl );
        this.isSequentialPlaying = true;
        
        // Set up event handlers
        this.currentSequentialAudio.addEventListener( 'ended', () => {
            if ( this.debug ) this.log( `Sequential chunk ${this.sequentialChunksPlayed} ended` );
            URL.revokeObjectURL( blobUrl ); // Clean up
            this.playNextSequentialChunk(); // Play next chunk
        });
        
        this.currentSequentialAudio.addEventListener( 'error', ( e ) => {
            this.error( `Sequential chunk ${this.sequentialChunksPlayed} error:`, e );
            URL.revokeObjectURL( blobUrl ); // Clean up
            this.playNextSequentialChunk(); // Continue on error
        });
        
        // Track timing for first chunk playback
        const playStartTime = Date.now();
        
        // Start playback with timing measurement
        this.currentSequentialAudio.play().then( () => {
            if ( !this.firstChunkPlayed && this.firstChunkStartTime ) {
                const timeToPlayback = ( Date.now() - this.firstChunkStartTime ) / 1000;
                this.log( `Instant mode: First chunk playing! (${timeToPlayback.toFixed(3)}s from arrival to playback start)` );
                this.firstChunkPlayed = true;
            }
        }).catch( e => {
            if ( !this.firstChunkPlayed && this.firstChunkStartTime ) {
                const timeToPlayback = ( Date.now() - this.firstChunkStartTime ) / 1000;
                this.log( `Instant mode: First chunk play failed (${timeToPlayback.toFixed(3)}s from arrival to attempt): ${e.message}` );
                this.firstChunkPlayed = true; // Mark as attempted even on failure
            }
            this.playNextSequentialChunk(); // Continue on play failure
        });
    }
    
    async playAudioChunkProgressive( blobData ) {
        try {
            if ( !this.audioContext ) {
                await this.createAudioContext();
            }
            
            // Skip chunks that are too small (likely metadata/headers)
            if ( blobData.size < 100 ) {
                if ( this.debug ) this.log( `Skipping small chunk: ${blobData.size} bytes (likely metadata)` );
                return;
            }
            
            // Convert blob to array buffer
            const arrayBuffer = await blobData.arrayBuffer();
            
            // Decode audio data with error handling
            let audioBuffer;
            try {
                audioBuffer = await this.audioContext.decodeAudioData( arrayBuffer );
            } catch ( decodeError ) {
                this.log( `Skipping chunk that failed to decode: ${blobData.size} bytes - ${decodeError.message}` );
                return; // Skip this chunk but continue processing others
            }
            
            // Create audio source
            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect( this.audioContext.destination );
            
            // Schedule playback
            const now = this.audioContext.currentTime;
            const playTime = this.nextScheduledTime || now;
            source.start( playTime );
            
            // Update next scheduled time
            this.nextScheduledTime = playTime + audioBuffer.duration;
            
            // Keep track of sources for cleanup and counting
            this.audioSources = this.audioSources || [];
            this.audioSources.push( source );
            
            // Track processed chunks for instant mode
            this.processedChunks = ( this.processedChunks || 0 ) + 1;
            
            if ( this.debug ) this.log( `Scheduled audio chunk at ${playTime}s, duration: ${audioBuffer.duration}s (chunk ${this.processedChunks})` );
            
        } catch ( error ) {
            this.error( "Failed to play audio chunk:", error );
        }
    }
    
    async playCollectedChunks() {
        try {
            if ( !this.audioChunks || this.audioChunks.length === 0 ) {
                this.log( "No audio chunks to play" );
                return;
            }

            // Combine all chunks into single blob
            const combinedBlob = new Blob( this.audioChunks, { type: 'audio/mpeg' } );
            await this.playAudioBlob( combinedBlob );

            // Clean up
            this.audioChunks = [];

        } catch ( error ) {
            this.error( "Failed to play collected chunks:", error );
        }
    }
    
    // Reliable mode audio playback (adapted from original HybridTTS)
    async playCollectedAudio() {
        if ( !this.audioChunks || this.audioChunks.length === 0 ) {
            this.error( "No audio data received for reliable mode" );
            return;
        }

        const totalTime = this.startTime ? ( Date.now() - this.startTime ) / 1000 : 0;
        this.log( `Reliable mode: Playing ${this.audioChunks.length} chunks collected in ${totalTime.toFixed(1)}s` );

        // Create single blob from all chunks (same as original HybridTTS)
        const audioBlob = new Blob( this.audioChunks, { type: 'audio/mpeg' } );
        const audioUrl = URL.createObjectURL( audioBlob );

        // Set up and play audio using HTML audio element
        this.audioElement.src = audioUrl;
        
        // Track time to begin playback
        const playbackStartTime = Date.now();
        
        try {
            await this.audioElement.play();
            const timeToPlayback = ( Date.now() - playbackStartTime ) / 1000;
            this.log( `Reliable mode: Audio playing! (${totalTime.toFixed(1)}s total collection time, ${timeToPlayback.toFixed(3)}s to begin playback)` );
            this.isPlaying = true;
            this.currentAudio = this.audioElement;
        } catch ( playError ) {
            // Handle autoplay prevention gracefully (like original)
            const timeToPlayback = ( Date.now() - playbackStartTime ) / 1000;
            this.log( `Reliable mode: Audio ready (${totalTime.toFixed(1)}s total collection time, ${timeToPlayback.toFixed(3)}s to ready) - autoplay prevented:`, playError.message );
        }

        // Clean up when ended (like original HybridTTS)
        this.audioElement.addEventListener( 'ended', () => {
            this.log( "Reliable mode: Audio playback ended" );
            URL.revokeObjectURL( audioUrl );
            this.isPlaying = false;
            this.currentAudio = null;
            this.audioChunks = []; // Clean up chunks
        }, { once: true });
    }
    
    async playAudioBlob( audioBlob ) {
        return new Promise( ( resolve, reject ) => {
            try {
                const audioUrl = URL.createObjectURL( audioBlob );
                const audio = new Audio( audioUrl );
                
                audio.onloadeddata = () => {
                    this.log( `Audio loaded, duration: ${audio.duration}s` );
                };
                
                audio.onplay = () => {
                    this.log( "Audio playback started" );
                    this.isPlaying = true;
                    this.currentAudio = audio;
                };
                
                audio.onended = () => {
                    this.log( "Audio playback ended" );
                    this.isPlaying = false;
                    this.currentAudio = null;
                    URL.revokeObjectURL( audioUrl );
                    resolve();
                };
                
                audio.onerror = ( error ) => {
                    this.error( "Audio playback error:", error );
                    this.isPlaying = false;
                    this.currentAudio = null;
                    URL.revokeObjectURL( audioUrl );
                    reject( error );
                };
                
                // Start playback
                audio.play().catch( reject );
                
            } catch ( error ) {
                reject( error );
            }
        });
    }
    
    stopAudio() {
        this.log( "Stopping all audio playback" );
        
        // Stop HTML audio (currentAudio, audioElement, and sequential)
        if ( this.currentAudio ) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
        
        if ( this.audioElement ) {
            this.audioElement.pause();
            this.audioElement.currentTime = 0;
            if ( this.audioElement.src ) {
                URL.revokeObjectURL( this.audioElement.src );
                this.audioElement.removeAttribute( 'src' );
            }
        }
        
        if ( this.currentSequentialAudio ) {
            this.currentSequentialAudio.pause();
            this.currentSequentialAudio.currentTime = 0;
            this.currentSequentialAudio = null;
        }
        
        // Stop Web Audio API sources
        if ( this.audioSources ) {
            this.audioSources.forEach( source => {
                try {
                    source.stop();
                } catch ( e ) {
                    // Source may already be stopped
                }
            });
            this.audioSources = [];
        }
        
        // Reset scheduling and state
        this.nextScheduledTime = null;
        this.isPlaying = false;
        this.audioChunks = [];
        this.processedChunks = 0;
        
        // Reset sequential playback
        this.sequentialQueue = [];
        this.isSequentialPlaying = false;
        this.sequentialChunksPlayed = 0;
        
        // Reset first chunk timing
        this.firstChunkStartTime = null;
        this.firstChunkPlayed = false;
        
        this.log( "Audio playback stopped" );
    }
    
    // ========================================
    // NOTIFICATION HANDLERS (from original queue.js)
    // ========================================
    
    handleUserNotification( envelope ) {
        this.log( "Claude Code notification received for list:", envelope );
        
        // Extract the actual notification data from the nested structure
        const notificationData = envelope.data || envelope;
        this.addNotificationToList( notificationData );
    }
    
    handleNotificationUpdate( envelope ) {
        this.log( "Notification queue update received:", envelope );
        
        // Handle real-time notification updates from NotificationFifoQueue
        if ( envelope.notification ) {
            this.addNotificationToList( envelope.notification );
        } else if ( envelope.data?.notification ) {
            this.addNotificationToList( envelope.data.notification );
        }
    }
    
    // ========================================
    // CONNECTION MANAGEMENT
    // ========================================
    
    scheduleReconnect() {
        if ( this.isConnecting ) {
            return; // Already attempting to reconnect
        }
        
        if ( this.connectionRetries >= this.maxRetries ) {
            this.error( "Max reconnection attempts reached" );
            this.updateStatus( "queue-ws-status", "Failed", "error" );
            this.updateStatus( "audio-ws-status", "Failed", "error" );
            return;
        }
        
        this.connectionRetries++;
        const delay = Math.min( 1000 * Math.pow( 2, this.connectionRetries ), 30000 ); // Exponential backoff, max 30s
        
        this.log( `Scheduling reconnect attempt ${this.connectionRetries}/${this.maxRetries} in ${delay}ms` );
        
        setTimeout( () => {
            this.isConnecting = true;
            this.connectWebSockets().finally( () => {
                this.isConnecting = false;
            });
        }, delay );
    }
    
    // ========================================
    // AUTHENTICATION HELPERS (from original queue.js)
    // ========================================
    
    getCurrentUserEmail() {
        // Use the hardcoded email as per original queue.js pattern
        return "ricardo.felipe.ruiz@gmail.com";
    }
    
    getAuthHeader() {
        const email = this.getCurrentUserEmail();
        return `Bearer mock_token_email_${email}`;
    }
    
    // ========================================
    // QUEUE LISTS MANAGEMENT (from original queue.js)
    // ========================================
    
    async updateQueueLists( queueName ) {
        this.log( `Updating queue list for: ${queueName}` );
        const url = `/api/get-queue/${queueName}`;
        
        try {
            const response = await fetch( url, {
                headers: {
                    'Authorization': this.getAuthHeader()
                }
            });
            
            if ( !response.ok ) {
                throw new Error( `HTTP error! status: ${response.status}` );
            }
            
            const data = await response.json();
            this.log( `Data received for ${queueName}:`, data );
            
            // Update the appropriate list based on queue name
            if ( queueName === "todo" ) {
                document.getElementById( "todo-list" ).innerHTML = data.todo_jobs.join( "" );
                document.getElementById( "todo-count" ).textContent = data.todo_jobs.length;
            } else if ( queueName === "run" ) {
                document.getElementById( "run-list" ).innerHTML = data.run_jobs.join( "" );
                document.getElementById( "run-count" ).textContent = data.run_jobs.length;
            } else if ( queueName === "done" ) {
                // Enhanced done list with playback and delete icons
                const doneListHtml = data.done_jobs.map( ( jobHtml, index ) => {
                    // Extract job ID from the HTML if possible, or generate one
                    const jobIdMatch = jobHtml.match( /id=['"]([^'"]+)['"]/ );
                    const jobId = jobIdMatch ? jobIdMatch[1] : `done-job-${index}`;
                    
                    // Add playback and delete icons to each job
                    const enhancedJobHtml = jobHtml.replace( 
                        /(<\/li>)$/,
                        `<span class="job-controls" style="margin-left: 10px;">
                            <span class="replay-job" data-job-id="${jobId}" 
                                  style="cursor: pointer; margin-right: 8px; opacity: 0.7; transition: opacity 0.2s; font-size: 14px;" 
                                  title="Replay job audio" role="button" tabindex="0" aria-label="Replay job audio">🔊</span>
                            <span class="delete-job" data-job-id="${jobId}" 
                                  style="cursor: pointer; opacity: 0.6; transition: opacity 0.2s; font-size: 14px; color: #dc3545;" 
                                  title="Delete job" role="button" tabindex="0" aria-label="Delete job">🗑️</span>
                        </span>$1`
                    );
                    
                    return enhancedJobHtml;
                }).join( "" );
                
                document.getElementById( "done-list" ).innerHTML = doneListHtml;
                document.getElementById( "done-count" ).textContent = data.done_jobs.length;
                
                // Add event listeners for the new icons
                this.addDoneListEventListeners();
            } else if ( queueName === "dead" ) {
                document.getElementById( "dead-list" ).innerHTML = data.dead_jobs.join( "" );
                document.getElementById( "dead-count" ).textContent = data.dead_jobs.length;
            } else {
                this.error( "Unknown queue name:", queueName );
            }
            
        } catch ( error ) {
            this.error( `Error updating ${queueName} queue:`, error );
        }
    }
    
    addDoneListEventListeners() {
        // Add event listeners for replay and delete buttons in the done jobs list
        const doneList = document.getElementById( "done-list" );
        if ( !doneList ) return;
        
        // Remove existing listeners to prevent duplicates
        const existingButtons = doneList.querySelectorAll( '.replay-job, .delete-job' );
        existingButtons.forEach( button => {
            // Clone and replace to remove all event listeners
            const newButton = button.cloneNode( true );
            button.parentNode.replaceChild( newButton, button );
        });
        
        // Add replay button listeners
        const replayButtons = doneList.querySelectorAll( '.replay-job' );
        replayButtons.forEach( button => {
            const jobId = button.dataset.jobId;
            
            // Click handler
            button.addEventListener( 'click', ( e ) => {
                e.stopPropagation();
                this.replayJobAudio( jobId );
            });
            
            // Keyboard handler
            button.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' || e.key === ' ' ) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.replayJobAudio( jobId );
                }
            });
            
            // Hover effects
            button.addEventListener( 'mouseenter', () => {
                button.style.opacity = '1';
                button.style.transform = 'scale(1.1)';
            });
            
            button.addEventListener( 'mouseleave', () => {
                button.style.opacity = '0.7';
                button.style.transform = 'scale(1)';
            });
        });
        
        // Add delete button listeners
        const deleteButtons = doneList.querySelectorAll( '.delete-job' );
        deleteButtons.forEach( button => {
            const jobId = button.dataset.jobId;
            
            // Click handler
            button.addEventListener( 'click', ( e ) => {
                e.stopPropagation();
                this.deleteJob( jobId );
            });
            
            // Keyboard handler
            button.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' || e.key === ' ' ) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.deleteJob( jobId );
                }
            });
            
            // Hover effects
            button.addEventListener( 'mouseenter', () => {
                button.style.opacity = '1';
            });
            
            button.addEventListener( 'mouseleave', () => {
                button.style.opacity = '0.6';
            });
        });
        
        this.log( `Added event listeners to ${replayButtons.length} replay and ${deleteButtons.length} delete buttons in done list` );
    }
    
    replayJobAudio( jobId ) {
        this.log( `Replay requested for job: ${jobId}` );
        // TODO: Implement job audio replay functionality
        alert( `Replay job audio for: ${jobId}\n\n(Functionality coming soon!)` );
    }
    
    deleteJob( jobId ) {
        this.log( `Delete requested for job: ${jobId}` );
        // Show alert as requested - don't implement delete yet
        alert( `Delete job: ${jobId}\n\n(Delete functionality not implemented yet)` );
    }
    
    // ========================================
    // NOTIFICATIONS MANAGEMENT (from original queue.js)
    // ========================================
    
    addNotificationToList( data ) {
        const { message, type, priority, source, timestamp } = data;
        const notificationsList = document.getElementById( "notifications-list" );
        const notificationsCounter = document.getElementById( "notifications-count" );
        
        if ( !notificationsList ) {
            this.error( "Notifications list element not found" );
            return;
        }
        
        // Format timestamp for display
        const time = new Date( timestamp ).toLocaleTimeString();
        
        // Create priority emoji and styling
        let priorityEmoji = "📝";
        let priorityColor = "#6c757d"; // Gray
        let typeEmoji = "📋";
        
        // Set priority-based styling
        switch ( priority ) {
            case "urgent":
                priorityEmoji = "🚨";
                priorityColor = "#dc3545"; // Red
                break;
            case "high":
                priorityEmoji = "⚠️";
                priorityColor = "#fd7e14"; // Orange
                break;
            case "medium":
                priorityEmoji = "📢";
                priorityColor = "#ffc107"; // Yellow
                break;
            case "low":
                priorityEmoji = "📝";
                priorityColor = "#6c757d"; // Gray
                break;
        }
        
        // Set type-based emoji
        switch ( type ) {
            case "task":
                typeEmoji = "✅";
                break;
            case "progress":
                typeEmoji = "🔄";
                break;
            case "alert":
                typeEmoji = "⚠️";
                break;
            case "custom":
                typeEmoji = "💡";
                break;
        }
        
        // Truncate long messages for list display
        const displayMessage = message.length > 80 ? message.substring( 0, 77 ) + "..." : message;
        
        // Use the server-provided id_hash for proper identification
        const notificationId = data.id_hash || `notification_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        this.log( `Adding notification to list with ID: "${notificationId}"` );
        
        // Create list item with styling from original queue.html
        const listItem = document.createElement( "li" );
        listItem.id = notificationId;
        listItem.style.marginBottom = "8px";
        listItem.style.padding = "5px";
        listItem.style.borderLeft = `3px solid ${priorityColor}`;
        listItem.style.backgroundColor = "#f8f9fa";
        listItem.innerHTML = `
            <div style="display: flex; align-items: center; font-size: 12px;">
                <span style="margin-right: 5px;">${typeEmoji}</span>
                <span style="margin-right: 5px; color: ${priorityColor}; font-weight: bold;">${priorityEmoji}</span>
                <span style="color: #666; margin-right: 10px;">[${time}]</span>
                <span style="color: ${priorityColor}; font-weight: bold; margin-right: 5px;">${type.toUpperCase()}</span>
                <span style="color: ${priorityColor}; font-size: 10px; margin-right: 10px;">(${priority})</span>
                <span style="flex: 1; color: #333;">${displayMessage}</span>
                <span class="replay-notification" data-notification-id="${notificationId}" 
                      style="cursor: pointer; margin-left: auto; margin-right: 8px; opacity: 0.7; transition: opacity 0.2s; font-size: 14px;" 
                      title="Replay notification audio" role="button" tabindex="0" aria-label="Replay notification audio">🔊</span>
                <span class="delete-notification" data-notification-id="${notificationId}" 
                      style="cursor: pointer; opacity: 0.6; transition: opacity 0.2s; font-size: 14px; color: #dc3545;" 
                      title="Delete notification" role="button" tabindex="0" aria-label="Delete notification">🗑️</span>
            </div>
        `;
        
        // Store notification data for replay functionality
        listItem.notificationData = {
            message: message,
            type: type,
            priority: priority,
            source: source,
            timestamp: timestamp,
            // Simple verbatim message without dressing up
            ttsMessage: message
        };
        
        // Add event listeners for replay and delete buttons (better than onclick)
        const replayButton = listItem.querySelector( '.replay-notification' );
        const deleteButton = listItem.querySelector( '.delete-notification' );
        
        if ( replayButton ) {
            // Mouse click
            replayButton.addEventListener( 'click', ( e ) => {
                e.stopPropagation();
                this.replayNotificationAudio( notificationId );
            });
            
            // Keyboard support (Enter/Space)
            replayButton.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' || e.key === ' ' ) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.replayNotificationAudio( notificationId );
                }
            });
            
            // Hover effects
            replayButton.addEventListener( 'mouseenter', () => {
                replayButton.style.opacity = '1';
                replayButton.style.transform = 'scale(1.1)';
            });
            
            replayButton.addEventListener( 'mouseleave', () => {
                replayButton.style.opacity = '0.7';
                replayButton.style.transform = 'scale(1)';
            });
        }
        
        if ( deleteButton ) {
            // Mouse click  
            deleteButton.addEventListener( 'click', ( e ) => {
                e.stopPropagation();
                this.deleteNotification( notificationId );
            });
            
            // Keyboard support (Enter/Space)
            deleteButton.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' || e.key === ' ' ) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.deleteNotification( notificationId );
                }
            });
            
            // Hover effects
            deleteButton.addEventListener( 'mouseenter', () => {
                deleteButton.style.opacity = '1';
            });
            
            deleteButton.addEventListener( 'mouseleave', () => {
                deleteButton.style.opacity = '0.6';
            });
        }
        
        // Add to top of list (newest first)
        notificationsList.insertBefore( listItem, notificationsList.firstChild );
        
        // Update counter
        const currentCount = notificationsList.children.length;
        if ( notificationsCounter ) {
            notificationsCounter.textContent = currentCount;
        }
        
        this.log( `Added ${type}/${priority} notification to list: "${displayMessage}"` );
    }
    
    async loadInitialNotifications() {
        if ( !this.notificationState.userId ) {
            this.log( "Cannot load notifications - user not authenticated" );
            return;
        }
        
        try {
            const response = await fetch( `/api/notifications/${this.notificationState.userId}?include_played=true&api_key=${this.notificationState.apiKey}` );
            
            if ( !response.ok ) {
                this.error( "Failed to load initial notifications:", response.status, response.statusText );
                return;
            }
            
            const data = await response.json();
            const serverNotifications = data.notifications || [];
            
            this.log( `Loaded ${serverNotifications.length} initial notifications` );
            
            // Clear existing notifications and populate with server data
            const notificationsList = document.getElementById( "notifications-list" );
            if ( notificationsList ) {
                notificationsList.innerHTML = "";
            }
            
            // Add each notification to the list (newest first)
            serverNotifications.reverse().forEach( notification => {
                this.addNotificationToList( notification );
            });
            
        } catch ( error ) {
            this.error( "Error loading initial notifications:", error );
        }
    }
    
    async deleteNotification( notificationId ) {
        this.log( `Delete button clicked for notification: ${notificationId}` );
        
        try {
            const response = await fetch( `/api/notifications/${notificationId}?api_key=${this.notificationState.apiKey}`, {
                method: 'DELETE'
            });
            
            if ( !response.ok && response.status !== 404 ) {
                this.error( `Server error (${response.status}) deleting notification, but removing from UI anyway.` );
            }
            
        } catch ( error ) {
            this.error( "Network error deleting notification:", error );
        }
        
        // ALWAYS remove from UI regardless of server response
        const listItem = document.getElementById( notificationId );
        if ( listItem ) {
            listItem.remove();
            
            // Update counter
            const notificationsList = document.getElementById( "notifications-list" );
            const notificationsCounter = document.getElementById( "notifications-count" );
            if ( notificationsList && notificationsCounter ) {
                const currentCount = notificationsList.children.length;
                notificationsCounter.textContent = currentCount;
            }
            
            this.log( `Notification ${notificationId} removed from UI` );
        }
        
        // Remove from local cache
        this.notificationState.notifications = this.notificationState.notifications.filter( 
            n => n.id_hash !== notificationId 
        );
    }
    
    async replayNotificationAudio( notificationId ) {
        this.log( `Replay button clicked for notification: ${notificationId}` );
        
        const listItem = document.getElementById( notificationId );
        if ( !listItem || !listItem.notificationData ) {
            this.error( `No notification data found for ID: ${notificationId}` );
            return;
        }
        
        const { ttsMessage, type, priority, message } = listItem.notificationData;
        
        try {
            // Show loading state on replay button
            const replayButton = listItem.querySelector( '.replay-notification' );
            const originalContent = replayButton.textContent;
            const originalOpacity = replayButton.style.opacity;
            
            // Visual feedback - loading state
            replayButton.textContent = '⏳';
            replayButton.style.opacity = '1';
            replayButton.style.pointerEvents = 'none'; // Prevent multiple clicks
            
            // Highlight the notification being replayed with smooth animation
            const originalBackground = listItem.style.backgroundColor;
            listItem.style.transition = "background-color 0.3s ease";
            listItem.style.backgroundColor = "#e3f2fd"; // Light blue highlight
            
            this.log( `Replaying notification audio: "${ttsMessage}"` );
            
            // **IMPROVEMENT**: Direct integration with our TTS system instead of external queue
            // Use the current TTS mode (instant/reliable) from the UI
            const currentMode = document.getElementById( 'tts-mode' )?.value || 'instant';
            
            if ( currentMode === 'instant' ) {
                // Use instant mode - direct WebSocket streaming
                await this.playInstantTTS( ttsMessage );
            } else {
                // Use reliable mode - collected audio playback
                await this.playReliableTTS( ttsMessage );
            }
            
            this.log( `Successfully replayed ${type}/${priority} notification` );
            
            // **IMPROVEMENT**: Enhanced visual feedback
            // Brief success indicator
            replayButton.textContent = '✅';
            setTimeout( () => {
                replayButton.textContent = originalContent;
                replayButton.style.opacity = originalOpacity;
                replayButton.style.pointerEvents = 'auto';
            }, 1000 );
            
        } catch ( error ) {
            this.error( `Failed to replay notification audio:`, error );
            
            // **IMPROVEMENT**: Better error handling with user feedback
            const replayButton = listItem.querySelector( '.replay-notification' );
            replayButton.textContent = '❌';
            setTimeout( () => {
                replayButton.textContent = '🔊';
                replayButton.style.opacity = '0.7';
                replayButton.style.pointerEvents = 'auto';
            }, 2000 );
        } finally {
            // Always restore the notification background
            setTimeout( () => {
                if ( listItem && originalBackground !== undefined ) {
                    listItem.style.backgroundColor = originalBackground;
                }
            }, 1500 );
        }
    }
    
    async loadInitialData() {
        this.log( "Loading initial data (queue lists and notifications)" );
        
        // Load all queue lists
        try {
            await Promise.all([
                this.updateQueueLists( "todo" ),
                this.updateQueueLists( "run" ),
                this.updateQueueLists( "done" ),
                this.updateQueueLists( "dead" )
            ]);
            this.log( "Initial queue lists loaded successfully" );
        } catch ( error ) {
            this.error( "Error loading initial queue lists:", error );
        }
        
        // Load initial notifications
        try {
            await this.loadInitialNotifications();
            this.log( "Initial notifications loaded successfully" );
        } catch ( error ) {
            this.error( "Error loading initial notifications:", error );
        }
    }
    
    // ========================================
    // UTILITY METHODS
    // ========================================
    
    log( message, ...args ) {
        if ( this.debug ) {
            console.log( `[FreshQueue] ${message}`, ...args );
            this.addDebugMessage( message );
        }
    }
    
    error( message, ...args ) {
        console.error( `[FreshQueue ERROR] ${message}`, ...args );
        this.addDebugMessage( `ERROR: ${message}`, 'error' );
    }
    
    addDebugMessage( message, type = 'info' ) {
        const debugLog = document.getElementById( 'debug-log' );
        if ( debugLog ) {
            const timestamp = new Date().toLocaleTimeString();
            const debugDiv = document.createElement( 'div' );
            debugDiv.className = `debug-info ${type}`;
            debugDiv.textContent = `[${timestamp}] ${message}`;
            
            // Prepend to show newest messages first
            debugLog.insertBefore( debugDiv, debugLog.firstChild );
            
            // Limit to last 20 messages
            while ( debugLog.children.length > 20 ) {
                debugLog.removeChild( debugLog.lastChild );
            }
        }
    }
    
    updateElement( elementId, content ) {
        const element = document.getElementById( elementId );
        if ( element ) {
            element.textContent = content;
        }
    }
    
    updateStatus( elementId, status, type ) {
        const element = document.getElementById( elementId );
        if ( element ) {
            element.textContent = status;
            element.className = `status-${type}`;
        }
    }
}

// ========================================
// INITIALIZATION
// ========================================

// Initialize when DOM is ready
if ( document.readyState === 'loading' ) {
    document.addEventListener( 'DOMContentLoaded', () => {
        window.freshQueueUI = new FreshQueueUI();
    });
} else {
    window.freshQueueUI = new FreshQueueUI();
}

// Make available globally for debugging
window.FreshQueueUI = FreshQueueUI;