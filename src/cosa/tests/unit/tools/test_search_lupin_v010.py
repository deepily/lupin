"""
Unit tests for cosa.tools.search_lupin_v010.LupinSearch.

LupinSearch is a thin vendor-neutral wrapper over KagiSearch. The KagiSearch
collaborator is fully mocked (no API key, no network), so tests focus on
wrapper behaviour: construction wiring, search delegation, and the
scope-based result accessor (all/meta/data/summary/references + invalid).
"""

import unittest
from unittest.mock import patch, MagicMock

import cosa.tools.search_lupin_v010 as slv
from cosa.tools.search_lupin_v010 import LupinSearch

_RESULTS = {
    "meta": { "id": "abc" },
    "data": { "output": "the summary", "references": [ "r1", "r2" ] },
}


class TestLupinSearch( unittest.TestCase ):
    """Construction, search delegation, and scoped result retrieval."""

    def setUp( self ):
        # Replace KagiSearch with a fake whose search_fastgpt() returns _RESULTS.
        self.fake_searcher = MagicMock()
        self.fake_searcher.search_fastgpt.return_value = _RESULTS
        self.patcher = patch.object(
            slv, "KagiSearch", return_value=self.fake_searcher
        )
        self.mock_kagi = self.patcher.start()
        self.addCleanup( self.patcher.stop )

    def test_init_wires_kagi_searcher( self ):
        s = LupinSearch( query="weather?", debug=True, verbose=True )
        self.mock_kagi.assert_called_once_with(
            query="weather?", url=None, debug=True, verbose=True
        )
        self.assertIsNone( s._results )
        self.assertEqual( s.query, "weather?" )

    def test_search_populates_results( self ):
        s = LupinSearch( query="q" )
        s.search_and_summarize_the_web()
        self.fake_searcher.search_fastgpt.assert_called_once()
        self.assertEqual( s._results, _RESULTS )

    def _searched( self ):
        s = LupinSearch( query="q" )
        s.search_and_summarize_the_web()
        return s

    def test_get_results_all( self ):
        self.assertEqual( self._searched().get_results( "all" ), _RESULTS )

    def test_get_results_meta( self ):
        self.assertEqual( self._searched().get_results( "meta" ), { "id": "abc" } )

    def test_get_results_data( self ):
        self.assertEqual( self._searched().get_results( "data" ), _RESULTS[ "data" ] )

    def test_get_results_summary( self ):
        self.assertEqual( self._searched().get_results( "summary" ), "the summary" )

    def test_get_results_references( self ):
        self.assertEqual( self._searched().get_results( "references" ), [ "r1", "r2" ] )

    def test_get_results_invalid_scope_returns_none( self ):
        self.assertIsNone( self._searched().get_results( "bogus" ) )


if __name__ == "__main__":
    unittest.main()
