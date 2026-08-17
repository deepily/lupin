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
    b, c = RH.discordant_counts( paired, "phi_4", "flash_lite" )
    assert ( b, c ) == ( 1, 1 )


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
# THE CLI
# ─────────────────────────────────────────────────────────────────────────────

def _fake_runner( outcomes_by_arm ):
    def run( rows, arm, max_model_failed_rate=None, preflight=25 ):
        return RH.replay_arm( rows, arm, tutor_fn=_tutor_returning( outcomes_by_arm[ arm ] ),
                              rewrite_fn=lambda b: "x", max_model_failed_rate=max_model_failed_rate,
                              preflight=preflight )
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
