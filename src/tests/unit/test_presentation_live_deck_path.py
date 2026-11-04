"""
Unit tests for where the live smoke's deck check looks for the finished deck.

job.py records artifacts["pptx_path"] relative to io/, stripping the io_base prefix.
The check must put `{root}/io/` back. The live smoke joined to the project root, one
directory short, and rejected a valid deck. The render-only smoke had the same fix in f201b109a.

Zero external dependencies. The object is built via __new__ to skip login and config.
The verdict function is replaced by one that records the path it is given.
"""

import unittest
from unittest.mock import patch

from tests.smoke.test_presentation_live_smoke import PresentationLiveSmokeTest


class _Refused:
    """A false deck verdict that carries a reason."""
    reason = "stub"
    def __bool__( self ): return False


class TestLiveDeckPath( unittest.TestCase ):
    """
    Tests the path handed to the deck verdict.

    Ensures:
        - a relative pptx_path is checked at {LUPIN_ROOT}/io/<path>
        - an absolute pptx_path is checked as given
        - the path job.py records round-trips to the file it wrote
    """

    def _checked_path( self, recorded, key="artifacts" ):
        """Ensures: returns the paths the verdict was given for a recorded pptx_path."""
        seen = []
        def _verdict( path ):
            seen.append( path )
            return _Refused()
        job_data = { "artifacts": { "pptx_path": recorded } } if key == "artifacts" else { "pptx_path": recorded }
        with patch( "cosa.utils.util.get_project_root", return_value="/var/lupin" ), \
             patch( "cosa.agents.presentation_generator.deck_verdict.verify_presentation_deck", _verdict ):
            PresentationLiveSmokeTest.__new__( PresentationLiveSmokeTest )._check_deck_file( job_data )
        return seen

    def test_io_relative_path_is_joined_under_io( self ):
        """Ensures: the io/ prefix job.py strips is put back."""
        self.assertEqual( self._checked_path( "presentations/u/deck.pptx" ), [ "/var/lupin/io/presentations/u/deck.pptx" ] )

    def test_absolute_path_is_checked_as_given( self ):
        """Ensures: an absolute pptx_path is not re-rooted."""
        self.assertEqual( self._checked_path( "/var/lupin/io/presentations/u/deck.pptx", key="job" ), [ "/var/lupin/io/presentations/u/deck.pptx" ] )

    def test_the_path_job_py_records_is_found_where_it_wrote_the_file( self ):
        """Ensures: job.py's strip, then the check, lands on the written file."""
        written  = "/var/lupin/io/presentations/u/2026.10.08-at-21:08-UTC-deck.pptx"
        recorded = written.replace( "/var/lupin" + "/io/", "" )
        self.assertEqual( self._checked_path( recorded ), [ written ] )
