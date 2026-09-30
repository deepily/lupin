# WebSocket Troubleshooting Guide

**Date**: 2026.03.20
**Source of truth**: `src/cosa/rest/websocket_manager.py`, `src/cosa/rest/routers/websocket.py`
**Status**: Active

## Quick Diagnostics

### Is WebSocket Working?

1. **Check connection status** in browser dev tools (Network → WS tab)
2. **Look for `auth_success`** message after connection
3. **Verify event reception** by watching for `sys_ping` events (every 30s by default)
4. **Check server health**:
   ```
   GET http://localhost:7999/health
   ```

### Common Error Patterns

| Symptom | Likely Cause |
|---------|-------------|
| Connection refused | Server not running or wrong port (default: 7999) |
| Close code `1008` | Invalid session ID format |
| `auth_error` message | JWT token expired, malformed, or invalid |
| No events received | Wrong subscription list or auth failed silently |
| Events stop arriving | Dead connection not yet detected by heartbeat |

---

## Connection Issues

### Problem: WebSocket Connection Fails

**Symptoms**: "WebSocket connection failed" in console, Network tab shows failed WS connection.

**Solutions**:

1. **Verify server is running** on port 7999
2. **Check endpoint URL**:
   - Queue: `ws://localhost:7999/ws/queue/{session_id}`
   - Audio: `ws://localhost:7999/ws/audio/{session_id}`
3. **Validate session ID format**:
   - Browser: two lowercase words with a space (e.g., `wise penguin`)
   - Programmatic: lowercase with hyphens (e.g., `cc-listener-12345`)
   - URL-encode the space: `ws://localhost:7999/ws/queue/wise%20penguin`
4. **Check for tab/newline characters** in session ID (rejected by validation)

### Problem: WebSocket Closes Immediately After Connect

**Symptoms**: Connection opens, then closes within seconds.

**Causes**:
- `/ws/queue/`: First message was not `auth_request`, or auth failed
- `/ws/audio/`: Less likely — audio accepts without auth. Check server logs for exceptions

---

## Authentication Issues

### Problem: `auth_error` Response

**Diagnosis**: Check the error message in the `auth_error` payload.

| Error Message | Fix |
|---------------|-----|
| `"Authentication message must be valid JSON"` | Ensure first message is parseable JSON |
| `"Authentication message must be a JSON object"` | Send a JSON object `{}`, not array or string |
| `"First message must be auth_request"` | Set `"type": "auth_request"` in first message |
| `"Authentication message must include token field"` | Add `"token"` key |
| `"Token must be a string"` | Ensure token value is a string, not number/null |
| `"Token cannot be empty"` | Token must be non-empty and not just whitespace |
| `"Token expired"` | Refresh the JWT token and reconnect |

### Correct Auth Request Format

```json
{
  "type": "auth_request",
  "token": "Bearer eyJhbGciOiJIUzI1NiIs...",
  "subscribed_events": ["job_state_transition", "notification_queue_update"]
}
```

- `token` can include or omit the `Bearer ` prefix (stripped server-side)
- `subscribed_events` is optional; defaults to `["*"]`

---

## Event Subscription Issues

### Problem: Not Receiving Expected Events

**Diagnosis steps**:

1. **Check subscription list**: Did you subscribe to the right events?
   ```json
   {"subscribed_events": ["job_state_transition"]}
   ```
   This will NOT receive `notification_queue_update` events.

2. **Use wildcard for debugging**: Subscribe to `["*"]` to receive all events, then narrow down.

3. **Check subscription stats** (admin endpoint):
   ```
   GET /api/websocket-sessions/stats
   Authorization: Bearer <jwt_token>
   ```
   Response includes `subscription_counts` per event.

4. **Update subscriptions dynamically** without reconnecting:
   ```json
   {
     "type": "update_subscriptions",
     "events": ["job_state_transition", "notification_queue_update"],
     "action": "replace"
   }
   ```
   Watch for the `subscription_update` response confirming success.

### Problem: Receiving Too Many Events

Subscribe to only the events you need:
```json
{
  "subscribed_events": ["job_state_transition", "notification_play_sound"]
}
```

