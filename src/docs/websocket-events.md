# WebSocket Event System Documentation

**Date**: 2025.07.30  
**Purpose**: Comprehensive documentation of all WebSocket events in the Lupin system  
**Status**: Current - Updated with normalized event names  

## Executive Summary

This document provides a complete catalog of WebSocket events used in the Lupin FastAPI system for real-time communication between the server and client applications. Events are organized by category and include payload structures, usage patterns, and client subscription guidelines.

## Event Categories

### 1. Queue Management Events

These events notify clients about changes to the job queue states.

#### `queue_todo_update`
- **Purpose**: Updates to the TODO queue count
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "queue_todo_update",
    "value": 5,
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: Updates `#todo` element display

#### `queue_running_update`
- **Purpose**: Updates to the RUNNING queue count
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "queue_running_update", 
    "value": 2,
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: Updates `#run` element display and refreshes running job list

#### `queue_done_update`
- **Purpose**: Updates to the DONE queue count
- **Direction**: Server → Client  
- **Payload**:
  ```json
  {
    "type": "queue_done_update",
    "value": 10,
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: Updates `#done` element display and refreshes completed job list

#### `queue_dead_update`
- **Purpose**: Updates to the DEAD queue count
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "queue_dead_update",
    "value": 1,
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: Updates `#dead` element display and refreshes dead job list

### 2. Audio/TTS Events

These events handle text-to-speech and audio streaming functionality.

#### `tts_job_request`
- **Purpose**: Job completion notifications with TTS audio
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "tts_job_request",
    "text": "Your calculation has been completed successfully.",
    "audioURL": "/static/audio/job_complete_123.mp3",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: `handleSpeechUpdate()` - Plays TTS audio via HybridTTS

#### `audio_streaming_status`
- **Purpose**: TTS audio loading/streaming status updates
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "audio_streaming_status",
    "text": "Generating audio...",
    "status": "loading",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: hybrid-tts.js
- **Handler**: Updates status display and manages loading states

#### `audio_streaming_complete`
- **Purpose**: TTS audio streaming completion notification
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "audio_streaming_complete",
    "text": "Audio streaming complete",
    "chunks": 15,
    "duration": 3.2,
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: hybrid-tts.js
- **Handler**: Finalizes audio playback in instant mode or plays collected audio in reliable mode

#### `audio_streaming_chunk`
- **Purpose**: Binary audio data chunks for progressive playback
- **Direction**: Server → Client
- **Payload**: Binary audio data (Blob)
- **Subscribed by**: hybrid-tts.js
- **Handler**: Collects chunks for playback or plays progressively in instant mode

### 3. Notification Events

These events handle user notifications and system alerts.

#### `notification_queue_update`
- **Purpose**: ALL notification updates - handles both queue-based notifications and Claude Code notifications
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "notification_queue_update",
    "notification": {
      "id_hash": "abc123",
      "message": "System update completed",
      "type": "progress",
      "priority": "medium",
      "timestamp": "2025-07-30T10:30:00Z"
    }
  }
  ```
- **Subscribed by**: queue.js, queue-fresh.js  
- **Handler**: `handleNotificationUpdate()` - Plays notification sounds, adds to list, handles TTS for high priority

#### `notification_play_sound`
- **Purpose**: Play notification sound files
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "notification_play_sound",
    "soundFile": "/static/audio/notification-high-priority.mp3",
    "priority": "high",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: `handleNotificationSound()` - Adds sound to audio queue

### 4. System Events

These events handle system-level functionality and maintenance.

#### `sys_time_update`
- **Purpose**: Clock updates for real-time display
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "sys_time_update",
    "date": "2025-07-30 10:30:00 PDT",
    "timestamp": "2025-07-30T17:30:00Z"
  }
  ```
- **Subscribed by**: queue.js
- **Handler**: Updates `#clock` element display

#### `sys_ping`
- **Purpose**: WebSocket heartbeat from server
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "sys_ping",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js, hybrid-tts.js
- **Handler**: Logs ping receipt, maintains connection health

#### `sys_pong`
- **Purpose**: WebSocket heartbeat response
- **Direction**: Client → Server
- **Payload**:
  ```json
  {
    "type": "sys_pong", 
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Used by**: WebSocket heartbeat system

### 5. Authentication Events

These events manage WebSocket authentication and connection lifecycle.

#### `auth_request`
- **Purpose**: Authentication request from client
- **Direction**: Client → Server
- **Payload**:
  ```json
  {
    "type": "auth_request",
    "token": "Bearer mock_token_email_user@example.com",
    "session_id": "wise penguin",
    "subscribed_events": ["queue_todo_update", "audio_streaming_status", ...]
  }
  ```
- **Sent by**: queue.js, hybrid-tts.js connection handlers

#### `auth_success`
- **Purpose**: Authentication successful confirmation
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "auth_success",
    "user_id": "user_12345",
    "session_id": "wise penguin",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js, hybrid-tts.js
- **Handler**: Updates authentication status display

#### `auth_error`
- **Purpose**: Authentication failed notification
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "auth_error",
    "message": "Invalid token provided",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js, hybrid-tts.js
- **Handler**: Displays error status and handles reconnection

#### `connect`
- **Purpose**: WebSocket connection confirmation
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "connect",
    "message": "Queue WebSocket connected for session wise penguin",
    "session_id": "wise penguin",
    "timestamp": "2025-07-30T10:30:00Z"
  }
  ```
- **Subscribed by**: queue.js, hybrid-tts.js
- **Handler**: Confirms successful connection establishment

### 6. Control Events

These events manage WebSocket behavior and subscriptions.

