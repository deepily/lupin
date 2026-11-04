"""
The flag that removes the template database, and the places the template is left alone.

--drop-template runs one SQL block and nothing else: it unmarks the template, drops it and stops. The
cutover's rollback leaves the template alone, since the template is a test aid. A re-run of the provisioner
never takes the template mark off, so a test that clones during a repair is not refused.

Venue: :7999-eligible. No database; the SQL file is read as text and the psql command is a recorder.
"""

import io
import re

import pytest

from cosa.utils import db_roles
from test_db_roles_provisioner import APP, HOST, SQL_PATH, TEST, Recorder, _argv, _blocks, files  # noqa: F401

TEMPLATE = "lupin_template_vector"


def _sql():
    return open( SQL_PATH ).read()


def test_the_stdin_for_a_drop_carries_one_flag_the_sql_and_no_password():
    text = db_roles.build_psql_stdin( APP, HOST, TEST, "SELECT 1;\n", drop_template=True )
    assert text.splitlines() == [ "\\set drop_template 1", "SELECT 1;" ]


def test_a_drop_dry_run_prints_the_plan_and_runs_nothing( files ):
    out, run = io.StringIO(), Recorder()
    assert db_roles.main( _argv( files, "--drop-template" ), run_fn=run, out=out ) == 0
    assert run.calls == [] and "DRY RUN" in out.getvalue() and "\\set drop_template 1" in out.getvalue()


def test_a_drop_apply_sends_the_flag_and_the_sql_and_never_a_password( files ):
    run = Recorder()
    assert db_roles.main( _argv( files, "--apply", "--drop-template" ), run_fn=run, out=io.StringIO() ) == 0
    ( command, stdin, _text ), = run.calls
    assert stdin.splitlines()[ 0 ] == "\\set drop_template 1" and "SELECT 2;" in stdin
    assert not any( secret in stdin + " ".join( command ) for secret in ( APP, HOST, TEST ) )


def test_a_drop_runs_with_no_password_file_options_at_all( files ):
    argv = [ "--psql", "psql -U admin -d lupin_db_dev", "--sql", files[ "sql" ], "--apply", "--drop-template" ]
    run  = Recorder( returncode=4 )
    assert db_roles.main( argv, run_fn=run, out=io.StringIO() ) == 4
    assert run.calls[ 0 ][ 1 ].startswith( "\\set drop_template 1\n" )


@pytest.mark.parametrize( "other", [ "--rollback", "--reassign", "--grants-only", "--check" ] )
def test_a_drop_cannot_be_combined_with_another_direction( files, other ):
    with pytest.raises( SystemExit ):
        db_roles.main( _argv( files, "--apply", "--drop-template", other ), run_fn=Recorder(), out=io.StringIO() )


def test_the_drop_block_unmarks_then_drops_then_stops_and_comes_before_everything_else():
    blocks = _blocks( _sql(), "\\if :{?drop_template}" )
    assert len( blocks ) == 1
    joined = " ".join( blocks[ 0 ] )
    assert joined.index( "IS_TEMPLATE false" ) < joined.index( "DROP DATABASE IF EXISTS lupin_template_vector" ) < joined.index( "\\quit" )
    assert _sql().index( "\\if :{?drop_template}" ) < _sql().index( "\\if :{?rollback}" )


def test_the_rollback_blocks_never_mention_the_template():
    for block in _blocks( _sql(), "\\if :{?rollback}" ): assert TEMPLATE not in " ".join( block )


def test_a_rerun_never_takes_the_template_mark_off_outside_the_drop_block():
    """The only statement that unmarks the template is the one inside the drop block."""
    sql   = _sql()
    start = sql.index( "\\if :{?drop_template}" )
    end   = sql.index( "\\endif", start )
    outside = sql[ :start ] + sql[ end: ]
    code = "\n".join( ln for ln in outside.splitlines() if not ln.lstrip().startswith( "--" ) )
    values = re.findall( r"IS_TEMPLATE\s*=?\s*(\w+)", code, re.IGNORECASE )
    assert values, "no IS_TEMPLATE token found outside the drop block, so this test would pass on nothing"
    assert all( v.lower() == "true" for v in values ), f"a re-run unmarks the template, so a clone can be refused during it: {values}"
    assert f"CREATE DATABASE {TEMPLATE} IS_TEMPLATE true" in code
