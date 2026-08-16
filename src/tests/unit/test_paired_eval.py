"""
Unit tests for src/scripts/paired_eval.py — the provenance-gated caller AND the §6 paired
median-Δ latency gate (moved here from v2_eval.py, rebuilt per Tiffany's B2).

VENUE: :7999 — pure, no server, no inference, well under 2 min.

TWO CONTROLS carry this file:
  1. test_gate_median_of_deltas_disagrees_with_difference_of_medians — the STATISTIC control.
     On this fixture median-of-Δ says FAIL/v1-faster while difference-of-medians says
     PASS/v2-faster. It pins the median-of-Δ answer, so reverting to the old (wrong)
     statistic flips it red. Coverage cannot catch a wrong statistic; only this can.
  2. test_provenance_mismatch_blocks_a_gate_that_would_fire — the WIRING control. Two arms
     with valid instruments WOULD fire; the provenance mismatch declines them. Delete the
     provenance check and it flips to fired=True.

Seam note: this module is PURE, so its "seams" are the real gate math (statistics.median, not
mocked), real sha256 signatures, and real tmp_path file IO — no mock stands in for any of them.
"""

import os
import statistics
import sys

import pytest

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _LUPIN_ROOT, "src" ), os.path.join( _LUPIN_ROOT, "src", "scripts" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

import paired_eval as pe   # noqa: E402


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
_PAIRS_A = [ ( "turn on the lights", "cmd_lights" ), ( "what time is it", "cmd_time" ) ]
_PAIRS_B = [ ( "play some jazz",     "cmd_music" ) ]


def _prov( arm, pairs=_PAIRS_A, corpus="simple", seed=1024, n=60 ):
    return pe.make_provenance( arm, corpus, seed, n, pairs )


def _metrics( spans_by_utt, p95=None ):
    return { "spans_by_utterance": dict( spans_by_utt ), "client_p95_ms": p95 }


def _artifact( spans_by_utt, provenance, p95=None ):
    return { "metrics": _metrics( spans_by_utt, p95 ), "provenance": provenance }


# ---------------------------------------------------------------------------
# compute_sample_signature
# ---------------------------------------------------------------------------
def test_signature_is_order_independent_and_deduped():
    a = pe.compute_sample_signature( [ ( "u1", "c1" ), ( "u2", "c2" ) ] )
    b = pe.compute_sample_signature( [ ( "u2", "c2" ), ( "u1", "c1" ), ( "u1", "c1" ) ] )
    assert a == b


def test_signature_binds_the_command_not_just_the_utterance():
    assert pe.compute_sample_signature( [ ( "x", "c1" ) ] ) != pe.compute_sample_signature( [ ( "x", "c2" ) ] )


def test_signature_separator_prevents_boundary_collision():
    assert pe.compute_sample_signature( [ ( "a", "bc" ) ] ) != pe.compute_sample_signature( [ ( "ab", "c" ) ] )


# ---------------------------------------------------------------------------
# make_provenance / _missing_provenance_fields
# ---------------------------------------------------------------------------
def test_make_provenance_carries_all_fields_and_counts():
    p = pe.make_provenance( "v1", "simple", 1024, 60, _PAIRS_A )
    assert set( p.keys() ) == set( pe.PROVENANCE_FIELDS )
    assert p[ "arm" ] == "v1" and p[ "corpus" ] == "simple" and p[ "seed" ] == 1024
    assert p[ "n_per_command" ] == 60 and p[ "sampled_n" ] == 2
    assert p[ "sample_signature" ] == pe.compute_sample_signature( _PAIRS_A )


def test_missing_fields_reports_absent_keys():
    assert pe._missing_provenance_fields( _prov( "v1" ) ) == []
    missing = pe._missing_provenance_fields( { "arm": "v1", "corpus": "simple" } )
    assert "seed" in missing and "sample_signature" in missing


# ---------------------------------------------------------------------------
# paired_provenance_check
# ---------------------------------------------------------------------------
def test_provenance_check_passes_on_identical_stamps():
    assert pe.paired_provenance_check( _prov( "v1" ), _prov( "v2" ) ) is None


def test_provenance_check_names_missing_fields_on_either_arm():
    assert "v1 provenance is missing" in pe.paired_provenance_check( { "arm": "v1" }, _prov( "v2" ) )
    assert "v2 provenance is missing" in pe.paired_provenance_check( _prov( "v1" ), { "arm": "v2" } )


def test_provenance_check_flags_empty_arm():
    v1_empty = pe.make_provenance( "v1", "simple", 1024, 60, [] )
    v2_empty = pe.make_provenance( "v2", "simple", 1024, 60, [] )
    assert "v1 measured 0 utterances" in pe.paired_provenance_check( v1_empty, _prov( "v2" ) )
    assert "v2 measured 0 utterances" in pe.paired_provenance_check( _prov( "v1" ), v2_empty )


def test_provenance_check_names_each_disagreeing_field():
    v1 = _prov( "v1", pairs=_PAIRS_A, corpus="simple", seed=1024, n=60 )
    v2 = _prov( "v2", pairs=_PAIRS_B, corpus="weather", seed=99, n=30 )
    reason = pe.paired_provenance_check( v1, v2 )
    for field in ( "corpus differs", "seed differs", "n_per_command differs", "sample_signature differs" ):
        assert field in reason


def test_provenance_check_catches_signature_mismatch_alone():
    reason = pe.paired_provenance_check( _prov( "v1", pairs=_PAIRS_A ), _prov( "v2", pairs=_PAIRS_B ) )
    assert "sample_signature differs" in reason and "corpus differs" not in reason


# ---------------------------------------------------------------------------
# _spans_by_utterance / _arm_instrument_reason
# ---------------------------------------------------------------------------
def test_spans_by_utterance_present_absent_empty_and_nondict():
    assert pe._spans_by_utterance( { "spans_by_utterance": { "a": 1.0 } } ) == { "a": 1.0 }
    assert pe._spans_by_utterance( {} ) is None                              # absent
    assert pe._spans_by_utterance( { "spans_by_utterance": {} } ) is None    # empty
    assert pe._spans_by_utterance( { "spans_by_utterance": "nope" } ) is None  # not a dict


def test_arm_instrument_reason_present_and_absent():
    assert pe._arm_instrument_reason( { "spans_by_utterance": { "a": 1.0 } }, "v2" ) is None
    assert "per-utterance client spans" in pe._arm_instrument_reason( {}, "v1" )


# ---------------------------------------------------------------------------
# paired_median_delta_gate — the §6 statistic
# ---------------------------------------------------------------------------
def test_gate_fires_pass_when_v2_at_least_20pct_faster():
    g = pe.paired_median_delta_gate(
        _metrics( { "a": 100.0, "b": 100.0, "c": 100.0 } ),
        _metrics( { "a": 40.0,  "b": 40.0,  "c": 40.0 } ),
    )
    assert g[ "fired" ] is True and g[ "verdict" ] == "PASS" and g[ "pass" ] is True
    assert g[ "median_delta_ms" ] == 60 and g[ "v1_median_ms" ] == 100 and g[ "threshold_ms" ] == 20.0
    assert g[ "faster_arm" ] == "v2" and g[ "n_shared" ] == 3 and g[ "n_dropped" ] == 0


def test_gate_fires_fail_when_v2_not_fast_enough():
    g = pe.paired_median_delta_gate(
        _metrics( { "a": 100.0, "b": 100.0, "c": 100.0 } ),
        _metrics( { "a": 95.0,  "b": 95.0,  "c": 95.0 } ),
    )
    assert g[ "verdict" ] == "FAIL" and g[ "pass" ] is False
    assert g[ "median_delta_ms" ] == 5 and g[ "threshold_ms" ] == 20.0 and g[ "faster_arm" ] == "v2"


def test_gate_median_of_deltas_disagrees_with_difference_of_medians():
    """THE STATISTIC CONTROL. On this fixture the two statistics give OPPOSITE verdicts.
    median-of-Δ (correct) = -3 → FAIL, v1 faster. difference-of-medians = +1 → would PASS,
    v2 faster. Pinning the median-of-Δ answer makes a revert to the old statistic go red."""
    v1_spans = { "a": 1.0, "b": 5.0, "c": 6.0 }
    v2_spans = { "a": 4.0, "b": 2.0, "c": 9.0 }
    g = pe.paired_median_delta_gate( _metrics( v1_spans ), _metrics( v2_spans ) )

    # The correct statistic: median of per-utterance Δ = median([-3, 3, -3]) = -3.
    assert g[ "median_delta_ms" ] == -3
    assert g[ "v1_median_ms" ] == 5 and g[ "threshold_ms" ] == 1.0
    assert g[ "verdict" ] == "FAIL" and g[ "faster_arm" ] == "v1"

    # The WRONG statistic (what the old gate computed) would give the opposite sign here —
    # difference of medians = median(v1) - median(v2) = 5 - 4 = +1. Prove they truly differ,
    # so this test cannot pass under the difference-of-medians implementation.
    difference_of_medians = statistics.median( v1_spans.values() ) - statistics.median( v2_spans.values() )
    assert difference_of_medians == 1.0
    assert g[ "median_delta_ms" ] != difference_of_medians


def test_gate_tie_when_median_delta_is_zero():
    g = pe.paired_median_delta_gate( _metrics( { "a": 10.0, "b": 10.0 } ), _metrics( { "a": 10.0, "b": 10.0 } ) )
    assert g[ "median_delta_ms" ] == 0 and g[ "faster_arm" ] == "tie" and g[ "verdict" ] == "FAIL"


def test_gate_records_drop_counts_for_unshared_utterances():
    g = pe.paired_median_delta_gate(
        _metrics( { "a": 100.0, "b": 100.0, "x": 100.0 } ),
        _metrics( { "a": 40.0,  "b": 40.0,  "y": 40.0 } ),
    )
    assert g[ "n_shared" ] == 2 and g[ "n_dropped" ] == 2
    assert g[ "dropped_v1_only" ] == 1 and g[ "dropped_v2_only" ] == 1


def test_gate_declines_naming_each_arm_missing_the_instrument():
    g = pe.paired_median_delta_gate( {}, _metrics( { "a": 1.0 } ) )
    assert g[ "fired" ] is False and "v1 arm did not report" in g[ "reason" ]
    g2 = pe.paired_median_delta_gate( {}, {} )
    assert "v1 arm did not report" in g2[ "reason" ] and "v2 arm did not report" in g2[ "reason" ]


def test_gate_declines_on_zero_shared_pairs():
    g = pe.paired_median_delta_gate( _metrics( { "a": 1.0 } ), _metrics( { "b": 1.0 } ) )
    assert g[ "fired" ] is False and "0 shared pairs" in g[ "reason" ]


def test_gate_declines_on_nonpositive_v1_median():
    g = pe.paired_median_delta_gate( _metrics( { "a": 0.0, "b": 0.0 } ), _metrics( { "a": 1.0, "b": 1.0 } ) )
    assert g[ "fired" ] is False and "non-positive" in g[ "reason" ]


def test_gate_carries_p95_as_informational():
    g = pe.paired_median_delta_gate(
        _metrics( { "a": 100.0, "b": 100.0 }, p95=180.0 ),
        _metrics( { "a": 40.0,  "b": 40.0 },  p95=70.0 ),
    )
    assert g[ "v1_p95_ms" ] == 180.0 and g[ "v2_p95_ms" ] == 70.0


# ---------------------------------------------------------------------------
# build_paired_verdict — the wiring
# ---------------------------------------------------------------------------
def test_build_verdict_fires_when_provenance_matches_and_instruments_present():
    v1 = _artifact( { "a": 100.0, "b": 100.0 }, _prov( "v1" ) )
    v2 = _artifact( { "a": 40.0,  "b": 40.0 },  _prov( "v2" ) )
    verdict = pe.build_paired_verdict( v1, v2 )
    assert verdict[ "fired" ] is True and verdict[ "provenance_ok" ] is True
    assert verdict[ "verdict" ] == "PASS" and verdict[ "faster_arm" ] == "v2"


def test_build_verdict_declines_on_provenance_mismatch_without_calling_gate():
    v1 = _artifact( { "a": 100.0 }, _prov( "v1", pairs=_PAIRS_A ) )
    v2 = _artifact( { "a": 40.0 },  _prov( "v2", pairs=_PAIRS_B ) )   # different sample
    verdict = pe.build_paired_verdict( v1, v2 )
    assert verdict[ "fired" ] is False and verdict[ "provenance_ok" ] is False
    assert verdict[ "reason" ].startswith( "paired gate DECLINED (provenance) —" )
    assert "sample_signature differs" in verdict[ "reason" ]
    assert "median_delta_ms" not in verdict          # the gate never ran


def test_provenance_mismatch_blocks_a_gate_that_would_fire():
    """WIRING CONTROL. Both arms carry valid instruments, so the bare gate WOULD fire; only
    the provenance mismatch declines it. Delete paired_provenance_check and this flips."""
    v1 = _artifact( { "a": 100.0, "b": 100.0 }, _prov( "v1", pairs=_PAIRS_A ) )
    v2 = _artifact( { "a": 40.0,  "b": 40.0 },  _prov( "v2", pairs=_PAIRS_B ) )
    bare = pe.paired_median_delta_gate( v1[ "metrics" ], v2[ "metrics" ] )
    assert bare[ "fired" ] is True                                    # the metrics WOULD fire
    assert pe.build_paired_verdict( v1, v2 )[ "fired" ] is False      # provenance refuses


def test_build_verdict_provenance_ok_but_instrument_declines():
    v1 = _artifact( { "a": 100.0 }, _prov( "v1" ) )
    v2 = { "metrics": { "spans_by_utterance": {} }, "provenance": _prov( "v2" ) }
    verdict = pe.build_paired_verdict( v1, v2 )
    assert verdict[ "provenance_ok" ] is True and verdict[ "fired" ] is False
    assert "v2 arm did not report" in verdict[ "reason" ]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def test_render_verdict_declined_and_fired():
    declined = pe.render_paired_verdict( { "fired": False, "reason": "paired latency gate DECLINED — x" } )
    assert "DECLINED — no number emitted" in declined and "DECLINED — x" in declined
    fired = pe.render_paired_verdict( pe.paired_median_delta_gate(
        _metrics( { "a": 100.0, "b": 100.0 }, p95=180.0 ), _metrics( { "a": 40.0, "b": 40.0 }, p95=70.0 ) ) )
    assert "VERDICT: PASS" in fired
    assert "queue-dwell" in fired            # the fix-#2 residual prints in the table
    assert "INFORMATIONAL" in fired and "faster arm: v2" in fired


def test_render_provenance_block_match_and_mismatch():
    assert "MATCH — arms measured the same sample" in pe.render_provenance_block( _prov( "v1" ), _prov( "v2" ) )
    assert "MISMATCH" in pe.render_provenance_block( _prov( "v1", pairs=_PAIRS_A ), _prov( "v2", pairs=_PAIRS_B ) )


def test_render_provenance_block_handles_non_string_signature():
    bad = { "arm": "v1", "corpus": "simple", "seed": 1, "n_per_command": 1, "sampled_n": 1 }
    block = pe.render_provenance_block( bad, _prov( "v2" ) )
    assert "None" in block and "MISMATCH" in block


def test_render_paired_report_carries_provenance_and_verdict():
    v1 = _artifact( { "a": 100.0, "b": 100.0 }, _prov( "v1" ) )
    v2 = _artifact( { "a": 40.0,  "b": 40.0 },  _prov( "v2" ) )
    report = pe.render_paired_report( pe.build_paired_verdict( v1, v2 ),
                                      v1[ "provenance" ], v2[ "provenance" ], "2026-08-16-12-00-00" )
    assert "# CJ Flow paired v1-vs-v2 latency verdict — 2026-08-16-12-00-00" in report
    assert "## Sample provenance" in report and "Paired median-Δ latency gate" in report


# ---------------------------------------------------------------------------
# load_arm_artifact
# ---------------------------------------------------------------------------
def test_load_arm_artifact_reads_valid_json( tmp_path ):
    import json
    path = tmp_path / "v1.json"
    path.write_text( json.dumps( _artifact( { "a": 1.0 }, _prov( "v1" ) ) ) )
    art = pe.load_arm_artifact( str( path ) )
    assert "metrics" in art and "provenance" in art


def test_load_arm_artifact_raises_on_missing_keys( tmp_path ):
    import json
    path = tmp_path / "bad.json"
    path.write_text( json.dumps( { "metrics": {} } ) )
    with pytest.raises( ValueError, match="missing top-level key" ):
        pe.load_arm_artifact( str( path ) )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
class _FakeStamp:
    def strftime( self, fmt ):
        return "STAMPED"


def test_main_writes_report_explicit_out( tmp_path ):
    artifacts = {
        "v1.json": _artifact( { "a": 100.0, "b": 100.0 }, _prov( "v1" ) ),
        "v2.json": _artifact( { "a": 40.0,  "b": 40.0 },  _prov( "v2" ) ),
    }
    out = tmp_path / "paired.md"
    result = pe.main(
        argv=[ "--v1-artifact", "v1.json", "--v2-artifact", "v2.json", "--out", str( out ) ],
        load_fn=lambda p: artifacts[ os.path.basename( p ) ],
        project_root=str( tmp_path ), timestamp="2026-08-16-12-00-00",
    )
    assert result[ "out_path" ] == str( out ) and result[ "verdict" ][ "verdict" ] == "PASS"
    assert "MATCH" in out.read_text()


def test_main_default_out_path_and_du_fallbacks( tmp_path, monkeypatch ):
    monkeypatch.setattr( pe.du, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( pe.du, "get_current_datetime_raw", lambda: _FakeStamp() )
    def _load( path ):
        return _artifact( { "a": 100.0 }, _prov( "v1" ) ) if "v1" in path else _artifact( { "a": 40.0 }, _prov( "v2" ) )
    result = pe.main( argv=[ "--v1-artifact", "a-v1.json", "--v2-artifact", "b-v2.json" ], load_fn=_load )
    expected = os.path.join( str( tmp_path ), "io", "v2-flow", "paired-verdict-STAMPED.md" )
    assert result[ "out_path" ] == expected and os.path.exists( expected )
