"""
Unit tests for the paired replay harness (handoff §7 item 2).

The four tests that matter most are the ones that prove a clean-looking run is
REFUSED rather than recorded:

  · `test_replay_aborts_when_the_tutor_was_disabled` — the F2 failure. A process
    without LUPIN_CONFIG_MGR_CLI_ARGS returns `tutor_enabled: False` on every row,
    both arms agree perfectly, and nothing raises. The harness must abort.
  · `test_replay_aborts_when_the_arm_is_dead` — the F3 failure. Missing ADC gives
    `model_failed` per row and the run completes.
  · `test_fabrication_rate_refuses_to_pick_a_denominator` — the F1 failure. The
    narrow-vs-wide choice is Rick's open decision, not the harness's default.
  · `test_pair_records_refuses_mismatched_arms` — unpaired arms are what the
    freeze exists to prevent; a zip() would hide it.

Every test drives the harness through INJECTED fakes for the tutor and the agent —
no model is called, no server is touched, no state is mutated.

Venue: :7999-eligible.
"""

import os
import json

import pytest

from cosa.research.phi4_flash_lite_study import replay_harness as RH
from cosa.research.phi4_flash_lite_study import freeze_corpus  as FZ


@pytest.fixture( autouse=True )
def _skip_surface_check( monkeypatch, request ):
    """
    The logic tests inject a fake tutor and must stay hermetic — building a real
    Vertex client to satisfy the arm-surface gate would couple every one of them to
    a resolvable GCP project and a gitignored env file. The gate itself is exercised
    by the tests marked `arm_surface`, which opt out of this fixture.
    """
    if "arm_surface" in request.keywords: return
    monkeypatch.setattr( RH, "verify_arm_surface", lambda arm, factory=None: None )


def _meta( outcome="rewritten", enabled=True, fired=True, claims_out=3, words_out=40 ):
    """A meta dict shaped exactly like the one `_apply_dm_tutor` returns."""
    return {
        "tutor_version"        : "test",
        "tutor_enabled"        : enabled,
        "tutor_trigger_claims" : 4,
        "tutor_gate_enabled"   : False,
        "tutor_fired"          : fired,
        "tutor_outcome"        : outcome,
        "tutor_claims_in"      : 7,
        "tutor_claims_out"     : claims_out,
        "tutor_words_in"       : 120,
        "tutor_words_out"      : words_out,
        "tutor_error"          : None,
        "tutor_fabricated"     : [ "a fact" ] if outcome == "fabrication_blocked" else None,
        "tutor_rescoped"       : None,
        "tutor_id_labels"      : None,
    }


def _rows( n=4 ):
    return [ { "ts": f"2026-08-17T10:0{i}:00", "from": "maria", "to": "rio", "body": f"body {i}" }
             for i in range( n ) ]


def _tutor_returning( outcomes ):
    """A fake `_apply_dm_tutor` that walks a scripted list of outcomes."""
    seq = list( outcomes )
    def fake( body_text, config=None, rewrite_fn=None ):
        spec = seq.pop( 0 )
        meta = spec if isinstance( spec, dict ) else _meta( outcome=spec )
        text = "rewritten text" if meta[ "tutor_outcome" ] == "rewritten" else body_text
        return text, meta
    return fake


# ─────────────────────────────────────────────────────────────────────────────
# F2 — the tutor never ran
# ─────────────────────────────────────────────────────────────────────────────

def test_replay_aborts_when_the_tutor_was_disabled():
    """
    The exact shape of a config-less run: every row `enabled: False`, outcome
    "disabled", nothing raised, both arms perfectly paired and entirely vacuous.
    """
    tutor = _tutor_returning( [ _meta( outcome="disabled", enabled=False, fired=False ) ] * 4 )

    with pytest.raises( RH.UnmeasurableRow ) as excinfo:
        RH.replay_arm( _rows(), RH.ARM_PHI4, tutor_fn=tutor, rewrite_fn=lambda b: "x",
                       max_model_failed_rate=0.05 )

    message = str( excinfo.value )
    assert "tutor_enabled is False" in message
    assert "LUPIN_CONFIG_MGR_CLI_ARGS" in message
    assert "row 0" in message


def test_replay_aborts_when_a_row_did_not_fire():
    """An under-trigger row in the frozen set means snapshot and live config disagree."""
    tutor = _tutor_returning( [ _meta(), _meta( outcome="under_trigger", fired=False ) ] )

    with pytest.raises( RH.UnmeasurableRow ) as excinfo:
        RH.replay_arm( _rows( 2 ), RH.ARM_PHI4, tutor_fn=tutor, rewrite_fn=lambda b: "x",
                       max_model_failed_rate=0.5 )
    assert "tutor_fired is False" in str( excinfo.value )
    assert "row 1" in str( excinfo.value )


def test_assert_row_is_measurable_passes_a_real_row():
    assert RH.assert_row_is_measurable( _meta(), 0, RH.ARM_PHI4 ) is None


# ─────────────────────────────────────────────────────────────────────────────
# F3 — the arm is dead
# ─────────────────────────────────────────────────────────────────────────────

def test_replay_aborts_when_the_arm_is_dead():
    """Missing ADC / dead region: every row `model_failed`, run completes silently."""
    tutor = _tutor_returning( [ "model_failed" ] * 10 )

    with pytest.raises( RH.ArmBroken ) as excinfo:
        RH.replay_arm( _rows( 10 ), RH.ARM_FLASH_LITE, tutor_fn=tutor, rewrite_fn=lambda b: None,
                       max_model_failed_rate=0.05, preflight=5 )
    assert "preflight" in str( excinfo.value )
    assert "1.000" in str( excinfo.value )


def test_preflight_fires_before_the_whole_arm_is_paid_for():
    """The point of a preflight is that it stops early — count the calls."""
    seen  = []
    tutor = _tutor_returning( [ "model_failed" ] * 100 )

    def counting( body, config=None, rewrite_fn=None ):
        seen.append( body )
        return tutor( body, config=config, rewrite_fn=rewrite_fn )

    with pytest.raises( RH.ArmBroken ):
        RH.replay_arm( _rows( 100 ), RH.ARM_FLASH_LITE, tutor_fn=counting, rewrite_fn=lambda b: None,
                       max_model_failed_rate=0.10, preflight=5 )
    assert len( seen ) == 5, f"preflight should have stopped at 5 rows, ran {len( seen )}"


def test_final_check_catches_an_arm_that_degrades_after_the_preflight():
    """Healthy for the first rows, dead afterwards — the preflight alone would miss it."""
    tutor = _tutor_returning( [ "rewritten" ] * 5 + [ "model_failed" ] * 5 )

    with pytest.raises( RH.ArmBroken ) as excinfo:
        RH.replay_arm( _rows( 10 ), RH.ARM_FLASH_LITE, tutor_fn=tutor, rewrite_fn=lambda b: None,
                       max_model_failed_rate=0.10, preflight=5 )
    assert "final" in str( excinfo.value )


def test_replay_demands_a_pre_stated_ceiling():
    """No default: the number is always someone's stated decision."""
    with pytest.raises( ValueError ) as excinfo:
        RH.replay_arm( _rows(), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 4 ),
                       rewrite_fn=lambda b: "x" )
    assert "PRE-STATED" in str( excinfo.value )


