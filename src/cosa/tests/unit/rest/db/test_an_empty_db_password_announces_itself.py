"""
An empty DB_PASSWORD must SAY SO. Silent-and-empty is what let this run for months.

THE DEFECT THESE PIN (row 2ab9961b, Rick's P1, 2026-09-04). `get_database_url` reads
`DB_PASSWORD` and defaults it to `""`. That default is DELIBERATE and stays — this module
builds its URL at import time and nearly everything imports it, so raising would take the
fleet down to report a misconfiguration. What was missing is the announcement.

⚠️ WARN, NEVER RAISE — AND THE RAISE BELONGS AT THE CONNECTION, NOT AT URL CONSTRUCTION.
María's constraint, 2026-09-04, and `test_it_warns_and_never_raises` is what holds it.

WHY IT MATTERED. `DB_PASSWORD` is read here and supplied nowhere for a host-side process:
the untracked repo-root `.env` carries `POSTGRES_PASSWORD`, and `docker-compose.yml` is the
only thing that translates one name into the other — for CONTAINERS. So an empty password
produced a syntactically valid URL, every call was refused deep downstream with
`fe_sendauth: no password supplied`, and the nearest broad `except` dressed the outage up as
a plausible short answer. Measured across 2,479 listener logs: 158 failures in seven days,
every one of them this.

⚠️ THE POINT IS THE SEAM, NOT THE CALL SITE. Fixing only the Gister would leave the next
caller of this module facing the same silence — a value produced in one place, read in
another under a different name, with nothing saying so. María's ruling, 2026-09-04:
"B is the point, not a bonus."

WHAT THESE DO NOT ASSERT: that the warning is correct advice for a container (it names the
host-side case explicitly), nor anything about what happens at connect time.

Created 2026-09-04 by Maya 🌻 for row 2ab9961b.
"""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cosa.rest.db.database as db


class TestAnEmptyDbPasswordAnnouncesItself( unittest.TestCase ):
    """
    Ensures:
        - an empty DB_PASSWORD prints a warning naming BOTH env var names
        - a populated DB_PASSWORD prints nothing (it does not fire on the healthy path)
        - the announcement fires at most once per process
        - it warns and NEVER raises, in either local venue
    """

    def setUp( self ):
        """
        Ensures: each test starts with the once-only latch cleared, and restores it after.
        """
        self._saved = db._ANNOUNCED_EMPTY_DB_PASSWORD
        db._ANNOUNCED_EMPTY_DB_PASSWORD = False
        self.addCleanup( setattr, db, "_ANNOUNCED_EMPTY_DB_PASSWORD", self._saved )

    def _url_with( self, env ):
        """
        Ensures: returns ( url, stdout_text ) from building the URL under exactly `env`.
        """
        buf = io.StringIO()
        with patch.dict( os.environ, env, clear=True ), redirect_stdout( buf ):
            url = db.get_database_url()
        return url, buf.getvalue()

    def test_an_empty_password_names_both_variables( self ):
        """
        THE DEFECT. The warning has to be actionable, which means naming the seam — a bare
        "no password" sends the reader looking for a missing secret rather than a mismatched
        name, which is the wrong search and the expensive one.
        """
        url, out = self._url_with( { "LUPIN_ENV": "development" } )

        self.assertIn( "DB_PASSWORD",       out, "the warning must name the variable the CODE reads" )
        self.assertIn( "POSTGRES_PASSWORD", out, "the warning must name the variable the ENVIRONMENT supplies" )
        self.assertIn( "WARNING",           out )
        self.assertTrue( url.startswith( "postgresql+psycopg2://" ),
                         "the URL must still be built — warning, not raising, is the invariant" )

    def test_a_populated_password_says_nothing( self ):
        """
        POSITIVE CONTROL — proves the announcement discriminates rather than firing on every
        call. Without this, a warning printed unconditionally would satisfy the test above,
        and the suite would be measuring that a print statement exists.
        """
        url, out = self._url_with( { "LUPIN_ENV": "development", "DB_PASSWORD": "a-real-password" } )

        self.assertEqual( out, "", f"the healthy path must be silent, got: {out!r}" )
        self.assertIn( "a-real-password", url )

    def test_it_announces_at_most_once_per_process( self ):
        """
        An alarm repeated on every call is an alarm people filter out — and this module's URL
        is rebuilt by several callers.
        """
        _, first  = self._url_with( { "LUPIN_ENV": "development" } )
        _, second = self._url_with( { "LUPIN_ENV": "development" } )

        self.assertIn(    "WARNING", first )
        self.assertEqual( "",        second, "the second call must be silent" )

    def test_the_testing_venue_announces_too( self ):
        """
        Both local venues read the same variable, so both owe the same warning. The venue name
        rides in the message so a reader knows which block resolved.
        """
        _, out = self._url_with( { "LUPIN_ENV": "testing" } )

        self.assertIn( "testing",     out )
        self.assertIn( "DB_PASSWORD", out )

    def test_it_warns_and_never_raises( self ):
        """
        🔴 MARÍA'S CONSTRAINT, HELD BY THIS TEST. `get_database_url` runs at IMPORT time and
        nearly everything imports this module, so a raise here is a fleet-wide startup
        failure to report a misconfiguration. The refusal belongs at the CONNECTION attempt,
        which is where it already lives and where it stays.

        Both local venues, no password at all — neither may raise.
        """
        for venue in ( "development", "testing" ):
            db._ANNOUNCED_EMPTY_DB_PASSWORD = False
            with self.subTest( venue=venue ):
                try:
                    url, _ = self._url_with( { "LUPIN_ENV": venue } )
                except Exception as e:
                    self.fail( f"get_database_url raised {type( e ).__name__} for venue "
                               f"{venue!r} with no DB_PASSWORD — it must warn, never raise: {e}" )
                self.assertTrue( url.startswith( "postgresql+psycopg2://" ) )


if __name__ == "__main__":
    unittest.main()
