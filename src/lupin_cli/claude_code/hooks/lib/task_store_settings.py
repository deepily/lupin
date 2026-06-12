"""
Task-store mirror settings loader for the Claude Code PostToolUse hook.

Reads `~/.claude/settings.json` ["task_store"] and returns a normalized config
dict for the Phase-2 write-path mirror (harness Task* events -> unified task
store). Mirrors the `heartbeat_settings` loader exactly — same file, same
defaults-on-missing, same fail-loud-on-malformed-values posture.

**DEFAULT enabled=False (conservative opt-in).** The mirror is a brand-new
ACTIVE behavior on the shared production PostToolUse hook — it issues
authenticated HTTP writes against `:7999`. Defaulting OFF when the
`task_store` block is absent means merging the mirror code is a NO-OP until
the user/manager explicitly opts in via `settings.json`; the settings wiring
IS the rollout gate / kill-switch.

Validates loudly — raises ValueError on a bogus timeout/TTL (mirrors
heartbeat_settings; per `feedback_no_defensive_programming`: no silent
fallback chains). The mirror orchestrator catches that ValueError and fails
SAFE (treats the mirror as disabled — never writes on a malformed config).

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md §1.1.
"""

import json
import os
from pathlib import Path
from typing import Any


# Documented defaults — single source of truth for "what does the user get
# if settings.json doesn't override?"
DEFAULT_ENABLED           = False                       # opt-in: mirror is dormant until wired on
DEFAULT_API_BASE_URL      = "http://localhost:7999"     # the F2-ruled store host
DEFAULT_TIMEOUT_SECONDS   = 3.0                         # bounded hook-side wait (C8: short hook timeout)
DEFAULT_SPOOL_TTL_SECONDS = 86400                       # mirrors `notify outbox ttl seconds` (24h)


def load_task_store_settings() -> dict:
    """
    Load task-store mirror settings from ~/.claude/settings.json with defaults.

    Schema in settings.json:
        {
          "task_store": {
            "enabled"           : bool,
            "api_base_url"      : str,
            "timeout_seconds"   : number > 0,
            "spool_ttl_seconds" : number > 0
          }
        }

    Requires:
        - ~/.claude/settings.json is either missing OR valid JSON

    Ensures:
        - File missing                  → returns defaults (enabled=False)
        - File unreadable / bad JSON    → returns defaults (shared file; other
          features surface the parse error in their own paths)
        - Top-level "task_store" missing or not a dict → returns defaults
        - Individual fields missing     → use individual defaults
        - "enabled" not bool            → coerced to bool (Python truthiness)
        - "api_base_url" not a non-empty string → raises ValueError
        - "timeout_seconds" / "spool_ttl_seconds" not positive numbers →
          raises ValueError (fail-loud; bool explicitly rejected)
        - Returns dict with exactly four keys: "enabled", "api_base_url",
          "timeout_seconds" (float), "spool_ttl_seconds" (float)

    Raises:
        ValueError: malformed api_base_url / timeout_seconds / spool_ttl_seconds
    """
    settings_path = Path( os.path.expanduser( "~/.claude/settings.json" ) )

    if not settings_path.exists():
        return _defaults()

    try:
        with open( settings_path ) as f:
            raw = json.load( f )
    except ( json.JSONDecodeError, OSError ):
        # Shared settings file unreadable. Per the heartbeat_settings
        # precedent, a malformed file shouldn't take down this path specifically.
        return _defaults()

    block = raw.get( "task_store" )
    if not isinstance( block, dict ):
        return _defaults()

    enabled  = bool( block.get( "enabled", DEFAULT_ENABLED ) )
    base_url = block.get( "api_base_url", DEFAULT_API_BASE_URL )
    timeout  = block.get( "timeout_seconds", DEFAULT_TIMEOUT_SECONDS )
    ttl      = block.get( "spool_ttl_seconds", DEFAULT_SPOOL_TTL_SECONDS )

    if not isinstance( base_url, str ) or not base_url.strip():
        raise ValueError( f"task_store.api_base_url must be a non-empty string, got {base_url!r}" )
    _validate_positive_number( "timeout_seconds", timeout )
    _validate_positive_number( "spool_ttl_seconds", ttl )

    return {
        "enabled"           : enabled,
        "api_base_url"      : base_url.rstrip( "/" ),
        "timeout_seconds"   : float( timeout ),
        "spool_ttl_seconds" : float( ttl ),
    }


def _defaults() -> dict:
    """Return a fresh copy of the defaults."""
    return {
        "enabled"           : DEFAULT_ENABLED,
        "api_base_url"      : DEFAULT_API_BASE_URL,
        "timeout_seconds"   : DEFAULT_TIMEOUT_SECONDS,
        "spool_ttl_seconds" : DEFAULT_SPOOL_TTL_SECONDS,
    }


def _validate_positive_number( name: str, value: Any ) -> None:
    """
    Raise ValueError unless value is a positive int/float.

    Bool is a subclass of int in Python — explicitly reject bools so `True`
    doesn't slip through as 1 (heartbeat_settings precedent).

    Requires:
        - name is the settings key (for the error message)
        - value is anything (foreign settings data)

    Ensures:
        - Returns None for positive int/float
        - Raises ValueError otherwise

    Raises:
        ValueError: non-number, bool, or value <= 0
    """
    if isinstance( value, bool ) or not isinstance( value, ( int, float ) ) or value <= 0:
        raise ValueError( f"task_store.{name} must be a positive number, got {value!r}" )
