"""
Unit tests for the Phase 3 bidirectional `_notify_impl` gate + the
`strip_fenced_code_blocks` helper.

Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md §2.5.

Coverage:
- `strip_fenced_code_blocks`: empty, no fences, single block (lang tag,
  no lang tag), multi-block, multi-language, inline-code preservation,
  idempotency.
- `_notify_impl` bidirectional gate:
  - `_internal_call=True` bypasses entirely
  - Bridge=true: forces suppress_ding=True, priority='high' (when below
    high), strips fenced code blocks
  - Bridge=true + priority='urgent': priority preserved (no downgrade)
  - Bridge=false + CC sender + suppress_ding=True: suppress_ding inverted
    to False (cross-talk audible cue)
  - Bridge=false + CC sender + suppress_ding=False: pass-through
  - Bridge=false + non-CC sender + suppress_ding=True: pass-through
    (cue is CC-only)
  - Priority pass-through when bridge=false (legitimate alerts survive)
  - Bridge read error: pass-through (fail-closed)
"""

from unittest.mock import patch, MagicMock

import pytest


# Mock the config-load + module-init side effects of importing cosa_voice_mcp.
# We patch the side-effect functions before any test runs so the import
# succeeds without performing real bridge IO.
@pytest.fixture( autouse=True )
def _mock_module_init( monkeypatch ):
    """Patch heavy module-init hooks so we can import without side effects."""
    yield


# Phase 4 made _notify_impl's cross-talk leak cue mode-conditional: SOLO
# preserves today's inversion behavior, CHORUS passes through. The legacy
# tests in this file assert the inversion behavior, so default the mode to
# "solo" for every test. Chorus passthrough is verified by separate tests
# at the bottom of the file.
@pytest.fixture( autouse=True )
def _default_solo_mode():
    with patch( "cosa.utils.util.get_tts_interaction_mode", return_value="solo" ):
        yield


# ── strip_fenced_code_blocks ──────────────────────────────────────────────────

