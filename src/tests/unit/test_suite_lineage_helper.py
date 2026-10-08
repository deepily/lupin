"""
The shared lineage helper for integration tests (tests.helpers.suite_lineage).

It adds the parent id to a request body and the token to its headers.
It does so only when the sweep exported them, and never changes what the caller passed in.
The three fresh-user integration files send their asks through it and keep no copy of the old helper.

Venue: :7999 (unit, no server).
"""

import os

import pytest

from cosa.rest.suite_run_token import TOKEN_ENV_NAME, TOKEN_HEADER
import ast

from tests.helpers.suite_lineage import PARENT_ENV_NAME, lineage_request, require_sweep, sweep_state

BODY    = { "question": "q" }
HEADERS = { "Authorization": "Bearer t" }
FILES   = [ "test_job_queue_progressive_disclosure.py", "test_queue_filtering_integration.py", "test_queue_not_self_filter.py" ]


@pytest.fixture( autouse=True )
def _clean_env( monkeypatch ):
    monkeypatch.delenv( PARENT_ENV_NAME, raising=False )
    monkeypatch.delenv( TOKEN_ENV_NAME, raising=False )


def test_outside_a_sweep_the_copies_equal_the_inputs():
    assert lineage_request( BODY, HEADERS ) == { "json": BODY, "headers": HEADERS }


def test_the_parent_id_goes_in_the_body_and_the_token_in_the_header( monkeypatch ):
    monkeypatch.setenv( PARENT_ENV_NAME, "ts-abc" )
    monkeypatch.setenv( TOKEN_ENV_NAME, "tok-123" )
    assert lineage_request( BODY, HEADERS ) == {
        "json"    : { "question": "q", "parent_id_hash": "ts-abc" },
        "headers" : { "Authorization": "Bearer t", TOKEN_HEADER: "tok-123" },
    }


def test_the_parent_alone_adds_no_header_and_the_token_alone_adds_no_body_field( monkeypatch ):
    monkeypatch.setenv( PARENT_ENV_NAME, "ts-abc" )
    assert lineage_request( BODY, HEADERS )[ "headers" ] == HEADERS
    monkeypatch.delenv( PARENT_ENV_NAME )
    monkeypatch.setenv( TOKEN_ENV_NAME, "tok-123" )
    result = lineage_request( BODY, HEADERS )
    assert result[ "json" ] == BODY and result[ "headers" ][ TOKEN_HEADER ] == "tok-123"


def test_the_callers_dicts_are_not_modified( monkeypatch ):
    monkeypatch.setenv( PARENT_ENV_NAME, "ts-abc" )
    monkeypatch.setenv( TOKEN_ENV_NAME, "tok-123" )
    body, headers = dict( BODY ), dict( HEADERS )
    lineage_request( body, headers )
    assert body == BODY and headers == HEADERS


def test_the_returned_dicts_are_copies_even_when_nothing_is_added():
    result = lineage_request( BODY, HEADERS )
    assert result[ "json" ] is not BODY and result[ "headers" ] is not HEADERS


@pytest.mark.parametrize( "name", FILES )
def test_each_fresh_user_file_sends_its_asks_through_the_helper_and_keeps_no_copy( name ):
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "tests", "integration", name )
    text = open( path, encoding="utf-8" ).read()
    assert "_with_lineage" not in text
    assert "from tests.helpers.suite_lineage import lineage_request" in text
    asks = text.count( '/api/v2/ask"' )
    assert asks >= 1, "the file posts no ask, so the guard counts nothing"
    assert text.count( "lineage_request(" ) == asks


@pytest.mark.parametrize( "environ, expected", [
    ( { },                                                       "outside" ),
    ( { TOKEN_ENV_NAME: "tok" },                                 "outside" ),
    ( { PARENT_ENV_NAME: "ts-abc" },                             "missing_token" ),
    ( { PARENT_ENV_NAME: "ts-abc", TOKEN_ENV_NAME: "" },         "missing_token" ),
    ( { PARENT_ENV_NAME: "ts-abc", TOKEN_ENV_NAME: "tok" },      "ready" ),
] )
def test_sweep_state_names_what_the_sweep_exported( environ, expected ):
    assert sweep_state( environ ) == expected


def test_sweep_state_reads_the_process_environment_by_default( monkeypatch ):
    monkeypatch.setenv( PARENT_ENV_NAME, "ts-abc" )
    assert sweep_state() == "missing_token"
    monkeypatch.setenv( TOKEN_ENV_NAME, "tok" )
    assert sweep_state() == "ready"


TOKEN_FILE = "test_suite_token_keeps_a_fresh_users_lineage.py"


def _token_file_tree():
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "tests", "integration", TOKEN_FILE )
    return ast.parse( open( path, encoding="utf-8" ).read() )


def test_outside_a_sweep_the_requirement_skips():
    with pytest.raises( pytest.skip.Exception ):
        require_sweep( { } )


def test_a_parent_without_a_token_fails_with_the_message_and_does_not_skip():
    with pytest.raises( pytest.fail.Exception ) as raised:
        require_sweep( { PARENT_ENV_NAME: "ts-abc" } )
    assert "no per-run token" in str( raised.value )


def test_with_both_exported_the_requirement_returns_none():
    assert require_sweep( { PARENT_ENV_NAME: "ts-abc", TOKEN_ENV_NAME: "tok" } ) is None


def test_the_token_file_fixture_only_calls_the_requirement():
    fixture = [ n for n in ast.walk( _token_file_tree() ) if isinstance( n, ast.FunctionDef )
                and n.name == "_sweep_exported_what_this_file_needs" ]
    assert len( fixture ) == 1
    calls = [ ast.unparse( n.func ) for stmt in fixture[ 0 ].body for n in ast.walk( stmt ) if isinstance( n, ast.Call ) ]
    assert calls == [ "require_sweep" ], "the state-to-action mapping lives in the helper, where it is tested"


def test_every_request_in_the_token_file_carries_the_sixty_second_timeout():
    tree     = _token_file_tree()
    requests = [ n for n in ast.walk( tree ) if isinstance( n, ast.Call ) and ast.unparse( n.func ) in ( "requests.post", "requests.get" ) ]
    assert len( requests ) == 3, "register, login and ask: a new request must be counted here"
    for call in requests:
        keywords = { k.arg: ast.unparse( k.value ) for k in call.keywords }
        assert keywords.get( "timeout" ) == "REQUEST_TIMEOUT", ast.unparse( call )
    constant = [ n for n in ast.walk( tree ) if isinstance( n, ast.Assign ) and ast.unparse( n.targets[ 0 ] ) == "REQUEST_TIMEOUT" ]
    assert len( constant ) == 1 and ast.unparse( constant[ 0 ].value ) == "60"