Or use `update_subscriptions` with `action: "remove"` to drop specific events after connecting.

---

## User Routing Issues

### Problem: Events Not Reaching the Right User

The system routes events by `user_id`, not `session_id`. Verify:

1. **Auth completed successfully**: The `auth_success` response should include your `user_id`
2. **User has active sessions**: Use `is_user_connected(user_id)` or check `/api/websocket-sessions`
3. **Events are user-scoped**: `job_state_transition` is only sent to the job's owner. If testing, ensure you're the owner of the job producing events

### Problem: Multiple Sessions for Same User

By default, multiple concurrent sessions per user are allowed (`websocket enforce single session per user = False`). Each session receives events independently based on its own subscriptions.

If `single_session_per_user` is `True`, connecting a new session closes the previous one. Check server logs for `"Closing existing session"` messages.

---

## Audio WebSocket Issues

### Problem: Audio WebSocket Not Receiving Audio

1. **Verify audio WebSocket is connected**: Check `/ws/audio/{session_id}` in Network tab
2. **Check WHICH session id the audio socket is on** — it is not always the queue's.
   The mobile app and the web multiplexer share one id across both sockets; the web app
   (`notifications.js`) gives the audio socket its own id and names it in the TTS request.
   Compare the id in the `/ws/audio/{session_id}` URL against the one the TTS POST sent —
   those two must match. The queue socket's id need not.
3. **Audio subscriptions are fixed**: Audio WebSocket always subscribes to `audio_streaming_status`, `audio_streaming_complete`, `sys_ping` — this is not configurable
4. **Check TTS request**: The TTS HTTP request triggers audio streaming. If no TTS request is sent, no audio events will arrive

### Problem: Audio Streaming Starts But Cuts Off

- Check for async task cancellation in server logs
- On disconnect, active streaming tasks are cancelled (`active_tasks[session_id].cancel()`)
- Reconnecting with the same session ID should work

---

## Performance Issues

### Problem: High Latency on Events

1. **Check heartbeat interval**: Default 30s. Lower for faster dead-connection detection, but increases traffic
2. **Check connection count**: `GET /api/websocket-sessions/stats` → `total_connections`
3. **Stale sessions accumulating**: Force cleanup via `POST /api/websocket-sessions/cleanup`

### Problem: Memory Growth

1. **Check for session leaks**: Sessions that disconnect without proper cleanup remain in memory until heartbeat or auto-cleanup detects them
2. **Verify cleanup is enabled**: `websocket cleanup enabled = True` in INI
3. **Reduce max age**: Lower `websocket session max age hours` to clean up faster

---

## Debug Mode

Enable verbose logging in `lupin-app.ini`:

```ini
app debug = true
```

This enables:
- Detailed connection/disconnection logging with email and session type
- Subscription change logging
- Emit routing decisions
- Faster `sys_time_update` broadcasts (5s instead of 60s) for testing event flow

---

## Recovery Procedures

### Force Disconnect All Sessions

```
POST /api/websocket-sessions/cleanup
Authorization: Bearer <jwt_token>
```

### Restart WebSocket Subsystem

Restart the FastAPI server. All WebSocket connections will be dropped and clients must reconnect.

### Browser-Side Recovery

1. Clear localStorage (`sessionId` key)
2. Refresh the page
3. A new session ID will be generated and connection re-established

---

## Log Collection Checklist

When reporting WebSocket issues, collect:

1. **Browser console logs**: Filter for WebSocket-related messages
2. **Network → WS tab**: Screenshot the WebSocket frames
3. **Server terminal output**: Look for connection/disconnection messages, auth errors
4. **Session stats**: `GET /api/websocket-sessions/stats`
5. **Config verification**: Check `lupin-app.ini` WebSocket keys

---

## Related Documentation

- [WebSocket Architecture](websocket-architecture.md) — System design and WebSocketManager API
- [WebSocket Events](websocket-events.md) — Complete event catalog with payload schemas
- [WebSocket Configuration](websocket-configuration.md) — Config keys and tuning
