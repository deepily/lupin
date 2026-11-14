"""
Cached browser login for the E2E UI fixtures.

A real form login waits out a 1000 ms redirect, and the two authenticated fixtures ran one before every test.
This module keeps one real login per role for the whole pytest process.

The server checks the user id inside the access token against the users table on every request.
`clean_test_db` deletes the unprotected users before each test.
So the saved tokens work only if the same user row is put back, id and password hash included.
This module saves that row with the tokens and restores it.

Nothing here imports Playwright or the database at module scope, so the logic runs without a browser or a server.
"""

import base64
import json
import time


# The localStorage key the page writes the access token under.
ACCESS_TOKEN_KEY = "lupin_access_token"

# A saved token with less than this many seconds of life left is not reused. The
# access token lives 30 minutes (`jwt access token expire minutes`), and the cache
# lives for the whole pytest process, so it has to be rebuilt about every 25 minutes.
MIN_SECONDS_LEFT = 300


def token_seconds_left( token, now=None ):
    """
    Say how many seconds a JWT access token has left before it expires.

    Requires:
        - token is a JWT string, header.payload.signature, with an integer "exp" claim
        - now is None or a time in seconds since the epoch

    Ensures:
        - returns exp minus now, negative when the token has already expired
        - never checks the signature; the server does that

    Raises:
        - KeyError if the payload has no "exp"
        - ValueError if the token is not three dot-separated parts
    """
    parts = token.split( "." )
    if len( parts ) != 3: raise ValueError( f"not a JWT: expected 3 parts, got {len( parts )}" )

    payload = parts[ 1 ]
    payload += "=" * ( -len( payload ) % 4 )
    claims  = json.loads( base64.urlsafe_b64decode( payload ) )
    now     = time.time() if now is None else now

    return claims[ "exp" ] - now


def access_token_from_state( state, origin ):
    """
    Pull the access token out of a Playwright storage state.

    Requires:
        - state is the dict `context.storage_state()` returns
        - origin is the page origin string, for example "http://localhost:8000"

    Ensures:
        - returns the token string, or None when the origin has none saved
    """
    for entry in state[ "origins" ]:
        if entry[ "origin" ] != origin: continue
        for item in entry[ "localStorage" ]:
            if item[ "name" ] == ACCESS_TOKEN_KEY: return item[ "value" ]

    return None


class LoginCache:
    """
    One saved login per role: the browser storage state and the user row behind it.

    Requires:
        - clock is a callable returning seconds since the epoch
        - min_seconds_left is a non-negative number

    Ensures:
        - get() never returns an entry whose token is within min_seconds_left of expiry
        - an entry that fails that test is dropped, so the caller falls back to a real login
        - nothing outlives the object, so one pytest process owns one cache
    """

    def __init__( self, origin, min_seconds_left=MIN_SECONDS_LEFT, clock=time.time ):
        """
        Requires:
            - origin is the page origin string the tokens were saved under
        """
        self.origin           = origin
        self.min_seconds_left = min_seconds_left
        self.clock            = clock
        self.entries          = {}

    def put( self, role, state, user_row ):
        """
        Save a login.

        Requires:
            - state is a Playwright storage state holding the access token for self.origin
            - user_row is the dict capture_user_row() returned

        Ensures:
            - replaces any earlier entry for the role

        Raises:
            - ValueError when the state holds no access token for the origin
        """
        if access_token_from_state( state, self.origin ) is None:
            raise ValueError( f"no {ACCESS_TOKEN_KEY} for {self.origin} in the storage state" )

        self.entries[ role ] = { "state": state, "user_row": user_row }

    def get( self, role ):
        """
        Return the saved login for a role while its token has life left.

        Ensures:
            - returns the entry dict { "state", "user_row" } while its token has life left
            - returns None for an unknown role, and for a token too close to expiry
        """
        entry = self.entries.get( role )
        if entry is None: return None

        token = access_token_from_state( entry[ "state" ], self.origin )
        if token_seconds_left( token, self.clock() ) < self.min_seconds_left:
            del self.entries[ role ]
            return None

        return entry


def _users_table( table ):
    """Return table, or the real users table when it is None."""
    if table is not None: return table

    from cosa.rest.postgres_models import User

    return User.__table__


def capture_user_row( conn, email, table=None ):
    """
    Read the users row for an email, with every column.

    Requires:
        - conn is an open SQLAlchemy connection to the test database
        - table is None, meaning the real users table, or a stand-in with the same columns

    Ensures:
        - returns a dict of column name to value, or None when no such user exists
    """
    from sqlalchemy import select

    table = _users_table( table )
    row   = conn.execute( select( table ).where( table.c.email == email ) ).mappings().first()

    return None if row is None else dict( row )


def restore_user_row( conn, user_row, table=None ):
    """
    Put a captured users row back, with its original id.

    Requires:
        - conn is an open SQLAlchemy connection inside a transaction the caller commits
        - user_row came from capture_user_row()
        - table is None, meaning the real users table, or a stand-in with the same columns
        - no row with that id or email exists, which clean_test_db guarantees

    Ensures:
        - the row is inserted, so a token issued for its id passes the server's user lookup
    """
    conn.execute( _users_table( table ).insert().values( **user_row ) )


def apply_state_to_page( page, state, origin, blank_url ):
    """
    Load a saved storage state into a page's fresh browser context.

    Requires:
        - page is a Playwright page whose context has no cookies or localStorage yet
        - blank_url is a cheap URL on the same origin that draws no application page
        - state came from context.storage_state()

    Ensures:
        - cookies are added to the context
        - every localStorage item saved for origin is set on that origin
        - the page is left on blank_url
    """
    if state[ "cookies" ]: page.context.add_cookies( state[ "cookies" ] )

    items = []
    for entry in state[ "origins" ]:
        if entry[ "origin" ] == origin: items = entry[ "localStorage" ]

    page.goto( blank_url )
    page.evaluate(
        "( items ) => { for ( const item of items ) localStorage.setItem( item.name, item.value ); }",
        items
    )
