"""
Heartbeat-Hook settings loader for the Claude Code Stop hook.

Reads `~/.claude/settings.json` and returns a normalized config dict for the
Branch-C heartbeat self-poke adapter. Falls back to documented defaults if the
file or keys are missing.

The default is enabled=False, a conservative opt-in. The heartbeat is a new
active behavior on the shared production Stop hook: it can self-poke (force a
continuation) on quiescence-with-work-owed. Defaulting off when the `heartbeat`
block is absent makes merging the adapter code a no-op until the user opts in
via `settings.json`. That wiring is the kill-switch and opt-in, flagged to the
manager before it lands. This differs from idle_detection (default on) because
idle_detection is a mature, passive feature whereas the heartbeat actively
forces continuations.

Validation is loud: a bogus poke_cap raises ValueError (mirrors idle_settings),
with no silent fallback chains. The Stop-hook adapter (`stop.py:_run_heartbeat`)
catches that ValueError and fails safe, treating the heartbeat as disabled, so
it never pokes on a malformed config.

Design authority (locked): planning-is-prompting ->
    planning-is-prompting/src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md section 0, sixth decision.
Lupin-side seam: lupin ->
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md
"""

import json
import os
from pathlib import Path
from typing import Any

from lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap import DEFAULT_POKE_CAP
from lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute import mute_message, read_poke_mute


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

# Poke-output mute switch (Rick 2026-07-22): a RUNTIME toggle that silences the
# stop-hook poke WITHOUT tearing down the heartbeat block. DEFAULT True = today's
# behavior (the live-obligations lookup runs and pokes). Flip False in
# settings.json to suppress the obligations lookup + its poke output; the hook is
# a fresh process per Stop, so the flip takes effect on the VERY NEXT Stop — no
# restart, toggleable mid-session.
DEFAULT_POKE_OUTPUT_ENABLED = True

# The substitute text emitted in place of the suppressed obligations poke. "" or
# None ⇒ the hook emits NO output at all (full silence). Only consulted when
# poke_output_enabled is False.
DEFAULT_POKE_DISABLED_MESSAGE = ""

# What a seat reads in place of the poke while skeleton crew is on and nobody wrote a line
# of their own. The operator asked for the poke to simply say this.
SKELETON_CREW_POKE_MESSAGE = "You are on skeleton crew."


