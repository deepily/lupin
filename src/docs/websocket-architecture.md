# WebSocket Architecture Overview

**Date**: 2025.08.13  
**Purpose**: Comprehensive architectural documentation for the Lupin WebSocket system  
**Status**: Active  

## Executive Summary

The Lupin WebSocket architecture provides real-time bidirectional communication between the FastAPI server and client applications. The system employs a dual-session design with user-centric routing, event subscription filtering, and robust connection management.

### Key Architectural Principles
- **User-Centric Routing**: Events route by user ID, not ephemeral WebSocket connection ID
- **Event Subscription Filtering**: Clients only receive events they explicitly subscribe to
- **Dual-Session Architecture**: Separate channels for queue management and audio streaming
- **Graceful Degradation**: HTTP polling fallback when WebSocket connections fail
- **Session Persistence**: localStorage-based session management across page reloads

---

## System Architecture

### High-Level Data Flow
```
┌─────────────────┐    WebSocket     ┌──────────────────┐    Events     ┌─────────────────┐
│   Client Apps   │ ←─────────────→  │  WebSocket       │ ←──────────   │   Background    │
│                 │                  │  Manager         │               │   Processes     │
│ • queue.js      │                  │                  │               │                 │
│ • hybrid-tts.js │                  │ • User routing   │               │ • Job queue     │
│ • queue-fresh   │                  │ • Event filtering│               │ • TTS streaming │
└─────────────────┘                  │ • Session mgmt   │               │ • Notifications │
                                     └──────────────────┘               └─────────────────┘
```

### Core Components

#### 1. WebSocketManager (`src/cosa/rest/websocket_manager.py`)
**Purpose**: Central hub for all WebSocket connection and event management

**Responsibilities**:
- User session lifecycle management
- Event routing and filtering
- Connection health monitoring
- Authentication validation
- Subscription management

**Key Methods**:
```python
async def emit_to_user(user_id, event_type, data)
async def handle_auth_request(websocket, auth_data)
def update_subscriptions(session_id, events, action)
def cleanup_stale_sessions(max_age_hours)
```

#### 2. WebSocket Routers (`src/cosa/rest/routers/websocket.py`)
**Purpose**: FastAPI endpoints for WebSocket connections

**Endpoints**:
- `/ws/queue/{session_id}` - Main application WebSocket
- `/ws/audio/{session_id}` - Audio-only WebSocket for TTS streaming

**Authentication Flow**:
```
Client Connect → Send auth_request → Server Validates → auth_success/auth_error
```

#### 3. Event Emission System (`src/fastapi_app/main.py`)
**Purpose**: Background processes that generate WebSocket events

**Event Sources**:
- **Job Queue Changes**: Todo/Running/Done/Dead count updates
- **TTS Streaming**: Audio chunk delivery and status updates  
- **Notifications**: User alerts and system messages
- **System Events**: Clock updates, heartbeat pings

---

## Dual-Session Architecture

### Session Types

#### Queue Session (`/ws/queue/{session_id}`)
**Purpose**: Primary application interface for authenticated users

**Events Received**:
- Queue state changes (`queue_todo_update`, `queue_running_update`, etc.)
- Job completion notifications (`tts_job_request`)
- User notifications (`notification_queue_update`)
- System events (`sys_time_update`, `sys_ping`)

**Authentication**: Required - first message must be `auth_request`

**Subscription Model**: Configurable - client specifies desired events

#### Audio Session (`/ws/audio/{session_id}`)
**Purpose**: Dedicated channel for TTS audio streaming

**Events Received**:
- Audio streaming data (`audio_streaming_chunk`)
- Audio status updates (`audio_streaming_status`, `audio_streaming_complete`)
- Basic system events (`sys_ping`, `auth_success`)

**Authentication**: Optional - can pre-register via TTS API request

**Subscription Model**: Fixed - audio events only

### Session Relationship
```
User "ricardo.felipe.ruiz@gmail.com"
├── Queue Session: "wise_penguin"
│   ├── Subscriptions: [queue_*, notification_*, sys_*]
│   └── Purpose: Main UI interaction
└── Audio Session: "wise_penguin_audio"  
    ├── Subscriptions: [audio_*, sys_ping]
    └── Purpose: TTS streaming only
```

---

## User-Centric Routing

### Traditional vs Lupin Approach

