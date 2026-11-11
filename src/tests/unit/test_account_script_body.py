"""
Tests for cosa.rest.account_script_body, the shared body of the two test-account scripts.

No database is opened and no real password is used. The seams are recording fakes. The credentials are obvious fakes
assembled from parts. The two scripts' own tests keep covering their hooks.
"""

import pytest

from cosa.rest import account_script_body as body

EMAIL_VAR = "FAKE_ACCOUNT_EMAIL"
PW_VAR    = "FAKE_ACCOUNT_PASSWORD"
EMAIL     = "fake.account@example.invalid"
PW        = "not" + "-a-real-" + "secret"
HASH      = "hash-of-" + "the-fake"


class User:
    """What the body reads off a repository result."""
    def __init__( self, email, roles, uid ):
        self.email, self.roles, self.id = email, roles, uid


class Repo:
    """Recording stand-in for UserRepository; `existing` is the create-or-update switch."""
    def __init__( self, existing, calls ):
        self.existing, self.calls = existing, calls
    def get_by_email( self, email ):
        self.calls.append( ( "get_by_email", email ) )
        return self.existing
    def create_user( self, email, password_hash, roles ):
        self.calls.append( ( "create_user", email, password_hash, tuple( roles ) ) )
        return User( email, list( roles ), 5 )
    def update_password( self, uid, password_hash ): self.calls.append( ( "update_password", uid, password_hash ) )
    def update_roles( self, uid, roles ):
        self.calls.append( ( "update_roles", uid, tuple( roles ) ) )
        return User( EMAIL, list( roles ), uid )


class Session:
    def __init__( self ): self.commits = 0
    def commit( self ): self.commits += 1
    def __enter__( self ): return self
    def __exit__( self, *exc ): return False


def run( monkeypatch, existing=None, valid=( True, "" ), set_env=True, opened=None ):
    """Ensures: returns ( exit code, calls, session ) from one run over the fakes."""
    calls, session = [], Session()
    if set_env:
        monkeypatch.setenv( EMAIL_VAR, EMAIL )
        monkeypatch.setenv( PW_VAR, PW )
    def get_db():
        if opened is not None: opened.append( 1 )
        return session
    seams  = { "get_db": get_db, "user_repository": lambda s: Repo( existing, calls ), "hash_password": lambda pw: HASH, "validate_password_strength": lambda pw: valid }
    finish_new      = lambda repo, user: calls.append( ( "finish_new", user.id ) )
    finish_existing = lambda repo, old, updated: calls.append( ( "finish_existing", old.id, updated.id ) ) or updated
    code = body.provision_test_account( EMAIL_VAR, PW_VAR, [ "user" ], seams, finish_new, finish_existing, "made it", "fixed it" )
    return code, calls, session


@pytest.mark.parametrize( "unset", [ [ EMAIL_VAR ], [ PW_VAR ], [ EMAIL_VAR, PW_VAR ] ] )
def test_every_unset_variable_is_named_and_no_database_is_opened( monkeypatch, capsys, unset ):
    opened = []
    for name in unset: monkeypatch.delenv( name, raising=False )
    monkeypatch.setenv( EMAIL_VAR, EMAIL ) if EMAIL_VAR not in unset else None
    monkeypatch.setenv( PW_VAR, PW ) if PW_VAR not in unset else None
    code, calls, _ = run( monkeypatch, set_env=False, opened=opened )
    err = capsys.readouterr().err
    assert code == 1 and all( name in err for name in unset ) and opened == [] and calls == []


def test_a_rejected_password_gives_the_reason_never_the_password_and_opens_no_database( monkeypatch, capsys ):
    opened = []
    code, calls, _ = run( monkeypatch, valid=( False, "too short" ), opened=opened )
    seen = capsys.readouterr()
    assert code == 1 and "too short" in seen.err and PW not in seen.out + seen.err and opened == [] and calls == []


def test_a_missing_account_is_created_then_finished_and_committed( monkeypatch, capsys ):
    code, calls, session = run( monkeypatch )
    assert code == 0 and session.commits == 1
    assert calls == [ ( "get_by_email", EMAIL ), ( "create_user", EMAIL, HASH, ( "user", ) ), ( "finish_new", 5 ) ]
    seen = capsys.readouterr().out
    assert seen == f"✓ made it: {EMAIL} roles=['user']\n" and PW not in seen


def test_an_existing_account_has_password_and_roles_reset_then_is_finished_and_committed( monkeypatch, capsys ):
    code, calls, session = run( monkeypatch, existing=User( EMAIL, [ "old" ], 11 ) )
    assert code == 0 and session.commits == 1
    assert calls == [ ( "get_by_email", EMAIL ), ( "update_password", 11, HASH ), ( "update_roles", 11, ( "user", ) ), ( "finish_existing", 11, 11 ) ]
    assert capsys.readouterr().out == f"✓ fixed it: {EMAIL} roles=['user']\n"
