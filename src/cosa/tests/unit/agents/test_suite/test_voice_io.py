"""
Unit tests for cosa/agents/test_suite/voice_io.py.

A thin re-export wrapper over cosa.agents.utils.voice_io configured with the
test_suite cosa_interface. Module-level code (configure + re-exports) runs at
import; reconfigure() re-binds. No external seams here — the underlying core
voice_io is covered by its own suite. ZERO API spend.
"""
from unittest.mock import patch

import cosa.agents.test_suite.voice_io as ts_voice_io
from cosa.agents.utils import voice_io as core_voice_io
from cosa.agents.test_suite import cosa_interface


def test_reexports_point_at_core():
    assert ts_voice_io.notify     is core_voice_io.notify
    assert ts_voice_io.ask_yes_no is core_voice_io.ask_yes_no
    assert ts_voice_io.choose     is core_voice_io.choose
    assert ts_voice_io.set_cli_mode is core_voice_io.set_cli_mode


def test_reconfigure_rebinds_core_to_test_suite_interface():
    with patch.object( core_voice_io, "configure" ) as m:
        ts_voice_io.reconfigure()
    m.assert_called_once_with( cosa_interface )
