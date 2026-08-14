"""
Self-re-spin liveness observer — the external check that a manager which typed
`/clear` into its OWN pane actually came back, at low context, as the same seat.

WHY THIS EXISTS (row 9e0678f6, work item 1 — ships BEFORE the self_respin verb).
A session that fires a self-clear cannot report its own outcome: it no longer
holds the context that knew it was trying. A manager that fires and does not
return is a silently dead seat — the exact failure the whole self-re-spin policy
exists to prevent. So an EXTERNAL observer (the arbiter, or a peer manager) must
verify the seat cleared and came back.

THE ORACLE (Krishna's gate). "Came back at low context" is NOT "the seat is
alive" — a seat that never cleared is also alive, so a bare alive-check greens
whether or not the clear happened. The observer instead reads a real transition
in the arbiter's OWN context-pressure payload: the marker records that the seat
was `over_budget` (that is WHY the tick fired self_respin); RETURNED is that SAME
seat now reading `within_budget`, with a fresh turn dated after the clear fired.
There is no second "low" threshold — observer and verb share the ONE INI budget
fraction via the payload's `status` field, so they can never disagree on "low."

PURITY. `classify_marker` is a pure function of (marker, pressure_record, now) —
stdlib only, no IO. The fleet helper `observe_fleet_self_respin` does the disk
glob + the pressure fetch behind an injectable `fetch_pressure` seam, so both the
alarm arm and the negative arm are unit-provable with fakes.

Design note: planning-is-prompting/src/rnd/2026.08.13-manager-self-respin-mechanism.md
"""

import datetime
import glob
import json
import os

from dataclasses import dataclass
from enum        import Enum


# The on-disk marker filename shape: <MARKER_PREFIX><session_id>.json, living
# under fleet_data_root() (never the repo root — the same placement discipline
# as heartbeat holds, so the fleet's readers actually see it).
MARKER_PREFIX = ".self-respin-"

# How much slack past (fired_at + delay) before a still-not-returned seat is
# declared dead. The verb writes expected_return_by = fired_at + delay + grace;
# this default only feeds build_marker_dict when a caller omits grace.
DEFAULT_GRACE_SECONDS = 120


class SelfRespinVerdict( str, Enum ):
    PENDING           = "PENDING"            # in flight; inside the window, not yet a proven return
    RETURNED          = "RETURNED"           # over_budget → within_budget, same seat, fresh turn
    DEAD_NO_RETURN    = "DEAD_NO_RETURN"     # ALARM: past deadline with no proven return
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"  # ALARM: a seat came back under this marker's session_id
                                             #        but a different tmux/session identity
    MALFORMED_MARKER  = "MALFORMED_MARKER"   # ALARM: a timestamp is missing/naive/unparseable, so the
                                             #        marker cannot be time-judged — surfaced LOUDLY, never
                                             #        degraded to the benign PENDING (a seat that never came
                                             #        back must never look like patience — Cheech's gate)


@dataclass
class SelfRespinAssessment:
    """One marker's verdict + the human-readable reason + the alarm flag."""
    session_id : str
    persona    : str
    verdict    : SelfRespinVerdict
    reason     : str
    is_alarm   : bool


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------
def _parse_iso( value ):
    """
    Parse an ISO-8601 string into an AWARE datetime, defensively.

    Requires:
        - value is anything (str / None / other)

    Ensures:
        - returns an aware datetime for a well-formed ISO-8601 string that
          carries a timezone offset
        - returns None for None, a non-string, an unparseable string, OR a
          NAIVE (offset-less) datetime — a naive value cannot be compared to the
          aware `now` without raising TypeError, so it is treated as "cannot
          judge" (NOT confirmed / PENDING) rather than crashing the observer.
          Every marker this module writes is aware (build_marker_dict stamps
          `.isoformat()` of an aware datetime); a naive value is a hand-written
          or legacy artifact and must not break the never-raises contract.
        - never raises
    """
    if not isinstance( value, str ):
        return None
    try:
        parsed = datetime.datetime.fromisoformat( value )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


