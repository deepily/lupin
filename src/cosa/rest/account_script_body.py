"""
The shared body of the two test-account scripts.

The scripts are create_admin_test_account.py and create_test_mock_user.py. Each names its own variables, roles and wording, and
supplies one hook for the step that makes its account different. This module does the rest. It reads the variables, checks the
password, then creates or updates the account in one session and commits.

It opens no connection of its own. The script hands in the database seams, so a test patches them on the script module.
"""

import os
import sys


def provision_test_account( email_var, password_var, roles, seams, finish_new, finish_existing, created_text, existing_text ):
    """
    Create the account named by the environment, or bring an existing one into shape.

    Requires:
        - email_var and password_var name environment variables
        - roles is the list of roles the account must hold
        - seams is a dict with get_db, user_repository, hash_password and validate_password_strength, all callables
        - finish_new( repo, user ) runs after create_user; finish_existing( repo, existing, updated ) runs after the password and
          roles are reset, takes the account and what update_roles returned, and returns the user to report
        - created_text and existing_text start the line printed after the commit

    Ensures:
        - returns 1 and prints the names of every unset variable, before any database is opened
        - returns 1 and prints the policy's reason, never the password, when the password is rejected, again before any database
        - a missing account is created with roles and the password hash, then finish_new runs; an existing account has its password
          hash and roles set, then finish_existing runs; the session commits once
        - prints "✓ <text>: <email> roles=<roles>" and never the password; returns 0
    """
    email    = os.environ.get( email_var )
    password = os.environ.get( password_var )

    missing = [ name for name, value in ( ( email_var, email ), ( password_var, password ) ) if not value ]
    if missing:
        print( f"ERROR: unset: {', '.join( missing )}", file=sys.stderr )
        return 1

    is_valid, why = seams[ "validate_password_strength" ]( password )
    if not is_valid:
        print( f"ERROR: supplied password rejected by the live policy: {why}", file=sys.stderr )
        return 1

    with seams[ "get_db" ]() as session:
        repo     = seams[ "user_repository" ]( session )
        existing = repo.get_by_email( email )

        if existing is None:
            user = repo.create_user( email=email, password_hash=seams[ "hash_password" ]( password ), roles=roles )
            finish_new( repo, user )
            text = created_text
        else:
            repo.update_password( existing.id, seams[ "hash_password" ]( password ) )
            user = finish_existing( repo, existing, repo.update_roles( existing.id, roles ) )
            text = existing_text
        session.commit()
        print( f"✓ {text}: {user.email} roles={user.roles}" )

    return 0
