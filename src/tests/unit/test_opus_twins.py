"""
The Opus twins, over in-memory SQLite with the principles forecast's stand-in baseline.

Each test names what it would catch:
  - a twin calling the Haiku model, or any prompt that differs from its Haiku arm  -> test_*_calls_opus_*, test_the_twin_sends_*
  - a twin running while switched off, or before the baseline exists               -> test_not_run_*
  - a twin row marked displayed, or written under the wrong arm or version         -> test_the_*_row_*
  - a retry, a second call per ask, or a queue past the cap                        -> test_a_failed_*, test_the_cap_*
  - a twin and its Haiku arm blocking each other's row                             -> test_a_twin_and_its_haiku_arm_*
  - the shipped switches on, the cap above one, or a missing model id              -> test_the_shipped_*
"""

import asyncio
import re
from datetime import timedelta

import pytest

import cosa.agents.prediction_engine.opus_twins as ot
import cosa.agents.prediction_engine.principles_forecast as pf
import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.db.repositories.arm_forecast_repository import CAPPED_ARM_REASON
from cosa.rest.postgres_models import PredictionArmForecast
from tests.unit.test_principles_forecast import ENCODER, EXTRACT, T0, Baseline, Embedder, Failed, Stub, ask, factory, principle, rows  # noqa: F401  (factory is a fixture)

OPUS = "opus-x"


def run_baseline( factory, nid, c0, gate=None, enabled=True, model=OPUS ):
    """Run the baseline twin for one card."""
    return asyncio.run( ot.run_baseline_opus( factory, nid, c0, gate or pf.CapGate( 1 ), enabled=enabled, model=model, clock=lambda: T0 + timedelta( minutes=1 ) ) )


def run_principles( factory, nid, c0, gate=None, enabled=True, model=OPUS ):
    """Run the principles twin for one card."""
    return asyncio.run( ot.run_principles_opus( factory, nid, c0, Embedder(), ENCODER, EXTRACT, gate or pf.CapGate( 1 ), enabled=enabled, model=model,
                                                clock=lambda: T0 + timedelta( minutes=1 ) ) )


def only_row( factory, arm ):
    """The one row of an arm."""
    found = [ r for r in rows( factory ) if r.arm == arm ]
    assert len( found ) == 1, f"expected one {arm} row, found {len( found )}"
    return found[ 0 ]


def test_the_baseline_twin_calls_opus_with_the_baselines_own_prompt_and_no_principle_block( factory ):
    """The call goes to Opus with the baseline's own prompt, even when principles exist."""
    nid = ask( factory )
    principle( factory )
    c0 = Baseline()
    assert run_baseline( factory, nid, c0 ) == { "status": "ran", "reason": None }
    call = c0.calls[ 0 ]
    assert len( c0.calls ) == 1 and ( call[ "model" ], call[ "system" ], call[ "user" ], call[ "timeout" ] ) == ( OPUS, "SYSTEM", "USER prompt for Which plan?", 30 )


def test_the_baseline_twin_row_is_its_own_arm_never_displayed_with_the_opus_version_and_no_principles( factory ):
    """One row for the twin: not displayed, the Opus version, cutoff at the ask, no principles."""
    nid = ask( factory )
    principle( factory )
    run_baseline( factory, nid, Baseline( reply="no" ) )
    row = only_row( factory, "C0-opus" )
    assert ( row.displayed, row.predictor_version, row.forecast, row.abstention_reason, row.evidence_ids ) == ( False, "c0-v1+opus", { "stance": "no" }, None, [] )
    assert pf.aware_moment( row.input_cutoff ) == T0 and pf.aware_moment( row.forecast_ready_at ) == T0 + timedelta( minutes=1 )


def test_the_principles_twin_sends_exactly_what_the_haiku_arm_sends_except_the_model( factory ):
    """Only the model id and the block's random tag differ from the Haiku arm's call."""
    nid = ask( factory )
    principle( factory )
    haiku, opus = Baseline(), Baseline()
    asyncio.run( pf.run_b1( factory, nid, haiku, Embedder(), ENCODER, EXTRACT, pf.CapGate( 1 ), enabled=True ) )
    assert run_principles( factory, nid, opus ) == { "status": "ran", "reason": None }
    h, o = haiku.calls[ 0 ], opus.calls[ 0 ]
    assert ( h[ "model" ], o[ "model" ] ) == ( "haiku-x", OPUS )
    unnonced = lambda call: { k: re.sub( r"principles_[0-9a-f]{8}", "principles_NONCE", v ) if isinstance( v, str ) else v for k, v in call.items() if k != "model" }
    assert unnonced( h ) == unnonced( o ), "the block's tag carries a fresh random token per call; nothing else may differ"
    assert pf.BLOCK_HEADING in o[ "user" ]


