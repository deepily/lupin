"""
The learner's second call per ask, over in-memory SQLite and a stand-in baseline.

The baseline, the embedder and the sessions are the stand-ins that file defines. The call, retrieval and the sibling table are real.
Each test names what it would catch:
  - the call building anything while switched off                        -> test_the_switch_off_*
  - a prompt that differs from the baseline's by more than the block    -> test_the_call_is_the_baselines_*
  - a second gate, so the cap does not hold across asks                  -> test_one_gate_*
  - the call taking a slot from the baseline                             -> test_the_cap_is_not_the_baselines
  - the wrong encoder or extractor version reaching retrieval            -> test_the_versions_*
  - the committed switch being on, or the cap missing                    -> test_the_committed_*
"""

import asyncio
from datetime import timedelta

import pytest

import cosa.agents.principle_learner.principles_call as pc
import cosa.rest.db.database as database
from cosa.agents.prediction_engine.principles_forecast import CAP_KEY, SWITCH_KEY, CapGate
from cosa.agents.principle_learner import extractor_job
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION
from cosa.rest.db.repositories.arm_forecast_repository import CAPPED_ARM_REASON
from test_principles_forecast import Baseline, ENCODER, EXTRACT, Embedder, T0, ask, factory, principle, rows, vec  # noqa: F401  factory is a fixture

NOW = T0 + timedelta( minutes=1 )


@pytest.fixture( autouse=True )
def _fresh_gate():
    """Start and end every test with no process gate."""
    pc.reset_gate()
    yield
    pc.reset_gate()


def settings( monkeypatch, model="model-x" ):
    """Make the settings read answer one extractor model, not the committed one."""
    monkeypatch.setattr( pc, "ConfigurationManager", lambda env_var_name=None: type( "C", (), { "get_required": lambda self, key: model } )() )


def run( factory, nid, **kwargs ):
    """Run the learner's call for one card, with stand-ins and a fixed clock."""
    kwargs.setdefault( "c0", Baseline() )
    kwargs.setdefault( "gate", CapGate( 2 ) )
    kwargs.setdefault( "embedder", Embedder() )
    kwargs.setdefault( "enabled", True )
    return asyncio.run( pc.run_principles_forecast( nid, session_factory=factory, clock=lambda: NOW, **kwargs ) )


def test_the_switch_off_builds_nothing_and_writes_nothing( factory, monkeypatch ):
    """With the switch off, neither the baseline nor the gate nor the embedder is built."""
    def boom( *a, **k ): raise AssertionError( "built while the switch was off" )
    monkeypatch.setattr( pc, "get_baseline", boom )
    monkeypatch.setattr( pc, "get_gate", boom )
    monkeypatch.setattr( pc, "provider_embedder", boom )
    result = asyncio.run( pc.run_principles_forecast( ask( factory ), session_factory=factory, enabled=False ) )
    assert result == { "status": "not_run", "reason": "switch off" } and rows( factory ) == []


def test_the_switch_is_read_from_the_ini_when_not_given( factory, monkeypatch ):
    """No argument means the INI switch decides, and the committed value is off."""
    seen = []
    monkeypatch.setattr( pc, "principles_forecast_enabled", lambda: seen.append( "read" ) or False )
    assert asyncio.run( pc.run_principles_forecast( ask( factory ), session_factory=factory ) ) == { "status": "not_run", "reason": "switch off" }
    assert seen == [ "read" ]


def test_the_call_is_the_baselines_prompt_plus_the_block_and_stores_a_principles_row( factory, monkeypatch ):
    """
    The baseline's model, timeout and system prompt are used once.

    The user prompt carries the block. One row for the principles arm is stored, not displayed, with the principle id.
    """
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: ENCODER )
    monkeypatch.setattr( pc, "extractor_version_of", lambda model: EXTRACT )
    settings( monkeypatch )
    nid, pid = ask( factory ), principle( factory )
    c0       = Baseline()
    result   = run( factory, nid, c0=c0 )
    call     = c0.calls[ 0 ]
    row      = rows( factory )[ 0 ]
    assert result == { "status": "ran", "reason": None } and len( c0.calls ) == 1
    assert ( call[ "model" ], call[ "system" ], call[ "timeout" ] ) == ( "haiku-x", "SYSTEM", 30 )
    assert "link what you ask me to approve" in call[ "user" ] and call[ "user" ].startswith( "USER prompt for Which plan?" )
    assert ( row.arm, row.displayed, row.predictor_version, row.evidence_ids ) == ( "B1", False, "c0-v1+principles", [ str( pid ) ] )


def test_the_baseline_gate_and_embedder_default_to_this_processs_own( factory, monkeypatch ):
    """With none given, the call uses the process's own baseline, gate and embedder."""
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: ENCODER )
    monkeypatch.setattr( pc, "extractor_version_of", lambda model: EXTRACT )
    settings( monkeypatch )
    c0 = Baseline()
    monkeypatch.setattr( pc, "get_baseline", lambda: ( c0, None ) )
    monkeypatch.setattr( pc, "concurrency_cap", lambda: 1 )
    monkeypatch.setattr( extractor_job, "default_embed", lambda text: vec( 1, 0 ) )
    nid, pid = ask( factory ), principle( factory )
    result = asyncio.run( pc.run_principles_forecast( nid, session_factory=factory, enabled=True, clock=lambda: NOW ) )
    assert result == { "status": "ran", "reason": None } and len( c0.calls ) == 1
    assert rows( factory )[ 0 ].evidence_ids == [ str( pid ) ], "the provider's vector found the principle"