#### Traditional WebSocket Routing (Problems)
```python
# Route by WebSocket connection ID (ephemeral)
websocket_id = "conn_12345"
emit_to_connection(websocket_id, event_data)

# Issues:
# - Connection IDs change on reconnect
# - Can't route to user across sessions
# - Difficult to handle multiple tabs
```

#### Lupin User-Centric Routing (Solution)
```python
# Route by stable user ID
user_id = email_to_system_id("ricardo.felipe.ruiz@gmail.com") 
emit_to_user(user_id, event_type, event_data)

# Benefits:
# - Survives reconnections
# - Works across multiple tabs
# - Enables persistent user state
```

### User ID Generation
```python
def email_to_system_id(email):
    """
    Convert email to consistent system user ID.
    
    Examples:
    "ricardo.felipe.ruiz@gmail.com" → "user_ricardo_felipe_ruiz_gmail_com"
    "test@example.com" → "user_test_example_com"
    """
    clean_email = email.replace("@", "_").replace(".", "_")
    return f"user_{clean_email}"
```

---

## Event Subscription System

### Subscription Filtering Benefits
- **Performance**: Clients only process relevant events
- **Security**: Prevents information leakage between users
- **Flexibility**: Different clients can have different event needs
- **Scalability**: Reduces network traffic and processing load

### Subscription Configuration

#### Static Subscriptions (Configured at Connection)
```javascript
// Queue interface subscriptions
const queueSubscriptions = [
    "queue_todo_update",
    "queue_running_update", 
    "queue_done_update",
    "queue_dead_update",
    "tts_job_request",
    "sys_time_update",
    "notification_queue_update",
    "sys_ping"
];

// Audio interface subscriptions  
const audioSubscriptions = [
    "audio_streaming_chunk",
    "audio_streaming_status",
    "audio_streaming_complete",
    "sys_ping"
];
```

#### Dynamic Subscription Updates
```javascript
// Add new event subscription
websocket.send(JSON.stringify({
    "type": "update_subscriptions",
    "events": ["new_event_type"],
    "action": "add"
}));

// Replace all subscriptions
websocket.send(JSON.stringify({
    "type": "update_subscriptions", 
    "events": ["event1", "event2"],
    "action": "replace"
}));
```

### Server-Side Filtering
```python
def emit_to_user(self, user_id, event_type, data):
    """Only emit event if user is subscribed to event_type"""
    for session_id, session_info in self.user_sessions.get(user_id, {}).items():
        if event_type in session_info.get("subscribed_events", []):
            await session_info["websocket"].send_text(json.dumps(data))
```

---

## Session Management Lifecycle

### Session Creation Flow
```
1. Client connects to WebSocket endpoint
2. Server generates connection and waits for auth
3. Client sends auth_request with session_id and subscriptions
4. Server validates token and session_id format
5. Server maps session to user_id
6. Server stores session info with subscriptions
7. Server responds with auth_success
8. Session is active and ready for events
```

### Session Persistence Strategy
```javascript
// Client-side session management
function getOrCreateSession() {
    let sessionId = localStorage.getItem("session_id");
    
    if (!sessionId || !isValidSessionFormat(sessionId)) {
        sessionId = generateSessionId(); // "wise_penguin" format
        localStorage.setItem("session_id", sessionId);
    }
    
    return sessionId;
}

function isValidSessionFormat(sessionId) {
    // Must be "adjective_noun" format
    return /^[a-z]+_[a-z]+$/.test(sessionId);
}
```

### Session Cleanup Policies
```python
# Automatic cleanup triggers
CLEANUP_TRIGGERS = {
    "stale_sessions": 24,      # Hours of inactivity
    "dead_connections": 5,     # Minutes of no heartbeat
    "invalid_auth": 0,         # Immediate cleanup
    "duplicate_sessions": 0    # When single-session policy enabled
}

# Manual cleanup endpoint
POST /api/websocket-sessions/cleanup?max_age_hours=1
```

---

## Authentication and Security

### Authentication Flow
```
┌─────────┐              ┌─────────────┐              ┌──────────────┐
│ Client  │              │ WebSocket   │              │ Auth System  │
│         │              │ Router      │              │              │
├─────────┤              ├─────────────┤              ├──────────────┤
│ Connect │ ────────────▶│ Accept      │              │              │
│         │              │ Connection  │              │              │
│         │              │             │              │              │
│ Send    │              │ Receive     │              │              │
│ auth_   │ ────────────▶│ auth_       │ ────────────▶│ Validate     │
│ request │              │ request     │              │ Token        │
│         │              │             │              │              │
│ Receive │              │ Send        │              │ Return       │
│ auth_   │ ◀────────────│ auth_       │ ◀────────────│ User Info    │
│ success │              │ success     │              │              │
└─────────┘              └─────────────┘              └──────────────┘
```

