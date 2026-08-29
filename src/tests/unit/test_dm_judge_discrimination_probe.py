"""
Unit tests for the DM-judge discrimination probe's classifier + verdict logic.

These test the PURE logic the probe added on 2026-08-01 (row ca7a2cbf): telling a real
grade from a judge non-answer, and refusing to let a non-answer satisfy an ordering. They
feed synthetic dimension-result dicts — no live model — so they run on :7999 and are fast.

THE NEGATIVE CONTROL that matters is test_fallback_worse_cell_does_not_satisfy_ordering:
a run whose "worse" cells are 100% fallback but whose "better" cells score high. The
weight-only comparison this probe REPLACED would read that as a clean pass (fallback
weight 0 < real weight 2). The discrimination-aware evaluate() must fail it. Mutating
is_measurement() back to "everything counts" turns that test red — the proof that the
test is actually catching the defect and not just passing by construction.
"""
import importlib.util
import os

import pytest

# Import the probe module by file path — it lives in src/tests/smoke/ and is not a package.
_PROBE_PATH = os.path.join(
    os.environ[ "LUPIN_ROOT" ], "src", "tests", "smoke", "dm_judge_discrimination_probe.py"
)
_spec  = importlib.util.spec_from_file_location( "dm_judge_discrimination_probe", _PROBE_PATH )
probe  = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( probe )

from cosa.agents.dm_quality_judge.judge import (
    _JUDGE_UNAVAILABLE_DETAIL,
    _QUALITATIVE_OFF_DETAIL,
    _TOO_LONG_DETAIL,
)


# ── synthetic dimension-result builders (the four shapes the judge actually emits) ──

def _real( weight ):
    """A real grade: a valid weight and a detail that describes the GRADED TEXT."""
    return { "emoji": "🙂", "weight": weight, "detail": "Leans on an aphorism instead of plain phrasing" }


def _fallback():
    """Parse/model failure: weight 0, detail names the JUDGE'S state, not the text."""
    return { "emoji": "🤷", "weight": 0, "detail": _JUDGE_UNAVAILABLE_DETAIL }


def _too_long():
    """Body over the word limit: its own distinct detail. Number-free since row 2cb46818 —
    the emitter no longer discloses the enforced ceiling, so neither does this stand-in."""
    return { "emoji": "🤷", "weight": 0, "detail": _TOO_LONG_DETAIL }


def _withheld():
    """Feature switched off: weight None (un-averageable by design)."""
    return { "emoji": "🚫", "weight": None, "detail": _QUALITATIVE_OFF_DETAIL }


def _cell( d_dim, t_dim, runs=3 ):
    """A cell of `runs` identical ( directness, tone ) results."""
    return [ ( d_dim, t_dim ) for _ in range( runs ) ]


# ── classifier ──────────────────────────────────────────────────────────────

def test_is_measurement_only_true_for_a_real_grade():
    assert probe.is_measurement( _real( 2 ) ) is True
    assert probe.is_measurement( _real( 0 ) ) is True          # a REAL meh is still a measurement
    assert probe.is_measurement( _fallback() ) is False
    assert probe.is_measurement( _too_long() ) is False
    assert probe.is_measurement( _withheld() ) is False


def test_nonanswer_kind_names_each_shape():
    assert probe.nonanswer_kind( _real( 0 ) )   is None
    assert probe.nonanswer_kind( _fallback() )  == "unavailable"
    assert probe.nonanswer_kind( _too_long() )  == "too_long"
    assert probe.nonanswer_kind( _withheld() )  == "withheld"


def test_real_meh_and_fallback_have_the_same_weight_but_differ():
    # The exact collision the probe exists to resolve: identical weight, different verdict.
    assert _real( 0 )[ "weight" ] == _fallback()[ "weight" ] == 0
    assert probe.is_measurement( _real( 0 ) ) != probe.is_measurement( _fallback() )


# ── evaluate() verdicts ─────────────────────────────────────────────────────

def _monotonic_results():
    """A clean run: DIRECT cells beat BURIED on directness; PLAIN beats JARGON on tone."""
    return {
        "DIRECT_PLAIN"  : _cell( _real(  2 ), _real(  2 ) ),
        "DIRECT_JARGON" : _cell( _real(  2 ), _real( -1 ) ),
        "BURIED_PLAIN"  : _cell( _real( -1 ), _real(  2 ) ),
        "BURIED_JARGON" : _cell( _real( -1 ), _real( -1 ) ),
    }


def test_real_monotonic_grades_pass():
    report = probe.evaluate( _monotonic_results(), probe.CONTRASTS )
    assert report[ "status" ]    == "MONOTONIC"
    assert report[ "exit_code" ] == 0
    assert report[ "dead_cells" ] == [ ]


def test_all_fallback_run_measures_nothing():
    results = { name: _cell( _fallback(), _fallback() ) for name, _ in probe.BODIES }
    report  = probe.evaluate( results, probe.CONTRASTS )
    assert report[ "status" ]     == "NO_MEASUREMENTS"
    assert report[ "exit_code" ]  == 2                     # hardest failure — never a pass
    assert report[ "total_real" ] == 0


def test_one_dead_cell_fails_even_with_three_good_cells():
    # Mr. Radio's sharpening: the guard is PER CELL. Three fully-graded cells must NOT let
    # a fourth all-fallback cell slide through by comparing fewer cells.
    results = _monotonic_results()
    results[ "BURIED_JARGON" ] = _cell( _fallback(), _fallback() )
    report = probe.evaluate( results, probe.CONTRASTS )
    assert report[ "status" ]    == "INSUFFICIENT"
    assert report[ "exit_code" ] == 1
    assert ( "BURIED_JARGON", "Directness" ) in report[ "dead_cells" ]
    assert ( "BURIED_JARGON", "Tone" )       in report[ "dead_cells" ]


def test_fallback_worse_cell_does_not_satisfy_ordering():
    """
    THE NEGATIVE CONTROL. The 'worse' cells on directness are 100% fallback; the 'better'
    cells score high. Weight-only comparison (2 > 0) would call this MONOTONIC. The
    discrimination-aware evaluate() must report INSUFFICIENT because those worse cells
    were never actually graded.

    Mutating probe.is_measurement to `lambda dim: True` (the weight-only behavior this
    replaced) makes this assertion fail — that mutation is the proof the test bites.
    """
    results = {
        "DIRECT_PLAIN"  : _cell( _real( 2 ), _real(  2 ) ),
        "DIRECT_JARGON" : _cell( _real( 2 ), _real( -1 ) ),
        "BURIED_PLAIN"  : _cell( _fallback(), _real(  2 ) ),   # directness never graded
        "BURIED_JARGON" : _cell( _fallback(), _real( -1 ) ),   # directness never graded
    }
    report = probe.evaluate( results, probe.CONTRASTS )
    assert report[ "status" ]    != "MONOTONIC"
    assert report[ "exit_code" ] != 0
    assert report[ "status" ]    == "INSUFFICIENT"


def test_not_monotonic_when_a_real_ordering_is_wrong():
    # Every cell measured, but directness is inverted on one held-plain pair.
    results = _monotonic_results()
    results[ "DIRECT_PLAIN" ]  = _cell( _real( -2 ), _real( 2 ) )   # direct now BELOW buried
    report = probe.evaluate( results, probe.CONTRASTS )
    assert report[ "status" ]    == "NOT_MONOTONIC"
    assert report[ "exit_code" ] == 1
    assert report[ "dead_cells" ] == [ ]
