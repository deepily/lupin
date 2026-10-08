"""
The conftest server probe must not hide a refused test login as a skip.

A skipped suite reads green. With a test role present, a stale password has to fail the run.
"""

import pytest
from sqlalchemy.exc import OperationalError

import cosa.tests.unit.rest.db.repositories.conftest as lane_b
import tests.helpers.template_database as td


class _Orig( Exception ):
    pgcode = None


def _raising( message ):
    def factory( *args, **kwargs ): raise OperationalError( "stmt", { }, _Orig( message ) )
    return factory


def test_a_refused_test_login_fails_instead_of_skipping( monkeypatch ):
    monkeypatch.setattr( td, "uses_template", lambda: True )
    monkeypatch.setattr( lane_b, "create_engine", _raising( 'FATAL:  password authentication failed for user "lupin_test"' ) )
    with pytest.raises( pytest.fail.Exception, match="LUPIN_TEST_DB_PASSWORD" ):
        lane_b._server_reachable( "postgresql+psycopg2://x:y@h:1/postgres" )


def test_a_connection_failure_still_reads_as_unreachable( monkeypatch ):
    monkeypatch.setattr( td, "uses_template", lambda: True )
    monkeypatch.setattr( lane_b, "create_engine", _raising( "connection refused" ) )
    assert lane_b._server_reachable( "postgresql+psycopg2://x:y@h:1/postgres" ) is False


def test_without_a_test_role_a_refusal_keeps_the_old_skip( monkeypatch ):
    monkeypatch.setattr( td, "uses_template", lambda: False )
    monkeypatch.setattr( lane_b, "create_engine", _raising( 'FATAL:  password authentication failed for user "lupin_dev"' ) )
    assert lane_b._server_reachable( "postgresql+psycopg2://x:y@h:1/postgres" ) is False


def test_any_other_error_reads_as_unreachable( monkeypatch ):
    def factory( *args, **kwargs ): raise RuntimeError( "boom" )
    monkeypatch.setattr( lane_b, "create_engine", factory )
    assert lane_b._server_reachable( "postgresql+psycopg2://x:y@h:1/postgres" ) is False
