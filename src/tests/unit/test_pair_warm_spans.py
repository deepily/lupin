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


def _rec( utterance, span, ok=True, wall_ts=2000.0, phase="end", seq=None ):
    r = { "phase": phase, "utterance": utterance, "client_span_ms": span,
          "ok": ok, "wall_ts": wall_ts }
    if seq is not None: r[ "seq" ] = seq
    return r


# ---------------------------------------------------------------------------
# The cold/warm split — the mistake this tool exists to prevent
# ---------------------------------------------------------------------------
def test_the_split_is_positional_cold_then_warm( tmp_path ):
    """The arm runs pass 1 then pass 2, so the split is by POSITION. A timestamp heuristic
    would misclassify a slow cold record as warm."""
    rows = [ _rec( f"u{i}", 100.0 + i, seq=i + 1 ) for i in range( 4 ) ]
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=2 )
    assert sorted( cold ) == [ "u0", "u1" ]
    assert sorted( warm ) == [ "u2", "u3" ]


def test_a_run_that_has_not_reached_warm_returns_an_EMPTY_warm( tmp_path ):
    """RED if warm ever borrows cold records. That silent borrow is exactly how a
    warm-versus-cold comparison gets quoted as a verdict."""
    rows = [ _rec( f"u{i}", 100.0, seq=i + 1 ) for i in range( 3 ) ]
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=5 )
    assert len( cold ) == 3 and warm == {}


def test_failed_and_spanless_records_are_excluded( tmp_path ):
    rows = [ _rec( "a", 100.0, seq=1 ), _rec( "b", 200.0, ok=False, seq=2 ),
             _rec( "c", None, seq=3 ), _rec( "d", 300.0, phase="start", seq=4 ) ]
    cold, _ = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=10 )
    assert sorted( cold ) == [ "a" ]


def test_records_from_an_earlier_run_are_excluded_by_since( tmp_path ):
    rows = [ _rec( "old", 100.0, wall_ts=1000.0, seq=1 ), _rec( "new", 200.0, wall_ts=3000.0, seq=2 ) ]
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
    """Uses a pairing ABOVE the floor: below it the report is deliberately not-ok, and
    that is asserted separately."""
    v1 = { f"u{i}": 100.0 for i in range( 30 ) }
    v2 = { f"u{i}":  50.0 for i in range( 30 ) }
    mapping = { f"u{i}": "todo" for i in range( 30 ) }
    text, ok = pw.render( v1, v2, mapping, 20, [ "todo", "math" ] )
    assert ok
    assert "Surviving into the warm-warm pairing: 30 of 40" in text
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
    assert "no latency statement is possible" in text.lower()


# ---------------------------------------------------------------------------
# THE DEFECT A POSITIONAL SPLIT HAD (found 2026-08-20 when Mr Radio pushed on
# whether records could be silently relabelled — they could).
# ---------------------------------------------------------------------------
def test_a_failure_in_the_cold_pass_does_NOT_shift_warm_records_into_cold( tmp_path ):
    """THE REAL BUG. Failures are filtered out before bucketing, so a positional slice
    moves every later ok record one place earlier — and the first warm records get
    labelled cold. Here cold is seq 1-3 with seq 2 failing; a positional split would pull
    w1 (seq 4, warm) back into cold. Splitting on the arm's own seq cannot do that."""
    rows = [ _rec( "c1", 10.0, seq=1 ),
             _rec( "c2", 20.0, seq=2, ok=False ),      # dropped by the ok filter
             _rec( "c3", 30.0, seq=3 ),
             _rec( "w1", 40.0, seq=4 ),
             _rec( "w2", 50.0, seq=5 ),
             _rec( "w3", 60.0, seq=6 ) ]
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=3 )
    assert sorted( cold ) == [ "c1", "c3" ]              # NOT ["c1","c3","w1"]
    assert sorted( warm ) == [ "w1", "w2", "w3" ]


def test_a_record_with_no_seq_is_dropped_rather_than_guessed_into_a_bucket( tmp_path ):
    """Guessing is what the positional version did. Dropping is honest, and the survivor
    count the report prints goes down visibly rather than the number quietly being wrong."""
    rows = [ _rec( "a", 10.0, seq=1 ), _rec( "b", 20.0 ) ]     # b carries no seq
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=5 )
    assert sorted( cold ) == [ "a" ] and warm == {}


def test_seq_beyond_the_cold_boundary_lands_in_warm_even_when_few_records_exist( tmp_path ):
    """A sparse trail must not be read as "all cold" just because it is short."""
    rows = [ _rec( "w", 10.0, seq=97 ) ]
    cold, warm = pw.v2_spans_by_pass( _trail( str( tmp_path ), rows ), since=0.0, n_per_pass=50 )
    assert cold == {} and sorted( warm ) == [ "w" ]


