"""
Unit tests for the Deep Research router (`cosa.rest.routers.deep_research`).

Covers all three endpoints + the dependency:
- `get_todo_queue` — dual-key `lupin_app.main` read.
- `submit_research` — missing-uid 400, missing-email 400, session-id fallback,
  success (minimal + every args arm: budget / dry_run / force_failure_mode /
  audience / audience_context + lead_model + scheduled_at + monopolize), factory-None
  → 500 (wrapped by the broad `except`), and push-failure 500.
- `get_report` — GCS unavailable 503, GCS success, GCS NotFound 404, GCS other 500;
  local relative success, local absolute success, local /io/<other> success (second
  allow-prefix arm), traversal 400, not-found 404, read-error 500.
- `deep_research_health` — dir-exists and dir-missing arms.

Zero external dependencies — create_agentic_job, user_job_tracker, the queue, the GCS
shim globals, cu.get_project_root, and filesystem probes are all boundary-mocked. No
real jobs, no LLM, no queue, no network, no GCS. Auth bypassed by passing current_user
explicitly.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
import asyncio
import builtins
import importlib
import sys
import time

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.deep_research as mod
from cosa.rest.routers.deep_research import (
    submit_research,
    get_report,
    deep_research_health,
)
from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT

PATH = "/api/deep-research/submit"

_MOD = "cosa.rest.routers.deep_research"


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _job( id_hash="init_hash", last_q="research the topic" ):
    """A DeepResearchJob stand-in with the attributes the endpoint reads."""
    job = MagicMock()
    job.id_hash             = id_hash
    job.last_question_asked = last_q
    return job


class TestTheSubmitDoorIsRetired( unittest.TestCase ):
    """
    WHAT USED TO BE HERE. `TestGetTodoQueue` and `TestSubmitResearch` — the identity 400s,
    the session-id fallback, every optional-field arm, the lineage stamp, the factory-None
    and push-failure 500s. That handler is gone: `/api/deep-research/submit` is a tombstone
    naming `/api/v2/submit`. There is nothing to rewrite those tests INTO; the behaviour
    did not move within this module, it moved to a door with its own suite.

    THE GET ROUTES BELOW ARE UNTOUCHED. `get_report` and `deep_research_health` read a
    finished report and answer a health check — neither queues work, so neither is a door
    in the sense this retirement is about, and their coverage stands exactly as it was.
    """

    def _client( self ):
        app = FastAPI()
        app.include_router( mod.router )
        return TestClient( app, raise_server_exceptions=False )

    def test_it_answers_410_and_names_the_submit_door( self ):
        response = self._client().post( PATH, json={ "query": "the state of AI" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_it_refuses_an_unauthenticated_caller_the_same_way( self ):
        """No auth on a tombstone: a 401 reads like a credentials problem, not a retired door."""
        self.assertEqual( self._client().post( PATH, json={ } ).status_code, 410 )

    def test_the_surviving_get_routes_are_still_mounted( self ):
        """The point of retiring a DOOR rather than a module: everything that was not a
        door keeps working."""
        paths = { route.path for route in self._client().app.routes }
        self.assertIn( "/api/deep-research/report", paths )
        self.assertIn( "/api/deep-research/health", paths )

    def test_the_table_says_this_door_retires_into_submit_not_ask( self ):
        self.assertEqual( RETIRED_DOORS[ PATH ], V2_SUBMIT )

    def test_the_handler_only_refuses( self ):
        """RED ON REVERT: give the handler a body again and it stops raising."""
        import asyncio
        with self.assertRaises( HTTPException ) as caught:
            asyncio.run( submit_research() )
        self.assertEqual( caught.exception.status_code, 410 )

    def test_the_job_building_machinery_is_gone_from_this_module( self ):
        for name in ( "create_agentic_job", "user_job_tracker", "get_todo_queue",
                      "DeepResearchSubmitRequest", "DeepResearchSubmitResponse" ):
            self.assertFalse( hasattr( mod, name ),
                              f"{name} survives in a module whose only POST is a tombstone" )


class TestGetReportGcs( unittest.TestCase ):
    """
    Unit tests for `get_report` GCS-path arms.

    Ensures:
        - 503 when SDK unavailable; success; 404 on NotFound; 500 on other errors
    """

    def _call( self, path ):
        return asyncio.run( get_report( path=path ) )

    def test_gcs_unavailable_503( self ):
        """Ensures: a gs:// path with GCS unavailable raises 503."""
        with patch( f"{_MOD}.GCS_AVAILABLE", False ), \
             patch( f"{_MOD}.read_text_from_gcs", None ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "gs://bucket/report.md" )
        self.assertEqual( ctx.exception.status_code, 503 )
        self.assertIn( "GCS SDK not available", ctx.exception.detail )

    def test_gcs_success( self ):
        """Ensures: a gs:// path returns markdown via the GCS reader."""
        reader = MagicMock( return_value="# GCS report" )
        with patch( f"{_MOD}.GCS_AVAILABLE", True ), \
             patch( f"{_MOD}.read_text_from_gcs", reader ):
            result = self._call( "gs://bucket/report.md" )
        self.assertIsInstance( result, PlainTextResponse )
        self.assertEqual( result.body, b"# GCS report" )
        reader.assert_called_once()

    def test_gcs_not_found_404( self ):
        """Ensures: a GCS NotFound error maps to 404."""
        reader = MagicMock( side_effect=Exception( "NotFound: no such object" ) )
        with patch( f"{_MOD}.GCS_AVAILABLE", True ), \
             patch( f"{_MOD}.read_text_from_gcs", reader ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "gs://bucket/missing.md" )
        self.assertEqual( ctx.exception.status_code, 404 )
        self.assertIn( "Report not found", ctx.exception.detail )

    def test_gcs_other_error_500( self ):
        """Ensures: a non-NotFound GCS error maps to 500."""
        reader = MagicMock( side_effect=Exception( "permission denied" ) )
        with patch( f"{_MOD}.GCS_AVAILABLE", True ), \
             patch( f"{_MOD}.read_text_from_gcs", reader ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "gs://bucket/x.md" )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Error reading from GCS", ctx.exception.detail )


