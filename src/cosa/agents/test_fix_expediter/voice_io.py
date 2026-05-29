"""
Voice I/O wrapper for the TestFixExpediter agent.

Thin facade over BFE's voice_io module — both agents use the same core
voice I/O mechanism (cosa-voice MCP), differentiated only by SENDER_ID.
This wrapper exists per the agentic-voice-workflow skill's mandated
agent-package layout.
"""

import cosa.utils.util as cu

# Re-export BFE's voice_io functions. TFE's cosa_interface provides the
# SENDER_ID; the underlying voice_io machinery is shared.
from cosa.agents.bug_fix_expediter.voice_io import (
    set_cli_mode,
    reset_voice_check,
    is_voice_available,
    get_mode_description,
    notify,
    ask_yes_no,
    get_input,
    choose,
)

# Session topic is handled by cosa-voice's set_session_topic tool directly;
# callers should invoke that via the MCP client.


def quick_smoke_test():
    """Quick smoke test for TFE voice_io."""
    cu.print_banner( "TFE voice_io Smoke Test", prepend_nl=True )

    try:
        # 1: All functions are callable
        assert callable( set_cli_mode )
        assert callable( reset_voice_check )
        assert callable( is_voice_available )
        assert callable( get_mode_description )
        assert callable( notify )
        assert callable( ask_yes_no )
        assert callable( get_input )
        assert callable( choose )
        print( "✓ All 8 voice_io functions re-exported" )

        # 2: Mode description is a string
        desc = get_mode_description()
        assert isinstance( desc, str )
        print( f"✓ get_mode_description() = '{desc}'" )

        print( "\n✓ TFE voice_io smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
