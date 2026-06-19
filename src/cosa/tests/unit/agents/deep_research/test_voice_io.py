"""
Unit tests for cosa.agents.deep_research.voice_io.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). This
module is a thin wrapper that configures the consolidated core voice_io with the
Deep Research cosa_interface and re-exports its public functions. Import-time
configuration + the re-exports are covered on import; reconfigure() is covered by
direct call. No network/LLM/voice I/O (core.configure is patched for the rebind
assertion).
"""

import unittest
from unittest.mock import patch

import cosa.agents.deep_research.voice_io as vio
from cosa.agents.utils import voice_io as core
from cosa.agents.deep_research import cosa_interface


class TestReconfigure( unittest.TestCase ):

    def test_reconfigure_rebinds_core_to_deep_research_interface( self ):
        # reconfigure() re-asserts the core voice_io binding to THIS agent's interface,
        # so notifications route through the Deep Research dispatcher regardless of
        # import order (last-configure-wins contention).
        with patch.object( core, "configure" ) as mock_cfg:
            vio.reconfigure()
        mock_cfg.assert_called_once_with( cosa_interface )

    def test_import_time_configure_bound_interface( self ):
        # importing the wrapper configured the core with a non-None interface
        self.assertIsNotNone( core._cosa_interface )


class TestReExports( unittest.TestCase ):
    """The wrapper's purpose: re-export the core voice_io callables verbatim."""

    def test_io_functions_are_core_identities( self ):
        self.assertIs( vio.notify, core.notify )
        self.assertIs( vio.ask_yes_no, core.ask_yes_no )
        self.assertIs( vio.get_input, core.get_input )
        self.assertIs( vio.choose, core.choose )
        self.assertIs( vio.present_choices, core.present_choices )

    def test_mode_and_job_helpers_are_core_identities( self ):
        self.assertIs( vio.set_cli_mode, core.set_cli_mode )
        self.assertIs( vio.reset_voice_check, core.reset_voice_check )
        self.assertIs( vio.is_voice_available, core.is_voice_available )
        self.assertIs( vio.get_mode_description, core.get_mode_description )
        self.assertIs( vio.is_cli_mode, core.is_cli_mode )
        self.assertIs( vio.set_job_id, core.set_job_id )
        self.assertIs( vio.clear_job_id, core.clear_job_id )

    def test_narrowing_functions_are_core_identities( self ):
        self.assertIs( vio.select_themes, core.select_themes )
        self.assertIs( vio.select_topics, core.select_topics )


if __name__ == "__main__":
    unittest.main()