def test_the_session_factory_defaults_to_the_apps_get_db( factory, monkeypatch ):
    """With no factory given, the app's get_db is the one used."""
    monkeypatch.setattr( database, "get_db", factory )
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: ENCODER )
    monkeypatch.setattr( pc, "extractor_version_of", lambda model: EXTRACT )
    settings( monkeypatch )
    nid = ask( factory )
    result = asyncio.run( pc.run_principles_forecast( nid, c0=Baseline(), gate=CapGate( 2 ), embedder=Embedder(), enabled=True, clock=lambda: NOW ) )
    assert result == { "status": "ran", "reason": None } and len( rows( factory ) ) == 1


def test_the_versions_the_call_passes_are_the_extractors_stored_encoder_and_the_settings_extractor( monkeypatch ):
    """
    The encoder is the extractor's own string.

    The extractor version is the settings' model plus the prompt version. Retrieval filters on both, so a wrong one finds no principle.
    """
    seen = {}
    async def recorder( session_factory, notification_id, c0, embedder, encoder, extractor, gate, enabled=None, clock=None ):
        seen.update( encoder=encoder, extractor=extractor, enabled=enabled )
        return { "status": "ran", "reason": None }
    monkeypatch.setattr( pc, "run_b1", recorder )
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: "enc-literal:recipe" )
    settings( monkeypatch, model="model-y" )
    asyncio.run( pc.run_principles_forecast( "n", session_factory=object(), c0=object(), gate=object(), embedder=object(), enabled=True ) )
    assert seen[ "encoder" ] == "enc-literal:recipe" and seen[ "enabled" ] is True
    assert seen[ "extractor" ] == f"model-y:{PROMPT_VERSION}" and seen[ "extractor" ].startswith( "model-y:" )


def test_one_gate_is_made_per_process_and_reset_makes_a_new_one( monkeypatch ):
    """Two reads give one gate, so the cap holds across asks; a reset reads the cap again."""
    monkeypatch.setattr( pc, "concurrency_cap", lambda: 3 )
    first = pc.get_gate()
    assert pc.get_gate() is first and first.limit == 3
    pc.reset_gate()
    assert pc.get_gate() is not first


def test_a_card_past_the_process_cap_gets_the_capped_row_and_no_call( factory, monkeypatch ):
    """With the one place taken, the next ask is capped at once through the process gate."""
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: ENCODER )
    monkeypatch.setattr( pc, "extractor_version_of", lambda model: EXTRACT )
    settings( monkeypatch )
    monkeypatch.setattr( pc, "concurrency_cap", lambda: 1 )
    assert pc.get_gate().try_enter() is True
    c0     = Baseline()
    result = asyncio.run( pc.run_principles_forecast( ask( factory ), session_factory=factory, c0=c0, embedder=Embedder(), enabled=True, clock=lambda: NOW ) )
    assert result == { "status": "capacity", "reason": CAPPED_ARM_REASON } and c0.calls == []
    assert rows( factory )[ 0 ].abstention_reason == CAPPED_ARM_REASON


def test_the_cap_is_not_the_baselines( factory, monkeypatch ):
    """A full baseline gate does not stop the principles call, because the two caps are separate."""
    monkeypatch.setattr( extractor_job, "encoder_version", lambda: ENCODER )
    monkeypatch.setattr( pc, "extractor_version_of", lambda model: EXTRACT )
    settings( monkeypatch )
    monkeypatch.setattr( pc, "concurrency_cap", lambda: 1 )
    full = CapGate( 1 )
    assert full.try_enter() is True
    monkeypatch.setattr( pc, "get_baseline", lambda: ( Baseline(), full ) )
    result = asyncio.run( pc.run_principles_forecast( ask( factory ), session_factory=factory, embedder=Embedder(), enabled=True, clock=lambda: NOW ) )
    assert result == { "status": "ran", "reason": None } and pc.get_gate() is not full


def test_the_provider_embedder_uses_the_extractors_own_embedding_call( monkeypatch ):
    """The embedder's encode is default_embed, looked up at call time."""
    monkeypatch.setattr( extractor_job, "default_embed", lambda text: [ text, "vector" ] )
    assert pc.provider_embedder().encode( "card text" ) == [ "card text", "vector" ]


def test_the_committed_ini_has_the_switch_off_and_a_positive_cap():
    """The committed settings: the principles forecast is off, with a positive cap."""
    from cosa.agents.prediction_engine.principles_forecast import concurrency_cap, principles_forecast_enabled
    assert SWITCH_KEY == "prediction learner principles forecast enabled" and CAP_KEY == "prediction learner principles forecast max concurrent"
    assert principles_forecast_enabled() is False
    assert concurrency_cap() >= 1
