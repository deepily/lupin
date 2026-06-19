"""
Unit tests for cosa.agents.agentic_job_base.AgenticJobBase.

AgenticJobBase is the abstract base for long-running CJ Flow jobs. Tests use a
minimal concrete subclass (delegating to super() so the abstract bodies execute)
plus boundary mocking of asyncio + the voice_io notifier:

- __init__ / _generate_id / base_id        — state seeding + scoped/unscoped IDs
- abstract bodies (last_question_asked / do_all / _execute) via super() delegation
- unified-interface properties              — question / answer / job_type / created_date
- is_cacheable / request_cancel             — including the orchestrator-signal branches
- code_ran_to_completion / formatter_ran_to_completion / create_progress_group
- notify_progress / notify_completion        — running-loop vs no-loop vs ImportError vs
                                               generic-Exception, across debug on/off
- get_execution_duration_seconds            — unset vs computed
- _raise_forced_failure                     — every force_failure_mode branch
- __repr__

No real LLM / network / event-loop work runs.

Created 2026-05-31 (CoSA coverage campaign, remaining agents lane — Tiffany 💍). New file.
"""

import asyncio
import builtins
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, AsyncMock, patch

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class _ConcreteJob( AgenticJobBase ):
    """Minimal concrete job; abstract members delegate to super() to cover their bodies."""

    JOB_TYPE   = "test"
    JOB_PREFIX = "tj"

    @property
    def last_question_asked( self ):
        super().last_question_asked   # executes the abstract getter body
        return "the task"

    def do_all( self ):
        super().do_all()              # executes the abstract body
        self.state = JobState.COMPLETED
        self.answer_conversational = "done"
        return self.answer_conversational

    async def _execute( self ):
        return await super()._execute()   # executes the abstract async body


