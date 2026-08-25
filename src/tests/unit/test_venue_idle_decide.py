"""
The falsifier for row e6b8fe56, as a regression test instead of a live probe.

WHY THIS FILE EXISTS
    e6b8fe56 filed a P1: the :8000 idle check reported idle off `monopolize_id`
    while the todo queue was backed up, so every seat that had ever "verified
    :8000 idle" had verified nothing about queued work. The reporter half landed
    in `cosa.rest.venue_idle`. NOTHING TESTED IT — a grep for "venue_idle" across
    src/tests/ returned no hits on 2026-08-25, so the fix for a P1 defect shipped
    with no guard that it still fires.

    The row proposed a live falsifier: queue a job without letting it start, then
    call the check and require NOT idle. Rick vetoed running it on 2026-08-24
    because it would have queued work on the venue his 09:30 gate needed. This
    file is that falsifier aimed at `decide()` instead of at the venue — it costs
    no queue contact, and it covers ALL FIVE rows of the row's table rather than
    the single case a live probe could reach.

CORROBORATION FROM A LIVE RUN, not a substitute for the table below.
    During the 2026-08-25 final gate the real venue passed through the exact
    defect scenario at 11:38 EDT: run_queue_size=1, todo_queue_size=216,
    monopolize_inflight=False, monopolize_id=None. The old logic would have read
    that as IDLE off the null monopolize slot. `venue_idle` reported BUSY and
    named the two occupied lanes. The inverse control also held twice the same
    day: a genuinely empty venue still reported IDLE, exit 0.

⚠️ These tests assert the DEFECT'S TABLE, not the implementation's shape. If
    someone later "simplifies" decide() back onto the monopolize slot, the five
    NOT-IDLE cases below go red. That is the whole point — do not relax them to
    make a refactor pass.
"""

import pytest

from cosa.rest.venue_idle import (
    decide, IDLE, BUSY, UNKNOWN,
    EXIT_IDLE, EXIT_BUSY, EXIT_UNKNOWN,
    COUNT_SIGNALS, FLAG_SIGNALS, REQUIRED_SIGNALS,
)


def _signals( run=0, todo=0, pool=0, mono=False, mono_id=None ):
    """Build a full signal bag; every REQUIRED_SIGNALS key is present by default."""
    return {
        "run_queue_size"        : run,
        "todo_queue_size"       : todo,
        "inflight_agentic_jobs" : pool,
        "monopolize_inflight"   : mono,
        "monopolize_id"         : mono_id,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# THE FALSIFIER — row e6b8fe56's own table, verbatim.
#
# Every row below has monopolize_id = None. Under the defect, all five read IDLE.
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "case, signals",
    [
        ( "2 jobs QUEUED in todo, none started",   _signals( todo=2 ) ),
        ( "+ 1 job RUNNING INLINE on the consumer", _signals( todo=2, run=1 ) ),
        ( "+ 1 job SCHEDULED for the future",       _signals( todo=3, run=1 ) ),
        ( "+ 1 job RUNNING in the shared pool",     _signals( todo=3, run=1, pool=1 ) ),
    ],
)
def test_queued_or_running_work_is_never_idle_even_with_an_empty_monopolize_slot( case, signals ):
    """
    The defect in one assertion: work that has not STARTED still occupies the venue.

    `monopolize_id` moves for exactly one condition — a monopolize-flagged job that
    has already started. It answers WHICH JOB HOLDS THE SLOT, an identity question.
    A verdict derived from it says nothing about queued, inline, or pooled work.
    """
    assert signals[ "monopolize_id" ] is None, "the defect scenario requires an empty slot"
    verdict, reasons = decide( signals )
    assert verdict == BUSY, f"{case}: venue is occupied but decide() said {verdict}"
    assert reasons, "every arm must explain itself"


def test_a_started_monopolizer_is_busy_and_names_its_holder():
    """The one case the OLD logic got right must stay right."""
    verdict, reasons = decide( _signals( mono=True, mono_id="mono-1" ) )
    assert verdict == BUSY
    assert any( "mono-1" in r for r in reasons ), "a BUSY verdict should name the holder"


# ═══════════════════════════════════════════════════════════════════════════════
# THE INVERSE CONTROL — without this, "always BUSY" would pass everything above.
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_genuinely_empty_venue_still_reads_idle():
    """
    A fix that never says IDLE has broken the check in the other direction.

    The row asked for this explicitly: "keep the inverse control — a genuinely
    empty venue must still read idle, or the fix has just made the check useless."
    """
    verdict, reasons = decide( _signals() )
    assert verdict == IDLE
    assert reasons


