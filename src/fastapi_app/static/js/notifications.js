/**
 * Notifications UI - Unified JavaScript Module
 * Single-file implementation to replace complex multi-file architecture
 * Handles WebSocket connections, authentication, Q&A, and TTS functionality
 */

class NotificationsUI {
    constructor() {
        // Configuration
        this.debug = true;
        this.verbose = true;

        // TTS Mode Constants
        this.TTS_MODE_INSTANT = 'instant';
        this.TTS_MODE_RELIABLE = 'reliable';
        this.TTS_MODE_DEFAULT = this.TTS_MODE_INSTANT;  // Default to instant (PCM 24000 streaming)

        // WebSocket connections
        this.queueWS = null;
        this.audioWS = null;
        this.claudeCodeWs = null;  // Claude Code Dispatcher WebSocket

        // Claude Code Dispatcher state
        this.currentClaudeCodeTaskId = null;

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
        // OLD: HTML Audio sequential chain (commented out - choppy)
        this.sequentialQueue = [];
        this.isSequentialPlaying = false;
        this.currentSequentialAudio = null;
        this.sequentialChunksPlayed = 0;

        // NEW: PCM 24000 playback state (ElevenLabs instant mode)
        // Web Audio API with precise scheduling for smooth playback
        this.pcmAudioContext = null;
        this.pcmNextStartTime = 0;
        this.pcmStreamComplete = false;  // True when all chunks received (but playback may continue)
        this.lastPCMSource = null;       // Reference to last scheduled AudioBufferSourceNode

        // First chunk timing for instant mode
        this.firstChunkStartTime = null;
        this.firstChunkPlayed = false;
        
        // State management
        this.isConnecting = false;
        this.connectionRetries = 0;
        this.maxRetries = 5;
        this.authRefreshAttempted = false; // Track refresh attempts to prevent loops
        this.isInitialLoad = false;        // Track initial load vs runtime for card ordering
        
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
        this.QUEUE_SESSION_KEY = 'notifications_queue_session_id';
        this.AUDIO_SESSION_KEY = 'notifications_audio_session_id';
        this.USER_EMAIL_KEY = 'notifications_user_email';
        this.VERSION_KEY = 'notifications_version';
        this.QUEUE_FILTER_PREF_KEY = 'notifications_filter_preference';  // Filter mode storage
        this.ACTION_REQUIRED_KEY = 'notifications_action_required';  // Persist action-required notifications
        this.TTS_QUEUE_KEY = 'notifications_tts_queue';  // Persist TTS queue across refresh
        this.SESSION_NAMES_KEY = 'notifications_session_names';  // Persist user-edited session names
        this.CURRENT_VERSION = '2.0.0'; // Increment to invalidate old cache - date grouping release

        // Session names cache (loaded from localStorage)
        this.sessionNames = JSON.parse( localStorage.getItem( this.SESSION_NAMES_KEY ) ) || {};

        // User role and filter state
        this.userRoles = [];  // NEW: User's roles from JWT
        this.isAdmin = false;  // NEW: Quick admin check
        this.queueFilterMode = 'own';  // NEW: 'own' or 'all' (admin only)

        // ========================================
        // PROGRESSIVE DISCLOSURE QUEUE UI STATE
        // ========================================
        // State management for expandable queue categories and job cards
        this.queueCategoryState = {
            todo : { expanded: false, loaded: false, jobs: [] },
            run  : { expanded: false, loaded: false, jobs: [] },
            done : { expanded: false, loaded: false, jobs: [] },
            dead : { expanded: false, loaded: false, jobs: [] }
        };
        this.expandedJobCards = new Set();         // Track which job cards are expanded
        this.jobInteractionsCache = new Map();     // Cache loaded interactions: job_id → interactions[]

        // Phase 2.2 SSE - Action Required notifications state
        this.actionRequiredNotifications = new Map();  // notification_id → notification data + UI state
        this.countdownTimers = new Map();  // notification_id → setInterval handle
        this.keyboardListenerActive = false;  // Track if keyboard listener is attached

        // ========================================
        // ACTION-REQUIRED QUEUE SYSTEM
        // ========================================
        // Only ONE notification can be "active" (fully displayed) at a time.
        // Additional notifications are queued and shown as minimized one-liners.
        // Timers only start when a notification becomes active.
        this.actionRequiredQueue = [];           // Ordered array of notification IDs (FIFO)
        this.activeActionRequiredId = null;      // Currently active notification ID (or null)

        // ========================================
        // UNIFIED TTS QUEUE SYSTEM
        // ========================================
        // Single queue for ALL notification types (action-required + fire-and-forget)
        // Priority insertion: action-required at FRONT, fire-and-forget at BACK
        // One TTS plays at a time - prevents audio collisions
        this.ttsQueue = [];                      // FIFO array of {id, type, notification, ttsText, addedAt}
        this.activeTTSItem = null;               // Currently playing TTS item (or null)

        // Focus Mode: Pause TTS queue while responding to action-required notification
        this.ttsFocusModeActive = false;         // True when queue is paused for response
        this.focusModeNotificationId = null;     // Which action-required triggered focus mode

        // ========================================
        // GENIE ANIMATION STATE
        // ========================================
        this.activeAnimations = new Map();  // notificationId → { element, animation, destination }
        this.ANIMATION_DURATION_MS = 600;   // Total animation time in milliseconds
        this.ANIMATION_EASING = 'cubic-bezier(0.25, 0.1, 0.25, 1)';  // Smooth ease-out

        // ========================================
        // SENDER-AWARE NOTIFICATION GROUPING WITH DATE ACCORDIONS
        // ========================================

        // Sender groups: Map<sender_id, {
        //   dateGroups: Map<dateString, notifications[]>,
        //   collapsed: boolean,
        //   lastActivity: Date,
        //   totalCount: number,
        //   newCount: number
        // }>
        this.senderGroups = new Map();

        // Default sender for notifications without sender_id
        this.UNKNOWN_SENDER = "claude.code@unknown.deepily.ai";

        // History window configuration (activity-anchored loading)
        this.HISTORY_WINDOW_KEY = 'notifications_history_window';
        this.historyWindowHours = parseInt( localStorage.getItem( this.HISTORY_WINDOW_KEY ) ) || 48; // Default to 2 days
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

        // ========================================
        // SECTION VISIBILITY TOOLBAR STATE
        // ========================================
        this.SECTION_VISIBILITY_KEY = 'lupin_section_visibility';
        this.sectionVisibility = this.loadSectionVisibility();

        // Initialize
        this.init();
    }
    
    // ========================================
    // INITIALIZATION
    // ========================================
    
