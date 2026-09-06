"""
Fill a BLANK ``DB_PASSWORD`` from the untracked, gitignored ``.env``.

WHY THIS MODULE EXISTS
----------------------
Row baac2474 (commit 765e7145, 2026-08-31) removed the plaintext postgres password
from the tree. The value now lives ONLY in the untracked ``.env`` beside
``docker-compose.yml``. That commit gave TWO of the three consumers a route to it and
missed the third:

    containers                    -> docker-compose.yml maps DB_PASSWORD from the
                                     .env's POSTGRES_PASSWORD                    OK
    pytest                        -> a seeder added to src/conftest.py            OK
    host-run long-lived processes -> nothing                                      MISSING

The missing one is not hypothetical. Between 2026-08-31 23:58 and 2026-09-05 the CC
notification listener — a host process, neither a container nor pytest — raised
``psycopg2.OperationalError … fe_sendauth: no password supplied`` on every gist it
attempted, 166 times in five days. It does not surface as a database error: the
listener catches it and emits a five-word prefix of the user's own text, which reads
in the UI as a short paraphrase rather than as a failure.

⚠️ THE FIX IS DELIBERATELY IN CODE, NOT IN A SPAWN ENVIRONMENT. Exporting the value
into each host process's environment would work and would put a live credential into
spawn payloads and process listings. Seeding it here keeps the secret in the one file
that already holds it, and means a process picks the fix up by importing the module
rather than by having its launcher edited.

CONTRACT
--------
An EXPORTED ``DB_PASSWORD`` always wins — this only ever fills a blank. So a container
(which is given the variable at create time) reaches the early return and never touches
the filesystem, and this module cannot change the behaviour of anything that was
already working.
"""

import os


def seed_db_password_from_dotenv( root=None ):
    """
    Fill a blank DB_PASSWORD from the nearest ``.env``'s POSTGRES_PASSWORD.

    Requires:
        - root, if given, is a directory path that may contain a .env or a .git marker

    Ensures:
        - Returns immediately, touching no filesystem, if DB_PASSWORD is already
          set to a non-empty value
        - Sets os.environ[ "DB_PASSWORD" ] from the .env's POSTGRES_PASSWORD when that
          value is present and non-empty
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

    try:
        with open( dotenv ) as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith( "POSTGRES_PASSWORD=" ): continue
                value = line.split( "=", 1 )[ 1 ].strip().strip( "\"'" )
                if value: os.environ[ "DB_PASSWORD" ] = value
                return
    except OSError:
        return
