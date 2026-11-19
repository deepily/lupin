"""
Real-Postgres proof of the displayed arm's sibling row, written in the ask-time commit.

A throwaway database is built by `alembic upgrade head`.
So the foreign key, the unique keys, the commit and the rollback behave as in production.
The tests run the real record_forecast, get_db and log_prediction.
The module skips when Postgres is unreachable.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

import tests.helpers.template_database as td
from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.db.repositories.arm_forecast_repository import displayed_arm_hook, notifications_missing_displayed_sibling
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog, User

_THROWAWAY_DB = f"arm_forecast_ledger_{os.getpid()}"
ASK           = { "message": "Should it proceed?", "response_type": "yes_no", "sender_id": "claude.code@lupin.deepily.ai#arm" }
GO_LIVE       = datetime( 2020, 1, 1, tzinfo=timezone.utc )


@pytest.fixture( scope="module" )
def database_url():
    """Yield a throwaway database URL at head; drop it at teardown; skip if Postgres is down."""
    server = make_url( td.clone_server_url() )
    plain  = server.render_as_string( hide_password=False )
    try:
        td.drop_database( plain, _THROWAWAY_DB )
        td.create_from_template( plain, _THROWAWAY_DB )
    except OperationalError as error:
        pytest.skip( f"Postgres unreachable, skipping the real-database arm forecast test: {error}" )
    url = server.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    try:
        command.upgrade( build_alembic_config( database_url=url ), "head" )
    except BaseException:
        td.drop_database( plain, _THROWAWAY_DB )
        raise
    yield url
    engine = create_engine( plain, isolation_level="AUTOCOMMIT" )
    with engine.connect() as conn:
        conn.execute( text( td.terminate_sessions_sql( td.uses_template() ) ), { "n": _THROWAWAY_DB } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
    engine.dispose()


@pytest.fixture
def wired( database_url, monkeypatch ):
    """Point get_db at the throwaway database; yield a session factory and a notification id."""
    engine  = create_engine( database_url )
    factory = sessionmaker( bind=engine )
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", factory )
    PredictionEngine.reset()
    with factory() as setup:
        uid = uuid.uuid4()
        setup.add( User( id=uid, email=f"arm-{uid.hex[:8]}@test.local", password_hash="x", email_verified=True, is_active=True,
                         is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ) ) )
        setup.flush()
        nid = uuid.uuid4()
        setup.add( Notification( id=nid, sender_id="claude.code@lupin.deepily.ai#arm", recipient_id=uid, message="m", type="task",
                                 priority="high", created_at=datetime.now( timezone.utc ), sender_persona="arm",
                                 response_requested=True, state="created" ) )
        setup.commit()
    yield factory, str( nid )
    PredictionEngine.reset()
    engine.dispose()


def _result():
    """A real forecast with evidence."""
    return PredictionResult( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_CBR_MAJORITY, predicted_value="yes",
                             confidence=0.8, similar_case_count=2, metadata={ "evidence_ids": [ "c1", "c2" ], "evidence_scores": [ 91.0, 80.5 ] } )


def test_a_hooked_forecast_commits_both_rows_and_the_sibling_equals_the_log_columns( wired ):
    """One commit stores both rows, and the sibling equals the log columns."""
    factory, nid = wired
    asked = datetime.now( timezone.utc ) - timedelta( seconds=5 )
    assert PredictionEngine( debug=False ).record_forecast( nid, ASK, prediction_result=_result(), asked_at=asked,
                                                            pre_commit_hook=displayed_arm_hook( "A1" ) ) is True
    with factory() as check:
        log     = check.query( PredictionLog ).filter_by( notification_id=uuid.UUID( nid ) ).one()
        sibling = check.query( PredictionArmForecast ).filter_by( notification_id=uuid.UUID( nid ) ).one()
        assert ( sibling.arm, sibling.displayed ) == ( "A1", True )
        assert sibling.forecast == log.predicted_value == { "value": "yes" }
        assert sibling.evidence_ids == log.evidence_ids == [ "c1", "c2" ]
        assert sibling.predictor_version == log.predictor_version and sibling.forecast_ready_at == log.forecast_ready_at
        assert sibling.input_cutoff == asked
        assert uuid.UUID( nid ) not in notifications_missing_displayed_sibling( check, GO_LIVE )


def test_no_hook_writes_the_log_row_alone_and_the_check_names_the_card( wired ):
    """Without a hook the sibling is absent, and the check names that card."""
    factory, nid = wired
    assert PredictionEngine( debug=False ).record_forecast( nid, ASK, strategy="cold_start", abstention_reason="no_history" ) is True
    with factory() as check:
        assert check.query( PredictionArmForecast ).filter_by( notification_id=uuid.UUID( nid ) ).count() == 0
        assert uuid.UUID( nid ) in notifications_missing_displayed_sibling( check, GO_LIVE )


def test_a_hook_that_raises_after_the_sibling_flush_leaves_neither_row( wired ):
    """The rollback takes the log row too, and record_forecast returns False."""
    factory, nid = wired
    write = displayed_arm_hook( "A1" )
    def hook( session, forecast ):
        write( session, forecast )
        raise RuntimeError( "after the sibling was flushed" )
    assert PredictionEngine( debug=False ).record_forecast( nid, ASK, strategy="cold_start", pre_commit_hook=hook ) is False
    with factory() as check:
        assert check.query( PredictionLog ).filter_by( notification_id=uuid.UUID( nid ) ).count() == 0
        assert check.query( PredictionArmForecast ).filter_by( notification_id=uuid.UUID( nid ) ).count() == 0


def test_a_card_that_is_not_a_notification_is_refused_by_the_foreign_key_and_nothing_is_stored( wired ):
    """The foreign key refuses the sibling; the call returns False and nothing is stored."""
    factory, _ = wired
    stranger = str( uuid.uuid4() )
    assert PredictionEngine( debug=False ).record_forecast( stranger, ASK, strategy="cold_start", pre_commit_hook=displayed_arm_hook( "A1" ) ) is False
    with factory() as check:
        assert check.query( PredictionLog ).filter_by( notification_id=uuid.UUID( stranger ) ).count() == 0


def test_a_second_forecast_for_one_card_is_refused_and_the_first_pair_stays( wired ):
    """The unique key refuses the repeat, so the stored pair is the first one."""
    factory, nid = wired
    engine = PredictionEngine( debug=False )
    assert engine.record_forecast( nid, ASK, strategy="cold_start", pre_commit_hook=displayed_arm_hook( "A1" ) ) is True
    assert engine.record_forecast( nid, ASK, strategy="cold_start", pre_commit_hook=displayed_arm_hook( "A1" ) ) is False
    with factory() as check:
        assert check.query( PredictionLog ).filter_by( notification_id=uuid.UUID( nid ) ).count() == 1
        assert check.query( PredictionArmForecast ).filter_by( notification_id=uuid.UUID( nid ) ).count() == 1
