"""
E2E UI tests for the CC session selector strip + exclusive focus mode.

Design: src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md

The tests in this file exercise the strip and focus-mode behaviors on the
notifications page. Where possible they DRIVE the UI by simulating sender
cards via DOM manipulation through window.notificationsUI helpers, rather
than spinning up multiple authenticated CC sessions and waiting for real
WebSocket notifications. This keeps tests deterministic and fast.

Requires:
    - Test server running with [Lupin: Testing] config (lupin_db_test).
      The :8000 test container per CLAUDE.md TESTING VENUES.
    - Standard E2E UI conftest fixtures (logged_in_page, BASE_URL).
"""

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Fixtures specific to strip/focus tests
# ---------------------------------------------------------------------------

@pytest.fixture( scope="function" )
def notifications_page_with_strip( logged_in_page ):
    """
    Navigate to /app/notifications and wait for the page to settle.

    Requires:
        - logged_in_page fixture (authenticated session)

    Ensures:
        - Page navigated to notifications
        - networkidle reached
        - cc-session-strip element exists in DOM (may be hidden until first CC card)
    """
    logged_in_page.goto( f"{BASE_URL}/app/notifications" )
    logged_in_page.wait_for_load_state( "networkidle" )

    # Strip element should always be present in markup, even when hidden.
    assert logged_in_page.locator( "#cc-session-strip" ).count() > 0, \
        "Strip element should exist in HTML even when hidden"

    return logged_in_page


def _inject_cc_sender_card( page, sender_id, project="lupin", session_hash="abc12345" ):
    """
    Drive window.notificationsUI to create a CC sender card without waiting
    for a real WebSocket notification. Mirrors what handleNotificationUpdate
    would do when a notification arrives for a new sender.

    Returns the card's DOM id for downstream assertions.
    """
    page.evaluate(
        """( args ) => {
            const ui = window.notificationsUI;
            // Seed a minimal sender group so createSenderCard finds context.
            if ( !ui.senderGroups.has( args.senderId ) ) {
                ui.senderGroups.set( args.senderId, {
                    senderId    : args.senderId,
                    project     : args.project,
                    sessionHash : args.sessionHash,
                    isActive    : true,
                    totalCount  : 0,
                    dateGroups  : new Map(),
                    lastActivity: new Date().toISOString()
                } );
            }
            ui.createSenderCard( args.senderId, true );
        }""",
        { "senderId": sender_id, "project": project, "sessionHash": session_hash }
    )
    page.wait_for_timeout( 100 )  # let DOM settle
    sanitized = sender_id.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
    return f"sender-card-{sanitized}"


def _trigger_promote( page, sender_id ):
    """Simulate a fresh notification arriving for an existing card."""
    page.evaluate(
        "( sid ) => window.notificationsUI.moveSenderCardToTop( sid )",
        sender_id
    )
    page.wait_for_timeout( 50 )


def _click_strip_toggle( page ):
    page.locator( "#cc-strip-toggle" ).click()
    page.wait_for_timeout( 100 )


def _click_strip_icon( page, sender_id ):
    sanitized = sender_id.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
    page.locator( f"#cc-strip-icon-{sanitized}" ).click()
    page.wait_for_timeout( 100 )


# ---------------------------------------------------------------------------
# Strip rendering & basic structure
# ---------------------------------------------------------------------------

class TestStripRenders:
    """Strip is present in markup, hidden until first CC session, has toggle."""

    def test_strip_element_present_in_dom( self, notifications_page_with_strip ):
        """
        Strip container exists at page load even when no CC sessions are active.
        """
        page = notifications_page_with_strip
        assert page.locator( "#cc-session-strip" ).count() == 1
        assert page.locator( "#cc-strip-icons"  ).count() == 1
        assert page.locator( "#cc-strip-toggle" ).count() == 1

    def test_strip_is_hidden_with_no_cc_sessions( self, notifications_page_with_strip ):
        """
        With zero CC sender cards, the strip is hidden via the HTML hidden attribute.
        """
        page = notifications_page_with_strip
        is_hidden = page.evaluate(
            "() => document.getElementById( 'cc-session-strip' ).hasAttribute( 'hidden' )"
        )
        assert is_hidden, "Strip should be hidden until a CC sender card exists"

    def test_strip_reveals_when_first_cc_session_arrives( self, notifications_page_with_strip ):
        """
        Injecting a CC sender card removes the hidden attribute and adds a strip icon.
        """
        page = notifications_page_with_strip
        _inject_cc_sender_card( page, "claude.code@lupin.deepily.ai#abc12345" )

        is_hidden = page.evaluate(
            "() => document.getElementById( 'cc-session-strip' ).hasAttribute( 'hidden' )"
        )
        assert not is_hidden
        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 1

    def test_toggle_pill_shows_focus_off_text_initially( self, notifications_page_with_strip ):
        """
        Default toggle text reads "👁 Focus" with data-focus-active="false".
        """
        page = notifications_page_with_strip
        toggle = page.locator( "#cc-strip-toggle" )
        assert toggle.get_attribute( "data-focus-active" ) == "false"
        assert "Focus" in toggle.text_content()