class TestAgenticJobBase( unittest.TestCase ):
    """
    Comprehensive unit tests for AgenticJobBase.

    Ensures:
        - The ABC cannot be instantiated; concrete subclasses initialize correctly
        - Every property, accessor, notification path, and failure mode is covered
    """

    def _make_job( self, debug=False, verbose=False ):
        """Construct a concrete job instance."""
        return _ConcreteJob(
            user_id="uid-1", user_email="user@example.com", session_id="sess-1",
            debug=debug, verbose=verbose
        )

    # ------------------------------------------------------------------ #
    # construction / IDs / abstract bodies                                #
    # ------------------------------------------------------------------ #

    def test_cannot_instantiate_abstract_base( self ):
        """Test the ABC refuses direct instantiation."""
        with self.assertRaises( TypeError ):
            AgenticJobBase( "u", "e@x.com", "s" )

    def test_init_seeds_default_state( self ):
        """
        Test the constructor seeds the documented default job state.

        Ensures:
            - id_hash carries the subclass prefix; queue + lifecycle fields defaulted
        """
        job = self._make_job()

        self.assertTrue( job.id_hash.startswith( "tj-" ) )
        self.assertEqual( len( job.id_hash ), 11 )
        self.assertEqual( job.push_counter, 0 )
        self.assertEqual( job.state, JobState.PENDING )
        self.assertFalse( job.is_cache_hit )
        self.assertFalse( job._cancel_requested )
        self.assertIsNone( job._orchestrator )
        self.assertEqual( job.artifacts, {} )
        self.assertIsNone( job.result )
        self.assertIsNone( job.scheduled_at )
        self.assertFalse( job.monopolize )
        self.assertIsNone( job.routing_command )
        self.assertIsNone( job.answer_conversational )
        self.assertIsInstance( job.run_date, str )

    def test_base_id_unscoped_and_scoped( self ):
        """
        Test base_id returns the bare id unscoped, and strips the ::user suffix scoped.
        """
        job = self._make_job()

        self.assertEqual( job.base_id, job.id_hash )   # unscoped

        bare = job.id_hash
        job.id_hash = f"{bare}::user-uuid"
        self.assertEqual( job.base_id, bare )           # scoped → stripped

    def test_abstract_bodies_run_via_super_delegation( self ):
        """
        Test the abstract members' bodies execute through the concrete subclass.

        Ensures:
            - last_question_asked / do_all / _execute all run (super() bodies covered)
        """
        job = self._make_job()

        self.assertEqual( job.last_question_asked, "the task" )
        self.assertEqual( job.do_all(), "done" )
        self.assertIsNone( asyncio.run( job._execute() ) )

    # ------------------------------------------------------------------ #
    # unified-interface properties                                        #
    # ------------------------------------------------------------------ #

    def test_unified_interface_properties( self ):
        """
        Test question / answer / job_type / created_date unified accessors.

        Ensures:
            - question mirrors last_question_asked
            - answer returns answer_conversational or "" ; job_type == JOB_TYPE
            - created_date == run_date
        """
        job = self._make_job()

        self.assertEqual( job.question, "the task" )
        self.assertEqual( job.answer, "" )                 # answer_conversational is None
        job.answer_conversational = "hi"
        self.assertEqual( job.answer, "hi" )
        self.assertEqual( job.job_type, "test" )
        self.assertEqual( job.created_date, job.run_date )

    def test_is_cacheable_always_false( self ):
        """Test agentic jobs are never cacheable."""
        self.assertFalse( self._make_job().is_cacheable )

    # ------------------------------------------------------------------ #
    # request_cancel                                                      #
    # ------------------------------------------------------------------ #

    def test_request_cancel_no_orchestrator( self ):
        """Test request_cancel sets the flag when no orchestrator is present."""
        job = self._make_job()
        job.request_cancel()
        self.assertTrue( job._cancel_requested )

    def test_request_cancel_signals_orchestrator( self ):
        """Test request_cancel also stops an orchestrator exposing _stop_requested."""
        job = self._make_job()
        orch = Mock()
        orch._stop_requested = False
        job._orchestrator = orch

        job.request_cancel()

        self.assertTrue( job._cancel_requested )
        self.assertTrue( orch._stop_requested )

    def test_request_cancel_orchestrator_without_stop_flag( self ):
        """Test request_cancel tolerates an orchestrator lacking _stop_requested."""
        class _Bare:
            __slots__ = ()
        job = self._make_job()
        job._orchestrator = _Bare()

        job.request_cancel()   # must not raise
        self.assertTrue( job._cancel_requested )

    # ------------------------------------------------------------------ #
    # completion / progress-group / duration                              #
    # ------------------------------------------------------------------ #

    def test_code_ran_to_completion( self ):
        """Test completion check tracks the COMPLETED state."""
        job = self._make_job()
        self.assertFalse( job.code_ran_to_completion() )
        job.state = JobState.COMPLETED
        self.assertTrue( job.code_ran_to_completion() )

    def test_formatter_ran_to_completion( self ):
        """Test formatter-completion check tracks answer_conversational presence."""
        job = self._make_job()
        self.assertFalse( job.formatter_ran_to_completion() )
        job.answer_conversational = "x"
        self.assertTrue( job.formatter_ran_to_completion() )

    def test_create_progress_group_format( self ):
        """Test create_progress_group returns a pg-prefixed 11-char id."""
        pg = self._make_job().create_progress_group()
        self.assertTrue( pg.startswith( "pg-" ) )
        self.assertEqual( len( pg ), 11 )

    def test_get_execution_duration_unset_is_zero( self ):
        """Test duration is 0.0 before start/completion timestamps are set."""
        self.assertEqual( self._make_job().get_execution_duration_seconds(), 0.0 )

    def test_get_execution_duration_computed( self ):
        """Test duration is computed from started_at / completed_at ISO timestamps."""
        job = self._make_job()
        job.started_at   = "2026-05-31T10:00:00"
        job.completed_at = "2026-05-31T10:00:05"
        self.assertEqual( job.get_execution_duration_seconds(), 5.0 )

    # ------------------------------------------------------------------ #
    # notify_progress / notify_completion                                 #
    # ------------------------------------------------------------------ #

    def _drive_notify( self, method_name, scenario, debug, job_id=None ):
        """
        Invoke a notify_* method under a controlled asyncio + voice_io scenario.

        scenario ∈ {"create_task", "run", "import_error", "exception"}.
        Returns a dict of the relevant mocks for assertion.
        """
        job        = self._make_job( debug=debug )
        mock_voice = Mock()
        mock_voice.notify = Mock( return_value=Mock() )   # not awaited (create_task/run mocked)
        out = {}

        with ExitStack() as es:
            if scenario == "import_error":
                real_import = builtins.__import__

                def fake_import( name, g=None, l=None, fromlist=(), level=0 ):
                    if name == "cosa.agents.utils" and fromlist and "voice_io" in fromlist:
                        raise ImportError( "no voice_io" )
                    return real_import( name, g, l, fromlist, level )

                es.enter_context( patch( "builtins.__import__", side_effect=fake_import ) )
            else:
                es.enter_context( patch( "cosa.agents.utils.voice_io", mock_voice, create=True ) )
                out[ "create_task" ] = es.enter_context( patch( "asyncio.create_task" ) )
                out[ "run" ]         = es.enter_context( patch( "asyncio.run" ) )
                grl                  = es.enter_context( patch( "asyncio.get_running_loop" ) )
                if scenario == "create_task":
                    grl.return_value = Mock()
                elif scenario == "run":
                    grl.side_effect = RuntimeError( "no running loop" )
                elif scenario == "exception":
                    grl.side_effect = RuntimeError( "no running loop" )
                    out[ "run" ].side_effect = Exception( "notify boom" )

            method = getattr( job, method_name )
            if method_name == "notify_progress":
                method( "progress msg", job_id=job_id )
            else:
                method( "done msg", abstract="abs", job_id=job_id )

        return out

    def test_notify_progress_running_loop_creates_task( self ):
        """Test notify_progress schedules a task when an event loop is running."""
        out = self._drive_notify( "notify_progress", "create_task", debug=False, job_id=None )
        out[ "create_task" ].assert_called_once()

    def test_notify_progress_no_loop_uses_asyncio_run( self ):
        """Test notify_progress falls back to asyncio.run with no running loop."""
        out = self._drive_notify( "notify_progress", "run", debug=False, job_id="custom-id" )
        out[ "run" ].assert_called_once()

    def test_notify_progress_import_error_swallowed_both_debug( self ):
        """Test a voice_io ImportError is swallowed (both debug arms)."""
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                self._drive_notify( "notify_progress", "import_error", debug=debug )   # must not raise

    def test_notify_progress_generic_exception_swallowed_both_debug( self ):
        """Test a generic notify error is swallowed (both debug arms)."""
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                self._drive_notify( "notify_progress", "exception", debug=debug )       # must not raise

    def test_notify_completion_running_loop_creates_task( self ):
        """Test notify_completion schedules a task when an event loop is running."""
        out = self._drive_notify( "notify_completion", "create_task", debug=False, job_id=None )
        out[ "create_task" ].assert_called_once()

    def test_notify_completion_no_loop_uses_asyncio_run( self ):
        """Test notify_completion falls back to asyncio.run with no running loop."""
        out = self._drive_notify( "notify_completion", "run", debug=False, job_id="custom-id" )
        out[ "run" ].assert_called_once()

    def test_notify_completion_import_error_swallowed_both_debug( self ):
        """Test a voice_io ImportError is swallowed by notify_completion (both debug arms)."""
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                self._drive_notify( "notify_completion", "import_error", debug=debug )

    def test_notify_completion_generic_exception_swallowed_both_debug( self ):
        """Test a generic error is swallowed by notify_completion (both debug arms)."""
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                self._drive_notify( "notify_completion", "exception", debug=debug )

    # ------------------------------------------------------------------ #
    # _raise_forced_failure (every mode)                                  #
    # ------------------------------------------------------------------ #

    def test_raise_forced_failure_all_modes( self ):
        """
        Test _raise_forced_failure raises the matching exception per force_failure_mode.

        Ensures:
            - code_bug → KeyError; infra_timeout → TimeoutError; rate_limit → Exception;
              unknown → ValueError; voice_io.notify awaited each time
        """
        cases = [
            ( "code_bug",      KeyError ),
            ( "infra_timeout", asyncio.TimeoutError ),
            ( "rate_limit",    Exception ),
            ( "something_else", ValueError ),
        ]
        for mode, exc_type in cases:
            with self.subTest( mode=mode ):
                job = self._make_job()
                job.force_failure_mode = mode
                mock_voice = Mock()
                mock_voice.notify = AsyncMock()

                with self.assertRaises( exc_type ):
                    asyncio.run( job._raise_forced_failure( mock_voice ) )
                mock_voice.notify.assert_awaited()

    # ------------------------------------------------------------------ #
    # __repr__                                                            #
    # ------------------------------------------------------------------ #

    def test_repr_includes_class_id_and_state( self ):
        """Test __repr__ embeds the class name, id, and state value."""
        job = self._make_job()
        r = repr( job )

        self.assertIn( "_ConcreteJob", r )
        self.assertIn( job.id_hash, r )
        self.assertIn( job.state.value, r )


if __name__ == "__main__":
    unittest.main()
