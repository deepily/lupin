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


def test_clean_test_db_removes_prior_test_users( clean_test_db ):
    """
    Insert a fake test user, re-trigger clean_test_db semantics by re-running
    drop+recreate+reseed, then confirm only the companions remain (the fake
    user got wiped). This validates that the fix doesn't preserve random
    leftovers — only the explicit companion seed.
    """
    from cosa.rest.db import database as db_module
    from cosa.rest.postgres_models import Base
    engine = db_module.engine

    # Insert a non-companion user
    fake_email = "should-not-survive@test.local"
    with engine.begin() as conn:
        conn.execute( text(
            "INSERT INTO users ( id, email, password_hash, is_active, email_verified, roles ) "
            "VALUES ( gen_random_uuid(), :email, 'x', true, true, '[\"user\"]'::jsonb )"
        ), { "email": fake_email } )

    assert fake_email in _query_user_emails(), "test setup: fake user did not insert"

    # Re-trigger the fixture's destructive cycle by manually replaying its
    # body (cannot re-invoke the fixture mid-test cleanly).
    Base.metadata.drop_all( bind=engine )
    Base.metadata.create_all( bind=engine )
    from seed_test_companions import seed_if_missing
    seed_if_missing()

    after = _query_user_emails()
    assert fake_email not in after, "fake user survived clean_test_db cycle"
    assert set( COMPANION_EMAILS ).issubset( after ), \
        f"companions missing after second cycle: {set(COMPANION_EMAILS) - after}"


def test_companion_emails_constant_nonempty():
    """Sanity check: the safety assertion in clean_test_db relies on this list."""
    assert isinstance( COMPANION_EMAILS, list )
    assert len( COMPANION_EMAILS ) >= 1
    # Service account that PQW + cosa-voice MCP both depend on
    assert "interactive.job.tester@lupin.deepily.ai" in COMPANION_EMAILS
