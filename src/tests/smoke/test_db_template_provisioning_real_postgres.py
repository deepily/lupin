"""
The provisioner makes, repairs, reports and removes the template database.

The real provisioner and the real check run against a throwaway Postgres made for the test. The template,
lupin_template_vector, is what a test that creates a database clones, so the extension needs no superuser.

Four things are pinned. The provisioner makes the template with the extension, as a template that refuses
connections, and repeating it changes nothing. The grants-only run makes a missing template without a
password file. The check reports a missing template and one that accepts connections, and stays quiet
when it is right. The rollback removes it.

Reuses the throwaway harness of test_db_roles_rollback_real_postgres.py.
Venue: host-side, docker required. The merge gate's containers have no docker socket, so there it skips.
"""

import pytest

from test_db_grants_real_postgres import _check
from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    SUPERUSER, _provision, _psql, needs_docker, stocked, throwaway,
)
from test_template_database_vector_real_postgres import _as, _ok

TEMPLATE = "lupin_template_vector"
FLAGS_SQL = f"SELECT datistemplate || '|' || datallowconn FROM pg_database WHERE datname = '{TEMPLATE}';\n"
COUNT_SQL = f"SELECT count(*) FROM pg_database WHERE datname = '{TEMPLATE}';\n"


def _flags( box ):
    return _psql( box[ "name" ], "postgres", FLAGS_SQL ).strip()


def _clone_has_the_extension( box, name ):
    """Clone the template as lupin_test and read the extension in the clone; drops the clone."""
    made = _as( box, "lupin_test", "postgres", f"CREATE DATABASE {name} TEMPLATE {TEMPLATE};\n" )
    assert made[ 0 ] == 0, f"the clone was refused: {made[ 2 ]}"
    try:
        return _ok( box, "lupin_test", name, "SELECT extname FROM pg_extension WHERE extname = 'vector';\n" )
    finally:
        _psql( box[ "name" ], "postgres", f"DROP DATABASE IF EXISTS {name};\n" )


@needs_docker
def test_the_provisioner_makes_the_template_with_the_extension_and_repeating_it_changes_nothing( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    assert _flags( stocked ) == "true|false"
    assert _clone_has_the_extension( stocked, "c1" ) == "vector"
    _provision( stocked, tmp_path )
    assert _flags( stocked ) == "true|false", "a second run left the template open or unmarked"
    assert _psql( stocked[ "name" ], "postgres", COUNT_SQL ).strip() == "1"
    assert _clone_has_the_extension( stocked, "c2" ) == "vector"


@needs_docker
def test_the_grants_only_run_makes_a_missing_template_without_a_password_file( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _psql( stocked[ "name" ], "postgres", f"ALTER DATABASE {TEMPLATE} WITH IS_TEMPLATE false;\nDROP DATABASE {TEMPLATE};\n" )
    assert _psql( stocked[ "name" ], "postgres", COUNT_SQL ).strip() == "0"
    _provision( stocked, tmp_path, "--grants-only" )
    assert _flags( stocked ) == "true|false"
    assert _clone_has_the_extension( stocked, "c3" ) == "vector"


@needs_docker
def test_the_grants_only_run_repairs_a_template_left_open_and_unmarked( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _psql( stocked[ "name" ], "postgres", f"ALTER DATABASE {TEMPLATE} WITH IS_TEMPLATE false ALLOW_CONNECTIONS true;\n" )
    assert _flags( stocked ) == "false|true"
    _provision( stocked, tmp_path, "--grants-only" )
    assert _flags( stocked ) == "true|false"


@needs_docker
def test_the_check_is_quiet_about_a_right_template_and_reports_a_missing_or_open_one( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    clean = _check( stocked )
    assert clean.returncode == 0 and TEMPLATE not in clean.stdout, clean.stdout + clean.stderr

    _psql( stocked[ "name" ], "postgres", f"ALTER DATABASE {TEMPLATE} WITH ALLOW_CONNECTIONS true;\n" )
    opened = _check( stocked )
    assert opened.returncode == 1 and f"{TEMPLATE}: 1 problems" in opened.stdout.splitlines(), opened.stdout
    assert f"  {TEMPLATE} accepts connections, so a clone can fail while someone is connected to it" in opened.stdout.splitlines()

    _psql( stocked[ "name" ], "postgres", f"ALTER DATABASE {TEMPLATE} WITH IS_TEMPLATE false;\nDROP DATABASE {TEMPLATE};\n" )
    missing = _check( stocked )
    assert missing.returncode == 1 and f"{TEMPLATE}: 1 problems" in missing.stdout.splitlines(), missing.stdout
    assert "does not exist" in missing.stdout and missing.stdout.splitlines()[ -1 ].startswith( "remedy:" )


@needs_docker
def test_the_check_run_by_a_plain_login_still_sees_the_template( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _psql( stocked[ "name" ], "postgres", f"ALTER DATABASE {TEMPLATE} WITH IS_TEMPLATE false;\nDROP DATABASE {TEMPLATE};\n" )
    plain = _check( stocked, "lupin_db_test", "lupin_test", "--database", "lupin_db_test" )
    assert plain.returncode == 1 and f"{TEMPLATE}: 1 problems" in plain.stdout.splitlines(), plain.stdout + plain.stderr


@needs_docker
def test_the_rollback_removes_the_template( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    assert _psql( stocked[ "name" ], "postgres", COUNT_SQL ).strip() == "1"
    _provision( stocked, tmp_path, "--rollback" )
    assert _psql( stocked[ "name" ], "postgres", COUNT_SQL ).strip() == "0"
    _provision( stocked, tmp_path, "--rollback" )   # a second rollback finds nothing and succeeds
    assert _psql( stocked[ "name" ], "postgres", COUNT_SQL ).strip() == "0"
