"""
The learner's Opus twin calls, over in-memory SQLite and stand-in baselines.

The twins, retrieval and the sibling table are real. The baseline is a stand-in, except in the cache tests, which run the real baseline over a ledger.
Each test names what it would catch:
  - a twin building anything while switched off                         -> test_the_switch_off_*
  - a twin sending Haiku's prompt to Haiku, or other prompts than its twin -> test_a_twin_*
  - a retry, or a second call in flight for one twin                    -> test_a_failed_call_*, test_a_card_past_*
  - a twin answered from its Haiku twin's cached reply                  -> test_a_twin_never_reads_*
  - a twin missing from, or shown by, the per-arm summary               -> test_the_summary_*
"""

import asyncio
import uuid
from datetime import timedelta

import pytest

import cosa.agents.prediction_engine.context_baseline as cb
import cosa.agents.prediction_engine.opus_twins as ot
import cosa.agents.principle_learner.opus_call as oc
import cosa.agents.principle_learner.principles_call as pc
from cosa.agents.prediction_engine.principles_forecast import CapGate, concurrency_cap
from cosa.agents.principle_learner import extractor_job
from cosa.research.preference_replay.arm_summary import per_arm_summary
from cosa.rest.db.repositories.arm_forecast_repository import CAPPED_ARM_REASON
from cosa.rest.postgres_models import PredictionLog
from test_context_baseline import YES, baseline, replying
from test_principles_forecast import Baseline, ENCODER, EXTRACT, Embedder, Failed, T0, ask, factory, principle, rows  # noqa: F401  factory is a fixture

NOW  = T0 + timedelta( minutes=1 )
NO   = '{"answer": "no", "confidence": 0.9}'
OPUS = "opus-x"


@pytest.fixture( autouse=True )
def _fresh_state( monkeypatch ):
    """Start every test with no process gates and the settings answered by stand-ins."""
    oc.reset_gates()
    monkeypatch.setattr( ot, "opus_model", lambda: OPUS )
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: ENCODER )
    monkeypatch.setattr( pc, "extractor_version_of", lambda model: EXTRACT )
    monkeypatch.setattr( pc, "ConfigurationManager", lambda env_var_name=None: type( "C", (), { "get_required": lambda self, key: "model-x" } )() )
    yield
    oc.reset_gates()


def baseline_twin( factory, nid, **kwargs ):
    """Run the baseline twin for one card with a fixed clock and a gate of two."""
    kwargs.setdefault( "c0", Baseline() )
    kwargs.setdefault( "gate", CapGate( 2 ) )
    kwargs.setdefault( "enabled", True )
    return asyncio.run( oc.run_baseline_twin( nid, session_factory=factory, clock=lambda: NOW, **kwargs ) )


def principles_twin( factory, nid, **kwargs ):
    """Run the principles twin for one card with a fixed clock and a gate of two."""
    kwargs.setdefault( "c0", Baseline() )
    kwargs.setdefault( "gate", CapGate( 2 ) )
    kwargs.setdefault( "embedder", Embedder() )
    kwargs.setdefault( "enabled", True )
    return asyncio.run( oc.run_principles_twin( nid, session_factory=factory, clock=lambda: NOW, **kwargs ) )


def test_the_switch_off_builds_nothing_and_writes_nothing_for_either_twin( factory, monkeypatch ):
    """With a twin's switch off, neither the baseline nor the gate nor the embedder is built."""
    def boom( *a, **k ): raise AssertionError( "built while the switch was off" )
    monkeypatch.setattr( oc, "get_baseline", boom )
    monkeypatch.setattr( oc, "get_gate", boom )
    monkeypatch.setattr( oc, "provider_embedder", boom )
    nid = ask( factory )
    off = { "status": "not_run", "reason": "switch off" }
    assert asyncio.run( oc.run_baseline_twin( nid, session_factory=factory, enabled=False ) ) == off
    assert asyncio.run( oc.run_principles_twin( nid, session_factory=factory, enabled=False ) ) == off
    assert rows( factory ) == []


def test_each_switch_is_read_from_its_own_ini_key_when_not_given( factory, monkeypatch ):
    """With no argument, each twin reads its own INI key and never the other's."""
    seen = []
    monkeypatch.setattr( oc, "switch_enabled", lambda key: seen.append( key ) or False )
    nid = ask( factory )
    asyncio.run( oc.run_baseline_twin( nid, session_factory=factory ) )
    asyncio.run( oc.run_principles_twin( nid, session_factory=factory ) )
    assert seen == [ "prediction learner opus twin baseline enabled", "prediction learner opus twin principles forecast enabled" ]


