# WebSocket Configuration Guide

**Date**: 2025.08.13  
**Purpose**: Comprehensive guide to all WebSocket configuration options in the Lupin system  
**Status**: Active  

## Configuration Hierarchy

Configuration values are resolved in the following priority order (highest to lowest):

1. **Environment Variables** (highest priority)
2. **lupin-app.ini** configuration file  
3. **Default values** (lowest priority)

### Environment Variable Override
Any configuration key can be overridden by setting an environment variable:
```bash
# Override websocket_enabled setting
export WEBSOCKET_ENABLED=false

# Override heartbeat interval
export WEBSOCKET_HEARTBEAT_INTERVAL=45
```

---

## WebSocket Configuration Keys

### Core WebSocket Settings

#### `websocket_enabled`
- **Type**: Boolean  
- **Default**: `true`  
- **Purpose**: Enable/disable all WebSocket functionality
- **Environment Variable**: `WEBSOCKET_ENABLED`

```ini
# Enable WebSocket connections
websocket_enabled = true
```

### Connection Management

#### `websocket_heartbeat_interval`
- **Type**: Integer (seconds)  
- **Default**: `30`  
- **Purpose**: Interval between server ping messages to clients
- **Environment Variable**: `WEBSOCKET_HEARTBEAT_INTERVAL`

```ini
# Send ping every 30 seconds
websocket_heartbeat_interval = 30
```

#### `websocket_cleanup_interval`
- **Type**: Integer (seconds)  
- **Default**: `3600` (1 hour)  
- **Purpose**: How often to clean up stale WebSocket sessions
- **Environment Variable**: `WEBSOCKET_CLEANUP_INTERVAL`

```ini
# Clean up stale sessions every hour
websocket_cleanup_interval = 3600
```

#### `websocket_max_connections_per_user`
- **Type**: Integer  
- **Default**: `5`  
- **Purpose**: Maximum WebSocket connections allowed per user (supports multiple tabs)
- **Environment Variable**: `WEBSOCKET_MAX_CONNECTIONS_PER_USER`

```ini
# Allow up to 5 connections per user
websocket_max_connections_per_user = 5
```

#### `websocket_single_session_policy`
- **Type**: Boolean  
- **Default**: `false`  
- **Purpose**: If true, only allow one session per user (disconnects previous sessions)
- **Environment Variable**: `WEBSOCKET_SINGLE_SESSION_POLICY`

```ini
# Allow multiple sessions per user
websocket_single_session_policy = false
```

### Event Configuration

#### `websocket_available_events`
- **Type**: Comma-separated string  
- **Default**: See complete list below  
- **Purpose**: Defines which events can be emitted/subscribed to
- **Environment Variable**: `WEBSOCKET_AVAILABLE_EVENTS`

```ini
# Complete list of available events
websocket_available_events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, tts_job_request, audio_streaming_chunk, notification_queue_update, notification_play_sound, sys_time_update, sys_ping, sys_pong, auth_request, auth_success, auth_error, connect, audio_streaming_status, audio_streaming_complete, update_subscriptions, subscription_update
```

---

## Configuration Examples

### Development Configuration
```ini
[DEFAULT]
# Enable debug mode for faster testing
app_debug = true

# WebSocket settings for development
websocket_enabled = true
websocket_heartbeat_interval = 10          # Faster pings for testing
websocket_cleanup_interval = 300           # Clean up every 5 minutes
websocket_max_connections_per_user = 10    # Allow more connections for testing
websocket_single_session_policy = false    # Multiple tabs for development

# Faster time updates in debug mode (handled in code)
```

### Production Configuration
```ini
[DEFAULT]
# Production mode
app_debug = false

# WebSocket settings for production
websocket_enabled = true
websocket_heartbeat_interval = 30          # Standard ping interval
websocket_cleanup_interval = 3600          # Clean up every hour
websocket_max_connections_per_user = 3     # Conservative connection limit
websocket_single_session_policy = true     # One session per user

# Standard time updates (60 seconds)
```

### High-Performance Configuration
```ini
[DEFAULT]
# Optimized for high load
websocket_enabled = true
websocket_heartbeat_interval = 60          # Reduce ping frequency
websocket_cleanup_interval = 7200          # Clean up every 2 hours
websocket_max_connections_per_user = 2     # Limit connections
websocket_single_session_policy = true     # Enforce single session

# Minimal event set for performance
websocket_available_events = queue_todo_update, queue_done_update, sys_ping, auth_request, auth_success
```

