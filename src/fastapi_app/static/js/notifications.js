/**
 * Notifications UI - Unified JavaScript Module
 * Single-file implementation to replace complex multi-file architecture
 * Handles WebSocket connections, authentication, Q&A, and TTS functionality
 */

// Test types that take a file path as the first positional pytest arg.
// Keep this in sync with FILE_DRIVEN_TEST_TYPES in cosa/agents/test_suite/job.py —
// a test type belongs here iff its shell script delegates to "$@" (i.e., accepts
// the file path as the first arg rather than fanning out to a fixed suite).
// Also mirrored in notifications.html inline <script> as FILE_DRIVEN_TEST_TYPES_HTML.
const FILE_DRIVEN_TEST_TYPES = new Set( [ 'smoke_direct', 'pytest_direct' ] );

// Delete-handler routing for job cards. Replaces the prior `_isHistory` boolean
// flag pattern with a queueName-keyed lookup table — single chokepoint, easy to
// extend, no string-template branching in the renderer.
// See src/rnd/v0.1.7/2026.04.26-cj-flow-card-rendering-unification/04-frontend-flag-removal.md
const DELETE_HANDLERS = {
    todo    : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    run     : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    done    : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    dead    : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    history : ( jobId )            => window.notificationsUI.deleteHistoryJob( jobId )
};

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
        this.currentUserEmail = null;
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
        this.queueWsConnected = false;
        this.audioWsConnected = false;
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

        // Per-session voice persona map: sender_id → { name, voice_id, icon, color, borrowed }
        // Hydrated from notification.voice_persona as notifications arrive.
        // Used by playTTS to pass voice_id so each session speaks with its own voice.
        // See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
        this.senderPersonaMap = new Map();
        
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
        this.RESUME_MODEL_PREF_KEY  = 'notifications_resume_model';   // Default model for stalled-job resume (TFE/BFE)
        this.RESUME_EFFORT_PREF_KEY = 'notifications_resume_effort';  // Default thinking-effort for stalled-job resume
        this.CONVERSATION_MODES_KEY = 'notifications_conversation_modes';  // Per-session conversation/notification toggle (object keyed by session_id)
        this.CC_FOCUS_STATE_KEY     = 'notifications_cc_focus_state';      // CC session focus mode: { enabled, focused_sender_id }
        this.CURRENT_VERSION = '2.0.0'; // Increment to invalidate old cache - date grouping release

        // Session names cache (loaded from localStorage)
        this.sessionNames = JSON.parse( localStorage.getItem( this.SESSION_NAMES_KEY ) ) || {};

        // Conversation mode cache (per-session: { [sessionId]: bool }). Read-through cache for instant
        // render — server-canonical state lives in the cosa-voice bridge file and arrives via the
        // conversation_mode_changed WebSocket event.
        this.conversationModes = JSON.parse( localStorage.getItem( this.CONVERSATION_MODES_KEY ) ) || {};

        // CC focus mode state (client-only, per-browser). Persists across reload via localStorage.
        // Design: src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md
        this.ccFocusState = JSON.parse( localStorage.getItem( this.CC_FOCUS_STATE_KEY ) )
                            || { enabled: false, focused_sender_id: null };
        // Per-sender unread counter for the strip's peripheral-awareness badge while focus is on.
        this.ccStripUnreadCounts = {};
        // Wire the strip toggle pill once. The button lives in notifications.html and
        // is hidden alongside the strip until the first CC sender card arrives.
        this._bindStripToggle();
        // If focus mode was on at last save, restore the toggle pill's visual state
        // immediately. Card-level data-focus-hidden is applied per-card by
        // createSenderCard as the cards are hydrated.
        if ( this.ccFocusState.enabled ) {
            const toggle = document.getElementById( "cc-strip-toggle" );
            if ( toggle ) {
                toggle.setAttribute( "data-focus-active", "true" );
                toggle.textContent = "👁 Focus: ON";
            }
        }

        // User role and filter state
        this.userRoles = [];  // NEW: User's roles from JWT
        this.isAdmin = false;  // NEW: Quick admin check
        this.queueFilterMode = 'own';  // NEW: 'own' or 'all' (admin only)

        // ========================================
        // PROGRESSIVE DISCLOSURE QUEUE UI STATE
        // ========================================
        // State management for expandable queue categories and job cards
        this.queueCategoryState = {
            todo    : { expanded: false, loaded: false, jobs: [] },
            run     : { expanded: false, loaded: false, jobs: [] },
            done    : { expanded: false, loaded: false, jobs: [] },
            dead    : { expanded: false, loaded: false, jobs: [] },
            history : { expanded: false, loaded: false, jobs: [], offset: 0, total: 0, timeWindow: 30 }
        };
        this.queueCounts = { todo: 0, run: 0, done: 0, dead: 0 };
        this.expandedJobCards = new Set();         // Track which job cards are expanded
        this.jobInteractionsCache = new Map();     // Cache loaded interactions: job_id → interactions[]

        // ========================================
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
        this.isPaused = false;                   // True when active notification is paused (timer frozen)

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
        this.focusModeTimeoutId = null;          // Safety timeout handle for focus mode
        this.focusModeEnteredAt = null;          // Timestamp when focus mode entered
        this.focusModeTimeoutMs = null;          // Duration of safety timeout (for restore)
        this.focusModeElapsedBeforePause = null; // Elapsed ms before pause (for resume calc)
        this.TTS_FOCUS_MODE_BUFFER_MS = 30000;   // 30s buffer beyond notification timeout
        this.TTS_FOCUS_MODE_FALLBACK_MS = 150000; // 150s fallback if timeout_seconds unknown

        // Manual Pause: User-controlled pause of TTS playback (via pause button)
        this.isTTSPaused = false;                // True when user clicks pause button

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
        const storedWindow = localStorage.getItem( this.HISTORY_WINDOW_KEY );
        // Sentinel values:
        //   null    → "All time" (no hours filter)
        //   'today' → since the user's local-midnight (calendar day, NOT last 24h)
        //   number  → fixed-hours window
        // Handles 'all' sentinel AND legacy empty string (migration from pre-fix code).
        if ( storedWindow === 'all' || storedWindow === '' ) {
            this.historyWindowHours = null;
        } else if ( storedWindow === 'today' ) {
            this.historyWindowHours = 'today';
        } else {
            this.historyWindowHours = parseInt( storedWindow ) || 48; // Default to 2 days
        }
        this.WINDOW_OPTIONS = [
            { label: 'Today',         hours: 'today' },
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

        // ========================================
        // QUEUE CATEGORY EXPAND/COLLAPSE STATE
        // ========================================
        this.QUEUE_EXPAND_STATE_KEY = 'lupin_queue_expand_state';

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

            // Initialize abstract tooltip for notifications history
            this.initAbstractTooltip();

            // Initialize section visibility toolbar
            this.initToolbar();

            // Apply saved queue expand/collapse state
            this.applyQueueExpandState();

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

            // Load Time Saved Dashboard stats
            this.refreshTimeSavedStats();

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
            window.location.href = `/app/auth/login?redirect=${currentPath}`;
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
        this.currentUserEmail = payload.email;
        this.userRoles = payload.roles || [];  // Extract roles array
        this.isAdmin = this.userRoles.includes( 'admin' );  // Check admin status

        // Update UI
        this.updateElement( "user-display", this.currentUserEmail );
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

        this.log( `✓ Authentication setup complete for user: ${this.currentUserEmail} (admin: ${this.isAdmin}, config fetched, monitors started)` );

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
            const response = await this.authedFetch( '/api/config/client', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
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
                this.tfeAutoFixDefault = !!config.test_fix_expediter_auto_fix_enabled;
                this.envLabel = config.env_label || "DEVELOPMENT";
                this.updateElement( "env-label", `[${this.envLabel}]: ` );

                // Sync the test runner submission card's auto-fix checkbox to the
                // INI default. The user can still toggle it for any individual
                // submission — that override travels in the request body and
                // does NOT round-trip back to the INI.
                const autoFixCheckbox = document.getElementById( 'test-suite-auto-fix' );
                if ( autoFixCheckbox ) {
                    autoFixCheckbox.checked = this.tfeAutoFixDefault;
                }

                // Log configuration for debugging
                this.log( "✓ Client config loaded from server:", {
                    refresh_check_interval : `${config.token_refresh_check_interval_ms / 60000} mins`,
                    expiry_threshold       : `${config.token_expiry_threshold_secs / 60} mins`,
                    dedup_window           : `${config.token_refresh_dedup_window_ms / 1000} secs`,
                    heartbeat_interval     : `${config.websocket_heartbeat_interval_secs} secs`,
                    app_timezone           : config.app_timezone,
                    tfe_auto_fix_default   : this.tfeAutoFixDefault
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
            this.tfeAutoFixDefault = false;                         // Conservative fallback

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
            // Disconnection detected — reconnect only what's broken
            const target = ( queueNeedsReconnect && audioNeedsReconnect ) ? 'both'
                         : queueNeedsReconnect ? 'queue' : 'audio';
            this.wsDiag( `Health check: Disconnected WebSockets detected (queue=${queueNeedsReconnect}, audio=${audioNeedsReconnect}) → reconnecting ${target}` );
            this.updateHealthStatus( "Reconnecting...", "status-warning" );

            // Reset retry counter to give reconnection a fresh start from health monitor
            this.connectionRetries = 0;

            // Trigger targeted reconnection
            this.scheduleReconnect( target );
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

    async authedFetch( url, options = {} ) {
        /**
         * Authenticated fetch wrapper.
         *
         * Proactively refreshes the JWT access token (via ensureValidToken) before
         * firing the request, then injects the Authorization header. Use this for
         * every authenticated API call from notifications.js — it eliminates the
         * 401s that occur when a user is idle longer than the JWT TTL and the
         * browser still holds a stale token.
         *
         * Requires:
         *     - this.ensureValidToken() and this.getAuthHeader() are available
         *     - options is a plain object (or omitted)
         *
         * Ensures:
         *     - Token is refreshed if expired before the fetch fires
         *     - Authorization header is injected (caller headers take precedence
         *       if they also define Authorization)
         *     - All other fetch options (method, body, signal, etc.) pass through
         *     - Returns the Response object as-is — caller handles status checking
         *
         * Raises:
         *     - Whatever ensureValidToken() raises (auth failure after refresh)
         *     - Whatever fetch() raises (network failure)
         */
        await this.ensureValidToken();
        const headers = {
            'Authorization': this.getAuthHeader(),
            ...( options.headers || {} )
        };
        return fetch( url, { ...options, headers } );
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
        window.location.href = `/app/auth/login?redirect=${currentPath}`;
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

        // Redirect to login page
        window.location.href = '/app/auth/login';
    }

    async reinitializeConfig() {
        /**
         * Reinitialize Lupin configuration by calling /api/init endpoint.
         * Refreshes configuration and reloads solution snapshots without server restart.
         *
         * Requires:
         *     - Server is running and responsive
         *     - /api/init endpoint is available
         *
         * Ensures:
         *     - Calls /api/init endpoint
         *     - Updates config-status span with result
         *     - Logs success or failure
         */
        const statusSpan = document.getElementById( 'config-status' );
        const button = document.getElementById( 'reinit-config-btn' );

        try {
            // Disable button during request
            if ( button ) {
                button.disabled = true;
                button.style.opacity = '0.6';
            }
            // Clear any previous error message
            if ( statusSpan ) {
                statusSpan.textContent = '';
            }

            this.log( 'Reinitializing configuration...' );

            const response = await fetch( '/api/init' );
            const data = await response.json();

            if ( data.status === 'success' ) {
                this.log( `Config reinitialized: ${data.message}` );
                if ( statusSpan ) {
                    statusSpan.textContent = '✓';
                    statusSpan.style.color = '#28a745';
                }
            } else {
                this.error( `Config reinit failed: ${data.message}` );
                if ( statusSpan ) {
                    statusSpan.textContent = `✗ ${data.message}`;
                    statusSpan.style.color = '#dc3545';
                }
            }
        } catch ( error ) {
            this.error( 'Config reinit error:', error );
            if ( statusSpan ) {
                statusSpan.textContent = `✗ ${error.message || 'Network error'}`;
                statusSpan.style.color = '#dc3545';
            }
        } finally {
            // Re-enable button
            if ( button ) {
                button.disabled = false;
                button.style.opacity = '1';
            }
        }
    }

    async refreshAllStatus() {
        /**
         * Refresh all status information in the System Status section.
         * Triggered by clicking the refresh button in the section header.
         *
         * Requires:
         *     - WebSocket connections may or may not be active
         *     - Auth token may or may not be valid
         *
         * Ensures:
         *     - Button shows spinning animation during refresh
         *     - All status fields are updated with current state
         *     - Button re-enables after refresh completes
         */
        const button = document.getElementById( 'refresh-status-btn' );

        try {
            // Disable button and add spinning animation
            if ( button ) {
                button.disabled = true;
                button.classList.add( 'spinning' );
            }

            this.log( "Refreshing all status information..." );

            // Refresh each status category
            this.refreshWebSocketStatus();
            await this.refreshAuthStatus();
            this.refreshSessionDisplay();
            this.checkWebSocketHealth();

            this.log( "✓ Status refresh complete" );

        } catch ( error ) {
            this.error( "Status refresh error:", error );
        } finally {
            // Re-enable button and remove spinning animation
            if ( button ) {
                button.disabled = false;
                button.classList.remove( 'spinning' );
            }
        }
    }

    refreshWebSocketStatus() {
        /**
         * Update WebSocket connection status displays.
         * Evaluates current readyState of both WebSocket connections.
         *
         * WebSocket readyState values:
         *     0 = CONNECTING, 1 = OPEN, 2 = CLOSING, 3 = CLOSED
         */
        const stateNames = [ 'Connecting', 'Connected', 'Closing', 'Disconnected' ];
        const stateTypes = [ 'warning', 'good', 'warning', 'error' ];

        // Queue WebSocket status
        if ( this.queueWS ) {
            const state = this.queueWS.readyState;
            this.updateStatus( 'queue-ws-status', stateNames[ state ], stateTypes[ state ] );
        } else {
            this.updateStatus( 'queue-ws-status', 'Not initialized', 'error' );
        }

        // Audio WebSocket status
        if ( this.audioWS ) {
            const state = this.audioWS.readyState;
            this.updateStatus( 'audio-ws-status', stateNames[ state ], stateTypes[ state ] );
        } else {
            this.updateStatus( 'audio-ws-status', 'Not initialized', 'error' );
        }
    }

    async refreshAuthStatus() {
        /**
         * Verify current authentication state and update display.
         * Checks token validity and triggers refresh if needed.
         *
         * Ensures:
         *     - Auth status element shows current authentication state
         *     - User display shows current user email
         *     - Triggers token refresh if access token is expired
         */
        const tokens = this.getStoredTokens();

        if ( !tokens.accessToken ) {
            this.updateStatus( 'auth-status', 'Not authenticated', 'warning' );
            this.updateElement( 'user-display', 'Not logged in' );
            return;
        }

        // Check if token is expired
        if ( this.isTokenExpired( tokens.accessToken ) ) {
            this.log( "Access token expired during status refresh - attempting refresh" );
            const refreshed = await this.refreshAccessToken();

            if ( !refreshed ) {
                this.updateStatus( 'auth-status', 'Token expired', 'error' );
                return;
            }
        }

        // Token is valid - extract user info
        const payload = this.parseJWTPayload( this.authToken || tokens.accessToken );
        const email = payload.email || 'Unknown';
        const roles = payload.roles || [];
        const isAdmin = roles.includes( 'admin' );

        this.updateElement( 'user-display', email );
        this.updateStatus( 'auth-status', `Authenticated${isAdmin ? ' (admin)' : ''}`, 'good' );
    }

    refreshSessionDisplay() {
        /**
         * Update session ID displays with current values.
         */
        this.updateElement( 'queue-session', this.queueSessionId || '-' );
        this.updateElement( 'audio-session', this.audioSessionId || '-' );
    }

    copyToClipboard( elementId ) {
        /**
         * Copy the text content of a session ID element to the clipboard.
         *
         * Requires:
         *     - elementId is the ID of an existing DOM element
         *
         * Ensures:
         *     - copies text to clipboard if value is not empty or '-'
         *     - shows brief checkmark feedback on the adjacent copy button
         */
        const el = document.getElementById( elementId );
        if ( !el ) return;

        const text = el.textContent.trim();
        if ( !text || text === '-' ) return;

        navigator.clipboard.writeText( text ).then( () => {
            // Brief visual feedback: swap icon to checkmark
            const btn = el.nextElementSibling;
            if ( btn ) {
                const original = btn.textContent;
                btn.textContent = '✅';
                setTimeout( () => { btn.textContent = original; }, 1200 );
            }
        } );
    }

    copySenderSessionId( btnElement ) {
        /**
         * Copy a sender session ID (without # prefix) to the clipboard.
         *
         * Requires:
         *     - btnElement is the 📋 span immediately after a .sender-session-id span
         *
         * Ensures:
         *     - copies hex session ID to clipboard (without # prefix)
         *     - shows brief checkmark feedback on the copy button
         */
        const idSpan = btnElement.previousElementSibling;
        if ( !idSpan ) return;
        const text = idSpan.textContent.trim().replace( /^#/, '' );
        if ( !text ) return;
        navigator.clipboard.writeText( text ).then( () => {
            const original = btnElement.textContent;
            btnElement.textContent = '✅';
            setTimeout( () => { btnElement.textContent = original; }, 1200 );
        } );
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
        const filterOwnBtn    = document.getElementById( 'filter-own-jobs' );
        const filterOthersBtn = document.getElementById( 'filter-others-jobs' );
        const filterAllBtn    = document.getElementById( 'filter-all-jobs' );

        if ( filterOwnBtn && filterAllBtn ) {
            filterOwnBtn.addEventListener( 'click', () => this.setFilterMode( 'own' ) );
            if ( filterOthersBtn ) {
                filterOthersBtn.addEventListener( 'click', () => this.setFilterMode( 'others' ) );
            }
            filterAllBtn.addEventListener( 'click', () => this.setFilterMode( 'all' ) );
            this.log( "Filter button event listeners added" );
        }

        // Filter mode badges in section headers (click to show + scroll to filter panel)
        const notifFilterBadge  = document.getElementById( 'notifications-filter-badge' );
        const queuesFilterBadge = document.getElementById( 'queues-filter-badge' );

        if ( notifFilterBadge ) {
            notifFilterBadge.addEventListener( 'click', ( e ) => {
                e.stopPropagation();  // Prevent section toggle
                this.showAndScrollToFilterPanel();
            } );
        }
        if ( queuesFilterBadge ) {
            queuesFilterBadge.addEventListener( 'click', ( e ) => {
                e.stopPropagation();  // Prevent section toggle
                this.showAndScrollToFilterPanel();
            } );
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

        // CC Session voice input (sender card delegation)
        this._setupCCSessionVoiceDelegation();

        // Job Submission (Research + Podcast) event listeners
        this.setupJobSubmitEventListeners();

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
        const taskTypeSelect = document.getElementById( 'cc-task-type' );
        if ( taskTypeSelect ) {
            taskTypeSelect.addEventListener( 'change', ( e ) => {
                const optionBControls = document.getElementById( 'cc-option-b-controls' );
                if ( optionBControls ) {
                    optionBControls.style.display = e.target.value === 'INTERACTIVE' ? 'block' : 'none';
                }
            });
        }

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

    // ========================================
    // CC SESSION VOICE INPUT (Phase 6)
    // ========================================

    _setupCCSessionVoiceDelegation() {
        /**
         * Setup event delegation for CC session voice input in sender cards.
         *
         * Sender cards for claude.code sessions include a voice input row
         * (STT button + text input + Send button). Since sender cards are
         * created dynamically, we use delegation on the notifications-list
         * container.
         *
         * Ensures:
         *     - STT button → handleSTTButtonClick (same as job cards)
         *     - Send button → sendCCSessionMessage
         *     - Enter key in input → sendCCSessionMessage
         */
        const container = document.getElementById( 'notifications-list' );
        if ( !container ) return;

        container.addEventListener( 'click', ( e ) => {
            // CC session STT button click
            const sttBtn = e.target.closest( '.cc-voice-input .cc-session-stt' );
            if ( sttBtn ) {
                const sessionHash = sttBtn.id.replace( 'cc-session-stt-', '' );
                this.handleSTTButtonClick( `cc-session-input-${sessionHash}`, sttBtn );
                return;
            }

            // CC session Send button click
            const sendBtn = e.target.closest( '.cc-voice-input .cc-session-send' );
            if ( sendBtn ) {
                const sessionHash = sendBtn.id.replace( 'cc-session-send-', '' );
                this.sendCCSessionMessage( sessionHash );
                return;
            }
        } );

        container.addEventListener( 'keydown', ( e ) => {
            if ( e.key !== 'Enter' ) return;
            const input = e.target.closest( '.cc-session-msg-input' );
            if ( input ) {
                e.preventDefault();
                const sessionHash = input.id.replace( 'cc-session-input-', '' );
                this.sendCCSessionMessage( sessionHash );
            }
        } );

        this.log( 'CC session voice input delegation setup complete' );
    }

    async sendCCSessionMessage( sessionHash ) {
        /**
         * Send a user message to a CC session via POST /api/notify.
         *
         * Unlike CJ Flow job cards which use /api/jobs/{jobId}/message,
         * CC hook sessions have no job_id in the queue system. Instead,
         * we POST to /api/notify with type=user_initiated_message and
         * job_id=sessionHash so the CCNotificationListener can filter
         * and buffer it for hook drain.
         *
         * Requires:
         *     - sessionHash is the 8-char CC session hash
         *     - DOM elements cc-session-input-{hash} and cc-session-send-{hash} exist
         *     - User is authenticated (authToken available)
         *
         * Ensures:
         *     - Message sent to /api/notify on valid input
         *     - Input cleared on success
         *     - Error shown inline on failure
         */
        const input   = document.getElementById( `cc-session-input-${sessionHash}` );
        const sendBtn = document.getElementById( `cc-session-send-${sessionHash}` );

        if ( !input ) return;

        const message = input.value.trim();
        if ( !message ) {
            input.focus();
            return;
        }

        // Disable controls and clear input immediately
        input.disabled   = true;
        sendBtn.disabled = true;
        input.value      = '';

        let success = false;

        try {
            await this.ensureValidToken();

            // Extract listener email from CC session sender_id (format: email#hash)
            const voiceDiv   = document.querySelector( `.cc-voice-input[data-session-hash="${sessionHash}"]` );
            const ccSenderId = voiceDiv?.getAttribute( 'data-sender-id' ) || '';

            if ( !ccSenderId.includes( '#' ) ) {
                throw new Error( `Cannot send CC session message: missing or malformed data-sender-id on voice input for session ${sessionHash}` );
            }
            const listenerEmail = ccSenderId.split( '#' )[ 0 ];

            const params = new URLSearchParams( {
                message     : message,
                type        : 'user_initiated_message',
                priority    : 'medium',
                target_user : listenerEmail,
                sender_id   : this.currentUserEmail,
                job_id      : sessionHash,
            } );

            const response = await fetch( `/api/notify?${params.toString()}`, {
                method  : 'POST',
                headers : {
                    'Authorization' : this.getAuthHeader(),
                },
            } );

            if ( !response.ok ) {
                const errData = await response.json().catch( () => ( {} ) );
                throw new Error( errData.detail || `HTTP ${response.status}` );
            }

            this.log( `[CC-VOICE] Sent to session ${sessionHash}: ${message.substring( 0, 80 )}` );

            if ( ccSenderId ) {
                const outgoing = {
                    id           : `cc-voice-${sessionHash}-${Date.now()}`,
                    sender_id    : ccSenderId,
                    message      : message,
                    timestamp    : new Date().toISOString(),
                    time_display : this.getLocalTimeDisplay(),
                    state        : 'delivered'
                };
                this.addNotificationToSenderGroup( outgoing, true );
            }

            success = true;

        } catch ( error ) {
            this.error( `[CC-VOICE] Failed to send to session ${sessionHash}:`, error );
            input.style.borderColor = '#dc3545';
            setTimeout( () => { input.style.borderColor = ''; }, 3000 );
        } finally {
            input.disabled   = false;
            sendBtn.disabled = false;
            if ( success ) {
                // UX: post-send focus shift to the mic so the user can
                // immediately dictate a follow-up thought without an extra click.
                const recBtn = document.getElementById( `cc-session-stt-${sessionHash}` );
                if ( recBtn ) recBtn.focus();
                else input.focus();
            } else {
                // Send failed — keep focus in the input so user can retry typing.
                input.focus();
            }
        }
    }

    // ========================================
    // JOB SUBMISSION EVENT LISTENERS
    // ========================================

    setupJobSubmitEventListeners() {
        // Research submit button
        const submitResearchBtn = document.getElementById( 'submit-research-job' );
        if ( submitResearchBtn ) {
            submitResearchBtn.addEventListener( 'click', () => {
                this.submitResearchJob();
            });
        }

        // Mutual exclusivity: podcast and presentation checkboxes
        const podcastCb = document.getElementById( 'research-with-podcast' );
        const presentationCb = document.getElementById( 'research-with-presentation' );
        if ( podcastCb && presentationCb ) {
            podcastCb.addEventListener( 'change', () => {
                if ( podcastCb.checked ) presentationCb.checked = false;
            });
            presentationCb.addEventListener( 'change', () => {
                if ( presentationCb.checked ) podcastCb.checked = false;
            });
        }

        // Podcast submit button
        const submitPodcastBtn = document.getElementById( 'submit-podcast-job' );
        if ( submitPodcastBtn ) {
            submitPodcastBtn.addEventListener( 'click', () => {
                this.submitPodcastJob();
            });
        }

        // Research STT button (voice input)
        const researchSttBtn = document.getElementById( 'research-stt-button' );
        if ( researchSttBtn ) {
            researchSttBtn.addEventListener( 'click', () => {
                this.handleSTTButtonClick( 'research-topic', researchSttBtn );
            });
        }

        // Podcast STT button (voice input)
        const podcastSttBtn = document.getElementById( 'podcast-stt-button' );
        if ( podcastSttBtn ) {
            podcastSttBtn.addEventListener( 'click', () => {
                this.handleSTTButtonClick( 'podcast-source', podcastSttBtn );
            });
        }

        // Enter key in research topic input
        const researchInput = document.getElementById( 'research-topic' );
        if ( researchInput ) {
            researchInput.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' ) {
                    e.preventDefault();
                    this.submitResearchJob();
                }
            });
        }

        // Enter key in podcast source input
        const podcastInput = document.getElementById( 'podcast-source' );
        if ( podcastInput ) {
            podcastInput.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' ) {
                    e.preventDefault();
                    this.submitPodcastJob();
                }
            });
        }

        // SWE Team submit button
        const submitSweBtn = document.getElementById( 'submit-swe-job' );
        if ( submitSweBtn ) {
            submitSweBtn.addEventListener( 'click', () => {
                this.submitSweTeamJob();
            });
        }

        // SWE Team STT button (voice input)
        const sweSttBtn = document.getElementById( 'swe-stt-button' );
        if ( sweSttBtn ) {
            sweSttBtn.addEventListener( 'click', () => {
                this.handleSTTButtonClick( 'swe-task', sweSttBtn );
            });
        }

        // Ctrl+Enter in SWE Team textarea (Enter alone inserts newline)
        const sweTaskInput = document.getElementById( 'swe-task' );
        if ( sweTaskInput ) {
            sweTaskInput.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' && e.ctrlKey ) {
                    e.preventDefault();
                    this.submitSweTeamJob();
                }
            });
        }

        // Presentation Generator submit button
        const submitPresentationBtn = document.getElementById( 'submit-presentation-job' );
        if ( submitPresentationBtn ) {
            submitPresentationBtn.addEventListener( 'click', () => {
                this.submitPresentationJob();
            });
        }

        // Presentation Generator STT button (voice input)
        const presentationSttBtn = document.getElementById( 'presentation-stt-button' );
        if ( presentationSttBtn ) {
            presentationSttBtn.addEventListener( 'click', () => {
                this.handleSTTButtonClick( 'presentation-source', presentationSttBtn );
            });
        }

        // Enter key in Presentation source input
        const presentationSourceInput = document.getElementById( 'presentation-source' );
        if ( presentationSourceInput ) {
            presentationSourceInput.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' ) {
                    e.preventDefault();
                    this.submitPresentationJob();
                }
            });
        }

        // Test Suite submit button
        const submitTestSuiteBtn = document.getElementById( 'submit-test-suite-job' );
        if ( submitTestSuiteBtn ) {
            submitTestSuiteBtn.addEventListener( 'click', () => {
                this.submitTestSuiteJob();
            });
        }

        // TFE Resume submit button (session 9056c113 — file-path resume)
        const submitTFEResumeBtn = document.getElementById( 'submit-tfe-resume-job' );
        if ( submitTFEResumeBtn ) {
            submitTFEResumeBtn.addEventListener( 'click', () => {
                this.submitTFEResume();
            });
        }

        // ── Job Message Send: Event delegation on todo + run queue containers ──
        // Handles dynamically-created job message inputs via bubbling
        this._setupJobMessageDelegation( 'run-jobs-container' );
        this._setupJobMessageDelegation( 'todo-jobs-container' );

        this.log( "Job submission event listeners setup complete" );
    }

    _setupJobMessageDelegation( containerId ) {
        /**
         * Setup click + keydown event delegation for job message send UI.
         *
         * Requires:
         *     - containerId is a valid DOM element ID
         *
         * Ensures:
         *     - STT, Send, Urgent toggle clicks handled via delegation
         *     - Enter key in job-msg-input triggers send
         */
        const container = document.getElementById( containerId );
        if ( !container ) return;

        container.addEventListener( 'click', ( e ) => {
            // STT button click
            const sttBtn = e.target.closest( '.job-send-message .stt-button' );
            if ( sttBtn ) {
                const jobId = sttBtn.id.replace( 'job-msg-stt-', '' );
                this.handleSTTButtonClick( `job-msg-input-${jobId}`, sttBtn );
                return;
            }

            // Send button click
            const sendBtn = e.target.closest( '.job-send-message .response-submit-button' );
            if ( sendBtn ) {
                const jobId = sendBtn.id.replace( 'job-msg-submit-', '' );
                this.sendJobMessage( jobId );
                return;
            }

            // Urgent toggle label click
            // NOTE: The checkbox is display:none, so clicks always land on the
            // <label> or the ⚡ emoji.  We must preventDefault() to stop the
            // browser's native label→checkbox toggle from firing a SECOND time
            // after our manual toggle (classic double-toggle bug).
            const urgentLabel = e.target.closest( '.urgent-toggle' );
            if ( urgentLabel ) {
                e.preventDefault();
                const checkbox = urgentLabel.querySelector( 'input[type="checkbox"]' );
                if ( checkbox ) {
                    checkbox.checked = !checkbox.checked;
                    urgentLabel.classList.toggle( 'checked', checkbox.checked );
                }
                return;
            }

            // Progress group toggle click (expand/collapse notification history)
            const pgToggle = e.target.closest( '.progress-group-toggle' );
            if ( pgToggle ) {
                const entry = pgToggle.closest( '.progress-group-entry' );
                if ( !entry ) return;
                const history = entry.querySelector( '.progress-group-history' );
                if ( !history ) return;
                const isExpanded = history.style.display !== 'none';
                history.style.display = isExpanded ? 'none' : 'block';
                const count = entry.getAttribute( 'data-progress-group-count' );
                pgToggle.innerHTML = ( isExpanded ? '&#9660;' : '&#9650;' ) + ` #${count}`;
            }
        } );

        // Enter key sends message in job input
        container.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Enter' && e.target.classList.contains( 'job-msg-input' ) ) {
                e.preventDefault();
                const jobId = e.target.id.replace( 'job-msg-input-', '' );
                this.sendJobMessage( jobId );
            }
        } );
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
    
    async connectWebSockets( target = 'both' ) {
        this.log( `Connecting WebSockets (target=${target})...` );

        try {
            // Get session IDs (cached in localStorage — no network call)
            this.queueSessionId = await this.getOrCreateSessionId( 'queue' );
            this.audioSessionId = await this.getOrCreateSessionId( 'audio' );

            // Update UI with session IDs
            this.updateElement( "queue-session", this.queueSessionId );
            this.updateElement( "audio-session", this.audioSessionId );

            // Connect only the requested WebSocket(s)
            const promises = [];
            if ( target === 'both' || target === 'queue' ) promises.push( this.connectQueueWebSocket() );
            if ( target === 'both' || target === 'audio' ) promises.push( this.connectAudioWebSocket() );

            await Promise.all( promises );

            this.log( `WebSocket(s) connected successfully (target=${target})` );

        } catch ( error ) {
            this.error( "WebSocket connection failed:", error );
            this.scheduleReconnect( target );
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
                    this.wsDiag( "Queue WebSocket TCP open, authenticating..." );
                    this.queueWsConnected = true;
                    this.updateStatus( "queue-ws-status", "Authenticating...", "warning" );
                    this.authenticateQueueWebSocket();
                };

                this.queueWS.onmessage = ( event ) => {
                    this.handleQueueMessage( event );
                };

                this.queueWS.onclose = ( event ) => {
                    this.wsDiag( `Queue WebSocket closed: code=${event.code} reason=${event.reason}` );
                    this.queueWsConnected = false;
                    this.updateStatus( "queue-ws-status", "Disconnected", "error" );
                    this.scheduleReconnect( 'queue' );
                };

                this.queueWS.onerror = ( error ) => {
                    this.wsDiag( `Queue WebSocket error: ${error}` );
                    this.queueWsConnected = false;
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
                    this.wsDiag( "Audio WebSocket TCP open, authenticating..." );
                    this.audioWsConnected = true;
                    this.updateStatus( "audio-ws-status", "Authenticating...", "warning" );
                    this.authenticateAudioWebSocket();
                };

                this.audioWS.onmessage = ( event ) => {
                    this.handleAudioMessage( event );
                };

                this.audioWS.onclose = ( event ) => {
                    this.wsDiag( `Audio WebSocket closed: code=${event.code} reason=${event.reason}` );
                    this.audioWsConnected = false;
                    this.updateStatus( "audio-ws-status", "Disconnected", "error" );
                    this.scheduleReconnect( 'audio' );
                };

                this.audioWS.onerror = ( error ) => {
                    this.wsDiag( `Audio WebSocket error: ${error}` );
                    this.audioWsConnected = false;
                    this.updateStatus( "audio-ws-status", "Error", "error" );
                    reject( error );
                };
                
                // Resolve when connection is established
                this.audioWS.addEventListener( 'open', resolve, { once: true } );
                
                // Set timeout for connection
                setTimeout( () => {
                    if ( this.audioWS && this.audioWS.readyState !== WebSocket.OPEN ) {
                        this.audioWsConnected = false;
                        this.updateStatus( "audio-ws-status", "Timeout", "error" );
                        try { this.audioWS.close(); } catch ( e ) { /* ignore close errors */ }
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
                "job_state_transition",
                "job_removed",
                "tts_job_request",
                "sys_time_update",
                "notification_play_sound",
                "notification_queue_update",
                "notification_responded",  // Phase 2.2 SSE - multi-device sync
                "notification_expired",    // Phase 2.2 SSE - timeout handling
                // conversation_mode_changed / voice_persona_assigned / voice_persona_released
                // arrive via notification_queue_update (custom notification_type values),
                // not as top-level WS events. See:
                // src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
                // job_paused/job_resumed removed — now handled as job_state_transition events
                "auth_success",
                "auth_error",
                "connect",
                "sys_ping"
            ]
        };
        
        this.queueWS.send( JSON.stringify( authMessage ) );
        this.wsDiag( "Queue WebSocket auth_request sent" );
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
        this.wsDiag( "Audio WebSocket auth_request sent" );
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
                    this.wsDiag( `Queue WebSocket authenticated for user: ${envelope.user_id}` );
                    this.updateStatus( "queue-ws-status", "Connected", "good" );
                    this.updateStatus( "auth-status", `Authenticated as ${envelope.user_id}`, "good" );
                    this.connectionRetries = 0; // Reset backoff on successful auth

                    // Store the server-provided user ID for notifications
                    this.notificationState.userId = envelope.user_id;
                    this.wsDiag( `Notification state updated with server user ID: ${envelope.user_id}` );

                    // Load initial data now that we have the correct user ID
                    this.loadInitialData();
                    break;

                case "auth_error":
                    this.wsDiag( `Queue WebSocket auth FAILED: ${envelope.message}` );
                    this.updateStatus( "queue-ws-status", "Auth Failed", "error" );
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
                    

                case "job_state_transition":
                    this.handleJobStateTransition( envelope );
                    break;

                case "job_removed":
                    // Remove card from DOM when another client/session deletes a job
                    const removedCard = document.getElementById( `job-card-${envelope.job_id}` );
                    if ( removedCard ) removedCard.remove();
                    if ( envelope.queue && this.queueCounts[ envelope.queue ] !== undefined ) {
                        this.queueCounts[ envelope.queue ] = Math.max( 0, this.queueCounts[ envelope.queue ] - 1 );
                        this.updateQueueCountBadge( envelope.queue, this.queueCounts[ envelope.queue ] );
                        this.updateQueueEmptyMessage( envelope.queue );
                    }
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

                case "notification_play_sound":
                    // Subscribed event — no-op handler to prevent "Unhandled message type" console noise
                    this.log( `[QUEUE WS] notification_play_sound received (priority: ${envelope.priority || 'default'})` );
                    break;

                case "sys_time_update":
                    // Update clock display with server time
                    if ( envelope.date ) {
                        this.updateElement( "clock", envelope.date );
                        this.log( `Clock updated: ${envelope.date}` );
                    }
                    if ( envelope.env_label ) {
                        this.envLabel = envelope.env_label;
                        this.updateElement( "env-label", `[${this.envLabel}]: ` );
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
                    this.wsDiag( `Audio WebSocket authenticated for user: ${envelope.user_id}` );
                    this.updateStatus( "audio-ws-status", "Connected", "good" );
                    break;

                case "auth_error":
                    this.wsDiag( `Audio WebSocket auth FAILED: ${envelope.message}` );
                    this.updateStatus( "audio-ws-status", "Auth Failed", "error" );
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

                case "audio_streaming_chunk":
                    // Subscribed event — binary audio handled in Blob branch above; text fallback is no-op
                    this.log( `[AUDIO WS] audio_streaming_chunk received (text envelope fallback)` );
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
    // JOB SUBMISSION HANDLERS
    // ========================================

    /**
     * Submit a Deep Research job (with optional podcast generation).
     *
     * If "Also generate podcast" checkbox is checked, submits to
     * /api/deep-research-to-podcast/submit endpoint.
     * Otherwise, submits to /api/deep-research/submit endpoint.
     */
    async submitResearchJob() {
        const topicInput = document.getElementById( 'research-topic' );
        const budgetInput = document.getElementById( 'research-budget' );
        const withPodcastCheckbox = document.getElementById( 'research-with-podcast' );
        const withPresentationCheckbox = document.getElementById( 'research-with-presentation' );
        const dryRunCheckbox = document.getElementById( 'research-dry-run' );
        const submitButton = document.getElementById( 'submit-research-job' );
        const loadingSpinner = document.getElementById( 'research-loading' );
        const statusDiv = document.getElementById( 'research-submit-status' );

        const topic = topicInput.value.trim();
        const budget = parseFloat( budgetInput.value ) || 3.00;
        const withPodcast = withPodcastCheckbox.checked;
        const withPresentation = withPresentationCheckbox ? withPresentationCheckbox.checked : false;
        const dryRun = dryRunCheckbox.checked;

        if ( !topic ) {
            statusDiv.textContent = '⚠️ Please enter a research topic.';
            statusDiv.style.color = '#dc3545';
            return;
        }

        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            statusDiv.textContent = 'Submitting research job...';
            statusDiv.style.color = '#666';

            // Ensure token is valid before API call
            await this.ensureValidToken();

            // Choose endpoint based on checkboxes (mutually exclusive)
            let endpoint = '/api/deep-research/submit';
            if ( withPresentation ) {
                endpoint = '/api/deep-research-to-presentation/submit';
            } else if ( withPodcast ) {
                endpoint = '/api/deep-research-to-podcast/submit';
            }

            const schedulingParams = this._getSchedulingParams( 'research' );
            let body = { query: topic, budget: budget, dry_run: dryRun, ...schedulingParams };
            if ( withPodcast ) {
                body.target_languages = [ 'en', 'es-MX' ];
            } else if ( withPresentation ) {
                body.target_duration_minutes = 15;
            }

            this.log( `Submitting research job to ${endpoint}: ${topic.substring( 0, 50 )}...` );

            const response = await fetch( endpoint, {
                method: 'POST',
                headers: {
                    'Authorization': this.getAuthHeader(),
                    'X-Session-ID': this.queueSessionId,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify( body )
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: response.statusText }) );
                throw new Error( errorData.detail || `HTTP ${response.status}` );
            }

            const result = await response.json();
            this.log( "Research job submitted:", result );

            // Success feedback
            const jobType = withPodcast ? 'Research→Podcast' : 'Research';
            statusDiv.textContent = `✓ ${jobType} job submitted! Job ID: ${result.job_id}, Position: ${result.queue_position}`;
            statusDiv.style.color = '#28a745';

            // Clear input
            topicInput.value = '';

        } catch ( error ) {
            this.error( "Research job submission failed:", error );
            statusDiv.textContent = `✗ Error: ${error.message}`;
            statusDiv.style.color = '#dc3545';
        } finally {
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }

    /**
     * Submit a Podcast generation job.
     *
     * Uses smart input detection:
     * - If input looks like a file path → direct job creation
     * - If input looks like a description → fuzzy match + notification for confirmation
     */
    async submitPodcastJob() {
        const sourceInput = document.getElementById( 'podcast-source' );
        const dryRunCheckbox = document.getElementById( 'podcast-dry-run' );
        const submitButton = document.getElementById( 'submit-podcast-job' );
        const loadingSpinner = document.getElementById( 'podcast-loading' );
        const statusDiv = document.getElementById( 'podcast-submit-status' );

        const source = sourceInput.value.trim();
        const dryRun = dryRunCheckbox.checked;

        if ( !source ) {
            statusDiv.textContent = '⚠️ Please enter a research source (path or description).';
            statusDiv.style.color = '#dc3545';
            return;
        }

        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            statusDiv.textContent = 'Processing...';
            statusDiv.style.color = '#666';

            // Ensure token is valid before API call
            await this.ensureValidToken();

            this.log( `Submitting podcast job: ${source.substring( 0, 50 )}...` );

            const response = await fetch( '/api/podcast-generator/submit', {
                method: 'POST',
                headers: {
                    'Authorization': this.getAuthHeader(),
                    'X-Session-ID': this.queueSessionId,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    research_source: source,
                    target_languages: [ 'en', 'es-MX' ],
                    dry_run: dryRun,
                    ...this._getSchedulingParams( 'podcast' )
                })
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: response.statusText }) );
                throw new Error( errorData.detail || `HTTP ${response.status}` );
            }

            const result = await response.json();
            this.log( "Podcast job response:", result );

            // Handle different response types
            if ( result.status === 'queued' ) {
                // Direct path mode - job created immediately
                statusDiv.textContent = `✓ Podcast job submitted! Job ID: ${result.job_id}, Position: ${result.queue_position}`;
                statusDiv.style.color = '#28a745';
                sourceInput.value = '';
            } else if ( result.status === 'matching' ) {
                // Description mode - fuzzy matching triggered
                statusDiv.textContent = `🔍 ${result.message}`;
                statusDiv.style.color = '#6f42c1';
                // Don't clear input - user may want to modify and retry
            } else if ( result.status === 'no_matches' ) {
                statusDiv.textContent = `⚠️ ${result.message}`;
                statusDiv.style.color = '#ffc107';
            }

        } catch ( error ) {
            this.error( "Podcast job submission failed:", error );
            statusDiv.textContent = `✗ Error: ${error.message}`;
            statusDiv.style.color = '#dc3545';
        } finally {
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }

    /**
     * Submit a SWE Team engineering task.
     *
     * Sends task to /api/swe-team/submit for asynchronous execution.
     * Budget and timeout are optional — only included if user sets them.
     */
    async submitSweTeamJob() {
        const taskInput      = document.getElementById( 'swe-task' );
        const budgetInput    = document.getElementById( 'swe-budget' );
        const timeoutInput   = document.getElementById( 'swe-timeout' );
        const dryRunCheckbox = document.getElementById( 'swe-dry-run' );
        const submitButton   = document.getElementById( 'submit-swe-job' );
        const loadingSpinner = document.getElementById( 'swe-loading' );
        const statusDiv      = document.getElementById( 'swe-submit-status' );

        const task   = taskInput.value.trim();
        const dryRun = dryRunCheckbox.checked;

        if ( !task ) {
            statusDiv.textContent = '⚠️ Please describe the engineering task.';
            statusDiv.style.color = '#dc3545';
            return;
        }

        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            statusDiv.textContent = 'Submitting SWE Team task...';
            statusDiv.style.color = '#666';

            // Ensure token is valid before API call
            await this.ensureValidToken();

            this.log( `Submitting SWE Team job: ${task.substring( 0, 50 )}...` );

            // Build request body — budget and timeout are nullable
            const body = {
                task         : task,
                dry_run      : dryRun,
                websocket_id : this.queueSessionId
            };

            const budgetVal = parseFloat( budgetInput.value );
            if ( !isNaN( budgetVal ) && budgetVal > 0 ) {
                body.budget = budgetVal;
            }

            const timeoutVal = parseInt( timeoutInput.value );
            if ( !isNaN( timeoutVal ) && timeoutVal > 0 ) {
                body.timeout = timeoutVal;
            }

            const trustModeSelect = document.getElementById( 'swe-trust-mode' );
            const trustMode = trustModeSelect ? trustModeSelect.value : '';
            if ( trustMode ) {
                body.trust_mode = trustMode;
            }

            Object.assign( body, this._getSchedulingParams( 'swe' ) );

            const response = await fetch( '/api/swe-team/submit', {
                method  : 'POST',
                headers : {
                    'Authorization' : this.getAuthHeader(),
                    'X-Session-ID'  : this.queueSessionId,
                    'Content-Type'  : 'application/json'
                },
                body: JSON.stringify( body )
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: response.statusText }) );
                throw new Error( errorData.detail || `HTTP ${response.status}` );
            }

            const result = await response.json();
            this.log( "SWE Team job response:", result );

            // Success feedback
            statusDiv.textContent = `✓ SWE Team job submitted! Job ID: ${result.job_id}, Position: ${result.queue_position}`;
            statusDiv.style.color = '#28a745';
            taskInput.value = '';

        } catch ( error ) {
            this.error( "SWE Team job submission failed:", error );
            statusDiv.textContent = `✗ Error: ${error.message}`;
            statusDiv.style.color = '#dc3545';
        } finally {
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }

    /**
     * Submit a Presentation Generator job.
     *
     * Sends source document to /api/presentation-generator/submit for
     * asynchronous slide generation via the CJ Flow queue.
     */
    async submitPresentationJob() {
        const sourceInput      = document.getElementById( 'presentation-source' );
        const audienceSelect   = document.getElementById( 'presentation-audience' );
        const durationInput    = document.getElementById( 'presentation-duration' );
        const dryRunCheckbox   = document.getElementById( 'presentation-dry-run' );
        const submitButton     = document.getElementById( 'submit-presentation-job' );
        const loadingSpinner   = document.getElementById( 'presentation-loading' );
        const statusDiv        = document.getElementById( 'presentation-submit-status' );

        const source   = sourceInput.value.trim();
        const audience = audienceSelect.value;
        const duration = parseInt( durationInput.value ) || 15;
        const dryRun   = dryRunCheckbox.checked;

        if ( !source ) {
            statusDiv.textContent = '⚠️ Please enter a source document path.';
            statusDiv.style.color = '#dc3545';
            return;
        }

        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            statusDiv.textContent = 'Submitting presentation job...';
            statusDiv.style.color = '#666';

            // Ensure token is valid before API call
            await this.ensureValidToken();

            this.log( `Submitting presentation job: ${source.substring( 0, 50 )}...` );

            const response = await fetch( '/api/presentation-generator/submit', {
                method  : 'POST',
                headers : {
                    'Authorization' : this.getAuthHeader(),
                    'X-Session-ID'  : this.queueSessionId,
                    'Content-Type'  : 'application/json'
                },
                body: JSON.stringify({
                    source_path              : source,
                    audience                 : audience,
                    target_duration_minutes  : duration,
                    dry_run                  : dryRun,
                    ...this._getSchedulingParams( 'presentation' )
                })
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: response.statusText }) );
                throw new Error( errorData.detail || `HTTP ${response.status}` );
            }

            const result = await response.json();
            this.log( "Presentation job response:", result );

            // Success feedback
            statusDiv.textContent = `✓ Presentation job submitted! Job ID: ${result.job_id}, Position: ${result.queue_position}`;
            statusDiv.style.color = '#28a745';
            sourceInput.value = '';

        } catch ( error ) {
            this.error( "Presentation job submission failed:", error );
            statusDiv.textContent = `✗ Error: ${error.message}`;
            statusDiv.style.color = '#dc3545';
        } finally {
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }

    /**
     * Submit a render-only presentation job from an existing YAML.
     *
     * Called from the "Re-render" button on completed presentation job cards.
     * Submits to the same endpoint with render_only=true, skipping Phases 1-5.
     *
     * @param {string} yamlPath - Relative path to the YAML intermediate file
     */
    async submitRerender( yamlPath ) {
        if ( !yamlPath ) {
            console.error( '[Notifications] submitRerender called without yamlPath' );
            return;
        }

        try {
            await this.ensureValidToken();
            this.log( `Submitting render-only job for: ${yamlPath}` );

            const response = await fetch( '/api/presentation-generator/submit', {
                method  : 'POST',
                headers : {
                    'Authorization' : this.getAuthHeader(),
                    'X-Session-ID'  : this.queueSessionId,
                    'Content-Type'  : 'application/json'
                },
                body: JSON.stringify({
                    source_path : yamlPath.startsWith( 'io/' ) || yamlPath.startsWith( '/io/' ) ? yamlPath : 'io/' + yamlPath,
                    render_only : true
                })
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: response.statusText }) );
                throw new Error( errorData.detail || `HTTP ${response.status}` );
            }

            const result = await response.json();
            this.log( "Render-only job response:", result );
            alert( `✓ Re-render job submitted! Job ID: ${result.job_id}` );

        } catch ( error ) {
            this.error( "Re-render submission failed:", error );
            alert( `✗ Re-render failed: ${error.message}` );
        }
    }

    /**
     * Submit a Test Suite job.
     *
     * Sends test suite parameters to /api/test-suite/submit for
     * asynchronous execution via the CJ Flow queue. Always runs
     * with monopolize=True (DB hot-swap is exclusive).
     */
    async submitTestSuiteJob() {
        const typesSelect     = document.getElementById( 'test-suite-types' );
        const filePathInput   = document.getElementById( 'test-suite-file-path' );
        const failFastCheckbox = document.getElementById( 'test-suite-fail-fast' );
        const pytestArgsInput = document.getElementById( 'test-suite-pytest-args' );
        const dryRunCheckbox  = document.getElementById( 'test-suite-dry-run' );
        const autoFixCheckbox = document.getElementById( 'test-suite-auto-fix' );
        const submitButton    = document.getElementById( 'submit-test-suite-job' );
        const loadingSpinner  = document.getElementById( 'test-suite-loading' );
        const statusDiv       = document.getElementById( 'test-suite-submit-status' );

        const testTypes  = typesSelect.value;
        const filePath   = ( filePathInput?.value || "" ).trim();
        const failFast   = failFastCheckbox?.checked || false;
        const pytestArgs = pytestArgsInput.value.trim();
        const dryRun     = dryRunCheckbox.checked;
        const autoFix    = autoFixCheckbox ? autoFixCheckbox.checked : null;

        // Validation: file-driven test types require a file path
        if ( FILE_DRIVEN_TEST_TYPES.has( testTypes ) && !filePath ) {
            statusDiv.textContent = `✗ Error: ${testTypes} requires a test file path`;
            statusDiv.style.color = '#dc3545';
            return;
        }

        // Build combined pytest_args:
        //   - file-driven types (smoke_direct, pytest_direct): prepend file path so
        //     runner delegates to `python3 <file>` or `pytest <file>` respectively
        //   - all + fail-fast: append --fail-fast flag
        let combinedArgs = pytestArgs;
        if ( FILE_DRIVEN_TEST_TYPES.has( testTypes ) && filePath ) {
            combinedArgs = combinedArgs ? `${filePath} ${combinedArgs}` : filePath;
        }
        if ( testTypes === 'all' && failFast ) {
            combinedArgs = combinedArgs ? `${combinedArgs} --fail-fast` : '--fail-fast';
        }

        try {
            // Update UI
            submitButton.disabled = true;
            loadingSpinner.style.display = 'inline-block';
            statusDiv.textContent = 'Submitting test suite job...';
            statusDiv.style.color = '#666';

            // Ensure token is valid before API call
            await this.ensureValidToken();

            this.log( `Submitting test suite job: types=${testTypes}, dryRun=${dryRun}, args="${combinedArgs}"` );

            const body = {
                test_types : testTypes,
                dry_run    : dryRun,
            };
            if ( combinedArgs ) {
                body.pytest_args = combinedArgs;
            }
            // Per-run override for the TestSuiteCompletionWatchdog (TFE).
            // Initial state mirrors INI default `test_fix_expediter_auto_fix_enabled`,
            // but the user can flip it for this submission only without changing the INI.
            if ( autoFix !== null ) {
                body.auto_fix_on_failure = autoFix;
            }

            // Add scheduling params (schedule checkbox + monopolize is always on)
            const scheduleCheckbox = document.getElementById( 'test-suite-schedule' );
            const scheduleTime     = document.getElementById( 'test-suite-scheduled-time' );
            if ( scheduleCheckbox?.checked && scheduleTime?.value ) {
                body.scheduled_at = new Date( scheduleTime.value ).toISOString();
            }

            const response = await fetch( '/api/test-suite/submit', {
                method  : 'POST',
                headers : {
                    'Authorization' : this.getAuthHeader(),
                    'X-Session-ID'  : this.queueSessionId,
                    'Content-Type'  : 'application/json'
                },
                body: JSON.stringify( body )
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: response.statusText }) );
                throw new Error( errorData.detail || `HTTP ${response.status}` );
            }

            const result = await response.json();
            this.log( "Test suite job response:", result );

            // Success feedback
            statusDiv.textContent = `✓ Test suite job submitted! Job ID: ${result.job_id}, Position: ${result.queue_position}`;
            statusDiv.style.color = '#28a745';

        } catch ( error ) {
            this.error( "Test suite job submission failed:", error );
            statusDiv.textContent = `✗ Error: ${error.message}`;
            statusDiv.style.color = '#dc3545';
        } finally {
            submitButton.disabled = false;
            loadingSpinner.style.display = 'none';
        }
    }

    /**
     * Generic STT button click handler for job submission cards.
     * Reuses the existing recording infrastructure.
     *
     * @param {string} inputId - ID of the input element to fill with transcription
     * @param {HTMLElement} button - The STT button element
     */
    async handleSTTButtonClick( inputId, button ) {
        // Delegate to the recording manager with appropriate context
        const inputElement = document.getElementById( inputId );
        if ( !inputElement ) {
            this.error( `Input element not found: ${inputId}` );
            return;
        }

        // Toggle behavior - stop if recording, start if not
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
        } else if ( !this.recordingManager.isProcessing() ) {
            await this.recordingManager.startRecording( inputId, button, inputElement );
        }
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
        // Thin wrapper - delegates to unified handleSTTButtonClick
        const button = document.getElementById( 'qa-stt-button' );
        await this.handleSTTButtonClick( 'qa-input', button );
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
        
        const mode = document.getElementById( 'tts-mode' ).value;
        this.log( "Job completion received:", envelope );

        const actualText = envelope.text;
        
        // Update response area with job completion
        this.updateElement( "response-text", `Job completed: ${actualText || 'No text provided'}` );

        // Capture TTT (Time to Text) metric
        this.metricsTextTime = Date.now();
        this.updateMetricsTTT();

        // Store job completion data in cache for replay functionality
        this.storeJobCompletionForReplay( envelope, actualText );
        
        // Play TTS audio based on current mode. Use the persona for the
        // job's sender (when known) so each session's job completions
        // speak with that session's assigned voice.
        const jobVoiceId = this.getVoiceIdForSender( envelope.sender_id );
        this.playTTS( actualText || "Job completed", mode, jobVoiceId );
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
                this.currentUserEmail, // User context for filtering
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
        // Thin wrapper - delegates to unified handleSTTButtonClick
        const button = document.getElementById( 'cc-stt-button' );
        await this.handleSTTButtonClick( 'cc-prompt', button );
    }

    async submitClaudeCode() {
        const project = document.getElementById( 'cc-project' ).value;
        const prompt = document.getElementById( 'cc-prompt' ).value;
        const taskType = document.getElementById( 'cc-task-type' ).value;
        const executionMode = document.getElementById( 'cc-execution-mode' ).value;
        const dryRunCheckbox = document.getElementById( 'cc-dry-run' );
        const dryRun = dryRunCheckbox ? dryRunCheckbox.checked : false;

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

        // Route to appropriate submission method based on execution mode
        if ( executionMode === 'queue' ) {
            await this.submitClaudeCodeToQueue( project, prompt, taskType, dryRun, loadingEl, submitBtn, responseEl );
        } else {
            await this.submitClaudeCodeDirect( project, prompt, taskType, loadingEl, submitBtn, responseEl );
        }
    }

    async submitClaudeCodeToQueue( project, prompt, taskType, dryRun, loadingEl, submitBtn, responseEl ) {
        /**
         * Submit Claude Code task to CJF queue for background execution.
         * Jobs appear in the queue section and are tracked via job cards.
         */
        if ( responseEl ) responseEl.textContent = 'Submitting to CJF queue...';

        this.log( `Claude Code queue submit: project=${project}, type=${taskType}, dry_run=${dryRun}` );

        try {
            const response = await fetch( '/api/claude-code/queue/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders()
                },
                body: JSON.stringify( {
                    prompt: prompt,
                    project: project,
                    task_type: taskType,
                    max_turns: taskType === 'INTERACTIVE' ? 200 : 50,
                    websocket_id: this.sessionId,
                    dry_run: dryRun,
                    ...this._getSchedulingParams( 'cc' )
                } )
            } );

            if ( !response.ok ) {
                const errorData = await response.json();
                throw new Error( errorData.detail || 'Queue submission failed' );
            }

            const data = await response.json();

            this.log( `Claude Code job queued: ${data.job_id} at position ${data.queue_position}` );

            // Update UI for queue mode
            document.getElementById( 'cc-task-id' ).textContent = data.job_id;
            document.getElementById( 'cc-status' ).textContent = 'Queued';
            document.getElementById( 'cc-session-info' ).style.display = 'flex';

            // Update response area with queue info
            if ( responseEl ) {
                responseEl.textContent = `Job ${data.job_id} queued at position ${data.queue_position}.\n\nThe job will appear in the CJF queue section and send notifications via the job card.\n\nNo WebSocket streaming in queue mode - check the queue section for progress.`;
            }

            // Clear cost display (not available until job completes)
            document.getElementById( 'cc-cost' ).textContent = '$0.00 (pending)';

            // Hide Option B controls in queue mode (handled via notifications)
            document.getElementById( 'cc-option-b-controls' ).style.display = 'none';

            // Refresh queues to show new job
            this.refreshAllQueues();

        } catch ( error ) {
            this.error( 'Claude Code queue submit failed:', error );
            if ( responseEl ) responseEl.textContent = `Error: ${error.message}`;
        } finally {
            if ( loadingEl ) loadingEl.style.display = 'none';
            if ( submitBtn ) submitBtn.disabled = false;
        }
    }

    async submitClaudeCodeDirect( project, prompt, taskType, loadingEl, submitBtn, responseEl ) {
        /**
         * Submit Claude Code task for direct execution with WebSocket streaming.
         * This is the original behavior - real-time output streaming.
         */
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
        let ttsMessage = notification.message;

        // Add priority prefix for urgent notifications
        if ( notification.priority === "urgent" ) {
            ttsMessage = `Urgent! ${ttsMessage}`;
        }

        return ttsMessage;
    }

    async testTTS( mode ) {
        const testText = "This is a test of the text-to-speech system in " + mode + " mode.";
        this.log( `Testing TTS in ${mode} mode: ${testText}` );
        
        await this.playTTS( testText, mode );
    }
    
    async playTTS( text, mode, voiceId = null ) {
        this.log( `Playing TTS: "${text}" in ${mode} mode${ voiceId ? ` (voice: ${voiceId})` : "" }` );

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
                await this.playInstantTTS( text, voiceId );
            } else {
                await this.playReliableTTS( text, voiceId );
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
    
    async playInstantTTS( text, voiceId = null ) {
        this.log( "Starting instant TTS (11labs streaming)..." );

        // Start pulsing indicator on notification card
        this.startTTSPlayingIndicator( this.currentNotificationId );

        try {
            // Ensure token is valid before API call (auto-refresh if expired)
            await this.ensureValidToken();

            // Start timing BEFORE the fetch for accurate TTFA measurement
            this.startTime = Date.now();
            this.metricsTTSStartTime = Date.now();

            // Request TTS via 11labs streaming endpoint.
            // Body key is `voice_id` (server reads `voice_id`, NOT `voice`).
            // When voiceId is null, omit the field so the server falls back to
            // its configured default (Sam, the system default voice).
            const ttsBody = {
                text       : text,
                session_id : this.audioSessionId  // Ensure session_id is included
            };
            if ( voiceId ) ttsBody.voice_id = voiceId;
            const response = await fetch( '/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader(),
                    'X-Session-ID': this.audioSessionId
                },
                body: JSON.stringify( ttsBody )
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
    
    async playReliableTTS( text, voiceId = null ) {
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

            // Request TTS via OpenAI batch endpoint.
            // Body key is `voice_id` (server reads `voice_id`, NOT `voice`).
            // Omit when voiceId is null so server-side default applies.
            const ttsBody = {
                text       : text,
                session_id : this.audioSessionId  // Add missing session_id
            };
            if ( voiceId ) ttsBody.voice_id = voiceId;
            const response = await fetch( '/api/get-speech', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.getAuthHeader(),
                    'X-Session-ID': this.audioSessionId
                },
                body: JSON.stringify( ttsBody )
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
        this.log( `🔊 handleAudioChunk: ${blobData.size} bytes, currentTTSMode=${this.currentTTSMode}` );

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
        this.log( `🔴 handleAudioComplete: currentTTSMode=${this.currentTTSMode} at ${Date.now()}` );

        // Guard: if stopAudio() already ran (mode is null), skip cleanup
        // to avoid clobbering a NEW notification's TTS mode that may have started
        if ( this.currentTTSMode === null ) {
            this.log( `🔴 handleAudioComplete: SKIPPING - stopAudio() already cleared mode (stale audio_complete from dismissed notification)` );
            return;
        }

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
        
        // Clean up - for instant mode, defer mode reset to onended handler
        // so in-flight chunks aren't dropped prematurely
        if ( this.currentTTSMode !== this.TTS_MODE_INSTANT ) {
            this.currentTTSMode = null;
            this.firstChunkStartTime = null;
            this.firstChunkPlayed = false;
            this.currentTTSText = null;
        }
        this.processedChunks = 0;
        this.sequentialChunksPlayed = 0;
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

        // Race condition guard: stopAudio() may have run during the await above
        if ( this.currentTTSMode === null ) {
            this.log( `🔴 playPCMChunk: RACE DETECTED - currentTTSMode went null during await, dropping chunk` );
            return;
        }

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
                // Deferred cleanup from handleAudioComplete (instant mode)
                this.currentTTSMode = null;
                this.firstChunkStartTime = null;
                this.firstChunkPlayed = false;
                this.currentTTSText = null;
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
        this.log( `🔴 stopAudio() CALLED at ${Date.now()}` );

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
        this.currentTTSMode = null;  // Prevent incoming WebSocket chunks from being played
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
    // JOB STATE TRANSITION HANDLERS (Session 107)
    // ========================================

    /**
     * Handle job_state_transition WebSocket event.
     * Map a JobState value to its UI container name.
     *
     * @param {string} state - JobState value (pending, queued, scheduled, paused, running, completed, failed, interrupted, cancelled)
     * @returns {string} UI container name (todo, run, done, dead)
     */
    stateToContainer( state ) {
        const mapping = {
            'pending'     : 'todo',
            'queued'      : 'todo',
            'scheduled'   : 'todo',
            'paused'      : 'todo',
            'running'     : 'run',
            'completed'   : 'done',
            'failed'      : 'dead',
            'interrupted' : 'dead',
            'cancelled'   : 'dead',
        };
        return mapping[ state ] || 'todo';
    }

    /**
     * Moves job cards between queue containers via DOM reparenting.
     *
     * @param {Object} event - WebSocket event with job_id, from_state, to_state, metadata
     */
    handleJobStateTransition( event ) {
        const { job_id: jobId, from_state: fromState, to_state: toState, metadata } = event;

        // Map states to UI containers
        const fromQueue = this.stateToContainer( fromState );
        const toQueue   = this.stateToContainer( toState );

        if ( !jobId || !fromState || !toState ) {
            this.error( '[JOB-TRANSITION] Invalid event:', event );
            return;
        }

        // Filter by queue view mode — admins with "own" filter skip other users' jobs
        const eventEmail = metadata?.user_email;
        if ( this.queueFilterMode === 'own' && eventEmail && eventEmail !== this.currentUserEmail ) {
            this.log( `[JOB-TRANSITION] Filtered out (own mode, job belongs to ${eventEmail})` );
            return;
        }
        if ( this.queueFilterMode === 'others' && eventEmail && eventEmail === this.currentUserEmail ) {
            this.log( `[JOB-TRANSITION] Filtered out (others mode, job belongs to self)` );
            return;
        }

        // Handle pause/resume as in-place card updates (no container move needed)
        if ( toState === 'paused' || ( fromState === 'paused' && toState === 'queued' ) ) {
            this.handleJobPauseStateChange( event, toState === 'paused' );
            return;
        }

        // Deduplicate events - prevent duplicate card creation (Session 107 bug fix)
        const eventId = `job_state_transition:${jobId}:${fromQueue}:${toQueue}`;
        if ( this.processedEvents.has( eventId ) ) {
            this.log( `[JOB-TRANSITION] Duplicate event ignored: ${eventId}` );
            return;
        }
        this.processedEvents.add( eventId );

        // Clean up old events if set gets too large
        if ( this.processedEvents.size > this.maxProcessedEvents ) {
            const eventsArray = Array.from( this.processedEvents );
            const keepEvents = eventsArray.slice( -this.maxProcessedEvents + 10 );
            this.processedEvents = new Set( keepEvents );
            this.log( `[JOB-TRANSITION] Cleaned up processed events cache, kept ${keepEvents.length} recent events` );
        }

        this.log( `[JOB-TRANSITION] ${jobId}: ${fromQueue} -> ${toQueue}` );

        // Find the card in source container
        const fromContainer = document.getElementById( `${fromQueue}-jobs-container` );
        const card = fromContainer?.querySelector( `.job-card[data-job-id="${jobId}"]` );

        if ( !card ) {
            // Phase 6.3: Card doesn't exist in source queue - create it in target queue
            this.log( `[JOB-TRANSITION] Card not found in ${fromQueue}, creating in ${toQueue}` );

            const toContainer = document.getElementById( `${toQueue}-jobs-container` );
            if ( !toContainer ) {
                this.error( `[JOB-TRANSITION] Target container not found: ${toQueue}-jobs-container` );
                return;
            }

            // Check if card already exists in TARGET container (Session 107 bug fix)
            const existingInTarget = toContainer.querySelector( `.job-card[data-job-id="${jobId}"]` );
            if ( existingInTarget ) {
                this.log( `[JOB-TRANSITION] Card ${jobId} already exists in ${toQueue}, skipping creation` );
                return;
            }

            if ( metadata ) {
                // Build job object for renderJobCard from transition metadata
                // Session 107: Fix field parity between WebSocket and server-fetched cards
                const job = {
                    job_id          : jobId,
                    question_text   : metadata.question_text || 'Processing...',
                    agent_type      : metadata.agent_type || 'Unknown',
                    timestamp       : metadata.timestamp || new Date().toISOString(),
                    started_at      : metadata.started_at || null,
                    completed_at    : metadata.completed_at || null,
                    response_text   : metadata.response_text || null,
                    abstract        : metadata.abstract || null,
                    report_path               : metadata.report_link || null,
                    remediation_snapshot_path : metadata.remediation_snapshot_path || null,
                    cost_summary              : metadata.cost_summary || null,
                    is_cache_hit    : metadata.is_cache_hit || false,
                    user_email      : metadata.user_email || null,
                    status          : metadata.status || 'completed',
                    error           : metadata.error || null,
                    has_interactions: metadata.has_interactions || false,
                    duration_seconds: metadata.duration_seconds || null,
                    expediting      : metadata.expediting || false,
                    scheduled_at    : metadata.scheduled_at || null,
                    monopolize      : metadata.monopolize || false,
                    paused          : metadata.paused || false
                };

                // Remove empty message if present
                const emptyMsg = toContainer.querySelector( '.queue-empty-message' );
                if ( emptyMsg ) emptyMsg.remove();

                const cardHtml = this.renderJobCard( job, toQueue );
                toContainer.insertAdjacentHTML( 'afterbegin', cardHtml );
                this.log( `[JOB-TRANSITION] Created new card in ${toQueue} container` );

                // Update count badge for target queue (local counter, not DOM-based)
                this.queueCounts[ toQueue ] = ( this.queueCounts[ toQueue ] || 0 ) + 1;
                this.updateQueueCountBadge( toQueue, this.queueCounts[ toQueue ] );
            } else {
                this.log( `[JOB-TRANSITION] No metadata provided, cannot create card` );
            }
            return;
        }

        // Terminal states (done/dead): full re-render via renderJobCard for parity with reload path.
        // Eliminates surgical-morph divergence: pause-button-persists, missing-trash-button,
        // missing scheduled/monopolize badges. Single source of truth shared with reload/history paths.
        if ( ( toQueue === 'done' || toQueue === 'dead' ) && metadata ) {
            const targetContainer = document.getElementById( `${toQueue}-jobs-container` );
            if ( !targetContainer ) {
                this.error( `[JOB-TRANSITION] Target container not found: ${toQueue}-jobs-container` );
                return;
            }

            // Build complete job object — same shape as cold-start branch above (lines 4764-4786)
            const job = {
                job_id          : jobId,
                question_text   : metadata.question_text || 'Processing...',
                agent_type      : metadata.agent_type || 'Unknown',
                timestamp       : metadata.timestamp || new Date().toISOString(),
                started_at      : metadata.started_at || null,
                completed_at    : metadata.completed_at || null,
                response_text   : metadata.response_text || null,
                abstract        : metadata.abstract || null,
                report_path               : metadata.report_link || metadata.report_path || null,
                yaml_path                 : metadata.yaml_path || null,
                remediation_snapshot_path : metadata.remediation_snapshot_path || null,
                cost_summary              : metadata.cost_summary || null,
                is_cache_hit    : metadata.is_cache_hit || false,
                user_email      : metadata.user_email || null,
                status          : metadata.status || ( toQueue === 'dead' ? 'failed' : 'completed' ),
                error           : metadata.error || null,
                has_interactions: metadata.has_interactions || false,
                duration_seconds: metadata.duration_seconds || null,
                expediting      : metadata.expediting || false,
                scheduled_at    : metadata.scheduled_at || null,
                monopolize      : metadata.monopolize || false,
                paused          : metadata.paused || false
            };

            // Remove empty message in target container if present
            const targetEmptyMsg = targetContainer.querySelector( '.queue-empty-message' );
            if ( targetEmptyMsg ) targetEmptyMsg.remove();

            // Remove the old card and insert freshly-rendered HTML at top of target
            card.remove();
            const newCardHtml = this.renderJobCard( job, toQueue );
            targetContainer.insertAdjacentHTML( 'afterbegin', newCardHtml );
            this.log( `[JOB-TRANSITION] Re-rendered ${jobId} into ${toQueue} via renderJobCard` );

            // Update empty message for source container
            this.updateQueueEmptyMessage( fromQueue );

            // Update count badges for both queues
            if ( fromQueue !== toQueue ) {
                this.queueCounts[ fromQueue ] = Math.max( 0, ( this.queueCounts[ fromQueue ] || 0 ) - 1 );
                this.updateQueueCountBadge( fromQueue, this.queueCounts[ fromQueue ] );
                this.queueCounts[ toQueue ] = ( this.queueCounts[ toQueue ] || 0 ) + 1;
                this.updateQueueCountBadge( toQueue, this.queueCounts[ toQueue ] );
            }
            return;
        }

        // Non-terminal transitions (todo/run), or terminal transitions without metadata —
        // fall back to reparent + surgical morph
        // Update status class
        card.classList.remove( `status-${fromQueue}` );
        card.classList.add( `status-${toQueue}` );

        // Move card to target container (DOM reparenting)
        const toContainer = document.getElementById( `${toQueue}-jobs-container` );
        if ( toContainer ) {
            // Remove empty message if present
            const emptyMsg = toContainer.querySelector( '.queue-empty-message' );
            if ( emptyMsg ) emptyMsg.remove();

            // Insert at top of target queue
            toContainer.insertAdjacentElement( 'afterbegin', card );
            this.log( `[JOB-TRANSITION] Card moved to ${toQueue} container` );
        }

        // Update empty messages for source container
        this.updateQueueEmptyMessage( fromQueue );

        // Inject static duration section if entering run queue (no live timer)
        // Final duration calculated server-side and shown in done queue via job.duration_seconds
        if ( toQueue === 'run' ) {
            const detailsSection = card.querySelector( '.job-card-details' );
            if ( detailsSection && !detailsSection.querySelector( '.job-duration-line' ) ) {
                const durationHtml = `
                    <div class="job-duration-line">
                        <span class="duration-label">Duration:</span>
                        <span class="duration-value">In progress...</span>
                    </div>
                `;
                detailsSection.insertAdjacentHTML( 'afterbegin', durationHtml );
            }
        }

        // Update status indicators when transitioning to done queue
        if ( toQueue === 'done' ) {
            const header = card.querySelector( '.job-card-header' );
            if ( header ) {
                // 1. Remove spinning indicator
                const spinner = header.querySelector( '.status-indicator.spinning' );
                if ( spinner ) {
                    spinner.remove();
                }

                // 2. Add completion badge (before .job-question)
                const questionSpan = header.querySelector( '.job-question' );
                if ( questionSpan && !header.querySelector( '.completion-badge' ) ) {
                    const badge = document.createElement( 'span' );
                    badge.className = 'completion-badge success';
                    badge.title = 'Completed';
                    badge.textContent = '✓';
                    header.insertBefore( badge, questionSpan );
                }

                // 3. Add interaction indicator (after .job-question, before .job-timestamp)
                const timestampSpan = header.querySelector( '.job-timestamp' );
                if ( timestampSpan && !header.querySelector( '.interaction-indicator' ) ) {
                    const indicator = document.createElement( 'span' );
                    indicator.className = 'interaction-indicator';
                    indicator.title = 'Has interaction history';
                    indicator.textContent = '💬';
                    header.insertBefore( indicator, timestampSpan );
                }

                // 4. Remove "In progress..." duration line (will be replaced by cost summary)
                const durationLine = card.querySelector( '.job-duration-line' );
                if ( durationLine ) {
                    durationLine.remove();
                }

                // 5. Remove send-message input (no messaging for done jobs)
                const sendMsg = card.querySelector( '.job-send-message' );
                if ( sendMsg ) {
                    sendMsg.remove();
                    this.log( `[JOB-TRANSITION] Removed send-message UI for ${jobId}` );
                }

                // 6. Remove cancel button (no cancelling completed jobs)
                const cancelBtn = header.querySelector( '.job-cancel-button' );
                if ( cancelBtn ) {
                    cancelBtn.remove();
                    header.classList.remove( 'has-cancel' );
                    this.log( `[JOB-TRANSITION] Removed cancel button for completed ${jobId}` );
                }

                // 7. Convert live interactions to done-queue lazy-load pattern
                const interactionsSection = card.querySelector( '.job-interactions-section' );
                if ( interactionsSection ) {
                    interactionsSection.classList.remove( 'live-interactions' );
                    // Update header text
                    const headerSpan = interactionsSection.querySelector( '.interactions-header span' );
                    if ( headerSpan ) headerSpan.textContent = '📋 Notification Conversation';
                    // Collapse and set up for lazy loading
                    const contentEl = interactionsSection.querySelector( '.interactions-content' );
                    if ( contentEl ) {
                        contentEl.classList.add( 'collapsed' );
                        contentEl.innerHTML = '<div class="interactions-loading">Loading...</div>';
                    }
                    // Reset expand button
                    const expandBtn = interactionsSection.querySelector( '.interactions-expand-btn' );
                    if ( expandBtn ) expandBtn.textContent = '▶';
                }
            }
        }

        // Remove cancel button when transitioning to dead queue
        if ( toQueue === 'dead' ) {
            const header = card.querySelector( '.job-card-header' );
            if ( header ) {
                const cancelBtn = header.querySelector( '.job-cancel-button' );
                if ( cancelBtn ) {
                    cancelBtn.remove();
                    header.classList.remove( 'has-cancel' );
                    this.log( `[JOB-TRANSITION] Removed cancel button for dead ${jobId}` );
                }
            }
        }

        // Insert metadata into placeholder nodes if provided (completion events)
        if ( metadata ) {
            this.insertJobMetadata( jobId, card, metadata );
        }

        // Update count badges for both queues (local counter, not DOM-based)
        if ( fromQueue !== toQueue ) {
            this.queueCounts[ fromQueue ] = Math.max( 0, ( this.queueCounts[ fromQueue ] || 0 ) - 1 );
            this.updateQueueCountBadge( fromQueue, this.queueCounts[ fromQueue ] );
            this.queueCounts[ toQueue ] = ( this.queueCounts[ toQueue ] || 0 ) + 1;
            this.updateQueueCountBadge( toQueue, this.queueCounts[ toQueue ] );
        }
    }

    handleJobPauseStateChange( event, isPaused ) {
        /**
         * Handle job_paused / job_resumed WebSocket event.
         * Updates card in-place without full queue reload.
         *
         * Requires:
         *     - event.data.job_id identifies a card in the todo queue
         *     - isPaused is boolean indicating new state
         *
         * Ensures:
         *     - Card classes toggled (job-paused added/removed)
         *     - Paused badge added/removed
         *     - Status indicator swapped
         *     - Pause button icon/state updated
         *     - data-paused attribute updated
         */
        const jobId = event.data?.job_id || event.job_id;
        if ( !jobId ) {
            this.error( '[JOB-PAUSE] Missing job_id in event:', event );
            return;
        }

        this.log( `[JOB-PAUSE] ${isPaused ? 'Paused' : 'Resumed'}: ${jobId}` );

        const card = document.getElementById( `job-card-${jobId}` );
        if ( !card ) {
            this.log( `[JOB-PAUSE] Card not found: ${jobId} (may not be rendered)` );
            return;
        }

        const header = card.querySelector( '.job-card-header' );

        // 1. Toggle card-level paused class and data attribute
        if ( isPaused ) {
            card.classList.add( 'job-paused' );
            card.dataset.paused = 'true';
        } else {
            card.classList.remove( 'job-paused' );
            card.dataset.paused = 'false';
        }

        // 2. Toggle paused badge
        const existingPausedBadge = header?.querySelector( '.paused-badge' );
        if ( isPaused && !existingPausedBadge && header ) {
            const badge = document.createElement( 'span' );
            badge.className = 'paused-badge';
            badge.title     = 'Paused — consumer will skip';
            badge.textContent = '⏸ Paused';
            const refNode = header.querySelector( '.job-question' );
            if ( refNode ) {
                header.insertBefore( badge, refNode );
            }
        } else if ( !isPaused && existingPausedBadge ) {
            existingPausedBadge.remove();
        }

        // 3. Toggle status indicator
        const existingIndicator = header?.querySelector( '.status-indicator' );
        if ( isPaused ) {
            if ( existingIndicator ) {
                existingIndicator.className   = 'status-indicator paused-icon';
                existingIndicator.title       = 'Paused';
                existingIndicator.textContent = '⏸';
            } else if ( header ) {
                const indicator = document.createElement( 'span' );
                indicator.className   = 'status-indicator paused-icon';
                indicator.title       = 'Paused';
                indicator.textContent = '⏸';
                const timestampSpan = header.querySelector( '.job-timestamp' );
                if ( timestampSpan ) header.insertBefore( indicator, timestampSpan );
            }
        } else {
            // Remove paused indicator (un-paused todo job has no spinning indicator unless expediting)
            if ( existingIndicator && existingIndicator.classList.contains( 'paused-icon' ) ) {
                existingIndicator.remove();
            }
        }

        // 4. Update pause/resume button
        const pauseBtn = document.getElementById( `job-pause-${jobId}` );
        if ( pauseBtn ) {
            pauseBtn.disabled    = false;
            pauseBtn.textContent = isPaused ? '▶' : '⏸';
            pauseBtn.title       = isPaused ? 'Resume this job' : 'Pause this job';
            pauseBtn.onclick     = ( e ) => {
                e.stopPropagation();
                window.notificationsUI.toggleJobPause( jobId, !isPaused );
            };

            if ( isPaused ) {
                pauseBtn.classList.add( 'is-paused' );
            } else {
                pauseBtn.classList.remove( 'is-paused' );
            }
        }
    }

    /**
     * Insert completion metadata into card's placeholder DOM nodes.
     *
     * @param {string} jobId - The job ID
     * @param {HTMLElement} card - The job card element
     * @param {Object} metadata - Completion metadata (response_text, abstract, report_link, cost_summary, error)
     */
    insertJobMetadata( jobId, card, metadata ) {
        this.log( `[JOB-TRANSITION] Inserting metadata for ${jobId}:`, metadata );

        if ( metadata.response_text ) {
            const responseEl = card.querySelector( '.job-response' );
            if ( responseEl ) {
                responseEl.innerHTML = `<strong>Response:</strong> ${this.escapeHtml( metadata.response_text )}`;
                responseEl.style.display = 'block';
            }
        }

        // Session 108: Use helper functions for consistent rendering
        if ( metadata.abstract ) {
            const abstractEl = card.querySelector( '.job-abstract' );
            if ( abstractEl ) {
                abstractEl.innerHTML = this.renderAbstractSection( metadata.abstract );
                abstractEl.style.display = 'block';
            }
        }

        // Session 108: Use helper function for report link (handle both report_link URL and report_path)
        const reportPath = metadata.report_link || metadata.report_path;
        if ( reportPath ) {
            const reportEl = card.querySelector( '.job-report-link' );
            if ( reportEl ) {
                const agentType        = metadata.agent_type || card.dataset.agentType || null;
                const yamlPath         = metadata.yaml_path || null;
                const remediationPath  = metadata.remediation_snapshot_path || null;
                const pptxPath         = metadata.pptx_path || null;
                reportEl.innerHTML = this.renderReportLinkSection( reportPath, agentType, yamlPath, remediationPath, pptxPath );
                reportEl.style.display = 'block';
            }
        }

        // Session 108: Use helper function for cost summary (handle object type)
        if ( metadata.cost_summary ) {
            const costEl = card.querySelector( '.job-cost-summary' );
            if ( costEl ) {
                const durationSeconds = metadata.duration_seconds || null;
                costEl.innerHTML = this.renderCostSummaryContent( metadata.cost_summary, durationSeconds );
                costEl.style.display = 'block';
            }
        }

        if ( metadata.error ) {
            const errorEl = card.querySelector( '.job-error' );
            if ( errorEl ) {
                errorEl.innerHTML = `<strong>Error:</strong> ${this.escapeHtml( metadata.error )}`;
                errorEl.style.display = 'block';
            }
        }
    }

    /**
     * Update queue count badge by counting cards in DOM.
     *
     * @param {string} queueType - Queue type (todo, run, done, dead)
     */
    updateQueueCountFromDOM( queueType ) {
        const container = document.getElementById( `${queueType}-jobs-container` );
        if ( !container ) return;

        const cardCount = container.querySelectorAll( '.job-card' ).length;
        const badge = document.getElementById( `${queueType}-count-badge` );
        if ( badge ) {
            badge.textContent = cardCount;
        }
    }

    /**
     * Update queue count badge with server-provided count.
     * Session 107: Badge-only updates from queue_*_update events.
     *
     * @param {string} queueType - Queue type (todo, run, done, dead)
     * @param {number} count - Server-provided count
     */
    updateQueueCountBadge( queueType, count ) {
        const badge = document.getElementById( `${queueType}-count-badge` );
        if ( badge ) {
            badge.textContent = count;
        }
    }

    /**
     * Update empty message for a queue container.
     *
     * @param {string} queueType - Queue type (todo, run, done, dead)
     */
    updateQueueEmptyMessage( queueType ) {
        const container = document.getElementById( `${queueType}-jobs-container` );
        if ( !container ) return;

        const cardCount = container.querySelectorAll( '.job-card' ).length;
        let emptyMsg = container.querySelector( '.queue-empty-message' );

        if ( cardCount === 0 && !emptyMsg ) {
            // Add empty message
            emptyMsg = document.createElement( 'div' );
            emptyMsg.className = 'queue-empty-message';
            emptyMsg.textContent = 'No jobs in queue';
            container.appendChild( emptyMsg );
        } else if ( cardCount > 0 && emptyMsg ) {
            // Remove empty message
            emptyMsg.remove();
        }
    }

    // ========================================
    // NOTIFICATION HANDLERS (from original queue.js)
    // ========================================

    async handleNotificationUpdate( envelope ) {
        console.log( `[DIAG-JR] ENTER handleNotificationUpdate: id=${envelope?.notification?.id_hash} job_id=${envelope?.notification?.job_id} type=${envelope?.notification?.type} msg=${(envelope?.notification?.message||'').substring(0,50)}` );
        this.log( "Notification queue update received:", envelope );

        // Handle real-time notification updates from NotificationFifoQueue
        const notification = envelope.notification;

        if ( !notification ) {
            this.log( "No notification data in WebSocket event" );
            return;
        }

        // Custom-typed state-update notifications (not user-facing messages).
        // Routed through the canonical notification subsystem rather than as
        // ad-hoc top-level WS events. Each case handles its own state update
        // and returns early so the message-render path is skipped.
        // See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
        switch ( notification.type ) {
            case "voice_persona_assigned":
                if ( notification.sender_id && notification.voice_persona ) {
                    this.senderPersonaMap.set( notification.sender_id, notification.voice_persona );
                    // Layer A: patch any existing card header in place so the
                    // badge appears without a re-render. No-op when card not yet built.
                    this._setPersonaBadgeOnCard( notification.sender_id, notification.voice_persona );
                }
                return;

            case "voice_persona_released":
                if ( notification.sender_id ) {
                    this.senderPersonaMap.delete( notification.sender_id );
                    // Layer A: remove the badge from any existing card header
                    this._setPersonaBadgeOnCard( notification.sender_id, null );
                }
                return;

            case "conversation_mode_changed":
                // Re-shape from notification.payload to the legacy envelope keys
                // that handleConversationModeChanged reads (session_id,
                // conversation_mode_active, displaced, displaced_by). The
                // strip-icon mic overlay is updated INSIDE handleConversationModeChanged
                // so it benefits from the full→8-char session_id normalization
                // (mismatched-key bug logged at line 9553-9564).
                this.handleConversationModeChanged({
                    session_id              : notification.payload?.session_id,
                    conversation_mode_active: notification.payload?.active,
                    displaced               : notification.payload?.displaced,
                    displaced_by            : notification.payload?.displaced_by
                });
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

        // Hydrate sender → voice persona map. The server stamps voice_persona on
        // every outbound notification envelope; we cache it here so playTTS and
        // sender-card badge rendering can look it up without re-fetching the bridge.
        // See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md §4.3
        if ( notification.voice_persona && notification.sender_id ) {
            this.senderPersonaMap.set( notification.sender_id, notification.voice_persona );
        }

        // Session topic control message — update header span, skip history card
        const notifType = notification.type || notification.notification_type;
        if ( notifType === 'session_topic' && notification.session_name ) {
            const parsed = this.parseSenderId( this.resolveSenderId( notification ) );
            if ( parsed.sessionId ) {
                this.saveSessionName( parsed.sessionId, notification.session_name, { fromServer: true } );
                this.refreshSessionNameDisplay( parsed.sessionId, notification.session_name );
            }
            this.log( `Session topic updated for ${parsed.sessionId}: ${notification.session_name}` );
            return;
        }

        // Approach D: Append user_initiated_message to live interaction pane on running job card
        if ( notifType === 'user_initiated_message' && notification.job_id ) {
            // Skip DOM append — optimistic render in sendJobMessage() already added the bubble
            return;
        }

        // Phase 2.2 SSE - Check if this is a response-required notification
        if ( notification.response_requested === true ) {
            this.log( `Response-required notification detected: ${notification.id}` );
            // Route to Action Required section (queue system handles activation and TTS)
            this.addActionRequiredNotification( notification );
            // Play sound unless suppress_ding is set (conversational TTS from queue)
            if ( notification.suppress_ding !== true ) {
                await this.playNotificationSoundByPriority( notification.priority );
            }

            // NOTE: TTS is now handled by activateNextNotification() when the notification
            // becomes active. This prevents simultaneous TTS playback when multiple
            // notifications arrive at once.

            return;  // Don't add to regular notifications list
        }

        // ========================================
        // Phase 6: Job-based notification routing
        // ========================================
        // If notification has job_id AND job is registered (active), route to job card
        // Session 105 FIX: Extract job_id from sender_id suffix if not explicitly provided
        // Pattern: sender_id ends with #<prefix>-<8hex> (e.g., deep.research@lupin.deepily.ai#dr-77b330d8)
        let jobId = notification.job_id;
        console.log( `[DIAG-JR] notification.job_id=${jobId} sender_id=${notification.sender_id} msg=${(notification.message||'').substring(0,60)}` );
        if ( !jobId && notification.sender_id ) {
            const senderIdMatch = notification.sender_id.match( /#([a-z]+-[a-f0-9]{8})$/ );
            if ( senderIdMatch ) {
                jobId = senderIdMatch[ 1 ];
                console.log( `[DIAG-JR] Fallback: extracted jobId=${jobId} from sender_id` );
            }
        }
        if ( jobId ) {
            const targetEl = document.getElementById( `interactions-content-${jobId}` );
            const allInteractions = document.querySelectorAll( '[id^="interactions-content-"]' );
            const existingIds = Array.from( allInteractions ).map( el => el.id );
            console.log( `[DIAG-JR] DOM lookup: interactions-content-${jobId} → ${targetEl ? 'FOUND' : 'MISSING'}` );
            if ( !targetEl ) {
                console.log( `[DIAG-JR] Existing interaction containers:`, existingIds );
            }
            // Session 107: Simplified - job_state_transition creates cards, we just route
            this.log( `[Session 107] Routing notification to job card: ${jobId}` );
            this.appendNotificationToJobCard( jobId, notification );

            // Play notification sound for high/urgent priority unless suppress_ding is set
            if ( notification.priority === "high" || notification.priority === "urgent" ) {
                if ( notification.suppress_ding !== true ) {
                    await this.playNotificationSoundByPriority( notification.priority );
                }

                // FIX (Session 98): Queue TTS for job-routed notifications
                // Job card context provides clarity, so play the raw message WITHOUT
                // the "Important! task notification:" prefix used for general notifications
                const notificationId = notification.id || notification.id_hash;
                // Phase 6 FIX: Job-card defaults to raw, but allow override via tts_raw: false
                const ttsMessage = notification.tts_raw === false
                    ? this.formatNotificationTTSMessage( notification )
                    : notification.message;
                this.log( `[Phase 6] Queuing job notification for TTS: "${ttsMessage}"` );

                // Add delay if notification sound played (to let it finish), otherwise queue immediately
                const delay = notification.suppress_ding ? 0 : 300;
                setTimeout( () => {
                    this.addToTTSQueue( {
                        id           : notificationId,
                        type         : 'job-card',
                        notification : notification,
                        ttsText      : ttsMessage,
                        addedAt      : Date.now()
                    } );
                }, delay );
            }

            return;  // Don't add to sender cards
        }

        // Regular fire-and-forget notification handling
        // 1. Play notification sound based on priority unless suppress_ding is set
        if ( notification.suppress_ding !== true ) {
            await this.playNotificationSoundByPriority( notification.priority );
        }

        // 2. High/urgent priority: Queue for TTS, add to project card when playback starts
        //    Low/medium priority: Add to project card immediately (no TTS)
        if ( notification.priority === "high" || notification.priority === "urgent" ) {
            // Phase 6 FIX: Check tts_raw flag - default to contextualized for backward compatibility
            const ttsMessage = notification.tts_raw === true
                ? notification.message
                : this.formatNotificationTTSMessage( notification );
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

    scheduleReconnect( target = 'both' ) {
        if ( this.isConnecting ) {
            return; // Already attempting to reconnect
        }

        this.connectionRetries++;
        // Exponential backoff: 2s, 4s, 8s, 16s, 30s... then cap at 60s after 10 failures
        const maxDelay = this.connectionRetries > 10 ? 60000 : 30000;
        const delay = Math.min( 1000 * Math.pow( 2, this.connectionRetries ), maxDelay );

        this.wsDiag( `Scheduling reconnect attempt #${this.connectionRetries} for ${target} in ${delay}ms` );

        setTimeout( () => {
            this.isConnecting = true;
            this.connectWebSockets( target ).finally( () => {
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

    /**
     * Read scheduling controls for a job submission form.
     *
     * Requires:
     *     - formPrefix matches the HTML id prefix (e.g. "research", "cc", "swe")
     *
     * Ensures:
     *     - returns object with scheduled_at (ISO string) and/or monopolize (true) when set
     *     - returns empty object when no scheduling options are selected
     */
    _getSchedulingParams( formPrefix ) {
        const params = {};
        const scheduleCheckbox   = document.getElementById( `${formPrefix}-schedule` );
        const scheduleTime       = document.getElementById( `${formPrefix}-scheduled-time` );
        const monopolizeCheckbox = document.getElementById( `${formPrefix}-monopolize` );

        if ( scheduleCheckbox?.checked && scheduleTime?.value ) {
            params.scheduled_at = new Date( scheduleTime.value ).toISOString();
        }
        if ( monopolizeCheckbox?.checked ) {
            params.monopolize = true;
        }
        return params;
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

        // Build URL with user_filter parameter for admins viewing filtered jobs
        let url = `/api/get-queue/${queueName}`;
        if ( this.isAdmin && this.queueFilterMode === 'all' ) {
            url += '?user_filter=*';  // Admin viewing all jobs
            this.log( `Admin mode: fetching ALL users' jobs for ${queueName}` );
        } else if ( this.isAdmin && this.queueFilterMode === 'others' ) {
            url += '?user_filter=!self';  // Admin viewing other users' jobs only
            this.log( `Admin mode: fetching OTHER users' jobs for ${queueName}` );
        } else {
            this.log( `Fetching own jobs only for ${queueName}` );
        }
        // Regular users and admins in 'own' mode: no parameter = own jobs only

        try {
            const response = await this.authedFetch( url );

            if ( !response.ok ) {
                throw new Error( `HTTP error! status: ${response.status}` );
            }

            const data = await response.json();
            this.log( `Data received for ${queueName}:`, data );
            
            // Update the appropriate list based on queue name
            // Also update the new progressive disclosure count badges
            // Session 107: Removed updateJobRegistration calls - job_state_transition handles routing
            // Session 128: Fixed field names - backend returns total_jobs, not {queue}_jobs arrays
            if ( queueName === "todo" ) {
                // Update count badge for progressive disclosure UI
                const countBadge = document.getElementById( "todo-count-badge" );
                if ( countBadge ) countBadge.textContent = data.total_jobs;
                this.queueCounts.todo = data.total_jobs;
                // Store metadata for progressive disclosure job cards
                this.queueCategoryState.todo.jobs = data.todo_jobs_metadata || [];
                // Also refresh job cards if category is expanded
                this.updateQueueCategoryIfExpanded( "todo", data.total_jobs );
            } else if ( queueName === "run" ) {
                const countBadge = document.getElementById( "run-count-badge" );
                if ( countBadge ) countBadge.textContent = data.total_jobs;
                this.queueCounts.run = data.total_jobs;
                // Store metadata for progressive disclosure job cards
                this.queueCategoryState.run.jobs = data.run_jobs_metadata || [];
                this.updateQueueCategoryIfExpanded( "run", data.total_jobs );
            } else if ( queueName === "done" ) {
                // Enhanced done queue handling with structured job metadata for replay functionality
                await this.handleDoneQueueUpdate( data );
                const countBadge = document.getElementById( "done-count-badge" );
                if ( countBadge ) countBadge.textContent = data.total_jobs;
                this.queueCounts.done = data.total_jobs;
                // Store metadata for progressive disclosure job cards
                this.queueCategoryState.done.jobs = data.done_jobs_metadata || [];
                this.updateQueueCategoryIfExpanded( "done", data.total_jobs );
            } else if ( queueName === "dead" ) {
                const countBadge = document.getElementById( "dead-count-badge" );
                if ( countBadge ) countBadge.textContent = data.total_jobs;
                this.queueCounts.dead = data.total_jobs;
                // Store metadata for progressive disclosure job cards
                this.queueCategoryState.dead.jobs = data.dead_jobs_metadata || [];
                this.updateQueueCategoryIfExpanded( "dead", data.total_jobs );
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
         *     - All three indicator locations update (toolbar, notifications header, queue header)
         *     - Filter preference persists in localStorage
         *     - All queues refresh and conversation history reloads with new filter applied
         *
         * Args:
         *     mode: 'own' (user's jobs only), 'others' (not user's jobs), or 'all' (all users' jobs)
         */
        if ( !this.isAdmin ) {
            this.warn( 'Only admin users can change filter mode' );
            return;
        }

        this.queueFilterMode = mode;

        // Mode display config
        const modeConfig = {
            own    : { icon: '👤', label: 'Mine',     displayText: 'Your jobs only' },
            others : { icon: '🚫', label: 'Not Mine', displayText: 'Other users\' jobs' },
            all    : { icon: '👥', label: 'All Users', displayText: 'All users\' jobs' }
        };

        const config = modeConfig[ mode ] || modeConfig.own;

        // Update filter panel button states
        document.getElementById( 'filter-own-jobs' ).classList.toggle( 'active', mode === 'own' );
        const othersBtn = document.getElementById( 'filter-others-jobs' );
        if ( othersBtn ) othersBtn.classList.toggle( 'active', mode === 'others' );
        document.getElementById( 'filter-all-jobs' ).classList.toggle( 'active', mode === 'all' );
        document.getElementById( 'filter-mode-display' ).textContent = config.displayText;

        // Update indicator Location 1: Notifications section header badge
        const notifBadge = document.getElementById( 'notifications-filter-badge' );
        if ( notifBadge ) {
            notifBadge.textContent = `${config.icon} ${config.label}`;
            notifBadge.setAttribute( 'data-mode', mode );
        }

        // Update indicator Location 2: Queue section header badge
        const queueBadge = document.getElementById( 'queues-filter-badge' );
        if ( queueBadge ) {
            queueBadge.textContent = `${config.icon} ${config.label}`;
            queueBadge.setAttribute( 'data-mode', mode );
        }

        // Save preference to localStorage
        localStorage.setItem( this.QUEUE_FILTER_PREF_KEY, mode );

        // Refresh all queues and reload conversation history with new filter
        this.log( `Filter mode changed to: ${mode} - refreshing queues and notifications` );
        this.refreshAllQueues();
        this.clearSenderGroups();  // Clear existing sender cards before reloading with new filter
        this.loadConversationHistory();
    }

    showAndScrollToFilterPanel() {
        /**
         * Show the filter settings panel and scroll it into view.
         *
         * Called when clicking the filter mode badges in section headers.
         * Ensures the filter panel is visible (removes section-hidden),
         * activates the toolbar button, and smooth-scrolls to the panel.
         */
        const filterSection = document.getElementById( 'filter-settings-section' );
        const filterBtn = document.querySelector( '.toolbar-btn[data-section="filter-settings-section"]' );

        if ( !filterSection ) return;

        // Show the section if hidden
        filterSection.classList.remove( 'section-hidden' );
        if ( filterBtn ) filterBtn.classList.add( 'active' );
        this.saveSectionVisibility();

        // Scroll to filter panel
        this.scrollIntoViewIfNeeded( filterSection );
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
         *     - Admin users see filter panel + header badge indicators
         *     - Admin filter preference loaded from localStorage (default: 'own')
         *     - UI button states and all indicators match current filter mode
         *     - Filter mode defaulted to 'own' for regular users
         */
        const filterSection      = document.getElementById( 'filter-settings-section' );
        const notifFilterBadge   = document.getElementById( 'notifications-filter-badge' );
        const queuesFilterBadge  = document.getElementById( 'queues-filter-badge' );

        if ( this.isAdmin ) {
            // Show filter panel and header badges for admins
            filterSection.style.display = 'block';
            if ( notifFilterBadge )  notifFilterBadge.style.display  = 'inline-flex';
            if ( queuesFilterBadge ) queuesFilterBadge.style.display = 'inline-flex';

            // Load saved preference or default to 'own'
            const savedFilter = localStorage.getItem( this.QUEUE_FILTER_PREF_KEY );
            const validModes = [ 'own', 'others', 'all' ];
            this.queueFilterMode = validModes.includes( savedFilter ) ? savedFilter : 'own';

            // Use setFilterMode to update both indicator locations consistently
            this.setFilterMode( this.queueFilterMode );

            this.log( `Admin filter UI initialized - mode: ${this.queueFilterMode}` );
        } else {
            // Hide for regular users
            filterSection.style.display = 'none';
            if ( notifFilterBadge )  notifFilterBadge.style.display  = 'none';
            if ( queuesFilterBadge ) queuesFilterBadge.style.display = 'none';
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
         *     - All four live queues (todo, run, done, dead) are refreshed
         *     - Job history refreshed if currently expanded
         *     - Fetches use current queueFilterMode setting
         *     - Errors logged but don't block other queues
         */
        this.log( 'Refreshing all queue lists...' );
        try {
            // Fetch live queues first — loadJobHistory() reads queueCategoryState.done/dead
            // to build exclude_ids. Running history in parallel with the live fetches
            // races: history may be queried while done/dead are still empty, so
            // exclude_ids is never sent and completed jobs appear in both panels.
            await Promise.all( [
                this.updateQueueLists( 'todo' ),
                this.updateQueueLists( 'run' ),
                this.updateQueueLists( 'done' ),
                this.updateQueueLists( 'dead' )
            ] );

            if ( this.queueCategoryState.history.expanded ) {
                await this.loadJobHistory();
            }
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
         *     - queueName is 'todo', 'run', 'done', 'dead', or 'history'
         *
         * Ensures:
         *     - Category container visibility toggles
         *     - First expansion triggers lazy load of job cards
         *     - History category routes to loadJobHistory() instead of loadQueueJobCards()
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
                if ( queueName === 'history' ) {
                    this.loadJobHistory();
                } else {
                    this.loadQueueJobCards( queueName );
                }
            }
        } else {
            container.classList.add( 'collapsed' );
            expandBtn.textContent = '▶';
        }

        this.log( `Queue category ${queueName} ${state.expanded ? 'expanded' : 'collapsed'}` );

        // Persist expand/collapse state to localStorage
        this.saveQueueExpandState();
    }

    updateQueueCategoryIfExpanded( queueName, count ) {
        /**
         * Refresh job cards if queue category is currently expanded.
         *
         * Called from updateQueueLists() when WebSocket update arrives.
         */
        const state = this.queueCategoryState[ queueName ];

        // ALWAYS mark as needing reload when new data arrives
        // This ensures collapsed sections re-render on next expansion
        // (Bug fix: Session 105 - job cards not appearing after expand)
        state.loaded = false;

        // If expanded, immediately reload job cards to reflect changes
        if ( state.expanded ) {
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

            const response = await this.authedFetch( url );

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

            // Session 107: Removed updateJobRegistration - job_state_transition handles routing

            // Update count badge - use metadata length (API returns *_jobs_metadata, not *_jobs)
            if ( countBadge ) countBadge.textContent = jobsMetadata.length;

            // Render job cards - check metadata, not the non-existent jobsHtml
            if ( jobsMetadata.length === 0 ) {
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

    // ═══════════════════════════════════════════════════════════════════════
    // JOB HISTORY — PostgreSQL-backed persistent job history
    //
    // OVERLAY MODEL: The live queue (Done/Dead) shows jobs from the CURRENT
    // server session only (in-memory). Job History queries PostgreSQL for ALL
    // persisted agentic jobs. To avoid duplicates, we collect job IDs from
    // the live Done and Dead queues and pass them as `exclude_ids` to the API.
    //
    // This means: a job appears in EITHER the live queue OR history, never
    // both. When the server restarts, previously-live jobs move to history
    // automatically (they are no longer in memory).
    // ═══════════════════════════════════════════════════════════════════════

    async loadJobHistory( append = false ) {
        /**
         * Fetch and render job history cards from PostgreSQL persistence.
         *
         * Requires:
         *     - Authentication is established
         *     - queueCategoryState.history is initialized
         *
         * Ensures:
         *     - Fetches from /api/job-history with time window + exclude_ids
         *     - Live Done/Dead job IDs excluded to prevent duplicates
         *     - Cards rendered with management actions (delete, retry)
         *     - Pagination via "Load More" button
         */
        const state      = this.queueCategoryState.history;
        const container  = document.getElementById( 'history-jobs-container' );
        const countBadge = document.getElementById( 'history-count-badge' );

        if ( !container ) return;

        try {
            // Collect live Done/Dead job IDs for deduplication
            const liveJobIds = [
                ...( this.queueCategoryState.done.jobs || [] ).map( j => j.job_id ),
                ...( this.queueCategoryState.dead.jobs || [] ).map( j => j.job_id )
            ].filter( Boolean );

            // Build URL with filters
            const params = new URLSearchParams();
            if ( state.timeWindow !== 'all' ) params.set( 'days', state.timeWindow );
            params.set( 'limit', '20' );
            params.set( 'offset', append ? state.offset : '0' );
            if ( liveJobIds.length > 0 ) params.set( 'exclude_ids', liveJobIds.join( ',' ) );

            const response = await this.authedFetch( `/api/job-history?${params}` );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            const data = await response.json();

            if ( append ) {
                state.jobs = [ ...state.jobs, ...data.jobs ];
            } else {
                state.jobs = data.jobs;
            }
            state.total  = data.total;
            state.offset = state.jobs.length;
            state.loaded = true;

            // Update badge
            if ( countBadge ) countBadge.textContent = data.total;

            // Render
            if ( state.jobs.length === 0 ) {
                container.innerHTML = '<div class="queue-empty-message">No job history found</div>';
            } else {
                container.innerHTML = state.jobs.map( job => this.renderHistoryCard( job ) ).join( '' );
            }

            // Show/hide Load More
            const pagination = document.getElementById( 'history-pagination' );
            if ( pagination ) {
                pagination.style.display = state.jobs.length < state.total ? 'block' : 'none';
            }

        } catch ( error ) {
            this.error( 'Error loading job history:', error );
            container.innerHTML = '<div class="queue-error-message">Error loading job history</div>';
        }
    }

    renderHistoryCard( job ) {
        /**
         * Render a history-pane job card.
         *
         * After the 2026-04-26 unification (A1+B+C), this is a thin splicer:
         * `/api/job-history` returns the same flat shape as `/api/get-queue/done`
         * (per src/cosa/rest/job_persistence.py:_build_history_row), so no
         * adapter normalization is needed here. We just normalize `job_id`
         * (history rows use `id_hash` as primary key but the response now also
         * sets `job_id` for parity), call the unified renderer with
         * queueName='history', and splice the prominent history-specific
         * action buttons (Delete / Retry) at card close.
         *
         * Requires:
         *     - job is a flat dict from /api/job-history (Phase 1 shape, 2026-04-26+)
         *
         * Ensures:
         *     - Returns full card HTML rendered via the unified renderJobCard path
         *     - Appends management action buttons (delete, optional retry)
         */
        // Render using the unified renderer with queueName='history'.
        // renderJobCard's queueName-driven branches handle history-aware
        // behavior (completion badges, interactions indicator, delete routing).
        let cardHtml = this.renderJobCard( job, 'history' );

        // Inject management action buttons before the last closing </div> of the card.
        // These are the prominent styled "🗑 Delete" / "↻ Retry" buttons distinct
        // from the small ✕ in the card header. Kept as a splice (rather than inlined
        // into renderJobCard) to preserve their visual UX placement at card-bottom.
        const actionsHtml = this.renderHistoryActions( job );
        const lastDivClose = cardHtml.lastIndexOf( '</div>' );
        if ( lastDivClose > 0 ) {
            cardHtml = cardHtml.substring( 0, lastDivClose ) + actionsHtml + cardHtml.substring( lastDivClose );
        }

        return cardHtml;
    }

    renderHistoryActions( job ) {
        /**
         * Render management action buttons for a history job card.
         *
         * Requires:
         *     - job has id_hash and status fields
         *
         * Ensures:
         *     - Delete button always shown (invokes deleteHistoryJob)
         *     - Retry button shown only for failed/interrupted jobs
         *     - Buttons use stopPropagation to prevent card toggle
         */
        const canRetry     = [ 'failed', 'interrupted' ].includes( job.status );
        const questionSafe = ( job.question_text || '' ).replace( /'/g, "\\'" ).replace( /"/g, '&quot;' ).substring( 0, 100 );

        const retryBtn = canRetry
            ? `<button class="history-action-btn retry-btn"
                    onclick="event.stopPropagation(); window.notificationsUI.retryHistoryJob( '${job.id_hash}', '${questionSafe}' )"
                    >↻ Retry</button>`
            : '';

        const deleteBtn = `<button class="history-action-btn delete-btn"
                    onclick="event.stopPropagation(); window.notificationsUI.deleteHistoryJob( '${job.id_hash}' )"
                    >🗑 Delete</button>`;

        return `
            <div class="history-action-buttons">
                ${retryBtn}${deleteBtn}
            </div>
        `;
    }

    _dispatchDelete( jobId, queueName ) {
        /**
         * Single chokepoint for card-level delete actions.
         *
         * Looks up the appropriate handler in DELETE_HANDLERS by queueName and
         * invokes it. Replaces the prior `job._isHistory` ternary that branched
         * inline in renderJobCard's HTML template — keeps the lookup private to
         * the class and makes future logging/instrumentation a one-liner.
         *
         * Requires:
         *     - jobId: string (the job's id_hash; for history this is the row id)
         *     - queueName: one of 'todo', 'run', 'done', 'dead', 'history'
         *
         * Ensures:
         *     - On valid queueName, invokes the registered handler
         *     - On unknown queueName, logs an error and is a no-op
         */
        const handler = DELETE_HANDLERS[ queueName ];
        if ( !handler ) {
            console.error( `[Notifications ERROR] No delete handler for queueName=${queueName}` );
            return;
        }
        handler( jobId, queueName );
    }

    async deleteHistoryJob( jobId ) {
        /**
         * Delete a job from PostgreSQL history.
         *
         * Requires:
         *     - jobId is a valid id_hash string
         *     - User is authenticated (admin or job owner)
         *
         * Ensures:
         *     - Prompts user for confirmation before deleting
         *     - Sends DELETE /api/job-history/{jobId}
         *     - Removes from local state and re-renders on success
         */
        if ( !confirm( 'Delete this job from history?' ) ) return;

        try {
            const response = await this.authedFetch( `/api/job-history/${jobId}`, {
                method : 'DELETE'
            } );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            // Remove from local state and re-render
            const state = this.queueCategoryState.history;
            state.jobs  = state.jobs.filter( j => j.id_hash !== jobId );
            state.total = Math.max( 0, state.total - 1 );
            this.loadJobHistory();

        } catch ( error ) {
            this.error( 'Error deleting job:', error );
            alert( 'Failed to delete job from history' );
        }
    }

    async deleteQueueJob( jobId, queueName ) {
        /**
         * Forcefully remove a job from an in-memory queue (todo, run, done, dead).
         *
         * Requires:
         *     - jobId is a valid job ID string
         *     - queueName is 'todo', 'run', 'done', or 'dead'
         *     - User is authenticated (admin or job owner)
         *
         * Ensures:
         *     - Prompts user for confirmation before removing
         *     - Sends DELETE /api/queue/{queueName}/{jobId}
         *     - Removes card from DOM and updates count badge on success
         */
        const label = queueName === 'run' ? 'running' : queueName;
        if ( !confirm( `Remove this job from the ${label} queue?` ) ) return;

        try {
            const response = await this.authedFetch( `/api/queue/${queueName}/${jobId}`, {
                method : 'DELETE'
            } );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            // Remove card from DOM
            const card = document.getElementById( `job-card-${jobId}` );
            if ( card ) card.remove();

            // Update local count badge
            this.queueCounts[ queueName ] = Math.max( 0, ( this.queueCounts[ queueName ] || 0 ) - 1 );
            this.updateQueueCountBadge( queueName, this.queueCounts[ queueName ] );
            this.updateQueueEmptyMessage( queueName );

            this.log( `[DELETE] Job ${jobId} removed from ${queueName} queue` );

        } catch ( error ) {
            this.error( `Error removing job from ${queueName} queue:`, error );
            alert( `Failed to remove job from ${label} queue` );
        }
    }

    async deleteAllQueueJobs( queueName ) {
        /**
         * Bulk delete all jobs from a queue pane (todo, run, done, dead, or history).
         *
         * Requires:
         *     - queueName is 'todo', 'run', 'done', 'dead', or 'history'
         *     - User is authenticated
         *
         * Ensures:
         *     - Prompts user for confirmation with job count and, for 'run', a
         *       cancellation warning
         *     - Sends DELETE /api/queue/{queueName}/all  OR
         *              DELETE /api/job-history/all?days={N}
         *     - Refreshes the pane and resets count badge on success
         */
        let count, confirmMsg, url;

        if ( queueName === 'history' ) {
            const state    = this.queueCategoryState && this.queueCategoryState.history;
            count          = ( state && state.total ) || 0;
            const select   = document.getElementById( 'history-time-window' );
            const days     = select ? select.value : 'all';
            const dayLabel = days === 'all' ? 'all time' : `last ${days} day${days === '1' ? '' : 's'}`;
            confirmMsg     = `Delete all ${count} history entries from ${dayLabel}?`;
            const daysParam = days === 'all' ? 'all' : days;
            url            = `/api/job-history/all?days=${daysParam}`;
        } else {
            count          = ( this.queueCounts && this.queueCounts[ queueName ] ) || 0;
            const label    = queueName === 'run' ? 'running' : queueName;
            confirmMsg     = queueName === 'run'
                ? `Cancel and remove all ${count} running job${count === 1 ? '' : 's'}? This will interrupt active jobs.`
                : `Remove all ${count} job${count === 1 ? '' : 's'} from the ${label} queue?`;
            url            = `/api/queue/${queueName}/all`;
        }

        if ( !confirm( confirmMsg ) ) return;

        try {
            const response = await this.authedFetch( url, { method: 'DELETE' } );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            if ( queueName === 'history' ) {
                this.loadJobHistory();
            } else {
                this.queueCounts[ queueName ] = 0;
                this.updateQueueCountBadge( queueName, 0 );
                this.loadQueueJobCards( queueName );
            }

            this.log( `[DELETE ALL] ${queueName} queue cleared` );

        } catch ( error ) {
            this.error( `Error clearing ${queueName} queue:`, error );
            alert( `Failed to clear ${queueName} queue` );
        }
    }

    async retryHistoryJob( jobId, questionText ) {
        /**
         * Retry a failed/interrupted job by re-submitting to the todo queue.
         *
         * Requires:
         *     - jobId is a valid id_hash of a failed/interrupted job
         *     - questionText is the original question for display
         *     - Active WebSocket connection with valid websocketId
         *
         * Ensures:
         *     - Prompts user for confirmation before retrying
         *     - Sends POST /api/job-history/{jobId}/retry with websocket_id
         *     - Refreshes history and live queues on success
         */
        if ( !confirm( `Retry this job?\n\n"${questionText}"` ) ) return;

        try {
            const response = await this.authedFetch( `/api/job-history/${jobId}/retry`, {
                method  : 'POST',
                headers : { 'Content-Type': 'application/json' },
                body    : JSON.stringify( { websocket_id: this.queueSessionId } )
            } );

            if ( !response.ok ) throw new Error( `HTTP ${response.status}` );

            const data = await response.json();
            this.log( `Job retried: ${JSON.stringify( data )}` );

            // Refresh history and live queues
            this.loadJobHistory();
            this.refreshAllQueues();

        } catch ( error ) {
            this.error( 'Error retrying job:', error );
            alert( 'Failed to retry job' );
        }
    }

    onHistoryTimeWindowChange( value ) {
        /**
         * Handle time window dropdown change.
         *
         * Requires:
         *     - value is '7', '14', '30', or 'all'
         *
         * Ensures:
         *     - Updates state.timeWindow
         *     - Reloads history if section is expanded
         *     - Marks as unloaded if collapsed (will reload on next expand)
         */
        const state = this.queueCategoryState.history;
        state.timeWindow = value === 'all' ? 'all' : parseInt( value );
        state.offset = 0;
        if ( state.expanded ) {
            this.loadJobHistory();
        } else {
            state.loaded = false;
        }
    }

    loadMoreHistory() {
        /**
         * Load next page of history results (append mode).
         */
        this.loadJobHistory( true );
    }

    extractQuestionFromHtml( html ) {
        /**
         * Extract question text from job HTML string.
         * HTML format: "<li id='hash'>...Q: question text...</li>"
         */
        const match = html.match( /Q:\s*([^<]+)/ );
        return match ? match[ 1 ].trim() : 'Unknown question';
    }

    // ========================================
    // ========================================
    // JOB CARD HELPERS (Session 107: Simplified after job_state_transition refactor)
    // ========================================

    cleanupRunQueueCard( jobId ) {
        /**
         * Remove a job card from the run queue and stop its timer.
         * Called when job moves from run to done/dead queue.
         *
         * Requires:
         *     - jobId is a valid job ID string
         *
         * Ensures:
         *     - Job card is removed from run queue container
         *     - Empty message shown if container becomes empty
         */
        // Remove the card from run queue
        const container = document.getElementById( 'run-jobs-container' );
        if ( !container ) return;

        const card = container.querySelector( `.job-card[data-job-id="${jobId}"]` );
        if ( card ) {
            card.remove();
            this.log( `[Phase 6] Removed run queue card for completed job: ${jobId}` );

            // If container is now empty, show empty message
            if ( container.querySelectorAll( '.job-card' ).length === 0 ) {
                container.innerHTML = '<div class="queue-empty-message">No jobs in this queue</div>';
            }
        }
    }

    updateJobCardMetadata( jobId, metadata, queueName ) {
        /**
         * Update a job card with full metadata while preserving activity log.
         *
         * Requires:
         *     - jobId is a valid job ID string
         *     - metadata is the full job metadata from server
         *     - queueName is the queue containing the job
         *
         * Ensures:
         *     - Job card is updated with full metadata (question, timestamp, etc.)
         *     - Activity log entries are preserved
         *     - Duration timer is started if in run queue
         */
        const container = document.getElementById( `${queueName}-jobs-container` );
        if ( !container ) return;

        const oldCard = container.querySelector( `.job-card[data-job-id="${jobId}"]` );
        if ( !oldCard ) {
            this.log( `[Phase 6] No existing card to update for ${jobId}` );
            return;
        }

        // Preserve unified conversation content
        const oldContent = oldCard.querySelector( '.interactions-content' );
        const conversationHtml = oldContent ? oldContent.innerHTML : null;

        // Render new card with full metadata
        const newCardHtml = this.renderJobCard( metadata, queueName );

        // Replace old card
        oldCard.outerHTML = newCardHtml;

        // Restore conversation content if it existed
        if ( conversationHtml ) {
            const newContent = document.getElementById( `interactions-content-${jobId}` );
            if ( newContent ) {
                newContent.innerHTML = conversationHtml;
            }
        }

        this.log( `[Phase 6] Updated job card with full metadata: ${jobId}` );
    }

    appendNotificationToJobCard( jobId, notification ) {
        /**
         * Append a notification to a job card's unified conversation container.
         * Writes directly to interactions-content-${jobId} (newest first).
         * Progress Group: If progress_group_id is set, updates existing entry in-place.
         *
         * Requires:
         *     - jobId is a valid job ID string
         *     - notification has message, priority, timestamp
         *
         * Ensures:
         *     - Finds interactions-content container by ID
         *     - If progress_group_id: updates existing entry in-place (or creates first)
         *     - If no progress_group_id: inserts entry at top (newest first)
         *     - Auto-expands job card if collapsed
         */
        // Find the unified conversation container
        const contentEl = document.getElementById( `interactions-content-${jobId}` );

        if ( !contentEl ) {
            this.log( `[Phase 6] interactions-content not found for ${jobId}` );
            return;
        }

        // Progress group: update existing entry in-place if one exists
        const groupId = notification.progress_group_id;
        if ( groupId ) {
            const existing = contentEl.querySelector( `[data-progress-group="${groupId}"]` );
            if ( existing ) {
                this.updateProgressGroupEntry( existing, notification );
                return;
            }
        }

        // User-initiated messages → right-justified blue chat bubble (same as appendJobUserMessage)
        const notifType = notification.type || notification.notification_type;
        if ( notifType === 'user_initiated_message' ) {
            const ts = notification.timestamp
                ? new Date( notification.timestamp ).toLocaleTimeString()
                : new Date().toLocaleTimeString();
            const urgentClass = notification.priority === 'urgent' ? ' priority-urgent' : '';
            const priorityBadge = notification.priority === 'urgent' ? ' <strong>[URGENT]</strong>' : '';
            const entry = document.createElement( 'div' );
            entry.className = `sender-message outgoing${urgentClass}`;
            entry.innerHTML = `
                <span class="message-time">${ts}${priorityBadge}</span>
                <span class="message-text">${this.renderMarkdownInline( notification.message )}</span>
            `;
            contentEl.insertBefore( entry, contentEl.firstChild );
            if ( !this.expandedJobCards.has( jobId ) ) {
                this.expandJobCard( jobId );
            }
            entry.scrollIntoView( { behavior: 'smooth', block: 'nearest' } );
            this.log( `[Phase 6] User message appended to job ${jobId}: ${notification.message.substring( 0, 50 )}...` );
            return;
        }

        // Create notification entry
        const entry = this.createActivityLogEntry( notification );

        // Tag with progress group ID if present (first occurrence)
        if ( groupId ) {
            entry.setAttribute( 'data-progress-group', groupId );
            entry.classList.add( 'progress-group-entry' );
            entry.setAttribute( 'data-progress-group-count', '1' );

            // Wrap existing content in progress-group-head div
            const headDiv = document.createElement( 'div' );
            headDiv.className = 'progress-group-head';
            while ( entry.firstChild ) {
                headDiv.appendChild( entry.firstChild );
            }
            entry.appendChild( headDiv );

            // Add proxy ratification link for proxy progress groups
            const proxyLink = this.createProxyRatifyLink( groupId );
            if ( proxyLink ) {
                headDiv.appendChild( proxyLink );
            }
        }

        // Insert at top (newest first)
        contentEl.insertBefore( entry, contentEl.firstChild );

        // Auto-expand interactions section if collapsed
        if ( contentEl.classList.contains( 'collapsed' ) ) {
            contentEl.classList.remove( 'collapsed' );
            const sectionEl = contentEl.closest( '.job-interactions-section' );
            const expandBtn = sectionEl?.querySelector( '.interactions-expand-btn' );
            if ( expandBtn ) expandBtn.textContent = '▼';
            const sendMsgEl = sectionEl?.querySelector( '.job-send-message' );
            if ( sendMsgEl ) sendMsgEl.classList.remove( 'collapsed' );
        }

        // Auto-expand job card to show new notification
        if ( !this.expandedJobCards.has( jobId ) ) {
            this.expandJobCard( jobId );
        }

        // Scroll to show new entry
        entry.scrollIntoView( { behavior: 'smooth', block: 'nearest' } );

        this.log( `[Phase 6] Notification appended to job ${jobId}: ${notification.message.substring( 0, 50 )}...` );
    }

    updateProgressGroupEntry( element, notification ) {
        /**
         * Update an existing progress group entry with history accumulation.
         *
         * Requires:
         *     - element is a DOM element with data-progress-group attribute
         *     - notification has message, timestamp
         *
         * Ensures:
         *     - Moves current head message into history container (newest first)
         *     - Sets new message + timestamp as head
         *     - Increments counter, updates toggle text
         *     - Preserves expanded/collapsed toggle state
         *     - Triggers CSS pulse animation on head
         */
        const head = element.querySelector( '.progress-group-head' );
        if ( !head ) return;

        // Read current head values before overwriting
        const oldMessageSpan = head.querySelector( '.activity-message' );
        const oldTimestampSpan = head.querySelector( '.activity-timestamp' );
        const oldMessage = oldMessageSpan ? oldMessageSpan.textContent : '';
        const oldTimestamp = oldTimestampSpan ? oldTimestampSpan.textContent : '';

        // Create history entry from old head values
        const historyEntry = document.createElement( 'div' );
        historyEntry.className = 'progress-history-entry';
        historyEntry.innerHTML = `
            <span class="activity-timestamp">${this.escapeHtml( oldTimestamp )}</span>
            <span class="activity-message">${this.escapeHtml( oldMessage )}</span>
        `;

        // Get or create history container
        let history = element.querySelector( '.progress-group-history' );
        if ( !history ) {
            history = document.createElement( 'div' );
            history.className = 'progress-group-history';
            history.style.display = 'none';
            element.appendChild( history );
        }

        // Prepend old head to history (newest first)
        history.insertBefore( historyEntry, history.firstChild );

        // Update head with new notification values
        if ( oldMessageSpan ) {
            oldMessageSpan.textContent = this.escapeHtml( notification.message );
        }
        if ( oldTimestampSpan ) {
            const timestamp = notification.timestamp
                ? new Date( notification.timestamp ).toLocaleTimeString()
                : new Date().toLocaleTimeString();
            oldTimestampSpan.textContent = timestamp;
        }

        // Increment counter
        let count = parseInt( element.getAttribute( 'data-progress-group-count' ) || '1', 10 ) + 1;
        element.setAttribute( 'data-progress-group-count', String( count ) );

        // Find or create toggle (replaces old counter badge)
        let toggle = element.querySelector( '.progress-group-toggle' );
        if ( !toggle ) {
            toggle = document.createElement( 'span' );
            toggle.className = 'progress-group-toggle';
            toggle.title = 'Show history';
            head.appendChild( toggle );
        }

        // Update toggle text — preserve expanded/collapsed state
        const isExpanded = history.style.display !== 'none';
        const chevron = isExpanded ? '&#9650;' : '&#9660;';
        toggle.innerHTML = `${chevron} #${count}`;

        // Trigger CSS pulse animation on head
        head.classList.remove( 'progress-group-updated' );
        void head.offsetWidth;
        head.classList.add( 'progress-group-updated' );
    }

    /**
     * Create a proxy ratification link element for proxy progress group notifications.
     *
     * @param {string} groupId - The progress group ID (must start with 'pr-')
     * @returns {HTMLAnchorElement} - The link element, or null if not a proxy group
     */
    createProxyRatifyLink( groupId ) {
        if ( !groupId || !groupId.startsWith( 'pr-' ) ) return null;

        const link = document.createElement( 'a' );
        link.className = 'proxy-ratify-link';
        link.href = '#';
        link.textContent = 'Open Ratification →';
        link.setAttribute( 'data-batch-id', groupId );

        const self = this;
        link.onclick = async function( e ) {
            e.preventDefault();

            // 1. Call acknowledge endpoint to retire this batch
            try {
                const response = await fetch( '/api/proxy/acknowledge', {
                    method  : 'POST',
                    headers : self.getAuthHeaders()
                });
                if ( !response.ok ) {
                    console.warn( '[PROXY] Acknowledge response not OK:', response.status );
                }
            } catch ( err ) {
                console.warn( '[PROXY] Acknowledge failed:', err );
            }

            // 2. Gray out this element + add checkmark
            const entry = this.closest( '.progress-group-entry' );
            if ( entry ) {
                entry.classList.add( 'progress-batch-retired' );
                const head = entry.querySelector( '.progress-group-head' );
                if ( head ) {
                    const check = document.createElement( 'span' );
                    check.className = 'batch-retired-indicator';
                    check.textContent = ' ✅';
                    head.appendChild( check );
                }
                // Remove the link itself
                this.remove();
            }

            // 3. Open (or focus) ratification page in single tab
            window.open( '/app/admin/proxy-ratify', 'lupin-proxy-ratify' );
        };

        return link;
    }

    createActivityLogEntry( notification ) {
        /**
         * Create a single activity log entry from a notification.
         *
         * Returns:
         *     - DOM element for activity log entry
         */
        const entry = document.createElement( 'div' );
        entry.className = `activity-log-entry priority-${notification.priority || 'low'}`;

        const timestamp = notification.timestamp
            ? new Date( notification.timestamp ).toLocaleTimeString()
            : new Date().toLocaleTimeString();

        // Abstract indicator — clickable 📋 that opens the abstract tooltip
        const hasAbstract = notification.abstract && notification.abstract.trim().length > 0;
        const abstractHtml = hasAbstract
            ? ` <span class="abstract-indicator" data-abstract="${encodeURIComponent( notification.abstract )}" title="View details">📋</span>`
            : '';

        entry.innerHTML = `
            <span class="activity-timestamp">${timestamp}</span>
            <span class="activity-message">${this.escapeHtml( notification.message )}${abstractHtml}</span>
        `;

        return entry;
    }

    // Session 107: Removed cacheJobNotification, createProvisionalJobRegistration,
    // ensureJobCardExists, scheduleQueueRefreshForJob - job_state_transition handles this now

    inferAgentTypeFromJobId( jobId ) {
        /**
         * Infer agent type from job ID prefix.
         *
         * Requires:
         *     - jobId is a string in format 'prefix-hexhash' (e.g., 'dr-a1b2c3d4')
         *
         * Ensures:
         *     - Returns agent type string based on known prefixes
         *     - Returns 'unknown' for unrecognized prefixes
         */
        if ( !jobId || typeof jobId !== 'string' ) {
            return 'unknown';
        }

        const prefix = jobId.split( '-' )[ 0 ];
        const prefixMap = {
            'dr'   : 'Deep Research',
            'pg'   : 'Podcast Generator',
            'd2p'  : 'Deep Research → Podcast',
            'swe'  : 'SWE Team',
            'mock' : 'Mock Agent'
        };

        return prefixMap[ prefix ] || 'unknown';
    }

    expandJobCard( jobId ) {
        /**
         * Auto-expand a job card to show activity.
         */
        const jobCard = document.querySelector( `.job-card[data-job-id="${jobId}"]` );
        if ( !jobCard ) return;

        const details = jobCard.querySelector( '.job-card-details' );
        const expandBtn = jobCard.querySelector( '.job-expand-btn' );

        if ( details && details.classList.contains( 'collapsed' ) ) {
            details.classList.remove( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▼';
            this.expandedJobCards.add( jobId );
        }
    }

    /**
     * Render cost summary content HTML.
     * Session 107: Helper for placeholder-based rendering.
     *
     * @param {Object} costSummary - Cost summary object with total_cost_usd, total_input_tokens, total_output_tokens
     * @param {number} durationSeconds - Optional job duration in seconds
     * @returns {string} HTML content for cost summary div
     */
    renderCostSummaryContent( costSummary, durationSeconds ) {
        const cost = costSummary.total_cost_usd || 0;
        const duration = durationSeconds ? this.formatDuration( durationSeconds ) : 'N/A';
        const tokens = ( costSummary.total_input_tokens || 0 ) + ( costSummary.total_output_tokens || 0 );

        return `
            <div class="cost-header">💰 Cost Breakdown</div>
            <div class="cost-grid">
                <span class="cost-label">Total Cost:</span>
                <span class="cost-value">$${cost.toFixed( 4 )}</span>
                <span class="cost-label">Duration:</span>
                <span class="cost-value">${duration}</span>
                <span class="cost-label">Tokens:</span>
                <span class="cost-value">${tokens.toLocaleString()}</span>
            </div>
        `;
    }

    /**
     * Render abstract section HTML.
     * Session 108: Helper for consistent rendering between WebSocket and server-fetched cards.
     *
     * @param {string} abstract - Abstract text to render
     * @returns {string} HTML content for abstract section
     */
    renderAbstractSection( abstract ) {
        if ( !abstract ) return '';
        return `
            <div class="abstract-header">📄 Summary</div>
            <div class="abstract-content">${this.renderMarkdown( abstract )}</div>
        `;
    }

    /**
     * Render report link section HTML.
     * Session 108: Helper for consistent rendering between WebSocket and server-fetched cards.
     *
     * @param {string} reportPath - Path to the report file
     * @returns {string} HTML content for report link section
     */
    renderReportLinkSection( reportPath, agentType, yamlPath, remediationPath, pptxPath ) {
        if ( !reportPath ) return '';
        let html = `<a href="/app/docs?path=${encodeURIComponent( reportPath )}" target="_blank" class="report-link-btn">📋 View Full Report</a>`;
        if ( remediationPath ) {
            html += ` <a href="/app/docs?path=${encodeURIComponent( remediationPath )}" target="_blank" class="report-link-btn">🔧 Remediation Snapshot</a>`;
        }
        // Re-render button for presentation jobs with existing YAML
        if ( agentType === 'presentation' && yamlPath ) {
            html += ` <button class="report-link-btn rerender-btn" onclick="window.notificationsUI.submitRerender( '${this.escapeHtml( yamlPath )}' )" title="Re-render from YAML (Phases 6-8 only)">🔄 Re-render</button>`;
        }
        // PPTX download button for presentation jobs
        if ( pptxPath ) {
            html += ` <a href="/api/io/file?path=${encodeURIComponent( pptxPath )}&download=true" class="report-link-btn">📊 Download PPTX</a>`;
        }
        return html;
    }

    /**
     * Debug utility to dump job card DOM for comparison.
     * Session 108: Helps verify WebSocket vs server-fetched card consistency.
     *
     * Usage: window.notificationsUI.debugDumpJobCard( 'dr-a0ebba60' )
     *
     * @param {string} jobId - The job ID to inspect
     */
    debugDumpJobCard( jobId ) {
        const card = document.querySelector( `.job-card[data-job-id="${jobId}"]` );
        if ( !card ) {
            console.warn( `Job card not found: ${jobId}` );
            return;
        }
        const container = card.closest( '.queue-jobs-container' );
        const queue = container?.id?.replace( '-jobs-container', '' ) || 'unknown';
        console.group( `Job Card: ${jobId} (${queue} queue)` );
        console.log( 'Outer HTML:' );
        console.log( card.outerHTML );
        console.log( 'Classes:', card.className );
        console.log( 'Data attributes:', { ...card.dataset } );
        console.groupEnd();
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
         *     - Running jobs: status line, duration timer, activity log
         *     - Done jobs: abstract, report link, cost summary, completion badge
         */
        const statusClass = `status-${queueName}`;
        const truncatedQuestion = this.truncateText( job.question_text || 'No question', 60 );
        const agentBadge = job.agent_type ? `<span class="agent-badge">${( job.agent_type || '' ).replace( 'Agent', '' )}</span>` : '';
        const ownerBadge = ( this.isAdmin && this.queueFilterMode !== 'own' && job.user_email )
            ? `<span class="owner-badge">${this.escapeHtml( job.user_email )}</span>`
            : '';
        const cacheHitBadge = job.is_cache_hit ? '<span class="cache-hit-badge" title="Result from cache">⚡ Cached</span>' : '';
        const timestamp = this.formatJobTimestamp( job.timestamp );
        const jobId = job.job_id || `job-${Date.now()}`;
        // Display-only: show the prefix before "::" (our canonical compound
        // split point) — e.g. "bfe-a1b2c3d4::<uuid>" renders as
        // "bfe-a1b2c3d4". If that prefix is still insanely long (64-char
        // sha-style ids like "<sha>::<uuid>"), collapse to 8 chars + "...".
        // The full jobId stays in data-job-id, the tooltip, clipboard copy,
        // and the expanded details block — every API call and DOM lookup
        // uses it intact.
        const idPrefix = jobId.split( "::" )[ 0 ];
        const jobIdDisplay = idPrefix.length > 16
            ? idPrefix.substring( 0, 8 ) + "..."
            : idPrefix;
        // History cards get a `history-` ID prefix so their DOM ids cannot
        // collide with the same job rendered in a live queue (Done, etc.).
        // All external lookups (websocket handlers, interaction appenders)
        // address live cards by bare jobId, so this prefix only applies to
        // history renders — `toggleJobCard` applies the same rule.
        const idKey = queueName === 'history' ? `history-${jobId}` : jobId;

        // ═══════════════════════════════════════════════════════════════════
        // Phase 7: Enhanced indicators based on queue type
        // ═══════════════════════════════════════════════════════════════════

        // Running job: spinning status indicator
        let statusIndicator = '';
        if ( queueName === 'run' ) {
            statusIndicator = '<span class="status-indicator spinning" title="Running">⟳</span>';
        }

        // Expediting job in todo queue: pulsing indicator while expeditor collects args
        if ( queueName === 'todo' && job.expediting ) {
            statusIndicator = '<span class="status-indicator expediting" title="Setting up...">⟳</span>';
        }

        // ═══════════════════════════════════════════════════════════════════
        // Phase 5 CJ Flow: Paused / Scheduled / Monopolize indicators
        // ═══════════════════════════════════════════════════════════════════

        // Paused job: muted card with pause icon
        let pausedBadge = '';
        let pausedCardClass = '';
        if ( queueName === 'todo' && job.paused ) {
            pausedBadge = '<span class="paused-badge" title="Paused — consumer will skip">⏸ Paused</span>';
            pausedCardClass = ' job-paused';
            statusIndicator = '<span class="status-indicator paused-icon" title="Paused">⏸</span>';
        }

        // Scheduled job: show clock badge with formatted time
        // Renders for any queue when job has scheduled_at — for done/dead the time is in the past
        // but the badge is still meaningful as historical context
        let scheduledBadge = '';
        if ( job.scheduled_at ) {
            const schedDate = new Date( job.scheduled_at );
            const tz = this.appTimezone || 'America/New_York';
            const schedTimeStr = schedDate.toLocaleTimeString( [], { hour: '2-digit', minute: '2-digit', timeZone: tz } );
            const schedDateStr = schedDate.toLocaleDateString( [], { month: 'short', day: 'numeric', timeZone: tz } );
            scheduledBadge = `<span class="scheduled-badge" title="Scheduled for ${schedDate.toISOString()}">🕐 ${schedDateStr} ${schedTimeStr}</span>`;
        }

        // Monopolize job: subtle lock badge (no-op in serial mode)
        let monopolizeBadge = '';
        if ( job.monopolize ) {
            monopolizeBadge = '<span class="monopolize-badge" title="Exclusive execution — no concurrent jobs">🔒</span>';
        }

        // Done job: completion badge
        let completionBadge = '';
        // Completion badges: ✓ for completed, ✗ for failed.
        // Renders in the done bucket (queueName='done') AND the history pane
        // (queueName='history'), since history mirrors terminal-state cards.
        if ( queueName === 'done' || queueName === 'history' ) {
            const jobStatus = job.status || 'completed';
            if ( jobStatus === 'completed' ) {
                completionBadge = '<span class="completion-badge success" title="Completed">✓</span>';
            } else if ( jobStatus === 'failed' ) {
                completionBadge = '<span class="completion-badge failed" title="Failed">✗</span>';
            }
        }

        // Dead job: error badge
        // Renders in the dead bucket and for any history row whose status is
        // 'failed' / 'interrupted' / 'dead' (terminal failure state).
        if ( queueName === 'dead' || ( queueName === 'history' && [ 'failed', 'interrupted', 'dead' ].includes( job.status ) ) ) {
            completionBadge = '<span class="completion-badge failed" title="Failed">✗</span>';
        }

        // Stalled / paused job: ⏸ badge with label varying by stall_reason
        // (Session 2026-04-15 Bug 8). Checkpoint-resume jobs share JobState.STALLED
        // but differentiate their label via stall_reason:
        //   voice_gate_timeout → "Stalled" (default, amber) — nobody answered
        //   user_pause         → "Paused"  (blue)           — user deferred deliberately
        //   rate_limit         → "Stalled" (amber)          — infrastructure throttle
        const isStalled = ( job.status === 'stalled' );
        if ( isStalled ) {
            const stallReason = (
                ( job.checkpoint && job.checkpoint.stall_reason )
                || ( job.metadata_json && job.metadata_json.checkpoint && job.metadata_json.checkpoint.stall_reason )
                || 'voice_gate_timeout'
            );
            const isPaused = ( stallReason === 'user_pause' );
            const label    = isPaused ? 'Paused' : 'Stalled';
            const cls      = isPaused ? 'paused' : 'stalled';
            const tip      = isPaused
                ? 'Paused — user deferred; resume when ready'
                : 'Stalled — awaiting user input';
            completionBadge = `<span class="completion-badge ${cls}" title="${tip}">⏸ ${label}</span>`;
        }

        // Stopped job: user explicitly cancelled mid-run. Terminal, not resumable.
        if ( job.status === 'cancelled' ) {
            completionBadge = '<span class="completion-badge stopped" title="Stopped — user cancelled">✕ Stopped</span>';
        }

        // Interaction indicator for any terminal-state pane (done or history).
        // Backend now returns accurate has_interactions count from the
        // notifications table — see Phase 1 (2026-04-26).
        let interactionIndicator = '';
        if ( ( queueName === 'done' || queueName === 'history' ) && job.has_interactions ) {
            interactionIndicator = '<span class="interaction-indicator" title="Has interaction history">💬</span>';
        }

        // ═══════════════════════════════════════════════════════════════════
        // Phase 7: Running job - show "In progress..." (no live timer)
        // Final duration calculated server-side and shown in done queue via job.duration_seconds
        // ═══════════════════════════════════════════════════════════════════
        let durationSection = '';
        if ( queueName === 'run' ) {
            durationSection = `
                <div class="job-duration-line">
                    <span class="duration-label">Duration:</span>
                    <span class="duration-value">In progress...</span>
                </div>
            `;
        }

        // ═══════════════════════════════════════════════════════════════════
        // Build final HTML
        // Session 107: Placeholder divs always present (hidden until populated)
        // Session 107: Removed provisionalAttr - no longer using provisional registration
        // ═══════════════════════════════════════════════════════════════════

        // ✕ button means "make this job go away" — but the mechanism differs by queue:
        //   run queue:  graceful cancel via cancelJob (POST /api/jobs/{id}/cancel)
        //   todo queue: forceful delete via deleteQueueJob (DELETE /api/queue/todo/{id})
        let cancelBtnHtml      = '';
        let headerCancelClass  = '';
        if ( queueName === 'run' ) {
            cancelBtnHtml     = `<button type="button" class="job-cancel-button" id="job-cancel-${jobId}" onclick="event.stopPropagation(); window.notificationsUI.cancelJob('${jobId}')" title="Cancel this job">✕</button>`;
            headerCancelClass = ' has-cancel';
        } else if ( [ 'todo', 'done', 'dead' ].includes( queueName ) ) {
            // Small ✕ delete button rendered for live-bucket cards. History
            // cards intentionally OMIT this button — they get the prominent
            // "🗑 Delete" / "↻ Retry" buttons spliced by renderHistoryActions
            // at card-bottom. Rendering both produced a confusing double-delete
            // (user feedback 2026-04-26).
            const deleteAction = `window.notificationsUI._dispatchDelete('${jobId}', '${queueName}')`;
            cancelBtnHtml     = `<button type="button" class="job-cancel-button" id="job-cancel-${idKey}" onclick="event.stopPropagation(); ${deleteAction}" title="Remove this job">✕</button>`;
            headerCancelClass = ' has-cancel';
        }

        // Phase 5 CJ Flow: Pause/resume toggle button (todo queue only)
        const pauseBtnHtml = ( queueName === 'todo' )
            ? `<button type="button" class="job-pause-button${job.paused ? ' is-paused' : ''}" id="job-pause-${idKey}" onclick="event.stopPropagation(); window.notificationsUI.toggleJobPause('${jobId}', ${!job.paused})" title="${job.paused ? 'Resume this job' : 'Pause this job'}">${job.paused ? '▶' : '⏸'}</button>`
            : '';

        const deleteBtnHtml = '';

        return `
            <div class="job-card ${statusClass}${pausedCardClass}" id="job-card-${idKey}" data-job-id="${jobId}" data-paused="${job.paused ? 'true' : 'false'}">
                <div class="job-card-header${headerCancelClass}" onclick="window.notificationsUI.toggleJobCard('${idKey}')">
                    ${cancelBtnHtml}${pauseBtnHtml}${deleteBtnHtml}
                    ${agentBadge}${ownerBadge}${cacheHitBadge}${completionBadge}${pausedBadge}${scheduledBadge}${monopolizeBadge}
                    <span class="job-id-chip" title="${jobId} — click to copy" onclick="event.stopPropagation(); navigator.clipboard.writeText('${jobId}'); this.classList.add('copied'); setTimeout(() => this.classList.remove('copied'), 900)">${jobIdDisplay}</span>
                    <span class="job-question">${this.escapeHtml( truncatedQuestion )}</span>
                    ${statusIndicator}${interactionIndicator}
                    <span class="job-timestamp">${timestamp}</span>
                    <button class="job-expand-btn">▶</button>
                </div>
                <div class="job-card-details collapsed" id="job-details-${idKey}">
                    ${durationSection}
                    <div class="job-id-line">
                        <strong>ID:</strong> <code>${jobId}</code>
                    </div>
                    <div class="job-full-question">
                        <strong>Question:</strong> ${this.escapeHtml( job.question_text || '' )}
                    </div>
                    <div class="job-response" style="${job.response_text ? '' : 'display: none'}">
                        ${job.response_text ? `<strong>Response:</strong> ${this.escapeHtml( job.response_text )}` : ''}
                    </div>
                    <div class="job-abstract" style="${job.abstract ? '' : 'display: none'}">
                        ${this.renderAbstractSection( job.abstract )}
                    </div>
                    <div class="job-report-link" style="${job.report_path ? '' : 'display: none'}">
                        ${this.renderReportLinkSection( job.report_path, job.agent_type, job.yaml_path, job.remediation_snapshot_path, job.pptx_path )}
                    </div>
                    <!-- Fix 8c: partial artifacts from failed-before-completion runs (dead queue only).
                         Surfaces TFE/BFE plan files + remediation snapshots that were written before
                         the job crashed, so users can recover partial diagnoses without grepping
                         docker logs. Links to /app/docs?path= for rendered markdown viewing.
                         See: src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md -->
                    <div class="job-partial-artifacts" style="${( queueName === 'dead' && ( job.plan_path || ( job.remediation_snapshot_path && !job.report_path ) ) ) ? '' : 'display: none'}">
                        ${queueName === 'dead' && job.plan_path ? `
                            <div class="partial-artifact">
                                <a href="/app/docs?path=${encodeURIComponent( job.plan_path || '' )}" target="_blank" class="report-link-btn">📋 Partial plan written before failure</a>
                            </div>
                        ` : ''}
                        ${queueName === 'dead' && job.remediation_snapshot_path && !job.report_path ? `
                            <div class="partial-artifact">
                                <a href="/app/docs?path=${encodeURIComponent( job.remediation_snapshot_path || '' )}" target="_blank" class="report-link-btn">🔍 Remediation Snapshot</a>
                            </div>
                        ` : ''}
                    </div>
                    <!-- Stalled job: resume button + plan link (checkpoint-resume, Session 9056c113) -->
                    <div class="job-stalled-actions" style="${isStalled ? '' : 'display: none'}">
                        ${isStalled && job.plan_path ? `
                            <div class="stalled-artifact">
                                <a href="/app/docs?path=${encodeURIComponent( job.plan_path || '' )}" target="_blank" class="report-link-btn">📋 View Plan</a>
                            </div>
                        ` : ''}
                        ${isStalled && this.isResumableWithOverrides( job ) ? this.renderResumeOverrideControls( jobId ) : ''}
                        ${isStalled ? `
                            <button class="btn btn-sm btn-warning mt-1 resume-stalled-btn"
                                    data-job-id="${jobId}"
                                    onclick="window.notificationsUI?.resumeStalledJob( '${jobId}' )">
                                ▶ Resume from Checkpoint
                            </button>
                        ` : ''}
                    </div>
                    <div class="job-cost-summary" style="${job.cost_summary ? '' : 'display: none'}">
                        ${job.cost_summary ? this.renderCostSummaryContent( job.cost_summary, job.duration_seconds ) : ''}
                    </div>
                    <div class="job-error" style="${job.error ? '' : 'display: none'}">
                        ${job.error ? `<div class="error-header">❌ Error</div><div class="error-content">${this.escapeHtml( job.error )}</div>` : ''}
                    </div>
                    <div class="job-metadata">
                        <span>Agent: ${job.agent_type || 'Unknown'}</span>
                        <span>Time: ${timestamp}</span>
                    </div>
                    ${( queueName === 'run' || queueName === 'todo' ) ? `
                    <div class="job-interactions-section live-interactions" id="job-interactions-${idKey}">
                        <div class="interactions-header" onclick="window.notificationsUI.toggleJobInteractions('${idKey}', event)">
                            <span>📋 Activity Log</span>
                            <button class="interactions-expand-btn">▶</button>
                        </div>
                        <div class="job-send-message collapsed" id="job-send-msg-${idKey}">
                            <div class="job-send-message-row">
                                <button type="button" class="stt-button" id="job-msg-stt-${idKey}"
                                        title="Click to record (30s max, ESC to cancel)">🎤</button>
                                <input type="text" id="job-msg-input-${idKey}" class="job-msg-input"
                                       placeholder="Send message to job..." />
                                <label class="urgent-toggle" title="Mark as urgent (interrupts current task)">
                                    <input type="checkbox" id="job-msg-urgent-${idKey}" />
                                    ⚡
                                </label>
                                <button type="button" class="response-submit-button"
                                        id="job-msg-submit-${idKey}">Send</button>
                            </div>
                        </div>
                        <div class="interactions-content collapsed" id="interactions-content-${idKey}">
                        </div>
                    </div>
                    ` : ''}
                    ${( queueName === 'done' || queueName === 'history' ) ? `
                    <div class="job-interactions-section" id="job-interactions-${idKey}">
                        <div class="interactions-header" onclick="window.notificationsUI.toggleJobInteractions('${idKey}', event)">
                            <span>📋 Notification Conversation</span>
                            <button class="interactions-expand-btn">▶</button>
                        </div>
                        <div class="interactions-content collapsed" id="interactions-content-${idKey}">
                            <div class="interactions-loading">Loading...</div>
                        </div>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    toggleJobCard( idKey ) {
        /**
         * Toggle expand/collapse for individual job card.
         *
         * idKey is either a bare jobId (live queues) or `history-${jobId}`
         * (history section) — renderJobCard emits the corresponding DOM ids.
         * Namespacing history cards prevents getElementById() collision with
         * the same job rendered in the live Done section.
         */
        const details = document.getElementById( `job-details-${idKey}` );
        const card    = document.getElementById( `job-card-${idKey}` );

        if ( !details || !card ) {
            this.error( `Job card elements not found: ${idKey}` );
            return;
        }

        const expandBtn = card.querySelector( '.job-expand-btn' );

        if ( this.expandedJobCards.has( idKey ) ) {
            details.classList.add( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▶';
            this.expandedJobCards.delete( idKey );
        } else {
            details.classList.remove( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▼';
            this.expandedJobCards.add( idKey );
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Approach D: Job Message Send — User-to-Job Communication
    // ═══════════════════════════════════════════════════════════════════════════

    async sendJobMessage( jobId ) {
        /**
         * Send a user message to a running job via POST /api/jobs/{jobId}/message.
         *
         * Reads input text and urgent checkbox state, POSTs to the API,
         * and appends the message to the job's live interaction pane on success.
         *
         * Requires:
         *     - jobId is a valid running job ID
         *     - DOM elements job-msg-input-{jobId} and job-msg-urgent-{jobId} exist
         *
         * Ensures:
         *     - Message sent to API on valid input
         *     - Input cleared on success
         *     - Message appended to live interaction pane (optimistic UI)
         *     - Error shown inline on failure
         */
        const input    = document.getElementById( `job-msg-input-${jobId}` );
        const urgentCb = document.getElementById( `job-msg-urgent-${jobId}` );
        const sendBtn  = document.getElementById( `job-msg-submit-${jobId}` );

        if ( !input ) return;

        const message  = input.value.trim();
        const priority = urgentCb && urgentCb.checked ? 'urgent' : 'normal';

        if ( !message ) {
            input.focus();
            return;
        }

        // Disable controls and clear input immediately
        input.disabled   = true;
        sendBtn.disabled = true;
        input.value      = '';
        if ( urgentCb ) {
            urgentCb.checked = false;
            const label = urgentCb.closest( '.urgent-toggle' );
            if ( label ) label.classList.remove( 'checked' );
        }

        // TRUE optimistic render — append user bubble BEFORE the fetch so
        // the bubble appears above any echo the server sends back via WebSocket
        this.appendJobUserMessage( jobId, message, priority );

        // Auto-expand conversation if collapsed
        const contentEl = document.getElementById( `interactions-content-${jobId}` );
        if ( contentEl && contentEl.classList.contains( 'collapsed' ) ) {
            contentEl.classList.remove( 'collapsed' );
            const section = document.getElementById( `job-interactions-${jobId}` );
            const expandBtn = section ? section.querySelector( '.interactions-expand-btn' ) : null;
            if ( expandBtn ) expandBtn.textContent = '▼';
        }

        try {
            const response = await this.authedFetch( `/api/jobs/${jobId}/message`, {
                method  : 'POST',
                headers : { 'Content-Type': 'application/json' },
                body    : JSON.stringify( { message, priority } ),
            } );

            if ( !response.ok ) {
                const errData = await response.json().catch( () => ( {} ) );
                throw new Error( errData.detail || `HTTP ${response.status}` );
            }

            this.log( `[JOB-MSG] Sent to ${jobId}: ${message.substring( 0, 80 )}` );

        } catch ( error ) {
            this.error( `[JOB-MSG] Failed to send message to ${jobId}:`, error );
            // Show inline error
            input.style.borderColor = '#dc3545';
            setTimeout( () => { input.style.borderColor = ''; }, 3000 );
        } finally {
            input.disabled  = false;
            sendBtn.disabled = false;
            input.focus();
        }
    }

    async cancelJob( jobId ) {
        /**
         * Request graceful cancellation of a running agentic job.
         *
         * POSTs to /api/jobs/{jobId}/cancel. On success, the job stops at the
         * next checkpoint and transitions to the dead queue via WebSocket.
         *
         * Requires:
         *     - jobId is a valid running agentic job ID
         *
         * Ensures:
         *     - Confirmation dialog shown before cancel
         *     - Button disabled while request is in-flight
         *     - Card moves to dead queue via normal WebSocket transition on success
         */
        if ( !confirm( 'Cancel this job? It will stop at the next checkpoint.' ) ) return;

        const cancelBtn = document.getElementById( `job-cancel-${jobId}` );
        if ( cancelBtn ) {
            cancelBtn.disabled  = true;
            cancelBtn.innerText = 'Cancelling...';
        }

        try {
            const response = await this.authedFetch( `/api/jobs/${jobId}/cancel`, {
                method : 'POST'
            } );

            if ( !response.ok ) {
                const errData = await response.json().catch( () => ( {} ) );
                throw new Error( errData.detail || `HTTP ${response.status}` );
            }

            this.log( `[JOB-CANCEL] Cancel requested for ${jobId}` );
            // On success, WebSocket state transition will move card to dead queue

        } catch ( error ) {
            this.error( `[JOB-CANCEL] Failed to cancel ${jobId}:`, error );
            alert( `Cancel failed: ${error.message}` );
            if ( cancelBtn ) {
                cancelBtn.disabled  = false;
                cancelBtn.innerText = 'Cancel Job';
            }
        }
    }

    isResumableWithOverrides( job ) {
        /**
         * Return true iff this job type supports per-resume model + effort overrides
         * (currently TFE and BFE). Used to gate the inline dropdown UI on stalled cards.
         *
         * Matches the snake_case JOB_TYPE class attrs emitted by the backend:
         *     TestFixExpediterJob.JOB_TYPE = "test_fix_expediter"
         *     BugFixExpediterJob.JOB_TYPE  = "bug_fix_expediter"
         */
        const agentType = job.agent_type || '';
        return agentType === 'test_fix_expediter' || agentType === 'bug_fix_expediter';
    }

    renderResumeOverrideControls( jobId ) {
        /**
         * Render Model + Effort dropdowns for a stalled TFE/BFE card. Defaults
         * come from localStorage; user's last selection persists across reloads.
         */
        const modelPref  = localStorage.getItem( this.RESUME_MODEL_PREF_KEY )  || 'claude-sonnet-4-6';
        const effortPref = localStorage.getItem( this.RESUME_EFFORT_PREF_KEY ) || 'high';
        const sel = ( optVal, prefVal ) => ( optVal === prefVal ? 'selected' : '' );
        return `
            <div class="resume-override-controls" data-job-id="${jobId}" style="display: inline-flex; gap: 0.5em; align-items: center; margin-right: 0.5em;">
                <label style="font-size: 0.85em;">
                    Model
                    <select class="resume-model-select" data-job-id="${jobId}"
                            onchange="window.notificationsUI?.saveResumeModelPref( this.value )">
                        <option value="claude-opus-4-7"           ${sel( 'claude-opus-4-7', modelPref )}>Opus 4.7</option>
                        <option value="claude-sonnet-4-6"         ${sel( 'claude-sonnet-4-6', modelPref )}>Sonnet 4.6</option>
                        <option value="claude-haiku-4-5-20251001" ${sel( 'claude-haiku-4-5-20251001', modelPref )}>Haiku 4.5</option>
                    </select>
                </label>
                <label style="font-size: 0.85em;">
                    Effort
                    <select class="resume-effort-select" data-job-id="${jobId}"
                            onchange="window.notificationsUI?.saveResumeEffortPref( this.value )">
                        <option value=""       ${sel( '',       effortPref )}>(default)</option>
                        <option value="low"    ${sel( 'low',    effortPref )}>low</option>
                        <option value="medium" ${sel( 'medium', effortPref )}>medium</option>
                        <option value="high"   ${sel( 'high',   effortPref )}>high</option>
                        <option value="xhigh"  ${sel( 'xhigh',  effortPref )}>xhigh</option>
                        <option value="max"    ${sel( 'max',    effortPref )}>max</option>
                    </select>
                </label>
            </div>
        `;
    }

    saveResumeModelPref( value ) {
        localStorage.setItem( this.RESUME_MODEL_PREF_KEY, value || '' );
    }

    saveResumeEffortPref( value ) {
        localStorage.setItem( this.RESUME_EFFORT_PREF_KEY, value || '' );
    }

    async resumeStalledJob( jobId ) {
        /**
         * Resume a stalled job from its checkpoint.
         *
         * POSTs to /api/jobs/{jobId}/resume-from-checkpoint. On success, a new job
         * is created and queued, resuming from the phase where it stalled.
         *
         * Session 9056c113 — checkpoint-resume infrastructure.
         * Session d8831785 — optional model + thinking-effort overrides for TFE/BFE.
         *
         * Requires:
         *     - jobId is a valid stalled agentic job ID
         *
         * Ensures:
         *     - Confirmation dialog shown before resume
         *     - Button disabled while request is in-flight
         *     - If the card has Model + Effort dropdowns, their values are sent
         *       as lead_model_override / worker_model_override / thinking_effort
         */
        if ( !confirm( 'Resume this job from its checkpoint?' ) ) return;

        const resumeBtn = document.querySelector( `.resume-stalled-btn[data-job-id="${jobId}"]` );
        if ( resumeBtn ) {
            resumeBtn.disabled  = true;
            resumeBtn.innerText = 'Resuming...';
        }

        // Read override selections from the card's dropdowns (if present).
        const modelSelect  = document.querySelector( `.resume-model-select[data-job-id="${jobId}"]` );
        const effortSelect = document.querySelector( `.resume-effort-select[data-job-id="${jobId}"]` );
        const overrides = {};
        if ( modelSelect?.value ) {
            overrides.lead_model_override   = modelSelect.value;
            overrides.worker_model_override = modelSelect.value;
        }
        if ( effortSelect?.value ) {
            overrides.thinking_effort = effortSelect.value;
        }

        try {
            const response = await this.authedFetch( `/api/jobs/${jobId}/resume-from-checkpoint`, {
                method  : 'POST',
                headers : { 'Content-Type': 'application/json' },
                body    : JSON.stringify( overrides ),
            } );

            if ( !response.ok ) {
                const errData = await response.json().catch( () => ( {} ) );
                throw new Error( errData.detail || `HTTP ${response.status}` );
            }

            const data = await response.json();
            this.log( `[JOB-RESUME] Resumed ${jobId} → ${data.resumed_job_id} from phase ${data.phase_name}` );
            this.log( `[JOB-RESUME] ✓ Resumed from ${data.phase_name} → new job ${data.resumed_job_id}` );

        } catch ( error ) {
            this.error( `[JOB-RESUME] Failed to resume ${jobId}:`, error );
            alert( `Resume failed: ${error.message}` );
            if ( resumeBtn ) {
                resumeBtn.disabled  = false;
                resumeBtn.innerText = '▶ Resume from Checkpoint';
            }
        }
    }

    async submitTFEResume() {
        /**
         * Smart TFE resume from free-form input (session 9056c113).
         *
         * Sends the resume_from text to /api/test-fix-expediter/resume-from which
         * auto-detects the input type (job ID, plan doc path, natural language) and
         * either auto-resumes (single match) or returns candidates for disambiguation.
         */
        const input = document.getElementById( 'tfe-resume-input' ).value.trim();
        if ( !input ) {
            alert( 'Enter a job ID, plan path, or description.' );
            return;
        }

        const statusEl     = document.getElementById( 'tfe-resume-submit-status' );
        const candidatesEl = document.getElementById( 'tfe-resume-candidates' );
        const submitBtn    = document.getElementById( 'submit-tfe-resume-job' );

        if ( submitBtn )     submitBtn.disabled = true;
        if ( statusEl )      statusEl.textContent = 'Resolving...';
        if ( candidatesEl )  candidatesEl.style.display = 'none';

        try {
            const response = await this.authedFetch( '/api/test-fix-expediter/resume-from', {
                method  : 'POST',
                headers : { 'Content-Type': 'application/json' },
                body    : JSON.stringify( { resume_from: input } )
            });

            if ( !response.ok ) {
                const errData = await response.json().catch( () => ({}) );
                throw new Error( errData.detail || `HTTP ${response.status}` );
            }

            const data = await response.json();

            if ( data.status === 'ambiguous' ) {
                // Multi-match disambiguation
                this._renderTFEResumeCandidates( data.candidates || [], candidatesEl );
                if ( statusEl ) {
                    statusEl.textContent = `Found ${( data.candidates || [] ).length} possible matches — pick one.`;
                }
                return;
            }

            if ( data.status === 'resumed' ) {
                const st = data.source_type || 'unknown';
                const phase = data.phase_name || `phase ${data.resume_from_phase}`;
                this.log( `[TFE-RESUME] ✓ Resumed (${st}) from ${phase} → ${data.resumed_job_id}` );
                if ( statusEl ) {
                    statusEl.textContent = `✓ Resumed via ${st}: ${data.resumed_job_id} from ${phase}`;
                }
                document.getElementById( 'tfe-resume-input' ).value = '';
            }
        } catch ( error ) {
            this.error( '[TFE-RESUME] submitTFEResume failed:', error );
            if ( statusEl ) statusEl.textContent = `✗ ${error.message}`;
        } finally {
            if ( submitBtn ) submitBtn.disabled = false;
        }
    }

    _renderTFEResumeCandidates( candidates, containerEl ) {
        /**
         * Render disambiguation list for ambiguous TFE resume matches.
         * Each candidate becomes a clickable row that re-submits with the exact job ID.
         */
        if ( !containerEl ) return;
        if ( !candidates.length ) {
            containerEl.style.display = 'none';
            return;
        }

        const html = candidates.map( ( c, i ) => {
            const conf = c.confidence != null ? `${Math.round( c.confidence * 100 )}%` : '?';
            const stalled = c.stalled_at ? `stalled ${c.stalled_at}` : '';
            const summary = this.escapeHtml( c.summary || '' );
            const jobId = this.escapeHtml( c.job_id );
            const reason = this.escapeHtml( c.reason || '' );
            return `
                <div class="tfe-resume-candidate" style="border: 1px solid #ced4da; border-radius: 4px; padding: 8px; margin-bottom: 4px; cursor: pointer;"
                     onclick="window.notificationsUI?._pickTFEResumeCandidate('${jobId}')">
                    <strong>${conf}</strong> · <code>${jobId}</code>
                    <span style="color: #888;">${stalled}</span>
                    <div style="font-size: 11px; color: #666;">${summary}${reason ? ' — ' + reason : ''}</div>
                </div>
            `;
        }).join( '' );

        containerEl.innerHTML = `
            <div style="font-size: 12px; color: #666; margin-bottom: 4px;">
                Click a candidate to resume it:
            </div>
            ${html}
        `;
        containerEl.style.display = 'block';
    }

    _pickTFEResumeCandidate( jobId ) {
        /** User picked a candidate from the disambiguation list — resubmit with exact job ID. */
        const inputEl = document.getElementById( 'tfe-resume-input' );
        if ( inputEl ) inputEl.value = jobId;
        this.submitTFEResume();
    }

    async toggleJobPause( jobId, shouldPause ) {
        /**
         * Toggle pause/resume state of a todo queue job.
         *
         * Requires:
         *     - jobId is a valid todo queue job ID
         *     - shouldPause is boolean (true=pause, false=resume)
         *
         * Ensures:
         *     - Calls PATCH /api/queue/todo/{jobId}/pause or /resume
         *     - Button updated optimistically, reverted on failure
         *     - WebSocket event will confirm state change
         */
        const action = shouldPause ? 'pause' : 'resume';
        const btn = document.getElementById( `job-pause-${jobId}` );

        // Optimistic UI update
        if ( btn ) {
            btn.disabled    = true;
            btn.textContent = '...';
        }

        try {
            const response = await this.authedFetch( `/api/queue/todo/${jobId}/${action}`, {
                method : 'PATCH'
            } );

            if ( !response.ok ) {
                const errData = await response.json().catch( () => ( {} ) );
                throw new Error( errData.detail || `HTTP ${response.status}` );
            }

            this.log( `[JOB-PAUSE] ${action} requested for ${jobId}` );
            // WebSocket event (job_paused/job_resumed) will apply final UI state

        } catch ( error ) {
            this.error( `[JOB-PAUSE] Failed to ${action} ${jobId}:`, error );
            alert( `${action} failed: ${error.message}` );

            // Revert optimistic update
            if ( btn ) {
                btn.disabled = false;
                const wasPaused = !shouldPause;
                btn.textContent = wasPaused ? '▶' : '⏸';
                btn.title       = wasPaused ? 'Resume this job' : 'Pause this job';
            }
        }
    }

    appendJobUserMessage( jobId, message, priority ) {
        /**
         * Append a user-sent message to the job's unified conversation pane.
         *
         * Creates an outgoing chat bubble (sender-message outgoing) and
         * inserts it at the top (newest first) of the conversation.
         */
        const contentEl = document.getElementById( `interactions-content-${jobId}` );
        if ( !contentEl ) return;

        const timestamp = new Date().toLocaleTimeString();
        const priorityBadge = priority === 'urgent' ? ' <strong>[URGENT]</strong>' : '';

        const itemHtml = `
            <div class="sender-message outgoing animated-in${priority === 'urgent' ? ' priority-urgent' : ''}">
                <span class="message-time">${timestamp}${priorityBadge}</span>
                <span class="message-text">${this.renderMarkdownInline( message )}</span>
            </div>
        `;

        contentEl.insertAdjacentHTML( 'afterbegin', itemHtml );
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Phase 7: Duration Timer Functions
    // ═══════════════════════════════════════════════════════════════════════════

    formatDuration( seconds ) {
        /**
         * Format duration in seconds to human-readable "Xm Ys" or "Xh Ym" format.
         *
         * Requires:
         *     - seconds is a number >= 0
         *
         * Ensures:
         *     - Returns formatted string like "2m 34s" or "1h 5m"
         */
        if ( typeof seconds !== 'number' || isNaN( seconds ) || seconds < 0 ) {
            return '0s';
        }

        const hours = Math.floor( seconds / 3600 );
        const minutes = Math.floor( ( seconds % 3600 ) / 60 );
        const secs = Math.floor( seconds % 60 );

        if ( hours > 0 ) {
            return `${hours}h ${minutes}m`;
        } else if ( minutes > 0 ) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }

    async toggleJobInteractions( idKey, event ) {
        /**
         * Toggle and lazy-load interaction history for a job.
         *
         * THE KEY FEATURE: Shows notification conversation history
         * associated with a completed job.
         *
         * Accepts `idKey` (possibly `history-` prefixed) so the DOM lookup
         * finds the correct card — history cards prefix their DOM ids to
         * avoid collision with the same job rendered in a live queue.
         * The bare `jobId` is used for API + cache calls.
         */
        event.stopPropagation();  // Don't toggle parent card

        const jobId = idKey.startsWith( 'history-' ) ? idKey.substring( 8 ) : idKey;

        const contentEl = document.getElementById( `interactions-content-${idKey}` );
        if ( !contentEl ) {
            this.error( `Interactions content not found: ${idKey}` );
            return;
        }

        const sectionEl = contentEl.closest( '.job-interactions-section' );
        const headerEl  = sectionEl ? sectionEl.querySelector( '.interactions-header' ) : null;
        const expandBtn = headerEl ? headerEl.querySelector( '.interactions-expand-btn' ) : null;

        const isExpanded = !contentEl.classList.contains( 'collapsed' );
        const sendMsgEl  = sectionEl ? sectionEl.querySelector( '.job-send-message' ) : null;

        if ( isExpanded ) {
            contentEl.classList.add( 'collapsed' );
            if ( sendMsgEl ) sendMsgEl.classList.add( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▶';
        } else {
            contentEl.classList.remove( 'collapsed' );
            if ( sendMsgEl ) sendMsgEl.classList.remove( 'collapsed' );
            if ( expandBtn ) expandBtn.textContent = '▼';

            // Lazy load interactions if not cached
            if ( !this.jobInteractionsCache.has( jobId ) ) {
                await this.loadJobInteractions( jobId, idKey );
            }

            // Scroll the interactions section header to the top of the viewport
            if ( sectionEl ) {
                sectionEl.scrollIntoView( { behavior: 'smooth', block: 'start' } );
            }
        }
    }

    async loadJobInteractions( jobId, idKey = null ) {
        /**
         * Fetch notification interactions for a job from API.
         *
         * `jobId` is the bare job id (always used for API + cache).
         * `idKey` is the DOM id suffix — defaults to `jobId` for live-queue
         * callers, but history-card callers pass the `history-` prefixed form.
         */
        const domKey = idKey || jobId;
        const contentEl = document.getElementById( `interactions-content-${domKey}` );
        if ( !contentEl ) return;

        try {
            const response = await this.authedFetch( `/api/get-job-interactions/${encodeURIComponent( jobId )}` );

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

    formatResponseValue( responseValue ) {
        /**
         * Format a notification response value for human-readable display.
         * Parses JSON envelope { value, source } and formats the inner value.
         *
         * Requires:
         *   - responseValue is a string, object, or primitive
         *
         * Ensures:
         *   - returns an HTML-safe string with the human-readable value
         *   - nested JSON answers are formatted as "key: value, ..." pairs
         */
        let parsed = responseValue;

        // Parse string to object if needed
        if ( typeof parsed === 'string' ) {
            try {
                parsed = JSON.parse( parsed );
            } catch ( e ) {
                return this.escapeHtml( parsed );  // Not JSON — show as-is
            }
        }

        // Extract inner value from { value, source } envelope
        if ( parsed && typeof parsed === 'object' && 'value' in parsed ) {
            let innerValue = parsed.value;

            // Try parsing nested JSON (open_ended_batch wraps answers as string)
            if ( typeof innerValue === 'string' ) {
                try {
                    const nested = JSON.parse( innerValue );
                    if ( nested && typeof nested === 'object' ) {
                        // Format answers dict as readable key-value pairs
                        if ( nested.answers && typeof nested.answers === 'object' ) {
                            const pairs = Object.entries( nested.answers )
                                .map( ( [ k, v ] ) => `${k}: ${v}` )
                                .join( ', ' );
                            return this.escapeHtml( pairs );
                        }
                        // Generic object — format as key-value pairs
                        const pairs = Object.entries( nested )
                            .map( ( [ k, v ] ) => `${k}: ${v}` )
                            .join( ', ' );
                        return this.escapeHtml( pairs );
                    }
                } catch ( e ) {
                    // Not nested JSON — use the string value directly
                }
                return this.escapeHtml( innerValue );
            }

            // Non-string inner value
            return this.escapeHtml( String( innerValue ) );
        }

        // Fallback: stringify the object
        return this.escapeHtml( JSON.stringify( parsed ) );
    }

    renderInteractionItem( interaction ) {
        /**
         * Render a single notification interaction.
         *
         * User-initiated messages (type="user_initiated_message") render as
         * outgoing chat bubbles; all other types render as system entries.
         */
        let timestamp = '';
        try {
            timestamp = new Date( interaction.timestamp ).toLocaleTimeString();
        } catch ( e ) {
            timestamp = interaction.timestamp || '';
        }

        // User-initiated messages → outgoing chat bubble (same style as live send)
        if ( interaction.type === 'user_initiated_message' ) {
            const urgentClass = interaction.priority === 'urgent' ? ' priority-urgent' : '';
            const priorityBadge = interaction.priority === 'urgent' ? ' <strong>[URGENT]</strong>' : '';
            return `
                <div class="sender-message outgoing${urgentClass}">
                    <span class="message-time">${timestamp}${priorityBadge}</span>
                    <span class="message-text">${this.renderMarkdownInline( interaction.message )}</span>
                </div>
            `;
        }

        // System notifications → standard interaction item
        const typeIcons = {
            'task'    : '📋',
            'progress': '⏳',
            'alert'   : '⚠️',
            'custom'  : '💬'
        };
        const typeIcon = typeIcons[ interaction.type ] || '📋';

        let responseHtml = '';
        if ( interaction.response_requested && interaction.response_value ) {
            const responseStr = this.formatResponseValue( interaction.response_value );
            responseHtml = `
                <div class="sender-message outgoing">
                    <span class="message-time">${timestamp}</span>
                    <span class="message-text">${responseStr}</span>
                </div>
            `;
        }

        // Abstract indicator — clickable 📋 that opens the abstract tooltip
        const hasAbstract = interaction.abstract && interaction.abstract.trim().length > 0;
        const abstractIndicator = hasAbstract
            ? ` <span class="abstract-indicator" data-abstract="${encodeURIComponent( interaction.abstract )}" title="View details">📋</span>`
            : '';

        return `
            <div class="interaction-item priority-${interaction.priority || 'medium'}">
                <div class="interaction-header">
                    <span class="interaction-type">${typeIcon} ${interaction.type}</span>
                    <span class="interaction-time">${timestamp}</span>
                </div>
                <div class="interaction-message">${this.escapeHtml( interaction.message || '' )}${abstractIndicator}</div>
            </div>
            ${responseHtml}
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
                month    : 'short',
                day      : 'numeric',
                hour     : 'numeric',
                minute   : '2-digit',
                timeZone : this.appTimezone || 'America/New_York'
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
    // TIME SAVED DASHBOARD METHODS
    // ========================================

    async refreshTimeSavedStats() {
        /**
         * Fetch and display time saved statistics from the API.
         *
         * Requires:
         *     - User is authenticated with valid accessToken
         *     - /api/stats/time-saved and /api/stats/time-saved/global endpoints available
         *
         * Ensures:
         *     - Updates dashboard stat elements with current values
         *     - Renders top solutions leaderboard
         *     - Handles errors gracefully
         */
        this.log( 'Refreshing Time Saved Dashboard stats...' );

        try {
            // Fetch user-specific stats
            const response = await fetch( '/api/stats/time-saved', {
                headers: { 'Authorization': `Bearer ${this.accessToken}` }
            } );

            if ( response.ok ) {
                const stats = await response.json();
                this.log( `Time saved stats received: ${JSON.stringify( stats )}` );

                // Update stat elements
                const timeSavedTotal = document.getElementById( 'time-saved-total' );
                const timeSavedOthers = document.getElementById( 'time-saved-others' );
                const solutionsCreated = document.getElementById( 'solutions-created' );
                const replaysBenefited = document.getElementById( 'replays-benefited' );

                if ( timeSavedTotal ) timeSavedTotal.textContent = stats.total_time_saved_formatted || '--';
                if ( timeSavedOthers ) timeSavedOthers.textContent = stats.time_saved_for_others_formatted || '--';
                if ( solutionsCreated ) solutionsCreated.textContent = stats.solutions_created || 0;
                if ( replaysBenefited ) replaysBenefited.textContent = stats.total_replays_benefited || 0;
            } else {
                this.log( `Failed to fetch time saved stats: ${response.status}`, 'error' );
            }

            // Also fetch global stats for top solutions
            const globalResponse = await fetch( '/api/stats/time-saved/global', {
                headers: { 'Authorization': `Bearer ${this.accessToken}` }
            } );

            if ( globalResponse.ok ) {
                const globalStats = await globalResponse.json();
                this.log( `Global stats received: ${globalStats.total_solutions} solutions, ${globalStats.total_replays} replays` );
                this.renderTopSolutions( globalStats.top_solutions );
            } else {
                this.log( `Failed to fetch global stats: ${globalResponse.status}`, 'error' );
            }
        } catch ( error ) {
            this.log( `Error fetching time saved stats: ${error}`, 'error' );
        }
    }

    renderTopSolutions( solutions ) {
        /**
         * Render the top solutions leaderboard.
         *
         * Requires:
         *     - solutions is an array of solution objects with question, replays, time_saved_formatted
         *
         * Ensures:
         *     - Renders ranked list of top solutions
         *     - Shows "no data" message if empty
         *     - Escapes HTML in question text
         */
        const container = document.getElementById( 'top-solutions-list' );
        if ( !container ) return;

        if ( !solutions || solutions.length === 0 ) {
            container.innerHTML = '<p class="no-data">No replayed solutions yet</p>';
            return;
        }

        container.innerHTML = solutions.map( ( sol, idx ) => `
            <div class="top-solution-item">
                <span class="rank">#${idx + 1}</span>
                <span class="question">${this.escapeHtml( sol.question )}</span>
                <span class="stats">${sol.replays} replays · ${sol.time_saved_formatted} saved</span>
            </div>
        ` ).join( '' );
    }

    // ========================================
    // ABSTRACT TOOLTIP FOR NOTIFICATIONS HISTORY
    // ========================================

    initAbstractTooltip() {
        /**
         * Initialize abstract tooltip container and click handler.
         *
         * Purpose: Allow users to view abstract details from notifications
         * in the history section by clicking a 📋 indicator.
         *
         * Requires:
         *     - DOM is ready
         *
         * Ensures:
         *     - Single tooltip container created in body
         *     - Click delegation handles indicator clicks
         *     - Click outside closes tooltip
         */

        // Create tooltip container (once)
        if ( !document.getElementById( 'abstract-tooltip' ) ) {
            const tooltip = document.createElement( 'div' );
            tooltip.id = 'abstract-tooltip';
            tooltip.className = 'abstract-tooltip';
            tooltip.innerHTML = `
                <div class="abstract-tooltip-header">
                    <span>📋 Details</span>
                    <button class="abstract-tooltip-close" title="Close">&times;</button>
                </div>
                <div class="abstract-tooltip-content"></div>
            `;
            document.body.appendChild( tooltip );

            // Close button handler
            tooltip.querySelector( '.abstract-tooltip-close' ).addEventListener( 'click', () => {
                tooltip.classList.remove( 'visible' );
            } );

            this.log( 'Abstract tooltip container initialized' );
        }

        // Event delegation for abstract indicator clicks
        document.addEventListener( 'click', ( e ) => {
            const indicator = e.target.closest( '.abstract-indicator' );
            const tooltip = document.getElementById( 'abstract-tooltip' );

            if ( indicator ) {
                e.stopPropagation();
                const abstract = decodeURIComponent( indicator.dataset.abstract );
                const content = tooltip.querySelector( '.abstract-tooltip-content' );
                // Render markdown with XSS protection (was: content.textContent = abstract)
                content.innerHTML = this.renderMarkdown( abstract );

                // Position near the indicator
                const rect = indicator.getBoundingClientRect();
                const tooltipHeight = 200; // Approximate initial height
                const viewportHeight = window.innerHeight;

                // Position below indicator, but flip above if near bottom
                let top = rect.bottom + 8;
                if ( top + tooltipHeight > viewportHeight ) {
                    top = rect.top - tooltipHeight - 8;
                }

                // Keep within horizontal bounds
                let left = Math.max( 10, rect.left - 100 );
                left = Math.min( left, window.innerWidth - 420 );

                tooltip.style.top = `${top}px`;
                tooltip.style.left = `${left}px`;
                tooltip.classList.add( 'visible' );

            } else if ( !e.target.closest( '.abstract-tooltip' ) ) {
                // Click outside closes tooltip
                if ( tooltip ) {
                    tooltip.classList.remove( 'visible' );
                }
            }
        } );

        // Close on Escape key
        document.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Escape' ) {
                const tooltip = document.getElementById( 'abstract-tooltip' );
                if ( tooltip ) {
                    tooltip.classList.remove( 'visible' );
                }
            }
        } );
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

            // Scroll the newly-shown section into view
            this.scrollIntoViewIfNeeded( section );
        }

        this.saveSectionVisibility();

        // Update TTS queue section to show/hide empty state when toggled
        if ( sectionId === 'tts-queue-section' ) {
            this.updateTTSQueueSection();
        }
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

        // Update TTS queue section to show/hide empty state based on restored visibility
        this.updateTTSQueueSection();

        this.log( 'Section visibility state restored from localStorage' );
    }

    // ========================================
    // QUEUE CATEGORY EXPAND/COLLAPSE PERSISTENCE
    // ========================================

    saveQueueExpandState() {
        /**
         * Save queue category expand/collapse state to localStorage.
         *
         * Ensures:
         *     - All queue category expanded states saved as JSON
         *     - Persists across page refreshes and browser restarts
         */
        const state = {};
        Object.keys( this.queueCategoryState ).forEach( queueName => {
            state[ queueName ] = this.queueCategoryState[ queueName ].expanded;
        } );
        localStorage.setItem( this.QUEUE_EXPAND_STATE_KEY, JSON.stringify( state ) );
        this.log( 'Queue expand state saved to localStorage' );
    }

    loadQueueExpandState() {
        /**
         * Load queue expand state from localStorage.
         *
         * Ensures:
         *     - Returns saved state object or null if not found
         *     - Handles JSON parse errors gracefully
         */
        try {
            const saved = localStorage.getItem( this.QUEUE_EXPAND_STATE_KEY );
            return saved ? JSON.parse( saved ) : null;
        } catch ( e ) {
            this.error( 'Error loading queue expand state:', e );
            return null;
        }
    }

    applyQueueExpandState() {
        /**
         * Apply saved queue expand state on page load.
         *
         * Requires:
         *     - Queue categories have been rendered
         *     - queueCategoryState is initialized
         *
         * Ensures:
         *     - All queue categories restored to their saved expand/collapse state
         *     - Only expanded queues trigger lazy loading of job cards
         */
        const savedState = this.loadQueueExpandState();
        if ( !savedState ) {
            this.log( 'No saved queue expand state - using defaults (all collapsed)' );
            return;
        }

        Object.keys( savedState ).forEach( queueName => {
            if ( savedState[ queueName ] === true && this.queueCategoryState[ queueName ] ) {
                // Queue was expanded - restore that state
                this.toggleQueueCategory( queueName );
            }
        } );

        this.log( 'Queue expand state restored from localStorage' );
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
            user_id: this.currentUserEmail,
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
        // Project segment must allow hyphens for nested repos like
        // "lupin-mobile" and "lupin-plugin-firefox". Matches the canonical
        // pattern used by cosa_voice_mcp.py and notification_models.py.
        const match = senderId.match( /^claude\.code@([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\.deepily\.ai/ );
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

        // Parse agent type and project. Project segment must allow hyphens
        // for nested repos like "lupin-mobile" and "lupin-plugin-firefox".
        const match = base.match( /^([^@]+)@([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\.deepily\.ai$/ );
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
     * Look up the voice_id for a given sender_id from the per-session
     * persona map. Returns null when no persona is known (server-side
     * default kicks in — Sam, the system default).
     *
     * Hydration happens in handleNotificationUpdate as soon as a
     * notification with a voice_persona payload arrives. The server
     * stamps voice_persona on every outbound envelope (see
     * src/cosa/rest/routers/notifications.py _voice_persona_for_sender_id).
     *
     * @param {string|null} senderId - Sender id (e.g., claude.code@lupin.deepily.ai#c7333045)
     * @returns {string|null} voice_id or null
     */
    getVoiceIdForSender( senderId ) {
        if ( !senderId ) return null;
        const persona = this.senderPersonaMap.get( senderId );
        return persona && persona.voice_id ? persona.voice_id : null;
    }

    /**
     * Look up the full persona object for a given sender_id.
     * Used by sender-card badge rendering.
     *
     * @param {string|null} senderId
     * @returns {object|null} persona dict or null
     */
    getPersonaForSender( senderId ) {
        if ( !senderId ) return null;
        return this.senderPersonaMap.get( senderId ) || null;
    }

    /**
     * Convert a hex color (e.g., "#E91E63") into the comma-separated RGB
     * triplet form ("233, 30, 99") that CSS `rgba()` consumes.
     *
     * Used to produce --persona-color-rgb on each sender card so Tier 1
     * (border + shadow) and Tier 2 (header gradient) CSS rules can apply
     * persona color with arbitrary alpha via rgba(var(--persona-color-rgb), 0.55).
     *
     * Returns null on malformed input — caller should skip setting the var.
     *
     * @param {string|null} hex — "#RRGGBB" or "#RGB"
     * @returns {string|null} "r, g, b" or null on parse failure
     */
    _hexToRgb( hex ) {
        if ( !hex || typeof hex !== "string" ) return null;
        let h = hex.trim().replace( /^#/, "" );
        if ( h.length === 3 ) {
            h = h.split( "" ).map( c => c + c ).join( "" );
        }
        if ( h.length !== 6 || !/^[0-9a-fA-F]{6}$/.test( h ) ) return null;
        const r = parseInt( h.substring( 0, 2 ), 16 );
        const g = parseInt( h.substring( 2, 4 ), 16 );
        const b = parseInt( h.substring( 4, 6 ), 16 );
        return `${r}, ${g}, ${b}`;
    }

    /**
     * Build the persona-badge HTML string for a given persona dict.
     * Returns '' when persona is null/undefined so callers can safely
     * inject the result into a template literal.
     *
     * Centralizes the markup so createSenderCard and the live DOM-patch
     * path (handleNotificationUpdate dispatch for voice_persona_assigned)
     * produce identical badges.
     *
     * @param {object|null} persona — { name, display_name, color, icon, profile, borrowed }
     * @returns {string} badge HTML, or '' when persona is null
     */
    _renderPersonaBadgeHTML( persona ) {
        if ( !persona ) return '';
        const borrowedClass = persona.borrowed ? ' borrowed' : '';
        const borrowedTitle = persona.borrowed ? ' (borrowed — pool exhausted)' : '';
        const profile       = persona.profile ? ` — ${persona.profile}` : '';
        // Pool names are stored lowercase, no-punctuation per project key
        // convention (e.g. "mr radio"). The server stamps `display_name`
        // (e.g. "Mr. Radio") via voice_persona_helpers.display_name_for for
        // UI surfaces. Fall back to `name` only if `display_name` is absent
        // (legacy envelope or hand-built persona dict).
        const label = persona.display_name || persona.name || '';
        return `<span class="persona-badge${borrowedClass}"
                  style="background-color: ${persona.color || '#888'};"
                  title="${label}${borrowedTitle}${profile}">
                <span class="persona-badge-icon">${persona.icon || '🎙️'}</span>
                <span class="persona-badge-name">${label}</span>
            </span>`;
    }

    /**
     * Patch an EXISTING sender-card header in place to reflect the given
     * persona. Used after voice_persona_assigned/released arrives so the
     * badge appears (or disappears) without waiting for a re-render.
     *
     * Behavior:
     *   - persona truthy + no badge present → insert badge before stats group
     *   - persona truthy + badge already present → replace badge
     *   - persona null → remove existing badge if present
     *   - card not found → no-op (card may be rendered later via createSenderCard,
     *     which will read senderPersonaMap and pick up the persona then)
     *
     * @param {string} senderId
     * @param {object|null} persona
     */
    _setPersonaBadgeOnCard( senderId, persona ) {
        if ( !senderId ) return;
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card   = document.getElementById( cardId );
        if ( !card ) return;
        const header = card.querySelector( ':scope > .sender-card-header' );
        if ( !header ) return;

        // Locate the existing badge (now inside .sender-stats-group as its first
        // child — see createSenderCard). Search the whole header so we also
        // catch legacy-positioned badges from cards rendered before the
        // 2026-04-29 right-align relocation.
        const existingBadge = header.querySelector( '.persona-badge' );
        const statsGroup    = header.querySelector( ':scope > .sender-stats-group' );

        if ( !persona ) {
            if ( existingBadge ) existingBadge.remove();
            // Foundation: also clear the persona-color custom properties on the
            // card so Tier 1/2 CSS rules fall back to their defaults.
            card.style.removeProperty( "--persona-color"     );
            card.style.removeProperty( "--persona-color-rgb" );
            // Mirror the clear onto the strip icon.
            this._setStripIconPersonaColor( senderId, null );
            return;
        }

        // Foundation: set --persona-color and --persona-color-rgb on the card
        // so Tier 1 (border + shadow) and Tier 2 (header gradient) CSS rules
        // pick up the persona color via var() with no inline-style coupling.
        if ( persona.color ) {
            card.style.setProperty( "--persona-color", persona.color );
            const rgb = this._hexToRgb( persona.color );
            if ( rgb ) card.style.setProperty( "--persona-color-rgb", rgb );
            // Mirror the persona-color update onto the strip icon.
            this._setStripIconPersonaColor( senderId, persona.color );
        }

        const html = this._renderPersonaBadgeHTML( persona );
        if ( existingBadge ) {
            existingBadge.outerHTML = html;
            return;
        }

        // Insert as the FIRST child of .sender-stats-group so the badge sits
        // in the right-aligned cluster (stats group has margin-left: auto).
        const tmp = document.createElement( 'template' );
        tmp.innerHTML = html.trim();
        const badgeNode = tmp.content.firstChild;
        if ( statsGroup ) {
            statsGroup.insertBefore( badgeNode, statsGroup.firstChild );
        } else {
            header.appendChild( badgeNode );
        }
    }

    // ============================================================
    // CC SESSION SELECTOR STRIP + EXCLUSIVE FOCUS MODE
    // Design: src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md
    // Permanent chrome above #notifications-list. One icon per active CC
    // session. Leftmost = most recently updated. Embedded toggle pill
    // enters/exits focus mode (only the focused session's card is rendered).
    // Orthogonal to conversation mode.
    // ============================================================

    /**
     * Build the DOM id used for a strip icon, derived from senderId
     * with the same escaping rules used for sender-card ids.
     */
    _stripIconIdFor( senderId ) {
        return `cc-strip-icon-${senderId.replace( /[@.#]/g, '-' )}`;
    }

    /**
     * Add a CC session icon to the selector strip. Idempotent — calling
     * twice for the same senderId is a no-op (the existing icon is
     * promoted to leftmost via _promoteStripIcon if you want that effect).
     *
     * Requires:
     *   - senderId is a non-empty string
     *   - This is a claude.code session (caller filters)
     */
    _addStripIcon( senderId, projectName, persona, sessionId ) {
        const iconsContainer = document.getElementById( "cc-strip-icons" );
        const strip          = document.getElementById( "cc-session-strip" );
        if ( !iconsContainer || !strip ) return;

        const iconId = this._stripIconIdFor( senderId );
        if ( document.getElementById( iconId ) ) return;  // idempotent

        const initial = ( projectName || "?" ).charAt( 0 ).toUpperCase();
        const color   = persona?.color || null;

        const icon = document.createElement( "div" );
        icon.id = iconId;
        icon.className = "cc-strip-icon";
        icon.setAttribute( "data-sender-id", senderId );
        if ( sessionId ) icon.setAttribute( "data-session-id", sessionId );
        icon.setAttribute( "title", `${projectName}${sessionId ? " #" + sessionId : ""}` );
        icon.textContent = initial;
        if ( color ) {
            icon.style.setProperty( "--persona-color", color );
        }

        // Mark focused if focus mode is on and this senderId matches the
        // persisted focused id (covers the case where a card for a
        // previously-focused session arrives after a page reload).
        if ( this.ccFocusState.enabled
             && this.ccFocusState.focused_sender_id === senderId ) {
            icon.setAttribute( "data-focused", "true" );
        }

        // Mirror conv-mode state if the bridge already says this session
        // is in conv-mode (handled separately for live changes).
        if ( sessionId && this.conversationModes && this.conversationModes[ sessionId ] ) {
            icon.setAttribute( "data-conv-mode", "true" );
        }

        // Click dispatch — scroll-to-card in default mode, switch-focus in focus mode.
        icon.addEventListener( "click", ( ev ) => {
            ev.stopPropagation();
            this._handleStripIconClick( senderId );
        } );

        // Insert at leftmost (newest icon = newest activity).
        if ( iconsContainer.firstChild ) {
            iconsContainer.insertBefore( icon, iconsContainer.firstChild );
        } else {
            iconsContainer.appendChild( icon );
        }

        // First icon → reveal the strip.
        if ( strip.hasAttribute( "hidden" ) ) {
            strip.removeAttribute( "hidden" );
        }
    }

    /**
     * Remove a CC session icon from the selector strip. If the removed
     * session was the focused session, auto-exit focus mode so the user
     * isn't stranded staring at a now-empty pane.
     */
    _removeStripIcon( senderId ) {
        const iconsContainer = document.getElementById( "cc-strip-icons" );
        const strip          = document.getElementById( "cc-session-strip" );
        if ( !iconsContainer ) return;

        const icon = document.getElementById( this._stripIconIdFor( senderId ) );
        if ( icon ) icon.remove();

        // If the deleted session was the focused one, exit focus mode.
        if ( this.ccFocusState.enabled
             && this.ccFocusState.focused_sender_id === senderId ) {
            this._exitFocusMode();
        }

        delete this.ccStripUnreadCounts[ senderId ];

        // Hide the whole strip when no icons remain.
        if ( strip && iconsContainer.children.length === 0 ) {
            strip.setAttribute( "hidden", "" );
        }
    }

    /**
     * Clear ALL strip icons in one shot. Used by bulk-clear paths
     * (Clear All, history-window change) where every sender card is
     * being torn down at once and per-sender _removeStripIcon would
     * thrash. Side effects mirror _removeStripIcon's cleanup:
     *   - Exits focus mode if active.
     *   - Empties #cc-strip-icons and hides #cc-session-strip.
     *   - Resets ccStripUnreadCounts.
     */
    _clearAllStripIcons() {
        if ( this.ccFocusState && this.ccFocusState.enabled ) {
            this._exitFocusMode();
        }

        const iconsContainer = document.getElementById( "cc-strip-icons" );
        if ( iconsContainer ) {
            iconsContainer.innerHTML = "";
        }

        const strip = document.getElementById( "cc-session-strip" );
        if ( strip ) {
            strip.setAttribute( "hidden", "" );
        }

        this.ccStripUnreadCounts = {};
    }

    /**
     * Move the icon for senderId to leftmost (most-recent-activity slot).
     * Called from moveSenderCardToTop's path so strip ordering stays
     * synchronized with stack ordering. Idempotent — if the icon is
     * already leftmost, no DOM mutation occurs.
     *
     * Side effect: when focus mode is on AND this senderId is NOT the
     * focused session, increment the unread badge so the user gets
     * peripheral awareness of activity on hidden sessions.
     */
    _promoteStripIcon( senderId ) {
        const iconsContainer = document.getElementById( "cc-strip-icons" );
        if ( !iconsContainer ) return;

        const icon = document.getElementById( this._stripIconIdFor( senderId ) );
        if ( !icon ) return;

        if ( iconsContainer.firstChild !== icon ) {
            iconsContainer.insertBefore( icon, iconsContainer.firstChild );
        }

        // Bump unread badge for non-focused sessions in focus mode.
        if ( this.ccFocusState.enabled
             && this.ccFocusState.focused_sender_id !== senderId ) {
            const next = ( this.ccStripUnreadCounts[ senderId ] || 0 ) + 1;
            this.ccStripUnreadCounts[ senderId ] = next;
            icon.setAttribute( "data-unread", "true" );
            icon.setAttribute( "data-unread-count", String( next ) );
        }
    }

    /**
     * Update the persona color on a strip icon. Mirror of
     * _setPersonaBadgeOnCard's color-var update for cards.
     * @param {string} senderId
     * @param {string|null} color — hex string or null to revert
     */
    _setStripIconPersonaColor( senderId, color ) {
        const icon = document.getElementById( this._stripIconIdFor( senderId ) );
        if ( !icon ) return;

        if ( color ) {
            icon.style.setProperty( "--persona-color", color );
        } else {
            icon.style.removeProperty( "--persona-color" );
        }
    }

    /**
     * Set/clear the conv-mode mic overlay on a strip icon, looked up by
     * sessionId (which is what the conversation_mode_changed event
     * carries). Each strip icon has both data-sender-id and
     * data-session-id for flexible lookup.
     */
    _setStripIconConvMode( sessionId, isOn ) {
        if ( !sessionId ) return;
        const icon = document.querySelector(
            `#cc-strip-icons .cc-strip-icon[data-session-id="${sessionId}"]`
        );
        if ( !icon ) return;

        if ( isOn ) {
            icon.setAttribute( "data-conv-mode", "true" );
        } else {
            icon.removeAttribute( "data-conv-mode" );
        }
    }

    /**
     * Enter exclusive focus mode for the given senderId. All sender
     * cards except the focused one are hidden via data-focus-hidden.
     * Persists state to localStorage so reload restores the same focus.
     *
     * @param {string} senderId - Session to focus on
     * @param {boolean} flash - Briefly highlight the focused card on entry.
     *   True for the off→on toggle (user just turned focus mode on; flash
     *   draws their eye to which card now has it). False for mid-mode
     *   focus switches (user clicked a strip icon — they already know).
     */
    _enterFocusMode( senderId, flash = false ) {
        if ( !senderId ) return;

        this.ccFocusState = { enabled: true, focused_sender_id: senderId };
        this._saveCcFocusState();

        // Mark the toggle pill as active.
        const toggle = document.getElementById( "cc-strip-toggle" );
        if ( toggle ) {
            toggle.setAttribute( "data-focus-active", "true" );
            toggle.textContent = "👁 Focus: ON";
        }

        // Walk all strip icons: mark focused, clear focused on others.
        const icons = document.querySelectorAll( "#cc-strip-icons .cc-strip-icon" );
        icons.forEach( ( icon ) => {
            const iconSender = icon.getAttribute( "data-sender-id" );
            if ( iconSender === senderId ) {
                icon.setAttribute( "data-focused", "true" );
                this._clearStripUnreadFor( iconSender );  // visiting this session clears its badge
            } else {
                icon.removeAttribute( "data-focused" );
            }
        } );

        // Walk all sender cards: hide all except the focused one.
        const cards = document.querySelectorAll( "#notifications-list .sender-card" );
        const expectedId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        cards.forEach( ( card ) => {
            if ( card.id === expectedId ) {
                card.removeAttribute( "data-focus-hidden" );
            } else {
                card.setAttribute( "data-focus-hidden", "true" );
            }
        } );

        if ( flash ) this._flashFocusedCard( expectedId );
    }

    /**
     * Briefly highlight the focused sender card so the user sees which
     * card now holds focus. Implemented via a short data-focus-flash
     * attribute that drives a CSS keyframe animation in notifications.css.
     */
    _flashFocusedCard( cardId ) {
        const card = document.getElementById( cardId );
        if ( !card ) return;

        // Restart the animation if a previous flash is still in flight
        // (e.g. user double-toggles): clearing then setting on the next
        // frame forces the keyframe to replay from 0%.
        card.removeAttribute( "data-focus-flash" );
        // Force reflow so the re-set attribute is treated as a state change.
        // eslint-disable-next-line no-unused-expressions
        void card.offsetWidth;
        card.setAttribute( "data-focus-flash", "true" );

        const cleanup = () => card.removeAttribute( "data-focus-flash" );
        card.addEventListener( "animationend", cleanup, { once: true } );
        // Belt-and-suspenders: drop the attribute after a fixed timeout in case
        // the animation never fires (e.g. card is detached mid-flash).
        setTimeout( cleanup, 2000 );
    }

    /**
     * Exit focus mode — revert all cards to visible, clear focused state.
     */
    _exitFocusMode() {
        this.ccFocusState = { enabled: false, focused_sender_id: null };
        this._saveCcFocusState();

        const toggle = document.getElementById( "cc-strip-toggle" );
        if ( toggle ) {
            toggle.setAttribute( "data-focus-active", "false" );
            toggle.textContent = "👁 Focus";
        }

        // Clear focused-marker on all icons.
        document.querySelectorAll( "#cc-strip-icons .cc-strip-icon[data-focused]" )
                .forEach( ( icon ) => icon.removeAttribute( "data-focused" ) );

        // Reveal all cards.
        document.querySelectorAll( "#notifications-list .sender-card[data-focus-hidden]" )
                .forEach( ( card ) => card.removeAttribute( "data-focus-hidden" ) );

        // Visiting all sessions clears all unread badges.
        document.querySelectorAll( "#cc-strip-icons .cc-strip-icon[data-unread]" )
                .forEach( ( icon ) => {
                    icon.removeAttribute( "data-unread" );
                    icon.removeAttribute( "data-unread-count" );
                } );
        this.ccStripUnreadCounts = {};
    }

    /**
     * Click dispatcher for a strip icon. Behavior depends on mode:
     *   - Default mode → smooth-scroll the corresponding card into view
     *   - Focus mode, different session → switch focus to clicked
     *   - Focus mode, same session → no-op
     */
    _handleStripIconClick( senderId ) {
        if ( this.ccFocusState.enabled ) {
            if ( this.ccFocusState.focused_sender_id === senderId ) return;  // no-op
            this._enterFocusMode( senderId );
            return;
        }

        // Default mode → scroll to that card.
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card   = document.getElementById( cardId );
        if ( card ) {
            card.scrollIntoView( { behavior: "smooth", block: "start" } );
        }
    }

    /**
     * Click handler for the focus-toggle pill. Off → on (using leftmost
     * icon's senderId or the persisted focused id); on → off.
     */
    _handleStripToggleClick() {
        if ( this.ccFocusState.enabled ) {
            this._exitFocusMode();
            return;
        }

        // Determine which session to focus: prefer persisted choice, else
        // leftmost icon (= most recently updated).
        let targetSenderId = this.ccFocusState.focused_sender_id;
        if ( !targetSenderId ) {
            const firstIcon = document.querySelector( "#cc-strip-icons .cc-strip-icon" );
            if ( firstIcon ) targetSenderId = firstIcon.getAttribute( "data-sender-id" );
        }
        if ( !targetSenderId ) {
            this.log( "Focus toggle: no CC sessions to focus on" );
            return;
        }

        this._enterFocusMode( targetSenderId, true );  // flash on off→on entry
    }

    /**
     * Wire up the toggle pill's click handler. Called once from the
     * constructor — the button exists in the HTML at page load.
     */
    _bindStripToggle() {
        const toggle = document.getElementById( "cc-strip-toggle" );
        if ( !toggle ) return;
        toggle.addEventListener( "click", ( ev ) => {
            ev.stopPropagation();
            this._handleStripToggleClick();
        } );
    }

    /**
     * Apply data-focus-hidden to a card if focus is on and the card is
     * not the focused sender. Called from createSenderCard so newly
     * inserted cards respect existing focus mode.
     */
    _applyFocusHiddenToCard( card, senderId ) {
        if ( !this.ccFocusState.enabled ) return;
        if ( this.ccFocusState.focused_sender_id === senderId ) return;
        card.setAttribute( "data-focus-hidden", "true" );
    }

    /**
     * Clear the unread badge + counter for a single sender's strip icon.
     */
    _clearStripUnreadFor( senderId ) {
        const icon = document.getElementById( this._stripIconIdFor( senderId ) );
        if ( icon ) {
            icon.removeAttribute( "data-unread" );
            icon.removeAttribute( "data-unread-count" );
        }
        delete this.ccStripUnreadCounts[ senderId ];
    }

    /**
     * Persist focus-mode state to localStorage.
     */
    _saveCcFocusState() {
        try {
            localStorage.setItem(
                this.CC_FOCUS_STATE_KEY,
                JSON.stringify( this.ccFocusState )
            );
        } catch ( err ) {
            this.error( "Failed to persist cc focus state:", err );
        }
    }

    /**
     * Save a session name to localStorage.
     * @param {string} sessionId - Session ID (hex string)
     * @param {string} name - Session name to save
     * @param {object} options - Optional flags: { fromServer: true } to skip push-back
     */
    saveSessionName( sessionId, name, options = {} ) {
        this.sessionNames[ sessionId ] = name;
        localStorage.setItem( this.SESSION_NAMES_KEY, JSON.stringify( this.sessionNames ) );
        this.log( `Saved session name for ${sessionId}: ${name}` );
        // Only push back to server if this came from the UI (not from server)
        if ( !options.fromServer ) {
            this.pushSessionTopicNotification( sessionId, name );
        }
    }

    /**
     * Push a session topic notification so the CC listener can update the session bridge file.
     * Uses hybrid encoding: type=custom, title=action:set_session_topic, job_id=sessionHash.
     * @param {string} sessionId - Session ID (8-char hex hash)
     * @param {string} topic - The session topic text
     */
    async pushSessionTopicNotification( sessionId, topic ) {
        try {
            await fetch( '/api/notify', {
                method  : 'POST',
                headers : { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body    : JSON.stringify( {
                    message       : topic,
                    type          : 'custom',
                    title         : 'action:set_session_topic',
                    job_id        : sessionId,
                    priority      : 'low',
                    suppress_ding : true
                } )
            } );
            this.log( `Pushed session topic notification for ${sessionId}: ${topic}` );
        } catch ( error ) {
            this.log( `Failed to push session topic: ${error.message}` );
        }
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
     * Toggle conversation mode for a session via the cosa-voice HTTP endpoint.
     *
     * The server bridge file is canonical. We POST the desired state, then update our
     * local cache + widget eagerly for responsiveness; the WebSocket
     * conversation_mode_changed broadcast that follows is the authoritative confirmation
     * (it lands in handleConversationModeChanged() and reconciles).
     *
     * @param {string} sessionId - Per-session_id key (8-char hex from sender_id)
     */
    async toggleConversationMode( sessionId ) {
        if ( !sessionId ) return;
        const current = !!this.conversationModes[ sessionId ];
        const next    = !current;
        try {
            const response = await this.authedFetch(
                `/api/cosa-voice/conversation-mode/${encodeURIComponent( sessionId )}`,
                {
                    method  : 'POST',
                    headers : { 'Content-Type': 'application/json' },
                    body    : JSON.stringify( { active: next } )
                }
            );
            if ( !response.ok ) {
                const errText = await response.text().catch( () => '' );
                this.error( `[CONVERSATION-MODE] toggle failed (${response.status}): ${errText}` );
                return;
            }
            // Optimistic local update — WS broadcast will reaffirm
            this._setConversationModeLocal( sessionId, next );

            // UX expediter: when ENTERING conversation mode (not exiting),
            // shift focus to the recording button. Clicking into conversation
            // mode is a strong signal the user wants to speak; pre-focusing
            // the mic shaves a step off "click toggle → click mic → speak".
            if ( next ) {
                const recBtn = document.getElementById( `cc-session-stt-${sessionId}` );
                if ( recBtn ) recBtn.focus();
            }
        } catch ( e ) {
            this.error( `[CONVERSATION-MODE] toggle exception: ${e}` );
        }
    }

    /**
     * Apply a conversation_mode_changed WebSocket envelope.
     *
     * Server-canonical state — overwrites localStorage cache + redraws all toggle widgets
     * matching this session_id (multiple sender cards may share the session_id if the
     * UI happens to render duplicates).
     *
     * @param {object} envelope - WebSocket message envelope:
     *     { type, session_id, conversation_mode_active, timestamp }
     */
    handleConversationModeChanged( envelope ) {
        const rawSessionId = envelope?.session_id;
        const active       = !!envelope?.conversation_mode_active;
        const displaced    = envelope?.displaced === true;
        const displacedBy  = envelope?.displaced_by || null;
        if ( !rawSessionId ) {
            this.log( '[CONVERSATION-MODE] WS event missing session_id, ignoring' );
            return;
        }
        // Normalize to 8-char prefix — the UI's data-session-id (set in
        // createSenderCard via parseSenderId) is keyed by the 8-char form
        // extracted from sender_id like "claude.code@lupin.deepily.ai#c7333045".
        // Server-side displace events emit the FULL UUID read from the bridge
        // file; without this normalization, downstream selector lookups
        // .sender-conversation-mode-btn[data-session-id="<full-uuid>"] miss
        // the actual button DOM, leaving the toggle icon stuck on the
        // displaced session. (Bug surfaced 2026-04-28 during multi-session
        // mutex testing.)
        const sessionId = ( typeof rawSessionId === 'string' && rawSessionId.length > 8 )
            ? rawSessionId.substring( 0, 8 )
            : rawSessionId;
        this._setConversationModeLocal( sessionId, active );

        // Mutex side effect: when this session was displaced by another, pause
        // any in-flight TTS so the user's audio focus doesn't trail behind
        // the toggle they just made on the OTHER session. The user can resume
        // manually via the global play or per-notification corner button.
        if ( displaced && this.activeTTSItem && !this.isTTSPaused ) {
            this.log( `[CONVERSATION-MODE] session ${sessionId} displaced by ${displacedBy} — pausing in-flight TTS` );
            this.pauseTTS();
        }

        // Pin/unpin the active conversation pane in the notifications accordion
        if ( active ) {
            this._pinSenderCardForSession( sessionId );
        } else {
            this._unpinSenderCardForSession( sessionId );
        }

        // Strip-icon mic overlay must follow the same normalized session_id —
        // the WS payload carries the full UUID but icons are keyed by the
        // 8-char prefix. Without this the OFF transition silently misses the
        // selector and the mic icon strands in the focus tray.
        this._setStripIconConvMode( sessionId, active );

        this.log( `[CONVERSATION-MODE] session ${sessionId} → ${active ? 'conversation' : 'notification'} mode (via WS${displaced ? ', displaced' : ''})` );
    }

    /**
     * Pin the sender card whose session_id matches the given id to DOM index 0
     * of #notifications-list, marking it with data-pinned-conv-mode="true" so
     * the soft-glow CSS rule applies and the sort-respecting insertion logic
     * keeps it at the top regardless of activity from other sessions.
     *
     * Unpins any previously-pinned card so the invariant "at most one pinned
     * card at a time" holds (matches the server-side mutex).
     *
     * @param {string} sessionId - The session whose card should be pinned
     */
    _pinSenderCardForSession( sessionId ) {
        if ( !sessionId ) return;

        const container = document.getElementById( 'notifications-list' );
        if ( !container ) return;

        // Unpin any previously-pinned card belonging to a DIFFERENT session
        // (server-side mutex guarantees only one is active at a time, but the
        // UI reconciles defensively in case events arrive out of order).
        const previouslyPinned = container.querySelectorAll( '.sender-card[data-pinned-conv-mode="true"]' );
        previouslyPinned.forEach( card => {
            if ( card.getAttribute( 'data-session-id' ) !== sessionId ) {
                card.removeAttribute( 'data-pinned-conv-mode' );
            }
        } );

        // Find the target card by session_id (data attribute set in createSenderCard).
        const card = container.querySelector( `.sender-card[data-session-id="${sessionId}"]` );
        if ( !card ) {
            // Card may not exist yet (first notification for this session arrives
            // later). When createSenderCard runs, it consults conversationModes
            // and pins itself if active=true at insertion time.
            this.log( `[CONVERSATION-MODE] _pinSenderCardForSession(${sessionId}) — no card yet, pin deferred to createSenderCard` );
            return;
        }

        card.setAttribute( 'data-pinned-conv-mode', 'true' );
        if ( container.firstChild !== card ) {
            container.insertBefore( card, container.firstChild );
        }
    }

    /**
     * Remove the data-pinned-conv-mode attribute from the matching sender card,
     * letting it resume normal activity-based sorting. Called on deactivate
     * (active=false) and on displaced events.
     *
     * @param {string} sessionId - The session whose card should be unpinned
     */
    _unpinSenderCardForSession( sessionId ) {
        if ( !sessionId ) return;
        const container = document.getElementById( 'notifications-list' );
        if ( !container ) return;
        const card = container.querySelector(
            `.sender-card[data-session-id="${sessionId}"][data-pinned-conv-mode="true"]`
        );
        if ( card ) {
            card.removeAttribute( 'data-pinned-conv-mode' );
        }
    }

    /**
     * Update the local cache + DOM widget for a session's conversation mode.
     * Internal helper — NOT a server write. Used by both optimistic toggle and WS sync.
     *
     * @param {string} sessionId - Session ID
     * @param {boolean} active - Target state
     */
    _setConversationModeLocal( sessionId, active ) {
        this.conversationModes[ sessionId ] = !!active;
        try {
            localStorage.setItem( this.CONVERSATION_MODES_KEY, JSON.stringify( this.conversationModes ) );
        } catch ( e ) {
            this.log( `[CONVERSATION-MODE] localStorage write failed (cache only): ${e}` );
        }

        // Redraw any matching toggle button(s). data-session-id selector matches both
        // the sender-card itself and the per-session toggle button.
        const buttons = document.querySelectorAll(
            `.sender-conversation-mode-btn[data-session-id="${sessionId}"]`
        );
        buttons.forEach( btn => {
            btn.textContent = active ? '📞' : '🔔';
            btn.title       = active
                ? 'Conversation mode ON — every Claude response is spoken (click to switch to notification mode)'
                : 'Notification mode (default) — only explicit notify() calls speak (click to switch to conversation mode)';
            btn.classList.toggle( 'is-active', active );
        } );
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

        // Collect both messages and abstracts for richer gist generation
        const messages = allNotifications.map( n => n.message ).filter( Boolean );
        const abstracts = allNotifications.map( n => n.abstract ).filter( Boolean );

        if ( messages.length === 0 && abstracts.length === 0 ) {
            this.log( 'No messages or abstracts for gist generation' );
            return;
        }

        // Find and disable the gist button to prevent duplicate clicks
        const gistBtn = document.querySelector( `[data-session-id="${sessionId}"] .sender-gist-btn` );
        if ( gistBtn ) {
            gistBtn.disabled = true;
            gistBtn.classList.add( 'working' );
            gistBtn.innerHTML = '⏳';
        }

        this.log( `Generating gist for session ${sessionId} from ${messages.length} messages and ${abstracts.length} abstracts...` );

        try {
            // Call backend API to generate gist (include abstracts for richer semantic signal)
            const response = await fetch( '/api/notifications/generate-gist', {
                method  : 'POST',
                headers : { ...this.getAuthHeaders(), 'Content-Type': 'application/json' },
                body    : JSON.stringify( { messages, abstracts } )
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

        // Save server-provided session_name if present (takes priority over auto-generated)
        if ( notification.session_name ) {
            const parsed = this.parseSenderId( senderId );
            if ( parsed.sessionId ) {
                this.saveSessionName( parsed.sessionId, notification.session_name, { fromServer: true } );
            }
        }

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
     * Extract date string from ISO timestamp, resolved to appTimezone.
     * Converts any ISO timestamp (UTC "Z" or offset-bearing) to the server's
     * configured timezone before extracting the date portion.
     * Falls back to local date if timestamp is missing or invalid.
     * @param {string|null} isoTimestamp - ISO 8601 timestamp (e.g., "2026-03-03T03:36:00.000Z")
     * @returns {string} ISO date string (YYYY-MM-DD) in appTimezone
     */
    extractDateFromTimestamp( isoTimestamp ) {
        if ( isoTimestamp && typeof isoTimestamp === 'string' && isoTimestamp.includes( 'T' ) ) {
            const parsed = new Date( isoTimestamp );
            if ( !isNaN( parsed.getTime() ) ) {
                return parsed.toLocaleDateString( 'en-CA', {
                    timeZone : this.appTimezone,
                    year     : 'numeric',
                    month    : '2-digit',
                    day      : '2-digit'
                } );
            }
        }
        // Fallback: use appTimezone-aware local date
        return this.getLocalDateDisplay();
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

        if ( !container || !card ) return;

        // Pinned-card invariant: never insert a non-pinned card above a pinned
        // conversation-mode card. If a pinned card exists AND we're moving a
        // DIFFERENT card, place it as the second child (immediately after the
        // pinned card) instead of clobbering position 0.
        const pinned = container.querySelector( '.sender-card[data-pinned-conv-mode="true"]' );
        if ( pinned && pinned !== card ) {
            const target = pinned.nextSibling;
            if ( target !== card ) {
                container.insertBefore( card, target );
                this.log( `Moved ${senderId} card to position 1 (after pinned conversation card)` );
            }
            return;
        }

        if ( container.firstChild !== card ) {
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
        const conversationModeActive = sessionId ? !!this.conversationModes[ sessionId ] : false;
        const conversationModeIcon   = conversationModeActive ? '📞' : '🔔';
        const conversationModeTitle  = conversationModeActive
            ? 'Conversation mode ON — every Claude response is spoken (click to switch to notification mode)'
            : 'Notification mode (default) — only explicit notify() calls speak (click to switch to conversation mode)';
        const sessionDisplay = sessionId
            ? `<span class="sender-session-id"
                     onclick="event.stopPropagation();">#${sessionId}</span><span class="sender-session-copy copy-btn"
                     onclick="event.stopPropagation(); window.notificationsUI.copySenderSessionId( this )"
                     title="Copy session ID">📋</span>
               <button class="sender-gist-btn"
                       onclick="event.stopPropagation(); window.notificationsUI.generateSessionGist('${escapedSenderId}')"
                       title="Generate smart gist from conversation">✨</button>
               <span class="sender-session-name"
                     onclick="event.stopPropagation(); window.notificationsUI.editSessionName('${sessionId}')"
                     title="Click to rename">${sessionName || ''}</span>`
            : '';

        // Active indicator: filled circle for most recent sender, hollow for others
        const activeIndicator = group?.isActive ? '●' : '○';
        const activeClass = group?.isActive ? ' sender-card-active' : '';
        const activeTitle = group?.isActive ? 'Active session' : 'Inactive session';

        // Voice persona badge: when this session has a per-session voice
        // assigned, render a colored chip in the header so the user can
        // visually identify which session is which (audio + visual cues).
        // Returns '' when no persona is known — typically because the
        // session predates the feature, the SessionStart hook's /allocate
        // call failed (server falls back to Sam, the system default voice),
        // or senderPersonaMap hasn't been hydrated yet for this sender.
        // Live arrivals patch the DOM in place via _setPersonaBadgeOnCard.
        const persona = this.getPersonaForSender( senderId );
        const personaBadge = this._renderPersonaBadgeHTML( persona );

        const card = document.createElement( 'div' );
        // Card ID must escape # character in addition to @ and .
        card.id = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        card.className = `sender-card${activeClass}`;
        card.setAttribute( 'data-project', parsed.project );
        card.setAttribute( 'data-session-id', sessionId || '' );
        card.setAttribute( 'data-sender-id', senderId );  // for focus-mode walker lookup

        // Foundation: set --persona-color + --persona-color-rgb on the card
        // root so Tier 1 (border + shadow) and Tier 2 (header gradient) CSS
        // rules can apply persona color via var() — without these vars set,
        // the rules fall back to their pre-theming defaults (grey/green).
        // See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/02-theming-round1-design.md §2.1
        if ( persona && persona.color ) {
            card.style.setProperty( "--persona-color", persona.color );
            const rgb = this._hexToRgb( persona.color );
            if ( rgb ) card.style.setProperty( "--persona-color-rgb", rgb );
        }
        // Build CC voice input row (only for claude.code sessions with a session ID)
        const isCCSession  = parsed.agentType === 'claude.code' && sessionId;
        const ccVoiceInput = isCCSession ? `
            <div class="cc-voice-input" data-session-hash="${sessionId}" data-sender-id="${senderId}">
                <div class="cc-voice-input-row">
                    <button type="button" class="sender-conversation-mode-btn${conversationModeActive ? ' is-active' : ''}"
                            data-session-id="${sessionId}"
                            onclick="event.stopPropagation(); window.notificationsUI.toggleConversationMode('${sessionId}')"
                            title="${conversationModeTitle}">${conversationModeIcon}</button>
                    <button type="button" class="stt-button cc-session-stt"
                            id="cc-session-stt-${sessionId}"
                            title="Click to record (30s max, ESC to cancel)">🎤</button>
                    <input type="text" class="cc-session-msg-input"
                           id="cc-session-input-${sessionId}"
                           placeholder="Send voice/text to CC session..." />
                    <button type="button" class="response-submit-button cc-session-send"
                            id="cc-session-send-${sessionId}">Send</button>
                </div>
            </div>
        ` : '';

        card.innerHTML = `
            <div class="sender-card-header" onclick="window.notificationsUI.toggleSenderCard('${escapedSenderId}')">
                <span class="sender-active-indicator" title="${activeTitle}">${activeIndicator}</span>
                <span class="sender-status">${statusIndicator}</span>
                <span class="sender-project-name">${projectName}</span>
                ${sessionDisplay}
                <span class="sender-stats-group">
                    ${personaBadge}
                    <span class="sender-new-count"></span>
                    <span class="sender-message-count">(0)</span>
                    <span class="sender-last-activity">Last: --</span>
                </span>
                <button class="sender-delete-btn" onclick="event.stopPropagation(); window.notificationsUI.deleteSenderConversation('${escapedSenderId}')" title="Delete all">×</button>
                <span class="sender-toggle">▼</span>
            </div>
            ${ccVoiceInput}
            <div class="sender-card-dates" id="sender-dates-${senderId.replace( /[@.#]/g, '-' )}">
                <!-- Date accordions will be added here -->
            </div>
        `;

        // If THIS card belongs to the active conversation-mode session, mark it
        // pinned at insert time so the soft-glow CSS rule kicks in immediately
        // and the sort-respecting insertion logic keeps it at the top. This
        // covers the initial-page-load case where conversationModes is hydrated
        // from localStorage and the session might already be active.
        const shouldPin = sessionId && !!this.conversationModes[ sessionId ];
        if ( shouldPin ) {
            card.setAttribute( 'data-pinned-conv-mode', 'true' );
        }

        // Insert at top for runtime updates, append for initial load (preserves API sort order).
        // Pinning invariant: a pinned card always lives at index 0; non-pinned
        // cards inserted at "top" go to index 1 when a pinned card exists.
        if ( insertAtTop ) {
            const pinned = container.querySelector( '.sender-card[data-pinned-conv-mode="true"]' );
            if ( pinned && pinned !== card ) {
                container.insertBefore( card, pinned.nextSibling );
            } else {
                container.insertBefore( card, container.firstChild );
            }
        } else {
            container.appendChild( card );
        }

        // CC focus mode + selector strip hooks (Design: src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md):
        // 1. If focus mode is on and this isn't the focused session, hide the card.
        // 2. If this is a CC session, register an icon in the strip.
        // 3. If focus is on and this isn't focused, bump the unread badge so the
        //    user gets peripheral awareness that a new session just appeared.
        this._applyFocusHiddenToCard( card, senderId );
        if ( isCCSession ) {
            this._addStripIcon( senderId, projectName, persona, sessionId );
            if ( this.ccFocusState.enabled
                 && this.ccFocusState.focused_sender_id !== senderId ) {
                const icon = document.getElementById( this._stripIconIdFor( senderId ) );
                if ( icon ) {
                    this.ccStripUnreadCounts[ senderId ] = 1;
                    icon.setAttribute( "data-unread", "true" );
                    icon.setAttribute( "data-unread-count", "1" );
                }
            }
        }

        this.log( `Created sender card for ${projectName}${sessionId ? '#' + sessionId : ''} (${senderId})${shouldPin ? ' [PINNED conversation mode]' : ''}` );
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
                <button class="date-delete-btn" onclick="event.stopPropagation(); window.notificationsUI.softDeleteByDate('${escapedSenderId}', '${dateString}')" title="Delete this day">×</button>
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

        // Delegated click handler for progress group toggles within this date accordion
        const messagesContainer = accordion.querySelector( '.date-accordion-messages' );
        if ( messagesContainer ) {
            messagesContainer.addEventListener( 'click', ( e ) => {
                const toggle = e.target.closest( '.progress-group-toggle' );
                if ( !toggle ) return;
                const entry = toggle.closest( '.progress-group-entry' );
                if ( !entry ) return;
                const history = entry.querySelector( '.progress-group-history' );
                if ( !history ) return;
                const isExpanded = history.style.display !== 'none';
                history.style.display = isExpanded ? 'none' : 'block';
                const count = entry.getAttribute( 'data-progress-group-count' );
                toggle.innerHTML = ( isExpanded ? '&#9660;' : '&#9650;' ) + ` #${count}`;
            } );
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

        // Progress group: update existing message in-place if one exists
        const groupId = notification.progress_group_id;
        if ( groupId && !isResponse ) {
            const existing = container.querySelector( `[data-progress-group="${groupId}"]` );
            if ( existing ) {
                this.updateSenderProgressGroupEntry( existing, notification );
                return;
            }
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

        // Build CSS class - add expired-response if notification was expired
        const isExpired = notification.was_expired === true;
        let cssClass = `sender-message ${isResponse ? 'outgoing' : 'incoming'}`;
        if ( isExpired ) {
            cssClass += ' expired-response';
        }

        // Add expired badge if applicable
        const expiredBadge = isExpired ? '<span class="expired-badge">EXPIRED</span>' : '';

        // Build abstract indicator if present and non-empty (for incoming messages only)
        const hasAbstract = !isResponse && notification.abstract && notification.abstract.trim().length > 0;
        const abstractIndicator = hasAbstract
            ? `<span class="abstract-indicator" data-abstract="${encodeURIComponent( notification.abstract )}" title="View details">📋</span>`
            : '';

        const messageDiv = document.createElement( 'div' );
        messageDiv.className = cssClass;
        messageDiv.id = notification.id || notification.id_hash || '';  // Set ID for TTS indicator

        // Tag with progress group ID if present (first occurrence in sender card)
        if ( groupId && !isResponse ) {
            messageDiv.setAttribute( 'data-progress-group', groupId );
            messageDiv.classList.add( 'progress-group-entry' );
            messageDiv.setAttribute( 'data-progress-group-count', '1' );

            // Wrap content in progress-group-head div for accordion structure
            messageDiv.innerHTML = `
                <div class="progress-group-head">
                    <span class="message-time">${timeStr}</span>
                    <span class="message-text" title="${cleanMessage.replace( /"/g, '&quot;' )}">${this.renderMarkdownInline( cleanMessage )}${expiredBadge}${abstractIndicator}</span>
                </div>
            `;

            // Add proxy ratification link for proxy progress groups
            const proxyLink = this.createProxyRatifyLink( groupId );
            if ( proxyLink ) {
                messageDiv.querySelector( '.progress-group-head' ).appendChild( proxyLink );
            }
        } else {
            messageDiv.innerHTML = `
                <span class="message-time">${timeStr}</span>
                <span class="message-text" title="${cleanMessage.replace( /"/g, '&quot;' )}">${this.renderMarkdownInline( cleanMessage )}${expiredBadge}${abstractIndicator}</span>
            `;
        }

        // Corner pause button — appears in upper-right of the message bubble while
        // its TTS is playing (gated by .tts-playing on the messageDiv, which is
        // already toggled by start/stopTTSPlayingIndicator across the audio
        // lifecycle). Click flips between pause and resume; the data-paused
        // attribute carries the toggle state.
        const cornerBtnId = notification.id || notification.id_hash || '';
        if ( cornerBtnId && !isResponse ) {
            const cornerBtn = document.createElement( 'button' );
            cornerBtn.type      = 'button';
            cornerBtn.className = 'notification-corner-pause-btn';
            cornerBtn.dataset.notificationId = cornerBtnId;
            cornerBtn.dataset.paused         = 'false';
            cornerBtn.title       = 'Pause this notification\'s playback';
            cornerBtn.textContent = '⏸';
            cornerBtn.setAttribute( 'aria-label', 'Pause notification audio' );
            cornerBtn.addEventListener( 'click', ( e ) => {
                e.stopPropagation();
                const nid = cornerBtn.dataset.notificationId;
                this.log( `[CORNER-PAUSE] click — nid=${nid}, isTTSPaused=${this.isTTSPaused}, activeTTSItem=${!!this.activeTTSItem}` );

                // Route through the canonical pauseTTS()/resumeTTS() helpers —
                // those handle BOTH playback modes (Web Audio API for instant
                // mode, HTML Audio for reliable mode). The earlier attempt at
                // calling this.currentAudio.pause() failed because instant mode
                // produces audio via AudioContext + AudioBufferSource and the
                // HTML5 Audio handle is a stale reference there. The global
                // pause button uses these same helpers — corner button now
                // mirrors that behavior so they stay in sync.
                if ( this.isTTSPaused ) {
                    this.resumeTTS();
                } else {
                    this.pauseTTS();
                }

                // Optimistic local UI update — the source of truth is
                // this.isTTSPaused, which the helpers above just flipped.
                if ( this.isTTSPaused ) {
                    cornerBtn.dataset.paused = 'true';
                    cornerBtn.textContent    = '▶';
                    cornerBtn.title          = 'Resume this notification\'s playback';
                    cornerBtn.setAttribute( 'aria-label', 'Resume notification audio' );
                    messageDiv.classList.add( 'is-paused-current' );
                } else {
                    cornerBtn.dataset.paused = 'false';
                    cornerBtn.textContent    = '⏸';
                    cornerBtn.title          = 'Pause this notification\'s playback';
                    cornerBtn.setAttribute( 'aria-label', 'Pause notification audio' );
                    messageDiv.classList.remove( 'is-paused-current' );
                }
            } );
            messageDiv.appendChild( cornerBtn );
        }

        // Add to top (newest first)
        container.insertBefore( messageDiv, container.firstChild );

        // Update date accordion count
        this.updateDateAccordionCount( senderId, dateString );
    }

    updateSenderProgressGroupEntry( element, notification ) {
        /**
         * Update an existing progress group entry with history accumulation (sender card path).
         *
         * Requires:
         *     - element is a DOM element with data-progress-group attribute
         *     - notification has message, timestamp/time_display
         *
         * Ensures:
         *     - Moves current head message into history container (newest first)
         *     - Sets new message + timestamp as head
         *     - Increments counter, updates toggle text
         *     - Preserves expanded/collapsed toggle state
         *     - Triggers CSS pulse animation on head
         */
        const head = element.querySelector( '.progress-group-head' );
        if ( !head ) return;

        // Read current head values before overwriting
        const oldTimeSpan = head.querySelector( '.message-time' );
        const oldMessageSpan = head.querySelector( '.message-text' );
        const oldTime = oldTimeSpan ? oldTimeSpan.textContent : '';
        const oldMessage = oldMessageSpan ? oldMessageSpan.textContent : '';

        // Create history entry from old head values
        const historyEntry = document.createElement( 'div' );
        historyEntry.className = 'progress-history-entry';
        historyEntry.innerHTML = `
            <span class="activity-timestamp">${this.escapeHtml( oldTime )}</span>
            <span class="activity-message">${this.escapeHtml( oldMessage )}</span>
        `;

        // Get or create history container
        let history = element.querySelector( '.progress-group-history' );
        if ( !history ) {
            history = document.createElement( 'div' );
            history.className = 'progress-group-history';
            history.style.display = 'none';
            element.appendChild( history );
        }

        // Prepend old head to history (newest first)
        history.insertBefore( historyEntry, history.firstChild );

        // Clean new message
        let cleanMessage = notification.message || '';
        cleanMessage = cleanMessage.replace( /^\[[A-Z]+\]\s*/, '' );

        // Update head with new notification values
        if ( oldMessageSpan ) {
            oldMessageSpan.innerHTML = this.renderMarkdownInline( cleanMessage );
            oldMessageSpan.title = cleanMessage.replace( /"/g, '&quot;' );
        }
        if ( oldTimeSpan ) {
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
            oldTimeSpan.textContent = timeStr;
        }

        // Increment counter
        let count = parseInt( element.getAttribute( 'data-progress-group-count' ) || '1', 10 ) + 1;
        element.setAttribute( 'data-progress-group-count', String( count ) );

        // Find or create toggle (replaces old counter badge)
        let toggle = element.querySelector( '.progress-group-toggle' );
        if ( !toggle ) {
            toggle = document.createElement( 'span' );
            toggle.className = 'progress-group-toggle';
            toggle.title = 'Show history';
            head.appendChild( toggle );
        }

        // Update toggle text — preserve expanded/collapsed state
        const isExpanded = history.style.display !== 'none';
        const chevron = isExpanded ? '&#9650;' : '&#9660;';
        toggle.innerHTML = `${chevron} #${count}`;

        // Trigger CSS pulse animation on head
        head.classList.remove( 'progress-group-updated' );
        void head.offsetWidth;
        head.classList.add( 'progress-group-updated' );
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
                `/api/notifications/date/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUserEmail )}/${dateString}`,
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
        // Strip icon must follow the card. If this was the focused
        // session, _removeStripIcon auto-exits focus mode.
        this._removeStripIcon( senderId );
        this.senderGroups.delete( senderId );
        this.updateTotalNotificationsCount();
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

        const messageDiv = document.createElement( 'div' );
        messageDiv.className = `sender-message ${isResponse ? 'outgoing' : 'incoming'}`;
        messageDiv.innerHTML = `
            <span class="message-time">${time}${isResponse ? ' →' : ''}</span>
            <span class="message-text" title="${displayMessage}">${this.renderMarkdownInline( displayMessage )}</span>
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
        if ( !this.currentUserEmail ) {
            this.log( 'Cannot load history: no user email' );
            return;
        }

        this.log( `Loading conversation history (window: ${this.historyWindowHours}h)...` );

        try {
            // Get list of senders with visible (non-hidden) notifications
            const sendersUrl = `/api/notifications/senders-visible/${encodeURIComponent( this.currentUserEmail )}`;
            const queryParams = new URLSearchParams();
            const effectiveHours = this.getEffectiveHoursForQuery();
            if ( effectiveHours !== null ) {
                queryParams.append( 'hours', effectiveHours );
            }
            if ( this.isAdmin && this.queueFilterMode === 'others' ) {
                queryParams.append( 'exclude_own_jobs', 'true' );
            }
            const params = queryParams.toString() ? `?${queryParams.toString()}` : '';

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

            // Layer B: pre-populate senderPersonaMap from the senders-visible
            // response BEFORE createSenderCard runs. The server stamps voice_persona
            // per sender via _voice_persona_for_sender_id; without this hydration
            // step, a force-refreshed page would render every card without a badge
            // until the first live notification arrives.
            // See: src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md §10
            for ( const senderInfo of senders ) {
                if ( senderInfo.sender_id && senderInfo.voice_persona ) {
                    this.senderPersonaMap.set( senderInfo.sender_id, senderInfo.voice_persona );
                }
            }

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
            const baseUrl = `/api/notifications/conversation-by-date/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUserEmail )}`;
            const params = new URLSearchParams();

            const effectiveHours = this.getEffectiveHoursForQuery();
            if ( effectiveHours !== null ) {
                params.append( 'hours', effectiveHours );
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
     * Resolve the active history window to a numeric hours value for backend queries.
     * The 'today' sentinel is computed dynamically from the user's local midnight,
     * so a notification from 12:01 AM today is included regardless of when the
     * user picked "Today" — distinct from a fixed 24-hour rolling window.
     *
     * @returns {number|null} Numeric hours for the `hours` query param, or null
     *   if no filter should be applied (sentinel maps to "All time").
     */
    getEffectiveHoursForQuery() {
        if ( this.historyWindowHours === null ) return null;
        if ( this.historyWindowHours === 'today' ) {
            const now      = new Date();
            const midnight = new Date( now.getFullYear(), now.getMonth(), now.getDate() );
            return Math.max( 1, Math.ceil( ( now - midnight ) / 3600000 ) );
        }
        return this.historyWindowHours;
    }

    /**
     * Set the history window and reload conversations.
     * @param {number|string|null} hours - Hours to look back, 'today' for since-midnight, or null for all time
     */
    async setHistoryWindow( hours ) {
        // Close dropdown menu first
        const menu = document.getElementById( 'history-dropdown-menu' );
        if ( menu ) {
            menu.classList.remove( 'show' );
        }

        // Skip reload if value hasn't changed - no point re-running the same query
        if ( hours === this.historyWindowHours ) {
            this.log( `History window unchanged (${hours}h), skipping reload` );
            return;
        }

        const storageValue = hours === null ? 'all' : hours.toString();
        this.historyWindowHours = hours;
        localStorage.setItem( this.HISTORY_WINDOW_KEY, storageValue );

        const logLabel = hours === null
            ? 'all time'
            : ( hours === 'today' ? `today (since local midnight, ~${this.getEffectiveHoursForQuery()}h)` : `${hours} hours` );
        this.log( `History window set to: ${logLabel}` );

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

        // Strip icons mirror sender cards — wipe them too so a history-
        // window change doesn't leave stranded icons in the focus tray.
        this._clearAllStripIcons();

        this.updateTotalNotificationsCount();
    }

    /**
     * Update the history window dropdown display.
     * @param {number|null} hours - Current window in hours
     */
    updateHistoryWindowDisplay( hours ) {
        const dropdown = document.getElementById( 'history-window-dropdown' );
        if ( !dropdown ) {
            return;
        }

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
            <button class="dropdown-display" onclick="event.stopPropagation(); window.notificationsUI.toggleHistoryDropdown()">
                ${currentOption.label}
                <span class="dropdown-arrow">▼</span>
            </button>
            <div class="dropdown-menu" id="history-dropdown-menu">
                ${this.WINDOW_OPTIONS.map( opt => `
                    <div class="dropdown-item ${opt.hours === this.historyWindowHours ? 'selected' : ''}"
                         onclick="event.stopPropagation(); window.notificationsUI.setHistoryWindow(${JSON.stringify( opt.hours ).replace( /"/g, '&quot;' )})">
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
        // position:relative anchors the absolutely-positioned corner pause button.
        listItem.style.position = "relative";
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
            <button type="button" class="notification-corner-pause-btn"
                    data-notification-id="${notificationId}"
                    title="Pause this notification's playback"
                    aria-label="Pause notification audio">⏸</button>
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
        const cornerPauseButton = listItem.querySelector( '.notification-corner-pause-btn' );
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
        if ( cornerPauseButton ) {
            // Corner pause button toggles between pause and resume based on the
            // listItem's current paused-state class. CSS gates visibility to
            // li.is-playing-current so the button only appears while audio is
            // loaded; we just dispatch the right action here.
            cornerPauseButton.addEventListener( 'click', ( e ) => {
                e.stopPropagation();
                const action = listItem.classList.contains( 'is-paused-current' )
                    ? 'resume'
                    : 'pause';
                this.handleAudioControl( action, notificationId );
            } );
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

        // Mirror the same state machine onto the absolutely-positioned corner
        // pause button on the parent <li>. CSS gates visibility to
        // li.is-playing-current; the icon flips between ⏸ (playing) and ▶
        // (paused) so the user can resume in place from a distance.
        const listItem      = panel.closest( 'li' );
        const cornerPauseBtn = listItem?.querySelector( '.notification-corner-pause-btn' );

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
                // Corner pause button: hide and reset to ⏸ for next playback
                if ( listItem ) {
                    listItem.classList.remove( 'is-playing-current', 'is-paused-current' );
                }
                if ( cornerPauseBtn ) {
                    cornerPauseBtn.textContent = '⏸';
                    cornerPauseBtn.title       = 'Pause this notification\'s playback';
                    cornerPauseBtn.setAttribute( 'aria-label', 'Pause notification audio' );
                }
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
                // Corner pause button: visible (playing), shows ⏸
                if ( listItem ) {
                    listItem.classList.add( 'is-playing-current' );
                    listItem.classList.remove( 'is-paused-current' );
                }
                if ( cornerPauseBtn ) {
                    cornerPauseBtn.textContent = '⏸';
                    cornerPauseBtn.title       = 'Pause this notification\'s playback';
                    cornerPauseBtn.setAttribute( 'aria-label', 'Pause notification audio' );
                }
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
                // Corner pause button: visible (paused), shows ▶
                if ( listItem ) {
                    listItem.classList.add( 'is-playing-current', 'is-paused-current' );
                }
                if ( cornerPauseBtn ) {
                    cornerPauseBtn.textContent = '▶';
                    cornerPauseBtn.title       = 'Resume this notification\'s playback';
                    cornerPauseBtn.setAttribute( 'aria-label', 'Resume notification audio' );
                }
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

            // Fire-and-forget: tell the server this notification was played so unread-count
            // tracking stays consistent across clients (mobile + other web sessions).
            // Playback already succeeded locally; a failed POST is a consistency concern
            // we log-only, not a user-visible error.
            fetch( `/api/notifications/${notificationId}/played?api_key=${this.notificationState.apiKey}`, {
                method: "POST"
            } ).catch( err => this.log( `mark-played POST failed (non-fatal): ${err.message}` ) );

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
         *     - User authenticated (this.currentUserEmail set)
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

        const count = group.totalCount;

        // Confirm before clearing (destructive action)
        if ( !confirm( `Delete all ${count} message${count !== 1 ? 's' : ''} from ${projectName}? This cannot be undone.` ) ) {
            this.log( "Delete conversation cancelled by user" );
            return;
        }

        this.log( `Deleting conversation with ${projectName} (${count} messages)...` );

        try {
            const response = await fetch(
                `/api/notifications/conversation/${encodeURIComponent( senderId )}/${encodeURIComponent( this.currentUserEmail )}`,
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

        // Remove the corresponding strip icon. If this session was the
        // focused one, _removeStripIcon auto-exits focus mode.
        this._removeStripIcon( senderId );

        // Remove from local state
        this.senderGroups.delete( senderId );

        // Update total count
        this.updateTotalNotificationsCount();

        this.log( `✓ Deleted conversation with ${projectName}` );
    }

    async clearAllNotifications() {
        /**
         * Clear all notifications from the UI and server using bulk delete.
         *
         * Purpose:
         *     - Bulk delete all notifications with user confirmation
         *     - Respects current history window filter setting
         *     - Uses single API call for efficient server-side deletion
         *
         * Behavior:
         *     1. Count notifications from senderGroups (actual data, not DOM)
         *     2. Build filter description for confirmation dialog
         *     3. If confirmed: Call bulk delete endpoint with current filter
         *     4. Clear local state and update UI
         *
         * Ensures:
         *     - User confirmation before destructive action
         *     - All notifications matching filter permanently deleted on server
         *     - UI updated properly (counter reset to 0, list cleared)
         *     - Local cache cleared
         */

        // 1. Count notifications from senderGroups (actual data, not DOM)
        let totalCount = 0;
        for ( const group of this.senderGroups.values() ) {
            totalCount += group.totalCount;
        }

        if ( totalCount === 0 ) {
            this.log( "No notifications to clear" );
            return;
        }

        // 2. Build filter description for confirmation
        const filterLabel = this.getFilterLabel();

        // 3. Confirm with user
        if ( !confirm( `Clear all ${totalCount} notification${totalCount !== 1 ? 's' : ''} (${filterLabel})? This cannot be undone.` ) ) {
            this.log( "Clear all notifications cancelled by user" );
            return;
        }

        this.log( `Clearing ${totalCount} notifications (${filterLabel})...` );

        // 4. Call bulk delete endpoint with current filter
        try {
            const params = new URLSearchParams();
            const effectiveHours = this.getEffectiveHoursForQuery();
            if ( effectiveHours !== null ) {
                params.append( 'hours', effectiveHours );
            }
            if ( this.isAdmin && this.queueFilterMode === 'others' ) {
                params.append( 'exclude_own_jobs', 'true' );
            }

            const url = `/api/notifications/bulk/${encodeURIComponent( this.currentUserEmail )}?${params}`;
            const response = await fetch( url, {
                method: 'DELETE'
            });

            if ( !response.ok ) {
                const errorData = await response.json().catch( () => ({ detail: 'Unknown error' }) );
                throw new Error( errorData.detail || `Server returned ${response.status}` );
            }

            const result = await response.json();
            this.log( `Server deleted ${result.deleted_count} notifications` );

        } catch ( error ) {
            this.error( "Failed to delete notifications:", error );
            alert( "Failed to clear notifications. Please try again." );
            return;
        }

        // 5. Clear local state
        this.senderGroups.clear();
        this.notificationState.notifications = [];

        // 6. Clear UI - remove all sender cards
        const notificationsList = document.getElementById( "notifications-list" );
        if ( notificationsList ) {
            notificationsList.innerHTML = '';
        }

        // 6a. Wipe the focus-tray strip icons too — they mirror cards.
        this._clearAllStripIcons();

        // 7. Update counter to zero
        const counter = document.getElementById( "notifications-count" );
        if ( counter ) {
            counter.textContent = '0';
        }

        // 8. Disable clear button
        this.updateClearButtonState( 0 );

        this.log( `✓ Cleared ${totalCount} notification${totalCount !== 1 ? 's' : ''}` );
    }

    getFilterLabel() {
        /**
         * Get human-readable label for current history window filter.
         *
         * Returns:
         *     String like "Last week", "All time", etc.
         */
        if ( this.historyWindowHours === null ) {
            return 'All time';
        }
        const option = this.WINDOW_OPTIONS.find( o => o.hours === this.historyWindowHours );
        return option ? option.label : `Last ${this.historyWindowHours} hours`;
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
        
        // NOTE: loadInitialNotifications() removed - loadConversationHistory() now handles this
        // during init(). Calling it here caused a race condition where auth_success would
        // clear notifications that were already loaded by loadConversationHistory().
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

    wsDiag( message, ...args ) {
        console.log( `[WS-DIAG] ${message}`, ...args );
        this.addDebugMessage( `WS-DIAG: ${message}` );
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

    /**
     * Render markdown text to sanitized HTML.
     * Uses marked.js for parsing and DOMPurify for XSS protection.
     *
     * Requires:
     *     - marked.js loaded globally (window.marked)
     *     - DOMPurify loaded globally (window.DOMPurify)
     *     - text is a string (can be empty/null)
     *
     * Ensures:
     *     - Returns sanitized HTML string safe for innerHTML
     *     - Returns empty string if text is null/undefined/empty
     *     - Common markdown elements rendered: bold, italic, lists, links, code
     *     - All potentially dangerous HTML/JS removed by DOMPurify
     *
     * @param {string} text - Raw markdown text to render
     * @returns {string} - Sanitized HTML string
     */
    renderMarkdown( text ) {
        if ( !text ) return '';

        // Normalize escaped newlines to actual newlines
        // Handles literal \n from MCP/JSON transport
        text = text.replace( /\\n/g, '\n' );

        // Check if libraries are available
        if ( typeof marked === 'undefined' ) {
            this.error( 'marked.js not loaded - falling back to plain text with HTML escaping' );
            return this.escapeHtml( text );
        }
        if ( typeof DOMPurify === 'undefined' ) {
            this.error( 'DOMPurify not loaded - falling back to plain text with HTML escaping' );
            return this.escapeHtml( text );
        }

        try {
            // Configure marked for safe rendering
            marked.setOptions( {
                gfm: true,           // GitHub Flavored Markdown
                breaks: true,        // Convert \n to <br>
                headerIds: false,    // Disable header IDs (not needed, reduces attack surface)
                mangle: false        // Don't mangle email addresses
            } );

            // Parse markdown to HTML
            const rawHtml = marked.parse( text );

            // Sanitize with DOMPurify - allow safe subset of HTML
            const sanitizedHtml = DOMPurify.sanitize( rawHtml, {
                ALLOWED_TAGS: [
                    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'del',
                    'ul', 'ol', 'li',
                    'a', 'code', 'pre',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                    'blockquote', 'hr',
                    'table', 'thead', 'tbody', 'tr', 'th', 'td'
                ],
                ALLOWED_ATTR: [
                    'href', 'target', 'rel', 'title'
                ],
                // Force all links to open in new tab safely
                ADD_ATTR: [ 'target', 'rel' ],
                FORBID_TAGS: [ 'script', 'style', 'iframe', 'form', 'input', 'img' ],
                FORBID_ATTR: [ 'onerror', 'onclick', 'onload', 'onmouseover' ]
            } );

            // Post-process: add target="_blank" and rel="noopener" to all links
            const tempDiv = document.createElement( 'div' );
            tempDiv.innerHTML = sanitizedHtml;
            tempDiv.querySelectorAll( 'a' ).forEach( link => {
                link.setAttribute( 'target', '_blank' );
                link.setAttribute( 'rel', 'noopener noreferrer' );
            } );

            return tempDiv.innerHTML;
        } catch ( error ) {
            this.error( `Markdown rendering failed: ${error.message}` );
            return this.escapeHtml( text );
        }
    }

    /**
     * Render markdown text to sanitized inline HTML (no block elements).
     * Uses marked.parseInline() to avoid wrapping output in <p> tags,
     * making it safe for use inside <span> elements (chat bubbles).
     *
     * Requires:
     *     - marked.js loaded globally (window.marked)
     *     - DOMPurify loaded globally (window.DOMPurify)
     *     - text is a string (can be empty/null)
     *
     * Ensures:
     *     - Returns sanitized inline HTML string safe for innerHTML inside <span>
     *     - Returns empty string if text is null/undefined/empty
     *     - Only inline elements rendered: bold, italic, code, links, strikethrough
     *     - All block elements and dangerous HTML/JS removed
     *
     * @param {string} text - Raw markdown text to render
     * @returns {string} - Sanitized inline HTML string
     */
    renderMarkdownInline( text ) {
        if ( !text ) return '';

        // Normalize escaped newlines to actual newlines
        text = text.replace( /\\n/g, '\n' );

        // Check if libraries are available
        if ( typeof marked === 'undefined' || typeof DOMPurify === 'undefined' ) {
            return this.escapeHtml( text );
        }

        try {
            marked.setOptions( {
                gfm    : true,
                breaks : true
            } );

            // parseInline() produces NO wrapping <p> tags
            const rawHtml = marked.parseInline( text );

            const sanitizedHtml = DOMPurify.sanitize( rawHtml, {
                ALLOWED_TAGS : [ 'strong', 'b', 'em', 'i', 'u', 's', 'del', 'a', 'code', 'br' ],
                ALLOWED_ATTR : [ 'href', 'target', 'rel', 'title' ],
                ADD_ATTR     : [ 'target', 'rel' ],
                FORBID_TAGS  : [ 'script', 'style', 'iframe', 'form', 'input', 'img', 'p', 'div' ],
                FORBID_ATTR  : [ 'onerror', 'onclick', 'onload', 'onmouseover' ]
            } );

            // Post-process: add target="_blank" and rel="noopener" to all links
            const tempDiv = document.createElement( 'div' );
            tempDiv.innerHTML = sanitizedHtml;
            tempDiv.querySelectorAll( 'a' ).forEach( link => {
                link.setAttribute( 'target', '_blank' );
                link.setAttribute( 'rel', 'noopener noreferrer' );
            } );

            return tempDiv.innerHTML;
        } catch ( error ) {
            this.error( `Inline markdown rendering failed: ${error.message}` );
            return this.escapeHtml( text );
        }
    }

    /**
     * Escape HTML special characters for safe display as plain text.
     * Fallback when markdown libraries aren't available.
     *
     * @param {string} text - Raw text to escape
     * @returns {string} - HTML-escaped text
     */
    escapeHtml( text ) {
        if ( !text ) return '';
        const escapeMap = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace( /[&<>"']/g, char => escapeMap[ char ] );
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
                    collectedAnswers     : state.collectedAnswers || {},
                    // Pause state fields
                    isPaused             : state.isPaused || false,
                    pausedAt             : state.pausedAt,
                    totalPausedDuration  : state.totalPausedDuration || 0,
                    serverExpiryEstimate : state.serverExpiryEstimate
                } );
            }

            // Save both notifications and queue state
            const queueState = {
                notifications : stateArray,
                queue         : this.actionRequiredQueue,
                activeId      : this.activeActionRequiredId,
                isPaused      : this.isPaused
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
                    collectedAnswers     : saved.collectedAnswers || {},
                    // Pause state fields
                    isPaused             : saved.isPaused || false,
                    pausedAt             : saved.pausedAt || null,
                    totalPausedDuration  : saved.totalPausedDuration || 0,
                    serverExpiryEstimate : saved.serverExpiryEstimate || null
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

                    // Handle pause state restoration
                    if ( activeState.isPaused ) {
                        // Restore paused state - don't start timer
                        this.isPaused = true;
                        this.updatePauseButtonUI( savedActiveId, true );
                        this.updatePausedTimerDisplay( savedActiveId, true );
                        this.showGracePeriodMessage( savedActiveId, true );
                        this.log( `Restored notification ${savedActiveId} in PAUSED state` );
                    } else {
                        // Start countdown timer with remaining time
                        this.startCountdownTimer( savedActiveId );
                        this.log( `Restored active notification: ${savedActiveId}` );
                    }
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

    /**
     * Ensure the action-required section is visible and expanded.
     * Called when a new action-required notification arrives to make it visible.
     *
     * Handles two separate visibility mechanisms:
     *     1. Section visibility (toolbar button) - removes 'section-hidden' class
     *     2. Section collapse (header click) - removes 'collapsed' class from content
     *
     * Ensures:
     *     - action-required-section has 'section-hidden' class removed if present
     *     - Toolbar button shows active state
     *     - action-required-content has 'collapsed' class removed if present
     *     - Toggle button shows expanded state (▼)
     */
    ensureActionRequiredExpanded() {
        const section = document.getElementById( 'action-required-section' );
        const content = document.getElementById( 'action-required-content' );
        const toggle = document.getElementById( 'action-required-toggle' );
        const toolbarBtn = document.querySelector( '.toolbar-btn[data-section="action-required-section"]' );

        // Handle toolbar visibility (section-hidden class on parent section)
        if ( section && section.classList.contains( 'section-hidden' ) ) {
            section.classList.remove( 'section-hidden' );
            if ( toolbarBtn ) {
                toolbarBtn.classList.add( 'active' );
            }
            this.saveSectionVisibility();
            this.log( 'Auto-showed action-required section (was hidden via toolbar)' );
        }

        // Handle header collapse (collapsed class on content div)
        if ( content && content.classList.contains( 'collapsed' ) ) {
            content.classList.remove( 'collapsed' );
            if ( toggle ) {
                toggle.textContent = '▼';
            }
            this.log( 'Auto-expanded action-required section (was collapsed via header)' );
        }
    }

    addActionRequiredNotification( notification ) {
        this.log( `Adding action-required notification: ${notification.id}` );

        // Store in action-required map with DEFERRED timer (expiresAt: null until activated)
        const state = {
            notification          : notification,
            expiresAt             : null,              // DEFERRED: set when activated, not on arrival
            activatedAt           : null,              // Timestamp when promoted to active
            timeoutSeconds        : notification.timeout_seconds,
            isExpired             : false,
            isResponded           : false,
            isActive              : false,             // True only for the active notification
            queuePosition         : null,              // Position in queue (1-indexed), null when active
            // Pause state fields
            isPaused              : false,             // True when paused
            pausedAt              : null,              // Timestamp when pause started
            totalPausedDuration   : 0,                 // Cumulative pause time in ms
            serverExpiryEstimate  : null               // Original server expiry (for grace period warning)
        };

        // Add multi-question state for multiple_choice notifications
        if ( notification.response_type === 'multiple_choice' ) {
            state.currentQuestionIndex = 0;
            state.collectedAnswers     = {};  // { header: value/[values] }
        }

        // Add empty answers state for open_ended_batch notifications
        if ( notification.response_type === 'open_ended_batch' ) {
            state.collectedAnswers = {};  // { header: value }
        }

        this.actionRequiredNotifications.set( notification.id, state );

        // Show the Action Required section
        const section = document.getElementById( 'action-required-section' );
        if ( section ) {
            section.style.display = 'block';
        }

        // Auto-expand the section content if collapsed
        this.ensureActionRequiredExpanded();

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
        state.serverExpiryEstimate = state.expiresAt;  // Track original expiry for grace period reference

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

        // Persona badge — right-aligned by sitting between the flex-grow message
        // and the timeout. Read voice_persona directly off the persisted envelope
        // so refresh-restored cards render correctly without map dependency.
        const personaBadge = this._renderPersonaBadgeHTML( notification.voice_persona );

        card.innerHTML = `
            <div class="minimized-position">#${queuePosition}</div>
            <div class="minimized-icon">${typeIcon}</div>
            <div class="minimized-message">${truncatedMessage}</div>
            ${personaBadge}
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
        // Don't activate if manually paused
        if ( this.isTTSPaused ) {
            this.log( 'TTS queue: Manually paused - not activating next' );
            return;
        }

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
        } else if ( item.type === 'job-card' ) {
            // Job card notification - already displayed in job card during Phase 6 routing
            // Just update tracking ID, don't add to project card (prevents duplication)
            this.log( `TTS queue: Playing job notification (already in job card): ${item.id}` );
            this.currentNotificationId = item.id;
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

        // Start TTS playback. Pull voice_id directly off the persisted notification
        // envelope first (server stamps voice_persona via _voice_persona_for_sender_id) —
        // strictly more reliable than the senderPersonaMap path because it doesn't
        // depend on the map being hydrated at activation time, which fails for
        // localStorage-restored action-required notifications and for any sender
        // that hasn't yet been hit by Layer B's senders-visible pre-hydration.
        // Falls back to map lookup, then to server-default (Sam).
        const ttsVoiceId = ( item.notification && item.notification.voice_persona && item.notification.voice_persona.voice_id )
            || this.getVoiceIdForSender( item.notification && item.notification.sender_id );
        this.playTTS( item.ttsText, this.getCurrentTTSMode(), ttsVoiceId ).catch( error => {
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

        // Timestamp span (matches .message-time styling used by conversation elements)
        const timeSpan = document.createElement( 'span' );
        timeSpan.className = 'message-time';
        if ( item.notification?.time_display ) {
            timeSpan.textContent = item.notification.time_display;
        } else {
            const ts = new Date( item.addedAt );
            timeSpan.textContent = ts.toLocaleTimeString( 'en-US', { hour: '2-digit', minute: '2-digit', hour12: false } );
        }

        const messageDiv = document.createElement( 'div' );
        messageDiv.className = 'tts-message';
        messageDiv.textContent = truncatedText;

        const stopBtn = document.createElement( 'button' );
        stopBtn.className = 'tts-stop-button';
        stopBtn.textContent = '⏹️ Stop';
        stopBtn.onclick = () => this.stopTTSAndAdvance();

        const deleteBtn       = document.createElement( 'button' );
        deleteBtn.className   = 'tts-delete-button';
        deleteBtn.textContent = '🗑';
        deleteBtn.title       = 'Remove from queue';
        deleteBtn.onclick     = ( e ) => {
            e.stopPropagation();
            this.removeFromTTSQueue( item.id );
        };

        card.appendChild( iconDiv );
        card.appendChild( timeSpan );
        card.appendChild( messageDiv );
        card.appendChild( stopBtn );
        card.appendChild( deleteBtn );

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

        // Timestamp span (matches .message-time styling used by conversation elements)
        const timeSpan = document.createElement( 'span' );
        timeSpan.className = 'message-time';
        if ( item.notification?.time_display ) {
            timeSpan.textContent = item.notification.time_display;
        } else {
            const ts = new Date( item.addedAt );
            timeSpan.textContent = ts.toLocaleTimeString( 'en-US', { hour: '2-digit', minute: '2-digit', hour12: false } );
        }

        const textDiv = document.createElement( 'div' );
        textDiv.className = 'tts-text';
        textDiv.textContent = truncatedText;

        const deleteBtn = document.createElement( 'button' );
        deleteBtn.className = 'tts-delete-button';
        deleteBtn.textContent = '\u00D7';
        deleteBtn.title = 'Remove from queue';
        deleteBtn.onclick = ( e ) => {
            e.stopPropagation();
            this.removeFromTTSQueue( item.id );
        };

        card.appendChild( positionDiv );
        card.appendChild( badgeDiv );
        card.appendChild( timeSpan );
        card.appendChild( textDiv );
        card.appendChild( deleteBtn );

        container.appendChild( card );

        // Re-order DOM to match ttsQueue array order (handles priority splice)
        this.reorderTTSQueueDOM();
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
     * Re-orders DOM children in tts-pending-queue to match ttsQueue array order.
     * Leverages the fact that appendChild on an existing DOM node moves it.
     */
    reorderTTSQueueDOM() {
        const container = document.getElementById( 'tts-pending-queue' );
        if ( !container ) return;

        this.ttsQueue.forEach( ( item ) => {
            const card = document.getElementById( `tts-minimized-${item.id}` );
            if ( card ) container.appendChild( card );
        } );

        this.updateTTSQueuePositions();
    }

    /**
     * Removes a single item from the TTS pending queue by ID.
     *
     * Requires:
     *     - itemId is a valid string matching a queued item's id
     *
     * Ensures:
     *     - Item is spliced from ttsQueue array
     *     - DOM card animates out with shrink-fade, then removed
     *     - Queue positions, section, and localStorage updated
     */
    removeFromTTSQueue( itemId ) {
        const idx = this.ttsQueue.findIndex( i => i.id === itemId );
        if ( idx === -1 ) {
            this.log( `TTS queue: removeFromTTSQueue - item ${itemId} not found, ignoring` );
            return;
        }

        this.log( `TTS queue: Removing item ${itemId} at position ${idx + 1}` );
        this.ttsQueue.splice( idx, 1 );

        const card = document.getElementById( `tts-minimized-${itemId}` );
        if ( card ) {
            card.classList.add( 'shrink-fade' );
            card.addEventListener( 'animationend', () => card.remove(), { once: true } );
        }

        this.updateTTSQueuePositions();
        this.updateTTSQueueSection();
        this.saveTTSQueueState();
    }

    /**
     * Clears all pending items from the TTS queue.
     * Also clears the active slot to remove any ghost cards.
     *
     * Requires:
     *     - nothing (safe to call when queue is empty)
     *
     * Ensures:
     *     - ttsQueue is emptied
     *     - activeTTSItem is cleared
     *     - Active slot and pending queue DOM are cleared
     *     - Section and localStorage updated
     */
    clearTTSQueue() {
        const hasPending = this.ttsQueue.length > 0;
        const hasActive  = this.activeTTSItem !== null;
        const activeSlot = document.getElementById( 'tts-active-slot' );
        const hasGhost   = activeSlot?.querySelector( '.tts-active-card' ) !== null;

        if ( !hasPending && !hasActive && !hasGhost ) return;

        this.log( `TTS queue: Clearing all (${this.ttsQueue.length} pending, active: ${hasActive}, ghost: ${hasGhost})` );
        this.ttsQueue      = [];
        this.activeTTSItem = null;

        if ( activeSlot ) activeSlot.innerHTML = '';

        const pendingContainer = document.getElementById( 'tts-pending-queue' );
        if ( pendingContainer ) pendingContainer.innerHTML = '';

        this.updateTTSQueueSection();
        this.saveTTSQueueState();
    }

    /**
     * Updates the Clear All button visibility and disabled state
     * based on whether there are pending queue items, an active item,
     * or a ghost card in the active slot DOM.
     *
     * Ensures:
     *     - Button shown and enabled when any TTS items exist (pending, active, or ghost)
     *     - Button hidden and disabled when nothing exists
     */
    updateTTSClearAllButtonState() {
        const btn = document.getElementById( 'tts-clear-all-btn' );
        if ( !btn ) return;

        const activeSlot  = document.getElementById( 'tts-active-slot' );
        const hasActiveUI = activeSlot?.querySelector( '.tts-active-card' ) !== null;
        const hasItems    = this.ttsQueue.length > 0 || this.activeTTSItem !== null || hasActiveUI;
        btn.style.display = hasItems ? 'inline-block' : 'none';
        btn.disabled      = !hasItems;
    }

    /**
     * Updates the TTS queue section visibility and count.
     * Shows paused state when in Focus Mode.
     * Shows empty state when section is visible but queue is empty.
     */
    updateTTSQueueSection() {
        const section = document.getElementById( 'tts-queue-section' );
        const countSpan = document.getElementById( 'tts-queue-count' );
        const activeSlot = document.getElementById( 'tts-active-slot' );
        const header = section?.querySelector( 'h3' );
        const resumeBtn = document.getElementById( 'tts-resume-btn' );
        const emptyState = document.getElementById( 'tts-queue-empty' );
        const toolbarBtn = document.querySelector( '.toolbar-btn[data-section="tts-queue-section"]' );

        if ( !section ) return;

        const totalCount = this.ttsQueue.length + ( this.activeTTSItem ? 1 : 0 );
        const hasActiveOrQueued = this.ttsQueue.length > 0 || this.activeTTSItem !== null;
        const toolbarWantsVisible = toolbarBtn?.classList.contains( 'active' );

        // Show section if: items in queue OR active item OR toolbar says show it
        const showSection = hasActiveOrQueued || toolbarWantsVisible;

        if ( !showSection ) {
            section.style.display = 'none';
            section.classList.remove( 'focus-mode' );
            section.classList.remove( 'paused' );
            // DON'T clear activeSlot - preserve paused item state for re-show
            if ( resumeBtn ) resumeBtn.style.display = 'none';
            if ( emptyState ) emptyState.style.display = 'none';
        } else {
            section.style.display = 'block';

            // Re-render active card if we have a paused/playing item but DOM was cleared
            if ( this.activeTTSItem && activeSlot ) {
                const existingCard = activeSlot.querySelector( '.tts-active-card' );
                if ( !existingCard ) {
                    this.renderActiveTTSCard( this.activeTTSItem );
                }
            }

            // Show/hide empty state based on whether we have active or queued items
            if ( emptyState ) {
                emptyState.style.display = hasActiveOrQueued ? 'none' : 'block';
            }

            // Manual Pause: User clicked pause button (has priority for header display)
            if ( this.isTTSPaused && this.activeTTSItem ) {
                section.classList.add( 'paused' );
                section.classList.remove( 'focus-mode' );
                if ( header ) {
                    header.innerHTML = `Paused: <span id="tts-queue-count">${totalCount}</span>`;
                }
                if ( resumeBtn ) resumeBtn.style.display = 'none';
            }
            // Focus Mode: Waiting for action-required response
            else if ( this.ttsFocusModeActive ) {
                section.classList.add( 'focus-mode' );
                section.classList.remove( 'paused' );
                if ( header ) {
                    header.innerHTML = `Paused: <span id="tts-queue-count">${this.ttsQueue.length}</span> waiting`;
                }
                if ( resumeBtn ) resumeBtn.style.display = 'inline-block';
            } else {
                section.classList.remove( 'focus-mode' );
                section.classList.remove( 'paused' );
                if ( header ) {
                    header.innerHTML = `🔊 Playing: <span id="tts-queue-count">${totalCount}</span>`;
                }
                if ( resumeBtn ) resumeBtn.style.display = 'none';
            }

            if ( countSpan ) {
                countSpan.textContent = this.ttsFocusModeActive ? this.ttsQueue.length : totalCount;
            }
        }

        // Update pause/play button states
        this.updateTTSPausePlayButtons();

        // Update Clear All button visibility
        this.updateTTSClearAllButtonState();
    }

    /**
     * Called when TTS playback completes (success or error).
     * Clears active item and activates next in queue.
     * For action-required: enters Focus Mode to pause queue during response.
     */
    onTTSPlaybackComplete() {
        // Don't advance if manually paused
        if ( this.isTTSPaused ) {
            this.log( 'TTS queue: Playback complete callback fired, but manually paused - not advancing' );
            return;
        }

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
        // Clear activeTTSItem BEFORE entering focus mode so updateTTSQueueSection()
        // (called inside enterTTSFocusMode) doesn't re-render a ghost card into active slot
        if ( wasActionRequired && justCompletedItem?.id ) {
            // Check if notification was already resolved while audio was playing (Path B-2 race)
            const arState = this.actionRequiredNotifications.get( justCompletedItem.id );
            if ( !arState || arState.isResponded || arState.isExpired ) {
                this.log( `TTS queue: Skipping focus mode — notification ${justCompletedItem.id} already resolved` );
                this.activeTTSItem = null;
                // Fall through to normal queue advancement below
            } else {
                this.activeTTSItem = null;  // Clear BEFORE focus mode to prevent ghost re-render
                this.enterTTSFocusMode( justCompletedItem.id );
                // updateTTSQueueSection() already called inside enterTTSFocusMode
                return;  // Exit early - don't activate next until response received
            }
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
        this.stopAudio();
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

        // GUARD: Never enter focus mode for an already-resolved notification.
        // Prevents Path B-2 race: onended fires after user already responded/dismissed/expired.
        const guardState = this.actionRequiredNotifications.get( notificationId );
        if ( !guardState || guardState.isResponded || guardState.isExpired ) {
            this.log( `TTS Focus Mode: SKIPPED — notification ${notificationId} already resolved (responded=${guardState?.isResponded}, expired=${guardState?.isExpired}, exists=${!!guardState})` );
            // Advance queue since onTTSPlaybackComplete() returned early expecting focus mode to handle it
            if ( this.ttsQueue.length > 0 && !this.isTTSPaused ) {
                setTimeout( () => this.activateNextTTS(), 100 );
            }
            return;
        }

        this.ttsFocusModeActive = true;
        this.focusModeNotificationId = notificationId;
        this.focusModeEnteredAt = Date.now();

        // Compute safety timeout from notification's own timeout + buffer
        // (guardState already fetched above and validated as non-null/non-resolved)
        const notifTimeoutMs = guardState?.timeoutSeconds
            ? guardState.timeoutSeconds * 1000 + this.TTS_FOCUS_MODE_BUFFER_MS
            : this.TTS_FOCUS_MODE_FALLBACK_MS;
        this.focusModeTimeoutMs = notifTimeoutMs;

        this.log( `TTS Focus Mode: Safety timeout set to ${notifTimeoutMs / 1000}s` );
        this.focusModeTimeoutId = setTimeout( () => {
            this.log( `TTS Focus Mode: Safety timeout (${notifTimeoutMs / 1000}s) — auto-exiting` );
            this.exitTTSFocusMode();
        }, notifTimeoutMs );

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
        this.log( `🔴 exitTTSFocusMode() CALLED at ${Date.now()}` );
        if ( !this.ttsFocusModeActive ) {
            return;  // Not in focus mode, nothing to do
        }

        // Stop any audio that was playing for this notification
        this.stopAudio();

        // Clear safety timeout if still pending
        if ( this.focusModeTimeoutId ) {
            clearTimeout( this.focusModeTimeoutId );
            this.focusModeTimeoutId = null;
        }

        this.log( `TTS Focus Mode: EXITING (was for ${this.focusModeNotificationId})` );
        this.ttsFocusModeActive = false;
        this.focusModeNotificationId = null;
        this.focusModeEnteredAt = null;
        this.focusModeTimeoutMs = null;
        this.focusModeElapsedBeforePause = null;
        this.updateTTSQueueSection();

        // Persist focus mode state change
        this.saveTTSQueueState();

        // Resume queue if items waiting AND not manually paused
        if ( this.ttsQueue.length > 0 && !this.isTTSPaused ) {
            this.log( `TTS Focus Mode: Resuming queue with ${this.ttsQueue.length} items` );
            setTimeout( () => this.activateNextTTS(), 100 );  // Small delay for UI to settle
        } else if ( this.isTTSPaused ) {
            this.log( `TTS Focus Mode: Exited but manual pause active - not resuming` );
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
    // TTS MANUAL PAUSE/PLAY - User-controlled pause like a music player
    // =========================================================================

    /**
     * Pauses TTS audio mid-stream (like a music player pause button).
     * Works with both instant mode (Web Audio) and reliable mode (HTML Audio).
     *
     * Ensures:
     *     - Audio is suspended at current position
     *     - Queue does not advance while paused
     *     - UI shows paused state with amber header
     */
    pauseTTS() {
        if ( this.isTTSPaused || !this.activeTTSItem ) {
            this.log( 'TTS Pause: Already paused or nothing playing' );
            return;
        }

        this.log( 'TTS Pause: User pausing playback' );

        // Pause Web Audio (instant mode)
        if ( this.pcmAudioContext && this.pcmAudioContext.state === 'running' ) {
            this.pcmAudioContext.suspend();
            this.log( 'TTS Pause: Suspended Web Audio context' );
        }

        // Pause HTML Audio (reliable mode)
        if ( this.audioElement && !this.audioElement.paused ) {
            this.audioElement.pause();
            this.log( 'TTS Pause: Paused HTML audio element' );
        }

        this.isTTSPaused = true;
        this.updateTTSPausePlayButtons();
        this.updateTTSQueueSection();
        this.saveTTSQueueState();
    }

    /**
     * Resumes TTS audio from the paused position.
     * Works with both instant mode (Web Audio) and reliable mode (HTML Audio).
     *
     * Ensures:
     *     - Audio resumes from where it was paused
     *     - Queue continues normally after current item finishes
     */
    resumeTTS() {
        if ( !this.isTTSPaused ) {
            this.log( 'TTS Resume: Not paused' );
            return;
        }

        this.log( 'TTS Resume: User resuming playback' );

        // Resume Web Audio (instant mode)
        if ( this.pcmAudioContext && this.pcmAudioContext.state === 'suspended' ) {
            this.pcmAudioContext.resume();
            this.log( 'TTS Resume: Resumed Web Audio context' );
        }

        // Resume HTML Audio (reliable mode)
        if ( this.audioElement && this.audioElement.paused && this.audioElement.src ) {
            this.audioElement.play().catch( e => this.error( 'TTS Resume failed:', e ) );
            this.log( 'TTS Resume: Resumed HTML audio element' );
        }

        this.isTTSPaused = false;
        this.updateTTSPausePlayButtons();
        this.updateTTSQueueSection();
        this.saveTTSQueueState();
    }

    /**
     * Updates pause/play button enabled states based on current playback status.
     *
     * Button states:
     *     - Nothing playing: both disabled
     *     - Playing: pause enabled, play disabled
     *     - Paused: pause disabled, play enabled
     */
    updateTTSPausePlayButtons() {
        const pauseBtn = document.getElementById( 'tts-pause-btn' );
        const playBtn = document.getElementById( 'tts-play-btn' );
        const section = document.getElementById( 'tts-queue-section' );

        if ( !pauseBtn || !playBtn ) return;

        const hasActiveItem = this.activeTTSItem !== null;

        if ( !hasActiveItem ) {
            // Nothing playing - both disabled
            pauseBtn.classList.add( 'disabled' );
            playBtn.classList.add( 'disabled' );
            section?.classList.remove( 'paused' );
        } else if ( this.isTTSPaused ) {
            // Paused - pause disabled, play enabled
            pauseBtn.classList.add( 'disabled' );
            playBtn.classList.remove( 'disabled' );
            section?.classList.add( 'paused' );
        } else {
            // Playing - pause enabled, play disabled
            pauseBtn.classList.remove( 'disabled' );
            playBtn.classList.add( 'disabled' );
            section?.classList.remove( 'paused' );
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
            if ( this.ttsQueue.length === 0 && !this.ttsFocusModeActive && !this.isTTSPaused ) {
                localStorage.removeItem( this.TTS_QUEUE_KEY );
                return;
            }

            const queueState = {
                queue                   : this.ttsQueue,
                focusModeActive         : this.ttsFocusModeActive,
                focusModeNotificationId : this.focusModeNotificationId,
                focusModeEnteredAt      : this.focusModeEnteredAt || null,
                focusModeTimeoutMs      : this.focusModeTimeoutMs || null,
                isTTSPaused             : this.isTTSPaused
            };

            localStorage.setItem( this.TTS_QUEUE_KEY, JSON.stringify( queueState ) );
            this.log( `Saved ${this.ttsQueue.length} TTS queue item(s) to localStorage (paused: ${this.isTTSPaused})` );
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
            this.focusModeEnteredAt = parsed.focusModeEnteredAt || null;
            this.focusModeTimeoutMs = parsed.focusModeTimeoutMs || null;
            // NOTE: Don't restore isTTSPaused - page refresh resets audio context,
            // so we should auto-resume playback. User can pause again if needed.
            this.isTTSPaused = false;

            this.log( `Restored ${this.ttsQueue.length} TTS queue item(s), focusMode: ${this.ttsFocusModeActive} (paused state reset on refresh)` );

            // Re-render minimized cards for queued items
            for ( const item of this.ttsQueue ) {
                this.renderMinimizedTTSCard( item );
            }

            this.updateTTSQueueSection();

            // Staleness check: if focus mode was restored but the triggering
            // notification no longer exists, auto-exit focus mode
            if ( this.ttsFocusModeActive && this.focusModeNotificationId ) {
                const notificationStillExists = this.actionRequiredNotifications.has( this.focusModeNotificationId );
                if ( !notificationStillExists ) {
                    this.log( `TTS Focus Mode: Stale — notification ${this.focusModeNotificationId} no longer exists, auto-exiting` );
                    this.ttsFocusModeActive = false;
                    this.focusModeNotificationId = null;
                    this.focusModeEnteredAt = null;
                    this.focusModeTimeoutMs = null;
                    this.saveTTSQueueState();
                }
            }

            // Time-based staleness: if focus mode has exceeded its safety timeout, auto-exit
            if ( this.ttsFocusModeActive && this.focusModeEnteredAt ) {
                const elapsed = Date.now() - this.focusModeEnteredAt;
                const timeoutMs = this.focusModeTimeoutMs || this.TTS_FOCUS_MODE_FALLBACK_MS;
                if ( elapsed > timeoutMs ) {
                    this.log( `TTS Focus Mode: Stale — entered ${Math.round( elapsed / 1000 )}s ago (limit: ${timeoutMs / 1000}s), auto-exiting` );
                    this.ttsFocusModeActive = false;
                    this.focusModeNotificationId = null;
                    this.focusModeEnteredAt = null;
                    this.focusModeTimeoutMs = null;
                    this.saveTTSQueueState();
                } else {
                    // Still within timeout — restart timer for remaining time
                    const remaining = timeoutMs - elapsed;
                    this.log( `TTS Focus Mode: Restored with ${Math.round( remaining / 1000 )}s remaining on safety timeout` );
                    this.focusModeTimeoutId = setTimeout( () => {
                        this.log( `TTS Focus Mode: Safety timeout — auto-exiting after restore` );
                        this.exitTTSFocusMode();
                    }, remaining );
                }
            }

            // If not in focus mode and queue has items, start playback
            // (isTTSPaused is always false after restore - refresh resets pause state)
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
                <div class="yes-no-comment-hint" data-notification-id="${notification.id}">
                    ${notification.display_qualifier_widget ? 'You may comment on your answer here if you wish' : 'Press C to add comment'}
                </div>
                <div class="yes-no-comment-container${notification.display_qualifier_widget ? ' expanded' : ''}" id="yn-comment-container-${notification.id}">
                    <div class="yes-no-comment-input-row">
                        <button class="response-mic-button yes-no-comment-mic" data-notification-id="${notification.id}" title="Record voice comment">
                            🎤
                        </button>
                        <input type="text" class="yes-no-comment-input" id="yn-comment-input-${notification.id}" maxlength="300" placeholder="Qualify your answer...">
                    </div>
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
        } else if ( notification.response_type === 'open_ended_batch' ) {
            responseUI = this.renderOpenEndedBatchUI( notification );
        }

        // Build abstract section if present - render markdown with XSS protection
        const abstractSection = notification.abstract ? `
            <div class="action-required-abstract">${this.renderMarkdown( notification.abstract )}</div>
        ` : '';

        const predictionHintSection = this.buildPredictionHintSection( notification );

        // Extract project badge from sender_id (same pattern as renderMultipleChoiceUI)
        const project      = this.getProjectFromSenderId( notification.sender_id );
        const projectBadge = project && project !== 'UNKNOWN'
            ? `<span class="mc-project-badge">[${project}]</span> `
            : '';

        // Persona badge — read voice_persona straight off the persisted notification
        // envelope (server stamps it via _voice_persona_for_sender_id). This avoids
        // any race between map hydration and action-required restore on refresh.
        // Right-aligned via insertion as the first child of .action-required-timer-controls
        // (the existing flex right-cluster).
        const personaBadge = this._renderPersonaBadgeHTML( notification.voice_persona );

        card.innerHTML = `
            <div class="action-required-header">
                <button class="action-required-cancel-btn" data-notification-id="${notification.id}" title="Cancel and use default (Esc)">
                    ✕
                </button>
                <div class="action-required-title">${projectBadge}${notification.title || notification.message}</div>
                <div class="action-required-timer-controls">
                    ${personaBadge}
                    <button class="action-required-pause-btn" id="pause-btn-${notification.id}" title="Pause timer and audio (P)">
                        \u23F8\uFE0F
                    </button>
                    <div class="action-required-timer" id="timer-${notification.id}">--:--</div>
                </div>
            </div>
            <div class="action-required-message">${this.renderMarkdown( notification.message )}</div>
            ${abstractSection}
            ${predictionHintSection}
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

        // Pause button (applies to all response types)
        const pauseBtn = card.querySelector( '.action-required-pause-btn' );
        if ( pauseBtn ) {
            pauseBtn.addEventListener( 'click', () => this.togglePause() );
        }

        // Cancel button in header (applies to all response types)
        const cancelBtn = card.querySelector( '.action-required-cancel-btn' );
        if ( cancelBtn ) {
            cancelBtn.addEventListener( 'click', () => this.cancelActionRequired( notification.id ) );
        }

        if ( notification.response_type === 'yes_no' ) {
            card.querySelectorAll( '.response-button' ).forEach( button => {
                button.addEventListener( 'click', ( e ) => {
                    const response = e.target.closest( '.response-button' ).dataset.response;
                    this.submitYesNoWithComment( notification.id, response );
                } );
            } );

            // Comment hint toggle
            const commentHint = card.querySelector( '.yes-no-comment-hint' );
            if ( commentHint ) {
                commentHint.addEventListener( 'click', () => this.toggleYesNoComment( notification.id ) );
            }

            // Comment mic button
            const commentMic = card.querySelector( '.yes-no-comment-mic' );
            if ( commentMic ) {
                commentMic.addEventListener( 'click', () => this.startYesNoCommentVoiceInput( notification.id ) );
            }

            // Comment input Enter key — blur back to card so Y/N keys work
            const commentInput = card.querySelector( '.yes-no-comment-input' );
            if ( commentInput ) {
                commentInput.addEventListener( 'keydown', ( e ) => {
                    if ( e.key === 'Enter' ) {
                        e.preventDefault();
                        commentInput.blur();
                    }
                } );
            }
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
                const isValid = value.length > 0;

                submitButton.disabled = !isValid;

                if ( input.value.length > 0 ) {
                    input.classList.remove( 'invalid' );
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
        } else if ( notification.response_type === 'open_ended_batch' ) {
            this.attachOpenEndedBatchEventHandlers( notification.id, card );
        }
    }

    /**
     * Renders the UI for an open-ended batch notification.
     * All questions visible at once with text input + mic button per question.
     *
     * Requires:
     *   - notification.response_options.questions is a non-empty array
     *   - Each question has: question (string), header (string), input_type = "text"
     *
     * Ensures:
     *   - Returns HTML string with all questions rendered at once
     *   - Each question has a numbered label, text, mic button, and text input
     *   - Single "Submit All" button at bottom
     */
    renderOpenEndedBatchUI( notification ) {
        const questions = notification.response_options?.questions || [];
        const total     = questions.length;

        if ( total === 0 ) {
            return '<div class="response-open-ended-batch"><p>No questions provided.</p></div>';
        }

        let questionsHTML = '';
        for ( let i = 0; i < total; i++ ) {
            const q = questions[ i ];
            const header       = q.header || `Question ${i + 1}`;
            const defaultValue = q.default_value || '';

            questionsHTML += `
                <div class="batch-question" data-question-index="${i}" data-header="${this.escapeHtml( header )}">
                    <div class="batch-question-label">Question ${i + 1} of ${total}</div>
                    <div class="batch-question-text">${this.escapeHtml( q.question || '' )}</div>
                    <div class="batch-input-row">
                        <button class="response-mic-button batch-mic-button" data-question-index="${i}" title="Press to record (30s max, ESC to cancel)">
                            🎤
                        </button>
                        <input type="text" class="response-text-input batch-text-input" data-question-index="${i}" data-header="${this.escapeHtml( header )}" value="${this.escapeHtml( defaultValue )}" placeholder="Type your answer...">
                    </div>
                </div>
            `;
        }

        return `
            <div class="response-open-ended-batch">
                ${questionsHTML}
                <div class="batch-submit-actions">
                    <button class="response-submit-button batch-submit-all">
                        Submit All ✓
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Builds prediction hint HTML section for action-required notification cards.
     *
     * Requires:
     *   - notification object with optional prediction_hint field
     *   - notification.response_type indicates the type of response expected
     *
     * Ensures:
     *   - Returns ghost hint box if prediction_hint is null/undefined (cold start)
     *   - Returns formatted HTML div for yes_no, multiple_choice, open_ended, open_ended_batch
     *   - Displays predicted value, confidence percentage, and strategy label
     */
    buildPredictionHintSection( notification ) {
        const hint = notification.prediction_hint;
        if ( !hint ) {
            return `
                <div class="prediction-hint prediction-hint-cold">
                    <div class="prediction-hint-label">Learning, no prediction yet</div>
                </div>
            `;
        }

        const confidence   = Math.round( hint.confidence * 100 );
        const strategy     = this.formatStrategyLabel( hint.strategy );
        const responseType = notification.response_type;

        let predictedText = '';

        if ( responseType === 'yes_no' ) {
            const value = typeof hint.predicted_value === 'string'
                ? hint.predicted_value.charAt( 0 ).toUpperCase() + hint.predicted_value.slice( 1 )
                : hint.predicted_value;
            predictedText = hint.predicted_qualifier
                ? `Predicted: ${value} — "${hint.predicted_qualifier}" (${confidence}%)`
                : `Predicted: ${value} (${confidence}%)`;

        } else if ( responseType === 'multiple_choice' ) {
            const answers = hint.predicted_value?.answers;
            if ( answers ) {
                const parts = Object.entries( answers ).map( ( [ header, val ] ) => {
                    return Array.isArray( val ) ? `${header}: [${val.join( ', ' )}]` : `${header}: ${val}`;
                } );
                predictedText = `Predicted: ${parts.join( '; ' )} (${confidence}%)`;
            }

        } else if ( responseType === 'open_ended' ) {
            const value = typeof hint.predicted_value === 'string'
                ? hint.predicted_value
                : JSON.stringify( hint.predicted_value );
            predictedText = `Predicted: "${value}" (${confidence}%)`;

        } else if ( responseType === 'open_ended_batch' ) {
            const answers = hint.predicted_value?.answers;
            if ( answers ) {
                const parts = Object.entries( answers ).map( ( [ header, val ] ) =>
                    `${header}: "${val}"`
                );
                predictedText = `Predicted: ${parts.join( '; ' )} (${confidence}%)`;
            }
        }

        if ( !predictedText ) return '';

        return `
            <div class="prediction-hint">
                <div class="prediction-hint-label">${predictedText}</div>
                <div class="prediction-hint-strategy">${strategy}</div>
            </div>
        `;
    }

    /**
     * Maps prediction strategy constants to human-readable labels.
     *
     * Requires:
     *   - strategy is a string constant from PredictionEngine
     *
     * Ensures:
     *   - Returns human-readable label for known strategies
     *   - Returns raw strategy string as fallback for unknown strategies
     */
    formatStrategyLabel( strategy ) {
        const labels = {
            'cbr_majority_vote'       : 'Based on majority vote',
            'cbr_retrieval'           : 'Based on exact match retrieval',
            'llm_synthesis'           : 'Based on LLM synthesis',
            'option_embedding_scoring': 'Based on option scoring',
            'cold_start'              : 'No prediction data'
        };
        return labels[ strategy ] || strategy;
    }

    /**
     * Attaches event handlers for an open-ended batch notification.
     *
     * Requires:
     *   - card contains rendered batch UI elements
     *
     * Ensures:
     *   - Submit button collects all answers and submits
     *   - Mic buttons start voice input for their respective text inputs
     *   - Enter on last input submits; Enter on others focuses next input
     */
    attachOpenEndedBatchEventHandlers( notificationId, card ) {
        const submitButton = card.querySelector( '.batch-submit-all' );
        const textInputs   = card.querySelectorAll( '.batch-text-input' );
        const micButtons   = card.querySelectorAll( '.batch-mic-button' );
        const totalInputs  = textInputs.length;

        // Submit button click
        if ( submitButton ) {
            submitButton.addEventListener( 'click', () => {
                this.submitOpenEndedBatchAnswers( notificationId );
            } );
        }

        // Text input keydown handlers
        textInputs.forEach( ( input, index ) => {
            input.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' ) {
                    e.preventDefault();
                    if ( index < totalInputs - 1 ) {
                        // Focus next input
                        textInputs[ index + 1 ].focus();
                    } else {
                        // Last input — submit
                        this.submitOpenEndedBatchAnswers( notificationId );
                    }
                }
            } );
        } );

        // Mic button click handlers — each bound to its own text input
        micButtons.forEach( ( micButton, index ) => {
            const textInput = textInputs[ index ];
            micButton.addEventListener( 'click', () => {
                this.startBatchVoiceInput( notificationId, index, micButton, textInput );
            } );
            micButton.addEventListener( 'keydown', ( e ) => {
                if ( e.key === 'Enter' || e.key === ' ' ) {
                    e.preventDefault();
                    this.startBatchVoiceInput( notificationId, index, micButton, textInput );
                }
            } );
        } );

        // Voice-first: focus first mic button for immediate activation
        if ( micButtons.length > 0 ) {
            micButtons[ 0 ].focus( { preventScroll: true } );
        }
    }

    /**
     * Collects all batch answers and submits as JSON.
     *
     * Requires:
     *   - All required batch text inputs have values
     *
     * Ensures:
     *   - Collects values keyed by header
     *   - Validates at least one field has content
     *   - Submits as JSON: { answers: { "Header": "value", ... } }
     */
    submitOpenEndedBatchAnswers( notificationId ) {
        const card       = document.getElementById( `action-required-${notificationId}` );
        const textInputs = card?.querySelectorAll( '.batch-text-input' );

        if ( !textInputs || textInputs.length === 0 ) return;

        const answers = {};
        let hasAnyContent = false;
        let allValid      = true;

        textInputs.forEach( ( input ) => {
            const header = input.dataset.header;
            const value  = input.value.trim();
            answers[ header ] = value;

            if ( value.length > 0 ) {
                hasAnyContent = true;
                input.classList.remove( 'invalid' );
            } else {
                input.classList.add( 'invalid' );
                allValid = false;
            }
        } );

        if ( !hasAnyContent || !allValid ) {
            this.log( 'submitOpenEndedBatchAnswers: Not all fields filled' );
            // Shake the container briefly for visual feedback
            const container = card?.querySelector( '.response-open-ended-batch' );
            if ( container ) {
                container.classList.add( 'invalid' );
                setTimeout( () => container.classList.remove( 'invalid' ), 2000 );
            }
            return;
        }

        const response = { answers: answers };
        this.log( 'Submitting batch answers:', response );
        this.submitResponse( notificationId, JSON.stringify( response ) );
    }

    /**
     * Starts voice input for a specific question in an open-ended batch.
     * Uses unified RecordingManager.
     */
    async startBatchVoiceInput( notificationId, questionIndex, micButton, textInput ) {
        this.log( `Starting voice input for batch question ${questionIndex}: ${notificationId}` );

        if ( !micButton || !textInput ) {
            this.error( `Voice input: Could not find batch UI elements for question ${questionIndex}` );
            return;
        }

        // Toggle recording state using unified RecordingManager
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
        } else if ( !this.recordingManager.isProcessing() ) {
            await this.recordingManager.startRecording( `batch-${notificationId}-${questionIndex}`, micButton, textInput, {
                onTranscriptionComplete: () => {
                    // Clear invalid state on successful transcription
                    textInput.classList.remove( 'invalid' );
                }
            } );
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
            this.log( "Already responded or notification not found — performing UI cleanup" );

            // Defense in depth: ensure card and focus mode are cleaned up
            if ( state?.isResponded ) {
                const card = document.getElementById( `action-required-${notificationId}` );
                if ( card ) card.remove();

                const minimized = document.getElementById( `action-required-minimized-${notificationId}` );
                if ( minimized ) minimized.remove();

                this.actionRequiredNotifications.delete( notificationId );
                this.updateActionRequiredCount();
                this.saveActionRequiredState();

                if ( this.activeActionRequiredId === notificationId ) {
                    this.activeActionRequiredId = null;
                    this.activateNextNotification();
                }

                if ( this.focusModeNotificationId === notificationId ) {
                    this.exitTTSFocusMode();
                }
            }

            return;
        }

        // Mark as responded
        state.isResponded = true;

        // Stop TTS immediately if this notification is currently playing
        // User already answered — don't keep reading the question
        if ( this.activeTTSItem?.id === notificationId ) {
            this.log( `Stopping TTS — user responded to currently-playing notification ${notificationId}` );
            this.stopAudio();
            this.onTTSPlaybackComplete();
        }

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

            const apiResponse = await this.authedFetch( '/api/notify/response', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify( payload )
            } );

            if ( !apiResponse.ok ) {
                const errorData = await apiResponse.json();

                // Special handling for grace period exceeded (rare with 5-minute window)
                if ( apiResponse.status === 400 && errorData.detail?.includes( 'grace period exceeded' ) ) {
                    this.handleGracePeriodExceeded( notificationId, state );
                    return;
                }

                // Already responded/expired server-side — dismiss card gracefully
                if ( apiResponse.status === 400 && errorData.detail?.includes( 'already responded' ) ) {
                    this.handleGracePeriodExceeded( notificationId, state );
                    return;
                }

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

    /**
     * Handles the case when response is submitted after grace period expired.
     * This is rare with the 5-minute window but should be handled gracefully.
     *
     * Requires:
     *     - notificationId is valid
     *     - state is the notification state object
     *
     * Ensures:
     *     - User is informed their response was too late
     *     - Notification transitions to conversation history
     *     - Default response indicator is shown
     */
    handleGracePeriodExceeded( notificationId, state ) {
        this.log( `Grace period exceeded for ${notificationId}` );

        const card = document.getElementById( `action-required-${notificationId}` );
        if ( !card ) return;

        // Show message in card
        const msgDiv = document.createElement( 'div' );
        msgDiv.className = 'grace-period-exceeded-message';
        msgDiv.innerHTML = '\u23F0 Response window has closed. Default response was used.';
        card.insertBefore( msgDiv, card.firstChild );

        // Mark as expired and stop timer
        state.isExpired = true;
        this.stopCountdownTimer( notificationId );

        // Stop TTS if this notification is currently playing
        if ( this.activeTTSItem?.id === notificationId ) {
            this.log( `Stopping TTS — grace period exceeded for currently-playing notification ${notificationId}` );
            this.stopAudio();
            this.onTTSPlaybackComplete();
        }

        // Exit focus mode if active for this notification
        if ( this.focusModeNotificationId === notificationId ) {
            this.exitTTSFocusMode();
        }

        // Transition to conversation history after delay
        setTimeout( () => {
            const senderId = state.notification?.sender_id || this.UNKNOWN_SENDER;

            // Remove card with animation
            card.classList.add( 'shrink-fade' );
            card.addEventListener( 'animationend', () => {
                card.remove();

                // Route to conversation with default indicator
                const defaultValue = state.notification.response_default || '(no response)';
                this.routeCompletedNotification( state.notification, defaultValue, true );

                // Cleanup
                this.actionRequiredNotifications.delete( notificationId );
                this.updateActionRequiredCount();
                this.saveActionRequiredState();

                // Promote next notification
                if ( this.activeActionRequiredId === notificationId ) {
                    this.activeActionRequiredId = null;
                    setTimeout( () => this.activateNextNotification(), 100 );
                }
            }, { once: true } );
        }, 2000 );  // Show message for 2 seconds before transitioning
    }

    showConfirmation( notificationId, response, serverTimeDisplay = null, serverDateDisplay = null ) {
        const card = document.getElementById( `action-required-${notificationId}` );
        if ( !card ) return;

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) return;

        // Get sender ID from notification
        const senderId = state.notification?.sender_id || this.UNKNOWN_SENDER;

        // Ensure sender card exists for the conversation (skip if routing to job card)
        let senderCard = null;
        if ( !state.notification.job_id ) {
            const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
            senderCard = document.getElementById( cardId );
            if ( !senderCard ) {
                this.createSenderCard( senderId );
                senderCard = document.getElementById( cardId );
            }
        }

        // Simple shrink-fade animation in place (no flying)
        card.classList.add( 'shrink-fade' );

        // On animation complete: remove card, add conversation pair with highlight
        card.addEventListener( 'animationend', () => {
            // Remove the action-required card from DOM
            card.remove();

            // Route completed Q&A to job card or sender card
            this.routeCompletedNotification( state.notification, response, false, serverTimeDisplay, serverDateDisplay );

            // Cleanup action-required state
            this.actionRequiredNotifications.delete( notificationId );
            this.updateActionRequiredCount();
            this.saveActionRequiredState();  // Persist removal

            // Scroll sender card into view (job card scroll handled by routeCompletedNotification)
            if ( !state.notification.job_id && senderCard ) {
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
                this.routeCompletedNotification( state.notification, response, false, serverTimeDisplay, serverDateDisplay );
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

        // TTS FOCUS MODE: Exit if this notification triggered focus mode
        if ( this.focusModeNotificationId === notificationId ) {
            this.exitTTSFocusMode();
        }

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

        // Calculate destination for animation (prefer job card when job_id exists)
        let destination;
        if ( state.notification.job_id ) {
            const jobCard = document.getElementById( `job-card-${state.notification.job_id}` );
            if ( jobCard ) {
                const header = jobCard.querySelector( '.job-card-header' );
                const rect = ( header || jobCard ).getBoundingClientRect();
                destination = {
                    cardId   : `job-card-${state.notification.job_id}`,
                    senderId : senderId,
                    rect     : rect
                };
            }
        }
        if ( !destination ) {
            destination = this.calculateDestination( senderId );
        }

        if ( destination ) {
            // Start genie animation for expired notification
            this.startGenieAnimation( notificationId, card, destination, () => {
                // On animation complete: route to job card or sender card (marked as expired)
                // Use client-generated time/date since there's no server call for timeout
                this.routeCompletedNotification( state.notification, defaultValue, true, this.getLocalTimeDisplay(), this.getLocalDateDisplay() );

                // Cleanup action-required state
                this.actionRequiredNotifications.delete( notificationId );
                this.updateActionRequiredCount();
                this.saveActionRequiredState();  // Persist removal

                // Scroll target card into view after DOM changes
                const targetCard = document.getElementById( destination.cardId );
                if ( targetCard ) {
                    targetCard.scrollIntoView( { behavior: 'smooth', block: 'start' } );
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

    stopCountdownTimer( notificationId ) {
        const intervalHandle = this.countdownTimers.get( notificationId );
        if ( intervalHandle ) {
            clearInterval( intervalHandle );
            this.countdownTimers.delete( notificationId );
        }
    }

    // ========================================
    // ACTION-REQUIRED PAUSE/RESUME METHODS
    // ========================================

    /**
     * Pauses the active action-required notification.
     * Freezes countdown timer and pauses TTS playback.
     *
     * Requires:
     *     - Active notification exists
     *     - Notification is not already paused
     *
     * Ensures:
     *     - Timer is frozen at current remaining time
     *     - TTS is paused
     *     - UI shows paused state with amber styling
     *     - Grace period message is displayed
     *     - State is persisted to localStorage
     */
    pauseActionRequired() {
        const notificationId = this.activeActionRequiredId;
        if ( !notificationId ) {
            this.log( 'Pause: No active notification' );
            return;
        }

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state || state.isPaused ) {
            this.log( 'Pause: Already paused or state not found' );
            return;
        }

        this.log( `Pause: Pausing notification ${notificationId}` );

        // 1. Record pause start time
        state.isPaused = true;
        state.pausedAt = Date.now();
        this.isPaused = true;

        // 2. Stop countdown timer (preserve expiresAt for remaining time calculation)
        this.stopCountdownTimer( notificationId );

        // 3. Pause TTS if playing
        this.pauseTTS();

        // 4. Update UI: button icon, amber styling, grace period message
        this.updatePauseButtonUI( notificationId, true );
        this.updatePausedTimerDisplay( notificationId, true );
        this.showGracePeriodMessage( notificationId, true );

        // 5. Persist state
        this.saveActionRequiredState();

        // Pause focus mode safety timer if active
        if ( this.ttsFocusModeActive && this.focusModeTimeoutId ) {
            clearTimeout( this.focusModeTimeoutId );
            this.focusModeTimeoutId = null;
            // Record how much time has elapsed so we can compute remaining on resume
            this.focusModeElapsedBeforePause = Date.now() - this.focusModeEnteredAt;
            this.log( `TTS Focus Mode: Safety timer paused (${Math.round( this.focusModeElapsedBeforePause / 1000 )}s elapsed)` );
        }

        this.log( `Pause: Notification ${notificationId} paused` );
    }

    /**
     * Resumes the paused action-required notification.
     * Restarts countdown timer and resumes TTS playback.
     *
     * Requires:
     *     - Active notification exists and is paused
     *
     * Ensures:
     *     - Timer resumes with extended time (pause duration added)
     *     - TTS resumes from paused position
     *     - UI returns to normal state
     *     - State is persisted to localStorage
     */
    resumeActionRequired() {
        const notificationId = this.activeActionRequiredId;
        if ( !notificationId ) {
            this.log( 'Resume: No active notification' );
            return;
        }

        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state || !state.isPaused ) {
            this.log( 'Resume: Not paused or state not found' );
            return;
        }

        this.log( `Resume: Resuming notification ${notificationId}` );

        // 1. Calculate pause duration and extend expiresAt
        const pauseDuration = Date.now() - state.pausedAt;
        state.totalPausedDuration += pauseDuration;
        state.expiresAt += pauseDuration;

        // 2. Clear pause state
        state.isPaused = false;
        state.pausedAt = null;
        this.isPaused = false;

        // 3. Restart countdown timer
        this.startCountdownTimer( notificationId );

        // 4. Resume TTS
        this.resumeTTS();

        // 5. Update UI: button icon, remove amber styling, hide grace period message
        this.updatePauseButtonUI( notificationId, false );
        this.updatePausedTimerDisplay( notificationId, false );
        this.showGracePeriodMessage( notificationId, false );

        // 6. Persist state
        this.saveActionRequiredState();

        // Resume focus mode safety timer if active
        if ( this.ttsFocusModeActive && this.focusModeTimeoutMs && !this.focusModeTimeoutId ) {
            const elapsed = this.focusModeElapsedBeforePause || ( Date.now() - this.focusModeEnteredAt );
            const remaining = this.focusModeTimeoutMs - elapsed;
            if ( remaining > 0 ) {
                this.log( `TTS Focus Mode: Safety timer resumed (${Math.round( remaining / 1000 )}s remaining)` );
                this.focusModeTimeoutId = setTimeout( () => {
                    this.log( `TTS Focus Mode: Safety timeout — auto-exiting` );
                    this.exitTTSFocusMode();
                }, remaining );
            } else {
                this.log( `TTS Focus Mode: Safety timeout already exceeded during pause — auto-exiting` );
                this.exitTTSFocusMode();
            }
            this.focusModeElapsedBeforePause = null;
        }

        this.log( `Resume: Notification ${notificationId} resumed, added ${pauseDuration}ms to timer` );
    }

    /**
     * Toggles pause state of the active action-required notification.
     * Includes state recovery if activeActionRequiredId is null but a notification is visible.
     */
    togglePause() {
        this.log( `togglePause called: isPaused=${this.isPaused}, activeId=${this.activeActionRequiredId}` );

        // Defensive check: if no active ID but notification is visible, attempt recovery
        if ( !this.activeActionRequiredId ) {
            const activeSlot = document.getElementById( 'action-required-active-slot' );
            const visibleCard = activeSlot?.querySelector( '.action-required-notification' );

            if ( visibleCard ) {
                // Extract notification ID from card ID (format: action-required-{id})
                const cardId = visibleCard.id;
                const notificationId = cardId.replace( 'action-required-', '' );

                if ( notificationId && this.actionRequiredNotifications.has( notificationId ) ) {
                    this.log( `togglePause: Recovering activeActionRequiredId from visible card: ${notificationId}` );
                    this.activeActionRequiredId = notificationId;

                    // Also mark state as active
                    const state = this.actionRequiredNotifications.get( notificationId );
                    if ( state ) {
                        state.isActive = true;
                    }
                }
            }
        }

        // Now proceed with pause toggle
        if ( this.isPaused ) {
            this.resumeActionRequired();
        } else {
            this.pauseActionRequired();
        }

        // Visual feedback if pause still didn't work (activeActionRequiredId still null)
        if ( !this.activeActionRequiredId ) {
            this.log( 'togglePause: Still no active notification after recovery attempt' );
            // Brief shake animation on the pause button to indicate issue
            const visibleCard = document.querySelector( '.action-required-notification.active' );
            const pauseBtn = visibleCard?.querySelector( '.action-required-pause-btn' );
            if ( pauseBtn ) {
                pauseBtn.classList.add( 'shake' );
                setTimeout( () => pauseBtn.classList.remove( 'shake' ), 300 );
            }
        }
    }

    /**
     * Cancels the active action-required notification by submitting the default value.
     * Triggered by Cancel button click or Escape key.
     *
     * Requires:
     *   - notificationId corresponds to an active action-required notification
     *
     * Ensures:
     *   - Submits response_default value (or 'no' for yes_no, '' for others)
     *   - Notification is dismissed same as a normal response
     */
    cancelActionRequired( notificationId ) {
        this.log( `🔴 cancelActionRequired CALLED at ${Date.now()} for ${notificationId}` );
        const state = this.actionRequiredNotifications.get( notificationId );
        if ( !state ) {
            this.log( `cancelActionRequired: Notification ${notificationId} not found` );
            return;
        }

        if ( state.isResponded ) {
            this.log( `cancelActionRequired: Notification ${notificationId} already responded — performing UI cleanup` );

            // Response already sent (e.g., by another session via WebSocket)
            // but cleanup hasn't fired yet. Force immediate cleanup.
            const card = document.getElementById( `action-required-${notificationId}` );
            if ( card ) card.remove();

            const minimized = document.getElementById( `action-required-minimized-${notificationId}` );
            if ( minimized ) minimized.remove();

            // Cleanup action-required state (idempotent — safe if already deleted)
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

            return;
        }

        const notification = state.notification;
        let defaultValue = notification.response_default;

        // Fallback defaults based on response type
        if ( defaultValue === undefined || defaultValue === null ) {
            if ( notification.response_type === 'yes_no' ) {
                defaultValue = 'no';
            } else if ( notification.response_type === 'multiple_choice' || notification.response_type === 'open_ended_batch' ) {
                // For multiple choice and batch, return a cancelled/timeout response structure
                defaultValue = JSON.stringify( { cancelled: true, answers: {} } );
            } else {
                defaultValue = '[cancelled]';
            }
        }

        this.log( `cancelActionRequired: Cancelling ${notificationId} with default value: "${defaultValue}"` );

        // Submit the default value
        this.submitResponse( notificationId, defaultValue );
    }

    /**
     * Updates the pause button icon and title.
     * @param {string} notificationId - Notification ID
     * @param {boolean} isPaused - True if paused
     */
    updatePauseButtonUI( notificationId, isPaused ) {
        const btn = document.getElementById( `pause-btn-${notificationId}` );
        if ( !btn ) return;

        if ( isPaused ) {
            btn.textContent = '\u25B6\uFE0F';  // ▶️ Play icon
            btn.title = 'Resume timer and audio (P)';
            btn.classList.add( 'paused' );
        } else {
            btn.textContent = '\u23F8\uFE0F';  // ⏸️ Pause icon
            btn.title = 'Pause timer and audio (P)';
            btn.classList.remove( 'paused' );
        }
    }

    /**
     * Updates the timer display styling when paused.
     * @param {string} notificationId - Notification ID
     * @param {boolean} isPaused - True if paused
     */
    updatePausedTimerDisplay( notificationId, isPaused ) {
        const timer = document.getElementById( `timer-${notificationId}` );
        const progress = document.querySelector( `#action-required-card-${notificationId} .action-required-progress-fill` );
        const card = document.getElementById( `action-required-card-${notificationId}` );

        if ( isPaused ) {
            if ( timer ) timer.classList.add( 'paused' );
            if ( progress ) progress.classList.add( 'paused' );
            if ( card ) card.classList.add( 'paused' );
        } else {
            if ( timer ) timer.classList.remove( 'paused' );
            if ( progress ) progress.classList.remove( 'paused' );
            if ( card ) card.classList.remove( 'paused' );
        }
    }

    /**
     * Shows or hides the grace period message.
     * @param {string} notificationId - Notification ID
     * @param {boolean} show - True to show, false to hide
     */
    showGracePeriodMessage( notificationId, show ) {
        const msgId = `grace-period-msg-${notificationId}`;
        let msg = document.getElementById( msgId );

        if ( show ) {
            // Create message if doesn't exist
            if ( !msg ) {
                const card = document.getElementById( `action-required-${notificationId}` );
                if ( card ) {
                    msg = document.createElement( 'div' );
                    msg.id = msgId;
                    msg.className = 'grace-period-message';
                    msg.innerHTML = '\u23F8\uFE0F Paused \u2013 5-minute grace period added';
                    // Insert after header
                    const header = card.querySelector( '.action-required-header' );
                    if ( header && header.nextSibling ) {
                        card.insertBefore( msg, header.nextSibling );
                    } else {
                        card.appendChild( msg );
                    }
                }
            }
            if ( msg ) msg.style.display = 'block';
        } else {
            if ( msg ) msg.style.display = 'none';
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
     * Get today's date string in YYYY-MM-DD format, resolved to appTimezone.
     * @returns {string} - ISO date string in appTimezone
     */
    getTodayDateString() {
        return this.getLocalDateDisplay();
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
        } else if ( notification.response_type === 'multiple_choice' || notification.response_type === 'open_ended_batch' ) {
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
     * Route a completed response-required notification to the correct UI container.
     *
     * When notification has job_id: routes to job card's interactions area.
     * When no job_id: routes to sender card's conversation history.
     *
     * @param {Object} notification - The original notification object
     * @param {string} response - The user's response text
     * @param {boolean} wasExpired - Whether the notification expired (default used)
     * @param {string|null} serverTimeDisplay - Server time string for display
     * @param {string|null} serverDateDisplay - Server date string for display
     */
    routeCompletedNotification( notification, response, wasExpired = false, serverTimeDisplay = null, serverDateDisplay = null ) {
        const jobId = notification.job_id;

        if ( jobId ) {
            const contentEl = document.getElementById( `interactions-content-${jobId}` );
            if ( contentEl ) {
                // Route to job card: append Q (original notification) then A (response)
                this.appendNotificationToJobCard( jobId, notification );

                const responseMessage = wasExpired
                    ? `[Default: ${response}]`
                    : ( notification.response_type === 'multiple_choice' || notification.response_type === 'open_ended_batch' )
                        ? this.formatMultipleChoiceResponse( response )
                        : response;

                const responseNotif = {
                    message   : `↳ ${responseMessage}`,
                    priority  : 'low',
                    timestamp : new Date().toISOString()
                };
                this.appendNotificationToJobCard( jobId, responseNotif );

                // Scroll job card into view
                const jobCard = document.getElementById( `job-card-${jobId}` );
                if ( jobCard ) {
                    jobCard.scrollIntoView( { behavior: 'smooth', block: 'start' } );
                }
                return;
            }
            // Fall through to sender card if job card not found
        }

        // Default: route to sender card
        const senderId = notification.sender_id || this.UNKNOWN_SENDER;
        this.addConversationPair( senderId, notification, response, wasExpired, serverTimeDisplay, serverDateDisplay );
    }

    /**
     * Move a sender card to the top of the notifications list.
     * Respects the pinned conversation-mode card if one exists — non-pinned
     * cards land at position 1 instead of 0 in that case.
     * @param {string} senderId - Sender ID
     */
    moveSenderCardToTop( senderId ) {
        // Synchronize the strip's recency ordering with the stack's
        // recency ordering: leftmost icon = most recently updated. Also
        // bumps the unread badge for non-focused sessions when focus is on.
        this._promoteStripIcon( senderId );

        const container = document.getElementById( 'notifications-list' );
        const cardId = `sender-card-${senderId.replace( /[@.#]/g, '-' )}`;
        const card = document.getElementById( cardId );

        if ( !container || !card ) return;

        const pinned = container.querySelector( '.sender-card[data-pinned-conv-mode="true"]' );
        if ( pinned && pinned !== card ) {
            const target = pinned.nextSibling;
            if ( target !== card ) {
                container.insertBefore( card, target );
            }
            return;
        }

        if ( container.firstChild !== card ) {
            container.insertBefore( card, container.firstChild );
        }
    }

    attachKeyboardListener() {
        if ( this.keyboardListenerActive ) return;

        // keypress for Y/N/C/P shortcuts
        document.addEventListener( 'keypress', ( e ) => {
            // Only respond if there's an active action-required notification
            if ( this.actionRequiredNotifications.size === 0 ) return;

            // Don't intercept keys when user is typing in an input field
            const activeEl = document.activeElement;
            if ( activeEl?.tagName === 'INPUT' || activeEl?.tagName === 'TEXTAREA' ) return;

            // P key - toggle pause (works for all response types)
            if ( e.key.toLowerCase() === 'p' && this.activeActionRequiredId ) {
                e.preventDefault();
                this.togglePause();
                return;
            }

            // Get first (oldest) notification
            const firstId = this.actionRequiredNotifications.keys().next().value;
            const state = this.actionRequiredNotifications.get( firstId );
            if ( !state || state.isResponded ) return;

            // Only for yes/no type
            if ( state.notification.response_type !== 'yes_no' ) return;

            // C key - toggle comment field
            if ( e.key.toLowerCase() === 'c' ) {
                e.preventDefault();
                this.toggleYesNoComment( firstId );
                return;
            }

            // Check key
            if ( e.key.toLowerCase() === 'y' ) {
                this.submitYesNoWithComment( firstId, 'yes' );
            } else if ( e.key.toLowerCase() === 'n' ) {
                this.submitYesNoWithComment( firstId, 'no' );
            }
        } );

        // keydown for Escape (keypress doesn't fire for Escape in many browsers)
        document.addEventListener( 'keydown', ( e ) => {
            if ( e.key === 'Escape' && this.activeActionRequiredId ) {
                // Don't cancel if user is in a text input (let them escape from recording instead)
                const activeElement = document.activeElement;
                const isInInput = activeElement?.tagName === 'INPUT' || activeElement?.tagName === 'TEXTAREA';
                if ( isInInput ) return;

                e.preventDefault();
                this.cancelActionRequired( this.activeActionRequiredId );
            }
        } );

        this.keyboardListenerActive = true;
        this.log( "Keyboard listener attached for Yes/No/Pause/Escape shortcuts" );
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
     * Toggles the expandable comment field for a yes/no notification.
     * Focuses the text input after expand transition.
     */
    toggleYesNoComment( notificationId ) {
        const container = document.getElementById( `yn-comment-container-${notificationId}` );
        if ( !container ) return;

        container.classList.toggle( 'expanded' );

        // Focus input after expand transition
        if ( container.classList.contains( 'expanded' ) ) {
            setTimeout( () => {
                const input = document.getElementById( `yn-comment-input-${notificationId}` );
                if ( input ) input.focus();
            }, 300 );
        }
    }

    /**
     * Submits a yes/no response with an optional comment annotation.
     *
     * If the comment input contains text, the response is annotated:
     *   "yes [comment: user text here]"
     * Otherwise the plain response is submitted: "yes" or "no"
     */
    submitYesNoWithComment( notificationId, response ) {
        const input = document.getElementById( `yn-comment-input-${notificationId}` );
        const comment = input ? input.value.trim() : '';

        if ( comment.length > 0 ) {
            response = `${response} [comment: ${comment}]`;
        }

        this.submitResponse( notificationId, response );
    }

    /**
     * Starts voice input for the comment field in a yes/no notification.
     * Follows the same RecordingManager pattern as open-ended and multiple-choice voice input.
     */
    async startYesNoCommentVoiceInput( notificationId ) {
        this.log( `Starting voice input for yes/no comment field: ${notificationId}` );

        const card = document.getElementById( `action-required-${notificationId}` );
        const micButton = card?.querySelector( '.yes-no-comment-mic' );
        const textInput = document.getElementById( `yn-comment-input-${notificationId}` );

        if ( !micButton || !textInput ) {
            this.error( `Voice input: Could not find yes/no comment UI elements for ${notificationId}` );
            return;
        }

        // Toggle recording state using unified RecordingManager
        if ( this.recordingManager.isRecording() ) {
            await this.recordingManager.stopRecording();
        } else if ( !this.recordingManager.isProcessing() ) {
            await this.recordingManager.startRecording( `yn-comment-${notificationId}`, micButton, textInput );
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
        if ( !this.currentUserEmail ) {
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
        if ( !this.currentUserEmail ) {
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