def test_a_twin_sends_its_twins_prompts_to_opus_and_stores_a_row_under_its_own_arm( factory ):
    """
    The baseline twin sends the baseline's prompts as they are, with the Opus id.

    The row is for its own arm, not displayed, with the baseline's version and the Opus suffix.
    """
    c0     = Baseline()
    result = baseline_twin( factory, ask( factory ), c0=c0 )
    row    = rows( factory )[ 0 ]
    assert result == { "status": "ran", "reason": None } and len( c0.calls ) == 1
    assert ( c0.calls[ 0 ][ "model" ], c0.calls[ 0 ][ "system" ], c0.calls[ 0 ][ "user" ] ) == ( OPUS, "SYSTEM", "USER prompt for Which plan?" )
    assert ( row.arm, row.displayed, row.predictor_version, row.evidence_ids ) == ( "C0-opus", False, "c0-v1+opus", [] )


def test_the_principles_twin_adds_the_same_block_the_principles_forecast_gets( factory ):
    """The principles twin sends the baseline's prompt plus the block, and names the principle."""
    nid, pid = ask( factory ), principle( factory )
    c0       = Baseline()
    result   = principles_twin( factory, nid, c0=c0 )
    row      = rows( factory )[ 0 ]
    assert result == { "status": "ran", "reason": None }
    assert c0.calls[ 0 ][ "model" ] == OPUS and c0.calls[ 0 ][ "user" ].startswith( "USER prompt for Which plan?" )
    assert "link what you ask me to approve" in c0.calls[ 0 ][ "user" ]
    assert ( row.arm, row.displayed, row.predictor_version, row.evidence_ids ) == ( "B1-opus", False, "c0-v1+principles+opus", [ str( pid ) ] )


def test_a_failed_call_is_one_call_with_no_retry_and_one_not_ready_row( factory ):
    """A model failure is not retried: one call, one failed row naming the error."""
    c0     = Baseline( fail=Failed( "overloaded" ) )
    result = baseline_twin( factory, ask( factory ), c0=c0 )
    assert result == { "status": "failed", "reason": "model_error: Failed" } and len( c0.calls ) == 1
    only = rows( factory )
    assert len( only ) == 1 and only[ 0 ].forecast is None and only[ 0 ].abstention_reason == "model_error: Failed"


def test_each_twin_has_its_own_gate_of_one_made_once_per_process():
    """Two reads give one gate per twin, never shared, and the committed cap is one in flight."""
    first, second = oc.get_gate( ot.ARM_BASELINE_OPUS ), oc.get_gate( ot.ARM_PRINCIPLES_OPUS )
    assert first is oc.get_gate( ot.ARM_BASELINE_OPUS ) and second is oc.get_gate( ot.ARM_PRINCIPLES_OPUS ) and first is not second
    assert ( first.limit, second.limit ) == ( 1, 1 )
    oc.reset_gates()
    assert oc.get_gate( ot.ARM_BASELINE_OPUS ) is not first
    with pytest.raises( KeyError ): oc.get_gate( "C0" )


def test_a_card_past_a_twins_cap_gets_the_capped_row_and_no_call_and_the_other_twin_still_runs( factory ):
    """With the baseline twin's one place taken, its next ask is capped and the other twin runs."""
    assert oc.get_gate( ot.ARM_BASELINE_OPUS ).try_enter() is True
    nid        = ask( factory )
    c0         = Baseline()
    capped     = asyncio.run( oc.run_baseline_twin( nid, session_factory=factory, c0=c0, enabled=True, clock=lambda: NOW ) )
    other      = asyncio.run( oc.run_principles_twin( nid, session_factory=factory, c0=c0, embedder=Embedder(), enabled=True, clock=lambda: NOW ) )
    assert capped == { "status": "capacity", "reason": CAPPED_ARM_REASON } and other == { "status": "ran", "reason": None }
    assert len( c0.calls ) == 1, "only the principles twin called a model"
    assert { r.arm: r.abstention_reason for r in rows( factory ) } == { "C0-opus": CAPPED_ARM_REASON, "B1-opus": None }


def test_the_session_factory_defaults_to_the_apps_get_db( factory, monkeypatch ):
    """With no factory given, the app's get_db is the one both twins use."""
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", factory )
    nid = ask( factory )
    asyncio.run( oc.run_baseline_twin( nid, c0=Baseline(), gate=CapGate( 2 ), enabled=True, clock=lambda: NOW ) )
    asyncio.run( oc.run_principles_twin( nid, c0=Baseline(), gate=CapGate( 2 ), embedder=Embedder(), enabled=True, clock=lambda: NOW ) )
    assert sorted( r.arm for r in rows( factory ) ) == [ "B1-opus", "C0-opus" ]