### Testing Configuration
```ini
[DEFAULT]
# Configuration for automated testing
app_debug = true
websocket_enabled = true
websocket_heartbeat_interval = 5           # Fast pings for test validation
websocket_cleanup_interval = 60            # Rapid cleanup for test isolation
websocket_max_connections_per_user = 50    # High limit for load testing
websocket_single_session_policy = false    # Allow multiple test connections

# All events available for comprehensive testing
websocket_available_events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, tts_job_request, audio_streaming_chunk, notification_queue_update, notification_play_sound, sys_time_update, sys_ping, sys_pong, auth_request, auth_success, auth_error, connect, audio_streaming_status, audio_streaming_complete, update_subscriptions, subscription_update
```

---

## Event Categories and Configuration

### Queue Management Events
**Required for**: Main queue interface functionality
```ini
# Minimum events for queue interface
websocket_available_events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, sys_ping, auth_request, auth_success, connect
```

### Audio/TTS Events  
**Required for**: Text-to-speech and audio streaming
```ini
# Minimum events for audio functionality
websocket_available_events = audio_streaming_chunk, audio_streaming_status, audio_streaming_complete, tts_job_request, sys_ping, auth_request, auth_success, connect
```

### Notification Events
**Required for**: User notifications and alerts
```ini
# Minimum events for notifications
websocket_available_events = notification_queue_update, notification_play_sound, sys_ping, auth_request, auth_success, connect
```

### System Events
**Required for**: Basic system functionality
```ini
# Minimum system events (always recommended)
websocket_available_events = sys_ping, sys_pong, auth_request, auth_success, auth_error, connect
```

---

## Configuration Validation

### Required Configuration Keys
The following keys must be present for WebSocket functionality:
- `websocket_enabled`
- `websocket_available_events`

### Validation Rules
1. **websocket_heartbeat_interval**: Must be > 0 and < 300 seconds
2. **websocket_cleanup_interval**: Must be > 60 seconds  
3. **websocket_max_connections_per_user**: Must be > 0 and < 100
4. **websocket_available_events**: Must include at minimum: `sys_ping`, `auth_request`, `auth_success`

### Configuration Validation Script
```bash
# Validate WebSocket configuration
curl "http://localhost:7999/api/config/websocket" \
     -H "Authorization: Bearer mock_token_email_user@example.com"
```

---

## Runtime Configuration Changes

### Dynamic Configuration Updates
Some configuration can be updated at runtime via API:

#### Update Single Session Policy
```bash
curl -X PUT "http://localhost:7999/api/websocket-sessions/single-session-policy" \
     -H "Authorization: Bearer mock_token_email_user@example.com" \
     -H "Content-Type: application/json" \
     -d '{"enabled": true}'
```

#### Trigger Manual Cleanup
```bash
curl -X POST "http://localhost:7999/api/websocket-sessions/cleanup" \
     -H "Authorization: Bearer mock_token_email_user@example.com" \
     -d "max_age_hours=1"
```

### Configuration Reloading
Most configuration changes require server restart. The following can be changed at runtime:
- `websocket_single_session_policy` (via API)
- Session cleanup triggers (via API)

---

## Environment-Specific Settings

### Docker Configuration
```dockerfile
# Docker environment variables
ENV WEBSOCKET_ENABLED=true
ENV WEBSOCKET_HEARTBEAT_INTERVAL=30
ENV WEBSOCKET_MAX_CONNECTIONS_PER_USER=3
```

### Kubernetes Configuration
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: lupin-websocket-config
data:
  WEBSOCKET_ENABLED: "true"
  WEBSOCKET_HEARTBEAT_INTERVAL: "30"
  WEBSOCKET_CLEANUP_INTERVAL: "3600"
  WEBSOCKET_MAX_CONNECTIONS_PER_USER: "5"
