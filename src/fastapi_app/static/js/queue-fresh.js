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

        // TTS Mode Constants
        this.TTS_MODE_INSTANT = 'instant';
        this.TTS_MODE_RELIABLE = 'reliable';
        this.TTS_MODE_DEFAULT = this.TTS_MODE_RELIABLE;  // Default to reliable for better browser compatibility

        // WebSocket connections
        this.queueWS = null;
        this.audioWS = null;
        
        // Session management
        this.queueSessionId = null;
        this.audioSessionId = null;
        
        // Authentication
        this.currentUser = null;
        this.authToken = null;

        // ========================================
        // TOKEN REFRESH CONFIGURATION
        // ========================================

        // Configuration constants (populated from /api/config/client)
        // These values come from server on startup - NO hardcoded defaults here
        this.TOKEN_REFRESH_CHECK_INTERVAL_MS = null;    // How often to check (periodic monitor)
        this.TOKEN_EXPIRY_THRESHOLD_SECS = null;        // When to trigger refresh (< N secs to expiry)
        this.TOKEN_REFRESH_DEDUP_WINDOW_MS = null;      // Prevent duplicate refreshes (within N ms)
        this.WEBSOCKET_HEARTBEAT_INTERVAL_SECS = null;  // For reference/logging only

        // Token refresh state tracking
        this.tokenRefreshIntervalHandle = null;         // setInterval handle (for cleanup)
        this.lastTokenRefresh_ms = null;                // Timestamp of last refresh (for deduplication)

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

        // Timing metrics for UI display
        this.metricsSubmitTime = null;      // When user clicks submit
        this.metricsTextTime = null;        // When text response received
        this.metricsTTSStartTime = null;    // When TTS request begins
        this.metricsFirstAudioTime = null;  // When first audio plays
        
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
        this.QUEUE_FILTER_PREF_KEY = 'fresh_queue_filter_preference';  // NEW: Filter mode storage
        this.CURRENT_VERSION = '1.1.1'; // Increment to invalidate old cache

        // User role and filter state
        this.userRoles = [];  // NEW: User's roles from JWT
        this.isAdmin = false;  // NEW: Quick admin check
        this.queueFilterMode = 'own';  // NEW: 'own' or 'all' (admin only)

        // Phase 2.2 SSE - Action Required notifications state
        this.actionRequiredNotifications = new Map();  // notification_id → notification data + UI state
        this.countdownTimers = new Map();  // notification_id → setInterval handle
        this.keyboardListenerActive = false;  // Track if keyboard listener is attached

        // ========================================
        // SENDER-AWARE NOTIFICATION GROUPING (Phase 5)
        // ========================================

        // Sender groups: Map<sender_id, { notifications: [], collapsed: boolean, lastActivity: Date }>
        this.senderGroups = new Map();

        // Default sender for notifications without sender_id
        this.UNKNOWN_SENDER = "claude.code@unknown.deepily.ai";

        // History window configuration (activity-anchored loading)
        this.HISTORY_WINDOW_KEY = 'fresh_queue_history_window';
        this.historyWindowHours = parseInt( localStorage.getItem( this.HISTORY_WINDOW_KEY ) ) || 24;
        this.WINDOW_OPTIONS = [
            { label: 'Last 24 hours', hours: 24 },
            { label: 'Last 2 days',   hours: 48 },
            { label: 'Last week',     hours: 168 },
            { label: 'Last month',    hours: 720 },
            { label: 'All time',      hours: null }
        ];

        // WebSocket Health Monitor - Periodic reconnection during work hours
        this.healthCheckIntervalHandle = null;  // Timer reference for health check interval
        this.HEALTH_CHECK_INTERVAL_MS = 90000;  // 90 seconds (1.5 minutes)
        this.WORK_HOURS_START = 8;              // 8 AM
        this.WORK_HOURS_END = 24;               // Midnight (12 AM next day)

        // STT for Q&A input
        this.qaAudioRecorder = null;
        this.qaRecordingInterval = null;
        this.qaRecordingCancelListener = null;

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

            // Initialize filter UI based on user role
            this.initializeFilterUI();

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

            // Initialize history dropdown UI
            this.initializeHistoryDropdown();

            // Connect WebSockets
            await this.connectWebSockets();

            // Load conversation history (after auth is complete)
            await this.loadConversationHistory();

            // Auto-focus STT button for spacebar activation
            document.getElementById( 'qa-stt-button' ).focus();

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
                ttsMode.value = this.TTS_MODE_RELIABLE;
                
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
        this.userRoles = payload.roles || [];  // Extract roles array
        this.isAdmin = this.userRoles.includes( 'admin' );  // Check admin status

        // Update UI
        this.updateElement( "user-display", this.currentUser );
        this.updateStatus( "auth-status", "Authenticated", "success" );

        // NEW: Fetch client config (requires valid token)
        // Must be called AFTER token validation (endpoint requires JWT auth)
        await this.fetchClientConfig();

        // NEW: Start token refresh monitor
        // Now that we have config values, start monitoring token freshness
        this.startTokenRefreshMonitor();

        // NEW: Start WebSocket health monitor
        // Periodic health checking during work hours for automatic reconnection
        this.startWebSocketHealthMonitor();

        this.log( `✓ Authentication setup complete for user: ${this.currentUser} (admin: ${this.isAdmin}, config fetched, monitors started)` );
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

    async fetchClientConfig() {
        /**
         * Fetch client configuration from authenticated server endpoint.
         * Populates timing constants for token refresh monitoring.
         *
         * Requires:
         *     - this.authToken is valid (called AFTER setupAuthentication)
         *     - Server /api/config/client endpoint available
         *
         * Ensures:
         *     - All TOKEN_* constants populated with server values
         *     - Falls back to hardcoded defaults if fetch fails
         *     - Logs configuration values for debugging
         *     - Sends JWT authentication header (endpoint protected)
         *
         * Raises:
         *     - None (handles errors gracefully with fallback defaults)
         */
        try {
            // Authenticated API call (requires valid JWT token)
            const response = await fetch( '/api/config/client', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader()  // JWT authentication required
                }
            });

            if ( response.ok ) {
                const config = await response.json();

                // Populate constants from server configuration
                this.TOKEN_REFRESH_CHECK_INTERVAL_MS = config.token_refresh_check_interval_ms;
                this.TOKEN_EXPIRY_THRESHOLD_SECS = config.token_expiry_threshold_secs;
                this.TOKEN_REFRESH_DEDUP_WINDOW_MS = config.token_refresh_dedup_window_ms;
                this.WEBSOCKET_HEARTBEAT_INTERVAL_SECS = config.websocket_heartbeat_interval_secs;

                // Log configuration for debugging
                this.log( "✓ Client config loaded from server:", {
                    refresh_check_interval: `${config.token_refresh_check_interval_ms / 60000} mins`,
                    expiry_threshold: `${config.token_expiry_threshold_secs / 60} mins`,
                    dedup_window: `${config.token_refresh_dedup_window_ms / 1000} secs`,
                    heartbeat_interval: `${config.websocket_heartbeat_interval_secs} secs`
                });

            } else if ( response.status === 401 ) {
                // Authentication failed (shouldn't happen after setupAuthentication)
                this.error( "Config fetch failed: 401 Unauthorized (token invalid?)" );
                throw new Error( "Unauthorized" );

            } else {
                throw new Error( `Config endpoint returned ${response.status}` );
            }

        } catch ( error ) {
            // Fallback to hardcoded defaults if config fetch fails
            this.error( "Failed to fetch client config, using defaults:", error );

            // Conservative defaults (same as baseline config)
            this.TOKEN_REFRESH_CHECK_INTERVAL_MS = 10 * 60 * 1000;  // 10 minutes
            this.TOKEN_EXPIRY_THRESHOLD_SECS = 5 * 60;              // 5 minutes
            this.TOKEN_REFRESH_DEDUP_WINDOW_MS = 60 * 1000;         // 60 seconds
            this.WEBSOCKET_HEARTBEAT_INTERVAL_SECS = 30;            // 30 seconds

            this.log( "⚠️ Using default client config (server fetch failed)" );
        }
    }

    async checkAndRefreshToken( source = "manual" ) {
        /**
         * Check token expiration and refresh proactively if needed.
         * Uses explicit unit suffixes to prevent conversion errors.
         * Implements deduplication to prevent rapid-fire refreshes.
         *
         * Requires:
         *     - this.authToken exists and is valid
         *     - TOKEN_* constants initialized via fetchClientConfig()
         *
         * Ensures:
         *     - Refreshes token if < threshold seconds to expiry
         *     - Skips refresh if refreshed within dedup window
         *     - Updates lastTokenRefresh_ms on successful refresh
         *     - Logs all refresh decisions for debugging
         *
         * Args:
         *     source: String describing trigger source for logging:
         *         - "periodic": Triggered by setInterval periodic monitor
         *         - "heartbeat": Triggered by WebSocket sys_ping handler
         *         - "manual": Manually triggered (testing/debugging)
         */

        // Skip if no auth token
        if ( !this.authToken ) {
            return;
        }

        // Deduplication: Skip if recently refreshed
        if ( this.lastTokenRefresh_ms ) {
            const timeSinceRefresh_ms = Date.now() - this.lastTokenRefresh_ms;

            if ( timeSinceRefresh_ms < this.TOKEN_REFRESH_DEDUP_WINDOW_MS ) {
                const timeSinceRefresh_secs = Math.round( timeSinceRefresh_ms / 1000 );
                this.log( `Token refresh skipped (${source}): refreshed ${timeSinceRefresh_secs}s ago` );
                return;
            }
        }

        // Parse token to get expiration claim
        const payload = this.parseJWTPayload( this.authToken );
        if ( !payload.exp ) {
            this.error( "Token has no expiration claim - cannot check freshness" );
            return;
        }

        // Calculate time until expiry (both in seconds for comparison)
        const now_secs = Math.floor( Date.now() / 1000 );
        const timeUntilExpiry_secs = payload.exp - now_secs;

        // Refresh if below threshold (comparing seconds to seconds - units match ✅)
        if ( timeUntilExpiry_secs < this.TOKEN_EXPIRY_THRESHOLD_SECS ) {
            const timeUntilExpiry_mins = Math.round( timeUntilExpiry_secs / 60 );
            this.log( `⏰ Proactive token refresh (${source}): ${timeUntilExpiry_mins} minutes until expiry` );

            const refreshed = await this.refreshAccessToken();

            if ( refreshed ) {
                // Update timestamp and token reference
                this.lastTokenRefresh_ms = Date.now();
                this.authToken = this.getStoredTokens().accessToken;
                this.log( `✓ Token proactively refreshed (${source})` );
            } else {
                this.error( `✗ Token refresh failed (${source})` );
            }
        } else {
            const timeUntilExpiry_mins = Math.round( timeUntilExpiry_secs / 60 );
            this.log( `Token fresh (${source}): ${timeUntilExpiry_mins} minutes remaining` );
        }
    }

    startTokenRefreshMonitor() {
        /**
         * Start periodic token refresh monitoring using setInterval.
         *
         * Requires:
         *     - TOKEN_REFRESH_CHECK_INTERVAL_MS initialized via fetchClientConfig()
         *
         * Ensures:
         *     - Clears any existing interval before starting new one (prevents duplicates)
         *     - Sets up periodic checkAndRefreshToken() calls
         *     - Logs monitor status for debugging
         */

        // Clear any existing interval (prevents duplicate monitors)
        this.stopTokenRefreshMonitor();

        // Start periodic token check
        this.tokenRefreshIntervalHandle = setInterval(
            () => this.checkAndRefreshToken( "periodic" ),
            this.TOKEN_REFRESH_CHECK_INTERVAL_MS
        );

        const interval_mins = this.TOKEN_REFRESH_CHECK_INTERVAL_MS / 60000;
        this.log( `✓ Token refresh monitor started (${interval_mins}-minute interval)` );
    }

    stopTokenRefreshMonitor() {
        /**
         * Stop periodic token refresh monitoring.
         *
         * Ensures:
         *     - Clears setInterval if active
         *     - Resets interval handle to null
         *     - Logs monitor status for debugging
         */

        if ( this.tokenRefreshIntervalHandle ) {
            clearInterval( this.tokenRefreshIntervalHandle );
            this.tokenRefreshIntervalHandle = null;
            this.log( "Token refresh monitor stopped" );
        }
    }

    startWebSocketHealthMonitor() {
        /**
         * Start periodic WebSocket health monitoring during work hours.
         *
         * Purpose:
         *     - Automatically detect and reconnect disconnected WebSockets
         *     - Only active during work hours (8 AM - Midnight)
         *     - Handles overnight server restarts gracefully
         *
         * Ensures:
         *     - Clears any existing interval first
         *     - Sets up 90-second periodic health checks
         *     - Updates UI status indicator
         */

        this.stopWebSocketHealthMonitor();  // Clear existing interval if any

        this.healthCheckIntervalHandle = setInterval(
            () => this.checkWebSocketHealth(),
            this.HEALTH_CHECK_INTERVAL_MS
        );

        this.updateHealthStatus( "Monitoring (90s interval)", "status-info" );
        this.log( "WebSocket health monitor started (90-second interval, work hours 8 AM - Midnight)" );
    }

    stopWebSocketHealthMonitor() {
        /**
         * Stop WebSocket health monitoring.
         *
         * Ensures:
         *     - Clears setInterval if active
         *     - Resets interval handle to null
         *     - Updates UI status
         */

        if ( this.healthCheckIntervalHandle ) {
            clearInterval( this.healthCheckIntervalHandle );
            this.healthCheckIntervalHandle = null;
            this.updateHealthStatus( "Stopped", "status-warning" );
            this.log( "WebSocket health monitor stopped" );
        }
    }

    checkWebSocketHealth() {
        /**
         * Periodic health check for WebSocket connections.
         *
         * Behavior:
         *     1. Check if current time is within work hours (8 AM - Midnight)
         *     2. If outside work hours: Skip check, update UI to show "Off-hours"
         *     3. If inside work hours: Check both WebSocket states
         *     4. If disconnected: Reset retry counter and trigger reconnection
         *     5. If connected: Update UI to show "Healthy"
         *
         * Ensures:
         *     - No reconnection attempts during off-hours (Midnight - 8 AM)
         *     - Automatic recovery from server restarts
         *     - Visual feedback in UI status indicator
         */

        // Check if we're in work hours (8 AM - Midnight)
        const now = new Date();
        const hour = now.getHours();

        if ( hour < this.WORK_HOURS_START || hour >= this.WORK_HOURS_END ) {
            // Outside work hours - skip check
            this.updateHealthStatus( "Off-hours (Midnight - 8 AM)", "status-info" );
            return;
        }

        // Check queue WebSocket state
        const queueNeedsReconnect = !this.queueWS || this.queueWS.readyState !== WebSocket.OPEN;

        // Check audio WebSocket state
        const audioNeedsReconnect = !this.audioWS || this.audioWS.readyState !== WebSocket.OPEN;

        if ( queueNeedsReconnect || audioNeedsReconnect ) {
            // Disconnection detected
            this.log( `Health check: Disconnected WebSockets detected (queue=${queueNeedsReconnect}, audio=${audioNeedsReconnect})` );
            this.updateHealthStatus( "Reconnecting...", "status-warning" );

            // Reset retry counter to give reconnection a fresh start
            // (scheduleReconnect gives up after 5 attempts, but health monitor provides unlimited retries)
            this.connectionRetries = 0;

            // Trigger existing reconnection logic
            this.scheduleReconnect();
        } else {
            // Both WebSockets healthy
            this.updateHealthStatus( `✓ Healthy (checked ${now.toLocaleTimeString()})`, "status-success" );
        }
    }

    updateHealthStatus( text, statusClass ) {
        /**
         * Update WebSocket health monitor status in UI.
         *
         * Requires:
         *     - text: Status message to display
         *     - statusClass: CSS class for styling (status-success, status-warning, status-info)
         *
         * Ensures:
         *     - Updates #ws-health-status element text and class
         *     - Handles missing element gracefully (no error thrown)
         */

        const element = document.getElementById( "ws-health-status" );
        if ( element ) {
            element.textContent = text;
            element.className = statusClass;
        }
    }

    async ensureValidToken() {
        /**
         * Ensure authentication token is valid before making API calls.
         * Automatically refreshes token if expired.
         *
         * Requires:
         *     - refreshAccessToken() method available
         *     - localStorage contains refresh token
         *
         * Ensures:
         *     - this.authToken contains valid, non-expired token
         *     - Token is refreshed if expired
         *
         * Raises:
         *     - Error if token refresh fails
         *
         * Performance:
         *     - Fast path (valid token): ~1-2ms (local check)
         *     - Slow path (expired token): ~50-200ms (network refresh)
         */
        const startTime = performance.now();

        // Check if token exists and is valid
        if ( !this.authToken || this.isTokenExpired( this.authToken ) ) {
            const wasExpired = this.authToken && this.isTokenExpired( this.authToken );

            if ( wasExpired ) {
                this.log( "⚠️ Token expired - refreshing before API call..." );
            } else {
                this.log( "⚠️ Token missing - refreshing before API call..." );
            }

            // Attempt to refresh token
            const refreshed = await this.refreshAccessToken();

            if ( !refreshed ) {
                const error = "Token refresh failed - cannot proceed with API call";
                this.error( error );
                this.handleAuthFailure();
                throw new Error( error );
            }

            // Update token reference with fresh token
            const tokens = this.getStoredTokens();
            this.authToken = tokens.accessToken;

            const elapsed = ( performance.now() - startTime ).toFixed( 1 );
            this.log( `✓ Token refreshed successfully (${elapsed}ms)` );
        } else {
            const elapsed = ( performance.now() - startTime ).toFixed( 1 );
            this.log( `✓ Token valid (checked in ${elapsed}ms)` );
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

        // NEW: Stop token refresh monitor
        this.stopTokenRefreshMonitor();

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

        // NEW: Stop token refresh monitor
        this.stopTokenRefreshMonitor();

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

        // Q&A STT button click
        document.getElementById( 'qa-stt-button' ).addEventListener( 'click', () => {
            this.handleQASTTButtonClick();
        });

        // Ctrl+R shortcut for Q&A STT recording
        document.addEventListener( 'keydown', ( e ) => {
            if ( e.ctrlKey && e.key === 'r' ) {
                e.preventDefault();  // Prevent browser refresh
                this.handleQASTTButtonClick();
            }
        });

        // Test buttons
        document.getElementById( 'test-instant-tts' ).addEventListener( 'click', () => {
            this.testTTS( this.TTS_MODE_INSTANT );
        });
        
        document.getElementById( 'test-reliable-tts' ).addEventListener( 'click', () => {
            this.testTTS( this.TTS_MODE_RELIABLE );
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

        // Queue filter toggle (admin only - buttons may not exist for regular users)
        const filterOwnBtn = document.getElementById( 'filter-own-jobs' );
        const filterAllBtn = document.getElementById( 'filter-all-jobs' );

        if ( filterOwnBtn && filterAllBtn ) {
            filterOwnBtn.addEventListener( 'click', () => this.setFilterMode( 'own' ) );
            filterAllBtn.addEventListener( 'click', () => this.setFilterMode( 'all' ) );
            this.log( "Filter button event listeners added" );
        }

        // Clear all notifications button
        const clearAllNotificationsBtn = document.getElementById( 'clear-all-notifications' );
        if ( clearAllNotificationsBtn ) {
            clearAllNotificationsBtn.addEventListener( 'click', ( e ) => {
                e.stopPropagation(); // Prevent section toggle when clicking button
                this.clearAllNotifications();
            });
            this.log( "Clear all notifications button event listener added" );
        }

        // NEW: Window beforeunload - cleanup on page close/reload
        window.addEventListener( 'beforeunload', () => {
            this.stopTokenRefreshMonitor();
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
            // Ensure token is valid before API call (auto-refresh if expired)
            await this.ensureValidToken();

            const response = await fetch( '/api/get-session-id', {
                method: 'GET',
                headers: {
                    'Authorization': this.getAuthHeader()
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
                "notification_responded",  // Phase 2.2 SSE - multi-device sync
                "notification_expired",    // Phase 2.2 SSE - timeout handling
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

                case "notification_responded":
                    // Phase 2.2 SSE - Multi-device sync when response submitted
                    this.handleNotificationResponded( envelope );
                    break;

                case "notification_expired":
                    // Phase 2.2 SSE - Notification timeout/expiration
                    this.handleNotificationExpired( envelope );
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
    
    async handlePing( connectionType ) {
        const ws = connectionType === "queue" ? this.queueWS : this.audioWS;

        // Send pong response (existing behavior)
        if ( ws && ws.readyState === WebSocket.OPEN ) {
            const pongMessage = {
                type: "sys_pong",
                timestamp: new Date().toISOString()
            };
            ws.send( JSON.stringify( pongMessage ) );
        }

        // NEW: Piggyback token freshness check on heartbeat
        // Only check on queue heartbeat to avoid duplicate checks
        // (We have TWO WebSockets: queue + audio, but only need one check)
        if ( connectionType === "queue" ) {
            await this.checkAndRefreshToken( "heartbeat" );
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

        // DEBOUNCE: Prevent rapid-fire double submissions
        const now = Date.now();
        const debounceMs = 2000;  // 2 second cooldown between submissions
        if ( this._lastSubmitTime && ( now - this._lastSubmitTime ) < debounceMs ) {
            this.log( `[DEBOUNCE] Ignoring rapid submission (${now - this._lastSubmitTime}ms since last)` );
            return;
        }
        this._lastSubmitTime = now;

        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            this.updateElement( "response-text", "Submitting Q&A..." );
            
            this.log( `Submitting Q&A: ${text}` );
            
            // Track for job completion debugging
            this.lastQASubmissionTime = Date.now();
            this.lastQASubmissionText = text;

            // Reset and capture timing metrics for UI display
            this.metricsSubmitTime = Date.now();
            this.metricsTextTime = null;
            this.metricsTTSStartTime = null;
            this.metricsFirstAudioTime = null;
            this.resetMetricsDisplay();

            // Ensure token is valid before API call (auto-refresh if expired)
            await this.ensureValidToken();

            // Submit to /api/push endpoint (POST request with JSON body)
            const url = `/api/push`;
            const response = await fetch( url, {
                method: 'POST',
                headers: {
                    'Authorization': this.getAuthHeader(),
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

    // ========================================
    // Q&A STT (Speech-to-Text) FUNCTIONALITY
    // ========================================

    async handleQASTTButtonClick() {
        const button = document.getElementById( 'qa-stt-button' );

        // If already recording, stop it
        if ( this.qaAudioRecorder && this.qaAudioRecorder.isRecording ) {
            await this.qaAudioRecorder.stopRecording();
            return;
        }

        // If processing, ignore click
        if ( this.qaAudioRecorder && this.qaAudioRecorder.isProcessing ) {
            return;
        }

        // Start new recording
        await this.startQAVoiceInput();
    }

    async startQAVoiceInput() {
        const button = document.getElementById( 'qa-stt-button' );
        const textInput = document.getElementById( 'qa-input' );

        if ( !this.authToken ) {
            alert( 'Please log in to use voice input' );
            return;
        }

        try {
            // Create new AudioRecorder instance
            this.qaAudioRecorder = new AudioRecorder( {
                uploadEndpoint: '/api/upload-and-transcribe-mp3',
                authToken: this.authToken,

                onRecordingStart: () => {
                    button.classList.add( 'recording' );
                    button.textContent = '🔴';
                    this._startQADurationCounter( button );
                    this._attachQARecordingCancelListener( button );
                },

                onRecordingStop: ( audioBlob ) => {
                    this._stopQADurationCounter();
                    this._detachQARecordingCancelListener();
                    button.classList.remove( 'recording' );
                    button.classList.add( 'processing' );
                    button.textContent = '⏳';
                    button.disabled = true;
                },

                onTranscription: ( text ) => {
                    // Fill text input with transcription
                    textInput.value = text;
                    textInput.focus();
                    textInput.select();

                    // Reset button UI
                    button.classList.remove( 'processing' );
                    button.textContent = '🎤';
                    button.disabled = false;
                    this._detachQARecordingCancelListener();
                },

                onError: ( error ) => {
                    alert( `Recording error: ${error.message}` );

                    // Reset button UI
                    button.classList.remove( 'recording', 'processing' );
                    button.textContent = '🎤';
                    button.disabled = false;
                    this._detachQARecordingCancelListener();
                },

                debug: this.debug
            } );

            await this.qaAudioRecorder.startRecording();

        } catch ( error ) {
            console.error( 'Failed to start Q&A voice input:', error );
            alert( `Failed to start recording: ${error.message}` );

            // Reset UI
            button.classList.remove( 'recording', 'processing' );
            button.textContent = '🎤';
            button.disabled = false;
        }
    }

    _startQADurationCounter( button ) {
        const startTime = Date.now();
        const MAX_DURATION_SECONDS = 30;

        this.qaRecordingInterval = setInterval( () => {
            const elapsed = Math.floor( ( Date.now() - startTime ) / 1000 );
            const icon = elapsed >= 25 ? '🟡' : '🔴';
            button.textContent = `${icon} ${elapsed}/${MAX_DURATION_SECONDS}s`;
        }, 1000 );
    }

    _stopQADurationCounter() {
        if ( this.qaRecordingInterval ) {
            clearInterval( this.qaRecordingInterval );
            this.qaRecordingInterval = null;
        }
    }

    _attachQARecordingCancelListener( button ) {
        this.qaRecordingCancelListener = ( event ) => {
            if ( event.key === 'Escape' ) {
                event.preventDefault();
                event.stopPropagation();
                this._cancelQARecording( button );
            }
        };
        document.addEventListener( 'keydown', this.qaRecordingCancelListener );
    }

    _detachQARecordingCancelListener() {
        if ( this.qaRecordingCancelListener ) {
            document.removeEventListener( 'keydown', this.qaRecordingCancelListener );
            this.qaRecordingCancelListener = null;
        }
    }

    _cancelQARecording( button ) {
        // Stop duration counter
        this._stopQADurationCounter();

        // Destroy recorder without uploading
        if ( this.qaAudioRecorder ) {
            this.qaAudioRecorder._cancelling = true;  // Signal cancellation
            this.qaAudioRecorder.destroy();
            this.qaAudioRecorder = null;
        }

        // Reset UI
        button.classList.remove( 'recording', 'processing' );
        button.textContent = '🎤';
        button.disabled = false;
        this._detachQARecordingCancelListener();
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

        // Capture TTT (Time to Text) metric
        this.metricsTextTime = Date.now();
        this.updateMetricsTTT();

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
                    ttsMode: document.getElementById( 'tts-mode' )?.value || this.TTS_MODE_DEFAULT
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

    getCurrentTTSMode() {
        // Get current TTS mode from UI selector with proper fallback to default
        const modeSelector = document.getElementById( 'tts-mode' );
        return modeSelector?.value || this.TTS_MODE_DEFAULT;
    }

    formatNotificationTTSMessage( notification ) {
        // Format notification message for TTS with priority prefix
        // Single source of truth for notification TTS message formatting
        let ttsMessage = `${notification.type} notification: ${notification.message}`;

        // Add priority prefix for urgent/high priority notifications
        if ( notification.priority === "urgent" ) {
            ttsMessage = `Urgent! ${ttsMessage}`;
        } else if ( notification.priority === "high" ) {
            ttsMessage = `Important! ${ttsMessage}`;
        }

        return ttsMessage;
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
            if ( mode === this.TTS_MODE_INSTANT ) {
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
            // Ensure token is valid before API call (auto-refresh if expired)
            await this.ensureValidToken();

            // Request TTS via 11labs streaming endpoint
            const response = await fetch( '/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader(),
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
            this.currentTTSMode = this.TTS_MODE_INSTANT;
            this.audioChunks = [];
            this.audioSources = [];
            this.startTime = Date.now(); // Track timing for both modes
            this.metricsTTSStartTime = Date.now(); // Capture TTS start for TTFA metric

        } catch ( error ) {
            this.error( "Instant TTS request failed:", error );
            throw error;
        }
    }
    
    async playReliableTTS( text ) {
        this.log( "Starting reliable TTS (OpenAI batch)..." );

        // Initialize state BEFORE async fetch to prevent race condition
        // (WebSocket may complete before fetch response arrives)
        this.currentTTSMode = this.TTS_MODE_RELIABLE;
        this.audioChunks = [];
        this.audioSources = [];
        this.startTime = Date.now(); // Track timing for reliable mode
        this.metricsTTSStartTime = Date.now(); // Capture TTS start for TTFA metric

        try {
            // Ensure token is valid before API call (auto-refresh if expired)
            await this.ensureValidToken();

            // Request TTS via OpenAI batch endpoint
            const response = await fetch( '/api/get-speech', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader(),
                    'X-Session-ID': this.audioSessionId
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

            // Audio chunks will be received via WebSocket and played by handleAudioComplete()
            
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

        if ( this.currentTTSMode === this.TTS_MODE_INSTANT ) {
            // Use sequential queue for Chrome compatibility AND collect for caching
            this.playChunkSequential( blobData );
        }
        // For reliable mode, chunks are just collected and played later in playCollectedAudio()
    }
    
    async handleAudioComplete( data ) {
        const collectedChunks = this.audioChunks ? this.audioChunks.length : 0;
        const processedChunks = this.processedChunks || 0;
        const sequentialPlayed = this.sequentialChunksPlayed || 0;

        if ( this.currentTTSMode === this.TTS_MODE_INSTANT ) {
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

        if ( this.currentTTSMode === this.TTS_MODE_RELIABLE && this.audioChunks && this.audioChunks.length > 0 ) {
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
            if ( !this.firstChunkPlayed && this.startTime ) {
                const timeToFirstPlayback = Date.now() - this.startTime;
                this.log( `⚡ Time to first playback (instant): ${timeToFirstPlayback}ms` );
                this.firstChunkPlayed = true;

                // Capture TTFA and RTT metrics for UI display
                this.metricsFirstAudioTime = Date.now();
                this.updateMetricsTTFA();
                this.updateMetricsRTT();
            }
        }).catch( e => {
            if ( !this.firstChunkPlayed && this.startTime ) {
                const timeToFirstPlayback = Date.now() - this.startTime;
                this.log( `⚡ Time to first playback attempt (instant): ${timeToFirstPlayback}ms - Play failed: ${e.message}` );
                this.firstChunkPlayed = true; // Mark as attempted even on failure

                // Still capture metrics even on failure (shows attempt timing)
                this.metricsFirstAudioTime = Date.now();
                this.updateMetricsTTFA();
                this.updateMetricsRTT();
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

        try {
            await this.audioElement.play();
            const timeToFirstPlayback = Date.now() - this.startTime;
            this.log( `⚡ Time to first playback (reliable): ${timeToFirstPlayback}ms` );
            this.log( `Reliable mode: Audio playing! (${totalTime.toFixed(1)}s total collection time)` );
            this.isPlaying = true;
            this.currentAudio = this.audioElement;

            // Capture TTFA and RTT metrics for UI display
            this.metricsFirstAudioTime = Date.now();
            this.updateMetricsTTFA();
            this.updateMetricsRTT();
        } catch ( playError ) {
            // Handle autoplay prevention gracefully (like original)
            const timeToFirstPlayback = Date.now() - this.startTime;
            this.log( `⚡ Time to first playback attempt (reliable): ${timeToFirstPlayback}ms - Autoplay prevented:`, playError.message );
            this.log( `Reliable mode: Audio ready (${totalTime.toFixed(1)}s total collection time) - autoplay prevented` );

            // Still capture metrics even on autoplay prevention (shows attempt timing)
            this.metricsFirstAudioTime = Date.now();
            this.updateMetricsTTFA();
            this.updateMetricsRTT();
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

        // DEBUG: Log the raw envelope structure
        console.log( '[DEBUG] WebSocket envelope:', envelope );
        console.log( '[DEBUG] envelope.notification:', envelope.notification );
        console.log( '[DEBUG] envelope.data:', envelope.data );

        // Handle real-time notification updates from NotificationFifoQueue
        const notification = envelope.notification || envelope.data?.notification;

        // DEBUG: Log extracted notification and its response_default field
        console.log( '[DEBUG] Extracted notification:', notification );
        if ( notification ) {
            console.log( '[DEBUG] notification.response_default:', notification.response_default );
            console.log( '[DEBUG] notification.response_requested:', notification.response_requested );
            console.log( '[DEBUG] notification.response_type:', notification.response_type );
        }

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

        // Phase 2.2 SSE - Check if this is a response-required notification
        if ( notification.response_requested === true ) {
            this.log( `Response-required notification detected: ${notification.id}` );
            // Route to Action Required section
            this.addActionRequiredNotification( notification );
            // Still play sound
            await this.playNotificationSoundByPriority( notification.priority );
            return;  // Don't add to regular notifications list
        }

        // Regular fire-and-forget notification handling
        // 1. ALWAYS play notification sound first based on priority
        await this.playNotificationSoundByPriority( notification.priority );

        // 2. Add to sender-grouped visual list (Phase 5)
        const senderId = this.resolveSenderId( notification );
        this.log( `Routing notification to sender: ${senderId}` );
        this.addNotificationToSenderGroup( notification, false );  // false = incoming message
        this.updateTotalNotificationsCount();

        // 3. Optional TTS for high/urgent priority notifications (like old queue.js)
        if ( notification.priority === "high" || notification.priority === "urgent" ) {
            // Format notification message for TTS using helper method
            const ttsMessage = this.formatNotificationTTSMessage( notification );

            this.log( `Queuing high priority notification for TTS playback: "${ttsMessage}"` );

            // Add slight delay to let notification sound finish (like old queue.js)
            setTimeout( () => {
                this.playTTS( ttsMessage, this.getCurrentTTSMode() ).catch( error => {
                    this.error( 'TTS failed for high priority notification:', error );
                });
            }, 300 );
        } else {
            this.log( `Skipping TTS for ${notification.priority} priority notification` );
        }
    }
    
    // ========================================
    // TIMING METRICS DISPLAY
    // ========================================

    resetMetricsDisplay() {
        const metricsDiv = document.getElementById( 'qa-metrics' );
        if ( metricsDiv ) {
            metricsDiv.style.display = 'none';
            document.getElementById( 'metric-ttt' ).textContent = '--';
            document.getElementById( 'metric-ttfa' ).textContent = '--';
            document.getElementById( 'metric-rtt' ).textContent = '--';
        }
    }

    updateMetricsTTT() {
        if ( this.metricsSubmitTime && this.metricsTextTime ) {
            const ttt = this.metricsTextTime - this.metricsSubmitTime;
            document.getElementById( 'metric-ttt' ).textContent = `${ttt}ms`;
            document.getElementById( 'qa-metrics' ).style.display = 'flex';
        }
    }

    updateMetricsTTFA() {
        // TTFA = TTS request start → first audio plays (audio generation only)
        if ( this.metricsTTSStartTime && this.metricsFirstAudioTime ) {
            const ttfa = this.metricsFirstAudioTime - this.metricsTTSStartTime;
            document.getElementById( 'metric-ttfa' ).textContent = `${ttfa}ms`;
            document.getElementById( 'qa-metrics' ).style.display = 'flex';
        }
    }

    updateMetricsRTT() {
        // RTT = Submit → first audio plays (full round-trip ≈ TTT + TTFA)
        if ( this.metricsSubmitTime && this.metricsFirstAudioTime ) {
            const rtt = this.metricsFirstAudioTime - this.metricsSubmitTime;
            document.getElementById( 'metric-rtt' ).textContent = `${rtt}ms`;
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

        // Build URL with user_filter parameter for admins viewing all jobs
        let url = `/api/get-queue/${queueName}`;
        if ( this.isAdmin && this.queueFilterMode === 'all' ) {
            url += '?user_filter=*';  // Admin viewing all jobs
            this.log( `Admin mode: fetching ALL users' jobs for ${queueName}` );
        } else {
            this.log( `Fetching own jobs only for ${queueName}` );
        }
        // Regular users and admins in 'own' mode: no parameter = own jobs only

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

    setFilterMode( mode ) {
        /**
         * Change the queue filter mode for admin users.
         *
         * Requires:
         *     - mode is 'own' or 'all'
         *     - User is authenticated
         *
         * Ensures:
         *     - Regular users cannot change filter mode (warning logged)
         *     - Admin users can toggle between 'own' and 'all'
         *     - UI buttons update to reflect active mode
         *     - Filter preference persists in localStorage
         *     - All queues refresh with new filter applied
         *
         * Args:
         *     mode: 'own' (user's jobs only) or 'all' (all users' jobs)
         */
        if ( !this.isAdmin ) {
            this.warn( 'Only admin users can change filter mode' );
            return;
        }

        this.queueFilterMode = mode;

        // Update UI button states
        document.getElementById( 'filter-own-jobs' ).classList.toggle( 'active', mode === 'own' );
        document.getElementById( 'filter-all-jobs' ).classList.toggle( 'active', mode === 'all' );
        document.getElementById( 'filter-mode-display' ).textContent =
            mode === 'own' ? 'Your jobs only' : 'All users\' jobs';

        // Save preference to localStorage
        localStorage.setItem( this.QUEUE_FILTER_PREF_KEY, mode );

        // Refresh all queues with new filter
        this.log( `Filter mode changed to: ${mode} - refreshing queues` );
        this.refreshAllQueues();
    }

    initializeFilterUI() {
        /**
         * Initialize the filter UI based on user role.
         *
         * Requires:
         *     - this.isAdmin is set (from authentication)
         *     - Filter panel HTML elements exist
         *
         * Ensures:
         *     - Admin users see filter panel, regular users don't
         *     - Admin filter preference loaded from localStorage (default: 'own')
         *     - UI button states match current filter mode
         *     - Filter mode defaulted to 'own' for regular users
         */
        const filterSection = document.getElementById( 'filter-settings-section' );

        if ( this.isAdmin ) {
            // Show filter panel for admins
            filterSection.style.display = 'block';

            // Load saved preference or default to 'own'
            const savedFilter = localStorage.getItem( this.QUEUE_FILTER_PREF_KEY );
            this.queueFilterMode = ( savedFilter === 'all' ) ? 'all' : 'own';

            // Update button states
            document.getElementById( 'filter-own-jobs' ).classList.toggle( 'active', this.queueFilterMode === 'own' );
            document.getElementById( 'filter-all-jobs' ).classList.toggle( 'active', this.queueFilterMode === 'all' );
            document.getElementById( 'filter-mode-display' ).textContent =
                this.queueFilterMode === 'own' ? 'Your jobs only' : 'All users\' jobs';

            this.log( `Admin filter UI initialized - mode: ${this.queueFilterMode}` );
        } else {
            // Hide for regular users
            filterSection.style.display = 'none';
            this.queueFilterMode = 'own';  // Force own jobs only

            this.log( 'Regular user - filter locked to own jobs' );
        }
    }

    async refreshAllQueues() {
        /**
         * Refresh all queue lists with current filter settings.
         *
         * Requires:
         *     - WebSocket connections established
         *     - Authentication complete
         *
         * Ensures:
         *     - All four queues (todo, run, done, dead) are refreshed
         *     - Fetches use current queueFilterMode setting
         *     - Errors logged but don't block other queues
         */
        this.log( 'Refreshing all queue lists...' );
        try {
            await Promise.all( [
                this.updateQueueLists( 'todo' ),
                this.updateQueueLists( 'run' ),
                this.updateQueueLists( 'done' ),
                this.updateQueueLists( 'dead' )
            ] );
            this.log( 'All queues refreshed successfully' );
        } catch ( error ) {
            this.error( 'Error refreshing queues:', error );
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
            const currentMode = document.getElementById( 'tts-mode' )?.value || this.TTS_MODE_DEFAULT;
            
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
    // SENDER-AWARE NOTIFICATION HELPERS (Phase 5)
    // ========================================

    /**
     * Extract sender ID from message prefix like [LUPIN] or [COSA].
     * @param {string} message - Notification message text
     * @returns {string|null} - Sender ID in email format, or null if no prefix
     */
    extractSenderFromMessage( message ) {
        const match = message.match( /^\[([A-Z]+)\]/ );
        if ( match ) {
            const project = match[1].toLowerCase();
            return `claude.code@${project}.deepily.ai`;
        }
        return null;
    }

    /**
     * Resolve sender ID using precedence: explicit > extracted from message > fallback.
     * @param {object} notification - Notification object with optional sender_id and message
     * @returns {string} - Resolved sender ID
     */
    resolveSenderId( notification ) {
        // 1. Explicit sender_id from notification
        if ( notification.sender_id ) {
            return notification.sender_id;
        }
        // 2. Extract from [PREFIX] in message
        const extracted = this.extractSenderFromMessage( notification.message || '' );
        if ( extracted ) {
            return extracted;
        }
        // 3. Fallback to unknown
        return this.UNKNOWN_SENDER;
    }

    /**
     * Extract project name from sender ID for display.
     * @param {string} senderId - Sender ID (e.g., claude.code@lupin.deepily.ai)
     * @returns {string} - Project name in uppercase (e.g., "LUPIN")
     */
    getProjectFromSenderId( senderId ) {
        const match = senderId.match( /^claude\.code@([a-z]+)\.deepily\.ai$/ );
        if ( match ) {
            return match[1].toUpperCase();
        }
        return 'UNKNOWN';
    }

    /**
     * Get sender status indicator based on activity.
     * @param {Date} lastActivity - Last activity timestamp
     * @returns {string} - Status emoji (🟢 active, 🟡 recent, ⚪ inactive)
     */
    getSenderStatusIndicator( lastActivity ) {
        if ( !lastActivity ) return '⚪';
        const now = new Date();
        const hoursSinceActivity = ( now - lastActivity ) / ( 1000 * 60 * 60 );
        if ( hoursSinceActivity < 1 ) return '🟢';   // Active within last hour
        if ( hoursSinceActivity < 24 ) return '🟡';  // Recent within last day
        return '⚪';  // Inactive
    }

    /**
     * Format relative time for display.
     * @param {Date} date - Timestamp
     * @returns {string} - Relative time string (e.g., "5 min ago", "2 hours ago")
     */
    formatRelativeTime( date ) {
        if ( !date ) return 'Never';
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor( diffMs / 60000 );
        const diffHours = Math.floor( diffMs / 3600000 );
        const diffDays = Math.floor( diffMs / 86400000 );

        if ( diffMins < 1 ) return 'Just now';
        if ( diffMins < 60 ) return `${diffMins} min ago`;
        if ( diffHours < 24 ) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
        return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
    }

    // ========================================
    // SENDER CARD MANAGEMENT (Phase 5)
    // ========================================

    /**
     * Add notification to appropriate sender group.
     * Creates sender card if it doesn't exist.
     * @param {object} notification - Notification data
     * @param {boolean} isResponse - True if this is a user response (right-aligned)
     */
    addNotificationToSenderGroup( notification, isResponse = false ) {
        const senderId = this.resolveSenderId( notification );
        const timestamp = new Date( notification.timestamp || Date.now() );

        // Get or create sender group
        let group = this.senderGroups.get( senderId );
        if ( !group ) {
            group = {
                notifications : [],
                collapsed     : false,
                lastActivity  : timestamp
            };
            this.senderGroups.set( senderId, group );
            this.createSenderCard( senderId );
        }

        // Update last activity
        if ( timestamp > group.lastActivity ) {
            group.lastActivity = timestamp;
        }

        // Add to notifications array
        group.notifications.push( { ...notification, isResponse } );

        // Update UI
        this.addMessageToSenderCard( senderId, notification, isResponse );
        this.updateSenderCardHeader( senderId );
    }

    /**
     * Create a new sender card in the UI.
     * @param {string} senderId - Sender ID
     */
    createSenderCard( senderId ) {
        const container = document.getElementById( 'notifications-list' );
        if ( !container ) {
            this.error( 'Notifications list container not found' );
            return;
        }

        const projectName = this.getProjectFromSenderId( senderId );
        const group = this.senderGroups.get( senderId );
        const statusIndicator = this.getSenderStatusIndicator( group?.lastActivity );

        const card = document.createElement( 'div' );
        card.id = `sender-card-${senderId.replace( /[@.]/g, '-' )}`;
        card.className = 'sender-card';
        card.innerHTML = `
            <div class="sender-card-header" onclick="window.freshQueueUI.toggleSenderCard('${senderId}')">
                <span class="sender-status">${statusIndicator}</span>
                <span class="sender-project-name">${projectName}</span>
                <span class="sender-message-count">(0)</span>
                <span class="sender-last-activity">Last: --</span>
                <button class="sender-delete-btn" onclick="event.stopPropagation(); window.freshQueueUI.deleteSenderConversation('${senderId}')" title="Delete conversation">×</button>
                <span class="sender-toggle">▼</span>
            </div>
            <div class="sender-card-messages" id="sender-messages-${senderId.replace( /[@.]/g, '-' )}">
                <!-- Messages will be added here -->
            </div>
        `;

        // Insert at top (most recent sender first)
        container.insertBefore( card, container.firstChild );
        this.log( `Created sender card for ${projectName} (${senderId})` );
    }

    /**
     * Toggle sender card collapse state.
     * @param {string} senderId - Sender ID
     */
    toggleSenderCard( senderId ) {
        const group = this.senderGroups.get( senderId );
        if ( !group ) return;

        group.collapsed = !group.collapsed;

        const cardId = `sender-card-${senderId.replace( /[@.]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( card ) {
            const messages = card.querySelector( '.sender-card-messages' );
            const toggle = card.querySelector( '.sender-toggle' );
            if ( messages ) {
                messages.style.display = group.collapsed ? 'none' : 'block';
            }
            if ( toggle ) {
                toggle.textContent = group.collapsed ? '▶' : '▼';
            }
        }
    }

    /**
     * Add a message to a sender card.
     * @param {string} senderId - Sender ID
     * @param {object} notification - Notification data
     * @param {boolean} isResponse - True if user response (right-aligned)
     */
    addMessageToSenderCard( senderId, notification, isResponse = false ) {
        const containerId = `sender-messages-${senderId.replace( /[@.]/g, '-' )}`;
        const container = document.getElementById( containerId );
        if ( !container ) return;

        const timestamp = new Date( notification.timestamp || Date.now() );
        const time = timestamp.toLocaleTimeString( [], { hour: '2-digit', minute: '2-digit' } );

        // Process message (remove [PREFIX] since we already show project name)
        let displayMessage = notification.message || '';
        const prefixMatch = displayMessage.match( /^\[([A-Z]+)\]\s*(.*)$/ );
        if ( prefixMatch ) {
            displayMessage = prefixMatch[2];  // Remove prefix
        }

        // Truncate long messages
        const truncatedMessage = displayMessage.length > 120
            ? displayMessage.substring( 0, 117 ) + '...'
            : displayMessage;

        const messageDiv = document.createElement( 'div' );
        messageDiv.className = `sender-message ${isResponse ? 'outgoing' : 'incoming'}`;
        messageDiv.innerHTML = `
            <span class="message-time">${time}${isResponse ? ' →' : ''}</span>
            <span class="message-text" title="${displayMessage}">${truncatedMessage}</span>
        `;

        // Add to container (CSS column-reverse handles display order)
        container.appendChild( messageDiv );
    }

    /**
     * Update sender card header with current stats.
     * @param {string} senderId - Sender ID
     */
    updateSenderCardHeader( senderId ) {
        const group = this.senderGroups.get( senderId );
        if ( !group ) return;

        const cardId = `sender-card-${senderId.replace( /[@.]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( !card ) return;

        // Update count
        const countEl = card.querySelector( '.sender-message-count' );
        if ( countEl ) {
            countEl.textContent = `(${group.notifications.length})`;
        }

        // Update status indicator
        const statusEl = card.querySelector( '.sender-status' );
        if ( statusEl ) {
            statusEl.textContent = this.getSenderStatusIndicator( group.lastActivity );
        }

        // Update last activity
        const activityEl = card.querySelector( '.sender-last-activity' );
        if ( activityEl ) {
            activityEl.textContent = `Last: ${this.formatRelativeTime( group.lastActivity )}`;
        }

        // Move card to top if it has new activity
        const container = document.getElementById( 'notifications-list' );
        if ( container && container.firstChild !== card ) {
            container.insertBefore( card, container.firstChild );
        }
    }

    /**
     * Update total notifications count display and Clear All button state.
     */
    updateTotalNotificationsCount() {
        let total = 0;
        for ( const group of this.senderGroups.values() ) {
            total += group.notifications.length;
        }
        const countEl = document.getElementById( 'notifications-count' );
        if ( countEl ) {
            countEl.textContent = total;
        }
        // Keep Clear All button state in sync with notification count
        this.updateClearButtonState( total );
    }

    // ========================================
    // HISTORY LOADING (Phase 5/6)
    // ========================================

    /**
     * Load conversation history for all senders from the API.
     * Uses activity-anchored window loading based on historyWindowHours.
     */
    async loadConversationHistory() {
        if ( !this.currentUser ) {
            this.log( 'Cannot load history: no user email' );
            return;
        }

        this.log( `Loading conversation history (window: ${this.historyWindowHours}h)...` );

        try {
            // First, get list of senders with recent activity
            const sendersUrl = `/api/notifications/senders/${encodeURIComponent( this.currentUser )}`;
            const params = this.historyWindowHours ? `?hours=${this.historyWindowHours}` : '';

            const sendersResponse = await fetch( sendersUrl + params, {
                headers: this.getAuthHeaders()
            } );

            if ( !sendersResponse.ok ) {
                if ( sendersResponse.status === 404 ) {
                    this.log( 'No notification history found' );
                    return;
                }
                throw new Error( `Failed to fetch senders: ${sendersResponse.status}` );
            }

            const senders = await sendersResponse.json();
            this.log( `Found ${senders.length} senders with history` );

            // Load conversation for each sender
            for ( const senderInfo of senders ) {
                await this.loadSenderConversation( senderInfo.sender_id, senderInfo.last_activity );
            }

            this.updateTotalNotificationsCount();

        } catch ( error ) {
            this.error( `Failed to load conversation history: ${error.message}` );
        }
    }

    /**
     * Load conversation history for a specific sender.
     * @param {string} senderId - Sender ID
     * @param {string} anchorTime - ISO timestamp to anchor the window around
     */
    async loadSenderConversation( senderId, anchorTime = null ) {
        try {
            const baseUrl = `/api/notifications/conversation/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUser )}`;
            const params = new URLSearchParams();

            if ( this.historyWindowHours ) {
                params.append( 'hours', this.historyWindowHours );
            }
            if ( anchorTime ) {
                params.append( 'anchor', anchorTime );
            }

            const url = params.toString() ? `${baseUrl}?${params}` : baseUrl;

            const response = await fetch( url, {
                headers: this.getAuthHeaders()
            } );

            if ( !response.ok ) {
                if ( response.status === 404 ) {
                    this.log( `No history for sender: ${senderId}` );
                    return;
                }
                throw new Error( `Failed to fetch conversation: ${response.status}` );
            }

            const notifications = await response.json();
            this.log( `Loaded ${notifications.length} notifications for ${senderId}` );

            // Add each notification to the sender group
            for ( const notification of notifications ) {
                const isResponse = notification.state === 'responded' && notification.responded_at;
                this.addNotificationToSenderGroup( notification, isResponse );
            }

        } catch ( error ) {
            this.error( `Failed to load conversation for ${senderId}: ${error.message}` );
        }
    }

    /**
     * Set the history window and reload conversations.
     * @param {number|null} hours - Hours to look back, or null for all time
     */
    async setHistoryWindow( hours ) {
        this.historyWindowHours = hours;
        localStorage.setItem( this.HISTORY_WINDOW_KEY, hours === null ? '' : hours.toString() );

        this.log( `History window set to: ${hours === null ? 'all time' : hours + ' hours'}` );

        // Update dropdown display
        this.updateHistoryWindowDisplay( hours );

        // Clear existing sender groups and reload
        this.clearSenderGroups();
        await this.loadConversationHistory();
    }

    /**
     * Clear all sender groups and their UI elements.
     */
    clearSenderGroups() {
        // Clear the Map
        this.senderGroups.clear();

        // Remove all sender cards from the DOM
        const container = document.getElementById( 'notifications-list' );
        if ( container ) {
            const cards = container.querySelectorAll( '.sender-card' );
            cards.forEach( card => card.remove() );
        }

        this.updateTotalNotificationsCount();
    }

    /**
     * Update the history window dropdown display.
     * @param {number|null} hours - Current window in hours
     */
    updateHistoryWindowDisplay( hours ) {
        const dropdown = document.getElementById( 'history-window-dropdown' );
        if ( !dropdown ) return;

        const option = this.WINDOW_OPTIONS.find( opt => opt.hours === hours );
        const display = dropdown.querySelector( '.dropdown-display' );
        if ( display && option ) {
            display.textContent = option.label;
        }
    }

    /**
     * Create the history window dropdown UI element.
     * @returns {HTMLElement} The dropdown element
     */
    createHistoryWindowDropdown() {
        const dropdown = document.createElement( 'div' );
        dropdown.id = 'history-window-dropdown';
        dropdown.className = 'history-window-dropdown';

        // Find current selection
        const currentOption = this.WINDOW_OPTIONS.find( opt => opt.hours === this.historyWindowHours )
            || this.WINDOW_OPTIONS[0];

        dropdown.innerHTML = `
            <span class="dropdown-label">History:</span>
            <button class="dropdown-display" onclick="window.freshQueueUI.toggleHistoryDropdown()">
                ${currentOption.label}
                <span class="dropdown-arrow">▼</span>
            </button>
            <div class="dropdown-menu" id="history-dropdown-menu">
                ${this.WINDOW_OPTIONS.map( opt => `
                    <div class="dropdown-item ${opt.hours === this.historyWindowHours ? 'selected' : ''}"
                         onclick="window.freshQueueUI.setHistoryWindow(${opt.hours})">
                        ${opt.label}
                    </div>
                ` ).join( '' )}
            </div>
        `;

        return dropdown;
    }

    /**
     * Toggle the history window dropdown menu visibility.
     */
    toggleHistoryDropdown() {
        const menu = document.getElementById( 'history-dropdown-menu' );
        if ( menu ) {
            menu.classList.toggle( 'show' );
        }
    }

    /**
     * Initialize the history window dropdown in the notifications header.
     */
    initializeHistoryDropdown() {
        const container = document.getElementById( 'history-dropdown-container' );
        if ( !container ) {
            this.log( 'History dropdown container not found' );
            return;
        }

        const dropdown = this.createHistoryWindowDropdown();
        container.appendChild( dropdown );

        // Close dropdown when clicking outside
        document.addEventListener( 'click', ( event ) => {
            const dropdownEl = document.getElementById( 'history-window-dropdown' );
            if ( dropdownEl && !dropdownEl.contains( event.target ) ) {
                const menu = document.getElementById( 'history-dropdown-menu' );
                if ( menu ) {
                    menu.classList.remove( 'show' );
                }
            }
        } );

        this.log( 'History dropdown initialized' );
    }

    /**
     * Get authentication headers for API requests.
     * @returns {Object} Headers object with authorization
     */
    getAuthHeaders() {
        return {
            'Authorization': `Bearer ${this.authToken}`,
            'Content-Type': 'application/json'
        };
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
            // Format TTS message with priority prefix for consistent cache key
            ttsMessage: this.formatNotificationTTSMessage( data )
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

        // Update clear button state (enable/disable based on count)
        this.updateClearButtonState( currentCount );

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
            const currentMode = document.getElementById( 'tts-mode' )?.value || this.TTS_MODE_DEFAULT;
            
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
            
            // Clear existing sender groups and populate with server data
            this.clearSenderGroups();

            // Add each notification to sender cards (oldest first for chronological order)
            serverNotifications.reverse().forEach( notification => {
                const isResponse = notification.state === 'responded' && notification.responded_at;
                this.addNotificationToSenderGroup( notification, isResponse );
            });

            this.updateTotalNotificationsCount();
            
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

                // Update clear button state (enable/disable based on count)
                this.updateClearButtonState( currentCount );
            }

            this.log( `Notification ${notificationId} removed from UI` );
        }
        
        // Remove from local cache
        this.notificationState.notifications = this.notificationState.notifications.filter(
            n => n.id_hash !== notificationId
        );
    }

    async deleteSenderConversation( senderId ) {
        /**
         * Delete all notifications for a specific sender (entire conversation).
         *
         * Requires:
         *     - senderId: Sender identifier (e.g., claude.code@lupin.deepily.ai)
         *     - User authenticated (this.currentUser set)
         *
         * Ensures:
         *     - User confirmation before destructive action
         *     - All notifications from sender deleted from server
         *     - Sender card removed from UI
         *     - Sender group removed from local state
         *     - Total count updated
         */

        const projectName = this.getProjectFromSenderId( senderId );
        const group = this.senderGroups.get( senderId );

        if ( !group ) {
            this.error( `No sender group found for: ${senderId}` );
            return;
        }

        const count = group.notifications.length;

        // Confirm before clearing (destructive action)
        if ( !confirm( `Delete all ${count} message${count !== 1 ? 's' : ''} from ${projectName}? This cannot be undone.` ) ) {
            this.log( "Delete conversation cancelled by user" );
            return;
        }

        this.log( `Deleting conversation with ${projectName} (${count} messages)...` );

        try {
            const response = await fetch(
                `/api/notifications/conversation/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUser )}`,
                {
                    method  : 'DELETE',
                    headers : this.getAuthHeaders()
                }
            );

            if ( !response.ok ) {
                this.error( `Server error (${response.status}) deleting conversation` );
                // Continue with UI cleanup anyway
            } else {
                const result = await response.json();
                this.log( `Server deleted ${result.deleted_count} notifications` );
            }

        } catch ( error ) {
            this.error( "Network error deleting conversation:", error );
            // Continue with UI cleanup anyway
        }

        // Remove sender card from UI
        const cardId = `sender-card-${senderId.replace( /[@.]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( card ) {
            card.remove();
        }

        // Remove from local state
        this.senderGroups.delete( senderId );

        // Update total count
        this.updateTotalNotificationsCount();

        this.log( `✓ Deleted conversation with ${projectName}` );
    }

    async clearAllNotifications() {
        /**
         * Clear all notifications from the UI and server.
         *
         * Purpose:
         *     - Bulk delete all notifications with user confirmation
         *     - Handles both UI cleanup and server-side deletion
         *
         * Behavior:
         *     1. Check if there are any notifications to clear
         *     2. Show confirmation dialog with count
         *     3. If confirmed: Loop through all notifications and delete each one
         *     4. Update UI and local cache
         *
         * Ensures:
         *     - User confirmation before destructive action
         *     - All notifications removed from server (via DELETE API)
         *     - UI updated properly (counter, list cleared)
         *     - Local cache cleared
         */

        const notificationsList = document.getElementById( "notifications-list" );
        const notificationsCounter = document.getElementById( "notifications-count" );

        if ( !notificationsList || notificationsList.children.length === 0 ) {
            this.log( "No notifications to clear" );
            return;
        }

        const count = notificationsList.children.length;

        // Confirm before clearing (destructive action)
        if ( !confirm( `Clear all ${count} notification${count !== 1 ? 's' : ''}? This cannot be undone.` ) ) {
            this.log( "Clear all notifications cancelled by user" );
            return;
        }

        this.log( `Clearing ${count} notifications...` );

        // Collect all notification IDs before deletion (array changes during loop)
        const notificationIds = Array.from( notificationsList.children ).map( li => li.id );

        // Delete each notification (calls existing deleteNotification method)
        for ( const notificationId of notificationIds ) {
            await this.deleteNotification( notificationId );
        }

        this.log( `✓ Cleared ${count} notification${count !== 1 ? 's' : ''}` );
    }

    updateClearButtonState( count ) {
        /**
         * Update the Clear All button enabled/disabled state based on notification count.
         *
         * Requires:
         *     - count: Number of notifications currently in the list
         *
         * Ensures:
         *     - Button disabled when count = 0 (nothing to clear)
         *     - Button enabled when count > 0 (notifications available to clear)
         *     - Handles missing button gracefully (no error thrown)
         */

        const clearButton = document.getElementById( 'clear-all-notifications' );
        if ( clearButton ) {
            clearButton.disabled = ( count === 0 );
        }
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
            const currentMode = document.getElementById( 'tts-mode' )?.value || this.TTS_MODE_DEFAULT;
            
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

    // ========================================
    // PHASE 2.2 SSE - ACTION REQUIRED NOTIFICATIONS
    // ========================================

    addActionRequiredNotification( notification ) {
        this.log( `Adding action-required notification: ${notification.id}` );

        // Store in action-required map
        this.actionRequiredNotifications.set( notification.id, {
            notification: notification,
            expiresAt: Date.now() + ( notification.timeout_seconds * 1000 ),
            timeoutSeconds: notification.timeout_seconds,
            isExpired: false,
            isResponded: false
        } );

        // Show the Action Required section
        const section = document.getElementById( 'action-required-section' );
        if ( section ) {
            section.style.display = 'block';
        }

        // Render the notification UI
        this.renderActionRequiredNotification( notification );

        // Update count
        this.updateActionRequiredCount();

        // Start countdown timer
        this.startCountdownTimer( notification.id );

        // Attach keyboard listener if not already active
        if ( !this.keyboardListenerActive ) {
            this.attachKeyboardListener();
        }
    }

    renderActionRequiredNotification( notification ) {
        const container = document.getElementById( 'action-required-list' );
        if ( !container ) {
            this.error( "Action required list container not found" );
            return;
        }

        // Hide empty state when adding first notification
        const emptyState = document.getElementById( 'action-required-empty' );
        if ( emptyState ) {
            emptyState.style.display = 'none';
        }

        // Create notification card
        const card = document.createElement( 'div' );
        card.id = `action-required-${notification.id}`;
        card.className = 'action-required-notification active';  // Phase 2.2: Add 'active' class

        // Build HTML based on response type
        let responseUI = '';

        if ( notification.response_type === 'yes_no' ) {
            // Phase 2.2: Highlight default button
            const defaultValue = notification.response_default;
            const yesClass = defaultValue === 'yes' ? 'default-value' : '';
            const noClass = defaultValue === 'no' ? 'default-value' : '';

            responseUI = `
                <div class="response-buttons">
                    <button class="response-button yes ${yesClass}" data-notification-id="${notification.id}" data-response="yes">
                        ✓ Yes <span class="keyboard-hint">(Y)</span>
                    </button>
                    <button class="response-button no ${noClass}" data-notification-id="${notification.id}" data-response="no">
                        ✗ No <span class="keyboard-hint">(N)</span>
                    </button>
                </div>
            `;
        } else if ( notification.response_type === 'open_ended' ) {
            // DEBUG: Log notification object and response_default value
            console.log( '[DEBUG] Open-ended notification object:', notification );
            console.log( '[DEBUG] response_default value:', notification.response_default );
            console.log( '[DEBUG] response_default type:', typeof notification.response_default );

            responseUI = `
                <div class="response-open-ended">
                    <div class="response-input-container">
                        <input type="text" class="response-text-input" id="response-input-${notification.id}" value="${notification.response_default || ''}" placeholder="Type your response...">
                        <button class="response-mic-button" data-notification-id="${notification.id}" title="Click to start recording (30s max, ESC to cancel)">
                            🎤
                        </button>
                        <button class="response-submit-button" data-notification-id="${notification.id}">
                            Submit
                        </button>
                    </div>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="action-required-header">
                <div class="action-required-title">${notification.title || notification.message}</div>
                <div class="action-required-timer" id="timer-${notification.id}">--:--</div>
            </div>
            <div class="action-required-message">${notification.message}</div>
            <div class="action-required-progress-bar">
                <div class="action-required-progress-fill" id="progress-${notification.id}" style="width: 100%;"></div>
            </div>
            ${responseUI}
        `;

        container.appendChild( card );

        // Attach event listeners
        if ( notification.response_type === 'yes_no' ) {
            card.querySelectorAll( '.response-button' ).forEach( button => {
                button.addEventListener( 'click', ( e ) => {
                    const response = e.target.dataset.response;
                    this.submitResponse( notification.id, response );
                } );
            } );
        } else if ( notification.response_type === 'open_ended' ) {
            const submitButton = card.querySelector( '.response-submit-button' );
            const input = card.querySelector( '.response-text-input' );
            const micButton = card.querySelector( '.response-mic-button' );

            // DEBUG: Verify input element and its value attribute
            console.log( '[DEBUG] Input element found:', input );
            console.log( '[DEBUG] Input value attribute:', input ? input.value : 'INPUT NOT FOUND' );
            console.log( '[DEBUG] Input getAttribute("value"):', input ? input.getAttribute( 'value' ) : 'N/A' );

            // Phase 2.4.1: Real-time validation for open-ended input
            const validateInput = () => {
                const value = input.value.trim();
                const isValid = value.length > 0 && value.length <= 500;

                submitButton.disabled = !isValid;

                // Visual feedback
                if ( input.value.length > 0 ) {
                    if ( value.length > 500 ) {
                        input.classList.add( 'invalid' );
                    } else {
                        input.classList.remove( 'invalid' );
                    }
                }

                return isValid;
            };

            // Phase 2.4.2: Run initial validation (enables button if default value exists)
            validateInput();

            // Phase 2.4.2: Auto-focus and select all text for fastest keyboard response
            input.focus();
            if ( notification.response_default ) {
                input.select();  // Select all text - typing replaces, arrows enter insert mode
            }

            // Validate on input
            input.addEventListener( 'input', validateInput );

            submitButton.addEventListener( 'click', () => {
                if ( validateInput() ) {
                    this.submitResponse( notification.id, input.value.trim() );
                }
            } );

            input.addEventListener( 'keypress', ( e ) => {
                if ( e.key === 'Enter' && validateInput() ) {
                    this.submitResponse( notification.id, input.value.trim() );
                }
            } );

            micButton.addEventListener( 'click', () => {
                this.startVoiceInput( notification.id );
            } );
        }
    }

    startCountdownTimer( notificationId ) {
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        const timerElement = document.getElementById( `timer-${notificationId}` );
        const progressElement = document.getElementById( `progress-${notificationId}` );

        // Update every second
        const intervalHandle = setInterval( () => {
            const remaining = state.expiresAt - Date.now();

            if ( remaining <= 0 ) {
                // Timeout expired
                clearInterval( intervalHandle );
                this.handleLocalTimeout( notificationId );
                return;
            }

            // Calculate MM:SS
            const totalSeconds = Math.floor( remaining / 1000 );
            const minutes = Math.floor( totalSeconds / 60 );
            const seconds = totalSeconds % 60;
            const timeString = `${String( minutes ).padStart( 2, '0' )}:${String( seconds ).padStart( 2, '0' )}`;

            // Update timer display
            if ( timerElement ) {
                timerElement.textContent = timeString;

                // Color coding
                const percentRemaining = remaining / ( state.timeoutSeconds * 1000 );
                timerElement.classList.remove( 'warning', 'danger' );
                if ( percentRemaining <= 0.25 ) {
                    timerElement.classList.add( 'danger' );
                } else if ( percentRemaining <= 0.5 ) {
                    timerElement.classList.add( 'warning' );
                }
            }

            // Update progress bar
            if ( progressElement ) {
                const percentRemaining = ( remaining / ( state.timeoutSeconds * 1000 ) ) * 100;
                progressElement.style.width = `${percentRemaining}%`;

                progressElement.classList.remove( 'warning', 'danger' );
                if ( percentRemaining <= 25 ) {
                    progressElement.classList.add( 'danger' );
                } else if ( percentRemaining <= 50 ) {
                    progressElement.classList.add( 'warning' );
                }
            }
        }, 1000 );

        this.countdownTimers.set( notificationId, intervalHandle );
    }

    async submitResponse( notificationId, response ) {
        this.log( `Submitting response for ${notificationId}: ${response}` );

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state || state.isResponded ) {
            this.log( "Already responded or notification not found" );
            return;
        }

        // Mark as responded
        state.isResponded = true;

        // Disable buttons to prevent double-submit
        const card = document.getElementById( `action-required-${notificationId}` );
        if ( card ) {
            card.querySelectorAll( 'button, input' ).forEach( el => el.disabled = true );
        }

        try {
            // Submit to server
            const payload = {
                notification_id: notificationId,
                response_value: response
            };

            const apiResponse = await fetch( '/api/notify/response', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader()
                },
                body: JSON.stringify( payload )
            } );

            if ( !apiResponse.ok ) {
                const errorData = await apiResponse.json();
                throw new Error( errorData.detail || `HTTP ${apiResponse.status}` );
            }

            const result = await apiResponse.json();
            this.log( "Response submitted successfully:", result );

            // Show confirmation
            this.showConfirmation( notificationId, response );

            // Stop countdown
            this.stopCountdownTimer( notificationId );

        } catch ( error ) {
            this.error( "Failed to submit response:", error );
            state.isResponded = false;  // Allow retry
            // Re-enable buttons
            if ( card ) {
                card.querySelectorAll( 'button, input' ).forEach( el => el.disabled = false );
            }
            alert( `Failed to submit response: ${error.message}` );
        }
    }

    showConfirmation( notificationId, response ) {
        const card = document.getElementById( `action-required-${notificationId}` );
        if ( !card ) return;

        // Phase 2.2: Change to 'responded' state (stay in-place, no movement)
        card.classList.remove( 'active' );
        card.classList.add( 'responded' );

        // Remove progress bar and timer (no longer needed)
        const progress = document.getElementById( `progress-${notificationId}` );
        const timer = document.getElementById( `timer-${notificationId}` );
        if ( progress && progress.parentElement ) progress.parentElement.remove();
        if ( timer ) timer.textContent = '✓ Responded';

        // Replace buttons with status badge
        const buttonsContainer = card.querySelector( '.response-buttons, .response-open-ended' );
        if ( buttonsContainer ) {
            buttonsContainer.innerHTML = `
                <div class="notification-status-badge responded">
                    ✓ You responded: ${response}
                </div>
            `;
        }
    }

    moveToRegularNotifications( notificationId ) {
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        // Remove from action required
        const card = document.getElementById( `action-required-${notificationId}` );
        if ( card ) {
            card.remove();
        }

        this.actionRequiredNotifications.delete( notificationId );
        this.updateActionRequiredCount();

        // Add to regular notifications (already has response info from server)
        this.addNotificationToList( state.notification );
    }

    handleLocalTimeout( notificationId ) {
        this.log( `Local timeout for notification ${notificationId}` );

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state || state.isResponded ) return;

        state.isExpired = true;

        const card = document.getElementById( `action-required-${notificationId}` );
        if ( !card ) return;

        // Phase 2.2: Change to 'expired' state (stay in-place, no movement)
        card.classList.remove( 'active' );
        card.classList.add( 'expired' );

        // Remove progress bar and update timer
        const progress = document.getElementById( `progress-${notificationId}` );
        const timer = document.getElementById( `timer-${notificationId}` );
        if ( progress && progress.parentElement ) progress.parentElement.remove();
        if ( timer ) timer.textContent = '⏰ Expired';

        // Replace buttons with status badge showing default was used
        let defaultValue = state.notification.response_default || 'none';

        // Phase 2.4.2: For open-ended responses, submit the current input value
        if ( state.notification.response_type === 'open_ended' ) {
            const input = card.querySelector( '.response-text-input' );
            if ( input && input.value.trim() ) {
                defaultValue = input.value.trim();
                // Submit the current input value to backend
                this.submitResponse( notificationId, defaultValue );
            }
        }

        const buttonsContainer = card.querySelector( '.response-buttons, .response-open-ended' );
        if ( buttonsContainer ) {
            buttonsContainer.innerHTML = `
                <div class="notification-status-badge expired">
                    ⏰ Expired - Default used: ${defaultValue}
                </div>
            `;
        }

        // Keep notification in list (no removal, no timeout)
        // User can manually dismiss later if needed
    }

    handleNotificationResponded( envelope ) {
        this.log( "Notification responded event (multi-device sync):", envelope );

        const notificationId = envelope.notification_id;
        const response = envelope.response_value;

        // Check if we have this in our action-required list
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) {
            this.log( "Not in action-required list (already handled or different device)" );
            return;
        }

        if ( state.isResponded ) {
            this.log( "Already marked as responded locally" );
            return;
        }

        // Another device/tab responded
        this.log( `Response from another session: ${response}` );

        // Mark as responded
        state.isResponded = true;

        // Stop countdown
        this.stopCountdownTimer( notificationId );

        // Phase 5: Add response to sender card as outgoing message
        if ( state.notification ) {
            const responseNotification = {
                ...state.notification,
                message       : `Response: ${response}`,
                timestamp     : new Date().toISOString(),
                response_value: response
            };
            this.addNotificationToSenderGroup( responseNotification, true );  // true = outgoing/response
            this.updateTotalNotificationsCount();
        }

        // Phase 2.2: Show responded state in-place (different message for multi-device)
        const card = document.getElementById( `action-required-${notificationId}` );
        if ( card ) {
            card.classList.remove( 'active' );
            card.classList.add( 'responded' );

            // Remove progress bar and update timer
            const progress = document.getElementById( `progress-${notificationId}` );
            const timer = document.getElementById( `timer-${notificationId}` );
            if ( progress && progress.parentElement ) progress.parentElement.remove();
            if ( timer ) timer.textContent = '✓ Responded (other device)';

            // Replace buttons with status badge
            const buttonsContainer = card.querySelector( '.response-buttons, .response-open-ended' );
            if ( buttonsContainer ) {
                buttonsContainer.innerHTML = `
                    <div class="notification-status-badge responded">
                        ✓ Responded in another session: ${response}
                    </div>
                `;
            }
        }
    }

    handleNotificationExpired( envelope ) {
        this.log( "Notification expired event:", envelope );

        const notificationId = envelope.notification_id;

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) {
            this.log( "Not in action-required list" );
            return;
        }

        // Server timeout occurred
        this.handleLocalTimeout( notificationId );
    }

    stopCountdownTimer( notificationId ) {
        const intervalHandle = this.countdownTimers.get( notificationId );
        if ( intervalHandle ) {
            clearInterval( intervalHandle );
            this.countdownTimers.delete( notificationId );
        }
    }

    updateActionRequiredCount() {
        // Phase 2.2: Count only ACTIVE notifications (not responded/expired)
        const activeCount = Array.from( this.actionRequiredNotifications.values() )
            .filter( state => !state.isResponded && !state.isExpired ).length;

        const countElement = document.getElementById( 'action-required-count' );
        if ( countElement ) {
            countElement.textContent = activeCount;
        }

        // Phase 2.2: Show empty state if no active notifications, but keep section visible
        const emptyState = document.getElementById( 'action-required-empty' );
        const container = document.getElementById( 'action-required-list' );

        if ( activeCount === 0 && container ) {
            // Check if there are any notification cards at all
            const cards = container.querySelectorAll( '.action-required-notification' );
            if ( cards.length === 0 && emptyState ) {
                emptyState.style.display = 'block';  // Show empty state
            }
        } else if ( emptyState ) {
            emptyState.style.display = 'none';  // Hide empty state when active notifications exist
        }

        // Section stays visible always (Phase 2.2 change)
    }

    attachKeyboardListener() {
        if ( this.keyboardListenerActive ) return;

        document.addEventListener( 'keypress', ( e ) => {
            // Only respond if there's an active action-required notification
            if ( this.actionRequiredNotifications.size === 0 ) return;

            // Get first (oldest) notification
            const firstId = this.actionRequiredNotifications.keys().next().value;
            const state = this.actionRequiredNotifications.get( firstId );
            if ( !state || state.isResponded ) return;

            // Only for yes/no type
            if ( state.notification.response_type !== 'yes_no' ) return;

            // Check key
            if ( e.key.toLowerCase() === 'y' ) {
                this.submitResponse( firstId, 'yes' );
            } else if ( e.key.toLowerCase() === 'n' ) {
                this.submitResponse( firstId, 'no' );
            }
        } );

        this.keyboardListenerActive = true;
        this.log( "Keyboard listener attached for Yes/No shortcuts" );
    }

    async startVoiceInput( notificationId ) {
        this.log( `Starting voice input for ${notificationId}` );

        const micButton = document.querySelector( `[data-notification-id="${notificationId}"].response-mic-button` );
        const textInput = document.getElementById( `response-input-${notificationId}` );

        if ( !micButton || !textInput ) {
            this.error( `Voice input: Could not find UI elements for ${notificationId}` );
            return;
        }

        // Toggle recording state
        if ( this.audioRecorder && this.audioRecorder.isRecording ) {
            // Stop recording
            this.log( 'Stopping audio recording...' );
            await this.audioRecorder.stopRecording();
        } else {
            // Start recording
            const token = localStorage.getItem( 'lupin_access_token' );

            if ( !token ) {
                this.error( 'No authentication token found' );
                alert( 'Authentication required. Please log in.' );
                return;
            }

            this.audioRecorder = new AudioRecorder({
                uploadEndpoint: '/api/upload-and-transcribe-mp3',
                authToken: token,
                onRecordingStart: () => {
                    this.log( 'Audio recording started' );
                    micButton.classList.add( 'recording' );
                    micButton.textContent = '🔴';
                    micButton.title = 'Click to stop recording (ESC to cancel)';

                    // Start duration counter
                    this._startDurationCounter( notificationId, micButton );

                    // Attach ESC key listener
                    this._attachRecordingCancelListener( notificationId, micButton );
                },
                onRecordingStop: ( audioBlob ) => {
                    this.log( `Audio recording stopped: ${audioBlob.size} bytes` );

                    // Stop duration counter
                    this._stopDurationCounter( notificationId );

                    // Remove ESC key listener (upload starting)
                    this._detachRecordingCancelListener();

                    // Show processing state
                    micButton.classList.remove( 'recording' );
                    micButton.classList.add( 'processing' );
                    micButton.textContent = '⏳';
                    micButton.title = 'Transcribing audio...';
                    micButton.disabled = true;
                },
                onTranscription: ( text ) => {
                    this.log( `Transcription received: "${text}"` );

                    // Fill text input with transcription
                    textInput.value = text;
                    textInput.focus();
                    textInput.select();

                    // Trigger validation
                    textInput.dispatchEvent( new Event( 'input', { bubbles: true } ) );

                    // Reset button UI
                    micButton.classList.remove( 'processing' );
                    micButton.textContent = '🎤';
                    micButton.title = 'Click to start recording (30s max, ESC to cancel)';
                    micButton.disabled = false;

                    // Remove ESC key listener (completed successfully)
                    this._detachRecordingCancelListener();
                },
                onError: ( error ) => {
                    this.error( `Audio recording error: ${error.type} - ${error.message}` );

                    // Stop duration counter
                    this._stopDurationCounter( notificationId );

                    // Remove ESC key listener (error occurred)
                    this._detachRecordingCancelListener();

                    // Show error to user
                    alert( error.message );

                    // Reset button UI
                    micButton.classList.remove( 'recording', 'processing' );
                    micButton.textContent = '🎤';
                    micButton.title = 'Click to start recording (30s max, ESC to cancel)';
                    micButton.disabled = false;
                },
                debug: this.debug
            });

            try {
                await this.audioRecorder.startRecording();
            } catch ( error ) {
                // Error already handled by onError callback
                this.error( `Failed to start recording: ${error}` );
            }
        }
    }

    _startDurationCounter( notificationId, micButton ) {
        // Clear any existing counter
        this._stopDurationCounter( notificationId );

        const startTime = Date.now();

        this.audioRecording = this.audioRecording || {};
        this.audioRecording[notificationId] = {
            startTime: startTime,
            interval: setInterval( () => {
                const elapsed = Math.floor( (Date.now() - startTime) / 1000 );
                const MAX_DURATION_SECONDS = 30;  // Whisper API limit

                // Yellow warning at 25+ seconds, red icon before that
                const icon = elapsed >= 25 ? '🟡' : '🔴';
                micButton.textContent = `${icon} ${elapsed}/${MAX_DURATION_SECONDS}s`;
                micButton.title = `Recording: ${elapsed}/${MAX_DURATION_SECONDS}s (ESC to cancel)`;
            }, 1000 )
        };
    }

    _stopDurationCounter( notificationId ) {
        if ( this.audioRecording && this.audioRecording[notificationId] ) {
            clearInterval( this.audioRecording[notificationId].interval );
            delete this.audioRecording[notificationId];
        }
    }

    /**
     * Attach keyboard listener for ESC key to cancel recording
     *
     * Requires:
     *   - notificationId is valid
     *   - micButton element exists
     *
     * Ensures:
     *   - ESC key listener attached to document
     *   - Only one listener active at a time
     *   - Listener stored for cleanup
     */
    _attachRecordingCancelListener( notificationId, micButton ) {
        // Remove any existing listener first
        this._detachRecordingCancelListener();

        // Create and store the listener
        this._recordingCancelListener = ( event ) => {
            if ( event.key === 'Escape' ) {
                this.log( `ESC key pressed - cancelling recording for ${notificationId}` );
                event.preventDefault();
                event.stopPropagation();
                this._cancelRecording( notificationId, micButton );
            }
        };

        // Attach to document
        document.addEventListener( 'keydown', this._recordingCancelListener );
        this.log( `ESC key listener attached for ${notificationId}` );
    }

    /**
     * Detach keyboard listener for ESC key
     *
     * Ensures:
     *   - ESC key listener removed from document
     *   - Listener reference cleared
     */
    _detachRecordingCancelListener() {
        if ( this._recordingCancelListener ) {
            document.removeEventListener( 'keydown', this._recordingCancelListener );
            this._recordingCancelListener = null;
            this.log( 'ESC key listener detached' );
        }
    }

    /**
     * Cancel recording without uploading
     *
     * Requires:
     *   - notificationId is valid
     *   - micButton element exists
     *
     * Ensures:
     *   - Recording stopped
     *   - Audio discarded (no upload)
     *   - UI reset to idle state
     *   - Duration counter stopped
     *   - ESC listener removed
     */
    _cancelRecording( notificationId, micButton ) {
        this.log( `Cancelling recording for ${notificationId}` );

        // Stop duration counter
        this._stopDurationCounter( notificationId );

        // Destroy audio recorder without uploading
        if ( this.audioRecorder ) {
            this.audioRecorder._cancelling = true;  // Signal cancellation to prevent upload
            this.audioRecorder.destroy();
            this.audioRecorder = null;
        }

        // Reset UI
        micButton.classList.remove( 'recording', 'processing' );
        micButton.textContent = '🎤';
        micButton.title = 'Click to start recording (30s max, ESC to cancel)';
        micButton.disabled = false;

        // Remove ESC listener
        this._detachRecordingCancelListener();

        this.log( 'Recording cancelled successfully' );
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