def test_the_twins_default_to_this_processs_baseline_gates_and_embedder( factory, monkeypatch ):
    """With none given, each twin uses the process's own baseline, gate and embedder."""
    c0 = Baseline()
    monkeypatch.setattr( oc, "get_baseline", lambda: ( c0, None ) )
    monkeypatch.setattr( ot, "baseline_gate", lambda: CapGate( 1 ) )
    monkeypatch.setattr( ot, "principles_gate", lambda: CapGate( 1 ) )
    monkeypatch.setattr( oc, "baseline_gate", lambda: CapGate( 1 ) )
    monkeypatch.setattr( oc, "principles_gate", lambda: CapGate( 1 ) )
    monkeypatch.setattr( extractor_job, "default_embed", lambda text: [ 1.0, 0.0 ] + [ 0.0 ] * 766 )
    nid, pid = ask( factory ), principle( factory )
    assert asyncio.run( oc.run_baseline_twin( nid, session_factory=factory, enabled=True, clock=lambda: NOW ) ) == { "status": "ran", "reason": None }
    assert asyncio.run( oc.run_principles_twin( nid, session_factory=factory, enabled=True, clock=lambda: NOW ) ) == { "status": "ran", "reason": None }
    assert len( c0.calls ) == 2
    by_arm = { r.arm: r.evidence_ids for r in rows( factory ) }
    assert by_arm == { "C0-opus": [], "B1-opus": [ str( pid ) ] }, "the provider's vector found the principle"


def test_a_twin_never_reads_its_haiku_twins_cached_reply( factory, tmp_path ):
    """
    The real baseline and ledger: Haiku answers first, then the same card goes to the twin.

    The prompts are identical, so only the model id tells the two apart in the ledger key. Opus must be asked,
    and its own reply, not Haiku's cached one, must be the stored forecast.
    """
    models = []
    async def query( prompt, options ):
        models.append( options.model )
        async for message in replying( YES if options.model == "haiku-x" else NO )( prompt, options ): yield message
    c0  = baseline( tmp_path, query )
    nid = ask( factory )
    haiku = asyncio.run( cb.run_context_forecast( nid, session_factory=factory, c0=c0, gate=CapGate( 1 ), enabled=True, clock=lambda: NOW ) )
    twin  = baseline_twin( factory, nid, c0=c0 )
    assert haiku == { "status": "ran", "reason": None } and twin == { "status": "ran", "reason": None }
    assert models == [ "haiku-x", OPUS ], "the twin made its own call to Opus"
    forecasts = { r.arm: r.forecast for r in rows( factory ) }
    assert forecasts[ "C0" ] != forecasts[ "C0-opus" ], "the twin's stored forecast is Opus's reply, not Haiku's"
    again = baseline_twin( factory, ask( factory ), c0=c0 )
    assert again == { "status": "ran", "reason": None } and models == [ "haiku-x", OPUS ], "a repeat of the same prompts by the twin is its own ledger read"


def test_the_summary_lists_the_twins_beside_their_haiku_twins_with_their_own_counts( factory ):
    """
    One answered card runs all four arms through the real calls.

    One summary call lists the four arms side by side, and the twins carry their own timeliness and are never displayed.
    """
    nid = ask( factory )
    with factory() as db:
        db.add( PredictionLog( notification_id=uuid.UUID( nid ), response_type="yes_no", category="c", predicted_at=T0, prediction_confidence=0.5,
                               prediction_strategy="s", similar_case_count=0, responded_at=T0 + timedelta( minutes=30 ), actual_value={ "value": "yes" } ) )
        db.commit()
    c0, gate, clock = Baseline(), lambda: CapGate( 2 ), lambda: NOW
    asyncio.run( cb.run_context_forecast( nid, session_factory=factory, c0=c0, gate=gate(), enabled=True, clock=clock ) )
    asyncio.run( pc.run_principles_forecast( nid, session_factory=factory, c0=c0, gate=gate(), embedder=Embedder(), enabled=True, clock=clock ) )
    baseline_twin( factory, nid, c0=c0 )
    principles_twin( factory, nid, c0=c0 )
    with factory() as db: summaries = per_arm_summary( db )
    assert [ s[ "arm" ] for s in summaries ] == [ "B1", "B1-opus", "C0", "C0-opus" ]
    assert all( ( s[ "forecasts" ], s[ "answered" ], s[ "timely" ], s[ "capped" ], s[ "timeliness" ] ) == ( 1, 1, 1, 0, 1.0 ) for s in summaries )
    assert [ r.displayed for r in rows( factory ) ] == [ False ] * 4


def test_the_committed_ini_has_both_switches_off_one_in_flight_each_and_an_opus_id():
    """The committed settings: both twins off, one call in flight each, and a non-blank model id."""
    from cosa.config.configuration_manager import ConfigurationManager
    config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    assert config.get( ot.BASELINE_SWITCH_KEY, default=True, return_type="boolean" ) is False
    assert config.get( ot.PRINCIPLES_SWITCH_KEY, default=True, return_type="boolean" ) is False
    assert ( ot.baseline_gate().limit, ot.principles_gate().limit ) == ( 1, 1 )
    assert config.get_required( ot.MODEL_KEY, return_type="str" ).strip() != ""
    assert concurrency_cap() >= 1
