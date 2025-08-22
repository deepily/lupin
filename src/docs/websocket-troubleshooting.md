# WebSocket Troubleshooting Guide

**Date**: 2025.08.13  
**Purpose**: Comprehensive troubleshooting guide for WebSocket issues in the Lupin system  
**Status**: Active  

## Quick Diagnostics

### Is WebSocket Working?
1. **Check connection status** in browser dev tools (Network → WS tab)
2. **Look for authentication success** message in console
3. **Verify event reception** by watching for `sys_ping` events
4. **Test with curl** for basic connectivity:
   ```bash
   curl --upgrade -H "Connection: Upgrade" -H "Upgrade: websocket" \
        ws://localhost:7999/ws/queue/test_session
   ```

### Common Error Patterns
- **401 Unauthorized**: Authentication issues
- **403 Forbidden**: Session validation problems  
- **404 Not Found**: Invalid endpoint or session format
- **Connection refused**: Server not running or wrong port
- **WebSocket closed immediately**: Authentication timeout

---

## Connection Issues

### Problem: WebSocket Connection Fails
**Symptoms**: 
- "WebSocket connection failed" in console
- Network tab shows failed WS connection
- Red connection status indicator

**Solutions**:
1. **Verify server is running**:
   ```bash
   curl http://localhost:7999/health
   ```

2. **Check correct port** (default: 7999):
   ```javascript
   // Correct
   ws://localhost:7999/ws/queue/session_id
   ```

3. **Validate session ID format**:
   ```javascript
   // Correct: "adjective noun" format
   "wise penguin", "clever dolphin", "brave falcon"
   
   // Incorrect: other formats
   "test-123", "user_session", "abc123"
   ```

4. **Check firewall/proxy settings**:
   - Corporate firewalls may block WebSocket upgrades
   - Ensure WebSocket traffic is allowed on port 7999

### Problem: Connection Succeeds But No Events
**Symptoms**:
- WebSocket shows as connected
- No events received (no sys_ping, no queue updates)
- Console shows successful connection but silence

**Solutions**:
1. **Check authentication flow**:
   ```javascript
   // Must send auth_request first
   {
     "type": "auth_request",
     "token": "Bearer mock_token_email_user@example.com",
      "session_id": "wise_penguin",
     "subscribed_events": ["sys_ping", "queue_todo_update"]
   }
   ```

2. **Verify event subscriptions**:
   ```javascript
   // Check subscribed_events array includes desired events
   const queueSubscriptions = [
     "queue_todo_update",
     "sys_ping",
     "auth_success"
   ];
   ```

3. **Enable debug mode** for more logging:
   ```ini
   # In lupin-app.ini
   app_debug = true
   ```

---

## Authentication Problems

### Problem: Authentication Always Fails
**Symptoms**:
- Constant `auth_error` responses
- "Invalid token" messages
- Unable to receive any events

**Solutions**:
1. **Use correct token format**:
   ```javascript
   // Correct format
   "Bearer mock_token_email_user@example.com"
   
   // Replace user@example.com with your actual email
   "Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com"
   ```

2. **Check token consistency**:
   - Same token must be used for all connections from same user
   - Token maps to user ID internally

3. **Verify session persistence**:
   ```javascript
   // Check localStorage for existing session
   console.log( localStorage.getItem( "session_id" ) );
   ```

### Problem: Multiple Sessions Conflict
**Symptoms**:
- One tab works, others don't
- Intermittent authentication failures
- Session ID conflicts

**Solutions**:
1. **Enable single-session policy** (if desired):
   ```bash
   curl -X PUT "http://localhost:7999/api/websocket-sessions/single-session-policy" \
        -H "Authorization: Bearer your_token" \
        -d "enabled=true"
   ```

2. **Use unique session IDs per tab**:
   ```javascript
   // Generate unique session ID per tab
   const sessionId = generateSessionId();
   localStorage.setItem( "session_id", sessionId );
   ```

3. **Clear existing sessions**:
   ```javascript
   // Clear localStorage and refresh
   localStorage.clear();
   window.location.reload();
   ```

---

## Event Subscription Issues

### Problem: Missing Specific Events
**Symptoms**:
- Receiving some events but not others
- Queue updates work but audio events don't
- Notifications not appearing

