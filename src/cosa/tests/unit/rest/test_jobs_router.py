"""
Unit tests for the jobs router (`cosa.rest.routers.jobs`).

Covers:
- `get_static_dir` — pulls static_dir off lupin_app.main (dual-key patched).
- `delete_snapshot` — valid id → success dict; empty / "invalid"-prefixed id → 404.
- `get_answer` — serves the placeholder audio via FileResponse; 404 when missing.

Zero external dependencies — lupin_app.main, os.path.exists, FileResponse, and
the timestamp helper are boundary-mocked. No real disk access.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import asyncio
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.jobs import get_static_dir, delete_snapshot, get_answer

JOBS = "cosa.rest.routers.jobs"


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


class TestGetStaticDir( unittest.TestCase ):
    """
    Ensures:
        - get_static_dir returns main_module.static_dir
    """

    def test_returns_main_module_static_dir( self ):
        """Ensures: dependency reads static_dir off lupin_app.main."""
        mock_main = MagicMock()
        mock_main.static_dir = "/static"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_static_dir(), "/static" )


class TestDeleteSnapshot( unittest.TestCase ):
    """
    Unit tests for `delete_snapshot`.

    Ensures:
        - valid id returns a success dict with a timestamp
        - empty id and 'invalid'-prefixed id raise 404
    """

    def test_valid_id_returns_success( self ):
        """Ensures: a valid id returns status 'deleted' + a stamped timestamp."""
        with patch( f"{JOBS}.du.get_current_datetime_iso", return_value="2026-06-01T00:00:00" ):
            result = asyncio.run( delete_snapshot( id="snap_123" ) )
        self.assertEqual( result[ "status" ], "deleted" )
        self.assertEqual( result[ "id" ], "snap_123" )
        self.assertEqual( result[ "timestamp" ], "2026-06-01T00:00:00" )

    def test_empty_id_404( self ):
        """Ensures: an empty id raises 404."""
        with self.assertRaises( HTTPException ) as ctx:
            asyncio.run( delete_snapshot( id="" ) )
        self.assertEqual( ctx.exception.status_code, 404 )

    def test_invalid_prefixed_id_404( self ):
        """Ensures: an 'invalid'-prefixed id raises 404."""
        with self.assertRaises( HTTPException ) as ctx:
            asyncio.run( delete_snapshot( id="invalid_xyz" ) )
        self.assertEqual( ctx.exception.status_code, 404 )


class TestGetAnswer( unittest.TestCase ):
    """
    Unit tests for `get_answer`.

    Requires:
        - lupin_app.main, os.path.exists, FileResponse boundary-mocked

    Ensures:
        - serves the placeholder audio via FileResponse when present
        - raises 404 when the audio file is missing
    """

    def test_serves_audio_when_present( self ):
        """Ensures: an existing audio file is served via FileResponse."""
        mock_main = MagicMock()
        mock_main.static_dir = "/static"
        with _patch_fastapi_main( mock_main ), \
             patch( f"{JOBS}.os.path.exists", return_value=True ), \
             patch( f"{JOBS}.FileResponse" ) as m_fr:
            m_fr.return_value = "FR"
            result = asyncio.run( get_answer( id="job_9" ) )

        self.assertEqual( result, "FR" )
        _, kwargs = m_fr.call_args
        self.assertEqual( kwargs[ "path" ], "/static/audio/gentle-gong.mp3" )
        self.assertEqual( kwargs[ "media_type" ], "audio/mpeg" )
        self.assertEqual( kwargs[ "filename" ], "answer-job_9.mp3" )

    def test_missing_audio_404( self ):
        """Ensures: a missing audio file raises 404."""
        mock_main = MagicMock()
        mock_main.static_dir = "/static"
        with _patch_fastapi_main( mock_main ), \
             patch( f"{JOBS}.os.path.exists", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                asyncio.run( get_answer( id="job_9" ) )
        self.assertEqual( ctx.exception.status_code, 404 )


def isolated_unit_test():
    """
    Run the jobs router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in ( TestGetStaticDir, TestDeleteSnapshot, TestGetAnswer ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL JOBS ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME JOBS ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 JOBS ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Jobs router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
