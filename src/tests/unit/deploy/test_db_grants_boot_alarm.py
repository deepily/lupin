"""
The boot-time grants alarm: it names each gap, skips what it should, and never raises.

The engine is a stub that answers the check's two queries from a canned database, so no Postgres runs here.
The real query against Postgres is covered in tests/smoke/test_db_grants_real_postgres.py.
Venue: :7999 (unit, no database).
"""

import os

import pytest

from cosa.utils import db_grants as g

ROOT = os.environ[ "LUPIN_ROOT" ]


class Connection:
    def __init__( self, database, lines ): self.database, self.lines, self.asked = database, lines, []
    def exec_driver_sql( self, sql ):
        self.asked.append( sql )
        return [ ( self.database, ) ] if sql.startswith( "SELECT current_database" ) else [ ( line, ) for line in self.lines ]
    def __enter__( self ): return self
    def __exit__( self, *exc ): return False


class Engine:
    def __init__( self, database="lupin_db_test", lines=( "lupin_db_test|tables||27|", ), fail=None ):
        self.connection, self.disposed, self.fail = Connection( database, list( lines ) ), 0, fail
    def connect( self ):
        if self.fail: raise self.fail
        return self.connection
    def dispose( self ): self.disposed += 1


@pytest.fixture( autouse=True )
def local_deployment( monkeypatch ):
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "placeholder" )
    monkeypatch.delenv( "LUPIN_CLOUD_BACKED" )


def test_a_clean_database_prints_one_summary_line_and_returns_none( capsys ):
    engine = Engine()
    assert g.emit_startup_grants_alarm( engine_factory=lambda: engine ) is None
    out = capsys.readouterr()
    assert out.out == "[db-grants] lupin_db_test: 27 tables, 3 roles, 0 problems\n" and out.err == ""
    assert engine.disposed == 1


def test_a_gap_writes_a_critical_block_naming_it_and_the_repair_command_to_stderr( capsys ):
    engine = Engine( lines=( "lupin_db_test|tables||27|", "lupin_db_test|missing|lupin_test|widgets|DELETE" ) )
    report = g.emit_startup_grants_alarm( engine_factory=lambda: engine )
    err = capsys.readouterr().err
    assert report[ "ok" ] is False
    assert "CRITICAL" in err and "  lupin_test cannot DELETE widgets" in err
    assert "--grants-only --apply" in err and "lupin-postgres" in err


def test_a_database_the_matrix_does_not_name_is_skipped_after_one_query( capsys ):
    engine = Engine( database="lupin_db_scratch" )
    assert g.emit_startup_grants_alarm( debug=True, engine_factory=lambda: engine ) is None
    assert "not one the matrix describes" in capsys.readouterr().out
    assert len( engine.connection.asked ) == 1


def test_a_cloud_backed_deployment_is_skipped_and_never_connects( monkeypatch, capsys ):
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "1" )
    def factory(): raise AssertionError( "a cloud-backed boot opened a connection" )
    assert g.emit_startup_grants_alarm( debug=True, engine_factory=factory ) is None
    assert "cloud-backed" in capsys.readouterr().out


def test_a_quiet_skip_prints_nothing( capsys ):
    assert g.emit_startup_grants_alarm( engine_factory=lambda: Engine( database="other" ) ) is None
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize( "make", [
    lambda: Engine( fail=RuntimeError( "connection refused" ) ),
    lambda: Engine( lines=( "garbage", ) ),
    lambda: Engine( lines=( "lupin_db_dev|tables||3|", ) ),
] )
def test_a_failing_check_never_raises_and_says_so_on_stderr( make, capsys ):
    engine = make()
    assert g.emit_startup_grants_alarm( engine_factory=lambda: engine ) is None
    assert "WARNING: grants check failed; continuing boot" in capsys.readouterr().err
    assert engine.disposed == 1, "the engine was left open"


def test_a_factory_that_raises_never_raises_out_of_the_alarm( capsys ):
    def factory(): raise OSError( "no url" )
    assert g.emit_startup_grants_alarm( engine_factory=factory ) is None
    assert "WARNING" in capsys.readouterr().err


def test_without_a_factory_the_alarm_builds_the_engine_from_the_apps_own_url( monkeypatch ):
    import sqlalchemy
    from cosa.rest.db import auto_migrate
    made = []
    monkeypatch.setattr( auto_migrate, "resolve_database_url", lambda url: made.append( ( "resolved", url ) ) or "postgresql://u@h/d" )
    monkeypatch.setattr( sqlalchemy, "create_engine", lambda url: made.append( ( "engine", url ) ) or Engine() )
    assert g.emit_startup_grants_alarm() is None
    assert made == [ ( "resolved", None ), ( "engine", "postgresql://u@h/d" ) ]


def test_the_runner_returns_the_first_column_of_each_row():
    connection = Connection( "lupin_db_test", [ "a|b|c|d|e", "f|g|h|i|j" ] )
    run = g.query_runner( connection )
    assert run( "SELECT current_database();" ) == [ "lupin_db_test" ]
    assert run( "SELECT 2;" ) == [ "a|b|c|d|e", "f|g|h|i|j" ]
    assert connection.asked == [ "SELECT current_database();", "SELECT 2;" ]


def test_main_runs_the_grants_alarm_after_the_migrations_and_the_drift_alarm():
    with open( os.path.join( ROOT, "src/lupin_app/main.py" ) ) as handle: text = handle.read()
    assert text.count( "emit_startup_grants_alarm( debug=app_debug )" ) == 1
    assert text.index( "run_migrations_to_head( debug=app_debug )" ) < text.index( "emit_startup_drift_alarm( debug=app_debug )" ) \
        < text.index( "emit_startup_grants_alarm( debug=app_debug )" )
