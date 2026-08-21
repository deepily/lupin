"""
Unit coverage for the warm-warm span pairing tool (row d8d019f6).

WHY IT MATTERS: pairing v1's WARM pass against v2's COLD pass produced a -11.2 second
"delta" on 2026-08-20 that meant nothing, because the two arms were at different points in
their own warm-up. The tool exists to make that mistake impossible to repeat silently, and
to state the three things Mr Radio required beside any latency number: warm-vs-warm only,
per-category as well as pooled, and how many utterances actually survived into the pairing.
"""

import importlib.util, json, os, tempfile

import pytest

import cosa.utils.util as cu

_SPEC = importlib.util.spec_from_file_location(
    "pair_warm", os.path.join( cu.get_project_root(), "src", "scripts", "pair-warm-spans.py" ) )
pw = importlib.util.module_from_spec( _SPEC )
_SPEC.loader.exec_module( pw )


def _trail( tmp_path, rows ):
    p = os.path.join( tmp_path, "trail.jsonl" )
    with open( p, "w" ) as fh:
        for r in rows: fh.write( json.dumps( r ) + "\n" )
    return p


def _rec( utterance, span, ok=True, wall_ts=2000.0, phase="end" ):
    return { "phase": phase, "utterance": utterance, "client_span_ms": span,
             "ok": ok, "wall_ts": wall_ts }


# ---------------------------------------------------------------------------
# The cold/warm split — the mistake this tool exists to prevent
# ---------------------------------------------------------------------------
def test_the_split_is_positional_cold_then_warm( tmp_path ):
    """The arm runs pass 1 then pass 2, so the split is by POSITION. A timestamp heuristic
    would misclassify a slow cold record as warm."""
    rows = [ _rec( f"u{i}", 100.0 + i ) for i in range( 4 ) ]
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=2 )
    assert sorted( cold ) == [ "u0", "u1" ]
    assert sorted( warm ) == [ "u2", "u3" ]


def test_a_run_that_has_not_reached_warm_returns_an_EMPTY_warm( tmp_path ):
    """RED if warm ever borrows cold records. That silent borrow is exactly how a
    warm-versus-cold comparison gets quoted as a verdict."""
    rows = [ _rec( f"u{i}", 100.0 ) for i in range( 3 ) ]
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=5 )
    assert len( cold ) == 3 and warm == {}


def test_failed_and_spanless_records_are_excluded( tmp_path ):
    rows = [ _rec( "a", 100.0 ), _rec( "b", 200.0, ok=False ),
             _rec( "c", None ), _rec( "d", 300.0, phase="start" ) ]
    cold, _ = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=10 )
    assert sorted( cold ) == [ "a" ]


def test_records_from_an_earlier_run_are_excluded_by_since( tmp_path ):
    rows = [ _rec( "old", 100.0, wall_ts=1000.0 ), _rec( "new", 200.0, wall_ts=3000.0 ) ]
    cold, _ = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=2000.0, n_per_pass=10 )
    assert sorted( cold ) == [ "new" ]


def test_a_missing_trail_is_empty_not_an_error():
    assert pw.v2_spans_by_pass( "/nonexistent/trail.jsonl", since=0.0, n_per_pass=5 ) == ( {}, {} )


# ---------------------------------------------------------------------------
# The statistic itself
# ---------------------------------------------------------------------------
def test_delta_is_the_median_of_PER_UTTERANCE_differences():
    """Not the difference of medians — the two are different numbers and only the first is
    a paired statistic. Constructed so they disagree: diff-of-medians would give 0."""
    v1 = { "a": 100.0, "b": 900.0 }
    v2 = { "a": 900.0, "b": 100.0 }
    s  = pw.summarise( v1, v2, pw.pair( v1, v2 ) )
    assert s[ "v1_median" ] == s[ "v2_median" ] == 500.0     # diff of medians would be 0
    assert s[ "delta" ] == 0.0                                 # median of (-800, +800)
    v1[ "c" ], v2[ "c" ] = 1000.0, 100.0
    s = pw.summarise( v1, v2, pw.pair( v1, v2 ) )
    assert s[ "delta" ] == 800.0                               # median of (-800, 800, 900)


def test_summarise_returns_None_for_an_empty_pairing():
    assert pw.summarise( {}, {}, [] ) is None


def test_pair_is_the_intersection_only():
    assert pw.pair( { "a": 1.0, "b": 2.0 }, { "b": 3.0, "c": 4.0 } ) == [ "b" ]


# ---------------------------------------------------------------------------
# What the rendered report must say
# ---------------------------------------------------------------------------
def test_report_states_the_surviving_count_and_the_selection_caveat():
    v1 = { "a": 100.0, "b": 200.0 }
    v2 = { "a": 50.0,  "b": 100.0 }
    text, ok = pw.render( v1, v2, { "a": "todo", "b": "todo" }, 20, [ "todo", "math" ] )
    assert ok
    assert "Surviving into the warm-warm pairing: 2 of 40" in text
    assert "SELECTED set, not the sample" in text


def test_report_carries_BOTH_pooled_and_per_category():
    """A pooled median hides a category behaving differently — on 08-20 pooled was -11.2s
    while todo alone was -59.9s."""
    v1 = { "a": 100.0, "b": 100.0 }
    v2 = { "a": 50.0,  "b": 900.0 }
    text, _ = pw.render( v1, v2, { "a": "math", "b": "todo" }, 1, [ "math", "todo" ] )
    assert "**POOLED**" in text
    assert "| math |" in text and "| todo |" in text


def test_report_names_which_arm_is_faster_per_row():
    v1 = { "a": 900.0 }
    v2 = { "a": 100.0 }
    text, _ = pw.render( v1, v2, { "a": "math" }, 1, [ "math" ] )
    assert "**v2**" in text          # positive delta ⇒ v2 faster
    text, _ = pw.render( { "a": 100.0 }, { "a": 900.0 }, { "a": "math" }, 1, [ "math" ] )
    assert "**v1**" in text


def test_report_REFUSES_when_no_warm_warm_pairing_exists():
    """The live state at 20:30 on 2026-08-20. It must refuse rather than quote a number
    over an empty intersection."""
    text, ok = pw.render( { "a": 100.0 }, {}, { "a": "math" }, 20, [ "math" ] )
    assert ok is False
    assert "NO WARM-WARM PAIRING AVAILABLE" in text
    assert "No latency statement is possible" in text
