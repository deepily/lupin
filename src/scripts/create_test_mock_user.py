#!/usr/bin/env python3
"""
Create (or reset) the shared test-mock-jobs login: the plain, non-admin tester account.

Why a separate script: `create_admin_test_account.py` always grants ["user", "admin"]. This
account must stay non-admin, because tests exist to prove a regular user is refused. The VM's
daily reuse-vector refresh logs in as this account. The VM database holds no copy of the dev
row that `seed_test_companions.py` would otherwise carry across.

Credentials come from the environment, the same two variables the tests and the refresh read.
They are never hardcoded and never printed back:

    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="..."
    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="..."
    python src/scripts/create_test_mock_user.py

The script is idempotent: an existing account has its password reset, its roles set to
["user"], and is activated and email-verified, rather than duplicated.

Warning: the database lives inside the Docker network, so run this inside the container:

    docker exec -e LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL=... -e LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=... \
        <app-container> python /var/lupin/src/scripts/create_test_mock_user.py
"""

import os
import sys

# Bootstrap: this runs before cosa is importable
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from cosa.rest.account_script_body     import provision_test_account
from cosa.rest.db.database             import get_db
from cosa.rest.db.repositories         import UserRepository
from cosa.rest.password_service        import hash_password, validate_password_strength

USER_ROLES = [ "user" ]


def _finish_new( repo, user ):
    """Ensures: the new account is marked email-verified."""
    repo.mark_email_verified( user.id )


def _finish_existing( repo, existing, updated ):
    """Ensures: the account is activated and verified; returns the verified user."""
    repo.activate( existing.id )
    return repo.mark_email_verified( existing.id )


def main():
    """
    Create or reset the environment's test-mock-jobs account.

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD are both set
        - the password satisfies the live password policy
        - the auth database is reachable

    Ensures:
        - the named account exists, is active, is email-verified, and holds roles ["user"] only
        - the account's password is the one supplied
        - reports the email and roles; never echoes the password

    Raises:
        - SystemExit(1) if either variable is unset or the password is rejected
    """
    seams = { "get_db": get_db, "user_repository": UserRepository, "hash_password": hash_password, "validate_password_strength": validate_password_strength }
    return provision_test_account( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", USER_ROLES, seams, _finish_new, _finish_existing,
                                   "created test-mock-jobs account", "reset existing account" )


if __name__ == "__main__":
    sys.exit( main() )