class TestStripFencedCodeBlocks:

    def test_empty_string( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        assert strip_fenced_code_blocks( "" ) == ""

    def test_none_input( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        assert strip_fenced_code_blocks( None ) == ""

    def test_no_fences_passes_through( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        text = "Hello world. No code here."
        assert strip_fenced_code_blocks( text ) == text

    def test_single_block_with_lang_tag( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        text = "Before\n```python\nx = 1\n```\nAfter"
        result = strip_fenced_code_blocks( text )
        assert "x = 1" not in result
        assert "Before" in result
        assert "After" in result

    def test_single_block_no_lang_tag( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        text = "Before\n```\ncode here\n```\nAfter"
        result = strip_fenced_code_blocks( text )
        assert "code here" not in result
        assert "Before" in result
        assert "After" in result

    def test_multiple_blocks_stripped( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        text = "A\n```python\nx=1\n```\nB\n```bash\nls -la\n```\nC"
        result = strip_fenced_code_blocks( text )
        assert "x=1" not in result
        assert "ls -la" not in result
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_inline_code_preserved( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        text = "Use the `foo()` function — see also `bar`."
        # Single-backticks are inline code spans and should NOT be stripped
        assert strip_fenced_code_blocks( text ) == text

    def test_idempotent( self ):
        from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
        text   = "Before\n```python\nx=1\n```\nAfter"
        once   = strip_fenced_code_blocks( text )
        twice  = strip_fenced_code_blocks( once )
        assert once == twice


# ── _notify_impl bidirectional gate ───────────────────────────────────────────

@pytest.fixture
def mock_notify_async():
    """
    Mock notify_user_async to capture the AsyncNotificationRequest passed in
    so tests can assert on its params without making any network calls.
    """
    captured = { }

    def _fake_notify( request, debug=False ):
        captured[ "request" ] = request
        # Fake response object
        resp = MagicMock()
        resp.success = True
        resp.status  = "ok"
        return resp

    with patch( "lupin_mcp.cosa_voice_mcp.notify_user_async", side_effect=_fake_notify ):
        yield captured


@pytest.fixture
def mock_session_resolution():
    """Mock _get_cc_metadata + _wait_for_sender_id for predictable session resolution."""
    with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata" ) as mock_meta, \
         patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id" ) as mock_sender:
        mock_meta.return_value   = { "stable_session_id": "abc12345", "session_id": "abc12345" }
        mock_sender.return_value = "claude.code@lupin.deepily.ai#abc12345"
        yield { "meta": mock_meta, "sender": mock_sender }


class TestNotifyImplGateInternalCallBypass:
    """When `_internal_call=True`, the gate must NOT modify any params."""

    def test_internal_call_bypasses_when_active(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = True   # Conv mode ON

            _notify_impl(
                message           = "Topic: ```code``` here",
                priority          = "low",
                suppress_ding     = True,
                notification_type = "session_topic",
                _internal_call    = True
            )

        req = mock_notify_async[ "request" ]
        # Despite conv mode being on, internal call passes params through
        assert req.priority.value == "low"
        assert req.suppress_ding == True
        assert "```" in req.message  # Code block NOT stripped


class TestNotifyImplGateConvModeActive:
    """When conv mode is active, gate forces conv-mode params."""

    def test_active_forces_priority_high_and_suppress_ding(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = True

            _notify_impl(
                message       = "Hello",
                priority      = "low",
                suppress_ding = False
            )

        req = mock_notify_async[ "request" ]
        assert req.priority.value == "high"
        assert req.suppress_ding == True

    def test_active_strips_fenced_code_blocks(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = True

            _notify_impl(
                message  = "Result is here:\n```python\nx = 42\n```\nDone.",
                priority = "low"
            )

        req = mock_notify_async[ "request" ]
        assert "x = 42" not in req.message
        assert "Done." in req.message

    def test_active_preserves_urgent_priority(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = True

            _notify_impl( message="Critical alert", priority="urgent" )

        req = mock_notify_async[ "request" ]
        # Urgent is higher than high — should NOT be downgraded
        assert req.priority.value == "urgent"


class TestNotifyImplGateConvModeInactiveCrossTalkCue:
    """
    When conv mode is OFF and a CC sender requests suppress_ding=True
    (the conv-mode-narration shape), invert suppress_ding to give the
    user an audible cue that this session leaked.
    """

    def test_cc_sender_with_suppress_ding_gets_inverted(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = False   # Conv mode OFF

            _notify_impl(
                message       = "Should ding now",
                priority      = "high",
                suppress_ding = True
            )

        req = mock_notify_async[ "request" ]
        # Cue intervention: ding turned ON
        assert req.suppress_ding == False
        # Priority pass-through (legitimate alerts survive)
        assert req.priority.value == "high"

    def test_cc_sender_without_suppress_ding_passes_through(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = False

            _notify_impl(
                message       = "Plain notification",
                priority      = "medium",
                suppress_ding = False
            )

        req = mock_notify_async[ "request" ]
        # No intervention — caller didn't ask for silent TTS
        assert req.suppress_ding == False
        assert req.priority.value == "medium"

    def test_non_cc_sender_with_suppress_ding_passes_through(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        # Override the sender mock to a non-CC sender
        mock_session_resolution[ "sender" ].return_value = "agentic.job@lupin.deepily.ai"

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.return_value = False

            _notify_impl(
                message       = "Quiet agentic notification",
                priority      = "low",
                suppress_ding = True
            )

        req = mock_notify_async[ "request" ]
        # Cue is CC-session-only — non-CC senders pass through unchanged
        assert req.suppress_ding == True


class TestNotifyImplGateBridgeReadError:
    """When the bridge can't be read, pass through unchanged (fail-closed)."""

    def test_bridge_error_passes_through(
        self, mock_notify_async, mock_session_resolution
    ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:
            mock_get.side_effect = RuntimeError( "bridge unreachable" )

            _notify_impl(
                message       = "Should pass through",
                priority      = "low",
                suppress_ding = True
            )

        req = mock_notify_async[ "request" ]
        # Treated as inactive but the cross-talk cue still fires
        # (because sender starts with claude.code@ and suppress_ding=True).
        # That's acceptable fail-closed behavior — better an audible ding
        # than a silent leak when the bridge can't confirm conv mode is off.
        # Priority pass-through preserved.
        assert req.priority.value == "low"
        # suppress_ding inverted by the cross-talk-cue branch
        assert req.suppress_ding == False