```

### Development .env File
```bash
# .env file for development
WEBSOCKET_ENABLED=true
WEBSOCKET_HEARTBEAT_INTERVAL=10
WEBSOCKET_CLEANUP_INTERVAL=300
WEBSOCKET_MAX_CONNECTIONS_PER_USER=10
WEBSOCKET_SINGLE_SESSION_POLICY=false
```

---

## Troubleshooting Configuration Issues

### Common Configuration Problems

#### WebSocket Connections Fail
**Check**: 
- `websocket_enabled = true`
- Server is running on correct port (7999)
- Firewall allows WebSocket connections

#### No Events Received
**Check**:
- `websocket_available_events` includes required events
- Event names match exactly (case-sensitive)
- Client subscription list matches available events

#### Frequent Disconnections
**Check**:
- `websocket_heartbeat_interval` not too aggressive (< 10 seconds)
- `websocket_cleanup_interval` appropriate for usage pattern
- Network stability and proxy configuration

#### Session Conflicts
**Check**:
- `websocket_single_session_policy` setting
- `websocket_max_connections_per_user` limit
- Client session ID management

### Debug Configuration Commands
```bash
# View current configuration
curl "http://localhost:7999/api/config" \
     -H "Authorization: Bearer mock_token_email_user@example.com"

# Check WebSocket-specific settings  
curl "http://localhost:7999/api/websocket-sessions/stats" \
     -H "Authorization: Bearer mock_token_email_user@example.com"

# View available events
curl "http://localhost:7999/api/websocket-events" \
     -H "Authorization: Bearer mock_token_email_user@example.com"
```

---

## Performance Tuning

### High-Load Optimization
```ini
# Optimize for high concurrent usage
websocket_heartbeat_interval = 60          # Reduce server load
websocket_cleanup_interval = 7200          # Less frequent cleanup
websocket_max_connections_per_user = 2     # Limit connections
websocket_single_session_policy = true     # Reduce memory usage

# Limit events to essential only
websocket_available_events = queue_todo_update, queue_done_update, sys_ping, auth_request, auth_success
```

### Low-Resource Optimization
```ini
# Optimize for limited server resources
websocket_heartbeat_interval = 120         # Very infrequent pings
websocket_cleanup_interval = 1800          # Aggressive cleanup
websocket_max_connections_per_user = 1     # Single connection only
websocket_single_session_policy = true     # Enforce single session

# Minimal event set
websocket_available_events = queue_todo_update, sys_ping, auth_request, auth_success
```

### Development Optimization
```ini
# Optimize for development/testing
websocket_heartbeat_interval = 5           # Fast feedback
websocket_cleanup_interval = 60            # Quick cleanup for testing
websocket_max_connections_per_user = 50    # High limit for testing
websocket_single_session_policy = false    # Multiple tabs/connections

# All events for full feature testing
websocket_available_events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, tts_job_request, audio_streaming_chunk, notification_queue_update, notification_play_sound, sys_time_update, sys_ping, sys_pong, auth_request, auth_success, auth_error, connect, audio_streaming_status, audio_streaming_complete, update_subscriptions, subscription_update
```

---

## Configuration Examples by Use Case

### Single-User Development
```ini
[DEFAULT]
app_debug = true
websocket_enabled = true
websocket_heartbeat_interval = 10
websocket_cleanup_interval = 300
websocket_max_connections_per_user = 10
websocket_single_session_policy = false
```

### Multi-User Production  
```ini
[DEFAULT]
app_debug = false
websocket_enabled = true
websocket_heartbeat_interval = 30
websocket_cleanup_interval = 3600
websocket_max_connections_per_user = 3
websocket_single_session_policy = true
```

### Audio-Only Application
```ini
[DEFAULT]
websocket_enabled = true
websocket_heartbeat_interval = 30
websocket_cleanup_interval = 3600
websocket_max_connections_per_user = 2
websocket_single_session_policy = false

# Audio events only
websocket_available_events = audio_streaming_chunk, audio_streaming_status, audio_streaming_complete, sys_ping, auth_request, auth_success, connect
```

### Queue-Only Application
```ini
[DEFAULT]
websocket_enabled = true
websocket_heartbeat_interval = 30
websocket_cleanup_interval = 3600
websocket_max_connections_per_user = 2
websocket_single_session_policy = false

# Queue events only
websocket_available_events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, sys_ping, auth_request, auth_success, connect
```

---

## Related Documentation

- **[WebSocket Architecture Overview](websocket-architecture.md)** - Complete system design and architectural patterns
- **[WebSocket Events Documentation](websocket-events.md)** - Comprehensive guide to all WebSocket events
- **[WebSocket Troubleshooting Guide](websocket-troubleshooting.md)** - Common issues, solutions, and debugging procedures
- **[Main README](../../README.md)** - Project overview and quick start guide

---

*Last updated: 2025.08.13*