# ---------------------------------------------------------------------------
# Recency reorder (default mode)
# ---------------------------------------------------------------------------

class TestRecencyReorder:
    """Strip icons reorder so leftmost = most recently updated."""

    def test_promote_moves_icon_to_leftmost( self, notifications_page_with_strip ):
        """
        After three sessions exist, promoting the third moves its icon leftmost.
        """
        page = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaaaaaa"
        sender_b = "claude.code@lupin.deepily.ai#bbbbbbbb"
        sender_c = "claude.code@lupin.deepily.ai#cccccccc"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )
        _inject_cc_sender_card( page, sender_c )

        # Promote A explicitly.
        _trigger_promote( page, sender_a )

        # Read the icon order left-to-right.
        order = page.evaluate(
            """() => Array.from(
                document.querySelectorAll( '#cc-strip-icons .cc-strip-icon' )
            ).map( i => i.getAttribute( 'data-sender-id' ) )"""
        )
        assert order[ 0 ] == sender_a, f"Expected A leftmost, got order: {order}"


# ---------------------------------------------------------------------------
# Focus mode entry / exit / switching
# ---------------------------------------------------------------------------

class TestFocusMode:
    """Toggle pill enters/exits focus; clicking icons switches focused session."""

    def test_enter_focus_hides_non_focused_cards( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaa1111"
        sender_b = "claude.code@lupin.deepily.ai#bbbb2222"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )

        _click_strip_toggle( page )

        # Toggle is active.
        toggle = page.locator( "#cc-strip-toggle" )
        assert toggle.get_attribute( "data-focus-active" ) == "true"
        # Exactly one card visible (no data-focus-hidden attr).
        visible_cards = page.evaluate(
            """() => Array.from(
                document.querySelectorAll( '#notifications-list .sender-card' )
            ).filter( c => !c.hasAttribute( 'data-focus-hidden' ) ).length"""
        )
        assert visible_cards == 1

    def test_exit_focus_reveals_all_cards( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaa3333"
        sender_b = "claude.code@lupin.deepily.ai#bbbb4444"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )

        _click_strip_toggle( page )  # enter
        _click_strip_toggle( page )  # exit

        toggle = page.locator( "#cc-strip-toggle" )
        assert toggle.get_attribute( "data-focus-active" ) == "false"
        visible_cards = page.evaluate(
            """() => Array.from(
                document.querySelectorAll( '#notifications-list .sender-card' )
            ).filter( c => !c.hasAttribute( 'data-focus-hidden' ) ).length"""
        )
        assert visible_cards == 2

    def test_clicking_different_strip_icon_switches_focus( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaa5555"
        sender_b = "claude.code@lupin.deepily.ai#bbbb6666"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )

        _click_strip_toggle( page )  # enter focus on B (B was added last → leftmost)

        focused_before = page.evaluate(
            """() => document.querySelector(
                '#cc-strip-icons .cc-strip-icon[data-focused="true"]'
            )?.getAttribute( 'data-sender-id' )"""
        )

        # Click the OTHER icon (whichever isn't focused now).
        other = sender_a if focused_before == sender_b else sender_b
        _click_strip_icon( page, other )

        focused_after = page.evaluate(
            """() => document.querySelector(
                '#cc-strip-icons .cc-strip-icon[data-focused="true"]'
            )?.getAttribute( 'data-sender-id' )"""
        )
        assert focused_after == other
        assert focused_after != focused_before


# ---------------------------------------------------------------------------
# Peripheral awareness (badge on non-focused sessions)
# ---------------------------------------------------------------------------

