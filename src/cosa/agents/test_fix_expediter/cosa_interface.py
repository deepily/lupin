"""
COSA interface for the TestFixExpediter agent.

Provides the SENDER_ID constant and the four cosa-voice wrappers, built by
the shared make_interface_functions factory exactly as BFE's cosa_interface.py
builds them, over TFE's own dispatcher.

The SENDER_ID format is `test.fix.expediter@{project}.deepily.ai[#{suffix}]` so
cosa-voice notifications are attributable to TFE in the notification history UI.
"""

import inspect
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, make_interface_functions

AGENT_TYPE = "test.fix.expediter"

_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE, default_priority="high" )


def _get_sender_id( suffix: str = None ) -> str:
    """
    Get sender_id for Test Fix Expediter notifications.

    Requires:
        - suffix is None or a non-empty string

    Ensures:
        - Returns sender_id in format: test.fix.expediter@{project}.deepily.ai[#{suffix}]

    Returns:
        str: Sender ID for notification identity
    """
    return _dispatcher.build_sender_id( suffix=suffix )


SENDER_ID: str                = _get_sender_id()
SESSION_NAME: Optional[ str ] = None
TARGET_USER: Optional[ str ]  = None


# The four wrappers are the shared factory's, bound to this module's own dispatcher,
# so a TFE notification carries TFE's sender_id and never the bug fix expediter's.
notify_progress, ask_confirmation, get_feedback, present_choices = make_interface_functions( globals(), notify_extras=( "progress_group_id", ), ask_extras=( "priority", ), feedback_extras=( "priority", "response_default" ), choices_extras=( "priority", "response_default" ) )


def quick_smoke_test():
    """Quick smoke test for TFE cosa_interface."""
    cu.print_banner( "TFE cosa_interface Smoke Test", prepend_nl=True )

    try:
        # 1: SENDER_ID constant
        assert SENDER_ID.startswith( "test.fix.expediter@" )
        assert _get_sender_id().startswith( "test.fix.expediter@" )
        print( f"✓ SENDER_ID = {SENDER_ID}" )

        # 2: Functions exist
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        assert inspect.iscoroutinefunction( get_feedback )
        assert inspect.iscoroutinefunction( present_choices )
        print( "✓ All 4 cosa-voice wrappers are coroutine functions" )

        print( "\n✓ TFE cosa_interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
