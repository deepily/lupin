"""
Run a block as the test venue, with the test role's login rather than the host role's.

The database login is chosen once, at the first call, from the LUPIN_ENV of that moment. Under
pytest that is the ambient environment, so a `.env` that carries the host and test role keys
seeds the host role. A test that then sets LUPIN_ENV=testing and opens the test database keeps the
host role, which may not connect to lupin_db_test. `reselected_for_testing` picks the login again
for the block and puts everything back afterwards.
"""

import contextlib
import os

from cosa.utils import dotenv_password

_KEYS = ( "LUPIN_ENV", "DATABASE_URL", "DB_NAME", "DB_USER", "DB_PASSWORD" )


@contextlib.contextmanager
def reselected_for_testing( root=None ):
    """
    Make LUPIN_ENV=testing and the login that goes with it, for the length of a with-block.

    Requires:
        - root, if given, is the directory the .env is read from (default: the project root)

    Ensures:
        - inside the block LUPIN_ENV is "testing" and DATABASE_URL and DB_NAME are unset
        - the login is chosen again for it, unless DB_USER or DB_PASSWORD was exported
        - yields True when the login was chosen again, False when it was left as it was
        - on exit, the five environment variables and the module's record of what it seeded are
          exactly as they were, even when the block raised
    """
    saved_env    = { key: os.environ.get( key ) for key in _KEYS }
    saved_seeded = dict( dotenv_password._SEEDED )
    try:
        os.environ[ "LUPIN_ENV" ] = "testing"
        os.environ.pop( "DATABASE_URL", None )
        os.environ.pop( "DB_NAME", None )
        yield dotenv_password.reselect_seeded_login( root )
    finally:
        for key, value in saved_env.items():
            if value is None: os.environ.pop( key, None )
            else:             os.environ[ key ] = value
        dotenv_password._SEEDED.clear()
        dotenv_password._SEEDED.update( saved_seeded )