class TestPeripheralAwareness:
    """In focus mode, non-focused sessions get unread badges on activity."""

    def test_promote_on_non_focused_session_sets_unread( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaa7777"
        sender_b = "claude.code@lupin.deepily.ai#bbbb8888"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )

        # Enter focus on whichever is currently leftmost; identify it.
        _click_strip_toggle( page )
        focused = page.evaluate(
            """() => document.querySelector(
                '#cc-strip-icons .cc-strip-icon[data-focused="true"]'
            )?.getAttribute( 'data-sender-id' )"""
        )
        non_focused = sender_a if focused == sender_b else sender_b

        # Simulate notification activity on the non-focused session.
        _trigger_promote( page, non_focused )
        _trigger_promote( page, non_focused )

        sanitized = non_focused.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        icon = page.locator( f"#cc-strip-icon-{sanitized}" )
        assert icon.get_attribute( "data-unread" )       == "true"
        assert icon.get_attribute( "data-unread-count" ) == "2"

    def test_switching_focus_clears_unread_on_target( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaa9999"
        sender_b = "claude.code@lupin.deepily.ai#bbbb0000"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )
        _click_strip_toggle( page )

        focused     = page.evaluate(
            """() => document.querySelector(
                '#cc-strip-icons .cc-strip-icon[data-focused="true"]'
            )?.getAttribute( 'data-sender-id' )"""
        )
        non_focused = sender_a if focused == sender_b else sender_b

        _trigger_promote( page, non_focused )

        # Switch focus to the non-focused session.
        _click_strip_icon( page, non_focused )

        sanitized = non_focused.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        icon = page.locator( f"#cc-strip-icon-{sanitized}" )
        assert icon.get_attribute( "data-unread" )       is None
        assert icon.get_attribute( "data-unread-count" ) is None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    """Focus state survives page reload via localStorage."""

    def test_focus_state_persists_across_reload( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#aaaapers"

        _inject_cc_sender_card( page, sender_a )
        _click_strip_toggle( page )

        # Verify localStorage state.
        stored = page.evaluate(
            "() => localStorage.getItem( 'notifications_cc_focus_state' )"
        )
        assert stored is not None
        assert "true" in stored.lower()

        # Reload the page.
        page.reload()
        page.wait_for_load_state( "networkidle" )

        # Toggle should still be ON (state restored).
        toggle = page.locator( "#cc-strip-toggle" )
        assert toggle.get_attribute( "data-focus-active" ) == "true"


# ---------------------------------------------------------------------------
# Conv-mode orthogonality
# ---------------------------------------------------------------------------

class TestConvModeOrthogonality:
    """Conv-mode and focus-mode are independent axes."""

    def test_conv_mode_overlay_appears_via_event( self, notifications_page_with_strip ):
        page         = notifications_page_with_strip
        sender_a     = "claude.code@lupin.deepily.ai#convmode"
        session_hash = "convmode"

        _inject_cc_sender_card( page, sender_a, session_hash=session_hash )

        # Manually invoke the strip helper (the real conv-mode event would fire
        # this via the handleNotificationUpdate switch case).
        page.evaluate(
            "( sid ) => window.notificationsUI._setStripIconConvMode( sid, true )",
            session_hash
        )
        page.wait_for_timeout( 50 )

        sanitized = sender_a.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        icon = page.locator( f"#cc-strip-icon-{sanitized}" )
        assert icon.get_attribute( "data-conv-mode" ) == "true"


# ---------------------------------------------------------------------------
# Edge cases — focused session deletion auto-exits focus
# ---------------------------------------------------------------------------

class TestFocusModeEdgeCases:
    """Focused session vanishing must not strand the user."""

    def test_removing_focused_icon_auto_exits_focus( self, notifications_page_with_strip ):
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#deletefocus"

        _inject_cc_sender_card( page, sender_a )
        _click_strip_toggle( page )

        # Sanity check: focus is on.
        toggle = page.locator( "#cc-strip-toggle" )
        assert toggle.get_attribute( "data-focus-active" ) == "true"

        # Remove the strip icon directly (simulates deleteSenderConversation
        # path — the real handler also calls _removeStripIcon).
        page.evaluate(
            "( sid ) => window.notificationsUI._removeStripIcon( sid )",
            sender_a
        )
        page.wait_for_timeout( 50 )

        # Focus should have auto-exited.
        assert toggle.get_attribute( "data-focus-active" ) == "false"
