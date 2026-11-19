"""
The record_forecast hook, the displayed arm's sibling row and the reconciliation check.

Two layers. The hook tests run record_forecast through the real get_db.
Only the session factory is replaced, by a recording session.
So the rollback on a raising hook is the real context manager's.
The reconciliation tests run the real models and queries on in-memory SQLite.
"""
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.rest.db.repositories.arm_forecast_repository import displayed_arm_hook, notifications_missing_displayed_sibling
from cosa.rest.postgres_models import PredictionArmForecast, PredictionLog

# Ids carry a hex letter, because SQLite reads an all-digit id back as a number.
NID = "a2345678-1234-5678-1234-567812345678"
ASK = { "message": "Should it proceed?", "response_type": "yes_no", "sender_id": "claude.code@lupin.deepily.ai#00000001" }


@compiles( JSONB, "sqlite" )
def _jsonb_as_json( _type, _compiler, **_kw ):
    """Let the two real tables be created on SQLite."""
    return "JSON"


class _RecordingSession:
    """A session that records what get_db does to it."""

    def __init__( self ):
        self.events = []
        self.added  = []

    def add( self, row ):   self.added.append( row )
    def flush( self ):      self.events.append( "flush" )
    def commit( self ):     self.events.append( "commit" )
    def rollback( self ):   self.events.append( "rollback" )
    def close( self ):      self.events.append( "close" )


@pytest.fixture
def wired( monkeypatch ):
    """The real engine and get_db over a recording session."""
    PredictionEngine.reset()
    session = _RecordingSession()
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", lambda: session )

    class _Repo:
        def __init__( self, sess ): self.sess = sess
        def log_prediction( self, **kwargs ):
            self.sess.events.append( "log_prediction" )
            self.sess.log_kwargs = kwargs
    monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", _Repo )
    yield PredictionEngine( debug=False ), session
    PredictionEngine.reset()


def test_with_no_hook_the_row_is_logged_and_committed_as_before( wired ):
    """No hook: log, commit, True, and no second write."""
    engine, session = wired
    assert engine.record_forecast( NID, ASK, strategy="cold_start", abstention_reason="no_history" ) is True
    assert session.events == [ "log_prediction", "commit", "commit", "close" ]  # record_forecast commits, then get_db commits on exit
    assert session.added == []


def test_a_hook_runs_between_the_log_row_and_the_commit_and_is_handed_the_stored_forecast( wired ):
    """The hook gets the session and the stored forecast, before the commit."""
    engine, session = wired
    seen = []
    def hook( sess, forecast ):
        sess.events.append( "hook" )
        seen.append( forecast )
    asked = datetime( 2026, 11, 19, 12, 0, tzinfo=timezone.utc )
    assert engine.record_forecast( NID, ASK, strategy="cold_start", abstention_reason="no_history", asked_at=asked, pre_commit_hook=hook ) is True
    assert session.events == [ "log_prediction", "hook", "commit", "commit", "close" ]
    forecast = seen[ 0 ]
    assert forecast[ "notification_id" ] == NID and forecast[ "input_cutoff" ] == asked
    assert forecast[ "abstention_reason" ] == "no_history" and forecast[ "forecast" ] is None
    assert forecast[ "forecast_source" ] == session.log_kwargs[ "ledger" ][ "forecast_source" ]
    assert forecast[ "forecast_ready_at" ] == session.log_kwargs[ "ledger" ][ "forecast_ready_at" ]
    assert forecast[ "predictor_version" ] == session.log_kwargs[ "ledger" ][ "predictor_version" ]


def test_a_raising_hook_rolls_everything_back_and_record_forecast_returns_false_without_raising( wired ):
    """A raising hook gives no commit, a rollback and False."""
    engine, session = wired
    def hook( sess, forecast ): raise RuntimeError( "sibling write failed" )
    assert engine.record_forecast( NID, ASK, strategy="cold_start", pre_commit_hook=hook ) is False
    assert session.events == [ "log_prediction", "rollback", "close" ]


def _sqlite_engine():
    """One in-memory SQLite database holding the two real tables, shared by every session."""
    engine = sa.create_engine( "sqlite://", poolclass=StaticPool )
    PredictionLog.__table__.create( engine )
    PredictionArmForecast.__table__.create( engine )
    return engine


def _real_session():
    """A session on a fresh in-memory SQLite database."""
    return Session( _sqlite_engine() )


GO_LIVE = datetime( 2026, 11, 19, 0, 0, tzinfo=timezone.utc )
AFTER   = datetime( 2026, 11, 19, 12, 0, tzinfo=timezone.utc )


def _log_row( nid, predicted_at=AFTER ):
    """A minimal prediction_log row, predicted at the given time."""
    return PredictionLog( notification_id=uuid.UUID( nid ), response_type="yes_no", category="c", predicted_at=predicted_at,
                          prediction_confidence=0.5, prediction_strategy="cold_start", similar_case_count=0 )


def _forecast( nid ):
    """The dict record_forecast hands a hook."""
    return { "notification_id": nid, "predictor_version": "pv", "forecast": { "value": "yes" },
             "input_cutoff": datetime( 2026, 11, 19, 12, 0, tzinfo=timezone.utc ), "evidence_ids": [ "e1" ],
             "forecast_ready_at": datetime( 2026, 11, 19, 12, 0, 1, tzinfo=timezone.utc ), "abstention_reason": "no_history" }