def test_the_principles_twin_row_carries_the_principle_ids_the_version_suffixes_and_is_never_displayed( factory ):
    """The row is not displayed, has both suffixes and holds the principle ids of the block."""
    nid, pid = ask( factory ), principle( factory )
    run_principles( factory, nid, Baseline() )
    row = only_row( factory, "B1-opus" )
    assert ( row.displayed, row.predictor_version, row.evidence_ids ) == ( False, "c0-v1+principles+opus", [ str( pid ) ] )


def test_a_twin_and_its_haiku_arm_each_keep_their_own_row_for_one_card( factory ):
    """A twin never reads as already stored because its Haiku arm ran."""
    nid = ask( factory )
    asyncio.run( pf.run_b1( factory, nid, Baseline(), Embedder(), ENCODER, EXTRACT, pf.CapGate( 1 ), enabled=True ) )
    assert run_principles( factory, nid, Baseline() ) == { "status": "ran", "reason": None }
    assert run_baseline( factory, nid, Baseline() ) == { "status": "ran", "reason": None }
    assert sorted( r.arm for r in rows( factory ) ) == [ "B1", "B1-opus", "C0-opus" ]


@pytest.mark.parametrize( "runner", [ run_baseline, run_principles ] )
def test_not_run_while_a_twin_is_off_reads_calls_and_writes_nothing( factory, monkeypatch, runner ):
    """Off: no row, the baseline untouched and the Opus id never read."""
    monkeypatch.setattr( ot, "opus_model", lambda: ( _ for _ in () ).throw( AssertionError( "the model id was read" ) ) )
    class Untouchable:
        def __getattr__( self, name ): raise AssertionError( f"the baseline was touched: {name}" )
    assert runner( factory, ask( factory ), Untouchable(), enabled=False ) == { "status": "not_run", "reason": "switch off" }
    assert rows( factory ) == []


@pytest.mark.parametrize( "runner", [ run_baseline, run_principles ] )
def test_not_run_before_the_baseline_exists_reads_blocked_by_phase_6( factory, monkeypatch, runner ):
    """On with no baseline job: the blocked reason, no row, and the Opus id never read."""
    monkeypatch.setattr( ot, "opus_model", lambda: ( _ for _ in () ).throw( AssertionError( "the model id was read" ) ) )
    assert runner( factory, ask( factory ), None ) == { "status": "not_run", "reason": "blocked by phase 6" }
    assert rows( factory ) == []


def test_a_failed_opus_call_stores_one_row_with_the_reason_and_is_not_retried( factory ):
    """One call, one row, no forecast, the cap place returned."""
    gate, c0 = pf.CapGate( 1 ), Baseline( fail=Failed( "boom" ) )
    assert run_baseline( factory, ask( factory ), c0, gate=gate ) == { "status": "failed", "reason": "model_error: Failed" }
    row = only_row( factory, "C0-opus" )
    assert len( c0.calls ) == 1 and ( row.forecast, row.forecast_ready_at, row.abstention_reason ) == ( None, None, "model_error: Failed" ) and gate.inflight == 0


def test_a_second_run_for_the_same_card_makes_no_second_opus_call( factory ):
    """One call per twin per ask."""
    nid, c0 = ask( factory ), Baseline()
    run_principles( factory, nid, c0 )
    assert run_principles( factory, nid, c0 ) == { "status": "not_run", "reason": "already stored" }
    assert len( c0.calls ) == 1 and len( rows( factory ) ) == 1


@pytest.mark.parametrize( "runner,arm,version", [ ( run_baseline, "C0-opus", "c0-v1+opus" ), ( run_principles, "B1-opus", "c0-v1+principles+opus" ) ] )
def test_the_cap_turns_a_card_away_at_once_without_a_call_under_the_twins_own_arm( factory, runner, arm, version ):
    """With the one place held, a capacity row is written for the twin and no model is called."""
    gate, c0 = pf.CapGate( 1 ), Baseline()
    assert gate.try_enter() is True
    assert runner( factory, ask( factory ), c0, gate=gate ) == { "status": "capacity", "reason": CAPPED_ARM_REASON }
    row = only_row( factory, arm )
    assert c0.calls == [] and ( row.forecast, row.abstention_reason, row.predictor_version, row.displayed ) == ( None, CAPPED_ARM_REASON, version, False ) and gate.inflight == 1


def test_the_model_id_and_the_switch_are_read_from_the_ini_when_not_given( factory, monkeypatch ):
    """No override: the INI id is the model called, and the INI switch decides."""
    c0 = Baseline()
    monkeypatch.setattr( ot, "ConfigurationManager", lambda env_var_name=None: Stub( "opus-from-ini" ) )
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( True ) )
    nid = ask( factory )
    assert asyncio.run( ot.run_baseline_opus( factory, nid, c0, pf.CapGate( 1 ) ) ) == { "status": "ran", "reason": None }
    assert c0.calls[ 0 ][ "model" ] == "opus-from-ini"
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( False ) )
    assert asyncio.run( ot.run_baseline_opus( factory, ask( factory ), Baseline(), pf.CapGate( 1 ) ) ) == { "status": "not_run", "reason": "switch off" }


