"""
A shadow row stores the proxy's forecast only when the INI switch is on.

The repository test writes through log_shadow into the real ProxyDecision table on in-memory SQLite and reads the column back.
The caller tests fake the database and the switch, and read what log_shadow was handed.
The switch test builds a real ConfigurationManager over a temporary file.
"""
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db   # noqa: F401  importing it registers the SQLite type hooks, JSONB included
from cosa.agents.decision_proxy import config as proxy_config
from cosa.agents.decision_proxy.responder import DecisionResponder
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository
from cosa.rest.postgres_models import ProxyDecision

_ROW = dict( notification_id="n-1", domain="swe", category="deployment", question="deploy?", sender_id="lead" )


@pytest.fixture
def factory():
    engine = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    ProxyDecision.__table__.create( engine )
    yield sessionmaker( bind=engine )
    engine.dispose()


def _shadow_row( factory, **kwargs ):
    with factory() as session:
        row_id = ProxyDecisionRepository( session ).log_shadow( **_ROW, **kwargs ).id
        session.commit()
    with factory() as fresh:
        return fresh.get( ProxyDecision, row_id )


def test_log_shadow_stores_the_forecast_it_is_given_and_stays_a_shadow_row( factory ):
    row = _shadow_row( factory, decision_value="requires_review" )
    assert row.decision_value == "requires_review" and row.action == "shadow" and row.ratification_state == "not_required"


def test_log_shadow_with_no_forecast_leaves_the_column_empty_as_before( factory ):
    assert _shadow_row( factory ).decision_value is None


def _result( value="approved" ):
    return SimpleNamespace( action="shadow", value=value, category="deployment", confidence=0.8, trust_level=1, reason="r" )


def _orchestrator_call( switch ):
    repo = MagicMock()
    orch = SweTeamOrchestrator( task_description="Build X", config=SweTeamConfig( dry_run=True, trust_mode="disabled" ), job_id="swe-1" )
    with patch( "cosa.agents.swe_team.orchestrator.shadow_forecast_recording_enabled", return_value=switch ), \
         patch( "cosa.rest.db.database.get_db" ) as get_db, \
         patch( "cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository", return_value=repo ):
        get_db.return_value.__enter__.return_value = MagicMock()
        orch._persist_proxy_decision( "lead", "deploy?", _result( "requires_review" ), True )
    return repo.log_shadow.call_args.kwargs


def test_the_orchestrator_passes_the_forecast_only_with_the_switch_on():
    assert _orchestrator_call( True )[ "decision_value" ] == "requires_review"
    assert _orchestrator_call( False )[ "decision_value" ] is None


def _responder_call( switch ):
    responder = DecisionResponder.__new__( DecisionResponder )
    responder.domain_strategy = SimpleNamespace( name="swe" )
    responder._persist_embedding = MagicMock()
    repo_cls = MagicMock()
    modules = { "cosa.rest.db.database": MagicMock(), "cosa.rest.db.repositories.proxy_decision_repository": MagicMock( ProxyDecisionRepository=repo_cls ) }
    with patch.dict( sys.modules, modules ), patch( "cosa.agents.decision_proxy.responder.shadow_forecast_recording_enabled", return_value=switch ):
        responder._persist_decision( "nid", _result( "approved" ), "question text" )
    return repo_cls.return_value.log_shadow.call_args.kwargs


def test_the_responder_passes_the_forecast_only_with_the_switch_on():
    assert _responder_call( True )[ "decision_value" ] == "approved"
    assert _responder_call( False )[ "decision_value" ] is None


@pytest.mark.parametrize( "flip, expected", [ ( None, True ), ( "false", False ) ] )
def test_the_switch_reads_the_ini_as_production_does_and_ships_on( tmp_path, flip, expected ):
    from cosa.config.configuration_manager import ConfigurationManager
    conf = proxy_config.__file__.split( "/src/cosa/" )[ 0 ] + "/src/conf"
    text = open( f"{conf}/lupin-app.ini" ).read()
    if flip is not None:
        line = re.compile( rf"^({re.escape( proxy_config.SHADOW_FORECAST_RECORDING_KEY )}\s*=\s*)true$", re.MULTILINE )
        assert len( line.findall( text ) ) == 1
        text = line.sub( rf"\g<1>{flip}", text )
    copy = tmp_path / "copy.ini"
    copy.write_text( text )
    try:
        seen = ConfigurationManager( config_path=str( copy ), splainer_path=f"{conf}/lupin-app-splainer.ini",
                                     config_block_id="Lupin: Production", silent=True, mute_splainer=True, _reset_singleton=True )
        with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=seen ):
            assert proxy_config.shadow_forecast_recording_enabled() is expected
    finally:
        ConfigurationManager.reset_for_testing()


def test_the_code_default_is_off_and_the_shipped_ini_turns_it_on_with_an_explainer():
    assert proxy_config.DEFAULT_SHADOW_FORECAST_RECORDING is False
    root = proxy_config.__file__.split( "/src/cosa/" )[ 0 ]
    key  = proxy_config.SHADOW_FORECAST_RECORDING_KEY
    ini  = [ l for l in open( f"{root}/src/conf/lupin-app.ini" ) if l.startswith( key ) ]
    expl = [ l for l in open( f"{root}/src/conf/lupin-app-splainer.ini" ) if l.startswith( key ) ]
    assert len( ini ) == 1 and ini[ 0 ].split( "=" )[ 1 ].strip() == "true" and len( expl ) == 1