    async init() {
        this.log( "NotificationsUI initializing..." );
        
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

            // Initialize section visibility toolbar
            this.initToolbar();

            // Initialize unified recording manager
            this.initRecordingManager();

            // Apply Firefox compatibility hack
            this.applyFirefoxCompatibilityHack();

            // Initialize history dropdown UI
            this.initializeHistoryDropdown();

            // Connect WebSockets
            await this.connectWebSockets();

            // Load conversation history (after auth is complete)
            await this.loadConversationHistory();

            // Restore action-required notifications from localStorage (refresh survival)
            this.restoreActionRequiredState();

            // Restore TTS queue from localStorage (refresh survival)
            this.restoreTTSQueueState();

            // Auto-focus STT button for spacebar activation
            document.getElementById( 'qa-stt-button' ).focus();

            this.log( "NotificationsUI initialization complete" );

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

        // Load user's current agent mode from server
        await this.loadCurrentMode();
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
                this.appTimezone = config.app_timezone;

                // Log configuration for debugging
                this.log( "✓ Client config loaded from server:", {
                    refresh_check_interval : `${config.token_refresh_check_interval_ms / 60000} mins`,
                    expiry_threshold       : `${config.token_expiry_threshold_secs / 60} mins`,
                    dedup_window           : `${config.token_refresh_dedup_window_ms / 1000} secs`,
                    heartbeat_interval     : `${config.websocket_heartbeat_interval_secs} secs`,
                    app_timezone           : config.app_timezone
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
            this.appTimezone = 'America/New_York';                  // Default timezone

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
            // Pattern: notification-{priority}-priority-v2.mp3 (no sound for low priority)
            this.notificationSounds = {
                urgent: new Audio( '/static/audio/notification-urgent-priority-v2.mp3' ),
                high: new Audio( '/static/audio/notification-high-priority-v2.mp3' ),
                medium: new Audio( '/static/audio/notification-medium-priority-v2.mp3' ),
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
                    audio = this.notificationSounds.urgent;
                    this.log( `Playing urgent priority notification sound` );
                    break;
                case "high":
                    audio = this.notificationSounds.high;
                    this.log( `Playing high priority notification sound` );
                    break;
                case "medium":
                    audio = this.notificationSounds.medium;
                    this.log( `Playing medium priority notification sound` );
                    break;
                case "low":
                    // No sound for low priority notifications
                    this.log( `Skipping sound for low priority notification` );
                    return;
                case "error":
                    audio = this.notificationSounds.error;
                    this.log( `Playing error notification sound` );
                    break;
                default:
                    // Default to medium priority sound for unknown priorities
                    audio = this.notificationSounds.medium;
                    this.log( `Playing default (medium) notification sound for unknown priority: ${priority}` );
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

        // NOTE: Ctrl+R shortcut removed - multiple recording contexts in same window
        // make keyboard shortcut ambiguous. Use mic buttons directly.

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
            this.cancelActiveAnimations();
        });

        // Claude Code Dispatcher event listeners
        this.setupClaudeCodeEventListeners();

        this.log( "Event listeners setup complete" );
    }

    setupClaudeCodeEventListeners() {
        // Submit button
        const submitBtn = document.getElementById( 'cc-submit' );
        if ( submitBtn ) {
            submitBtn.addEventListener( 'click', () => {
                this.submitClaudeCode();
            });
        }

        // Claude Code Dispatcher STT button (voice input for task prompt)
        const ccSttBtn = document.getElementById( 'cc-stt-button' );
        if ( ccSttBtn ) {
            ccSttBtn.addEventListener( 'click', () => {
                this.handleCCSTTButtonClick();
            });
        }

        // Inject button (Option B)
        const injectBtn = document.getElementById( 'cc-inject-btn' );
        if ( injectBtn ) {
            injectBtn.addEventListener( 'click', () => {
                this.injectClaudeCode();
            });
        }

        // Interrupt button (Option B)
        const interruptBtn = document.getElementById( 'cc-interrupt-btn' );
        if ( interruptBtn ) {
            interruptBtn.addEventListener( 'click', () => {
                this.interruptClaudeCode();
            });
        }

        // End Session button (Option B)
        const endBtn = document.getElementById( 'cc-end-btn' );
        if ( endBtn ) {
            endBtn.addEventListener( 'click', () => {
                this.endClaudeCodeSession();
            });
        }

        // Show/hide Option B controls based on task type selection
        document.querySelectorAll( 'input[name="cc-task-type"]' ).forEach( radio => {
            radio.addEventListener( 'change', ( e ) => {
                const optionBControls = document.getElementById( 'cc-option-b-controls' );
                if ( optionBControls ) {
                    optionBControls.style.display = e.target.value === 'INTERACTIVE' ? 'block' : 'none';
                }
            });
        });

        // Enter key in inject input
        const injectInput = document.getElementById( 'cc-inject-input' );
        if ( injectInput ) {
            injectInput.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' ) {
                    e.preventDefault();
                    this.injectClaudeCode();
                }
            });
        }

        // Ctrl+Enter in prompt to submit
        const promptInput = document.getElementById( 'cc-prompt' );
        if ( promptInput ) {
            promptInput.addEventListener( 'keydown', ( e ) => {
                if ( e.ctrlKey && e.key === 'Enter' ) {
                    e.preventDefault();
                    this.submitClaudeCode();
                }
            });
        }

        this.log( "Claude Code Dispatcher event listeners setup complete" );

        // ========================================
        // Agent Mode Selector
        // ========================================

        const agentModeSelect = document.getElementById( 'agent-mode' );
        const modeBadge = document.getElementById( 'mode-badge' );
        const modeStatus = document.getElementById( 'mode-status' );

        if ( agentModeSelect ) {
            agentModeSelect.addEventListener( 'change', async ( e ) => {
                const mode = e.target.value === 'system' ? null : e.target.value;
                await this.setAgentMode( mode );
            });
        }

        if ( modeBadge ) {
            modeBadge.addEventListener( 'click', async () => {
                // Click badge to return to system mode
                await this.setAgentMode( null );
                if ( agentModeSelect ) {
                    agentModeSelect.value = 'system';
                }
            });
        }

        this.log( "Agent mode selector event listeners setup complete" );
    }

    /**
     * Cancel all active genie animations.
     * Called on page unload to ensure clean state.
     */
    cancelActiveAnimations() {
        if ( this.activeAnimations.size > 0 ) {
            this.log( `Cancelling ${this.activeAnimations.size} active animations` );
            this.activeAnimations.forEach( ( state, notificationId ) => {
                if ( state.element && state.element.parentNode ) {
                    state.element.remove();
                }
            } );
            this.activeAnimations.clear();
        }
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
                "tts_error",
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

                case "active_conversation_changed":
                    // Conversation Identity Phase 3 - Update active sender indicator
                    this.handleActiveConversationChanged( envelope.data || envelope );
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

                case "tts_error":
                    this.handleTTSError( envelope );
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
    // RECORDING MANAGER - Unified STT Recording
    // ========================================

    /**
     * Unified recording manager for all STT (Speech-to-Text) contexts.
     * Handles Q&A input, notification responses, multiple-choice "Other", and Claude Code Dispatcher.
     *
     * Design decisions:
     * - Single AudioRecorder instance (auto-cancels previous recording when new one starts)
     * - Timer starts at "0/30s" to prevent button width change
     * - ESC key cancels recording without uploading
     */
    initRecordingManager() {
        this.recordingManager = {
            ui                   : this,
            audioRecorder        : null,
            activeRecording      : null,  // { contextId, button, inputElement, options }
            cancelListener       : null,
            durationInterval     : null,
            MAX_DURATION_SECONDS : 30,

            /**
             * Start recording for a given context.
             * Auto-cancels any active recording before starting.
             *
             * @param {string} contextId - Unique identifier for this recording context
             * @param {HTMLElement} button - The mic button element
             * @param {HTMLElement} inputElement - The text input to fill with transcription
             * @param {object} options - Optional callbacks and settings
             *   - onTranscriptionComplete: Called after filling input (for context-specific logic)
             *   - autoSelectElement: Element to auto-select (e.g., "Other" radio button)
             */
            startRecording: async function( contextId, button, inputElement, options = {} ) {
                const self = this;

                // Auto-cancel any active recording
                if ( this.activeRecording ) {
                    this.ui.log( `Auto-cancelling previous recording: ${this.activeRecording.contextId}` );
                    this.cancelRecording();
                }

                // Get auth token
                const token = localStorage.getItem( 'lupin_access_token' ) || this.ui.authToken;
                if ( !token ) {
                    alert( 'Please log in to use voice input' );
                    return;
                }

                // Auto-select element if provided (e.g., "Other" radio for MC)
                if ( options.autoSelectElement ) {
                    options.autoSelectElement.checked = true;
                }

                // Track active recording
                this.activeRecording = { contextId, button, inputElement, options };

                try {
                    this.audioRecorder = new AudioRecorder( {
                        uploadEndpoint : '/api/upload-and-transcribe-mp3',
                        authToken      : token,

                        onRecordingStart: () => {
                            self.ui.log( `Recording started: ${contextId}` );
                            button.classList.add( 'recording' );
                            button.textContent = `🔴 0/${self.MAX_DURATION_SECONDS}s`;
                            button.title = `Recording: 0/${self.MAX_DURATION_SECONDS}s (ESC to cancel)`;
                            self._startDurationCounter( button );
                            self._attachCancelListener( button );
                        },

                        onRecordingStop: ( audioBlob ) => {
                            self.ui.log( `Recording stopped: ${contextId}, ${audioBlob.size} bytes` );
                            self._stopDurationCounter();
                            self._detachCancelListener();
                            button.classList.remove( 'recording' );
                            button.classList.add( 'processing' );
                            button.textContent = '⏳';
                            button.title = 'Transcribing audio...';
                            button.disabled = true;
                        },

                        onTranscription: ( text ) => {
                            self.ui.log( `Transcription received for ${contextId}: "${text}"` );

                            // Fill text input
                            inputElement.value = text;
                            inputElement.focus();
                            inputElement.select();

                            // Trigger input event for validation
                            inputElement.dispatchEvent( new Event( 'input', { bubbles: true } ) );

                            // Reset button UI
                            self._resetButton( button );

                            // Call context-specific completion handler
                            if ( options.onTranscriptionComplete ) {
                                options.onTranscriptionComplete( text );
                            }

                            // Clear active recording
                            self.activeRecording = null;
                        },

                        onError: ( error ) => {
                            self.ui.error( `Recording error for ${contextId}: ${error.type} - ${error.message}` );
                            self._stopDurationCounter();
                            self._detachCancelListener();
                            alert( error.message );
                            self._resetButton( button );
                            self.activeRecording = null;
                        },

                        debug: self.ui.debug
                    } );

                    await this.audioRecorder.startRecording();

                } catch ( error ) {
                    this.ui.error( `Failed to start recording for ${contextId}: ${error}` );
                    alert( `Failed to start recording: ${error.message}` );
                    this._resetButton( button );
                    this.activeRecording = null;
                }
            },

            /**
             * Stop recording (user clicked mic button while recording).
             */
            stopRecording: async function() {
                if ( this.audioRecorder && this.audioRecorder.isRecording ) {
                    this.ui.log( 'Stopping recording via user action...' );
                    await this.audioRecorder.stopRecording();
                }
            },

            /**
             * Cancel recording without uploading (ESC key or auto-cancel).
             */
            cancelRecording: function() {
                if ( !this.activeRecording ) return;

                const { contextId, button } = this.activeRecording;
                this.ui.log( `Cancelling recording: ${contextId}` );

                this._stopDurationCounter();
                this._detachCancelListener();

                if ( this.audioRecorder ) {
                    this.audioRecorder._cancelling = true;
                    this.audioRecorder.destroy();
                    this.audioRecorder = null;
                }

                this._resetButton( button );
                this.activeRecording = null;
            },

            /**
             * Check if currently recording.
             */
            isRecording: function() {
                return this.audioRecorder && this.audioRecorder.isRecording;
            },

            /**
             * Check if currently processing (uploading/transcribing).
             */
            isProcessing: function() {
                return this.audioRecorder && this.audioRecorder.isProcessing;
            },

            // --- Private helpers ---

            _startDurationCounter: function( button ) {
                const self = this;
                const startTime = Date.now();

                // Immediately show 0/30s (already set in onRecordingStart)
                this.durationInterval = setInterval( () => {
                    const elapsed = Math.floor( ( Date.now() - startTime ) / 1000 );
                    const icon = elapsed >= 25 ? '🟡' : '🔴';
                    button.textContent = `${icon} ${elapsed}/${self.MAX_DURATION_SECONDS}s`;
                    button.title = `Recording: ${elapsed}/${self.MAX_DURATION_SECONDS}s (ESC to cancel)`;
                }, 1000 );
            },

            _stopDurationCounter: function() {
                if ( this.durationInterval ) {
                    clearInterval( this.durationInterval );
                    this.durationInterval = null;
                }
            },

            _attachCancelListener: function( button ) {
                const self = this;
                this.cancelListener = ( event ) => {
                    if ( event.key === 'Escape' ) {
                        event.preventDefault();
                        event.stopPropagation();
                        self.cancelRecording();
                    }
                };
                document.addEventListener( 'keydown', this.cancelListener );
            },

            _detachCancelListener: function() {
                if ( this.cancelListener ) {
                    document.removeEventListener( 'keydown', this.cancelListener );
                    this.cancelListener = null;
                }
            },

            _resetButton: function( button ) {
                button.classList.remove( 'recording', 'processing' );
                button.textContent = '🎤';
                button.title = 'Click to record (30s max, ESC to cancel)';
                button.disabled = false;
            }
        };

        this.log( 'RecordingManager initialized' );
    }

    // ========================================
    // Q&A STT (Speech-to-Text) FUNCTIONALITY
    // Now uses unified RecordingManager
    // ========================================

    async handleQASTTButtonClick() {
        const button = document.getElementById( 'qa-stt-button' );
        const textInput = document.getElementById( 'qa-input' );

        // If already recording, stop it
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
            return;
        }

        // If processing, ignore click
        if ( this.recordingManager.isProcessing() ) {
            return;
        }

        // Start new recording using unified RecordingManager
        await this.recordingManager.startRecording( 'qa', button, textInput );
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
    // CLAUDE CODE DISPATCHER
    // ========================================

    /**
     * Handle click on Claude Code Dispatcher STT button.
     * Uses unified RecordingManager for voice input.
     */
    async handleCCSTTButtonClick() {
        const button = document.getElementById( 'cc-stt-button' );
        const textInput = document.getElementById( 'cc-prompt' );

        // Toggle recording state using unified RecordingManager
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
        } else if ( !this.recordingManager.isProcessing() ) {
            await this.recordingManager.startRecording( 'cc-prompt', button, textInput );
        }
    }

    async submitClaudeCode() {
        const project = document.getElementById( 'cc-project' ).value;
        const prompt = document.getElementById( 'cc-prompt' ).value;
        const taskType = document.querySelector( 'input[name="cc-task-type"]:checked' ).value;

        if ( !prompt.trim() ) {
            alert( 'Please enter a task prompt' );
            return;
        }

        // Show loading state
        const loadingEl = document.getElementById( 'cc-loading' );
        const submitBtn = document.getElementById( 'cc-submit' );
        const responseEl = document.getElementById( 'cc-response' );

        if ( loadingEl ) loadingEl.style.display = 'inline-block';
        if ( submitBtn ) submitBtn.disabled = true;
        if ( responseEl ) responseEl.textContent = 'Dispatching task...';

        this.log( `Claude Code dispatch: project=${project}, type=${taskType}` );

        try {
            const response = await fetch( '/api/claude-code/dispatch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify( { project, prompt, task_type: taskType } )
            });

            if ( !response.ok ) {
                const errorData = await response.json();
                throw new Error( errorData.detail || 'Dispatch failed' );
            }

            const data = await response.json();
            this.currentClaudeCodeTaskId = data.task_id;

            this.log( `Claude Code task dispatched: ${data.task_id}` );

            // Update UI
            document.getElementById( 'cc-task-id' ).textContent = data.task_id;
            document.getElementById( 'cc-status' ).textContent = 'Dispatched';
            document.getElementById( 'cc-session-info' ).style.display = 'flex';

            // Clear response area
            if ( responseEl ) responseEl.textContent = '';

            // Connect to WebSocket for streaming
            this.connectClaudeCodeWebSocket( data.task_id );

        } catch ( error ) {
            this.error( 'Claude Code dispatch failed:', error );
            if ( responseEl ) responseEl.textContent = `Error: ${error.message}`;
        } finally {
            if ( loadingEl ) loadingEl.style.display = 'none';
            if ( submitBtn ) submitBtn.disabled = false;
        }
    }

    connectClaudeCodeWebSocket( taskId ) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/claude-code/ws/${taskId}`;

        this.log( `Connecting to Claude Code WebSocket: ${wsUrl}` );

        this.claudeCodeWs = new WebSocket( wsUrl );

        this.claudeCodeWs.onopen = () => {
            this.log( 'Claude Code WebSocket connected' );
            document.getElementById( 'cc-status' ).textContent = 'Connected';
        };

        this.claudeCodeWs.onmessage = ( event ) => {
            try {
                const data = JSON.parse( event.data );
                this.handleClaudeCodeMessage( data );
            } catch ( e ) {
                this.error( 'Failed to parse Claude Code message:', e );
            }
        };

        this.claudeCodeWs.onclose = ( event ) => {
            this.log( `Claude Code WebSocket closed: code=${event.code}` );
            const statusEl = document.getElementById( 'cc-status' );
            if ( statusEl && statusEl.textContent === 'Running' ) {
                statusEl.textContent = 'Disconnected';
            }
        };

        this.claudeCodeWs.onerror = ( error ) => {
            this.error( 'Claude Code WebSocket error:', error );
        };
    }

    handleClaudeCodeMessage( data ) {
        const responseArea = document.getElementById( 'cc-response' );
        if ( !responseArea ) return;

        switch ( data.type ) {
            case 'connected':
                this.log( `Claude Code connected: task=${data.task_id}` );
                break;

            case 'status':
                document.getElementById( 'cc-status' ).textContent = data.state || 'Unknown';
                break;

            case 'text':
                responseArea.textContent += data.content;
                break;

            case 'tool_use':
                responseArea.textContent += `\n[TOOL: ${data.name}]\n`;
                break;

            case 'tool_result':
                const content = typeof data.content === 'string' ? data.content : JSON.stringify( data.content );
                responseArea.textContent += `${content}\n`;
                break;

            case 'complete':
                document.getElementById( 'cc-status' ).textContent = data.success ? 'Complete' : 'Failed';
                if ( data.cost_usd ) {
                    document.getElementById( 'cc-cost' ).textContent = `$${data.cost_usd.toFixed( 4 )}`;
                }
                if ( data.error ) {
                    responseArea.textContent += `\n[ERROR: ${data.error}]\n`;
                }
                break;

            case 'error':
                responseArea.textContent += `\n[ERROR: ${data.message}]\n`;
                document.getElementById( 'cc-status' ).textContent = 'Error';
                break;

            case 'info':
                responseArea.textContent += `[INFO: ${data.content}]\n`;
                break;

            case 'keepalive':
                // Ignore keepalive messages
                break;

            default:
                this.log( `Unknown Claude Code message type: ${data.type}` );
        }

        // Auto-scroll
        responseArea.scrollTop = responseArea.scrollHeight;
    }

    async injectClaudeCode() {
        const injectInput = document.getElementById( 'cc-inject-input' );
        const message = injectInput ? injectInput.value.trim() : '';

        if ( !message || !this.currentClaudeCodeTaskId ) {
            if ( !message ) alert( 'Please enter a follow-up message' );
            return;
        }

        this.log( `Injecting message: ${message.substring( 0, 50 )}...` );

        try {
            const response = await fetch( `/api/claude-code/${this.currentClaudeCodeTaskId}/inject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify( { message } )
            });

            if ( !response.ok ) {
                const errorData = await response.json();
                throw new Error( errorData.detail || 'Inject failed' );
            }

            // Clear input and show in response
            if ( injectInput ) injectInput.value = '';
            const responseEl = document.getElementById( 'cc-response' );
            if ( responseEl ) {
                responseEl.textContent += `\n[YOU: ${message}]\n`;
                responseEl.scrollTop = responseEl.scrollHeight;
            }

            this.log( 'Message injected successfully' );

        } catch ( error ) {
            this.error( 'Inject failed:', error );
            alert( `Inject failed: ${error.message}` );
        }
    }

    async interruptClaudeCode() {
        if ( !this.currentClaudeCodeTaskId ) return;

        this.log( 'Interrupting Claude Code session' );

        try {
            const response = await fetch( `/api/claude-code/${this.currentClaudeCodeTaskId}/interrupt`, {
                method: 'POST'
            });

            if ( !response.ok ) {
                const errorData = await response.json();
                throw new Error( errorData.detail || 'Interrupt failed' );
            }

            const responseEl = document.getElementById( 'cc-response' );
            if ( responseEl ) {
                responseEl.textContent += '\n[INTERRUPTED]\n';
            }

            this.log( 'Session interrupted' );

        } catch ( error ) {
            this.error( 'Interrupt failed:', error );
            alert( `Interrupt failed: ${error.message}` );
        }
    }

    async endClaudeCodeSession() {
        if ( !this.currentClaudeCodeTaskId ) return;

        this.log( 'Ending Claude Code session' );

        try {
            const response = await fetch( `/api/claude-code/${this.currentClaudeCodeTaskId}/end`, {
                method: 'POST'
            });

            if ( !response.ok ) {
                const errorData = await response.json();
                throw new Error( errorData.detail || 'End session failed' );
            }

            document.getElementById( 'cc-status' ).textContent = 'Ended';
            this.currentClaudeCodeTaskId = null;

            if ( this.claudeCodeWs ) {
                this.claudeCodeWs.close();
                this.claudeCodeWs = null;
            }

            this.log( 'Session ended' );

        } catch ( error ) {
            this.error( 'End session failed:', error );
            alert( `End session failed: ${error.message}` );
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
                // Notify TTS queue that playback is complete
                this.onTTSPlaybackComplete();
                resolve();
            };

            audio.onerror = ( error ) => {
                this.error( "Cached audio playback failed:", error );
                // Notify TTS queue even on error (to advance queue)
                this.onTTSPlaybackComplete();
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

        // Start pulsing indicator on notification card
        this.startTTSPlayingIndicator( this.currentNotificationId );

        try {
            // Ensure token is valid before API call (auto-refresh if expired)
            await this.ensureValidToken();

            // Start timing BEFORE the fetch for accurate TTFA measurement
            this.startTime = Date.now();
            this.metricsTTSStartTime = Date.now();

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

            // Reset PCM playback timing for new stream
            if ( this.pcmAudioContext ) {
                this.pcmNextStartTime = this.pcmAudioContext.currentTime;
            }
            this.firstChunkPlayed = false;

        } catch ( error ) {
            this.error( "Instant TTS request failed:", error );
            throw error;
        }
    }
    
    async playReliableTTS( text ) {
        this.log( "Starting reliable TTS (OpenAI batch)..." );

        // Start pulsing indicator on notification card
        this.startTTSPlayingIndicator( this.currentNotificationId );

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

    /**
     * Handle TTS service errors with visual feedback.
     *
     * Requires:
     *     - envelope contains type: "tts_error" with text, error_code, provider fields
     *
     * Ensures:
     *     - Stops TTS playing indicator if active
     *     - Shows brief red error indicator on notification card
     *     - Logs error for debugging
     *     - Cleans up TTS state
     */
    handleTTSError( envelope ) {
        const errorCode = envelope.error_code || "unknown";
        const errorText = envelope.text || "TTS service error";
        const details = envelope.details || "";

        this.error( `TTS Error [${errorCode}]: ${errorText}` );

        // Stop playing indicator if we have a notification ID
        if ( this.currentNotificationId ) {
            this.stopTTSPlayingIndicator( this.currentNotificationId );
        }

        // Show error modal overlay (works regardless of TTS context)
        this.showTTSErrorModal( errorCode, errorText, details );

        // Clean up TTS state
        this.currentTTSMode = null;
        this.pcmStreamComplete = true;

        // Notify TTS queue that playback failed
        this.onTTSPlaybackComplete();
    }

    /**
     * Show a semi-transparent modal overlay with TTS error message.
     * Auto-dismisses after 5 seconds or on click.
     */
    showTTSErrorModal( errorCode, errorText, details ) {
        // Remove any existing error modal
        const existing = document.getElementById( 'tts-error-modal' );
        if ( existing ) existing.remove();

        // Create modal overlay
        const modal = document.createElement( 'div' );
        modal.id = 'tts-error-modal';
        modal.className = 'tts-error-modal';

        // Create modal content
        modal.innerHTML = `
            <div class="tts-error-modal-content">
                <div class="tts-error-icon">⚠️</div>
                <div class="tts-error-title">TTS Error</div>
                <div class="tts-error-message">${errorText}</div>
                <div class="tts-error-code">${errorCode}</div>
                <div class="tts-error-dismiss">Click to dismiss (auto-closes in 5s)</div>
            </div>
        `;

        // Click to dismiss
        modal.addEventListener( 'click', () => {
            modal.classList.add( 'tts-error-modal-fadeout' );
            setTimeout( () => modal.remove(), 300 );
        } );

        // Add to DOM
        document.body.appendChild( modal );

        // Auto-dismiss after 5 seconds
        setTimeout( () => {
            if ( document.body.contains( modal ) ) {
                modal.classList.add( 'tts-error-modal-fadeout' );
                setTimeout( () => modal.remove(), 300 );
            }
        }, 5000 );

        this.log( `Showing TTS error modal: ${errorCode} - ${errorText}` );
    }

    handleAudioChunk( blobData ) {
        if ( this.debug ) this.log( `Received audio chunk: ${blobData.size} bytes` );

        // TEMPORARY: Only collect chunks for reliable mode (MP3)
        // PCM caching disabled until quality validated
        if ( this.currentTTSMode === this.TTS_MODE_RELIABLE ) {
            this.audioChunks = this.audioChunks || [];
            this.audioChunks.push( blobData );
        }

        if ( this.currentTTSMode === this.TTS_MODE_INSTANT ) {
            // OLD: HTML Audio sequential playback (commented out - choppy)
            // this.playChunkSequential( blobData );

            // NEW: Web Audio API with PCM 24000 precise scheduling
            this.playPCMChunk( blobData );
        }
        // For reliable mode, chunks are just collected and played later in playCollectedAudio()
    }
    
    async handleAudioComplete( data ) {
        // Handle pulsing indicator based on TTS mode
        if ( this.currentTTSMode === this.TTS_MODE_INSTANT ) {
            // For instant mode: defer indicator stop until last chunk finishes playing
            // The onended handler in playPCMChunk() will stop the indicator
            this.pcmStreamComplete = true;
        } else {
            // For reliable mode: stop immediately (playback hasn't started yet)
            // playCollectedAudio() has its own onended handler for actual playback end
            this.stopTTSPlayingIndicator( this.currentNotificationId );
        }

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
        // TEMPORARY: Only cache for reliable mode (MP3) until PCM caching validated
        if ( this.currentTTSMode === this.TTS_MODE_RELIABLE && this.audioChunks && this.audioChunks.length > 0 ) {
            // Create audio blob for caching
            const audioBlob = new Blob( this.audioChunks, { type: 'audio/mpeg' } );
            await this.cacheGeneratedAudio( audioBlob );
        }
        // NOTE: PCM caching disabled for now - chunks are raw Int16 and can't be cached as MP3

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
    // PCM 24000 PLAYBACK FOR INSTANT MODE (NEW)
    // Web Audio API with precise scheduling - replaces choppy sequential playback
    // ========================================

    initPCMAudioContext() {
        if ( !this.pcmAudioContext ) {
            this.pcmAudioContext = new ( window.AudioContext || window.webkitAudioContext )( {
                sampleRate: 24000  // Match ElevenLabs PCM 24000 format
            } );
            this.pcmNextStartTime = this.pcmAudioContext.currentTime;
            this.log( "PCM AudioContext initialized at 24kHz" );
        }
    }

    async playPCMChunk( blobData ) {
        // Capture TTFA state BEFORE any awaits to avoid race condition
        // (handleAudioComplete may reset firstChunkPlayed while we're awaiting)
        const isFirstChunk = !this.firstChunkPlayed && this.startTime;
        const ttfaStartTime = this.startTime;
        if ( isFirstChunk ) {
            this.firstChunkPlayed = true;  // Mark immediately to prevent duplicates
        }

        // Initialize context if needed
        if ( !this.pcmAudioContext ) {
            this.initPCMAudioContext();
        }

        // Resume if suspended (browser autoplay policy)
        if ( this.pcmAudioContext.state === 'suspended' ) {
            await this.pcmAudioContext.resume();
        }

        // Skip small chunks (likely metadata)
        if ( blobData.size < 100 ) {
            if ( this.debug ) this.log( `Skipping small PCM chunk: ${blobData.size} bytes` );
            return;
        }

        // Convert blob to ArrayBuffer
        const arrayBuffer = await blobData.arrayBuffer();

        // Convert PCM16 (Int16Array, signed 16-bit little-endian) to Float32Array
        // This is the same approach as Gemini Live
        const pcm16 = new Int16Array( arrayBuffer );
        const float32 = new Float32Array( pcm16.length );
        for ( let i = 0; i < pcm16.length; i++ ) {
            // Convert from signed 16-bit [-32768, 32767] to float [-1.0, 1.0]
            float32[ i ] = pcm16[ i ] / 32768.0;
        }

        // Create audio buffer at 24kHz (mono)
        const buffer = this.pcmAudioContext.createBuffer( 1, float32.length, 24000 );
        buffer.copyToChannel( float32, 0, 0 );

        // Create buffer source
        const source = this.pcmAudioContext.createBufferSource();
        source.buffer = buffer;
        source.connect( this.pcmAudioContext.destination );

        // Schedule playback with PRECISE timing
        // This is the key difference from HTML5 Audio onended chain
        const currentTime = this.pcmAudioContext.currentTime;
        const startTime = Math.max( this.pcmNextStartTime, currentTime );
        source.start( startTime );

        // Track this source for end-of-playback detection and manual stop
        this.lastPCMSource = source;
        this.audioSources = this.audioSources || [];
        this.audioSources.push( source );
        const notificationId = this.currentNotificationId;  // Capture for closure

        // Attach onended handler to detect when audio playback actually finishes
        source.onended = () => {
            // Only signal completion if:
            // 1. Stream download is complete (all chunks received)
            // 2. This is the last scheduled source (no new chunks came after)
            if ( this.pcmStreamComplete && source === this.lastPCMSource ) {
                if ( this.debug ) this.log( "PCM playback complete - notifying TTS queue" );
                this.pcmStreamComplete = false;
                this.lastPCMSource = null;
                // Notify TTS queue that playback is complete
                this.onTTSPlaybackComplete();
            }
        };

        // Update next start time for seamless sequential playback
        this.pcmNextStartTime = startTime + buffer.duration;

        // Track first chunk for TTFA metrics (using captured state from before awaits)
        if ( isFirstChunk ) {
            const ttfa = Date.now() - ttfaStartTime;
            this.log( `⚡ Time to first audio (PCM): ${ttfa}ms` );
            this.metricsFirstAudioTime = Date.now();
            this.updateMetricsTTFA();
            this.updateMetricsRTT();
        }

        if ( this.debug ) {
            this.log( `PCM chunk: ${blobData.size} bytes, scheduled at ${startTime.toFixed( 3 )}s, duration ${buffer.duration.toFixed( 3 )}s` );
        }
    }

    // ========================================
    // SEQUENTIAL PLAYBACK FOR INSTANT MODE (OLD - COMMENTED OUT)
    // HTML Audio with onended chain - causes choppy audio
    // Replaced by PCM 24000 Web Audio API playback above
    // ========================================

    /* COMMENTED OUT - OLD CHOPPY IMPLEMENTATION
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
    END COMMENTED OUT - OLD CHOPPY IMPLEMENTATION */

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
            // Notify TTS queue that playback is complete
            this.onTTSPlaybackComplete();
        }, { once: true } );
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
                    }
                    URL.revokeObjectURL( audioUrl );
                    // Notify TTS queue that playback is complete
                    this.onTTSPlaybackComplete();
                    resolve();
                };

                audio.onerror = ( error ) => {
                    this.error( "Audio playback error:", error );
                    this.isPlaying = false;
                    this.currentAudio = null;
                    // Reset UI to stopped state on error
                    if ( this.currentNotificationId ) {
                        this.updateAudioControlStates( this.currentNotificationId, 'stopped' );
                    }
                    URL.revokeObjectURL( audioUrl );
                    // Notify TTS queue even on error (to advance queue)
                    this.onTTSPlaybackComplete();
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

        // Stop pulsing indicator on notification card
        this.stopTTSPlayingIndicator( this.currentNotificationId );

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
        
        // Reset sequential playback (legacy - commented out code)
        this.sequentialQueue = [];
        this.isSequentialPlaying = false;
        this.sequentialChunksPlayed = 0;

        // Reset PCM playback state
        if ( this.pcmAudioContext ) {
            this.pcmNextStartTime = this.pcmAudioContext.currentTime;
        }
        this.firstChunkPlayed = false;
        this.pcmStreamComplete = false;
        this.lastPCMSource = null;
        
        // Reset first chunk timing
        this.firstChunkStartTime = null;
        this.firstChunkPlayed = false;
        
        this.log( "Audio playback stopped" );
    }

    // ========================================
    // TTS PLAYBACK VISUAL INDICATOR
    // ========================================

    /**
     * Add pulsing gold border to notification card during TTS playback.
     * Called when TTS request starts (before fetch to TTS server).
     */
    startTTSPlayingIndicator( notificationId ) {
        if ( !notificationId ) return;

        // Auto-expand accordions so user can see the pulsing border
        this.expandAccordionsForNotification( notificationId );

        // Find the notification list item by ID
        const notificationElement = document.getElementById( notificationId );
        if ( notificationElement ) {
            notificationElement.classList.add( 'tts-playing' );
            if ( this.debug ) this.log( `Started TTS indicator for: ${notificationId}` );
        }
    }

    /**
     * Remove pulsing gold border when TTS playback completes.
     * Called when all audio chunks have been received.
     *
     * Note: Uses animation-play-state toggle instead of class removal to prevent
     * compositor layer demotion which causes layout collapse. See:
     * src/rnd/2026.01.09-debugging-css-layout-collapse.md
     */
    stopTTSPlayingIndicator( notificationId ) {
        if ( !notificationId ) return;

        const notificationElement = document.getElementById( notificationId );
        if ( notificationElement ) {
            notificationElement.classList.remove( 'tts-playing' );
            if ( this.debug ) this.log( `Stopped TTS indicator for: ${notificationId}` );
        }
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
            // Route to Action Required section (queue system handles activation and TTS)
            this.addActionRequiredNotification( notification );
            // Still play sound
            await this.playNotificationSoundByPriority( notification.priority );

            // NOTE: TTS is now handled by activateNextNotification() when the notification
            // becomes active. This prevents simultaneous TTS playback when multiple
            // notifications arrive at once.

            return;  // Don't add to regular notifications list
        }

        // Regular fire-and-forget notification handling
        // 1. ALWAYS play notification sound first based on priority
        await this.playNotificationSoundByPriority( notification.priority );

        // 2. High/urgent priority: Queue for TTS, add to project card when playback starts
        //    Low/medium priority: Add to project card immediately (no TTS)
        if ( notification.priority === "high" || notification.priority === "urgent" ) {
            const ttsMessage = this.formatNotificationTTSMessage( notification );
            const notificationId = notification.id || notification.id_hash;

            this.log( `Queuing high priority notification for TTS (will add to project card on playback): "${ttsMessage}"` );

            // Add slight delay to let notification sound finish
            setTimeout( () => {
                this.addToTTSQueue( {
                    id           : notificationId,
                    type         : 'fire-and-forget',
                    notification : notification,
                    ttsText      : ttsMessage,
                    addedAt      : Date.now()
                } );
            }, 300 );
            // NOTE: addNotificationToSenderGroup() is called from activateNextTTS() when playback starts
        } else {
            // Low/medium priority: Add to project card immediately (no TTS)
            const senderId = this.resolveSenderId( notification );
            this.log( `Routing ${notification.priority} priority notification to sender: ${senderId}` );
            this.addNotificationToSenderGroup( notification, false );
            this.updateTotalNotificationsCount();
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
            // Also update the new progressive disclosure count badges
            if ( queueName === "todo" ) {
                // Update count badge for progressive disclosure UI
                const countBadge = document.getElementById( "todo-count-badge" );
                if ( countBadge ) countBadge.textContent = data.todo_jobs.length;
                // Also refresh job cards if category is expanded
                this.updateQueueCategoryIfExpanded( "todo", data.todo_jobs.length );
            } else if ( queueName === "run" ) {
                const countBadge = document.getElementById( "run-count-badge" );
                if ( countBadge ) countBadge.textContent = data.run_jobs.length;
                this.updateQueueCategoryIfExpanded( "run", data.run_jobs.length );
            } else if ( queueName === "done" ) {
                // Enhanced done queue handling with structured job metadata for replay functionality
                await this.handleDoneQueueUpdate( data );
                const countBadge = document.getElementById( "done-count-badge" );
                if ( countBadge ) countBadge.textContent = data.done_jobs.length;
                // Store metadata for progressive disclosure job cards
                this.queueCategoryState.done.jobs = data.done_jobs_metadata || [];
                this.updateQueueCategoryIfExpanded( "done", data.done_jobs.length );
            } else if ( queueName === "dead" ) {
                const countBadge = document.getElementById( "dead-count-badge" );
                if ( countBadge ) countBadge.textContent = data.dead_jobs.length;
                this.updateQueueCategoryIfExpanded( "dead", data.dead_jobs.length );
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

    // ========================================
    // PROGRESSIVE DISCLOSURE QUEUE UI METHODS
    // ========================================

    toggleQueueCategory( queueName ) {
        /**
         * Toggle expand/collapse for a queue category.
         *
         * Requires:
         *     - queueName is 'todo', 'run', 'done', or 'dead'
         *
         * Ensures:
         *     - Category container visibility toggles
         *     - First expansion triggers lazy load of job cards
         *     - Expand button icon updates (▶ / ▼)
         */
        const state = this.queueCategoryState[ queueName ];
        const container = document.getElementById( `${queueName}-jobs-container` );
        const expandBtn = document.getElementById( `${queueName}-expand` );

        if ( !container || !expandBtn ) {
            this.error( `Queue category elements not found for: ${queueName}` );
            return;
        }

        state.expanded = !state.expanded;

        if ( state.expanded ) {
            container.classList.remove( 'collapsed' );
            expandBtn.textContent = '▼';

            // Lazy load job cards on first expansion
            if ( !state.loaded ) {
                this.loadQueueJobCards( queueName );
            }
        } else {
            container.classList.add( 'collapsed' );
            expandBtn.textContent = '▶';
        }

        this.log( `Queue category ${queueName} ${state.expanded ? 'expanded' : 'collapsed'}` );
    }

    updateQueueCategoryIfExpanded( queueName, count ) {
        /**
         * Refresh job cards if queue category is currently expanded.
         *
         * Called from updateQueueLists() when WebSocket update arrives.
         */
        const state = this.queueCategoryState[ queueName ];

        // Update count in state
        // If expanded, reload job cards to reflect changes
        if ( state.expanded ) {
            state.loaded = false;  // Force reload
            this.loadQueueJobCards( queueName );
        }
    }

    async loadQueueJobCards( queueName ) {
        /**
         * Fetch and render job cards for a queue category.
         *
         * Requires:
         *     - queueName is valid queue identifier
         *     - Authentication is established
         *
         * Ensures:
         *     - Fetches queue data with metadata
         *     - Renders job cards with progressive disclosure
         *     - Updates count badge
         */
        this.log( `Loading job cards for: ${queueName}` );
        const container = document.getElementById( `${queueName}-jobs-container` );
        const countBadge = document.getElementById( `${queueName}-count-badge` );

        if ( !container ) {
            this.error( `Jobs container not found for: ${queueName}` );
            return;
        }

        try {
            let url = `/api/get-queue/${queueName}`;
            if ( this.isAdmin && this.queueFilterMode === 'all' ) {
                url += '?user_filter=*';
            }

            const response = await fetch( url, {
                headers: { 'Authorization': this.getAuthHeader() }
            } );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            const data = await response.json();

            // Get jobs array based on queue name
            const jobsKey = `${queueName}_jobs`;
            const metadataKey = `${queueName}_jobs_metadata`;
            const jobsHtml = data[ jobsKey ] || [];
            const jobsMetadata = data[ metadataKey ] || [];

            // Store in state
            this.queueCategoryState[ queueName ].jobs = jobsMetadata.length > 0 ? jobsMetadata : jobsHtml;
            this.queueCategoryState[ queueName ].loaded = true;

            // Update count badge
            if ( countBadge ) countBadge.textContent = jobsHtml.length;

            // Render job cards
            if ( jobsHtml.length === 0 ) {
                container.innerHTML = '<div class="queue-empty-message">No jobs in this queue</div>';
            } else {
                // Use metadata if available (done queue), otherwise create minimal metadata from HTML
                const jobsToRender = jobsMetadata.length > 0 ? jobsMetadata : jobsHtml.map( ( html, idx ) => ( {
                    job_id          : `job-${queueName}-${idx}`,
                    question_text   : this.extractQuestionFromHtml( html ),
                    timestamp       : '',
                    agent_type      : '',
                    has_interactions: false
                } ) );

                container.innerHTML = jobsToRender.map( job => this.renderJobCard( job, queueName ) ).join( '' );
            }

        } catch ( error ) {
            this.error( `Error loading ${queueName} job cards:`, error );
            container.innerHTML = '<div class="queue-error-message">Error loading jobs</div>';
        }
    }

    extractQuestionFromHtml( html ) {
        /**
         * Extract question text from job HTML string.
         * HTML format: "<li id='hash'>...Q: question text...</li>"
         */
        const match = html.match( /Q:\s*([^<]+)/ );
        return match ? match[ 1 ].trim() : 'Unknown question';
    }

    renderJobCard( job, queueName ) {
        /**
         * Generate HTML for a single job card.
         *
         * Requires:
         *     - job object with job_id, question_text, timestamp, agent_type
         *     - queueName for styling context
         *
         * Ensures:
         *     - Returns HTML string for collapsible job card
         *     - Includes agent badge, truncated question, timestamp
         *     - Done queue cards include interaction toggle
         */
        const statusClass = `status-${queueName}`;
        const truncatedQuestion = this.truncateText( job.question_text || 'No question', 60 );
        const agentBadge = job.agent_type ? `<span class="agent-badge">${( job.agent_type || '' ).replace( 'Agent', '' )}</span>` : '';
        const timestamp = this.formatJobTimestamp( job.timestamp );

        // Interaction indicator for done queue
        let interactionIndicator = '';
        if ( queueName === 'done' && job.has_interactions ) {
            interactionIndicator = '<span class="interaction-indicator" title="Has interaction history">💬</span>';
        }

        const jobId = job.job_id || `job-${Date.now()}`;

        return `
            <div class="job-card ${statusClass}" id="job-card-${jobId}" data-job-id="${jobId}">
                <div class="job-card-header" onclick="window.notificationsUI.toggleJobCard('${jobId}', '${queueName}')">
                    ${agentBadge}
                    <span class="job-question">${this.escapeHtml( truncatedQuestion )}</span>
                    ${interactionIndicator}
                    <span class="job-timestamp">${timestamp}</span>
                    <button class="job-expand-btn">▶</button>
                </div>
                <div class="job-card-details collapsed" id="job-details-${jobId}">
                    <div class="job-full-question">
                        <strong>Question:</strong> ${this.escapeHtml( job.question_text || '' )}
                    </div>
                    <div class="job-response">
                        <strong>Response:</strong> ${this.escapeHtml( job.response_text || 'Processing...' )}
                    </div>
                    <div class="job-metadata">
                        <span>Agent: ${job.agent_type || 'Unknown'}</span>
                        <span>Time: ${timestamp}</span>
                    </div>
                    ${queueName === 'done' ? `
                    <div class="job-interactions-section" id="job-interactions-${jobId}">
                        <div class="interactions-header" onclick="window.notificationsUI.toggleJobInteractions('${jobId}', event)">
                            <span>📋 Notification Conversation</span>
                            <button class="interactions-expand-btn">▶</button>
                        </div>
                        <div class="interactions-content collapsed" id="interactions-content-${jobId}">
                            <div class="interactions-loading">Loading...</div>
                        </div>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    toggleJobCard( jobId, queueName ) {
        /**
         * Toggle expand/collapse for individual job card.
         */
        const details = document.getElementById( `job-details-${jobId}` );
        const card = document.getElementById( `job-card-${jobId}` );

        if ( !details || !card ) {
            this.error( `Job card elements not found: ${jobId}` );
            return;
        }

        const expandBtn = card.querySelector( '.job-expand-btn' );

        if ( this.expandedJobCards.has( jobId ) ) {
            details.classList.add( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▶';
            this.expandedJobCards.delete( jobId );
        } else {
            details.classList.remove( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▼';
            this.expandedJobCards.add( jobId );
        }
    }

    async toggleJobInteractions( jobId, event ) {
        /**
         * Toggle and lazy-load interaction history for a job.
         *
         * THE KEY FEATURE: Shows notification conversation history
         * associated with a completed job.
         */
        event.stopPropagation();  // Don't toggle parent card

        const contentEl = document.getElementById( `interactions-content-${jobId}` );
        if ( !contentEl ) {
            this.error( `Interactions content not found: ${jobId}` );
            return;
        }

        const headerEl = contentEl.previousElementSibling;
        const expandBtn = headerEl ? headerEl.querySelector( '.interactions-expand-btn' ) : null;

        const isExpanded = !contentEl.classList.contains( 'collapsed' );

        if ( isExpanded ) {
            contentEl.classList.add( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▶';
        } else {
            contentEl.classList.remove( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▼';

            // Lazy load interactions if not cached
            if ( !this.jobInteractionsCache.has( jobId ) ) {
                await this.loadJobInteractions( jobId );
            }
        }
    }

    async loadJobInteractions( jobId ) {
        /**
         * Fetch notification interactions for a job from API.
         */
        const contentEl = document.getElementById( `interactions-content-${jobId}` );
        if ( !contentEl ) return;

        try {
            const response = await fetch( `/api/get-job-interactions/${jobId}`, {
                headers: { 'Authorization': this.getAuthHeader() }
            } );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            const data = await response.json();
            this.jobInteractionsCache.set( jobId, data.interactions );

            if ( data.interactions.length === 0 ) {
                contentEl.innerHTML = '<div class="no-interactions">No interactions recorded for this job</div>';
            } else {
                contentEl.innerHTML = data.interactions.map( i => this.renderInteractionItem( i ) ).join( '' );
            }

        } catch ( error ) {
            this.error( `Error loading interactions for job ${jobId}:`, error );
            contentEl.innerHTML = '<div class="interactions-error">Error loading interactions</div>';
        }
    }

    renderInteractionItem( interaction ) {
        /**
         * Render a single notification interaction.
         */
        const typeIcons = {
            'task'    : '📋',
            'progress': '⏳',
            'alert'   : '⚠️',
            'custom'  : '💬'
        };
        const typeIcon = typeIcons[ interaction.type ] || '📋';

        let timestamp = '';
        try {
            timestamp = new Date( interaction.timestamp ).toLocaleTimeString();
        } catch ( e ) {
            timestamp = interaction.timestamp || '';
        }

        let responseHtml = '';
        if ( interaction.response_requested && interaction.response_value ) {
            const responseStr = typeof interaction.response_value === 'object'
                ? JSON.stringify( interaction.response_value )
                : String( interaction.response_value );
            responseHtml = `
                <div class="interaction-response">
                    <span class="response-label">Your response:</span>
                    <span class="response-value">${this.escapeHtml( responseStr )}</span>
                </div>
            `;
        }

        return `
            <div class="interaction-item priority-${interaction.priority || 'medium'}">
                <div class="interaction-header">
                    <span class="interaction-type">${typeIcon} ${interaction.type}</span>
                    <span class="interaction-time">${timestamp}</span>
                </div>
                <div class="interaction-message">${this.escapeHtml( interaction.message || '' )}</div>
                ${responseHtml}
            </div>
        `;
    }

    truncateText( text, maxLength ) {
        /**
         * Truncate text with ellipsis if it exceeds maxLength.
         */
        if ( !text ) return '';
        if ( text.length <= maxLength ) return text;
        return text.substring( 0, maxLength - 3 ) + '...';
    }

    formatJobTimestamp( timestamp ) {
        /**
         * Format job timestamp for display.
         */
        if ( !timestamp ) return '';
        try {
            // Handle "2026-01-14 @ 10:30:45 EST" format
            const cleaned = timestamp.replace( ' @ ', 'T' ).replace( ' EST', '' ).replace( ' EDT', '' );
            const date = new Date( cleaned );
            return date.toLocaleString( 'en-US', {
                month  : 'short',
                day    : 'numeric',
                hour   : 'numeric',
                minute : '2-digit'
            } );
        } catch ( e ) {
            return timestamp;
        }
    }

    escapeHtml( text ) {
        /**
         * Escape HTML special characters to prevent XSS.
         */
        if ( !text ) return '';
        const div = document.createElement( 'div' );
        div.textContent = text;
        return div.innerHTML;
    }

    // ========================================
    // SECTION VISIBILITY TOOLBAR METHODS
    // ========================================

    initToolbar() {
        /**
         * Initialize section visibility toolbar click handlers.
         *
         * Requires:
         *     - Toolbar HTML exists in DOM
         *
         * Ensures:
         *     - Click handlers attached to all toolbar buttons
         *     - Saved visibility state applied from localStorage
         */
        const toolbar = document.getElementById( 'section-toolbar' );
        if ( !toolbar ) {
            this.log( 'Section toolbar not found - skipping initialization' );
            return;
        }

        toolbar.querySelectorAll( '.toolbar-btn' ).forEach( btn => {
            btn.addEventListener( 'click', () => this.toggleSectionVisibility( btn.dataset.section ) );
        } );

        // Apply saved visibility state
        this.applySectionVisibility();
        this.log( 'Section visibility toolbar initialized' );
    }

    toggleSectionVisibility( sectionId ) {
        /**
         * Toggle a section's visibility.
         *
         * Requires:
         *     - sectionId matches a valid section wrapper ID
         *
         * Ensures:
         *     - Section visibility toggled (show/hide entire section including header)
         *     - Toolbar button state updated (active/dimmed)
         *     - State saved to localStorage for persistence
         */
        const section = document.getElementById( sectionId );
        const btn = document.querySelector( `.toolbar-btn[data-section="${sectionId}"]` );

        if ( !section ) {
            this.error( `Section not found: ${sectionId}` );
            return;
        }

        const isVisible = !section.classList.contains( 'section-hidden' );

        if ( isVisible ) {
            section.classList.add( 'section-hidden' );
            btn?.classList.remove( 'active' );
            this.log( `Section hidden: ${sectionId}` );
        } else {
            section.classList.remove( 'section-hidden' );
            btn?.classList.add( 'active' );
            this.log( `Section shown: ${sectionId}` );
        }

        this.saveSectionVisibility();
    }

    saveSectionVisibility() {
        /**
         * Save visibility state to localStorage.
         *
         * Ensures:
         *     - All section visibility states saved as JSON
         *     - Persists across page refreshes and browser restarts
         */
        const visibility = {};
        document.querySelectorAll( '.toolbar-btn' ).forEach( btn => {
            visibility[ btn.dataset.section ] = btn.classList.contains( 'active' );
        } );
        localStorage.setItem( this.SECTION_VISIBILITY_KEY, JSON.stringify( visibility ) );
        this.log( 'Section visibility state saved to localStorage' );
    }

    loadSectionVisibility() {
        /**
         * Load visibility state from localStorage.
         *
         * Ensures:
         *     - Returns saved state object or null if not found
         *     - Handles JSON parse errors gracefully
         */
        try {
            const saved = localStorage.getItem( this.SECTION_VISIBILITY_KEY );
            return saved ? JSON.parse( saved ) : null;
        } catch ( e ) {
            this.error( 'Error loading section visibility state:', e );
            return null;
        }
    }

    applySectionVisibility() {
        /**
         * Apply saved visibility state on page load.
         *
         * Requires:
         *     - this.sectionVisibility loaded from localStorage
         *
         * Ensures:
         *     - All sections restored to their saved visibility state
         *     - Toolbar buttons updated to match section visibility
         */
        if ( !this.sectionVisibility ) {
            this.log( 'No saved section visibility state - showing all sections' );
            return;
        }

        Object.entries( this.sectionVisibility ).forEach( ( [ sectionId, isVisible ] ) => {
            const section = document.getElementById( sectionId );
            const btn = document.querySelector( `.toolbar-btn[data-section="${sectionId}"]` );

            if ( section && !isVisible ) {
                section.classList.add( 'section-hidden' );
                btn?.classList.remove( 'active' );
            }
        } );

        this.log( 'Section visibility state restored from localStorage' );
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
        const match = senderId.match( /^claude\.code@([a-z]+)\.deepily\.ai/ );
        if ( match ) {
            return match[1].toUpperCase();
        }
        return 'UNKNOWN';
    }

    /**
     * Parse sender_id into components (backward compatible).
     * Supports new session-aware format: claude.code@project.deepily.ai#session_id
     *
     * @param {string} senderId - Full sender_id string
     * @returns {Object} - { agentType, project, sessionId, fullSenderId, baseSenderId }
     */
    parseSenderId( senderId ) {
        let base, sessionId;

        // Handle new format with session_id
        if ( senderId.includes( '#' ) ) {
            const parts = senderId.split( '#' );
            base = parts[ 0 ];
            sessionId = parts[ 1 ];
        } else {
            base = senderId;
            sessionId = null;
        }

        // Parse agent type and project
        const match = base.match( /^([^@]+)@([a-z]+)\.deepily\.ai$/ );
        const agentType = match ? match[ 1 ] : 'unknown';
        const project = match ? match[ 2 ] : 'unknown';

        return {
            agentType     : agentType,
            project       : project,
            sessionId     : sessionId,
            fullSenderId  : senderId,
            baseSenderId  : base
        };
    }

    /**
     * Save a session name to localStorage.
     * @param {string} sessionId - Session ID (hex string)
     * @param {string} name - Session name to save
     */
    saveSessionName( sessionId, name ) {
        this.sessionNames[ sessionId ] = name;
        localStorage.setItem( this.SESSION_NAMES_KEY, JSON.stringify( this.sessionNames ) );
        this.log( `Saved session name for ${sessionId}: ${name}` );
    }

    /**
     * Get session name, checking localStorage first then falling back to auto-generation.
     * @param {string} sessionId - Session ID (hex string)
     * @param {string} firstMessage - First notification message (for auto-generation)
     * @returns {string} - Session name
     */
    getSessionName( sessionId, firstMessage ) {
        // Check for user-provided/generated name first
        if ( this.sessionNames[ sessionId ] ) {
            return this.sessionNames[ sessionId ];
        }
        // Fall back to auto-generation from first message
        return this.generateSessionName( firstMessage );
    }

    /**
     * Generate a human-readable session name from first message content.
     * Uses smarter algorithm to extract action verbs + key nouns instead of first 4 words.
     *
     * @param {string} firstMessage - First notification message from session
     * @returns {string} - Short session name (max 30 chars)
     */
    generateSessionName( firstMessage ) {
        if ( !firstMessage ) return 'Session';

        // Remove common prefixes like "[LUPIN] "
        const cleaned = firstMessage.replace( /^\[[A-Z]+\]\s*/, '' );

        // Skip words: pronouns, articles, common verbs, filler words
        const skipWords = new Set( [
            // Pronouns
            'i', 'you', 'we', 'they', 'it', 'me', 'my', 'your', 'our',
            // Articles
            'a', 'an', 'the',
            // Common verbs (non-action)
            'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'can', 'could',
            'would', 'should', 'will', 'shall', 'may', 'might', 'must',
            // Filler words
            'please', 'just', 'really', 'very', 'actually', 'basically',
            'need', 'want', 'like', 'know', 'think', 'help', 'trying',
            'hello', 'hi', 'hey', 'sure', 'okay', 'ok', 'yes', 'no',
            'going', 'gonna', 'wanna', 'let', 'lets', 'get', 'got',
            'make', 'made', 'take', 'took', 'see', 'saw', 'look', 'looked',
            'some', 'any', 'this', 'that', 'these', 'those', 'with', 'for',
            'about', 'into', 'from', 'up', 'down', 'out', 'in', 'on', 'off',
            'over', 'under', 'again', 'then', 'once', 'here', 'there', 'when',
            'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
            'more', 'most', 'other', 'such', 'only', 'own', 'same', 'so',
            'than', 'too', 'also', 'now', 'well', 'way', 'even', 'new',
            'first', 'last', 'long', 'little', 'great', 'good', 'right',
            'still', 'after', 'before', 'being', 'while', 'through', 'during'
        ] );

        // Action verbs to prioritize (keep these!)
        const actionVerbs = new Set( [
            'add', 'fix', 'update', 'create', 'delete', 'remove', 'change',
            'implement', 'refactor', 'debug', 'test', 'deploy', 'configure',
            'migrate', 'upgrade', 'install', 'build', 'run', 'check', 'verify',
            'enable', 'disable', 'optimize', 'improve', 'review', 'merge',
            'search', 'find', 'replace', 'rename', 'move', 'copy', 'edit',
            'write', 'read', 'load', 'save', 'export', 'import', 'convert',
            'parse', 'format', 'validate', 'authenticate', 'authorize',
            'connect', 'disconnect', 'start', 'stop', 'restart', 'reset',
            'send', 'receive', 'fetch', 'push', 'pull', 'sync', 'upload',
            'download', 'backup', 'restore', 'clean', 'clear', 'flush'
        ] );

        const words = cleaned.toLowerCase().split( /\s+/ );
        const meaningful = [];

        for ( const word of words ) {
            // Clean punctuation
            const clean = word.replace( /[^a-z0-9]/g, '' );
            if ( !clean ) continue;

            // Always include action verbs
            if ( actionVerbs.has( clean ) ) {
                meaningful.push( clean );
                continue;
            }

            // Skip filler words
            if ( skipWords.has( clean ) ) continue;

            // Include remaining words (likely nouns/subjects)
            meaningful.push( clean );

            // Stop at 4 meaningful words
            if ( meaningful.length >= 4 ) break;
        }

        // Capitalize first letter of each word
        const name = meaningful
            .map( w => w.charAt( 0 ).toUpperCase() + w.slice( 1 ) )
            .join( ' ' );

        // Truncate to 30 chars if needed
        const result = name || 'Session';
        return result.length > 30 ? result.substring( 0, 27 ) + '...' : result;
    }

    /**
     * Allow user to edit a session name inline via prompt dialog.
     * @param {string} sessionId - Session ID (hex string)
     */
    editSessionName( sessionId ) {
        const currentName = this.sessionNames[ sessionId ] || '';
        // Create voice-first edit modal instead of browser prompt
        this.showSessionNameEditModal( sessionId, currentName );
    }

    /**
     * Show the voice-first session name edit modal.
     * Modal auto-starts recording for audio-first UX.
     * @param {string} sessionId - Session ID (hex string)
     * @param {string} currentName - Current session name
     */
    showSessionNameEditModal( sessionId, currentName ) {
        // Remove any existing modal
        const existingModal = document.getElementById( 'session-name-edit-modal' );
        if ( existingModal ) existingModal.remove();

        // Create modal overlay
        const modal = document.createElement( 'div' );
        modal.id = 'session-name-edit-modal';
        modal.className = 'session-name-edit-modal';
        modal.innerHTML = `
            <div class="session-name-edit-content">
                <div class="session-name-edit-header">
                    <span>Rename Session</span>
                    <button class="session-name-edit-close" onclick="window.notificationsUI.closeSessionNameEditModal()">&times;</button>
                </div>
                <div class="session-name-edit-body">
                    <div class="session-name-input-row">
                        <button id="session-name-mic-btn" class="stt-button" title="Voice input (click to record)">🎤</button>
                        <input type="text" id="session-name-input" class="session-name-input"
                               value="${this.escapeHtml( currentName )}"
                               placeholder="Enter session name..."
                               autocomplete="off" />
                    </div>
                    <div class="session-name-edit-hint">Click mic to speak, or type directly</div>
                </div>
                <div class="session-name-edit-footer">
                    <button class="session-name-cancel-btn" onclick="window.notificationsUI.closeSessionNameEditModal()">Cancel</button>
                    <button class="session-name-save-btn" onclick="window.notificationsUI.saveSessionNameFromModal('${sessionId}')">Save</button>
                </div>
            </div>
        `;

        document.body.appendChild( modal );

        // Auto-focus input
        const input = document.getElementById( 'session-name-input' );
        input.focus();
        input.select();

        // Wire up mic button using existing recordingManager with toggle logic
        const micBtn = document.getElementById( 'session-name-mic-btn' );
        const self = this;
        micBtn.addEventListener( 'click', async () => {
            // If already recording, stop it (toggle behavior)
            if ( self.recordingManager.isRecording() ) {
                await self.recordingManager.stopRecording();
                return;
            }

            // If processing, ignore click
            if ( self.recordingManager.isProcessing() ) {
                return;
            }

            // Start new recording
            await self.recordingManager.startRecording(
                `session-name-${sessionId}`,
                micBtn,
                input,
                {
                    onTranscriptionComplete: ( text ) => {
                        self.log( `Session name voice input: "${text}"` );
                    }
                }
            );
        } );

        // Handle spacebar on mic button to stop recording (voice-first UX)
        micBtn.addEventListener( 'keydown', async ( e ) => {
            if ( e.key === ' ' || e.key === 'Enter' ) {
                e.preventDefault();
                micBtn.click();
            }
        } );

        // Handle Enter key to save, Escape to cancel (on input field)
        input.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' ) {
                self.saveSessionNameFromModal( sessionId );
            } else if ( e.key === 'Escape' ) {
                self.closeSessionNameEditModal();
            }
        } );

        // Auto-start recording for voice-first UX, then focus mic button for spacebar
        setTimeout( async () => {
            micBtn.click();
            // Focus mic button after recording starts so spacebar can stop it
            setTimeout( () => {
                micBtn.focus( { preventScroll: true } );
            }, 100 );
        }, 100 );
    }

    /**
     * Close the session name edit modal.
     */
    closeSessionNameEditModal() {
        const modal = document.getElementById( 'session-name-edit-modal' );
        if ( modal ) modal.remove();
    }

    /**
     * Save session name from the edit modal.
     * @param {string} sessionId - Session ID (hex string)
     */
    saveSessionNameFromModal( sessionId ) {
        const input = document.getElementById( 'session-name-input' );
        const newName = input?.value?.trim() || '';

        if ( newName ) {
            this.saveSessionName( sessionId, newName );
            this.refreshSessionNameDisplay( sessionId, newName );
            this.log( `Session ${sessionId} renamed to: ${newName}` );
        }

        this.closeSessionNameEditModal();
    }

    /**
     * Refresh the session name display across all sender cards with this session ID.
     * @param {string} sessionId - Session ID (hex string)
     * @param {string} newName - New session name to display
     */
    refreshSessionNameDisplay( sessionId, newName ) {
        // Find all sender cards with this session ID and update the name span
        const cards = document.querySelectorAll( `[data-session-id="${sessionId}"]` );
        cards.forEach( card => {
            const nameSpan = card.querySelector( '.sender-session-name' );
            if ( nameSpan ) nameSpan.textContent = newName;
        } );
    }

    /**
     * Generate a smart gist (3-4 word summary) for a session using backend LLM.
     * Collects messages from the session and calls the gist API endpoint.
     * @param {string} senderId - Full sender ID to generate gist for
     */
    async generateSessionGist( senderId ) {
        const parsed = this.parseSenderId( senderId );
        const sessionId = parsed.sessionId;
        if ( !sessionId ) {
            this.log( 'No session ID found for gist generation' );
            return;
        }

        const group = this.senderGroups.get( senderId );
        if ( !group?.dateGroups?.size ) {
            this.log( 'No notifications to generate gist from' );
            return;
        }

        // Flatten all notifications from all date groups
        const allNotifications = Array.from( group.dateGroups.values() ).flat();
        if ( !allNotifications.length ) {
            this.log( 'No notifications to generate gist from' );
            return;
        }

        // Collect all messages for this session
        const messages = allNotifications.map( n => n.message ).filter( Boolean );
        if ( messages.length === 0 ) {
            this.log( 'No messages with content for gist generation' );
            return;
        }

        // Find and disable the gist button to prevent duplicate clicks
        const gistBtn = document.querySelector( `[data-session-id="${sessionId}"] .sender-gist-btn` );
        if ( gistBtn ) {
            gistBtn.disabled = true;
            gistBtn.classList.add( 'working' );
            gistBtn.innerHTML = '⏳';
        }

        this.log( `Generating gist for session ${sessionId} from ${messages.length} messages...` );

        try {
            // Call backend API to generate gist
            const response = await fetch( '/api/notifications/generate-gist', {
                method  : 'POST',
                headers : { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body    : JSON.stringify( { messages } )
            } );

            if ( !response.ok ) {
                throw new Error( `API error: ${response.status}` );
            }

            const data = await response.json();
            const gist = data.gist;

            // Save and display the generated gist
            this.saveSessionName( sessionId, gist );
            this.refreshSessionNameDisplay( sessionId, gist );
            this.log( `Generated gist for ${sessionId}: ${gist}` );

        } catch ( error ) {
            this.error( 'Failed to generate gist:', error );
        } finally {
            // Restore button state (always runs, even on error)
            if ( gistBtn ) {
                gistBtn.disabled = false;
                gistBtn.classList.remove( 'working' );
                gistBtn.innerHTML = '✨';
            }
        }
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
     * Add notification to appropriate sender group with date-based sub-grouping.
     * Creates sender card and date accordion if they don't exist.
     * @param {object} notification - Notification data
     * @param {boolean} isResponse - True if this is a user response (right-aligned)
     */
    addNotificationToSenderGroup( notification, isResponse = false ) {
        const senderId = this.resolveSenderId( notification );
        // Extract date directly from ISO timestamp to preserve server timezone
        // (avoids browser timezone conversion issues)
        const dateString = this.extractDateFromTimestamp( notification.timestamp );
        const timestamp = new Date( notification.timestamp || Date.now() );

        // Get or create sender group
        let group = this.senderGroups.get( senderId );
        const isNewSender = !group;

        if ( !group ) {
            group = {
                dateGroups   : new Map(),
                collapsed    : false,
                lastActivity : timestamp,
                totalCount   : 0,
                newCount     : 0
            };
            this.senderGroups.set( senderId, group );
            // During initial load, append to preserve API order; at runtime, prepend to show new activity first
            this.createSenderCard( senderId, !this.isInitialLoad );
        }

        // Get or create date group within sender
        let dateGroup = group.dateGroups.get( dateString );
        const isNewDate = !dateGroup;

        if ( !dateGroup ) {
            dateGroup = [];
            group.dateGroups.set( dateString, dateGroup );
            this.createDateAccordion( senderId, dateString );
        }

        // Add notification to date group
        dateGroup.push( { ...notification, isResponse } );
        group.totalCount++;

        // Count as "new" if not delivered/responded
        if ( !notification.state || notification.state === 'created' || notification.state === 'queued' ) {
            group.newCount++;
        }

        // Update last activity and move card to top
        if ( timestamp > group.lastActivity ) {
            group.lastActivity = timestamp;
            // Only move card during runtime updates, not during initial page load
            // (initial load relies on API sort order preserved via appendChild)
            if ( !isNewSender && !this.isInitialLoad ) {
                this.moveSenderCardToTop( senderId );
            }
        }

        // Update UI
        this.addMessageToDateAccordion( senderId, dateString, notification, isResponse );
        this.updateSenderCardHeader( senderId );
    }

    /**
     * Get ISO date string (YYYY-MM-DD) from timestamp.
     * Uses configured timezone.
     * @param {Date} timestamp - Date to convert
     * @returns {string} ISO date string
     */
    getDateString( timestamp ) {
        // Use local timezone (which should match server's app_timezone)
        const year = timestamp.getFullYear();
        const month = String( timestamp.getMonth() + 1 ).padStart( 2, '0' );
        const day = String( timestamp.getDate() ).padStart( 2, '0' );
        return `${year}-${month}-${day}`;
    }

    /**
     * Extract date string from ISO timestamp, preserving server timezone.
     * Falls back to local date if timestamp is missing or invalid.
     * @param {string|null} isoTimestamp - ISO 8601 timestamp (e.g., "2026-01-06T02:30:00-05:00")
     * @returns {string} ISO date string (YYYY-MM-DD)
     */
    extractDateFromTimestamp( isoTimestamp ) {
        if ( isoTimestamp && typeof isoTimestamp === 'string' && isoTimestamp.includes( 'T' ) ) {
            return isoTimestamp.split( 'T' )[ 0 ];
        }
        // Fallback: use local date (existing behavior for edge cases)
        return this.getDateString( new Date() );
    }

    /**
     * Get formatted time display with timezone abbreviation.
     * Used when server-provided time_display is not available (e.g., timeout case).
     * Format matches server's get_formatted_time_display(): "HH:MM TZ" (e.g., "16:26 EST")
     * Uses timezone from server config (this.appTimezone), set via fetchClientConfig().
     * @returns {string} Formatted time string with timezone
     */
    getLocalTimeDisplay() {
        const now = new Date();
        const time = now.toLocaleTimeString( 'en-US', {
            hour     : '2-digit',
            minute   : '2-digit',
            hour12   : false,
            timeZone : this.appTimezone
        } );
        // Extract timezone abbreviation (e.g., "EST" or "EDT")
        const tzAbbrev = now.toLocaleTimeString( 'en-US', {
            timeZoneName : 'short',
            timeZone     : this.appTimezone
        } ).split( ' ' ).pop();
        return `${time} ${tzAbbrev}`;
    }

    /**
     * Get formatted date display in ISO format (YYYY-MM-DD).
     * Used when server-provided date_display is not available (e.g., timeout case).
     * Format matches server's get_formatted_date_display(): "YYYY-MM-DD"
     * Uses timezone from server config (this.appTimezone), set via fetchClientConfig().
     * @returns {string} Formatted date string
     */
    getLocalDateDisplay() {
        const now = new Date();
        // Use en-CA locale which returns ISO format (YYYY-MM-DD)
        return now.toLocaleDateString( 'en-CA', {
            timeZone : this.appTimezone,
            year     : 'numeric',
            month    : '2-digit',
            day      : '2-digit'
        } );
    }

    /**
     * Move sender card to top of notifications list.
     * Called when a sender receives new activity.
     * @param {string} senderId - Sender ID
     */
    moveSenderCardToTop( senderId ) {
        const container = document.getElementById( 'notifications-list' );
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );

        if ( container && card && container.firstChild !== card ) {
            container.insertBefore( card, container.firstChild );
            this.log( `Moved ${senderId} card to top` );
        }
    }

    /**
     * Create a new sender card in the UI with date accordion container.
     * @param {string} senderId - Sender ID
     * @param {boolean} insertAtTop - If true, prepend to top; if false, append (preserves API order during initial load)
     */
    createSenderCard( senderId, insertAtTop = true ) {
        const container = document.getElementById( 'notifications-list' );
        if ( !container ) {
            this.error( 'Notifications list container not found' );
            return;
        }

        // Parse sender_id for session info (Conversation Identity Phase 3)
        const parsed = this.parseSenderId( senderId );
        const projectName = parsed.project.toUpperCase();
        const sessionId = parsed.sessionId;

        const group = this.senderGroups.get( senderId );
        const statusIndicator = this.getSenderStatusIndicator( group?.lastActivity );
        const escapedSenderId = senderId.replace( /'/g, "\\'" );

        // Get session name: check localStorage first, then auto-generate from first message
        // Extract first message from nested dateGroups structure
        // dateGroups is a Map of { dateString → notificationArray }
        let firstMsg = '';
        if ( group?.dateGroups?.size > 0 ) {
            // Get all notifications from all date groups and flatten
            const allNotifications = Array.from( group.dateGroups.values() ).flat();
            // Sort by timestamp to get chronologically first
            allNotifications.sort( ( a, b ) => new Date( a.timestamp ) - new Date( b.timestamp ) );
            firstMsg = allNotifications[ 0 ]?.message || '';
        }
        const sessionName = sessionId ? this.getSessionName( sessionId, firstMsg ) : null;

        // Build session display string (only if session_id present)
        // Session name is clickable for inline editing, gist button triggers LLM summary
        const sessionDisplay = sessionId
            ? `<span class="sender-session-id">#${sessionId}</span>
               <span class="sender-session-name"
                     onclick="event.stopPropagation(); window.notificationsUI.editSessionName('${sessionId}')"
                     title="Click to rename">${sessionName || ''}</span>
               <button class="sender-gist-btn"
                       onclick="event.stopPropagation(); window.notificationsUI.generateSessionGist('${escapedSenderId}')"
                       title="Generate smart gist from conversation">✨</button>`
            : '';

        // Active indicator: filled circle for most recent sender, hollow for others
        const activeIndicator = group?.isActive ? '●' : '○';
        const activeClass = group?.isActive ? ' sender-card-active' : '';
        const activeTitle = group?.isActive ? 'Active session' : 'Inactive session';

        const card = document.createElement( 'div' );
        // Card ID must escape # character in addition to @ and .
        card.id = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        card.className = `sender-card${activeClass}`;
        card.setAttribute( 'data-project', parsed.project );
        card.setAttribute( 'data-session-id', sessionId || '' );
        card.innerHTML = `
            <div class="sender-card-header" onclick="window.notificationsUI.toggleSenderCard('${escapedSenderId}')">
                <span class="sender-active-indicator" title="${activeTitle}">${activeIndicator}</span>
                <span class="sender-status">${statusIndicator}</span>
                <span class="sender-project-name">${projectName}</span>
                ${sessionDisplay}
                <span class="sender-new-count"></span>
                <span class="sender-message-count">(0)</span>
                <span class="sender-last-activity">Last: --</span>
                <button class="sender-delete-btn" onclick="event.stopPropagation(); window.notificationsUI.deleteSenderConversation('${escapedSenderId}')" title="Delete all">×</button>
                <span class="sender-toggle">▼</span>
            </div>
            <div class="sender-card-dates" id="sender-dates-${senderId.replace( /[@.#]/g, '-' )}">
                <!-- Date accordions will be added here -->
            </div>
        `;

        // Insert at top for runtime updates, append for initial load (preserves API sort order)
        if ( insertAtTop ) {
            container.insertBefore( card, container.firstChild );
        } else {
            container.appendChild( card );
        }
        this.log( `Created sender card for ${projectName}${sessionId ? '#' + sessionId : ''} (${senderId})` );
    }

    /**
     * Create a date accordion within a sender card.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string (YYYY-MM-DD)
     */
    createDateAccordion( senderId, dateString ) {
        const containerId = `sender-dates-${senderId.replace( /[@.#]/g, '-' )}`;
        const container = document.getElementById( containerId );
        if ( !container ) {
            this.error( `Date container not found: ${containerId}` );
            return;
        }

        const accordionId = `date-accordion-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        const escapedSenderId = senderId.replace( /'/g, "\\'" );

        const accordion = document.createElement( 'div' );
        accordion.id = accordionId;
        accordion.className = 'date-accordion';
        accordion.innerHTML = `
            <div class="date-accordion-header" onclick="window.notificationsUI.toggleDateAccordion('${escapedSenderId}', '${dateString}')">
                <span class="date-text">${dateString}</span>
                <span class="date-count">(0)</span>
                <button class="date-delete-btn" onclick="event.stopPropagation(); window.notificationsUI.softDeleteByDate('${escapedSenderId}', '${dateString}')" title="Hide this day">🗑️</button>
                <span class="date-toggle">▼</span>
            </div>
            <div class="date-accordion-messages" id="date-messages-${senderId.replace( /[@.#]/g, '-' )}-${dateString}">
                <!-- Messages for this date will be added here -->
            </div>
        `;

        // Insert in descending chronological order (newest dates at top)
        // Date strings are ISO format (YYYY-MM-DD), lexicographically comparable
        const existingAccordions = container.querySelectorAll( '.date-accordion' );
        let insertBefore = null;

        for ( const existing of existingAccordions ) {
            // Extract date from accordion id: "date-accordion-{senderId}-{dateString}"
            const existingDate = existing.id.split( '-' ).slice( -3 ).join( '-' );
            if ( dateString > existingDate ) {
                // New date is newer, insert before this one
                insertBefore = existing;
                break;
            }
        }

        if ( insertBefore ) {
            container.insertBefore( accordion, insertBefore );
        } else {
            // New date is oldest, append to end
            container.appendChild( accordion );
        }

        this.log( `Created date accordion for ${senderId} on ${dateString}` );
    }

    /**
     * Toggle date accordion collapse state.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string
     */
    toggleDateAccordion( senderId, dateString ) {
        const accordionId = `date-accordion-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        const accordion = document.getElementById( accordionId );
        if ( !accordion ) return;

        const messages = accordion.querySelector( '.date-accordion-messages' );
        const toggle = accordion.querySelector( '.date-toggle' );

        if ( messages.classList.contains( 'collapsed' ) ) {
            messages.classList.remove( 'collapsed' );
            toggle.textContent = '▼';
        } else {
            messages.classList.add( 'collapsed' );
            toggle.textContent = '▶';
        }
    }

    /**
     * Expand a date accordion if it's collapsed.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string
     */
    expandDateAccordion( senderId, dateString ) {
        const accordionId = `date-accordion-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        const accordion = document.getElementById( accordionId );
        if ( !accordion ) return;

        const messages = accordion.querySelector( '.date-accordion-messages' );
        const toggle = accordion.querySelector( '.date-toggle' );

        // Only expand if currently collapsed
        if ( messages && messages.classList.contains( 'collapsed' ) ) {
            messages.classList.remove( 'collapsed' );
            if ( toggle ) toggle.textContent = '▼';
            this.log( `Auto-expanded date accordion: ${dateString}` );
        }
    }

    /**
     * Add message to a date accordion.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string
     * @param {object} notification - Notification data
     * @param {boolean} isResponse - True if this is a user response
     */
    addMessageToDateAccordion( senderId, dateString, notification, isResponse ) {
        const containerId = `date-messages-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        const container = document.getElementById( containerId );
        if ( !container ) {
            this.error( `Date messages container not found: ${containerId}` );
            return;
        }

        // Format timestamp for display (time only since date is in header)
        // Prefer backend-provided time_display (includes timezone abbreviation: "23:10 EST")
        // Fall back to JavaScript formatting for legacy data
        let timeStr;
        if ( notification.time_display ) {
            timeStr = notification.time_display;
        } else {
            const timestamp = new Date( notification.timestamp || Date.now() );
            timeStr = timestamp.toLocaleTimeString( 'en-US', {
                hour   : '2-digit',
                minute : '2-digit',
                hour12 : false
            });
        }

        // Clean message (remove [PREFIX] since it's already shown in card header)
        let cleanMessage = notification.message || '';
        cleanMessage = cleanMessage.replace( /^\[[A-Z]+\]\s*/, '' );

        // Format multiple_choice JSON responses for display
        if ( isResponse && cleanMessage.startsWith( '{"answers":' ) ) {
            cleanMessage = this.formatMultipleChoiceResponse( cleanMessage );
        }

        // Truncate long messages
        const maxLength = 120;
        const displayMessage = cleanMessage.length > maxLength
            ? cleanMessage.substring( 0, maxLength ) + '...'
            : cleanMessage;

        // Build CSS class - add expired-response if notification was expired
        const isExpired = notification.was_expired === true;
        let cssClass = `sender-message ${isResponse ? 'outgoing' : 'incoming'}`;
        if ( isExpired ) {
            cssClass += ' expired-response';
        }

        // Add expired badge if applicable
        const expiredBadge = isExpired ? '<span class="expired-badge">EXPIRED</span>' : '';

        const messageDiv = document.createElement( 'div' );
        messageDiv.className = cssClass;
        messageDiv.id = notification.id || notification.id_hash || '';  // Set ID for TTS indicator
        messageDiv.innerHTML = `
            <span class="message-time">${timeStr}</span>
            <span class="message-text" title="${cleanMessage.replace( /"/g, '&quot;' )}">${displayMessage}${expiredBadge}</span>
            <button class="tts-stop-btn" onclick="window.notificationsUI.stopAudio(); event.stopPropagation();" title="Stop audio">⏹</button>
        `;

        // Add to top (newest first)
        container.insertBefore( messageDiv, container.firstChild );

        // Update date accordion count
        this.updateDateAccordionCount( senderId, dateString );
    }

    /**
     * Update the count display on a date accordion.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string
     */
    updateDateAccordionCount( senderId, dateString ) {
        const group = this.senderGroups.get( senderId );
        if ( !group ) return;

        const dateGroup = group.dateGroups.get( dateString );
        if ( !dateGroup ) return;

        const accordionId = `date-accordion-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        const accordion = document.getElementById( accordionId );
        if ( !accordion ) return;

        const countSpan = accordion.querySelector( '.date-count' );
        if ( countSpan ) {
            countSpan.textContent = `(${dateGroup.length})`;
        }
    }

    /**
     * Soft delete (hide) all notifications for a sender on a specific date.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string
     */
    async softDeleteByDate( senderId, dateString ) {
        if ( !confirm( `Hide all notifications from ${dateString}?` ) ) {
            return;
        }

        try {
            const response = await fetch(
                `/api/notifications/date/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUser )}/${dateString}`,
                {
                    method  : 'DELETE',
                    headers : this.getAuthHeaders()
                }
            );

            if ( response.ok ) {
                const result = await response.json();
                this.log( `Hidden ${result.hidden_count} notifications for ${dateString}` );

                // Remove from local data structure
                const group = this.senderGroups.get( senderId );
                if ( group && group.dateGroups.has( dateString ) ) {
                    const dateGroup = group.dateGroups.get( dateString );
                    group.totalCount -= dateGroup.length;
                    group.dateGroups.delete( dateString );

                    // Remove accordion from UI
                    const accordionId = `date-accordion-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
                    const accordion = document.getElementById( accordionId );
                    if ( accordion ) {
                        accordion.remove();
                    }

                    // Update sender card header
                    this.updateSenderCardHeader( senderId );

                    // If no more dates, remove sender card
                    if ( group.dateGroups.size === 0 ) {
                        this.removeSenderCard( senderId );
                    }
                }
            } else {
                const errorData = await response.json();
                this.error( `Failed to hide notifications: ${errorData.detail}` );
            }
        } catch ( error ) {
            this.error( `Error hiding notifications: ${error.message}` );
        }
    }

    /**
     * Remove a sender card from the UI and data structure.
     * @param {string} senderId - Sender ID
     */
    removeSenderCard( senderId ) {
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( card ) {
            card.remove();
        }
        this.senderGroups.delete( senderId );
        this.updateNotificationCount();
        this.log( `Removed sender card for ${senderId}` );
    }

    /**
     * Toggle sender card collapse state.
     * Shows/hides the date accordions container.
     * @param {string} senderId - Sender ID
     */
    toggleSenderCard( senderId ) {
        const group = this.senderGroups.get( senderId );
        if ( !group ) return;

        group.collapsed = !group.collapsed;

        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( card ) {
            const datesContainer = card.querySelector( '.sender-card-dates' );
            const toggle = card.querySelector( '.sender-toggle' );
            if ( datesContainer ) {
                datesContainer.style.display = group.collapsed ? 'none' : 'block';
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
        const containerId = `sender-messages-${senderId.replace( /[@.#]/g, '-' )}`;
        const container = document.getElementById( containerId );
        if ( !container ) return;

        // Prefer backend-provided time_display (includes timezone abbreviation: "23:10 EST")
        // Fall back to JavaScript formatting for legacy data
        let time;
        if ( notification.time_display ) {
            time = notification.time_display;
        } else {
            const timestamp = new Date( notification.timestamp || Date.now() );
            time = timestamp.toLocaleTimeString( [], { hour: '2-digit', minute: '2-digit' } );
        }

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

        // Prepend to container so newest messages always appear at top
        container.insertBefore( messageDiv, container.firstChild );
    }

    /**
     * Update sender card header with current stats.
     * Uses new data structure with dateGroups, totalCount, and newCount.
     * @param {string} senderId - Sender ID
     */
    updateSenderCardHeader( senderId ) {
        const group = this.senderGroups.get( senderId );
        if ( !group ) return;

        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( !card ) return;

        // Update total count
        const countEl = card.querySelector( '.sender-message-count' );
        if ( countEl ) {
            countEl.textContent = `(${group.totalCount})`;
        }

        // Update new count badge
        const newCountEl = card.querySelector( '.sender-new-count' );
        if ( newCountEl ) {
            if ( group.newCount > 0 ) {
                newCountEl.textContent = `${group.newCount} new`;
                newCountEl.style.display = 'inline-block';
            } else {
                newCountEl.style.display = 'none';
            }
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

        // Move card to top if it has new activity (handled by moveSenderCardToTop)
    }

    /**
     * Update total notifications count display and Clear All button state.
     * Uses new data structure with totalCount per sender group.
     */
    updateTotalNotificationsCount() {
        let total = 0;
        for ( const group of this.senderGroups.values() ) {
            total += group.totalCount;
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
     * Uses the senders-visible endpoint that excludes hidden notifications.
     * Uses activity-anchored window loading based on historyWindowHours.
     */
    async loadConversationHistory() {
        if ( !this.currentUser ) {
            this.log( 'Cannot load history: no user email' );
            return;
        }

        this.log( `Loading conversation history (window: ${this.historyWindowHours}h)...` );

        try {
            // Get list of senders with visible (non-hidden) notifications
            const sendersUrl = `/api/notifications/senders-visible/${encodeURIComponent( this.currentUser )}`;
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
            this.log( `Found ${senders.length} senders with visible history` );

            // Load date-grouped conversation for each sender
            // Set flag so createSenderCard() appends (preserving API sort order) instead of prepending
            this.isInitialLoad = true;
            for ( const senderInfo of senders ) {
                await this.loadSenderConversation( senderInfo.sender_id, senderInfo.last_activity );
            }
            this.isInitialLoad = false;

            this.updateTotalNotificationsCount();

        } catch ( error ) {
            this.error( `Failed to load conversation history: ${error.message}` );
        }
    }

    /**
     * Load conversation history for a specific sender.
     * Uses the conversation-by-date endpoint that returns date-grouped notifications.
     * @param {string} senderId - Sender ID
     * @param {string} anchorTime - ISO timestamp to anchor the window around
     */
    async loadSenderConversation( senderId, anchorTime = null ) {
        try {
            const baseUrl = `/api/notifications/conversation-by-date/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUser )}`;
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

            const dateGroupedData = await response.json();
            this.log( `Loaded date-grouped notifications for ${senderId}: ${Object.keys( dateGroupedData ).length} dates` );

            // Sort dates descending (newest first) for consistent UI ordering
            const sortedDates = Object.keys( dateGroupedData ).sort().reverse();

            // Process each date group in sorted order
            for ( const dateString of sortedDates ) {
                const notifications = dateGroupedData[ dateString ];
                for ( const notification of notifications ) {
                    // Always render original notification as incoming (left-aligned)
                    this.addNotificationToSenderGroup( notification, false );

                    // If user responded, render their response as a separate outgoing message
                    if ( notification.response_value && notification.response_value.value ) {
                        const responseNotification = {
                            ...notification,
                            id              : `${notification.id}-response`,
                            message         : notification.response_value.value,
                            created_at      : notification.responded_at,
                            response_value  : null  // Prevent infinite recursion
                        };
                        this.addNotificationToSenderGroup( responseNotification, true );
                    }
                }
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
            <button class="dropdown-display" onclick="window.notificationsUI.toggleHistoryDropdown()">
                ${currentOption.label}
                <span class="dropdown-arrow">▼</span>
            </button>
            <div class="dropdown-menu" id="history-dropdown-menu">
                ${this.WINDOW_OPTIONS.map( opt => `
                    <div class="dropdown-item ${opt.hours === this.historyWindowHours ? 'selected' : ''}"
                         onclick="window.notificationsUI.setHistoryWindow(${opt.hours})">
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

            // Add each notification to sender cards (newest first - server returns DESC order)
            serverNotifications.forEach( notification => {
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
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
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
            console.log( `[Notifications] ${message}`, ...args );
            this.addDebugMessage( message );
        }
    }
    
    error( message, ...args ) {
        console.error( `[Notifications ERROR] ${message}`, ...args );
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

    /**
     * Save action-required notifications to localStorage for persistence across refresh.
     * Saves queue order, active ID, and all pending/active notifications.
     */
    saveActionRequiredState() {
        try {
            const stateArray = [];
            const now = Date.now();

            for ( const [ id, state ] of this.actionRequiredNotifications.entries() ) {
                // Skip expired or responded notifications
                if ( state.isExpired || state.isResponded ) continue;

                // For active notification, check if it has expired
                if ( state.isActive && state.expiresAt && state.expiresAt <= now ) continue;

                // For pending notifications (expiresAt is null), always save
                stateArray.push( {
                    id                   : id,
                    notification         : state.notification,
                    expiresAt            : state.expiresAt,            // null for pending
                    activatedAt          : state.activatedAt,          // null for pending
                    timeoutSeconds       : state.timeoutSeconds,
                    isActive             : state.isActive || false,
                    queuePosition        : state.queuePosition,
                    currentQuestionIndex : state.currentQuestionIndex || 0,
                    collectedAnswers     : state.collectedAnswers || {}
                } );
            }

            // Save both notifications and queue state
            const queueState = {
                notifications : stateArray,
                queue         : this.actionRequiredQueue,
                activeId      : this.activeActionRequiredId
            };

            if ( stateArray.length > 0 ) {
                localStorage.setItem( this.ACTION_REQUIRED_KEY, JSON.stringify( queueState ) );
                this.log( `Saved ${stateArray.length} action-required notification(s) to localStorage` );
            } else {
                localStorage.removeItem( this.ACTION_REQUIRED_KEY );
                this.log( 'Cleared action-required localStorage (no active notifications)' );
            }
        } catch ( error ) {
            this.error( 'Failed to save action-required state:', error );
        }
    }

    /**
     * Restore action-required notifications from localStorage after page refresh.
     * Restores queue order, active notification, and pending notifications.
     */
    restoreActionRequiredState() {
        try {
            const stored = localStorage.getItem( this.ACTION_REQUIRED_KEY );
            if ( !stored ) {
                this.log( 'No action-required notifications to restore from localStorage' );
                return;
            }

            const parsed = JSON.parse( stored );
            const now = Date.now();

            // Handle both old format (array) and new format (object with queue)
            const stateArray = Array.isArray( parsed ) ? parsed : parsed.notifications || [];
            const savedQueue = parsed.queue || [];
            const savedActiveId = parsed.activeId || null;

            this.log( `Restoring: ${stateArray.length} notifications, queue: ${savedQueue.length}, active: ${savedActiveId}` );

            // First pass: restore all notification states to the Map
            for ( const saved of stateArray ) {
                // Skip if already in our Map (duplicate)
                if ( this.actionRequiredNotifications.has( saved.id ) ) {
                    this.log( `Skipping duplicate notification: ${saved.id}` );
                    continue;
                }

                const notification = saved.notification;

                // Recreate state object with queue properties
                const state = {
                    notification         : notification,
                    expiresAt            : saved.expiresAt,       // null for pending
                    activatedAt          : saved.activatedAt,     // null for pending
                    timeoutSeconds       : saved.timeoutSeconds,
                    isExpired            : false,
                    isResponded          : false,
                    isActive             : false,                 // Will be set during activation
                    queuePosition        : saved.queuePosition,
                    currentQuestionIndex : saved.currentQuestionIndex || 0,
                    collectedAnswers     : saved.collectedAnswers || {}
                };

                this.actionRequiredNotifications.set( saved.id, state );
            }

            // Restore queue order (filter out IDs not in our Map)
            this.actionRequiredQueue = savedQueue.filter( id =>
                this.actionRequiredNotifications.has( id )
            );

            // Show the Action Required section if we have notifications
            if ( this.actionRequiredNotifications.size > 0 ) {
                const section = document.getElementById( 'action-required-section' );
                if ( section ) {
                    section.style.display = 'block';
                }

                // Hide empty state
                const emptyState = document.getElementById( 'action-required-empty' );
                if ( emptyState ) {
                    emptyState.style.display = 'none';
                }
            }

            // Check if the saved active notification is still valid
            if ( savedActiveId && this.actionRequiredNotifications.has( savedActiveId ) ) {
                const activeState = this.actionRequiredNotifications.get( savedActiveId );

                // Check if active notification has expired
                if ( activeState.expiresAt && activeState.expiresAt <= now ) {
                    this.log( `Active notification ${savedActiveId} has expired, will activate next` );
                    this.actionRequiredNotifications.delete( savedActiveId );
                    // Remove from queue if present
                    this.actionRequiredQueue = this.actionRequiredQueue.filter( id => id !== savedActiveId );
                } else {
                    // Recalculate remaining time for active notification
                    if ( activeState.expiresAt ) {
                        const remainingMs = activeState.expiresAt - now;
                        const remainingSeconds = Math.ceil( remainingMs / 1000 );
                        activeState.timeoutSeconds = remainingSeconds;
                        activeState.notification.timeout_seconds = remainingSeconds;
                    }

                    // Mark as active and render
                    activeState.isActive = true;
                    this.activeActionRequiredId = savedActiveId;

                    // Render the active notification in the active slot
                    this.renderActionRequiredNotification( activeState.notification );

                    // Start countdown timer with remaining time
                    this.startCountdownTimer( savedActiveId );

                    this.log( `Restored active notification: ${savedActiveId}` );
                }
            }

            // Render pending notifications as minimized
            let position = 1;
            for ( const id of this.actionRequiredQueue ) {
                // Skip the active one (already rendered)
                if ( id === this.activeActionRequiredId ) continue;

                const state = this.actionRequiredNotifications.get( id );
                if ( state ) {
                    state.queuePosition = position;
                    this.renderMinimizedNotificationDOM( state.notification, position );
                    position++;
                }
            }

            // If no active notification but queue has items, activate first
            if ( this.activeActionRequiredId === null && this.actionRequiredQueue.length > 0 ) {
                this.log( 'No active notification, activating first in queue' );
                this.activateNextNotification();
            }

            // Update count and keyboard listener
            this.updateActionRequiredCount();
            if ( this.actionRequiredNotifications.size > 0 && !this.keyboardListenerActive ) {
                this.attachKeyboardListener();
            }

            this.log( `Restored ${this.actionRequiredNotifications.size} notification(s), queue: ${this.actionRequiredQueue.length}` );

            // Clean up localStorage after restore (remove expired entries)
            this.saveActionRequiredState();

        } catch ( error ) {
            this.error( 'Failed to restore action-required state:', error );
            // Clear corrupted data
            localStorage.removeItem( this.ACTION_REQUIRED_KEY );
        }
    }

    addActionRequiredNotification( notification ) {
        this.log( `Adding action-required notification: ${notification.id}` );

        // Store in action-required map with DEFERRED timer (expiresAt: null until activated)
        const state = {
            notification        : notification,
            expiresAt           : null,              // DEFERRED: set when activated, not on arrival
            activatedAt         : null,              // Timestamp when promoted to active
            timeoutSeconds      : notification.timeout_seconds,
            isExpired           : false,
            isResponded         : false,
            isActive            : false,             // True only for the active notification
            queuePosition       : null               // Position in queue (1-indexed), null when active
        };

        // Add multi-question state for multiple_choice notifications
        if ( notification.response_type === 'multiple_choice' ) {
            state.currentQuestionIndex = 0;
            state.collectedAnswers     = {};  // { header: value/[values] }
        }

        this.actionRequiredNotifications.set( notification.id, state );

        // Show the Action Required section
        const section = document.getElementById( 'action-required-section' );
        if ( section ) {
            section.style.display = 'block';
        }

        // Hide empty state
        const emptyState = document.getElementById( 'action-required-empty' );
        if ( emptyState ) {
            emptyState.style.display = 'none';
        }

        // Decision: activate immediately or defer until current TTS finishes?
        if ( this.activeActionRequiredId === null ) {
            this.actionRequiredQueue.push( notification.id );

            // Only activate if nothing is currently playing TTS
            // Otherwise, defer entire activation until current TTS finishes
            if ( !this.activeTTSItem ) {
                this.activateNextNotification();
            } else {
                // TTS is playing - defer activation and show minimal waiting indicator
                state.queuePosition = 1;  // Will be first when current TTS ends
                this.renderMinimizedNotificationDOM( notification, state.queuePosition );
                this.log( `Action-required deferred: waiting for current TTS to complete` );
            }
        } else {
            // Already have active - add to pending queue as minimized
            this.actionRequiredQueue.push( notification.id );
            state.queuePosition = this.actionRequiredQueue.length;
            this.renderMinimizedNotificationDOM( notification, state.queuePosition );
        }

        // Update count
        this.updateActionRequiredCount();

        // Attach keyboard listener if not already active
        if ( !this.keyboardListenerActive ) {
            this.attachKeyboardListener();
        }

        // Persist to localStorage for refresh survival
        this.saveActionRequiredState();
    }

    // ========================================
    // ACTION-REQUIRED QUEUE METHODS
    // ========================================

    /**
     * Promotes the next pending notification in queue to active state.
     * Only called when no notification is currently active.
     */
    activateNextNotification() {
        if ( this.activeActionRequiredId !== null ) {
            this.log( 'Cannot activate: another notification is already active' );
            return;
        }

        if ( this.actionRequiredQueue.length === 0 ) {
            this.log( 'Queue empty, nothing to activate' );
            this.activeActionRequiredId = null;

            // Show empty state if no notifications left
            const emptyState = document.getElementById( 'action-required-empty' );
            if ( emptyState && this.actionRequiredNotifications.size === 0 ) {
                emptyState.style.display = 'block';
            }
            return;
        }

        // Get next notification ID from queue
        const notificationId = this.actionRequiredQueue.shift();
        const state = this.actionRequiredNotifications.get( notificationId );

        if ( !state ) {
            this.log( `Notification ${notificationId} not found in state map, trying next` );
            this.activateNextNotification();  // Recursive call for next
            return;
        }

        // Promote to active
        this.activeActionRequiredId = notificationId;
        state.isActive = true;
        state.queuePosition = null;
        state.activatedAt = Date.now();
        state.expiresAt = Date.now() + ( state.timeoutSeconds * 1000 );

        this.log( `Activating notification: ${notificationId}, timeout: ${state.timeoutSeconds}s` );

        // Remove minimized version if it exists (for refresh recovery)
        const minimized = document.getElementById( `action-required-minimized-${notificationId}` );
        if ( minimized ) {
            minimized.classList.add( 'minimized-to-active' );
            setTimeout( () => minimized.remove(), 300 );
        }

        // Render full card in active slot
        this.renderActionRequiredNotification( state.notification );

        // Start timer (only now!)
        this.startCountdownTimer( notificationId );

        // Play TTS for this notification (if high/urgent)
        this.playActivatedNotificationTTS( notificationId );

        // Recalculate queue positions for remaining items
        this.recalculateQueuePositions();

        // Persist state
        this.saveActionRequiredState();
    }

    /**
     * Renders a minimized (collapsed) notification card for queue display.
     */
    renderMinimizedNotificationDOM( notification, queuePosition ) {
        const container = document.getElementById( 'action-required-pending-queue' );
        if ( !container ) {
            this.error( 'Pending queue container not found' );
            return;
        }

        const truncatedMessage = notification.message.length > 60
            ? notification.message.substring( 0, 57 ) + '...'
            : notification.message;

        const typeIcon = {
            'yes_no': '❓',
            'open_ended': '💬',
            'multiple_choice': '📋'
        }[ notification.response_type ] || '📢';

        const timeoutDisplay = this.formatTimeoutDisplay( notification.timeout_seconds );

        const card = document.createElement( 'div' );
        card.className = 'action-required-minimized';
        card.id = `action-required-minimized-${notification.id}`;
        card.dataset.notificationId = notification.id;

        card.innerHTML = `
            <div class="minimized-position">#${queuePosition}</div>
            <div class="minimized-icon">${typeIcon}</div>
            <div class="minimized-message">${truncatedMessage}</div>
            <div class="minimized-timeout">${timeoutDisplay}</div>
        `;

        // Click handler shows tooltip (no jump-the-queue allowed)
        card.addEventListener( 'click', () => {
            this.showMinimizedTooltip( card );
        } );

        container.appendChild( card );
    }

    /**
     * Formats timeout duration for display in minimized cards.
     */
    formatTimeoutDisplay( seconds ) {
        if ( seconds >= 60 ) {
            return `${Math.floor( seconds / 60 )}m`;
        }
        return `${seconds}s`;
    }

    /**
     * Shows tooltip when user clicks on a minimized (pending) notification.
     */
    showMinimizedTooltip( card ) {
        // Remove any existing tooltip
        const existingTooltip = document.querySelector( '.minimized-tooltip' );
        if ( existingTooltip ) {
            existingTooltip.remove();
        }

        const tooltip = document.createElement( 'div' );
        tooltip.className = 'minimized-tooltip';
        tooltip.textContent = 'Please respond to the current notification first';
        tooltip.style.cssText = `
            position: absolute;
            background: #333;
            color: white;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            z-index: 1000;
            white-space: nowrap;
        `;

        // Position near the card
        const rect = card.getBoundingClientRect();
        tooltip.style.left = `${rect.left}px`;
        tooltip.style.top = `${rect.bottom + 5}px`;

        document.body.appendChild( tooltip );

        // Auto-remove after 2 seconds
        setTimeout( () => tooltip.remove(), 2000 );
    }

    // ========================================
    // UNIFIED TTS QUEUE METHODS
    // ========================================

    /**
     * Adds an item to the unified TTS queue with priority insertion.
     * Action-required notifications insert at FRONT (after other action-required items).
     * Fire-and-forget notifications insert at BACK.
     *
     * @param {object} item - TTS queue item: {id, type, notification, ttsText, addedAt}
     */
    addToTTSQueue( item ) {
        if ( item.type === 'action-required' ) {
            // Priority: Insert at front (but after other action-required items)
            const insertIndex = this.ttsQueue.findIndex( q => q.type !== 'action-required' );
            if ( insertIndex === -1 ) {
                this.ttsQueue.push( item );  // All are action-required, add to end
            } else {
                this.ttsQueue.splice( insertIndex, 0, item );  // Insert before first non-priority
            }
            this.log( `TTS queue: Added action-required item at priority position, queue length: ${this.ttsQueue.length}` );
        } else {
            // Fire-and-forget: Add to back
            this.ttsQueue.push( item );
            this.log( `TTS queue: Added fire-and-forget item at back, queue length: ${this.ttsQueue.length}` );
        }

        // Update UI
        this.updateTTSQueueSection();

        // If nothing is currently playing AND not in focus mode, start playback
        if ( !this.activeTTSItem && !this.ttsFocusModeActive ) {
            this.activateNextTTS();
        } else if ( this.ttsFocusModeActive ) {
            // In focus mode: just render the minimized card, don't auto-play
            this.renderMinimizedTTSCard( item );
            this.log( 'TTS queue: In focus mode, item queued but not auto-playing' );
        } else {
            // Something is playing: render minimized card for the queued item
            this.renderMinimizedTTSCard( item );
        }

        // Persist queue state
        this.saveTTSQueueState();
    }

    /**
     * Activates the next item in the TTS queue for playback.
     * Called when nothing is playing or when current playback completes.
     *
     * Behavior differs by type:
     * - Fire-and-forget: Add to project card now (was waiting in queue), no TTS active card
     * - Action-required: Show in TTS active slot (response UI is in action-required section)
     */
    activateNextTTS() {
        if ( this.ttsQueue.length === 0 ) {
            this.log( 'TTS queue empty, nothing to activate' );
            this.activeTTSItem = null;
            this.updateTTSQueueSection();
            return;
        }

        // Get next item from queue
        const item = this.ttsQueue.shift();
        this.activeTTSItem = item;

        this.log( `TTS queue: Activating item ${item.id} (${item.type})` );

        // Remove minimized card from TTS queue UI
        const minimized = document.getElementById( `tts-minimized-${item.id}` );
        if ( minimized ) {
            minimized.remove();
        }

        // Handle differently based on type
        if ( item.type === 'action-required' ) {
            // Action-required: Show active card in TTS queue (response UI is elsewhere)
            this.renderActiveTTSCard( item );
            this.currentNotificationId = `action-required-${item.id}`;
        } else {
            // Fire-and-forget: NOW add to project card (was waiting in TTS queue)
            this.log( `Moving fire-and-forget to project card: ${item.id}` );
            this.addNotificationToSenderGroup( item.notification, false );
            this.updateTotalNotificationsCount();
            // No active card in TTS queue - message now visible in project card
            this.currentNotificationId = item.id;
        }

        // Recalculate queue positions for remaining items
        this.updateTTSQueuePositions();

        // Update TTS queue section display
        this.updateTTSQueueSection();

        // Persist queue state (item was removed from queue)
        this.saveTTSQueueState();

        // Start TTS playback
        this.playTTS( item.ttsText, this.getCurrentTTSMode() ).catch( error => {
            this.error( 'TTS queue: Playback failed:', error );
            this.onTTSPlaybackComplete();  // Move to next item even on error
        } );
    }

    /**
     * Renders the currently playing TTS item in the active slot.
     */
    renderActiveTTSCard( item ) {
        const container = document.getElementById( 'tts-active-slot' );
        if ( !container ) {
            this.error( 'TTS active slot container not found' );
            return;
        }

        const icon = item.type === 'action-required' ? '⚠️' : '🔔';
        const truncatedText = item.ttsText.length > 80
            ? item.ttsText.substring( 0, 77 ) + '...'
            : item.ttsText;

        // Build card using DOM methods for safe text insertion
        const card = document.createElement( 'div' );
        card.className = 'tts-active-card';

        const iconDiv = document.createElement( 'div' );
        iconDiv.className = 'tts-type-icon';
        iconDiv.textContent = icon;

        const messageDiv = document.createElement( 'div' );
        messageDiv.className = 'tts-message';
        messageDiv.textContent = truncatedText;

        const stopBtn = document.createElement( 'button' );
        stopBtn.className = 'tts-stop-button';
        stopBtn.textContent = '⏹️ Stop';
        stopBtn.onclick = () => this.stopTTSAndAdvance();

        card.appendChild( iconDiv );
        card.appendChild( messageDiv );
        card.appendChild( stopBtn );

        container.innerHTML = '';
        container.appendChild( card );
    }

    /**
     * Renders a minimized card for a queued TTS item.
     */
    renderMinimizedTTSCard( item ) {
        const container = document.getElementById( 'tts-pending-queue' );
        if ( !container ) {
            this.error( 'TTS pending queue container not found' );
            return;
        }

        // Calculate position (1-indexed)
        const position = this.ttsQueue.indexOf( item ) + 1;
        const icon = item.type === 'action-required' ? '⚠️' : '🔔';
        const truncatedText = item.ttsText.length > 50
            ? item.ttsText.substring( 0, 47 ) + '...'
            : item.ttsText;

        // Build card using DOM methods for safe text insertion
        const card = document.createElement( 'div' );
        card.className = `tts-minimized ${item.type === 'action-required' ? 'priority' : ''}`;
        card.id = `tts-minimized-${item.id}`;
        card.dataset.itemId = item.id;

        const positionDiv = document.createElement( 'div' );
        positionDiv.className = 'tts-position';
        positionDiv.textContent = position;

        const badgeDiv = document.createElement( 'div' );
        badgeDiv.className = 'tts-type-badge';
        badgeDiv.textContent = icon;

        const textDiv = document.createElement( 'div' );
        textDiv.className = 'tts-text';
        textDiv.textContent = truncatedText;

        card.appendChild( positionDiv );
        card.appendChild( badgeDiv );
        card.appendChild( textDiv );

        container.appendChild( card );
    }

    /**
     * Updates position badges for all minimized TTS cards.
     */
    updateTTSQueuePositions() {
        this.ttsQueue.forEach( ( item, index ) => {
            const badge = document.querySelector( `#tts-minimized-${item.id} .tts-position` );
            if ( badge ) {
                badge.textContent = `${index + 1}`;
            }
        } );
    }

    /**
     * Updates the TTS queue section visibility and count.
     * Shows paused state when in Focus Mode.
     */
    updateTTSQueueSection() {
        const section = document.getElementById( 'tts-queue-section' );
        const countSpan = document.getElementById( 'tts-queue-count' );
        const activeSlot = document.getElementById( 'tts-active-slot' );
        const header = section?.querySelector( 'h3' );
        const resumeBtn = document.getElementById( 'tts-resume-btn' );

        if ( !section ) return;

        const totalCount = this.ttsQueue.length + ( this.activeTTSItem ? 1 : 0 );

        // Show section only if items actually waiting in queue
        // Focus mode with 0 items = nothing to show (no "Paused: 0 waiting")
        const showSection = this.ttsQueue.length > 0;

        if ( !showSection ) {
            section.style.display = 'none';
            section.classList.remove( 'focus-mode' );
            if ( activeSlot ) activeSlot.innerHTML = '';
            if ( resumeBtn ) resumeBtn.style.display = 'none';
        } else {
            section.style.display = 'block';

            // Focus Mode: Update header and styling
            if ( this.ttsFocusModeActive ) {
                section.classList.add( 'focus-mode' );
                if ( header ) {
                    header.innerHTML = `Paused: <span id="tts-queue-count">${this.ttsQueue.length}</span> waiting`;
                }
                if ( resumeBtn ) resumeBtn.style.display = 'inline-block';
            } else {
                section.classList.remove( 'focus-mode' );
                if ( header ) {
                    header.innerHTML = `🔊 Playing: <span id="tts-queue-count">${totalCount}</span>`;
                }
                if ( resumeBtn ) resumeBtn.style.display = 'none';
            }

            if ( countSpan ) {
                countSpan.textContent = this.ttsFocusModeActive ? this.ttsQueue.length : totalCount;
            }
        }
    }

    /**
     * Called when TTS playback completes (success or error).
     * Clears active item and activates next in queue.
     * For action-required: enters Focus Mode to pause queue during response.
     */
    onTTSPlaybackComplete() {
        this.log( 'TTS queue: Playback complete' );

        // Capture item info BEFORE clearing (needed for focus mode check)
        const justCompletedItem = this.activeTTSItem;
        const wasActionRequired = justCompletedItem?.type === 'action-required';

        // Clear pulsing border from current item
        if ( this.currentNotificationId ) {
            this.stopTTSPlayingIndicator( this.currentNotificationId );
            this.currentNotificationId = null;
        }

        // Clear active slot
        const activeSlot = document.getElementById( 'tts-active-slot' );
        if ( activeSlot ) activeSlot.innerHTML = '';

        // FOCUS MODE: If action-required just finished, pause queue for user response
        // IMPORTANT: Enter focus mode BEFORE clearing activeTTSItem to prevent race condition
        // where incoming notifications could trigger TTS between clearing and setting focus mode
        if ( wasActionRequired && justCompletedItem?.id ) {
            this.enterTTSFocusMode( justCompletedItem.id );
            this.activeTTSItem = null;  // Now safe to clear
            this.updateTTSQueueSection();
            return;  // Exit early - don't activate next until response received
        }

        // Clear active item (only for non-action-required completions)
        this.activeTTSItem = null;

        // Check if there's a deferred action-required waiting to be activated
        // This happens when action-required arrived while fire-and-forget was playing
        if ( this.actionRequiredQueue.length > 0 && this.activeActionRequiredId === null ) {
            this.log( 'TTS queue: Activating deferred action-required notification' );
            this.activateNextNotification();
            return;  // activateNextNotification() will handle TTS via playActivatedNotificationTTS()
        }

        // Don't advance queue if in focus mode (waiting for response)
        if ( this.ttsFocusModeActive ) {
            this.log( 'TTS queue: In focus mode, not advancing' );
            this.updateTTSQueueSection();
            return;
        }

        // Normal flow: activate next item if queue not empty
        if ( this.ttsQueue.length > 0 ) {
            this.activateNextTTS();
        } else {
            this.updateTTSQueueSection();
        }
    }

    /**
     * Stops current TTS playback and advances to next item in queue.
     * Called from UI stop button.
     */
    stopTTSAndAdvance() {
        this.log( 'TTS queue: User requested stop' );
        this.stopAllAudio();
        this.onTTSPlaybackComplete();
    }

    // =========================================================================
    // TTS FOCUS MODE - Pause queue while responding to action-required
    // =========================================================================

    /**
     * Enters TTS Focus Mode - pauses queue while user responds to action-required.
     * Called after action-required TTS completes.
     *
     * Requires:
     *     - notificationId is a valid action-required notification ID
     *
     * Ensures:
     *     - ttsFocusModeActive is set to true
     *     - focusModeNotificationId is stored
     *     - UI updated to show paused state
     */
    enterTTSFocusMode( notificationId ) {
        this.log( `TTS Focus Mode: ENTERING for notification ${notificationId}` );
        this.ttsFocusModeActive = true;
        this.focusModeNotificationId = notificationId;
        this.updateTTSQueueSection();

        // Persist focus mode state
        this.saveTTSQueueState();
    }

    /**
     * Exits TTS Focus Mode - resumes queue after action-required is resolved.
     * Called when notification is responded, expired, or dismissed.
     *
     * Ensures:
     *     - ttsFocusModeActive is set to false
     *     - focusModeNotificationId is cleared
     *     - Queue resumes if items are waiting
     */
    exitTTSFocusMode() {
        if ( !this.ttsFocusModeActive ) {
            return;  // Not in focus mode, nothing to do
        }

        this.log( `TTS Focus Mode: EXITING (was for ${this.focusModeNotificationId})` );
        this.ttsFocusModeActive = false;
        this.focusModeNotificationId = null;
        this.updateTTSQueueSection();

        // Persist focus mode state change
        this.saveTTSQueueState();

        // Resume queue if items waiting
        if ( this.ttsQueue.length > 0 ) {
            this.log( `TTS Focus Mode: Resuming queue with ${this.ttsQueue.length} items` );
            setTimeout( () => this.activateNextTTS(), 100 );  // Small delay for UI to settle
        }
    }

    /**
     * Toggles TTS Focus Mode - manual Resume button handler.
     * Allows user to resume queue early if they want to.
     */
    toggleTTSFocusMode() {
        if ( this.ttsFocusModeActive ) {
            this.log( 'TTS Focus Mode: Manual resume requested' );
            this.exitTTSFocusMode();
        }
    }

    // =========================================================================
    // TTS QUEUE PERSISTENCE - Save/restore across page refresh
    // =========================================================================

    /**
     * Save TTS queue state to localStorage for persistence across page refresh.
     * Saves queue items and focus mode state.
     */
    saveTTSQueueState() {
        try {
            if ( this.ttsQueue.length === 0 && !this.ttsFocusModeActive ) {
                localStorage.removeItem( this.TTS_QUEUE_KEY );
                return;
            }

            const queueState = {
                queue                   : this.ttsQueue,
                focusModeActive         : this.ttsFocusModeActive,
                focusModeNotificationId : this.focusModeNotificationId
            };

            localStorage.setItem( this.TTS_QUEUE_KEY, JSON.stringify( queueState ) );
            this.log( `Saved ${this.ttsQueue.length} TTS queue item(s) to localStorage` );
        } catch ( error ) {
            this.error( 'Failed to save TTS queue state:', error );
        }
    }

    /**
     * Restore TTS queue state from localStorage after page refresh.
     * Restores queue items and focus mode state.
     */
    restoreTTSQueueState() {
        try {
            const stored = localStorage.getItem( this.TTS_QUEUE_KEY );
            if ( !stored ) {
                this.log( 'No TTS queue to restore from localStorage' );
                return;
            }

            const parsed = JSON.parse( stored );
            this.ttsQueue = parsed.queue || [];
            this.ttsFocusModeActive = parsed.focusModeActive || false;
            this.focusModeNotificationId = parsed.focusModeNotificationId || null;

            this.log( `Restored ${this.ttsQueue.length} TTS queue item(s), focusMode: ${this.ttsFocusModeActive}` );

            // Re-render minimized cards for queued items
            for ( const item of this.ttsQueue ) {
                this.renderMinimizedTTSCard( item );
            }

            this.updateTTSQueueSection();

            // If not in focus mode and queue has items, start playback
            if ( !this.ttsFocusModeActive && this.ttsQueue.length > 0 ) {
                this.activateNextTTS();
            }
        } catch ( error ) {
            this.error( 'Failed to restore TTS queue state:', error );
            localStorage.removeItem( this.TTS_QUEUE_KEY );
        }
    }

    /**
     * Recalculates and updates queue position badges for all pending notifications.
     */
    recalculateQueuePositions() {
        this.actionRequiredQueue.forEach( ( notificationId, index ) => {
            const state = this.actionRequiredNotifications.get( notificationId );
            if ( state ) {
                state.queuePosition = index + 1;  // 1-indexed
            }

            // Update DOM badge
            const badge = document.querySelector(
                `#action-required-minimized-${notificationId} .minimized-position`
            );
            if ( badge ) {
                badge.textContent = `#${index + 1}`;
            }
        } );
    }

    /**
     * Plays TTS for an activated notification (only if high/urgent priority).
     */
    playActivatedNotificationTTS( notificationId ) {
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        const notification = state.notification;

        // Only play TTS for high/urgent priority
        if ( notification.priority !== 'high' && notification.priority !== 'urgent' ) {
            this.log( `Skipping TTS for ${notification.priority} priority notification` );
            return;
        }

        let ttsText = null;

        // Different field per response type:
        // - Multiple-choice: Read the question field from response_options
        // - Open-ended / Yes-No: Read the message field
        if ( notification.response_type === 'multiple_choice' &&
             notification.response_options?.questions?.[0]?.question ) {
            ttsText = notification.response_options.questions[0].question;
        } else {
            ttsText = notification.message;
        }

        if ( ttsText ) {
            this.log( `Adding action-required notification to TTS queue: "${ttsText}"` );

            // Use unified TTS queue with priority insertion (action-required goes to front)
            this.addToTTSQueue( {
                id           : notificationId,
                type         : 'action-required',
                notification : notification,
                ttsText      : ttsText,
                addedAt      : Date.now()
            } );
        }
    }

    renderActionRequiredNotification( notification ) {
        // Render to the active slot (only ONE notification fully displayed at a time)
        const container = document.getElementById( 'action-required-active-slot' );
        if ( !container ) {
            this.error( "Action required active slot container not found" );
            return;
        }

        // Clear any existing active notification from the slot
        container.innerHTML = '';

        // Hide empty state when adding notification
        const emptyState = document.getElementById( 'action-required-empty' );
        if ( emptyState ) {
            emptyState.style.display = 'none';
        }

        // Create notification card
        const card = document.createElement( 'div' );
        card.id = `action-required-${notification.id}`;
        card.className = 'action-required-notification active expand-in';  // Add expand animation

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

            // Voice-first layout: mic button first for immediate keyboard activation
            responseUI = `
                <div class="response-open-ended">
                    <div class="response-input-container">
                        <button class="response-mic-button" data-notification-id="${notification.id}" title="Press Enter or Space to record (30s max, ESC to cancel)">
                            🎤
                        </button>
                        <input type="text" class="response-text-input" id="response-input-${notification.id}" value="${notification.response_default || ''}" placeholder="Type your response...">
                        <button class="response-submit-button" data-notification-id="${notification.id}">
                            Submit
                        </button>
                    </div>
                </div>
            `;
        } else if ( notification.response_type === 'multiple_choice' ) {
            responseUI = this.renderMultipleChoiceUI( notification );
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

        // Scroll the action required section into view (delay ensures DOM is settled)
        setTimeout( () => {
            const section = document.getElementById( 'action-required-section' );
            if ( section ) {
                section.scrollIntoView( { behavior: 'smooth', block: 'start' } );
            }
        }, 50 );

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

            // Voice-first: focus mic button for immediate Enter/Space activation
            micButton.focus( { preventScroll: true } );

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

            // Voice-first: Enter/Space activates voice recording when mic button is focused
            micButton.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' || e.key === ' ' ) {
                    e.preventDefault();  // Prevent space from scrolling page
                    this.startVoiceInput( notification.id );
                }
            } );
        } else if ( notification.response_type === 'multiple_choice' ) {
            // Use centralized event handler attachment (supports multi-question navigation)
            this.attachMultipleChoiceEventHandlers( notification.id, card );
        }
    }

    /**
     * Renders the UI for a multiple-choice question notification.
     * Supports multi-question flows with Back/Next/Submit navigation.
     *
     * Requires:
     *   - notification.response_options.questions is a non-empty array
     *   - Each question has: question (string), header (string), multi_select (bool), options (array)
     *   - State has currentQuestionIndex and collectedAnswers
     *
     * Ensures:
     *   - Returns HTML string with radio buttons (single-select) or checkboxes (multi-select)
     *   - Always includes "Other" option with text input and voice recording
     *   - Shows "Question N of X" indicator
     *   - Shows appropriate navigation buttons based on position
     */
    renderMultipleChoiceUI( notification, questionIndex = 0 ) {
        const questions = notification.response_options?.questions || [];
        if ( questions.length === 0 ) return '';

        const totalQuestions = questions.length;
        const question       = questions[ questionIndex ];
        const inputType      = question.multi_select ? 'checkbox' : 'radio';
        const questionId     = `mc-${notification.id}-q${questionIndex}`;

        // Extract project for source indicator badge
        const project      = this.getProjectFromSenderId( notification.sender_id );
        const projectBadge = project && project !== 'UNKNOWN'
            ? `<span class="mc-project-badge">[${project}]</span>`
            : '';

        // Check for previously saved answer for this question
        const state       = this.actionRequiredNotifications.get( notification.id );
        const savedAnswer = state?.collectedAnswers?.[ question.header ];

        let optionsHTML = question.options.map( ( opt, idx ) => {
            // Check if this option was previously selected
            let isChecked = false;
            if ( savedAnswer ) {
                if ( Array.isArray( savedAnswer ) ) {
                    isChecked = savedAnswer.includes( opt.label );
                } else {
                    isChecked = savedAnswer === opt.label;
                }
            }

            return `
                <label class="mc-option">
                    <input type="${inputType}" name="${questionId}" value="${opt.label}"
                           class="mc-input" data-idx="${idx}" ${isChecked ? 'checked' : ''}>
                    <div class="mc-option-content">
                        <span class="mc-option-label">${opt.label}</span>
                        <span class="mc-option-desc">${opt.description || ''}</span>
                    </div>
                </label>
            `;
        } ).join( '' );

        // Check if "Other" was previously selected and get its text
        let otherChecked = false;
        let otherText    = '';
        if ( savedAnswer ) {
            const allLabels = question.options.map( o => o.label );
            if ( Array.isArray( savedAnswer ) ) {
                // Multi-select: find any value not in options
                const customAnswers = savedAnswer.filter( v => !allLabels.includes( v ) );
                if ( customAnswers.length > 0 ) {
                    otherChecked = true;
                    otherText    = customAnswers.join( ', ' );
                }
            } else if ( !allLabels.includes( savedAnswer ) ) {
                // Single-select: answer not in options means it's custom
                otherChecked = true;
                otherText    = savedAnswer;
            }
        }

        // Always add "Other" option with voice input support
        optionsHTML += `
            <label class="mc-option mc-option-other">
                <input type="${inputType}" name="${questionId}" value="__other__"
                       class="mc-input mc-other-radio" ${otherChecked ? 'checked' : ''}>
                <div class="mc-option-content">
                    <span class="mc-option-label">Other</span>
                    <div class="mc-other-input-container">
                        <button type="button" class="response-mic-button mc-other-mic"
                                data-notification-id="${notification.id}"
                                title="Press Enter or Space to record (30s max, ESC to cancel)">🎤</button>
                        <input type="text" class="mc-other-input" id="mc-other-input-${notification.id}"
                               placeholder="Type or speak custom answer..." value="${otherText}">
                    </div>
                </div>
            </label>
        `;

        // Build navigation buttons
        const isFirstQuestion = questionIndex === 0;
        const isLastQuestion  = questionIndex === totalQuestions - 1;

        let actionsHTML = '<div class="mc-actions">';

        if ( !isFirstQuestion ) {
            actionsHTML += `
                <button class="response-submit-button mc-back" data-notification-id="${notification.id}">
                    ← Back
                </button>
            `;
        }

        if ( isLastQuestion ) {
            actionsHTML += `
                <button class="response-submit-button mc-submit" data-notification-id="${notification.id}">
                    ${totalQuestions === 1 ? 'Submit' : 'Submit All ✓'}
                </button>
            `;
        } else {
            actionsHTML += `
                <button class="response-submit-button mc-next" data-notification-id="${notification.id}">
                    Next Question →
                </button>
            `;
        }

        actionsHTML += '</div>';

        return `
            <div class="response-multiple-choice" data-notification-id="${notification.id}" data-question-index="${questionIndex}">
                <div class="mc-question-header">
                    ${projectBadge}
                    <span class="mc-question-indicator">Question ${questionIndex + 1} of ${totalQuestions}</span>
                </div>
                <div class="mc-question-text">${question.question}</div>
                ${question.multi_select ? '<div class="mc-multi-hint">(Select all that apply)</div>' : ''}
                <div class="mc-options">
                    ${optionsHTML}
                </div>
                ${actionsHTML}
            </div>
        `;
    }

    /**
     * Gets the current question's answer from the UI.
     *
     * Requires:
     *   - notificationId corresponds to an active multiple_choice notification
     *
     * Ensures:
     *   - Returns { header, value } for the current question
     *   - Returns null and shows validation error if no selection
     */
    getCurrentQuestionAnswer( notificationId ) {
        const card      = document.getElementById( `action-required-${notificationId}` );
        const container = card?.querySelector( '.response-multiple-choice' );
        if ( !container ) return null;

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return null;

        const questionIndex = state.currentQuestionIndex || 0;
        const questions     = state.notification.response_options?.questions || [];
        const question      = questions[ questionIndex ];
        if ( !question ) return null;

        const checked = container.querySelectorAll( '.mc-input:checked' );
        if ( checked.length === 0 ) {
            container.classList.add( 'invalid' );
            return null;
        }

        const answers = [];
        checked.forEach( input => {
            if ( input.value === '__other__' ) {
                const otherText = container.querySelector( '.mc-other-input' )?.value.trim();
                if ( otherText ) answers.push( otherText );
            } else {
                answers.push( input.value );
            }
        } );

        // Handle case where "Other" was selected but no text entered
        if ( answers.length === 0 ) {
            container.classList.add( 'invalid' );
            return null;
        }

        return {
            header: question.header,
            value : question.multi_select ? answers : answers[ 0 ]
        };
    }

    /**
     * Saves the current question's answer to collectedAnswers.
     *
     * Requires:
     *   - notificationId corresponds to an active multiple_choice notification
     *
     * Ensures:
     *   - Current answer is saved to state.collectedAnswers
     *   - Returns true if saved successfully, false if validation failed
     */
    saveCurrentQuestionAnswer( notificationId ) {
        const answer = this.getCurrentQuestionAnswer( notificationId );
        if ( !answer ) return false;

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return false;

        state.collectedAnswers[ answer.header ] = answer.value;
        this.log( `Saved answer for "${answer.header}":`, answer.value );
        return true;
    }

    /**
     * Navigates to a different question in a multi-question notification.
     *
     * Requires:
     *   - notificationId corresponds to an active multiple_choice notification
     *   - direction is 'next' or 'back'
     *
     * Ensures:
     *   - For 'next': saves current answer, advances to next question
     *   - For 'back': goes to previous question (answer already saved)
     *   - Re-renders the question UI with event handlers
     */
    navigateMultipleChoice( notificationId, direction ) {
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        const questions    = state.notification.response_options?.questions || [];
        const currentIndex = state.currentQuestionIndex || 0;

        if ( direction === 'next' ) {
            // Save current answer before moving forward
            if ( !this.saveCurrentQuestionAnswer( notificationId ) ) {
                return;  // Validation failed
            }

            if ( currentIndex < questions.length - 1 ) {
                state.currentQuestionIndex = currentIndex + 1;
            }
        } else if ( direction === 'back' ) {
            // Save current answer when going back (optional but nice)
            this.saveCurrentQuestionAnswer( notificationId );

            if ( currentIndex > 0 ) {
                state.currentQuestionIndex = currentIndex - 1;
            }
        }

        // Re-render the question UI
        this.rerenderMultipleChoiceUI( notificationId );
    }

    /**
     * Re-renders the multiple choice UI after navigation.
     * Replaces the question content and re-attaches event handlers.
     */
    rerenderMultipleChoiceUI( notificationId ) {
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        const card      = document.getElementById( `action-required-${notificationId}` );
        const container = card?.querySelector( '.response-multiple-choice' );
        if ( !container ) return;

        // Generate new HTML for current question
        const newHTML = this.renderMultipleChoiceUI(
            state.notification,
            state.currentQuestionIndex || 0
        );

        // Replace container content
        container.outerHTML = newHTML;

        // Re-attach event handlers
        this.attachMultipleChoiceEventHandlers( notificationId, card );
    }

    /**
     * Attaches event handlers to multiple choice UI elements.
     * Called after initial render and after navigation re-renders.
     */
    attachMultipleChoiceEventHandlers( notificationId, card ) {
        const container   = card.querySelector( '.response-multiple-choice' );
        const submitBtn   = card.querySelector( '.mc-submit' );
        const nextBtn     = card.querySelector( '.mc-next' );
        const backBtn     = card.querySelector( '.mc-back' );
        const otherInput  = card.querySelector( '.mc-other-input' );
        const otherRadio  = card.querySelector( '.mc-other-radio' );
        const otherMicBtn = card.querySelector( '.mc-other-mic' );

        // Clear validation state when user makes a selection
        // Also auto-focus the action button (Next or Submit) for keyboard accessibility
        container?.querySelectorAll( '.mc-input' ).forEach( input => {
            input.addEventListener( 'change', () => {
                container.classList.remove( 'invalid' );
                // Focus the primary action button so user can press Enter
                // Next button exists for non-final questions, Submit for final
                const actionBtn = nextBtn || submitBtn;
                if ( actionBtn ) {
                    actionBtn.focus( { preventScroll: true } );
                }
            } );
        } );

        // Enable Other text input when Other is selected
        otherInput?.addEventListener( 'focus', () => {
            if ( otherRadio ) otherRadio.checked = true;
        } );

        // Next button - save answer and go to next question
        nextBtn?.addEventListener( 'click', () => {
            this.navigateMultipleChoice( notificationId, 'next' );
        } );

        // Back button - go to previous question
        backBtn?.addEventListener( 'click', () => {
            this.navigateMultipleChoice( notificationId, 'back' );
        } );

        // Submit button - save final answer and submit all
        submitBtn?.addEventListener( 'click', () => {
            this.submitAllMultipleChoiceAnswers( notificationId );
        } );

        // Enter key in Other text input triggers next/submit
        otherInput?.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' ) {
                e.preventDefault();
                if ( nextBtn ) {
                    this.navigateMultipleChoice( notificationId, 'next' );
                } else if ( submitBtn ) {
                    this.submitAllMultipleChoiceAnswers( notificationId );
                }
            }
        } );

        // Mic button click - start voice input for Other field
        otherMicBtn?.addEventListener( 'click', ( e ) => {
            e.preventDefault();
            e.stopPropagation();
            this.startMultipleChoiceVoiceInput( notificationId );
        } );

        // Mic button keyboard activation (Enter/Space)
        otherMicBtn?.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' || e.key === ' ' ) {
                e.preventDefault();
                e.stopPropagation();
                this.startMultipleChoiceVoiceInput( notificationId );
            }
        } );

        // Store notification ID for Ctrl+R shortcut
        this.activeMultipleChoiceNotificationId = notificationId;
    }

    /**
     * Submits all collected answers for a multi-question notification.
     */
    submitAllMultipleChoiceAnswers( notificationId ) {
        // Save the final question's answer
        if ( !this.saveCurrentQuestionAnswer( notificationId ) ) {
            return;  // Validation failed
        }

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        // Build final response with all collected answers
        const response = {
            answers: state.collectedAnswers
        };

        this.log( 'Submitting all answers:', response );
        this.submitResponse( notificationId, JSON.stringify( response ) );
    }

    /**
     * Legacy method - gets selection for single-question notifications.
     * For multi-question, use submitAllMultipleChoiceAnswers instead.
     */
    getMultipleChoiceSelection( notificationId ) {
        const answer = this.getCurrentQuestionAnswer( notificationId );
        if ( !answer ) return null;

        return {
            answers: {
                [ answer.header ]: answer.value
            }
        };
    }

    /**
     * Formats a multiple-choice response JSON into human-readable text.
     *
     * Requires:
     *   - responseJson is a JSON string or object with {answers: {...}} structure
     *
     * Ensures:
     *   - Returns formatted string like "Option1, Option2" for multi-select
     *   - Returns single value for single-select
     *   - Returns raw input if parsing fails
     */
    formatMultipleChoiceResponse( responseJson ) {
        try {
            const parsed = typeof responseJson === 'string' ? JSON.parse( responseJson ) : responseJson;
            const answers = parsed.answers || {};

            const parts = [];
            for ( const [ header, value ] of Object.entries( answers ) ) {
                if ( Array.isArray( value ) ) {
                    parts.push( value.join( ', ' ) );
                } else {
                    parts.push( value );
                }
            }
            return parts.join( ' • ' ) || responseJson;
        } catch ( e ) {
            return responseJson;  // Return raw if parsing fails
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
            this.showConfirmation( notificationId, response, result.time_display, result.date_display );

            // Stop countdown
            this.stopCountdownTimer( notificationId );

            // Clear active multiple-choice notification if this was it
            if ( this.activeMultipleChoiceNotificationId === notificationId ) {
                this.activeMultipleChoiceNotificationId = null;
            }

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

    showConfirmation( notificationId, response, serverTimeDisplay = null, serverDateDisplay = null ) {
        const card = document.getElementById( `action-required-${notificationId}` );
        if ( !card ) return;

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        // Get sender ID from notification
        const senderId = state.notification?.sender_id || this.UNKNOWN_SENDER;

        // Ensure sender card exists for the conversation
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        let senderCard = document.getElementById( cardId );
        if ( !senderCard ) {
            this.createSenderCard( senderId );
            senderCard = document.getElementById( cardId );
        }

        // Simple shrink-fade animation in place (no flying)
        card.classList.add( 'shrink-fade' );

        // On animation complete: remove card, add conversation pair with highlight
        card.addEventListener( 'animationend', () => {
            // Remove the action-required card from DOM
            card.remove();

            // Add conversation pair to sender card (with pulsing highlight)
            this.addConversationPair( senderId, state.notification, response, false, serverTimeDisplay, serverDateDisplay );

            // Cleanup action-required state
            this.actionRequiredNotifications.delete( notificationId );
            this.updateActionRequiredCount();
            this.saveActionRequiredState();  // Persist removal

            // Scroll sender card into view
            if ( senderCard ) {
                senderCard.scrollIntoView( { behavior: 'smooth', block: 'start' } );
            }

            // QUEUE SYSTEM: Promote next pending notification
            if ( this.activeActionRequiredId === notificationId ) {
                this.activeActionRequiredId = null;
                // Small delay to let UI settle before promoting next
                setTimeout( () => this.activateNextNotification(), 100 );
            }

            // TTS FOCUS MODE: Exit if this notification triggered focus mode
            if ( this.focusModeNotificationId === notificationId ) {
                this.exitTTSFocusMode();
            }
        }, { once: true } );

        // Fallback in case animationend doesn't fire (shouldn't happen, but safety net)
        setTimeout( () => {
            if ( card.parentElement ) {
                card.remove();
                this.addConversationPair( senderId, state.notification, response, false, serverTimeDisplay, serverDateDisplay );
                this.actionRequiredNotifications.delete( notificationId );
                this.updateActionRequiredCount();
                this.saveActionRequiredState();  // Persist removal

                // QUEUE SYSTEM: Promote next pending notification (fallback path)
                if ( this.activeActionRequiredId === notificationId ) {
                    this.activeActionRequiredId = null;
                    setTimeout( () => this.activateNextNotification(), 100 );
                }

                // TTS FOCUS MODE: Exit if this notification triggered focus mode (fallback path)
                if ( this.focusModeNotificationId === notificationId ) {
                    this.exitTTSFocusMode();
                }
            }
        }, 600 );

        // Early return - we've handled the animation
        return;

        // Fallback code below only runs if we somehow get past the return (shouldn't happen)
        if ( false ) {
            // Fallback: no animation, just show responded state
            this.log( 'No destination found, using fallback display' );

            card.classList.remove( 'active' );
            card.classList.add( 'responded' );

            const progress = document.getElementById( `progress-${notificationId}` );
            const timer = document.getElementById( `timer-${notificationId}` );
            if ( progress && progress.parentElement ) progress.parentElement.remove();
            if ( timer ) timer.textContent = '✓ Responded';

            const buttonsContainer = card.querySelector( '.response-buttons, .response-open-ended' );
            if ( buttonsContainer ) {
                buttonsContainer.innerHTML = `
                    <div class="notification-status-badge responded">
                        ✓ You responded: ${response}
                    </div>
                `;
            }
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
        this.saveActionRequiredState();  // Persist removal

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

        // Determine the default value used
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

        // Get sender ID from notification
        const senderId = state.notification?.sender_id || this.UNKNOWN_SENDER;

        // Calculate destination for animation
        const destination = this.calculateDestination( senderId );

        if ( destination ) {
            // Start genie animation for expired notification
            this.startGenieAnimation( notificationId, card, destination, () => {
                // On animation complete: add conversation pair (marked as expired)
                // Use client-generated time/date since there's no server call for timeout
                this.addConversationPair( senderId, state.notification, defaultValue, true, this.getLocalTimeDisplay(), this.getLocalDateDisplay() );

                // Cleanup action-required state
                this.actionRequiredNotifications.delete( notificationId );
                this.updateActionRequiredCount();
                this.saveActionRequiredState();  // Persist removal

                // Scroll sender card into view after DOM changes (moveSenderCardToTop shifts layout)
                const senderCard = document.getElementById( destination.cardId );
                if ( senderCard ) {
                    senderCard.scrollIntoView( { behavior: 'smooth', block: 'start' } );
                }

                // QUEUE SYSTEM: Promote next pending notification
                if ( this.activeActionRequiredId === notificationId ) {
                    this.activeActionRequiredId = null;
                    setTimeout( () => this.activateNextNotification(), 100 );
                }

                // TTS FOCUS MODE: Exit if this notification triggered focus mode
                if ( this.focusModeNotificationId === notificationId ) {
                    this.exitTTSFocusMode();
                }
            } );
        } else {
            // Fallback: no animation, just show expired state in place
            this.log( 'No destination found, using fallback display for expired' );

            card.classList.remove( 'active' );
            card.classList.add( 'expired' );

            const progress = document.getElementById( `progress-${notificationId}` );
            const timer = document.getElementById( `timer-${notificationId}` );
            if ( progress && progress.parentElement ) progress.parentElement.remove();
            if ( timer ) timer.textContent = '⏰ Expired';

            const buttonsContainer = card.querySelector( '.response-buttons, .response-open-ended' );
            if ( buttonsContainer ) {
                buttonsContainer.innerHTML = `
                    <div class="notification-status-badge expired">
                        ⏰ Expired - Default used: ${defaultValue}
                    </div>
                `;
            }

            // Cleanup and promote (fallback path)
            this.actionRequiredNotifications.delete( notificationId );
            this.updateActionRequiredCount();
            this.saveActionRequiredState();

            // QUEUE SYSTEM: Promote next pending notification (fallback path)
            if ( this.activeActionRequiredId === notificationId ) {
                this.activeActionRequiredId = null;
                setTimeout( () => this.activateNextNotification(), 100 );
            }

            // TTS FOCUS MODE: Exit if this notification triggered focus mode (fallback path)
            if ( this.focusModeNotificationId === notificationId ) {
                this.exitTTSFocusMode();
            }
        }
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
        // Note: We inherit timestamp from original notification so response appears
        // in the same date card as the question (keeps conversation together)
        if ( state.notification ) {
            const responseNotification = {
                ...state.notification,
                message       : `Response: ${response}`,
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

            // Cleanup after a short delay to let user see the "responded" state
            setTimeout( () => {
                card.remove();

                // Cleanup action-required state
                this.actionRequiredNotifications.delete( notificationId );
                this.updateActionRequiredCount();
                this.saveActionRequiredState();

                // QUEUE SYSTEM: Promote next pending notification
                if ( this.activeActionRequiredId === notificationId ) {
                    this.activeActionRequiredId = null;
                    this.activateNextNotification();
                }

                // TTS FOCUS MODE: Exit if this notification triggered focus mode
                if ( this.focusModeNotificationId === notificationId ) {
                    this.exitTTSFocusMode();
                }
            }, 1500 );  // 1.5 second delay to show "responded in another session"
        } else {
            // Card not found (might be minimized or already removed)
            // Still cleanup state and promote next
            this.actionRequiredNotifications.delete( notificationId );
            this.updateActionRequiredCount();
            this.saveActionRequiredState();

            // Remove from queue if it was pending
            this.actionRequiredQueue = this.actionRequiredQueue.filter( id => id !== notificationId );
            this.recalculateQueuePositions();

            // Remove minimized card if exists
            const minimized = document.getElementById( `action-required-minimized-${notificationId}` );
            if ( minimized ) {
                minimized.remove();
            }

            // QUEUE SYSTEM: Promote next if this was the active one
            if ( this.activeActionRequiredId === notificationId ) {
                this.activeActionRequiredId = null;
                this.activateNextNotification();
            }

            // TTS FOCUS MODE: Exit if this notification triggered focus mode
            if ( this.focusModeNotificationId === notificationId ) {
                this.exitTTSFocusMode();
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

    /**
     * Handle active_conversation_changed WebSocket event.
     * Updates the active indicator on sender cards.
     * (Conversation Identity Phase 3)
     *
     * @param {Object} data - { active_sender_id, timestamp }
     */
    handleActiveConversationChanged( data ) {
        const activeSenderId = data.active_sender_id;
        this.log( `Active conversation changed to: ${activeSenderId}` );

        // Update all sender groups
        for ( const [ senderId, group ] of this.senderGroups ) {
            const wasActive = group.isActive;
            group.isActive = ( senderId === activeSenderId );

            // Update UI if state changed
            if ( wasActive !== group.isActive ) {
                this.updateSenderActiveIndicator( senderId, group.isActive );
            }
        }
    }

    /**
     * Update the active indicator on a sender card.
     * (Conversation Identity Phase 3)
     *
     * @param {string} senderId - Sender ID
     * @param {boolean} isActive - Whether this sender is now active
     */
    updateSenderActiveIndicator( senderId, isActive ) {
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );
        if ( !card ) return;

        const indicator = card.querySelector( '.sender-active-indicator' );
        if ( indicator ) {
            indicator.textContent = isActive ? '●' : '○';
            indicator.title = isActive ? 'Active session' : 'Inactive session';
        }

        // Add/remove CSS class for styling
        if ( isActive ) {
            card.classList.add( 'sender-card-active' );
        } else {
            card.classList.remove( 'sender-card-active' );
        }

        this.log( `Updated active indicator for ${senderId}: ${isActive ? 'active' : 'inactive'}` );
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

    // ========================================
    // GENIE ANIMATION METHODS
    // ========================================

    /**
     * Calculate destination position for genie fly animation.
     * @param {string} senderId - Sender ID to fly to
     * @returns {object} - { x, y, cardId, isCollapsed } or null if can't find
     */
    calculateDestination( senderId ) {
        // Ensure sender ID is valid
        if ( !senderId ) {
            senderId = this.UNKNOWN_SENDER;
        }

        // Find or create the sender card
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        let senderCard = document.getElementById( cardId );

        // If sender card doesn't exist, create it
        if ( !senderCard ) {
            this.log( `Creating sender card for animation destination: ${senderId}` );
            // Initialize sender group if needed
            if ( !this.senderGroups.has( senderId ) ) {
                this.senderGroups.set( senderId, {
                    dateGroups   : new Map(),
                    collapsed    : false,
                    lastActivity : new Date(),
                    totalCount   : 0,
                    newCount     : 0
                } );
            }
            this.createSenderCard( senderId );
            senderCard = document.getElementById( cardId );
        }

        if ( !senderCard ) {
            this.error( `Failed to create sender card: ${cardId}` );
            return null;
        }

        // Get the header element for positioning
        const header = senderCard.querySelector( '.sender-card-header' );
        if ( !header ) {
            this.error( `Sender card header not found: ${cardId}` );
            return null;
        }

        const rect = header.getBoundingClientRect();
        const group = this.senderGroups.get( senderId );

        return {
            x          : rect.left + ( rect.width / 2 ),
            y          : rect.top + ( rect.height / 2 ),
            cardId     : cardId,
            isCollapsed: group?.collapsed || false,
            senderId   : senderId
        };
    }

    /**
     * Ensure a date accordion exists for the given sender and date.
     * Creates sender card and date accordion if needed.
     * @param {string} senderId - Sender ID
     * @param {string} dateString - ISO date string (YYYY-MM-DD)
     * @returns {boolean} - True if accordion exists or was created
     */
    ensureDateAccordionExists( senderId, dateString ) {
        // Ensure sender group exists
        if ( !this.senderGroups.has( senderId ) ) {
            this.senderGroups.set( senderId, {
                dateGroups   : new Map(),
                collapsed    : false,
                lastActivity : new Date(),
                totalCount   : 0,
                newCount     : 0
            } );
        }

        const group = this.senderGroups.get( senderId );

        // Ensure sender card exists
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        if ( !document.getElementById( cardId ) ) {
            this.createSenderCard( senderId );
        }

        // Ensure date group exists in data structure
        if ( !group.dateGroups.has( dateString ) ) {
            group.dateGroups.set( dateString, [] );
        }

        // Ensure date accordion exists in DOM
        const accordionId = `date-accordion-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        if ( !document.getElementById( accordionId ) ) {
            this.createDateAccordion( senderId, dateString );
        }

        return true;
    }

    /**
     * Expand a sender card if it's collapsed.
     * @param {string} senderId - Sender ID
     */
    expandSenderCard( senderId ) {
        const group = this.senderGroups.get( senderId );
        if ( !group || !group.collapsed ) return;

        // Toggle to expand
        this.toggleSenderCard( senderId );
        this.log( `Auto-expanded sender card for ${senderId}` );
    }

    /**
     * Expand all accordions containing a notification to make it visible.
     * Used when TTS playback starts so user can see the pulsing border.
     * @param {string} notificationId - Notification element ID
     */
    expandAccordionsForNotification( notificationId ) {
        const notificationElement = document.getElementById( notificationId );
        if ( !notificationElement ) return;

        // Find containing sender card via DOM traversal
        const senderCard = notificationElement.closest( '.sender-card' );
        if ( !senderCard ) return;

        // Find containing date accordion
        const dateAccordion = notificationElement.closest( '.date-accordion' );

        // Extract senderId by matching against senderGroups
        const cardId = senderCard.id; // "sender-card-{ESCAPED_SENDER_ID}"
        let foundSenderId = null;

        for ( const senderId of this.senderGroups.keys() ) {
            const testCardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
            if ( testCardId === cardId ) {
                foundSenderId = senderId;
                break;
            }
        }

        if ( !foundSenderId ) {
            this.log( `Could not find senderId for card: ${cardId}` );
            return;
        }

        // Expand sender card if collapsed
        this.expandSenderCard( foundSenderId );

        // Extract dateString from accordion ID and expand date accordion
        if ( dateAccordion ) {
            // ID format: "date-accordion-{ESCAPED_SENDER_ID}-{DATE_STRING}"
            const accordionId = dateAccordion.id;
            const escapedSenderId = foundSenderId.replace( /[@.#]/g, '-' );
            const prefix = `date-accordion-${escapedSenderId}-`;
            if ( accordionId.startsWith( prefix ) ) {
                const dateString = accordionId.substring( prefix.length );
                this.expandDateAccordion( foundSenderId, dateString );
            }
        }

        // Scroll notification into view
        this.scrollIntoViewIfNeeded( notificationElement );
    }

    /**
     * Scroll an element into view if it's not visible.
     * @param {HTMLElement} element - Element to scroll into view
     * @returns {Promise} - Resolves when scroll is complete
     */
    scrollIntoViewIfNeeded( element ) {
        return new Promise( ( resolve ) => {
            if ( !element ) {
                resolve();
                return;
            }

            const rect = element.getBoundingClientRect();
            const isVisible = (
                rect.top >= 0 &&
                rect.bottom <= window.innerHeight
            );

            if ( !isVisible ) {
                // Scroll to top of element - new messages appear at top of sender card
                element.scrollIntoView( { behavior: 'smooth', block: 'start' } );
                // Wait for scroll to complete (approximate)
                setTimeout( resolve, 300 );
            } else {
                resolve();
            }
        } );
    }

    /**
     * Get today's date string in YYYY-MM-DD format.
     * @returns {string} - ISO date string
     */
    getTodayDateString() {
        const now = new Date();
        return now.toISOString().split( 'T' )[ 0 ];
    }

    /**
     * Start the genie fly-to-destination animation.
     * @param {string} notificationId - The notification ID being animated
     * @param {HTMLElement} element - The action-required card element to animate
     * @param {object} destination - Destination position from calculateDestination()
     * @param {function} onComplete - Callback when animation completes
     */
    async startGenieAnimation( notificationId, element, destination, onComplete ) {
        if ( !element || !destination ) {
            this.error( 'startGenieAnimation: Missing element or destination' );
            if ( onComplete ) onComplete();
            return;
        }

        this.log( `Starting genie animation for ${notificationId}` );

        // Track this animation
        this.activeAnimations.set( notificationId, {
            element     : element,
            destination : destination,
            startTime   : Date.now()
        } );

        try {
            // Step 1: Auto-expand collapsed sender card (scroll happens after animation callback)
            if ( destination.isCollapsed ) {
                this.expandSenderCard( destination.senderId );
                // Small delay to let expansion animation complete
                await new Promise( r => setTimeout( r, 100 ) );
            }

            // Step 3: Get current position of the element
            const sourceRect = element.getBoundingClientRect();
            const sourceX = sourceRect.left + ( sourceRect.width / 2 );
            const sourceY = sourceRect.top + ( sourceRect.height / 2 );

            // Recalculate destination after potential scroll/expansion
            const updatedDest = this.calculateDestination( destination.senderId );
            const endX = updatedDest ? updatedDest.x : destination.x;
            const endY = updatedDest ? updatedDest.y : destination.y;

            // Step 4: Calculate bezier curve control point (arc upward)
            const controlX = ( sourceX + endX ) / 2;
            const controlY = Math.min( sourceY, endY ) - 100;  // Arc 100px above midpoint

            // Step 5: Fix element position for animation
            const width = element.offsetWidth;
            const height = element.offsetHeight;

            element.style.width = `${width}px`;
            element.style.height = `${height}px`;
            element.style.left = `${sourceRect.left}px`;
            element.style.top = `${sourceRect.top}px`;
            element.classList.add( 'flying' );

            // Step 6: Animate using Web Animations API with bezier curve approximation
            // We'll use multiple keyframes to approximate a quadratic bezier curve
            const keyframes = this.generateBezierKeyframes(
                sourceX, sourceY,
                controlX, controlY,
                endX, endY,
                width, height
            );

            const animation = element.animate( keyframes, {
                duration : this.ANIMATION_DURATION_MS,
                easing   : this.ANIMATION_EASING,
                fill     : 'forwards'
            } );

            // Step 7: Wait for animation to complete with fallback timeout
            const fallbackTimeout = this.ANIMATION_DURATION_MS + 200;  // Extra 200ms buffer
            await Promise.race( [
                animation.finished,
                new Promise( resolve => setTimeout( resolve, fallbackTimeout ) )
            ] );

            this.log( `Genie animation completed for ${notificationId}` );

        } catch ( error ) {
            this.error( `Genie animation error: ${error.message}` );
        } finally {
            // Cleanup
            this.activeAnimations.delete( notificationId );

            // Remove from DOM (it will be added to sender card as conversation)
            if ( element.parentNode ) {
                element.remove();
            }

            // Call completion callback
            if ( onComplete ) {
                onComplete();
            }
        }
    }

    /**
     * Generate keyframes for a quadratic bezier curve animation.
     * Approximates the curve with multiple intermediate points.
     * @param {number} x0 - Start X
     * @param {number} y0 - Start Y
     * @param {number} x1 - Control point X
     * @param {number} y1 - Control point Y
     * @param {number} x2 - End X
     * @param {number} y2 - End Y
     * @param {number} width - Element width
     * @param {number} height - Element height
     * @returns {array} - Keyframes array for Web Animations API
     */
    generateBezierKeyframes( x0, y0, x1, y1, x2, y2, width, height ) {
        const keyframes = [];
        const steps = 10;  // Number of intermediate points

        for ( let i = 0; i <= steps; i++ ) {
            const t = i / steps;

            // Quadratic bezier formula: B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2
            const oneMinusT = 1 - t;
            const x = oneMinusT * oneMinusT * x0 + 2 * oneMinusT * t * x1 + t * t * x2;
            const y = oneMinusT * oneMinusT * y0 + 2 * oneMinusT * t * y1 + t * t * y2;

            // Calculate offset from starting position (element is positioned at start)
            const offsetX = x - x0;
            const offsetY = y - y0;

            // Scale decreases from 1 to 0.5 along the path (50% end size)
            const scale = 1 - ( t * 0.5 );

            // Opacity decreases from 1 to 0.5 along the path (50% visible at end for debugging)
            const opacity = 1 - ( t * 0.5 );

            // Rotation increases slightly for genie effect
            const rotation = t * 15;

            keyframes.push( {
                transform: `translate( ${offsetX}px, ${offsetY}px ) scale( ${scale} ) perspective( 500px ) rotateX( ${rotation}deg )`,
                opacity  : opacity,
                offset   : t
            } );
        }

        return keyframes;
    }

    /**
     * Add a conversation pair (notification + response) to the sender card.
     * @param {string} senderId - Sender ID
     * @param {object} notification - Original notification data
     * @param {string} response - User's response text
     * @param {boolean} wasExpired - True if notification expired (used default)
     * @param {string} serverTimeDisplay - Optional server-provided formatted time (e.g., "16:26 EST")
     * @param {string} serverDateDisplay - Optional server-provided formatted date (e.g., "2026-01-08")
     */
    addConversationPair( senderId, notification, response, wasExpired = false, serverTimeDisplay = null, serverDateDisplay = null ) {
        // Use server-provided date (source of truth) or fall back to extracting from notification
        const dateString = serverDateDisplay || this.extractDateFromTimestamp( notification.timestamp );

        // Ensure sender card and date accordion exist
        this.ensureDateAccordionExists( senderId, dateString );

        // Get the group and add to data structure
        const group = this.senderGroups.get( senderId );
        if ( !group ) {
            this.error( `Sender group not found: ${senderId}` );
            return;
        }

        // 1. Add original notification (incoming/left-aligned)
        const incomingNotification = {
            ...notification,
            timestamp: notification.timestamp || new Date().toISOString(),
            state    : 'delivered'
        };

        // Add to data structure
        const dateGroup = group.dateGroups.get( dateString );
        if ( dateGroup ) {
            dateGroup.unshift( incomingNotification );
            group.totalCount++;
        }

        // Add to UI
        this.addMessageToDateAccordion( senderId, dateString, incomingNotification, false );

        // 2. Add user response (outgoing/right-aligned)
        let responseMessage;
        if ( wasExpired ) {
            responseMessage = `[Default: ${response}]`;
        } else if ( notification.response_type === 'multiple_choice' ) {
            responseMessage = this.formatMultipleChoiceResponse( response );
        } else {
            responseMessage = response;
        }

        const outgoingNotification = {
            id           : `${notification.id || 'unknown'}-response`,
            sender_id    : senderId,
            message      : responseMessage,
            timestamp    : new Date().toISOString(),
            time_display : serverTimeDisplay || notification.time_display,
            state        : 'responded',
            was_expired  : wasExpired
        };

        // Add to data structure
        if ( dateGroup ) {
            dateGroup.unshift( outgoingNotification );
            group.totalCount++;
        }

        // Add to UI with animated-in class
        this.addMessageToDateAccordion( senderId, dateString, outgoingNotification, true );

        // Mark new messages with animation class
        const containerId = `date-messages-${senderId.replace( /[@.#]/g, '-' )}-${dateString}`;
        const container = document.getElementById( containerId );
        if ( container ) {
            const messages = container.querySelectorAll( '.sender-message' );
            // Add animation to the two newest messages
            if ( messages.length >= 1 ) messages[ 0 ].classList.add( 'animated-in' );
            if ( messages.length >= 2 ) messages[ 1 ].classList.add( 'animated-in' );

            // Add pulsing highlight to the response (first message = most recent)
            // This draws attention to where the response now "lives" in the conversation
            if ( messages.length >= 1 ) {
                messages[ 0 ].classList.add( 'response-highlight' );
                // Remove highlight class after animation completes (3 pulses * 0.6s = 1.8s)
                setTimeout( () => {
                    messages[ 0 ].classList.remove( 'response-highlight' );
                }, 1800 );
            }
        }

        // Update sender card header
        this.updateSenderCardHeader( senderId );
        this.updateTotalNotificationsCount();

        // Move sender card to top (most recent activity)
        this.moveSenderCardToTop( senderId );

        this.log( `Added conversation pair for ${senderId}: "${notification.message?.substring( 0, 30 )}..." → "${response}"` );
    }

    /**
     * Move a sender card to the top of the notifications list.
     * @param {string} senderId - Sender ID
     */
    moveSenderCardToTop( senderId ) {
        const container = document.getElementById( 'notifications-list' );
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );

        if ( container && card && container.firstChild !== card ) {
            container.insertBefore( card, container.firstChild );
        }
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

    /**
     * Starts voice input for an open-ended notification response.
     * Now uses unified RecordingManager.
     */
    async startVoiceInput( notificationId ) {
        this.log( `Starting voice input for ${notificationId}` );

        const micButton = document.querySelector( `[data-notification-id="${notificationId}"].response-mic-button` );
        const textInput = document.getElementById( `response-input-${notificationId}` );

        if ( !micButton || !textInput ) {
            this.error( `Voice input: Could not find UI elements for ${notificationId}` );
            return;
        }

        // Toggle recording state using unified RecordingManager
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
        } else if ( !this.recordingManager.isProcessing() ) {
            await this.recordingManager.startRecording( `response-${notificationId}`, micButton, textInput );
        }
    }

    /**
     * Starts voice input for the "Other" field in a multiple-choice notification.
     * Now uses unified RecordingManager with auto-select and validation options.
     */
    async startMultipleChoiceVoiceInput( notificationId ) {
        this.log( `Starting voice input for multiple choice Other field: ${notificationId}` );

        const card = document.getElementById( `action-required-${notificationId}` );
        const micButton = card?.querySelector( '.mc-other-mic' );
        const textInput = card?.querySelector( '.mc-other-input' );
        const otherRadio = card?.querySelector( '.mc-other-radio' );

        if ( !micButton || !textInput ) {
            this.error( `Voice input: Could not find Other field UI elements for ${notificationId}` );
            return;
        }

        // Toggle recording state using unified RecordingManager
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
        } else if ( !this.recordingManager.isProcessing() ) {
            await this.recordingManager.startRecording( `mc-${notificationId}`, micButton, textInput, {
                autoSelectElement: otherRadio,
                onTranscriptionComplete: () => {
                    // Clear invalid state on successful transcription
                    const container = card?.querySelector( '.response-multiple-choice' );
                    if ( container ) container.classList.remove( 'invalid' );
                }
            } );
        }
    }

    // NOTE: The following deprecated helper methods have been removed and consolidated
    // into the RecordingManager (initialized in initRecordingManager):
    // - _startDurationCounter, _stopDurationCounter
    // - _attachRecordingCancelListener, _detachRecordingCancelListener
    // - _cancelRecording
    // - this.audioRecorder, this.audioRecording, this._recordingCancelListener

    // ========================================
    // AGENT MODE MANAGEMENT
    // ========================================

    /**
     * Set the agent mode for the current user.
     * Mode determines whether questions bypass the LLM router.
     *
     * Args:
     *     mode: String mode name (e.g., 'math', 'calendar') or null for system mode
     *
     * Returns:
     *     Boolean indicating success
     */
    async setAgentMode( mode ) {
        if ( !this.currentUser ) {
            this.error( "Cannot set mode: No user logged in" );
            return false;
        }

        try {
            await this.ensureValidToken();

            // Use /current endpoint - server extracts user from auth token
            const response = await fetch( `/api/mode/current`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader()
                },
                body: JSON.stringify( { mode: mode } )
            } );

            if ( !response.ok ) {
                const errorData = await response.json();
                this.error( `Failed to set mode: ${errorData.detail || response.statusText}` );
                return false;
            }

            const data = await response.json();
            this.log( `Mode changed: ${data.message}` );

            // Update UI elements
            this.updateModeUI( data.mode, data.display_name );

            return true;

        } catch ( e ) {
            this.error( `Error setting mode: ${e.message}` );
            return false;
        }
    }

    /**
     * Get the current agent mode for the user.
     *
     * Returns:
     *     Object with mode info or null on error
     */
    async getAgentMode() {
        if ( !this.currentUser ) {
            this.error( "Cannot get mode: No user logged in" );
            return null;
        }

        try {
            await this.ensureValidToken();

            // Use /current endpoint - server extracts user from auth token
            const response = await fetch( `/api/mode/current`, {
                method: 'GET',
                headers: {
                    'Authorization': this.getAuthHeader()
                }
            } );

            if ( !response.ok ) {
                this.error( `Failed to get mode: ${response.statusText}` );
                return null;
            }

            const data = await response.json();
            return data;

        } catch ( e ) {
            this.error( `Error getting mode: ${e.message}` );
            return null;
        }
    }

    /**
     * Update the mode selector UI to reflect current mode.
     *
     * Args:
     *     mode: String mode name or null for system mode
     *     displayName: Human-readable mode name
     */
    updateModeUI( mode, displayName ) {
        const agentModeSelect = document.getElementById( 'agent-mode' );
        const modeBadge = document.getElementById( 'mode-badge' );
        const modeStatus = document.getElementById( 'mode-status' );

        // Update dropdown selection
        if ( agentModeSelect ) {
            agentModeSelect.value = mode || 'system';
        }

        // Update badge visibility and content
        if ( modeBadge ) {
            if ( mode && mode !== 'system' ) {
                modeBadge.textContent = displayName;
                modeBadge.style.display = 'inline-block';
            } else {
                modeBadge.style.display = 'none';
            }
        }

        // Update status text
        if ( modeStatus ) {
            if ( mode && mode !== 'system' ) {
                modeStatus.textContent = `Direct routing to ${displayName}`;
                modeStatus.style.color = '#0d6efd';
            } else {
                modeStatus.textContent = 'Auto-routing enabled';
                modeStatus.style.color = '#6c757d';
            }
        }
    }

    /**
     * Load current mode from server on page load.
     * Called after authentication is complete.
     */
    async loadCurrentMode() {
        const modeData = await this.getAgentMode();
        if ( modeData ) {
            this.updateModeUI( modeData.mode, modeData.display_name );
        }
    }
}

// ========================================
// INITIALIZATION
// ========================================

// Initialize when DOM is ready
if ( document.readyState === 'loading' ) {
    document.addEventListener( 'DOMContentLoaded', () => {
        window.notificationsUI = new NotificationsUI();
    });
} else {
    window.notificationsUI = new NotificationsUI();
}

// Make available globally for debugging
window.NotificationsUI = NotificationsUI;