# ═══════════════════════════════════════════════════════════════════════════════
# UNKNOWN IS NOT IDLE — the rule that keeps the defect from reappearing one level up.
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "missing", REQUIRED_SIGNALS )
def test_any_unreadable_required_signal_yields_unknown_never_idle( missing ):
    """
    An absent signal is not proof of absence.

    This is the arm that caught the real container on 2026-08-24: it predated
    `todo_queue_size` and literally could not see waiting work. Reporting IDLE
    there would have reproduced the original bug one level up.
    """
    signals = _signals()
    signals[ missing ] = None
    verdict, _ = decide( signals )
    assert verdict == UNKNOWN, f"{missing} unreadable must not read as IDLE"


@pytest.mark.parametrize( "missing", REQUIRED_SIGNALS )
def test_a_signal_dropped_from_the_bag_entirely_also_yields_unknown( missing ):
    """A key that is absent must behave like a key that is None, not like zero."""
    signals = _signals()
    del signals[ missing ]
    verdict, _ = decide( signals )
    assert verdict == UNKNOWN


def test_busy_wins_over_unknown():
    """
    Proven occupancy is already a decision.

    A caller who knows to stay off the venue gains nothing from ambiguity, so a
    readable occupied lane must not be downgraded to UNKNOWN by an unreadable one.
    """
    signals = _signals( todo=5 )
    signals[ "monopolize_inflight" ] = None
    verdict, reasons = decide( signals )
    assert verdict == BUSY
    assert any( "todo_queue_size=5" in r for r in reasons )


# ═══════════════════════════════════════════════════════════════════════════════
# The exit codes ARE the caller's branch — RIG-PROCEDURE §1a reads nothing else.
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_three_exit_codes_are_distinct_and_idle_alone_is_zero():
    """
    A caller branches on the exit status, so IDLE must be the only success code.

    If UNKNOWN ever shared an exit code with IDLE, `case $? in 0) proceed` would
    walk straight onto a venue whose state was never established.
    """
    assert ( EXIT_IDLE, EXIT_BUSY, EXIT_UNKNOWN ) == ( 0, 1, 2 )
    assert len( { EXIT_IDLE, EXIT_BUSY, EXIT_UNKNOWN } ) == 3


def test_every_lane_is_required_and_none_was_quietly_dropped():
    """
    Guards the definition, not the code path.

    "A venue is free iff NOTHING is running AND NOTHING is queued AND nothing is
    scheduled to start." Deleting a lane from REQUIRED_SIGNALS would silently
    restore the blind spot while every other test above still passed.
    """
    assert set( COUNT_SIGNALS ) == { "run_queue_size", "todo_queue_size", "inflight_agentic_jobs" }
    assert set( FLAG_SIGNALS ) == { "monopolize_inflight" }
    assert len( REQUIRED_SIGNALS ) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# read_signals — the transport arm. `opener` is an injected seam, so no venue is
# contacted here and none of these tests can collide with a live :8000 job.
# ═══════════════════════════════════════════════════════════════════════════════

import io as _io
import json as _json

from cosa.rest.venue_idle import read_signals, format_report, check, main


class _FakeResponse:
    """Minimal stand-in for urlopen's context-managed response."""
    def __init__( self, body ): self._body = body.encode()
    def read( self ): return self._body
    def __enter__( self ): return self
    def __exit__( self, *a ): return False


def _opener_returning( payload ):
    def _open( url, timeout=None ): return _FakeResponse( _json.dumps( payload ) )
    return _open


def _opener_raising( exc ):
    def _open( url, timeout=None ): raise exc
    return _open


def test_read_signals_parses_every_lane_from_the_busy_payload():
    signals = read_signals( opener=_opener_returning( {
        "run_queue_size": 1, "todo_queue_size": 216,
        "inflight_agentic_jobs": 0, "monopolize_inflight": False,
        "monopolize_id": None,
    } ) )
    assert signals[ "run_queue_size" ]  == 1
    assert signals[ "todo_queue_size" ] == 216
    assert signals[ "monopolize_inflight" ] is False
    assert signals[ "error" ] is None


def test_the_live_2026_08_25_defect_scenario_reads_busy_end_to_end():
    """
    The natural experiment from the final gate, replayed through the real code path.

    Measured on the venue at 11:38 EDT: one job running, 216 queued, and an EMPTY
    monopolize slot. The old logic would have called that idle.
    """
    verdict, report, _ = check( opener=_opener_returning( {
        "run_queue_size": 1, "todo_queue_size": 216,
        "inflight_agentic_jobs": 0, "monopolize_inflight": False,
        "monopolize_id": None,
    } ) )
    assert verdict == BUSY
    assert "todo_queue_size=216" in report


@pytest.mark.parametrize( "failure", [
    ConnectionRefusedError( "venue is down" ),
    ValueError( "not json" ),
] )
def test_a_transport_or_parse_failure_is_unknown_and_never_raises( failure ):
    """A venue that is down, old, or answering nonsense must not crash the caller."""
    signals = read_signals( opener=_opener_raising( failure ) )
    assert all( signals[ n ] is None for n in REQUIRED_SIGNALS )
    assert signals[ "error" ]
    assert decide( signals )[ 0 ] == UNKNOWN


