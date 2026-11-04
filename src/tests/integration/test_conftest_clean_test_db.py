"""
Integration tests for the `clean_test_db` fixture itself.

Regression coverage for the 2026-04-14 PQW 502/401 incident: the fixture
used to drop+recreate the users table without restoring the companion
seed, which broke service-account logins (Peer Queue Watcher, cosa-voice
MCP key-owner lookup, etc.) the moment any user-management test ran.

These tests confirm that:
  - companion users are present after every clean_test_db invocation
  - non-companion test data introduced before the fixture runs is wiped
  - the safety assertion's expected-row-count tracks COMPANION_EMAILS

Lives in src/tests/integration/ because the fixture exercises the live
lupin_db_test database; no unit-tier substitute exists.
"""

import sys
import pathlib

import pytest
from sqlalchemy import text

# COMPANION_EMAILS lives in src/scripts/, which conftest.py adds to
# sys.path inside clean_test_db. Mirror that here for direct access.
import cosa.utils.util as cu
_scripts_dir = pathlib.Path( cu.get_project_root() ) / "src" / "scripts"
if str( _scripts_dir ) not in sys.path:
    sys.path.insert( 0, str( _scripts_dir ) )
from seed_test_companions import COMPANION_EMAILS


def _query_user_emails():
    """Return the set of emails currently in the test DB's users table."""
    from cosa.rest.db import database as db_module
    engine = db_module.engine
    with engine.connect() as conn:
        rows = conn.execute( text( "SELECT email FROM users ORDER BY email" ) ).fetchall()
    return { r[ 0 ] for r in rows }


def test_clean_test_db_preserves_companions( clean_test_db ):
    """
    After the fixture runs, every companion email must be present.

    Asserts the regression: pre-fix the users table was empty post-cleanup,
    which broke any subsequent service-account auth. Post-fix the seed is
    restored in the same fixture invocation.
    """
    emails = _query_user_emails()
    missing = set( COMPANION_EMAILS ) - emails
    assert not missing, f"clean_test_db dropped companion seeds: missing={missing}"


STRAY_EMAIL = "should-not-survive@test.local"


@pytest.fixture
def a_stray_user():
    """
    Insert one unprotected, non-companion user and yield its email.

    Requested BEFORE clean_test_db in the test's argument list, so pytest builds this fixture
    first and the real cleanup then runs over the stray user. The insert is read back, so a
    stray user that never went in cannot make the test pass.
    """
    from cosa.rest.db import database as db_module
    with db_module.engine.begin() as conn:
        conn.execute( text(
            "INSERT INTO users ( id, email, password_hash, is_active, email_verified, roles ) "
            "VALUES ( gen_random_uuid(), :email, 'x', true, true, '[\"user\"]'::jsonb ) "
            "ON CONFLICT ( email ) DO NOTHING"
        ), { "email": STRAY_EMAIL } )
    assert STRAY_EMAIL in _query_user_emails(), "test setup: the stray user did not insert"
    yield STRAY_EMAIL


def test_clean_test_db_removes_prior_test_users( a_stray_user, clean_test_db ):
    """
    The real clean_test_db fixture wipes a stray user and leaves every companion in place.

    a_stray_user is built first, so the fixture's own cleanup runs over it. No copy of the
    cleanup statements lives here: a change to the fixture changes what this test measures.
    No table is dropped, so every grant on the test database survives.
    """
    after = _query_user_emails()
    assert a_stray_user not in after, "the stray user survived clean_test_db"
    assert set( COMPANION_EMAILS ).issubset( after ), \
        f"companions missing after clean_test_db: {set( COMPANION_EMAILS ) - after}"


def test_companion_emails_constant_nonempty():
    """Sanity check: the safety assertion in clean_test_db relies on this list."""
    assert isinstance( COMPANION_EMAILS, list )
    assert len( COMPANION_EMAILS ) >= 1
    # Service account that PQW + cosa-voice MCP both depend on
    assert "interactive.job.tester@lupin.deepily.ai" in COMPANION_EMAILS
