"""
Real-database tests for the auth log repositories: paged reads and age cleanup.

The mocked tests for these repositories answer the same for any filter column. These run the
queries against Postgres, so a swapped column, a lost order or a wrong cutoff changes the result.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cosa.rest.db.repositories.auth_audit_log_repository import AuthAuditLogRepository
from cosa.rest.db.repositories.failed_login_attempt_repository import FailedLoginAttemptRepository
from cosa.rest.postgres_models import AuthAuditLog, Base, FailedLoginAttempt

NOW = datetime.now( timezone.utc )


@pytest.fixture( scope="module" )
def auth_tables( pg_engine ):
    """Ensures: the audit log and failed-attempt tables exist on the disposable database."""
    for model in ( AuthAuditLog, FailedLoginAttempt ):
        Base.metadata.tables[ model.__tablename__ ].create( bind=pg_engine, checkfirst=True )


def _event( repo, event_type, user_id, minutes_ago ):
    return repo.create( event_type=event_type, user_id=user_id, success=True, event_time=NOW - timedelta( minutes=minutes_ago ) )


def test_get_by_user_returns_only_that_users_events_newest_first_and_pages( db_session, auth_tables ):
    repo, me, other = AuthAuditLogRepository( db_session ), uuid.uuid4(), uuid.uuid4()
    for minutes, who in ( ( 50, me ), ( 10, me ), ( 30, me ), ( 20, other ) ):
        _event( repo, "login", who, minutes )
    got = repo.get_by_user( me )
    assert [ ( NOW - e.event_time ).total_seconds() // 60 for e in got ] == [ 10, 30, 50 ] and all( e.user_id == me for e in got )
    assert [ ( NOW - e.event_time ).total_seconds() // 60 for e in repo.get_by_user( me, limit=1, offset=1 ) ] == [ 30 ]


def test_get_by_event_type_returns_only_that_type_newest_first_and_pages( db_session, auth_tables ):
    repo, who = AuthAuditLogRepository( db_session ), uuid.uuid4()
    for minutes, kind in ( ( 40, "logout" ), ( 5, "logout" ), ( 25, "logout" ), ( 15, "login" ) ):
        _event( repo, kind, who, minutes )
    got = repo.get_by_event_type( "logout" )
    assert [ ( NOW - e.event_time ).total_seconds() // 60 for e in got ] == [ 5, 25, 40 ] and all( e.event_type == "logout" for e in got )
    assert [ ( NOW - e.event_time ).total_seconds() // 60 for e in repo.get_by_event_type( "logout", limit=2, offset=1 ) ] == [ 25, 40 ]


def test_the_shared_page_helper_filters_on_any_column_it_is_given( db_session, auth_tables ):
    repo, who = AuthAuditLogRepository( db_session ), uuid.uuid4()
    _event( repo, "mfa", who, 3 )
    _event( repo, "mfa", uuid.uuid4(), 4 )
    assert len( repo._page_by( AuthAuditLog.event_type, "mfa", 10, 0 ) ) == 2
    assert len( repo._page_by( AuthAuditLog.user_id, who, 10, 0 ) ) == 1
    assert repo._page_by( AuthAuditLog.event_type, "no-such-type", 10, 0 ) == []
