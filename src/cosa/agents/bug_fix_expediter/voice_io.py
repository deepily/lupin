"""
Voice-First I/O Wrapper for Bug Fix Expediter.

Thin wrapper layer configuring and re-exporting the consolidated
voice I/O module. Call reconfigure() at the start of _execute()
to ensure notifications route through this agent's dispatcher.
"""

from cosa.agents.utils import voice_io as _core_voice_io
from . import cosa_interface as _cosa_interface

# Configure core voice_io at module load
_core_voice_io.configure( _cosa_interface )


def reconfigure():
    """
    Re-establish voice_io binding to this agent's cosa_interface.

    Call at start of _execute() to ensure notifications route through
    correct agent's dispatcher (handles import-order race when multiple
    agents import wrappers).
    """
    _core_voice_io.configure( _cosa_interface )


# === Configuration functions ===
set_cli_mode       = _core_voice_io.set_cli_mode
reset_voice_check  = _core_voice_io.reset_voice_check
is_voice_available = _core_voice_io.is_voice_available
get_mode_description = _core_voice_io.get_mode_description
is_cli_mode        = _core_voice_io.is_cli_mode

# === Job ID management ===
set_job_id         = _core_voice_io.set_job_id
clear_job_id       = _core_voice_io.clear_job_id

# === Voice-first I/O functions (all async) ===
notify             = _core_voice_io.notify
ask_yes_no         = _core_voice_io.ask_yes_no
get_input          = _core_voice_io.get_input
choose             = _core_voice_io.choose
present_choices    = _core_voice_io.present_choices


def quick_smoke_test():
    """Quick smoke test for BFE voice_io module."""
    import cosa.utils.util as cu
    import inspect

    cu.print_banner( "BFE Voice I/O Smoke Test", prepend_nl=True )

    try:
        # 1: Core re-exports exist
        assert callable( set_job_id )
        assert callable( clear_job_id )
        assert callable( reconfigure )
        print( "✓ Core functions exported" )

        # 2: Async functions
        assert inspect.iscoroutinefunction( notify )
        assert inspect.iscoroutinefunction( ask_yes_no )
        assert inspect.iscoroutinefunction( get_input )
        assert inspect.iscoroutinefunction( choose )
        assert inspect.iscoroutinefunction( present_choices )
        print( "✓ Async functions have correct signatures" )

        # 3: Configuration functions
        assert callable( set_cli_mode )
        assert callable( reset_voice_check )
        assert callable( is_voice_available )
        assert callable( get_mode_description )
        print( "✓ Configuration functions exported" )

        # 4: reconfigure doesn't crash
        reconfigure()
        print( "✓ reconfigure() succeeds" )

        print( "\n✓ BFE Voice I/O smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
