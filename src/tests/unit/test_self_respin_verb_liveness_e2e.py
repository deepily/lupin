#!/usr/bin/env python3
"""
Whole-chain (integration/e2e) proof for the self_respin verb + its EXTERNAL
liveness observer (row 233f30e4; implementation row 9e0678f6).

WHAT THE UNIT SUITES ALREADY PROVE, SEPARATELY:
  • perform_self_respin's guard tree + marker/token writes (test_self_respin_core)
  • the observer's classify_marker / observe_fleet_self_respin oracle
    (test_self_respin_observer, ..._liveness_observer_control)
  • the disposable-seat harness's fire-gate + verdict mapping — but over a marker
    it hand-builds with build_marker_dict, NOT one the verb itself wrote.

THE GAP THIS FILE FILLS — the two halves CONNECTED across the disk hand-off:
the verb's OWN write path (write_json_fn → real file on disk) produces the exact
marker the EXTERNAL observer (read_markers → classify) then reads and judges. The
observation runs OUTSIDE the firing seat: it takes only a base_dir + a pressure
payload, never the cleared session's context (which the verb destroys). Every
verdict is driven purely by the persisted marker + the identity tuple
(session_id / tmux_session / persona) — proving the seat can be judged AFTER it
has cleared itself, which is the whole point of an external observer.

Constraint honoured: no real tmux, no real /clear, no subprocess, no live fleet
IO. The only disk touched is pytest's tmp_path — the SAME isolated surface the
harness unit test uses — because the disk hand-off IS the integration point under
test. Every dangerous seam (tmux resolve, the confirmation ask, the detached
schedule) is injected.

Venue: :7999-eligible / local — seam-injected, tmp-dir marker, injected
pressure + clock, no server, no persistent state outside tmp_path.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp.self_respin_core import (
    perform_self_respin,
    self_respin_from_bridge,
    build_nonce_line,
    FIRE_TOKEN_PREFIX,
)
from cosa.agents.heartbeat_arbiter.self_respin_observer import (
    observe_fleet_self_respin,
    SelfRespinVerdict,
    MARKER_PREFIX,
)

UTC     = datetime.timezone.utc
FIRED   = datetime.datetime( 2026, 8, 15, 2, 0, 0, tzinfo=UTC )
SESSION = "d15fa6fa"
PERSONA = "tiberius"
TMUX    = "cc-tiberius-1"
DELAY   = 5                                              # deadline = FIRED + DELAY + grace(120) = FIRED+125s

_INSIDE   = FIRED + datetime.timedelta( seconds=40 )    # before expected_return_by
_AFTER    = FIRED + datetime.timedelta( seconds=30 )    # a returned reading, still inside the window
_PAST_DUE = FIRED + datetime.timedelta( seconds=600 )   # well past the deadline


# ── real-disk seams (the integration surface) ──────────────────────────────────

def _real_write_json( path, data ):
    """Write JSON to disk exactly as the atomic seam would land it (real file)."""
    with open( path, "w" ) as f:
        json.dump( data, f )


def _real_read_text( path ):
    try:
        with open( path, "r" ) as f:
            return f.read()
    except OSError:
        return None


class _Schedule:
    """Captures the detached argv the verb would have spawned — never runs it."""
    def __init__( self ):
        self.argv = None
    def __call__( self, argv ):
        self.argv = argv


def _seed_memento( tmp_path, nonce_uuid, stamp_ts=FIRED ):
    """Write a complete memento carrying a fresh this-cycle nonce line."""
    memento = tmp_path / "tiberius-memento.md"
    memento.write_text(
        "# Memento\nsome durable state\n" + build_nonce_line( nonce_uuid, stamp_ts ) + "\n"
    )
    return str( memento )


def _fire_the_verb( tmp_path, schedule, *, ask="[default used] ", nonce_uuid="nonce-abc",
                    stamp_ts=FIRED, now=FIRED ):
    """
    Run the REAL perform_self_respin with only the dangerous seams injected and a
    real tmp-dir disk, returning its SelfRespinResult. The marker + fire token
    land on disk exactly as production writes them.
    """
    memento_path = _seed_memento( tmp_path, nonce_uuid, stamp_ts )
    return perform_self_respin(
        SESSION,
        persona              = PERSONA,
        memento_path         = memento_path,
        memento_nonce        = nonce_uuid,
        pre_clear_status     = "over_budget",
        pre_clear_pct        = 61.0,
        delay_seconds        = DELAY,
        base_dir             = str( tmp_path ),
        now                  = now,
        resolve_tmux_fn      = lambda sid: TMUX if sid == SESSION else None,
        ask_fn               = lambda: ask,
        schedule_fn          = schedule,
        read_text_fn         = _real_read_text,
        write_json_fn        = _real_write_json,
    )


def _pressure( **record ):
    """A context-pressure section keyed under the persona, carrying the identity tuple."""
    return { "personas": { PERSONA: { "session_id": SESSION, "tmux_session": TMUX, **record } } }


# ═══════════════════════════════════════════════════════════════════════════
#  1. The connected chain: verb WRITES → external observer READS → RETURNED
# ═══════════════════════════════════════════════════════════════════════════

def test_verb_written_marker_is_observed_as_returned( tmp_path ):
    schedule = _Schedule()
    result   = _fire_the_verb( tmp_path, schedule )

    # writer half: a real marker landed on disk under the observer's own glob
    assert result.status == "scheduled"
    marker_files = list( tmp_path.glob( f"{MARKER_PREFIX}*.json" ) )
    assert [ p.name for p in marker_files ] == [ f"{MARKER_PREFIX}{SESSION}.json" ]

    # external observer half: same base_dir, a fresh call, seat has come back low
    assessments = observe_fleet_self_respin(
        base_dir      = str( tmp_path ),
        now           = _AFTER,
        fetch_pressure= lambda: _pressure( status="within_budget", last_turn_age_s=10 ),
    )
    assert len( assessments ) == 1
    a = assessments[ 0 ]
    assert a.verdict is SelfRespinVerdict.RETURNED and a.is_alarm is False
    assert a.session_id == SESSION and a.persona == PERSONA   # identity tuple carried through


def test_scheduled_argv_is_the_one_shot_guarded_clear( tmp_path ):
    """The chain scheduled a detached argv whose rm-then-send-keys consumes the
    real fire token the verb wrote — the double-fire guard, end to end."""
    schedule = _Schedule()
    result   = _fire_the_verb( tmp_path, schedule )

    token_path = os.path.join( str( tmp_path ), f"{FIRE_TOKEN_PREFIX}{SESSION}.token" )
    assert os.path.exists( token_path )                       # the one-shot token really landed
    assert result.fire_token_path == token_path

    argv = schedule.argv
    assert argv is not None and argv[ 0 ] == "bash" and argv[ 1 ] == "-c"
    assert 'rm "$4"' in argv[ 2 ] and 'send-keys' in argv[ 2 ]
    assert argv[ 5 ] == TMUX and argv[ 6 ] == "/clear" and argv[ 7 ] == token_path
    # the fire token is NOT a marker — it must not be globbed as one
    assert token_path not in [ str( p ) for p in tmp_path.glob( f"{MARKER_PREFIX}*.json" ) ]


# ═══════════════════════════════════════════════════════════════════════════
#  2. The alarm verdicts — judged from OUTSIDE, seat context long gone
# ═══════════════════════════════════════════════════════════════════════════

def test_verb_written_marker_observed_dead_past_deadline( tmp_path ):
    """Fired, nobody came back, now past expected_return_by → DEAD_NO_RETURN alarm."""
    _fire_the_verb( tmp_path, _Schedule() )
    assessments = observe_fleet_self_respin(
        base_dir      = str( tmp_path ),
        now           = _PAST_DUE,
        fetch_pressure= lambda: { "personas": {} },          # nobody answered
    )
    assert assessments[ 0 ].verdict is SelfRespinVerdict.DEAD_NO_RETURN
    assert assessments[ 0 ].is_alarm is True


def test_verb_written_marker_observed_identity_mismatch( tmp_path ):
    """A seat answered under this session_id but from a DIFFERENT tmux — the
    identity-tuple guard flags it rather than trusting the session_id alone."""
    _fire_the_verb( tmp_path, _Schedule() )
    assessments = observe_fleet_self_respin(
        base_dir      = str( tmp_path ),
        now           = _AFTER,
        fetch_pressure= lambda: _pressure( status="within_budget", last_turn_age_s=10,
                                           tmux_session="cc-someone-else-9" ),
    )
    assert assessments[ 0 ].verdict is SelfRespinVerdict.IDENTITY_MISMATCH
    assert assessments[ 0 ].is_alarm is True


def test_verb_written_marker_pending_inside_window( tmp_path ):
    """Inside the return window with nobody back yet → PENDING (no alarm)."""
    _fire_the_verb( tmp_path, _Schedule() )
    assessments = observe_fleet_self_respin(
        base_dir      = str( tmp_path ),
        now           = _INSIDE,
        fetch_pressure= lambda: { "personas": {} },
    )
    assert assessments[ 0 ].verdict is SelfRespinVerdict.PENDING
    assert assessments[ 0 ].is_alarm is False


# ═══════════════════════════════════════════════════════════════════════════
#  3. A failed guard writes NO marker — the observer sees nothing in flight
# ═══════════════════════════════════════════════════════════════════════════

def test_aborted_memento_verify_leaves_nothing_for_the_observer( tmp_path ):
    """A stale nonce aborts BEFORE any marker is written; the external observer
    then finds no marker — a clear that never scheduled raises no liveness alarm."""
    stale = FIRED - datetime.timedelta( seconds=10_000 )     # far outside the cycle window
    result = _fire_the_verb( tmp_path, _Schedule(), stamp_ts=stale )
    assert result.status == "aborted"
    assert list( tmp_path.glob( f"{MARKER_PREFIX}*.json" ) ) == []
    assert observe_fleet_self_respin(
        base_dir=str( tmp_path ), now=_PAST_DUE, fetch_pressure=lambda: { "personas": {} } ) == []


def test_declined_ask_leaves_nothing_for_the_observer( tmp_path ):
    """A real human 'no' declines; no marker is written, so nothing is observed."""
    result = _fire_the_verb( tmp_path, _Schedule(), ask="no" )
    assert result.status == "declined"
    assert list( tmp_path.glob( f"{MARKER_PREFIX}*.json" ) ) == []
    assert observe_fleet_self_respin(
        base_dir=str( tmp_path ), now=_AFTER, fetch_pressure=lambda: { "personas": {} } ) == []


# ═══════════════════════════════════════════════════════════════════════════
#  4. Identity is resolved from the BRIDGE, never a caller argument
# ═══════════════════════════════════════════════════════════════════════════

def test_bridge_chain_uses_bridge_identity_not_a_caller_id( tmp_path ):
    """self_respin_from_bridge takes NO session_id arg — it resolves the seat from
    identity_fn (the bridge). Prove the id perform_fn receives is the bridge's."""
    seen = {}
    def _perform( session_id, **kwargs ):
        seen[ "session_id" ] = session_id
        seen[ "persona" ]    = kwargs[ "persona" ]
        from lupin_mcp.self_respin_core import SelfRespinResult
        return SelfRespinResult( status="scheduled", reason="stub" )

    result = self_respin_from_bridge(
        memento_path  = "io/mementos/tiberius.md",
        memento_nonce = "nonce-xyz",
        identity_fn   = lambda: ( SESSION, PERSONA ),        # the bridge resolver
        pressure_fn   = lambda persona: ( "over_budget", 61.0 ),
        perform_fn    = _perform,
    )
    assert result.status == "scheduled"
    assert seen == { "session_id": SESSION, "persona": PERSONA }


def test_bridge_chain_aborts_when_bridge_yields_no_id():
    """No session id from the bridge ⇒ aborted; perform is never reached (no blind clear)."""
    reached = { "called": False }
    def _perform( *a, **k ):
        reached[ "called" ] = True
    result = self_respin_from_bridge(
        memento_path  = "m", memento_nonce = "n",
        identity_fn   = lambda: ( None, "unknown" ),
        pressure_fn   = lambda persona: ( "unknown", None ),
        perform_fn    = _perform,
    )
    assert result.status == "aborted" and reached[ "called" ] is False


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