### Token Format and Validation
```python
# Expected token format
"Bearer mock_token_email_user@example.com"

# Server validation
def validate_websocket_token(token):
    if not token.startswith("Bearer mock_token_email_"):
        return None
    
    email = token.replace("Bearer mock_token_email_", "")
    user_id = email_to_system_id(email)
    return {"user_id": user_id, "email": email}
```

### Security Considerations
- **User Isolation**: Events only route to intended users
- **Session Validation**: Session IDs must match expected format
- **Token Consistency**: Same user must use same token across sessions
- **Event Filtering**: Subscription-based access control
- **Rate Limiting**: Heartbeat system prevents resource exhaustion

---

## Connection Management

### Connection Health Monitoring
```python
# Heartbeat system
HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 90   # seconds

# Server sends sys_ping every 30s
# Client should respond with sys_pong
# Connections without pong for 90s are cleaned up
```

### Reconnection Strategy
```javascript
// Client-side exponential backoff
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const INITIAL_RETRY_DELAY = 1000;    // 1 second
const MAX_RETRY_DELAY = 30000;       // 30 seconds

function calculateRetryDelay(attempt) {
    const delay = INITIAL_RETRY_DELAY * Math.pow(2, attempt);
    return Math.min(delay, MAX_RETRY_DELAY);
}

function reconnectWebSocket() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.log("Max reconnection attempts reached, falling back to HTTP polling");
        startHttpPolling();
        return;
    }
    
    const delay = calculateRetryDelay(reconnectAttempts);
    setTimeout(connectWebSocket, delay);
    reconnectAttempts++;
}
```

### Graceful Degradation
```javascript
// HTTP polling fallback when WebSocket fails
function startHttpPolling() {
    setInterval(async () => {
        try {
            const response = await fetch('/api/queue/status');
            const data = await response.json();
            updateQueueDisplay(data);
        } catch (error) {
            console.error("HTTP polling failed:", error);
        }
    }, 5000); // Poll every 5 seconds
}
```

---

## Event Processing Pipeline

### Server-Side Event Generation
```python
# Background process generates event
job_completed = True
if job_completed:
    event_data = {
        "type": "queue_todo_update", 
        "value": get_todo_count(),
        "timestamp": datetime.now().isoformat()
    }
    
    # Route to all users subscribed to queue events
    await websocket_manager.emit_to_all_users("queue_todo_update", event_data)
```

### Client-Side Event Processing
```javascript
// Event reception and routing
websocket.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    // Log for debugging
    if (debug) console.log("[WS] Received:", data.type, data);
    
    // Route to appropriate handler
    const handler = eventHandlers[data.type];
    if (handler) {
        handler(data);
    } else {
        console.warn("No handler for event type:", data.type);
    }
};

// Event handler registration
const eventHandlers = {
    "queue_todo_update": handleQueueUpdate,
    "tts_job_request": handleSpeechUpdate,
    "sys_ping": handlePing,
    "auth_success": handleAuthSuccess
};
```

---

## Performance Considerations

### Event Frequency Management
```python
# Production vs Debug event timing
if app_debug:
    CLOCK_UPDATE_INTERVAL = 5    # seconds (for testing)
else:
    CLOCK_UPDATE_INTERVAL = 60   # seconds (production)
```

### Connection Scaling
```python
# Current capacity planning
MAX_CONNECTIONS_PER_USER = 5    # Multiple tabs support
MAX_TOTAL_CONNECTIONS = 1000    # Server capacity limit
CONNECTION_CLEANUP_INTERVAL = 3600  # 1 hour

# Memory usage optimization
SESSION_DATA_TTL = 86400        # 24 hours
MAX_MESSAGE_QUEUE_SIZE = 100    # Per connection
```

### Client-Side Performance
```javascript
// Debounce rapid UI updates
const debouncedQueueUpdate = debounce(updateQueueDisplay, 100);

// Use requestAnimationFrame for smooth UI updates
function updateQueueDisplay(data) {
    requestAnimationFrame(() => {
        document.getElementById("todo").textContent = data.value;
    });
}

// Efficient event handler management
function addEventHandler(eventType, handler) {
    // Remove existing handler to prevent duplicates
    removeEventHandler(eventType);
    eventHandlers[eventType] = handler;
}
```

