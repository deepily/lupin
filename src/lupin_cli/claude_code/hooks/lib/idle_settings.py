"""
Idle-detection settings loader for the Claude Code idle-aware Stop hook.

Reads `~/.claude/settings.json` and returns a normalized config dict for the
deferred-ask waiter. Falls back to documented defaults if the file or keys
are missing.

Validates loudly — raises ValueError on bogus schedule (e.g. non-int values
in backoff_minutes). Per `feedback_no_defensive_programming`: no silent
fallback chains. If the user has typoed their settings, fail at hook startup
with a clear error rather than degrade silently into surprising behavior.

See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
"""

import json
import os
from pathlib import Path
from typing import Any


# Documented defaults — single source of truth for "what does the user get
# if settings.json doesn't override?"
DEFAULT_ENABLED         = True
DEFAULT_BACKOFF_MINUTES = [ 5, 10, 20, 40, 60 ]


def load_idle_settings() -> dict:
    """
    Load idle-detection settings from ~/.claude/settings.json with defaults.

    Schema in settings.json:
        {
          "idle_detection": {
            "enabled"        : bool,
            "backoff_minutes": [int, int, ...]
          }
        }

    Behavior:
      - File missing → returns defaults
      - Top-level "idle_detection" key missing → returns defaults
      - Individual fields missing → use individual defaults
      - "enabled" not bool → coerce to bool (Python truthiness)
      - "backoff_minutes" not a non-empty list of positive ints → raise ValueError

    Requires:
      - ~/.claude/settings.json is either missing OR valid JSON

    Ensures:
      - Returns dict with exactly two keys: "enabled" (bool), "backoff_minutes"
        (list of int, length >= 1, all values > 0)
      - Raises ValueError on schema violations (so the user sees the typo
        instead of silently falling back to defaults)

    Returns:
      dict: { "enabled": bool, "backoff_minutes": list[int] }

    Raises:
      ValueError: malformed backoff_minutes (non-list, empty list, non-int
        values, or values <= 0)
    """
    settings_path = Path( os.path.expanduser( "~/.claude/settings.json" ) )

    if not settings_path.exists():
        return _defaults()

    try:
        with open( settings_path ) as f:
            raw = json.load( f )
    except ( json.JSONDecodeError, OSError ):
        # Settings file unreadable. Per fail-loud principle, we COULD raise
        # here — but ~/.claude/settings.json is shared with other Claude Code
        # features, and a malformed file shouldn't take down the idle hook
        # specifically. Fall back to defaults; other features will surface
        # the parse error in their own paths.
        return _defaults()

    block = raw.get( "idle_detection" )
    if not isinstance( block, dict ):
        return _defaults()

    enabled         = bool( block.get( "enabled", DEFAULT_ENABLED ) )
    backoff_minutes = block.get( "backoff_minutes", DEFAULT_BACKOFF_MINUTES )

    _validate_backoff_minutes( backoff_minutes )

    return {
        "enabled"         : enabled,
        "backoff_minutes" : list( backoff_minutes ),
    }


def _defaults() -> dict:
    """Return a fresh copy of the defaults — list is copied to avoid mutation."""
    return {
        "enabled"         : DEFAULT_ENABLED,
        "backoff_minutes" : list( DEFAULT_BACKOFF_MINUTES ),
    }


def _validate_backoff_minutes( value: Any ) -> None:
    """
    Raise ValueError if backoff_minutes is not a non-empty list of positive ints.

    Bool is a subclass of int in Python — explicitly reject bools so
    `[True, False]` doesn't slip through.
    """
    if not isinstance( value, list ):
        raise ValueError(
            f"idle_detection.backoff_minutes must be a list, got {type( value ).__name__}: {value!r}"
        )
    if len( value ) == 0:
        raise ValueError(
            "idle_detection.backoff_minutes must be a non-empty list (at least one entry)"
        )
    for i, v in enumerate( value ):
        if isinstance( v, bool ) or not isinstance( v, int ):
            raise ValueError(
                f"idle_detection.backoff_minutes[{i}] must be an int, got {type( v ).__name__}: {v!r}"
            )
        if v <= 0:
            raise ValueError(
                f"idle_detection.backoff_minutes[{i}] must be > 0, got {v}"
            )


def quick_smoke_test():
    """Quick smoke test for idle_settings."""
    print( "=" * 70 )
    print( " idle_settings.py smoke test" )
    print( "=" * 70 )

    # Defaults shape
    d = _defaults()
    assert d == { "enabled": True, "backoff_minutes": [ 5, 10, 20, 40, 60 ] }, d
    print( "✓ defaults shape" )

    # Valid schedule passes validation
    _validate_backoff_minutes( [ 1 ] )
    _validate_backoff_minutes( [ 5, 10, 20 ] )
    print( "✓ valid schedules pass validation" )

    # Invalid schedules raise loudly
    bad_cases = [
        ( "not a list",      "string" ),
        ( "empty list",      [ ] ),
        ( "string element",  [ 5, "ten" ] ),
        ( "bool element",    [ True, 5 ] ),
        ( "zero element",    [ 5, 0, 10 ] ),
        ( "negative",        [ 5, -1 ] ),
    ]
    for label, val in bad_cases:
        try:
            _validate_backoff_minutes( val )
        except ValueError:
            print( f"✓ rejects {label}" )
            continue
        raise AssertionError( f"should have raised for: {label} = {val!r}" )

    # Real load (whatever's on disk)
    loaded = load_idle_settings()
    assert isinstance( loaded[ "enabled" ], bool )
    assert isinstance( loaded[ "backoff_minutes" ], list )
    assert all( isinstance( x, int ) and x > 0 for x in loaded[ "backoff_minutes" ] )
    print( f"✓ load_idle_settings() returned: enabled={loaded[ 'enabled' ]}, "
           f"backoff_minutes={loaded[ 'backoff_minutes' ]}" )

    print( "\nAll smoke tests passed." )


if __name__ == "__main__":
    quick_smoke_test()