class KeyedSwitches:
    """A configuration manager stand-in that answers each switch key from its own value."""
    def __init__( self, values ): self.values = values
    def get( self, key, default=None, return_type=None ): return self.values[ key ]


@pytest.mark.parametrize( "baseline_on, principles_on", [ ( True, False ), ( False, True ) ] )
def test_each_twin_reads_only_its_own_switch( factory, monkeypatch, baseline_on, principles_on ):
    """One switch on and the other off: only the twin that owns the on switch runs."""
    values = { ot.BASELINE_SWITCH_KEY: baseline_on, ot.PRINCIPLES_SWITCH_KEY: principles_on }
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: KeyedSwitches( values ) )
    monkeypatch.setattr( ot, "opus_model", lambda: OPUS )
    stamp = lambda: T0 + timedelta( minutes=1 )
    first = asyncio.run( ot.run_baseline_opus( factory, ask( factory ), Baseline(), pf.CapGate( 1 ), clock=stamp ) )
    second = asyncio.run( ot.run_principles_opus( factory, ask( factory ), Baseline(), Embedder(), ENCODER, EXTRACT, pf.CapGate( 1 ), clock=stamp ) )
    off = { "status": "not_run", "reason": "switch off" }
    assert ( first == off ) is ( not baseline_on ) and ( second == off ) is ( not principles_on )


def test_the_opus_baseline_keeps_every_member_of_the_contract_but_the_model():
    """It meets the contract, carries the model given and shares the rest with the baseline."""
    c0   = Baseline()
    twin = ot.OpusBaseline( c0, "opus-y" )
    assert pf.check_baseline( twin ) is None and twin.model == "opus-y"
    assert ( twin.timeout_seconds, twin.errors, twin.predictor_version ) == ( c0.timeout_seconds, c0.errors, c0.predictor_version )
    assert ( twin.build_prompts, twin.parse, twin.complete ) == ( c0.build_prompts, c0.parse, c0.complete )


@pytest.mark.parametrize( "model", [ "", "   ", None, 7 ] )
def test_the_opus_baseline_refuses_a_blank_model( model ):
    """A twin never falls back to the baseline's model."""
    with pytest.raises( ValueError, match="non-empty string" ): ot.OpusBaseline( Baseline(), model )


def test_each_gate_takes_its_own_cap_from_the_ini( monkeypatch ):
    """The two twins have separate caps, each read from its own key."""
    seen = []
    class Keyed:
        def get_required( self, key, return_type=None ):
            seen.append( key )
            return 3 if key == ot.BASELINE_CAP_KEY else 1
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Keyed() )
    assert ( ot.baseline_gate().limit, ot.principles_gate().limit ) == ( 3, 1 )
    assert seen == [ ot.BASELINE_CAP_KEY, ot.PRINCIPLES_CAP_KEY ]


def test_the_opus_id_is_required_and_read_through_the_manager( monkeypatch ):
    """The id comes through the manager's required read, so a twin never guesses a model."""
    monkeypatch.setattr( ot, "ConfigurationManager", lambda env_var_name=None: Stub( "opus-z" ) )
    assert ot.opus_model() == "opus-z"


_CONF_DIR = cu.get_project_root() + "/src/conf"
_KEYS     = [ ot.MODEL_KEY, ot.BASELINE_SWITCH_KEY, ot.BASELINE_CAP_KEY, ot.PRINCIPLES_SWITCH_KEY, ot.PRINCIPLES_CAP_KEY ]


@pytest.fixture
def shipped():
    """Open the shipped INI file as production reads it, then drop the singleton."""
    yield ConfigurationManager( config_path=_CONF_DIR + "/lupin-app.ini", splainer_path=_CONF_DIR + "/lupin-app-splainer.ini",
                                config_block_id="Lupin: Production", silent=True, mute_splainer=True, _reset_singleton=True )
    ConfigurationManager.reset_for_testing()


@pytest.mark.parametrize( "key", _KEYS )
def test_the_shipped_each_key_is_written_once_in_the_ini_and_explained_once_in_the_splainer( key ):
    """One line in each file names the key, so no later line can quietly override it."""
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
        assert len( [ line for line in open( f"{_CONF_DIR}/{name}" ).read().split( "\n" ) if line.startswith( key ) ] ) == 1, name


def test_the_shipped_ini_holds_both_twins_off_each_capped_at_one_call_and_names_the_opus_model( shipped ):
    """Both twins ship off, capped at one call each, with the Opus model id named."""
    assert shipped.get( ot.BASELINE_SWITCH_KEY, default=True, return_type="boolean" ) is False
    assert shipped.get( ot.PRINCIPLES_SWITCH_KEY, default=True, return_type="boolean" ) is False
    assert shipped.get_required( ot.BASELINE_CAP_KEY, return_type="int" ) == 1
    assert shipped.get_required( ot.PRINCIPLES_CAP_KEY, return_type="int" ) == 1
    assert shipped.get_required( ot.MODEL_KEY, return_type="str" ) == "claude-opus-5-5"
