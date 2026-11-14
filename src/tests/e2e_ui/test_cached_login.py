"""
E2E guard for the cached browser login in `logged_in_page` and `admin_page`.

Before each cached test the fixtures put the saved user row back and load the saved tokens.
`clean_test_db` has by then deleted that user and emptied refresh_tokens.
So these tests ask the server, at /auth/me, whether the saved token is still accepted.

Requires:
    - Server running with Testing config on port 8000

Ensures:
    - every test passes whether it runs first (real login) or later (cached)
"""

import pytest

from .conftest import BASE_URL, _LOGIN_CACHE, get_user_id_from_page


def _me_status( page ):
    """Ask /auth/me about the page's token; return ( status, email )."""
    return page.evaluate(
        """async () => {
            const token    = localStorage.getItem( "lupin_access_token" );
            const response = await fetch( "/auth/me", { headers: { Authorization: `Bearer ${ token }` } } );
            const body     = response.ok ? await response.json() : {};
            return [ response.status, body.email ];
        }"""
    )


class TestCachedLogin:

    def test_user_token_is_accepted_by_the_server( self, logged_in_page, test_user_credentials ):
        """
        Ensures:
            - the server accepts the token and names the test user
        """
        status, email = _me_status( logged_in_page )
        assert ( status, email ) == ( 200, test_user_credentials[ "email" ] )

    def test_admin_token_is_accepted_by_the_server( self, admin_page, test_admin_credentials ):
        """
        Ensures:
            - the server accepts the admin token and names the admin
        """
        status, email = _me_status( admin_page )
        assert ( status, email ) == ( 200, test_admin_credentials[ "email" ] )

    def test_page_lands_off_the_auth_pages( self, logged_in_page ):
        """
        Ensures:
            - the page ends off the auth pages, as after a real login
        """
        assert "/auth/" not in logged_in_page.url

    def test_the_login_is_saved_for_the_role_after_use( self, logged_in_page ):
        """
        Ensures:
            - the cache holds a user entry with the page's user id
        """
        entry = _LOGIN_CACHE.get( "user" )
        assert entry is not None, "logged_in_page left nothing in the cache"
        assert str( entry[ "user_row" ][ "id" ] ) == get_user_id_from_page( logged_in_page )

    @pytest.mark.real_login
    def test_a_real_login_mark_registers_a_new_user( self, logged_in_page ):
        """
        Ensures:
            - a real_login test gets a new user id and leaves the cache alone
        """
        before = _LOGIN_CACHE.get( "user" )
        assert get_user_id_from_page( logged_in_page ) is not None
        if before is not None:
            assert str( before[ "user_row" ][ "id" ] ) != get_user_id_from_page( logged_in_page )
        after = _LOGIN_CACHE.get( "user" )
        assert ( after is None ) == ( before is None )
        if before is not None: assert after[ "user_row" ] == before[ "user_row" ]