def load_heartbeat_settings() -> dict:
    """
    Load heartbeat settings from ~/.claude/settings.json with defaults.

    Keys under "heartbeat": enabled, poke_cap, count_inbound_questions_as_owed, owed_source_from_store,
    verification_threshold_seconds, poke_output_enabled, poke_disabled_message (a string or None).

    Requires:
        - ~/.claude/settings.json is either missing or valid JSON

    Ensures:
        - File missing → returns defaults (enabled=False)
        - File unreadable / bad JSON → returns defaults (shared file; other
          features surface the parse error in their own paths)
        - Top-level "heartbeat" missing → returns defaults
        - "heartbeat" not a dict → returns defaults
        - Individual fields missing → use individual defaults
        - "enabled" not bool → coerced to bool (Python truthiness)
        - "poke_cap" not a positive int → raises ValueError (fail-loud)
        - "count_inbound_questions_as_owed" missing → default False; non-bool → coerced to bool (Python truthiness)
        - "owed_source_from_store" missing → default False (the old transcript path); non-bool → coerced to bool
          (Python truthiness)
        - "verification_threshold_seconds" missing → default 600 (10 minutes); non-positive-int → raises ValueError
          (fail-loud, like poke_cap)
        - "poke_output_enabled" missing → default True (poke as today); non-bool → coerced to bool (Python truthiness)
        - when settings.json leaves the poke on and the fleet switch file
          (heartbeat_poke_mute.read_poke_mute) says muted, "poke_output_enabled" is
          False; "poke_disabled_message" keeps the settings.json text when there is one,
          and otherwise names who muted it and when. A settings.json mute wins outright;
          the switch file is not read then
        - "poke_disabled_message" missing → default "" (no output when muted);
          None → normalized to ""; non-str → raises ValueError (fail-loud: a
          non-string substitute would be emitted verbatim into the worker)
        - Returns dict with exactly seven keys: "enabled" (bool), "poke_cap"
          (int > 0), "count_inbound_questions_as_owed" (bool),
          "owed_source_from_store" (bool), "verification_threshold_seconds" (int > 0), "poke_output_enabled" (bool),
          "poke_disabled_message" (str, possibly "")

    Raises:
        ValueError: malformed poke_cap or verification_threshold_seconds
          (non-int, bool, or value <= 0), or a non-string poke_disabled_message
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
    poke_output_enabled    = bool( block.get( "poke_output_enabled",
                                              DEFAULT_POKE_OUTPUT_ENABLED ) )
    poke_disabled_message  = block.get( "poke_disabled_message",
                                        DEFAULT_POKE_DISABLED_MESSAGE )

    _validate_poke_cap( poke_cap )
    _validate_verification_threshold( verification_threshold )
    poke_disabled_message = _normalize_poke_disabled_message( poke_disabled_message )

    # The fleet switch (row 3526fb95): an admin's toggle in a notification client. The
    # settings.json key above still mutes on its own; this can only ADD a mute, and a
    # missing or broken switch file reads as not muted.
    if poke_output_enabled:
        fleet_switch = read_poke_mute()
        if fleet_switch[ "muted" ]:
            poke_output_enabled   = False
            # The operator's own line wins when there is one (Rick: "I want the poke to
            # simply say you're on skeleton crew"); the who-and-when line fills a blank.
            poke_disabled_message = poke_disabled_message or mute_message( fleet_switch )

    # The skeleton crew switch is the third input. It has one stored value, the key in the
    # main configuration file, read here at read time, so the poke has no copy of its own.
    # A key that is absent or unreadable never mutes.
    if poke_output_enabled:
        try:
            from lupin_mcp import skeleton_crew
            skeleton_on = skeleton_crew.is_on_quietly()
        except Exception:
            skeleton_on = False       # a hook that cannot ask leaves the poke on, never off
        if skeleton_on:
            poke_output_enabled   = False
            poke_disabled_message = poke_disabled_message or SKELETON_CREW_POKE_MESSAGE

    return {
        "enabled"                        : enabled,
        "poke_cap"                       : poke_cap,
        "count_inbound_questions_as_owed": count_inbound,
        "owed_source_from_store"         : owed_source_from_store,
        "verification_threshold_seconds" : verification_threshold,
        "poke_output_enabled"            : poke_output_enabled,
        "poke_disabled_message"          : poke_disabled_message,
    }


def _defaults() -> dict:
    """Return a fresh copy of the defaults."""
    return {
        "enabled"                        : DEFAULT_ENABLED,
        "poke_cap"                       : DEFAULT_POKE_CAP,
        "count_inbound_questions_as_owed": DEFAULT_COUNT_INBOUND_AS_OWED,
        "owed_source_from_store"         : DEFAULT_OWED_SOURCE_FROM_STORE,
        "verification_threshold_seconds" : DEFAULT_VERIFICATION_THRESHOLD_SECONDS,
        "poke_output_enabled"            : DEFAULT_POKE_OUTPUT_ENABLED,
        "poke_disabled_message"          : DEFAULT_POKE_DISABLED_MESSAGE,
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


def _normalize_poke_disabled_message( value: Any ) -> str:
    """
    Normalize the mute-substitute message to a plain string.

    None is the other documented spelling of "emit nothing", like an empty string, so it normalizes
    to "" rather than raising. Any other non-string is fail-loud. The text is emitted verbatim into the
    worker's Stop-hook output, where a dict, int or list is garbage that looks like a real obligation.

    Requires:
        - value is anything (foreign settings data)

    Ensures:
        - None → ""
        - str  → returned unchanged (including "")
        - anything else → raises ValueError
    """
    if value is None:
        return ""
    if not isinstance( value, str ):
        raise ValueError(
            f"heartbeat.poke_disabled_message must be a string or null, "
            f"got {type( value ).__name__}: {value!r}"
        )
    return value


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
                  "verification_threshold_seconds": DEFAULT_VERIFICATION_THRESHOLD_SECONDS,
                  "poke_output_enabled": True,
                  "poke_disabled_message": "" }, d

    # Mute-substitute normalization: None and "" both mean "emit nothing"
    assert _normalize_poke_disabled_message( None ) == ""
    assert _normalize_poke_disabled_message( "" ) == ""
    assert _normalize_poke_disabled_message( "carry on" ) == "carry on"

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
    assert isinstance( loaded[ "poke_output_enabled" ], bool )
    assert isinstance( loaded[ "poke_disabled_message" ], str )

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_settings smoke: {'PASS' if ok else 'FAIL'}" )
