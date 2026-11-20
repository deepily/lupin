"""
The repository writes rule_agreement to the row, and a reader gets it back.

The other repository tests mock the session, so a repository that dropped the argument would stay green.
These write through log_shadow and log_decision into the real ProxyDecision table, built in in-memory SQLite,
then read the column back in a fresh session. The migration is not applied to any shared database, and none is touched.
The SQLite stand-in renders JSONB as JSON and nothing else about the table changes.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository
from cosa.rest.postgres_models import ProxyDecision


@compiles( JSONB, "sqlite" )
def _jsonb_as_json( element, compiler, **kw ):
    return "JSON"


_ROW = dict( notification_id="n-1", domain="swe", category="deployment", question="deploy?", sender_id="lead" )


@pytest.fixture
def factory():
    engine = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    ProxyDecision.__table__.create( engine )
    yield sessionmaker( bind=engine )
    engine.dispose()


def _write_and_read_back( factory, method, **kwargs ):
    with factory() as session:
        row_id = getattr( ProxyDecisionRepository( session ), method )( **_ROW, **kwargs ).id
        session.commit()
    with factory() as fresh:
        return fresh.get( ProxyDecision, row_id )


@pytest.mark.parametrize( "value", [ True, False, None ] )
def test_log_decision_stores_the_rule_agreement_it_is_given( factory, value ):
    row = _write_and_read_back( factory, "log_decision", action="act", decision_value="approved", rule_agreement=value )
    assert row.rule_agreement is value
    assert row.action == "act" and row.decision_value == "approved"


@pytest.mark.parametrize( "value", [ True, False, None ] )
def test_log_shadow_stores_the_rule_agreement_it_is_given( factory, value ):
    row = _write_and_read_back( factory, "log_shadow", rule_agreement=value )
    assert row.rule_agreement is value
    assert row.action == "shadow" and row.decision_value is None


def test_a_row_written_without_the_argument_reads_back_null( factory ):
    assert _write_and_read_back( factory, "log_decision", action="suggest" ).rule_agreement is None
    assert _write_and_read_back( factory, "log_shadow" ).rule_agreement is None


def test_the_column_is_the_only_one_the_two_values_differ_on( factory ):
    approved = _write_and_read_back( factory, "log_decision", action="act", rule_agreement=True )
    declined = _write_and_read_back( factory, "log_decision", action="act", rule_agreement=False )
    assert ( approved.rule_agreement, declined.rule_agreement ) == ( True, False )
    assert approved.action == declined.action and approved.category == declined.category
