"""
A lookup-neither replay reads only the cases answered by each ask's own moment.

The live engine reads cases from the database as of now. The replay injects a case provider, so the vote reads the
replay's visible cases at the ask's stamp. The named cases plant answers dated after the ask: the replay must not see
them, and the live path, with no provider, still must.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cosa.agents.prediction_engine import three_way_shadow
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, replay
from cosa.tests.unit.research.test_replay_loop import NOON, OWNER, SHA, _ask


@pytest.fixture
def engine( monkeypatch ):
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng.lookup_neither_forecast_enabled = True
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    @contextmanager
    def fake_db():
        yield SimpleNamespace()
    monkeypatch.setattr( "cosa.rest.db.database.get_db", fake_db )
    yield eng
    PredictionEngine.reset()


def _asks( engine ):
    """An early yes, the target ask, and three neither answers given after it."""
    return [ _ask( engine, "early", 1, 0, "yes" ), _ask( engine, "target", 1, 10, "yes" ) ] + \
           [ _ask( engine, f"late{i}", 1, 20 + i, "neither" ) for i in range( 3 ) ]


def _target_forecast( run ):
    return next( r for r in run[ "records" ][ ENGINE_ARM ] if r[ "meta" ][ "notification_id" ] == "target" )[ "meta" ][ "forecast" ]


def test_a_replay_does_not_see_an_answer_given_after_the_ask( engine, monkeypatch ):
    asks = _asks( engine )
    monkeypatch.setattr( three_way_shadow, "live_cases", lambda session, owner: pytest.fail( "the replay read the live database" ) )
    run  = replay( asks, engine, SHA, target_ids={ "target" } )
    assert _target_forecast( run )[ "value" ] == "yes"


def test_the_live_path_with_no_provider_still_reads_the_database_as_of_now( engine, monkeypatch ):
    asks = _asks( engine )
    late = [ dict( a, asked_at=NOON + timedelta( minutes=20 + i ) ) for i, a in enumerate( asks[ 2: ] ) ]
    seen = []
    monkeypatch.setattr( three_way_shadow, "live_cases", lambda session, owner: seen.append( owner ) or late )
    result = engine._predict_yes_no( "Proceed?", "c", asks[ 0 ][ "question_embedding" ], owner_user_id=OWNER )
    assert seen == [ OWNER ] and result.predicted_value == "neither"
    assert engine.three_way_case_provider is None


def test_the_provider_is_called_with_the_owner_and_its_moment_and_cases_are_the_votes( engine, monkeypatch ):
    asks   = _asks( engine )
    calls  = []
    moment = NOON + timedelta( minutes=30 )
    def provider( owner ):
        calls.append( owner )
        return moment, asks[ 2: ]
    engine.three_way_case_provider = provider
    monkeypatch.setattr( three_way_shadow, "live_cases", lambda session, owner: pytest.fail( "the provider was bypassed" ) )
    result = engine._predict_yes_no( "Proceed?", "c", asks[ 0 ][ "question_embedding" ], owner_user_id=OWNER )
    assert calls == [ OWNER ] and result.predicted_value == "neither"


def test_the_provider_is_removed_after_a_replay_and_when_it_raises( engine ):
    asks = _asks( engine )
    sentinel = lambda owner: ( NOON, [] )
    engine.three_way_case_provider = sentinel
    replay( asks, engine, SHA, target_ids={ "target" } )
    assert engine.three_way_case_provider is sentinel
    def boom( *a, **k ): raise RuntimeError( "predict failed" )
    engine.predict = boom
    with pytest.raises( RuntimeError ):
        replay( asks, engine, SHA, target_ids={ "target" } )
    assert engine.three_way_case_provider is sentinel