def test_model_failed_rate_is_zero_for_no_rows():
    assert RH.model_failed_rate( [] ) == 0.0


def test_assert_arm_is_alive_returns_the_rate_when_under_the_ceiling():
    metas = [ _meta() ] * 9 + [ _meta( outcome="model_failed" ) ]
    assert RH.assert_arm_is_alive( metas, 0.2, RH.ARM_PHI4, "final" ) == pytest.approx( 0.1 )


# ─────────────────────────────────────────────────────────────────────────────
# F1 — the denominator is Rick's, not the harness's
# ─────────────────────────────────────────────────────────────────────────────

def test_the_module_constant_is_unset():
    """If this ever holds a value, someone closed Rick's open decision by editing a file."""
    assert RH.FABRICATION_DENOMINATOR is None


def test_fabrication_rate_refuses_to_pick_a_denominator():
    metas = [ _meta( outcome="fabrication_blocked" ), _meta() ]
    with pytest.raises( RH.DenominatorUnset ) as excinfo:
        RH.fabrication_rate( metas )
    assert "76755526" in str( excinfo.value )
    assert "DENOMINATOR-TBD" in str( excinfo.value )


def test_fabrication_rate_rejects_an_unknown_denominator():
    with pytest.raises( ValueError ):
        RH.fabrication_rate( [ _meta() ], denominator="whatever" )


def test_narrow_and_wide_denominators_differ_on_the_same_rows():
    """The choice is not cosmetic — it moves the headline number."""
    metas = [
        _meta( outcome="fabrication_blocked" ),
        _meta( outcome="rewritten" ),
        _meta( outcome="rescope_blocked" ),
        _meta( outcome="model_failed" ),
    ]
    narrow = RH.fabrication_rate( metas, denominator="narrow" )
    wide   = RH.fabrication_rate( metas, denominator="wide" )

    assert narrow == pytest.approx( 1 / 2 )      # blocked / ( blocked + rewritten )
    assert wide   == pytest.approx( 1 / 4 )      # blocked / every fired row
    assert narrow != wide


def test_fabrication_rate_is_none_when_the_denominator_is_empty():
    """An honest "no rate exists" rather than a zero that reads like a clean arm."""
    assert RH.fabrication_rate( [], denominator="narrow" ) is None
    assert RH.fabrication_rate( [ _meta( outcome="model_failed" ) ], denominator="narrow" ) is None


def test_summarize_arm_reports_the_metrics_that_remain():
    metas = [
        _meta( outcome="fabrication_blocked" ),
        _meta( outcome="rewritten", claims_out=3, words_out=40 ),
        _meta( outcome="rewritten", claims_out=5, words_out=60 ),
        _meta( outcome="rescope_blocked" ),
        _meta( outcome="label_blocked" ),
        _meta( outcome="model_failed" ),
    ]
    summary = RH.summarize_arm( metas, denominator="wide" )

    assert summary[ "rows" ]                == 6
    assert summary[ "fabrication_blocked" ] == 1
    assert summary[ "rescope_blocked" ]     == 1
    assert summary[ "label_blocked" ]       == 1
    assert summary[ "rewritten" ]           == 2
    assert summary[ "model_failed" ]        == 1
    assert summary[ "model_failed_rate" ]   == pytest.approx( 1 / 6 )
    assert summary[ "fabrication_rate" ]    == pytest.approx( 1 / 6 )
    assert summary[ "denominator" ]         == "wide"
    assert summary[ "unknown_outcomes" ]    == []


def test_summarize_arm_surfaces_an_unknown_outcome():
    """A new tutor outcome must show up, not vanish out of every denominator."""
    summary = RH.summarize_arm( [ _meta( outcome="brand_new_refusal" ) ], denominator="wide" )
    assert summary[ "unknown_outcomes" ] == [ "brand_new_refusal" ]


def test_median_handles_empty_odd_and_even():
    assert RH._median( [] )              is None
    assert RH._median( [ 1, 2, 3 ] )     == 2
    assert RH._median( [ 1, 2, 3, 4 ] )  == 2.5


def test_summarize_arm_medians_ignore_the_nulls():
    """`tutor_claims_out` is null on every refused row; a null is not a zero."""
    metas = [
        _meta( outcome="rewritten", claims_out=4, words_out=50 ),
        { **_meta( outcome="fabrication_blocked" ), "tutor_claims_out": None, "tutor_words_out": None },
    ]
    summary = RH.summarize_arm( metas, denominator="wide" )
    assert summary[ "median_claims_out" ] == 4
    assert summary[ "median_words_out" ]  == 50


# ─────────────────────────────────────────────────────────────────────────────
# PAIRING — the reason the freeze exists
# ─────────────────────────────────────────────────────────────────────────────

def test_replay_records_the_meta_verbatim():
    """The work order says verbatim. Not summarized, not re-keyed."""
    original = _meta( outcome="fabrication_blocked" )
    records  = RH.replay_arm( _rows( 1 ), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ original ] ),
                              rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )
    assert records[ 0 ][ "meta" ] == original
    assert records[ 0 ][ "spec_key" ] == "dm_tutor/phi_4"
    assert records[ 0 ][ "delivered_differs" ] is False       # a blocked row delivers the original


def test_replay_carries_the_row_identity_through():
    records = RH.replay_arm( _rows( 2 ), RH.ARM_FLASH_LITE,
                             tutor_fn=_tutor_returning( [ "rewritten", "rewritten" ] ),
                             rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )
    assert [ r[ "row_index" ] for r in records ] == [ 0, 1 ]
    assert records[ 0 ][ "from" ] == "maria"
    assert records[ 0 ][ "ts" ]   == "2026-08-17T10:00:00"
    assert records[ 0 ][ "delivered_differs" ] is True


def test_replay_calls_the_on_row_hook():
    seen = []
    RH.replay_arm( _rows( 3 ), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 3 ),
                   rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, on_row=seen.append )
    assert len( seen ) == 3