---

## Error Handling and Recovery

### Error Types and Responses

#### Connection Errors
```javascript
websocket.onerror = function(error) {
    console.error("WebSocket error:", error);
    showConnectionError("Connection lost. Attempting to reconnect...");
    reconnectWebSocket();
};

websocket.onclose = function(event) {
    if (event.code !== 1000) { // Not normal closure
        console.warn("WebSocket closed unexpectedly:", event.code, event.reason);
        reconnectWebSocket();
    }
};
```

#### Authentication Errors
```javascript
function handleAuthError(data) {
    console.error("Authentication failed:", data.message);
    
    // Clear invalid session data
    localStorage.removeItem("session_id");
    
    // Show user-friendly error
    showAuthError("Please refresh the page to reconnect");
    
    // Don't auto-reconnect on auth errors
    stopReconnectionAttempts();
}
```

#### Event Processing Errors
```javascript
function safeEventHandler(handler) {
    return function(data) {
        try {
            handler(data);
        } catch (error) {
            console.error("Event handler error:", error);
            // Continue processing other events
        }
    };
}
```

---

## Configuration Architecture

### Configuration Hierarchy
```
Environment Variables (highest priority)
    ↓
lupin-app.ini (application config)
    ↓
Default values (lowest priority)
```

### WebSocket-Specific Configuration
```ini
# lupin-app.ini WebSocket section
[websocket]
enabled = true
heartbeat_interval = 30
cleanup_interval = 3600
max_connections_per_user = 5
single_session_policy = false

available_events = queue_todo_update, queue_done_update, queue_running_update, 
                  queue_dead_update, tts_job_request, audio_streaming_chunk, 
                  notification_queue_update, sys_time_update, sys_ping, sys_pong, 
                  auth_request, auth_success, auth_error, connect, 
                  audio_streaming_status, audio_streaming_complete
```

### Runtime Configuration Access
```python
# Server-side configuration access
config_mgr = ConfigurationManager(env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS")
heartbeat_interval = config_mgr.get("websocket_heartbeat_interval", default=30)
available_events = config_mgr.get("websocket_available_events", default="").split(", ")
```

---

## Testing and Validation

### Automated Testing Strategy
- **Unit Tests**: Individual WebSocket endpoint connections
- **Integration Tests**: Full event flow from generation to client reception  
- **Load Tests**: Multiple concurrent connections and event throughput
- **Regression Tests**: Smoke test suite for ongoing validation

### Manual Testing Procedures
1. **Basic Connection Test**: Verify WebSocket upgrade succeeds
2. **Authentication Test**: Confirm auth_request → auth_success flow
3. **Event Subscription Test**: Verify only subscribed events are received
4. **Multi-Tab Test**: Confirm user-centric routing works across sessions
5. **Reconnection Test**: Verify graceful reconnection after network interruption

### Debug Tools and Monitoring
```bash
# WebSocket session monitoring
curl "http://localhost:7999/api/websocket-sessions/stats" \
     -H "Authorization: Bearer mock_token_email_user@example.com"

# Connection health check
curl "http://localhost:7999/api/websocket-sessions" \
     -H "Authorization: Bearer mock_token_email_user@example.com"
```

---

## Future Architecture Considerations

### Scalability Enhancements
- **Redis Pub/Sub**: For multi-server WebSocket event distribution
- **Load Balancing**: Sticky sessions for WebSocket connections
- **Microservice Architecture**: Separate WebSocket service from main API

### Security Improvements
- **JWT Token Validation**: Replace simple token with proper JWT
- **Rate Limiting**: Per-user event emission limits
- **Audit Logging**: Complete WebSocket activity logging

### Feature Extensions
- **Message Persistence**: Store events for offline users
- **Custom Event Types**: User-defined event subscriptions
- **Event History**: Replay missed events on reconnection

---

## Related Documentation

- **[WebSocket Events Documentation](websocket-events.md)** - Complete event catalog and payloads
- **[WebSocket Troubleshooting Guide](websocket-troubleshooting.md)** - Common issues and solutions
- **[WebSocket Testing Results](websocket-testing-results.md)** - Validation and testing outcomes
- **[WebSocket Configuration Guide](websocket-configuration.md)** - All configuration options

---

*This document reflects the current architecture as of 2025.08.13. For the most current implementation details, refer to the source code and related documentation.*