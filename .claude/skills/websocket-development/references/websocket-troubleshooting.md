# WebSocket Troubleshooting Reference

This is a reference pointer to the full troubleshooting documentation.

**Full Documentation**: See `src/docs/websocket-troubleshooting.md`

## Quick Troubleshooting

### Connection Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Connection refused | Server not running | Start with `src/scripts/run-fastapi-lupin.sh` |
| Connection drops | Ping timeout | Check network, increase timeout |
| Auth fails | Bad token format | Use `Bearer mock_token_email_{email}` |

### Event Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| No events | Not subscribed | Send subscribe message |
| Wrong events | Subscription filter | Check event types in subscribe |
| Duplicate events | Multiple connections | Check for zombie sessions |

### Audio Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| No audio | Audio WS not connected | Connect to `/ws/audio/{session_id}` |
| Choppy audio | Network latency | Check bandwidth, buffer settings |
| Audio cuts off | Stream not completing | Check `audio_end` event |

## Debug Tools

1. **Browser DevTools**: Network → WS → Messages
2. **Server logs**: Check FastAPI output
3. **Console messages**: Auth success/failure logged

For comprehensive debugging procedures, read `src/docs/websocket-troubleshooting.md`.
