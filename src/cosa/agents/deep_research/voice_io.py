#!/usr/bin/env python3
"""
Voice-First I/O Layer for COSA Deep Research Agent.

Thin wrapper around the consolidated voice_io module in
cosa.agents.utils.voice_io, configured with the Deep Research
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

    The consolidated core voice_io uses a single global _cosa_interface.
    When multiple agents import their wrappers, the last configure() call
    wins. This function re-asserts the correct binding for this agent.
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
    """Quick smoke test for Deep Research voice_io wrapper module."""
    import asyncio
    import inspect
    import cosa.utils.util as cu

    cu.print_banner( "Deep Research Voice I/O Wrapper Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports and configuration
        print( "Testing module configuration..." )
        assert _core_voice_io._cosa_interface is not None
        print( "✓ Core voice_io configured with cosa_interface" )

        # Test 2: set_cli_mode works
        print( "Testing set_cli_mode..." )
        set_cli_mode( True )
        assert _core_voice_io._force_cli_mode is True
        set_cli_mode( False )
        assert _core_voice_io._force_cli_mode is False
        print( "✓ set_cli_mode works correctly" )

        # Test 3: reset_voice_check works
        print( "Testing reset_voice_check..." )
        _core_voice_io._voice_available = True
        reset_voice_check()
        assert _core_voice_io._voice_available is None
        print( "✓ reset_voice_check works correctly" )

        # Test 4: Async function signatures
        print( "Testing async function signatures..." )
        assert inspect.iscoroutinefunction( is_voice_available )
        assert inspect.iscoroutinefunction( notify )
        assert inspect.iscoroutinefunction( ask_yes_no )
        assert inspect.iscoroutinefunction( get_input )
        assert inspect.iscoroutinefunction( choose )
        assert inspect.iscoroutinefunction( select_themes )
        assert inspect.iscoroutinefunction( select_topics )
        print( "✓ All async functions have correct signatures" )

        # Test 5: notify has job_id parameter
        print( "Testing notify() has job_id parameter..." )
        sig = inspect.signature( notify )
        assert "job_id" in sig.parameters
        print( "✓ notify() supports job_id parameter" )

        # Test 6: CLI mode fallback
        print( "Testing CLI mode fallback..." )
        set_cli_mode( True )

        async def test_cli_fallback():
            mode = get_mode_description()
            assert "forced" in mode.lower()

        asyncio.run( test_cli_fallback() )
        set_cli_mode( False )
        print( "✓ CLI mode fallback configured correctly" )

        # Reset state
        _core_voice_io._voice_available = None

        print( "\n✓ Deep Research voice_io wrapper smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
