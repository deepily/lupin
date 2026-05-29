#!/usr/bin/env python3
"""
Voice-First I/O Layer for COSA Test Suite Agent.

Thin wrapper around the consolidated voice_io module in
cosa.agents.utils.voice_io, configured with the Test Suite
cosa_interface for proper sender identity.

All voice-first functions are re-exported from the core module.
"""

# Import the consolidated voice_io module and configure it
from cosa.agents.utils import voice_io as _core_voice_io
from . import cosa_interface as _cosa_interface

# Configure the core voice_io with our cosa_interface
_core_voice_io.configure( _cosa_interface )


def reconfigure():
    """
    Re-establish core voice_io binding to this agent's cosa_interface.

    Call this at the start of _execute() to ensure notifications route
    through the correct agent's dispatcher, regardless of import order.
    """
    _core_voice_io.configure( _cosa_interface )


# =============================================================================
# Re-export all public functions from core voice_io
# =============================================================================

set_cli_mode       = _core_voice_io.set_cli_mode
reset_voice_check  = _core_voice_io.reset_voice_check
is_voice_available = _core_voice_io.is_voice_available
get_mode_description = _core_voice_io.get_mode_description
is_cli_mode        = _core_voice_io.is_cli_mode
set_job_id         = _core_voice_io.set_job_id
clear_job_id       = _core_voice_io.clear_job_id

# Voice-first I/O functions
notify             = _core_voice_io.notify
ask_yes_no         = _core_voice_io.ask_yes_no
get_input          = _core_voice_io.get_input
choose             = _core_voice_io.choose
