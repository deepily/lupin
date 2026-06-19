"""
Unit tests for cosa.agents.test_harness.mock_job.MockAgenticJob.

MockAgenticJob is the queue-UI test double — a long-running AgenticJobBase that
sleeps + emits notifications without inference cost. Tests mock random (for
deterministic parameter rolls), use fixed_sleep=0.0, and mock the voice_io
notifier so do_all/_execute run instantly with no real sleep or network:

- __init__ / _randomize_parameters — fixed vs random iterations/sleep, will-fail roll
- _get_phase_message               — cycling through phase messages
- _create_mock_artifacts           — duration from timestamps vs estimate; artifacts/cost
- last_question_asked              — description vs default
- do_all                           — success (COMPLETED + artifacts) and failure (FAILED)
- _execute                         — covered via do_all (success loop + failure raise)
- _send_notification               — success / ImportError / generic-Exception (debug arms)

Created 2026-05-31 (CoSA coverage campaign, test_harness package — Tiffany 💍). New file.
"""

import asyncio
import builtins
import unittest
from unittest.mock import Mock, AsyncMock, patch

from cosa.agents.test_harness.mock_job import MockAgenticJob
from cosa.rest.job_state import JobState


class TestMockAgenticJob( unittest.TestCase ):
    """
    Comprehensive unit tests for MockAgenticJob.

    Ensures:
        - Parameter randomization, artifacts, lifecycle, and notifications are covered
          with full boundary isolation (no real sleep / network / inference).
    """

    def _make_job( self, **kwargs ):
        """Construct a MockAgenticJob with sensible identity defaults."""
        params = dict( user_id="u", user_email="e@x.com", session_id="s" )
        params.update( kwargs )
        return MockAgenticJob( **params )

    # ------------------------------------------------------------------ #
    # __init__ / _randomize_parameters                                    #
    # ------------------------------------------------------------------ #

    def test_init_fixed_params_no_failure( self ):
        """
        Test construction with fixed iterations/sleep and zero failure probability.

        Ensures:
            - Fixed values used; will_fail False → fail_at_iteration -1
            - id_hash carries the mock- prefix; results start unpopulated
        """
        job = self._make_job( fixed_iterations=5, fixed_sleep=0.1, failure_probability=0.0 )

        self.assertEqual( job.iterations, 5 )
        self.assertEqual( job.sleep_seconds, 0.1 )
        self.assertFalse( job.will_fail )
        self.assertEqual( job.fail_at_iteration, -1 )
        self.assertTrue( job.id_hash.startswith( "mock-" ) )
        self.assertIsNone( job.report_path )

    def test_randomize_random_params_no_failure( self ):
        """
        Test random iteration/sleep selection when no fixed overrides are given.

        Ensures:
            - random.randint / random.uniform drive iterations / sleep
            - A roll above the probability leaves will_fail False
        """
        with patch( "cosa.agents.test_harness.mock_job.random" ) as mr:
            mr.randint.return_value  = 4
            mr.uniform.return_value  = 2.5
            mr.random.return_value   = 0.9
            job = self._make_job( failure_probability=0.5 )

        self.assertEqual( job.iterations, 4 )
        self.assertEqual( job.sleep_seconds, 2.5 )
        self.assertFalse( job.will_fail )
        self.assertEqual( job.fail_at_iteration, -1 )

    def test_randomize_will_fail_picks_iteration( self ):
        """
        Test the failure roll selects a random fail-at iteration.

        Ensures:
            - A roll below the probability sets will_fail True
            - fail_at_iteration is drawn within [1, iterations]
        """
        with patch( "cosa.agents.test_harness.mock_job.random" ) as mr:
            mr.randint.side_effect = [ 4, 2 ]   # iterations=4, then fail_at=2
            mr.uniform.return_value = 1.0
            mr.random.return_value  = 0.0       # < probability → will_fail
            job = self._make_job( failure_probability=1.0 )

        self.assertTrue( job.will_fail )
        self.assertEqual( job.fail_at_iteration, 2 )

    def test_get_phase_message_cycles( self ):
        """
        Test _get_phase_message cycles through PHASE_MESSAGES modulo length.

        Ensures:
            - Index 0 and index len() map to the same message
        """
        job = self._make_job( fixed_iterations=3, fixed_sleep=0.0 )
        n   = len( job.PHASE_MESSAGES )

        self.assertEqual( job._get_phase_message( 0 ), job.PHASE_MESSAGES[ 0 ] )
        self.assertEqual( job._get_phase_message( n ), job.PHASE_MESSAGES[ 0 ] )

    # ------------------------------------------------------------------ #
    # _create_mock_artifacts                                              #
    # ------------------------------------------------------------------ #

    def test_create_mock_artifacts_with_timestamps( self ):
        """
        Test artifact creation computes duration from start/completed timestamps.

        Ensures:
            - duration derived from the ISO timestamps; artifacts + cost populated
        """
        job = self._make_job( fixed_iterations=3, fixed_sleep=2.0 )
        job.started_at   = "2026-05-31T10:00:00"
        job.completed_at = "2026-05-31T10:00:06"

        with patch( "cosa.agents.test_harness.mock_job.random.randint", return_value=1000 ):
            job._create_mock_artifacts()

        self.assertIn( job.id_hash, job.report_path )
        self.assertIn( "3 phases", job.abstract )
        self.assertEqual( job.artifacts[ "report_path" ], job.report_path )
        self.assertEqual( job.cost_summary[ "duration_seconds" ], 6.0 )
        self.assertEqual( job.cost_summary[ "total_cost_usd" ], 0.0 )

    def test_create_mock_artifacts_estimates_duration_without_timestamps( self ):
        """
        Test artifact creation estimates duration when timestamps are unset.

        Ensures:
            - duration falls back to iterations * sleep_seconds
        """
        job = self._make_job( fixed_iterations=3, fixed_sleep=2.0 )   # started/completed None

        with patch( "cosa.agents.test_harness.mock_job.random.randint", return_value=1000 ):
            job._create_mock_artifacts()

        self.assertEqual( job.cost_summary[ "duration_seconds" ], 6.0 )   # 3 * 2.0

    # ------------------------------------------------------------------ #
    # last_question_asked                                                 #
    # ------------------------------------------------------------------ #

    def test_last_question_asked_with_description( self ):
        """Test the display string uses a custom description when provided."""
        job = self._make_job( fixed_iterations=4, description="Quarterly review" )
        self.assertEqual( job.last_question_asked, "[Mock] Quarterly review" )

    def test_last_question_asked_default( self ):
        """Test the display string falls back to a phase-count summary."""
        job = self._make_job( fixed_iterations=4 )
        self.assertEqual( job.last_question_asked, "[Mock] Test job with 4 phases" )

    # ------------------------------------------------------------------ #
    # do_all (covers _execute success + failure)                          #
    # ------------------------------------------------------------------ #

    def test_do_all_success( self ):
        """
        Test do_all runs the phases, completes, and builds artifacts.

        Ensures:
            - state COMPLETED; answer_conversational set; artifacts populated
            - voice_io notifications are issued via the (mocked) notifier
        """
        job = self._make_job( fixed_iterations=2, fixed_sleep=0.0, failure_probability=0.0, debug=True )

        mock_voice = Mock()
        mock_voice.notify = AsyncMock()
        with patch( "cosa.agents.deep_research.voice_io", mock_voice, create=True ), \
             patch( "cosa.agents.test_harness.mock_job.random.randint", return_value=1000 ):
            result = job.do_all()

        self.assertEqual( job.state, JobState.COMPLETED )
        self.assertEqual( job.answer_conversational, result )
        self.assertIn( "completed successfully", result )
        self.assertIsNotNone( job.artifacts[ "report_path" ] )
        self.assertTrue( mock_voice.notify.await_count >= 1 )

    def test_do_all_failure_sets_failed_state( self ):
        """
        Test do_all captures a simulated failure into the FAILED state.

        Ensures:
            - A will_fail job raises inside _execute → state FAILED, error set
            - The conversational answer reports the failure
        """
        job = self._make_job( fixed_iterations=2, fixed_sleep=0.0, failure_probability=1.0, debug=True )

        mock_voice = Mock()
        mock_voice.notify = AsyncMock()
        with patch( "cosa.agents.deep_research.voice_io", mock_voice, create=True ):
            result = job.do_all()

        self.assertEqual( job.state, JobState.FAILED )
        self.assertIn( "Mock job failed", result )
        self.assertTrue( job.error )

    def test_do_all_success_no_debug( self ):
        """Test do_all success path with debug off (covers the debug-off trace arms)."""
        job = self._make_job( fixed_iterations=1, fixed_sleep=0.0, failure_probability=0.0, debug=False )

        mock_voice = Mock()
        mock_voice.notify = AsyncMock()
        with patch( "cosa.agents.deep_research.voice_io", mock_voice, create=True ), \
             patch( "cosa.agents.test_harness.mock_job.random.randint", return_value=1000 ):
            result = job.do_all()

        self.assertEqual( job.state, JobState.COMPLETED )
        self.assertIn( "completed successfully", result )

    def test_do_all_failure_no_debug( self ):
        """Test do_all failure path with debug off (covers the debug-off failure arm)."""
        job = self._make_job( fixed_iterations=2, fixed_sleep=0.0, failure_probability=1.0, debug=False )

        mock_voice = Mock()
        mock_voice.notify = AsyncMock()
        with patch( "cosa.agents.deep_research.voice_io", mock_voice, create=True ):
            result = job.do_all()

        self.assertEqual( job.state, JobState.FAILED )
        self.assertIn( "Mock job failed", result )

    # ------------------------------------------------------------------ #
    # _send_notification                                                  #
    # ------------------------------------------------------------------ #

    def test_send_notification_success( self ):
        """
        Test _send_notification awaits voice_io.notify with the job id.

        Ensures:
            - The notifier is awaited once
        """
        job = self._make_job( fixed_iterations=1 )
        mock_voice = Mock()
        mock_voice.notify = AsyncMock()

        with patch( "cosa.agents.deep_research.voice_io", mock_voice, create=True ):
            asyncio.run( job._send_notification( "hello", priority="low" ) )

        mock_voice.notify.assert_awaited_once()

    def test_send_notification_import_error_swallowed_both_debug( self ):
        """
        Test a voice_io ImportError is swallowed by _send_notification (both debug arms).
        """
        real_import = builtins.__import__

        def fake_import( name, g=None, l=None, fromlist=(), level=0 ):
            if name == "cosa.agents.deep_research" and fromlist and "voice_io" in fromlist:
                raise ImportError( "no voice_io" )
            return real_import( name, g, l, fromlist, level )

        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                job = self._make_job( fixed_iterations=1, debug=debug )
                with patch( "builtins.__import__", side_effect=fake_import ):
                    asyncio.run( job._send_notification( "hi" ) )   # must not raise

    def test_send_notification_generic_exception_swallowed_both_debug( self ):
        """
        Test a notifier error is swallowed by _send_notification (both debug arms).
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                job = self._make_job( fixed_iterations=1, debug=debug )
                mock_voice = Mock()
                mock_voice.notify = AsyncMock( side_effect=Exception( "notify boom" ) )
                with patch( "cosa.agents.deep_research.voice_io", mock_voice, create=True ):
                    asyncio.run( job._send_notification( "hi" ) )   # must not raise


if __name__ == "__main__":
    unittest.main()