# ---------------------------------------------------------------------------
# Marker schema constructor — ONE shape shared by the verb (writer) and here
# ---------------------------------------------------------------------------
def build_marker_dict( *, session_id, persona, tmux_session, fired_at, delay_seconds,
                       pre_clear_status, pre_clear_pct, memento_path, memento_verified,
                       grace_seconds=DEFAULT_GRACE_SECONDS ):
    """
    Build the self-re-spin marker dict the verb writes to disk BEFORE it schedules
    the clear (the pre-clear facts must survive the context wipe — the cleared
    session cannot report them).

    Requires:
        - fired_at is an aware datetime (the moment the clear is scheduled)
        - delay_seconds, grace_seconds are non-negative numbers
        - pre_clear_status is the seat's `status` at fire time ("over_budget"
          in every real firing — the tick only fires when the seat is over budget)

    Ensures:
        - returns the full marker dict with expected_return_by =
          fired_at + delay_seconds + grace_seconds (ISO-8601)
        - all fields JSON-serializable
    """
    # Normalize to aware UTC so our OWN markers can never reach the malformed
    # (naive-timestamp) path — the observer only sees aware timestamps from us.
    if fired_at.tzinfo is None:
        fired_at = fired_at.replace( tzinfo=datetime.timezone.utc )
    deadline = fired_at + datetime.timedelta( seconds=delay_seconds + grace_seconds )
    return {
        "session_id"         : session_id,
        "persona"            : persona,
        "tmux_session"       : tmux_session,
        "fired_at"           : fired_at.isoformat(),
        "expected_return_by" : deadline.isoformat(),
        "pre_clear_status"   : pre_clear_status,
        "pre_clear_pct"      : pre_clear_pct,
        "memento_path"       : memento_path,
        "memento_verified"   : memento_verified,
    }


# ---------------------------------------------------------------------------
# The pure classifier — the whole oracle lives here
# ---------------------------------------------------------------------------
def _identity_matches( marker, pressure_record ):
    """
    Ensures:
        - True iff the pressure record's session_id AND tmux_session both equal
          the marker's — i.e. the seat came back as the SAME seat (Cheech's gate)
    """
    return (
        pressure_record.get( "session_id" )   == marker.get( "session_id" ) and
        pressure_record.get( "tmux_session" ) == marker.get( "tmux_session" )
    )


def _is_confirmed_return( marker, pressure_record, fired_at, now ):
    """
    Is this a proven over_budget → within_budget return for the same seat?

    Requires:
        - pressure_record is a dict (the matched record; caller guarantees non-None)
        - fired_at is an aware datetime (the caller parsed + validated it)
        - now is an aware datetime

    Ensures:
        - True iff ALL hold:
            * the marker recorded pre_clear_status == "over_budget" (there was a
              high state to fall FROM — no transition otherwise)
            * the record's current status == "within_budget" (fell to low)
            * the record's last turn is FRESH: dated at/after the marker's
              fired_at (a stale low reading from before the clear proves nothing)
        - a missing last_turn_age_s ⇒ not confirmed
        - never raises
    """
    if marker.get( "pre_clear_status" ) != "over_budget":
        return False
    if pressure_record.get( "status" ) != "within_budget":
        return False

    age = pressure_record.get( "last_turn_age_s" )
    if not isinstance( age, ( int, float ) ):
        return False

    last_turn_ts = now - datetime.timedelta( seconds=age )
    return last_turn_ts >= fired_at


