"""
No test file makes its own database: they go through tests.helpers.template_database.

A site that reverts to a bare create-database statement still passes in plain mode. The helper issues
the same statement there. It fails only in keyed mode, on a host this suite does not run on.
This guard reads the files, so a reverted site fails here in any mode.

The population is every tracked .py file under the two test roots, counted before the check.
"""

import os
import re
import subprocess

ROOT      = os.environ[ "LUPIN_ROOT" ]
PATTERN   = re.compile( "create" + r"\s+" + "database", re.IGNORECASE )
ALLOWED   = (
    "src/cosa/tests/unit/scripts_tests/test_check_schema_parity.py",
    "src/tests/helpers/template_database.py",
    "src/tests/smoke/test_db_roles_rollback_real_postgres.py",
    "src/tests/smoke/test_db_template_provisioning_real_postgres.py",
    "src/tests/smoke/test_template_database_vector_real_postgres.py",
    "src/tests/unit/deploy/test_db_roles_drop_template.py",
    "src/tests/unit/test_template_database_helper.py",
)


def _population():
    listed = subprocess.run( [ "git", "ls-files", "src/tests", "src/cosa/tests" ], cwd=ROOT, capture_output=True, text=True, check=True ).stdout.split()
    return [ path for path in listed if path.endswith( ".py" ) ]


def _offenders( population, read ):
    return sorted( path for path in population if path not in ALLOWED and PATTERN.search( read( path ) ) )


def _read( path ):
    with open( os.path.join( ROOT, path ), encoding="utf-8", errors="replace" ) as handle: return handle.read()


def test_the_population_is_not_empty():
    assert len( _population() ) > 1000, "git ls-files returned too few test files, so the guard below would pass on nothing"


def test_every_allowed_file_exists_and_still_needs_its_allowance():
    population = _population()
    for path in ALLOWED:
        assert path in population, f"{path} is on the allow-list but is not a tracked test file"
        assert PATTERN.search( _read( path ) ), f"{path} no longer makes a database itself, so drop it from the allow-list"


def test_no_other_test_file_makes_its_own_database():
    assert _offenders( _population(), _read ) == [ ]


def test_the_check_names_a_reverted_site():
    population = _population()
    found = _offenders( population, lambda path: "CREATE" + " DATABASE x" if path.endswith( "test_acks_are_not_conversations.py" ) else "" )
    assert found == [ "src/tests/smoke/test_acks_are_not_conversations.py" ]