class TestGetReportLocal( unittest.TestCase ):
    """
    Unit tests for `get_report` local-path arms.

    Ensures:
        - relative + absolute + /io/<other> success arms, traversal 400, 404, read 500
    """

    def setUp( self ):
        """Ensures: project root is a fixed sentinel for deterministic path math."""
        self.p_root = patch( f"{_MOD}.cu.get_project_root", return_value="/proj" )
        self.p_root.start()
        self.addCleanup( self.p_root.stop )

    def _call( self, path ):
        return asyncio.run( get_report( path=path ) )

    def test_local_relative_success( self ):
        """Ensures: a relative path under io/deep-research is read and returned."""
        with patch( f"{_MOD}.os.path.isfile", return_value=True ), \
             patch( "builtins.open", mock_open( read_data="# local report" ) ):
            result = self._call( "report.md" )
        self.assertIsInstance( result, PlainTextResponse )
        self.assertEqual( result.body, b"# local report" )

    def test_local_absolute_under_allowed_base_success( self ):
        """Ensures: an absolute path inside io/deep-research is served (absolute arm)."""
        with patch( f"{_MOD}.os.path.isfile", return_value=True ), \
             patch( "builtins.open", mock_open( read_data="# abs" ) ):
            result = self._call( "/proj/io/deep-research/x.md" )
        self.assertEqual( result.body, b"# abs" )

    def test_local_absolute_io_other_success( self ):
        """Ensures: an absolute path under io/ (but not deep-research) passes the 2nd allow-prefix arm."""
        with patch( f"{_MOD}.os.path.isfile", return_value=True ), \
             patch( "builtins.open", mock_open( read_data="# other" ) ):
            result = self._call( "/proj/io/other/x.md" )
        self.assertEqual( result.body, b"# other" )

    def test_local_traversal_400( self ):
        """Ensures: an absolute path outside all allowed bases raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( "/etc/passwd" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Invalid path", ctx.exception.detail )

    def test_local_not_found_404( self ):
        """Ensures: a valid-but-missing local file raises 404."""
        with patch( f"{_MOD}.os.path.isfile", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "missing.md" )
        self.assertEqual( ctx.exception.status_code, 404 )
        self.assertIn( "Report not found", ctx.exception.detail )

    def test_local_read_error_500( self ):
        """Ensures: an OS error while reading the file maps to 500."""
        with patch( f"{_MOD}.os.path.isfile", return_value=True ), \
             patch( "builtins.open", side_effect=OSError( "disk gone" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "report.md" )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Error reading file", ctx.exception.detail )


class TestDeepResearchHealth( unittest.TestCase ):
    """
    Unit tests for `deep_research_health`.

    Ensures:
        - reports GCS availability + local dir existence (both arms)
    """

    def test_health_dir_exists( self ):
        """Ensures: health reports exists True when the local dir is present."""
        with patch( f"{_MOD}.cu.get_project_root", return_value="/proj" ), \
             patch( f"{_MOD}.GCS_AVAILABLE", True ), \
             patch( f"{_MOD}.os.path.isdir", return_value=True ):
            result = asyncio.run( deep_research_health() )
        self.assertEqual( result[ "status" ], "ok" )
        self.assertTrue( result[ "gcs_available" ] )
        self.assertTrue( result[ "local_storage" ][ "exists" ] )
        self.assertEqual( result[ "local_storage" ][ "path" ], "/proj/io/deep-research" )

    def test_health_dir_missing( self ):
        """Ensures: health reports exists False when the local dir is absent."""
        with patch( f"{_MOD}.cu.get_project_root", return_value="/proj" ), \
             patch( f"{_MOD}.GCS_AVAILABLE", False ), \
             patch( f"{_MOD}.os.path.isdir", return_value=False ):
            result = asyncio.run( deep_research_health() )
        self.assertFalse( result[ "gcs_available" ] )
        self.assertFalse( result[ "local_storage" ][ "exists" ] )


class TestGcsImportFallback( unittest.TestCase ):
    """
    Unit test for the module-level GCS-shim `except ImportError` fallback (lines 28-30).

    The cosa venv has `cosa.utils.util_gcs` importable, so the defensive fallback
    never runs at normal import time. We force the ImportError by reloading the
    module with that one import blocked, then reload again to restore real state.
    """

    def test_import_error_sets_fallback_globals( self ):
        """Ensures: a failed util_gcs import sets GCS_AVAILABLE=False + read_text_from_gcs=None."""
        import cosa.rest.routers.deep_research as dr_mod

        real_import = builtins.__import__

        def _blocking_import( name, *args, **kwargs ):
            if name == "cosa.utils.util_gcs":
                raise ImportError( "simulated missing google-cloud-storage" )
            return real_import( name, *args, **kwargs )

        try:
            with patch( "builtins.__import__", side_effect=_blocking_import ):
                importlib.reload( dr_mod )
            self.assertFalse( dr_mod.GCS_AVAILABLE )
            self.assertIsNone( dr_mod.read_text_from_gcs )
        finally:
            # Restore the real module binding so module state reflects the live venv.
            importlib.reload( dr_mod )


def isolated_unit_test():
    """
    Run the deep-research router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestGetTodoQueue, TestSubmitResearch, TestGetReportGcs,
            TestGetReportLocal, TestDeepResearchHealth, TestGcsImportFallback,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL DEEP-RESEARCH ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME DEEP-RESEARCH ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 DEEP-RESEARCH ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Deep-research router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