#### `update_subscriptions`
- **Purpose**: Update client event subscriptions
- **Direction**: Client → Server
- **Payload**:
  ```json
  {
    "type": "update_subscriptions",
    "events": ["queue_todo_update", "audio_streaming_status"],
    "action": "replace"
  }
  ```
- **Handler**: `WebSocketManager.update_subscriptions()`

#### `subscription_update`
- **Purpose**: Confirmation of subscription changes
- **Direction**: Server → Client
- **Payload**:
  ```json
  {
    "type": "subscription_update",
    "success": true,
    "subscriptions": ["queue_todo_update", "audio_streaming_status"]
  }
  ```

## Event Subscription Patterns

### Queue Interface Subscriptions
```javascript
const queueSubscriptions = [
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
];
```

### Audio Interface Subscriptions
```javascript
const audioSubscriptions = [
    "audio_streaming_chunk",
    "audio_streaming_status", 
    "audio_streaming_complete",
    "sys_ping",
    "auth_success",
    "auth_error",
    "connect"
];
```

## WebSocket Endpoints

### `/ws/queue/{session_id}`
- **Purpose**: Main application WebSocket for authenticated users
- **Authentication**: Required (first message must be `auth_request`)
- **Subscriptions**: Configurable via `subscribed_events` in auth message
- **Default Events**: All queue, notification, and system events

### `/ws/audio/{session_id}`
- **Purpose**: Audio-only WebSocket for TTS streaming
- **Authentication**: Optional (can pre-register via TTS request)
- **Subscriptions**: Fixed audio-related events only
- **Events**: `audio_streaming_*`, `sys_ping`, `auth_*`, `connect`

## Event Flow Examples

### Job Submission and Completion
```
1. Client submits job via /api/push
2. Server emits queue_todo_update (count increased)
3. Job begins processing
4. Server emits queue_todo_update (count decreased)
5. Server emits queue_running_update (count increased) 
6. Job completes
7. Server emits queue_running_update (count decreased)
8. Server emits queue_done_update (count increased)
9. Server emits tts_job_request (completion notification)
```

### TTS Audio Streaming
```
1. Client requests TTS via /api/get-speech
2. Server emits audio_streaming_status ("loading")
3. Server streams audio_streaming_chunk events (binary data)
4. Client plays chunks progressively (instant mode) or collects (reliable mode)
5. Server emits audio_streaming_complete
6. Client finalizes playback and caches audio
```

### Notification Delivery
```
1. External system sends notification via /api/notify
2. Server stores in NotificationFifoQueue
3. Server emits notification_queue_update to target user
4. Client plays notification sound based on priority
5. Client may play TTS for high priority notifications
6. Client adds notification to UI list
7. Client marks notification as played on server
```

## Configuration

The available events are configured in `lupin-app.ini`:

```ini
websocket available events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, tts_job_request, audio_streaming_chunk, notification_queue_update, notification_play_sound, sys_time_update, sys_ping, sys_pong, auth_request, auth_success, auth_error, connect, audio_streaming_status, audio_streaming_complete, update_subscriptions
```

## Error Handling

All WebSocket implementations include:
- **Connection failure recovery**: Automatic reconnection with exponential backoff (max 10 attempts)
- **Authentication failure handling**: Clear error messages and retry mechanisms  
- **Message validation**: Events not in subscription list are ignored
- **Graceful degradation**: HTTP polling fallback when WebSocket connections fail
- **Input validation**: Comprehensive validation on all WebSocket message handlers and API endpoints
- **User-friendly error messages**: Technical errors converted to actionable user guidance

## Security Considerations

- **Authentication required**: All non-audio endpoints require valid authentication tokens
- **User-based routing**: Events are routed by user ID, not ephemeral WebSocket ID
- **Session validation**: Server validates session ID format and associations
- **Event filtering**: Clients only receive events they are subscribed to
- **Rate limiting**: WebSocket heartbeat and cleanup prevents resource exhaustion

## Migration from Legacy Events

This system replaces the previous Flask-SocketIO implementation. Legacy event names have been normalized:

| Legacy Event | New Event | Notes |
|--------------|-----------|-------|
| `todo_update` | `queue_todo_update` | Prefixed for clarity |
| `speech_update` | `tts_job_request` | More descriptive purpose |
| `user_notification` | `notification_queue_update` | Consolidated into single notification path |
| `time_update` | `sys_time_update` | System event prefix |
| `ping` | `sys_ping` | System event prefix |
| `auth` | `auth_request` | Clarifies direction |

The new event names provide better categorization and clearer intent while maintaining all existing functionality.

## Recent Updates (2025.08.13)

### Code Quality Improvements
- **Magic Numbers Extraction**: Critical timing constants moved to DELAYS object in queue.js
- **Error Handling Standardization**: Consistent logError() function across JavaScript codebase  
- **Input Validation**: Comprehensive validation added to all WebSocket message handlers
- **JSDoc Documentation**: Added to complex JavaScript functions for better maintainability

### Connection Management Enhancements
- **Exponential Backoff**: WebSocket reconnection now uses exponential backoff (1s → 30s max)
- **Connection Limits**: Maximum 10 reconnection attempts before falling back to HTTP polling
- **Graceful Degradation**: Automatic HTTP polling fallback when WebSocket fails
- **Health Monitoring**: Improved connection health tracking and status reporting

### Documentation Updates
- **[Architecture Overview](websocket-architecture.md)**: Complete system design documentation
- **[Troubleshooting Guide](websocket-troubleshooting.md)**: Comprehensive debugging procedures
- **Configuration Guide**: Detailed WebSocket configuration options and examples

For the most current implementation details and architectural patterns, see the complete documentation suite in `/src/docs/`.