**Solutions**:
1. **Check subscription list**:
   ```javascript
   // Ensure event is in subscribed_events array
   const subscriptions = [
     "queue_todo_update",     // ✓ Queue events
     "tts_job_request",       // ✓ Audio notifications
     "notification_queue_update", // ✓ Notifications
     "sys_ping"               // ✓ Heartbeat
   ];
   ```

2. **Use correct endpoint for event type**:
   ```javascript
   // Queue events
   ws://localhost:7999/ws/queue/session_id
   
   // Audio events only
   ws://localhost:7999/ws/audio/session_id
   ```

3. **Update subscriptions dynamically**:
   ```javascript
   // Send subscription update
   websocket.send( JSON.stringify( {
     "type": "update_subscriptions",
     "events": ["new_event_type"],
     "action": "add"  // or "remove" or "replace"
   } ) );
   ```

### Problem: Events Received But Not Handled
**Symptoms**:
- Console shows event reception
- UI doesn't update
- Event handlers not triggering

**Solutions**:
1. **Check event handler registration**:
   ```javascript
   // Verify handlers are registered
   websocket.onmessage = function( event ) {
     const data = JSON.parse( event.data );
     console.log( "Received event:", data.type );
     
     // Ensure handler exists for event type
     if ( eventHandlers[data.type] ) {
       eventHandlers[data.type]( data );
     }
   };
   ```

2. **Verify event type names**:
   ```javascript
   // Use correct normalized event names
   "queue_todo_update"    // not "todo_update"
   "tts_job_request"      // not "speech_update"
   "sys_ping"             // not "ping"
   ```

3. **Check for JavaScript errors**:
   - Open browser dev tools Console tab
   - Look for handler function errors
   - Verify DOM elements exist for UI updates

---

## Performance Issues

### Problem: Slow Event Processing
**Symptoms**:
- Delayed UI updates
- Events arrive but take time to process
- Browser becomes unresponsive

**Solutions**:
1. **Reduce event frequency** in debug mode:
   ```ini
   # In lupin-app.ini - slows down sys_time_update
   app_debug = false
   ```

2. **Optimize event handlers**:
   ```javascript
   // Use requestAnimationFrame for DOM updates
   function updateQueueCount( count ) {
     requestAnimationFrame( () => {
       document.getElementById( "todo" ).textContent = count;
     } );
   }
   ```

3. **Implement event debouncing**:
   ```javascript
   // Debounce rapid events
   const debouncedHandler = debounce( handleQueueUpdate, 100 );
   ```

### Problem: Memory Leaks
**Symptoms**:
- Browser memory usage grows over time
- Page becomes slower after extended use
- Connection issues after long sessions

**Solutions**:
1. **Check for duplicate event listeners**:
   ```javascript
   // Remove existing listeners before adding new ones
   websocket.removeEventListener( "message", oldHandler );
   websocket.addEventListener( "message", newHandler );
   ```

2. **Clean up audio objects**:
   ```javascript
   // Properly dispose of audio objects
   audioElement.pause();
   audioElement.src = "";
   audioElement.load();
   ```

3. **Monitor WebSocket connections**:
   ```bash
   # Check active connections
   curl "http://localhost:7999/api/websocket-sessions/stats" \
        -H "Authorization: Bearer your_token"
   ```

---

## Network and Browser Issues

### Problem: Corporate Firewall Blocking
**Symptoms**:
- Works locally but fails in corporate environment
- WebSocket upgrade fails
- Connection timeout errors

**Solutions**:
1. **Use HTTPS/WSS in production**:
   ```javascript
   // Use secure WebSocket
   wss://your-domain.com/ws/queue/session_id
   ```

2. **Configure proxy headers**:
   ```nginx
   # Nginx proxy configuration
   proxy_http_version 1.1;
   proxy_set_header Upgrade $http_upgrade;
   proxy_set_header Connection "upgrade";
   ```

3. **Test with HTTP polling fallback**:
   ```javascript
   // Implement fallback when WebSocket fails
   if ( websocketFailed ) {
     startHttpPolling();
   }
   ```

### Problem: Browser Compatibility
**Symptoms**:
- Works in Chrome but not Safari/Firefox
- Intermittent connection issues
- Different behavior across browsers

**Solutions**:
1. **Check WebSocket API support**:
   ```javascript
   if ( !window.WebSocket ) {
     console.error( "WebSocket not supported" );
     // Implement fallback
   }
   ```

