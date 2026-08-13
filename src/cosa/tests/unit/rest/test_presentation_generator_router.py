"""
Unit tests for the Presentation Generator router (`cosa.rest.routers.presentation_generator`).

Covers:
- `get_todo_queue` / `get_websocket_mgr` — dual-key `lupin_app.main` reads.
- `validate_source_path` — within-root (absolute + relative), escape, and the
  exact-project-root edge.
- `submit_presentation_job` — empty-source 400, path-escape 403, file-not-found 404,
  render_only-requested-on-non-YAML 400, YAML auto-detect render_only success
  (absolute path arm), full non-render success (relative path arm + every args arm:
  target_duration_minutes / dry_run / force_failure_mode / audience / theme /
  content_model + scheduled_at + monopolize), and factory-None 500.

Zero external dependencies — create_agentic_job, user_job_tracker, the queue, and
filesystem probes (validate_source_path / os.path.exists / cu.get_project_root) are
all boundary-mocked. No real jobs, no LLM, no queue, no network. Auth bypassed by
passing current_user explicitly.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import asyncio
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.presentation_generator import (
    get_todo_queue,
    get_websocket_mgr,
    validate_source_path,
    submit_presentation_job,
    PresentationSubmitRequest,
    PresentationSubmitResponse,
)


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _job( id_hash="init_hash" ):
    """A PresentationGeneratorJob stand-in."""
    job = MagicMock()
    job.id_hash = id_hash
    return job


class TestDependencies( unittest.TestCase ):
    """
    Ensures:
        - get_todo_queue / get_websocket_mgr read the right attrs off lupin_app.main
    """

    def test_get_todo_queue( self ):
        """Ensures: get_todo_queue returns main_module.jobs_todo_queue."""
        mock_main = MagicMock()
        mock_main.jobs_todo_queue = "Q"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_todo_queue(), "Q" )

    def test_get_websocket_mgr( self ):
        """Ensures: get_websocket_mgr returns main_module.websocket_manager."""
        mock_main = MagicMock()
        mock_main.websocket_manager = "WS"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_websocket_mgr(), "WS" )


class TestValidateSourcePath( unittest.TestCase ):
    """
    Unit tests for `validate_source_path`.

    Ensures:
        - within-root absolute + relative → True; escape → False; ==root → True
    """

    def setUp( self ):
        """Ensures: project root is a fixed sentinel for deterministic realpath math."""
        self.p = patch( "cosa.rest.routers.presentation_generator.cu.get_project_root",
                        return_value="/proj" )
        self.p.start()
        self.addCleanup( self.p.stop )

    def test_absolute_within_root_true( self ):
        """Ensures: an absolute project-relative path inside root resolves True."""
        self.assertTrue( validate_source_path( "/src/rnd/report.md" ) )

    def test_relative_within_root_true( self ):
        """Ensures: a relative path inside root resolves True."""
        self.assertTrue( validate_source_path( "src/rnd/report.md" ) )

    def test_escape_false( self ):
        """Ensures: a traversal path that escapes root resolves False."""
        self.assertFalse( validate_source_path( "../../etc/passwd" ) )

    def test_equals_root_true( self ):
        """Ensures: a path resolving exactly to project root resolves True (== arm)."""
        self.assertTrue( validate_source_path( "/" ) )


class TestSubmitPresentationJob( unittest.TestCase ):
    """
    Unit tests for `submit_presentation_job`.

    Requires:
        - create_agentic_job + user_job_tracker + filesystem probes boundary-mocked

    Ensures:
        - 400/403/404 validations, YAML auto-detect, full success, factory-None 500
    """

    def setUp( self ):
        """Ensures: a default authenticated user + mocked queue + fixed project root."""
        self.user  = { "uid": "u1", "email": "u@test.com", "session_id": "sess-1" }
        self.queue = MagicMock()
        self.ws    = MagicMock()
        self.p_root = patch( "cosa.rest.routers.presentation_generator.cu.get_project_root",
                             return_value="/proj" )
        self.p_root.start()
        self.addCleanup( self.p_root.stop )

    def _call( self, body ):
        return asyncio.run( submit_presentation_job(
            request       = body,
            current_user  = self.user,
            todo_queue    = self.queue,
            websocket_mgr = self.ws,
        ) )

    def test_empty_source_400( self ):
        """Ensures: a whitespace-only source_path raises 400 after strip."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( PresentationSubmitRequest( source_path="   " ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "source_path cannot be empty", ctx.exception.detail )

    def test_path_escape_403( self ):
        """Ensures: a path that escapes project root raises 403."""
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PresentationSubmitRequest( source_path="../../etc/passwd" ) )
        self.assertEqual( ctx.exception.status_code, 403 )
        self.assertIn( "escapes project root", ctx.exception.detail )

    def test_file_not_found_404( self ):
        """Ensures: a valid-but-missing source raises 404."""
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.os.path.exists",
                    return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PresentationSubmitRequest( source_path="io/missing.md" ) )
        self.assertEqual( ctx.exception.status_code, 404 )
        self.assertIn( "Source file not found", ctx.exception.detail )

    def test_absolute_path_under_root_400( self ):
        """Ensures: an absolute source_path under the project root is rejected
        LOUDLY with 400 (not silently double-rooted into a misleading 404)."""
        with self.assertRaises( HTTPException ) as ctx:
            # cu.get_project_root() is mocked to "/proj" in setUp; a caller sending
            # "/proj/src/..." (an absolute FS path, not a repo-relative "/src/...")
            # would otherwise double-root to "/proj/proj/src/..." → bogus 404.
            self._call( PresentationSubmitRequest( source_path="/proj/src/tests/fixtures/x.yaml" ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "must be repo-relative", ctx.exception.detail )

    def test_source_path_equals_root_400( self ):
        """Ensures: source_path exactly equal to the project root is rejected 400."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( PresentationSubmitRequest( source_path="/proj" ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "must be repo-relative", ctx.exception.detail )

    def test_render_only_requested_non_yaml_400( self ):
        """Ensures: render_only=True on a non-YAML source raises 400."""
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.os.path.exists",
                    return_value=True ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PresentationSubmitRequest( source_path="io/x.md", render_only=True ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "render_only mode requires", ctx.exception.detail )

    def test_success_yaml_render_only_absolute( self ):
        """Ensures: a .yaml source auto-enables render_only; absolute-path normalize arm."""
        self.queue.size.return_value = 3
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "pr-yaml"
        job = _job()
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.os.path.exists",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.create_agentic_job",
                    return_value=job ) as m_create, \
             patch( "cosa.rest.routers.presentation_generator.user_job_tracker", tracker ):
            result = self._call( PresentationSubmitRequest( source_path="/io/deck.yaml" ) )

        self.assertIsInstance( result, PresentationSubmitResponse )
        self.assertEqual( result.job_id, "pr-yaml" )
        self.assertEqual( result.queue_position, 3 )
        self.assertEqual( result.status, "queued" )
        _, kwargs = m_create.call_args
        self.assertTrue( kwargs[ "args_dict" ][ "render_only" ] )         # auto-detected from .yaml
        self.assertEqual( kwargs[ "args_dict" ][ "source" ], "/proj/io/deck.yaml" )  # absolute arm
        self.queue.push.assert_called_once()

    def test_success_full_non_render_relative( self ):
        """Ensures: relative-path arm + every optional args arm + scheduling thread through."""
        self.queue.size.return_value = 6
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "pr-full"
        job = _job()
        body = PresentationSubmitRequest(
            source_path             = "io/source.md",
            target_duration_minutes = 15,
            target_slide_count      = 40,
            audience                = "general",
            theme                   = "default",
            content_model           = "claude-sonnet-4-6",
            dry_run                 = True,
            force_failure_mode      = "code_bug",
            scheduled_at            = "2026-01-01T00:00:00",
            monopolize              = True,
        )
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.os.path.exists",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.create_agentic_job",
                    return_value=job ) as m_create, \
             patch( "cosa.rest.routers.presentation_generator.user_job_tracker", tracker ):
            result = self._call( body )

        self.assertEqual( result.job_id, "pr-full" )
        _, kwargs = m_create.call_args
        ad = kwargs[ "args_dict" ]
        self.assertEqual( ad[ "source" ], "/proj/io/source.md" )          # relative arm
        self.assertNotIn( "render_only", ad )                             # non-yaml, not requested
        self.assertEqual( ad[ "target_duration_minutes" ], "15" )
        self.assertEqual( ad[ "target_slide_count" ], "40" )
        self.assertTrue( ad[ "dry_run" ] )
        self.assertEqual( ad[ "force_failure_mode" ], "code_bug" )
        self.assertEqual( ad[ "audience" ], "general" )
        self.assertEqual( ad[ "theme" ], "default" )
        self.assertEqual( ad[ "content_model" ], "claude-sonnet-4-6" )
        self.assertEqual( job.scheduled_at, "2026-01-01T00:00:00" )
        self.assertTrue( job.monopolize )

    def test_parent_id_hash_stamps_lineage( self ):
        """5ed4f187 (mirrors 3a14292b): parent_id_hash threads onto job.spawned_by_id_hash
        so the consumer's Gate B admits this child through a monopolizing test-suite's intake
        hold instead of starving it 900s as a foreign writer. CONTROL: without the endpoint's
        stamp line this assertion fails (job.spawned_by_id_hash never set to the parent)."""
        self.queue.size.return_value = 1
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "pr-child"
        job = _job()
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.os.path.exists",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.create_agentic_job",
                    return_value=job ), \
             patch( "cosa.rest.routers.presentation_generator.user_job_tracker", tracker ):
            self._call( PresentationSubmitRequest( source_path="io/deck.md", parent_id_hash="ts-parent" ) )
        self.assertEqual( job.spawned_by_id_hash, "ts-parent" )

    def test_factory_none_500( self ):
        """Ensures: create_agentic_job None → 500."""
        with patch( "cosa.rest.routers.presentation_generator.validate_source_path",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.os.path.exists",
                    return_value=True ), \
             patch( "cosa.rest.routers.presentation_generator.create_agentic_job",
                    return_value=None ), \
             patch( "cosa.rest.routers.presentation_generator.user_job_tracker", MagicMock() ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PresentationSubmitRequest( source_path="io/x.md" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to create presentation job", ctx.exception.detail )


def isolated_unit_test():
    """
    Run the presentation-generator router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in ( TestDependencies, TestValidateSourcePath, TestSubmitPresentationJob ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL PRESENTATION-GENERATOR ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PRESENTATION-GENERATOR ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 PRESENTATION-GENERATOR ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Presentation-generator router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
