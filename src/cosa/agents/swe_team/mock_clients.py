#!/usr/bin/env python3
"""
Mock Clients for COSA SWE Team Agent.

Provides mock implementations of the Claude Agent SDK session
for dry-run mode and testing. Simulates the query() stream
with realistic phase progression.
"""

import asyncio
import logging
import uuid
from typing import AsyncIterator, Optional

logger = logging.getLogger( __name__ )


class MockAgentMessage:
    """
    Simulated message from the Agent SDK query() stream.

    Mirrors the structure of real SDK messages for dry-run compatibility.
    """

    def __init__( self, role: str, content: str, agent_name: str = "lead" ):
        self.role       = role
        self.content    = content
        self.agent_name = agent_name


class MockAgentSDKSession:
    """
    Mock Agent SDK session for dry-run mode.

    Simulates the full task lifecycle without making API calls:
    1. Task decomposition (lead)
    2. Implementation (coder)
    3. Test writing (tester)
    4. Code review (reviewer)
    5. Completion report (lead)

    Requires:
        - task_description is a non-empty string

    Ensures:
        - query() yields a sequence of MockAgentMessage objects
        - All phases complete without errors in dry-run mode
        - Realistic delays between phases
    """

    # Per-test scaling knob — multiply all per-phase delays by this factor.
    # Default 1.0 preserves real-time pacing for CLI / manual / smoke runs.
    # Unit tests monkeypatch this to 0.0 to skip the legitimate ~3.4s of
    # cumulative phase sleeps. Added 2026-04-30 (Session b195a160) for the
    # TestDryRunRegression performance fix — see
    # src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md.
    DELAY_MULTIPLIER = 1.0

    DRY_RUN_PHASES = [
        {
            "agent"   : "lead",
            "message" : "Analyzing task and decomposing into subtasks...",
            "delay"   : 0.5,
        },
        {
            "agent"   : "lead",
            "message" : "Task decomposed into 2 subtasks:\n"
                        "1. Implement core functionality\n"
                        "2. Write unit tests",
            "delay"   : 0.3,
        },
        {
            "agent"   : "coder",
            "message" : "[DRY RUN] Would implement core functionality here.\n"
                        "Files that would be modified: src/example.py",
            "delay"   : 1.0,
        },
        {
            "agent"   : "tester",
            "message" : "[DRY RUN] Would write tests here.\n"
                        "Files that would be created: tests/test_example.py\n"
                        "Expected: 3 unit tests",
            "delay"   : 0.8,
        },
        {
            "agent"   : "reviewer",
            "message" : "[DRY RUN] Would review code changes here.\n"
                        "Review scope: 2 files\n"
                        "Status: No issues found (dry run)",
            "delay"   : 0.5,
        },
        {
            "agent"   : "lead",
            "message" : "Task completed successfully (dry run).\n"
                        "Summary: All phases simulated without errors.",
            "delay"   : 0.3,
        },
    ]

    def __init__( self, task_description: str, debug: bool = False ):
        self.task_description = task_description
        self.debug            = debug
        self.session_id       = f"st-{uuid.uuid4().hex[ :8 ]}"
        self.messages_sent    = 0

    async def query( self ) -> AsyncIterator[ MockAgentMessage ]:
        """
        Simulate the Agent SDK query() stream.

        Ensures:
            - Yields messages in phase order
            - Includes realistic delays between phases
            - Completes all phases successfully

        Yields:
            MockAgentMessage: Simulated SDK messages
        """
        if self.debug: print( f"[MockSDK] Starting dry-run for: {self.task_description[ :80 ]}" )

        for phase in self.DRY_RUN_PHASES:
            scaled_delay = phase[ "delay" ] * self.DELAY_MULTIPLIER
            if scaled_delay > 0:
                await asyncio.sleep( scaled_delay )
            self.messages_sent += 1

            msg = MockAgentMessage(
                role       = "assistant",
                content    = phase[ "message" ],
                agent_name = phase[ "agent" ],
            )

            if self.debug: print( f"[MockSDK] [{phase[ 'agent' ]}] {phase[ 'message' ][ :60 ]}..." )

            yield msg

    def get_session_summary( self ) -> dict:
        """
        Get summary of the mock session.

        Returns:
            dict: Session metadata and statistics
        """
        return {
            "session_id"       : self.session_id,
            "task"             : self.task_description[ :100 ],
            "messages_sent"    : self.messages_sent,
            "dry_run"          : True,
            "tokens_used"      : 0,
            "cost_usd"         : 0.0,
        }


def quick_smoke_test():
    """Quick smoke test for mock_clients module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team Mock Clients Smoke Test", prepend_nl=True )

    try:
        # Test 1: MockAgentMessage creation
        print( "Testing MockAgentMessage..." )
        msg = MockAgentMessage( role="assistant", content="test", agent_name="coder" )
        assert msg.role == "assistant"
        assert msg.content == "test"
        assert msg.agent_name == "coder"
        print( "✓ MockAgentMessage creates correctly" )

        # Test 2: MockAgentSDKSession creation
        print( "Testing MockAgentSDKSession..." )
        session = MockAgentSDKSession( "Test task", debug=False )
        assert session.task_description == "Test task"
        assert session.session_id.startswith( "st-" )
        assert len( session.session_id ) == 11  # "st-" + 8 hex chars
        print( f"✓ MockAgentSDKSession created: {session.session_id}" )

        # Test 3: Dry-run phases defined
        print( "Testing dry-run phases..." )
        assert len( MockAgentSDKSession.DRY_RUN_PHASES ) == 6
        agents_used = { p[ "agent" ] for p in MockAgentSDKSession.DRY_RUN_PHASES }
        assert "lead" in agents_used
        assert "coder" in agents_used
        assert "tester" in agents_used
        assert "reviewer" in agents_used
        print( f"✓ {len( MockAgentSDKSession.DRY_RUN_PHASES )} dry-run phases using {sorted( agents_used )}" )

        # Test 4: Async query stream
        print( "Testing async query stream..." )

        async def run_mock():
            session = MockAgentSDKSession( "Test task", debug=False )
            messages = []
            async for msg in session.query():
                messages.append( msg )
            return session, messages

        session, messages = asyncio.run( run_mock() )
        assert len( messages ) == 6
        assert session.messages_sent == 6
        print( f"✓ Query stream yielded {len( messages )} messages" )

        # Test 5: Session summary
        print( "Testing session summary..." )
        summary = session.get_session_summary()
        assert summary[ "dry_run" ] is True
        assert summary[ "cost_usd" ] == 0.0
        assert summary[ "messages_sent" ] == 6
        print( "✓ Session summary correct" )

        print( "\n✓ Mock Clients smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