def classify_marker( marker, pressure_record, *, now ):
    """
    Classify ONE self-re-spin marker against the seat's live pressure record.

    Requires:
        - marker is a parsed marker dict (build_marker_dict shape)
        - pressure_record is the arbiter context_pressure record for the SAME
          session_id, or None when the seat is absent from the pressure map
        - now is an aware datetime

    Ensures:
        - MALFORMED_MARKER (alarm) when fired_at OR expected_return_by is missing,
          naive, or unparseable — the marker cannot be time-judged, and degrading
          it to PENDING would let a dead seat hide behind permanent "patience"
          (Cheech's gate). Surfaced loudly BEFORE any other verdict.
        - IDENTITY_MISMATCH (alarm) when a record exists but its session_id/
          tmux_session disagree with the marker — a different seat answered
        - RETURNED (no alarm) on a confirmed over→within transition, same seat,
          fresh turn after fired_at
        - DEAD_NO_RETURN (alarm) when not returned AND now >= expected_return_by
        - PENDING (no alarm) otherwise (inside the window)
        - never raises
    """
    session_id = marker.get( "session_id", "" )
    persona    = marker.get( "persona", "" )

    # A marker we cannot place in time is UNTRUSTWORTHY, not patient. Parse both
    # timestamps up front; either one missing/naive/unparseable ⇒ a loud alarm.
    # Our own writer stamps aware UTC, so this only fires on a corrupt or
    # hand-written marker — and when it does, it must be seen, not silently held.
    fired_at = _parse_iso( marker.get( "fired_at" ) )
    deadline = _parse_iso( marker.get( "expected_return_by" ) )
    if fired_at is None or deadline is None:
        return SelfRespinAssessment(
            session_id = session_id,
            persona    = persona,
            verdict    = SelfRespinVerdict.MALFORMED_MARKER,
            reason     = "fired_at/expected_return_by missing, naive, or unparseable — marker cannot be time-judged",
            is_alarm   = True,
        )

    if pressure_record is not None:
        if not _identity_matches( marker, pressure_record ):
            return SelfRespinAssessment(
                session_id = session_id,
                persona    = persona,
                verdict    = SelfRespinVerdict.IDENTITY_MISMATCH,
                reason     = "a seat answered under this marker but its session_id/tmux differ — different seat",
                is_alarm   = True,
            )
        if _is_confirmed_return( marker, pressure_record, fired_at, now ):
            return SelfRespinAssessment(
                session_id = session_id,
                persona    = persona,
                verdict    = SelfRespinVerdict.RETURNED,
                reason     = "over_budget → within_budget on the same seat, fresh turn after the clear fired",
                is_alarm   = False,
            )

    if now >= deadline:
        return SelfRespinAssessment(
            session_id = session_id,
            persona    = persona,
            verdict    = SelfRespinVerdict.DEAD_NO_RETURN,
            reason     = "past expected_return_by with no proven return — fired and did not come back",
            is_alarm   = True,
        )

    return SelfRespinAssessment(
        session_id = session_id,
        persona    = persona,
        verdict    = SelfRespinVerdict.PENDING,
        reason     = "in flight — inside the return window, no confirmed return yet",
        is_alarm   = False,
    )


# ---------------------------------------------------------------------------
# Disk read — glob markers under a base dir (fleet_data_root by default)
# ---------------------------------------------------------------------------
def read_markers( base_dir=None ):
    """
    Read every self-re-spin marker under `base_dir`, skipping unreadable ones.

    Requires:
        - base_dir is a directory path or None (None ⇒ fleet_data_root(), lazily)

    Ensures:
        - returns a list of parsed marker dicts (may be empty)
        - a missing directory ⇒ [] (not an error — nothing has fired)
        - a malformed / unreadable marker file is skipped, never propagated
        - never raises
    """
    base = _resolve_base_dir( base_dir )
    results = []
    for path in sorted( glob.glob( os.path.join( base, f"{MARKER_PREFIX}*.json" ) ) ):
        try:
            with open( path, "r" ) as f:
                obj = json.load( f )
        except ( OSError, ValueError ):
            continue
        if isinstance( obj, dict ):
            results.append( obj )
    return results


