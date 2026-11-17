"""
Unit tests for the cached browser login in `src/tests/e2e_ui/cached_login.py`.

They need no browser and no server.
They cover token expiry, the per-role cache, and the users row capture and restore.
The row round trip runs on an in-memory SQLite copy of the real users table.

Venue: :7999-eligible, no network, no persistent state.
"""

import base64
import json

import pytest
from sqlalchemy import create_engine

from tests.e2e_ui import cached_login as cl

ORIGIN = "http://localhost:8000"


def _token( exp ):
    """A JWT-shaped string whose payload carries exp; the signature part is not checked."""
    body = base64.urlsafe_b64encode( json.dumps( { "sub": "u1", "exp": exp } ).encode() ).decode().rstrip( "=" )
    return f"h.{body}.s"


def _state( token, origin=ORIGIN, cookies=None ):
    """A Playwright-shaped storage state holding one localStorage item."""
    items = [] if token is None else [ { "name": cl.ACCESS_TOKEN_KEY, "value": token } ]
    return { "cookies": cookies or [], "origins": [ { "origin": origin, "localStorage": items } ] }


class TestTokenSecondsLeft:

    def test_returns_exp_minus_now( self ):
        assert cl.token_seconds_left( _token( 1500 ), now=1000 ) == 500

    def test_negative_once_expired( self ):
        assert cl.token_seconds_left( _token( 900 ), now=1000 ) == -100

    def test_defaults_now_to_the_wall_clock( self ):
        assert 1700 < cl.token_seconds_left( _token( 10**10 ) ) < 10**10

    def test_rejects_a_token_that_is_not_three_parts( self ):
        with pytest.raises( ValueError, match="expected 3 parts, got 2" ):
            cl.token_seconds_left( "a.b" )

    def test_a_payload_needing_padding_decodes( self ):
        # exp of 1 digit changes the base64 length; any padding length must decode
        for exp in ( 1, 22, 333, 4444 ):
            assert cl.token_seconds_left( _token( exp ), now=0 ) == exp


class TestAccessTokenFromState:

    def test_finds_the_token_for_the_origin( self ):
        assert cl.access_token_from_state( _state( "tok" ), ORIGIN ) == "tok"

    def test_none_for_another_origin( self ):
        assert cl.access_token_from_state( _state( "tok", origin="http://other" ), ORIGIN ) is None

    def test_none_when_the_origin_holds_no_token( self ):
        assert cl.access_token_from_state( _state( None ), ORIGIN ) is None

    def test_ignores_other_keys( self ):
        state = _state( "tok" )
        state[ "origins" ][ 0 ][ "localStorage" ].insert( 0, { "name": "other", "value": "x" } )
        assert cl.access_token_from_state( state, ORIGIN ) == "tok"


class TestLoginCache:

    def _cache( self, now ):
        return cl.LoginCache( ORIGIN, min_seconds_left=300, clock=lambda: now[ 0 ] )

    def test_unknown_role_is_a_miss( self ):
        assert self._cache( [ 0 ] ).get( "user" ) is None

    def test_put_then_get_returns_the_same_entry( self ):
        cache = self._cache( [ 0 ] )
        state = _state( _token( 1800 ) )
        cache.put( "user", state, { "id": 1 } )
        assert cache.get( "user" ) == { "state": state, "user_row": { "id": 1 } }

    def test_roles_do_not_share_an_entry( self ):
        cache = self._cache( [ 0 ] )
        cache.put( "user", _state( _token( 1800 ) ), { "id": 1 } )
        cache.put( "admin", _state( _token( 1800 ) ), { "id": 2 } )
        assert cache.get( "user" )[ "user_row" ] == { "id": 1 }
        assert cache.get( "admin" )[ "user_row" ] == { "id": 2 }

    def test_put_replaces_the_earlier_entry( self ):
        cache = self._cache( [ 0 ] )
        cache.put( "user", _state( _token( 1800 ) ), { "id": 1 } )
        cache.put( "user", _state( _token( 1800 ) ), { "id": 9 } )
        assert cache.get( "user" )[ "user_row" ] == { "id": 9 }

    def test_a_token_with_life_left_is_kept( self ):
        now   = [ 0 ]
        cache = self._cache( now )
        cache.put( "user", _state( _token( 1800 ) ), {} )
        now[ 0 ] = 1499          # 301 s left, one over the floor
        assert cache.get( "user" ) is not None

    def test_a_token_at_the_floor_is_kept_and_one_second_under_is_dropped( self ):
        now   = [ 0 ]
        cache = self._cache( now )
        cache.put( "user", _state( _token( 1800 ) ), {} )
        now[ 0 ] = 1500          # exactly 300 s left: not under the floor
        assert cache.get( "user" ) is not None
        now[ 0 ] = 1501          # 299 s left
        assert cache.get( "user" ) is None
        assert "user" not in cache.entries, "an expired entry is dropped, not just hidden"

    def test_put_refuses_a_state_without_a_token_for_the_origin( self ):
        cache = self._cache( [ 0 ] )
        with pytest.raises( ValueError, match="lupin_access_token" ):
            cache.put( "user", _state( None ), {} )
        assert cache.get( "user" ) is None

    def test_defaults_are_the_module_constants( self ):
        cache = cl.LoginCache( ORIGIN )
        assert cache.min_seconds_left == cl.MIN_SECONDS_LEFT == 300
        assert cache.clock.__name__ == "time"


