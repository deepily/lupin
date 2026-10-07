"""
No integration or e2e test drops a table, a schema, or the shared test database.

Dropping and recreating the tables of the shared test database erases every grant on them.
The integration cleanup test did that on each run, so the app login lost its rights on all
but one table. Row-level cleanup (delete, truncate) keeps the grants.

The scan reads the tracked python files of both folders. A database a test creates for
itself and names in a throwaway constant may be dropped; nothing else may.
"""

import os
import re
import subprocess

import pytest

ROOT    = os.environ.get( "LUPIN_ROOT", os.getcwd() )
FOLDERS = ( "src/tests/integration", "src/tests/e2e_ui" )

_FORBIDDEN = (
    re.compile( r"drop_all\s*\(" ),
    re.compile( r"\bDROP\s+(TABLE|SCHEMA)\b", re.IGNORECASE ),
)
_DROP_DATABASE = re.compile( r"\bDROP\s+DATABASE\b", re.IGNORECASE )
_THROWAWAY     = "_THROWAWAY_DB"


def drops_found( text ):
    """The (line number, line) pairs of text that drop something the test venue must keep."""
    found = []
    for number, line in enumerate( text.splitlines(), start=1 ):
        if line.lstrip().startswith( "#" ): continue
        if any( pattern.search( line ) for pattern in _FORBIDDEN ):
            found.append( ( number, line.strip() ) )
        elif _DROP_DATABASE.search( line ) and _THROWAWAY not in line:
            found.append( ( number, line.strip() ) )
    return found


def _tracked_python_files():
    listing = subprocess.run( [ "git", "-C", ROOT, "ls-files", *FOLDERS ], capture_output=True, text=True, check=True )
    return [ name for name in listing.stdout.splitlines() if name.endswith( ".py" ) ]


def test_the_scan_finds_the_files_it_is_meant_to_read():
    names = _tracked_python_files()
    assert len( names ) > 100, f"only {len( names )} files under {FOLDERS}; the scan would pass over nothing"
    assert any( name.endswith( "src/tests/integration/test_conftest_clean_test_db.py" ) for name in names )
    assert any( name.endswith( "src/tests/e2e_ui/conftest.py" ) for name in names )


@pytest.mark.parametrize( "line", [
    "    Base.metadata.drop_all( bind=engine )",
    "Base.metadata.drop_all(engine)",
    "conn.execute( text( 'DROP TABLE users' ) )",
    "conn.execute( text( 'drop table users' ) )",
    "conn.execute( text( 'DROP SCHEMA public CASCADE' ) )",
    "conn.execute( text( 'DROP DATABASE lupin_db_test' ) )",
] )
def test_the_scan_recognises_each_kind_of_drop( line ):
    assert drops_found( line ) != [], f"{line!r} was not recognised as a drop"


@pytest.mark.parametrize( "line", [
    "conn.execute( text( f'DROP DATABASE IF EXISTS \"{_THROWAWAY_DB}\"' ) )",
    "    # Post-test cleanup: drop table + reset again",
    "params={ \"drop_table\": \"true\" }",
    "conn.execute( text( 'TRUNCATE TABLE jobs' ) )",
] )
def test_the_scan_leaves_a_throwaway_database_a_comment_and_a_truncate_alone( line ):
    assert drops_found( line ) == [], f"{line!r} was flagged"


def test_no_integration_or_e2e_test_drops_a_table_a_schema_or_the_test_database():
    offenders = []
    for name in _tracked_python_files():
        with open( os.path.join( ROOT, name ), encoding="utf-8" ) as handle:
            offenders += [ f"{name}:{number}: {line}" for number, line in drops_found( handle.read() ) ]
    assert offenders == [], "a drop erases the grants on the shared test database:\n" + "\n".join( offenders )
