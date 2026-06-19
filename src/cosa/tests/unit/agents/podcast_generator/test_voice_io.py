#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.voice_io

Target: the thin re-export wrapper around cosa.agents.utils.voice_io. The
module-level configure() + re-export bindings run on import; the only callable
defined here is reconfigure(), which re-asserts the core binding.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

from unittest.mock import patch

import cosa.agents.podcast_generator.voice_io as pg_voice_io
from cosa.agents.utils import voice_io as core_voice_io
from cosa.agents.podcast_generator import cosa_interface as pg_cosa_interface


class TestReExports:
    """
    The wrapper re-exports core voice_io callables verbatim.

    Ensures every re-exported name is the SAME object as the core module's,
    so callers get the consolidated implementation unchanged.
    """

    def test_reexported_names_are_core_objects( self ):
        assert pg_voice_io.set_cli_mode       is core_voice_io.set_cli_mode
        assert pg_voice_io.reset_voice_check  is core_voice_io.reset_voice_check
        assert pg_voice_io.is_voice_available is core_voice_io.is_voice_available
        assert pg_voice_io.get_mode_description is core_voice_io.get_mode_description
        assert pg_voice_io.is_cli_mode        is core_voice_io.is_cli_mode
        assert pg_voice_io.set_job_id         is core_voice_io.set_job_id
        assert pg_voice_io.clear_job_id       is core_voice_io.clear_job_id
        assert pg_voice_io.notify             is core_voice_io.notify
        assert pg_voice_io.ask_yes_no         is core_voice_io.ask_yes_no
        assert pg_voice_io.get_input          is core_voice_io.get_input
        assert pg_voice_io.choose             is core_voice_io.choose
        assert pg_voice_io.present_choices    is core_voice_io.present_choices
        assert pg_voice_io.select_themes      is core_voice_io.select_themes
        assert pg_voice_io.select_topics      is core_voice_io.select_topics


class TestReconfigure:
    """
    reconfigure() re-binds the core voice_io to THIS agent's cosa_interface.

    Ensures it delegates to core_voice_io.configure with the package's own
    cosa_interface module (last-writer-wins re-assertion).
    """

    def test_reconfigure_rebinds_core_to_package_interface( self ):
        with patch.object( core_voice_io, "configure" ) as cfg:
            pg_voice_io.reconfigure()
        cfg.assert_called_once_with( pg_cosa_interface )
