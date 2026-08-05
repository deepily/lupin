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

from cosa.rest.routers.deep_research import (
    get_todo_queue,
    submit_research,
    get_report,
    deep_research_health,
    DeepResearchSubmitRequest,
    DeepResearchSubmitResponse,
)

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


class TestGetTodoQueue( unittest.TestCase ):
    """
    Ensures:
        - get_todo_queue returns main_module.jobs_todo_queue
    """

    def test_returns_main_module_todo_queue( self ):
        """Ensures: dependency reads jobs_todo_queue off lupin_app.main."""
        mock_main = MagicMock()
        mock_main.jobs_todo_queue = "Q"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_todo_queue(), "Q" )


class TestSubmitResearch( unittest.TestCase ):
    """
    Unit tests for `submit_research`.

    Requires:
        - DeepResearchJob import, create_agentic_job, user_job_tracker boundary-mocked

    Ensures:
        - 400 validations, session fallback, success arms, factory-None 500, push 500
    """

    def setUp( self ):
        """Ensures: a default authenticated user + mocked queue per test."""
        self.user  = { "uid": "user_1234567890", "email": "u@test.com" }
        self.queue = MagicMock()

    def _call( self, body ):
        return asyncio.run( submit_research(
            request_body = body,
            current_user = self.user,
            todo_queue   = self.queue,
        ) )

    def test_missing_uid_400( self ):
        """Ensures: a token without uid raises 400 (before the try block)."""
        self.user = { "email": "u@test.com" }
        with self.assertRaises( HTTPException ) as ctx:
            self._call( DeepResearchSubmitRequest( query="q" ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "User ID not found", ctx.exception.detail )

    def test_missing_email_400( self ):
        """Ensures: a token without email raises 400 (before the try block)."""
        self.user = { "uid": "user_1234567890" }
        with self.assertRaises( HTTPException ) as ctx:
            self._call( DeepResearchSubmitRequest( query="q" ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "User email not found", ctx.exception.detail )

    def test_success_minimal_session_fallback( self ):
        """Ensures: minimal body queues a job; websocket_id None → api-<uid8> fallback."""
        self.queue.size.return_value = 2
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "dr-scoped"
        with patch( f"{_MOD}.create_agentic_job", return_value=_job() ) as m_create, \
             patch( f"{_MOD}.user_job_tracker", tracker ):
            result = self._call( DeepResearchSubmitRequest( query="state of AI" ) )

        self.assertIsInstance( result, DeepResearchSubmitResponse )
        self.assertEqual( result.status, "queued" )
        self.assertEqual( result.job_id, "dr-scoped" )
        self.assertEqual( result.queue_position, 2 )
        self.assertIn( "Deep research job queued", result.message )
        _, kwargs = m_create.call_args
        self.assertEqual( kwargs[ "session_id" ], "api-user_123" )
        self.assertEqual( kwargs[ "args_dict" ], { "query": "state of AI" } )
        self.queue.push.assert_called_once()

    def test_success_all_optional_arms( self ):
        """Ensures: budget + dry_run + force_failure_mode + audience + audience_context + lead_model + scheduling thread through."""
        self.queue.size.return_value = 5
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "dr-2"
        job = _job()
        body = DeepResearchSubmitRequest(
            query              = "topic",
            budget             = 3.0,
            websocket_id       = "ws-abc",
            lead_model         = "claude-opus-4-8",
            dry_run            = True,
            force_failure_mode = "rate_limit",
            audience           = "expert",
            audience_context   = "researchers",
            scheduled_at       = "2026-01-01T00:00:00",
            monopolize         = True,
        )
        with patch( f"{_MOD}.create_agentic_job", return_value=job ) as m_create, \
             patch( f"{_MOD}.user_job_tracker", tracker ):
            result = self._call( body )

        self.assertEqual( result.status, "queued" )
        self.assertEqual( result.job_id, "dr-2" )
        _, kwargs = m_create.call_args
        ad = kwargs[ "args_dict" ]
        self.assertEqual( kwargs[ "session_id" ], "ws-abc" )              # provided websocket_id
        self.assertEqual( ad[ "budget" ], "3.0" )
        self.assertTrue( ad[ "dry_run" ] )
        self.assertEqual( ad[ "force_failure_mode" ], "rate_limit" )
        self.assertEqual( ad[ "audience" ], "expert" )
        self.assertEqual( ad[ "audience_context" ], "researchers" )
        self.assertEqual( job.lead_model, "claude-opus-4-8" )            # applied post-factory
        self.assertEqual( job.scheduled_at, "2026-01-01T00:00:00" )
        self.assertTrue( job.monopolize )

    def test_parent_id_hash_stamps_lineage( self ):
        """5ed4f187 (mirrors 3a14292b): parent_id_hash threads onto job.spawned_by_id_hash so the
        consumer's Gate B admits this child through a monopolizing test-suite's intake hold instead
        of starving it 900s. CONTROL: without the endpoint stamp this fails (never set to parent)."""
        self.queue.size.return_value = 1
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "dr-child"
        job = _job()
        with patch( f"{_MOD}.create_agentic_job", return_value=job ), \
             patch( f"{_MOD}.user_job_tracker", tracker ):
            self._call( DeepResearchSubmitRequest( query="state of AI", parent_id_hash="ts-parent" ) )
        self.assertEqual( job.spawned_by_id_hash, "ts-parent" )

    def test_factory_none_500( self ):
        """Ensures: create_agentic_job None → 500 (inner HTTPException wrapped by broad except)."""
        with patch( f"{_MOD}.create_agentic_job", return_value=None ), \
             patch( f"{_MOD}.user_job_tracker", MagicMock() ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( DeepResearchSubmitRequest( query="q" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to submit research job", ctx.exception.detail )

    def test_push_failure_500( self ):
        """Ensures: an exception during job push maps to 500."""
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "h"
        self.queue.push.side_effect = RuntimeError( "queue down" )
        with patch( f"{_MOD}.create_agentic_job", return_value=_job() ), \
             patch( f"{_MOD}.user_job_tracker", tracker ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( DeepResearchSubmitRequest( query="q" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to submit research job", ctx.exception.detail )


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