def test_pair_records_joins_on_row_index():
    a = RH.replay_arm( _rows( 2 ), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 2 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )
    b = RH.replay_arm( _rows( 2 ), RH.ARM_FLASH_LITE,
                       tutor_fn=_tutor_returning( [ "fabrication_blocked" ] * 2 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )

    paired = RH.pair_records( a, b )
    assert len( paired ) == 2
    assert paired[ 0 ][ "body" ] == "body 0"
    assert paired[ 0 ][ RH.ARM_PHI4 ][ "meta" ][ "tutor_outcome" ]       == "rewritten"
    assert paired[ 0 ][ RH.ARM_FLASH_LITE ][ "meta" ][ "tutor_outcome" ] == "fabrication_blocked"


def test_pair_records_refuses_two_different_draws_of_the_same_size():
    """
    THE finding. Two draws of the same size both produce row_index 0..N-1, so a join
    on row_index passes its own guard while pairing DIFFERENT BODIES — arms that look
    perfectly paired, and McNemar cells built from two populations. Reachable without
    anything odd: --arm runs one arm at a time and --seed has a default.
    """
    rows      = _many_rows( 800 )
    draw_a, _ = RH.draw_seeded_subset( rows, 5, 42 )
    draw_b, _ = RH.draw_seeded_subset( rows, 5, 43 )
    assert [ r[ "frozen_index" ] for r in draw_a ] != [ r[ "frozen_index" ] for r in draw_b ]

    a = RH.replay_arm( draw_a, RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 5 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="abc" )
    b = RH.replay_arm( draw_b, RH.ARM_FLASH_LITE, tutor_fn=_tutor_returning( [ "rewritten" ] * 5 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="abc" )

    assert [ r[ "row_index" ] for r in a ] == [ r[ "row_index" ] for r in b ], \
        "the row_index lists are identical — which is exactly why joining on them was wrong"

    with pytest.raises( ValueError ) as excinfo:
        RH.pair_records( a, b )
    assert "frozen indices differ" in str( excinfo.value )


def test_pair_records_refuses_two_different_snapshots():
    """
    Matching frozen indices across two DIFFERENT freezes is still not a pairing —
    index 25 of one snapshot is not index 25 of another. The old docstring asked for
    this as a precondition nothing checked.
    """
    rows   = _many_rows( 100 )
    draw, _ = RH.draw_seeded_subset( rows, 4, 11 )

    a = RH.replay_arm( draw, RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 4 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="freeze-one" )
    b = RH.replay_arm( draw, RH.ARM_FLASH_LITE, tutor_fn=_tutor_returning( [ "rewritten" ] * 4 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="freeze-two" )

    with pytest.raises( ValueError ) as excinfo:
        RH.pair_records( a, b )
    assert "different frozen snapshots" in str( excinfo.value )


def test_pair_records_refuses_when_the_key_agrees_but_the_body_does_not():
    """
    Belt to the index check's braces. If the indices agree and the bodies do not, the
    records did not come from the snapshot they claim — assert the conclusion, not
    just the premise.
    """
    rows    = _many_rows( 20 )
    draw, _ = RH.draw_seeded_subset( rows, 3, 3 )

    a = RH.replay_arm( draw, RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 3 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="s" )
    b = RH.replay_arm( draw, RH.ARM_FLASH_LITE, tutor_fn=_tutor_returning( [ "rewritten" ] * 3 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="s" )
    b[ 1 ][ "body" ] = "a body from somewhere else"

    with pytest.raises( ValueError ) as excinfo:
        RH.pair_records( a, b )
    assert "different bodies" in str( excinfo.value )


def test_pair_records_joins_a_sampled_run_on_the_frozen_index():
    """The happy path after the fix: same draw, paired on the snapshot's own index."""
    rows    = _many_rows( 500 )
    draw, drawn = RH.draw_seeded_subset( rows, 6, 20260817 )

    a = RH.replay_arm( draw, RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 6 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="s" )
    b = RH.replay_arm( draw, RH.ARM_FLASH_LITE, tutor_fn=_tutor_returning( [ "fabrication_blocked" ] * 6 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, snapshot_sha256="s" )

    paired = RH.pair_records( a, b )
    assert [ p[ "frozen_index" ] for p in paired ] == drawn
    assert all( p[ "body" ] == rows[ p[ "frozen_index" ] ][ "body" ] for p in paired )


def test_pair_records_refuses_mismatched_arms():
    """A zip() would truncate silently; unpaired arms invalidate every comparison."""
    a = RH.replay_arm( _rows( 3 ), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 3 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )
    b = RH.replay_arm( _rows( 2 ), RH.ARM_FLASH_LITE, tutor_fn=_tutor_returning( [ "rewritten" ] * 2 ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )

    with pytest.raises( ValueError ) as excinfo:
        RH.pair_records( a, b )
    assert "not paired" in str( excinfo.value )


def test_discordant_counts_ignores_the_concordant_rows():
    """McNemar reads only the rows where the arms disagreed."""
    def rec( index, arm, outcome ):
        return { "row_index": index, "arm": arm, "body": "b", "meta": _meta( outcome=outcome ) }

    paired = [
        { "row_index": 0, "body": "b", "phi_4": rec( 0, "phi_4", "fabrication_blocked" ),
                                        "flash_lite": rec( 0, "flash_lite", "rewritten" ) },
        { "row_index": 1, "body": "b", "phi_4": rec( 1, "phi_4", "rewritten" ),
                                        "flash_lite": rec( 1, "flash_lite", "fabrication_blocked" ) },
        { "row_index": 2, "body": "b", "phi_4": rec( 2, "phi_4", "fabrication_blocked" ),
                                        "flash_lite": rec( 2, "flash_lite", "fabrication_blocked" ) },
        { "row_index": 3, "body": "b", "phi_4": rec( 3, "phi_4", "rewritten" ),
                                        "flash_lite": rec( 3, "flash_lite", "rewritten" ) },
    ]
    counts = RH.discordant_counts( paired, "phi_4", "flash_lite" )
    assert ( counts[ "b" ], counts[ "c" ] ) == ( 1, 1 )
    assert counts[ "n_discordant" ] == 2
    assert counts[ "n_concordant" ] == 2          # rows 2 and 3 agreed and are excluded


def test_discordant_counts_names_the_arm_not_just_the_letter():
    """
    Sam and I label the two cells in OPPOSITE orders — my b=0,c=5 is his b=5,c=0 for
    the same data. A bare tuple travels without the fact that makes it readable, so
    the first person to quote it gets the direction backwards.
    """
    def rec( index, arm, outcome ):
        return { "row_index": index, "frozen_index": index, "arm": arm, "body": "b",
                 "meta": _meta( outcome=outcome ) }

    paired = [
        { "row_index": i, "frozen_index": i, "body": "b",
          "phi_4"     : rec( i, "phi_4", "rewritten" ),
          "flash_lite": rec( i, "flash_lite", "fabrication_blocked" ) }
        for i in range( 5 )
    ]

    counts = RH.discordant_counts( paired, "phi_4", "flash_lite" )

    assert counts[ "only_flash_lite" ] == 5
    assert counts[ "only_phi_4" ]      == 0
    assert "ONLY phi_4" in counts[ "b_means" ]
    assert "ONLY flash_lite" in counts[ "c_means" ]
    assert counts[ "outcome" ] == "fabrication_blocked"


def test_the_direction_label_does_not_invert_the_finding():
    """
    Sam caught this on the real run: the label used to read "favours flash_lite" when
    flash_lite was the arm the guard BLOCKED more — i.e. the arm that fabricated more.
    A raw count carries no merit direction; whether hitting an outcome is good or bad
    is a property of the OUTCOME. The label states the fact and refuses the judgement.
    """
    def rec( index, arm, outcome ):
        return { "row_index": index, "frozen_index": index, "arm": arm, "body": "b",
                 "meta": _meta( outcome=outcome ) }

    paired = [
        { "row_index": i, "frozen_index": i, "body": "b",
          "phi_4"     : rec( i, "phi_4", "rewritten" ),
          "flash_lite": rec( i, "flash_lite", "fabrication_blocked" ) }
        for i in range( 5 )
    ]

    counts = RH.discordant_counts( paired, "phi_4", "flash_lite" )

    assert counts[ "more_often" ] == "flash_lite"
    assert counts[ "direction" ]  == "flash_lite hit fabrication_blocked more often"
    assert "favours" not in counts[ "direction" ], \
        "a raw count must not be labelled as favouring anyone — it inverted the finding"
    assert "counts AGAINST it" in counts[ "reading_the_direction" ]


def test_the_direction_label_names_the_other_arm_when_the_cells_flip():
    def rec( index, arm, outcome ):
        return { "row_index": index, "arm": arm, "body": "b", "meta": _meta( outcome=outcome ) }

    paired = [ { "row_index": 0, "body": "b",
                 "phi_4"     : rec( 0, "phi_4", "fabrication_blocked" ),
                 "flash_lite": rec( 0, "flash_lite", "rewritten" ) } ]

    counts = RH.discordant_counts( paired, "phi_4", "flash_lite" )
    assert counts[ "more_often" ] == "phi_4"
    assert counts[ "direction" ]  == "phi_4 hit fabrication_blocked more often"


def test_discordant_direction_reads_even_when_the_cells_match():
    def rec( index, arm, outcome ):
        return { "row_index": index, "arm": arm, "body": "b", "meta": _meta( outcome=outcome ) }

    paired = [
        { "row_index": 0, "body": "b", "phi_4": rec( 0, "phi_4", "fabrication_blocked" ),
                                       "flash_lite": rec( 0, "flash_lite", "rewritten" ) },
        { "row_index": 1, "body": "b", "phi_4": rec( 1, "phi_4", "rewritten" ),
                                       "flash_lite": rec( 1, "flash_lite", "fabrication_blocked" ) },
    ]
    counts = RH.discordant_counts( paired, "phi_4", "flash_lite" )
    assert counts[ "more_often" ] is None
    assert counts[ "direction" ]  == "neither arm hit fabrication_blocked more often"


# ─────────────────────────────────────────────────────────────────────────────
# F4 — the arm seam. No INI edit, no tutor change.
# ─────────────────────────────────────────────────────────────────────────────

class _FakeAgent:
    """Stands in for DmTutorAgent: records what model_name it was given."""
    constructed = []

    def __init__( self, dm_body="" ):
        self.dm_body    = dm_body
        self.model_name = "dm_tutor/phi_4"          # what AgentBase would have set
        _FakeAgent.constructed.append( self )

    def rewrite( self ):
        return f"[{self.model_name}] {self.dm_body}"


def test_arm_seam_overrides_only_the_model_name():
    """The whole difference between the arms is one attribute read at call time."""
    _FakeAgent.constructed = []
    fn = RH.make_arm_rewrite_fn( RH.ARM_FLASH_LITE, agent_cls=_FakeAgent )

    out = fn( "a long body" )
    assert out == "[dm_tutor/flash_lite] a long body"
    assert _FakeAgent.constructed[ 0 ].model_name == "dm_tutor/flash_lite"
    assert fn.spec_key == "dm_tutor/flash_lite"
    assert fn.arm      == RH.ARM_FLASH_LITE


def test_arm_seam_phi4_uses_the_production_key():
    fn = RH.make_arm_rewrite_fn( RH.ARM_PHI4, agent_cls=_FakeAgent )
    assert fn( "body" ) == "[dm_tutor/phi_4] body"


def test_arm_seam_is_fail_closed_on_construction_failure():
    """Production `rewrite_dm` returns None on a construction error; so must this."""
    class Exploding:
        def __init__( self, dm_body="" ): raise ValueError( "dm_body is empty" )

    fn = RH.make_arm_rewrite_fn( RH.ARM_PHI4, agent_cls=Exploding )
    assert fn( "" ) is None


def test_arm_seam_rejects_an_unknown_arm():
    with pytest.raises( KeyError ):
        RH.make_arm_rewrite_fn( "gpt_whatever" )


def test_the_harness_never_names_the_production_routing_key():
    """
    F4's ask, asserted rather than promised: the harness must not reach for
    `llm spec key for dm tutor rewrite`, the INI line that would swap the model
    for every DM the fleet sends.
    """
    source = open( RH.__file__, encoding="utf-8" ).read()

    # The key appears in the module docstring as the thing NOT to touch; it must
    # never appear in code. Strip comments and docstring-quoted prose crudely by
    # checking the executable lines only.
    code_lines = [ line for line in source.splitlines()
                   if not line.lstrip().startswith( "#" ) and "llm spec key" not in line ]
    assert "llm spec key for dm tutor rewrite" not in "\n".join( code_lines )
    assert 'cm.set(' not in source and "configuration_manager.set" not in source


# ─────────────────────────────────────────────────────────────────────────────
# LOADING THE FROZEN SET
# ─────────────────────────────────────────────────────────────────────────────

def _make_snapshot( tmp_path ):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    body     = "One claim. Two claims. Three claims. Four claims. Five claims."
    live.write_text( "".join(
        json.dumps( { "ts": "2026-08-17T10:00:00", "from": "maria", "to": "rio", "body": body } ) + "\n"
        for _ in range( 3 )
    ) )
    out_dir = tmp_path / "frozen"
    FZ.freeze( out_dir=str( out_dir ), live_path=str( live ) )
    return out_dir


def test_load_frozen_rows_reads_the_snapshot_and_manifest( tmp_path ):
    out_dir      = _make_snapshot( tmp_path )
    rows, manifest = RH.load_frozen_rows( str( out_dir ), freezer=FZ )
    assert len( rows ) == 3
    assert manifest[ "snapshot_row_count" ] == 3


def test_load_frozen_rows_refuses_a_drifted_snapshot( tmp_path ):
    """A snapshot edited after the freeze is not the set the manifest describes."""
    out_dir = _make_snapshot( tmp_path )
    snap    = out_dir / "dm_replay_frozen.jsonl"
    with open( snap, "a", encoding="utf-8" ) as handle:
        handle.write( json.dumps( { "body": "appended later" } ) + "\n" )

    with pytest.raises( RuntimeError ) as excinfo:
        RH.load_frozen_rows( str( out_dir ), freezer=FZ )
    assert "does not match its manifest" in str( excinfo.value )


def test_load_frozen_rows_refuses_the_live_corpus():
    """
    EXECUTOR: AI. Aims the loader at the REAL live corpus directory and proves it
    refuses — the harness reading the append-only log is the F1-from-the-cascade
    defect that unpairs the arms.
    """
    live_dir = os.path.dirname( FZ.resolve_live_corpus_path() )
    with pytest.raises( FZ.LivePathRefused ):
        RH.load_frozen_rows( live_dir, freezer=FZ )


def test_load_frozen_rows_defaults_to_the_sibling_freeze_module( tmp_path ):
    """Covers the `freezer is None` branch — the production wiring, not an injection."""
    out_dir        = _make_snapshot( tmp_path )
    rows, manifest = RH.load_frozen_rows( str( out_dir ) )
    assert len( rows ) == 3


# ─────────────────────────────────────────────────────────────────────────────
# THE PRODUCTION WIRING — covered for real, not pragma'd
# ─────────────────────────────────────────────────────────────────────────────

def test_arm_seam_defaults_to_the_REAL_DmTutorAgent( monkeypatch ):
    """
    With no agent_cls the seam imports `cosa.agents.dm_tutor.agent.DmTutorAgent`,
    builds the same object the live send path builds, and overrides `model_name`
    on IT. Only `rewrite()` is stubbed, so no model is called — the one attribute
    that distinguishes the arms is asserted on the real class.
    """
    from cosa.agents.dm_tutor.agent import DmTutorAgent

    seen = {}
    monkeypatch.setattr( DmTutorAgent, "rewrite",
                         lambda self: seen.setdefault( "model_name", self.model_name ) )

    fn = RH.make_arm_rewrite_fn( RH.ARM_FLASH_LITE )
    fn( "One claim. Two claims. Three claims. Four claims. Five claims here." )

    assert seen[ "model_name" ] == "dm_tutor/flash_lite"


def test_replay_defaults_to_the_REAL_apply_dm_tutor():
    """
    Covers the `tutor_fn is None` branch by running the genuine production
    `_apply_dm_tutor`: the real fabrication guard, pointer restore, id-label repair
    and claim counter all run. The injected rewrite_fn returns a canned string, so
    no model is called.
    """
    body = (
        "The queue stalled at src/cosa/rest/queue.py:412 this morning. "
        "I traced it to the pool callback. The sweeper did not fire. "
        "I have not reproduced it twice. I will report back after the next run."
    )
    rows = [ { "ts": "2026-08-17T10:00:00", "from": "maria", "to": "rio", "body": body } ]

    records = RH.replay_arm(
        rows, RH.ARM_PHI4,
        rewrite_fn=lambda b: "The queue stalled at src/cosa/rest/queue.py:412. I traced it to the pool callback.",
        max_model_failed_rate=0.0,
    )

    meta = records[ 0 ][ "meta" ]
    assert meta[ "tutor_enabled" ] is True
    assert meta[ "tutor_fired" ]   is True
    assert meta[ "tutor_outcome" ] in RH.FIRED_OUTCOMES
    assert "tutor_version" in meta                    # the real meta shape, recorded verbatim


def test_replay_builds_the_arm_rewrite_fn_when_none_is_given():
    """Covers the `rewrite_fn is None` branch; the fake tutor never calls it."""
    records = RH.replay_arm(
        _rows( 1 ), RH.ARM_FLASH_LITE,
        tutor_fn=_tutor_returning( [ "rewritten" ] ),
        max_model_failed_rate=0.5,
    )
    assert records[ 0 ][ "spec_key" ] == "dm_tutor/flash_lite"


# ─────────────────────────────────────────────────────────────────────────────
# THE ARM-SURFACE GATE — "it answered" is not the assertion
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.arm_surface
def test_the_flash_lite_arm_really_reaches_vertex():
    """
    EXECUTOR: AI. Builds the REAL client from the shipped INI key and reads Sam's
    four markers off the SDK object the call would ride. Construction only — no
    network, no credentials resolved, no model called.
    """
    markers = RH.verify_arm_surface( RH.ARM_FLASH_LITE )

    assert "aiplatform.googleapis.com" in str( markers[ "endpoint" ] )   # M1
    assert markers[ "model_id" ] == "gemini-3.1-flash-lite"              # M2 (see the arm_markers caveat)
    assert markers[ "vertexai" ] is True                                 # M3
    assert markers[ "project" ]                                          # M3
    assert markers[ "api_key" ] is None                                  # M4


@pytest.mark.arm_surface
def test_the_phi4_arm_is_verified_negatively():
    """The local arm must NOT be a Vertex client — the fall-through, pointing the other way."""
    assert RH.verify_arm_surface( RH.ARM_PHI4 ) is None


@pytest.mark.arm_surface
def test_a_crossed_pair_is_refused():
    """
    Two arms that both resolved the same client would produce a perfectly paired
    study of one model against itself, and every counter would look reasonable.
    """
    from cosa.agents.llm_client_factory import LlmClientFactory

    class CrossedFactory:
        def get_client( self, spec_key, *args, **kwargs ):
            return LlmClientFactory().get_client( "dm_tutor/flash_lite" )   # both arms -> Vertex

    with pytest.raises( RH.ArmNotVerified ) as excinfo:
        RH.verify_arm_surface( RH.ARM_PHI4, factory=CrossedFactory() )
    assert "crossed" in str( excinfo.value )


@pytest.mark.arm_surface
def test_a_fall_through_arm_is_refused_by_name():
    """
    The prove-it-red control at the harness layer: hand the Vertex arm a client that
    answers well and is not Vertex, and the gate must name the marker that failed.
    """
    from cosa.agents.llm_client_factory import LlmClientFactory

    class FallThroughFactory:
        def get_client( self, spec_key, *args, **kwargs ):
            return LlmClientFactory().get_client( "dm_tutor/phi_4" )

    with pytest.raises( RH.ArmNotVerified ) as excinfo:
        RH.verify_arm_surface( RH.ARM_FLASH_LITE, factory=FallThroughFactory() )
    assert "M1 Vertex endpoint marker" in str( excinfo.value )


def test_replay_refuses_to_record_a_row_from_an_unverified_arm( monkeypatch ):
    """The gate runs BEFORE row 0, not after the run."""
    def boom( arm, factory=None ):
        raise RH.ArmNotVerified( "M1 Vertex endpoint marker: observed a LAN host" )

    monkeypatch.setattr( RH, "verify_arm_surface", boom )
    seen = []

    with pytest.raises( RH.ArmNotVerified ):
        RH.replay_arm( _rows( 5 ), RH.ARM_FLASH_LITE,
                       tutor_fn=lambda b, config=None, rewrite_fn=None: seen.append( b ),
                       rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )

    assert seen == [], "not a single row may be recorded from an arm that failed its surface check"


def test_verify_surface_can_be_disabled_for_hermetic_replays( monkeypatch ):
    """The flag exists so the fake-tutor tests need no GCP project; production defaults to on."""
    monkeypatch.setattr( RH, "verify_arm_surface",
                         lambda *a, **k: ( _ for _ in () ).throw( AssertionError( "must not be called" ) ) )
    records = RH.replay_arm( _rows( 1 ), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] ),
                             rewrite_fn=lambda b: "x", max_model_failed_rate=0.5, verify_surface=False )
    assert len( records ) == 1


# ─────────────────────────────────────────────────────────────────────────────
# BACKFILLING PROVENANCE ONTO PRE-FIELD RUNS
# ─────────────────────────────────────────────────────────────────────────────

def test_backfill_stamps_provenance_from_the_run_header():
    """Sam's 400-row run predates both fields; its header carries them, so nothing is guessed."""
    records = [ { "row_index": 0, "arm": "phi_4", "body": "a", "elapsed_seconds": 1.0,
                  "meta": _meta() },
                { "row_index": 1, "arm": "phi_4", "body": "b", "elapsed_seconds": 2.0,
                  "meta": _meta() } ]

    filled = RH.backfill_provenance( records, "sha-from-header", drawn_frozen_indices=[ 272, 382 ] )

    assert [ r[ "frozen_index" ] for r in filled ]    == [ 272, 382 ]
    assert { r[ "snapshot_sha256" ] for r in filled } == { "sha-from-header" }
    assert all( r[ "provenance_backfilled" ] for r in filled )


def test_backfill_does_not_mutate_the_caller_s_records():
    records = [ { "row_index": 0, "arm": "phi_4", "body": "a", "elapsed_seconds": 1.0, "meta": _meta() } ]
    RH.backfill_provenance( records, "sha", drawn_frozen_indices=[ 5 ] )
    assert "frozen_index" not in records[ 0 ]
    assert "snapshot_sha256" not in records[ 0 ]


def test_backfill_never_overwrites_real_provenance():
    """A backfill must not replace a recorded fact with a reconstructed one."""
    records = [ { "row_index": 0, "frozen_index": 99, "snapshot_sha256": "real",
                  "arm": "phi_4", "body": "a", "elapsed_seconds": 1.0, "meta": _meta() } ]

    filled = RH.backfill_provenance( records, "reconstructed", drawn_frozen_indices=[ 7 ] )
    assert filled[ 0 ][ "frozen_index" ]    == 99
    assert filled[ 0 ][ "snapshot_sha256" ] == "real"


def test_backfill_refuses_a_mismatched_index_list():
    """A silent zip would misattribute every row to the wrong body."""
    records = [ { "row_index": i, "arm": "phi_4", "body": "b", "elapsed_seconds": 1.0,
                  "meta": _meta() } for i in range( 3 ) ]

    with pytest.raises( ValueError ) as excinfo:
        RH.backfill_provenance( records, "sha", drawn_frozen_indices=[ 1, 2 ] )
    assert "misattribute every row" in str( excinfo.value )


def test_backfill_falls_back_to_row_index_without_a_draw():
    """Correct ONLY for an unsampled full-population run, and documented as such."""
    records = [ { "row_index": 3, "arm": "phi_4", "body": "b", "elapsed_seconds": 1.0, "meta": _meta() } ]
    assert RH.backfill_provenance( records, "sha" )[ 0 ][ "frozen_index" ] == 3


def test_backfilled_records_pair_successfully():
    """The point of the backfill: pair_records must accept the result."""
    def raw( index, arm ):
        return { "row_index": index, "arm": arm, "body": f"body {index}",
                 "elapsed_seconds": 1.0, "meta": _meta() }

    a = RH.backfill_provenance( [ raw( 0, "phi_4" ), raw( 1, "phi_4" ) ], "sha", [ 10, 20 ] )
    b = RH.backfill_provenance( [ raw( 0, "flash_lite" ), raw( 1, "flash_lite" ) ], "sha", [ 10, 20 ] )

    paired = RH.pair_records( a, b )
    assert [ p[ "frozen_index" ] for p in paired ] == [ 10, 20 ]


def test_backfilled_records_still_refuse_a_snapshot_mismatch():
    """The backfill must not weaken the guard it exists to satisfy."""
    def raw( index, arm ):
        return { "row_index": index, "arm": arm, "body": f"body {index}",
                 "elapsed_seconds": 1.0, "meta": _meta() }

    a = RH.backfill_provenance( [ raw( 0, "phi_4" ) ], "freeze-one", [ 10 ] )
    b = RH.backfill_provenance( [ raw( 0, "flash_lite" ) ], "freeze-two", [ 10 ] )

    with pytest.raises( ValueError ) as excinfo:
        RH.pair_records( a, b )
    assert "different frozen snapshots" in str( excinfo.value )


# ─────────────────────────────────────────────────────────────────────────────
# LATENCY — the tiebreaker, and the split that keeps it meaning what it says
# ─────────────────────────────────────────────────────────────────────────────

def _timed( outcome, seconds, index=0 ):
    return { "row_index": index, "frozen_index": index, "arm": "x", "body": "b",
             "elapsed_seconds": seconds, "meta": _meta( outcome=outcome ) }


def test_latency_excludes_model_failed_from_the_tiebreaker_figure():
    """
    THE design point. A model_failed row is timed too, and its duration is a
    different KIND of number — a fast 404 or a slow timeout, not how long the model
    took to answer. Pooling it makes the tiebreaker mean something else.
    """
    records = [ _timed( "rewritten", 2.0 ), _timed( "rewritten", 4.0 ),
                _timed( "model_failed", 90.0 ) ]                 # a timeout, not an answer

    summary = RH.latency_summary( records )

    assert summary[ "answered" ][ "n" ]      == 2
    assert summary[ "answered" ][ "median" ] == 3.0              # the 90s row cannot reach this
    assert summary[ "all_fired" ][ "n" ]     == 3
    assert summary[ "all_fired" ][ "median" ] == 4.0             # ...but it is still visible here


def test_latency_counts_refusals_as_answered():
    """A fabrication refusal required an answer to judge; the model did the work."""
    for refusal in ( "fabrication_blocked", "rescope_blocked", "label_blocked", "gate_rejected" ):
        assert RH.latency_summary( [ _timed( refusal, 3.0 ) ] )[ "answered" ][ "n" ] == 1


def test_latency_median_is_none_rather_than_zero_when_nothing_qualifies():
    """A 0.0 would read as "instant"; None reads as "no measurement", which is true."""
    summary = RH.latency_summary( [ _timed( "model_failed", 5.0 ) ] )
    assert summary[ "answered" ][ "median" ] is None
    assert summary[ "answered" ][ "mean" ]   is None
    assert summary[ "answered" ][ "n" ]      == 0


def test_latency_ratio_names_the_faster_arm():
    a = [ _timed( "rewritten", 8.0, 0 ), _timed( "rewritten", 8.0, 1 ) ]     # phi_4
    b = [ _timed( "rewritten", 2.0, 0 ), _timed( "rewritten", 2.0, 1 ) ]     # flash_lite

    result = RH.latency_ratio( a, b )

    assert result[ "ratio_of_medians" ]    == pytest.approx( 4.0 )
    assert result[ "paired_median_ratio" ] == pytest.approx( 4.0 )
    assert result[ "faster_arm" ]          == "flash_lite"
    assert "> 1 means phi_4 is slower" in result[ "ratio_meaning" ]


def test_latency_ratio_the_other_way_round():
    a = [ _timed( "rewritten", 1.0, 0 ) ]
    b = [ _timed( "rewritten", 5.0, 0 ) ]
    result = RH.latency_ratio( a, b )
    assert result[ "ratio_of_medians" ] == pytest.approx( 0.2 )
    assert result[ "faster_arm" ]       == "phi_4"


def test_latency_ratio_reports_a_tie_as_a_tie():
    a = [ _timed( "rewritten", 3.0, 0 ) ]
    b = [ _timed( "rewritten", 3.0, 0 ) ]
    assert RH.latency_ratio( a, b )[ "faster_arm" ] == "tie"


def test_paired_median_ratio_is_robust_where_the_ratio_of_medians_is_not():
    """
    The arms are paired, so a per-row ratio is available. One arm meeting a single
    very slow body moves the mean and can move the ratio of medians; the paired
    median does not. Both are reported — neither replaces the other.
    """
    a = [ _timed( "rewritten", 2.0, 0 ), _timed( "rewritten", 2.0, 1 ), _timed( "rewritten", 200.0, 2 ) ]
    b = [ _timed( "rewritten", 1.0, 0 ), _timed( "rewritten", 1.0, 1 ), _timed( "rewritten", 1.0, 2 ) ]

    result = RH.latency_ratio( a, b )
    assert result[ "paired_median_ratio" ] == pytest.approx( 2.0 )    # unmoved by the outlier
    assert result[ "ratio_of_medians" ]    == pytest.approx( 2.0 )


def test_latency_ratio_is_none_when_it_cannot_be_formed():
    """Never a fabricated number: no answered rows means no ratio."""
    a = [ _timed( "model_failed", 5.0, 0 ) ]
    b = [ _timed( "model_failed", 5.0, 0 ) ]

    result = RH.latency_ratio( a, b )
    assert result[ "ratio_of_medians" ] is None
    assert result[ "faster_arm" ]       is None


def test_latency_ratio_survives_a_zero_denominator():
    a = [ _timed( "rewritten", 3.0, 0 ), _timed( "rewritten", 4.0, 1 ) ]
    b = [ _timed( "rewritten", 0.0, 0 ), _timed( "rewritten", 2.0, 1 ) ]

    result = RH.latency_ratio( a, b )
    assert result[ "paired_median_ratio" ] == pytest.approx( 2.0 )    # the 0.0 row is skipped
    assert result[ "ratio_of_medians" ]    == pytest.approx( 3.5 )


def test_latency_reports_p90_and_p99_per_arm():
    """Rick's condition 2: the internet leg is the variable one and p99 is where it shows."""
    records = [ _timed( "rewritten", float( t ), i ) for i, t in enumerate( range( 1, 101 ) ) ]
    answered = RH.latency_summary( records )[ "answered" ]

    assert answered[ "p90" ] == pytest.approx( 90.1, abs=0.5 )
    assert answered[ "p99" ] == pytest.approx( 99.0, abs=0.5 )
    assert answered[ "p90" ] < answered[ "p99" ]
    assert answered[ "median" ] < answered[ "p90" ]


def test_p99_catches_a_tail_the_median_hides():
    """The whole reason Rick asked for it: two arms with the SAME median, different tails."""
    steady  = [ _timed( "rewritten", 2.0, i ) for i in range( 19 ) ] + [ _timed( "rewritten", 2.0, 19 ) ]
    spiky   = [ _timed( "rewritten", 2.0, i ) for i in range( 19 ) ] + [ _timed( "rewritten", 60.0, 19 ) ]

    a = RH.latency_summary( steady )[ "answered" ]
    b = RH.latency_summary( spiky )[ "answered" ]

    assert a[ "median" ] == b[ "median" ]                  # identical by the headline...
    assert b[ "p99" ] > a[ "p99" ] * 5                     # ...and nothing like it in the tail


def test_percentile_handles_empty_and_single():
    assert RH._percentile( [], 0.9 )      is None
    assert RH._percentile( [ 4.0 ], 0.99 ) == 4.0


def test_the_package_percentile_is_nearest_rank():
    """
    Mr. Radio's ruling: nearest-rank, so every figure on the page is one a request
    actually took. A study about a model inventing facts must not report a latency
    nothing measured.
    """
    assert RH.PERCENTILE_METHOD == "nearest_rank"

    values = [ 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0 ]
    for q in ( 0.5, 0.9, 0.95, 0.99 ):
        assert RH._percentile( values, q ) in values, "nearest-rank must never invent a value"


def test_nearest_rank_and_linear_genuinely_differ():
    """
    The ruling is not cosmetic. On the real 8-row shape these disagreed by 10 seconds,
    which is why two implementations could not both survive.
    """
    values = [ 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 24.5 ]

    nearest = RH._percentile( values, 0.90, method="nearest_rank" )
    linear  = RH._percentile( values, 0.90, method="linear" )

    assert nearest == 24.5                       # a value that was measured
    assert linear  != nearest
    assert linear not in values                  # ...against one that never happened


def test_percentile_rejects_an_unknown_method():
    """Silently picking one is how two definitions got here in the first place."""
    with pytest.raises( ValueError ):
        RH._percentile( [ 1.0, 2.0 ], 0.9, method="whatever" )


def test_the_two_call_sites_agree_on_identical_input():
    """
    Mr. Radio's explicit ask: feed the same input to BOTH call sites and assert
    identical output, so the package cannot silently diverge again. The reader
    rounds for display, so compare against the shared value rounded the same way.
    """
    from cosa.research.phi4_flash_lite_study import report

    for values in ( [ 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 24.5 ],
                    [ 0.5 ],
                    [ 2.0, 2.0, 2.0, 60.0 ],
                    [ float( i ) for i in range( 1, 401 ) ] ):
        for q in ( 0.90, 0.99 ):
            assert report._percentile( values, q ) == round( RH._percentile( values, q ), 3 ), \
                f"the two call sites disagree on {values[ :3 ]}... at q={q}"


def test_latency_payload_carries_the_deployment_framing():
    """
    Rick's condition 1, and it must be in the PAYLOAD — a caveat that lives only where
    the number does not travel is a caveat nobody reads.
    """
    result = RH.latency_ratio( [ _timed( "rewritten", 1.0 ) ], [ _timed( "rewritten", 2.0 ) ] )

    assert result[ "comparison_kind" ] == "DEPLOYMENT, not model speed"
    assert "LAN hop" in result[ "what_this_measures" ]
    assert "internet round trip" in result[ "what_this_measures" ]
    assert "NOT a claim that one model is intrinsically faster" in result[ "what_this_measures" ]
    assert "p99" in result[ "tail_note" ]


def test_latency_ratio_says_out_loud_that_it_is_only_a_tiebreaker():
    """A faster arm that is significantly less honest does not win on speed."""
    result = RH.latency_ratio( [ _timed( "rewritten", 1.0 ) ], [ _timed( "rewritten", 1.0 ) ] )
    assert "ONLY after the statistical test" in result[ "tiebreaker_only" ]
    assert "model_failed" in result[ "basis" ]


def test_the_report_carries_latency_even_without_a_denominator( tmp_path ):
    """
    Latency needs neither Rick's denominator nor his floor, so withholding it would
    withhold a number nothing is waiting on.
    """
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 3, RH.ARM_FLASH_LITE: [ "rewritten" ] * 3 } ),
    )

    report = json.loads( printed[ -1 ] )
    assert "withheld" in report[ "arms" ][ RH.ARM_PHI4 ]          # the summary IS withheld...
    assert "ratio_of_medians" in report[ "latency" ]              # ...and latency is not
    assert "faster_arm" in report[ "latency" ]


def test_the_report_withholds_the_ratio_on_a_one_armed_run( tmp_path ):
    """A tiebreaker needs both arms; one arm gets its summary and an explicit note."""
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5", "--arm", RH.ARM_PHI4 ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 3 } ),
    )

    latency = json.loads( printed[ -1 ] )[ "latency" ]
    assert "ratio_of_medians" not in latency
    assert "one arm only" in latency[ "note" ]


