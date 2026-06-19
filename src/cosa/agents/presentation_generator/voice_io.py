#!/usr/bin/env python3
"""
Voice-First I/O Layer for COSA Presentation Generator Agent.

Thin wrapper around the consolidated voice_io module in
cosa.agents.utils.voice_io, configured with the Presentation Generator
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
present_choices    = _core_voice_io.present_choices

# Progressive narrowing functions
select_themes      = _core_voice_io.select_themes
select_topics      = _core_voice_io.select_topics


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for Presentation Generator voice_io wrapper module."""
    import inspect
    import cosa.utils.util as cu

    cu.print_banner( "Presentation Generator Voice I/O Wrapper Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module configured
        print( "Testing module configuration..." )
        assert _core_voice_io._cosa_interface is not None
        print( "  PASS" )

        # Test 2: Async function signatures
        print( "Testing async function signatures..." )
        assert inspect.iscoroutinefunction( notify )
        assert inspect.iscoroutinefunction( ask_yes_no )
        assert inspect.iscoroutinefunction( get_input )
        assert inspect.iscoroutinefunction( present_choices )
        assert inspect.iscoroutinefunction( choose )
        print( "  PASS" )

        # Test 3: reconfigure works
        print( "Testing reconfigure..." )
        reconfigure()
        assert _core_voice_io._cosa_interface is _cosa_interface
        print( "  PASS" )

        print( "\nAll Presentation Generator voice_io smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
