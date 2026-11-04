"""
The undelivered-inbox round trip sends to a recipient made for it.

The shared test user collects undelivered rows on every run, and the pull returns the oldest first,
up to a limit. Past the limit the marker the test just sent is not in the answer.
A user registered inside the test starts with an empty inbox.
The test file needs a live server, so this reads its syntax tree.

Venue: :7999 (unit, no server).
"""

import ast
import os

PATH = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "tests", "integration", "test_undelivered_inbox_integration.py" )


def _tree():
    with open( PATH, encoding="utf-8" ) as handle: return ast.parse( handle.read() )


def _function( name ):
    found = [ n for n in ast.walk( _tree() ) if isinstance( n, ast.FunctionDef ) and n.name == name ]
    assert len( found ) == 1, f"{name} must exist once"
    return found[ 0 ]


def _calls( node, dotted ):
    return [ n for n in ast.walk( node ) if isinstance( n, ast.Call ) and ast.unparse( n.func ) == dotted ]


def _keyword( call, name ):
    return [ ast.unparse( k.value ) for k in call.keywords if k.arg == name ]


def test_the_notify_targets_the_throwaway_recipient_and_not_the_shared_user():
    posts = [ c for c in _calls( _function( "test_undelivered_inbox_round_trip" ), "requests.post" )
              if "/api/notify" in ast.unparse( c ) ]
    assert len( posts ) == 1
    params = [ k.value for k in posts[ 0 ].keywords if k.arg == "params" ]
    assert len( params ) == 1 and isinstance( params[ 0 ], ast.Dict )
    target = { ast.unparse( k ): ast.unparse( v ) for k, v in zip( params[ 0 ].keys, params[ 0 ].values ) }[ "'target_user'" ]
    assert target == "recipient_email", f"the notify is addressed to {target}"


def test_the_pull_is_made_as_the_recipient_and_not_as_the_shared_user():
    pulls = [ c for c in _calls( _function( "test_undelivered_inbox_round_trip" ), "requests.get" )
              if "/api/notifications/undelivered" in ast.unparse( c ) ]
    assert len( pulls ) == 1
    assert _keyword( pulls[ 0 ], "headers" ) == [ "recipient_headers" ]


def test_the_recipient_is_registered_fresh_for_each_test():
    fixture = _function( "throwaway_recipient" )
    registers = [ c for c in _calls( fixture, "requests.post" ) if "/auth/register" in ast.unparse( c ) ]
    assert len( registers ) == 1
    emails = [ n for n in ast.walk( fixture ) if isinstance( n, ast.Assign ) and ast.unparse( n.targets[ 0 ] ) == "email" ]
    assert len( emails ) == 1 and "uuid.uuid4()" in ast.unparse( emails[ 0 ].value ), "the email must be unique per run"
    decorators = [ ast.unparse( d ) for d in fixture.decorator_list ]
    assert decorators == [ "pytest.fixture" ], "a module-scoped recipient would share one inbox across tests"