# ─────────────────────────────────────────────────────────────────────────────
# THE CLI
# ─────────────────────────────────────────────────────────────────────────────

def _fake_runner( outcomes_by_arm ):
    def run( rows, arm, max_model_failed_rate=None, preflight=25, snapshot_sha256=None ):
        return RH.replay_arm( rows, arm, tutor_fn=_tutor_returning( outcomes_by_arm[ arm ] ),
                              rewrite_fn=lambda b: "x", max_model_failed_rate=max_model_failed_rate,
                              preflight=preflight, snapshot_sha256=snapshot_sha256 )
    return run


def test_main_runs_both_arms_and_writes_the_records( tmp_path ):
    out_dir = _make_snapshot( tmp_path )
    results = tmp_path / "results.jsonl"
    printed = []

    code = RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( results ), "--max-model-failed-rate", "0.5" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 3, RH.ARM_FLASH_LITE: [ "rewritten" ] * 3 } ),
    )

    assert code == 0
    lines = results.read_text().strip().splitlines()
    assert len( lines ) == 6                                  # 3 rows x 2 arms
    arms = { json.loads( line )[ "arm" ] for line in lines }
    assert arms == { RH.ARM_PHI4, RH.ARM_FLASH_LITE }


def test_main_withholds_the_summary_when_the_denominator_is_unset( tmp_path ):
    """F1 at the report layer: no rate is printed under a denominator nobody chose."""
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 3, RH.ARM_FLASH_LITE: [ "rewritten" ] * 3 } ),
    )

    report = json.loads( printed[ -1 ] )
    assert "withheld" in report[ "arms" ][ RH.ARM_PHI4 ]
    assert "76755526" in report[ "arms" ][ RH.ARM_PHI4 ]


