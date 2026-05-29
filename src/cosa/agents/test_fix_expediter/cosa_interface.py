"""
COSA interface for the TestFixExpediter agent.

Provides the SENDER_ID constant and thin wrappers around cosa-voice MCP
tools, matching the pattern established by BFE's cosa_interface.py and
mandated by the agentic-voice-workflow skill.

The SENDER_ID format is `{agent_name}@{project}.deepily.ai` so cosa-voice
notifications are attributable to TFE in the notification history UI.
"""

from typing import Optional

import cosa.utils.util as cu

# Reuse BFE's cosa_interface implementations — they're agent-agnostic
# façades over the cosa-voice MCP tools. TFE uses the same tools with
# its own SENDER_ID.
from cosa.agents.bug_fix_expediter.cosa_interface import (
    notify_progress as _bfe_notify_progress,
    ask_confirmation as _bfe_ask_confirmation,
    get_feedback as _bfe_get_feedback,
    present_choices as _bfe_present_choices,
)


SENDER_ID = "test_fix_expediter@lupin.deepily.ai"


def _get_sender_id() -> str:
    """Return the TFE sender_id for notification routing."""
    return SENDER_ID


# ─────────────────────────────────────────────────────────────────────────
# Thin wrappers — identical to BFE's implementations but namespaced here
# so TFE's code imports from its own package (keeps the agentic-voice-workflow
# skill's mandated layout consistent). The SENDER_ID is used by
# voice_io.py when it constructs notification payloads.
# ─────────────────────────────────────────────────────────────────────────


async def notify_progress( *args, **kwargs ):
    """Delegate to BFE's notify_progress (shared cosa-voice facade)."""
    return await _bfe_notify_progress( *args, **kwargs )


async def ask_confirmation( *args, **kwargs ):
    """Delegate to BFE's ask_confirmation."""
    return await _bfe_ask_confirmation( *args, **kwargs )


async def get_feedback( *args, **kwargs ):
    """Delegate to BFE's get_feedback."""
    return await _bfe_get_feedback( *args, **kwargs )


async def present_choices( *args, **kwargs ):
    """Delegate to BFE's present_choices."""
    return await _bfe_present_choices( *args, **kwargs )


def quick_smoke_test():
    """Quick smoke test for TFE cosa_interface."""
    cu.print_banner( "TFE cosa_interface Smoke Test", prepend_nl=True )

    try:
        # 1: SENDER_ID constant
        assert SENDER_ID == "test_fix_expediter@lupin.deepily.ai"
        assert _get_sender_id() == SENDER_ID
        print( f"✓ SENDER_ID = {SENDER_ID}" )

        # 2: Functions exist
        assert callable( notify_progress )
        assert callable( ask_confirmation )
        assert callable( get_feedback )
        assert callable( present_choices )
        print( "✓ All 4 cosa-voice wrappers are callable" )

        print( "\n✓ TFE cosa_interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
