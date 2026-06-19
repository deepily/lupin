"""
Unit tests for the thin BFE wiring modules:
  - voice_io.py     : configures + re-exports cosa.agents.utils.voice_io;
                      reconfigure() re-binds the core module to BFE's cosa_interface
  - plan_writer.py  : backwards-compat shim re-exporting shared.plan_writer.PlanWriter
  - __init__.py     : package aggregator (__all__ + __version__)

The core voice_io.configure() boundary is mocked so reconfigure() is verified
by its call (not by real dispatcher mutation). quick_smoke_test + __main__
excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import inspect
import unittest
from unittest.mock import patch

import cosa.agents.bug_fix_expediter.voice_io as bfe_voice_io
import cosa.agents.bug_fix_expediter.cosa_interface as bfe_cosa_interface
from cosa.agents.utils import voice_io as core_voice_io


class TestVoiceIoReExports( unittest.TestCase ):
    """The wrapper re-exports the SAME callables as the core module."""

    def test_config_functions_are_core_objects( self ):
        self.assertIs( bfe_voice_io.set_cli_mode,         core_voice_io.set_cli_mode )
        self.assertIs( bfe_voice_io.reset_voice_check,    core_voice_io.reset_voice_check )
        self.assertIs( bfe_voice_io.is_voice_available,   core_voice_io.is_voice_available )
        self.assertIs( bfe_voice_io.get_mode_description, core_voice_io.get_mode_description )
        self.assertIs( bfe_voice_io.is_cli_mode,          core_voice_io.is_cli_mode )
        self.assertIs( bfe_voice_io.set_job_id,           core_voice_io.set_job_id )
        self.assertIs( bfe_voice_io.clear_job_id,         core_voice_io.clear_job_id )

    def test_async_io_functions_are_core_coroutines( self ):
        for fn in ( bfe_voice_io.notify, bfe_voice_io.ask_yes_no,
                    bfe_voice_io.get_input, bfe_voice_io.choose,
                    bfe_voice_io.present_choices ):
            self.assertTrue( inspect.iscoroutinefunction( fn ) )
        self.assertIs( bfe_voice_io.notify, core_voice_io.notify )


class TestReconfigure( unittest.TestCase ):
    """reconfigure() re-binds the core module to BFE's cosa_interface."""

    def test_reconfigure_calls_core_configure_with_bfe_interface( self ):
        with patch.object( bfe_voice_io._core_voice_io, "configure" ) as mock_cfg:
            bfe_voice_io.reconfigure()
            mock_cfg.assert_called_once_with( bfe_cosa_interface )


class TestPlanWriterShim( unittest.TestCase ):
    """plan_writer.py is a backwards-compat re-export of the shared PlanWriter."""

    def test_shim_reexports_shared_planwriter( self ):
        from cosa.agents.bug_fix_expediter.plan_writer import PlanWriter as ShimPW
        from cosa.agents.shared.plan_writer import PlanWriter as SharedPW
        self.assertIs( ShimPW, SharedPW )


class TestPackageInit( unittest.TestCase ):
    """Package __init__ aggregates the public surface."""

    def test_version_and_all_surface( self ):
        import cosa.agents.bug_fix_expediter as pkg
        self.assertEqual( pkg.__version__, "0.1.0" )
        for name in ( "BugFixExpediterConfig", "BFEPhase", "DeadJobContext",
                      "create_initial_state", "package_dead_job",
                      "BFEOrchestrator", "PlanWriter", "voice_notify" ):
            self.assertIn( name, pkg.__all__ )
            self.assertTrue( hasattr( pkg, name ) )


if __name__ == "__main__":
    unittest.main()
