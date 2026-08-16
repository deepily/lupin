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
import threading

from dataclasses import dataclass
from enum        import Enum


# The on-disk marker filename shape: <MARKER_PREFIX><session_id>.json, living
# under fleet_data_root() (never the repo root — the same placement discipline
# as heartbeat holds, so the fleet's readers actually see it).
MARKER_PREFIX = ".self-respin-"

# The WAKE PROOF (row 275cb0b9 follow-up, John's ruling). Two failure modes had to
# close at once:
#   (1) STRANGER'S HELLO — the over_budget→within_budget-with-a-fresh-turn transition
#       cannot tell a self-wake from a colleague's DM: any fresh turn satisfies it.
#   (2) INJECTOR SELF-CERTIFICATION — a receipt WRITTEN BY THE INJECTOR proves only
#       that the injector reached the write line, never that the pane INGESTED the
#       keystrokes (`tmux send-keys` has no ingestion feedback) — the exit-code defect
#       one layer out.
# Both close with a CONSUMER-WRITTEN, NONCE-BOUND proof. The verb mints a nonce into
# the marker; the wake text instructs the rehydrated seat to write THIS artifact
# echoing that nonce. RETURNED requires the artifact to exist, ECHO THE MARKER'S
# NONCE, and be dated after the clear fired — plus the budget transition. Only a seat
# that actually took a turn on our wake can produce it (proving ingestion → a real
# turn, stronger than "reached the pane"), and a peer DM cannot forge it (it does not
# know the nonce) — the stranger's hole closes BY CONSTRUCTION, the same way the
# memento nonce proves a this-cycle memento. Mechanism-agnostic: whatever delivers the
# wake (this injector or a future peer-message path), the CONSUMER writes the proof.
WAKE_PROOF_PREFIX      = ".self-respin-wake-proof-"
WAKE_PROOF_NONCE_LINE  = "SELF-RESPIN-WAKE-PROOF:"     # the seat writes: "SELF-RESPIN-WAKE-PROOF: <nonce>"

# How much slack past (fired_at + delay) before a still-not-returned seat is
# declared dead. The verb writes expected_return_by = fired_at + delay + grace;
# this default only feeds build_marker_dict when a caller omits grace.
DEFAULT_GRACE_SECONDS = 120

# How long a CONFIRMED-RETURNED marker is kept before the janitor sweeps it. A
# RETURNED marker has done its whole job — it proved the seat came back — so it
# is pure accumulation from then on. The TTL is deliberately long relative to the
# 60s observer cadence (~15 ticks) so the RETURN is witnessed many times before
# the record is deleted; the sweep NEVER touches a PENDING or alarm marker, whose
# job is not yet done. Only RETURNED + older-than-TTL is swept.
DEFAULT_RETURNED_TTL_SECONDS = 900


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
                       wake_nonce=None, grace_seconds=DEFAULT_GRACE_SECONDS ):
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
        "wake_nonce"         : wake_nonce,     # the seat must echo THIS in its wake proof for RETURNED
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


def _is_confirmed_return( marker, pressure_record, fired_at, now, wake_proof_nonce, wake_proof_at ):
    """
    Is this a proven over_budget → within_budget return for the same seat, woken by
    OUR OWN wake (not a stranger's hello) and PROVEN by the seat's own turn?

    Requires:
        - pressure_record is a dict (the matched record; caller guarantees non-None)
        - fired_at is an aware datetime (the caller parsed + validated it)
        - now is an aware datetime
        - wake_proof_nonce is the nonce the rehydrated seat ECHOED in its wake proof
          artifact (str), or None when no proof exists
        - wake_proof_at is the aware datetime that proof was written, or None

    Ensures:
        - True iff ALL hold:
            * the marker recorded pre_clear_status == "over_budget" (there was a
              high state to fall FROM — no transition otherwise)
            * the record's current status == "within_budget" (fell to low)
            * the record's last turn is FRESH: dated at/after the marker's fired_at
            * a WAKE PROOF exists, written at/after fired_at, whose nonce EQUALS the
              marker's own wake_nonce. This is CONSUMER-written (the seat had to take a
              turn on our wake to produce it — proving ingestion, not just delivery)
              and NONCE-BOUND (a peer DM cannot forge it — it does not know the nonce).
              A blank marker nonce can never be matched, so a marker minted without a
              nonce is never falsely RETURNED.
        - a missing last_turn_age_s ⇒ not confirmed
        - a missing / pre-fire / nonce-mismatched proof ⇒ not confirmed
        - never raises
    """
    if marker.get( "pre_clear_status" ) != "over_budget":
        return False
    if pressure_record.get( "status" ) != "within_budget":
        return False

    marker_nonce = marker.get( "wake_nonce" )
    if not marker_nonce or wake_proof_nonce != marker_nonce:
        return False
    if wake_proof_at is None or wake_proof_at < fired_at:
        return False

    age = pressure_record.get( "last_turn_age_s" )
    if not isinstance( age, ( int, float ) ):
        return False

    last_turn_ts = now - datetime.timedelta( seconds=age )
    return last_turn_ts >= fired_at