# ---------------------------------------------------------------------------
# A refusal must say WHY it is zero. "0 shared" reads as a broken tool, while 49
# shared from the WRONG pairing reads as a healthy sample — the numbers give the
# opposite impression to the truth (Mr Radio, 2026-08-20).
# ---------------------------------------------------------------------------
def test_a_not_ready_run_says_so_rather_than_looking_broken():
    text, ok = pw.render( { "a": 100.0 }, {}, { "a": "math" }, 20, [ "math" ],
                          v2_cold={ "a": 90.0, "b": 80.0 } )
    assert ok is False
    assert "NOT a broken tool" in text
    assert "2 COLD spans and 0 WARM" in text
    assert "still inside its first pass of 20" in text


def test_two_arms_that_measured_DIFFERENT_utterances_is_named_as_provenance_not_timing():
    """Both arms have warm spans but share nothing. That is a different failure from a
    not-ready run and must not be reported as one."""
    text, ok = pw.render( { "a": 100.0 }, { "z": 50.0 }, { "a": "math", "z": "math" }, 20, [ "math" ],
                          v2_cold={} )
    assert ok is False
    assert "provenance problem, not a timing one" in text
    assert "NOT a broken tool" not in text


def test_an_empty_v1_side_points_at_the_artifact():
    text, ok = pw.render( {}, {}, {}, 20, [ "math" ], v2_cold={} )
    assert ok is False
    assert "no spans at all" in text


def test_every_refusal_warns_against_reaching_for_the_cold_pass():
    """The tempting wrong move, with the receipt attached so nobody re-derives it."""
    for v1, warm, cold in ( ( { "a": 1.0 }, {}, { "a": 1.0 } ),
                            ( { "a": 1.0 }, { "z": 1.0 }, {} ),
                            ( {}, {}, {} ) ):
        text, _ = pw.render( v1, warm, { "a": "math", "z": "math" }, 20, [ "math" ], v2_cold=cold )
        assert "Do not reach for the cold pass" in text
        assert "49 shared utterances" in text


# ---------------------------------------------------------------------------
# The sample-size floor. The tool fired at n=2 the instant v2's warm pass began
# on 2026-08-20 — a median over two points, offered as if it were a result.
# ---------------------------------------------------------------------------
def _many( n, v1_ms, v2_ms ):
    return ( { f"u{i}": float( v1_ms ) for i in range( n ) },
             { f"u{i}": float( v2_ms ) for i in range( n ) },
             { f"u{i}": "math" for i in range( n ) } )


def test_a_pairing_below_the_floor_is_flagged_and_returns_not_ok():
    v1, v2, mapping = _many( 2, 3484, 22227 )
    text, ok = pw.render( v1, v2, mapping, 20, [ "math" ], v2_cold={} )
    assert ok is False                                   # exit code must not read as success
    assert "BELOW THE 30-PAIR FLOOR" in text
    assert "not yet a number" in text
    assert "NOT so they can be quoted" in text


def test_the_figures_are_still_shown_below_the_floor_so_progress_is_visible():
    """Hiding them entirely would make a growing run look identical to a broken one —
    the same mistake as a bare zero."""
    v1, v2, mapping = _many( 2, 3484, 22227 )
    text, _ = pw.render( v1, v2, mapping, 20, [ "math" ], v2_cold={} )
    assert "**POOLED**" in text and "3484 ms" in text


def test_a_pairing_at_the_floor_is_accepted():
    v1, v2, mapping = _many( 30, 1000, 500 )
    text, ok = pw.render( v1, v2, mapping, 20, [ "math" ], v2_cold={} )
    assert ok is True
    assert "BELOW THE" not in text


def test_the_floor_is_the_REAL_gate_s_floor_not_a_second_copy():
    """A threshold duplicated is a threshold that drifts. RED if this tool ever stops
    agreeing with the gate that actually decides go/no-go."""
    import paired_eval
    v1, v2, mapping = _many( paired_eval.MIN_SHARED_PAIRS - 1, 1000, 500 )
    _text, ok = pw.render( v1, v2, mapping, 20, [ "math" ], v2_cold={} )
    assert ok is False
    v1, v2, mapping = _many( paired_eval.MIN_SHARED_PAIRS, 1000, 500 )
    _text, ok = pw.render( v1, v2, mapping, 20, [ "math" ], v2_cold={} )
    assert ok is True
