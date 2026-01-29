# WebSocket Configuration Reference

This is a reference pointer to the full configuration documentation.

**Full Documentation**: See `src/docs/websocket-configuration.md`

## Quick Reference

All WebSocket settings are in `src/conf/lupin-app.ini` under `websocket_*` keys.

### Common Settings

```ini
[websocket]
# Connection settings
websocket_host = 0.0.0.0
websocket_port = 7999

# Timeouts
websocket_ping_interval = 30
websocket_ping_timeout = 10

# Debug mode (faster updates)
app_debug = true  # 5s updates vs 60s
```

### Environment Overrides

Environment variables override config file settings:
- `WEBSOCKET_HOST`
- `WEBSOCKET_PORT`
- `APP_DEBUG`

For complete configuration options, read `src/docs/websocket-configuration.md`.