def test_main_reports_the_summary_once_a_denominator_is_given( tmp_path ):
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5", "--denominator", "narrow" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4       : [ "fabrication_blocked", "rewritten", "rewritten" ],
                               RH.ARM_FLASH_LITE : [ "rewritten" ] * 3 } ),
    )

    report = json.loads( printed[ -1 ] )
    assert report[ "arms" ][ RH.ARM_PHI4 ][ "fabrication_rate" ] == pytest.approx( 1 / 3 )
    assert report[ "arms" ][ RH.ARM_FLASH_LITE ][ "fabrication_rate" ] == 0.0
    assert report[ "arms" ][ RH.ARM_PHI4 ][ "denominator" ] == "narrow"


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLING — a seeded draw, not the first N in corpus order
# ─────────────────────────────────────────────────────────────────────────────

def _many_rows( n ):
    return [ { "ts": f"2026-08-17T{i:04d}", "from": "maria", "to": "rio", "body": f"body {i}" }
             for i in range( n ) ]


def test_seeded_subset_is_reproducible_and_not_the_first_n():
    """
    The whole point. `--limit` returns rows 0..9 every time; a seeded draw returns
    the SAME ten rows on any machine without them being a time window.
    """
    rows = _many_rows( 200 )

    first, drawn_a  = RH.draw_seeded_subset( rows, 10, 42 )
    second, drawn_b = RH.draw_seeded_subset( rows, 10, 42 )
    other, drawn_c  = RH.draw_seeded_subset( rows, 10, 43 )

    assert drawn_a == drawn_b                       # same seed, same draw
    assert drawn_a != drawn_c                       # different seed, different draw
    assert drawn_a != list( range( 10 ) ), "a seeded draw that returns the first N is not a draw"
    assert [ r[ "body" ] for r in first ] == [ r[ "body" ] for r in second ]
    assert len( first ) == 10


