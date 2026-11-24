"""
The re-frame history survives a restart, rebuilt from the stored rows.

The store is a real ProxyDecision table in in-memory SQLite, written through the real repository.
The strategy is real, over a real tracker. Only the neither switch is patched.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db   # noqa: F401  registers the SQLite type hooks, JSONB included
from cosa.agents.decision_proxy.agreement import REFRAME_WINDOW
from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.swe_team import strategy_builder
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
from cosa.agents.utils.agent_notification_dispatcher import answer_source_is_human
from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository
from cosa.rest.postgres_models import ProxyDecision

SWITCH = "cosa.agents.swe_team.proxy.engineering_strategy.neither_is_no_ruling_enabled"
T0     = datetime( 2026, 11, 1, tzinfo=timezone.utc )


@pytest.fixture
def factory():
    engine = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    ProxyDecision.__table__.create( engine )
    yield sessionmaker( bind=engine )
    engine.dispose()


def _store( factory, rows, category="general" ):
    """Write ( minutes, source, stance ) rows in the order given, each with its own time."""
    with factory() as session:
        for i, ( minutes, source, stance ) in enumerate( rows ):
            meta = { "job_id": "j", "user_answer": True, "answer_source": source }
            if source in ( "human", "not_operator" ): meta.update( { "answer_stance": stance, "answer_comment": None, "answer_raw": stance } )
            row = ProxyDecisionRepository( session ).log_shadow( f"n-{category}-{i}-{minutes}", "swe", category, "q?", metadata_json=meta )
            row.created_at = T0 + timedelta( minutes=minutes )
        session.commit()


def _loader( factory, seen=None ):
    def stored_answers( category ):
        with factory() as session:
            for row in ProxyDecisionRepository( session ).iter_answered_newest_first( "swe", category ):
                if seen is not None: seen.append( row.metadata_json )
                yield row.metadata_json
    return stored_answers


def _strategy( factory, switch=True, seen=None ):
    tracker = TrustTracker( l2_threshold=3, l3_threshold=6, l4_threshold=9, l5_threshold=12 )
    with patch( SWITCH, return_value=switch ):
        return EngineeringStrategy( trust_tracker=tracker, trust_mode="active", cap_levels={ "general": 5 }, stored_answers=_loader( factory, seen ) )


def _human( stances ):
    return [ ( i, "human", stance ) for i, stance in enumerate( stances ) ]


def test_a_category_over_the_bar_before_the_restart_is_still_blocked( factory ):
    _store( factory, _human( [ "neither" ] * 3 + [ "yes" ] * 17 ) )         # 3 of 20: over 1 in 10
    strategy = _strategy( factory )
    assert strategy.reframe_blocked( "general" ) is True


def test_a_category_just_under_the_bar_is_not_blocked( factory ):
    _store( factory, _human( [ "neither" ] * 2 + [ "yes" ] * 18 ) )         # 2 of 20: at the bar
    assert _strategy( factory ).reframe_blocked( "general" ) is False


def test_the_rebuilt_block_holds_the_level_restored_after_construction( factory ):
    _store( factory, _human( [ "neither" ] * 3 + [ "yes" ] * 17 ) )
    strategy = _strategy( factory )
    for _ in range( 7 ): strategy.trust_tracker.record_decision( "general", success=True )     # the trust rows load after construction
    assert strategy.trust_tracker.get_level( "general" ) == 3
    assert strategy.get_trust_level( "general" ) == 3
    for _ in range( 3 ): strategy.trust_tracker.record_decision( "general", success=True )
    assert strategy.trust_tracker.get_level( "general" ) == 4 and strategy.get_trust_level( "general" ) == 3


def test_a_note_after_the_rebuild_settles_the_ceiling_first_and_can_lift_it( factory ):
    _store( factory, _human( [ "neither" ] * 3 + [ "yes" ] * 17 ) )
    strategy = _strategy( factory )
    for _ in range( 20 ): strategy.note_stance( "general", "yes" )          # the three neithers leave the window
    assert strategy.reframe_blocked( "general" ) is False


def test_default_and_unattributed_rows_never_enter_the_window( factory ):
    rows = [ ( i, source, "neither" ) for i, source in enumerate( [ "default", "unattributed", "proxy" ] * 5 ) ] + [ ( 100 + i, "human", "yes" ) for i in range( 5 ) ]
    _store( factory, rows )
    strategy = _strategy( factory )
    assert strategy._stance_history[ "general" ] == [ "yes" ] * 5
    assert strategy.reframe_blocked( "general" ) is False


def test_a_not_operator_row_never_enters_the_window_even_with_a_stance_stored( factory ):
    _store( factory, [ ( i, "not_operator", "neither" ) for i in range( 5 ) ] + [ ( 100 + i, "human", "yes" ) for i in range( 5 ) ] )
    strategy = _strategy( factory )
    assert strategy._stance_history[ "general" ] == [ "yes" ] * 5
    assert strategy.reframe_blocked( "general" ) is False


def test_the_window_is_the_newest_twenty_ordered_by_stored_time_not_insertion( factory ):
    # inserted oldest-stored-time last: the five oldest by time are neithers written LAST
    rows = [ ( 100 + i, "human", "yes" ) for i in range( 20 ) ] + [ ( i, "human", "neither" ) for i in range( 5 ) ]
    _store( factory, rows )
    strategy = _strategy( factory )
    assert strategy._stance_history[ "general" ] == [ "yes" ] * 20
    assert strategy.reframe_blocked( "general" ) is False


def test_the_newest_row_is_last_in_the_rebuilt_window( factory ):
    _store( factory, [ ( 5, "human", "no" ), ( 1, "human", "yes" ), ( 9, "human", "neither" ) ] )
    assert _strategy( factory )._stance_history[ "general" ] == [ "yes", "no", "neither" ]


def test_it_reads_no_more_than_the_window_per_category( factory ):
    _store( factory, _human( [ "yes" ] * 30 ) )
    seen = []
    _strategy( factory, seen=seen )
    assert len( seen ) == REFRAME_WINDOW


def test_with_the_switch_off_nothing_is_rebuilt_and_the_store_is_not_read( factory ):
    _store( factory, _human( [ "neither" ] * 20 ) )
    seen     = []
    strategy = _strategy( factory, switch=False, seen=seen )
    assert strategy._stance_history == {} and seen == [] and strategy.reframe_blocked( "general" ) is False


def test_with_no_store_given_the_windows_start_empty():
    with patch( SWITCH, return_value=True ):
        assert EngineeringStrategy( trust_mode="active" )._stance_history == {}


def test_a_category_with_no_human_rows_gets_no_window( factory ):
    _store( factory, [ ( 1, "default", None ) ] )
    assert _strategy( factory )._stance_history == {}


def test_the_rebuild_asks_the_one_predicate( factory ):
    _store( factory, _human( [ "neither" ] * 4 ) )
    with patch( "cosa.agents.swe_team.proxy.engineering_strategy.answer_source_is_human", return_value=False ) as ask:
        strategy = _strategy( factory )
    assert ask.called and strategy._stance_history == {}


@pytest.mark.parametrize( "source, expected", [ ( "human", True ), ( "default", False ), ( "unattributed", False ), ( None, False ) ] )
def test_the_predicate_counts_only_human( source, expected ):
    assert answer_source_is_human( source ) is expected


def test_the_builders_stream_reads_the_store_newest_first( factory ):
    _store( factory, [ ( 1, "human", "yes" ), ( 2, "human", "no" ) ] )
    from contextlib import contextmanager

    @contextmanager
    def get_db():
        with factory() as session: yield session

    with patch( "cosa.rest.db.database.get_db", get_db ):
        assert [ m[ "answer_stance" ] for m in strategy_builder.stored_answers_for( "general" ) ] == [ "no", "yes" ]


def test_the_builders_stream_ends_empty_when_the_database_fails( caplog ):
    def broken(): raise RuntimeError( "db down" )
    with patch( "cosa.rest.db.database.get_db", broken ):
        assert list( strategy_builder.stored_answers_for( "general" ) ) == []
    assert "Re-frame history rebuild skipped" in caplog.text
