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

# A sample AT the minimum-shared-pairs floor (row b7658173). Any test that expects
# build_paired_verdict to FIRE needs at least this many shared utterances, since the
# go/no-go layer refuses a thinner sample. Sized off the constant, never a literal 30,
# so raising the floor moves these fixtures with it instead of turning them red.
_PAIRS_FLOOR = [ ( f"utterance {i}", f"cmd_{i % 6}" ) for i in range( pe.MIN_SHARED_PAIRS ) ]


# The two arms legitimately run DIFFERENT trees — v1 a pinned worktree, v2 whatever is
# deployed — so these differ on purpose. The sha check is presence, never equality.
_V1_SHA = "15536409"   # the v1 pin since 2026-08-21 (rows 647f3733/297b1fc3); fixture data, presence-checked
_V2_SHA = "f7c5e349"


def _prov( arm, pairs=_PAIRS_A, corpus="simple", seed=1024, n=60, git_sha=None ):
    if git_sha is None:
        git_sha = _V1_SHA if arm == "v1" else _V2_SHA
    return pe.make_provenance( arm, corpus, seed, n, pairs, git_sha=git_sha )


def _metrics( spans_by_utt, p95=None ):
    return { "spans_by_utterance": dict( spans_by_utt ), "client_p95_ms": p95 }


def _artifact( spans_by_utt, provenance, p95=None ):
    return { "metrics": _metrics( spans_by_utt, p95 ), "provenance": provenance }


def _spans_at_floor( span_ms, pairs=_PAIRS_FLOOR ):
    """One identical span per utterance of `pairs` — a sample the floor lets through."""
    return { utterance: span_ms for utterance, _ in pairs }


def _floor_artifact( arm, span_ms, pairs=_PAIRS_FLOOR ):
    """An artifact whose provenance and spans describe the SAME sample, at the floor."""
    return _artifact( _spans_at_floor( span_ms, pairs ), _prov( arm, pairs=pairs ) )


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
    p = pe.make_provenance( "v1", "simple", 1024, 60, _PAIRS_A, git_sha=_V1_SHA )
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
    v1_empty = pe.make_provenance( "v1", "simple", 1024, 60, [], git_sha=_V1_SHA )
    v2_empty = pe.make_provenance( "v2", "simple", 1024, 60, [], git_sha=_V2_SHA )
    # SAMPLED, not measured (row b7658173): this check reads sampled_n — what the run
    # INTENDED to draw — so the sentence must not claim the outcome count.
    assert "v1 sampled 0 utterances" in pe.paired_provenance_check( v1_empty, _prov( "v2" ) )
    assert "v2 sampled 0 utterances" in pe.paired_provenance_check( _prov( "v1" ), v2_empty )


def test_provenance_check_names_each_disagreeing_field():
    v1 = _prov( "v1", pairs=_PAIRS_A, corpus="simple", seed=1024, n=60 )
    v2 = _prov( "v2", pairs=_PAIRS_B, corpus="weather", seed=99, n=30 )
    reason = pe.paired_provenance_check( v1, v2 )
    for field in ( "corpus differs", "seed differs", "n_per_command differs", "sample_signature differs" ):
        assert field in reason