def test_seeded_subset_stays_in_frozen_set_order():
    """Both arms walk the subset identically, so it must be ordered, not shuffled."""
    _, drawn = RH.draw_seeded_subset( _many_rows( 100 ), 12, 7 )
    assert drawn == sorted( drawn )


def test_seeded_subset_carries_the_frozen_index_back_to_the_snapshot():
    """
    A record must be traceable to its row in the snapshot, not merely to its
    position in the draw — those differ the moment you sample.
    """
    rows          = _many_rows( 100 )
    subset, drawn = RH.draw_seeded_subset( rows, 5, 99 )

    assert [ r[ "frozen_index" ] for r in subset ] == drawn
    for row in subset:
        assert row[ "body" ] == rows[ row[ "frozen_index" ] ][ "body" ]


def test_seeded_subset_does_not_mutate_the_frozen_rows():
    rows = _many_rows( 50 )
    RH.draw_seeded_subset( rows, 5, 1 )
    assert all( "frozen_index" not in row for row in rows )


def test_seeded_subset_returns_everything_when_the_sample_exceeds_the_population():
    subset, drawn = RH.draw_seeded_subset( _many_rows( 8 ), 99, 1 )
    assert len( subset ) == 8
    assert drawn == list( range( 8 ) )


def test_seeded_subset_rejects_a_non_positive_size():
    with pytest.raises( ValueError ):
        RH.draw_seeded_subset( _many_rows( 5 ), 0, 1 )


