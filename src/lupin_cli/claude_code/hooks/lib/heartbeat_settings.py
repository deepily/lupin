"""
Heartbeat-Hook settings loader for the Claude Code Stop hook.

Reads `~/.claude/settings.json` and returns a normalized config dict for the
Branch-C heartbeat self-poke adapter. Falls back to documented defaults if the
file or keys are missing.

**DEFAULT enabled=False (conservative opt-in).** The heartbeat is a brand-new
ACTIVE behavior on the shared production Stop hook — it can self-poke (force a
continuation) on quiescence-with-work-owed. Defaulting OFF when the `heartbeat`
block is absent means merging the adapter code is a NO-OP until the user
explicitly opts in via `settings.json`; the settings.json wiring is the
kill-switch / opt-in (flagged to the manager before it lands). This differs
from idle_detection (default ON) precisely because idle_detection is a mature,
passive feature whereas the heartbeat actively forces continuations.

Validates loudly — raises ValueError on a bogus poke_cap (mirrors
idle_settings; per `feedback_no_defensive_programming`: no silent fallback
chains). The Stop-hook adapter (`stop.py:_run_heartbeat`) catches that
ValueError and fails SAFE (treats the heartbeat as disabled — never pokes on a
malformed config).

Design authority (LOCKED): planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0 #6.
Lupin-side seam: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md
"""

import json
import os
from pathlib import Path
from typing import Any

from lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap import DEFAULT_POKE_CAP


# Documented defaults — single source of truth for "what does the user get
# if settings.json doesn't override?"
DEFAULT_ENABLED = False               # opt-in: heartbeat is dormant until wired on
# DEFAULT_POKE_CAP is owned by heartbeat_poke_cap (the counter module) — single
# source of truth for the cap value; re-exported here for the settings default.

# Thread B (Rick 2026-06-16): whether an unanswered inbound DM counts as OWED work
# (the v3 worker-inbound poke signal). DEFAULT False = "removed for the moment" —
# the arbiter's own manager-stale poke-DMs were self-inflating the owed count and
# re-poking on the arbiter's own poke. Flip True in settings.json to restore.
DEFAULT_COUNT_INBOUND_AS_OWED = False

# Spine Step-2 (store-canonical task management) — owed-items SOURCE selector.
# DEFAULT False = the OLD transcript-replay path (the work-owed verdict reads the
# session's own Task* state from its transcript). Flip True in settings.json to
# source the owed COUNT from the unified task store instead. DEFAULT-old is the
# BLOCKING sequencing gate (cascade review §A): the seam ships behind this flag
# so merging it is a NO-OP until the fleet-wide cutover explicitly flips it — an
# obeying session must never go dark on an empty transcript before the store is
# the source. Rollback = flip back to False (no redeploy).
DEFAULT_OWED_SOURCE_FROM_STORE = False

# Receipts-of-progress inward twin (6929f4ac, Rick 2026-06-22): the manager
# worker-verification debounce window, in seconds. While a manager's last look-in
# is older than this AND workers are out, the oracle fires `needs_verification`
# (work-owed) so the manager keeps getting poked to verify. Rick: 10 min (600s).
# Mirrors VERIFICATION_DEBOUNCE_SECONDS in heartbeat_work_owed (the pure default);
# this is the settings-overridable runtime value the stop.py shell passes in.
DEFAULT_VERIFICATION_THRESHOLD_SECONDS = 600


def load_heartbeat_settings() -> dict:
    """
    Load heartbeat settings from ~/.claude/settings.json with defaults.

    Schema in settings.json:
        {
          "heartbeat": {
            "enabled"  : bool,
            "poke_cap" : int,   # > 0
            "count_inbound_questions_as_owed" : bool,  # Thread B; default False
            "owed_source_from_store" : bool,           # Step-2; default False
            "verification_threshold_seconds" : int     # 6929f4ac; default 600 (>0)
          }
        }

    Requires:
        - ~/.claude/settings.json is either missing OR valid JSON

    Ensures:
        - File missing                 → returns defaults (enabled=False)
        - File unreadable / bad JSON    → returns defaults (shared file; other
          features surface the parse error in their own paths)
        - Top-level "heartbeat" missing → returns defaults
        - "heartbeat" not a dict        → returns defaults
        - Individual fields missing     → use individual defaults
        - "enabled" not bool            → coerced to bool (Python truthiness)
        - "poke_cap" not a positive int → raises ValueError (fail-loud)
        - "count_inbound_questions_as_owed" missing → DEFAULT False; non-bool →
          coerced to bool (Python truthiness)
        - "owed_source_from_store" missing → DEFAULT False (the old transcript
          path); non-bool → coerced to bool (Python truthiness)
        - "verification_threshold_seconds" missing → DEFAULT 600 (Rick's 10 min);
          non-positive-int → raises ValueError (fail-loud, like poke_cap)
        - Returns dict with exactly five keys: "enabled" (bool), "poke_cap"
          (int > 0), "count_inbound_questions_as_owed" (bool),
          "owed_source_from_store" (bool), "verification_threshold_seconds" (int > 0)

    Raises:
        ValueError: malformed poke_cap or verification_threshold_seconds
          (non-int, bool, or value <= 0)
    """
    settings_path = Path( os.path.expanduser( "~/.claude/settings.json" ) )

    if not settings_path.exists():
        return _defaults()

    try:
        with open( settings_path ) as f:
            raw = json.load( f )
    except ( json.JSONDecodeError, OSError ):
        # Shared settings file unreadable. Per the idle_settings precedent, a
        # malformed file shouldn't take down the heartbeat path specifically.
        return _defaults()

    block = raw.get( "heartbeat" )
    if not isinstance( block, dict ):
        return _defaults()

    enabled       = bool( block.get( "enabled", DEFAULT_ENABLED ) )
    poke_cap      = block.get( "poke_cap", DEFAULT_POKE_CAP )
    count_inbound = bool( block.get( "count_inbound_questions_as_owed",
                                     DEFAULT_COUNT_INBOUND_AS_OWED ) )
    owed_source_from_store = bool( block.get( "owed_source_from_store",
                                              DEFAULT_OWED_SOURCE_FROM_STORE ) )
    verification_threshold = block.get( "verification_threshold_seconds",
                                        DEFAULT_VERIFICATION_THRESHOLD_SECONDS )

    _validate_poke_cap( poke_cap )
    _validate_verification_threshold( verification_threshold )

    return {
        "enabled"                        : enabled,
        "poke_cap"                       : poke_cap,
        "count_inbound_questions_as_owed": count_inbound,
        "owed_source_from_store"         : owed_source_from_store,
        "verification_threshold_seconds" : verification_threshold,
    }