def test_an_unrecorded_tree_refuses_a_gate_that_would_otherwise_pass():
    """THE c9b43538 CONTROL — proven by deletion, not by coverage.

    Before the fix, this exact fixture produced `provenance_ok: True`, `fired: True`,
    `verdict: PASS`, `median_delta_ms: 1500.0`, and a report reading
    "Provenance: MATCH — arms measured the same sample." Nobody had recorded which tree
    produced either arm's numbers, and nothing downstream noticed: the sha was absent from
    PROVENANCE_FIELDS, never compared across arms, ignored by the gate arithmetic, and
    rendered as an ordinary em-dash.

    The pairing is otherwise PERFECT — same corpus, seed, n_per_command and signature — so
    the only thing that can decline it is the missing tree. Restore the em-dash default or
    drop git_sha from PROVENANCE_FIELDS and this flips back to a confident PASS.
    """
    pairs = [ ( f"utterance {i}", "agent router go to math" ) for i in range( 30 ) ]
    # A stamp that has the KEY but no value — the shape a skipped read actually takes,
    # since read_running_server_sha returns "" when the server does not answer.
    v1 = { **_prov( "v1", pairs=pairs ), "git_sha": "" }
    v2 = { **_prov( "v2", pairs=pairs ), "git_sha": "" }

    verdict = pe.build_paired_verdict(
        _artifact( { u: 2000.0 for u, _ in pairs }, v1 ),
        _artifact( { u:  500.0 for u, _ in pairs }, v2 ),
    )
    assert verdict[ "fired" ] is False and verdict[ "provenance_ok" ] is False
    assert "v1 did not record the git sha" in verdict[ "reason" ]
    assert "v2 did not record the git sha" in verdict[ "reason" ]
    assert "median_delta_ms" not in verdict          # no number escapes an untraceable pair


def test_provenance_check_accepts_two_arms_on_different_trees():
    # The arms run DIFFERENT trees by design — v1 a pinned worktree, v2 whatever is deployed.
    # The sha check must be presence, never equality; an equality check would refuse every
    # legitimate paired run. Guards against over-tightening the fix above.
    assert pe.paired_provenance_check( _prov( "v1", git_sha="b0735467" ),
                                       _prov( "v2", git_sha="f7c5e349" ) ) is None


def test_provenance_check_names_a_blank_sha_on_one_arm_only():
    # Half-recorded provenance is still untraceable: one arm's sha does not cover the pair.
    reason = pe.paired_provenance_check( _prov( "v1" ), { **_prov( "v2" ), "git_sha": "   " } )
    assert "v2 did not record the git sha" in reason and "v1 did not record" not in reason


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
    verdict = pe.build_paired_verdict( _floor_artifact( "v1", 100.0 ), _floor_artifact( "v2", 40.0 ) )
    assert verdict[ "fired" ] is True and verdict[ "provenance_ok" ] is True
    assert verdict[ "verdict" ] == "PASS" and verdict[ "faster_arm" ] == "v2"


def test_build_verdict_refuses_a_go_no_go_decided_by_one_utterance():
    """THE FLOOR CONTROL (María's ruling, row b7658173). Before the floor this fired
    verdict PASS at n_shared=1 — a ship decision taken on a single utterance."""
    one     = [ _PAIRS_FLOOR[ 0 ] ]
    verdict = pe.build_paired_verdict( _floor_artifact( "v1", 100.0, one ),
                                       _floor_artifact( "v2", 40.0,  one ) )
    assert verdict[ "fired" ] is False and verdict[ "provenance_ok" ] is True
    assert verdict[ "n_shared" ] == 1 and "verdict" not in verdict
    assert f"below the {pe.MIN_SHARED_PAIRS}-pair floor" in verdict[ "reason" ]


def test_the_gate_has_exactly_one_non_test_caller():
    """THE DEPENDENCY GUARD (María, row b7658173). The floor lives in
    build_paired_verdict, and that covers every production path ONLY because it is
    paired_median_delta_gate's sole non-test caller. Nothing in the language enforces
    that, so a second caller would silently ship un-floored verdicts and nobody would
    find out. This test is what finds out.

    If you are adding a caller and this went red: route it through build_paired_verdict,
    or apply the MIN_SHARED_PAIRS floor yourself, then add it to _ALLOWED below."""
    import re

    _ALLOWED = { "src/scripts/paired_eval.py" }   # the definition + build_paired_verdict's call

    root    = os.path.join( _LUPIN_ROOT, "src" )
    callers = set()
    for directory, dirs, files in os.walk( root ):
        dirs[ : ] = [ d for d in dirs if d not in ( "__pycache__", ".venv", "node_modules" ) ]
        if f"{os.sep}tests{os.sep}" in f"{directory}{os.sep}": continue
        for name in files:
            if not name.endswith( ".py" ): continue
            path = os.path.join( directory, name )
            # errors="ignore": a non-UTF8 byte cannot hide an ASCII identifier, and one
            # undecodable file must not blind the whole scan.
            with open( path, encoding="utf-8", errors="ignore" ) as handle: text = handle.read()
            # a CALL, not the def line and not a bare mention in prose
            if re.search( r"(?<!def )paired_median_delta_gate\s*\(", text ):
                callers.add( os.path.relpath( path, _LUPIN_ROOT ) )

    assert callers == _ALLOWED, (
        f"paired_median_delta_gate gained a caller outside {_ALLOWED}: {sorted( callers - _ALLOWED )}. "
        "The MIN_SHARED_PAIRS floor lives in build_paired_verdict, so a caller that skips it "
        "reports a go/no-go over a sample the floor would have refused (row b7658173)."
    )