def _resolve_base_dir( base_dir ):
    """
    Ensures:
        - returns base_dir when provided (tests + explicit callers win)
        - returns fleet_data_root() (lazily imported to keep this leaf pure) when None
    """
    if base_dir is not None:
        return base_dir
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root   # lazy: keep the leaf pure
    return str( fleet_data_root() )


# ---------------------------------------------------------------------------
# Fleet helper — glob markers, fetch pressure, match by session_id, classify
# ---------------------------------------------------------------------------
def observe_fleet_self_respin( *, base_dir=None, now=None, fetch_pressure=None ):
    """
    Assess every in-flight self-re-spin against the live context-pressure payload.

    Requires:
        - base_dir is a directory path or None (None ⇒ fleet_data_root())
        - now is an aware datetime or None (None ⇒ datetime.now(UTC))
        - fetch_pressure is a zero-arg callable returning the context_pressure
          section (a { "personas": { persona: record } } dict), or None to use
          the live :7999 reverse-proxy reader

    Ensures:
        - returns a list[ SelfRespinAssessment ], one per marker on disk
        - each marker is matched to its pressure record BY session_id (a record
          keyed under a persona the marker did not name still matches on id)
        - an unreachable pressure fetch (personas None/missing) ⇒ every marker is
          classified with a None record (PENDING inside the window, DEAD past it)
        - never raises on a single bad marker
    """
    if now is None:
        now = datetime.datetime.now( datetime.timezone.utc )
    if fetch_pressure is None:
        fetch_pressure = _fetch_live_pressure

    markers = read_markers( base_dir )
    if not markers:
        return []

    section  = fetch_pressure() or {}
    personas = section.get( "personas" ) if isinstance( section, dict ) else None
    by_id    = {}
    if isinstance( personas, dict ):
        for record in personas.values():
            if isinstance( record, dict ) and record.get( "session_id" ):
                by_id[ record[ "session_id" ] ] = record

    return [
        classify_marker( m, by_id.get( m.get( "session_id" ) ), now=now )
        for m in markers
    ]


def _fetch_live_pressure():   # pragma: no cover - live HTTP boundary, exercised via injected fetch in tests
    """
    Fetch the live `context_pressure` section from the arbiter state service.

    Ensures:
        - returns the section dict, or { "personas": None } on any failure
        - never raises
    """
    try:
        import httpx
        from cosa.rest.dependencies.config import get_config_manager
        config_mgr = get_config_manager()
        url     = config_mgr.get( "arbiter vigilance state url", default="http://127.0.0.1:8001/state" )
        timeout = config_mgr.get( "arbiter vigilance state timeout seconds", default=5, return_type="int" )
        state   = httpx.get( url, timeout=timeout ).raise_for_status().json()
        section = state.get( "context_pressure" ) if isinstance( state, dict ) else None
        return section if section is not None else { "personas": None }
    except Exception:
        return { "personas": None }


# ---------------------------------------------------------------------------
# Rendering + smoke
# ---------------------------------------------------------------------------
def render_observer_table( assessments ):
    """
    Ensures:
        - returns a multi-line string: header + one row per assessment
        - a friendly one-liner when there are no markers
    """
    if not assessments:
        return "(no self-re-spin markers in flight)"
    header = f"{'PERSONA':<12} {'SESSION':<10} {'VERDICT':<18} {'ALARM':<6} REASON"
    rows   = [ header, "-" * len( header ) ]
    for a in assessments:
        alarm = "ALARM" if a.is_alarm else ""
        rows.append( f"{a.persona:<12} {a.session_id[:8]:<10} {a.verdict.value:<18} {alarm:<6} {a.reason}" )
    return "\n".join( rows )


def quick_smoke_test():
    """Print the live self-re-spin observer table (read-only, :7999-safe)."""
    print( "Assessing in-flight self-re-spin markers...\n" )
    assessments = observe_fleet_self_respin()
    print( render_observer_table( assessments ) )


if __name__ == "__main__":   # pragma: no cover - CLI entry point, exercised via quick_smoke_test() in tests
    quick_smoke_test()
