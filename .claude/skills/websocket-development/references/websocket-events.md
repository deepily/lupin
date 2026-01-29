# WebSocket Events Reference

This is a reference pointer to the full events documentation.

**Full Documentation**: See `src/docs/websocket-events.md`

## Event Categories

### System Events
- `auth_request` / `auth_response` - Authentication
- `subscribe` / `unsubscribe` - Event filtering
- `ping` / `pong` - Keepalive

### Queue Events
- `queue_update` - Job queue changes
- `job_created` - New job added
- `job_completed` - Job finished
- `job_failed` - Job error

### Notification Events
- `notification` - User notifications
- `alert` - System alerts

### Audio Events (Audio WebSocket only)
- `audio_chunk` - TTS audio data
- `audio_start` - Stream beginning
- `audio_end` - Stream complete

## Event Format

```json
{
  "type": "event_type",
  "timestamp": "2026-01-28T12:00:00Z",
  "data": { ... }
}
```

For complete event catalog and payload schemas, read `src/docs/websocket-events.md`.