def test_build_verdict_refuses_one_pair_below_the_floor():
    """The boundary's REFUSING side. One short must refuse, or the floor is off by one."""
    under   = _PAIRS_FLOOR[ : pe.MIN_SHARED_PAIRS - 1 ]
    verdict = pe.build_paired_verdict( _floor_artifact( "v1", 100.0, under ),
                                       _floor_artifact( "v2", 40.0,  under ) )
    assert verdict[ "fired" ] is False
    assert verdict[ "n_shared" ] == pe.MIN_SHARED_PAIRS - 1


def test_build_verdict_fires_exactly_at_the_floor():
    """The boundary's PROCEEDING side. AT the floor must fire — the floor is a minimum,
    not a threshold to exceed."""
    verdict = pe.build_paired_verdict( _floor_artifact( "v1", 100.0 ), _floor_artifact( "v2", 40.0 ) )
    assert verdict[ "fired" ] is True and verdict[ "verdict" ] == "PASS"
    assert verdict[ "n_shared" ] == pe.MIN_SHARED_PAIRS


def test_build_verdict_still_fires_on_a_healthy_run():
    """THE OTHER HALF, the one that is easy to skip: without it the floor could buy safety
    by refusing everything and still look correct."""
    healthy = [ ( f"healthy {i}", f"cmd_{i % 6}" ) for i in range( 480 ) ]
    verdict = pe.build_paired_verdict( _floor_artifact( "v1", 100.0, healthy ),
                                       _floor_artifact( "v2", 40.0,  healthy ) )
    assert verdict[ "fired" ] is True and verdict[ "verdict" ] == "PASS"
    assert verdict[ "n_shared" ] == 480


def test_the_gate_itself_keeps_computing_the_statistic_below_the_floor():
    """The floor is a GO/NO-GO policy, not part of the statistic. paired_median_delta_gate
    stays pure so its small-fixture tests keep meaning what they say; refusing a thin
    sample is build_paired_verdict's job."""
    g = pe.paired_median_delta_gate( _metrics( { "a": 100.0, "b": 100.0 } ),
                                     _metrics( { "a": 40.0,  "b": 40.0 } ) )
    assert g[ "fired" ] is True and g[ "n_shared" ] == 2


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


def test_render_provenance_block_stamps_both_arms_measured_shas():
    # HALF B (row 221de5d2), extended to BOTH arms by c9b43538: the block renders each arm's
    # MEASURED sha so a reader can audit the report back to the trees that produced the
    # numbers. One-armed provenance cannot validate a paired comparison, so v2 is no longer
    # a hard-coded dash. The two shas legitimately differ — presence is the property, not
    # equality.
    block = pe.render_provenance_block( _prov( "v1", git_sha="b0735467cafe" ),
                                        _prov( "v2", git_sha="f7c5e349beef" ) )
    assert "arm sha" in block
    assert "b0735467cafe" in block and "f7c5e349beef" in block