def test_records_carry_the_frozen_index_of_a_sampled_row():
    rows, _ = RH.draw_seeded_subset( _many_rows( 100 ), 3, 5 )
    records = RH.replay_arm( rows, RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 3 ),
                             rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )

    assert [ r[ "row_index" ] for r in records ]    == [ 0, 1, 2 ]          # position in the draw
    assert [ r[ "frozen_index" ] for r in records ] == [ r[ "frozen_index" ] for r in rows ]
    assert [ r[ "frozen_index" ] for r in records ] != [ 0, 1, 2 ]          # ...and not the same thing


def test_records_frozen_index_falls_back_to_row_index_on_a_full_run():
    """An unsampled run has no draw, so the two indices coincide."""
    records = RH.replay_arm( _rows( 2 ), RH.ARM_PHI4, tutor_fn=_tutor_returning( [ "rewritten" ] * 2 ),
                             rewrite_fn=lambda b: "x", max_model_failed_rate=0.5 )
    assert [ r[ "frozen_index" ] for r in records ] == [ 0, 1 ]


def test_main_records_the_seed_and_drawn_indices_in_the_report( tmp_path ):
    """A sample nobody can reproduce is not evidence."""
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5", "--sample-size", "2", "--seed", "77" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 2, RH.ARM_FLASH_LITE: [ "rewritten" ] * 2 } ),
    )

    selection = json.loads( printed[ -1 ] )[ "selection" ]
    assert selection[ "mode" ]        == "seeded_random"
    assert selection[ "seed" ]        == 77
    assert selection[ "sample_size" ] == 2
    assert selection[ "population" ]  == 3
    assert len( selection[ "drawn_frozen_indices" ] ) == 2