def _defaults() -> dict:
    """Return a fresh copy of the defaults."""
    return {
        "enabled"                        : DEFAULT_ENABLED,
        "poke_cap"                       : DEFAULT_POKE_CAP,
        "count_inbound_questions_as_owed": DEFAULT_COUNT_INBOUND_AS_OWED,
        "owed_source_from_store"         : DEFAULT_OWED_SOURCE_FROM_STORE,
        "verification_threshold_seconds" : DEFAULT_VERIFICATION_THRESHOLD_SECONDS,
    }


def _validate_poke_cap( value: Any ) -> None:
    """
    Raise ValueError if poke_cap is not a positive int.

    Bool is a subclass of int in Python — explicitly reject bools so `True`
    doesn't slip through as 1.

    Requires:
        - value is anything (foreign settings data)

    Ensures:
        - Returns None when value is an int > 0
        - Raises ValueError otherwise
    """
    if isinstance( value, bool ) or not isinstance( value, int ):
        raise ValueError(
            f"heartbeat.poke_cap must be an int, got {type( value ).__name__}: {value!r}"
        )
    if value <= 0:
        raise ValueError(
            f"heartbeat.poke_cap must be > 0, got {value}"
        )


def _validate_verification_threshold( value: Any ) -> None:
    """
    Raise ValueError if verification_threshold_seconds is not a positive int.

    Same fail-loud bug-class guard as poke_cap (no silent fallback chains): a
    bogus threshold would silently config-dead or thrash the inward-twin debounce.
    Bool is a subclass of int — explicitly rejected so `True` doesn't slip as 1.

    Requires:
        - value is anything (foreign settings data)

    Ensures:
        - Returns None when value is an int > 0
        - Raises ValueError otherwise
    """
    if isinstance( value, bool ) or not isinstance( value, int ):
        raise ValueError(
            f"heartbeat.verification_threshold_seconds must be an int, "
            f"got {type( value ).__name__}: {value!r}"
        )
    if value <= 0:
        raise ValueError(
            f"heartbeat.verification_threshold_seconds must be > 0, got {value}"
        )


def quick_smoke_test():
    """
    Self-contained smoke test for heartbeat_settings.

    Ensures:
        - Returns True if defaults + validation behave as designed;
          raises AssertionError otherwise.
    """
    # Defaults shape — conservative opt-out
    d = _defaults()
    assert d == { "enabled": False, "poke_cap": DEFAULT_POKE_CAP,
                  "count_inbound_questions_as_owed": False,
                  "owed_source_from_store": False,
                  "verification_threshold_seconds": DEFAULT_VERIFICATION_THRESHOLD_SECONDS }, d

    # Valid poke_caps pass validation
    _validate_poke_cap( 1 )
    _validate_poke_cap( 3 )
    _validate_poke_cap( 99 )

    # Valid verification thresholds pass validation
    _validate_verification_threshold( 1 )
    _validate_verification_threshold( 600 )

    # Note: the exhaustive INVALID-poke_cap raise matrix (string / bool / float
    # / zero / negative / None / list) is owned by the unit test
    # (test_heartbeat_settings.py::test_validate_poke_cap_rejects). It is NOT
    # repeated here — an inline "assert it raised" loop carries an unreachable
    # fall-through raise (dead line) that the house "no unreachable defensive
    # branches" rule rejects.

    # Real load (whatever's on disk) — enabled is a bool, poke_cap a positive int
    loaded = load_heartbeat_settings()
    assert isinstance( loaded[ "enabled" ], bool )
    assert isinstance( loaded[ "poke_cap" ], int ) and loaded[ "poke_cap" ] > 0
    assert isinstance( loaded[ "count_inbound_questions_as_owed" ], bool )
    assert isinstance( loaded[ "owed_source_from_store" ], bool )
    assert isinstance( loaded[ "verification_threshold_seconds" ], int ) and loaded[ "verification_threshold_seconds" ] > 0

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_settings smoke: {'PASS' if ok else 'FAIL'}" )
