#!/usr/bin/env python3
"""
Create (or promote) the dedicated ADMIN test account used by admin-only smoke tests.

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

⚠️ The dev database lives inside the Docker network, so run this INSIDE the container:

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

from cosa.rest.db.database             import get_db
from cosa.rest.db.repositories         import UserRepository
from cosa.rest.password_service        import hash_password, validate_password_strength

ADMIN_ROLES = [ "user", "admin" ]


def main():
    """
    Create or promote the admin test account named by the environment.

    Requires:
        - LUPIN_TEST_ADMIN_EMAIL and LUPIN_TEST_ADMIN_PASSWORD are both set
        - the password satisfies the live password policy
        - the auth database is reachable

    Ensures:
        - the named account exists, is active, and holds roles ["user", "admin"]
        - the account's password is the one supplied
        - reports the email and roles; never echoes the password

    Raises:
        - SystemExit(1) if either variable is unset or the password is rejected
    """
    email    = os.environ.get( "LUPIN_TEST_ADMIN_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_ADMIN_PASSWORD" )

    missing = [ name for name, value in (
        ( "LUPIN_TEST_ADMIN_EMAIL",    email    ),
        ( "LUPIN_TEST_ADMIN_PASSWORD", password ),
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
                roles         = ADMIN_ROLES
            )
            session.commit()
            print( f"✓ created admin test account: {user.email} roles={user.roles}" )
        else:
            user_repo.update_password( existing.id, hash_password( password ) )
            user = user_repo.update_roles( existing.id, ADMIN_ROLES )
            session.commit()
            print( f"✓ promoted existing account: {user.email} roles={user.roles}" )

    return 0


if __name__ == "__main__":
    sys.exit( main() )
