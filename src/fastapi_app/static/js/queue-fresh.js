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
        this.currentNotificationId = null;
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
        this.authRefreshAttempted = false; // Track refresh attempts to prevent loops
        
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
        
        // Notification sound system
        this.notificationSounds = {};
        this.soundsInitialized = false;
        
        // TTS audio cache system
        this.audioCache = new TTSAudioCache({
            cacheEnabled: true,
            maxAge: 24 * 60 * 60 * 1000, // 24 hours
            maxSize: 50 * 1024 * 1024,   // 50MB
            debug: this.debug
        });
        this.audioCacheInitialized = false;
        
        // Job completion cache system for replay functionality
        this.jobCompletionCache = new JobCompletionCache({
            cacheEnabled: true,
            cacheMaxAge: 30 * 24 * 60 * 60 * 1000, // 30 days
            maxEntries: 1000,
            debug: this.debug
        });
        this.jobCompletionCacheInitialized = false;
        
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
            
            // Initialize notification sound system
            await this.initializeNotificationSounds();
            
            // Initialize TTS audio cache system
            await this.audioCache.initialize();
            this.audioCacheInitialized = true;
            
            // Initialize job completion cache system
            await this.jobCompletionCache.initializeIndexedDB();
            this.jobCompletionCacheInitialized = true;
            this.log( "Job completion cache initialized for replay functionality" );
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Apply Firefox compatibility hack
            this.applyFirefoxCompatibilityHack();
            
            // Connect WebSockets
            await this.connectWebSockets();
            
            this.log( "FreshQueueUI initialization complete" );
            
        } catch ( error ) {
            this.error( "Initialization failed:", error );
            this.updateStatus( "auth-status", "Initialization failed", "error" );
        }
    }
    
    applyFirefoxCompatibilityHack() {
        /**
         * Firefox Runtime Compatibility Hack
         * 
         * Problem: Instant mode (11labs streaming) has compatibility issues with Firefox
         * Solution: Auto-detect Firefox and force reliable mode (OpenAI batch)
         * 
         * This is a temporary workaround until Firefox instant mode issues are resolved.
         */
        
        // Detect Firefox using multiple methods for reliability
        const isFirefox = navigator.userAgent.toLowerCase().includes( 'firefox' ) || 
                         typeof InstallTrigger !== 'undefined' ||
                         ( navigator.userAgent.includes( 'Gecko/' ) && !navigator.userAgent.includes( 'Chrome' ) );
        
        if ( isFirefox ) {
            console.log( "🦊 [FIREFOX-HACK] Firefox detected - forcing reliable mode for TTS compatibility" );
            
            // Get the TTS mode selector
            const ttsMode = document.getElementById( 'tts-mode' );
            if ( ttsMode ) {
                // Force reliable mode
                ttsMode.value = 'reliable';
                
                // Optional: Disable instant mode option to prevent manual switching
                const instantOption = ttsMode.querySelector( 'option[value="instant"]' );
                if ( instantOption ) {
                    instantOption.disabled = true;
                    instantOption.textContent = 'Instant (Disabled in Firefox)';
                }
                
                console.log( "🦊 [FIREFOX-HACK] Switched TTS mode to 'reliable' - instant mode disabled" );
            } else {
                console.warn( "🦊 [FIREFOX-HACK] Could not find TTS mode selector to apply Firefox hack" );
            }
        } else {
            console.log( "🌐 [BROWSER-DETECT] Non-Firefox browser detected - instant mode available" );
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
        // JWT Authentication: Check for stored tokens
        const tokens = this.getStoredTokens();

        if ( !tokens.accessToken ) {
            // No tokens found - redirect to login with current page as redirect target
            this.log( "No authentication tokens found - redirecting to login" );
            const currentPath = window.location.pathname;
            window.location.href = `/static/html/auth/login.html?redirect=${currentPath}`;
            return;
        }

        // Check if access token is expired
        if ( this.isTokenExpired( tokens.accessToken ) ) {
            this.log( "Access token expired - attempting refresh" );
            const refreshed = await this.refreshAccessToken();

            if ( !refreshed ) {
                this.log( "Token refresh failed - redirecting to login" );
                this.handleAuthFailure();
                return;
            }

            // Get refreshed tokens
            const newTokens = this.getStoredTokens();
            this.authToken = newTokens.accessToken;
        } else {
            this.authToken = tokens.accessToken;
        }

        // Extract user info from JWT payload
        const payload = this.parseJWTPayload( this.authToken );
        this.currentUser = payload.email;

        // Update UI
        this.updateElement( "user-display", this.currentUser );
        this.updateStatus( "auth-status", "Authenticated", "success" );
        this.log( `Authentication setup complete for user: ${this.currentUser}` );
    }

    getStoredTokens() {
        /**
         * Retrieve JWT tokens from localStorage.
         *
         * Returns:
         *     Object with accessToken and refreshToken properties (may be null)
         */
        return {
            accessToken: localStorage.getItem( 'lupin_access_token' ),
            refreshToken: localStorage.getItem( 'lupin_refresh_token' )
        };
    }

    parseJWTPayload( token ) {
        /**
         * Decode JWT payload without verification (client-side).
         * Used to extract user info like email.
         *
         * Note: This does NOT validate the token - validation happens server-side.
         *
         * Args:
         *     token: JWT token string
         *
         * Returns:
         *     Object with decoded payload
         */
        try {
            // JWT format: header.payload.signature
            const parts = token.split( '.' );
            if ( parts.length !== 3 ) {
                throw new Error( "Invalid JWT format" );
            }

            // Decode base64url payload (second part)
            const payload = parts[1];
            // Base64url to base64: replace - with + and _ with /
            const base64 = payload.replace( /-/g, '+' ).replace( /_/g, '/' );
            // Decode and parse JSON
            const jsonPayload = decodeURIComponent( atob( base64 ).split( '' ).map( function( c ) {
                return '%' + ( '00' + c.charCodeAt( 0 ).toString( 16 ) ).slice( -2 );
            }).join( '' ) );

            return JSON.parse( jsonPayload );
        } catch ( error ) {
            this.error( "Failed to parse JWT payload:", error );
            return {};
        }
    }

    isTokenExpired( token ) {
        /**
         * Check if JWT token is expired by examining exp claim.
         *
         * Args:
         *     token: JWT token string
         *
         * Returns:
         *     Boolean - true if expired or invalid, false otherwise
         */
        try {
            const payload = this.parseJWTPayload( token );

            if ( !payload.exp ) {
                return true; // No expiration claim - consider invalid
            }

            // exp is in seconds, Date.now() is in milliseconds
            const now = Math.floor( Date.now() / 1000 );

            // Add 60 second buffer to refresh before actual expiry
            return payload.exp < ( now + 60 );
        } catch ( error ) {
            this.error( "Failed to check token expiration:", error );
            return true; // Consider expired on error
        }
    }

    async refreshAccessToken() {
        /**
         * Refresh access token using refresh token.
         *
         * Returns:
         *     Boolean - true if refresh succeeded, false otherwise
         */
        const tokens = this.getStoredTokens();

        if ( !tokens.refreshToken ) {
            this.error( "No refresh token available" );
            return false;
        }

        try {
            this.log( "Refreshing access token..." );

            const response = await fetch( '/auth/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    refresh_token: tokens.refreshToken
                })
            });

            if ( response.ok ) {
                const data = await response.json();

                // Store new tokens
                localStorage.setItem( 'lupin_access_token', data.tokens.access_token );
                localStorage.setItem( 'lupin_refresh_token', data.tokens.refresh_token );

                this.authToken = data.tokens.access_token;
                this.log( "Access token refreshed successfully" );
                return true;
            } else {
                this.error( `Token refresh failed: ${response.status} ${response.statusText}` );
                return false;
            }
        } catch ( error ) {
            this.error( "Token refresh error:", error );
            return false;
        }
    }

    handleAuthFailure() {
        /**
         * Handle authentication failure by clearing tokens and redirecting to login.
         */
        this.log( "Handling authentication failure" );

        // Clear tokens
        localStorage.removeItem( 'lupin_access_token' );
        localStorage.removeItem( 'lupin_refresh_token' );

        // Disconnect WebSockets
        if ( this.queueWS ) {
            this.queueWS.close();
        }
        if ( this.audioWS ) {
            this.audioWS.close();
        }

        // Redirect to login with current page as redirect target
        const currentPath = window.location.pathname;
        window.location.href = `/static/html/auth/login.html?redirect=${currentPath}`;
    }

    logout() {
        /**
         * Logout user by clearing authentication and redirecting to login.
         * Called by logout button in UI.
         */
        this.log( "User logout initiated" );

        // Clear tokens
        localStorage.removeItem( 'lupin_access_token' );
        localStorage.removeItem( 'lupin_refresh_token' );

        // Disconnect WebSockets gracefully
        if ( this.queueWS ) {
            this.queueWS.close();
            this.queueWS = null;
        }
        if ( this.audioWS ) {
            this.audioWS.close();
            this.audioWS = null;
        }

        // Update UI
        this.updateStatus( "auth-status", "Logged out", "warning" );

        // Redirect to login page (no redirect param - go to profile after login)
        window.location.href = '/static/html/auth/login.html';
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
    
    async initializeNotificationSounds() {
        try {
            // Pre-load and cache notification sounds for instant playback
            this.notificationSounds = {
                lowPriority: new Audio( '/static/audio/notification-low-priority.mp3' ),
                highPriority: new Audio( '/static/audio/notification-high-priority.mp3' ),
                error: new Audio( '/static/audio/notification-error.mp3' )
            };
            
            // Set properties for better performance
            Object.values( this.notificationSounds ).forEach( audio => {
                audio.preload = 'auto';
                audio.volume = 0.7; // Slightly quieter than default
            } );
            
            this.soundsInitialized = true;
            this.log( "Notification sounds initialized and cached" );
            
        } catch ( error ) {
            this.error( "Failed to initialize notification sounds:", error );
            this.notificationSounds = {};
            this.soundsInitialized = false;
        }
    }
    
    async playNotificationSoundByPriority( priority ) {
        try {
            if ( !this.soundsInitialized ) {
                this.log( "Notification sounds not initialized, skipping sound playback" );
                return;
            }
            
            let audio = null;
            
            // Map priority to appropriate sound
            switch ( priority ) {
                case "urgent":
                case "high":
                    audio = this.notificationSounds.highPriority;
                    this.log( `Playing high priority notification sound for ${priority} priority` );
                    break;
                case "medium":
                case "low":
                    audio = this.notificationSounds.lowPriority;
                    this.log( `Playing low priority notification sound for ${priority} priority` );
                    break;
                case "error":
                    audio = this.notificationSounds.error;
                    this.log( `Playing error notification sound` );
                    break;
                default:
                    // Default to low priority sound for unknown priorities
                    audio = this.notificationSounds.lowPriority;
                    this.log( `Playing default (low priority) notification sound for unknown priority: ${priority}` );
                    break;
            }
            
            if ( audio ) {
                // Reset audio to beginning in case it was played before
                audio.currentTime = 0;
                await audio.play();
            } else {
                this.error( 'No notification sound available for priority:', priority );
            }
            
        } catch ( error ) {
            this.error( 'Failed to play notification sound:', error );
            // Continue execution even if sound fails
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
        
        // Enter key in Q&A input
        document.getElementById( 'qa-input' ).addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' ) {
                e.preventDefault(); // Prevent default form submission behavior
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

                    // Attempt token refresh once
                    if ( !this.authRefreshAttempted ) {
                        this.authRefreshAttempted = true;
                        this.log( "Attempting token refresh after auth error..." );

                        this.refreshAccessToken().then( ( success ) => {
                            if ( success ) {
                                this.log( "Token refreshed - reconnecting WebSockets" );
                                this.authRefreshAttempted = false;
                                this.connectWebSockets();
                            } else {
                                this.error( "Token refresh failed - redirecting to login" );
                                this.handleAuthFailure();
                            }
                        });
                    } else {
                        // Already tried refresh - give up and redirect to login
                        this.error( "Auth error after refresh attempt - redirecting to login" );
                        this.handleAuthFailure();
                    }
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
                    this.updateStatus( "auth-status", "Auth failed", "error" );

                    // Audio WebSocket auth error - delegate to queue handler logic
                    // (Both WebSockets use same auth token, so one refresh attempt handles both)
                    if ( !this.authRefreshAttempted ) {
                        this.authRefreshAttempted = true;
                        this.log( "Attempting token refresh after audio auth error..." );

                        this.refreshAccessToken().then( ( success ) => {
                            if ( success ) {
                                this.log( "Token refreshed - reconnecting WebSockets" );
                                this.authRefreshAttempted = false;
                                this.connectWebSockets();
                            } else {
                                this.error( "Token refresh failed - redirecting to login" );
                                this.handleAuthFailure();
                            }
                        });
                    }
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
            
            // Submit to /api/push endpoint (POST request with JSON body)
            const url = `/api/push`;
            const response = await fetch( url, {
                method: 'POST',
                headers: {
                    'Authorization': this.authToken,
                    'X-Session-ID': this.queueSessionId,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    question: text,
                    websocket_id: this.queueSessionId
                })
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
            
            // Check for server errors and trigger spoken notification
            this.handleServerError( error );
            
        } finally {
            // Reset UI
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }
    
    handleServerError( error ) {
        /**
         * Detect server errors (500, 503, etc.) and create spoken notifications
         * to alert the developer to check system logs.
         */
        
        let isServerError = false;
        let errorType = 'unknown';
        
        // Detect different types of server errors
        if ( error.message && error.message.includes( '500' ) ) {
            isServerError = true;
            errorType = '500 Internal Server Error';
        } else if ( error.message && error.message.includes( '503' ) ) {
            isServerError = true;
            errorType = '503 Service Unavailable';
        } else if ( error.message && error.message.includes( '502' ) ) {
            isServerError = true;
            errorType = '502 Bad Gateway';
        }
        
        if ( isServerError ) {
            console.log( `🚨 [ERROR-NOTIFICATION] Server error detected: ${errorType}` );
            
            // Create notification data mimicking server-sent notification_queue_update
            const errorNotification = {
                id_hash: `error_${Date.now()}`,
                message: "System error detected - check logs",
                type: "alert", 
                priority: "urgent",
                source: "frontend-error-handler",
                timestamp: new Date().toISOString()
            };
            
            // Trigger the same notification flow as server-sent notifications
            this.simulateNotificationUpdate( errorNotification );
        }
    }
    
    simulateNotificationUpdate( notification ) {
        /**
         * Simulate a notification_queue_update WebSocket event locally
         * to trigger the same audio + visual feedback as server notifications.
         */
        
        console.log( `🔔 [ERROR-NOTIFICATION] Triggering local notification: ${notification.message}` );
        
        // Create envelope structure matching WebSocket notification_queue_update format
        const envelope = {
            type: "notification_queue_update",
            notification: notification,
            timestamp: notification.timestamp
        };
        
        // Call existing notification handler (reuse all existing logic)
        this.handleNotificationUpdate( envelope );
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
        
        // Store job completion data in cache for replay functionality
        this.storeJobCompletionForReplay( envelope, actualText );
        
        // Play TTS audio based on current mode
        this.playTTS( actualText || "Job completed", mode );
    }
    
    async storeJobCompletionForReplay( envelope, actualText ) {
        /**
         * Store job completion data in JobCompletionCache for replay functionality.
         * 
         * Requires:
         *     - envelope contains WebSocket job completion event data
         *     - actualText is the extracted completion response text
         *     - jobCompletionCache is initialized
         *     
         * Ensures:
         *     - Job data stored with consistent ID and metadata
         *     - Original question and response text preserved
         *     - User context and timestamp included
         *     - Cache storage errors handled gracefully
         */
        try {
            if ( !this.jobCompletionCacheInitialized || !this.jobCompletionCache ) {
                this.log( "⚠️ Job completion cache not available - skipping cache storage" );
                return;
            }
            
            // Generate consistent job ID from envelope data
            const jobId = envelope.id || envelope.job_id || envelope.timestamp || `job_${Date.now()}`;
            
            // Use original Q&A text as question context
            const questionText = this.lastQASubmissionText || "Q&A submission";
            const responseText = actualText || "Job completed";
            const timestamp = envelope.timestamp || new Date().toISOString();
            
            // Store in JobCompletionCache with full context
            await this.jobCompletionCache.store(
                jobId,
                responseText, // Primary text for cache key generation
                timestamp,
                this.currentUser, // User context for filtering
                {
                    originalQuestion: questionText,
                    submissionTime: this.lastQASubmissionTime,
                    envelope: envelope, // Store full envelope for debugging
                    ttsMode: document.getElementById( 'tts-mode' )?.value || 'instant'
                }
            );
            
            this.log( `✅ Job completion stored in cache: "${questionText}" → "${responseText.substring( 0, 50 )}..."` );
            
            // Update analytics
            const stats = this.jobCompletionCache.getAnalytics();
            this.log( `📊 Job cache stats: ${stats.cacheEntries} entries, ${stats.totalStores} stored` );
            
        } catch ( error ) {
            this.error( "Failed to store job completion for replay:", error );
            // Continue execution - cache storage failure shouldn't break TTS
        }
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
            // Check cache first if available
            if ( this.audioCacheInitialized ) {
                this.log( `Cache check for: "${text.substring( 0, 50 )}..." (Cache initialized: ${this.audioCacheInitialized})` );
                const cachedAudioBlob = await this.audioCache.checkCache( text );
                if ( cachedAudioBlob ) {
                    const stats = this.audioCache.getStats();
                    this.log( `🎯 Cache hit! Playing cached audio for: "${text.substring( 0, 30 )}..." (Hit rate: ${stats.hitRate})` );
                    await this.playAudioBlob( cachedAudioBlob );
                    return;
                }
                const stats = this.audioCache.getStats();
                this.log( `❌ Cache miss - generating TTS for: "${text.substring( 0, 30 )}..." (Hit rate: ${stats.hitRate})` );
            } else {
                this.log( `⚠️ Cache not initialized - skipping cache check for: "${text.substring( 0, 30 )}..."` );
            }
            
            // Store current text for caching after TTS generation
            this.currentTTSText = text;
            
            // Cache miss or cache not available - generate TTS as normal
            if ( mode === 'instant' ) {
                await this.playInstantTTS( text );
            } else {
                await this.playReliableTTS( text );
            }
        } catch ( error ) {
            this.error( `TTS playback failed in ${mode} mode:`, error );
        }
    }
    
    async playAudioBlob( audioUrl ) {
        return new Promise( ( resolve, reject ) => {
            const audio = this.createAudioElement();
            
            audio.onloadeddata = () => {
                this.log( "Cached audio loaded successfully" );
            };
            
            audio.onended = () => {
                this.log( "Cached audio playback completed" );
                resolve();
            };
            
            audio.onerror = ( error ) => {
                this.error( "Cached audio playback failed:", error );
                reject( error );
            };
            
            audio.src = audioUrl;
            audio.style.display = 'block';
            
            audio.play().catch( error => {
                this.log( "Auto-play prevented for cached audio, but audio is ready" );
                resolve(); // Resolve anyway as audio is ready to play
            });
        });
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
        
        // Always collect chunks for caching (both instant and reliable modes)
        this.audioChunks = this.audioChunks || [];
        this.audioChunks.push( blobData );
        
        if ( this.currentTTSMode === 'instant' ) {
            // Use sequential queue for Chrome compatibility AND collect for caching
            this.playChunkSequential( blobData );
        }
        // For reliable mode, chunks are just collected and played later in playCollectedAudio()
    }
    
    async handleAudioComplete( data ) {
        const collectedChunks = this.audioChunks ? this.audioChunks.length : 0;
        const processedChunks = this.processedChunks || 0;
        const sequentialPlayed = this.sequentialChunksPlayed || 0;
        
        if ( this.currentTTSMode === 'instant' ) {
            // For instant mode, show sequential chunks played
            this.log( `Audio streaming complete: ${data.chunks || 0} server chunks, ${sequentialPlayed} sequential chunks played, ${data.duration || 0}s` );
        } else {
            this.log( `Audio streaming complete: ${data.chunks || 0} server chunks, ${collectedChunks} collected chunks, ${data.duration || 0}s` );
        }
        
        // Cache the audio BEFORE clearing currentTTSText to avoid race condition
        if ( this.audioChunks && this.audioChunks.length > 0 ) {
            // Create audio blob for caching
            const audioBlob = new Blob( this.audioChunks, { type: 'audio/mpeg' } );
            await this.cacheGeneratedAudio( audioBlob );
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
        
        // Clear current TTS text after caching is complete
        this.currentTTSText = null;
    }
    
    async cacheGeneratedAudio( audioBlob = null ) {
        this.log( `Attempting to cache audio - Cache initialized: ${this.audioCacheInitialized}, Current TTS text: ${this.currentTTSText ? '"' + this.currentTTSText.substring( 0, 30 ) + '..."' : 'null'}` );
        
        if ( !this.audioCacheInitialized || !this.currentTTSText ) {
            this.log( "❌ Cache storage skipped - cache not initialized or no current TTS text" );
            return;
        }
        
        try {
            let blobToCache = audioBlob;
            
            // If no blob provided, create one from collected chunks (instant mode)
            if ( !blobToCache && this.audioChunks && this.audioChunks.length > 0 ) {
                blobToCache = new Blob( this.audioChunks, { type: 'audio/mpeg' } );
                this.log( `Created audio blob from ${this.audioChunks.length} chunks for caching (${blobToCache.size} bytes)` );
            }
            
            if ( blobToCache && blobToCache.size > 0 ) {
                await this.audioCache.saveToCache( this.currentTTSText, blobToCache );
                const stats = this.audioCache.getStats();
                this.log( `✅ Cached TTS audio for: "${this.currentTTSText.substring( 0, 30 )}..." (${blobToCache.size} bytes) - Cache stats: ${stats.stores} stored, ${stats.hitRate} hit rate` );
            } else {
                this.log( "❌ No valid audio blob to cache" );
            }
            
        } catch ( error ) {
            this.error( "Failed to cache generated audio:", error );
            // Continue execution even if caching fails
        }
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
        
        // Note: Audio caching now happens in handleAudioStreamingComplete() to avoid race condition

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
                // Create URL from Blob (cache now returns Blobs, not URLs)
                const audioUrl = URL.createObjectURL( audioBlob );
                const audio = new Audio( audioUrl );
                
                audio.onloadeddata = () => {
                    this.log( `Audio loaded, duration: ${audio.duration}s` );
                };
                
                audio.onplay = () => {
                    this.log( "Audio playback started" );
                    this.isPlaying = true;
                    this.currentAudio = audio;
                    // Update UI to playing state
                    if ( this.currentNotificationId ) {
                        this.updateAudioControlStates( this.currentNotificationId, 'playing' );
                    }
                };
                
                audio.onpause = () => {
                    this.log( "Audio playback paused" );
                    this.isPlaying = false;
                    // Update UI to paused state
                    if ( this.currentNotificationId ) {
                        this.updateAudioControlStates( this.currentNotificationId, 'paused' );
                    }
                };
                
                audio.onended = () => {
                    this.log( "Audio playback ended" );
                    this.isPlaying = false;
                    this.currentAudio = null;
                    // Reset UI to stopped state
                    if ( this.currentNotificationId ) {
                        this.updateAudioControlStates( this.currentNotificationId, 'stopped' );
                        this.currentNotificationId = null;
                    }
                    URL.revokeObjectURL( audioUrl );
                    resolve();
                };
                
                audio.onerror = ( error ) => {
                    this.error( "Audio playback error:", error );
                    this.isPlaying = false;
                    this.currentAudio = null;
                    // Reset UI to stopped state on error
                    if ( this.currentNotificationId ) {
                        this.updateAudioControlStates( this.currentNotificationId, 'stopped' );
                        this.currentNotificationId = null;
                    }
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
    
    async handleNotificationUpdate( envelope ) {
        this.log( "Notification queue update received:", envelope );
        
        // Handle real-time notification updates from NotificationFifoQueue
        const notification = envelope.notification || envelope.data?.notification;
        
        if ( !notification ) {
            this.log( "No notification data in WebSocket event" );
            return;
        }
        
        // Check for duplicates (same logic as old queue.js)
        const exists = this.notificationState.notifications.find( n => n.id_hash === notification.id_hash );
        if ( exists ) {
            this.log( `Notification ${notification.id_hash} already processed - ignoring duplicate` );
            return;
        }
        
        // New notification - add to local cache
        this.notificationState.notifications.push( notification );
        this.log( `Processing new notification: ${notification.type}/${notification.priority} - ${notification.message}` );
        
        // 1. ALWAYS play notification sound first based on priority
        await this.playNotificationSoundByPriority( notification.priority );
        
        // 2. Add to visual list
        this.addNotificationToList( notification );
        
        // 3. Optional TTS for high/urgent priority notifications (like old queue.js)
        if ( notification.priority === "high" || notification.priority === "urgent" ) {
            // Create formatted notification message for TTS
            let ttsMessage = `${notification.type} notification: ${notification.message}`;
            
            // Add priority prefix for urgent/high priority notifications
            if ( notification.priority === "urgent" ) {
                ttsMessage = `Urgent! ${ttsMessage}`;
            } else if ( notification.priority === "high" ) {
                ttsMessage = `Important! ${ttsMessage}`;
            }
            
            this.log( `Queuing high priority notification for TTS playback: "${ttsMessage}"` );
            
            // Add slight delay to let notification sound finish (like old queue.js)
            setTimeout( () => {
                this.playTTS( ttsMessage, 'instant' ).catch( error => {
                    this.error( 'TTS failed for high priority notification:', error );
                });
            }, 300 );
        } else {
            this.log( `Skipping TTS for ${notification.priority} priority notification` );
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
        // Return JWT access token for authentication
        if ( this.authToken ) {
            return `Bearer ${this.authToken}`;
        }

        // Fallback: try to get token from localStorage
        const tokens = this.getStoredTokens();
        if ( tokens.accessToken ) {
            return `Bearer ${tokens.accessToken}`;
        }

        // No token available - this shouldn't happen if setupAuthentication() ran correctly
        this.error( "No authentication token available" );
        this.handleAuthFailure();
        return null;
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
                // Enhanced done queue handling with structured job metadata for replay functionality
                await this.handleDoneQueueUpdate( data );
                
                // Keep original HTML rendering for backward compatibility
                document.getElementById( "done-list" ).innerHTML = this.enhancedDoneListHtml;
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
    
    async handleDoneQueueUpdate( data ) {
        /**
         * Handle done queue update with enhanced structured job metadata.
         * 
         * Requires:
         *     - data contains done_jobs (HTML list) and done_jobs_metadata (structured data)
         *     - JobCompletionCache and audio cache are initialized
         *     
         * Ensures:
         *     - Job metadata stored for replay functionality
         *     - Audio cache availability checked and indicated
         *     - Enhanced HTML generated with proper replay button states
         *     - Backward compatibility maintained with original HTML format
         */
        try {
            this.log( `Processing ${data.done_jobs?.length || 0} done jobs with metadata enhancement` );
            
            // Use structured metadata if available, fallback to HTML parsing
            const jobsMetadata = data.done_jobs_metadata || [];
            const jobsHtml = data.done_jobs || [];
            
            // Store job metadata for replay functionality
            this.doneJobsMetadata = new Map();
            
            // Process each job and check audio cache availability
            const enhancedJobs = [];
            
            for ( let i = 0; i < jobsHtml.length; i++ ) {
                const jobHtml = jobsHtml[i];
                const jobMetadata = jobsMetadata[i] || this.parseJobMetadataFromHtml( jobHtml, i );
                
                // Check if audio is available in cache
                jobMetadata.has_audio_cache = await this.checkJobAudioCacheAvailability( jobMetadata );
                
                // Store metadata for replay access
                this.doneJobsMetadata.set( jobMetadata.job_id, jobMetadata );
                
                // Generate enhanced HTML with proper replay button state
                const enhancedJobHtml = this.generateEnhancedJobHtml( jobMetadata );
                enhancedJobs.push( enhancedJobHtml );
                
                this.log( `Job ${jobMetadata.job_id}: cache=${jobMetadata.has_audio_cache ? '✓' : '✗'}` );
            }
            
            // Store enhanced HTML for rendering
            this.enhancedDoneListHtml = enhancedJobs.join( "" );
            
            this.log( `✅ Processed ${enhancedJobs.length} done jobs with replay metadata` );
            
        } catch ( error ) {
            this.error( "Error processing done queue metadata:", error );
            
            // Fallback to basic HTML rendering
            this.enhancedDoneListHtml = data.done_jobs?.join( "" ) || "";
            this.doneJobsMetadata = new Map();
        }
    }
    
    parseJobMetadataFromHtml( jobHtml, index ) {
        /**
         * Parse job metadata from HTML for backward compatibility.
         * Fallback when structured metadata not available from API.
         */
        const jobIdMatch = jobHtml.match( /id=['"]([^'"]+)['"]/ );
        const jobId = jobIdMatch ? jobIdMatch[1] : `done-job-${index}`;
        
        // Extract text content (basic parsing)
        const textMatch = jobHtml.match( />([^<]+)</);
        const text = textMatch ? textMatch[1].trim() : "Job completed";
        
        return {
            job_id: jobId,
            html: jobHtml,
            question_text: "Q&A submission",
            response_text: text,
            timestamp: new Date().toISOString(),
            user_id: this.currentUser,
            has_audio_cache: false
        };
    }
    
    async checkJobAudioCacheAvailability( jobMetadata ) {
        /**
         * Check if audio is available in TTS cache for this job.
         * 
         * Requires:
         *     - jobMetadata contains response_text
         *     - audioCache is initialized
         *     
         * Ensures:
         *     - Returns true if audio cached, false otherwise
         *     - Handles cache check errors gracefully
         */
        try {
            if ( !this.audioCacheInitialized || !this.audioCache ) {
                return false;
            }
            
            // Check TTS cache for response text
            const cachedAudio = await this.audioCache.checkCache( jobMetadata.response_text );
            
            return cachedAudio !== null;
            
        } catch ( error ) {
            this.log( `Cache check failed for job ${jobMetadata.job_id}:`, error );
            return false;
        }
    }
    
    generateEnhancedJobHtml( jobMetadata ) {
        /**
         * Generate enhanced HTML with replay and delete controls.
         * 
         * Requires:
         *     - jobMetadata contains job_id, html, has_audio_cache
         *     
         * Ensures:
         *     - Returns HTML with properly styled replay/delete buttons
         *     - Replay button state reflects audio availability
         */
        const replayOpacity = jobMetadata.has_audio_cache ? '1.0' : '0.7';
        const replayTitle = jobMetadata.has_audio_cache 
            ? "Replay cached audio" 
            : "Generate and replay audio";
        
        return jobMetadata.html.replace( 
            /(<\/li>)$/,
            `<span class="job-controls" style="margin-left: 10px;">
                <span class="replay-job" data-job-id="${jobMetadata.job_id}" 
                      style="cursor: pointer; margin-right: 8px; opacity: ${replayOpacity}; transition: opacity 0.2s; font-size: 14px;" 
                      title="${replayTitle}" role="button" tabindex="0" aria-label="Replay job audio">🔊</span>
                <span class="delete-job" data-job-id="${jobMetadata.job_id}" 
                      style="cursor: pointer; opacity: 0.6; transition: opacity 0.2s; font-size: 14px; color: #dc3545;" 
                      title="Delete job" role="button" tabindex="0" aria-label="Delete job">🗑️</span>
            </span>$1`
        );
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
    
    async replayJobAudio( jobId ) {
        /**
         * Replay audio for a completed job using cached or generated TTS.
         * 
         * Requires:
         *     - jobId exists in doneJobsMetadata
         *     - TTS system is initialized
         *     - Audio replay infrastructure is available
         *     
         * Ensures:
         *     - Plays job audio using existing TTS system
         *     - Uses cached audio when available for instant playback
         *     - Stops any currently playing audio (single session model)
         *     - Provides visual feedback during replay
         *     - Handles errors gracefully with user notification
         */
        this.log( `🔊 Job replay requested for: ${jobId}` );
        
        try {
            // Get job metadata
            const jobMetadata = this.doneJobsMetadata?.get( jobId );
            if ( !jobMetadata ) {
                this.error( `Job metadata not found for: ${jobId}` );
                alert( `Cannot replay job: ${jobId}\n\nJob data not available.` );
                return;
            }
            
            // Stop any currently playing audio (single active session model)
            if ( this.isPlaying ) {
                this.stopAudio();
                this.log( "Stopped current audio for job replay" );
            }
            
            // Get replay button for visual feedback
            const replayButton = document.querySelector( `.replay-job[data-job-id="${jobId}"]` );
            let originalContent = null;
            let originalOpacity = null;
            
            if ( replayButton ) {
                originalContent = replayButton.textContent;
                originalOpacity = replayButton.style.opacity;
                
                // Visual feedback - loading state
                replayButton.textContent = '⏳';
                replayButton.style.opacity = '1';
                replayButton.style.pointerEvents = 'none';
            }
            
            // Determine text to replay - use JobCompletionCache for correct response text
            let replayText = "Job completed";
            
            try {
                // First, try to get the actual response text from JobCompletionCache
                const cachedJob = await this.jobCompletionCache.get( jobId );
                if ( cachedJob && cachedJob.text ) {
                    replayText = cachedJob.text; // This is the actual TTS response like "It's 6:27 PM."
                    this.log( `✅ Found cached response text: "${replayText.substring( 0, 30 )}..."` );
                } else {
                    // Fallback to SolutionSnapshot data (but this contains wrong text)
                    replayText = jobMetadata.response_text || jobMetadata.question_text || "Job completed";
                    this.log( `⚠️ Using fallback text from SolutionSnapshot: "${replayText.substring( 0, 30 )}..."` );
                }
            } catch ( error ) {
                this.log( `❌ Failed to get cached response, using fallback: ${error}` );
                replayText = jobMetadata.response_text || jobMetadata.question_text || "Job completed";
            }
            
            this.log( `🔊 Replaying job audio: "${replayText.substring( 0, 50 )}..." (cached: ${jobMetadata.has_audio_cache})` );
            
            // Use current TTS mode from UI
            const currentMode = document.getElementById( 'tts-mode' )?.value || 'instant';
            
            // Play using existing TTS infrastructure
            await this.playTTS( replayText, currentMode );
            
            this.log( `✅ Job replay completed for: ${jobId}` );
            
            // Success feedback
            if ( replayButton ) {
                replayButton.textContent = '✅';
                setTimeout( () => {
                    replayButton.textContent = originalContent;
                    replayButton.style.opacity = originalOpacity;
                    replayButton.style.pointerEvents = 'auto';
                }, 1000 );
            }
            
        } catch ( error ) {
            this.error( `Job replay failed for ${jobId}:`, error );
            
            // Error feedback
            const replayButton = document.querySelector( `.replay-job[data-job-id="${jobId}"]` );
            if ( replayButton ) {
                replayButton.textContent = '❌';
                setTimeout( () => {
                    replayButton.textContent = '🔊';
                    replayButton.style.opacity = '0.7';
                    replayButton.style.pointerEvents = 'auto';
                }, 2000 );
            }
            
            // User notification
            alert( `Job replay failed: ${jobId}\n\nError: ${error.message}` );
        }
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
        
        // Process message for project prefix formatting (e.g., [LUPIN] -> LUPIN:)
        let processedMessage = message;
        const prefixMatch = message.match( /^\[([A-Z]+)\]\s*(.*)$/ );
        if ( prefixMatch ) {
            const prefix = prefixMatch[1];  // Extract "LUPIN"
            const remainingMessage = prefixMatch[2];  // Extract remaining message
            processedMessage = `<strong><em>${prefix}:</em></strong> ${remainingMessage}`;
        }
        
        // Truncate long messages for list display (use processed message)
        const displayMessage = processedMessage.length > 80 ? processedMessage.substring( 0, 77 ) + "..." : processedMessage;
        
        // Use the server-provided id_hash for proper identification
        const notificationId = data.id_hash || `notification_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        this.log( `Adding notification to list with ID: "${notificationId}"` );
        
        // Create list item with styling from original queue.html
        const listItem = document.createElement( "li" );
        listItem.id = notificationId;
        listItem.style.marginBottom = "8px";
        listItem.style.padding = "5px";
        listItem.style.border = "1px solid transparent";
        listItem.style.borderLeft = `3px solid ${priorityColor}`;
        listItem.style.backgroundColor = "#f8f9fa";
        listItem.style.transition = "border 0.2s ease";
        listItem.style.cursor = "default";
        
        // Add hover effect for entire notification border
        listItem.addEventListener( 'mouseenter', () => {
            listItem.style.border = `1px solid ${priorityColor}`;
            listItem.style.borderLeft = `3px solid ${priorityColor}`;
        });
        
        listItem.addEventListener( 'mouseleave', () => {
            listItem.style.border = "1px solid transparent";
            listItem.style.borderLeft = `3px solid ${priorityColor}`;
        });
        listItem.innerHTML = `
            <div style="display: flex; align-items: center; font-size: 12px;">
                <span style="margin-right: 8px; color: ${priorityColor}; font-weight: bold;">${priorityEmoji}</span>
                <span style="color: #666; margin-right: 10px; font-size: 10px; font-style: italic; font-weight: bold;">${time}</span>
                <span style="color: ${priorityColor}; font-weight: bold; margin-right: 5px;">${type.toUpperCase()}</span>
                <span style="color: ${priorityColor}; font-size: 10px; margin-right: 10px;">(${priority})</span>
                <span style="flex: 1; color: #333;" title="${message}">${displayMessage}</span>
                <span class="audio-control-panel" data-notification-id="${notificationId}" style="margin-left: auto; margin-right: 8px; display: flex; gap: 3px; align-items: center;">
                    <span class="audio-restart-btn audio-control-enabled" 
                          style="cursor: pointer; opacity: 1.0; transition: opacity 0.2s; font-size: 14px;" 
                          title="Restart notification audio from beginning" role="button" tabindex="0" aria-label="Restart notification audio from beginning">⏮️</span>
                    <span class="audio-resume-btn audio-control-disabled" 
                          style="cursor: not-allowed; opacity: 0.4; transition: opacity 0.2s; font-size: 14px;" 
                          title="Resume notification audio" role="button" tabindex="-1" aria-label="Resume notification audio">▶️</span>
                    <span class="audio-pause-btn audio-control-disabled" 
                          style="cursor: not-allowed; opacity: 0.4; transition: opacity 0.2s; font-size: 14px;" 
                          title="Pause notification audio" role="button" tabindex="-1" aria-label="Pause notification audio">⏸️</span>
                    <span class="audio-stop-btn audio-control-disabled" 
                          style="cursor: not-allowed; opacity: 0.4; transition: opacity 0.2s; font-size: 14px;" 
                          title="Stop notification audio" role="button" tabindex="-1" aria-label="Stop notification audio">⏹️</span>
                </span>
                <span class="delete-notification" data-notification-id="${notificationId}" 
                      style="cursor: pointer; opacity: 0.6; transition: opacity 0.2s; font-size: 14px; color: #dc3545; margin-left: 4px;" 
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
        
        // Add event listeners for audio control panel and delete button
        const restartButton = listItem.querySelector( '.audio-restart-btn' );
        const resumeButton = listItem.querySelector( '.audio-resume-btn' );
        const pauseButton = listItem.querySelector( '.audio-pause-btn' );
        const stopButton = listItem.querySelector( '.audio-stop-btn' );
        const deleteButton = listItem.querySelector( '.delete-notification' );
        
        if ( restartButton ) {
            this.addAudioControlListeners( restartButton, 'restart', notificationId );
        }
        if ( resumeButton ) {
            this.addAudioControlListeners( resumeButton, 'resume', notificationId );
        }
        if ( pauseButton ) {
            this.addAudioControlListeners( pauseButton, 'pause', notificationId );
        }
        if ( stopButton ) {
            this.addAudioControlListeners( stopButton, 'stop', notificationId );
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
    
    addAudioControlListeners( button, action, notificationId ) {
        // Add listeners to all buttons, but only respond when enabled
        
        // Mouse click
        button.addEventListener( 'click', ( e ) => {
            e.stopPropagation();
            if ( button.classList.contains( 'audio-control-enabled' ) ) {
                this.handleAudioControl( action, notificationId );
            }
        });
        
        // Keyboard support (Enter/Space)
        button.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' || e.key === ' ' ) {
                e.preventDefault();
                e.stopPropagation();
                if ( button.classList.contains( 'audio-control-enabled' ) ) {
                    this.handleAudioControl( action, notificationId );
                }
            }
        });
        
        // Hover effects only for enabled buttons
        button.addEventListener( 'mouseenter', () => {
            if ( button.classList.contains( 'audio-control-enabled' ) ) {
                button.style.transform = 'scale(1.1)';
            }
        });
        
        button.addEventListener( 'mouseleave', () => {
            if ( button.classList.contains( 'audio-control-enabled' ) ) {
                button.style.transform = 'scale(1)';
            }
        });
    }
    
    async handleAudioControl( action, notificationId ) {
        this.log( `Audio control: ${action} for notification ${notificationId}` );
        
        switch ( action ) {
            case 'restart':
                // If another notification is playing, stop it first
                if ( this.currentNotificationId && this.currentNotificationId !== notificationId ) {
                    this.stopCurrentAudio();
                }
                // Start playing this notification from beginning
                await this.playNotificationAudio( notificationId, true ); // true = restart from beginning
                break;
                
            case 'resume':
                if ( this.currentAudio && this.currentNotificationId === notificationId ) {
                    // Resume from current position
                    this.currentAudio.play();
                    this.updateAudioControlStates( notificationId, 'playing' );
                }
                break;
                
            case 'pause':
                if ( this.currentAudio && this.currentNotificationId === notificationId ) {
                    this.currentAudio.pause();
                    this.updateAudioControlStates( notificationId, 'paused' );
                }
                break;
                
            case 'stop':
                if ( this.currentNotificationId === notificationId ) {
                    this.stopCurrentAudio();
                }
                break;
        }
    }
    
    stopCurrentAudio() {
        if ( this.currentAudio ) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
        
        if ( this.currentNotificationId ) {
            // Reset UI to stopped state
            this.updateAudioControlStates( this.currentNotificationId, 'stopped' );
            this.currentNotificationId = null;
        }
        
        this.isPlaying = false;
        this.log( "Audio stopped and reset" );
    }
    
    updateAudioControlStates( notificationId, audioState ) {
        // Find all notification control panels and reset them to default
        const allPanels = document.querySelectorAll( '.audio-control-panel' );
        allPanels.forEach( panel => {
            const panelNotificationId = panel.dataset.notificationId;
            if ( panelNotificationId !== notificationId ) {
                // Reset other notifications to default (stopped) state
                this.setControlPanelState( panel, 'stopped' );
            }
        });
        
        // Update the target notification's control panel
        const targetPanel = document.querySelector( `.audio-control-panel[data-notification-id="${notificationId}"]` );
        if ( targetPanel ) {
            this.setControlPanelState( targetPanel, audioState );
        }
    }
    
    setControlPanelState( panel, audioState ) {
        const restartBtn = panel.querySelector( '.audio-restart-btn' );
        const resumeBtn = panel.querySelector( '.audio-resume-btn' );
        const pauseBtn = panel.querySelector( '.audio-pause-btn' );
        const stopBtn = panel.querySelector( '.audio-stop-btn' );
        
        // Remove all existing state classes
        [restartBtn, resumeBtn, pauseBtn, stopBtn].forEach( btn => {
            if ( btn ) {
                btn.classList.remove( 'audio-control-enabled', 'audio-control-disabled' );
            }
        });
        
        switch ( audioState ) {
            case 'stopped':
                // [⏮️ enabled] [▶️ disabled] [⏸️ disabled] [⏹️ disabled]
                restartBtn?.classList.add( 'audio-control-enabled' );
                resumeBtn?.classList.add( 'audio-control-disabled' );
                pauseBtn?.classList.add( 'audio-control-disabled' );
                stopBtn?.classList.add( 'audio-control-disabled' );
                this.updateButtonVisualState( restartBtn, true );
                this.updateButtonVisualState( resumeBtn, false );
                this.updateButtonVisualState( pauseBtn, false );
                this.updateButtonVisualState( stopBtn, false );
                break;
                
            case 'playing':
                // [⏮️ disabled] [▶️ disabled] [⏸️ enabled] [⏹️ enabled]
                restartBtn?.classList.add( 'audio-control-disabled' );
                resumeBtn?.classList.add( 'audio-control-disabled' );
                pauseBtn?.classList.add( 'audio-control-enabled' );
                stopBtn?.classList.add( 'audio-control-enabled' );
                this.updateButtonVisualState( restartBtn, false );
                this.updateButtonVisualState( resumeBtn, false );
                this.updateButtonVisualState( pauseBtn, true );
                this.updateButtonVisualState( stopBtn, true );
                break;
                
            case 'paused':
                // [⏮️ enabled] [▶️ enabled] [⏸️ disabled] [⏹️ enabled]
                restartBtn?.classList.add( 'audio-control-enabled' );
                resumeBtn?.classList.add( 'audio-control-enabled' );
                pauseBtn?.classList.add( 'audio-control-disabled' );
                stopBtn?.classList.add( 'audio-control-enabled' );
                this.updateButtonVisualState( restartBtn, true );
                this.updateButtonVisualState( resumeBtn, true );
                this.updateButtonVisualState( pauseBtn, false );
                this.updateButtonVisualState( stopBtn, true );
                break;
        }
    }
    
    updateButtonVisualState( button, enabled ) {
        if ( !button ) return;
        
        if ( enabled ) {
            button.style.opacity = '1.0';
            button.style.cursor = 'pointer';
            button.setAttribute( 'tabindex', '0' );
        } else {
            button.style.opacity = '0.4';
            button.style.cursor = 'not-allowed';
            button.setAttribute( 'tabindex', '-1' );
        }
    }
    
    async playNotificationAudio( notificationId, restart = false ) {
        const listItem = document.getElementById( notificationId );
        if ( !listItem || !listItem.notificationData ) {
            this.error( `No notification data found for ID: ${notificationId}` );
            return;
        }
        
        const { ttsMessage, type, priority } = listItem.notificationData;
        
        try {
            // Set current notification tracking
            this.currentNotificationId = notificationId;
            
            // Update UI to playing state
            this.updateAudioControlStates( notificationId, 'playing' );
            
            // Highlight the notification being played
            listItem.style.transition = "background-color 0.3s ease";
            listItem.style.backgroundColor = "#e3f2fd"; // Light blue highlight
            
            this.log( `${restart ? 'Restarting' : 'Playing'} notification audio: "${ttsMessage}"` );
            
            // Use the current TTS mode (instant/reliable) from the UI
            const currentMode = document.getElementById( 'tts-mode' )?.value || 'instant';
            
            // Use playTTS() to ensure cache checking and proper currentTTSText handling
            await this.playTTS( ttsMessage, currentMode );
            
            // If we have currentAudio and this is a restart, reset position to beginning
            if ( restart && this.currentAudio ) {
                this.currentAudio.currentTime = 0;
            }
            
            this.log( `Successfully ${restart ? 'restarted' : 'played'} ${type}/${priority} notification` );
            
        } catch ( error ) {
            this.error( `Failed to ${restart ? 'restart' : 'play'} notification audio:`, error );
            // Reset UI state on error
            this.updateAudioControlStates( notificationId, 'stopped' );
            this.currentNotificationId = null;
        } finally {
            // Always restore the notification background after a delay
            setTimeout( () => {
                if ( listItem ) {
                    listItem.style.backgroundColor = '';
                }
            }, 1000 );
        }
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
        
        // Store original background color for restoration in finally block
        const originalBackground = listItem.style.backgroundColor;
        
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
            listItem.style.transition = "background-color 0.3s ease";
            listItem.style.backgroundColor = "#e3f2fd"; // Light blue highlight
            
            this.log( `Replaying notification audio: "${ttsMessage}"` );
            
            // **IMPROVEMENT**: Direct integration with our TTS system instead of external queue
            // Use the current TTS mode (instant/reliable) from the UI
            const currentMode = document.getElementById( 'tts-mode' )?.value || 'instant';
            
            // Use playTTS() to ensure cache checking and proper currentTTSText handling
            await this.playTTS( ttsMessage, currentMode );
            
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
            
            // Add manual refresh capability for debugging
            window.refreshQueues = () => {
                this.log( "🔄 Manual queue refresh triggered" );
                Promise.all([
                    this.updateQueueLists( "todo" ),
                    this.updateQueueLists( "run" ),
                    this.updateQueueLists( "done" ),
                    this.updateQueueLists( "dead" )
                ]);
            };
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