def classify_marker( marker, pressure_record, *, now, wake_proof_nonce=None, wake_proof_at=None ):
    """
    Classify ONE self-re-spin marker against the seat's live pressure record.

    Requires:
        - marker is a parsed marker dict (build_marker_dict shape)
        - pressure_record is the arbiter context_pressure record for the SAME
          session_id, or None when the seat is absent from the pressure map
        - now is an aware datetime
        - wake_proof_nonce / wake_proof_at describe the seat's consumer-written wake
          proof (the nonce it echoed + when), or None/None when no proof exists —
          RETURNED requires a proof whose nonce matches the marker's own wake_nonce

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
        if _is_confirmed_return( marker, pressure_record, fired_at, now, wake_proof_nonce, wake_proof_at ):
            return SelfRespinAssessment(
                session_id = session_id,
                persona    = persona,
                verdict    = SelfRespinVerdict.RETURNED,
                reason     = "over_budget → within_budget on the same seat, fresh turn AND a nonce-matched wake proof after the clear fired",
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


def wake_proof_path( base, session_id ):
    """Ensures: the canonical wake-proof artifact path for `session_id` (the ONE shape
    the verb tells the seat to write and the observer reads back)."""
    return os.path.join( base, f"{WAKE_PROOF_PREFIX}{session_id}.marker" )


def read_wake_proof( base, session_id ):
    """
    Read the CONSUMER-written wake proof for `session_id` — the artifact the rehydrated
    seat writes, echoing the marker's nonce, once it takes a turn on our wake.

    Requires:
        - base is a resolved directory path; session_id is the seat's id

    Ensures:
        - returns ( nonce, proof_at ): the nonce the seat echoed on the
          `SELF-RESPIN-WAKE-PROOF: <nonce>` line, and the file's mtime as an aware UTC
          datetime. The nonce is the token proving the wake reached a TURN and was OURS
          (a peer cannot echo an unknown nonce).
        - ( None, None ) when the artifact is absent, unreadable, or carries no
          proof-nonce line — no proof ⇒ the oracle will not confirm RETURNED
        - never raises
    """
    if not session_id:
        return ( None, None )
    path = wake_proof_path( base, session_id )
    try:
        proof_at = datetime.datetime.fromtimestamp( os.path.getmtime( path ), tz=datetime.timezone.utc )
        with open( path, "r" ) as f:
            content = f.read()
    except OSError:
        return ( None, None )
    nonce  = None
    needle = f"{WAKE_PROOF_NONCE_LINE} "
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith( needle ):
            nonce = stripped[ len( needle ): ].strip() or None
            break
    return ( nonce, proof_at )


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

    base     = _resolve_base_dir( base_dir )
    section  = fetch_pressure() or {}
    personas = section.get( "personas" ) if isinstance( section, dict ) else None
    by_id    = {}
    if isinstance( personas, dict ):
        for record in personas.values():
            if isinstance( record, dict ) and record.get( "session_id" ):
                by_id[ record[ "session_id" ] ] = record

    def _classify( m ):
        nonce, proof_at = read_wake_proof( base, m.get( "session_id" ) )
        return classify_marker(
            m, by_id.get( m.get( "session_id" ) ), now=now,
            wake_proof_nonce=nonce, wake_proof_at=proof_at,
        )
    return [ _classify( m ) for m in markers ]


# ---------------------------------------------------------------------------
# The janitor — TTL-sweep confirmed-RETURNED markers so they don't accumulate
#
# WHY (row 6d6a9da2). A successful self-respin leaves its .self-respin-<sid>.json
# marker on disk forever — the verb never removes it (it is cleared before it
# could), and the observer keeps re-classifying it RETURNED every tick. That is
# harmless but unbounded. This sweep deletes a marker ONLY once it is BOTH
# confirmed-RETURNED (the observer's own oracle said so — this reuses
# classify_marker read-only, it does NOT reimplement the verdict) AND older than
# the TTL (so many ticks have witnessed the RETURN first). A PENDING marker (job
# not done) or any alarm marker (DEAD_NO_RETURN / IDENTITY_MISMATCH /
# MALFORMED_MARKER — must stay visible) is NEVER swept.
# ---------------------------------------------------------------------------
def _read_markers_with_paths( base_dir=None ):
    """
    Like read_markers, but pairs each parsed marker with its file path so the
    janitor can delete it. Kept separate so read_markers stays untouched.

    Ensures:
        - returns a list of ( path, marker_dict ), sorted by path
        - a missing directory ⇒ [] ; an unreadable/malformed file is skipped
        - never raises
    """
    base    = _resolve_base_dir( base_dir )
    results = []
    for path in sorted( glob.glob( os.path.join( base, f"{MARKER_PREFIX}*.json" ) ) ):
        try:
            with open( path, "r" ) as f:
                obj = json.load( f )
        except ( OSError, ValueError ):
            continue
        if isinstance( obj, dict ):
            results.append( ( path, obj ) )
    return results


def _best_effort_unlink( path ):
    """Ensures: removes `path`, returning True on success and False on any OSError; never raises."""
    try:
        os.remove( path )
        return True
    except OSError:
        return False


def sweep_returned_markers( *, base_dir=None, now=None, fetch_pressure=None,
                            ttl_seconds=DEFAULT_RETURNED_TTL_SECONDS ):
    """
    Delete self-re-spin markers that are DONE: confirmed RETURNED AND older than
    the TTL. Hygiene only — the verb and observer both work without it.

    Requires:
        - base_dir is a directory path or None (None ⇒ fleet_data_root())
        - now is an aware datetime or None (None ⇒ datetime.now(UTC))
        - fetch_pressure is a zero-arg callable returning the context_pressure
          section, or None to use the live reader
        - ttl_seconds is a non-negative number of seconds

    Ensures:
        - returns the list of session_ids whose markers were deleted (may be empty)
        - deletes a marker IFF classify_marker(...) == RETURNED AND
          (now - fired_at) > ttl_seconds — a RETURNED verdict guarantees the
          classifier already parsed fired_at, so no separate parse-guard is needed
        - a marker that is PENDING, any alarm verdict, or RETURNED-but-younger than
          the TTL is LEFT in place
        - reuses classify_marker READ-ONLY (the oracle is not reimplemented here)
        - a failed unlink is skipped (not counted, not raised)
        - never raises on a single bad marker or an unreachable pressure fetch
    """
    if now is None:
        now = datetime.datetime.now( datetime.timezone.utc )
    if fetch_pressure is None:
        fetch_pressure = _fetch_live_pressure

    pairs = _read_markers_with_paths( base_dir )
    if not pairs:
        return []

    base     = _resolve_base_dir( base_dir )
    section  = fetch_pressure() or {}
    personas = section.get( "personas" ) if isinstance( section, dict ) else None
    by_id    = {}
    if isinstance( personas, dict ):
        for record in personas.values():
            if isinstance( record, dict ) and record.get( "session_id" ):
                by_id[ record[ "session_id" ] ] = record

    swept = []
    for path, marker in pairs:
        nonce, proof_at = read_wake_proof( base, marker.get( "session_id" ) )
        assessment = classify_marker(
            marker, by_id.get( marker.get( "session_id" ) ), now=now,
            wake_proof_nonce=nonce, wake_proof_at=proof_at,
        )
        if assessment.verdict is not SelfRespinVerdict.RETURNED:
            continue
        # RETURNED ⇒ classify_marker parsed fired_at (else it would be MALFORMED),
        # so this parse always yields an aware datetime.
        fired_at = _parse_iso( marker.get( "fired_at" ) )
        if ( now - fired_at ).total_seconds() <= ttl_seconds:
            continue
        if _best_effort_unlink( path ):
            # the proof has done its job too (it proved the RETURN) — sweep it with the
            # marker so proofs don't accumulate. Best-effort; a missing one is fine (the
            # marker is already gone, so nothing re-reads it).
            _best_effort_unlink( wake_proof_path( base, marker.get( "session_id" ) ) )
            swept.append( marker.get( "session_id" ) )
    return swept


def _fetch_live_pressure():   # pragma: no cover - live HTTP boundary, exercised via injected fetch in tests
    """
    Fetch the live `context_pressure` section from the arbiter state service.

    HOST-SIDE reader. Every caller of this function — the self_respin MCP verb's
    `_live_own_pressure` and the observer loop's default fetch — runs on the HOST
    (the MCP child in a tmux pane; the arbiter as a `systemctl --user` service),
    NOT in a container. So it reads `arbiter local state url` (loopback,
    http://127.0.0.1:8001/state), NEVER the container-scoped `arbiter vigilance
    state url` (http://host.docker.internal:8001/state) — that hostname does not
    resolve on the host, and reading it made EVERY self_respin marker record
    pre_clear_status "unknown" (row 275cb0b9). The :7999 reverse-proxy router keeps
    reading the vigilance key directly; it is unaffected.

    Ensures:
        - returns the section dict, or { "personas": None } on any failure
        - never raises
    """
    try:
        import httpx
        from cosa.rest.dependencies.config import get_config_manager
        config_mgr = get_config_manager()
        url     = config_mgr.get( "arbiter local state url", default="http://127.0.0.1:8001/state" )
        timeout = config_mgr.get( "arbiter vigilance state timeout seconds", default=5, return_type="int" )
        state   = httpx.get( url, timeout=timeout ).raise_for_status().json()
        section = state.get( "context_pressure" ) if isinstance( state, dict ) else None
        return section if section is not None else { "personas": None }
    except Exception:
        return { "personas": None }


# ---------------------------------------------------------------------------
# The daemon loop — the PRODUCTION caller the observer never had (row 275cb0b9,
# GAP 2). observe_fleet_self_respin + sweep_returned_markers had NO caller outside
# quick_smoke_test, so DEAD_NO_RETURN never fired and RETURNED markers never swept
# (11 piled up, oldest 2026-08-13). This runs both on the arbiter's live tick,
# mirroring TurnAgeWatchdog: INI-gated (default OFF → start() no-ops, sweep_once
# does zero work), injectable seams, one-shot-per-alarm flood guard, daemon lifecycle.
# ---------------------------------------------------------------------------
class SelfRespinObserverLoop:
    """
    Standing self-re-spin liveness loop. Inert unless `arbiter self respin observer
    enabled` is True. Each tick it (a) classifies every in-flight marker against the
    live pressure and fires ONE advisory per alarm marker (DEAD_NO_RETURN /
    IDENTITY_MISMATCH / MALFORMED_MARKER), and (b) sweeps confirmed-RETURNED markers
    past their TTL. The pressure read, advisory sink, clock, and marker base dir are
    ALL injectable, so the detection + flood-guard logic is unit-provable with fakes.
    """

    def __init__(
        self,
        config_mgr,
        *,
        fetch_pressure_fn = None,
        base_dir          = None,
        advisory_fn       = None,
        now_fn            = None,
    ):
        """
        Requires:
            - config_mgr exposes .get( key, default=, return_type= )
            - fetch_pressure_fn() -> the context_pressure section ({personas: {...}}),
              or None to use the live host-loopback reader. Production injects an
              IN-PROCESS store read (the arbiter already holds the section — no HTTP
              self-call); tests inject a fake.
            - base_dir is the marker directory or None (None ⇒ fleet_data_root())
            - advisory_fn( message ) -> None emits ONE operator advisory (default: a
              banner print; production injects the throttled escalation rail)
            - now_fn() -> aware datetime (default: datetime.now(utc))

        Ensures:
            - no thread is started at construction (call start() explicitly)
            - the one-shot `_advised` marker set starts empty
        """
        self._config_mgr        = config_mgr
        self._fetch_pressure_fn = fetch_pressure_fn
        self._base_dir          = base_dir
        self._advisory_fn       = advisory_fn if advisory_fn is not None else self._default_advisory_signal
        self._now_fn            = now_fn      if now_fn      is not None else ( lambda: datetime.datetime.now( datetime.timezone.utc ) )
        self._advised           = set()       # (session_id, verdict) advised once — flood-guard one-shot
        self._stop_event        = threading.Event()
        self._thread            = None

    # -- config accessors -----------------------------------------------------

    def _enabled( self ) -> bool:
        return self._config_mgr.get( "arbiter self respin observer enabled", default=False, return_type="boolean" )

    def _tick_seconds( self ) -> int:
        # the SAME live tick the :8001 fleet-arbiter loop polls on (no separate knob).
        return self._config_mgr.get( "arbiter poll seconds", default=60, return_type="int" )

    def _returned_ttl_seconds( self ) -> int:
        return self._config_mgr.get(
            "arbiter self respin observer returned ttl seconds",
            default=DEFAULT_RETURNED_TTL_SECONDS, return_type="int",
        )

    # -- core (unit-testable, no thread) --------------------------------------

    def sweep_once( self ) -> dict:
        """
        Run one observe + sweep pass.

        Ensures:
            - flag OFF -> no IO; returns {enabled:False, alarms:0, advised:0, swept:0}
            - flag ON  -> classify every marker; fire ONE advisory per alarm marker
              (one-shot per (session_id, verdict) — a still-alarming marker across
              ticks fires nothing more), then sweep confirmed-RETURNED-past-TTL markers
            - `_advised` is intersected with the live alarm set after the pass, so a
              marker that stops alarming (swept, or came back) drops its one-shot key
            - never raises: observe/sweep already swallow per-marker errors; a total
              failure is caught and demoted to a zero summary so the daemon survives

        Returns:
            { "enabled": bool, "alarms": int, "advised": int, "swept": int }
        """
        if not self._enabled():
            return { "enabled": False, "alarms": 0, "advised": 0, "swept": 0 }

        now     = self._now_fn()
        advised = 0
        alarms  = 0
        live    = set()                                # (session_id, verdict) alarming this pass
        try:
            assessments = observe_fleet_self_respin(
                base_dir=self._base_dir, now=now, fetch_pressure=self._fetch_pressure_fn )
            for a in assessments:
                if not a.is_alarm:
                    continue
                alarms += 1
                key = ( a.session_id, a.verdict.value )
                live.add( key )
                if key in self._advised:
                    continue                           # one-shot — already advised this alarm
                self._emit_advisory( a )
                self._advised.add( key )
                advised += 1

            swept = len( sweep_returned_markers(
                base_dir=self._base_dir, now=now, fetch_pressure=self._fetch_pressure_fn,
                ttl_seconds=self._returned_ttl_seconds() ) )
        except Exception as e:                         # observer invariant: never kill the daemon
            self._log_skip( f"self-respin observer sweep error (continuing): {e!r}" )
            return { "enabled": True, "alarms": alarms, "advised": advised, "swept": 0 }

        # flood-guard clear: an alarm that is gone (returned or swept) drops its marker
        self._advised &= live
        return { "enabled": True, "alarms": alarms, "advised": advised, "swept": swept }

    def _emit_advisory( self, assessment ) -> None:
        """
        Compose + fire the ONE operator advisory for an alarming marker.

        Ensures:
            - names the persona/session, the verdict, and the reason; delegates
              delivery to the injected advisory_fn; never raises (sweep_once guards)
        """
        message = (
            f"SELF-RESPIN OBSERVER — {assessment.verdict.value} for session "
            f"{assessment.session_id} (persona {assessment.persona or 'unknown'}): "
            f"{assessment.reason}. A manager typed /clear into its own pane and the "
            f"observer cannot confirm it came back at low context."
        )
        self._advisory_fn( message )

    # -- default IO boundaries (pragma'd — injected fakes exercise the logic) --

    def _default_advisory_signal( self, message ) -> None:   # pragma: no cover - default sink; production injects the rail
        """Default advisory sink: a plain print (production injects the escalation rail)."""
        print( f"[self-respin-observer] {message}" )

    def _log_skip( self, message ) -> None:   # pragma: no cover - diagnostic print boundary
        print( message )

    # -- daemon lifecycle -----------------------------------------------------

    def _loop( self ) -> None:   # pragma: no cover - thread body; sweep_once covered directly
        """Daemon loop until stop(); each sweep is exception-guarded so a transient error never kills it."""
        while not self._stop_event.is_set():
            try:
                self.sweep_once()
            except Exception as e:
                self._log_skip( f"self-respin observer loop caught exception (continuing): {e!r}" )
            self._stop_event.wait( timeout=self._tick_seconds() )

    def start( self ) -> bool:
        """
        Spawn the daemon thread — ONLY if the flag is enabled and no thread runs.
        Returns True if a thread was started, else False (the no-op rollout gate).
        """
        if not self._enabled():
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread( target=self._loop, daemon=True, name="SelfRespinObserverLoop" )
        self._thread.start()
        return True

    def stop( self, timeout: float = 5.0 ) -> None:
        """Signal the daemon to exit and join it (idempotent — safe if never started)."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join( timeout=timeout )


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
