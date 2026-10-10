> Part 15 of 16 of the [Lupin Notification API Reference](../notification-api.md): the configuration reference (section 12).

## 12. Configuration Reference

### 12.1 Notification Config Keys

These keys live in `src/conf/lupin-app.ini` under `[Lupin: Baseline]`:

| Key | Default | Description |
|-----|---------|-------------|
| `enable response required notifications` | `false` | Enable response-required notifications (Phase 2). When `false`, only fire-and-forget is supported. |
| `enable sse blocking` | `false` | Enable SSE blocking mode for synchronous notifications. When `false`, all notifications are async. |
| `notification timeout default seconds` | `120` | Default timeout in seconds for response-required notifications. |
| `notification grace period seconds` | `300` | Grace period after timeout expires during which the server still accepts a response. |
| `notification offline immediate default` | `true` | When `true`, immediately returns default answer if user is offline (no active WebSocket). |

---

### 12.2 Notification Proxy Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `llm spec key for notification proxy matcher` | `kaitchup/phi_4_14b` | LLM model identifier for Phi-4 script matcher. |
| `prompt template for notification proxy script matcher` | `/src/conf/prompts/notification-proxy-script-matcher.txt` | Prompt template for single-question and multiple-choice matching. |
| `prompt template for notification proxy batch matcher` | `/src/conf/prompts/notification-proxy-batch-matcher.txt` | Prompt template for batch (`open_ended_batch`) matching. |
| `prompt template for notification proxy answer verifier` | `/src/conf/prompts/notification-proxy-answer-verifier.txt` | Prompt template for semantic answer verification. |
| `notification proxy scripts directory` | `/src/conf/notification-proxy-scripts` | Directory containing Q&A script JSON files. |

All config keys have matching explainer entries in `src/conf/lupin-app-splainer.ini`.

---

### 12.3 WebSocket Events Quick Reference

| Event | Direction | Description |
|-------|-----------|-------------|
| `notification_queue_update` | Server -> Client | New or updated notification in the queue |
| `notification_play_sound` | Server -> Client | Command to play a notification sound file |
| `job_state_transition` | Server -> Client | Job moved between queues (todo -> running -> done/dead) |
| `sys_ping` | Server -> Client | Keep-alive ping from server |
| `sys_pong` | Client -> Server | Keep-alive response from client |
| `auth_request` | Client -> Server | Authentication with Bearer token |
| `auth_success` | Server -> Client | Authentication accepted |
| `auth_error` | Server -> Client | Authentication failed |

---

### 12.4 Environment Variables

| Variable | Purpose |
|----------|---------|
| `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` | Login email for notification proxy and smoke tests |
| `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD` | Login password for notification proxy and smoke tests |
| `ANTHROPIC_API_KEY_FIREWALLED` | Anthropic API key for Tier 3 LLM Fallback |
| `LUPIN_ROOT` | Project root directory (used by `cu.get_project_root()`) |
| `LUPIN_CONFIG_MGR_CLI_ARGS` | CLI args JSON for `ConfigurationManager` |

---

### 12.5 Configuration Inheritance

The `ConfigurationManager` uses a single INI file with section-based inheritance:

```
[Lupin: Baseline]        <-- Base defaults
[Lupin: Docker]          <-- Docker overrides ( inherits from Baseline )
[Lupin: Test]            <-- Test overrides ( inherits from Baseline )
```

Runtime overrides follow this priority chain:

1. **Environment variables** (highest priority)
2. **CLI arguments** (via `LUPIN_CONFIG_MGR_CLI_ARGS`)
3. **INI file values** (lowest priority)

---

### 12.6 ConfigurationManager Access Pattern

```python
from cosa.app.configuration_manager import ConfigurationManager

config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

# Read a notification config key
timeout = config.get_int( "notification timeout default seconds" )

# Read a notification proxy key
spec_key = config.get( "llm spec key for notification proxy matcher" )

# Read a boolean flag
enabled = config.get_bool( "enable response required notifications" )
```

All notification and proxy keys follow the same access pattern. The
`ConfigurationManager` handles type coercion, default resolution, and
section inheritance transparently.

---
