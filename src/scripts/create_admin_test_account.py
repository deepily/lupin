#!/usr/bin/env python3
"""
Create (or promote) the dedicated admin test account used by admin-only smoke tests.

Why a dedicated account: the shared LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* tester holds
roles ["user"], and several tests exist precisely to prove a NON-admin is refused
(test_regular_user_wildcard_blocked, test_regular_user_other_user_blocked). Promoting
that shared account would buy a few admin greens by making those tests prove nothing.

Credentials come from the environment — never hardcoded, never printed back:

    export LUPIN_TEST_ADMIN_EMAIL="lupin.test.admin@lupin.deepily.ai"
    export LUPIN_TEST_ADMIN_PASSWORD="..."
    python src/scripts/create_admin_test_account.py

The script is idempotent: an existing account is promoted in place (and its password
reset to the supplied one) rather than duplicated.

Warning: the dev database lives inside the Docker network, so run this inside the container:

    docker exec -e LUPIN_TEST_ADMIN_EMAIL=... -e LUPIN_TEST_ADMIN_PASSWORD=... \
        lupin-rest-dev python /var/lupin/src/scripts/create_admin_test_account.py
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

ADMIN_ROLES = [ "user", "admin" ]


def _finish_new( repo, user ):
    """Ensures: the new account is marked is_protected, so test-database cleanups keep it."""
    repo.update( user.id, is_protected=True )


def _finish_existing( repo, existing, updated ):
    """Ensures: the promoted account is marked is_protected; returns the updated user."""
    repo.update( existing.id, is_protected=True )
    return updated


def main():
    """
    Create or promote the environment's admin test account.

    Requires:
        - LUPIN_TEST_ADMIN_EMAIL and LUPIN_TEST_ADMIN_PASSWORD are both set
        - the password satisfies the live password policy
        - the auth database is reachable

    Ensures:
        - the named account exists, is active, and holds roles ["user", "admin"]
        - the account's password is the one supplied
        - the account is marked is_protected, so the test-database cleanups that run
          "DELETE FROM users WHERE NOT is_protected" leave it in place
        - reports the email and roles; never echoes the password

    Raises:
        - SystemExit(1) if either variable is unset or the password is rejected
    """
    seams = { "get_db": get_db, "user_repository": UserRepository, "hash_password": hash_password, "validate_password_strength": validate_password_strength }
    return provision_test_account( "LUPIN_TEST_ADMIN_EMAIL", "LUPIN_TEST_ADMIN_PASSWORD", ADMIN_ROLES, seams, _finish_new, _finish_existing,
                                   "created admin test account", "promoted existing account" )


if __name__ == "__main__":
    sys.exit( main() )
