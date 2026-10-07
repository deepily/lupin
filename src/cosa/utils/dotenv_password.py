"""
Fill a blank ``DB_PASSWORD`` from the untracked, gitignored ``.env``.

The plaintext postgres password was removed from the tree. The value now lives only in
the untracked ``.env`` beside ``docker-compose.yml``. Three kinds of consumer need a
route to it, and this module is the route for the third:

    containers                    -> docker-compose.yml maps DB_PASSWORD from the
                                     .env's POSTGRES_PASSWORD
    pytest                        -> a seeder in src/conftest.py
    host-run long-lived processes -> this module

A host process such as the CC notification listener is neither a container nor pytest.
Without this module every gist fails with a ``psycopg2.OperationalError`` saying no
password was supplied. It does not surface as a database error. The listener catches it.
It then emits a five-word prefix of the user's own text. The UI shows that as a short
paraphrase, not as a failure.

The fix is in code and not in a spawn environment. Exporting the value into each host
process's environment would work, but it would put a live credential into spawn
payloads and process listings. Seeding it here keeps the secret in the one file that
already holds it. A process picks the fix up by importing the module, not by having its
launcher edited.

An exported ``DB_PASSWORD`` always wins, because this only ever fills a blank. A
container is given the variable at create time, so it reaches the early return and
never touches the filesystem. This module cannot change the behaviour of anything that
already worked.
"""

import os

# What seed_db_password_from_dotenv put into os.environ, by name. It lets reselect_seeded_login
# tell a login this module chose from one the caller exported.
_SEEDED = { }


def seed_db_password_from_dotenv( root=None ):
    """
    Fill a blank DB_PASSWORD from the nearest ``.env``, preferring a role password.

    Requires:
        - root, if given, is a directory path that may contain a .env or a .git marker

    Ensures:
        - Returns immediately, touching no filesystem, if DB_PASSWORD is already
          set to a non-empty value
        - Sets os.environ[ "DB_PASSWORD" ] from the .env's POSTGRES_PASSWORD when that
          value is present and non-empty and no role password applies
        - Prefers the role password when the .env carries one: LUPIN_TEST_DB_PASSWORD
          when LUPIN_ENV is "testing", otherwise LUPIN_HOST_DB_PASSWORD. It then also
          sets DB_USER from the matching user key, falling back to "lupin_test" or
          "lupin_host", unless DB_USER is already exported
        - Uses the first line for a key as the one that decides, blank or not
        - Looks in the worktree's own .env first, then in the main checkout's .env,
          found through the worktree's ``.git`` file
        - Leaves DB_PASSWORD unset when no .env is found, when the key is absent, or
          when its value is empty
        - Never raises: an unreadable .env or a malformed .git marker is swallowed

    Args:
        root: Directory to search from. Defaults to the project root inferred from
              this file's location.

    Returns:
        None — the effect is on os.environ.
    """
    if os.environ.get( "DB_PASSWORD" ): return

    # <root>/src/cosa/utils/dotenv_password.py -> <root>
    if root is None: root = os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ) ) )

    # A worktree has no .env of its own — it is untracked, so it exists only in the main
    # checkout. In a worktree `.git` is a FILE reading "gitdir: <main>/.git/worktrees/<n>";
    # that is how we reach the checkout that actually holds it, with no subprocess.
    candidates = [ os.path.join( root, ".env" ) ]
    git_marker = os.path.join( root, ".git" )
    if os.path.isfile( git_marker ):
        try:
            gitdir = open( git_marker ).read().split( "gitdir:", 1 )[ 1 ].strip()
            main   = os.path.dirname( gitdir.split( "/.git/worktrees/" )[ 0 ] + "/.git" )
            candidates.append( os.path.join( main, ".env" ) )
        except ( OSError, IndexError ):
            pass

    dotenv = next( ( c for c in candidates if os.path.isfile( c ) ), None )
    if dotenv is None: return

    wanted = ( "POSTGRES_PASSWORD", "LUPIN_HOST_DB_USER", "LUPIN_HOST_DB_PASSWORD",
               "LUPIN_TEST_DB_USER", "LUPIN_TEST_DB_PASSWORD" )
    found  = { }
    seen   = set()
    # THE FIRST LINE FOR A KEY DECIDES, blank or not, which is what the loop that stood here
    # before row 80513825 did (it returned at the first `POSTGRES_PASSWORD=` line). The
    # reviewer's three divergences (a duplicate key, a blank line before a value, undecodable
    # bytes after the key) are tests in test_db_url_unchanged_without_the_new_keys.py.
    try:
        # errors="replace": a stray non-UTF-8 byte in a comment must not hide a key on another line.
        with open( dotenv, errors="replace" ) as fh:
            for line in fh:
                line = line.strip()
                for key in wanted:
                    if key in seen or not line.startswith( key + "=" ): continue
                    seen.add( key )
                    value = line.split( "=", 1 )[ 1 ].strip().strip( "\"'" )
                    if value: found[ key ] = value
                if len( seen ) == len( wanted ): break
    except ( OSError, UnicodeDecodeError ):
        # Whatever was read before the failure stands, as it did when the loop returned at the
        # key. An unreadable file reads nothing and so sets nothing. Never raises: this module
        # is imported by nearly everything at startup.
        pass

    # ROLE KEYS WIN OVER THE SUPERUSER PASSWORD (row 80513825, the approval-settings guard rail).
    # A seat's `.env` is allowed to carry the credentials of a role that cannot write policy
    # (`lupin_host`, or `lupin_test` for the test database) instead of the superuser's. A
    # `testing` process reads the test role, anything else the host role. Absent the keys this
    # is the behaviour that has always been here.
    testing  = os.environ.get( "LUPIN_ENV", "" ).lower() == "testing"
    prefix   = "LUPIN_TEST_DB_" if testing else "LUPIN_HOST_DB_"
    password = found.get( prefix + "PASSWORD" )
    if password:
        os.environ[ "DB_PASSWORD" ] = password
        _SEEDED[ "DB_PASSWORD" ]    = password
        # THE PASSWORD AND THE LOGIN NAME TRAVEL TOGETHER. A role's password paired with the
        # superuser's default name fails to authenticate with an error that names the password,
        # so a missing USER key falls back to the role the SQL creates (init-db-roles.sql).
        # An exported DB_USER still wins.
        if not os.environ.get( "DB_USER" ):
            os.environ[ "DB_USER" ] = found.get( prefix + "USER" ) or ( "lupin_test" if testing else "lupin_host" )
            _SEEDED[ "DB_USER" ]    = os.environ[ "DB_USER" ]
        return
    if "POSTGRES_PASSWORD" in found:
        os.environ[ "DB_PASSWORD" ] = found[ "POSTGRES_PASSWORD" ]
        _SEEDED[ "DB_PASSWORD" ]    = found[ "POSTGRES_PASSWORD" ]