2. **Use browser-specific debugging**:
   ```javascript
   // Safari: Enable Develop menu → WebSockets
   // Firefox: about:config → network.websocket.enabled
   // Chrome: chrome://flags → WebSocket
   ```

3. **Test with different browsers**:
   - Chrome: Best WebSocket support
   - Firefox: Good support, check security settings
   - Safari: May have stricter security policies
   - Edge: Generally good compatibility

---

## Debug Mode and Logging

### Enable Comprehensive Logging
```ini
# In lupin-app.ini
app_debug = true
verbose = true
```

### Server-Side Debug Commands
```bash
# Check WebSocket sessions
curl "http://localhost:7999/api/websocket-sessions" \
     -H "Authorization: Bearer mock_token_email_user@example.com"

# View connection stats
curl "http://localhost:7999/api/websocket-sessions/stats" \
     -H "Authorization: Bearer mock_token_email_user@example.com"

# Force cleanup stale sessions
curl -X POST "http://localhost:7999/api/websocket-sessions/cleanup" \
     -H "Authorization: Bearer mock_token_email_user@example.com"
```

### Client-Side Debug Helpers
```javascript
// Enable WebSocket debug logging
localStorage.setItem( "debug_websocket", "true" );

// Monitor all WebSocket events
websocket.addEventListener( "message", function( event ) {
  console.log( "[WS DEBUG]", JSON.parse( event.data ) );
} );

// Check connection health
function checkWebSocketHealth() {
  console.log( "WebSocket state:", websocket.readyState );
  console.log( "Last ping:", lastPingTime );
  console.log( "Session ID:", localStorage.getItem( "session_id" ) );
}
```

---

## Common Configuration Issues

### Problem: Events Not Configured
**Symptoms**:
- Server logs show "Event not in available_events"
- Client receives subscription_error responses

**Solutions**:
1. **Check available events configuration**:
   ```ini
   # In lupin-app.ini
   websocket available events = queue_todo_update, queue_done_update, sys_ping, tts_job_request
   ```

2. **Verify event names match exactly**:
   - No typos in event names
   - Use underscore format (not camelCase)
   - Check against `/src/docs/websocket-events.md`

### Problem: Timeout Issues
**Symptoms**:
- Connections drop after specific time
- Authentication timeouts
- Heartbeat failures

**Solutions**:
1. **Adjust timeout settings**:
   ```ini
   # In lupin-app.ini
   websocket_heartbeat_interval = 30
   websocket_cleanup_interval = 3600
   ```

2. **Monitor heartbeat responses**:
   ```javascript
   // Respond to server pings
   if ( data.type === "sys_ping" ) {
     websocket.send( JSON.stringify( { "type": "sys_pong" } ) );
   }
   ```

---

## Recovery Procedures

### Complete Reset
1. **Clear all local storage**:
   ```javascript
   localStorage.clear();
   ```

2. **Restart WebSocket connections**:
   ```javascript
   if ( websocket ) {
     websocket.close();
   }
   initializeWebSocket();
   ```

3. **Server-side cleanup**:
   ```bash
   # Force cleanup all sessions
   curl -X POST "http://localhost:7999/api/websocket-sessions/cleanup?max_age_hours=0" \
        -H "Authorization: Bearer your_token"
   ```

### Gradual Debugging
1. **Start with basic connection**
2. **Add authentication**
3. **Subscribe to single event type**
4. **Gradually add more events**
5. **Monitor each step for issues**

---

## Getting Help

### Log Collection
Before reporting issues, collect:
1. **Browser console logs** (entire session)
2. **Network tab WebSocket frames**
3. **Server logs** with debug enabled
4. **Configuration files** (lupin-app.ini)
5. **Browser and OS version**

### Useful Debug Commands
```bash
# Test WebSocket with wscat (if installed)
wscat -c ws://localhost:7999/ws/queue/test_session

# Check server health
curl http://localhost:7999/health

# View current configuration
curl "http://localhost:7999/api/config" \
     -H "Authorization: Bearer your_token"
```

---

## Reference Links

- **[WebSocket Events Documentation](websocket-events.md)** - Complete event catalog
- **[WebSocket Testing Results](websocket-testing-results.md)** - Known working configurations
- **[Main README](../../README.md)** - Project overview and setup
- **[Configuration Guide](websocket-configuration.md)** - All config options

*Last updated: 2025.08.13*