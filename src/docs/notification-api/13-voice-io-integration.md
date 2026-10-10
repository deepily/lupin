> Part 13 of 16 of the [Lupin Notification API Reference](../notification-api.md): voice I/O integration (section 10).

## 10. Voice I/O Integration

### 10.1 Overview

The `voice_io` module (`src/cosa/agents/utils/voice_io.py`) provides a
voice-first interaction layer for COSA agents. It uses the cosa_interface pattern (Tier 2) as its primary channel.
It falls back to CLI text (`print` / `input`) automatically when the voice service is unavailable or `--cli-mode` is explicitly set.

```
Priority Order:
  1. Voice I/O (cosa_interface functions) -- PRIMARY
  2. CLI fallback (print / input) -- when voice unavailable
  3. --cli-mode flag -- forces CLI regardless of voice availability
```

---

### 10.2 Module Configuration

The module maintains three pieces of global state:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `_force_cli_mode` | `bool` | `False` | When `True`, voice is never attempted |
| `_voice_available` | `Optional[ bool ]` | `None` | `None` = not yet checked; `True`/`False` = cached probe result |
| `_cosa_interface` | `Optional[ object ]` | `None` | Agent-specific cosa_interface module |

**Configuration functions**:

| Function | Signature | Description |
|----------|-----------|-------------|
| `configure()` | `configure( cosa_interface_module ) -> None` | Set the agent-specific cosa_interface module. Must be called before voice functions work. |
| `set_cli_mode()` | `set_cli_mode( enabled: bool ) -> None` | Force CLI mode on/off. When enabled, all interactions use `print` / `input`. |
| `get_mode_description()` | `get_mode_description() -> str` | Human-readable description of current mode (e.g., `"Voice mode (primary)"`, `"CLI mode (forced)"`). |
| `reset_voice_check()` | `reset_voice_check() -> None` | Clear the cached `_voice_available` value so the next call re-probes the voice service. |
| `is_cli_mode()` | `is_cli_mode() -> bool` | Returns `True` if CLI mode is active (forced or not configured). |

**Typical setup in an agent orchestrator**:

```python
from cosa.agents.utils import voice_io
from cosa.agents.deep_research import cosa_interface

voice_io.configure( cosa_interface )

# Or force CLI mode:
voice_io.set_cli_mode( True )
```

---

### 10.3 Voice I/O Functions

All functions are `async` and follow the same pattern: check CLI mode, try voice,
fall back to CLI on failure.

| Function | Signature | Voice Behavior | CLI Fallback |
|----------|-----------|----------------|--------------|
| `notify()` | `notify( message, priority="medium", abstract=None, session_name=None, job_id=None, queue_name=None ) -> None` | TTS announcement via `cosa_interface.notify_progress()` | `print( message )` |
| `ask_yes_no()` | `ask_yes_no( question, default="no", timeout=60, abstract=None ) -> bool` | TTS question, voice response via `cosa_interface.ask_confirmation()` | `input( question [Y/n]: )` |
| `get_input()` | `get_input( prompt, allow_empty=True, timeout=300 ) -> Optional[ str ]` | TTS prompt, voice capture via `cosa_interface.get_feedback()` | `input( prompt: )` |
| `choose()` | `choose( question, options, timeout=120, allow_custom=False ) -> str` | TTS options, voice selection via `cosa_interface.present_choices()` | Numbered menu with `input()` |
| `present_choices()` | `present_choices( questions, timeout=120, title=None, abstract=None ) -> dict` | Full multi-question voice UI via `cosa_interface.present_choices()` | Numbered menu per question |
| `select_themes()` | `select_themes( themes, timeout=180 ) -> list[ int ]` | Multi-select themes with TTS descriptions | Comma-separated number input or `"all"` |
| `select_topics()` | `select_topics( topics, preselected=True, timeout=180 ) -> list[ int ]` | Multi-select topics for progressive narrowing | Comma-separated number input, `"all"`, or `"none"` |

**Example -- voice-first notify with job card routing**:

```python
await voice_io.notify(
    "Phase 3 complete: 15 sources analyzed.",
    priority   = "medium",
    job_id     = "dr-a1b2c3d4",
    queue_name = "run"
)
```

**Example -- choose with custom option**:

```python
approach = await voice_io.choose(
    "Which approach should I use?",
    options = [
        { "label" : "Incremental", "description" : "Migrate one table at a time" },
        { "label" : "Big-bang",    "description" : "Migrate everything at once" }
    ],
    allow_custom = True
)
```

---

### 10.4 Voice Service Availability

The `is_voice_available()` coroutine probes the voice service exactly once per
session and caches the result in `_voice_available`:

| State | Meaning |
|-------|---------|
| `None` | Not yet checked -- next call will probe |
| `True` | Voice service responded to a minimal `notify_progress( "Initializing...", priority="low" )` call |
| `False` | Voice service unavailable or cosa_interface not configured |

**Probe behavior**: Sends a silent low-priority notification. If it succeeds,
voice is marked available. If any exception occurs, voice is marked unavailable
and all subsequent calls fall back to CLI for the rest of the session.

**Manual reset**: Call `reset_voice_check()` to clear the cache and force a
re-probe on the next voice function call.

---

### 10.5 Priority Levels and Audio Behavior

Priority determines **how the user is alerted**, not workflow importance:

| Priority | Audio Behavior | When to Use |
|----------|----------------|-------------|
| `urgent` | Alert tone + TTS read aloud | Critical errors, blockers, failures |
| `high` | Prominent ping + TTS read aloud | Blocking decisions requiring response |
| `medium` | Gentle ping (no TTS) | Informational updates user should notice |
| `low` | Silent (no sound) | Background info, minor completions |

**Critical rule**: All **blocking tools** (`ask_yes_no`, `converse`,
`ask_multiple_choice`, `ask_open_ended_batch`) **must** use `priority="high"` to
ensure TTS reaches the user. Without high priority, the notification plays a
gentle ping at best, and the user may miss it entirely -- causing a timeout.

---

### 10.6 Error Handling

Every voice I/O function follows a three-step error handling pattern:

1. **Check CLI mode** -- If `_force_cli_mode` is `True`, or `_cosa_interface` is
   `None`, or `is_voice_available()` returns `False`, use CLI fallback immediately.
2. **Try voice** -- Call the appropriate `_cosa_interface` function inside a
   `try` / `except` block.
3. **Fallback on failure** -- If the voice call raises any exception, log a
   warning and fall back to CLI (`print` / `input`).

**Never-raise guarantee**: The `notify()`, `ask_yes_no()`, `get_input()`,
`choose()`, and `present_choices()` functions never raise exceptions. Errors are
logged via `logger.warning()` and the CLI fallback is used transparently.

**Exception**: `select_themes()` and `select_topics()` **do** re-raise as
`RuntimeError` after notifying the user of the failure. This is intentional.
The caller needs to distinguish "user cancelled" (returns an empty list) from "voice service error" (raises `RuntimeError`).
With that distinction it can retry or switch modes.

---
