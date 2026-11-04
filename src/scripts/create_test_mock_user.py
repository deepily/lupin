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

from cosa.rest.db.database             import get_db
from cosa.rest.db.repositories         import UserRepository
from cosa.rest.password_service        import hash_password, validate_password_strength

USER_ROLES = [ "user" ]


def main():
    """
    Create or reset the test-mock-jobs account named by the environment.

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
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    missing = [ name for name, value in (
        ( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL",    email    ),
        ( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", password ),
    ) if not value ]
    if missing:
        print( f"ERROR: unset: {', '.join( missing )}", file=sys.stderr )
        return 1

    is_valid, why = validate_password_strength( password )
    if not is_valid:
        print( f"ERROR: supplied password rejected by the live policy: {why}", file=sys.stderr )
        return 1

    with get_db() as session:
        user_repo = UserRepository( session )
        existing  = user_repo.get_by_email( email )

        if existing is None:
            user = user_repo.create_user(
                email         = email,
                password_hash = hash_password( password ),
                roles         = USER_ROLES
            )
            user_repo.mark_email_verified( user.id )
            session.commit()
            print( f"✓ created test-mock-jobs account: {user.email} roles={user.roles}" )
        else:
            user_repo.update_password( existing.id, hash_password( password ) )
            user_repo.update_roles( existing.id, USER_ROLES )
            user_repo.activate( existing.id )
            user = user_repo.mark_email_verified( existing.id )
            session.commit()
            print( f"✓ reset existing account: {user.email} roles={user.roles}" )

    return 0


if __name__ == "__main__":
    sys.exit( main() )