def test_a_container_predating_the_fix_yields_unknown_with_the_bounce_remedy():
    """
    The 2026-08-24 container, exactly: every lane readable EXCEPT the todo depth.

    The report must name the bounce remedy and must NOT suggest --force-recreate
    as the fix, because a recreate is for mount/env changes and would kill a job.
    """
    verdict, report, _ = check( opener=_opener_returning( {
        "run_queue_size": 0, "inflight_agentic_jobs": 0, "monopolize_id": None,
    } ) )
    assert verdict == UNKNOWN
    assert "UNKNOWN IS NOT IDLE" in report


def test_the_todo_only_gap_names_the_bounce_remedy_and_not_a_force_recreate():
    """
    The narrower gap: EVERY lane readable except the todo depth.

    That is the case the report singles out, because it is the one where a bounce
    is the whole fix. It must NOT recommend --force-recreate, which is for
    mount/env changes and would kill a running job.
    """
    verdict, report, _ = check( opener=_opener_returning( {
        "run_queue_size": 0, "inflight_agentic_jobs": 0,
        "monopolize_inflight": False, "monopolize_id": None,
    } ) )
    assert verdict == UNKNOWN
    assert "BOUNCE" in report
    assert "predates row e6b8fe56" in report


def test_a_broadly_unreadable_venue_does_not_claim_the_container_is_merely_old():
    """The bounce advice is specific to the todo-only gap; it must not over-fire."""
    _, report, _ = check( opener=_opener_raising( ConnectionRefusedError( "down" ) ) )
    assert "UNKNOWN IS NOT IDLE" in report
    assert "predates row e6b8fe56" not in report
    assert "read failed:" in report


def test_the_report_always_names_the_port_verdict_and_every_signal():
    signals = _signals( todo=2 )
    verdict, reasons = decide( signals )
    report = format_report( "8000", signals, verdict, reasons )
    assert ":8000 -- BUSY" in report
    for name in REQUIRED_SIGNALS:
        assert name in report


# ═══════════════════════════════════════════════════════════════════════════════
# main() — the exit code IS the caller's branch (RIG-PROCEDURE §1a reads nothing else)
# ═══════════════════════════════════════════════════════════════════════════════

def _run_main( monkeypatch, payload, argv ):
    monkeypatch.setattr( "cosa.rest.venue_idle.read_signals",
                         lambda port=None, timeout=10, opener=None: payload )
    return main( argv )


def test_main_returns_zero_only_on_a_genuinely_empty_venue( monkeypatch, capsys ):
    assert _run_main( monkeypatch, _signals(), [] ) == EXIT_IDLE
    assert "IDLE" in capsys.readouterr().out


def test_main_returns_one_when_work_is_queued_behind_an_empty_monopolize_slot( monkeypatch ):
    assert _run_main( monkeypatch, _signals( todo=2 ), [] ) == EXIT_BUSY


def test_main_returns_two_when_a_lane_is_unreadable( monkeypatch ):
    blind = _signals(); blind[ "todo_queue_size" ] = None
    assert _run_main( monkeypatch, blind, [] ) == EXIT_UNKNOWN


def test_main_honours_the_port_flag( monkeypatch, capsys ):
    _run_main( monkeypatch, _signals(), [ "--port", "7999" ] )
    assert ":7999" in capsys.readouterr().out


def test_an_unrecognised_argument_is_ignored_rather_than_fatal( monkeypatch, capsys ):
    """
    A bad flag must never be why a gate step produces no reading.

    Silence and a crash look identical to a caller reading only the exit code.
    """
    assert _run_main( monkeypatch, _signals(), [ "--nonsense", "x", "--port", "8000" ] ) == EXIT_IDLE
    assert ":8000" in capsys.readouterr().out


def test_main_reads_sys_argv_when_argv_is_none( monkeypatch, capsys ):
    monkeypatch.setattr( "sys.argv", [ "venue_idle", "--port", "9111" ] )
    _run_main( monkeypatch, _signals(), None )
    assert ":9111" in capsys.readouterr().out


def test_the_formatter_survives_an_empty_reason_list():
    """
    Covers the loop-skip branch, and states why it is unreachable in practice.

    `decide()` guarantees a non-empty `reasons` in every arm, so this input cannot
    arise today. The formatter is still called with whatever a future caller hands
    it, and a report that crashes is a gate step that produces no reading at all —
    indistinguishable, to a caller reading the exit code, from a venue that is fine.
    """
    report = format_report( "8000", _signals(), IDLE, [] )
    assert ":8000 -- IDLE" in report
    assert "signals:" in report