def test_main_labels_a_limit_run_as_a_time_window_sample( tmp_path ):
    """--limit still works, and the report says out loud what kind of sample it is."""
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5", "--limit", "2" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 2, RH.ARM_FLASH_LITE: [ "rewritten" ] * 2 } ),
    )

    selection = json.loads( printed[ -1 ] )[ "selection" ]
    assert selection[ "mode" ] == "first_n_corpus_order"
    assert "TIME-WINDOW" in selection[ "caveat" ]


def test_main_refuses_both_selectors_at_once( tmp_path ):
    """They select rows two different ways; silently letting one win would be a lie."""
    out_dir = _make_snapshot( tmp_path )

    with pytest.raises( SystemExit ):
        RH.main( [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
                   "--max-model-failed-rate", "0.5", "--limit", "2", "--sample-size", "2" ],
                 printer=lambda *a: None, runner=_fake_runner( {} ) )


def test_main_reports_the_full_population_when_unsampled( tmp_path ):
    out_dir = _make_snapshot( tmp_path )
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( tmp_path / "r.jsonl" ),
          "--max-model-failed-rate", "0.5" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_PHI4: [ "rewritten" ] * 3, RH.ARM_FLASH_LITE: [ "rewritten" ] * 3 } ),
    )

    assert json.loads( printed[ -1 ] )[ "selection" ] == { "mode": "all", "population": 3 }


def test_main_single_arm_and_limit( tmp_path ):
    out_dir = _make_snapshot( tmp_path )
    results = tmp_path / "one.jsonl"
    printed = []

    RH.main(
        [ "--snapshot-dir", str( out_dir ), "--out", str( results ), "--max-model-failed-rate", "0.5",
          "--arm", RH.ARM_FLASH_LITE, "--limit", "2" ],
        printer=printed.append,
        runner=_fake_runner( { RH.ARM_FLASH_LITE: [ "rewritten" ] * 2 } ),
    )

    lines = results.read_text().strip().splitlines()
    assert len( lines ) == 2
    assert all( json.loads( line )[ "arm" ] == RH.ARM_FLASH_LITE for line in lines )