@pytest.fixture
def users():
    """
    A SQLite copy of the real `users` table and a connection to it, as ( conn, table ).

    The copy keeps every column name.
    It swaps the Postgres-only types and server defaults.
    So the insert is built from the real column list.
    """
    from cosa.rest.postgres_models import User
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB

    table = User.__table__.to_metadata( MetaData() )
    for column in table.columns:
        column.server_default = None
        if isinstance( column.type, JSONB ): column.type = JSON()
    engine = create_engine( "sqlite://" )
    table.create( engine )
    with engine.begin() as connection:
        yield connection, table
    engine.dispose()


def _user( email, **extra ):
    import uuid
    return { "id": uuid.uuid4(), "email": email, "password_hash": "$2b$12$hash", "roles": [ "user", "admin" ], **extra }


class TestUserRowRoundTrip:

    def test_capture_returns_none_for_an_unknown_email( self, users ):
        conn, table = users
        assert cl.capture_user_row( conn, "nobody@example.com", table ) is None

    def test_a_deleted_user_comes_back_with_the_same_id_hash_and_roles( self, users ):
        conn, table = users
        conn.execute( table.insert().values( **_user( "e2e_admin@example.com" ) ) )

        saved = cl.capture_user_row( conn, "e2e_admin@example.com", table )
        conn.execute( table.delete() )                       # what clean_test_db does
        assert cl.capture_user_row( conn, "e2e_admin@example.com", table ) is None

        cl.restore_user_row( conn, saved, table )
        again = cl.capture_user_row( conn, "e2e_admin@example.com", table )

        assert again[ "id" ] == saved[ "id" ]
        assert again[ "password_hash" ] == "$2b$12$hash"
        assert again[ "roles" ] == [ "user", "admin" ]
        assert again == saved

    def test_capture_picks_the_row_for_the_email_asked( self, users ):
        conn, table = users
        conn.execute( table.insert().values( **_user( "a@example.com" ) ) )
        conn.execute( table.insert().values( **_user( "b@example.com" ) ) )
        assert cl.capture_user_row( conn, "b@example.com", table )[ "email" ] == "b@example.com"

    def test_the_default_table_is_the_real_users_table( self ):
        from cosa.rest.postgres_models import User
        assert cl._users_table( None ) is User.__table__
        sentinel = object()
        assert cl._users_table( sentinel ) is sentinel


class _Context:
    def __init__( self ): self.cookies = None
    def add_cookies( self, cookies ): self.cookies = cookies


class _Page:
    """Records what apply_state_to_page does to a page."""
    def __init__( self ):
        self.context = _Context()
        self.calls   = []
    def goto( self, url ): self.calls.append( ( "goto", url ) )
    def evaluate( self, script, items ): self.calls.append( ( "evaluate", items ) )


class TestApplyStateToPage:

    def test_sets_the_items_for_the_origin_on_the_blank_url( self ):
        page = _Page()
        cl.apply_state_to_page( page, _state( "tok" ), ORIGIN, ORIGIN + "/health" )
        assert page.calls == [
            ( "goto", ORIGIN + "/health" ),
            ( "evaluate", [ { "name": cl.ACCESS_TOKEN_KEY, "value": "tok" } ] ),
        ]
        assert page.context.cookies is None

    def test_adds_cookies_only_when_there_are_some( self ):
        page = _Page()
        cl.apply_state_to_page( page, _state( "tok", cookies=[ { "name": "c" } ] ), ORIGIN, ORIGIN + "/health" )
        assert page.context.cookies == [ { "name": "c" } ]

    def test_items_saved_for_another_origin_are_not_set( self ):
        page = _Page()
        cl.apply_state_to_page( page, _state( "tok", origin="http://other" ), ORIGIN, ORIGIN + "/health" )
        assert page.calls[ 1 ] == ( "evaluate", [] )