def test_render_provenance_block_unrecorded_sha_cannot_be_misread_as_normal():
    # LAYER 4 CONTROL (c9b43538). The old renderer printed `.get( key, "—" )`, so an arm
    # whose tree nobody recorded looked exactly like an arm that legitimately had nothing to
    # show. A reader could not tell "no pin by design" from "never checked". An unrecorded
    # sha must now announce itself. RED against the old em-dash default.
    block = pe.render_provenance_block( { **_prov( "v1" ), "git_sha": "" },
                                        { **_prov( "v2" ), "git_sha": None } )
    assert block.count( "NOT RECORDED" ) == 2
    assert "| arm sha | — |" not in block          # never the silent dash again


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
        "v1.json": _floor_artifact( "v1", 100.0 ),
        "v2.json": _floor_artifact( "v2", 40.0 ),
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


# ---------------------------------------------------------------------------
# the readability block (5dfe0d43's ruling, finally implemented)
#
# "The report must carry the per-arm failure rate and each arm's surviving category
# composition beside the median delta, or the number is not readable at any n."
# The report carried none of it, so a bare delta over survivors read as a verdict.
# ---------------------------------------------------------------------------
_V1_M = { "n": 100, "ok_n": 72, "failure_rate": 0.28,
          "spans_by_utterance": { "turn on the lights": 120.0, "what time is it": 130.0 } }
_V2_M = { "n": 100, "n_ok": 94, "cache_hit_rate": 0.61,
          "spans_by_utterance": { "turn on the lights": 40.0 } }
_MAP  = { "turn on the lights": "cmd_lights", "what time is it": "cmd_time" }


def test_failure_rate_prefers_the_arms_own_published_value():
    assert pe._arm_failure_rate( _V1_M ) == 0.28


def test_failure_rate_is_derived_when_the_arm_publishes_only_a_count():
    """v1 emits ok_n, v2 emits n_ok — reading one key only is how ts-217961e6 KeyError'd."""
    assert pe._arm_failure_rate( _V2_M ) == 0.06
    assert pe._arm_failure_rate( { "n": 10, "ok_n": 8 } ) == 0.2


def test_failure_rate_is_none_rather_than_a_fabricated_zero():
    assert pe._arm_failure_rate( { } )                 is None
    assert pe._arm_failure_rate( { "n": 0, "n_ok": 0 } ) is None


def test_readability_block_carries_both_failure_rates_and_the_cache_hit_rate():
    block = pe.render_readability_block( _V1_M, _V2_M, _MAP )
    assert "28.0%" in block and "6.0%" in block      # the two failure rates
    assert "61.0%" in block                          # v2's cache-hit rate — the mechanism under test


def test_readability_block_says_not_reported_rather_than_inventing_a_number():
    block = pe.render_readability_block( { }, { }, None )
    assert "not reported" in block
    assert "0.0%" not in block


def test_readability_block_counts_survivors_per_command():
    block = pe.render_readability_block( _V1_M, _V2_M, _MAP )
    assert "| cmd_lights | 1 | 1 |" in block
    assert "| cmd_time | 1 | 0 |" in block           # a category v2 lost entirely


def test_readability_block_says_composition_not_computed_without_a_mapping():
    """An absent composition must read as 'not computed', never as an empty one."""
    block = pe.render_readability_block( _V1_M, _V2_M, None )
    assert "NOT COMPUTED" in block
    assert "v1 survived" not in block


def test_report_carries_the_readability_block_when_metrics_are_supplied():
    report = pe.render_paired_report( { "fired": False, "reason": "r" }, _prov( "v1" ), _prov( "v2" ), "TS",
                                      v1_metrics=_V1_M, v2_metrics=_V2_M, mapping=_MAP )
    assert "Is this delta readable?" in report
    assert "28.0%" in report and "61.0%" in report


def test_report_without_metrics_is_unchanged_for_existing_callers():
    report = pe.render_paired_report( { "fired": False, "reason": "r" }, _prov( "v1" ), _prov( "v2" ), "TS" )
    assert "Is this delta readable?" not in report
    assert "DECLINED" in report
