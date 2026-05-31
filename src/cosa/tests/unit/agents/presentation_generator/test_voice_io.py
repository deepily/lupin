#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.voice_io

Thin re-export wrapper around cosa.agents.utils.voice_io configured with the
presentation_generator cosa_interface. Verifies the binding + re-exports.
No real notifications fire (nothing is awaited).
"""

import inspect

import pytest

from cosa.agents.presentation_generator import voice_io as vio
from cosa.agents.utils import voice_io as core_voice_io
from cosa.agents.presentation_generator import cosa_interface


class TestReExports:
    def test_async_functions_reexported( self ):
        for fn in ( vio.notify, vio.ask_yes_no, vio.get_input, vio.present_choices, vio.choose ):
            assert inspect.iscoroutinefunction( fn )

    def test_identity_with_core( self ):
        assert vio.notify is core_voice_io.notify
        assert vio.present_choices is core_voice_io.present_choices
        assert vio.select_themes is core_voice_io.select_themes
        assert vio.select_topics is core_voice_io.select_topics
        assert vio.set_cli_mode is core_voice_io.set_cli_mode


class TestReconfigure:
    def test_reconfigure_binds_interface( self ):
        # rebind to something else, then reconfigure should restore our interface
        core_voice_io._cosa_interface = None
        vio.reconfigure()
        assert core_voice_io._cosa_interface is cosa_interface


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
