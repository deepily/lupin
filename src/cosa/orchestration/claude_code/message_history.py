#!/usr/bin/env python3
"""
Message History for Claude Code Session Continuity.

Tracks conversation history during interactive SDK sessions to enable
context preservation across session restarts (interrupts).

When the SDK's interrupt() terminates a session, a new session starts with
zero memory. This class captures the conversation so it can be injected
into the new session's prompt.

Usage:
    from cosa.orchestration.claude_code import MessageHistory

    history = MessageHistory()
    history.set_original_prompt( "Debug the auth issue" )
    history.add_assistant_text( "I see the problem in line 42..." )

    # When restarting session, prepend context:
    context = history.get_context_prompt()
    new_prompt = f"{context}New message: Also check refresh tokens"

Created: 2026-01-07
Purpose: Enable "polite queue" semantics on top of SDK session restarts
"""

from typing import List, Dict


class MessageHistory:
    """
    Tracks conversation history for session continuity across interrupts.

    The SDK's interrupt() kills sessions entirely. This class captures
    the conversation so it can be reconstructed when a new session starts.

    Requires:
        - Messages are added in chronological order
        - Original prompt is set before adding messages

    Ensures:
        - History is preserved across session restarts
        - Context prompt is formatted for Claude to understand
        - Long messages are truncated to prevent token explosion
    """

    def __init__( self ):
        """Initialize empty history."""
        self.messages: List[Dict[str, str]] = []
        self.original_prompt: str = ""

    def set_original_prompt( self, prompt: str ):
        """
        Store the original task prompt.

        Requires:
            - prompt is a non-empty string

        Ensures:
            - Original prompt is stored for context reconstruction
        """
        self.original_prompt = prompt

    def add_assistant_text( self, text: str ):
        """
        Track Claude's text output.

        Consecutive assistant messages are concatenated to form complete thoughts.

        Requires:
            - text is a string (can be empty for streaming chunks)

        Ensures:
            - Text is added to the most recent assistant message
            - Or creates a new assistant message if none exists
        """
        if not text:
            return

        if self.messages and self.messages[-1]["role"] == "assistant":
            # Append to existing assistant turn
            self.messages[-1]["content"] += text
        else:
            # Start new assistant turn
            self.messages.append( { "role": "assistant", "content": text } )

    def add_user_message( self, text: str ):
        """
        Track user's injected message.

        Requires:
            - text is a non-empty string

        Ensures:
            - User message is appended to history
        """
        if text:
            self.messages.append( { "role": "user", "content": text } )

    def get_context_prompt( self, max_chars_per_message: int = 500 ) -> str:
        """
        Format history for injection into new session.

        Requires:
            - max_chars_per_message is a positive integer

        Ensures:
            - Returns empty string if no history
            - Formats history with clear markers for Claude
            - Truncates long messages to prevent token explosion
            - Original prompt is included for task continuity
        """
        if not self.messages:
            return ""

        lines = []
        lines.append( "[CONVERSATION CONTEXT]" )
        lines.append( "" )

        # Include original task
        original_truncated = self.original_prompt[:max_chars_per_message]
        if len( self.original_prompt ) > max_chars_per_message:
            original_truncated += "..."
        lines.append( f"Original task: {original_truncated}" )
        lines.append( "" )
        lines.append( "What happened so far:" )

        # Add each message
        for msg in self.messages:
            role = "User" if msg["role"] == "user" else "You (Claude)"
            content = msg["content"][:max_chars_per_message]
            if len( msg["content"] ) > max_chars_per_message:
                content += "..."
            lines.append( f"- {role}: {content}" )

        lines.append( "" )
        lines.append( "[END CONTEXT - Continue from here]" )
        lines.append( "" )

        return "\n".join( lines )

    def clear( self ):
        """Clear all history."""
        self.messages = []
        self.original_prompt = ""

    def __len__( self ) -> int:
        """Return number of messages in history."""
        return len( self.messages )

    def __bool__( self ) -> bool:
        """Return True if history has messages."""
        return len( self.messages ) > 0


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for MessageHistory - validates basic functionality.
    """
    import cosa.utils.util as cu

    cu.print_banner( "MessageHistory Smoke Test", prepend_nl=True )

    try:
        # Test 1: Basic creation
        print( "Test 1: Creating MessageHistory..." )
        history = MessageHistory()
        assert len( history ) == 0
        assert not history
        print( "✓ Empty history created" )

        # Test 2: Set original prompt
        print( "\nTest 2: Setting original prompt..." )
        history.set_original_prompt( "Debug the authentication issue in jwt_service.py" )
        assert history.original_prompt == "Debug the authentication issue in jwt_service.py"
        print( "✓ Original prompt stored" )

        # Test 3: Add assistant text
        print( "\nTest 3: Adding assistant text..." )
        history.add_assistant_text( "I see the problem. " )
        history.add_assistant_text( "Line 42 has a bug." )
        assert len( history ) == 1  # Consecutive messages are concatenated
        assert "I see the problem" in history.messages[0]["content"]
        assert "Line 42" in history.messages[0]["content"]
        print( "✓ Assistant text concatenated correctly" )

        # Test 4: Add user message
        print( "\nTest 4: Adding user message..." )
        history.add_user_message( "Also check the refresh token logic" )
        assert len( history ) == 2
        assert history.messages[1]["role"] == "user"
        print( "✓ User message added" )

        # Test 5: Add more assistant text (new turn)
        print( "\nTest 5: Adding more assistant text..." )
        history.add_assistant_text( "Looking at refresh tokens now..." )
        assert len( history ) == 3
        print( "✓ New assistant turn created" )

        # Test 6: Get context prompt
        print( "\nTest 6: Getting context prompt..." )
        context = history.get_context_prompt()
        assert "[CONVERSATION CONTEXT]" in context
        assert "[END CONTEXT" in context
        assert "Original task:" in context
        assert "You (Claude):" in context
        assert "User:" in context
        print( "✓ Context prompt generated" )
        print( f"\n--- Context Preview ---\n{context[:400]}...\n--- End Preview ---" )

        # Test 7: Truncation
        print( "\nTest 7: Testing truncation..." )
        long_history = MessageHistory()
        long_history.set_original_prompt( "x" * 1000 )
        long_history.add_assistant_text( "y" * 1000 )
        context = long_history.get_context_prompt( max_chars_per_message=100 )
        assert "..." in context
        print( "✓ Long messages are truncated" )

        # Test 8: Clear
        print( "\nTest 8: Testing clear..." )
        history.clear()
        assert len( history ) == 0
        assert history.original_prompt == ""
        print( "✓ History cleared" )

        # Test 9: Empty text handling
        print( "\nTest 9: Testing empty text handling..." )
        history.add_assistant_text( "" )
        history.add_user_message( "" )
        assert len( history ) == 0
        print( "✓ Empty strings ignored" )

        print( "\n" + "=" * 60 )
        print( "✅ ALL SMOKE TESTS PASSED!" )
        print( "=" * 60 )

    except AssertionError as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print( f"\n✗ Error: {e}" )
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = quick_smoke_test()
    import sys
    sys.exit( 0 if success else 1 )