def test_the_hook_writes_the_displayed_arm_row_from_the_forecast_columns():
    """The sibling row equals the forecast columns and is flagged displayed."""
    session = _real_session()
    session.add( _log_row( NID ) )
    displayed_arm_hook( "A1" )( session, _forecast( NID ) )
    session.commit()
    row = session.query( PredictionArmForecast ).one()
    assert ( row.arm, row.displayed, row.predictor_version, row.forecast, row.evidence_ids, row.abstention_reason ) == ( "A1", True, "pv", { "value": "yes" }, [ "e1" ], "no_history" )
    assert row.input_cutoff.replace( tzinfo=None ) == datetime( 2026, 11, 19, 12, 0 ) and row.forecast_ready_at.replace( tzinfo=None ) == datetime( 2026, 11, 19, 12, 0, 1 )
    assert str( row.notification_id ) == NID


def test_the_hook_needs_an_arm_name():
    """An empty arm is refused when the hook is made."""
    with pytest.raises( ValueError, match="arm name" ):
        displayed_arm_hook( "" )


def test_the_reconciliation_check_reports_a_planted_missing_sibling_and_nothing_else():
    """Three cards: one reconciled, one with no sibling, one with only a hidden arm's row."""
    session = _real_session()
    ok, missing, hidden_only = ( "aaaaaaaa-0000-0000-0000-00000000000%d" % i for i in ( 1, 3, 2 ) )
    for nid in ( ok, missing, hidden_only ): session.add( _log_row( nid ) )
    displayed_arm_hook( "A1" )( session, _forecast( ok ) )
    session.add( PredictionArmForecast( notification_id=uuid.UUID( hidden_only ), arm="B1", displayed=False ) )
    session.commit()
    assert notifications_missing_displayed_sibling( session, GO_LIVE ) == [ uuid.UUID( hidden_only ), uuid.UUID( missing ) ]
    displayed_arm_hook( "A1" )( session, _forecast( missing ) )
    displayed_arm_hook( "A1" )( session, _forecast( hidden_only ) )
    session.commit()
    assert notifications_missing_displayed_sibling( session, GO_LIVE ) == []


def test_a_second_displayed_row_for_one_card_and_arm_is_refused_by_the_table():
    """The unique key on card and arm raises at the flush."""
    session = _real_session()
    session.add( _log_row( NID ) )
    hook = displayed_arm_hook( "A1" )
    hook( session, _forecast( NID ) )
    with pytest.raises( sa.exc.IntegrityError ):
        hook( session, _forecast( NID ) )


def test_a_row_predicted_before_the_go_live_is_not_listed():
    """Rows written before the hook existed never had a sibling, so the bound leaves them out."""
    session = _real_session()
    old, new = "aaaaaaaa-0000-0000-0000-000000000004", "aaaaaaaa-0000-0000-0000-000000000005"
    session.add( _log_row( old, predicted_at=datetime( 2026, 11, 18, 23, 59, tzinfo=timezone.utc ) ) )
    session.add( _log_row( new, predicted_at=GO_LIVE ) )
    session.commit()
    assert notifications_missing_displayed_sibling( session, GO_LIVE ) == [ uuid.UUID( new ) ]


def test_a_real_forecast_reaches_the_hook_and_the_sibling_row_matches_the_prediction_log_row( monkeypatch ):
    """On SQLite, a real forecast gives a sibling row equal to the forecast columns."""
    PredictionEngine.reset()
    engine = _sqlite_engine()
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", sessionmaker( bind=engine ) )
    result = PredictionResult( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_CBR_MAJORITY, predicted_value="yes",
                               confidence=0.8, similar_case_count=2, metadata={ "evidence_ids": [ "c1", "c2" ], "evidence_scores": [ 91.0, 80.5 ] } )
    asked = datetime( 2026, 11, 19, 12, 0, tzinfo=timezone.utc )
    forecaster = PredictionEngine( debug=False )
    assert forecaster.record_forecast( NID, ASK, prediction_result=result, asked_at=asked, pre_commit_hook=displayed_arm_hook( "A1" ) ) is True
    with Session( engine ) as check:
        log, sibling = check.query( PredictionLog ).one(), check.query( PredictionArmForecast ).one()
        assert sibling.forecast == log.predicted_value == { "value": "yes" }
        assert sibling.evidence_ids == log.evidence_ids == [ "c1", "c2" ]
        assert sibling.predictor_version == log.predictor_version and sibling.abstention_reason == log.abstention_reason
        assert sibling.forecast_ready_at == log.forecast_ready_at and sibling.displayed is True
        assert notifications_missing_displayed_sibling( check, datetime( 2020, 1, 1, tzinfo=timezone.utc ) ) == []
    PredictionEngine.reset()


def test_a_sibling_failure_leaves_no_row_in_either_table_on_a_real_database( monkeypatch ):
    """A hook that raises after the sibling is added leaves both tables empty."""
    PredictionEngine.reset()
    engine = _sqlite_engine()
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", sessionmaker( bind=engine ) )
    write_sibling = displayed_arm_hook( "A1" )
    def hook( session, forecast ):
        write_sibling( session, forecast )
        raise RuntimeError( "after the sibling was flushed" )
    assert PredictionEngine( debug=False ).record_forecast( NID, ASK, strategy="cold_start", pre_commit_hook=hook ) is False
    with Session( engine ) as check:
        assert check.query( PredictionLog ).count() == 0 and check.query( PredictionArmForecast ).count() == 0
    PredictionEngine.reset()
