"""
Unit tests for the unified `init_watchdogs()` facade in cosa.rest.watchdogs.

Session 1cfcdf73 (2026-04-10): Replaces the old single-watchdog init in main.py
with a single call that brings up both BFE (DeadQueueWatchdog) and TFE
(TestSuiteCompletionWatchdog) singletons. The original bug was that main.py
only called BFE's init, so TFE's `get_watchdog()` returned None and the
done-queue hook silently no-op'd.
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.watchdogs import init_watchdogs
from cosa.rest import dead_queue_watchdog
from cosa.rest import test_suite_completion_watchdog


def _make_config_mgr( bfe_enabled: bool = True, tfe_enabled: bool = True ):
    """Build a config_mgr that returns toggleable enabled-states for both watchdogs."""
    mock = MagicMock()
    def _get( key, default=None, return_type="string" ):
        if key == "auto fix enabled":
            return bfe_enabled
        if key == "test fix expediter auto fix enabled":
            return tfe_enabled
        if key == "auto fix eligible job types":
            return "presentation, deep_research, podcast, test_suite"
        if key == "test fix expediter max cluster seed failures":
            return 50
        if key == "auto fix max attempts per job":
            return 3
        if key == "auto fix max cost usd":
            return 10.0
        if key == "auto fix max wall clock seconds":
            return 1800
        if key == "auto fix cooldown seconds":
            return 60
        return default
    mock.get = MagicMock( side_effect=_get )
    return mock


class TestInitWatchdogsHappyPath:

    def setup_method( self ):
        dead_queue_watchdog._watchdog_instance = None
        test_suite_completion_watchdog.reset_watchdog()

    def teardown_method( self ):
        dead_queue_watchdog._watchdog_instance = None
        test_suite_completion_watchdog.reset_watchdog()

    def test_returns_both_watchdogs( self ):
        cm    = _make_config_mgr( bfe_enabled=True, tfe_enabled=True )
        queue = MagicMock()
        bfe, tfe = init_watchdogs( cm, queue, debug=False )

        assert bfe is not None
        assert tfe is not None
        assert isinstance( bfe, dead_queue_watchdog.DeadQueueWatchdog )
        assert isinstance( tfe, test_suite_completion_watchdog.TestSuiteCompletionWatchdog )

    def test_singletons_populated_after_init( self ):
        """After init_watchdogs, get_watchdog() on each module returns the live instance."""
        cm    = _make_config_mgr()
        queue = MagicMock()
        bfe, tfe = init_watchdogs( cm, queue, debug=False )

        assert dead_queue_watchdog.get_watchdog() is bfe
        assert test_suite_completion_watchdog.get_watchdog() is tfe

    def test_bfe_and_tfe_share_todo_queue( self ):
        """Both watchdogs receive the same TodoFifoQueue reference for spawning jobs."""
        cm    = _make_config_mgr()
        queue = MagicMock()
        bfe, tfe = init_watchdogs( cm, queue, debug=False )

        assert bfe.todo_queue is queue
        assert tfe.todo_queue is queue

    def test_enabled_flags_propagate_from_config( self ):
        cm = _make_config_mgr( bfe_enabled=False, tfe_enabled=True )
        bfe, tfe = init_watchdogs( cm, MagicMock(), debug=False )
        assert bfe.enabled is False
        assert tfe.enabled is True

        cm = _make_config_mgr( bfe_enabled=True, tfe_enabled=False )
        # reset singletons so the next init reads fresh state
        dead_queue_watchdog._watchdog_instance = None
        test_suite_completion_watchdog.reset_watchdog()
        bfe, tfe = init_watchdogs( cm, MagicMock(), debug=False )
        assert bfe.enabled is True
        assert tfe.enabled is False

    def test_debug_flag_propagated( self ):
        cm = _make_config_mgr()
        bfe, tfe = init_watchdogs( cm, MagicMock(), debug=True )
        assert bfe.debug is True
        assert tfe.debug is True


class TestInitWatchdogsResilience:
    """One watchdog construction failing must NOT prevent the other from initializing."""

    def setup_method( self ):
        dead_queue_watchdog._watchdog_instance = None
        test_suite_completion_watchdog.reset_watchdog()

    def teardown_method( self ):
        dead_queue_watchdog._watchdog_instance = None
        test_suite_completion_watchdog.reset_watchdog()

    def test_bfe_init_failure_does_not_block_tfe( self ):
        cm    = _make_config_mgr()
        queue = MagicMock()
        with patch(
            "cosa.rest.watchdogs.init_bfe_watchdog",
            side_effect=RuntimeError( "bfe boom" ),
        ):
            bfe, tfe = init_watchdogs( cm, queue, debug=False )

        assert bfe is None
        assert tfe is not None
        assert isinstance( tfe, test_suite_completion_watchdog.TestSuiteCompletionWatchdog )

    def test_tfe_init_failure_does_not_block_bfe( self ):
        cm    = _make_config_mgr()
        queue = MagicMock()
        with patch(
            "cosa.rest.watchdogs.init_tfe_watchdog",
            side_effect=RuntimeError( "tfe boom" ),
        ):
            bfe, tfe = init_watchdogs( cm, queue, debug=False )

        assert bfe is not None
        assert tfe is None
        assert isinstance( bfe, dead_queue_watchdog.DeadQueueWatchdog )

    def test_both_init_failures_returns_two_nones( self ):
        cm    = _make_config_mgr()
        queue = MagicMock()
        with patch(
            "cosa.rest.watchdogs.init_bfe_watchdog",
            side_effect=RuntimeError( "bfe boom" ),
        ), patch(
            "cosa.rest.watchdogs.init_tfe_watchdog",
            side_effect=RuntimeError( "tfe boom" ),
        ):
            bfe, tfe = init_watchdogs( cm, queue, debug=False )

        assert bfe is None
        assert tfe is None