def reselect_seeded_login( root=None ):
    """
    Choose the login again for the current LUPIN_ENV, if this module chose the old one.

    The login is picked once, at the first call, from whatever LUPIN_ENV said then. A process
    that later moves to another environment (swap_database) would keep the first role.

    Requires:
        - LUPIN_ENV already holds the environment being moved to
        - root, if given, is the directory seed_db_password_from_dotenv should search from

    Ensures:
        - changes nothing, and returns False, when DB_USER or DB_PASSWORD was exported or changed
          since this module set it, or when this module set nothing
        - otherwise clears the seeded values and seeds again, so the role matches LUPIN_ENV, and
          returns True
        - puts the previous login back, and returns False, when the second seeding finds nothing
          or finds only a password that would replace a role login with the superuser's name
        - never raises
    """
    if not _SEEDED: return False
    for key in ( "DB_USER", "DB_PASSWORD" ):
        if key in os.environ and _SEEDED.get( key ) != os.environ[ key ]: return False

    previous = { key: os.environ[ key ] for key in ( "DB_USER", "DB_PASSWORD" ) if key in os.environ }
    for key in previous: del os.environ[ key ]
    _SEEDED.clear()

    seed_db_password_from_dotenv( root )
    # A role login that is replaced by a bare password (no DB_USER) would fall back to the
    # superuser's name, so that counts as finding none.
    lost_role = "DB_USER" in previous and "DB_USER" not in os.environ
    if os.environ.get( "DB_PASSWORD" ) and not lost_role: return True

    for key in ( "DB_USER", "DB_PASSWORD" ): os.environ.pop( key, None )
    _SEEDED.clear()

    os.environ.update( previous )
    _SEEDED.update( previous )
    return False


def seed_db_password_from_file():
    """
    Fill a blank DB_PASSWORD from the file named by DB_PASSWORD_FILE.

    Requires:
        - nothing; DB_PASSWORD_FILE may be unset

    Ensures:
        - returns immediately if DB_PASSWORD is already non-empty, or DB_PASSWORD_FILE is unset
        - sets os.environ[ "DB_PASSWORD" ] to the file's content with surrounding whitespace
          stripped, when that is non-empty
        - an unreadable or empty file prints one named warning and leaves DB_PASSWORD
          unset: this module is imported by nearly everything at startup and must not
          raise, and the empty-password announcement then fires downstream as it always has
        - never raises

    A file is used because a password in a container's environment is readable by anyone
    who can run `docker inspect`, while a file mounted as a secret is readable only by
    whoever owns the file. It lets the app's credential live somewhere a seat's `.env`
    is not.
    """
    if os.environ.get( "DB_PASSWORD" ): return
    path = os.environ.get( "DB_PASSWORD_FILE" )
    if not path: return
    try:
        with open( path ) as fh:
            value = fh.read().strip()
    except OSError as error:
        print( f"[DB] WARNING: DB_PASSWORD_FILE={path} could not be read ({error.__class__.__name__}); DB_PASSWORD stays unset" )
        return
    if value: os.environ[ "DB_PASSWORD" ] = value
    else: print( f"[DB] WARNING: DB_PASSWORD_FILE={path} is empty; DB_PASSWORD stays unset" )
